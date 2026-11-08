"""Switch platform for Smart Aircon Manager."""
from __future__ import annotations

import logging
from typing import Any

from homeassistant.components.switch import SwitchEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .const import (
    CONF_ENABLE_BATTERY_MODE,
    CONF_ENABLE_EFFICIENCY_MODE,
    CONF_ENABLE_NIGHT_MODE,
    CONF_EXCLUDED_ROOMS,
    CONF_NIGHT_MODE_SAVED_TARGET,
    CONF_NIGHT_MODE_TEMP_DROP,
    CONF_TARGET_TEMPERATURE,
    DEFAULT_NIGHT_MODE_TEMP_DROP,
    DOMAIN,
)
from .night_mode import night_mode_entry_data

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

    # Night mode needs its rooms (chosen on the Night Mode options page)
    if optimizer.night_mode_rooms:
        entities.append(NightModeSwitch(optimizer, config_entry, data.get("coordinator")))

    # One "In Use" switch per room: off closes the room off and leaves it out
    # of every AC decision, keeping its configuration
    for room in optimizer.room_configs:
        entities.append(RoomInUseSwitch(optimizer, config_entry, room["room_name"], data.get("coordinator")))

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
        # Set by switches whose change should take effect at once
        self._coordinator = None

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
        """Save the new state first, then apply it.

        If saving fails nothing changes, so the running state never drifts
        from the stored one (night mode's on/off transitions depend on it).
        """
        new_data = self._new_entry_data(enabled)
        try:
            self.hass.config_entries.async_update_entry(self._config_entry, data=new_data)
        except Exception as err:  # noqa: BLE001 - report and leave the state alone
            _LOGGER.warning("Could not save %s (%s) - left unchanged", self._attr_name, err)
            self.async_write_ha_state()
            return
        self._apply(enabled, new_data)
        self.async_write_ha_state()
        _LOGGER.info("%s %s", self._attr_name, "enabled" if enabled else "disabled")

    def _new_entry_data(self, enabled: bool) -> dict[str, Any]:
        """Entry data with the feature switched on or off."""
        return {**self._config_entry.data, self._conf_key: enabled}

    def _apply(self, enabled: bool, new_data: dict[str, Any]) -> None:
        """Apply a saved change to the running optimizer."""
        setattr(self._optimizer, self._attribute, enabled)

    async def _refresh(self) -> None:
        """Show a change at once (e.g. the target on the climate card), then
        run a cycle with it instead of waiting for the next poll."""
        if self._coordinator is not None:
            self._coordinator.async_update_listeners()
            await self._coordinator.async_request_refresh()


class NightModeSwitch(OptimizerFeatureSwitch):
    """Condition only the night-mode rooms and close off the rest.

    Toggle it from a dashboard or an automation (e.g. on at bedtime, off in
    the morning). The state survives restarts. With a temperature drop set,
    turning it on lowers the target once and turning it off restores the
    target from before (see night_mode_entry_data).
    """

    # New entity, so it can follow the documented naming without renaming
    # anyone's existing entities: switch.smart_aircon_manager_night_mode
    _attr_has_entity_name = True

    def __init__(self, optimizer, config_entry: ConfigEntry, coordinator=None) -> None:
        """Initialize the night mode switch."""
        super().__init__(
            optimizer, config_entry, "enable_night_mode", CONF_ENABLE_NIGHT_MODE,
            "Night Mode", "mdi:weather-night",
        )
        self._coordinator = coordinator

    async def async_added_to_hass(self) -> None:
        """Refresh the closed-room attributes after every cycle."""
        await super().async_added_to_hass()
        if self._coordinator is not None:
            self.async_on_remove(self._coordinator.async_add_listener(self.async_write_ha_state))

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        """Return the rooms night mode focuses on, the rooms it closes and
        the temperature drop."""
        closed = []
        if self._optimizer.night_mode_active:
            # The rooms night mode closed as of the last cycle (a room in a
            # critical-room emergency stays open; rooms switched out of use
            # are closed anyway and listed on their own switches)
            closed = sorted(
                set(self._optimizer._night_mode_applied_closed or []) - set(self._optimizer.excluded_rooms)
            )
        data = self._config_entry.data
        return {
            "night_mode_rooms": list(self._optimizer.night_mode_rooms),
            "closed_rooms": closed,
            "closed_position": self._optimizer.night_mode_closed_position,
            "temperature_drop": data.get(CONF_NIGHT_MODE_TEMP_DROP, DEFAULT_NIGHT_MODE_TEMP_DROP),
            # The target night mode restores when it turns off (None when
            # no drop was applied)
            "restores_target": data.get(CONF_NIGHT_MODE_SAVED_TARGET),
        }

    def _new_entry_data(self, enabled: bool) -> dict[str, Any]:
        """Entry data with night mode on or off, its drop applied or undone."""
        return night_mode_entry_data(self._config_entry.data, enabled, self._optimizer.target_temperature)

    def _apply(self, enabled: bool, new_data: dict[str, Any]) -> None:
        """Switch the optimizer over, including any target change."""
        self._optimizer.enable_night_mode = enabled
        new_target = new_data.get(CONF_TARGET_TEMPERATURE)
        if new_target is not None and float(new_target) != self._optimizer.target_temperature:
            previous = self._optimizer.target_temperature
            self._optimizer.target_temperature = float(new_target)
            _LOGGER.info(
                "Night mode %s - target %.1f -> %.1f °C",
                "on" if enabled else "off", previous, float(new_target),
            )

    async def async_turn_on(self, **kwargs: Any) -> None:
        """Turn night mode on and apply it now."""
        self._set(True)
        await self._refresh()

    async def async_turn_off(self, **kwargs: Any) -> None:
        """Turn night mode off and reopen the house now."""
        self._set(False)
        await self._refresh()


class RoomInUseSwitch(OptimizerFeatureSwitch):
    """Take a room out of use, and back, without reconfiguring it.

    Off: the room's zone closes (to the closed-off position) and the room
    stops counting toward any AC decision, like a room night mode closes.
    On: it's managed again straight away. Its sensors keep reporting either
    way, and a critical-room emergency still opens it.
    """

    _attr_has_entity_name = True

    def __init__(self, optimizer, config_entry: ConfigEntry, room_name: str, coordinator=None) -> None:
        """Initialize the switch for one room."""
        super().__init__(
            optimizer, config_entry, "excluded_rooms", CONF_EXCLUDED_ROOMS,
            f"{room_name} In Use", "mdi:door-open",
        )
        self._room_name = room_name
        self._coordinator = coordinator
        room_id = room_name.lower().replace(" ", "_")
        self._attr_unique_id = f"{config_entry.entry_id}_{room_id}_in_use"

    @property
    def is_on(self) -> bool:
        """Return true while the room is managed.

        Reflects what the optimizer does: if every room were out of use the
        exclusions are ignored, and the switches then show every room on.
        """
        return self._room_name not in self._optimizer._excluded_rooms_now()

    @property
    def icon(self) -> str:
        """Door open while in use, closed while out of use."""
        return "mdi:door-open" if self.is_on else "mdi:door-closed"

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        """Return the room and the zone position used while out of use."""
        return {
            "room": self._room_name,
            "closed_position": self._optimizer.night_mode_closed_position,
        }

    async def async_turn_on(self, **kwargs: Any) -> None:
        """Put the room back in use."""
        await self._set_in_use(True)

    async def async_turn_off(self, **kwargs: Any) -> None:
        """Take the room out of use."""
        await self._set_in_use(False)

    async def _set_in_use(self, in_use: bool) -> None:
        if in_use == (self._room_name not in self._optimizer.excluded_rooms):
            return  # already stored that way
        self._set(in_use)
        await self._refresh()

    def _new_entry_data(self, enabled: bool) -> dict[str, Any]:
        """Entry data with this room in or out of use."""
        excluded = [room for room in self._optimizer.excluded_rooms if room != self._room_name]
        if not enabled:
            excluded.append(self._room_name)
            rooms = {cfg["room_name"] for cfg in self._optimizer.room_configs}
            if rooms <= set(excluded):
                # Every zone closed would leave nothing to manage, with the
                # AC blowing into closed ducts
                raise HomeAssistantError(
                    f"Can't take {self._room_name} out of use: at least one room has to stay in use"
                )
        return {**self._config_entry.data, CONF_EXCLUDED_ROOMS: excluded}

    def _apply(self, enabled: bool, new_data: dict[str, Any]) -> None:
        """Switch the optimizer over to the saved list."""
        self._optimizer.excluded_rooms = list(new_data[CONF_EXCLUDED_ROOMS])
