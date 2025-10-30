"""The Smart Aircon Manager integration."""
from __future__ import annotations

import logging
from datetime import timedelta

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import Platform
from homeassistant.core import HomeAssistant
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator

from .const import (
    DOMAIN,
    DEFAULT_UPDATE_INTERVAL,
    DEFAULT_DATA_POLL_INTERVAL,
    DEFAULT_TEMPERATURE_DEADBAND,
    DEFAULT_HVAC_MODE,
    DEFAULT_AUTO_CONTROL_MAIN_AC,
    DEFAULT_AUTO_CONTROL_AC_TEMPERATURE,
    DEFAULT_ENABLE_NOTIFICATIONS,
    DEFAULT_AC_TURN_ON_THRESHOLD,
    DEFAULT_AC_TURN_OFF_THRESHOLD,
    DEFAULT_MAIN_FAN_HIGH_THRESHOLD,
    DEFAULT_MAIN_FAN_MEDIUM_THRESHOLD,
    DEFAULT_WEATHER_INFLUENCE_FACTOR,
    DEFAULT_OVERSHOOT_TIER1_THRESHOLD,
    DEFAULT_OVERSHOOT_TIER2_THRESHOLD,
    DEFAULT_OVERSHOOT_TIER3_THRESHOLD,
)
from .optimizer import AirconOptimizer

_LOGGER = logging.getLogger(__name__)

PLATFORMS: list[Platform] = [Platform.CLIMATE, Platform.SENSOR, Platform.BINARY_SENSOR]


def get_device_info(config_entry: ConfigEntry) -> dict:
    """Get device info for all entities."""
    return {
        "identifiers": {(DOMAIN, config_entry.entry_id)},
        "name": "Smart Aircon Manager",
        "manufacturer": "Smart Aircon Manager",
        "model": "Logic-Based HVAC Controller",
        "sw_version": "1.8.3",
    }


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Set up Smart Aircon Manager from a config entry."""
    hass.data.setdefault(DOMAIN, {})

    # Create the optimizer instance
    optimizer = AirconOptimizer(
        hass=hass,
        target_temperature=entry.data.get("target_temperature", 22),
        room_configs=entry.data.get("room_configs", {}),
        main_climate_entity=entry.data.get("main_climate_entity"),
        main_fan_entity=entry.data.get("main_fan_entity"),
        temperature_deadband=entry.data.get("temperature_deadband", DEFAULT_TEMPERATURE_DEADBAND),
        hvac_mode=entry.data.get("hvac_mode", DEFAULT_HVAC_MODE),
        auto_control_main_ac=entry.data.get("auto_control_main_ac", DEFAULT_AUTO_CONTROL_MAIN_AC),
        auto_control_ac_temperature=entry.data.get("auto_control_ac_temperature", DEFAULT_AUTO_CONTROL_AC_TEMPERATURE),
        enable_notifications=entry.data.get("enable_notifications", DEFAULT_ENABLE_NOTIFICATIONS),
        room_overrides=entry.data.get("room_overrides", {}),
        config_entry=entry,
        ac_turn_on_threshold=entry.data.get("ac_turn_on_threshold", DEFAULT_AC_TURN_ON_THRESHOLD),
        ac_turn_off_threshold=entry.data.get("ac_turn_off_threshold", DEFAULT_AC_TURN_OFF_THRESHOLD),
        weather_entity=entry.data.get("weather_entity"),
        enable_weather_adjustment=entry.data.get("enable_weather_adjustment", False),
        outdoor_temp_sensor=entry.data.get("outdoor_temp_sensor"),
        enable_scheduling=entry.data.get("enable_scheduling", False),
        schedules=entry.data.get("schedules", []),
        main_fan_high_threshold=entry.data.get("main_fan_high_threshold", DEFAULT_MAIN_FAN_HIGH_THRESHOLD),
        main_fan_medium_threshold=entry.data.get("main_fan_medium_threshold", DEFAULT_MAIN_FAN_MEDIUM_THRESHOLD),
        weather_influence_factor=entry.data.get("weather_influence_factor", DEFAULT_WEATHER_INFLUENCE_FACTOR),
        overshoot_tier1_threshold=entry.data.get("overshoot_tier1_threshold", DEFAULT_OVERSHOOT_TIER1_THRESHOLD),
        overshoot_tier2_threshold=entry.data.get("overshoot_tier2_threshold", DEFAULT_OVERSHOOT_TIER2_THRESHOLD),
        overshoot_tier3_threshold=entry.data.get("overshoot_tier3_threshold", DEFAULT_OVERSHOOT_TIER3_THRESHOLD),
    )

    # Get update interval from config (for AI optimization)
    update_interval = entry.data.get("update_interval", DEFAULT_UPDATE_INTERVAL)

    # Pass the AI optimization interval to the optimizer
    optimizer._ai_optimization_interval = update_interval * 60  # Convert minutes to seconds
    _LOGGER.info(
        "AI optimization interval set to %d minutes (%d seconds)",
        update_interval,
        optimizer._ai_optimization_interval
    )

    # Create coordinator for frequent data polling (independent of AI optimization)
    coordinator = DataUpdateCoordinator(
        hass,
        _LOGGER,
        name=DOMAIN,
        update_method=optimizer.async_optimize,
        update_interval=timedelta(seconds=DEFAULT_DATA_POLL_INTERVAL),
    )

    # Store the optimizer and coordinator
    hass.data[DOMAIN][entry.entry_id] = {
        "optimizer": optimizer,
        "coordinator": coordinator,
    }

    # Fetch initial data
    await coordinator.async_config_entry_first_refresh()

    # Setup platforms
    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)

    # Register reload service
    async def async_reload_service(call):
        """Handle reload service call."""
        _LOGGER.info("Reloading Smart Aircon Manager integration")
        await hass.config_entries.async_reload(entry.entry_id)

    # Register services (only once for first entry)
    if not hass.services.has_service(DOMAIN, "reload"):
        hass.services.async_register(DOMAIN, "reload", async_reload_service)
        _LOGGER.debug("Registered reload service")

        # Register force_optimize service
        async def async_force_optimize_service(call):
            """Handle force_optimize service call."""
            config_entry_id = call.data.get("config_entry_id")

            if config_entry_id:
                # Run for specific entry
                if config_entry_id in hass.data[DOMAIN]:
                    _LOGGER.info("Force running optimization for entry %s", config_entry_id)
                    coordinator = hass.data[DOMAIN][config_entry_id]["coordinator"]
                    await coordinator.async_refresh()
                else:
                    _LOGGER.error("Config entry %s not found", config_entry_id)
            else:
                # Run for all entries
                _LOGGER.info("Force running optimization for all entries")
                for entry_id in hass.data[DOMAIN]:
                    coordinator = hass.data[DOMAIN][entry_id]["coordinator"]
                    await coordinator.async_refresh()

        hass.services.async_register(DOMAIN, "force_optimize", async_force_optimize_service)
        _LOGGER.debug("Registered force_optimize service")

        # Register reset_smoothing service
        async def async_reset_smoothing_service(call):
            """Handle reset_smoothing service call."""
            config_entry_id = call.data.get("config_entry_id")

            if config_entry_id:
                if config_entry_id in hass.data[DOMAIN]:
                    _LOGGER.info("Resetting smoothing for entry %s", config_entry_id)
                    optimizer = hass.data[DOMAIN][config_entry_id]["optimizer"]
                    optimizer._last_fan_speeds = {}
                else:
                    _LOGGER.error("Config entry %s not found", config_entry_id)
            else:
                # Reset for all entries
                _LOGGER.info("Resetting smoothing for all entries")
                for entry_id in hass.data[DOMAIN]:
                    optimizer = hass.data[DOMAIN][entry_id]["optimizer"]
                    optimizer._last_fan_speeds = {}

        hass.services.async_register(DOMAIN, "reset_smoothing", async_reset_smoothing_service)
        _LOGGER.debug("Registered reset_smoothing service")

        # Register set_room_override service
        async def async_set_room_override_service(call):
            """Handle set_room_override service call."""
            config_entry_id = call.data.get("config_entry_id")
            room_name = call.data.get("room_name")
            enabled = call.data.get("enabled", True)

            if not config_entry_id or not room_name:
                _LOGGER.error("config_entry_id and room_name are required")
                return

            if config_entry_id in hass.data[DOMAIN]:
                _LOGGER.info("Setting room override for %s in entry %s: enabled=%s", room_name, config_entry_id, enabled)
                optimizer = hass.data[DOMAIN][config_entry_id]["optimizer"]
                optimizer.room_overrides[f"{room_name}_enabled"] = enabled
            else:
                _LOGGER.error("Config entry %s not found", config_entry_id)

        hass.services.async_register(DOMAIN, "set_room_override", async_set_room_override_service)
        _LOGGER.debug("Registered set_room_override service")

        # Register reset_error_count service
        async def async_reset_error_count_service(call):
            """Handle reset_error_count service call."""
            config_entry_id = call.data.get("config_entry_id")

            if config_entry_id:
                if config_entry_id in hass.data[DOMAIN]:
                    _LOGGER.info("Resetting error count for entry %s", config_entry_id)
                    optimizer = hass.data[DOMAIN][config_entry_id]["optimizer"]
                    optimizer._error_count = 0
                    optimizer._last_error = None
                else:
                    _LOGGER.error("Config entry %s not found", config_entry_id)
            else:
                # Reset for all entries
                _LOGGER.info("Resetting error count for all entries")
                for entry_id in hass.data[DOMAIN]:
                    optimizer = hass.data[DOMAIN][entry_id]["optimizer"]
                    optimizer._error_count = 0
                    optimizer._last_error = None

        hass.services.async_register(DOMAIN, "reset_error_count", async_reset_error_count_service)
        _LOGGER.debug("Registered reset_error_count service")

    return True


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Unload a config entry."""
    # Cleanup optimizer resources
    optimizer = hass.data[DOMAIN][entry.entry_id]["optimizer"]
    await optimizer.async_cleanup()

    # Unload platforms
    if unload_ok := await hass.config_entries.async_unload_platforms(entry, PLATFORMS):
        hass.data[DOMAIN].pop(entry.entry_id)

        # Unregister services if this was the last entry
        if not hass.data[DOMAIN]:
            hass.services.async_remove(DOMAIN, "reload")
            hass.services.async_remove(DOMAIN, "force_optimize")
            hass.services.async_remove(DOMAIN, "reset_smoothing")
            hass.services.async_remove(DOMAIN, "set_room_override")
            hass.services.async_remove(DOMAIN, "reset_error_count")
            _LOGGER.debug("Unregistered all services")

    return unload_ok
