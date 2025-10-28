"""Binary sensor platform for AI Aircon Manager integration."""
from __future__ import annotations

import logging
from typing import Any

from homeassistant.components.binary_sensor import (
    BinarySensorDeviceClass,
    BinarySensorEntity,
)
from homeassistant.config_entries import ConfigEntry
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
    """Set up the AI Aircon Manager binary sensor platform."""
    coordinator = hass.data[DOMAIN][config_entry.entry_id]["coordinator"]
    optimizer = hass.data[DOMAIN][config_entry.entry_id]["optimizer"]

    entities = []

    # Add main climate running sensor if configured
    if optimizer.main_climate_entity:
        entities.append(MainClimateRunningSensor(coordinator, config_entry))

    if entities:
        async_add_entities(entities)


class MainClimateRunningSensor(CoordinatorEntity, BinarySensorEntity):
    """Binary sensor showing if the main aircon is running."""

    _attr_device_class = BinarySensorDeviceClass.RUNNING

    def __init__(self, coordinator, config_entry: ConfigEntry) -> None:
        """Initialize the sensor."""
        super().__init__(coordinator)
        self._config_entry = config_entry
        self._attr_unique_id = f"{config_entry.entry_id}_main_climate_running"
        self._attr_name = "Main Aircon Running"

    @property
    def device_info(self):
        """Return device information."""
        from . import get_device_info
        return get_device_info(self._config_entry)

    @property
    def is_on(self) -> bool | None:
        """Return true if the main aircon is running."""
        if not self.coordinator.data:
            return None

        main_climate_state = self.coordinator.data.get("main_climate_state")
        if not main_climate_state:
            return None

        # Check if HVAC action is actively cooling/heating
        hvac_action = main_climate_state.get("hvac_action")
        if hvac_action and hvac_action not in ["unknown", "unavailable", "idle", "off"]:
            return hvac_action in ["cooling", "heating"]

        # Fall back to checking if HVAC mode is on
        hvac_mode = main_climate_state.get("hvac_mode")
        state = main_climate_state.get("state")

        if hvac_mode:
            return hvac_mode != "off"
        if state:
            return state != "off"

        return None

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        """Return additional attributes."""
        if not self.coordinator.data:
            return {}

        main_climate_state = self.coordinator.data.get("main_climate_state")
        if not main_climate_state:
            return {}

        return {
            "hvac_mode": main_climate_state.get("hvac_mode"),
            "hvac_action": main_climate_state.get("hvac_action"),
            "target_temperature": main_climate_state.get("temperature"),
            "current_temperature": main_climate_state.get("current_temperature"),
        }
