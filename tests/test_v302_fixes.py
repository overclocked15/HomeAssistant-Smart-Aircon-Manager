"""Regression tests for the v3.0.2 fixes.

Most tests run full optimization cycles against mocked Home Assistant states
and record the service calls the optimizer makes, so they exercise the real
decision path (mode resolution -> on/off -> setpoint -> dampers).
"""
from __future__ import annotations

import asyncio
import datetime
import json
import sys
import tempfile
import time
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))


class FakeState:
    """Minimal stand-in for a Home Assistant State object."""

    def __init__(self, state, attributes=None):
        self.state = state
        self.attributes = attributes or {}
        self.entity_id = ""


def make_cycle_optimizer(
    hvac_mode="cool",
    rooms=(("Bed", 23.0, None), ("Living", 23.0, None)),
    ac_state="cool",
    target=23.0,
    climate_attrs=None,
    storage=None,
    **kwargs,
):
    """Optimizer wired to fake states; returns (optimizer, service_calls, states).

    rooms: (name, temperature or "unavailable", per-room target or None)
    """
    from custom_components.smart_aircon_manager.optimizer import AirconOptimizer

    calls = []

    async def service_call(domain, service, data, blocking=False):
        calls.append((domain, service, dict(data)))

    async def executor(func, *args):
        return func(*args)

    hass = MagicMock()
    hass.services.async_call = service_call
    hass.async_add_executor_job = executor
    hass.async_create_task = MagicMock(side_effect=lambda coro: coro.close())
    hass.config.path = MagicMock(return_value=storage or tempfile.mkdtemp())

    attrs = {
        "hvac_modes": ["off", "cool", "heat", "fan_only", "dry"],
        "temperature": target,
        "hvac_action": {"cool": "cooling", "heat": "heating"}.get(ac_state, "idle"),
        "min_temp": 16,
        "max_temp": 30,
        "target_temp_step": 0.5,
    }
    attrs.update(climate_attrs or {})
    states = {"climate.ac": FakeState(ac_state, attrs)}
    room_configs = []
    for name, temp, room_target in rooms:
        key = name.lower()
        states[f"sensor.{key}"] = FakeState(str(temp), {"unit_of_measurement": "°C"})
        states[f"cover.{key}"] = FakeState("open", {"current_position": 50})
        cfg = {"room_name": name, "temperature_sensor": f"sensor.{key}", "cover_entity": f"cover.{key}"}
        if room_target is not None:
            cfg["room_target_temperature"] = room_target
        room_configs.append(cfg)
    hass.states.get = lambda entity_id: states.get(entity_id)

    kwargs.setdefault("auto_control_main_ac", True)
    opt = AirconOptimizer(
        hass=hass,
        target_temperature=target,
        room_configs=room_configs,
        main_climate_entity="climate.ac",
        hvac_mode=hvac_mode,
        **kwargs,
    )
    opt._startup_time = time.time() - 1000
    opt._ac_last_turned_on = time.time() - 3600
    opt._ac_last_turned_off = time.time() - 3600
    if ac_state in ("cool", "heat"):
        opt._last_hvac_mode = ac_state
        opt._last_active_operating_mode = ac_state
    return opt, calls, states


def run_cycle(opt):
    return asyncio.run(opt.async_optimize())


def hvac_commands(calls):
    return [c[2]["hvac_mode"] for c in calls if c[1] == "set_hvac_mode"]


def set_room_temps(states, **temps):
    for name, temp in temps.items():
        states[f"sensor.{name.lower()}"].state = str(temp)


def set_ac_mode(states, mode):
    states["climate.ac"].state = mode
    states["climate.ac"].attributes["hvac_action"] = {"cool": "cooling", "heat": "heating"}.get(mode, "idle")


class TestAutoModeReversalGuard:
    """Auto mode used to reverse a cooling AC to HEAT whenever the house dipped
    just below target (zero-width rule), and could never turn off."""

    def test_cooling_ac_is_not_reversed_below_target(self):
        opt, calls, states = make_cycle_optimizer(hvac_mode="auto", rooms=(("Bed", 22.9, None), ("Living", 22.9, None)))
        run_cycle(opt)
        assert "heat" not in hvac_commands(calls)

    def test_no_reversals_as_house_crosses_target_repeatedly(self):
        opt, calls, states = make_cycle_optimizer(hvac_mode="auto")
        for temp in (23.3, 22.9, 23.1, 22.8, 23.2, 22.7):
            set_room_temps(states, Bed=temp, Living=temp)
            run_cycle(opt)
        assert "heat" not in hvac_commands(calls)

    def test_turns_off_when_overcooled_then_heats_only_from_off(self):
        opt, calls, states = make_cycle_optimizer(hvac_mode="auto")
        # 2.5 C below target with every room satisfied -> off (not heat)
        set_room_temps(states, Bed=20.5, Living=20.5)
        run_cycle(opt)
        assert hvac_commands(calls) == ["off"]
        # The next cycle observes our own turn-off; min off-time still holds
        calls.clear()
        set_ac_mode(states, "off")
        run_cycle(opt)
        assert hvac_commands(calls) == []
        # Once the min off-time has passed, a cold house may start heating
        opt._ac_last_turned_off = time.time() - 3600
        run_cycle(opt)
        assert hvac_commands(calls) == ["heat"]

    def test_humidity_branch_falls_back_to_fan_only_instead_of_heat(self):
        opt, calls, states = make_cycle_optimizer(
            hvac_mode="auto", rooms=(("Bed", 22.2, None), ("Living", 22.2, None)), enable_humidity_control=True
        )
        run_cycle(opt)
        assert "heat" not in hvac_commands(calls)

    def test_hold_never_keeps_opposite_mode(self):
        """Hysteresis must not hold 'heat' when the resolved direction is cool."""
        opt, calls, states = make_cycle_optimizer(
            hvac_mode="auto", ac_state="off", rooms=(("Bed", 24.6, None), ("Living", 24.6, None)),
            enable_humidity_control=True,
        )
        opt._last_hvac_mode = "heat"
        opt._last_active_operating_mode = "heat"
        opt._last_mode_change_time = time.time() - 10  # inside the hysteresis window
        run_cycle(opt)
        assert hvac_commands(calls) == ["cool"]


class TestSleepRelaxation:
    def test_sleep_in_auto_mode_does_not_heat(self):
        opt, calls, states = make_cycle_optimizer(hvac_mode="auto", rooms=(("Bed", 23.4, None), ("Living", 23.4, None)))
        opt._enter_quick_action_mode("sleep")
        result = run_cycle(opt)
        assert "heat" not in hvac_commands(calls)
        assert result["effective_target_temperature"] == pytest.approx(24.0)
        assert opt.target_temperature == 23.0

    def test_sleep_applies_on_top_of_a_schedule_and_never_leaks(self):
        import homeassistant.util.dt as dt_util

        if not hasattr(dt_util, "set_now"):
            pytest.skip("needs the offline HA stub's clock hook")
        opt, calls, states = make_cycle_optimizer(
            hvac_mode="cool", target=22.0, enable_scheduling=True,
            schedules=[{
                "schedule_name": "Night", "schedule_days": ["all"], "schedule_start_time": "21:00",
                "schedule_end_time": "07:00", "schedule_target_temp": 23, "schedule_enabled": True,
            }],
        )
        try:
            dt_util.set_now(datetime.datetime(2026, 1, 10, 22, 0))
            opt._enter_quick_action_mode("sleep", 60)
            result = run_cycle(opt)
            assert result["effective_target_temperature"] == pytest.approx(24.0)  # schedule 23 + sleep 1
            opt._quick_action_expiry = time.time() - 1  # sleep expires mid-schedule
            run_cycle(opt)
            assert opt._quick_action_mode is None
            dt_util.set_now(datetime.datetime(2026, 1, 11, 8, 0))  # schedule over
            result = run_cycle(opt)
            assert result["effective_target_temperature"] == pytest.approx(22.0)
            assert opt.target_temperature == 22.0
        finally:
            dt_util.set_now(None)

    def test_sleep_relaxes_rooms_with_own_targets(self):
        opt, calls, states = make_cycle_optimizer(hvac_mode="cool", rooms=(("Bed", 23.0, 21.0), ("Living", 23.0, None)))
        opt._enter_quick_action_mode("sleep")
        result = run_cycle(opt)
        assert result["room_states"]["Bed"]["target_temperature"] == pytest.approx(22.0)

    def test_boost_suspends_relaxation(self):
        opt, calls, states = make_cycle_optimizer(hvac_mode="cool")
        opt._quick_action_mode = "boost"
        relaxation = opt._compute_comfort_relaxation({"Bed": {}, "Living": {}})
        assert relaxation["global"] == 0.0


class TestPerRoomSatisfaction:
    """A room set warmer than the global target (cooling) used to keep the AC
    on forever and switch it on while sitting at its own target."""

    def test_cool_mode_turns_off_with_warm_override_room_at_its_target(self):
        opt, calls, states = make_cycle_optimizer(
            hvac_mode="cool", target=22.0,
            rooms=(("Bed", 17.5, None), ("Living", 17.5, None), ("Store", 24.8, 25.0)),
        )
        run_cycle(opt)
        assert hvac_commands(calls) == ["off"]

    def test_cool_mode_does_not_start_for_warm_room_below_its_target(self):
        opt, calls, states = make_cycle_optimizer(
            hvac_mode="cool", target=22.0, ac_state="off",
            rooms=(("Bed", 22.0, None), ("Living", 22.0, None), ("Store", 24.0, 25.0)),
        )
        run_cycle(opt)
        assert hvac_commands(calls) == []

    def test_heat_mode_mirror_cool_override_room(self):
        """Heating: a room set cooler than global must neither block turn-off
        nor drag the house average down (which kept heating every other room:
        the raw average here is only +0.5 C over target)."""
        opt, calls, states = make_cycle_optimizer(hvac_mode="heat", ac_state="heat", target=21.0)
        opt._current_global_effective_target = 21.0
        assert asyncio.run(opt._check_if_ac_needed(
            {
                "Bed": {"current_temperature": 24.2, "target_temperature": 21.0},
                "Living": {"current_temperature": 24.2, "target_temperature": 21.0},
                "Garage": {"current_temperature": 16.2, "target_temperature": 16.0},
            },
            ac_currently_on=True,
        )) is False

    def test_room_wanting_more_conditioning_stays_best_effort(self):
        """v2.16.2 intent kept: a room set colder than global while cooling
        is judged against the global target (it never keeps the AC on alone)."""
        opt, calls, states = make_cycle_optimizer(hvac_mode="cool", target=23.0)
        opt._current_global_effective_target = 23.0
        assert asyncio.run(opt._check_if_ac_needed(
            {
                "Bed": {"current_temperature": 20.9, "target_temperature": 20.0},
                "Living": {"current_temperature": 20.5, "target_temperature": 23.0},
            },
            ac_currently_on=True,
        )) is False

    def test_auto_winter_warm_room_does_not_select_cool(self):
        opt, calls, states = make_cycle_optimizer(
            hvac_mode="auto", ac_state="heat", target=21.0,
            rooms=(("Bed", 20.6, None), ("Living", 20.6, None), ("Medical", 24.0, 25.0)),
        )
        run_cycle(opt)
        assert "cool" not in hvac_commands(calls)


class TestRestartAndCrashFixes:
    def test_enhanced_protection_releases_after_restart(self):
        opt, calls, states = make_cycle_optimizer(
            hvac_mode="cool", enable_humidity_control=True, enable_enhanced_compressor_protection=True,
        )
        opt._mode_start_time = None  # what a restart used to leave behind
        opt._current_hvac_mode = None
        rs = {"Bed": {"current_temperature": 21.5, "current_humidity": 50, "target_temperature": 23.0},
              "Living": {"current_temperature": 21.5, "current_humidity": 50, "target_temperature": 23.0}}
        now = [time.time()]
        with patch("time.time", side_effect=lambda: now[0]):
            modes = []
            for _ in range(40):  # 20 minutes, min_mode_duration is 10
                modes.append(opt._determine_optimal_hvac_mode(rs, 23.0))
                now[0] += 30
        assert "fan_only" in modes

    def test_vacation_survives_restart(self):
        storage = tempfile.mkdtemp()
        opt, _, _ = make_cycle_optimizer(storage=storage)
        opt._enter_quick_action_mode("vacation")
        asyncio.run(opt._save_compressor_state())
        restarted, _, _ = make_cycle_optimizer(storage=storage)
        asyncio.run(restarted._load_compressor_state())
        assert restarted._quick_action_mode == "vacation"
        assert restarted.temperature_deadband == 2.0

    def test_no_crash_when_ac_started_externally_with_rooms_at_target(self):
        opt, calls, states = make_cycle_optimizer(
            hvac_mode="cool", ac_state="off", rooms=(("Bed", 23.2, None), ("Living", 23.1, None)),
        )
        run_cycle(opt)  # AC off: pre-positions dampers
        set_ac_mode(states, "cool")
        result = run_cycle(opt)
        assert "last_error" not in result or not result["last_error"]
        assert result["room_states"]

    def test_all_sensors_unavailable_leaves_ac_alone(self):
        opt, calls, states = make_cycle_optimizer(
            rooms=(("Bed", "unavailable", None), ("Living", "unavailable", None)),
        )
        run_cycle(opt)
        assert hvac_commands(calls) == []


class TestSetpointHandling:
    def test_setpoint_relaxes_while_rooms_sit_in_deadband(self):
        opt, calls, states = make_cycle_optimizer(
            rooms=(("Bed", 24.5, None), ("Living", 24.5, None)), auto_control_ac_temperature=True,
        )
        run_cycle(opt)
        first = [c[2]["temperature"] for c in calls if c[1] == "set_temperature"]
        assert first == [20.0]
        states["climate.ac"].attributes["temperature"] = 20.0
        calls.clear()
        set_room_temps(states, Bed=23.0, Living=23.0)
        opt._last_optimization -= 100
        run_cycle(opt)
        assert [c[2]["temperature"] for c in calls if c[1] == "set_temperature"] == [23.0]

    def test_setpoint_fitted_to_unit_range_and_step(self):
        from custom_components.smart_aircon_manager.optimizer import AirconOptimizer

        fit = AirconOptimizer._fit_setpoint_to_entity
        attrs = {"min_temp": 16, "max_temp": 30, "target_temp_step": 1}
        assert fit(32.0, attrs) == 30
        assert fit(14.0, attrs) == 16
        assert fit(23.200000000000003, attrs) == 23
        assert fit(23.3, {}) == 23.5  # default 0.5 step

    def test_setpoint_sent_in_the_cycle_the_ac_turns_on(self):
        opt, calls, states = make_cycle_optimizer(
            ac_state="off", rooms=(("Bed", 25.0, None), ("Living", 25.0, None)), auto_control_ac_temperature=True,
        )
        run_cycle(opt)
        assert hvac_commands(calls) == ["cool"]
        assert any(c[1] == "set_temperature" for c in calls)


class TestMainFan:
    def test_fan_mode_mapping(self):
        from custom_components.smart_aircon_manager.optimizer import AirconOptimizer

        match = AirconOptimizer._match_fan_mode
        assert match("medium", ["auto", "low", "mid", "high"]) == "mid"
        assert match("medium", ["Low", "Med", "High"]) == "Med"
        assert match("medium", ["Auto", "Silence", "1", "2", "3", "4", "5"]) == "3"
        assert match("high", ["Auto", "1", "2", "3", "4", "5"]) == "5"
        assert match("low", ["auto", "quiet", "powerful"]) == "quiet"
        assert match("medium", ["auto", "turbo"]) is None
        assert match("medium", None) == "medium"

    def test_unchanged_fan_mode_not_resent(self):
        opt, calls, states = make_cycle_optimizer(
            rooms=(("Bed", 25.0, None), ("Living", 23.5, None)),
            climate_attrs={"fan_mode": "mid", "fan_modes": ["low", "mid", "high"]},
        )
        opt.main_fan_entity = "climate.ac"
        for _ in range(3):
            opt._last_optimization = None
            run_cycle(opt)
        assert [c for c in calls if c[1] == "set_fan_mode"] == []

    def test_manual_fan_mode_is_respected(self):
        opt, calls, states = make_cycle_optimizer(
            rooms=(("Bed", 26.0, None), ("Living", 26.0, None)),
            climate_attrs={"fan_mode": "low", "fan_modes": ["low", "medium", "high"]},
        )
        opt.main_fan_entity = "climate.ac"
        opt.manual_main_fan_mode = "low"
        run_cycle(opt)
        assert [c for c in calls if c[1] == "set_fan_mode"] == []


class TestCriticalEmergencyInteplay:
    def _with_emergency(self, opt, direction, room="Bed"):
        monitor = MagicMock()
        monitor.get_all_statuses.return_value = {room: {"status": "critical", "direction": direction}}
        opt._get_critical_monitor = lambda: monitor

    def test_operating_mode_follows_emergency(self):
        opt, calls, states = make_cycle_optimizer(hvac_mode="cool")
        self._with_emergency(opt, "cold")
        assert opt._get_effective_operating_mode() == "heat"

    def test_manager_off_does_not_cut_rescue(self):
        opt, calls, states = make_cycle_optimizer(hvac_mode="cool")
        self._with_emergency(opt, "hot")
        asyncio.run(opt.async_turn_off_main_ac())
        assert hvac_commands(calls) == []

    def test_no_demand_during_emergency_switches_to_serving_mode(self):
        opt, calls, states = make_cycle_optimizer(hvac_mode="cool", ac_state="fan_only")
        self._with_emergency(opt, "hot")
        climate = {"hvac_mode": "fan_only", "state": "fan_only"}
        asyncio.run(opt._control_main_ac(False, climate, "fan_only"))
        assert hvac_commands(calls) == ["cool"]

    def test_quick_action_caps_skip_emergency_rooms(self):
        opt, calls, states = make_cycle_optimizer()
        self._with_emergency(opt, "hot", room="Bed")
        opt._quick_action_mode = "sleep"
        adjusted = opt._apply_quick_action_adjustments({"Bed": 90, "Living": 90}, {})
        assert adjusted == {"Bed": 90, "Living": 40}

    def test_relaxation_suspended_during_emergency(self):
        opt, calls, states = make_cycle_optimizer()
        self._with_emergency(opt, "hot")
        opt._quick_action_mode = "sleep"
        assert opt._compute_comfort_relaxation({"Bed": {}, "Living": {}})["global"] == 0.0


class TestQuickActionSafety:
    def test_party_does_not_override_open_window_pause(self):
        opt, calls, states = make_cycle_optimizer()
        opt._open_window_state = {"Bed": {"detected_at": time.time()}}
        opt._quick_action_mode = "party"
        adjusted = opt._apply_quick_action_adjustments({"Bed": 15, "Living": 80}, {})
        assert adjusted["Bed"] == 15

    def test_vacation_respects_min_airflow(self):
        opt, calls, states = make_cycle_optimizer(min_airflow_percent=20)
        opt._quick_action_mode = "vacation"
        adjusted = opt._apply_quick_action_adjustments({"Bed": 30, "Living": 90}, {})
        assert adjusted["Bed"] == 20


class TestExternalTransitions:
    def test_external_turn_on_arms_min_on_timer(self):
        opt, calls, states = make_cycle_optimizer(ac_state="off", rooms=(("Bed", 23.0, None), ("Living", 23.0, None)))
        run_cycle(opt)
        set_ac_mode(states, "cool")  # e.g. the critical monitor started it
        run_cycle(opt)
        assert time.time() - opt._ac_last_turned_on < 5


class TestLearningTargetChanges:
    def test_target_step_is_not_an_overshoot(self):
        from custom_components.smart_aircon_manager.learning import PerformanceTracker

        tracker = PerformanceTracker(MagicMock(), "t", Path(tempfile.mkdtemp()))
        now = time.time()
        points = []
        for i in range(20):
            target = 23.0 if i < 10 else 25.0  # comfort relaxation steps the target up
            temp = 23.2
            points.append({
                "timestamp": now - (20 - i) * 30, "temp_before": temp, "temp_after": temp,
                "fan_speed": 50, "target_temp": target, "cycle_duration": 30,
                "temp_diff_from_target": temp - target, "operating_mode": "cool",
            })
        tracker._data_points["Bed"] = points
        assert tracker.get_overshoot_frequency("Bed") == 0.0
