"""Logic-based Manager for Aircon control."""
from __future__ import annotations

import asyncio
import json
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
        enable_adaptive_bands: bool = True,
        enable_adaptive_efficiency: bool = True,
        enable_adaptive_predictive: bool = True,
        enable_adaptive_ac_setpoint: bool = False,
        enable_adaptive_balancing: bool = True,
        enable_room_coupling_detection: bool = True,
        enable_enhanced_compressor_protection: bool = False,
        compressor_undercool_margin: float = 0.5,
        compressor_overheat_margin: float = 0.5,
        min_mode_duration: float = 600.0,
        min_compressor_run_cycles: int = 3,
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

        # Enhanced compressor protection (reduces mode change frequency)
        self.enable_enhanced_compressor_protection = enable_enhanced_compressor_protection
        self.compressor_undercool_margin = self._validate_positive_float(
            compressor_undercool_margin, "compressor_undercool_margin", 0.0, 5.0
        )
        self.compressor_overheat_margin = self._validate_positive_float(
            compressor_overheat_margin, "compressor_overheat_margin", 0.0, 5.0
        )
        self.min_mode_duration = max(0, float(min_mode_duration))
        self.min_compressor_run_cycles = max(0, int(min_compressor_run_cycles))
        self._current_hvac_mode = None  # Track current HVAC mode (cool/heat/fan/off)
        self._mode_start_time = None  # Timestamp when current mode started
        self._compressor_run_cycle_count = 0  # Count optimization cycles in compressor mode

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

        # Smart learning improvements
        self.enable_adaptive_bands = enable_adaptive_bands
        self.enable_adaptive_efficiency = enable_adaptive_efficiency
        self.enable_adaptive_predictive = enable_adaptive_predictive
        self.enable_adaptive_ac_setpoint = enable_adaptive_ac_setpoint

        # Adaptive balancing
        self.enable_adaptive_balancing = enable_adaptive_balancing
        self.enable_room_coupling_detection = enable_room_coupling_detection

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
        self._outdoor_temperature_timestamp = None  # Timestamp when outdoor temp was last fetched
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

        # Quick action modes
        self._quick_action_mode = None  # None, "vacation", "boost", "sleep", "party"
        self._quick_action_expiry = None  # Timestamp when mode expires
        self._quick_action_original_settings = {}  # Store settings to restore

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

        # Load persisted compressor protection state
        await self._load_compressor_state()

        # Clean up any stale cache entries for deleted rooms
        self._cleanup_room_caches()

    def _cleanup_room_caches(self) -> None:
        """Remove cache entries for rooms that are no longer configured.

        This prevents memory leaks when rooms are removed during reconfiguration.
        """
        # Get current room names from config
        current_rooms = {config["name"] for config in self.room_configs}

        # Clean up caches
        caches_to_clean = [
            ("_last_fan_speeds", self._last_fan_speeds),
            ("_temp_history", self._temp_history),
            ("_last_recommendations", self._last_recommendations),
            ("_last_room_temps", self._last_room_temps),
            ("_room_occupancy_state", self._room_occupancy_state),
        ]

        total_removed = 0
        for cache_name, cache_dict in caches_to_clean:
            rooms_to_remove = [room for room in cache_dict.keys() if room not in current_rooms]
            for room in rooms_to_remove:
                del cache_dict[room]
                total_removed += 1
                _LOGGER.debug("Cleaned up %s entry for deleted room: %s", cache_name, room)

        if total_removed > 0:
            _LOGGER.info("Cleaned up %d cache entries for %d deleted rooms",
                        total_removed, len(set(room for cache_name, cache_dict in caches_to_clean
                                               for room in cache_dict.keys() if room not in current_rooms)))

    async def _load_compressor_state(self) -> None:
        """Load persisted compressor protection timestamps from storage."""
        try:
            storage_path = Path(self.hass.config.path(".storage"))
            config_entry_id = self.config_entry.entry_id if self.config_entry else "default"
            state_file = storage_path / f"smart_aircon_manager.{config_entry_id}.state.json"

            if state_file.exists():
                def _load():
                    with open(state_file, 'r') as f:
                        return json.load(f)

                data = await self.hass.async_add_executor_job(_load)

                # Restore timestamps if they exist and are recent (within last 24 hours)
                # This prevents using very stale data after long HA downtime
                current_time = time.time()
                max_age = 86400  # 24 hours

                if 'ac_last_turned_on' in data and data['ac_last_turned_on']:
                    if current_time - data['ac_last_turned_on'] < max_age:
                        self._ac_last_turned_on = data['ac_last_turned_on']
                        _LOGGER.debug("Restored AC last turned on timestamp: %.0f seconds ago",
                                     current_time - self._ac_last_turned_on)

                if 'ac_last_turned_off' in data and data['ac_last_turned_off']:
                    if current_time - data['ac_last_turned_off'] < max_age:
                        self._ac_last_turned_off = data['ac_last_turned_off']
                        _LOGGER.debug("Restored AC last turned off timestamp: %.0f seconds ago",
                                     current_time - self._ac_last_turned_off)

                _LOGGER.info("Compressor protection state loaded successfully")
            else:
                _LOGGER.debug("No existing compressor state file found, starting fresh")

        except Exception as e:
            _LOGGER.warning("Failed to load compressor state: %s", e)
            # Don't fail startup, just log and continue

    async def _save_compressor_state(self) -> None:
        """Save compressor protection timestamps to storage."""
        try:
            storage_path = Path(self.hass.config.path(".storage"))
            config_entry_id = self.config_entry.entry_id if self.config_entry else "default"
            state_file = storage_path / f"smart_aircon_manager.{config_entry_id}.state.json"

            data = {
                'ac_last_turned_on': self._ac_last_turned_on,
                'ac_last_turned_off': self._ac_last_turned_off,
                'saved_at': time.time(),
            }

            def _save():
                storage_path.mkdir(parents=True, exist_ok=True)
                with open(state_file, 'w') as f:
                    json.dump(data, f, indent=2)

            await self.hass.async_add_executor_job(_save)
            _LOGGER.debug("Compressor protection state saved")

        except Exception as e:
            _LOGGER.warning("Failed to save compressor state: %s", e)
            # Don't fail operation, just log

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

        # Determine the optimal mode (before hysteresis and enhanced protection)
        optimal_mode = None

        # Enhanced compressor protection: Adjust deadband based on current mode
        # This creates hysteresis to reduce mode switching frequency
        effective_deadband = self.temperature_deadband

        if self.enable_enhanced_compressor_protection and self._current_hvac_mode in ["cool", "heat"]:
            # If currently in compressor mode, require additional margin before switching to fan
            if self._current_hvac_mode == "cool":
                # In cooling mode: need to undercool before switching to fan
                # temp must be BELOW target by (deadband + undercool_margin)
                if temp_deviation < 0:  # Already below target
                    # Apply undercool margin - need to be even MORE below target
                    effective_deadband = self.temperature_deadband + self.compressor_undercool_margin
                    _LOGGER.debug(
                        "Enhanced compressor protection (cooling): Temp %.1f°C below target, requiring %.1f°C total deviation before switching to fan",
                        abs(temp_deviation), effective_deadband
                    )
            elif self._current_hvac_mode == "heat":
                # In heating mode: need to overheat before switching to fan
                # temp must be ABOVE target by (deadband + overheat_margin)
                if temp_deviation > 0:  # Already above target
                    # Apply overheat margin - need to be even MORE above target
                    effective_deadband = self.temperature_deadband + self.compressor_overheat_margin
                    _LOGGER.debug(
                        "Enhanced compressor protection (heating): Temp %.1f°C above target, requiring %.1f°C total deviation before switching to fan",
                        temp_deviation, effective_deadband
                    )

        # Priority 1: Temperature needs attention (outside effective deadband)
        if abs_deviation > effective_deadband:
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

            # Enhanced compressor protection: Check minimum duration and run cycles
            # Prevents frequent switching between compressor modes (cool/heat) and fan_only
            if self.enable_enhanced_compressor_protection:
                # Check if trying to exit compressor mode to fan_only
                if self._last_hvac_mode in ["cool", "heat"] and optimal_mode == "fan_only":
                    # Check minimum mode duration
                    mode_duration = current_time - self._mode_start_time if self._mode_start_time else 0

                    if mode_duration < self.min_mode_duration:
                        should_change_mode = False
                        remaining = self.min_mode_duration - mode_duration
                        _LOGGER.info(
                            "Enhanced compressor protection: Minimum mode duration not met - staying in %s mode (%.0fs elapsed, %.0fs required, %.0fs remaining)",
                            self._last_hvac_mode, mode_duration, self.min_mode_duration, remaining
                        )
                        optimal_mode = self._last_hvac_mode

                    # Check minimum run cycles
                    elif self._compressor_run_cycle_count < self.min_compressor_run_cycles:
                        should_change_mode = False
                        remaining_cycles = self.min_compressor_run_cycles - self._compressor_run_cycle_count
                        _LOGGER.info(
                            "Enhanced compressor protection: Minimum run cycles not met - staying in %s mode (%d cycles elapsed, %d required, %d remaining)",
                            self._last_hvac_mode, self._compressor_run_cycle_count, self.min_compressor_run_cycles, remaining_cycles
                        )
                        optimal_mode = self._last_hvac_mode

            # CRITICAL: If currently in fan_only and conditions require active mode, switch immediately!
            # Fan_only doesn't control temperature/humidity, so we must exit it when conditions demand action
            if should_change_mode and self._last_hvac_mode == "fan_only" and optimal_mode in ["cool", "heat", "dry"]:
                if optimal_mode in ["cool", "heat"]:
                    _LOGGER.info(
                        "Exiting fan_only mode immediately due to temperature deviation %.1f°C (deadband: %.1f°C) - switching to %s",
                        abs_deviation, effective_deadband, optimal_mode
                    )
                else:  # dry mode
                    _LOGGER.info(
                        "Exiting fan_only mode immediately due to high humidity %.1f%% (threshold: %.1f%%) - switching to DRY",
                        avg_humidity if avg_humidity is not None else 0, self.dry_mode_humidity_threshold
                    )
                # Don't apply hysteresis when exiting fan_only - allow immediate switch
            elif should_change_mode and time_since_last_change < self.mode_change_hysteresis_time:
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

            # Enhanced compressor protection: Reset tracking on mode change
            if self.enable_enhanced_compressor_protection:
                # Track when this mode started
                if optimal_mode != self._current_hvac_mode:
                    self._current_hvac_mode = optimal_mode
                    self._mode_start_time = current_time
                    self._compressor_run_cycle_count = 0
                    _LOGGER.debug(
                        "Enhanced compressor protection: Mode change to %s, reset tracking (duration=0s, cycles=0)",
                        optimal_mode
                    )

        elif self._last_hvac_mode is None:
            # First run
            self._last_hvac_mode = optimal_mode
            self._last_mode_change_time = current_time

            if self.enable_enhanced_compressor_protection:
                self._current_hvac_mode = optimal_mode
                self._mode_start_time = current_time
                self._compressor_run_cycle_count = 0

        # Enhanced compressor protection: Increment cycle count if in compressor mode
        if self.enable_enhanced_compressor_protection and self._current_hvac_mode in ["cool", "heat"]:
            self._compressor_run_cycle_count += 1
            _LOGGER.debug(
                "Enhanced compressor protection: Cycle count in %s mode: %d (min required: %d)",
                self._current_hvac_mode, self._compressor_run_cycle_count, self.min_compressor_run_cycles
            )

        # Update mode state flags
        self._dry_mode_active = (optimal_mode == "dry")
        self._fan_only_mode_active = (optimal_mode == "fan_only")

        return optimal_mode

    async def _get_outdoor_temperature(self) -> float | None:
        """Get outdoor temperature from weather entity or outdoor sensor.

        Uses 1-hour cache to handle temporary sensor unavailability.
        """
        CACHE_MAX_AGE = 3600  # 1 hour in seconds
        current_time = time.time()

        # Try to get fresh outdoor temperature
        fresh_temp = None

        if self.outdoor_temp_sensor:
            sensor_state = self.hass.states.get(self.outdoor_temp_sensor)
            if sensor_state and sensor_state.state not in ["unknown", "unavailable", "none", None]:
                try:
                    temp = float(sensor_state.state)
                    unit = sensor_state.attributes.get("unit_of_measurement", "°C")
                    if unit in ["°F", "fahrenheit", "F"]:
                        temp = (temp - 32) * 5.0 / 9.0
                    fresh_temp = temp
                except (ValueError, TypeError) as e:
                    _LOGGER.warning("Could not read outdoor temperature sensor: %s", e)

        if fresh_temp is None and self.weather_entity:
            weather_state = self.hass.states.get(self.weather_entity)
            if weather_state:
                temp = weather_state.attributes.get("temperature")
                if temp is not None:
                    try:
                        fresh_temp = float(temp)
                    except (ValueError, TypeError) as e:
                        _LOGGER.warning("Could not read weather temperature: %s", e)

        # If we got fresh temperature, cache it and return
        if fresh_temp is not None:
            self._outdoor_temperature = fresh_temp
            self._outdoor_temperature_timestamp = current_time
            return fresh_temp

        # No fresh temperature available - check if we have cached value within max age
        if self._outdoor_temperature is not None and self._outdoor_temperature_timestamp is not None:
            cache_age = current_time - self._outdoor_temperature_timestamp
            if cache_age < CACHE_MAX_AGE:
                _LOGGER.debug("Using cached outdoor temperature (%.1f°C, age: %.0f seconds)",
                             self._outdoor_temperature, cache_age)
                return self._outdoor_temperature
            else:
                _LOGGER.debug("Cached outdoor temperature expired (age: %.0f seconds > %d max)",
                             cache_age, CACHE_MAX_AGE)

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
                    # Default to distant past to force vacancy if last_seen is missing
                    last_seen = room_state.get("last_seen", current_time - self.vacancy_timeout - 1)
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

        Uses least-squares regression with outlier filtering to handle sensor glitches.
        Positive = temperature rising, Negative = temperature falling.
        Returns None if insufficient data.
        """
        history = self._temp_history.get(room_name, [])
        if len(history) < 3:
            return None

        # Extract times and temperatures
        times = [h[0] for h in history]
        temps = [h[1] for h in history]

        # Filter outliers using 2-sigma rule (remove points > 2 std devs from mean)
        # This prevents sensor glitches from skewing the regression
        if len(temps) >= 5:  # Only filter if we have enough data
            temp_mean = sum(temps) / len(temps)
            temp_variance = sum((t - temp_mean) ** 2 for t in temps) / len(temps)
            temp_std = temp_variance ** 0.5

            if temp_std > 0.1:  # Only filter if there's meaningful variation
                filtered_data = [(t, temp) for t, temp in zip(times, temps)
                                if abs(temp - temp_mean) <= 2 * temp_std]

                if len(filtered_data) >= 3:  # Need at least 3 points after filtering
                    times = [d[0] for d in filtered_data]
                    temps = [d[1] for d in filtered_data]
                    if len(filtered_data) < len(history):
                        _LOGGER.debug(
                            "Filtered %d outlier(s) from temperature history for %s",
                            len(history) - len(filtered_data), room_name
                        )

        # Calculate slope using least squares regression
        n = len(times)
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

        Uses dampening to account for exponential decay (Newton's law of cooling).
        As temperature approaches target, rate of change slows down.

        Returns predicted temperature or None if insufficient data.
        """
        rate = self._get_temp_rate_of_change(room_name)
        if rate is None:
            return None

        # Apply exponential decay dampening factor
        # Linear prediction overestimates because it assumes constant rate
        # Reality: rate slows as temp approaches equilibrium
        # Dampen by 60% to account for this (empirically determined)
        DECAY_DAMPING_FACTOR = 0.6

        predicted_change = rate * self.predictive_lookahead_minutes * DECAY_DAMPING_FACTOR
        predicted = current_temp + predicted_change

        return predicted

    def _apply_predictive_adjustment(self, room_name: str, base_fan_speed: int,
                                      current_temp: float, target_temp: float) -> int:
        """Adjust fan speed based on predicted future temperature.

        If prediction shows the room will overshoot, boost fan speed preemptively.
        If prediction shows the room will undershoot, reduce fan speed.
        Uses adaptive boost factor based on learned convergence rate if enabled.
        """
        predicted_temp = self._predict_temperature(room_name, current_temp)
        if predicted_temp is None:
            return base_fan_speed

        rate = self._get_temp_rate_of_change(room_name)
        predicted_diff = predicted_temp - target_temp

        # Get adaptive predictive boost factor (or default if not available)
        boost_factor = self._get_adaptive_predictive_boost(room_name)

        # In cooling mode: if temp is predicted to rise above target, boost cooling
        # In heating mode: if temp is predicted to fall below target, boost heating
        adjustment = 0
        if self.hvac_mode == "cool":
            if predicted_diff > self.temperature_deadband and rate > 0:
                # Temperature rising toward/past target - boost cooling
                adjustment = int(predicted_diff * boost_factor * 20)
            elif predicted_diff < -self.temperature_deadband and rate < 0:
                # Temperature falling well below target - reduce cooling
                adjustment = -int(abs(predicted_diff) * boost_factor * 15)
        elif self.hvac_mode == "heat":
            if predicted_diff < -self.temperature_deadband and rate < 0:
                # Temperature falling away from target - boost heating
                adjustment = int(abs(predicted_diff) * boost_factor * 20)
            elif predicted_diff > self.temperature_deadband and rate > 0:
                # Temperature rising past target - reduce heating
                adjustment = -int(predicted_diff * boost_factor * 15)

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

        # Always update temperature history (even if predictive control is disabled)
        # This ensures history is available if user enables predictive control later
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

                # Apply quick action adjustments if active
                recommendations = self._apply_quick_action_adjustments(recommendations, room_states)

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

            # Calculate raw fan speed (with adaptive bands and efficiency if enabled)
            raw_fan_speed = self._calculate_fan_speed(temp_diff, abs_temp_diff, room_name)

            # Apply predictive adjustment BEFORE smoothing to preserve predictive boost effectiveness
            # Predictive control adds proactive adjustments to prevent overshoot
            fan_speed_with_prediction = raw_fan_speed
            if self.enable_predictive_control:
                fan_speed_with_prediction = self._apply_predictive_adjustment(
                    room_name, raw_fan_speed, current_temp, room_effective_target
                )

            # Apply smoothing AFTER predictive adjustment to prevent oscillation
            # This ensures the predictive boost isn't dampened by smoothing
            fan_speed = self._smooth_fan_speed(room_name, fan_speed_with_prediction)

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

    def _calculate_fan_speed(self, temp_diff: float, abs_temp_diff: float, room_name: str = None) -> int:
        """Calculate fan speed based on temperature difference and HVAC mode.

        Uses granular bands for smooth, responsive temperature control.
        Optionally uses adaptive bands based on learned thermal characteristics.
        """
        # Get adaptive temperature bands if room_name provided
        bands = self._get_adaptive_temperature_bands(room_name) if room_name else {
            'extreme': 4.0, 'very_high': 3.0, 'high': 2.0, 'moderate': 1.5,
            'slight': 1.0, 'minimal': 0.7, 'very_minimal': 0.5
        }

        # Within deadband - maintain with moderate circulation
        if abs_temp_diff <= self.temperature_deadband:
            base_speed = 50  # Baseline circulation when at target
            # Apply efficiency adjustment if room provided
            if room_name:
                return self._apply_efficiency_adjustment(base_speed, room_name)
            return base_speed

        if self.hvac_mode == "cool":
            if temp_diff > 0:
                # Room is too hot - needs cooling (using adaptive bands)
                if abs_temp_diff >= bands['extreme']:
                    base_speed = 100  # Extreme heat - maximum cooling
                elif abs_temp_diff >= bands['very_high']:
                    base_speed = 90   # Very hot - aggressive cooling
                elif abs_temp_diff >= bands['high']:
                    base_speed = 75   # Hot - strong cooling
                elif abs_temp_diff >= bands['moderate']:
                    base_speed = 65   # Moderately hot - good cooling
                elif abs_temp_diff >= bands['slight']:
                    base_speed = 60   # Slightly hot - moderate cooling
                else:
                    base_speed = 55   # Just outside deadband - slightly above baseline

                # Apply efficiency adjustment if room provided
                if room_name:
                    return self._apply_efficiency_adjustment(base_speed, room_name)
                return base_speed
            else:
                # Room is too cold - overshot target, reduce cooling progressively
                if abs_temp_diff >= self.overshoot_tier3_threshold:  # 3°C+
                    base_speed = 5    # Severe overshoot - near shutdown
                elif abs_temp_diff >= self.overshoot_tier2_threshold:  # 2-3°C
                    base_speed = 12   # High overshoot - minimal airflow
                elif abs_temp_diff >= self.overshoot_tier1_threshold:  # 1-2°C
                    base_speed = 22   # Medium overshoot - reduced cooling
                elif abs_temp_diff >= 0.7:
                    base_speed = 30   # Small overshoot - gentle reduction
                else:
                    base_speed = 35   # Very small overshoot - slight reduction

                # Apply efficiency adjustment if room provided
                if room_name:
                    return self._apply_efficiency_adjustment(base_speed, room_name)
                return base_speed

        elif self.hvac_mode == "heat":
            if temp_diff < 0:
                # Room is too cold - needs heating (using adaptive bands)
                if abs_temp_diff >= bands['extreme']:
                    base_speed = 100  # Extreme cold - maximum heating
                elif abs_temp_diff >= bands['very_high']:
                    base_speed = 90   # Very cold - aggressive heating
                elif abs_temp_diff >= bands['high']:
                    base_speed = 75   # Cold - strong heating
                elif abs_temp_diff >= bands['moderate']:
                    base_speed = 65   # Moderately cold - good heating
                elif abs_temp_diff >= bands['slight']:
                    base_speed = 60   # Slightly cold - moderate heating
                else:
                    base_speed = 55   # Just outside deadband - slightly above baseline

                # Apply efficiency adjustment if room provided
                if room_name:
                    return self._apply_efficiency_adjustment(base_speed, room_name)
                return base_speed
            else:
                # Room is too warm - overshot target, reduce heating progressively
                if abs_temp_diff >= self.overshoot_tier3_threshold:  # 3°C+
                    base_speed = 5    # Severe overshoot - near shutdown
                elif abs_temp_diff >= self.overshoot_tier2_threshold:  # 2-3°C
                    base_speed = 12   # High overshoot - minimal airflow
                elif abs_temp_diff >= self.overshoot_tier1_threshold:  # 1-2°C
                    base_speed = 22   # Medium overshoot - reduced heating
                elif abs_temp_diff >= 0.7:
                    base_speed = 30   # Small overshoot - gentle reduction
                else:
                    base_speed = 35   # Very small overshoot - slight reduction

                # Apply efficiency adjustment if room provided
                if room_name:
                    return self._apply_efficiency_adjustment(base_speed, room_name)
                return base_speed
        else:
            # Auto mode - use magnitude-based approach with adaptive bands
            if abs_temp_diff >= bands['extreme']:
                base_speed = 100
            elif abs_temp_diff >= bands['very_high']:
                base_speed = 85
            elif abs_temp_diff >= bands['high']:
                base_speed = 70
            elif abs_temp_diff >= bands['moderate']:
                base_speed = 60
            elif abs_temp_diff >= bands['slight']:
                base_speed = 50
            elif abs_temp_diff >= bands['minimal']:
                base_speed = 42
            else:
                base_speed = 35

            # Apply efficiency adjustment if room provided
            if room_name:
                return self._apply_efficiency_adjustment(base_speed, room_name)
            return base_speed

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

            # Apply adaptive balancing adjustments if enabled and learning available
            if self.enable_adaptive_balancing and self.learning_manager:
                if self.learning_manager.should_apply_learning(room_name):
                    profile = self.learning_manager.get_profile(room_name)
                    if profile:
                        # 1. Apply learned balancing bias (accumulated historical adjustments)
                        # Clamp to prevent unbounded accumulation over months
                        clamped_learned_bias = max(-5.0, min(5.0, profile.balancing_bias))
                        balancing_bias += clamped_learned_bias * 10

                        # 2. Apply relative convergence rate adjustment (additive, not multiplicative)
                        # This prevents the multiplier from affecting the learned bias component
                        convergence_adjustment = 0.0
                        if self.hvac_mode == "cool":
                            # Fast heating room needs more cooling in cooling mode
                            # relative_heat_gain_rate > 1.0 means faster than average
                            convergence_adjustment = (profile.relative_heat_gain_rate - 1.0) * deviation_from_avg * 50
                        elif self.hvac_mode == "heat":
                            # Fast cooling room needs more heating in heating mode
                            # relative_cool_rate > 1.0 means faster than average
                            convergence_adjustment = (1.0 - profile.relative_cool_rate) * deviation_from_avg * 50

                        balancing_bias += convergence_adjustment

                        # 3. Apply room coupling adjustments if enabled
                        if self.enable_room_coupling_detection and profile.coupling_factors:
                            for coupled_room, coupling_factor in profile.coupling_factors.items():
                                coupled_state = room_states.get(coupled_room)
                                if coupled_state and coupled_state["current_temperature"] is not None:
                                    coupled_temp = coupled_state["current_temperature"]
                                    coupled_deviation = coupled_temp - avg_temp
                                    # If coupled room is hot, this room likely needs adjustment too
                                    balancing_bias += coupled_deviation * coupling_factor * 5

                        _LOGGER.debug(
                            "  %s: Applied adaptive balancing (learned_bias=%.1f, convergence_adj=%.1f, %d coupled rooms)",
                            room_name, clamped_learned_bias, convergence_adjustment,
                            len(profile.coupled_rooms)
                        )

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
        """Calculate optimal AC temperature setpoint.

        Optionally uses adaptive setpoints based on house-wide cooling efficiency.
        """
        temps = self._valid_temps(room_states)
        if not temps:
            return effective_target

        avg_temp = sum(temps) / len(temps)
        temp_diff = avg_temp - effective_target

        # Get base setpoint using standard logic
        if self.hvac_mode == "cool":
            if temp_diff >= 2.0:
                base_setpoint = 19.0
            elif temp_diff >= 0.5:
                base_setpoint = 21.0
            else:
                base_setpoint = 23.0
        elif self.hvac_mode == "heat":
            if temp_diff <= -2.0:
                base_setpoint = 25.0
            elif temp_diff <= -0.5:
                base_setpoint = 23.0
            else:
                base_setpoint = 21.0
        else:
            return effective_target

        # Apply adaptive adjustment if enabled
        if not self.enable_adaptive_ac_setpoint:
            return base_setpoint

        if not self.learning_manager:
            return base_setpoint

        # Calculate average efficiency across all rooms with sufficient confidence
        efficiencies = []
        for room_name in room_states.keys():
            if not self.learning_manager.should_apply_learning(room_name):
                continue

            profile = self.learning_manager.get_profile(room_name)
            if profile and profile.confidence >= 0.5:
                efficiencies.append(profile.cooling_efficiency)

        if not efficiencies:
            return base_setpoint

        import statistics
        avg_efficiency = statistics.mean(efficiencies)

        # Adjust setpoint based on house-wide efficiency
        if avg_efficiency > 0.7:
            # High efficiency house - less aggressive AC needed
            adjusted_setpoint = base_setpoint + 1.0
            _LOGGER.debug(
                "High house efficiency (%.2f), adjusting AC setpoint from %.1f°C to %.1f°C",
                avg_efficiency, base_setpoint, adjusted_setpoint
            )
            return adjusted_setpoint
        elif avg_efficiency < 0.4:
            # Low efficiency house - more aggressive AC needed
            adjusted_setpoint = base_setpoint - 1.0
            _LOGGER.debug(
                "Low house efficiency (%.2f), adjusting AC setpoint from %.1f°C to %.1f°C",
                avg_efficiency, base_setpoint, adjusted_setpoint
            )
            return adjusted_setpoint
        else:
            # Medium efficiency - use base setpoint
            return base_setpoint

    def _apply_quick_action_adjustments(
        self,
        recommendations: dict[str, int],
        room_states: dict[str, dict[str, Any]]
    ) -> dict[str, int]:
        """Apply quick action mode adjustments to recommendations."""
        if not self._quick_action_mode:
            return recommendations

        # Check expiry with atomic check-and-clear to prevent race conditions
        import time
        if self._quick_action_expiry and time.time() > self._quick_action_expiry:
            # Atomically capture and clear expiry to prevent duplicate exits
            expiry_time = self._quick_action_expiry
            self._quick_action_expiry = None

            # Only exit if we successfully captured a non-None expiry
            # This prevents concurrent calls from both exiting
            if expiry_time:
                self._exit_quick_action_mode()
            return recommendations

        adjusted = {}

        if self._quick_action_mode == "vacation":
            # Reduce all fan speeds by 70%, widen deadband
            for room, speed in recommendations.items():
                adjusted[room] = max(10, int(speed * 0.3))
            _LOGGER.debug("Vacation mode: Reduced fan speeds to 30%%")

        elif self._quick_action_mode == "boost":
            # Aggressive cooling/heating for 30 mins
            for room, speed in recommendations.items():
                adjusted[room] = min(100, int(speed * 1.5))
            _LOGGER.debug("Boost mode: Increased fan speeds by 50%%")

        elif self._quick_action_mode == "sleep":
            # Quieter fans (cap at 40%)
            for room, speed in recommendations.items():
                adjusted[room] = min(40, speed)
            _LOGGER.debug("Sleep mode: Capped fan speeds at 40%%")

        elif self._quick_action_mode == "party":
            # Equalize all rooms quickly - set all to median speed (min 60%)
            import statistics
            speeds = list(recommendations.values())
            median_speed = int(statistics.median(speeds)) if speeds else 60
            target_speed = max(60, median_speed)
            for room in recommendations.keys():
                adjusted[room] = target_speed
            _LOGGER.debug("Party mode: Set all rooms to %d%% for equalization", target_speed)

        else:
            adjusted = recommendations

        return adjusted

    def _enter_quick_action_mode(self, mode: str, duration_minutes: int = None):
        """Enter a quick action mode."""
        import time

        # Validate mode
        valid_modes = ["vacation", "boost", "sleep", "party"]
        if mode not in valid_modes:
            _LOGGER.error("Invalid quick action mode: %s", mode)
            return

        self._quick_action_mode = mode

        # Set default durations
        default_durations = {
            "vacation": None,  # Manual exit only
            "boost": 30,
            "sleep": 480,  # 8 hours
            "party": 120,  # 2 hours
        }

        duration = duration_minutes if duration_minutes else default_durations.get(mode)

        if duration:
            self._quick_action_expiry = time.time() + (duration * 60)
        else:
            self._quick_action_expiry = None

        # Store original settings
        self._quick_action_original_settings = {
            "target_temperature": self.target_temperature,
            "temperature_deadband": self.temperature_deadband,
        }

        # Adjust settings for mode
        if mode == "vacation":
            self.temperature_deadband = 2.0  # Wider tolerance
        elif mode == "sleep":
            # Adjust target slightly for sleep comfort
            if self.hvac_mode == "cool":
                self.target_temperature += 1.0
            elif self.hvac_mode == "heat":
                self.target_temperature -= 1.0

        expiry_str = f"in {duration}min" if duration else "manual exit only"
        _LOGGER.info("Entered quick action mode: %s (expires: %s)", mode, expiry_str)

    def _exit_quick_action_mode(self):
        """Exit quick action mode and restore settings."""
        if not self._quick_action_mode:
            return

        mode = self._quick_action_mode

        # Restore original settings only if they haven't been changed externally
        if self._quick_action_original_settings:
            original_temp = self._quick_action_original_settings.get("target_temperature")
            original_deadband = self._quick_action_original_settings.get("temperature_deadband")

            # Check if current values match what the mode would have set
            # If they don't match, user likely changed them manually - don't restore
            mode_changed_temp = False
            mode_changed_deadband = False

            if mode == "vacation":
                mode_changed_deadband = (self.temperature_deadband == 2.0)
            elif mode == "sleep":
                if self.hvac_mode == "cool" and original_temp:
                    mode_changed_temp = abs(self.target_temperature - (original_temp + 1.0)) < 0.1
                elif self.hvac_mode == "heat" and original_temp:
                    mode_changed_temp = abs(self.target_temperature - (original_temp - 1.0)) < 0.1

            # Only restore if value appears unchanged by user
            if original_temp and (mode not in ["sleep"] or mode_changed_temp):
                self.target_temperature = original_temp
            elif original_temp and mode in ["sleep"] and not mode_changed_temp:
                _LOGGER.info("Target temperature was manually changed during %s mode, not restoring", mode)

            if original_deadband and (mode != "vacation" or mode_changed_deadband):
                self.temperature_deadband = original_deadband
            elif original_deadband and mode == "vacation" and not mode_changed_deadband:
                _LOGGER.info("Temperature deadband was manually changed during %s mode, not restoring", mode)

        self._quick_action_mode = None
        self._quick_action_expiry = None
        self._quick_action_original_settings = {}

        _LOGGER.info("Exited quick action mode: %s", mode)

    def _get_adaptive_temperature_bands(self, room_name: str) -> dict[str, float]:
        """Get temperature bands adjusted for room thermal characteristics.

        Uses learned thermal_mass to adjust band thresholds:
        - High thermal mass (0.7-1.0): Wider bands for slower response rooms
        - Medium thermal mass (0.4-0.7): Default bands
        - Low thermal mass (0.0-0.4): Tighter bands for fast response rooms
        """
        # Default bands (in degrees from target)
        default_bands = {
            'extreme': 4.0,      # 4°C+ away
            'very_high': 3.0,    # 3-4°C away
            'high': 2.0,         # 2-3°C away
            'moderate': 1.5,     # 1.5-2°C away
            'slight': 1.0,       # 1-1.5°C away
            'minimal': 0.7,      # 0.7-1°C away
            'very_minimal': 0.5, # 0.5-0.7°C away
        }

        # Check if adaptive bands are enabled and learning is available
        if not self.enable_adaptive_bands:
            return default_bands

        if not self.learning_manager or not self.learning_manager.should_apply_learning(room_name):
            return default_bands

        profile = self.learning_manager.get_profile(room_name)
        if not profile:
            return default_bands

        thermal_mass = profile.thermal_mass

        # Determine multiplier based on thermal mass
        if thermal_mass > 0.7:
            # High thermal inertia - room responds slowly - use wider bands
            multiplier = 1.2
            _LOGGER.debug(
                "Room %s has high thermal mass (%.2f), using wider bands (×%.1f)",
                room_name, thermal_mass, multiplier
            )
        elif thermal_mass < 0.4:
            # Low thermal inertia - room responds quickly - use tighter bands
            multiplier = 0.8
            _LOGGER.debug(
                "Room %s has low thermal mass (%.2f), using tighter bands (×%.1f)",
                room_name, thermal_mass, multiplier
            )
        else:
            # Medium thermal mass - use defaults
            multiplier = 1.0

        # Apply multiplier to all bands
        adaptive_bands = {k: v * multiplier for k, v in default_bands.items()}
        return adaptive_bands

    def _apply_efficiency_adjustment(self, base_speed: int, room_name: str) -> int:
        """Adjust fan speed based on learned cooling/heating efficiency.

        Uses learned cooling_efficiency to optimize fan speeds:
        - High efficiency (0.7-1.0): Room cools/heats easily - reduce fan speed 15%
        - Low efficiency (0.0-0.4): Room struggles - increase fan speed 15%
        - Medium efficiency (0.4-0.7): No adjustment needed
        """
        # Check if adaptive efficiency is enabled
        if not self.enable_adaptive_efficiency:
            return base_speed

        if not self.learning_manager or not self.learning_manager.should_apply_learning(room_name):
            return base_speed

        profile = self.learning_manager.get_profile(room_name)
        if not profile:
            return base_speed

        efficiency = profile.cooling_efficiency

        # Proportional adjustment based on efficiency
        # Target efficiency is 0.55 (middle of range)
        # Adjustment scales linearly with distance from target:
        #   efficiency = 1.0 → adjustment = -18% (highly efficient, reduce fan)
        #   efficiency = 0.7 → adjustment = -6%
        #   efficiency = 0.55 → adjustment = 0% (optimal)
        #   efficiency = 0.4 → adjustment = +6%
        #   efficiency = 0.0 → adjustment = +22% (inefficient, increase fan)
        TARGET_EFFICIENCY = 0.55
        MAX_ADJUSTMENT = 0.40  # Max ±40% adjustment

        # Calculate proportional adjustment
        efficiency_deviation = TARGET_EFFICIENCY - efficiency
        adjustment = efficiency_deviation * MAX_ADJUSTMENT

        # Clamp adjustment to reasonable bounds (±25%)
        adjustment = max(-0.25, min(0.25, adjustment))

        _LOGGER.debug(
            "Room %s efficiency-based adjustment: efficiency=%.2f, adjustment=%+.1f%%",
            room_name, efficiency, adjustment * 100
        )

        # Apply adjustment and clamp to valid range
        adjusted_speed = base_speed * (1 + adjustment)
        final_speed = max(0, min(100, int(adjusted_speed)))

        return final_speed

    def _get_adaptive_predictive_boost(self, room_name: str) -> float:
        """Get predictive boost factor adjusted for room convergence rate.

        Uses learned avg_convergence_time to scale predictive adjustments:
        - Fast convergence (<300s): Reduce boost by 30% - room reaches target quickly
        - Slow convergence (>900s): Increase boost by 30% - room needs more help
        - Medium convergence (300-900s): Use default boost factor
        """
        base_boost = self.predictive_boost_factor  # Default from config

        # Check if adaptive predictive is enabled
        if not self.enable_adaptive_predictive:
            return base_boost

        if not self.learning_manager or not self.learning_manager.should_apply_learning(room_name):
            return base_boost

        profile = self.learning_manager.get_profile(room_name)
        if not profile or not profile.avg_convergence_time_seconds:
            return base_boost

        convergence_time = profile.avg_convergence_time_seconds

        # Adjust boost based on convergence speed
        if convergence_time < 300:
            # Fast converging room - reduce predictive boost
            adaptive_boost = base_boost * 0.7
            _LOGGER.debug(
                "Room %s converges quickly (%ds), reducing predictive boost to %.2f",
                room_name, convergence_time, adaptive_boost
            )
        elif convergence_time > 900:
            # Slow converging room - increase predictive boost
            adaptive_boost = base_boost * 1.3
            _LOGGER.debug(
                "Room %s converges slowly (%ds), increasing predictive boost to %.2f",
                room_name, convergence_time, adaptive_boost
            )
        else:
            # Medium convergence - use default
            adaptive_boost = base_boost

        return adaptive_boost

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

            # Skip if cover is currently moving to prevent oscillation
            # Wait for current movement to complete before issuing new command
            if cover_state.state in ["opening", "closing"]:
                _LOGGER.debug(
                    "Cover %s for room %s is currently %s, skipping position update to avoid oscillation",
                    cover_entity, room_name, cover_state.state
                )
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
                # To turn OFF in cooling mode, we must have OVERCOOLED
                # avg_temp must be below target by turn_off_threshold
                # AND max room temp must also be at or below target (all rooms satisfied)
                # This prevents turning off when we just haven't reached target yet
                max_temp = max(temps)
                overcooled = (temp_diff <= -self.ac_turn_off_threshold and max_temp <= effective_target)
                if overcooled:
                    _LOGGER.info("AC turn OFF (overcooled): avg=%.1f°C (%.1f°C below target), max=%.1f°C",
                                 avg_temp, abs(temp_diff), max_temp)
                return not overcooled
            else:
                # To turn ON in cooling mode, avg temp must be above target
                turn_on = temp_diff >= self.ac_turn_on_threshold
                if turn_on:
                    _LOGGER.info("AC turn ON (too hot): avg=%.1f°C (+%.1f°C above target)", avg_temp, temp_diff)
                return turn_on

        elif self.hvac_mode == "heat":
            if ac_currently_on:
                # To turn OFF in heating mode, we must have OVERHEATED
                # avg_temp must be above target by turn_off_threshold
                # AND min room temp must also be at or above target (all rooms satisfied)
                # This prevents turning off when we just haven't reached target yet
                min_temp = min(temps)
                overheated = (temp_diff >= self.ac_turn_off_threshold and min_temp >= effective_target)
                if overheated:
                    _LOGGER.info("AC turn OFF (overheated): avg=%.1f°C (+%.1f°C above target), min=%.1f°C",
                                 avg_temp, temp_diff, min_temp)
                return not overheated
            else:
                # To turn ON in heating mode, avg temp must be below target
                turn_on = temp_diff <= -self.ac_turn_on_threshold
                if turn_on:
                    _LOGGER.info("AC turn ON (too cold): avg=%.1f°C (%.1f°C below target)", avg_temp, abs(temp_diff))
                return turn_on
        else:  # auto mode
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
                    # Persist timestamp for compressor protection across restarts
                    await self._save_compressor_state()
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
                    # Persist timestamp for compressor protection across restarts
                    await self._save_compressor_state()
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
