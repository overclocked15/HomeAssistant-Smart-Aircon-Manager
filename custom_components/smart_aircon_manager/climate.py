"""Climate platform for Smart Aircon Manager integration."""
from __future__ import annotations

import logging
from typing import Any

from homeassistant.components.climate import (
    ClimateEntity,
    ClimateEntityFeature,
    HVACMode,
    FAN_AUTO,
    FAN_LOW,
    FAN_MEDIUM,
    FAN_HIGH,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import ATTR_TEMPERATURE, UnitOfTemperature
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import DOMAIN

_LOGGER = logging.getLogger(__name__)


async def async_setup_entry(
    hass: HomeAssistant,
    config_entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up the Smart Aircon Manager climate platform."""
    coordinator = hass.data[DOMAIN][config_entry.entry_id]["coordinator"]
    optimizer = hass.data[DOMAIN][config_entry.entry_id]["optimizer"]

    entities = [AirconAIClimate(coordinator, optimizer, config_entry)]
    async_add_entities(entities)


class AirconAIClimate(CoordinatorEntity, ClimateEntity):
    """Representation of an Smart Aircon Manager climate entity."""

    _attr_has_entity_name = True
    _attr_name = "Smart Aircon Manager"
    _attr_temperature_unit = UnitOfTemperature.CELSIUS
    _attr_supported_features = (
        ClimateEntityFeature.TARGET_TEMPERATURE
        | ClimateEntityFeature.TURN_ON
        | ClimateEntityFeature.TURN_OFF
        | ClimateEntityFeature.FAN_MODE
    )
    _attr_hvac_modes = [HVACMode.OFF, HVACMode.COOL, HVACMode.HEAT, HVACMode.AUTO]
    _attr_fan_modes = [FAN_AUTO, FAN_LOW, FAN_MEDIUM, FAN_HIGH]

    def __init__(self, coordinator, optimizer, config_entry: ConfigEntry) -> None:
        """Initialize the climate entity."""
        super().__init__(coordinator)
        self._optimizer = optimizer
        self._config_entry = config_entry
        self._attr_unique_id = f"{config_entry.entry_id}_climate"

        # Restore persisted state from config entry (survives HA restarts)
        from .const import CONF_HVAC_MODE
        persisted_mode = config_entry.data.get(CONF_HVAC_MODE, "auto")
        self._is_on = config_entry.data.get("is_system_on", True)

        mode_map = {"cool": HVACMode.COOL, "heat": HVACMode.HEAT, "auto": HVACMode.AUTO}
        self._attr_hvac_mode = mode_map.get(persisted_mode, HVACMode.AUTO)
        self._optimizer.is_enabled = self._is_on

    @property
    def device_info(self):
        """Return device information."""
        from . import get_device_info
        return get_device_info(self._config_entry)

    @property
    def current_temperature(self) -> float | None:
        """Return the current temperature (average of all rooms)."""
        if not self.coordinator.data:
            return None

        room_states = self.coordinator.data.get("room_states", {})
        temps = [
            state["current_temperature"]
            for state in room_states.values()
            if state["current_temperature"] is not None
        ]

        if not temps:
            return None

        return round(sum(temps) / len(temps), 1)

    @property
    def target_temperature(self) -> float | None:
        """Return the target temperature."""
        return self._optimizer.target_temperature

    @property
    def hvac_mode(self) -> HVACMode:
        """Return current operation mode."""
        if not self._is_on:
            return HVACMode.OFF
        return self._attr_hvac_mode

    @property
    def fan_mode(self) -> str | None:
        """Return the current fan mode."""
        if not self.coordinator.data:
            return FAN_AUTO
        main_fan_speed = self.coordinator.data.get("main_fan_speed")
        if main_fan_speed == "low":
            return FAN_LOW
        elif main_fan_speed == "medium":
            return FAN_MEDIUM
        elif main_fan_speed == "high":
            return FAN_HIGH
        return FAN_AUTO

    async def async_set_fan_mode(self, fan_mode: str) -> None:
        """Set new fan mode (overrides automatic main fan control)."""
        if not self._optimizer.main_fan_entity:
            _LOGGER.warning("Cannot set fan mode - no main fan entity configured")
            return

        fan_state = self.hass.states.get(self._optimizer.main_fan_entity)
        if not fan_state or fan_state.state in ["unavailable", "unknown"]:
            return

        if self._optimizer.main_fan_entity.startswith("climate."):
            await self.hass.services.async_call(
                "climate", "set_fan_mode",
                {"entity_id": self._optimizer.main_fan_entity, "fan_mode": fan_mode},
            )
        elif self._optimizer.main_fan_entity.startswith("fan."):
            # Map to percentage for fan entities
            pct_map = {FAN_LOW: 33, FAN_MEDIUM: 66, FAN_HIGH: 100, FAN_AUTO: 66}
            await self.hass.services.async_call(
                "fan", "set_percentage",
                {"entity_id": self._optimizer.main_fan_entity, "percentage": pct_map.get(fan_mode, 66)},
            )

        self.async_write_ha_state()

    async def async_set_temperature(self, **kwargs: Any) -> None:
        """Set new target temperature."""
        if (temperature := kwargs.get(ATTR_TEMPERATURE)) is None:
            return

        # Update optimizer
        self._optimizer.target_temperature = temperature

        # Persist to config entry
        from .const import CONF_TARGET_TEMPERATURE
        new_data = {**self._config_entry.data, CONF_TARGET_TEMPERATURE: temperature}
        self.hass.config_entries.async_update_entry(self._config_entry, data=new_data)

        await self.coordinator.async_request_refresh()

    async def async_set_hvac_mode(self, hvac_mode: HVACMode) -> None:
        """Set new target hvac mode."""
        if hvac_mode == HVACMode.OFF:
            self._is_on = False
            self._optimizer.is_enabled = False
        else:
            self._is_on = True
            self._optimizer.is_enabled = True
            self._attr_hvac_mode = hvac_mode

            # Propagate HVAC mode to optimizer so control logic uses the new mode
            mode_str = hvac_mode.value if hasattr(hvac_mode, 'value') else str(hvac_mode)
            if mode_str in ("cool", "heat", "auto"):
                self._optimizer.hvac_mode = mode_str

        # Persist state for restart recovery
        from .const import CONF_HVAC_MODE
        if hvac_mode == HVACMode.OFF:
            # Keep last active mode, store is_system_on=False
            new_data = {**self._config_entry.data, "is_system_on": False}
        else:
            persist_mode = hvac_mode.value if hasattr(hvac_mode, 'value') else str(hvac_mode)
            new_data = {**self._config_entry.data, CONF_HVAC_MODE: persist_mode, "is_system_on": True}
        self.hass.config_entries.async_update_entry(self._config_entry, data=new_data)

        self.async_write_ha_state()

        if self._is_on:
            await self.coordinator.async_request_refresh()

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        """Return additional state attributes."""
        if not self.coordinator.data:
            return {}

        room_states = self.coordinator.data.get("room_states", {})
        recommendations = self.coordinator.data.get("recommendations", {})

        attrs = {
            "room_temperatures": {
                room: state["current_temperature"]
                for room, state in room_states.items()
            },
            "cover_positions": {
                room: state["cover_position"] for room, state in room_states.items()
            },
            "ai_recommendations": recommendations,
        }

        # Add effective target if scheduling/weather is active
        effective_target = self.coordinator.data.get("effective_target_temperature")
        if effective_target and effective_target != self._optimizer.target_temperature:
            attrs["effective_target_temperature"] = effective_target
            attrs["base_target_temperature"] = self._optimizer.target_temperature

            # Add schedule info if active
            active_schedule = self.coordinator.data.get("active_schedule")
            if active_schedule:
                from .const import CONF_SCHEDULE_NAME
                attrs["active_schedule"] = active_schedule.get(CONF_SCHEDULE_NAME)

            # Add weather adjustment if present
            weather_adj = self.coordinator.data.get("weather_adjustment")
            if weather_adj and weather_adj != 0:
                attrs["weather_adjustment"] = weather_adj
                attrs["outdoor_temperature"] = self.coordinator.data.get("outdoor_temperature")

        return attrs
