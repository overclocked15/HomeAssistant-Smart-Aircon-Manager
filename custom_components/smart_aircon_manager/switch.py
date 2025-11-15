"""Switch platform for Smart Aircon Manager."""
from __future__ import annotations

import logging
from typing import Any

from homeassistant.components.switch import SwitchEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .const import DOMAIN

_LOGGER = logging.getLogger(__name__)


async def async_setup_entry(
    hass: HomeAssistant,
    config_entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up Smart Aircon Manager switch platform."""
    data = hass.data[DOMAIN][config_entry.entry_id]
    optimizer = data["optimizer"]

    entities = [
        ManualOverrideSwitch(optimizer, config_entry),
    ]

    async_add_entities(entities)


class ManualOverrideSwitch(SwitchEntity):
    """Switch to enable/disable manual override mode."""

    def __init__(self, optimizer, config_entry: ConfigEntry) -> None:
        """Initialize the manual override switch."""
        self._optimizer = optimizer
        self._config_entry = config_entry
        self._attr_name = "Manual Override"
        self._attr_unique_id = f"{config_entry.entry_id}_manual_override"
        self._attr_icon = "mdi:account-wrench"

        # Initialize the override state in the optimizer
        if not hasattr(self._optimizer, 'manual_override_enabled'):
            self._optimizer.manual_override_enabled = False

    @property
    def device_info(self):
        """Return device info."""
        from . import get_device_info
        return get_device_info(self._config_entry)

    @property
    def is_on(self) -> bool:
        """Return true if manual override is enabled."""
        return getattr(self._optimizer, 'manual_override_enabled', False)

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        """Return extra state attributes."""
        return {
            "description": "When enabled, automatic optimization is disabled, allowing manual control",
            "status": "Active - Manual Control" if self.is_on else "Inactive - Automatic Control",
        }

    async def async_turn_on(self, **kwargs: Any) -> None:
        """Enable manual override mode."""
        self._optimizer.manual_override_enabled = True
        self.async_write_ha_state()
        _LOGGER.info("Manual override ENABLED - automatic optimization disabled")

    async def async_turn_off(self, **kwargs: Any) -> None:
        """Disable manual override mode."""
        self._optimizer.manual_override_enabled = False
        self.async_write_ha_state()
        _LOGGER.info("Manual override DISABLED - automatic optimization enabled")
