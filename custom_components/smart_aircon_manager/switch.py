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

    from .const import CONF_ENABLE_BATTERY_MODE, CONF_ENABLE_EFFICIENCY_MODE

    entities = [
        ManualOverrideSwitch(optimizer, config_entry),
        OptimizerFeatureSwitch(
            optimizer, config_entry, "enable_efficiency_mode", CONF_ENABLE_EFFICIENCY_MODE,
            "Efficient Operation", "mdi:leaf",
        ),
    ]
    # Battery-aware mode needs a battery sensor (chosen on the options page)
    if optimizer.battery_soc_entity:
        entities.append(OptimizerFeatureSwitch(
            optimizer, config_entry, "enable_battery_mode", CONF_ENABLE_BATTERY_MODE,
            "Battery-Aware Mode", "mdi:home-battery",
        ))

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

        self._hass = None  # Set when added to hass
        # Restore override state from config entry data, or default to False
        saved_state = config_entry.data.get("manual_override_enabled", False)
        if not hasattr(self._optimizer, 'manual_override_enabled'):
            self._optimizer.manual_override_enabled = saved_state

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
        self._persist_state(True)
        self.async_write_ha_state()
        _LOGGER.info("Manual override ENABLED - automatic optimization disabled")

    async def async_turn_off(self, **kwargs: Any) -> None:
        """Disable manual override mode."""
        self._optimizer.manual_override_enabled = False
        self._persist_state(False)
        self.async_write_ha_state()
        _LOGGER.info("Manual override DISABLED - automatic optimization enabled")

    def _persist_state(self, enabled: bool) -> None:
        """Persist manual override state to config entry."""
        try:
            new_data = {**self._config_entry.data, "manual_override_enabled": enabled}
            self.hass.config_entries.async_update_entry(
                self._config_entry, data=new_data
            )
        except Exception:
            _LOGGER.debug("Could not persist manual override state")


class OptimizerFeatureSwitch(SwitchEntity):
    """Toggle an optimizer feature at runtime (persisted to the config entry).

    Lets dashboards and automations switch efficient operation or
    battery-aware mode on and off (e.g. only in summer) without opening the
    options page.
    """

    def __init__(
        self, optimizer, config_entry: ConfigEntry, attribute: str, conf_key: str, name: str, icon: str
    ) -> None:
        """Initialize the switch."""
        self._optimizer = optimizer
        self._config_entry = config_entry
        self._attribute = attribute
        self._conf_key = conf_key
        self._attr_name = name
        self._attr_icon = icon
        self._attr_unique_id = f"{config_entry.entry_id}_{conf_key}"

    @property
    def device_info(self):
        """Return device info."""
        from . import get_device_info
        return get_device_info(self._config_entry)

    @property
    def is_on(self) -> bool:
        """Return true if the feature is enabled."""
        return bool(getattr(self._optimizer, self._attribute, False))

    async def async_turn_on(self, **kwargs: Any) -> None:
        """Enable the feature."""
        self._set(True)

    async def async_turn_off(self, **kwargs: Any) -> None:
        """Disable the feature."""
        self._set(False)

    def _set(self, enabled: bool) -> None:
        setattr(self._optimizer, self._attribute, enabled)
        try:
            new_data = {**self._config_entry.data, self._conf_key: enabled}
            self.hass.config_entries.async_update_entry(self._config_entry, data=new_data)
        except Exception:
            _LOGGER.debug("Could not persist %s", self._conf_key)
        self.async_write_ha_state()
        _LOGGER.info("%s %s", self._attr_name, "enabled" if enabled else "disabled")
