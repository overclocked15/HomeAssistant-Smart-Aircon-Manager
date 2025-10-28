"""Logic-based Manager for Aircon control."""
from __future__ import annotations

import logging
import time
from typing import Any

from homeassistant.core import HomeAssistant

_LOGGER = logging.getLogger(__name__)


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
        self.target_temperature = target_temperature
        self.room_configs = room_configs
        self.main_climate_entity = main_climate_entity
        self.main_fan_entity = main_fan_entity
        self.temperature_deadband = temperature_deadband
        self.hvac_mode = hvac_mode
        self.auto_control_main_ac = auto_control_main_ac
        self.auto_control_ac_temperature = auto_control_ac_temperature
        self.enable_notifications = enable_notifications
        self.room_overrides = room_overrides or {}
        self.config_entry = config_entry
        self.ac_turn_on_threshold = ac_turn_on_threshold
        self.ac_turn_off_threshold = ac_turn_off_threshold
        self.weather_entity = weather_entity
        self.enable_weather_adjustment = enable_weather_adjustment
        self.outdoor_temp_sensor = outdoor_temp_sensor
        self.enable_scheduling = enable_scheduling
        self.schedules = schedules or []
        self.main_fan_high_threshold = main_fan_high_threshold
        self.main_fan_medium_threshold = main_fan_medium_threshold
        self.weather_influence_factor = weather_influence_factor
        self.overshoot_tier1_threshold = overshoot_tier1_threshold
        self.overshoot_tier2_threshold = overshoot_tier2_threshold
        self.overshoot_tier3_threshold = overshoot_tier3_threshold
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

    async def async_setup(self) -> None:
        """Set up the optimizer."""
        self._startup_time = time.time()
        _LOGGER.info("Smart Aircon Manager optimizer initialized (logic-based, no AI required)")

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
        """Run optimization cycle."""
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

            if temp_state and temp_state.state not in ["unknown", "unavailable", "none", None]:
                try:
                    current_temp = float(temp_state.state)
                    unit = temp_state.attributes.get("unit_of_measurement", "°C")
                    
                    if unit in ["°F", "fahrenheit", "F"]:
                        current_temp = (current_temp - 32) * 5.0 / 9.0
                        _LOGGER.info("Converted temperature for %s from F to C: %.1f°C", room_name, current_temp)
                except (ValueError, TypeError) as e:
                    _LOGGER.warning("Could not convert temperature for %s: %s", room_name, e)

            cover_state = self.hass.states.get(cover_entity)
            cover_position = 100
            if cover_state:
                try:
                    if "current_position" in cover_state.attributes:
                        pos = cover_state.attributes.get("current_position")
                        if pos not in ["unknown", "unavailable", "none", None]:
                            cover_position = int(pos)
                except (ValueError, TypeError) as e:
                    _LOGGER.warning("Could not convert cover position for %s: %s", room_name, e)

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

            fan_speed = self._calculate_fan_speed(temp_diff, abs_temp_diff)
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

            try:
                await self.hass.services.async_call(
                    "cover",
                    "set_cover_position",
                    {"entity_id": cover_entity, "position": position},
                    blocking=True,
                )
                _LOGGER.info("Set cover position for %s (%s) to %d%%", room_name, cover_entity, position)
            except Exception as e:
                _LOGGER.error("Error setting cover position for %s: %s", room_name, e)
                self._last_error = f"Cover Control Error ({room_name}): {e}"
                self._error_count += 1
                await self._send_notification("Cover Control Error", f"Failed to set fan speed for {room_name}: {e}")

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

        try:
            if self.main_fan_entity.startswith("climate."):
                await self.hass.services.async_call(
                    "climate",
                    "set_fan_mode",
                    {"entity_id": self.main_fan_entity, "fan_mode": fan_speed},
                    blocking=True,
                )
            else:
                await self.hass.services.async_call(
                    "fan",
                    "set_preset_mode",
                    {"entity_id": self.main_fan_entity, "preset_mode": fan_speed},
                    blocking=True,
                )
            _LOGGER.info("Set main fan (%s) to %s", self.main_fan_entity, fan_speed)
        except Exception as e:
            _LOGGER.error("Error setting main fan speed: %s", e)
            await self._send_notification("Main Fan Error", f"Failed to set main fan speed: {e}")

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

        try:
            if needs_ac:
                if current_mode == "off":
                    target_mode = self.hvac_mode if self.hvac_mode != "auto" else "cool"
                    _LOGGER.info("Turning ON main AC (mode: %s)", target_mode)
                    await self.hass.services.async_call(
                        "climate",
                        "set_hvac_mode",
                        {"entity_id": self.main_climate_entity, "hvac_mode": target_mode},
                        blocking=True,
                    )
                    await self._send_notification("AC Turned On", f"Smart Manager turned on AC in {target_mode} mode")
            else:
                if current_mode and current_mode != "off":
                    _LOGGER.info("Turning OFF main AC")
                    await self.hass.services.async_call(
                        "climate",
                        "set_hvac_mode",
                        {"entity_id": self.main_climate_entity, "hvac_mode": "off"},
                        blocking=True,
                    )
                    await self._send_notification("AC Turned Off", "Smart Manager turned off AC (rooms at target)")
        except Exception as e:
            _LOGGER.error("Error controlling main AC: %s", e)
            self._last_error = f"AC Control Error: {e}"
            self._error_count += 1
            await self._send_notification("AC Control Error", f"Failed to control main AC: {e}")

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
            await self.hass.services.async_call(
                "climate",
                "set_temperature",
                {"entity_id": self.main_climate_entity, "temperature": temperature},
                blocking=True,
            )
        except Exception as e:
            _LOGGER.error("Error setting AC temperature: %s", e)
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
        _LOGGER.info("AirconOptimizer cleanup completed")
