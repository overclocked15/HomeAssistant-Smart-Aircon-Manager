"""Regression tests for the v3.5.0 logic and maths review.

Each test reproduces a defect found in the review and fails on v3.4.0.
"""
from __future__ import annotations

import asyncio
import sys
import time
from pathlib import Path
from unittest.mock import patch

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))
sys.path.insert(0, str(Path(__file__).parent))

from test_v302_fixes import (  # noqa: E402
    FakeState,
    hvac_commands,
    make_cycle_optimizer,
    run_cycle,
)


def live_ac(opt, states):
    """Make the fake AC follow the mode commands it receives."""
    record = opt.hass.services.async_call

    async def device(domain, service, data, blocking=False):
        await record(domain, service, data, blocking)
        if service == "set_hvac_mode":
            states["climate.ac"].state = data["hvac_mode"]

    opt.hass.services.async_call = device


def drift(opt, states, start, step, cycles, rooms=("bed", "living")):
    """Run cycles 30 s apart while every room drifts by ``step`` per cycle.

    Returns [(temperature offset from start, AC mode)] at each mode change.
    """
    now = [time.time()]
    changes = []
    with patch("time.time", side_effect=lambda: now[0]):
        for i in range(cycles):
            now[0] += 30
            temp = round(start + step * i, 2)
            for room in rooms:
                states[f"sensor.{room}"].state = str(temp)
            run_cycle(opt)
            mode = states["climate.ac"].state
            if not changes or changes[-1][1] != mode:
                changes.append((round(temp - start, 2), mode))
    return changes


class TestAutoModeChangeover:
    """v3.4.0: a running AC kept its direction until the 2 C turn-off, so the
    house drifted 2 C past target before auto mode could change over."""

    def test_cooling_changes_over_to_heating_at_the_turn_on_threshold(self):
        opt, calls, states = make_cycle_optimizer(hvac_mode="auto", ac_state="cool")
        live_ac(opt, states)
        changes = drift(opt, states, 23.0, -0.02, 120)
        modes = [mode for _, mode in changes]
        assert modes[:3] == ["cool", "off", "heat"]
        off_at = changes[1][0]
        heat_at = changes[2][0]
        assert off_at == pytest.approx(-1.0, abs=0.03)
        assert heat_at > -1.5          # v3.4.0: -2.12

    def test_heating_changes_over_to_cooling_at_the_turn_on_threshold(self):
        opt, calls, states = make_cycle_optimizer(hvac_mode="auto", ac_state="heat")
        live_ac(opt, states)
        changes = drift(opt, states, 23.0, +0.02, 120)
        assert [mode for _, mode in changes][:3] == ["heat", "off", "cool"]
        assert changes[1][0] == pytest.approx(1.0, abs=0.03)

    def test_never_reverses_directly(self):
        opt, calls, states = make_cycle_optimizer(hvac_mode="auto", ac_state="cool")
        live_ac(opt, states)
        drift(opt, states, 23.0, -0.02, 120)
        commands = hvac_commands(calls)
        assert commands.index("off") < commands.index("heat")

    def test_one_hot_room_blocks_the_changeover(self):
        """A room still extreme on the running side keeps the run going, so a
        sunny room and a cold house can't bounce the AC between modes."""
        opt, calls, states = make_cycle_optimizer(
            hvac_mode="auto", ac_state="cool",
            rooms=(("Sun", 25.0, None), ("Bed", 20.0, None), ("Living", 20.0, None)),
        )
        run_cycle(opt)
        assert opt._auto_changeover is None
        assert hvac_commands(calls) == []

    def test_relaxation_never_triggers_a_changeover(self):
        """A relaxed (raised) cooling target must not read as heating demand."""
        from test_battery_mode import with_decision

        opt, calls, states = make_cycle_optimizer(
            hvac_mode="auto", ac_state="cool", rooms=(("Bed", 23.0, None), ("Living", 23.0, None)),
        )
        with_decision(opt, 3)
        live_ac(opt, states)
        for _ in range(3):
            run_cycle(opt)
            assert opt._auto_changeover is None
        assert "heat" not in hvac_commands(calls)

    def test_dry_counts_as_a_cooling_run(self):
        """Dry runs the compressor cooling: auto mode must not switch dry -> heat directly."""
        opt, calls, states = make_cycle_optimizer(hvac_mode="auto", ac_state="dry")
        assert opt._resolve_cycle_direction(
            {"Bed": {"current_temperature": 21.9, "target_temperature": 23.0},
             "Living": {"current_temperature": 21.9, "target_temperature": 23.0}},
            23.0, None, "dry",
        ) == "cool"
        assert opt._auto_changeover == "heat"

    def test_fixed_modes_never_change_over(self):
        opt, calls, states = make_cycle_optimizer(hvac_mode="cool", ac_state="cool")
        opt._resolve_cycle_direction(
            {"Bed": {"current_temperature": 20.0, "target_temperature": 23.0}}, 23.0, None, "cool",
        )
        assert opt._auto_changeover is None


class TestDryModeHysteresis:
    """v3.4.0 entered and left dry mode at the same 65%: humidity hovering
    there flipped dry/fan_only every few minutes, with an alert each time."""

    def test_dry_holds_until_humidity_is_back_to_target(self):
        from test_battery_mode import make_humid_optimizer

        opt, calls, states = make_humid_optimizer(rh=63, ac_state="dry")
        opt._dry_mode_active = True
        run_cycle(opt)
        assert hvac_commands(calls) == []          # v3.4.0: fan_only at 63%

    def test_fan_only_does_not_start_dry_inside_the_band(self):
        from test_battery_mode import make_humid_optimizer

        opt, calls, states = make_humid_optimizer(rh=63, ac_state="fan_only")
        run_cycle(opt)
        assert hvac_commands(calls) == []

    def test_dry_stops_at_the_target(self):
        from test_battery_mode import make_humid_optimizer

        opt, calls, states = make_humid_optimizer(rh=59.9, ac_state="dry")
        opt._dry_mode_active = True
        run_cycle(opt)
        assert hvac_commands(calls) == ["fan_only"]

    def test_exit_point_always_below_the_start(self):
        opt, _, _ = make_cycle_optimizer(
            enable_humidity_control=True, target_humidity=60, humidity_deadband=5,
            dry_mode_humidity_threshold=65,
        )
        assert opt._dry_mode_exit_humidity() == 60
        opt.dry_mode_humidity_threshold = 55    # threshold set below the target
        assert opt._dry_mode_exit_humidity() == 50

    def test_hovering_humidity_switches_rarely(self):
        opt, calls, states = make_cycle_optimizer(
            ac_state="fan_only", enable_humidity_control=True, notify_services=["notify.phone"],
        )
        for cfg in opt.room_configs:
            cfg["humidity_sensor"] = f"sensor.{cfg['room_name'].lower()}_h"
            states[cfg["humidity_sensor"]] = FakeState("64.5")
        live_ac(opt, states)
        rh = 64.5
        now = [time.time()]
        with patch("time.time", side_effect=lambda: now[0]):
            for _ in range(480):                    # 4 hours
                now[0] += 30
                rh += -0.1 if states["climate.ac"].state == "dry" else 0.1
                for cfg in opt.room_configs:
                    states[cfg["humidity_sensor"]].state = f"{rh:.1f}"
                run_cycle(opt)
        pushes = [c for c in calls if c[0] == "notify" and "AC Mode Changed" in c[2]["title"]]
        assert len(hvac_commands(calls)) <= 12      # v3.4.0: 48
        assert len(pushes) <= 8                     # v3.4.0: 48

    def test_mode_change_alerts_are_throttled(self):
        opt, calls, states = make_cycle_optimizer(notify_services=["notify.phone"])
        for mode in ("dry", "fan_only", "dry", "fan_only"):
            asyncio.run(opt._set_hvac_mode(mode, {"hvac_mode": "cool", "state": "cool"}))
        assert hvac_commands(calls) == ["dry", "fan_only", "dry", "fan_only"]
        assert len([c for c in calls if c[0] == "notify"]) == 2


def fan_rooms(*rooms):
    """room_states from (name, temperature, own target)."""
    return {name: {"current_temperature": t, "target_temperature": tt} for name, t, tt in rooms}


class TestMainFan:
    """v3.4.0 judged the main fan on raw temperatures against the global target
    (ignoring per-room targets) and had no hysteresis between levels."""

    def _fan_optimizer(self, **kw):
        opt, calls, states = make_cycle_optimizer(
            main_fan_entity="climate.ac",
            climate_attrs={"fan_modes": ["low", "medium", "high"], "fan_mode": "low"}, **kw,
        )
        return opt, calls, states

    def _decide(self, opt, states, rooms, target):
        opt._current_global_effective_target = target
        level = asyncio.run(opt._determine_and_set_main_fan_speed(fan_rooms(*rooms)))
        states["climate.ac"].attributes["fan_mode"] = level
        return level

    def test_room_held_warmer_on_purpose_is_not_unmet_demand(self):
        opt, calls, states = self._fan_optimizer(target=22.0)
        level = self._decide(opt, states, (("Bed", 22.0, 22.0), ("Living", 22.0, 22.0), ("Office", 25.0, 25.0)), 22.0)
        assert level == "low"                       # v3.4.0: high, with zero demand

    def test_room_below_its_warmer_override_does_not_count_as_spread(self):
        opt, calls, states = self._fan_optimizer(target=22.0)
        level = self._decide(opt, states, (("Bed", 22.0, 22.0), ("Living", 22.0, 22.0), ("Office", 22.0, 25.0)), 22.0)
        assert level == "low"

    def test_overcooled_room_does_not_ask_for_more_blower(self):
        opt, calls, states = self._fan_optimizer()
        level = self._decide(opt, states, (("Bed", 23.2, 23.0), ("Living", 21.2, 23.0)), 23.0)
        assert level == "low"                       # v3.4.0: medium (2 °C range)

    def test_heating_room_held_cooler_on_purpose(self):
        opt, calls, states = self._fan_optimizer(hvac_mode="heat", ac_state="heat", target=21.0)
        level = self._decide(opt, states, (("Bed", 21.0, 21.0), ("Living", 21.0, 21.0), ("Garage", 17.0, 17.0)), 21.0)
        assert level == "low"

    def test_no_flapping_on_a_threshold(self):
        opt, calls, states = self._fan_optimizer()
        for avg in (23.95, 24.05, 23.95, 24.05, 23.95):
            self._decide(opt, states, (("Bed", avg - 0.3, 23.0), ("Living", avg + 0.3, 23.0)), 23.0)
        sent = [c[2]["fan_mode"] for c in calls if c[1] == "set_fan_mode"]
        assert sent == []                           # v3.4.0: medium, low, medium, low

    def test_steps_up_and_down_past_the_margin(self):
        opt, calls, states = self._fan_optimizer()
        levels = [
            self._decide(opt, states, (("Bed", avg - 0.3, 23.0), ("Living", avg + 0.3, 23.0)), 23.0)
            for avg in (24.25, 23.85, 23.75)        # +1.25, +0.85, +0.75
        ]
        assert levels == ["medium", "medium", "low"]

    def test_decision_is_reported(self):
        opt, calls, states = self._fan_optimizer(rooms=(("Bed", 26.0, None), ("Living", 26.0, None)))
        result = run_cycle(opt)
        assert result["main_fan_decision"]["level"] == "high"
        assert result["main_fan_decision"]["demand"] == pytest.approx(3.0)

    def test_recommendation_reported_without_a_main_fan(self):
        opt, calls, states = make_cycle_optimizer(rooms=(("Bed", 24.5, None), ("Living", 24.5, None)))
        result = run_cycle(opt)
        assert result["main_fan_decision"]["level"] == "medium"


def house(temp, target=23.0, rooms=("Bed", "Living")):
    return {name: {"current_temperature": temp, "target_temperature": target} for name in rooms}


class TestSetpoint:
    """v3.4.0's setpoint could only push harder: once past the target it sat at
    the target, so a unit whose sensor reads warm overcooled the house by the
    full error. The adaptive setpoint shifted it by ±1 °C at every demand."""

    def _settle(self, opt, sensor_bias, target=23.0, step=0.5):
        """Where the rooms settle when the unit holds its own sensor at the setpoint."""
        opt._current_global_effective_target = target
        temp = target + 2.0
        for _ in range(400):
            setpoint = opt._fit_setpoint_to_entity(
                opt._calculate_ac_temperature(house(temp, target), target), {"target_temp_step": step}
            )
            temp += 0.2 * ((setpoint - sensor_bias) - temp)
        return temp - target

    def test_warm_reading_unit_no_longer_overcools_by_the_full_error(self):
        opt, _, _ = make_cycle_optimizer()
        assert self._settle(opt, sensor_bias=1.0) > -0.6   # v3.4.0: -1.00

    def test_accurate_sensor_settles_on_target(self):
        opt, _, _ = make_cycle_optimizer()
        assert self._settle(opt, sensor_bias=0.0) == pytest.approx(0.0, abs=0.05)

    def test_cooling_setpoint_backs_off_when_overcooled(self):
        opt, _, _ = make_cycle_optimizer()
        opt._current_global_effective_target = 23.0
        assert opt._calculate_ac_temperature(house(22.0), 23.0) == pytest.approx(25.0)   # capped back-off
        assert opt._calculate_ac_temperature(house(22.5), 23.0) == pytest.approx(24.0)

    def test_heating_setpoint_backs_off_when_overheated(self):
        opt, _, _ = make_cycle_optimizer(hvac_mode="heat", ac_state="heat", target=21.0)
        opt._current_global_effective_target = 21.0
        assert opt._calculate_ac_temperature(house(21.5, 21.0), 21.0) == pytest.approx(20.0)

    def test_overdrive_unchanged(self):
        opt, _, _ = make_cycle_optimizer()
        opt._current_global_effective_target = 23.0
        assert opt._calculate_ac_temperature(house(24.0), 23.0) == pytest.approx(21.0)
        assert opt._calculate_ac_temperature(house(27.0), 23.0) == pytest.approx(19.0)  # capped at 4

    def test_adaptive_setpoint_scales_the_gain_without_shifting_the_target(self):
        from unittest.mock import MagicMock
        from custom_components.smart_aircon_manager.learning import LearningProfile

        opt, _, _ = make_cycle_optimizer(enable_adaptive_ac_setpoint=True)
        profile = LearningProfile("Bed")
        profile.confidence = 0.9
        profile.cooling_efficiency = 0.8          # "high efficiency" house
        opt.learning_manager = MagicMock()
        opt.learning_manager.should_apply_learning.return_value = True
        opt.learning_manager.get_profile.return_value = profile
        opt._current_global_effective_target = 23.0
        assert opt._calculate_ac_temperature(house(23.0), 23.0) == pytest.approx(23.0)  # v3.4.0: 24.0
        assert opt._calculate_ac_temperature(house(24.0), 23.0) == pytest.approx(21.5)  # gain 2 x 0.75
        profile.cooling_efficiency = 0.3          # "low efficiency" house
        assert opt._calculate_ac_temperature(house(23.0), 23.0) == pytest.approx(23.0)  # v3.4.0: 22.0
        assert opt._calculate_ac_temperature(house(24.0), 23.0) == pytest.approx(20.5)  # gain 2 x 1.25

    def test_halves_round_up(self):
        from custom_components.smart_aircon_manager.optimizer import AirconOptimizer

        fit = AirconOptimizer._fit_setpoint_to_entity
        assert fit(22.5, {"target_temp_step": 1}) == 23    # v3.4.0: 22
        assert fit(23.5, {"target_temp_step": 1}) == 24
        assert fit(22.75, {"target_temp_step": 0.5}) == 23.0


def history_with_rate(opt, room, current, rate_per_min, points=10):
    """A 30-second history ending at ``current`` that rises at ``rate_per_min``."""
    now = time.time()
    opt._temp_history[room] = [
        (now - 30 * k, current - rate_per_min * 0.5 * k) for k in range(points - 1, -1, -1)
    ]


class TestPredictiveControl:
    """v3.4.0 added an amount proportional to the whole predicted error,
    switched on by the sign of the rate, so sensor noise flipped dampers."""

    def test_sensor_noise_does_not_switch_the_damper(self):
        opt, _, _ = make_cycle_optimizer(enable_predictive_control=True)
        base = opt._calculate_fan_speed(3.0, 3.0, "Bed")
        for rate in (0.004, -0.004, 0.004):
            history_with_rate(opt, "Bed", 26.0, rate)
            assert opt._apply_predictive_adjustment("Bed", base, 26.0, 23.0) == base  # v3.4.0: 100 / 89

    def test_room_closing_on_its_target_eases_off(self):
        opt, _, _ = make_cycle_optimizer(enable_predictive_control=True, predictive_boost_factor=1.0)
        base = opt._calculate_fan_speed(1.0, 1.0, "Bed")
        history_with_rate(opt, "Bed", 24.0, -0.15)
        assert opt._apply_predictive_adjustment("Bed", base, 24.0, 23.0) < base       # v3.4.0: unchanged

    def test_room_drifting_away_gets_more_air(self):
        opt, _, _ = make_cycle_optimizer(enable_predictive_control=True)
        base = opt._calculate_fan_speed(1.0, 1.0, "Bed")
        history_with_rate(opt, "Bed", 24.0, 0.1)
        assert opt._apply_predictive_adjustment("Bed", base, 24.0, 23.0) > base

    def test_heading_out_of_the_deadband_is_anticipated(self):
        opt, _, _ = make_cycle_optimizer(enable_predictive_control=True)
        history_with_rate(opt, "Bed", 23.4, 0.2)
        assert opt._apply_predictive_adjustment("Bed", 50, 23.4, 23.0) > 50

    def test_heating_mirror(self):
        opt, _, _ = make_cycle_optimizer(
            hvac_mode="heat", ac_state="heat", target=21.0,
            enable_predictive_control=True, predictive_boost_factor=1.0,
        )
        base = opt._calculate_fan_speed(-1.0, 1.0, "Bed")
        history_with_rate(opt, "Bed", 20.0, 0.15)   # warming toward its target
        assert opt._apply_predictive_adjustment("Bed", base, 20.0, 21.0) < base


def tracker_with(rooms, minutes=240, fan=50, target=23.0, mode="cool", quantum=0.1, noise=None):
    """PerformanceTracker fed 30-second points per room.

    rooms: {name: (start temperature, true rate °C/min)}; readings rounded to
    ``quantum`` (plus optional deterministic noise callable(i) in °C).
    """
    from unittest.mock import MagicMock
    from custom_components.smart_aircon_manager.learning import PerformanceTracker

    tracker = PerformanceTracker(MagicMock(), "t", Path("/tmp"))
    start = time.time() - minutes * 60
    for name, (temp0, rate) in rooms.items():
        last = None
        points = []
        for i in range(int(minutes * 2)):
            true = temp0 + rate * i * 0.5
            reading = round((true + (noise(i) if noise else 0.0)) / quantum) * quantum
            before = reading if last is None else last
            points.append({
                "timestamp": start + 30 * i, "temp_before": before, "temp_after": reading,
                "fan_speed": fan, "target_temp": target, "cycle_duration": 30.0,
                "temp_diff_from_target": before - target, "operating_mode": mode,
            })
            last = reading
        tracker._data_points[name] = points
    return tracker


class TestLearningEstimators:
    """v3.4.0's estimators saturated or measured sensor noise."""

    def test_thermal_mass_separates_fast_and_slow_rooms(self):
        tracker = tracker_with({"Slow": (27.0, -0.03), "Fast": (27.0, -0.12)}, minutes=30, fan=80)
        slow = tracker.estimate_thermal_mass("Slow")
        fast = tracker.estimate_thermal_mass("Fast")
        assert slow > 0.7                  # high mass
        assert fast < 0.7                  # v3.4.0: 0.88, "high mass" like every room
        assert slow > fast

    def test_room_sitting_at_target_is_not_read_as_high_mass(self):
        tracker = tracker_with({"Still": (23.2, 0.0)}, minutes=60)
        assert tracker.estimate_thermal_mass("Still") is None    # v3.4.0: 1.0

    def test_heat_gain_ratio_survives_quantized_sensors(self):
        tracker = tracker_with({"A": (23.0, 0.010), "B": (23.0, 0.040)}, minutes=240, fan=20)
        a = tracker.get_relative_drift_rate("A", "cool")
        b = tracker.get_relative_drift_rate("B", "cool")
        assert a < 1.0 < b                 # v3.4.0: 1.0 and 1.0
        assert b / a == pytest.approx(4.0, rel=0.2)

    def test_efficiency_ignores_noise(self):
        flicker = lambda i: 0.06 if i % 2 else -0.06      # noqa: E731 - no real cooling
        tracker = tracker_with({"Noisy": (25.0, 0.0)}, minutes=60, fan=60, noise=flicker)
        assert tracker.estimate_cooling_efficiency("Noisy") == pytest.approx(0.0, abs=0.05)

    def test_efficiency_measures_cooling_per_unit_of_airflow(self):
        tracker = tracker_with({"Room": (27.0, -0.05)}, minutes=30, fan=100)
        assert tracker.estimate_cooling_efficiency("Room") == pytest.approx(0.5, abs=0.1)

    def test_convergence_ignores_noise(self):
        flicker = lambda i: 0.06 if i % 2 else -0.06      # noqa: E731
        tracker = tracker_with({"Noisy": (24.5, 0.0)}, minutes=60, noise=flicker)
        assert not tracker.get_convergence_rate("Noisy")  # v3.4.0: a positive rate

    def test_damper_position_is_the_one_in_place_during_the_interval(self):
        tracker = tracker_with({"Room": (27.0, -0.05)}, minutes=30, fan=100)
        for p in tracker._data_points["Room"]:
            p["fan_speed"] = 100
        tracker._data_points["Room"][-1]["fan_speed"] = 20   # applied after the last change
        assert tracker.estimate_cooling_efficiency("Room") == pytest.approx(0.5, abs=0.1)


class TestLearningProfile:
    def _profile_after(self, tracker, room, **kw):
        from custom_components.smart_aircon_manager.learning import LearningProfile

        profile = LearningProfile(room)
        for key, value in kw.items():
            setattr(profile, key, value)
        profile.update_from_tracker(tracker)
        return profile

    def test_smoothing_damps_more_after_more_overshoots(self):
        from unittest.mock import MagicMock
        from custom_components.smart_aircon_manager.learning import LearningProfile, PerformanceTracker

        tracker = PerformanceTracker(MagicMock(), "t", Path("/tmp"))
        now = time.time()
        points = []
        for i in range(60):
            crossing = i >= 30 and i % 4 < 2          # overshoots only in the second half
            diff = (1.0 if i % 4 == 0 else -1.0) if crossing else 1.0
            points.append({
                "timestamp": now - (60 - i) * 30, "temp_before": 23 + diff, "temp_after": 23 + diff,
                "fan_speed": 50, "target_temp": 23.0, "cycle_duration": 30.0,
                "temp_diff_from_target": diff, "operating_mode": "cool",
            })
        tracker._data_points["Room"] = points
        profile = LearningProfile("Room")
        profile.update_from_tracker(tracker)
        assert profile.optimal_smoothing_factor < 0.7    # v3.4.0: 0.72 (less damping)
        assert profile.optimal_smoothing_threshold > 10

    def test_balancing_bias_follows_the_rooms_need(self):
        cold = self._profile_after(tracker_with({"Cold": (22.0, 0.0)}, minutes=30), "Cold")
        warm = self._profile_after(tracker_with({"Warm": (24.0, 0.0)}, minutes=30), "Warm")
        assert cold.balancing_bias < 0      # over-cooled: less air (v3.4.0: +0.05)
        assert warm.balancing_bias > 0      # short of target: more air
        heat = self._profile_after(tracker_with({"Cold": (22.0, 0.0)}, minutes=30, mode="heat"), "Cold")
        assert heat.balancing_bias > 0      # too cold while heating: more air

    def test_balancing_bias_decays_when_the_room_is_fine(self):
        fine = self._profile_after(tracker_with({"Fine": (23.1, 0.0)}, minutes=30), "Fine", balancing_bias=0.5)
        assert fine.balancing_bias == pytest.approx(0.45)

    def test_max_adjustment_limits_each_update(self):
        from custom_components.smart_aircon_manager.learning import LearningProfile

        tracker = tracker_with({"Fast": (27.0, -0.12)}, minutes=30, fan=80)
        profile = LearningProfile("Fast")
        profile.update_from_tracker(tracker, max_step=0.05)
        assert profile.thermal_mass == pytest.approx(0.45)   # 0.5 moved by at most 0.05

    def test_profiles_from_the_old_estimators_start_again(self):
        from custom_components.smart_aircon_manager.learning import LearningProfile

        old = {"room_name": "Bed", "thermal_mass": 0.97, "cooling_efficiency": 0.2,
               "optimal_smoothing_factor": 0.95, "optimal_smoothing_threshold": 20,
               "balancing_bias": 1.0, "relative_heat_gain_rate": 1.0, "confidence": 0.8,
               "coupling_factors": {"Living": 0.6}}
        profile = LearningProfile.from_dict(old)
        assert (profile.thermal_mass, profile.cooling_efficiency) == (0.5, 0.6)
        assert (profile.optimal_smoothing_factor, profile.optimal_smoothing_threshold) == (0.7, 10)
        assert profile.balancing_bias == 0.0
        assert profile.coupling_factors == {"Living": 0.6}
        assert LearningProfile.from_dict(profile.to_dict() | {"thermal_mass": 0.8}).thermal_mass == 0.8


def balancing_optimizer(**kw):
    kw.setdefault("enable_room_balancing", True)
    opt, _, _ = make_cycle_optimizer(**kw)
    return opt


class TestBalancing:
    """v3.4.0 triggered on a standard deviation (scales with room count), had
    no hysteresis, and its floor lifted deep-overshoot rooms."""

    def test_single_outlier_triggers_in_a_big_house(self):
        opt = balancing_optimizer()
        rooms = {f"R{i}": {"current_temperature": 23.0, "target_temperature": 23.0} for i in range(5)}
        rooms["Hot"] = {"current_temperature": 25.0, "target_temperature": 23.0}
        recs = {name: 50 for name in rooms}
        result = opt._apply_room_balancing(recs, rooms, 23.0)
        assert opt._balancing_active                   # v3.4.0: stdev 0.82 < 1.5, inactive
        assert result["Hot"] > 50

    def test_hysteresis(self):
        opt = balancing_optimizer()
        def spread(gap):
            rooms = {"A": {"current_temperature": 23.0 + gap / 2, "target_temperature": 23.0},
                     "B": {"current_temperature": 23.0 - gap / 2, "target_temperature": 23.0}}
            opt._apply_room_balancing({"A": 60, "B": 40}, rooms, 23.0)
            return opt._balancing_active
        assert [spread(g) for g in (1.6, 1.2, 1.4, 0.9, 1.2)] == [True, True, True, False, False]

    def test_floor_never_lifts_a_deep_overshoot_room(self):
        opt = balancing_optimizer(min_airflow_percent=15)
        rooms = {"Hot": {"current_temperature": 24.0, "target_temperature": 23.0},
                 "Cold": {"current_temperature": 20.0, "target_temperature": 23.0},
                 "Mid": {"current_temperature": 23.0, "target_temperature": 23.0}}
        result = opt._apply_room_balancing({"Hot": 66, "Cold": 5, "Mid": 50}, rooms, 23.0)
        assert result["Cold"] == 5                     # v3.4.0: lifted to 15

    def test_floor_still_stops_balancing_pushing_rooms_too_low(self):
        opt = balancing_optimizer(min_airflow_percent=20)
        rooms = {"Hot": {"current_temperature": 24.5, "target_temperature": 23.0},
                 "Cold": {"current_temperature": 22.0, "target_temperature": 23.0}}
        result = opt._apply_room_balancing({"Hot": 75, "Cold": 30}, rooms, 23.0)
        assert result["Cold"] == 20

    def test_learned_bias_keeps_its_meaning_when_heating(self):
        from unittest.mock import MagicMock
        from custom_components.smart_aircon_manager.learning import LearningProfile

        def bias_effect(mode, learned):
            opt = balancing_optimizer(hvac_mode=mode, ac_state=mode, enable_adaptive_balancing=True)
            profile = LearningProfile("A")
            profile.balancing_bias = learned
            opt.learning_manager = MagicMock()
            opt.learning_manager.should_apply_learning.side_effect = lambda room: room == "A"
            opt.learning_manager.get_profile.return_value = profile
            opt.enable_room_coupling_detection = False
            rooms = {"A": {"current_temperature": 23.0, "target_temperature": 23.0},
                     "B": {"current_temperature": 24.0, "target_temperature": 23.0},
                     "C": {"current_temperature": 22.0, "target_temperature": 23.0}}
            return opt._apply_room_balancing({"A": 50, "B": 50, "C": 50}, rooms, 23.0)["A"]

        assert bias_effect("heat", 1.0) - bias_effect("heat", 0.0) == 10   # v3.4.0: -10
        assert bias_effect("cool", 1.0) - bias_effect("cool", 0.0) == 10


class TestMinimumAirflow:
    def test_learning_does_not_lift_a_deep_overshoot_room(self):
        from unittest.mock import MagicMock
        from custom_components.smart_aircon_manager.learning import LearningProfile

        opt, _, _ = make_cycle_optimizer(min_airflow_percent=15)
        profile = LearningProfile("Bed")
        profile.cooling_efficiency = 0.55            # neutral: no adjustment
        opt.learning_manager = MagicMock()
        opt.learning_manager.should_apply_learning.return_value = True
        opt.learning_manager.get_profile.return_value = profile
        assert opt._apply_efficiency_adjustment(5, "Bed", 3.5) == 5       # v3.4.0: 15

    def test_vacation_keeps_the_floor_for_normal_rooms(self):
        opt, _, _ = make_cycle_optimizer(min_airflow_percent=20)
        opt._quick_action_mode = "vacation"
        assert opt._apply_quick_action_adjustments({"Bed": 5, "Living": 90}, {}) == {"Bed": 5, "Living": 27}


class TestQuickActions:
    """v3.4.0's boost multiplied every damper by 1.5 (flattening the split) and
    left the AC alone; sleep capped the dampers but not the blower."""

    def test_boost_keeps_the_airflow_split(self):
        opt, _, _ = make_cycle_optimizer()
        opt._quick_action_mode = "boost"
        adjusted = opt._apply_quick_action_adjustments({"Hot": 75, "Warm": 60, "Cold": 30}, {})
        assert adjusted == {"Hot": 100, "Warm": 80, "Cold": 30}   # v3.4.0: 100, 90, 45

    def test_boost_drives_the_setpoint_and_main_fan_while_rooms_need_it(self):
        opt, _, _ = make_cycle_optimizer()
        opt._quick_action_mode = "boost"
        opt._current_global_effective_target = 23.0
        assert opt._calculate_ac_temperature(house(23.3), 23.0) == pytest.approx(19.0)   # full overdrive
        assert opt._calculate_ac_temperature(house(22.5), 23.0) == pytest.approx(24.0)   # satisfied: normal
        opt._main_fan_metrics = {"worst_room_excess": 0.3}
        assert opt._cap_main_fan_speed("low") == "high"
        opt._main_fan_metrics = {"worst_room_excess": -0.2}
        assert opt._cap_main_fan_speed("low") == "low"

    def test_boost_suspends_efficient_operation(self):
        opt, _, _ = make_cycle_optimizer(enable_efficiency_mode=True)
        assert opt._efficiency_active()
        opt._quick_action_mode = "boost"
        assert not opt._efficiency_active()

    def test_sleep_quietens_the_blower_not_the_dampers(self):
        opt, _, _ = make_cycle_optimizer()
        opt._quick_action_mode = "sleep"
        assert opt._apply_quick_action_adjustments({"Bed": 90, "Living": 60}, {}) == {"Bed": 90, "Living": 60}
        assert opt._cap_main_fan_speed("high") == "low"                # v3.4.0: high

    def test_sleep_end_to_end(self):
        opt, calls, states = make_cycle_optimizer(
            rooms=(("Bed", 27.0, None), ("Living", 27.0, None)), main_fan_entity="climate.ac",
            climate_attrs={"fan_modes": ["low", "medium", "high"], "fan_mode": "high"},
        )
        opt._enter_quick_action_mode("sleep")
        run_cycle(opt)
        assert [c[2]["fan_mode"] for c in calls if c[1] == "set_fan_mode"] == ["low"]


class TestSmoothing:
    def test_settles_on_the_value_from_below(self):
        opt, _, _ = make_cycle_optimizer()
        opt._last_fan_speeds["Bed"] = 50
        seq = [opt._smooth_fan_speed("Bed", 60) for _ in range(5)]
        assert seq[-1] == 60                       # v3.4.0: stuck at 59
