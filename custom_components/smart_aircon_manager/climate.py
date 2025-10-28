"""Climate platform for AI Aircon Manager integration."""
from __future__ import annotations

import logging
from typing import Any

from homeassistant.components.climate import (
    ClimateEntity,
    ClimateEntityFeature,
    HVACMode,
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
    """Set up the AI Aircon Manager climate platform."""
    coordinator = hass.data[DOMAIN][config_entry.entry_id]["coordinator"]
    optimizer = hass.data[DOMAIN][config_entry.entry_id]["optimizer"]

    entities = [AirconAIClimate(coordinator, optimizer, config_entry)]
    async_add_entities(entities)


class AirconAIClimate(CoordinatorEntity, ClimateEntity):
    """Representation of an AI Aircon Manager climate entity."""

    _attr_has_entity_name = True
    _attr_name = "AI Aircon Manager"
    _attr_temperature_unit = UnitOfTemperature.CELSIUS
    _attr_supported_features = (
        ClimateEntityFeature.TARGET_TEMPERATURE | ClimateEntityFeature.TURN_ON | ClimateEntityFeature.TURN_OFF
    )
    _attr_hvac_modes = [HVACMode.OFF, HVACMode.COOL, HVACMode.HEAT, HVACMode.AUTO]

    def __init__(self, coordinator, optimizer, config_entry: ConfigEntry) -> None:
        """Initialize the climate entity."""
        super().__init__(coordinator)
        self._optimizer = optimizer
        self._config_entry = config_entry
        self._attr_unique_id = f"{config_entry.entry_id}_climate"
        self._attr_hvac_mode = HVACMode.AUTO
        self._is_on = True

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

    async def async_set_temperature(self, **kwargs: Any) -> None:
        """Set new target temperature."""
        if (temperature := kwargs.get(ATTR_TEMPERATURE)) is None:
            return

        # Update optimizer
        self._optimizer.target_temperature = temperature

        # Persist to config entry
        config_entry = self.hass.config_entries.async_get_entry(self._attr_unique_id.replace("_climate", ""))
        if config_entry:
            from .const import CONF_TARGET_TEMPERATURE
            new_data = {**config_entry.data, CONF_TARGET_TEMPERATURE: temperature}
            self.hass.config_entries.async_update_entry(config_entry, data=new_data)

        await self.coordinator.async_request_refresh()

    async def async_set_hvac_mode(self, hvac_mode: HVACMode) -> None:
        """Set new target hvac mode."""
        if hvac_mode == HVACMode.OFF:
            self._is_on = False
        else:
            self._is_on = True
            self._attr_hvac_mode = hvac_mode

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
