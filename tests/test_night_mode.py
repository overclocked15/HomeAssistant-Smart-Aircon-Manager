"""Tests for night mode (condition only the selected rooms, close off the rest).

Full optimization cycles against simulated Home Assistant states, recording
the service calls the optimizer makes.
"""
from __future__ import annotations

import sys
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).parent.parent))
sys.path.insert(0, str(Path(__file__).parent))

from test_v302_fixes import (  # noqa: E402
    hvac_commands,
    make_cycle_optimizer,
    run_cycle,
    set_room_temps,
)

ROOMS = (("Bed", 23.0, None), ("Kids", 23.0, None), ("Living", 27.0, None))


def cover_positions(calls):
    """Last position commanded per cover entity."""
    positions = {}
    for domain, service, data in calls:
        if domain == "cover" and service == "set_cover_position":
            positions[data["entity_id"]] = data["position"]
    return positions


def night_optimizer(**kwargs):
    kwargs.setdefault("rooms", ROOMS)
    kwargs.setdefault("enable_night_mode", True)
    kwargs.setdefault("night_mode_rooms", ["Bed", "Kids"])
    return make_cycle_optimizer(**kwargs)


class TestConfiguration:
    def test_unknown_rooms_dropped_and_no_rooms_means_inactive(self):
        opt, _, _ = night_optimizer(night_mode_rooms=["Ghost"])
        assert opt.night_mode_rooms == []
        assert not opt.night_mode_active

    def test_closed_position_clamped(self):
        opt, _, _ = night_optimizer(night_mode_closed_position=150)
        assert opt.night_mode_closed_position == 100
        opt, _, _ = night_optimizer(night_mode_closed_position="bad")
        assert opt.night_mode_closed_position == 0

    def test_off_by_default(self):
        opt, _, _ = make_cycle_optimizer(rooms=ROOMS)
        assert not opt.night_mode_active


class TestDampers:
    def test_closed_rooms_parked_and_night_rooms_controlled(self):
        opt, calls, _ = night_optimizer()
        result = run_cycle(opt)
        positions = cover_positions(calls)
        assert positions["cover.living"] == 0
        assert result["recommendations"]["Living"] == 0
        assert result["night_mode_closed_rooms"] == ["Living"]
        assert result["room_states"]["Living"]["night_mode_closed"] is True
        assert result["room_states"]["Bed"]["night_mode_closed"] is False
        # Night rooms still get a computed position
        assert result["recommendations"]["Bed"] > 0

    def test_custom_closed_position(self):
        opt, calls, _ = night_optimizer(night_mode_closed_position=10)
        run_cycle(opt)
        assert cover_positions(calls)["cover.living"] == 10

    def test_quick_action_cannot_reopen_closed_room(self):
        opt, calls, _ = night_optimizer()
        opt._enter_quick_action_mode("party", 60)
        result = run_cycle(opt)
        assert result["recommendations"]["Living"] == 0
        opt2, _, _ = night_optimizer()
        opt2._enter_quick_action_mode("vacation", 60)
        assert run_cycle(opt2)["recommendations"]["Living"] == 0

    def test_closed_rooms_parked_while_ac_off(self):
        # AC off: the pre-positioning branch must close rooms too
        opt, calls, _ = night_optimizer(
            ac_state="off", rooms=(("Bed", 23.0, None), ("Kids", 23.0, None), ("Living", 23.2, None))
        )
        result = run_cycle(opt)
        assert hvac_commands(calls) == []
        assert cover_positions(calls)["cover.living"] == 0
        assert result["recommendations"]["Living"] == 0


class TestACDecisions:
    def test_hot_closed_room_does_not_turn_ac_on(self):
        rooms = (("Bed", 23.0, None), ("Kids", 23.0, None), ("Living", 27.0, None))
        # Without night mode the hot living room starts the AC
        opt, calls, _ = make_cycle_optimizer(rooms=rooms, ac_state="off")
        run_cycle(opt)
        assert "cool" in hvac_commands(calls)
        # With night mode only the bedrooms count, and they're at target
        opt, calls, _ = night_optimizer(rooms=rooms, ac_state="off")
        result = run_cycle(opt)
        assert hvac_commands(calls) == []
        assert result["needs_ac"] is False

    def test_hot_closed_room_does_not_keep_ac_running(self):
        rooms = (("Bed", 20.5, None), ("Kids", 20.5, None), ("Living", 27.0, None))
        opt, calls, _ = make_cycle_optimizer(rooms=rooms)
        run_cycle(opt)
        assert "off" not in hvac_commands(calls)
        opt, calls, _ = night_optimizer(rooms=rooms)
        run_cycle(opt)
        assert hvac_commands(calls) == ["off"]

    def test_hot_night_room_turns_ac_on(self):
        rooms = (("Bed", 25.0, None), ("Kids", 23.0, None), ("Living", 21.0, None))
        opt, calls, _ = night_optimizer(rooms=rooms, ac_state="off")
        run_cycle(opt)
        assert "cool" in hvac_commands(calls)

    def test_setpoint_ignores_closed_rooms(self):
        rooms = (("Bed", 23.0, None), ("Kids", 23.0, None), ("Living", 30.0, None))
        kwargs = dict(rooms=rooms, auto_control_ac_temperature=True)
        opt, _, _ = make_cycle_optimizer(**kwargs)
        whole_house = run_cycle(opt)["recommendations"].get("ac_temperature")
        opt, _, _ = night_optimizer(**kwargs)
        night = run_cycle(opt)["recommendations"].get("ac_temperature")
        assert whole_house is not None and night is not None
        # A 30 °C living room drags the whole-house setpoint down; at night
        # the bedrooms at target don't
        assert night > whole_house


class TestToggle:
    def test_turning_on_moves_dampers_immediately_even_when_stable(self):
        rooms = (("Bed", 23.0, None), ("Kids", 23.0, None), ("Living", 23.1, None))
        opt, calls, _ = make_cycle_optimizer(rooms=rooms, night_mode_rooms=["Bed", "Kids"])
        run_cycle(opt)
        # Every room inside the deadband: the next cycle would normally skip
        calls.clear()
        opt.enable_night_mode = True
        result = run_cycle(opt)
        assert cover_positions(calls).get("cover.living") == 0
        assert result["recommendations"]["Living"] == 0

    def test_turning_off_reopens_rooms(self):
        opt, calls, states = night_optimizer()
        run_cycle(opt)
        states["cover.living"].attributes["current_position"] = 0
        calls.clear()
        opt.enable_night_mode = False
        result = run_cycle(opt)
        assert result["night_mode_closed_rooms"] == []
        assert result["recommendations"]["Living"] > 0
        assert cover_positions(calls).get("cover.living", 0) > 0

    def test_reopened_room_drops_stale_memory(self):
        opt, _, _ = night_optimizer()
        opt._last_fan_speeds["Living"] = 5
        opt._last_room_temps["Living"] = 18.0
        run_cycle(opt)  # Living closed
        assert "Living" not in opt._last_room_temps
        opt._last_fan_speeds["Living"] = 5
        opt.enable_night_mode = False
        run_cycle(opt)  # Living reopened: smoothing starts fresh
        assert opt._last_fan_speeds.get("Living") != 5


class TestSafety:
    def test_critical_emergency_room_stays_open(self):
        opt, calls, _ = night_optimizer()
        with patch.object(type(opt), "_critical_emergency_rooms", return_value={"Living"}):
            result = run_cycle(opt)
        assert result["night_mode_closed_rooms"] == []
        assert result["recommendations"]["Living"] > 0

    def test_night_room_sensors_down_leaves_ac_and_still_closes_rooms(self):
        rooms = (("Bed", "unavailable", None), ("Kids", "unavailable", None), ("Living", 27.0, None))
        opt, calls, _ = night_optimizer(rooms=rooms)
        result = run_cycle(opt)
        assert hvac_commands(calls) == []
        assert cover_positions(calls)["cover.living"] == 0
        assert result["needs_ac"] is False
        # Readings return: the pending change still gets a full pass
        assert opt._night_mode_pending is True

    def test_closed_room_sensor_outage_is_ignored(self):
        rooms = (("Bed", 25.0, None), ("Kids", 23.0, None), ("Living", "unavailable", None))
        opt, calls, _ = night_optimizer(rooms=rooms, ac_state="off")
        run_cycle(opt)
        assert "cool" in hvac_commands(calls)


class TestSurfaces:
    def test_climate_current_temperature_ignores_closed_rooms(self):
        from custom_components.smart_aircon_manager.climate import AirconAIClimate
        opt, _, _ = night_optimizer()
        data = run_cycle(opt)

        class Coordinator:
            pass

        coordinator = Coordinator()
        coordinator.data = data
        entity = object.__new__(AirconAIClimate)
        entity.coordinator = coordinator
        assert entity.current_temperature == 23.0

    def test_temperatures_keep_updating_for_closed_rooms(self):
        opt, _, states = night_optimizer()
        run_cycle(opt)
        set_room_temps(states, Living=28.5)
        result = run_cycle(opt)
        assert result["room_states"]["Living"]["current_temperature"] == 28.5
