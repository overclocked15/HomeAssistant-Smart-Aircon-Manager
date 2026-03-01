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
