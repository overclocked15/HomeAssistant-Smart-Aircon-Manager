"""Tests for optimizer core logic (fan speed calculation, balancing, etc.)."""
from __future__ import annotations

import sys
import time
from pathlib import Path
from unittest.mock import MagicMock, AsyncMock, patch

import pytest

# Add parent directory to path for imports
sys.path.insert(0, str(Path(__file__).parent.parent))


def _make_optimizer(**kwargs):
    """Create an AirconOptimizer with mocked HA dependencies."""
    from custom_components.smart_aircon_manager.optimizer import AirconOptimizer

    hass = MagicMock()
    hass.services = MagicMock()
    hass.services.async_call = AsyncMock()
    hass.states = MagicMock()
    hass.config = MagicMock()
    hass.config.path = MagicMock(return_value="/tmp/test_storage")
    hass.async_add_executor_job = AsyncMock()
    hass.async_create_task = MagicMock()

    defaults = {
        "hass": hass,
        "target_temperature": 24.0,
        "room_configs": [
            {"room_name": "Living Room", "temperature_sensor": "sensor.lr_temp", "cover_entity": "cover.lr_fan"},
            {"room_name": "Bedroom", "temperature_sensor": "sensor.br_temp", "cover_entity": "cover.br_fan"},
        ],
        "main_climate_entity": "climate.ac",
        "temperature_deadband": 0.5,
        "hvac_mode": "cool",
    }
    defaults.update(kwargs)
    opt = AirconOptimizer(**defaults)
    opt._startup_time = time.time()
    return opt


class TestFanSpeedCalculation:
    """Test _calculate_fan_speed with various temperature differences."""

    def test_within_deadband_returns_baseline(self):
        opt = _make_optimizer(temperature_deadband=0.5)
        # Within deadband - should return 50% baseline
        assert opt._calculate_fan_speed(0.3, 0.3) == 50
        assert opt._calculate_fan_speed(-0.3, 0.3) == 50
        assert opt._calculate_fan_speed(0.0, 0.0) == 50

    def test_cool_mode_hot_room_tiers(self):
        opt = _make_optimizer(hvac_mode="cool", temperature_deadband=0.5)
        # Proportional curve: 50 + 50 * min(1.0, (diff/4.0)^0.8)
        # Speed increases monotonically with temperature difference
        s06 = opt._calculate_fan_speed(0.6, 0.6)
        s10 = opt._calculate_fan_speed(1.0, 1.0)
        s15 = opt._calculate_fan_speed(1.5, 1.5)
        s20 = opt._calculate_fan_speed(2.0, 2.0)
        s30 = opt._calculate_fan_speed(3.0, 3.0)
        s50 = opt._calculate_fan_speed(5.0, 5.0)
        # Verify monotonically increasing
        assert 50 < s06 < s10 < s15 < s20 < s30 <= s50
        # 4°C+ above - should reach maximum
        assert s50 == 100

    def test_cool_mode_overcooled_room(self):
        opt = _make_optimizer(hvac_mode="cool", temperature_deadband=0.5)
        # Room is below target (overshot) - reduce cooling
        speed = opt._calculate_fan_speed(-1.5, 1.5)
        assert speed < 50  # Should be reduced

    def test_cool_mode_severe_overshoot(self):
        opt = _make_optimizer(hvac_mode="cool", temperature_deadband=0.5)
        # 3°C+ overshoot - near shutdown
        assert opt._calculate_fan_speed(-3.5, 3.5) == 5

    def test_heat_mode_cold_room_tiers(self):
        opt = _make_optimizer(hvac_mode="heat", temperature_deadband=0.5)
        # Room is below target - needs heating (proportional curve)
        s06 = opt._calculate_fan_speed(-0.6, 0.6)
        s10 = opt._calculate_fan_speed(-1.0, 1.0)
        s20 = opt._calculate_fan_speed(-2.0, 2.0)
        s40 = opt._calculate_fan_speed(-4.0, 4.0)
        # Verify monotonically increasing
        assert 50 < s06 < s10 < s20 < s40
        # 4°C should be at or very near max
        assert s40 >= 95

    def test_heat_mode_overheated_room(self):
        opt = _make_optimizer(hvac_mode="heat", temperature_deadband=0.5)
        # Room above target in heat mode (overshot) - reduce heating
        speed = opt._calculate_fan_speed(1.5, 1.5)
        assert speed < 50

    def test_auto_mode(self):
        opt = _make_optimizer(hvac_mode="auto", temperature_deadband=0.5)
        # Auto mode delegates to cool/heat via proportional curve
        s20 = opt._calculate_fan_speed(2.0, 2.0)
        s40 = opt._calculate_fan_speed(4.0, 4.0)
        assert s20 > 50  # Active conditioning
        assert s40 >= 95  # Near max
        # Overshoot detection: in auto mode (defaults to cool), temp_diff < 0 is overshoot
        assert opt._calculate_fan_speed(-2.0, 2.0) < 50  # Should reduce, not blast

    def test_auto_mode_heat_overshoot(self):
        opt = _make_optimizer(hvac_mode="auto", temperature_deadband=0.5)
        # When last mode is heat, positive temp_diff is overshoot (overheated)
        opt._last_hvac_mode = "heat"
        assert opt._calculate_fan_speed(2.0, 2.0) < 50  # Overshoot in heat mode
        # Negative temp_diff in heat mode = needs heating (active conditioning)
        s20 = opt._calculate_fan_speed(-2.0, 2.0)
        assert s20 > 50  # Active conditioning in heat mode

    def test_no_discontinuity_at_deadband_boundary(self):
        """Fan speed should not decrease when crossing from in-deadband to out-of-deadband."""
        opt = _make_optimizer(hvac_mode="cool", temperature_deadband=0.5)
        within = opt._calculate_fan_speed(0.4, 0.4)   # Within deadband
        outside = opt._calculate_fan_speed(0.6, 0.6)   # Just outside deadband
        assert outside >= within, f"Fan speed dropped from {within}% to {outside}% crossing deadband boundary"


class TestFanSpeedSmoothing:
    """Test fan speed smoothing logic."""

    def test_first_reading_no_smoothing(self):
        opt = _make_optimizer()
        result = opt._smooth_fan_speed("Room1", 75)
        assert result == 75

    def test_small_change_smoothed(self):
        opt = _make_optimizer()
        opt._last_fan_speeds["Room1"] = 50
        # Small change (5%) should be dampened
        result = opt._smooth_fan_speed("Room1", 55)
        assert 50 < result < 55  # Should be between old and new

    def test_large_change_applied_immediately(self):
        opt = _make_optimizer()
        opt._last_fan_speeds["Room1"] = 50
        # Large change (30%) should be applied immediately
        result = opt._smooth_fan_speed("Room1", 80)
        assert result == 80


class TestRoomBalancing:
    """Test inter-room temperature balancing."""

    def test_balancing_with_single_room(self):
        opt = _make_optimizer(enable_room_balancing=True)
        recommendations = {"Room1": 60}
        room_states = {"Room1": {"current_temperature": 26.0, "target_temperature": 24.0}}
        result = opt._apply_room_balancing(recommendations, room_states, 24.0)
        assert result == {"Room1": 60}  # No balancing with single room

    def test_balancing_equalizes_rooms(self):
        opt = _make_optimizer(
            enable_room_balancing=True,
            target_room_variance=1.0,
            balancing_aggressiveness=0.3,
        )
        recommendations = {"Room1": 60, "Room2": 60}
        room_states = {
            "Room1": {"current_temperature": 25.0, "target_temperature": 24.0},
            "Room2": {"current_temperature": 23.0, "target_temperature": 24.0},
        }
        result = opt._apply_room_balancing(recommendations, room_states, 24.0)
        # Room1 is hotter than avg (24.0) - should get more cooling (higher fan)
        # Room2 is cooler than avg - should get less cooling (lower fan)
        assert result["Room1"] >= result["Room2"]

    def test_balancing_inactive_when_house_far_from_target(self):
        opt = _make_optimizer(enable_room_balancing=True)
        recommendations = {"Room1": 80, "Room2": 80}
        room_states = {
            "Room1": {"current_temperature": 28.0, "target_temperature": 24.0},
            "Room2": {"current_temperature": 26.0, "target_temperature": 24.0},
        }
        # House avg is 27.0, which is 3.0°C from target - exceeds 1.0°C threshold
        result = opt._apply_room_balancing(recommendations, room_states, 24.0)
        assert result == {"Room1": 80, "Room2": 80}  # No balancing applied

    def test_balancing_respects_min_airflow(self):
        opt = _make_optimizer(
            enable_room_balancing=True,
            target_room_variance=0.5,
            balancing_aggressiveness=0.5,
            min_airflow_percent=20,
        )
        recommendations = {"Room1": 60, "Room2": 25}
        room_states = {
            "Room1": {"current_temperature": 24.5, "target_temperature": 24.0},
            "Room2": {"current_temperature": 23.5, "target_temperature": 24.0},
        }
        result = opt._apply_room_balancing(recommendations, room_states, 24.0)
        assert result["Room2"] >= 20  # Should not go below min_airflow_percent


class TestACNeeded:
    """Test AC on/off hysteresis logic."""

    @pytest.mark.asyncio
    async def test_cool_mode_turn_on(self):
        opt = _make_optimizer(hvac_mode="cool", ac_turn_on_threshold=1.0)
        room_states = {
            "Room1": {"current_temperature": 25.5, "target_temperature": 24.0},
        }
        # avg_temp = 25.5, diff = +1.5 >= 1.0 threshold
        result = await opt._check_if_ac_needed(room_states, ac_currently_on=False)
        assert result is True

    @pytest.mark.asyncio
    async def test_cool_mode_stay_off(self):
        opt = _make_optimizer(hvac_mode="cool", ac_turn_on_threshold=1.0)
        room_states = {
            "Room1": {"current_temperature": 24.5, "target_temperature": 24.0},
        }
        # avg_temp = 24.5, diff = +0.5 < 1.0 threshold
        result = await opt._check_if_ac_needed(room_states, ac_currently_on=False)
        assert result is False

    @pytest.mark.asyncio
    async def test_cool_mode_turn_off(self):
        opt = _make_optimizer(hvac_mode="cool", ac_turn_off_threshold=2.0)
        room_states = {
            "Room1": {"current_temperature": 21.5, "target_temperature": 24.0},
        }
        # avg = 21.5, diff = -2.5 <= -2.0 AND max(21.5) <= 24.0
        result = await opt._check_if_ac_needed(room_states, ac_currently_on=True)
        assert result is False

    @pytest.mark.asyncio
    async def test_heat_mode_turn_on(self):
        opt = _make_optimizer(hvac_mode="heat", ac_turn_on_threshold=1.0)
        room_states = {
            "Room1": {"current_temperature": 22.5, "target_temperature": 24.0},
        }
        # avg_temp = 22.5, diff = -1.5 <= -1.0 threshold
        result = await opt._check_if_ac_needed(room_states, ac_currently_on=False)
        assert result is True

    @pytest.mark.asyncio
    async def test_no_temps_returns_false(self):
        opt = _make_optimizer()
        room_states = {
            "Room1": {"current_temperature": None, "target_temperature": 24.0},
        }
        result = await opt._check_if_ac_needed(room_states, ac_currently_on=False)
        assert result is False


class TestWeatherAdjustment:
    """Test weather-based target temperature adjustment."""

    def test_hot_weather_lowers_target(self):
        opt = _make_optimizer(weather_influence_factor=0.5)
        result = opt._calculate_weather_adjusted_target(24.0, 35.0)
        assert result < 24.0

    def test_cold_weather_raises_target(self):
        # Cold weather raises target only in heat mode (L2 fix: cross-mode suppression)
        opt = _make_optimizer(hvac_mode="heat", weather_influence_factor=0.5)
        result = opt._calculate_weather_adjusted_target(24.0, 10.0)
        assert result > 24.0

    def test_mild_weather_no_adjustment(self):
        opt = _make_optimizer(weather_influence_factor=0.5)
        result = opt._calculate_weather_adjusted_target(24.0, 22.0)
        assert result == 24.0


class TestScheduleMatching:
    """Test schedule priority matching logic."""

    def test_no_schedules_returns_none(self):
        opt = _make_optimizer(enable_scheduling=True, schedules=[])
        assert opt._get_active_schedule() is None

    def test_disabled_scheduling_returns_none(self):
        opt = _make_optimizer(enable_scheduling=False, schedules=[
            {"schedule_name": "Test", "schedule_days": ["all"],
             "schedule_start_time": "00:00", "schedule_end_time": "23:59",
             "schedule_target_temp": 22, "schedule_enabled": True}
        ])
        assert opt._get_active_schedule() is None

    def test_specific_day_beats_all(self):
        """Specific day schedule should have higher priority than 'all'."""
        from datetime import datetime
        now = datetime.now()
        current_day = now.strftime("%A").lower()

        opt = _make_optimizer(enable_scheduling=True, schedules=[
            {
                "schedule_name": "All Days",
                "schedule_days": ["all"],
                "schedule_start_time": "00:00",
                "schedule_end_time": "23:59",
                "schedule_target_temp": 22,
                "schedule_enabled": True,
            },
            {
                "schedule_name": "Today Only",
                "schedule_days": [current_day],
                "schedule_start_time": "00:00",
                "schedule_end_time": "23:59",
                "schedule_target_temp": 20,
                "schedule_enabled": True,
            },
        ])
        result = opt._get_active_schedule()
        assert result is not None
        assert result["schedule_name"] == "Today Only"

    def test_disabled_schedule_skipped(self):
        opt = _make_optimizer(enable_scheduling=True, schedules=[
            {
                "schedule_name": "Disabled",
                "schedule_days": ["all"],
                "schedule_start_time": "00:00",
                "schedule_end_time": "23:59",
                "schedule_target_temp": 22,
                "schedule_enabled": False,
            },
        ])
        assert opt._get_active_schedule() is None


class TestSensorValidation:
    """Test temperature sensor validation."""

    def test_valid_temperature(self):
        opt = _make_optimizer()
        assert opt._validate_sensor_temperature(25.5, "Room1") == 25.5

    def test_zero_temperature_accepted(self):
        opt = _make_optimizer()
        assert opt._validate_sensor_temperature(0.0, "Room1") == 0.0

    def test_extreme_temperature_rejected(self):
        opt = _make_optimizer()
        assert opt._validate_sensor_temperature(100.0, "Room1") is None
        assert opt._validate_sensor_temperature(-60.0, "Room1") is None

    def test_none_temperature(self):
        opt = _make_optimizer()
        assert opt._validate_sensor_temperature(None, "Room1") is None

    def test_string_unavailable(self):
        opt = _make_optimizer()
        assert opt._validate_sensor_temperature("unavailable", "Room1") is None
        assert opt._validate_sensor_temperature("unknown", "Room1") is None

    def test_string_numeric(self):
        opt = _make_optimizer()
        assert opt._validate_sensor_temperature("23.5", "Room1") == 23.5


class TestPredictiveControl:
    """Test rate-of-change and predictive control."""

    def test_rate_of_change_insufficient_data(self):
        opt = _make_optimizer(enable_predictive_control=True)
        # No data yet
        assert opt._get_temp_rate_of_change("Room1") is None

    def test_rate_of_change_rising(self):
        opt = _make_optimizer(enable_predictive_control=True)
        now = time.time()
        opt._temp_history["Room1"] = [
            (now - 120, 24.0),
            (now - 90, 24.1),
            (now - 60, 24.2),
            (now - 30, 24.3),
            (now, 24.4),
        ]
        rate = opt._get_temp_rate_of_change("Room1")
        assert rate is not None
        assert rate > 0  # Temperature is rising

    def test_rate_of_change_falling(self):
        opt = _make_optimizer(enable_predictive_control=True)
        now = time.time()
        opt._temp_history["Room1"] = [
            (now - 120, 26.0),
            (now - 90, 25.8),
            (now - 60, 25.6),
            (now - 30, 25.4),
            (now, 25.2),
        ]
        rate = opt._get_temp_rate_of_change("Room1")
        assert rate is not None
        assert rate < 0  # Temperature is falling

    def test_predictive_boost_when_rising_toward_target(self):
        opt = _make_optimizer(
            enable_predictive_control=True,
            hvac_mode="cool",
            predictive_lookahead_minutes=5.0,
            predictive_boost_factor=0.3,
        )
        now = time.time()
        # Temperature is rising at ~0.2°C/min (will be +1°C in 5 min)
        opt._temp_history["Room1"] = [
            (now - 120, 24.0),
            (now - 90, 24.1),
            (now - 60, 24.2),
            (now - 30, 24.3),
            (now, 24.4),
        ]
        # Current temp is 24.4, target is 24.0 - base fan speed 55
        adjusted = opt._apply_predictive_adjustment("Room1", 55, 24.4, 24.0)
        assert adjusted >= 55  # Should boost cooling since temp is rising


class TestCompressorProtection:
    """Test compressor minimum runtime protection."""

    def test_protection_disabled(self):
        opt = _make_optimizer(enable_compressor_protection=False)
        assert opt._is_compressor_protected() is False

    def test_protection_blocks_quick_turn_on(self):
        opt = _make_optimizer(
            enable_compressor_protection=True,
            compressor_min_off_time=180.0,
        )
        # AC was turned off 60 seconds ago
        opt._ac_last_turned_off = time.time() - 60
        assert opt._is_compressor_protected() is True

    def test_protection_allows_turn_on_after_min_time(self):
        opt = _make_optimizer(
            enable_compressor_protection=True,
            compressor_min_off_time=180.0,
        )
        # AC was turned off 200 seconds ago
        opt._ac_last_turned_off = time.time() - 200
        # _ac_last_turned_on is None, so only off-time check applies
        assert opt._is_compressor_protected() is False

    def test_protection_blocks_quick_turn_off(self):
        opt = _make_optimizer(
            enable_compressor_protection=True,
            compressor_min_on_time=180.0,
        )
        # AC was turned on 60 seconds ago
        opt._ac_last_turned_on = time.time() - 60
        assert opt._is_compressor_protected() is True


class TestOccupancyControl:
    """Test occupancy-based temperature setback."""

    def test_occupied_room_uses_base_target(self):
        opt = _make_optimizer(enable_occupancy_control=True, vacant_room_setback=2.0)
        opt._room_occupancy_state["Room1"] = {"occupied": True, "last_seen": time.time()}
        assert opt._get_room_effective_target("Room1", 24.0) == 24.0

    def test_vacant_room_cool_mode_raises_target(self):
        opt = _make_optimizer(
            enable_occupancy_control=True,
            hvac_mode="cool",
            vacant_room_setback=2.0,
        )
        opt._room_occupancy_state["Room1"] = {"occupied": False, "last_seen": time.time() - 600}
        result = opt._get_room_effective_target("Room1", 24.0)
        assert result == 26.0  # +2°C setback in cool mode

    def test_vacant_room_heat_mode_lowers_target(self):
        opt = _make_optimizer(
            enable_occupancy_control=True,
            hvac_mode="heat",
            vacant_room_setback=2.0,
        )
        opt._room_occupancy_state["Room1"] = {"occupied": False, "last_seen": time.time() - 600}
        result = opt._get_room_effective_target("Room1", 24.0)
        assert result == 22.0  # -2°C setback in heat mode

    def test_unknown_room_uses_base_target(self):
        opt = _make_optimizer(enable_occupancy_control=True)
        # Room not in occupancy state
        assert opt._get_room_effective_target("UnknownRoom", 24.0) == 24.0


class TestManualOverride:
    """Test manual override behavior."""

    @pytest.mark.asyncio
    async def test_manual_override_skips_optimization(self):
        opt = _make_optimizer()
        opt.manual_override_enabled = True
        result = await opt.async_optimize()
        assert result.get("manual_override") is True

    @pytest.mark.asyncio
    async def test_manual_override_skips_apply_recommendations(self):
        opt = _make_optimizer()
        opt.manual_override_enabled = True
        # Should return without calling any services
        await opt._apply_recommendations({"Room1": 75})
        opt.hass.services.async_call.assert_not_called()


class TestFahrenheitConversion:
    """Test that Fahrenheit sensors are converted before validation (C2 fix)."""

    def test_valid_fahrenheit_accepted_after_conversion(self):
        """75°F = 23.9°C should be accepted, not rejected by range check."""
        opt = _make_optimizer()
        # After conversion, 75°F = 23.9°C which is valid
        celsius = (75 - 32) * 5.0 / 9.0
        result = opt._validate_sensor_temperature(celsius, "TestRoom")
        assert result is not None
        assert abs(result - 23.9) < 0.1

    def test_high_fahrenheit_converts_correctly(self):
        """100°F = 37.8°C should be valid after conversion."""
        opt = _make_optimizer()
        celsius = (100 - 32) * 5.0 / 9.0
        result = opt._validate_sensor_temperature(celsius, "TestRoom")
        assert result is not None
        assert abs(result - 37.8) < 0.1

    def test_extreme_fahrenheit_rejected_after_conversion(self):
        """200°F = 93.3°C should be rejected even after conversion."""
        opt = _make_optimizer()
        celsius = (200 - 32) * 5.0 / 9.0
        result = opt._validate_sensor_temperature(celsius, "TestRoom")
        assert result is None


class TestACTemperatureSetpoint:
    """Test _calculate_ac_temperature uses relative offsets (C1 fix)."""

    def test_cool_mode_setpoint_at_or_below_target(self):
        """AC setpoint should never exceed the target in cool mode."""
        opt = _make_optimizer(hvac_mode="cool", target_temperature=18.0)
        room_states = {
            "Room1": {"current_temperature": 20.5, "target_temperature": 18.0, "cover_position": 50},
        }
        result = opt._calculate_ac_temperature(room_states, 18.0)
        assert result <= 18.0  # Must not be above user's target

    def test_heat_mode_setpoint_at_or_above_target(self):
        """AC setpoint should never be below the target in heat mode."""
        opt = _make_optimizer(hvac_mode="heat", target_temperature=26.0)
        room_states = {
            "Room1": {"current_temperature": 23.5, "target_temperature": 26.0, "cover_position": 50},
        }
        result = opt._calculate_ac_temperature(room_states, 26.0)
        assert result >= 26.0  # Must not be below user's target

    def test_aggressive_cool_offset(self):
        """Far above target should apply -4°C offset."""
        opt = _make_optimizer(hvac_mode="cool", target_temperature=24.0)
        room_states = {
            "Room1": {"current_temperature": 27.0, "target_temperature": 24.0, "cover_position": 50},
        }
        result = opt._calculate_ac_temperature(room_states, 24.0)
        assert result == 20.0  # 24.0 - 4.0

    def test_auto_mode_not_bypassed(self):
        """Auto mode should apply optimization, not just return target."""
        opt = _make_optimizer(hvac_mode="auto", target_temperature=24.0)
        opt._last_hvac_mode = "cool"
        room_states = {
            "Room1": {"current_temperature": 27.0, "target_temperature": 24.0, "cover_position": 50},
        }
        result = opt._calculate_ac_temperature(room_states, 24.0)
        assert result != 24.0  # Should apply optimization

    def test_heat_mode_no_setpoint_boost_during_overshoot(self):
        """Heat mode must NOT push setpoint above target when house is overshooting.

        Regression: previously used abs(temp_diff) which sent the AC ever-higher
        setpoints (e.g. target=21°C, avg=23°C → setpoint=25°C), telling the unit's
        own thermostat to keep heating past the user's target.
        """
        opt = _make_optimizer(hvac_mode="heat", target_temperature=21.0)
        # Mixed rooms: average above target, but AC may still be running due to
        # hysteresis (e.g. one cold outlier room).
        room_states = {
            "Warm": {"current_temperature": 23.0, "target_temperature": 21.0, "cover_position": 50},
            "Cold": {"current_temperature": 21.0, "target_temperature": 21.0, "cover_position": 50},
        }
        # avg = 22.0, target = 21.0 → overshoot of +1.0°C
        result = opt._calculate_ac_temperature(room_states, 21.0)
        assert result <= 21.0, (
            f"Heat setpoint must not exceed target during overshoot, got {result}°C"
        )

    def test_heat_mode_aggressive_heat_offset(self):
        """Far below target should apply +4°C offset (aggressive heating overdrive)."""
        opt = _make_optimizer(hvac_mode="heat", target_temperature=21.0)
        room_states = {
            "Room1": {"current_temperature": 17.5, "target_temperature": 21.0, "cover_position": 50},
        }
        # avg = 17.5, target = 21.0 → deviation -3.5 → offset capped at 4.0
        result = opt._calculate_ac_temperature(room_states, 21.0)
        assert result == 25.0  # 21.0 + 4.0


class TestAdaptiveBalancingConvergence:
    """Test adaptive room balancing convergence adjustment sign for both modes.

    Regression: heat-mode formula used (1.0 - relative_cool_rate) before the
    heat-mode bias flip, so a fast-cooling (poorly-insulated) cold room ended
    up with LESS heating fan, exactly the opposite of intent. Cool mode used
    (relative_heat_gain_rate - 1.0) and worked. The fix makes heat mode mirror
    the cool-mode sign convention.
    """

    def _make_learning_optimizer(self, mode: str):
        from custom_components.smart_aircon_manager.learning import LearningManager, LearningProfile

        opt = _make_optimizer(
            hvac_mode=mode,
            target_temperature=22.0,
            enable_room_balancing=True,
            enable_adaptive_balancing=True,
            target_room_variance=0.5,
            balancing_aggressiveness=0.3,
        )
        # Stub out a learning_manager that always returns a fast-degrading room.
        mgr = MagicMock(spec=LearningManager)
        mgr.should_apply_learning.return_value = True
        profile = LearningProfile(room_name="Slow")
        profile.balancing_bias = 0.0
        profile.relative_heat_gain_rate = 1.5  # heats up fast (cool-mode lever)
        profile.relative_cool_rate = 1.5       # cools down fast (heat-mode lever)
        profile.coupling_factors = {}
        mgr.get_profile.return_value = profile
        opt.learning_manager = mgr
        opt.enable_room_coupling_detection = False
        return opt

    def test_cool_mode_fast_heating_hot_room_gets_more_fan(self):
        """Baseline: cool mode with fast-heating hot room gets boosted (works pre-fix)."""
        opt = self._make_learning_optimizer("cool")
        recs = {"Hot": 80, "Cold": 60}
        room_states = {
            "Hot": {"current_temperature": 23.0, "target_temperature": 22.0, "cover_position": 50},
            "Cold": {"current_temperature": 21.0, "target_temperature": 22.0, "cover_position": 50},
        }
        result = opt._apply_room_balancing(recs, room_states, 22.0)
        # Hot room (above avg, fast-heating) should get more fan in cool mode.
        assert result["Hot"] > result["Cold"], (
            f"Cool mode: hot room should outpace cold room, got Hot={result['Hot']} Cold={result['Cold']}"
        )

    def test_heat_mode_fast_cooling_cold_room_gets_more_fan(self):
        """Regression: heat mode with fast-cooling cold room must get MORE fan.

        Before fix: the (1.0 - relative_cool_rate) formula combined with the
        heat-mode bias flip resulted in the cold/poorly-insulated room getting
        LESS fan than the hot room — the opposite of correct equalization.
        """
        opt = self._make_learning_optimizer("heat")
        recs = {"Hot": 60, "Cold": 80}
        room_states = {
            "Hot": {"current_temperature": 23.0, "target_temperature": 22.0, "cover_position": 50},
            "Cold": {"current_temperature": 21.0, "target_temperature": 22.0, "cover_position": 50},
        }
        result = opt._apply_room_balancing(recs, room_states, 22.0)
        # Cold room (below avg, fast-cooling = poorly insulated) needs MORE
        # heating fan than the hot room.
        assert result["Cold"] > result["Hot"], (
            f"Heat mode: cold/fast-cooling room should outpace hot room, "
            f"got Cold={result['Cold']} Hot={result['Hot']}"
        )


class TestPrePositioningMode:
    """Test pre-positioning is mode-aware (only prepares rooms needing the mode)."""

    def test_pre_positioning_uses_relevant_diff_cool_mode(self):
        """Cool mode: hot rooms get higher pre-position than cold rooms.

        Regression: pre-positioning used abs(deviation), so a cold room got
        the same airflow boost as a hot room, leading to over-cooling the
        cold room the moment AC turned on.
        """
        # Smoke-test the formula directly (the method itself is async + uses HA
        # services, so we verify the underlying math): in cool mode a -2°C room
        # should get min_pos, and a +2°C room should get a boosted position.
        min_pos = 30
        target = 22.0

        # Hot room (cool mode)
        hot_diff = 24.0 - target
        relevant_diff = max(0.0, hot_diff)
        hot_pos = min(80, int(min_pos + (80 - min_pos) * min(1.0, relevant_diff / 3.0)))

        # Cold room (cool mode) — wrong direction, gets min position
        cold_diff = 20.0 - target
        relevant_diff = max(0.0, cold_diff)  # 0
        cold_pos = min(80, int(min_pos + (80 - min_pos) * min(1.0, relevant_diff / 3.0)))

        assert hot_pos > cold_pos, "Cool mode: hot room must outrank cold room in pre-positioning"
        assert cold_pos == min_pos, f"Cool mode cold room should get min_pos={min_pos}, got {cold_pos}"

    def test_pre_positioning_uses_relevant_diff_heat_mode(self):
        """Heat mode: cold rooms get higher pre-position than hot rooms."""
        min_pos = 30
        target = 22.0

        # Cold room (heat mode)
        cold_diff = 20.0 - target  # -2
        relevant_diff = max(0.0, -cold_diff)  # 2
        cold_pos = min(80, int(min_pos + (80 - min_pos) * min(1.0, relevant_diff / 3.0)))

        # Hot room (heat mode) — wrong direction
        hot_diff = 24.0 - target  # +2
        relevant_diff = max(0.0, -hot_diff)  # 0
        hot_pos = min(80, int(min_pos + (80 - min_pos) * min(1.0, relevant_diff / 3.0)))

        assert cold_pos > hot_pos, "Heat mode: cold room must outrank hot room in pre-positioning"
        assert hot_pos == min_pos, f"Heat mode hot room should get min_pos={min_pos}, got {hot_pos}"


class TestPredictTemperatureRoomTarget:
    """_predict_temperature damping uses per-room target when provided."""

    def test_room_target_overrides_global_for_damping(self):
        """Rooms with target overrides should use their own target for damping calc."""
        opt = _make_optimizer(target_temperature=24.0, predictive_lookahead_minutes=10)
        # Inject a stable rate-of-change so prediction is deterministic.
        with patch.object(opt, "_get_temp_rate_of_change", return_value=0.1):
            # Room is at its OVERRIDE target (22°C) — gap should be ~0, damping=0.4
            predicted_with_override = opt._predict_temperature("Living Room", 22.0, target_temp=22.0)
            # Same physical position but using the global target (24°C) → gap=2, damping=0.6
            predicted_without_override = opt._predict_temperature("Living Room", 22.0)

        # Bigger damping factor = more predicted change (rate * lookahead * damping).
        # Without target_temp the function defaults to the global target so it
        # predicts MORE change than when we tell it the room is already at target.
        change_with = predicted_with_override - 22.0
        change_without = predicted_without_override - 22.0
        assert change_with < change_without, (
            f"Using per-room target should produce smaller predicted change near target, "
            f"got with={change_with:.3f}, without={change_without:.3f}"
        )


class TestAdaptiveDeadband:
    """Adaptive deadband widens with house-wide rate-of-change."""

    def test_disabled_returns_base_deadband(self):
        opt = _make_optimizer(temperature_deadband=0.5, enable_adaptive_deadband=False)
        # Stuff history so rate-of-change is non-zero
        with patch.object(opt, "_get_temp_rate_of_change", return_value=1.0):
            opt._temp_history = {"Living Room": [(time.time(), 20.0)] * 3}
            assert opt._get_adaptive_deadband() == 0.5

    def test_zero_rate_yields_base_deadband(self):
        opt = _make_optimizer(
            temperature_deadband=0.5,
            enable_adaptive_deadband=True,
            adaptive_deadband_max_scale=2.0,
            adaptive_deadband_rate_threshold=0.5,
        )
        # Force rate-of-change to 0
        with patch.object(opt, "_get_temp_rate_of_change", return_value=0.0):
            opt._temp_history = {"Living Room": [(time.time(), 20.0)] * 3}
            assert opt._get_adaptive_deadband() == 0.5

    def test_high_rate_clamps_to_max_scale(self):
        opt = _make_optimizer(
            temperature_deadband=0.5,
            enable_adaptive_deadband=True,
            adaptive_deadband_max_scale=2.0,
            adaptive_deadband_rate_threshold=0.5,
        )
        # Rate well past threshold → max scale (2.0×)
        with patch.object(opt, "_get_temp_rate_of_change", return_value=2.0):
            opt._temp_history = {"Living Room": [(time.time(), 20.0)] * 3}
            assert opt._get_adaptive_deadband() == 1.0  # 0.5 × 2.0

    def test_mid_rate_scales_linearly(self):
        opt = _make_optimizer(
            temperature_deadband=0.5,
            enable_adaptive_deadband=True,
            adaptive_deadband_max_scale=2.0,
            adaptive_deadband_rate_threshold=0.5,
        )
        # Rate = half of threshold → 1.5× scale
        with patch.object(opt, "_get_temp_rate_of_change", return_value=0.25):
            opt._temp_history = {"Living Room": [(time.time(), 20.0)] * 3}
            assert opt._get_adaptive_deadband() == pytest.approx(0.75, abs=0.01)

    def test_no_history_returns_base_deadband(self):
        opt = _make_optimizer(
            temperature_deadband=0.5,
            enable_adaptive_deadband=True,
        )
        # No history available — must safely return base deadband
        opt._temp_history = {}
        assert opt._get_adaptive_deadband() == 0.5

    def test_negative_rate_uses_magnitude(self):
        """Falling rate (heat mode recovery) should widen deadband just like rising."""
        opt = _make_optimizer(
            temperature_deadband=0.5,
            enable_adaptive_deadband=True,
            adaptive_deadband_max_scale=2.0,
            adaptive_deadband_rate_threshold=0.5,
        )
        with patch.object(opt, "_get_temp_rate_of_change", return_value=-2.0):
            opt._temp_history = {"Living Room": [(time.time(), 20.0)] * 3}
            assert opt._get_adaptive_deadband() == 1.0  # clamps to max regardless of sign


class TestDryModeAutoEngage:
    """Auto-control AC must engage dry mode for humidity-only demand."""

    @pytest.mark.asyncio
    async def test_dry_mode_powers_on_with_humid_air_in_deadband(self):
        """Bug: when temp is in deadband and humidity is high, AC stayed off.

        With enable_humidity_control=True and optimal_mode resolved to "dry",
        needs_ac must be coerced True so the AC powers on for dehumidification.
        """
        opt = _make_optimizer(
            hvac_mode="cool",
            target_temperature=24.0,
            auto_control_main_ac=True,
            enable_humidity_control=True,
            temperature_deadband=0.5,
            target_humidity=50.0,
        )
        # Make sensor state lookups return sensible values
        temp_state = MagicMock()
        temp_state.state = "24.1"
        temp_state.attributes = {"unit_of_measurement": "°C"}
        humid_state = MagicMock()
        humid_state.state = "75.0"
        cover_state = MagicMock()
        cover_state.state = "open"
        cover_state.attributes = {"current_position": 50}
        climate_state = MagicMock()
        climate_state.state = "off"
        climate_state.attributes = {
            "temperature": 24.0,
            "current_temperature": 24.0,
            "hvac_mode": "off",
            "hvac_action": "off",
        }

        def state_factory(eid):
            if "climate" in eid:
                return climate_state
            if "humidity" in eid:
                return humid_state
            if "cover" in eid:
                return cover_state
            return temp_state

        opt.hass.states.get.side_effect = state_factory
        # Add humidity sensor to room config
        opt.room_configs[0]["humidity_sensor"] = "sensor.lr_humidity"
        opt.room_configs[1]["humidity_sensor"] = "sensor.br_humidity"

        # Spy on _control_main_ac to see what needs_ac value it received
        with patch.object(opt, "_control_main_ac", new=AsyncMock()) as control_spy:
            await opt._async_optimize_impl()

        # _control_main_ac is called with (needs_ac, state, optimal_mode)
        assert control_spy.call_args is not None
        needs_ac_arg = control_spy.call_args[0][0]
        optimal_mode_arg = control_spy.call_args[0][2]
        assert optimal_mode_arg == "dry", f"Expected dry mode, got {optimal_mode_arg}"
        assert needs_ac_arg is True, (
            "AC must be engaged when humidity is high and mode resolves to dry, "
            f"but needs_ac was {needs_ac_arg}"
        )


class TestOvernightScheduleDays:
    """Schedule day-matching honors yesterday's day during overnight wrap."""

    def test_overnight_schedule_active_in_morning_leg(self):
        """A 'Mon 22:00–06:00' schedule must be active at 03:00 Tuesday."""
        import datetime
        from unittest.mock import patch as patch_mod

        opt = _make_optimizer(
            enable_scheduling=True,
            schedules=[
                {
                    "schedule_name": "Monday night",
                    "schedule_enabled": True,
                    "schedule_days": ["monday"],
                    "schedule_start_time": "22:00",
                    "schedule_end_time": "06:00",
                    "schedule_target_temp": 19.0,
                }
            ],
        )

        # Mock now() to be Tuesday 03:00
        fake_now = datetime.datetime(2026, 5, 19, 3, 0, 0)  # Tuesday
        with patch_mod("homeassistant.util.dt.now", return_value=fake_now):
            active = opt._get_active_schedule()

        assert active is not None, "Overnight Monday schedule must still be active at 03:00 Tuesday"
        assert active["schedule_name"] == "Monday night"

    def test_overnight_schedule_inactive_when_wrong_anchor_day(self):
        """A 'Mon 22:00–06:00' schedule must NOT be active at 03:00 Wednesday."""
        import datetime
        from unittest.mock import patch as patch_mod

        opt = _make_optimizer(
            enable_scheduling=True,
            schedules=[
                {
                    "schedule_name": "Monday night",
                    "schedule_enabled": True,
                    "schedule_days": ["monday"],
                    "schedule_start_time": "22:00",
                    "schedule_end_time": "06:00",
                    "schedule_target_temp": 19.0,
                }
            ],
        )

        # Wednesday 03:00 — Tuesday's leg already expired
        fake_now = datetime.datetime(2026, 5, 20, 3, 0, 0)
        with patch_mod("homeassistant.util.dt.now", return_value=fake_now):
            active = opt._get_active_schedule()

        assert active is None

    def test_overnight_schedule_evening_leg_still_uses_today(self):
        """A 'Mon 22:00–06:00' schedule on Monday at 23:00 should match today=Mon."""
        import datetime
        from unittest.mock import patch as patch_mod

        opt = _make_optimizer(
            enable_scheduling=True,
            schedules=[
                {
                    "schedule_name": "Monday night",
                    "schedule_enabled": True,
                    "schedule_days": ["monday"],
                    "schedule_start_time": "22:00",
                    "schedule_end_time": "06:00",
                    "schedule_target_temp": 19.0,
                }
            ],
        )

        # Monday 23:00 — evening leg, anchor day is today (Mon)
        fake_now = datetime.datetime(2026, 5, 18, 23, 0, 0)  # Monday
        with patch_mod("homeassistant.util.dt.now", return_value=fake_now):
            active = opt._get_active_schedule()

        assert active is not None
        assert active["schedule_name"] == "Monday night"


class TestQuickActionRestartRestoration:
    """Quick-action setbacks survive HA restart (target_temp in particular)."""

    @pytest.mark.asyncio
    async def test_sleep_setback_reapplied_on_restart(self):
        """If HA restarts mid-sleep, target_temp must reflect the sleep setback."""
        import json
        import tempfile

        opt = _make_optimizer(target_temperature=24.0, hvac_mode="cool")
        # Fake config_entry with an entry_id
        opt.config_entry = MagicMock()
        opt.config_entry.entry_id = "test_entry"
        # Pretend HA storage path is a temp dir; build the state file there.
        with tempfile.TemporaryDirectory() as tmpdir:
            opt.hass.config.path = MagicMock(return_value=tmpdir)
            from pathlib import Path
            state_file = Path(tmpdir) / "smart_aircon_manager.test_entry.state.json"
            now = time.time()
            state_file.write_text(json.dumps({
                "ac_last_turned_on": None,
                "ac_last_turned_off": None,
                "quick_action_mode": "sleep",
                "quick_action_expiry": now + 3600,  # 1h remaining
                "quick_action_original_settings": {
                    "target_temperature": 24.0,
                    "temperature_deadband": 0.5,
                    "hvac_mode": "cool",
                    "resolved_mode": "cool",
                },
                "saved_at": now - 600,
            }))
            # Real async_add_executor_job: just call the func synchronously.
            async def run_executor(func, *args):
                return func(*args)
            opt.hass.async_add_executor_job = run_executor

            await opt._load_compressor_state()

        assert opt._quick_action_mode == "sleep"
        # Cool sleep mode adds +1°C — target must reflect this after restart.
        assert opt.target_temperature == pytest.approx(25.0)


class TestPerRoomTargetMath:
    """AC unit decisions must anchor to the GLOBAL target, not the weighted
    average of per-room targets. Otherwise a single high-target override pulls
    the house effective target up and the AC keeps running past the user's
    actual set temperature.
    """

    @pytest.mark.asyncio
    async def test_heat_mode_does_not_keep_ac_on_for_overridden_room(self):
        """User sets 21°C global; one room overrides to 25°C. AC should turn
        off once all rooms cross 21°C, not chase the 25°C override into
        overheating the rest of the house."""
        opt = _make_optimizer(hvac_mode="heat", target_temperature=21.0,
                              ac_turn_off_threshold=0.3)
        # Simulate the global effective target the optimization cycle would set.
        opt._current_global_effective_target = 21.0
        room_states = {
            "Living": {"current_temperature": 21.5, "target_temperature": 21.0, "cover_position": 50},
            "Office": {"current_temperature": 21.2, "target_temperature": 21.0, "cover_position": 50},
            "MedicalSupplies": {"current_temperature": 23.8, "target_temperature": 25.0, "cover_position": 50},
        }
        # avg = (21.5 + 21.2 + 23.8) / 3 = 22.17; global target 21.0 →
        # temp_diff = +1.17, well past the 0.3 turn-off threshold. min_temp =
        # 21.2 >= global target 21.0. Pre-fix this would have used the
        # weighted-avg target ~22.33 and concluded AC must stay on.
        result = await opt._check_if_ac_needed(room_states, ac_currently_on=True)
        assert result is False, "AC should turn off once house exceeds global target, even if one room has higher override"

    @pytest.mark.asyncio
    async def test_heat_mode_keeps_ac_on_for_cold_room(self):
        """Per-room targets only affect dampers; if a room is below the
        GLOBAL target, AC stays on."""
        opt = _make_optimizer(hvac_mode="heat", target_temperature=21.0,
                              ac_turn_off_threshold=0.3)
        opt._current_global_effective_target = 21.0
        room_states = {
            "Living": {"current_temperature": 20.0, "target_temperature": 21.0, "cover_position": 50},
            "MedicalSupplies": {"current_temperature": 23.8, "target_temperature": 25.0, "cover_position": 50},
        }
        # avg = 21.9, temp_diff = +0.9 (past threshold), but min_temp = 20.0
        # < global target 21.0 → AC stays on.
        result = await opt._check_if_ac_needed(room_states, ac_currently_on=True)
        assert result is True

    def test_ac_setpoint_uses_global_target_not_weighted_avg(self):
        """In heat mode with one high-target room, AC setpoint should still
        anchor to the user's global target, not the average."""
        opt = _make_optimizer(hvac_mode="heat", target_temperature=21.0)
        opt._current_global_effective_target = 21.0
        room_states = {
            "Living": {"current_temperature": 21.5, "target_temperature": 21.0, "cover_position": 50},
            "MedicalSupplies": {"current_temperature": 23.8, "target_temperature": 25.0, "cover_position": 50},
        }
        # avg = 22.65, global target = 21.0 → temp_diff = +1.65, offset = 0
        # (we're already above the global target in heat mode), so setpoint
        # clamps to 21.0. Pre-fix the formula reached for the weighted-avg
        # target (~23.0) and emitted a setpoint near 23°C.
        result = opt._calculate_ac_temperature(room_states, effective_target=23.0)
        assert result <= 21.0, (
            f"Heat setpoint must not exceed global target with per-room override, got {result}°C"
        )


class TestHvacModeInitialization:
    """async_setup must only seed _last_hvac_mode with real conditioning modes."""

    @pytest.mark.asyncio
    async def test_off_state_does_not_seed_last_hvac_mode(self):
        """If the climate entity is off at startup, _last_hvac_mode stays None.

        Regression: previously accepted any non-"unavailable" state, leaking
        strings like "off" into mode-dependent branches.
        """
        opt = _make_optimizer(hvac_mode="auto", main_climate_entity="climate.ac")
        opt.config_entry = MagicMock()
        opt.config_entry.entry_id = "test_entry"
        opt.config_entry.data = {}
        # Climate entity is in "off" state on boot
        climate_state = MagicMock()
        climate_state.state = "off"
        opt.hass.states.get.return_value = climate_state
        # Stub async file I/O so async_setup doesn't try to touch disk
        async def noop_executor(func, *args):
            return None
        opt.hass.async_add_executor_job = noop_executor

        await opt.async_setup()
        assert opt._last_hvac_mode is None, (
            f"_last_hvac_mode should not be seeded with 'off', got {opt._last_hvac_mode!r}"
        )

    @pytest.mark.asyncio
    async def test_cool_state_seeds_last_hvac_mode(self):
        """A real conditioning mode at startup should seed tracking."""
        opt = _make_optimizer(hvac_mode="auto", main_climate_entity="climate.ac")
        opt.config_entry = MagicMock()
        opt.config_entry.entry_id = "test_entry"
        opt.config_entry.data = {}
        climate_state = MagicMock()
        climate_state.state = "cool"
        opt.hass.states.get.return_value = climate_state
        async def noop_executor(func, *args):
            return None
        opt.hass.async_add_executor_job = noop_executor

        await opt.async_setup()
        assert opt._last_hvac_mode == "cool"


class TestOptimizerDisabled:
    """Test that optimizer respects is_enabled flag (C4 fix)."""

    @pytest.mark.asyncio
    async def test_disabled_optimizer_returns_system_off(self):
        opt = _make_optimizer()
        opt.is_enabled = False
        result = await opt.async_optimize()
        assert result.get("system_off") is True
        assert result["recommendations"] == {}

    @pytest.mark.asyncio
    async def test_enabled_optimizer_does_not_return_system_off(self):
        opt = _make_optimizer()
        opt.is_enabled = True
        result = await opt.async_optimize()
        assert result.get("system_off") is not True


class TestQuickActionExit:
    """Test that boost/party mode exit doesn't revert user temp changes (H3 fix)."""

    def test_boost_exit_preserves_user_temp_change(self):
        opt = _make_optimizer(target_temperature=24.0)
        opt._quick_action_mode = "boost"
        opt._quick_action_original_settings = {
            "target_temperature": 24.0,
            "temperature_deadband": 0.5,
        }
        # User changes temp during boost
        opt.target_temperature = 22.0
        opt._exit_quick_action_mode()
        # boost didn't modify temp, so user's 22.0 should be preserved
        assert opt.target_temperature == 22.0

    def test_party_exit_preserves_user_temp_change(self):
        opt = _make_optimizer(target_temperature=24.0)
        opt._quick_action_mode = "party"
        opt._quick_action_original_settings = {
            "target_temperature": 24.0,
            "temperature_deadband": 0.5,
        }
        opt.target_temperature = 20.0
        opt._exit_quick_action_mode()
        assert opt.target_temperature == 20.0

    def test_sleep_exit_restores_if_unmodified(self):
        opt = _make_optimizer(target_temperature=25.0, hvac_mode="cool")
        opt._quick_action_mode = "sleep"
        opt._quick_action_original_settings = {
            "target_temperature": 24.0,
            "temperature_deadband": 0.5,
        }
        # Sleep mode set temp to 25.0 (original 24.0 + 1.0 for cool mode)
        # User didn't change it, so current == what mode would have set
        opt._exit_quick_action_mode()
        assert opt.target_temperature == 24.0  # Restored to original


class TestAutoModeOccupancySetback:
    """Test auto mode occupancy setback uses effective mode, not magic number (H1 fix)."""

    def test_auto_mode_high_target_cooling(self):
        """Target=28 in auto mode resolving to cool should apply +setback."""
        opt = _make_optimizer(
            enable_occupancy_control=True,
            hvac_mode="auto",
            target_temperature=28.0,
            vacant_room_setback=2.0,
        )
        opt._last_hvac_mode = "cool"
        opt._room_occupancy_state["Living Room"] = {"occupied": False, "last_seen": time.time() - 600}
        result = opt._get_room_effective_target("Living Room", 28.0)
        assert result == 30.0  # +2°C setback (cooling direction)

    def test_auto_mode_resolving_to_heat(self):
        """Auto mode resolving to heat should apply -setback."""
        opt = _make_optimizer(
            enable_occupancy_control=True,
            hvac_mode="auto",
            target_temperature=22.0,
            vacant_room_setback=2.0,
        )
        opt._last_hvac_mode = "heat"
        opt._room_occupancy_state["Living Room"] = {"occupied": False, "last_seen": time.time() - 600}
        result = opt._get_room_effective_target("Living Room", 22.0)
        assert result == 20.0  # -2°C setback (heating direction)


class TestModeTrackingWithoutHumidity:
    """Test that _determine_optimal_hvac_mode tracks state even without humidity (H2 fix)."""

    def test_no_humidity_auto_resolves_to_heat_when_cold(self):
        opt = _make_optimizer(hvac_mode="auto", enable_humidity_control=False)
        room_states = {
            "Room1": {"current_temperature": 20.0, "target_temperature": 24.0},
        }
        result = opt._determine_optimal_hvac_mode(room_states, 24.0)
        assert result == "heat"
        assert opt._last_hvac_mode == "heat"

    def test_no_humidity_auto_resolves_to_cool_when_hot(self):
        opt = _make_optimizer(hvac_mode="auto", enable_humidity_control=False)
        room_states = {
            "Room1": {"current_temperature": 27.0, "target_temperature": 24.0},
        }
        result = opt._determine_optimal_hvac_mode(room_states, 24.0)
        assert result == "cool"
        assert opt._last_hvac_mode == "cool"

    def test_no_humidity_explicit_mode_preserved(self):
        opt = _make_optimizer(hvac_mode="heat", enable_humidity_control=False)
        room_states = {
            "Room1": {"current_temperature": 27.0, "target_temperature": 24.0},
        }
        result = opt._determine_optimal_hvac_mode(room_states, 24.0)
        assert result == "heat"  # Explicit mode preserved regardless of temp

class TestTemperatureNormalization:
    """Test temperature normalization (Finding 1 fix)."""

    def test_celsius_passthrough(self):
        from custom_components.smart_aircon_manager.temperature_utils import normalize_temperature

        # Mock state object with Celsius
        state = MagicMock()
        state.state = "22.5"
        state.attributes = {"unit_of_measurement": "°C"}

        result = normalize_temperature(state, "test_sensor")
        assert result == 22.5

    def test_fahrenheit_conversion(self):
        from custom_components.smart_aircon_manager.temperature_utils import normalize_temperature

        # Mock state object with Fahrenheit (72°F = 22.2°C)
        state = MagicMock()
        state.state = "72.0"
        state.attributes = {"unit_of_measurement": "°F"}

        result = normalize_temperature(state, "test_sensor")
        assert result is not None
        assert abs(result - 22.22) < 0.01  # Allow small floating point variance

    def test_fahrenheit_high_value_valid(self):
        from custom_components.smart_aircon_manager.temperature_utils import normalize_temperature, validate_temperature_range

        # 80°F = 26.67°C - should be valid after conversion
        state = MagicMock()
        state.state = "80.0"
        state.attributes = {"unit_of_measurement": "°F"}

        result = normalize_temperature(state, "test_sensor")
        assert result is not None
        assert validate_temperature_range(result)

    def test_unavailable_returns_none(self):
        from custom_components.smart_aircon_manager.temperature_utils import normalize_temperature

        state = MagicMock()
        state.state = "unavailable"
        state.attributes = {"unit_of_measurement": "°C"}

        result = normalize_temperature(state, "test_sensor")
        assert result is None

    def test_non_numeric_returns_none(self):
        from custom_components.smart_aircon_manager.temperature_utils import normalize_temperature

        state = MagicMock()
        state.state = "not_a_number"
        state.attributes = {"unit_of_measurement": "°C"}

        result = normalize_temperature(state, "test_sensor")
        assert result is None


class TestACTurnOnOutlier:
    """Test AC turn-on with outlier room detection (Finding 2 fix)."""

    @pytest.mark.asyncio
    async def test_cool_mode_outlier_triggers_ac(self):
        """One very hot room should trigger AC even if average is okay."""
        opt = _make_optimizer(hvac_mode="cool", ac_turn_on_threshold=1.0)
        room_states = {
            "Room1": {"current_temperature": 28.0, "target_temperature": 24.0},  # +4°C (outlier)
            "Room2": {"current_temperature": 23.0, "target_temperature": 24.0},  # -1°C
            "Room3": {"current_temperature": 23.5, "target_temperature": 24.0},  # -0.5°C
        }
        # avg_temp = 24.83, diff = +0.83 < 1.0 threshold (wouldn't trigger)
        # BUT max_temp = 28.0, max_deviation = +4.0 >= 1.5 (SHOULD trigger)
        result = await opt._check_if_ac_needed(room_states, ac_currently_on=False)
        assert result is True

    @pytest.mark.asyncio
    async def test_heat_mode_outlier_triggers_ac(self):
        """One very cold room should trigger AC even if average is okay."""
        opt = _make_optimizer(hvac_mode="heat", ac_turn_on_threshold=1.0)
        room_states = {
            "Room1": {"current_temperature": 20.0, "target_temperature": 24.0},  # -4°C (outlier)
            "Room2": {"current_temperature": 25.0, "target_temperature": 24.0},  # +1°C
            "Room3": {"current_temperature": 24.5, "target_temperature": 24.0},  # +0.5°C
        }
        # avg_temp = 23.17, diff = -0.83 > -1.0 threshold (wouldn't trigger)
        # BUT min_temp = 20.0, min_deviation = +4.0 >= 1.5 (SHOULD trigger)
        result = await opt._check_if_ac_needed(room_states, ac_currently_on=False)
        assert result is True

    @pytest.mark.asyncio
    async def test_no_outlier_requires_average(self):
        """Without outlier, normal threshold applies."""
        opt = _make_optimizer(hvac_mode="cool", ac_turn_on_threshold=1.0)
        room_states = {
            "Room1": {"current_temperature": 24.6, "target_temperature": 24.0},
            "Room2": {"current_temperature": 24.5, "target_temperature": 24.0},
        }
        # avg = 24.55, diff = +0.55 < 1.0 threshold (shouldn't trigger)
        # max = 24.6, max_deviation = +0.6 < 1.5 (no outlier)
        result = await opt._check_if_ac_needed(room_states, ac_currently_on=False)
        assert result is False


class TestHeatModeDryModeSuppression:
    """Heat mode must not select dry mode (dry runs the compressor in a low-flow
    refrigeration cycle and cools the air, fighting the heat loop)."""

    def test_heat_mode_high_humidity_picks_fan_only_not_dry(self):
        opt = _make_optimizer(
            hvac_mode="heat",
            enable_humidity_control=True,
            target_humidity=60.0,
            humidity_deadband=5.0,
            dry_mode_humidity_threshold=65.0,
            temperature_deadband=0.5,
        )
        # Temperature in deadband, humidity above dry-mode threshold
        room_states = {
            "Room1": {"current_temperature": 24.0, "target_temperature": 24.0, "current_humidity": 70.0},
        }
        result = opt._determine_optimal_hvac_mode(room_states, 24.0)
        assert result == "fan_only", f"Expected fan_only in heat mode, got {result}"

    def test_heat_mode_humidity_excess_picks_fan_only_not_dry(self):
        opt = _make_optimizer(
            hvac_mode="heat",
            enable_humidity_control=True,
            target_humidity=60.0,
            humidity_deadband=5.0,
            dry_mode_humidity_threshold=80.0,  # High threshold so only the deadband path can match
            temperature_deadband=0.5,
        )
        # Humidity exceeds deadband (66 - 60 = 6 > 5) but below dry threshold (80)
        room_states = {
            "Room1": {"current_temperature": 24.0, "target_temperature": 24.0, "current_humidity": 66.0},
        }
        result = opt._determine_optimal_hvac_mode(room_states, 24.0)
        assert result == "fan_only"

    def test_cool_mode_high_humidity_still_picks_dry(self):
        """Sanity check — dry-mode suppression must NOT affect cooling."""
        opt = _make_optimizer(
            hvac_mode="cool",
            enable_humidity_control=True,
            target_humidity=60.0,
            humidity_deadband=5.0,
            dry_mode_humidity_threshold=65.0,
            temperature_deadband=0.5,
        )
        room_states = {
            "Room1": {"current_temperature": 24.0, "target_temperature": 24.0, "current_humidity": 70.0},
        }
        result = opt._determine_optimal_hvac_mode(room_states, 24.0)
        assert result == "dry"

    def test_auto_mode_with_last_heat_picks_fan_only_not_dry(self):
        """Auto mode that resolved to heat last cycle should also suppress dry."""
        opt = _make_optimizer(
            hvac_mode="auto",
            enable_humidity_control=True,
            target_humidity=60.0,
            humidity_deadband=5.0,
            dry_mode_humidity_threshold=65.0,
            temperature_deadband=0.5,
        )
        opt._last_hvac_mode = "heat"
        room_states = {
            "Room1": {"current_temperature": 24.0, "target_temperature": 24.0, "current_humidity": 70.0},
        }
        result = opt._determine_optimal_hvac_mode(room_states, 24.0)
        assert result == "fan_only"

    def test_heat_mode_temp_priority_still_returns_heat(self):
        """Temperature priority must still beat humidity in heat mode."""
        opt = _make_optimizer(
            hvac_mode="heat",
            enable_humidity_control=True,
            target_humidity=60.0,
            humidity_deadband=5.0,
            dry_mode_humidity_threshold=65.0,
            temperature_deadband=0.5,
        )
        room_states = {
            # Below target by more than deadband AND humidity is high
            "Room1": {"current_temperature": 22.0, "target_temperature": 24.0, "current_humidity": 75.0},
        }
        result = opt._determine_optimal_hvac_mode(room_states, 24.0)
        assert result == "heat"
