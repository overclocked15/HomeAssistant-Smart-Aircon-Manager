"""Logic-based Manager for Aircon control."""
from __future__ import annotations

import asyncio
import logging
import statistics
import time
from pathlib import Path
from typing import Any

from homeassistant.core import HomeAssistant

from .learning import LearningManager

_LOGGER = logging.getLogger(__name__)

# Retry configuration
MAX_RETRIES = 3
INITIAL_RETRY_DELAY = 1.0  # seconds
RETRY_BACKOFF_FACTOR = 2.0  # exponential backoff multiplier


class AirconOptimizer:
    """Manages logic-based aircon optimization."""

    def __init__(
        self,
        hass: HomeAssistant,
        target_temperature: float,
        room_configs: list[dict[str, Any]],
        main_climate_entity: str | None = None,
        main_fan_entity: str | None = None,
        temperature_deadband: float = 0.5,
        hvac_mode: str = "cool",
        auto_control_main_ac: bool = False,
        auto_control_ac_temperature: bool = False,
        enable_notifications: bool = True,
        room_overrides: dict[str, Any] | None = None,
        config_entry: Any | None = None,
        ac_turn_on_threshold: float = 1.0,
        ac_turn_off_threshold: float = 2.0,
        weather_entity: str | None = None,
        enable_weather_adjustment: bool = False,
        outdoor_temp_sensor: str | None = None,
        enable_scheduling: bool = False,
        schedules: list[dict[str, Any]] | None = None,
        main_fan_high_threshold: float = 2.5,
        main_fan_medium_threshold: float = 1.0,
        weather_influence_factor: float = 0.5,
        overshoot_tier1_threshold: float = 1.0,
        overshoot_tier2_threshold: float = 2.0,
        overshoot_tier3_threshold: float = 3.0,
        enable_room_balancing: bool = True,
        target_room_variance: float = 1.5,
        balancing_aggressiveness: float = 0.2,
        min_airflow_percent: int = 15,
        enable_humidity_control: bool = False,
        target_humidity: float = 60.0,
        humidity_deadband: float = 5.0,
        dry_mode_humidity_threshold: float = 65.0,
        mode_change_hysteresis_time: float = 300.0,
        mode_change_hysteresis_temp: float = 0.3,
        enable_occupancy_control: bool = False,
        occupancy_sensors: dict[str, str] | None = None,
        vacant_room_setback: float = 2.0,
        vacancy_timeout: float = 300.0,
        enable_compressor_protection: bool = True,
        compressor_min_on_time: float = 180.0,
        compressor_min_off_time: float = 180.0,
        enable_predictive_control: bool = False,
        predictive_lookahead_minutes: float = 5.0,
        predictive_boost_factor: float = 0.3,
        notify_services: list[str] | None = None,
    ) -> None:
        """Initialize the optimizer."""
        self.hass = hass

        # Validate and store configuration parameters
        self.target_temperature = self._validate_temperature(target_temperature, "target_temperature", 10.0, 35.0)
        self.room_configs = room_configs
        self.main_climate_entity = main_climate_entity
        self.main_fan_entity = main_fan_entity
        self.temperature_deadband = self._validate_positive_float(temperature_deadband, "temperature_deadband", 0.1, 5.0)
        self.hvac_mode = hvac_mode if hvac_mode in ["cool", "heat", "auto"] else "cool"
        self.auto_control_main_ac = auto_control_main_ac
        self.auto_control_ac_temperature = auto_control_ac_temperature
        self.enable_notifications = enable_notifications
        self.room_overrides = room_overrides or {}
        self.config_entry = config_entry
        self.ac_turn_on_threshold = self._validate_positive_float(ac_turn_on_threshold, "ac_turn_on_threshold", 0.1, 10.0)
        self.ac_turn_off_threshold = self._validate_positive_float(ac_turn_off_threshold, "ac_turn_off_threshold", 0.1, 10.0)
        self.weather_entity = weather_entity
        self.enable_weather_adjustment = enable_weather_adjustment
        self.outdoor_temp_sensor = outdoor_temp_sensor
        self.enable_scheduling = enable_scheduling
        self.schedules = schedules or []
        self.main_fan_high_threshold = self._validate_positive_float(main_fan_high_threshold, "main_fan_high_threshold", 0.1, 10.0)
        self.main_fan_medium_threshold = self._validate_positive_float(main_fan_medium_threshold, "main_fan_medium_threshold", 0.1, 10.0)
        self.weather_influence_factor = self._validate_positive_float(weather_influence_factor, "weather_influence_factor", 0.0, 1.0)
        self.overshoot_tier1_threshold = self._validate_positive_float(overshoot_tier1_threshold, "overshoot_tier1_threshold", 0.1, 10.0)
        self.overshoot_tier2_threshold = self._validate_positive_float(overshoot_tier2_threshold, "overshoot_tier2_threshold", 0.1, 10.0)
        self.overshoot_tier3_threshold = self._validate_positive_float(overshoot_tier3_threshold, "overshoot_tier3_threshold", 0.1, 10.0)

        # Validate overshoot thresholds are in ascending order
        if not (self.overshoot_tier1_threshold < self.overshoot_tier2_threshold < self.overshoot_tier3_threshold):
            _LOGGER.warning(
                "Overshoot thresholds not in ascending order (%.1f, %.1f, %.1f), auto-correcting...",
                self.overshoot_tier1_threshold, self.overshoot_tier2_threshold, self.overshoot_tier3_threshold
            )
            sorted_thresholds = sorted([self.overshoot_tier1_threshold, self.overshoot_tier2_threshold, self.overshoot_tier3_threshold])
            self.overshoot_tier1_threshold = sorted_thresholds[0]
            self.overshoot_tier2_threshold = sorted_thresholds[1]
            self.overshoot_tier3_threshold = sorted_thresholds[2]
            _LOGGER.info(
                "Corrected overshoot thresholds to: tier1=%.1f, tier2=%.1f, tier3=%.1f",
                self.overshoot_tier1_threshold, self.overshoot_tier2_threshold, self.overshoot_tier3_threshold
            )

        # Inter-room balancing configuration
        self.enable_room_balancing = enable_room_balancing
        self.target_room_variance = self._validate_positive_float(target_room_variance, "target_room_variance", 0.5, 5.0)
        self.balancing_aggressiveness = self._validate_positive_float(balancing_aggressiveness, "balancing_aggressiveness", 0.0, 0.5)
        self.min_airflow_percent = max(5, min(50, int(min_airflow_percent)))  # Clamp to 5-50%

        # Balancing state tracking
        self._house_avg_temp = None
        self._house_temp_variance = None
        self._balancing_active = False

        # Humidity control configuration
        self.enable_humidity_control = enable_humidity_control
        self.target_humidity = self._validate_positive_float(target_humidity, "target_humidity", 30.0, 80.0)
        self.humidity_deadband = self._validate_positive_float(humidity_deadband, "humidity_deadband", 1.0, 15.0)
        self.dry_mode_humidity_threshold = self._validate_positive_float(dry_mode_humidity_threshold, "dry_mode_humidity_threshold", 50.0, 90.0)

        # Humidity state tracking
        self._house_avg_humidity = None
        self._dry_mode_active = False
        self._fan_only_mode_active = False

        # HVAC mode change hysteresis configuration
        self.mode_change_hysteresis_time = max(0, float(mode_change_hysteresis_time))
        self.mode_change_hysteresis_temp = self._validate_positive_float(mode_change_hysteresis_temp, "mode_change_hysteresis_temp", 0.0, 2.0)
        self._last_hvac_mode = None
        self._last_mode_change_time = None

        # Occupancy-based control configuration
        self.enable_occupancy_control = enable_occupancy_control
        self.occupancy_sensors = occupancy_sensors or {}
        self.vacant_room_setback = self._validate_positive_float(vacant_room_setback, "vacant_room_setback", 0.0, 5.0)
        self.vacancy_timeout = max(0, float(vacancy_timeout))
        self._room_occupancy_state = {}  # room_name -> {"occupied": bool, "last_seen": timestamp}

        # Compressor protection
        self.enable_compressor_protection = enable_compressor_protection
        self.compressor_min_on_time = max(0, float(compressor_min_on_time))
        self.compressor_min_off_time = max(0, float(compressor_min_off_time))
        self._ac_last_turned_on = None   # Timestamp when AC was last turned on
        self._ac_last_turned_off = None  # Timestamp when AC was last turned off

        # Predictive control
        self.enable_predictive_control = enable_predictive_control
        self.predictive_lookahead_minutes = self._validate_positive_float(
            predictive_lookahead_minutes, "predictive_lookahead_minutes", 1.0, 30.0
        )
        self.predictive_boost_factor = self._validate_positive_float(
            predictive_boost_factor, "predictive_boost_factor", 0.0, 1.0
        )
        self._temp_history = {}  # room_name -> list of (timestamp, temp) tuples
        self._max_history_points = 10  # Keep last 10 readings per room

        # Configurable notification services
        self.notify_services = notify_services or []

        self._last_optimization_response = None
        self._last_error = None
        self._error_count = 0
        self._startup_time = None
        from .const import DEFAULT_STARTUP_DELAY, DEFAULT_UPDATE_INTERVAL
        self._startup_delay_seconds = DEFAULT_STARTUP_DELAY
        self._last_optimization = None
        self._optimization_interval = DEFAULT_UPDATE_INTERVAL * 60
        self._last_recommendations = {}
        self._last_main_fan_speed = None
        self._current_schedule = None
        self._outdoor_temperature = None
        self._last_fan_speeds = {}  # For smoothing

        # Performance metrics tracking
        self._total_optimizations_run = 0
        self._optimization_start_time = None
        self._last_cycle_time_ms = None
        self._last_cycle_timestamp = None  # Track actual wall-clock time between cycles

        # Adaptive learning
        self.learning_manager = None  # Will be initialized in async_setup
        self._last_room_temps = {}  # Track temps for learning
        self._last_learning_update = None  # Track when we last updated learning profiles
        self._learning_update_interval = 3600  # Update learning profiles every hour

    def _validate_temperature(self, value: float, name: str, min_val: float, max_val: float) -> float:
        """Validate temperature value is within acceptable range."""
        try:
            temp = float(value)
            if not (min_val <= temp <= max_val):
                _LOGGER.warning(
                    "%s value %.1f°C outside valid range (%.1f-%.1f°C), using default",
                    name, temp, min_val, max_val
                )
                return 22.0  # Safe default
            return temp
        except (ValueError, TypeError) as e:
            _LOGGER.error("Invalid %s value '%s': %s, using default", name, value, e)
            return 22.0

    def _validate_positive_float(self, value: float, name: str, min_val: float, max_val: float) -> float:
        """Validate float value is positive and within range."""
        try:
            val = float(value)
            if not (min_val <= val <= max_val):
                _LOGGER.warning(
                    "%s value %.2f outside valid range (%.2f-%.2f), clamping",
                    name, val, min_val, max_val
                )
                return max(min_val, min(max_val, val))
            return val
        except (ValueError, TypeError) as e:
            _LOGGER.error("Invalid %s value '%s': %s, using minimum", name, value, e)
            return min_val

    def _validate_sensor_temperature(self, value: Any, room_name: str) -> float | None:
        """Validate temperature reading from sensor with sanity checks."""
        if value is None or value in ["unknown", "unavailable", "none"]:
            return None

        try:
            temp = float(value)

            # Sanity check: realistic temperature range (-50°C to 70°C)
            if not (-50.0 <= temp <= 70.0):
                _LOGGER.warning(
                    "Temperature reading for %s (%.1f°C) outside realistic range, ignoring",
                    room_name, temp
                )
                return None

            return temp
        except (ValueError, TypeError) as e:
            _LOGGER.warning("Could not parse temperature for %s: %s", room_name, e)
            return None

    async def async_setup(self) -> None:
        """Set up the optimizer."""
        self._startup_time = time.time()
        _LOGGER.info("Smart Aircon Manager optimizer initialized (logic-based, no AI required)")

        # Initialize learning manager
        storage_path = Path(self.hass.config.path(".storage"))
        config_entry_id = self.config_entry.entry_id if self.config_entry else "default"
        self.learning_manager = LearningManager(self.hass, config_entry_id, storage_path)

        # Apply configuration from config entry
        if self.config_entry:
            from .const import (
                CONF_ENABLE_LEARNING,
                CONF_LEARNING_MODE,
                CONF_LEARNING_CONFIDENCE_THRESHOLD,
                CONF_LEARNING_MAX_ADJUSTMENT,
                DEFAULT_ENABLE_LEARNING,
                DEFAULT_LEARNING_MODE,
                DEFAULT_LEARNING_CONFIDENCE_THRESHOLD,
                DEFAULT_LEARNING_MAX_ADJUSTMENT,
            )
            _LOGGER.debug(
                "Reading learning config from entry. Config entry data keys: %s",
                list(self.config_entry.data.keys())
            )
            self.learning_manager.enabled = self.config_entry.data.get(CONF_ENABLE_LEARNING, DEFAULT_ENABLE_LEARNING)
            self.learning_manager.learning_mode = self.config_entry.data.get(CONF_LEARNING_MODE, DEFAULT_LEARNING_MODE)
            self.learning_manager.confidence_threshold = self.config_entry.data.get(
                CONF_LEARNING_CONFIDENCE_THRESHOLD, DEFAULT_LEARNING_CONFIDENCE_THRESHOLD
            )
            self.learning_manager.max_adjustment_per_update = self.config_entry.data.get(
                CONF_LEARNING_MAX_ADJUSTMENT, DEFAULT_LEARNING_MAX_ADJUSTMENT
            )
            _LOGGER.debug(
                "Learning config applied: enabled=%s, mode=%s, confidence=%s, max_adj=%s",
                self.learning_manager.enabled,
                self.learning_manager.learning_mode,
                self.learning_manager.confidence_threshold,
                self.learning_manager.max_adjustment_per_update
            )

        # Load existing learning profiles
        await self.learning_manager.async_load_profiles()
        _LOGGER.info(
            "Adaptive learning initialized (enabled: %s, mode: %s)",
            self.learning_manager.enabled,
            self.learning_manager.learning_mode
        )

        # Initialize HVAC mode tracking from current climate entity state
        if self.main_climate_entity:
            climate_state = self.hass.states.get(self.main_climate_entity)
            if climate_state:
                current_hvac_mode = climate_state.state
                if current_hvac_mode and current_hvac_mode != "unavailable":
                    self._last_hvac_mode = current_hvac_mode
                    _LOGGER.info(
                        "Initialized HVAC mode tracking: %s (from climate entity %s)",
                        current_hvac_mode,
                        self.main_climate_entity
                    )
                else:
                    _LOGGER.debug(
                        "Climate entity %s state unavailable, HVAC mode tracking will initialize on first optimization",
                        self.main_climate_entity
                    )
            else:
                _LOGGER.debug(
                    "Climate entity %s not found, HVAC mode tracking will initialize on first optimization",
                    self.main_climate_entity
                )

    async def _retry_service_call(
        self,
        domain: str,
        service: str,
        service_data: dict[str, Any],
        entity_name: str = "unknown"
    ) -> bool:
        """Call a service with retry logic and exponential backoff.

        Returns True if successful, False if all retries exhausted.
        """
        last_exception = None

        for attempt in range(MAX_RETRIES):
            try:
                await self.hass.services.async_call(
                    domain,
                    service,
                    service_data,
                    blocking=True,
                )

                if attempt > 0:
                    _LOGGER.info(
                        "Successfully called %s.%s for %s on attempt %d",
                        domain, service, entity_name, attempt + 1
                    )

                return True

            except Exception as e:
                last_exception = e

                if attempt < MAX_RETRIES - 1:
                    delay = INITIAL_RETRY_DELAY * (RETRY_BACKOFF_FACTOR ** attempt)
                    _LOGGER.warning(
                        "Failed to call %s.%s for %s (attempt %d/%d): %s. Retrying in %.1fs...",
                        domain, service, entity_name, attempt + 1, MAX_RETRIES, e, delay
                    )
                    await asyncio.sleep(delay)
                else:
                    _LOGGER.error(
                        "Failed to call %s.%s for %s after %d attempts: %s",
                        domain, service, entity_name, MAX_RETRIES, e
                    )

        # All retries exhausted
        self._last_error = f"Service call failed after {MAX_RETRIES} attempts: {last_exception}"
        self._error_count += 1
        return False

    def _get_active_schedule(self) -> dict[str, Any] | None:
        """Get the currently active schedule based on time and day.

        When multiple schedules match, the most specific day match wins:
        - Specific day (e.g. "monday") beats "weekdays"/"weekends"
        - "weekdays"/"weekends" beats "all"
        """
        if not self.enable_scheduling or not self.schedules:
            return None

        from homeassistant.util import dt as dt_util
        now = dt_util.now()
        current_time = now.time()
        current_day = now.strftime("%A").lower()

        best_schedule = None
        best_priority = -1  # Higher = more specific

        for schedule in self.schedules:
            if not schedule.get("schedule_enabled", True):
                continue

            schedule_days = schedule.get("schedule_days", [])
            if not schedule_days:
                continue

            # Check day match and assign specificity priority
            day_match = False
            priority = 0
            if current_day in schedule_days:
                day_match = True
                priority = 3  # Most specific: exact day name
            elif "weekdays" in schedule_days and current_day in ["monday", "tuesday", "wednesday", "thursday", "friday"]:
                day_match = True
                priority = 2  # Medium: weekdays group
            elif "weekends" in schedule_days and current_day in ["saturday", "sunday"]:
                day_match = True
                priority = 2  # Medium: weekends group
            elif "all" in schedule_days:
                day_match = True
                priority = 1  # Least specific: all days

            if not day_match:
                continue

            # Check time range
            start_time = schedule.get("schedule_start_time")
            end_time = schedule.get("schedule_end_time")

            if not start_time or not end_time:
                continue

            try:
                from datetime import time as dt_time
                start_hour, start_min = map(int, start_time.split(":"))
                end_hour, end_min = map(int, end_time.split(":"))
                start_t = dt_time(start_hour, start_min)
                end_t = dt_time(end_hour, end_min)

                time_match = False
                if start_t <= end_t:
                    time_match = start_t <= current_time <= end_t
                else:
                    # Crosses midnight
                    time_match = current_time >= start_t or current_time <= end_t

                if time_match and priority > best_priority:
                    best_schedule = schedule
                    best_priority = priority
            except (ValueError, AttributeError) as e:
                _LOGGER.warning("Invalid schedule time format: %s", e)
                continue

        if best_schedule:
            _LOGGER.debug(
                "Active schedule found: %s (priority: %d)",
                best_schedule.get("schedule_name", "Unnamed"),
                best_priority
            )

        return best_schedule

    def _determine_optimal_hvac_mode(self, room_states: dict[str, dict[str, Any]], effective_target: float) -> str:
        """Determine optimal HVAC mode based on temperature and humidity conditions.

        Logic-based decision making with hysteresis to prevent mode thrashing:
        1. Temperature ALWAYS has priority over humidity
        2. If temperature needs attention (>deadband from target) -> cool/heat mode
        3. If temperature is OK but humidity is high -> dry mode
        4. If both temperature and humidity are OK -> fan_only mode for circulation
        5. Hysteresis prevents rapid mode switching unless deviation is severe

        Returns: "cool", "heat", "dry", or "fan_only"
        """
        if not self.enable_humidity_control:
            # No humidity control - return based on hvac_mode setting
            return self.hvac_mode if self.hvac_mode != "auto" else "cool"

        # Collect valid temperatures and humidities
        temps = self._valid_temps(room_states)
        humidities = [s["current_humidity"] for s in room_states.values() if s["current_humidity"] is not None]

        if not temps:
            # No temperature data - default to current mode
            return self.hvac_mode if self.hvac_mode != "auto" else "cool"

        # Calculate average temperature deviation from target
        avg_temp = sum(temps) / len(temps)
        temp_deviation = avg_temp - effective_target
        abs_deviation = abs(temp_deviation)

        # Calculate average humidity if available
        avg_humidity = None
        if humidities:
            avg_humidity = sum(humidities) / len(humidities)
            self._house_avg_humidity = avg_humidity
        else:
            # No valid humidity data - clear the average to prevent stale data
            self._house_avg_humidity = None

        # Determine the optimal mode (before hysteresis)
        optimal_mode = None

        # Priority 1: Temperature needs attention (outside deadband)
        if abs_deviation > self.temperature_deadband:
            if self.hvac_mode == "cool" or (self.hvac_mode == "auto" and temp_deviation > 0):
                optimal_mode = "cool"
                _LOGGER.debug(
                    "Temperature priority: %.1f°C deviation → COOL mode (candidate)",
                    temp_deviation
                )
            elif self.hvac_mode == "heat" or (self.hvac_mode == "auto" and temp_deviation < 0):
                optimal_mode = "heat"
                _LOGGER.debug(
                    "Temperature priority: %.1f°C deviation → HEAT mode (candidate)",
                    temp_deviation
                )
            else:
                # Temperature deviation exists but mode unclear - use fallback
                _LOGGER.warning(
                    "Temperature deviation %.1f°C but unclear HVAC mode (%s), using fallback",
                    temp_deviation, self.hvac_mode
                )
                optimal_mode = self.hvac_mode if self.hvac_mode != "auto" else "cool"

        # Priority 2: Temperature OK, check humidity
        elif avg_humidity is not None:
            humidity_excess = avg_humidity - self.target_humidity

            # High humidity - use dry mode
            if avg_humidity >= self.dry_mode_humidity_threshold or humidity_excess > self.humidity_deadband:
                optimal_mode = "dry"
                _LOGGER.debug(
                    "Humidity control: %.1f%% (target: %.1f%%, threshold: %.1f%%) → DRY mode (candidate)",
                    avg_humidity, self.target_humidity, self.dry_mode_humidity_threshold
                )

        # Priority 3: Both temperature and humidity OK - use fan only for circulation
        if optimal_mode is None:
            optimal_mode = "fan_only"
            _LOGGER.debug(
                "Temperature and humidity within targets (temp: %.1f°C/%.1f°C, humidity: %.1f%%/%.1f%%) → FAN_ONLY mode (candidate)",
                avg_temp, effective_target,
                avg_humidity if avg_humidity else 0, self.target_humidity
            )

        # Apply hysteresis logic to prevent mode thrashing
        current_time = time.time()
        should_change_mode = True

        if self._last_hvac_mode is not None and optimal_mode != self._last_hvac_mode:
            # We want to change mode - check hysteresis
            time_since_last_change = (
                current_time - self._last_mode_change_time
                if self._last_mode_change_time is not None
                else float('inf')
            )

            # CRITICAL: If currently in fan_only and conditions require active mode, switch immediately!
            # Fan_only doesn't control temperature/humidity, so we must exit it when conditions demand action
            if self._last_hvac_mode == "fan_only" and optimal_mode in ["cool", "heat", "dry"]:
                if optimal_mode in ["cool", "heat"]:
                    _LOGGER.info(
                        "Exiting fan_only mode immediately due to temperature deviation %.1f°C (deadband: %.1f°C) - switching to %s",
                        abs_deviation, self.temperature_deadband, optimal_mode
                    )
                else:  # dry mode
                    _LOGGER.info(
                        "Exiting fan_only mode immediately due to high humidity %.1f%% (threshold: %.1f%%) - switching to DRY",
                        avg_humidity if avg_humidity is not None else 0, self.dry_mode_humidity_threshold
                    )
                # Don't apply hysteresis when exiting fan_only - allow immediate switch
            elif time_since_last_change < self.mode_change_hysteresis_time:
                # Within hysteresis period - only change if deviation is severe
                hysteresis_threshold = self.temperature_deadband + self.mode_change_hysteresis_temp

                if abs_deviation < hysteresis_threshold:
                    # Deviation not severe enough to override hysteresis
                    should_change_mode = False
                    _LOGGER.info(
                        "Mode change hysteresis active: keeping %s mode (wanted %s, but only %.1f°C deviation, need %.1f°C to override, %ds since last change)",
                        self._last_hvac_mode, optimal_mode, abs_deviation, hysteresis_threshold,
                        int(time_since_last_change)
                    )
                    optimal_mode = self._last_hvac_mode
                else:
                    _LOGGER.info(
                        "Overriding hysteresis due to severe deviation: %.1f°C (threshold: %.1f°C) - switching to %s",
                        abs_deviation, hysteresis_threshold, optimal_mode
                    )

        # Update mode tracking
        if optimal_mode != self._last_hvac_mode:
            _LOGGER.info("HVAC mode change: %s → %s", self._last_hvac_mode or "unknown", optimal_mode)
            self._last_hvac_mode = optimal_mode
            self._last_mode_change_time = current_time
        elif self._last_hvac_mode is None:
            # First run
            self._last_hvac_mode = optimal_mode
            self._last_mode_change_time = current_time

        # Update mode state flags
        self._dry_mode_active = (optimal_mode == "dry")
        self._fan_only_mode_active = (optimal_mode == "fan_only")

        return optimal_mode

    async def _get_outdoor_temperature(self) -> float | None:
        """Get outdoor temperature from weather entity or outdoor sensor."""
        if self.outdoor_temp_sensor:
            sensor_state = self.hass.states.get(self.outdoor_temp_sensor)
            if sensor_state and sensor_state.state not in ["unknown", "unavailable", "none", None]:
                try:
                    temp = float(sensor_state.state)
                    unit = sensor_state.attributes.get("unit_of_measurement", "°C")
                    if unit in ["°F", "fahrenheit", "F"]:
                        temp = (temp - 32) * 5.0 / 9.0
                    self._outdoor_temperature = temp
                    return temp
                except (ValueError, TypeError) as e:
                    _LOGGER.warning("Could not read outdoor temperature sensor: %s", e)

        if self.weather_entity:
            weather_state = self.hass.states.get(self.weather_entity)
            if weather_state:
                temp = weather_state.attributes.get("temperature")
                if temp is not None:
                    try:
                        temp = float(temp)
                        self._outdoor_temperature = temp
                        return temp
                    except (ValueError, TypeError) as e:
                        _LOGGER.warning("Could not read weather temperature: %s", e)

        return None

    def _calculate_weather_adjusted_target(self, base_target: float, outdoor_temp: float) -> float:
        """Calculate weather-adjusted target temperature."""
        if outdoor_temp > 30:
            adjustment = -0.5 * self.weather_influence_factor
            _LOGGER.debug("Hot weather (%.1f°C) - adjusting target by %.1f°C", outdoor_temp, adjustment)
        elif outdoor_temp > 25:
            adjustment = -0.25 * self.weather_influence_factor
            _LOGGER.debug("Warm weather (%.1f°C) - adjusting target by %.1f°C", outdoor_temp, adjustment)
        elif outdoor_temp < 15:
            adjustment = 0.5 * self.weather_influence_factor
            _LOGGER.debug("Cold weather (%.1f°C) - adjusting target by %.1f°C", outdoor_temp, adjustment)
        elif outdoor_temp < 20:
            adjustment = 0.25 * self.weather_influence_factor
            _LOGGER.debug("Cool weather (%.1f°C) - adjusting target by %.1f°C", outdoor_temp, adjustment)
        else:
            adjustment = 0.0
            _LOGGER.debug("Mild weather (%.1f°C) - no adjustment", outdoor_temp)

        adjusted = base_target + adjustment
        return round(adjusted, 1)

    async def _update_occupancy_state(self) -> None:
        """Update occupancy state for all rooms with occupancy sensors."""
        if not self.enable_occupancy_control or not self.occupancy_sensors:
            return

        current_time = time.time()

        for room_name, sensor_entity in self.occupancy_sensors.items():
            # Get occupancy sensor state
            state = self.hass.states.get(sensor_entity)
            if not state:
                _LOGGER.debug("Occupancy sensor %s not found for room %s", sensor_entity, room_name)
                continue

            is_occupied = state.state in ["on", "home", "occupied", "detected", "motion", "true"]

            # Initialize room occupancy tracking if needed
            if room_name not in self._room_occupancy_state:
                self._room_occupancy_state[room_name] = {
                    "occupied": is_occupied,
                    "last_seen": current_time if is_occupied else None,
                }
                continue

            # Update occupancy state
            room_state = self._room_occupancy_state[room_name]

            if is_occupied:
                # Room is occupied
                room_state["occupied"] = True
                room_state["last_seen"] = current_time
            else:
                # Room shows no occupancy - check vacancy timeout
                if room_state["occupied"]:
                    # Was occupied, now vacant - check timeout
                    last_seen = room_state.get("last_seen", current_time)
                    time_vacant = current_time - last_seen

                    if time_vacant >= self.vacancy_timeout:
                        # Vacancy timeout reached - mark as vacant
                        room_state["occupied"] = False
                        _LOGGER.info(
                            "Room %s marked as vacant after %d seconds of no activity",
                            room_name, int(time_vacant)
                        )

    def _get_room_effective_target(self, room_name: str, base_target: float) -> float:
        """Get effective target temperature for a room considering occupancy.

        For vacant rooms:
        - In cooling mode: increase target by setback amount (less cooling)
        - In heating mode: decrease target by setback amount (less heating)

        Args:
            room_name: Name of the room
            base_target: Base target temperature

        Returns:
            Effective target temperature for the room
        """
        if not self.enable_occupancy_control:
            return base_target

        # Check occupancy state
        room_state = self._room_occupancy_state.get(room_name)
        if not room_state or room_state.get("occupied", True):
            # Room is occupied or no occupancy tracking - use base target
            return base_target

        # Room is vacant - apply setback
        if self.hvac_mode == "cool" or (self.hvac_mode == "auto" and self.target_temperature < 24):
            # Cooling mode - increase target (reduce cooling)
            effective_target = base_target + self.vacant_room_setback
            _LOGGER.debug(
                "Room %s is vacant - applying +%.1f°C setback (cooling mode): %.1f°C → %.1f°C",
                room_name, self.vacant_room_setback, base_target, effective_target
            )
        else:
            # Heating mode - decrease target (reduce heating)
            effective_target = base_target - self.vacant_room_setback
            _LOGGER.debug(
                "Room %s is vacant - applying -%.1f°C setback (heating mode): %.1f°C → %.1f°C",
                room_name, self.vacant_room_setback, base_target, effective_target
            )

        return effective_target

    def _update_temp_history(self, room_states: dict[str, dict[str, Any]]) -> None:
        """Update temperature history for rate-of-change calculations."""
        current_time = time.time()
        for room_name, state in room_states.items():
            temp = state.get("current_temperature")
            if temp is None:
                continue
            if room_name not in self._temp_history:
                self._temp_history[room_name] = []
            self._temp_history[room_name].append((current_time, temp))
            # Keep only last N points
            if len(self._temp_history[room_name]) > self._max_history_points:
                self._temp_history[room_name] = self._temp_history[room_name][-self._max_history_points:]

    def _get_temp_rate_of_change(self, room_name: str) -> float | None:
        """Get temperature rate of change in degrees per minute.

        Positive = temperature rising, Negative = temperature falling.
        Returns None if insufficient data.
        """
        history = self._temp_history.get(room_name, [])
        if len(history) < 3:
            return None

        # Use linear regression over recent points for a more stable estimate
        n = len(history)
        times = [h[0] for h in history]
        temps = [h[1] for h in history]

        # Calculate slope using least squares
        t_mean = sum(times) / n
        temp_mean = sum(temps) / n

        numerator = sum((t - t_mean) * (temp - temp_mean) for t, temp in zip(times, temps))
        denominator = sum((t - t_mean) ** 2 for t in times)

        if denominator == 0:
            return 0.0

        # Slope is degrees per second, convert to degrees per minute
        slope_per_second = numerator / denominator
        return slope_per_second * 60.0

    def _predict_temperature(self, room_name: str, current_temp: float) -> float | None:
        """Predict temperature N minutes in the future based on rate of change.

        Returns predicted temperature or None if insufficient data.
        """
        rate = self._get_temp_rate_of_change(room_name)
        if rate is None:
            return None
        predicted = current_temp + (rate * self.predictive_lookahead_minutes)
        return predicted

    def _apply_predictive_adjustment(self, room_name: str, base_fan_speed: int,
                                      current_temp: float, target_temp: float) -> int:
        """Adjust fan speed based on predicted future temperature.

        If prediction shows the room will overshoot, boost fan speed preemptively.
        If prediction shows the room will undershoot, reduce fan speed.
        """
        predicted_temp = self._predict_temperature(room_name, current_temp)
        if predicted_temp is None:
            return base_fan_speed

        rate = self._get_temp_rate_of_change(room_name)
        predicted_diff = predicted_temp - target_temp

        # In cooling mode: if temp is predicted to rise above target, boost cooling
        # In heating mode: if temp is predicted to fall below target, boost heating
        adjustment = 0
        if self.hvac_mode == "cool":
            if predicted_diff > self.temperature_deadband and rate > 0:
                # Temperature rising toward/past target - boost cooling
                adjustment = int(predicted_diff * self.predictive_boost_factor * 20)
            elif predicted_diff < -self.temperature_deadband and rate < 0:
                # Temperature falling well below target - reduce cooling
                adjustment = -int(abs(predicted_diff) * self.predictive_boost_factor * 15)
        elif self.hvac_mode == "heat":
            if predicted_diff < -self.temperature_deadband and rate < 0:
                # Temperature falling away from target - boost heating
                adjustment = int(abs(predicted_diff) * self.predictive_boost_factor * 20)
            elif predicted_diff > self.temperature_deadband and rate > 0:
                # Temperature rising past target - reduce heating
                adjustment = -int(predicted_diff * self.predictive_boost_factor * 15)

        if adjustment != 0:
            adjusted = max(5, min(100, base_fan_speed + adjustment))
            _LOGGER.debug(
                "Predictive adjustment for %s: rate=%.3f°C/min, predicted=%.1f°C, "
                "base=%d%% → adjusted=%d%% (%+d%%)",
                room_name, rate, predicted_temp,
                base_fan_speed, adjusted, adjustment
            )
            return adjusted

        return base_fan_speed

    def _is_compressor_protected(self) -> bool:
        """Check if compressor protection is currently blocking an AC state change."""
        if not self.enable_compressor_protection:
            return False
        current_time = time.time()
        if self._ac_last_turned_off is not None:
            if (current_time - self._ac_last_turned_off) < self.compressor_min_off_time:
                return True
        if self._ac_last_turned_on is not None:
            if (current_time - self._ac_last_turned_on) < self.compressor_min_on_time:
                return True
        return False

    @staticmethod
    def _valid_temps(room_states: dict[str, dict[str, Any]]) -> list[float]:
        """Extract valid (non-None) temperatures from room states."""
        return [s["current_temperature"] for s in room_states.values() if s["current_temperature"] is not None]

    async def async_optimize(self) -> dict[str, Any]:
        """Run optimization cycle with error handling."""
        try:
            return await self._async_optimize_impl()
        except Exception as e:
            _LOGGER.error("Unexpected error during optimization: %s", e, exc_info=True)
            self._last_error = f"Optimization Error: {e}"
            self._error_count += 1

            # Return safe default state
            return {
                "room_states": {},
                "recommendations": {},
                "optimization_response_text": None,
                "main_climate_state": None,
                "main_fan_speed": None,
                "main_ac_running": False,
                "needs_ac": False,
                "last_error": self._last_error,
                "error_count": self._error_count,
            }

    async def _async_optimize_impl(self) -> dict[str, Any]:
        """Implementation of optimization cycle."""
        # Check for manual override - skip optimization if enabled
        if getattr(self, 'manual_override_enabled', False):
            _LOGGER.debug("Manual override active - skipping optimization cycle")
            return {
                "room_states": {},
                "recommendations": {},
                "optimization_response_text": "Manual override active - automatic optimization disabled",
                "main_climate_state": None,
                "main_fan_speed": None,
                "main_ac_running": False,
                "needs_ac": False,
                "manual_override": True,
            }

        # Start performance tracking
        import time
        cycle_start = time.time()

        active_schedule = None
        effective_target = self.target_temperature

        if self.enable_scheduling:
            active_schedule = self._get_active_schedule()
            if active_schedule:
                schedule_temp = active_schedule.get("schedule_target_temp")
                if schedule_temp is not None:
                    effective_target = float(schedule_temp)
                    _LOGGER.info(
                        "Schedule '%s' active - using target temperature: %.1f°C",
                        active_schedule.get("schedule_name", "Unnamed"),
                        effective_target
                    )
                self._current_schedule = active_schedule
            else:
                self._current_schedule = None

        outdoor_temp = None
        weather_adjustment = 0.0
        if self.enable_weather_adjustment:
            outdoor_temp = await self._get_outdoor_temperature()
            if outdoor_temp is not None:
                adjusted_target = self._calculate_weather_adjusted_target(effective_target, outdoor_temp)
                weather_adjustment = adjusted_target - effective_target
                effective_target = adjusted_target
                _LOGGER.info(
                    "Weather adjustment: outdoor %.1f°C, adjustment %.1f°C, new target %.1f°C",
                    outdoor_temp,
                    weather_adjustment,
                    effective_target
                )

        # Update occupancy state before collecting room states
        await self._update_occupancy_state()

        room_states = await self._collect_room_states(effective_target)

        # Update temperature history for predictive control
        if self.enable_predictive_control:
            self._update_temp_history(room_states)

        main_climate_state = None
        main_ac_running = False
        if self.main_climate_entity:
            climate_state = self.hass.states.get(self.main_climate_entity)
            if climate_state:
                main_climate_state = {
                    "state": climate_state.state,
                    "temperature": climate_state.attributes.get("temperature"),
                    "current_temperature": climate_state.attributes.get("current_temperature"),
                    "hvac_mode": climate_state.attributes.get("hvac_mode"),
                    "hvac_action": climate_state.attributes.get("hvac_action"),
                }
                hvac_action = climate_state.attributes.get("hvac_action")
                # Check both hvac_mode attribute and state (some entities use state as hvac_mode)
                hvac_mode = climate_state.attributes.get("hvac_mode") or climate_state.state
                main_ac_running = (
                    hvac_action in ["cooling", "heating", "drying", "fan"]  # Include more actions
                    or (hvac_mode and hvac_mode not in ["off", "unavailable"])
                )

        needs_ac = await self._check_if_ac_needed(room_states, main_ac_running)

        # Determine optimal HVAC mode (cool/heat/dry/fan_only)
        optimal_hvac_mode = self._determine_optimal_hvac_mode(room_states, effective_target)

        if self.auto_control_main_ac and self.main_climate_entity:
            await self._control_main_ac(needs_ac, main_climate_state, optimal_hvac_mode)
        elif self.enable_humidity_control and self.main_climate_entity and main_ac_running:
            # Even without auto AC control, we can still switch modes if AC is already on
            await self._set_hvac_mode(optimal_hvac_mode, main_climate_state)

        valid_temps = [
            state["current_temperature"]
            for state in room_states.values()
            if state["current_temperature"] is not None
        ]

        if not valid_temps:
            time_since_startup = time.time() - self._startup_time if self._startup_time else float('inf')
            in_startup_delay = time_since_startup < self._startup_delay_seconds

            if in_startup_delay:
                _LOGGER.info(
                    "No valid temperature readings during startup delay (%.0fs / %ds)",
                    time_since_startup,
                    self._startup_delay_seconds,
                )
            else:
                _LOGGER.warning("No valid temperature readings available - skipping optimization")
                await self._send_notification(
                    "No Temperature Data",
                    "No valid temperature readings from sensors. Check sensor availability."
                )

            return {
                "room_states": room_states,
                "recommendations": {},
                "optimization_response_text": None,
                "main_climate_state": main_climate_state,
                "main_fan_speed": None,
                "main_ac_running": main_ac_running,
                "needs_ac": False,
                "last_error": "No valid temperature data" if not in_startup_delay else None,
                "error_count": self._error_count if not in_startup_delay else 0,
            }

        all_rooms_stable = self._check_rooms_stable(room_states)
        current_time = time.time()
        should_run_optimization = (
            self._last_optimization is None or
            (current_time - self._last_optimization) >= self._optimization_interval
        )

        if all_rooms_stable and self._last_recommendations:
            should_run_optimization = False
            _LOGGER.debug(
                "Skipping optimization - all rooms stable within deadband (±%.1f°C)",
                self.temperature_deadband
            )

        if self._last_optimization is not None:
            time_since_last = current_time - self._last_optimization
            _LOGGER.debug(
                "Optimization check: interval=%.0fs, time_since_last=%.0fs, should_run=%s",
                self._optimization_interval,
                time_since_last,
                should_run_optimization
            )

        recommendations = self._last_recommendations if self._last_recommendations else {}
        main_fan_speed = self._last_main_fan_speed

        if not self.main_climate_entity or main_ac_running:
            if should_run_optimization:
                _LOGGER.info(
                    "Running logic-based optimization (first run: %s, %.0fs since last)",
                    self._last_optimization is None,
                    current_time - self._last_optimization if self._last_optimization else 0
                )

                recommendations = self._calculate_recommendations(room_states)
                await self._apply_recommendations(recommendations)

                if self.main_fan_entity:
                    main_fan_speed = await self._determine_and_set_main_fan_speed(room_states)

                if recommendations:
                    self._last_error = None
                    self._error_count = 0

                self._total_optimizations_run += 1
                self._last_recommendations = recommendations
                self._last_main_fan_speed = main_fan_speed
                self._last_optimization = current_time
            else:
                time_until_next = self._optimization_interval - (current_time - self._last_optimization)
                _LOGGER.debug(
                    "Data collection only (next optimization in %.0fs)",
                    time_until_next
                )
        else:
            _LOGGER.debug("Main AC is not running - skipping optimization")

        # End performance tracking
        cycle_end = time.time()
        cycle_time_ms = (cycle_end - cycle_start) * 1000
        self._last_cycle_time_ms = cycle_time_ms

        # Calculate error rate (errors per hour)
        uptime_hours = (cycle_end - self._startup_time) / 3600 if self._startup_time else 1
        error_rate = self._error_count / uptime_hours if uptime_hours > 0 else 0

        # Track performance data for adaptive learning
        if self.learning_manager and self.learning_manager.enabled:
            # Calculate actual wall-clock interval between cycles (NOT processing time)
            actual_interval = 0.0
            if self._last_cycle_timestamp is not None:
                actual_interval = cycle_end - self._last_cycle_timestamp
            self._last_cycle_timestamp = cycle_end

            for room_name, state in room_states.items():
                current_temp = state.get("current_temperature")
                if current_temp is None:
                    continue

                # Get previous temperature for this room
                previous_temp = self._last_room_temps.get(room_name)

                # Get fan speed applied
                fan_speed = recommendations.get(room_name, 50)

                # Track this cycle - use actual wall-clock interval, not processing time
                # On first cycle (no previous timestamp), use optimization_interval as estimate
                cycle_interval = actual_interval if actual_interval > 0 else self._optimization_interval
                self.learning_manager.tracker.track_cycle(
                    room_name=room_name,
                    temp_before=previous_temp if previous_temp else current_temp,
                    temp_after=current_temp,
                    fan_speed=fan_speed,
                    target_temp=state.get("target_temperature", self.target_temperature),
                    cycle_duration=cycle_interval,
                )

                # Store current temp for next cycle
                self._last_room_temps[room_name] = current_temp

            # Periodically update learning profiles from collected data
            current_time = time.time()
            should_update_learning = (
                self._last_learning_update is None
                or (current_time - self._last_learning_update) >= self._learning_update_interval
            )

            if should_update_learning:
                _LOGGER.debug("Updating learning profiles from collected data...")
                updated_rooms = await self.learning_manager.async_update_profiles()
                if updated_rooms:
                    _LOGGER.info(
                        "Learning profiles updated for %d rooms: %s",
                        len(updated_rooms),
                        ", ".join(updated_rooms)
                    )
                else:
                    _LOGGER.debug("Learning profiles update - insufficient data for any rooms yet (need 50+ data points per room)")
                self._last_learning_update = current_time

        return {
            "room_states": room_states,
            "recommendations": recommendations,
            "optimization_response_text": self._last_optimization_response,
            "main_climate_state": main_climate_state,
            "main_fan_speed": main_fan_speed,
            "main_ac_running": main_ac_running,
            "needs_ac": needs_ac,
            "last_error": self._last_error,
            "error_count": self._error_count,
            "active_schedule": active_schedule,
            "effective_target_temperature": effective_target,
            "base_target_temperature": self.target_temperature,
            "weather_adjustment": weather_adjustment,
            "outdoor_temperature": outdoor_temp,
            # Performance metrics
            "optimization_cycle_time_ms": cycle_time_ms,
            "total_optimizations_run": self._total_optimizations_run,
            "error_rate_per_hour": round(error_rate, 2),
            # Compressor protection state
            "compressor_protection_active": self._is_compressor_protected(),
        }

    async def _collect_room_states(self, target_temperature: float | None = None) -> dict[str, dict[str, Any]]:
        """Collect current temperature, humidity, and cover state for all rooms."""
        room_states = {}
        effective_target = target_temperature if target_temperature is not None else self.target_temperature

        for room in self.room_configs:
            room_name = room["room_name"]
            temp_sensor = room["temperature_sensor"]
            cover_entity = room["cover_entity"]
            humidity_sensor = room.get("humidity_sensor")  # Optional
            room_target_temp = room.get("room_target_temperature")  # Per-room override

            temp_state = self.hass.states.get(temp_sensor)
            current_temp = None

            if temp_state:
                # Use validation method for temperature
                current_temp = self._validate_sensor_temperature(temp_state.state, room_name)

                if current_temp is not None:
                    # Handle unit conversion
                    unit = temp_state.attributes.get("unit_of_measurement", "°C")
                    if unit in ["°F", "fahrenheit", "F"]:
                        current_temp = (current_temp - 32) * 5.0 / 9.0
                        _LOGGER.debug("Converted temperature for %s from F to C: %.1f°C", room_name, current_temp)
                        # Re-validate after conversion
                        current_temp = self._validate_sensor_temperature(current_temp, room_name)

            # Collect humidity if sensor is configured
            current_humidity = None
            if humidity_sensor and self.enable_humidity_control:
                humidity_state = self.hass.states.get(humidity_sensor)
                if humidity_state and humidity_state.state not in ["unknown", "unavailable", "none", None]:
                    try:
                        current_humidity = float(humidity_state.state)
                        # Validate humidity is in realistic range (0-100%)
                        if not (0 <= current_humidity <= 100):
                            _LOGGER.warning(
                                "Humidity reading for %s (%.1f%%) outside valid range (0-100%%), ignoring",
                                room_name, current_humidity
                            )
                            current_humidity = None
                    except (ValueError, TypeError) as e:
                        _LOGGER.warning("Could not parse humidity for %s: %s", room_name, e)
                        current_humidity = None

            cover_state = self.hass.states.get(cover_entity)
            cover_position = 100  # Default to fully open

            if cover_state:
                pos = cover_state.attributes.get("current_position")
                if pos not in ["unknown", "unavailable", "none", None]:
                    try:
                        cover_position = int(float(pos))
                        # Validate cover position is 0-100
                        if not (0 <= cover_position <= 100):
                            _LOGGER.warning(
                                "Cover position for %s (%d%%) outside valid range (0-100%%), clamping",
                                room_name, cover_position
                            )
                            cover_position = max(0, min(100, cover_position))
                    except (ValueError, TypeError) as e:
                        _LOGGER.warning("Could not parse cover position for %s: %s, using default", room_name, e)
                        cover_position = 100

            # Use per-room target if configured, otherwise fall back to global effective target
            room_effective_target = float(room_target_temp) if room_target_temp is not None else effective_target

            room_states[room_name] = {
                "current_temperature": current_temp,
                "current_humidity": current_humidity,
                "target_temperature": room_effective_target,
                "cover_position": cover_position,
                "temperature_sensor": temp_sensor,
                "humidity_sensor": humidity_sensor,
                "cover_entity": cover_entity,
            }

        return room_states

    def _calculate_recommendations(self, room_states: dict[str, dict[str, Any]]) -> dict[str, int | float]:
        """Calculate logic-based recommendations for cover positions and AC temperature."""
        recommendations = {}

        base_effective_target = self.target_temperature
        if room_states:
            first_room = next(iter(room_states.values()))
            if 'target_temperature' in first_room and first_room['target_temperature'] is not None:
                base_effective_target = first_room['target_temperature']

        for room_name, state in room_states.items():
            current_temp = state["current_temperature"]
            if current_temp is None:
                continue

            # Use per-room target from room_states (already includes per-room override)
            room_base_target = state.get("target_temperature", base_effective_target)
            # Then apply occupancy setback on top
            room_effective_target = self._get_room_effective_target(room_name, room_base_target)

            temp_diff = current_temp - room_effective_target
            abs_temp_diff = abs(temp_diff)

            # Calculate raw fan speed
            raw_fan_speed = self._calculate_fan_speed(temp_diff, abs_temp_diff)

            # Apply smoothing to prevent oscillation
            fan_speed = self._smooth_fan_speed(room_name, raw_fan_speed)

            # Apply predictive adjustment if enabled
            if self.enable_predictive_control:
                fan_speed = self._apply_predictive_adjustment(
                    room_name, fan_speed, current_temp, room_effective_target
                )

            recommendations[room_name] = fan_speed

            _LOGGER.debug(
                "Room %s: temp=%.1f°C, target=%.1f°C, diff=%+.1f°C → fan=%d%%",
                room_name,
                current_temp,
                room_effective_target,
                temp_diff,
                fan_speed
            )

        # Apply inter-room balancing if enabled
        if self.enable_room_balancing and len(recommendations) > 1:
            recommendations = self._apply_room_balancing(recommendations, room_states, base_effective_target)

        if self.auto_control_ac_temperature and self.main_climate_entity:
            ac_temp = self._calculate_ac_temperature(room_states, base_effective_target)
            recommendations["ac_temperature"] = ac_temp

        self._last_optimization_response = self._build_optimization_summary(recommendations, room_states)
        return recommendations

    def _smooth_fan_speed(self, room_name: str, new_speed: int, smoothing_threshold: int = 10) -> int:
        """Smooth fan speed transitions to prevent rapid oscillation.

        Uses learned smoothing parameters if adaptive learning is active.
        """
        # Get learned smoothing parameters if available
        if self.learning_manager and self.learning_manager.should_apply_learning(room_name):
            profile = self.learning_manager.get_profile(room_name)
            smoothing_factor = profile.optimal_smoothing_factor
            smoothing_threshold = profile.optimal_smoothing_threshold
            _LOGGER.debug(
                "Using learned smoothing for %s: factor=%.2f, threshold=%d",
                room_name, smoothing_factor, smoothing_threshold
            )
        else:
            # Use default values
            smoothing_factor = 0.7  # 70% new, 30% old
            smoothing_threshold = 10  # Default threshold for smoothing

        if room_name not in self._last_fan_speeds:
            self._last_fan_speeds[room_name] = new_speed
            return new_speed

        last_speed = self._last_fan_speeds[room_name]
        speed_diff = abs(new_speed - last_speed)

        # If change is small (within threshold), dampen it
        if speed_diff <= smoothing_threshold:
            # Use weighted average with learned factor
            smoothed = int(smoothing_factor * new_speed + (1 - smoothing_factor) * last_speed)
            _LOGGER.debug(
                "Smoothing fan speed for %s: %d%% -> %d%% (dampened to %d%%)",
                room_name, last_speed, new_speed, smoothed
            )
            self._last_fan_speeds[room_name] = smoothed
            return smoothed

        # Large change - apply immediately
        self._last_fan_speeds[room_name] = new_speed
        return new_speed

    def _calculate_fan_speed(self, temp_diff: float, abs_temp_diff: float) -> int:
        """Calculate fan speed based on temperature difference and HVAC mode.

        Uses granular bands for smooth, responsive temperature control.
        """
        # Within deadband - maintain with moderate circulation
        if abs_temp_diff <= self.temperature_deadband:
            return 50  # Baseline circulation when at target

        if self.hvac_mode == "cool":
            if temp_diff > 0:
                # Room is too hot - needs cooling (more granular bands)
                if abs_temp_diff >= 4.0:
                    return 100  # Extreme heat - maximum cooling
                elif abs_temp_diff >= 3.0:
                    return 90   # Very hot - aggressive cooling
                elif abs_temp_diff >= 2.0:
                    return 75   # Hot - strong cooling
                elif abs_temp_diff >= 1.5:
                    return 65   # Moderately hot - good cooling
                elif abs_temp_diff >= 1.0:
                    return 60   # Slightly hot - moderate cooling
                else:
                    return 55   # Just outside deadband - slightly above baseline
            else:
                # Room is too cold - overshot target, reduce cooling progressively
                if abs_temp_diff >= self.overshoot_tier3_threshold:  # 3°C+
                    return 5    # Severe overshoot - near shutdown
                elif abs_temp_diff >= self.overshoot_tier2_threshold:  # 2-3°C
                    return 12   # High overshoot - minimal airflow
                elif abs_temp_diff >= self.overshoot_tier1_threshold:  # 1-2°C
                    return 22   # Medium overshoot - reduced cooling
                elif abs_temp_diff >= 0.7:
                    return 30   # Small overshoot - gentle reduction
                else:
                    return 35   # Very small overshoot - slight reduction

        elif self.hvac_mode == "heat":
            if temp_diff < 0:
                # Room is too cold - needs heating (more granular bands)
                if abs_temp_diff >= 4.0:
                    return 100  # Extreme cold - maximum heating
                elif abs_temp_diff >= 3.0:
                    return 90   # Very cold - aggressive heating
                elif abs_temp_diff >= 2.0:
                    return 75   # Cold - strong heating
                elif abs_temp_diff >= 1.5:
                    return 65   # Moderately cold - good heating
                elif abs_temp_diff >= 1.0:
                    return 60   # Slightly cold - moderate heating
                else:
                    return 55   # Just outside deadband - slightly above baseline
            else:
                # Room is too warm - overshot target, reduce heating progressively
                if abs_temp_diff >= self.overshoot_tier3_threshold:  # 3°C+
                    return 5    # Severe overshoot - near shutdown
                elif abs_temp_diff >= self.overshoot_tier2_threshold:  # 2-3°C
                    return 12   # High overshoot - minimal airflow
                elif abs_temp_diff >= self.overshoot_tier1_threshold:  # 1-2°C
                    return 22   # Medium overshoot - reduced heating
                elif abs_temp_diff >= 0.7:
                    return 30   # Small overshoot - gentle reduction
                else:
                    return 35   # Very small overshoot - slight reduction
        else:
            # Auto mode - use magnitude-based approach with granular control
            if abs_temp_diff >= 4.0:
                return 100
            elif abs_temp_diff >= 3.0:
                return 85
            elif abs_temp_diff >= 2.0:
                return 70
            elif abs_temp_diff >= 1.5:
                return 60
            elif abs_temp_diff >= 1.0:
                return 50
            elif abs_temp_diff >= 0.7:
                return 42
            else:
                return 35

    def _apply_room_balancing(
        self,
        recommendations: dict[str, int],
        room_states: dict[str, dict[str, Any]],
        effective_target: float
    ) -> dict[str, int]:
        """Apply inter-room temperature balancing adjustments.

        When rooms are unbalanced but house average is near target, this applies
        adjustments to equalize temperatures across all rooms. Works for both
        heating and cooling modes.

        Args:
            recommendations: Initial fan speed recommendations per room
            room_states: Current state of all rooms
            effective_target: Target temperature

        Returns:
            Adjusted recommendations with balancing applied
        """
        # Get all valid temperatures
        temps = self._valid_temps(room_states)
        if len(temps) < 2:
            self._balancing_active = False
            return recommendations  # Need at least 2 rooms to balance

        # Calculate house statistics
        avg_temp = statistics.mean(temps)
        temp_variance = statistics.stdev(temps)  # Safe now - len(temps) >= 2

        # Store for diagnostics
        self._house_avg_temp = avg_temp
        self._house_temp_variance = temp_variance

        # Check if balancing is needed
        house_deviation_from_target = abs(avg_temp - effective_target)
        needs_balancing = (
            temp_variance > self.target_room_variance and  # Rooms are unbalanced
            house_deviation_from_target < 1.0  # House average is reasonably close to target
        )

        if not needs_balancing:
            self._balancing_active = False
            return recommendations

        self._balancing_active = True
        _LOGGER.debug(
            "Applying room balancing: avg=%.1f°C, variance=%.2f°C, target_variance=%.2f°C",
            avg_temp, temp_variance, self.target_room_variance
        )

        # Apply balancing adjustments
        balanced_recommendations = {}
        for room_name, base_fan_speed in recommendations.items():
            state = room_states.get(room_name)
            if not state or state["current_temperature"] is None:
                balanced_recommendations[room_name] = base_fan_speed
                continue

            room_temp = state["current_temperature"]
            deviation_from_avg = room_temp - avg_temp

            # Calculate balancing adjustment
            # Positive deviation = room is hotter than house average
            # Negative deviation = room is cooler than house average
            balancing_bias = deviation_from_avg * self.balancing_aggressiveness * 100

            # Flip the bias sign for heating mode to ensure correct behavior:
            # Cooling mode (no flip):
            #   - Hot room (+deviation) → +bias → MORE airflow → MORE cooling ✓
            #   - Cold room (-deviation) → -bias → LESS airflow → LESS cooling (warms up) ✓
            # Heating mode (flip bias):
            #   - Hot room (+deviation) → -bias (after flip) → LESS airflow → LESS heating ✓
            #   - Cold room (-deviation) → +bias (after flip) → MORE airflow → MORE heating ✓
            if self.hvac_mode == "heat":
                balancing_bias = -balancing_bias

            # Apply adjustment
            adjusted_speed = base_fan_speed + balancing_bias

            # Enforce minimum airflow and bounds
            final_speed = max(self.min_airflow_percent, min(100, int(adjusted_speed)))

            balanced_recommendations[room_name] = final_speed

            _LOGGER.debug(
                "  %s: %.1f°C (avg %+.1f°C) → base=%d%% + bias=%+.1f%% = %d%% (final=%d%%)",
                room_name, room_temp, deviation_from_avg,
                base_fan_speed, balancing_bias, int(adjusted_speed), final_speed
            )

        return balanced_recommendations

    def _calculate_ac_temperature(self, room_states: dict[str, dict[str, Any]], effective_target: float) -> float:
        """Calculate optimal AC temperature setpoint."""
        temps = self._valid_temps(room_states)
        if not temps:
            return effective_target

        avg_temp = sum(temps) / len(temps)
        temp_diff = avg_temp - effective_target

        if self.hvac_mode == "cool":
            if temp_diff >= 2.0:
                return 19.0
            elif temp_diff >= 0.5:
                return 21.0
            else:
                return 23.0
        elif self.hvac_mode == "heat":
            if temp_diff <= -2.0:
                return 25.0
            elif temp_diff <= -0.5:
                return 23.0
            else:
                return 21.0
        else:
            return effective_target

    def _build_optimization_summary(self, recommendations: dict[str, int | float], room_states: dict[str, dict[str, Any]]) -> str:
        """Build a human-readable summary."""
        summary_lines = ["Logic-based optimization decisions:"]
        
        for room_name, fan_speed in recommendations.items():
            if room_name == "ac_temperature":
                summary_lines.append(f"AC Temperature: {fan_speed}°C")
            else:
                state = room_states.get(room_name)
                if state and state["current_temperature"] is not None:
                    temp = state["current_temperature"]
                    target = state["target_temperature"]
                    diff = temp - target
                    summary_lines.append(
                        f"{room_name}: {temp:.1f}°C (target {target:.1f}°C, {diff:+.1f}°C) → {fan_speed}%"
                    )
        
        return "\n".join(summary_lines)

    async def _apply_recommendations(self, recommendations: dict[str, int | float]) -> None:
        """Apply the recommended cover positions and AC temperature."""
        # Check manual override before issuing any commands
        if getattr(self, 'manual_override_enabled', False):
            _LOGGER.debug("Manual override active - skipping apply_recommendations")
            return

        if "ac_temperature" in recommendations and self.auto_control_ac_temperature and self.main_climate_entity:
            await self._set_ac_temperature(recommendations["ac_temperature"])

        for room_name, position in recommendations.items():
            if room_name == "ac_temperature":
                continue

            room_override = self.room_overrides.get(f"{room_name}_enabled")
            if room_override is False:
                _LOGGER.debug("Skipping %s - control disabled via override", room_name)
                continue

            room_config = next((r for r in self.room_configs if r["room_name"] == room_name), None)
            if not room_config:
                continue

            cover_entity = room_config["cover_entity"]
            cover_state = self.hass.states.get(cover_entity)
            
            if not cover_state:
                _LOGGER.warning("Cover entity %s for room %s not found", cover_entity, room_name)
                continue

            if cover_state.state in ["unavailable", "unknown"]:
                _LOGGER.warning("Cover entity %s for room %s is %s", cover_entity, room_name, cover_state.state)
                continue

            # Use retry logic for cover position changes
            success = await self._retry_service_call(
                "cover",
                "set_cover_position",
                {"entity_id": cover_entity, "position": position},
                entity_name=f"{room_name} ({cover_entity})"
            )

            if success:
                _LOGGER.debug("Set cover position for %s (%s) to %d%%", room_name, cover_entity, position)
            else:
                await self._send_notification(
                    "Cover Control Error",
                    f"Failed to set fan speed for {room_name} after {MAX_RETRIES} attempts"
                )

    async def _determine_and_set_main_fan_speed(self, room_states: dict[str, dict[str, Any]]) -> str:
        """Determine and set the main aircon fan speed."""
        # Check manual override before issuing commands
        if getattr(self, 'manual_override_enabled', False):
            _LOGGER.debug("Manual override active - skipping main fan speed control")
            return self._last_main_fan_speed or "medium"

        effective_target = self.target_temperature
        if room_states:
            first_room = next(iter(room_states.values()))
            if 'target_temperature' in first_room and first_room['target_temperature'] is not None:
                effective_target = first_room['target_temperature']

        temps = self._valid_temps(room_states)
        if not temps:
            return "medium"

        avg_temp = sum(temps) / len(temps)
        max_temp = max(temps)
        min_temp = min(temps)
        temp_variance = max_temp - min_temp
        avg_temp_diff = avg_temp - effective_target
        avg_deviation = abs(avg_temp_diff)
        max_temp_diff = max(temp - effective_target for temp in temps)
        min_temp_diff = min(temp - effective_target for temp in temps)

        fan_speed = "medium"

        if temp_variance <= 1.0 and avg_deviation <= 0.5:
            fan_speed = "low"
            _LOGGER.debug("Main fan -> LOW: Maintaining (variance: %.1f°C)", temp_variance)
        elif self.hvac_mode == "cool":
            if avg_temp_diff >= self.main_fan_high_threshold or (max_temp_diff >= 3.0 and temp_variance >= 2.0):
                fan_speed = "high"
                _LOGGER.debug("Main fan -> HIGH: Aggressive cooling (avg: +%.1f°C)", avg_temp_diff)
            elif avg_temp_diff <= -0.5:
                # Only set LOW when well below target (overcooled)
                fan_speed = "low"
                _LOGGER.debug("Main fan -> LOW: Well below target in cool mode (avg: %.1f°C)", avg_temp_diff)
            else:
                # Default to MEDIUM for moderate cooling needs
                fan_speed = "medium"
        elif self.hvac_mode == "heat":
            if avg_temp_diff <= -self.main_fan_high_threshold or (min_temp_diff <= -3.0 and temp_variance >= 2.0):
                fan_speed = "high"
                _LOGGER.debug("Main fan -> HIGH: Aggressive heating (avg: %.1f°C)", avg_temp_diff)
            elif avg_temp_diff >= 0.5:
                # Only set LOW when well above target (overheated)
                fan_speed = "low"
                _LOGGER.debug("Main fan -> LOW: Well above target in heat mode (avg: %.1f°C)", avg_temp_diff)
            else:
                # Default to MEDIUM for moderate heating needs
                fan_speed = "medium"
        else:
            if avg_deviation >= 3.0 or temp_variance >= 3.0:
                fan_speed = "high"
            else:
                fan_speed = "medium"

        fan_state = self.hass.states.get(self.main_fan_entity)
        if not fan_state:
            _LOGGER.warning("Main fan entity %s not found", self.main_fan_entity)
            return fan_speed

        if fan_state.state in ["unavailable", "unknown"]:
            _LOGGER.warning("Main fan entity %s is %s", self.main_fan_entity, fan_state.state)
            return fan_speed

        # Use retry logic for fan speed changes
        if self.main_fan_entity.startswith("climate."):
            success = await self._retry_service_call(
                "climate",
                "set_fan_mode",
                {"entity_id": self.main_fan_entity, "fan_mode": fan_speed},
                entity_name=f"Main Fan ({self.main_fan_entity})"
            )
        else:
            success = await self._retry_service_call(
                "fan",
                "set_preset_mode",
                {"entity_id": self.main_fan_entity, "preset_mode": fan_speed},
                entity_name=f"Main Fan ({self.main_fan_entity})"
            )

        if success:
            _LOGGER.debug("Set main fan (%s) to %s", self.main_fan_entity, fan_speed)
        else:
            await self._send_notification(
                "Main Fan Error",
                f"Failed to set main fan speed after {MAX_RETRIES} attempts"
            )

        return fan_speed

    def _check_rooms_stable(self, room_states: dict[str, dict[str, Any]]) -> bool:
        """Check if all rooms are stable."""
        if not room_states:
            return False

        for room_name, state in room_states.items():
            current_temp = state.get("current_temperature")
            target_temp = state.get("target_temperature")

            if current_temp is None or target_temp is None:
                return False

            temp_diff = abs(current_temp - target_temp)
            if temp_diff > self.temperature_deadband:
                return False

        return True

    async def _check_if_ac_needed(self, room_states: dict[str, dict[str, Any]], ac_currently_on: bool) -> bool:
        """Check if AC is needed with hysteresis."""
        effective_target = self.target_temperature
        if room_states:
            first_room = next(iter(room_states.values()))
            if 'target_temperature' in first_room and first_room['target_temperature'] is not None:
                effective_target = first_room['target_temperature']

        temps = self._valid_temps(room_states)
        if not temps:
            return False

        avg_temp = sum(temps) / len(temps)
        temp_diff = avg_temp - effective_target

        if self.hvac_mode == "cool":
            if ac_currently_on:
                max_temp = max(temps)
                turn_off = (temp_diff <= -self.ac_turn_off_threshold and max_temp <= effective_target)
                if turn_off:
                    _LOGGER.info("AC turn OFF: avg=%.1f°C (%.1f°C below)", avg_temp, abs(temp_diff))
                return not turn_off
            else:
                turn_on = temp_diff >= self.ac_turn_on_threshold
                if turn_on:
                    _LOGGER.info("AC turn ON: avg=%.1f°C (+%.1f°C above)", avg_temp, temp_diff)
                return turn_on

        elif self.hvac_mode == "heat":
            if ac_currently_on:
                min_temp = min(temps)
                turn_off = (temp_diff >= self.ac_turn_off_threshold and min_temp >= effective_target)
                if turn_off:
                    _LOGGER.info("AC turn OFF: avg=%.1f°C (+%.1f°C above)", avg_temp, temp_diff)
                return not turn_off
            else:
                turn_on = temp_diff <= -self.ac_turn_on_threshold
                if turn_on:
                    _LOGGER.info("AC turn ON: avg=%.1f°C (%.1f°C below)", avg_temp, abs(temp_diff))
                return turn_on
        else:
            return abs(temp_diff) > self.temperature_deadband

    async def _set_hvac_mode(self, optimal_mode: str, main_climate_state: dict[str, Any] | None) -> None:
        """Set the HVAC mode on the main climate entity.

        Args:
            optimal_mode: Desired mode (cool/heat/dry/fan_only)
            main_climate_state: Current climate entity state
        """
        if not main_climate_state or not self.main_climate_entity:
            return

        current_mode = main_climate_state.get("hvac_mode")

        # Don't change if already in the desired mode
        if current_mode == optimal_mode:
            return

        # Get actual climate entity state to check available modes
        climate_entity = self.hass.states.get(self.main_climate_entity)
        if not climate_entity:
            _LOGGER.warning("Climate entity %s not found", self.main_climate_entity)
            return

        available_modes = climate_entity.attributes.get("hvac_modes", [])
        if optimal_mode not in available_modes:
            _LOGGER.debug(
                "Climate entity doesn't support %s mode (available: %s), using closest alternative",
                optimal_mode, available_modes
            )
            # Fall back to appropriate mode
            if optimal_mode == "dry" and "cool" in available_modes:
                _LOGGER.debug("Dry mode not supported, using cool mode as fallback")
                optimal_mode = "cool"  # Use cool mode if dry not available
            elif optimal_mode == "fan_only" and "fan" in available_modes:
                _LOGGER.debug("Fan-only mode not found, using 'fan' mode instead")
                optimal_mode = "fan"  # Some devices use "fan" instead of "fan_only"
            elif optimal_mode == "fan_only" and "cool" in available_modes:
                _LOGGER.debug("Fan-only mode not supported by climate entity, maintaining current mode for energy efficiency")
                return  # Don't switch if fan_only not available - keep current mode
            else:
                _LOGGER.warning("HVAC mode %s not supported by climate entity (available: %s), no change made",
                              optimal_mode, available_modes)
                return  # Mode not supported, don't change

        _LOGGER.info(
            "Switching HVAC mode: %s → %s",
            current_mode, optimal_mode
        )

        success = await self._retry_service_call(
            "climate",
            "set_hvac_mode",
            {"entity_id": self.main_climate_entity, "hvac_mode": optimal_mode},
            entity_name=f"Main AC Mode ({self.main_climate_entity})"
        )

        if success and optimal_mode == "dry":
            await self._send_notification(
                "AC Mode Changed",
                f"Switched to DRY mode for dehumidification (humidity: {self._house_avg_humidity:.1f}%)"
            )
        elif success and optimal_mode == "fan_only":
            await self._send_notification(
                "AC Mode Changed",
                "Switched to FAN ONLY mode for energy-efficient circulation"
            )

    async def _control_main_ac(self, needs_ac: bool, main_climate_state: dict[str, Any] | None, optimal_mode: str = "cool") -> None:
        """Control the main AC on/off and mode.

        Args:
            needs_ac: Whether AC is needed
            main_climate_state: Current climate entity state
            optimal_mode: Optimal HVAC mode based on temp/humidity
        """
        if not main_climate_state:
            return

        # Check manual override before issuing commands
        if getattr(self, 'manual_override_enabled', False):
            _LOGGER.debug("Manual override active - skipping AC control")
            return

        current_mode = main_climate_state.get("hvac_mode")

        # Compressor protection: enforce minimum on/off times
        if self.enable_compressor_protection:
            current_time = time.time()

            if needs_ac and current_mode == "off":
                # Want to turn ON - check minimum off-time
                if self._ac_last_turned_off is not None:
                    off_duration = current_time - self._ac_last_turned_off
                    if off_duration < self.compressor_min_off_time:
                        remaining = self.compressor_min_off_time - off_duration
                        _LOGGER.info(
                            "Compressor protection: delaying AC turn-on (%.0fs remaining of %.0fs min off-time)",
                            remaining, self.compressor_min_off_time
                        )
                        return

            elif not needs_ac and current_mode and current_mode != "off":
                # Want to turn OFF - check minimum on-time
                if self._ac_last_turned_on is not None:
                    on_duration = current_time - self._ac_last_turned_on
                    if on_duration < self.compressor_min_on_time:
                        remaining = self.compressor_min_on_time - on_duration
                        _LOGGER.info(
                            "Compressor protection: delaying AC turn-off (%.0fs remaining of %.0fs min on-time)",
                            remaining, self.compressor_min_on_time
                        )
                        return

        # Use retry logic for AC control
        if needs_ac:
            if current_mode == "off":
                # Turn on AC in optimal mode
                _LOGGER.info("Turning ON main AC (mode: %s)", optimal_mode)
                success = await self._retry_service_call(
                    "climate",
                    "set_hvac_mode",
                    {"entity_id": self.main_climate_entity, "hvac_mode": optimal_mode},
                    entity_name=f"Main AC ({self.main_climate_entity})"
                )
                if success:
                    self._ac_last_turned_on = time.time()
                    await self._send_notification("AC Turned On", f"Smart Manager turned on AC in {optimal_mode} mode")
            else:
                # AC is already on, just set the optimal mode
                await self._set_hvac_mode(optimal_mode, main_climate_state)
        else:
            if current_mode and current_mode != "off":
                _LOGGER.info("Turning OFF main AC")
                success = await self._retry_service_call(
                    "climate",
                    "set_hvac_mode",
                    {"entity_id": self.main_climate_entity, "hvac_mode": "off"},
                    entity_name=f"Main AC ({self.main_climate_entity})"
                )
                if success:
                    self._ac_last_turned_off = time.time()
                    await self._send_notification("AC Turned Off", "Smart Manager turned off AC (rooms at target)")

    async def _set_ac_temperature(self, temperature: float) -> None:
        """Set the main AC temperature setpoint."""
        if not self.main_climate_entity:
            return

        try:
            climate_state = self.hass.states.get(self.main_climate_entity)
            if not climate_state:
                _LOGGER.warning("Main climate entity %s not found", self.main_climate_entity)
                return

            current_temp = climate_state.attributes.get("temperature")
            if current_temp is not None and abs(current_temp - temperature) < 0.5:
                _LOGGER.debug("Skipping AC temperature update (difference < 0.5°C)")
                return

            _LOGGER.debug("Setting main AC temperature to %.1f°C", temperature)
            await self._retry_service_call(
                "climate",
                "set_temperature",
                {"entity_id": self.main_climate_entity, "temperature": temperature},
                entity_name=f"Main AC Temperature ({self.main_climate_entity})"
            )
        except Exception as e:
            _LOGGER.error("Error in _set_ac_temperature: %s", e)
            self._last_error = f"AC Temperature Control Error: {e}"
            self._error_count += 1

    async def _send_notification(self, title: str, message: str) -> None:
        """Send notifications via persistent_notification and configured services."""
        if not self.enable_notifications:
            return

        full_title = f"Smart Aircon Manager: {title}"

        # Always send persistent notification (HA built-in, always available)
        try:
            await self.hass.services.async_call(
                "persistent_notification",
                "create",
                {
                    "title": full_title,
                    "message": message,
                    "notification_id": f"smart_aircon_manager_{title.lower().replace(' ', '_')}",
                },
                blocking=False,
            )
        except Exception as e:
            _LOGGER.error("Error sending persistent notification: %s", e)

        # Send to configured additional notification services
        for service in self.notify_services:
            try:
                service_name = service.replace("notify.", "")
                full_message = f"{full_title}\n\n{message}"

                try:
                    await self.hass.services.async_call(
                        "notify",
                        service_name,
                        {"title": full_title, "message": message},
                    )
                except Exception:
                    # Fallback: some services don't support title
                    await self.hass.services.async_call(
                        "notify",
                        service_name,
                        {"message": full_message},
                    )
                _LOGGER.debug("Sent notification via %s", service)
            except Exception as e:
                _LOGGER.error("Failed to send notification via %s: %s", service, e)

    async def async_cleanup(self) -> None:
        """Cleanup resources on unload."""
        _LOGGER.debug("Cleaning up AirconOptimizer resources")

        # Save learning profiles before shutdown
        if self.learning_manager:
            await self.learning_manager.async_save_profiles()
            _LOGGER.debug("Saved learning profiles")

        _LOGGER.info("AirconOptimizer cleanup completed")
