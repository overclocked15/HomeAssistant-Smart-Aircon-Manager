"""Logic-based Manager for Aircon control."""
from __future__ import annotations

import asyncio
import logging
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

        # Adaptive learning
        self.learning_manager = None  # Will be initialized in async_setup
        self._last_room_temps = {}  # Track temps for learning

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

            # Additional check for clearly wrong readings
            if abs(temp) < 0.01:
                _LOGGER.warning("Temperature reading for %s suspiciously close to zero, ignoring", room_name)
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
        """Get the currently active schedule based on time and day."""
        if not self.enable_scheduling or not self.schedules:
            return None

        from datetime import datetime
        now = datetime.now()
        current_time = now.time()
        current_day = now.strftime("%A").lower()

        for schedule in self.schedules:
            if not schedule.get("schedule_enabled", True):
                continue

            schedule_days = schedule.get("schedule_days", [])
            if not schedule_days:
                continue

            # Check day match
            day_match = False
            if "all" in schedule_days:
                day_match = True
            elif "weekdays" in schedule_days and current_day in ["monday", "tuesday", "wednesday", "thursday", "friday"]:
                day_match = True
            elif "weekends" in schedule_days and current_day in ["saturday", "sunday"]:
                day_match = True
            elif current_day in schedule_days:
                day_match = True

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

                if start_t <= end_t:
                    if start_t <= current_time <= end_t:
                        _LOGGER.info("Active schedule found: %s", schedule.get("schedule_name", "Unnamed"))
                        return schedule
                else:
                    if current_time >= start_t or current_time <= end_t:
                        _LOGGER.info("Active schedule found: %s (crosses midnight)", schedule.get("schedule_name", "Unnamed"))
                        return schedule
            except (ValueError, AttributeError) as e:
                _LOGGER.warning("Invalid schedule time format: %s", e)
                continue

        return None

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

        room_states = await self._collect_room_states(effective_target)

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
                hvac_mode = climate_state.attributes.get("hvac_mode")
                main_ac_running = (
                    hvac_action in ["cooling", "heating"]
                    or (hvac_mode and hvac_mode not in ["off", "unavailable"])
                )

        needs_ac = await self._check_if_ac_needed(room_states, main_ac_running)

        if self.auto_control_main_ac and self.main_climate_entity:
            await self._control_main_ac(needs_ac, main_climate_state)

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
            _LOGGER.info(
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
            _LOGGER.info("Main AC is not running - skipping optimization")

        # End performance tracking
        cycle_end = time.time()
        cycle_time_ms = (cycle_end - cycle_start) * 1000
        self._last_cycle_time_ms = cycle_time_ms
        self._total_optimizations_run += 1

        # Calculate error rate (errors per hour)
        uptime_hours = (cycle_end - self._startup_time) / 3600 if self._startup_time else 1
        error_rate = self._error_count / uptime_hours if uptime_hours > 0 else 0

        # Track performance data for adaptive learning
        if self.learning_manager and self.learning_manager.enabled:
            for room_name, state in room_states.items():
                current_temp = state.get("current_temperature")
                if current_temp is None:
                    continue

                # Get previous temperature for this room
                previous_temp = self._last_room_temps.get(room_name)

                # Get fan speed applied
                fan_speed = recommendations.get(room_name, 50)

                # Track this cycle
                self.learning_manager.tracker.track_cycle(
                    room_name=room_name,
                    temp_before=previous_temp if previous_temp else current_temp,
                    temp_after=current_temp,
                    fan_speed=fan_speed,
                    target_temp=state.get("target_temperature", self.target_temperature),
                    cycle_duration=cycle_time_ms / 1000.0,  # Convert to seconds
                )

                # Store current temp for next cycle
                self._last_room_temps[room_name] = current_temp

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
        }

    async def _collect_room_states(self, target_temperature: float | None = None) -> dict[str, dict[str, Any]]:
        """Collect current temperature and cover state for all rooms."""
        room_states = {}
        effective_target = target_temperature if target_temperature is not None else self.target_temperature

        for room in self.room_configs:
            room_name = room["room_name"]
            temp_sensor = room["temperature_sensor"]
            cover_entity = room["cover_entity"]

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

            room_states[room_name] = {
                "current_temperature": current_temp,
                "target_temperature": effective_target,
                "cover_position": cover_position,
                "temperature_sensor": temp_sensor,
                "cover_entity": cover_entity,
            }

        return room_states

    def _calculate_recommendations(self, room_states: dict[str, dict[str, Any]]) -> dict[str, int | float]:
        """Calculate logic-based recommendations for cover positions and AC temperature."""
        recommendations = {}

        effective_target = self.target_temperature
        if room_states:
            first_room = next(iter(room_states.values()))
            if 'target_temperature' in first_room and first_room['target_temperature'] is not None:
                effective_target = first_room['target_temperature']

        for room_name, state in room_states.items():
            current_temp = state["current_temperature"]
            if current_temp is None:
                continue

            temp_diff = current_temp - effective_target
            abs_temp_diff = abs(temp_diff)

            # Calculate raw fan speed
            raw_fan_speed = self._calculate_fan_speed(temp_diff, abs_temp_diff)

            # Apply smoothing to prevent oscillation
            fan_speed = self._smooth_fan_speed(room_name, raw_fan_speed)
            recommendations[room_name] = fan_speed

            _LOGGER.debug(
                "Room %s: temp=%.1f°C, target=%.1f°C, diff=%+.1f°C → fan=%d%%",
                room_name,
                current_temp,
                effective_target,
                temp_diff,
                fan_speed
            )

        if self.auto_control_ac_temperature and self.main_climate_entity:
            ac_temp = self._calculate_ac_temperature(room_states, effective_target)
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
                    return 55   # Slightly hot - moderate cooling
                elif abs_temp_diff >= 0.7:
                    return 45   # Just above target - gentle cooling
                else:
                    return 40   # Barely above - minimal cooling
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
                    return 55   # Slightly cold - moderate heating
                elif abs_temp_diff >= 0.7:
                    return 45   # Just below target - gentle heating
                else:
                    return 40   # Barely below - minimal heating
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

    def _calculate_ac_temperature(self, room_states: dict[str, dict[str, Any]], effective_target: float) -> float:
        """Calculate optimal AC temperature setpoint."""
        temps = [s["current_temperature"] for s in room_states.values() if s["current_temperature"] is not None]
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
        if "ac_temperature" in recommendations and self.auto_control_ac_temperature and self.main_climate_entity:
            await self._set_ac_temperature(recommendations["ac_temperature"])

        for room_name, position in recommendations.items():
            if room_name == "ac_temperature":
                continue
                
            room_override = self.room_overrides.get(f"{room_name}_enabled")
            if room_override is False:
                _LOGGER.info("Skipping %s - control disabled via override", room_name)
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
                _LOGGER.info("Set cover position for %s (%s) to %d%%", room_name, cover_entity, position)
            else:
                await self._send_notification(
                    "Cover Control Error",
                    f"Failed to set fan speed for {room_name} after {MAX_RETRIES} attempts"
                )

    async def _determine_and_set_main_fan_speed(self, room_states: dict[str, dict[str, Any]]) -> str:
        """Determine and set the main aircon fan speed."""
        effective_target = self.target_temperature
        if room_states:
            first_room = next(iter(room_states.values()))
            if 'target_temperature' in first_room and first_room['target_temperature'] is not None:
                effective_target = first_room['target_temperature']

        temps = [s["current_temperature"] for s in room_states.values() if s["current_temperature"] is not None]
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
            _LOGGER.info("Main fan -> LOW: Maintaining (variance: %.1f°C)", temp_variance)
        elif self.hvac_mode == "cool":
            if avg_temp_diff >= self.main_fan_high_threshold or (max_temp_diff >= 3.0 and temp_variance >= 2.0):
                fan_speed = "high"
                _LOGGER.info("Main fan -> HIGH: Aggressive cooling (avg: +%.1f°C)", avg_temp_diff)
            elif avg_temp_diff <= -0.5 or (avg_temp_diff < self.main_fan_medium_threshold and max_temp_diff < 2.0):
                fan_speed = "low"
                _LOGGER.info("Main fan -> LOW: At/below target in cool mode")
            else:
                fan_speed = "medium"
        elif self.hvac_mode == "heat":
            if avg_temp_diff <= -self.main_fan_high_threshold or (min_temp_diff <= -3.0 and temp_variance >= 2.0):
                fan_speed = "high"
                _LOGGER.info("Main fan -> HIGH: Aggressive heating (avg: %.1f°C)", avg_temp_diff)
            elif avg_temp_diff >= 0.5 or (avg_temp_diff > -self.main_fan_medium_threshold and min_temp_diff > -2.0):
                fan_speed = "low"
                _LOGGER.info("Main fan -> LOW: At/above target in heat mode")
            else:
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
            _LOGGER.info("Set main fan (%s) to %s", self.main_fan_entity, fan_speed)
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

        temps = [s["current_temperature"] for s in room_states.values() if s["current_temperature"] is not None]
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

    async def _control_main_ac(self, needs_ac: bool, main_climate_state: dict[str, Any] | None) -> None:
        """Control the main AC on/off."""
        if not main_climate_state:
            return

        current_mode = main_climate_state.get("hvac_mode")

        # Use retry logic for AC control
        if needs_ac:
            if current_mode == "off":
                target_mode = self.hvac_mode if self.hvac_mode != "auto" else "cool"
                _LOGGER.info("Turning ON main AC (mode: %s)", target_mode)
                success = await self._retry_service_call(
                    "climate",
                    "set_hvac_mode",
                    {"entity_id": self.main_climate_entity, "hvac_mode": target_mode},
                    entity_name=f"Main AC ({self.main_climate_entity})"
                )
                if success:
                    await self._send_notification("AC Turned On", f"Smart Manager turned on AC in {target_mode} mode")
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

            _LOGGER.info("Setting main AC temperature to %.1f°C", temperature)
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
        """Send a persistent notification."""
        if not self.enable_notifications:
            return

        try:
            await self.hass.services.async_call(
                "persistent_notification",
                "create",
                {
                    "title": f"Smart Aircon Manager: {title}",
                    "message": message,
                    "notification_id": f"smart_aircon_manager_{title.lower().replace(' ', '_')}",
                },
                blocking=False,
            )
        except Exception as e:
            _LOGGER.error("Error sending notification: %s", e)

    async def async_cleanup(self) -> None:
        """Cleanup resources on unload."""
        _LOGGER.debug("Cleaning up AirconOptimizer resources")

        # Save learning profiles before shutdown
        if self.learning_manager:
            await self.learning_manager.async_save_profiles()
            _LOGGER.info("Saved learning profiles")

        _LOGGER.info("AirconOptimizer cleanup completed")
