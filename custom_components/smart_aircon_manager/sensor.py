"""Sensor platform for Smart Aircon Manager integration."""
from __future__ import annotations

import logging
from typing import Any

from homeassistant.components.sensor import (
    SensorDeviceClass,
    SensorEntity,
    SensorStateClass,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import PERCENTAGE, UnitOfTemperature
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import DOMAIN

_LOGGER = logging.getLogger(__name__)


class AirconManagerSensorBase(CoordinatorEntity, SensorEntity):
    """Base class for Smart Aircon Manager sensors with device info."""

    def __init__(self, coordinator, config_entry: ConfigEntry, optimizer=None) -> None:
        """Initialize the base sensor."""
        super().__init__(coordinator)
        self._config_entry = config_entry
        self._optimizer = optimizer

    @property
    def device_info(self):
        """Return device information."""
        from . import get_device_info
        return get_device_info(self._config_entry)


async def async_setup_entry(
    hass: HomeAssistant,
    config_entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up the Smart Aircon Manager sensor platform."""
    _LOGGER.info(
        "Setting up Smart Aircon Manager sensor platform for entry_id: %s",
        config_entry.entry_id
    )

    coordinator = hass.data[DOMAIN][config_entry.entry_id]["coordinator"]
    optimizer = hass.data[DOMAIN][config_entry.entry_id]["optimizer"]

    _LOGGER.info("Room configs: %s", optimizer.room_configs)

    entities = []

    # Add room-specific diagnostic sensors
    for room_config in optimizer.room_configs:
        room_name = room_config["room_name"]
        _LOGGER.info("Creating sensors for room: %s", room_name)

        # Temperature difference sensor
        try:
            sensor = RoomTemperatureDifferenceSensor(coordinator, config_entry, room_name, optimizer)
            entities.append(sensor)
            _LOGGER.info("Created RoomTemperatureDifferenceSensor for %s", room_name)
        except Exception as e:
            _LOGGER.error("Failed to create RoomTemperatureDifferenceSensor for %s: %s", room_name, e, exc_info=True)

        # Fan speed recommendation sensor
        try:
            sensor = RoomFanRecommendationSensor(coordinator, config_entry, room_name)
            entities.append(sensor)
            _LOGGER.info("Created RoomFanRecommendationSensor for %s", room_name)
        except Exception as e:
            _LOGGER.error("Failed to create RoomFanRecommendationSensor for %s: %s", room_name, e, exc_info=True)

        # Fan speed sensor
        try:
            sensor = RoomFanSpeedSensor(coordinator, config_entry, room_name)
            entities.append(sensor)
            _LOGGER.info("Created RoomFanSpeedSensor for %s", room_name)
        except Exception as e:
            _LOGGER.error("Failed to create RoomFanSpeedSensor for %s: %s", room_name, e, exc_info=True)

    # Add overall status sensor
    entities.append(OptimizationStatusSensor(coordinator, config_entry))

    # Add last optimization response sensor for debugging
    entities.append(LastResponseSensor(coordinator, config_entry))

    # Add main fan speed sensor if configured
    if optimizer.main_fan_entity:
        entities.append(MainFanSpeedSensor(coordinator, config_entry))

    # Add debug sensors
    entities.append(SystemStatusDebugSensor(coordinator, config_entry))
    entities.append(LastOptimizationTimeSensor(coordinator, config_entry))
    entities.append(LastActualOptimizationSensor(coordinator, config_entry))
    entities.append(NextOptimizationTimeSensor(coordinator, config_entry))
    entities.append(ErrorTrackingSensor(coordinator, config_entry))
    entities.append(ValidSensorsCountSensor(coordinator, config_entry))

    # Add performance metrics sensors
    entities.append(OptimizationCycleTimeSensor(coordinator, config_entry))
    entities.append(ErrorRateSensor(coordinator, config_entry))
    entities.append(TotalOptimizationsRunSensor(coordinator, config_entry))
    entities.append(SensorDataQualitySensor(coordinator, config_entry))

    # Add adaptive learning sensors (if learning is enabled)
    _LOGGER.debug(
        "Checking learning sensors: learning_manager=%s, enabled=%s",
        optimizer.learning_manager is not None,
        optimizer.learning_manager.enabled if optimizer.learning_manager else "N/A"
    )
    if optimizer.learning_manager and optimizer.learning_manager.enabled:
        _LOGGER.info("Creating learning sensors for %d rooms", len(optimizer.room_configs))
        for room_config in optimizer.room_configs:
            room_name = room_config["room_name"]
            entities.append(RoomThermalMassSensor(coordinator, config_entry, room_name, optimizer))
            entities.append(RoomCoolingEfficiencySensor(coordinator, config_entry, room_name, optimizer))
            entities.append(RoomLearningConfidenceSensor(coordinator, config_entry, room_name, optimizer))
            entities.append(RoomDataPointsSensor(coordinator, config_entry, room_name, optimizer))
            entities.append(RoomOvershootRateSensor(coordinator, config_entry, room_name, optimizer))
    else:
        _LOGGER.info("Learning sensors NOT created - learning is not enabled")

    # Add main fan speed recommendation debug sensor if configured
    if optimizer.main_fan_entity:
        entities.append(MainFanSpeedRecommendationSensor(coordinator, config_entry))

    # Add AC temperature control sensors if auto control is enabled
    if optimizer.auto_control_ac_temperature and optimizer.main_climate_entity:
        entities.append(ACTemperatureRecommendationSensor(coordinator, config_entry))
        entities.append(ACCurrentTemperatureSensor(coordinator, config_entry))

    # Add weather sensors if weather integration is enabled
    if optimizer.enable_weather_adjustment:
        entities.append(OutdoorTemperatureSensor(coordinator, config_entry))
        entities.append(WeatherAdjustmentSensor(coordinator, config_entry))

    # Add scheduling sensors if scheduling is enabled
    if optimizer.enable_scheduling:
        entities.append(ActiveScheduleSensor(coordinator, config_entry))
        entities.append(EffectiveTargetTemperatureSensor(coordinator, config_entry))

    # Add balancing sensors if balancing is enabled
    if (optimizer.enable_room_balancing and
        optimizer.room_configs and
        isinstance(optimizer.room_configs, list) and
        len(optimizer.room_configs) > 1):
        entities.append(HouseAverageTemperatureSensor(coordinator, config_entry))
        entities.append(RoomTemperatureVarianceSensor(coordinator, config_entry))
        entities.append(BalancingActiveSensor(coordinator, config_entry))

    # Add humidity control sensors if humidity control is enabled
    if optimizer.enable_humidity_control:
        entities.append(HVACModeRecommendationSensor(coordinator, config_entry))
        entities.append(HouseAverageHumiditySensor(coordinator, config_entry))
        entities.append(DryModeActiveSensor(coordinator, config_entry))
        entities.append(FanOnlyModeActiveSensor(coordinator, config_entry))
        entities.append(ComfortIndexSensor(coordinator, config_entry))

    _LOGGER.info("Total entities to add: %d", len(entities))
    _LOGGER.info("Entity unique_ids: %s", [e.unique_id for e in entities if hasattr(e, 'unique_id')])

    async_add_entities(entities)
    _LOGGER.info("Entities added successfully")


class RoomTemperatureDifferenceSensor(AirconManagerSensorBase):
    """Sensor showing temperature difference from target for a room."""

    _attr_device_class = SensorDeviceClass.TEMPERATURE
    _attr_state_class = SensorStateClass.MEASUREMENT
    _attr_native_unit_of_measurement = UnitOfTemperature.CELSIUS

    def __init__(self, coordinator, config_entry: ConfigEntry, room_name: str, optimizer=None) -> None:
        """Initialize the sensor."""
        super().__init__(coordinator, config_entry, optimizer)
        self._room_name = room_name
        # Normalize room name for unique_id (replace spaces with underscores, lowercase)
        room_id = room_name.lower().replace(" ", "_")
        self._attr_unique_id = f"{config_entry.entry_id}_{room_id}_temp_diff"
        self._attr_name = f"{room_name} Temperature Difference"

    @property
    def native_value(self) -> float | None:
        """Return the temperature difference."""
        if not self.coordinator.data:
            return None

        room_states = self.coordinator.data.get("room_states", {})
        if self._room_name not in room_states:
            return None

        state = room_states[self._room_name]
        if state["current_temperature"] is None:
            return None

        diff = state["current_temperature"] - state["target_temperature"]
        return round(diff, 1)

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        """Return additional attributes."""
        if not self.coordinator.data:
            return {}

        room_states = self.coordinator.data.get("room_states", {})
        if self._room_name not in room_states:
            return {}

        state = room_states[self._room_name]
        # Use configured deadband instead of hardcoded 0.5
        deadband = self._optimizer.temperature_deadband if self._optimizer else 0.5
        return {
            "current_temperature": state["current_temperature"],
            "target_temperature": state["target_temperature"],
            "deadband": deadband,
            "status": (
                "too_hot" if state["current_temperature"] and state["current_temperature"] > state["target_temperature"] + deadband
                else "too_cold" if state["current_temperature"] and state["current_temperature"] < state["target_temperature"] - deadband
                else "at_target"
            ),
        }


class RoomFanRecommendationSensor(AirconManagerSensorBase):
    """Sensor showing fan speed recommendation for a room."""

    _attr_native_unit_of_measurement = PERCENTAGE
    _attr_state_class = SensorStateClass.MEASUREMENT

    def __init__(self, coordinator, config_entry: ConfigEntry, room_name: str) -> None:
        """Initialize the sensor."""
        super().__init__(coordinator, config_entry)
        self._room_name = room_name
        # Normalize room name for unique_id (replace spaces with underscores, lowercase)
        room_id = room_name.lower().replace(" ", "_")
        self._attr_unique_id = f"{config_entry.entry_id}_{room_id}_fan_recommendation"
        self._attr_name = f"{room_name} Fan Speed Recommendation"

    @property
    def native_value(self) -> int | None:
        """Return the recommended fan speed."""
        if not self.coordinator.data:
            return None

        recommendations = self.coordinator.data.get("recommendations", {})
        return recommendations.get(self._room_name)

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        """Return additional attributes."""
        if not self.coordinator.data:
            return {}

        room_states = self.coordinator.data.get("room_states", {})
        recommendations = self.coordinator.data.get("recommendations", {})

        if self._room_name not in room_states:
            return {}

        state = room_states[self._room_name]
        current_position = state["cover_position"]
        recommended = recommendations.get(self._room_name, current_position)

        change = recommended - current_position if recommended is not None else 0

        return {
            "current_fan_speed": current_position,
            "recommended_fan_speed": recommended,
            "change": change,
            "action": (
                "increasing" if change > 0
                else "decreasing" if change < 0
                else "no_change"
            ),
        }


class RoomFanSpeedSensor(AirconManagerSensorBase):
    """Sensor showing current fan speed for a room."""

    _attr_native_unit_of_measurement = PERCENTAGE
    _attr_state_class = SensorStateClass.MEASUREMENT

    def __init__(self, coordinator, config_entry: ConfigEntry, room_name: str) -> None:
        """Initialize the sensor."""
        super().__init__(coordinator, config_entry)
        self._room_name = room_name
        # Normalize room name for unique_id (replace spaces with underscores, lowercase)
        room_id = room_name.lower().replace(" ", "_")
        self._attr_unique_id = f"{config_entry.entry_id}_{room_id}_fan_speed"
        self._attr_name = f"{room_name} Fan Speed"

    @property
    def native_value(self) -> int | None:
        """Return the current fan speed."""
        if not self.coordinator.data:
            return None

        room_states = self.coordinator.data.get("room_states", {})
        if self._room_name not in room_states:
            return None

        return room_states[self._room_name]["cover_position"]


class OptimizationStatusSensor(AirconManagerSensorBase):
    """Sensor showing overall optimization status."""

    def __init__(self, coordinator, config_entry: ConfigEntry) -> None:
        """Initialize the sensor."""
        super().__init__(coordinator, config_entry)
        self._attr_unique_id = f"{config_entry.entry_id}_optimization_status"
        self._attr_name = "Optimization Status"

    @property
    def native_value(self) -> str:
        """Return the optimization status."""
        if not self.coordinator.data:
            return "unknown"

        room_states = self.coordinator.data.get("room_states", {})
        if not room_states:
            return "no_data"

        # Check if all rooms are at target
        all_at_target = True
        any_too_hot = False
        any_too_cold = False

        for state in room_states.values():
            if state["current_temperature"] is None:
                continue

            diff = state["current_temperature"] - state["target_temperature"]
            if abs(diff) > 0.5:
                all_at_target = False
                if diff > 0:
                    any_too_hot = True
                else:
                    any_too_cold = True

        if all_at_target:
            return "maintaining"
        elif any_too_hot and any_too_cold:
            return "equalizing"
        elif any_too_hot:
            return "cooling"
        else:
            return "reducing_cooling"

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        """Return additional attributes."""
        if not self.coordinator.data:
            return {}

        room_states = self.coordinator.data.get("room_states", {})
        recommendations = self.coordinator.data.get("recommendations", {})

        temps = [
            state["current_temperature"]
            for state in room_states.values()
            if state["current_temperature"] is not None
        ]

        if not temps:
            return {}

        avg_temp = sum(temps) / len(temps)
        max_temp = max(temps)
        min_temp = min(temps)
        temp_variance = max_temp - min_temp

        return {
            "average_temperature": round(avg_temp, 1),
            "max_temperature": round(max_temp, 1),
            "min_temperature": round(min_temp, 1),
            "temperature_variance": round(temp_variance, 1),
            "rooms_count": len(room_states),
            "recommendations_count": len(recommendations),
            "last_update_success": self.coordinator.last_update_success,
        }


class LastResponseSensor(AirconManagerSensorBase):
    """Sensor showing the last optimization response for debugging."""

    def __init__(self, coordinator, config_entry: ConfigEntry) -> None:
        """Initialize the sensor."""
        super().__init__(coordinator, config_entry)
        self._attr_unique_id = f"{config_entry.entry_id}_last_response"
        self._attr_name = "Last Optimization Response"

    @property
    def native_value(self) -> str:
        """Return the last optimization response status."""
        if not self.coordinator.data:
            return "no_data"

        recommendations = self.coordinator.data.get("recommendations", {})
        if not recommendations:
            return "no_recommendations"

        return "success"

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        """Return additional attributes."""
        if not self.coordinator.data:
            return {}

        return {
            "raw_recommendations": self.coordinator.data.get("recommendations", {}),
            "optimization_response_text": self.coordinator.data.get("optimization_response_text", ""),
        }


class MainFanSpeedSensor(AirconManagerSensorBase):
    """Sensor showing the main aircon fan speed set by AI."""

    def __init__(self, coordinator, config_entry: ConfigEntry) -> None:
        """Initialize the sensor."""
        super().__init__(coordinator, config_entry)
        self._attr_unique_id = f"{config_entry.entry_id}_main_fan_speed"
        self._attr_name = "Main Aircon Fan Speed"
        self._attr_icon = "mdi:fan"

    @property
    def native_value(self) -> str:
        """Return the main fan speed."""
        if not self.coordinator.data:
            return "unknown"

        return self.coordinator.data.get("main_fan_speed", "unknown")

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        """Return additional attributes."""
        if not self.coordinator.data:
            return {}

        room_states = self.coordinator.data.get("room_states", {})

        temps = [
            state["current_temperature"]
            for state in room_states.values()
            if state["current_temperature"] is not None
        ]

        if not temps:
            return {}

        avg_temp = sum(temps) / len(temps)
        max_temp = max(temps)
        min_temp = min(temps)
        temp_variance = max_temp - min_temp

        target_temp = next(iter(room_states.values()))["target_temperature"] if room_states else None
        avg_deviation = abs(avg_temp - target_temp) if target_temp else None

        return {
            "temperature_variance": round(temp_variance, 1),
            "average_deviation_from_target": round(avg_deviation, 1) if avg_deviation else None,
            "logic": (
                "Low: variance ≤1°C and deviation ≤0.5°C (maintaining)\n"
                "High: max deviation ≥3°C or variance ≥3°C (aggressive cooling)\n"
                "Medium: All other cases (moderate cooling/equalizing)"
            ),
        }


class MainFanSpeedRecommendationSensor(AirconManagerSensorBase):
    """Debug sensor showing the AI's recommendation for main fan speed."""

    def __init__(self, coordinator, config_entry: ConfigEntry) -> None:
        """Initialize the sensor."""
        super().__init__(coordinator, config_entry)
        self._attr_unique_id = f"{config_entry.entry_id}_main_fan_recommendation_debug"
        self._attr_name = "Main Fan Speed Fan Speed Recommendation"
        self._attr_icon = "mdi:fan-alert"

    @property
    def native_value(self) -> str:
        """Return the recommended fan speed."""
        if not self.coordinator.data:
            return "unknown"

        # First check if optimizer calculated it
        main_fan_speed = self.coordinator.data.get("main_fan_speed")
        if main_fan_speed:
            return main_fan_speed

        # Otherwise calculate it ourselves for debug purposes
        room_states = self.coordinator.data.get("room_states", {})

        if not room_states:
            return "no_room_data"

        # Use .get() to safely access current_temperature
        temps = [
            state.get("current_temperature")
            for state in room_states.values()
            if state.get("current_temperature") is not None
        ]

        if not temps:
            return "no_valid_temps"

        # Get target temp from first room (they all share same target)
        first_room = next(iter(room_states.values()), None)
        if not first_room:
            return "no_rooms"

        target_temp = first_room.get("target_temperature")
        if not target_temp:
            return "no_target_temp"

        # Get HVAC mode from climate state
        main_climate_state = self.coordinator.data.get("main_climate_state", {})
        hvac_mode = main_climate_state.get("hvac_mode", "cool") if main_climate_state else "cool"

        # Calculate fan speed using same logic as optimizer
        avg_temp = sum(temps) / len(temps)
        max_temp = max(temps)
        min_temp = min(temps)
        temp_variance = max_temp - min_temp
        avg_temp_diff = avg_temp - target_temp  # Positive = too hot, Negative = too cold
        avg_deviation = abs(avg_temp_diff)
        max_temp_diff = max(temp - target_temp for temp in temps)
        min_temp_diff = min(temp - target_temp for temp in temps)

        # Check if at target (maintaining)
        if temp_variance <= 1.0 and avg_deviation <= 0.5:
            return "low"
        # Mode-aware fan speed logic
        elif hvac_mode == "cool":
            # In cool mode: high fan only if temps are ABOVE target
            if avg_temp_diff >= 3.0 or (max_temp_diff >= 3.0 and temp_variance >= 2.0):
                return "high"
            elif avg_temp_diff <= -1.0:
                # Temps below target in cool mode - reduce cooling
                return "low"
            else:
                return "medium"
        elif hvac_mode == "heat":
            # In heat mode: high fan only if temps are BELOW target
            if avg_temp_diff <= -3.0 or (min_temp_diff <= -3.0 and temp_variance >= 2.0):
                return "high"
            elif avg_temp_diff >= 1.0:
                # Temps above target in heat mode - reduce heating
                return "low"
            else:
                return "medium"
        else:
            # Auto mode or unknown - use deviation magnitude
            max_deviation = max(abs(max_temp_diff), abs(min_temp_diff))
            if max_deviation >= 3.0 or temp_variance >= 3.0:
                return "high"
            else:
                return "medium"

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        """Return detailed debug attributes."""
        if not self.coordinator.data:
            return {"status": "no_coordinator_data"}

        room_states = self.coordinator.data.get("room_states", {})

        if not room_states:
            return {"status": "no_room_states", "coordinator_data_keys": list(self.coordinator.data.keys())}

        # Use .get() to safely access current_temperature
        temps = [
            state.get("current_temperature")
            for state in room_states.values()
            if state.get("current_temperature") is not None
        ]

        if not temps:
            # Provide debug info about why no temps
            all_temps = {room: state.get("current_temperature") for room, state in room_states.items()}
            return {
                "status": "no_valid_temperatures",
                "room_count": len(room_states),
                "room_temperatures": all_temps,
            }

        avg_temp = sum(temps) / len(temps)
        max_temp = max(temps)
        min_temp = min(temps)
        temp_variance = max_temp - min_temp

        first_room = next(iter(room_states.values()), None)
        target_temp = first_room.get("target_temperature") if first_room else None
        avg_deviation = abs(avg_temp - target_temp) if target_temp else None
        max_deviation = max(abs(temp - target_temp) for temp in temps) if target_temp else None

        return {
            "average_temperature": round(avg_temp, 1),
            "temperature_variance": round(temp_variance, 1),
            "average_deviation": round(avg_deviation, 1) if avg_deviation else None,
            "max_deviation": round(max_deviation, 1) if max_deviation else None,
            "decision_criteria": {
                "low": "variance ≤1°C AND avg_deviation ≤0.5°C",
                "high": "max_deviation ≥3°C OR variance ≥3°C",
                "medium": "all other cases",
            },
            "current_values_meet": self._evaluate_criteria(temp_variance, avg_deviation, max_deviation),
        }

    def _evaluate_criteria(self, variance, avg_dev, max_dev):
        """Evaluate which criteria are met."""
        if avg_dev is None or max_dev is None:
            return "no_data"

        criteria = []
        if variance <= 1.0 and avg_dev <= 0.5:
            criteria.append("low_criteria")
        if max_dev >= 3.0 or variance >= 3.0:
            criteria.append("high_criteria")
        if not criteria:
            criteria.append("medium_criteria")

        return ", ".join(criteria)


class SystemStatusDebugSensor(AirconManagerSensorBase):
    """Debug sensor showing overall system status."""

    def __init__(self, coordinator, config_entry: ConfigEntry) -> None:
        """Initialize the sensor."""
        super().__init__(coordinator, config_entry)
        self._attr_unique_id = f"{config_entry.entry_id}_system_status_debug"
        self._attr_name = "System Status Debug"
        self._attr_icon = "mdi:bug"

    @property
    def native_value(self) -> str:
        """Return the system status."""
        if not self.coordinator.data:
            return "no_data"

        main_ac_running = self.coordinator.data.get("main_ac_running", False)
        needs_ac = self.coordinator.data.get("needs_ac", False)
        error = self.coordinator.data.get("last_error")

        if error:
            return "error"
        elif not main_ac_running and needs_ac:
            return "ac_needed_but_off"
        elif main_ac_running and not needs_ac:
            return "ac_running_but_not_needed"
        elif main_ac_running:
            return "optimizing"
        else:
            return "idle"

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        """Return detailed debug attributes."""
        if not self.coordinator.data:
            return {}

        return {
            "main_ac_running": self.coordinator.data.get("main_ac_running", "unknown"),
            "needs_ac": self.coordinator.data.get("needs_ac", "unknown"),
            "last_error": self.coordinator.data.get("last_error"),
            "error_count": self.coordinator.data.get("error_count", 0),
            "has_recommendations": bool(self.coordinator.data.get("recommendations")),
            "recommendation_count": len(self.coordinator.data.get("recommendations", {})),
            "ai_response_available": bool(self.coordinator.data.get("optimization_response_text")),
            "main_climate_state": self.coordinator.data.get("main_climate_state"),
        }


class LastOptimizationTimeSensor(AirconManagerSensorBase):
    """Sensor showing when last optimization ran."""

    _attr_device_class = SensorDeviceClass.TIMESTAMP

    def __init__(self, coordinator, config_entry: ConfigEntry) -> None:
        """Initialize the sensor."""
        super().__init__(coordinator, config_entry)
        self._attr_unique_id = f"{config_entry.entry_id}_last_optimization_time"
        self._attr_name = "Last Data Update Time"
        self._attr_icon = "mdi:clock-check"

    @property
    def native_value(self):
        """Return the last successful update time."""
        # Use coordinator's internal last update time
        from datetime import datetime, timezone
        if hasattr(self.coordinator, '_last_update_time'):
            return self.coordinator._last_update_time
        # Fallback: return current time if data exists, None otherwise
        if self.coordinator.data:
            return datetime.now(timezone.utc)
        return None

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        """Return additional attributes."""
        from datetime import datetime, timezone
        import time

        attrs = {
            "last_update_success": self.coordinator.last_update_success,
            "update_interval_minutes": self.coordinator.update_interval.total_seconds() / 60 if self.coordinator.update_interval else None,
        }

        # Calculate next update time if possible
        if hasattr(self.coordinator, '_last_update_time') and self.coordinator.update_interval:
            try:
                last_time = self.coordinator._last_update_time
                if last_time:
                    next_update = last_time + self.coordinator.update_interval
                    now = datetime.now(timezone.utc)
                    seconds_until = (next_update - now).total_seconds()
                    attrs["next_update_in_seconds"] = max(0, seconds_until)
            except Exception:
                attrs["next_update_in_seconds"] = None
        else:
            attrs["next_update_in_seconds"] = None

        return attrs


class LastActualOptimizationSensor(AirconManagerSensorBase):
    """Sensor showing when last optimization ran (not just coordinator updates)."""

    _attr_device_class = SensorDeviceClass.TIMESTAMP

    def __init__(self, coordinator, config_entry: ConfigEntry) -> None:
        """Initialize the sensor."""
        super().__init__(coordinator, config_entry)
        self._attr_unique_id = f"{config_entry.entry_id}_last_actual_optimization"
        self._attr_name = "Last Actual Optimization"
        self._attr_icon = "mdi:brain"

    @property
    def native_value(self):
        """Return the last optimization time."""
        from datetime import datetime, timezone

        if not self.coordinator.data:
            return None

        # Get optimizer from hass data
        from .const import DOMAIN
        entry_data = self.coordinator.hass.data.get(DOMAIN, {}).get(self._config_entry.entry_id, {})
        optimizer = entry_data.get("optimizer")

        if not optimizer:
            return None

        # Get actual optimization timestamp
        if hasattr(optimizer, '_last_optimization') and optimizer._last_optimization:
            return datetime.fromtimestamp(optimizer._last_optimization, tz=timezone.utc)

        return None

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        """Return additional attributes."""
        import time

        if not self.coordinator.data:
            return {}

        # Get optimizer from hass data
        from .const import DOMAIN
        entry_data = self.coordinator.hass.data.get(DOMAIN, {}).get(self._config_entry.entry_id, {})
        optimizer = entry_data.get("optimizer")

        if not optimizer:
            return {"status": "optimizer_not_found"}

        attrs = {}

        if hasattr(optimizer, '_last_optimization') and optimizer._last_optimization:
            current_time = time.time()
            seconds_since = current_time - optimizer._last_optimization
            attrs["seconds_since_last_ai_run"] = round(seconds_since, 1)
            attrs["minutes_since_last_ai_run"] = round(seconds_since / 60, 2)
        else:
            attrs["seconds_since_last_ai_run"] = None
            attrs["status"] = "never_run"

        return attrs


class NextOptimizationTimeSensor(AirconManagerSensorBase):
    """Sensor showing when next optimization will run."""

    _attr_device_class = SensorDeviceClass.TIMESTAMP

    def __init__(self, coordinator, config_entry: ConfigEntry) -> None:
        """Initialize the sensor."""
        super().__init__(coordinator, config_entry)
        self._attr_unique_id = f"{config_entry.entry_id}_next_optimization_time"
        self._attr_name = "Next Optimization Time"
        self._attr_icon = "mdi:clock-outline"

    @property
    def native_value(self):
        """Return the next optimization time."""
        from datetime import datetime, timezone, timedelta

        if not self.coordinator.data:
            return None

        # Get optimizer from hass data
        from .const import DOMAIN
        entry_data = self.coordinator.hass.data.get(DOMAIN, {}).get(self._config_entry.entry_id, {})
        optimizer = entry_data.get("optimizer")

        if not optimizer:
            return None

        # Calculate next optimization time
        if hasattr(optimizer, '_last_optimization') and optimizer._last_optimization:
            last_opt_timestamp = optimizer._last_optimization
            interval_seconds = optimizer._optimization_interval
            next_opt_timestamp = last_opt_timestamp + interval_seconds

            # Convert to datetime
            next_opt_dt = datetime.fromtimestamp(next_opt_timestamp, tz=timezone.utc)
            return next_opt_dt

        return None

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        """Return additional attributes."""
        from datetime import datetime, timezone
        import time

        if not self.coordinator.data:
            return {}

        # Get optimizer from hass data
        from .const import DOMAIN
        entry_data = self.coordinator.hass.data.get(DOMAIN, {}).get(self._config_entry.entry_id, {})
        optimizer = entry_data.get("optimizer")

        if not optimizer:
            return {"status": "optimizer_not_found"}

        attrs = {
            "optimization_interval_seconds": optimizer._optimization_interval if hasattr(optimizer, '_optimization_interval') else None,
            "optimization_interval_minutes": (optimizer._optimization_interval / 60) if hasattr(optimizer, '_optimization_interval') else None,
        }

        # Calculate time until next optimization
        if hasattr(optimizer, '_last_optimization') and optimizer._last_optimization:
            current_time = time.time()
            time_since_last = current_time - optimizer._last_optimization
            time_until_next = optimizer._optimization_interval - time_since_last

            attrs["seconds_until_next"] = max(0, time_until_next)
            attrs["minutes_until_next"] = max(0, time_until_next / 60)
            attrs["seconds_since_last"] = time_since_last
            attrs["will_run_next_cycle"] = time_until_next <= 0
        else:
            attrs["seconds_until_next"] = 0
            attrs["will_run_next_cycle"] = True  # First run

        return attrs


class ErrorTrackingSensor(AirconManagerSensorBase):
    """Sensor tracking errors and warnings."""

    def __init__(self, coordinator, config_entry: ConfigEntry) -> None:
        """Initialize the sensor."""
        super().__init__(coordinator, config_entry)
        self._attr_unique_id = f"{config_entry.entry_id}_error_tracking"
        self._attr_name = "Error Tracking"
        self._attr_icon = "mdi:alert-circle"

    @property
    def native_value(self) -> int:
        """Return the error count."""
        if not self.coordinator.data:
            return 0
        return self.coordinator.data.get("error_count", 0)

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        """Return error details."""
        if not self.coordinator.data:
            return {}

        return {
            "last_error": self.coordinator.data.get("last_error"),
            "status": "errors_present" if self.coordinator.data.get("error_count", 0) > 0 else "no_errors",
        }


class ValidSensorsCountSensor(AirconManagerSensorBase):
    """Sensor showing count of valid temperature sensors."""

    def __init__(self, coordinator, config_entry: ConfigEntry) -> None:
        """Initialize the sensor."""
        super().__init__(coordinator, config_entry)
        self._attr_unique_id = f"{config_entry.entry_id}_valid_sensors_count"
        self._attr_name = "Valid Sensors Count"
        self._attr_icon = "mdi:thermometer-check"

    @property
    def native_value(self) -> int:
        """Return count of valid sensors."""
        if not self.coordinator.data:
            return 0

        room_states = self.coordinator.data.get("room_states", {})
        valid_count = sum(
            1 for state in room_states.values()
            if state.get("current_temperature") is not None
        )
        return valid_count

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        """Return sensor details."""
        if not self.coordinator.data:
            return {"status": "no_coordinator_data"}

        room_states = self.coordinator.data.get("room_states", {})

        if not room_states:
            return {
                "status": "no_room_states",
                "coordinator_data_keys": list(self.coordinator.data.keys()) if self.coordinator.data else [],
            }

        total_rooms = len(room_states)

        invalid_sensors = [
            room_name for room_name, state in room_states.items()
            if state.get("current_temperature") is None
        ]

        # Debug info: show what each sensor's temp is
        sensor_temps = {
            room_name: state.get("current_temperature")
            for room_name, state in room_states.items()
        }

        return {
            "total_rooms": total_rooms,
            "valid_sensors": self.native_value,
            "invalid_sensors": invalid_sensors,
            "all_sensors_valid": len(invalid_sensors) == 0,
            "percentage_valid": round((self.native_value / total_rooms * 100), 1) if total_rooms > 0 else 0,
            "sensor_temperatures": sensor_temps,
        }


class ACTemperatureRecommendationSensor(AirconManagerSensorBase):
    """Sensor showing AI's recommended AC temperature."""

    _attr_device_class = SensorDeviceClass.TEMPERATURE
    _attr_state_class = SensorStateClass.MEASUREMENT
    _attr_native_unit_of_measurement = UnitOfTemperature.CELSIUS

    def __init__(self, coordinator, config_entry: ConfigEntry) -> None:
        """Initialize the sensor."""
        super().__init__(coordinator, config_entry)
        self._attr_unique_id = f"{config_entry.entry_id}_ac_temp_recommendation"
        self._attr_name = "AC Temperature Recommendation"
        self._attr_icon = "mdi:thermostat-auto"

    @property
    def native_value(self) -> float | None:
        """Return the AI's recommended AC temperature."""
        if not self.coordinator.data:
            return None

        recommendations = self.coordinator.data.get("recommendations", {})
        return recommendations.get("ac_temperature")

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        """Return additional attributes."""
        if not self.coordinator.data:
            return {}

        room_states = self.coordinator.data.get("room_states", {})

        # Calculate average room temperature and deviation from target
        temps = [s.get("current_temperature") for s in room_states.values() if s.get("current_temperature") is not None]
        avg_temp = sum(temps) / len(temps) if temps else None

        # Get target temperature from first room (they all use the same target)
        target_temp = None
        for state in room_states.values():
            if state.get("target_temperature") is not None:
                target_temp = state.get("target_temperature")
                break

        attrs = {
            "average_room_temperature": round(avg_temp, 1) if avg_temp else None,
            "target_temperature": target_temp,
            "has_recommendation": self.native_value is not None,
        }

        if avg_temp and target_temp:
            deviation = avg_temp - target_temp
            attrs["temperature_deviation"] = round(deviation, 1)

            # Determine control mode
            if deviation > 2:
                attrs["control_mode"] = "aggressive_cooling" if avg_temp > target_temp else "aggressive_heating"
            elif abs(deviation) > 0.5:
                attrs["control_mode"] = "moderate"
            else:
                attrs["control_mode"] = "maintenance"

        return attrs


class ACCurrentTemperatureSensor(AirconManagerSensorBase):
    """Sensor showing current AC temperature setpoint."""

    _attr_device_class = SensorDeviceClass.TEMPERATURE
    _attr_state_class = SensorStateClass.MEASUREMENT
    _attr_native_unit_of_measurement = UnitOfTemperature.CELSIUS

    def __init__(self, coordinator, config_entry: ConfigEntry) -> None:
        """Initialize the sensor."""
        super().__init__(coordinator, config_entry)
        self._attr_unique_id = f"{config_entry.entry_id}_ac_current_temp"
        self._attr_name = "AC Current Temperature"
        self._attr_icon = "mdi:thermostat"

    @property
    def native_value(self) -> float | None:
        """Return the current AC temperature setpoint."""
        if not self.coordinator.data:
            return None

        main_climate = self.coordinator.data.get("main_climate_state")
        if not main_climate:
            return None

        return main_climate.get("temperature")

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        """Return additional attributes."""
        if not self.coordinator.data:
            return {}

        main_climate = self.coordinator.data.get("main_climate_state")
        if not main_climate:
            return {"status": "no_climate_data"}

        recommendations = self.coordinator.data.get("recommendations", {})
        recommended_temp = recommendations.get("ac_temperature")
        current_temp = main_climate.get("temperature")

        attrs = {
            "hvac_mode": main_climate.get("hvac_mode"),
            "hvac_action": main_climate.get("hvac_action"),
            "recommended_temperature": recommended_temp,
        }

        # Calculate if temperature needs updating
        if current_temp and recommended_temp:
            temp_diff = abs(current_temp - recommended_temp)
            attrs["temperature_difference"] = round(temp_diff, 1)
            attrs["needs_update"] = temp_diff >= 0.5
        else:
            attrs["needs_update"] = False

        return attrs



class OutdoorTemperatureSensor(AirconManagerSensorBase):
    """Sensor showing outdoor temperature from weather integration."""

    _attr_device_class = SensorDeviceClass.TEMPERATURE
    _attr_state_class = SensorStateClass.MEASUREMENT
    _attr_native_unit_of_measurement = UnitOfTemperature.CELSIUS

    def __init__(self, coordinator, config_entry: ConfigEntry) -> None:
        """Initialize the sensor."""
        super().__init__(coordinator, config_entry)
        self._attr_unique_id = f"{config_entry.entry_id}_outdoor_temperature"
        self._attr_name = "Outdoor Temperature"

    @property
    def native_value(self) -> float | None:
        """Return the outdoor temperature."""
        if not self.coordinator.data:
            return None
        return self.coordinator.data.get("outdoor_temperature")

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        """Return additional attributes."""
        return {
            "source": "weather_integration",
        }


class WeatherAdjustmentSensor(AirconManagerSensorBase):
    """Sensor showing weather-based temperature adjustment."""

    _attr_device_class = SensorDeviceClass.TEMPERATURE
    _attr_state_class = SensorStateClass.MEASUREMENT
    _attr_native_unit_of_measurement = UnitOfTemperature.CELSIUS

    def __init__(self, coordinator, config_entry: ConfigEntry) -> None:
        """Initialize the sensor."""
        super().__init__(coordinator, config_entry)
        self._attr_unique_id = f"{config_entry.entry_id}_weather_adjustment"
        self._attr_name = "Weather Adjustment"

    @property
    def native_value(self) -> float | None:
        """Return the weather adjustment amount."""
        if not self.coordinator.data:
            return None
        return self.coordinator.data.get("weather_adjustment", 0.0)

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        """Return additional attributes."""
        if not self.coordinator.data:
            return {}

        outdoor_temp = self.coordinator.data.get("outdoor_temperature")
        base_target = self.coordinator.data.get("base_target_temperature")
        effective_target = self.coordinator.data.get("effective_target_temperature")

        return {
            "outdoor_temperature": outdoor_temp,
            "base_target": base_target,
            "effective_target": effective_target,
            "adjustment_applied": self.native_value != 0.0 if self.native_value is not None else False,
        }


class ActiveScheduleSensor(AirconManagerSensorBase):
    """Sensor showing the currently active schedule."""

    def __init__(self, coordinator, config_entry: ConfigEntry) -> None:
        """Initialize the sensor."""
        super().__init__(coordinator, config_entry)
        self._attr_unique_id = f"{config_entry.entry_id}_active_schedule"
        self._attr_name = "Active Schedule"

    @property
    def native_value(self) -> str | None:
        """Return the active schedule name."""
        if not self.coordinator.data:
            return None

        from .const import CONF_SCHEDULE_NAME
        active_schedule = self.coordinator.data.get("active_schedule")
        if active_schedule:
            return active_schedule.get(CONF_SCHEDULE_NAME, "Unnamed Schedule")
        return "None"

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        """Return additional attributes."""
        if not self.coordinator.data:
            return {}

        from .const import (
            CONF_SCHEDULE_NAME,
            CONF_SCHEDULE_DAYS,
            CONF_SCHEDULE_START_TIME,
            CONF_SCHEDULE_END_TIME,
            CONF_SCHEDULE_TARGET_TEMP,
        )

        active_schedule = self.coordinator.data.get("active_schedule")
        if not active_schedule:
            return {"status": "No active schedule"}

        return {
            "schedule_name": active_schedule.get(CONF_SCHEDULE_NAME),
            "days": active_schedule.get(CONF_SCHEDULE_DAYS, []),
            "start_time": active_schedule.get(CONF_SCHEDULE_START_TIME),
            "end_time": active_schedule.get(CONF_SCHEDULE_END_TIME),
            "target_temperature": active_schedule.get(CONF_SCHEDULE_TARGET_TEMP),
            "status": "Active",
        }


class EffectiveTargetTemperatureSensor(AirconManagerSensorBase):
    """Sensor showing the effective target temperature (after schedule and weather adjustments)."""

    _attr_device_class = SensorDeviceClass.TEMPERATURE
    _attr_state_class = SensorStateClass.MEASUREMENT
    _attr_native_unit_of_measurement = UnitOfTemperature.CELSIUS

    def __init__(self, coordinator, config_entry: ConfigEntry) -> None:
        """Initialize the sensor."""
        super().__init__(coordinator, config_entry)
        self._attr_unique_id = f"{config_entry.entry_id}_effective_target_temperature"
        self._attr_name = "Effective Target Temperature"

    @property
    def native_value(self) -> float | None:
        """Return the effective target temperature."""
        if not self.coordinator.data:
            return None
        return self.coordinator.data.get("effective_target_temperature")

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        """Return additional attributes."""
        if not self.coordinator.data:
            return {}

        base_target = self.coordinator.data.get("base_target_temperature")
        weather_adj = self.coordinator.data.get("weather_adjustment", 0.0)
        active_schedule = self.coordinator.data.get("active_schedule")

        attrs = {
            "base_target": base_target,
            "weather_adjustment": weather_adj,
        }

        if active_schedule:
            from .const import CONF_SCHEDULE_NAME, CONF_SCHEDULE_TARGET_TEMP
            attrs["schedule_name"] = active_schedule.get(CONF_SCHEDULE_NAME)
            attrs["schedule_target"] = active_schedule.get(CONF_SCHEDULE_TARGET_TEMP)

        return attrs



class OptimizationCycleTimeSensor(AirconManagerSensorBase):
    """Sensor showing how long the last optimization cycle took."""

    _attr_native_unit_of_measurement = "ms"
    _attr_state_class = SensorStateClass.MEASUREMENT

    def __init__(self, coordinator, config_entry: ConfigEntry) -> None:
        """Initialize the sensor."""
        super().__init__(coordinator, config_entry)
        self._attr_unique_id = f"{config_entry.entry_id}_optimization_cycle_time"
        self._attr_name = "Optimization Cycle Time"
        self._attr_icon = "mdi:timer-outline"

    @property
    def native_value(self) -> float | None:
        """Return the last optimization cycle time in milliseconds."""
        if not self.coordinator.data:
            return None
        return self.coordinator.data.get("optimization_cycle_time_ms")

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        """Return additional attributes."""
        if not self.coordinator.data:
            return {}

        cycle_time = self.coordinator.data.get("optimization_cycle_time_ms")

        attrs = {
            "status": "fast" if cycle_time and cycle_time < 100 else "moderate" if cycle_time and cycle_time < 500 else "slow" if cycle_time else "unknown",
        }

        if cycle_time:
            attrs["cycle_time_seconds"] = round(cycle_time / 1000, 3)

        return attrs


class ErrorRateSensor(AirconManagerSensorBase):
    """Sensor showing error rate (errors per hour)."""

    _attr_native_unit_of_measurement = "errors/hour"
    _attr_state_class = SensorStateClass.MEASUREMENT

    def __init__(self, coordinator, config_entry: ConfigEntry) -> None:
        """Initialize the sensor."""
        super().__init__(coordinator, config_entry)
        self._attr_unique_id = f"{config_entry.entry_id}_error_rate"
        self._attr_name = "Error Rate"
        self._attr_icon = "mdi:alert-circle-outline"

    @property
    def native_value(self) -> float | None:
        """Return the error rate (errors per hour)."""
        if not self.coordinator.data:
            return None
        return self.coordinator.data.get("error_rate_per_hour", 0.0)

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        """Return additional attributes."""
        if not self.coordinator.data:
            return {}

        error_count = self.coordinator.data.get("error_count", 0)
        total_optimizations = self.coordinator.data.get("total_optimizations_run", 0)

        attrs = {
            "total_errors": error_count,
            "total_optimizations": total_optimizations,
        }

        if total_optimizations > 0:
            error_percentage = (error_count / total_optimizations) * 100
            attrs["error_percentage"] = round(error_percentage, 2)
            attrs["health_status"] = (
                "excellent" if error_percentage < 1
                else "good" if error_percentage < 5
                else "fair" if error_percentage < 10
                else "poor"
            )
        else:
            attrs["error_percentage"] = 0.0
            attrs["health_status"] = "no_data"

        return attrs


class TotalOptimizationsRunSensor(AirconManagerSensorBase):
    """Sensor showing total number of optimizations run since startup."""

    _attr_state_class = SensorStateClass.TOTAL_INCREASING

    def __init__(self, coordinator, config_entry: ConfigEntry) -> None:
        """Initialize the sensor."""
        super().__init__(coordinator, config_entry)
        self._attr_unique_id = f"{config_entry.entry_id}_total_optimizations"
        self._attr_name = "Total Optimizations Run"
        self._attr_icon = "mdi:counter"

    @property
    def native_value(self) -> int:
        """Return the total optimizations run."""
        if not self.coordinator.data:
            return 0
        return self.coordinator.data.get("total_optimizations_run", 0)

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        """Return additional attributes."""
        if not self.coordinator.data:
            return {}

        total = self.native_value
        error_count = self.coordinator.data.get("error_count", 0)
        success_count = total - error_count

        return {
            "successful_optimizations": success_count,
            "failed_optimizations": error_count,
            "success_rate": round((success_count / total * 100), 2) if total > 0 else 100.0,
        }


class SensorDataQualitySensor(AirconManagerSensorBase):
    """Sensor showing sensor data quality metrics."""

    _attr_native_unit_of_measurement = PERCENTAGE
    _attr_state_class = SensorStateClass.MEASUREMENT

    def __init__(self, coordinator, config_entry: ConfigEntry) -> None:
        """Initialize the sensor."""
        super().__init__(coordinator, config_entry)
        self._attr_unique_id = f"{config_entry.entry_id}_sensor_data_quality"
        self._attr_name = "Sensor Data Quality"
        self._attr_icon = "mdi:quality-high"

    @property
    def native_value(self) -> float:
        """Return the sensor data quality percentage."""
        if not self.coordinator.data:
            return 0.0

        room_states = self.coordinator.data.get("room_states", {})
        if not room_states:
            return 0.0

        valid_count = sum(
            1 for state in room_states.values()
            if state.get("current_temperature") is not None
        )
        total_count = len(room_states)

        return round((valid_count / total_count * 100), 1) if total_count > 0 else 0.0

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        """Return additional attributes."""
        if not self.coordinator.data:
            return {}

        room_states = self.coordinator.data.get("room_states", {})

        if not room_states:
            return {"status": "no_room_data"}

        valid_sensors = []
        invalid_sensors = []

        for room_name, state in room_states.items():
            if state.get("current_temperature") is not None:
                valid_sensors.append(room_name)
            else:
                invalid_sensors.append(room_name)

        quality_pct = self.native_value

        return {
            "total_sensors": len(room_states),
            "valid_sensors": len(valid_sensors),
            "invalid_sensors": len(invalid_sensors),
            "invalid_sensor_names": invalid_sensors,
            "quality_status": (
                "excellent" if quality_pct == 100
                else "good" if quality_pct >= 90
                else "fair" if quality_pct >= 75
                else "poor"
            ),
        }


# Adaptive Learning Sensors

class RoomThermalMassSensor(AirconManagerSensorBase):
    """Sensor showing learned thermal mass for a room."""

    _attr_state_class = SensorStateClass.MEASUREMENT

    def __init__(self, coordinator, config_entry: ConfigEntry, room_name: str, optimizer=None) -> None:
        """Initialize the sensor."""
        super().__init__(coordinator, config_entry, optimizer)
        self._room_name = room_name
        room_id = room_name.lower().replace(" ", "_")
        self._attr_unique_id = f"{config_entry.entry_id}_{room_id}_thermal_mass"
        self._attr_name = f"{room_name} Thermal Mass"
        self._attr_icon = "mdi:heat-wave"

    @property
    def native_value(self) -> float | None:
        """Return the learned thermal mass (0.0-1.0)."""
        if not self._optimizer or not self._optimizer.learning_manager:
            return None

        profile = self._optimizer.learning_manager.get_profile(self._room_name)
        return profile.thermal_mass if profile else None

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        """Return additional attributes."""
        if not self._optimizer or not self._optimizer.learning_manager:
            return {}

        profile = self._optimizer.learning_manager.get_profile(self._room_name)
        if not profile:
            return {"status": "learning_not_started"}

        return {
            "description": "Higher = slower temperature change (more thermal inertia)",
            "scale": "0.0 (fast response) to 1.0 (slow response)",
            "last_updated": profile.last_updated,
            "confidence": profile.confidence,
        }


class RoomCoolingEfficiencySensor(AirconManagerSensorBase):
    """Sensor showing learned cooling efficiency for a room."""

    _attr_state_class = SensorStateClass.MEASUREMENT

    def __init__(self, coordinator, config_entry: ConfigEntry, room_name: str, optimizer=None) -> None:
        """Initialize the sensor."""
        super().__init__(coordinator, config_entry, optimizer)
        self._room_name = room_name
        room_id = room_name.lower().replace(" ", "_")
        self._attr_unique_id = f"{config_entry.entry_id}_{room_id}_cooling_efficiency"
        self._attr_name = f"{room_name} Cooling Efficiency"
        self._attr_icon = "mdi:fan-speed-3"

    @property
    def native_value(self) -> float | None:
        """Return the learned cooling efficiency (0.0-1.0)."""
        if not self._optimizer or not self._optimizer.learning_manager:
            return None

        profile = self._optimizer.learning_manager.get_profile(self._room_name)
        return profile.cooling_efficiency if profile else None

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        """Return additional attributes."""
        if not self._optimizer or not self._optimizer.learning_manager:
            return {}

        profile = self._optimizer.learning_manager.get_profile(self._room_name)
        if not profile:
            return {"status": "learning_not_started"}

        return {
            "description": "How effectively fan speed controls temperature",
            "scale": "0.0 (ineffective) to 1.0 (very effective)",
            "last_updated": profile.last_updated,
            "confidence": profile.confidence,
        }


class RoomLearningConfidenceSensor(AirconManagerSensorBase):
    """Sensor showing learning confidence score for a room."""

    _attr_native_unit_of_measurement = PERCENTAGE
    _attr_state_class = SensorStateClass.MEASUREMENT

    def __init__(self, coordinator, config_entry: ConfigEntry, room_name: str, optimizer=None) -> None:
        """Initialize the sensor."""
        super().__init__(coordinator, config_entry, optimizer)
        self._room_name = room_name
        room_id = room_name.lower().replace(" ", "_")
        self._attr_unique_id = f"{config_entry.entry_id}_{room_id}_learning_confidence"
        self._attr_name = f"{room_name} Learning Confidence"
        self._attr_icon = "mdi:chart-line"

    @property
    def native_value(self) -> float | None:
        """Return the learning confidence percentage."""
        if not self._optimizer or not self._optimizer.learning_manager:
            return None

        profile = self._optimizer.learning_manager.get_profile(self._room_name)
        if not profile:
            return 0.0

        return round(profile.confidence * 100, 1)

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        """Return additional attributes."""
        if not self._optimizer or not self._optimizer.learning_manager:
            return {}

        profile = self._optimizer.learning_manager.get_profile(self._room_name)
        threshold = self._optimizer.learning_manager.confidence_threshold * 100

        if not profile:
            return {
                "status": "learning_not_started",
                "threshold_for_activation": f"{threshold}%",
            }

        return {
            "status": (
                "active" if profile.confidence >= self._optimizer.learning_manager.confidence_threshold
                else "collecting_data"
            ),
            "threshold_for_activation": f"{threshold}%",
            "last_updated": profile.last_updated,
            "data_points_needed": max(0, int(200 * self._optimizer.learning_manager.confidence_threshold) - 
                                     self._optimizer.learning_manager.tracker.get_data_point_count(self._room_name)),
        }


class RoomDataPointsSensor(AirconManagerSensorBase):
    """Sensor showing number of data points collected for a room."""

    _attr_state_class = SensorStateClass.TOTAL_INCREASING

    def __init__(self, coordinator, config_entry: ConfigEntry, room_name: str, optimizer=None) -> None:
        """Initialize the sensor."""
        super().__init__(coordinator, config_entry, optimizer)
        self._room_name = room_name
        room_id = room_name.lower().replace(" ", "_")
        self._attr_unique_id = f"{config_entry.entry_id}_{room_id}_data_points"
        self._attr_name = f"{room_name} Data Points Collected"
        self._attr_icon = "mdi:database"

    @property
    def native_value(self) -> int:
        """Return the number of data points collected."""
        if not self._optimizer or not self._optimizer.learning_manager:
            return 0

        return self._optimizer.learning_manager.tracker.get_data_point_count(self._room_name)

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        """Return additional attributes."""
        if not self._optimizer or not self._optimizer.learning_manager:
            return {}

        count = self.native_value
        max_points = self._optimizer.learning_manager.tracker._max_data_points_per_room

        return {
            "max_capacity": max_points,
            "utilization": f"{round((count / max_points) * 100, 1)}%",
            "status": (
                "full" if count >= max_points
                else "collecting" if count > 0
                else "empty"
            ),
        }


class RoomOvershootRateSensor(AirconManagerSensorBase):
    """Sensor showing overshoot rate for a room."""

    _attr_native_unit_of_measurement = "overshoots/day"
    _attr_state_class = SensorStateClass.MEASUREMENT

    def __init__(self, coordinator, config_entry: ConfigEntry, room_name: str, optimizer=None) -> None:
        """Initialize the sensor."""
        super().__init__(coordinator, config_entry, optimizer)
        self._room_name = room_name
        room_id = room_name.lower().replace(" ", "_")
        self._attr_unique_id = f"{config_entry.entry_id}_{room_id}_overshoot_rate"
        self._attr_name = f"{room_name} Overshoot Rate"
        self._attr_icon = "mdi:sine-wave"

    @property
    def native_value(self) -> float | None:
        """Return the overshoot rate (overshoots per day)."""
        if not self._optimizer or not self._optimizer.learning_manager:
            return None

        profile = self._optimizer.learning_manager.get_profile(self._room_name)
        if not profile:
            return None

        # Return 0.0 if overshoot rate hasn't been calculated yet (insufficient data)
        return profile.overshoot_rate_per_day if profile.overshoot_rate_per_day is not None else 0.0

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        """Return additional attributes."""
        if not self._optimizer or not self._optimizer.learning_manager:
            return {}

        profile = self._optimizer.learning_manager.get_profile(self._room_name)
        if not profile:
            return {"status": "learning_not_started"}

        rate = profile.overshoot_rate_per_day if profile.overshoot_rate_per_day is not None else 0.0

        # Calculate live confidence based on current data points (not stale saved value)
        tracker = self._optimizer.learning_manager.tracker
        data_count = tracker.get_data_point_count(self._room_name)
        live_confidence = min(1.0, data_count / 200.0) if data_count is not None else 0.0

        # Determine status based on whether we have data yet
        if profile.last_updated is None or data_count < 10:
            status = "collecting_data"
        elif rate < 0.5:
            status = "excellent"
        elif rate < 1.0:
            status = "good"
        elif rate < 2.0:
            status = "fair"
        else:
            status = "poor"

        return {
            "description": "How often temperature overshoots target",
            "status": status,
            "optimal_smoothing_factor": profile.optimal_smoothing_factor,
            "optimal_smoothing_threshold": profile.optimal_smoothing_threshold,
            "last_updated": profile.last_updated if profile.last_updated else "Not yet updated",
            "confidence": round(live_confidence * 100, 1),
            "data_points": data_count if data_count is not None else 0,
        }


class HouseAverageTemperatureSensor(AirconManagerSensorBase):
    """Sensor showing the average temperature across all rooms."""

    _attr_device_class = SensorDeviceClass.TEMPERATURE
    _attr_native_unit_of_measurement = UnitOfTemperature.CELSIUS
    _attr_state_class = SensorStateClass.MEASUREMENT

    def __init__(self, coordinator, config_entry: ConfigEntry) -> None:
        """Initialize the sensor."""
        super().__init__(coordinator, config_entry)
        self._attr_unique_id = f"{config_entry.entry_id}_house_average_temperature"
        self._attr_name = "House Average Temperature"
        self._attr_icon = "mdi:home-thermometer"

    @property
    def native_value(self) -> float | None:
        """Return the house average temperature."""
        # Get optimizer from hass data
        from .const import DOMAIN
        entry_data = self.coordinator.hass.data.get(DOMAIN, {}).get(self._config_entry.entry_id, {})
        optimizer = entry_data.get("optimizer")

        if not optimizer or not hasattr(optimizer, '_house_avg_temp'):
            return None

        return round(optimizer._house_avg_temp, 1) if optimizer._house_avg_temp is not None else None

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        """Return additional attributes."""
        from .const import DOMAIN
        entry_data = self.coordinator.hass.data.get(DOMAIN, {}).get(self._config_entry.entry_id, {})
        optimizer = entry_data.get("optimizer")

        if not optimizer:
            return {}

        return {
            "room_count": len(optimizer.room_configs) if optimizer.room_configs else 0,
            "target_temperature": optimizer.target_temperature,
            "deviation_from_target": round(optimizer._house_avg_temp - optimizer.target_temperature, 2) if optimizer._house_avg_temp is not None else None,
        }


class RoomTemperatureVarianceSensor(AirconManagerSensorBase):
    """Sensor showing the standard deviation of room temperatures."""

    _attr_native_unit_of_measurement = UnitOfTemperature.CELSIUS
    _attr_state_class = SensorStateClass.MEASUREMENT

    def __init__(self, coordinator, config_entry: ConfigEntry) -> None:
        """Initialize the sensor."""
        super().__init__(coordinator, config_entry)
        self._attr_unique_id = f"{config_entry.entry_id}_room_temperature_variance"
        self._attr_name = "Room Temperature Variance"
        self._attr_icon = "mdi:chart-bell-curve"

    @property
    def native_value(self) -> float | None:
        """Return the room temperature variance (standard deviation)."""
        # Get optimizer from hass data
        from .const import DOMAIN
        entry_data = self.coordinator.hass.data.get(DOMAIN, {}).get(self._config_entry.entry_id, {})
        optimizer = entry_data.get("optimizer")

        if not optimizer or not hasattr(optimizer, '_house_temp_variance'):
            return None

        return round(optimizer._house_temp_variance, 2) if optimizer._house_temp_variance is not None else None

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        """Return additional attributes."""
        from .const import DOMAIN
        entry_data = self.coordinator.hass.data.get(DOMAIN, {}).get(self._config_entry.entry_id, {})
        optimizer = entry_data.get("optimizer")

        if not optimizer:
            return {}

        variance = optimizer._house_temp_variance if hasattr(optimizer, '_house_temp_variance') else None
        target = optimizer.target_room_variance

        return {
            "target_variance": target,
            "variance_status": (
                "excellent" if variance and variance < target * 0.5
                else "good" if variance and variance < target
                else "needs_balancing" if variance and variance >= target
                else "unknown"
            ),
            "balancing_enabled": optimizer.enable_room_balancing,
        }


class BalancingActiveSensor(AirconManagerSensorBase):
    """Sensor showing whether room balancing is currently active."""

    def __init__(self, coordinator, config_entry: ConfigEntry) -> None:
        """Initialize the sensor."""
        super().__init__(coordinator, config_entry)
        self._attr_unique_id = f"{config_entry.entry_id}_balancing_active"
        self._attr_name = "Room Balancing Active"
        self._attr_icon = "mdi:scale-balance"

    @property
    def native_value(self) -> str:
        """Return whether balancing is active."""
        # Get optimizer from hass data
        from .const import DOMAIN
        entry_data = self.coordinator.hass.data.get(DOMAIN, {}).get(self._config_entry.entry_id, {})
        optimizer = entry_data.get("optimizer")

        if not optimizer or not hasattr(optimizer, '_balancing_active'):
            return "unknown"

        return "active" if optimizer._balancing_active else "inactive"

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        """Return additional attributes."""
        from .const import DOMAIN
        entry_data = self.coordinator.hass.data.get(DOMAIN, {}).get(self._config_entry.entry_id, {})
        optimizer = entry_data.get("optimizer")

        if not optimizer:
            return {}

        attrs = {
            "balancing_enabled": optimizer.enable_room_balancing,
            "target_variance": optimizer.target_room_variance,
            "aggressiveness": optimizer.balancing_aggressiveness,
            "min_airflow_percent": optimizer.min_airflow_percent,
        }

        if hasattr(optimizer, '_house_avg_temp') and optimizer._house_avg_temp is not None:
            attrs["current_house_avg"] = round(optimizer._house_avg_temp, 1)
            attrs["target_temperature"] = optimizer.target_temperature
            attrs["house_deviation"] = round(optimizer._house_avg_temp - optimizer.target_temperature, 2)

        if hasattr(optimizer, '_house_temp_variance') and optimizer._house_temp_variance is not None:
            attrs["current_variance"] = round(optimizer._house_temp_variance, 2)

        return attrs


# Humidity Control Sensors

class HVACModeRecommendationSensor(AirconManagerSensorBase):
    """Sensor showing the recommended HVAC mode based on temperature and humidity."""

    def __init__(self, coordinator, config_entry: ConfigEntry) -> None:
        """Initialize the sensor."""
        super().__init__(coordinator, config_entry)
        self._attr_unique_id = f"{config_entry.entry_id}_hvac_mode_recommendation"
        self._attr_name = "HVAC Mode Recommendation"
        self._attr_icon = "mdi:air-conditioner"

    @property
    def native_value(self) -> str:
        """Return the recommended HVAC mode."""
        # Get optimizer from hass data
        from .const import DOMAIN
        entry_data = self.coordinator.hass.data.get(DOMAIN, {}).get(self._config_entry.entry_id, {})
        optimizer = entry_data.get("optimizer")

        if not optimizer or not self.coordinator.data:
            return "unknown"

        room_states = self.coordinator.data.get("room_states", {})
        effective_target = self.coordinator.data.get("effective_target_temperature", optimizer.target_temperature)

        # Use the optimizer's method to determine optimal mode
        optimal_mode = optimizer._determine_optimal_hvac_mode(room_states, effective_target)
        return optimal_mode

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        """Return additional attributes."""
        from .const import DOMAIN
        entry_data = self.coordinator.hass.data.get(DOMAIN, {}).get(self._config_entry.entry_id, {})
        optimizer = entry_data.get("optimizer")

        if not optimizer or not self.coordinator.data:
            return {}

        room_states = self.coordinator.data.get("room_states", {})

        # Calculate average temperature and humidity
        temps = [s["current_temperature"] for s in room_states.values() if s["current_temperature"] is not None]
        humidities = [s.get("current_humidity") for s in room_states.values() if s.get("current_humidity") is not None]

        attrs = {
            "decision_logic": "Temperature ALWAYS has priority over humidity",
            "priority_1": "Temperature outside deadband → cool/heat",
            "priority_2": "Humidity high + temp OK → dry",
            "priority_3": "Both OK → fan_only for circulation",
            "humidity_control_enabled": optimizer.enable_humidity_control,
        }

        if temps:
            avg_temp = sum(temps) / len(temps)
            attrs["average_temperature"] = round(avg_temp, 1)
            attrs["target_temperature"] = optimizer.target_temperature
            attrs["temp_deviation"] = round(avg_temp - optimizer.target_temperature, 2)
            attrs["temp_deadband"] = optimizer.temperature_deadband

        if humidities:
            avg_humidity = sum(humidities) / len(humidities)
            attrs["average_humidity"] = round(avg_humidity, 1)
            attrs["target_humidity"] = optimizer.target_humidity
            attrs["humidity_deadband"] = optimizer.humidity_deadband
            attrs["dry_mode_threshold"] = optimizer.dry_mode_humidity_threshold

        return attrs


class HouseAverageHumiditySensor(AirconManagerSensorBase):
    """Sensor showing the average humidity across all rooms."""

    _attr_device_class = SensorDeviceClass.HUMIDITY
    _attr_native_unit_of_measurement = PERCENTAGE
    _attr_state_class = SensorStateClass.MEASUREMENT

    def __init__(self, coordinator, config_entry: ConfigEntry) -> None:
        """Initialize the sensor."""
        super().__init__(coordinator, config_entry)
        self._attr_unique_id = f"{config_entry.entry_id}_house_average_humidity"
        self._attr_name = "House Average Humidity"
        self._attr_icon = "mdi:water-percent"

    @property
    def native_value(self) -> float | None:
        """Return the house average humidity."""
        # Get optimizer from hass data
        from .const import DOMAIN
        entry_data = self.coordinator.hass.data.get(DOMAIN, {}).get(self._config_entry.entry_id, {})
        optimizer = entry_data.get("optimizer")

        if not optimizer or not hasattr(optimizer, '_house_avg_humidity'):
            return None

        return round(optimizer._house_avg_humidity, 1) if optimizer._house_avg_humidity is not None else None

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        """Return additional attributes."""
        from .const import DOMAIN
        entry_data = self.coordinator.hass.data.get(DOMAIN, {}).get(self._config_entry.entry_id, {})
        optimizer = entry_data.get("optimizer")

        if not optimizer or not self.coordinator.data:
            return {}

        room_states = self.coordinator.data.get("room_states", {})
        humidities = [s.get("current_humidity") for s in room_states.values() if s.get("current_humidity") is not None]

        attrs = {
            "target_humidity": optimizer.target_humidity,
            "humidity_deadband": optimizer.humidity_deadband,
            "dry_mode_threshold": optimizer.dry_mode_humidity_threshold,
            "rooms_with_humidity_sensors": len(humidities),
            "total_rooms": len(room_states),
        }

        if optimizer._house_avg_humidity is not None:
            deviation = optimizer._house_avg_humidity - optimizer.target_humidity
            attrs["deviation_from_target"] = round(deviation, 1)
            attrs["needs_dehumidification"] = optimizer._house_avg_humidity >= optimizer.dry_mode_humidity_threshold

        return attrs


class DryModeActiveSensor(AirconManagerSensorBase):
    """Sensor showing whether dry mode is currently active."""

    def __init__(self, coordinator, config_entry: ConfigEntry) -> None:
        """Initialize the sensor."""
        super().__init__(coordinator, config_entry)
        self._attr_unique_id = f"{config_entry.entry_id}_dry_mode_active"
        self._attr_name = "Dry Mode Active"
        self._attr_icon = "mdi:air-humidifier-off"

    @property
    def native_value(self) -> str:
        """Return whether dry mode is active."""
        # Get optimizer from hass data
        from .const import DOMAIN
        entry_data = self.coordinator.hass.data.get(DOMAIN, {}).get(self._config_entry.entry_id, {})
        optimizer = entry_data.get("optimizer")

        if not optimizer or not hasattr(optimizer, '_dry_mode_active'):
            return "unknown"

        return "active" if optimizer._dry_mode_active else "inactive"

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        """Return additional attributes."""
        from .const import DOMAIN
        entry_data = self.coordinator.hass.data.get(DOMAIN, {}).get(self._config_entry.entry_id, {})
        optimizer = entry_data.get("optimizer")

        if not optimizer:
            return {}

        attrs = {
            "humidity_control_enabled": optimizer.enable_humidity_control,
            "dry_mode_threshold": optimizer.dry_mode_humidity_threshold,
        }

        if hasattr(optimizer, '_house_avg_humidity') and optimizer._house_avg_humidity is not None:
            attrs["current_humidity"] = round(optimizer._house_avg_humidity, 1)
            attrs["target_humidity"] = optimizer.target_humidity

        return attrs


class FanOnlyModeActiveSensor(AirconManagerSensorBase):
    """Sensor showing whether fan-only mode is currently active."""

    def __init__(self, coordinator, config_entry: ConfigEntry) -> None:
        """Initialize the sensor."""
        super().__init__(coordinator, config_entry)
        self._attr_unique_id = f"{config_entry.entry_id}_fan_only_mode_active"
        self._attr_name = "Fan Only Mode Active"
        self._attr_icon = "mdi:fan"

    @property
    def native_value(self) -> str:
        """Return whether fan-only mode is active."""
        # Get optimizer from hass data
        from .const import DOMAIN
        entry_data = self.coordinator.hass.data.get(DOMAIN, {}).get(self._config_entry.entry_id, {})
        optimizer = entry_data.get("optimizer")

        if not optimizer or not hasattr(optimizer, '_fan_only_mode_active'):
            return "unknown"

        return "active" if optimizer._fan_only_mode_active else "inactive"

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        """Return additional attributes."""
        from .const import DOMAIN
        entry_data = self.coordinator.hass.data.get(DOMAIN, {}).get(self._config_entry.entry_id, {})
        optimizer = entry_data.get("optimizer")

        if not optimizer or not self.coordinator.data:
            return {}

        room_states = self.coordinator.data.get("room_states", {})
        temps = [s["current_temperature"] for s in room_states.values() if s["current_temperature"] is not None]

        attrs = {
            "humidity_control_enabled": optimizer.enable_humidity_control,
            "description": "Fan-only mode saves ~95% energy when temp and humidity are OK",
        }

        if temps:
            avg_temp = sum(temps) / len(temps)
            attrs["current_temperature"] = round(avg_temp, 1)
            attrs["target_temperature"] = optimizer.target_temperature
            attrs["temp_within_deadband"] = abs(avg_temp - optimizer.target_temperature) <= optimizer.temperature_deadband

        if hasattr(optimizer, '_house_avg_humidity') and optimizer._house_avg_humidity is not None:
            attrs["current_humidity"] = round(optimizer._house_avg_humidity, 1)
            attrs["target_humidity"] = optimizer.target_humidity
            attrs["humidity_within_threshold"] = optimizer._house_avg_humidity < optimizer.dry_mode_humidity_threshold

        return attrs


class ComfortIndexSensor(AirconManagerSensorBase):
    """Sensor showing the comfort index (feels-like temperature) combining temperature and humidity."""

    def __init__(self, coordinator, config_entry: ConfigEntry) -> None:
        """Initialize the sensor."""
        super().__init__(coordinator, config_entry)
        self._attr_unique_id = f"{config_entry.entry_id}_comfort_index"
        self._attr_name = "Comfort Index"
        self._attr_icon = "mdi:weather-partly-cloudy"
        self._attr_device_class = "temperature"
        self._attr_native_unit_of_measurement = "°C"

    def _calculate_heat_index(self, temp_c: float, humidity: float) -> float:
        """Calculate heat index (feels-like temperature) from temperature and humidity.

        Uses the simplified Steadman formula for heat index.
        Only applies when temperature >= 27°C, otherwise returns actual temperature.
        """
        # Heat index only applies at higher temperatures
        if temp_c < 27.0:
            return temp_c

        # Simplified Steadman heat index formula
        # HI = c1 + c2*T + c3*RH + c4*T*RH + c5*T² + c6*RH² + c7*T²*RH + c8*T*RH² + c9*T²*RH²
        # Coefficients for Celsius version
        c1 = -8.78469475556
        c2 = 1.61139411
        c3 = 2.33854883889
        c4 = -0.14611605
        c5 = -0.012308094
        c6 = -0.0164248277778
        c7 = 0.002211732
        c8 = 0.00072546
        c9 = -0.000003582

        T = temp_c
        RH = humidity

        heat_index = (
            c1 + c2*T + c3*RH + c4*T*RH + c5*T*T + c6*RH*RH +
            c7*T*T*RH + c8*T*RH*RH + c9*T*T*RH*RH
        )

        return heat_index

    @property
    def native_value(self) -> float | None:
        """Return the comfort index (feels-like temperature)."""
        from .const import DOMAIN
        entry_data = self.coordinator.hass.data.get(DOMAIN, {}).get(self._config_entry.entry_id, {})
        optimizer = entry_data.get("optimizer")

        if not optimizer or not self.coordinator.data:
            return None

        room_states = self.coordinator.data.get("room_states", {})

        # Get average temperature
        temps = [s["current_temperature"] for s in room_states.values() if s["current_temperature"] is not None]
        if not temps:
            return None
        avg_temp = sum(temps) / len(temps)

        # Get average humidity if available
        avg_humidity = None
        if hasattr(optimizer, '_house_avg_humidity') and optimizer._house_avg_humidity is not None:
            avg_humidity = optimizer._house_avg_humidity
        else:
            # Try to get from room states
            humidities = [s["current_humidity"] for s in room_states.values() if s["current_humidity"] is not None]
            if humidities:
                avg_humidity = sum(humidities) / len(humidities)

        # Calculate comfort index
        if avg_humidity is not None:
            comfort_index = self._calculate_heat_index(avg_temp, avg_humidity)
        else:
            # No humidity data - just use temperature
            comfort_index = avg_temp

        return round(comfort_index, 1)

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        """Return additional attributes."""
        from .const import DOMAIN
        entry_data = self.coordinator.hass.data.get(DOMAIN, {}).get(self._config_entry.entry_id, {})
        optimizer = entry_data.get("optimizer")

        if not optimizer or not self.coordinator.data:
            return {}

        room_states = self.coordinator.data.get("room_states", {})

        # Get average temperature
        temps = [s["current_temperature"] for s in room_states.values() if s["current_temperature"] is not None]
        humidities = [s["current_humidity"] for s in room_states.values() if s["current_humidity"] is not None]

        attrs = {
            "description": "Feels-like temperature combining temp + humidity",
        }

        if temps:
            avg_temp = sum(temps) / len(temps)
            attrs["actual_temperature"] = round(avg_temp, 1)
            attrs["target_temperature"] = optimizer.target_temperature

        if humidities or (hasattr(optimizer, '_house_avg_humidity') and optimizer._house_avg_humidity is not None):
            avg_humidity = (
                optimizer._house_avg_humidity if hasattr(optimizer, '_house_avg_humidity') and optimizer._house_avg_humidity is not None
                else (sum(humidities) / len(humidities) if humidities else None)
            )
            if avg_humidity is not None:
                attrs["humidity"] = round(avg_humidity, 1)

                # Calculate difference from actual temp
                if temps:
                    comfort_index = self._calculate_heat_index(avg_temp, avg_humidity)
                    diff = comfort_index - avg_temp
                    attrs["heat_index_adjustment"] = round(diff, 1)

                    # Provide comfort guidance
                    if comfort_index - optimizer.target_temperature > 3:
                        attrs["comfort_level"] = "Very uncomfortable - hot & humid"
                    elif comfort_index - optimizer.target_temperature > 1.5:
                        attrs["comfort_level"] = "Uncomfortable - warm & humid"
                    elif abs(comfort_index - optimizer.target_temperature) <= 1.5:
                        attrs["comfort_level"] = "Comfortable"
                    else:
                        attrs["comfort_level"] = "Cool"
        else:
            attrs["note"] = "No humidity data - showing actual temperature"

        return attrs
