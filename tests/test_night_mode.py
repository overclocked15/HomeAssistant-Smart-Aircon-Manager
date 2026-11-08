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
        assert result["room_states"]["Living"]["closed_off"] is True
        assert result["room_states"]["Bed"]["closed_off"] is False
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


class TestReviewFixes:
    """Regression tests for issues found in the v3.2.0 pre-release review."""

    def test_adaptive_deadband_ignores_closed_rooms(self):
        import time as _time
        opt, _, _ = night_optimizer(
            enable_adaptive_deadband=True, adaptive_deadband_max_scale=2.0,
            adaptive_deadband_rate_threshold=0.5,
        )
        now = _time.time()
        # Bedrooms steady, closed living room warming fast (damper shut)
        for room, rate in (("Bed", 0.0), ("Kids", 0.0), ("Living", 0.5)):
            opt._temp_history[room] = [(now - 600 + i * 60, 23.0 + rate * i) for i in range(11)]
        opt._night_mode_applied_closed = frozenset({"Living"})
        assert opt._get_adaptive_deadband() == opt.temperature_deadband
        # Without night mode the same drift widens it
        opt._night_mode_applied_closed = frozenset()
        assert opt._get_adaptive_deadband() > opt.temperature_deadband

    def test_moving_zone_closed_once_it_stops(self):
        opt, calls, states = night_optimizer()
        states["cover.living"].state = "closing"  # still moving from an earlier command
        run_cycle(opt)
        assert "cover.living" not in cover_positions(calls)
        assert opt._night_mode_unsettled == {"Living"}
        # Zone stops; the house is stable, so no full pass would run
        states["cover.living"].state = "open"
        calls.clear()
        run_cycle(opt)
        assert cover_positions(calls).get("cover.living") == 0
        assert opt._night_mode_unsettled == set()
        # Delivered once; not re-sent every cycle
        calls.clear()
        run_cycle(opt)
        assert "cover.living" not in cover_positions(calls)

    def test_unavailable_zone_retried_without_forcing_optimizations(self):
        opt, calls, states = night_optimizer()
        states["cover.living"].state = "unavailable"
        run_cycle(opt)
        assert opt._night_mode_pending is False
        last_opt = opt._last_optimization
        calls.clear()
        run_cycle(opt)  # still unavailable: nothing sent, no forced pass
        assert "cover.living" not in cover_positions(calls)
        assert opt._last_optimization == last_opt
        states["cover.living"].state = "open"
        calls.clear()
        run_cycle(opt)
        assert cover_positions(calls).get("cover.living") == 0

    def test_reopen_retried_with_computed_position(self):
        opt, calls, states = night_optimizer()
        run_cycle(opt)
        states["cover.living"].attributes["current_position"] = 0
        states["cover.living"].state = "unavailable"
        opt.enable_night_mode = False
        run_cycle(opt)
        assert opt._night_mode_unsettled == {"Living"}
        computed = opt._last_recommendations["Living"]
        assert computed > 0
        states["cover.living"].state = "open"
        calls.clear()
        run_cycle(opt)
        assert cover_positions(calls).get("cover.living") == computed

    def test_reopened_room_without_reading_is_not_left_shut(self):
        opt, calls, states = night_optimizer()
        run_cycle(opt)
        states["cover.living"].attributes["current_position"] = 0
        states["sensor.living"].state = "unavailable"
        calls.clear()
        opt.enable_night_mode = False
        result = run_cycle(opt)
        assert result["recommendations"]["Living"] == 50
        assert cover_positions(calls).get("cover.living") == 50

    def test_closed_room_open_window_pause_cleared(self):
        opt, _, _ = night_optimizer(enable_open_window_detection=True)
        opt._open_window_state["Living"] = {"detected_at": 0}
        result = run_cycle(opt)
        assert "Living" not in result["open_window_rooms"]

    def test_switch_entity_naming_and_live_attributes(self):
        from custom_components.smart_aircon_manager.switch import NightModeSwitch
        opt, _, _ = night_optimizer()
        entry = type("Entry", (), {"entry_id": "abc", "data": {}})()
        switch = NightModeSwitch(opt, entry)
        assert switch.has_entity_name is True
        assert switch.name == "Night Mode"
        assert switch.unique_id == "abc_enable_night_mode"
        assert switch.extra_state_attributes["closed_rooms"] == []
        run_cycle(opt)
        assert switch.extra_state_attributes["closed_rooms"] == ["Living"]
        opt.enable_night_mode = False
        assert switch.extra_state_attributes["closed_rooms"] == []


def fail_cover_calls(opt, calls, entity_id):
    """Make service calls for one cover raise (zone online but rejecting)."""
    original = opt.hass.services.async_call

    async def service_call(domain, service, data, blocking=False):
        if domain == "cover" and data.get("entity_id") == entity_id:
            calls.append(("failed", service, dict(data)))
            raise RuntimeError("zone controller error")
        return await original(domain, service, data, blocking)

    opt.hass.services.async_call = service_call
    return original


def failed_attempts(calls, entity_id):
    return sum(1 for c in calls if c[0] == "failed" and c[2]["entity_id"] == entity_id)


class TestDeliveryConfirmation:
    """A night-mode change only settles once its command actually went through."""

    def test_apply_reports_delivered_rooms(self):
        import asyncio
        opt, calls, states = night_optimizer()
        states["cover.bed"].attributes["current_position"] = 51   # within debounce of 50
        states["cover.kids"].state = "unavailable"
        opt.room_overrides["Living_enabled"] = False
        delivered = asyncio.run(opt._apply_recommendations({"Bed": 50, "Kids": 40, "Living": 0}))
        assert delivered == {"Bed", "Living"}
        opt.manual_override_enabled = True
        assert asyncio.run(opt._apply_recommendations({"Bed": 10})) == set()

    def test_failed_close_is_retried_with_backoff(self):
        opt, calls, states = night_optimizer()
        original = fail_cover_calls(opt, calls, "cover.living")
        with patch("asyncio.sleep", new=_no_sleep):
            run_cycle(opt)                      # full pass: command fails -> backoff
            assert opt._night_mode_unsettled == {"Living"}
            assert failed_attempts(calls, "cover.living") == 3   # existing per-call retries
            assert opt._night_mode_retry_backoff["Living"][1] == 60
            run_cycle(opt)                      # inside the backoff: no attempt
            assert failed_attempts(calls, "cover.living") == 3
            opt._night_mode_retry_backoff["Living"] = (0.0, 60.0)
            run_cycle(opt)                      # backoff elapsed: retried, fails again
            assert failed_attempts(calls, "cover.living") == 6
            assert opt._night_mode_retry_backoff["Living"][1] == 120
            # Zone recovers and the backoff elapses
            opt.hass.services.async_call = original
            opt._night_mode_retry_backoff["Living"] = (0.0, 60.0)
            calls.clear()
            run_cycle(opt)
        assert cover_positions(calls).get("cover.living") == 0
        assert opt._night_mode_unsettled == set()
        assert opt._night_mode_retry_backoff == {}

    def test_backoff_grows_and_is_capped(self):
        opt, calls, states = night_optimizer()
        fail_cover_calls(opt, calls, "cover.living")
        delays = []
        with patch("asyncio.sleep", new=_no_sleep):
            run_cycle(opt)
            for _ in range(8):
                if "Living" in opt._night_mode_retry_backoff:
                    # Let the backoff elapse, keep its delay
                    opt._night_mode_retry_backoff["Living"] = (0.0, opt._night_mode_retry_backoff["Living"][1])
                run_cycle(opt)
                delays.append(opt._night_mode_retry_backoff["Living"][1])
        assert delays[:3] == [120, 240, 480]   # 60 s was set by the full pass
        assert max(delays) == 1800

    def test_manual_override_mid_cycle_keeps_change_pending(self):
        opt, calls, states = night_optimizer()
        real_apply = opt._apply_recommendations

        async def override_switched_on(recommendations):
            opt.manual_override_enabled = True   # user hits Manual Override mid-cycle
            return await real_apply(recommendations)

        with patch.object(opt, "_apply_recommendations", side_effect=override_switched_on):
            run_cycle(opt)
        assert "cover.living" not in cover_positions(calls)
        assert "Living" in opt._night_mode_unsettled
        assert opt._night_mode_retry_backoff == {}   # not a zone failure
        run_cycle(opt)                            # override on: cycle skipped entirely
        assert "cover.living" not in cover_positions(calls)
        opt.manual_override_enabled = False
        run_cycle(opt)                            # override off: the close goes out
        assert cover_positions(calls).get("cover.living") == 0
        assert opt._night_mode_unsettled == set()

    def test_new_target_resets_backoff(self):
        opt, calls, states = night_optimizer()
        opt._night_mode_retry_backoff["Living"] = (10**12, 1800.0)
        opt._night_mode_unsettled.add("Living")
        opt.enable_night_mode = False             # Living now reopens: new target
        opt._night_mode_applied_closed = frozenset({"Living"})
        run_cycle(opt)
        assert "Living" not in opt._night_mode_retry_backoff


async def _no_sleep(*_args, **_kwargs):
    return None


class TestBackoffInFullPasses:
    """Full optimization passes honour the retry backoff (v3.2.2)."""

    @staticmethod
    def _full_pass(opt):
        # Optimization due on every cycle, as when rooms sit outside the deadband
        opt._last_optimization = None
        return run_cycle(opt)

    def test_full_pass_does_not_resend_during_backoff(self):
        rooms = (("Bed", 25.0, None), ("Kids", 24.5, None), ("Living", 27.0, None))
        opt, calls, states = night_optimizer(rooms=rooms)
        fail_cover_calls(opt, calls, "cover.living")
        with patch("asyncio.sleep", new=_no_sleep):
            result = self._full_pass(opt)       # rejected -> backoff 60 s
            assert failed_attempts(calls, "cover.living") == 3
            for _ in range(5):                  # five more full passes inside the backoff
                result = self._full_pass(opt)
            assert failed_attempts(calls, "cover.living") == 3
            assert opt._night_mode_retry_backoff["Living"][1] == 60   # no doubling without attempts
            # Intended position still reported
            assert result["recommendations"]["Living"] == 0
            # Deadline passes: the next full pass tries once and doubles once
            opt._night_mode_retry_backoff["Living"] = (0.0, 60.0)
            self._full_pass(opt)
            assert failed_attempts(calls, "cover.living") == 6
            assert opt._night_mode_retry_backoff["Living"][1] == 120

    def test_preposition_pass_honours_backoff(self):
        rooms = (("Bed", 23.0, None), ("Kids", 23.0, None), ("Living", 23.2, None))
        opt, calls, states = night_optimizer(rooms=rooms, ac_state="off")
        fail_cover_calls(opt, calls, "cover.living")
        with patch("asyncio.sleep", new=_no_sleep):
            run_cycle(opt)
            assert failed_attempts(calls, "cover.living") == 3
            opt._night_mode_pending = True      # e.g. a critical room flips: forced pass
            run_cycle(opt)
            assert failed_attempts(calls, "cover.living") == 3

    def test_healthy_rooms_still_applied_while_one_backs_off(self):
        rooms = (("Bed", 25.0, None), ("Kids", 24.5, None), ("Living", 27.0, None))
        opt, calls, states = night_optimizer(rooms=rooms)
        fail_cover_calls(opt, calls, "cover.living")
        with patch("asyncio.sleep", new=_no_sleep):
            self._full_pass(opt)
            states["cover.bed"].attributes["current_position"] = 10
            calls.clear()
            self._full_pass(opt)
        assert cover_positions(calls).get("cover.bed", 10) != 10
