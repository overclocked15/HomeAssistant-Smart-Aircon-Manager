"""Config flow for Smart Aircon Manager integration."""
from __future__ import annotations

import logging
from typing import Any

import voluptuous as vol

from homeassistant import config_entries
from homeassistant.core import HomeAssistant, callback
from homeassistant.data_entry_flow import FlowResult
from homeassistant.helpers import selector
import homeassistant.helpers.config_validation as cv

from .const import (
    DOMAIN,
    CONF_TARGET_TEMPERATURE,
    CONF_ROOM_CONFIGS,
    CONF_ROOM_NAME,
    CONF_TEMPERATURE_SENSOR,
    CONF_COVER_ENTITY,
    CONF_HUMIDITY_SENSOR,
    CONF_ROOM_TARGET_TEMPERATURE,
    CONF_MAIN_CLIMATE_ENTITY,
    CONF_MAIN_FAN_ENTITY,
    CONF_UPDATE_INTERVAL,
    CONF_TEMPERATURE_DEADBAND,
    CONF_HVAC_MODE,
    CONF_AUTO_CONTROL_MAIN_AC,
    CONF_AUTO_CONTROL_AC_TEMPERATURE,
    CONF_ENABLE_NOTIFICATIONS,
    CONF_ROOM_OVERRIDES,
    CONF_WEATHER_ENTITY,
    CONF_ENABLE_WEATHER_ADJUSTMENT,
    CONF_OUTDOOR_TEMP_SENSOR,
    CONF_ENABLE_SCHEDULING,
    CONF_SCHEDULES,
    CONF_SCHEDULE_NAME,
    CONF_SCHEDULE_DAYS,
    CONF_SCHEDULE_START_TIME,
    CONF_SCHEDULE_END_TIME,
    CONF_SCHEDULE_TARGET_TEMP,
    CONF_SCHEDULE_ENABLED,
    CONF_ENABLE_HUMIDITY_CONTROL,
    CONF_TARGET_HUMIDITY,
    CONF_HUMIDITY_DEADBAND,
    CONF_DRY_MODE_HUMIDITY_THRESHOLD,
    SCHEDULE_DAYS_OPTIONS,
    HVAC_MODE_COOL,
    HVAC_MODE_HEAT,
    HVAC_MODE_AUTO,
    DEFAULT_TARGET_TEMPERATURE,
    DEFAULT_UPDATE_INTERVAL,
    DEFAULT_TEMPERATURE_DEADBAND,
    DEFAULT_HVAC_MODE,
    DEFAULT_AUTO_CONTROL_MAIN_AC,
    DEFAULT_AUTO_CONTROL_AC_TEMPERATURE,
    DEFAULT_ENABLE_NOTIFICATIONS,
    DEFAULT_ENABLE_HUMIDITY_CONTROL,
    DEFAULT_TARGET_HUMIDITY,
    DEFAULT_HUMIDITY_DEADBAND,
    DEFAULT_DRY_MODE_HUMIDITY_THRESHOLD,
    CONF_ENABLE_LEARNING,
    CONF_LEARNING_MODE,
    CONF_LEARNING_CONFIDENCE_THRESHOLD,
    CONF_LEARNING_MAX_ADJUSTMENT,
    CONF_SMOOTHING_FACTOR,
    DEFAULT_ENABLE_LEARNING,
    DEFAULT_LEARNING_MODE,
    DEFAULT_LEARNING_CONFIDENCE_THRESHOLD,
    DEFAULT_LEARNING_MAX_ADJUSTMENT,
    DEFAULT_SMOOTHING_FACTOR,
    CONF_ENABLE_ROOM_BALANCING,
    CONF_TARGET_ROOM_VARIANCE,
    CONF_BALANCING_AGGRESSIVENESS,
    CONF_MIN_AIRFLOW_PERCENT,
    DEFAULT_ENABLE_ROOM_BALANCING,
    DEFAULT_TARGET_ROOM_VARIANCE,
    DEFAULT_BALANCING_AGGRESSIVENESS,
    DEFAULT_MIN_AIRFLOW_PERCENT,
    CONF_CRITICAL_ROOMS,
    CONF_CRITICAL_TEMP_MAX,
    CONF_CRITICAL_TEMP_SAFE,
    CONF_CRITICAL_TEMP_MIN,
    CONF_CRITICAL_TEMP_MIN_SAFE,
    CONF_CRITICAL_WARNING_OFFSET,
    CONF_CRITICAL_NOTIFY_SERVICES,
    DEFAULT_CRITICAL_WARNING_OFFSET,
    CONF_ENABLE_OCCUPANCY_CONTROL,
    CONF_OCCUPANCY_SENSORS,
    CONF_VACANT_ROOM_SETBACK,
    CONF_VACANCY_TIMEOUT,
    DEFAULT_ENABLE_OCCUPANCY_CONTROL,
    DEFAULT_VACANT_ROOM_SETBACK,
    DEFAULT_VACANCY_TIMEOUT,
    CONF_ENABLE_AWAY_MODE,
    CONF_AWAY_MODE_ENTITIES,
    CONF_AWAY_MODE_DELAY_MINUTES,
    DEFAULT_ENABLE_AWAY_MODE,
    DEFAULT_AWAY_MODE_DELAY_MINUTES,
    CONF_ENABLE_PREDICTIVE_CONTROL,
    CONF_PREDICTIVE_LOOKAHEAD_MINUTES,
    CONF_PREDICTIVE_BOOST_FACTOR,
    DEFAULT_ENABLE_PREDICTIVE_CONTROL,
    DEFAULT_PREDICTIVE_LOOKAHEAD_MINUTES,
    DEFAULT_PREDICTIVE_BOOST_FACTOR,
    CONF_ENABLE_OPEN_WINDOW_DETECTION,
    CONF_OPEN_WINDOW_RATE_THRESHOLD,
    CONF_OPEN_WINDOW_PAUSE_MINUTES,
    DEFAULT_ENABLE_OPEN_WINDOW_DETECTION,
    DEFAULT_OPEN_WINDOW_RATE_THRESHOLD,
    DEFAULT_OPEN_WINDOW_PAUSE_MINUTES,
    CONF_ENABLE_COMPRESSOR_PROTECTION,
    CONF_COMPRESSOR_MIN_ON_TIME,
    CONF_COMPRESSOR_MIN_OFF_TIME,
    DEFAULT_ENABLE_COMPRESSOR_PROTECTION,
    DEFAULT_COMPRESSOR_MIN_ON_TIME,
    DEFAULT_COMPRESSOR_MIN_OFF_TIME,
    CONF_ENABLE_ENHANCED_COMPRESSOR_PROTECTION,
    CONF_COMPRESSOR_UNDERCOOL_MARGIN,
    CONF_COMPRESSOR_OVERHEAT_MARGIN,
    CONF_MIN_MODE_DURATION,
    CONF_MIN_COMPRESSOR_RUN_CYCLES,
    DEFAULT_ENABLE_ENHANCED_COMPRESSOR_PROTECTION,
    DEFAULT_COMPRESSOR_UNDERCOOL_MARGIN,
    DEFAULT_COMPRESSOR_OVERHEAT_MARGIN,
    DEFAULT_MIN_MODE_DURATION,
    DEFAULT_MIN_COMPRESSOR_RUN_CYCLES,
    CONF_AC_TURN_ON_THRESHOLD,
    CONF_AC_TURN_OFF_THRESHOLD,
    DEFAULT_AC_TURN_ON_THRESHOLD,
    DEFAULT_AC_TURN_OFF_THRESHOLD,
    CONF_MODE_CHANGE_HYSTERESIS_TIME,
    CONF_MODE_CHANGE_HYSTERESIS_TEMP,
    DEFAULT_MODE_CHANGE_HYSTERESIS_TIME,
    DEFAULT_MODE_CHANGE_HYSTERESIS_TEMP,
    CONF_FAN_ONLY_IDLE_MINUTES,
    DEFAULT_FAN_ONLY_IDLE_MINUTES,
    CONF_NOTIFY_SERVICES,
    CONF_ENABLE_FAN_SMOOTHING,
    CONF_SMOOTHING_THRESHOLD,
    DEFAULT_ENABLE_FAN_SMOOTHING,
    DEFAULT_SMOOTHING_THRESHOLD,
    CONF_SCHEDULE_ROOM_TARGETS,
)
from .temperature_utils import normalize_temperature, validate_temperature_range

_LOGGER = logging.getLogger(__name__)

STEP_USER_DATA_SCHEMA = vol.Schema(
    {
        vol.Optional(CONF_TARGET_TEMPERATURE, default=DEFAULT_TARGET_TEMPERATURE): selector.NumberSelector(
            selector.NumberSelectorConfig(min=10, max=35, step=0.5, mode="box", unit_of_measurement="°C")
        ),
        vol.Optional(CONF_MAIN_CLIMATE_ENTITY): selector.EntitySelector(
            selector.EntitySelectorConfig(domain="climate")
        ),
        vol.Optional(CONF_MAIN_FAN_ENTITY): selector.EntitySelector(
            selector.EntitySelectorConfig(domain=["fan", "climate"])
        ),
    }
)


class ConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    """Handle a config flow for Smart Aircon Manager."""

    VERSION = 2

    def __init__(self) -> None:
        """Initialize the config flow."""
        self._data: dict[str, Any] = {}
        self._rooms: list[dict[str, Any]] = []

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        """Handle the initial step."""
        if user_input is not None:
            self._data = user_input
            return await self.async_step_add_room()

        return self.async_show_form(
            step_id="user",
            data_schema=STEP_USER_DATA_SCHEMA,
        )

    def _validate_entities(self, temp_sensor: str, cover_entity: str) -> dict[str, str] | None:
        """Validate that entities exist and are available with enhanced checks."""
        return _validate_entities_common(self.hass, temp_sensor, cover_entity)

    async def async_step_add_room(
        self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        """Handle adding room configuration."""
        errors = {}

        if user_input is not None:
            # Check for duplicate room name
            new_name = user_input[CONF_ROOM_NAME].strip()
            existing_names = [r[CONF_ROOM_NAME].lower() for r in self._rooms]
            if new_name.lower() in existing_names:
                errors["base"] = "duplicate_room_name"

            # Validate entities
            if not errors:
                validation_errors = self._validate_entities(
                    user_input[CONF_TEMPERATURE_SENSOR],
                    user_input[CONF_COVER_ENTITY]
                )

                if validation_errors:
                    errors = validation_errors

            if not errors:
                # Add the current room to the list (use stripped name)
                new_room = {
                    CONF_ROOM_NAME: new_name,
                    CONF_TEMPERATURE_SENSOR: user_input[CONF_TEMPERATURE_SENSOR],
                    CONF_COVER_ENTITY: user_input[CONF_COVER_ENTITY],
                }

                # Add optional fields if provided
                if user_input.get(CONF_HUMIDITY_SENSOR):
                    new_room[CONF_HUMIDITY_SENSOR] = user_input[CONF_HUMIDITY_SENSOR]
                if user_input.get(CONF_ROOM_TARGET_TEMPERATURE) is not None:
                    new_room[CONF_ROOM_TARGET_TEMPERATURE] = user_input[CONF_ROOM_TARGET_TEMPERATURE]

                self._rooms.append(new_room)

                # Check if user wants to add another room
                if user_input.get("add_another"):
                    return await self.async_step_add_room()
                else:
                    self._data[CONF_ROOM_CONFIGS] = self._rooms
                    return self.async_create_entry(
                        title="Smart Aircon Manager", data=self._data
                    )

        return self.async_show_form(
            step_id="add_room",
            data_schema=self._get_room_schema(),
            description_placeholders={
                "rooms_added": str(len(self._rooms)),
            },
            errors=errors,
        )

    def _get_room_schema(self) -> vol.Schema:
        """Get the schema for adding a room."""
        return vol.Schema(
            {
                vol.Required(CONF_ROOM_NAME): cv.string,
                vol.Required(CONF_TEMPERATURE_SENSOR): selector.EntitySelector(
                    selector.EntitySelectorConfig(domain="sensor")
                ),
                vol.Required(CONF_COVER_ENTITY): selector.EntitySelector(
                    selector.EntitySelectorConfig(domain="cover")
                ),
                vol.Optional(CONF_HUMIDITY_SENSOR): selector.EntitySelector(
                    selector.EntitySelectorConfig(domain="sensor", device_class="humidity")
                ),
                vol.Optional(CONF_ROOM_TARGET_TEMPERATURE): selector.NumberSelector(
                    selector.NumberSelectorConfig(
                        min=10.0,
                        max=35.0,
                        step=0.5,
                        unit_of_measurement="°C",
                        mode=selector.NumberSelectorMode.BOX,
                    )
                ),
                vol.Required("add_another", default=False): cv.boolean,
            }
        )

    @staticmethod
    @callback
    def async_get_options_flow(
        config_entry: config_entries.ConfigEntry,
    ) -> config_entries.OptionsFlow:
        """Create the options flow."""
        return OptionsFlowHandler(config_entry)


def _validate_entities_common(hass, temp_sensor: str, cover_entity: str) -> dict[str, str] | None:
    """Validate that entities exist and are available with thorough checks.

    Shared validation logic used by both ConfigFlow and OptionsFlowHandler.
    """
    errors = {}

    # Check temperature sensor (normalize handles F→C conversion)
    temp_state = hass.states.get(temp_sensor)
    if not temp_state:
        errors["temperature_sensor"] = "entity_not_found"
    elif temp_state.state in ["unavailable", "unknown"]:
        errors["temperature_sensor"] = "entity_unavailable"
    else:
        # Normalize temperature (handles F→C conversion automatically)
        temp_celsius = normalize_temperature(temp_state, temp_sensor)

        if temp_celsius is None:
            _LOGGER.error("Temperature sensor %s has non-numeric state: %s", temp_sensor, temp_state.state)
            errors["temperature_sensor"] = "non_numeric_temperature"
        elif not validate_temperature_range(temp_celsius):
            _LOGGER.warning(
                "Temperature sensor %s has unrealistic value: %.1f°C (converted from %s %s)",
                temp_sensor, temp_celsius, temp_state.state,
                temp_state.attributes.get("unit_of_measurement", "°C")
            )
            errors["temperature_sensor"] = "unrealistic_temperature"

        if "temperature_sensor" not in errors and not temp_state.entity_id.startswith("sensor."):
            _LOGGER.warning("Temperature entity %s is not a sensor domain", temp_sensor)
            errors["temperature_sensor"] = "invalid_domain"

    # Check cover entity
    cover_state = hass.states.get(cover_entity)
    if not cover_state:
        errors["cover_entity"] = "entity_not_found"
    elif cover_state.state in ["unavailable", "unknown"]:
        errors["cover_entity"] = "entity_unavailable"
    else:
        if "current_position" not in cover_state.attributes:
            _LOGGER.warning("Cover entity %s missing current_position attribute", cover_entity)
            errors["cover_entity"] = "missing_position_attribute"
        else:
            try:
                position = int(cover_state.attributes["current_position"])
                if not (0 <= position <= 100):
                    _LOGGER.warning("Cover %s position %d outside valid range (0-100)", cover_entity, position)
                    errors["cover_entity"] = "invalid_position_range"
            except (ValueError, TypeError):
                _LOGGER.error("Cover %s has non-numeric position", cover_entity)
                errors["cover_entity"] = "non_numeric_position"

        if "cover_entity" not in errors and not cover_state.entity_id.startswith("cover."):
            _LOGGER.warning("Cover entity %s is not a cover domain", cover_entity)
            errors["cover_entity"] = "invalid_domain"

    return errors if errors else None


class OptionsFlowHandler(config_entries.OptionsFlow):
    """Handle options flow for the integration."""

    def __init__(self, config_entry: config_entries.ConfigEntry) -> None:
        """Initialize options flow."""
        # config_entry is already available as self.config_entry via parent class
        self._rooms = list(config_entry.data.get(CONF_ROOM_CONFIGS, []))

    async def async_step_init(
        self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        """Manage the options - show menu."""
        return self.async_show_menu(
            step_id="init",
            menu_options=[
                "settings", "manage_rooms", "room_overrides", "weather", "humidity",
                "schedules", "occupancy", "predictive", "protection", "learning",
                "balancing", "critical_rooms", "advanced",
            ],
        )

    async def async_step_settings(
        self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        """Handle settings configuration."""
        if user_input is not None:
            # Merge with existing data and update the config entry
            new_data = {**self.config_entry.data, **user_input}
            self.hass.config_entries.async_update_entry(
                self.config_entry, data=new_data
            )
            # Reload the integration to apply changes
            await self.hass.config_entries.async_reload(self.config_entry.entry_id)
            return self.async_create_entry(title="", data={})

        return self.async_show_form(
            step_id="settings",
            data_schema=vol.Schema(
                {
                    vol.Optional(
                        CONF_TARGET_TEMPERATURE,
                        default=self.config_entry.data.get(
                            CONF_TARGET_TEMPERATURE, DEFAULT_TARGET_TEMPERATURE
                        ),
                    ): selector.NumberSelector(
                        selector.NumberSelectorConfig(min=10, max=35, step=0.5, mode="box", unit_of_measurement="°C")
                    ),
                    vol.Optional(
                        CONF_TEMPERATURE_DEADBAND,
                        default=self.config_entry.data.get(
                            CONF_TEMPERATURE_DEADBAND, DEFAULT_TEMPERATURE_DEADBAND
                        ),
                    ): selector.NumberSelector(
                        selector.NumberSelectorConfig(
                            min=0.1, max=5.0, step=0.1, mode=selector.NumberSelectorMode.BOX
                        )
                    ),
                    vol.Optional(
                        CONF_UPDATE_INTERVAL,
                        default=self.config_entry.data.get(
                            CONF_UPDATE_INTERVAL, DEFAULT_UPDATE_INTERVAL
                        ),
                    ): selector.NumberSelector(
                        selector.NumberSelectorConfig(
                            min=0.5, max=60, step=0.5, mode=selector.NumberSelectorMode.BOX, unit_of_measurement="minutes"
                        )
                    ),
                    vol.Optional(
                        CONF_HVAC_MODE,
                        default=self.config_entry.data.get(CONF_HVAC_MODE, DEFAULT_HVAC_MODE),
                    ): selector.SelectSelector(
                        selector.SelectSelectorConfig(
                            options=[
                                {"label": "Cooling", "value": HVAC_MODE_COOL},
                                {"label": "Heating", "value": HVAC_MODE_HEAT},
                                {"label": "Auto (based on main climate)", "value": HVAC_MODE_AUTO},
                            ],
                            mode=selector.SelectSelectorMode.DROPDOWN,
                        )
                    ),
                    vol.Optional(
                        CONF_MAIN_CLIMATE_ENTITY,
                        # suggested_value pre-fills the field for editing without
                        # substituting on empty submit, so the user can clear it.
                        **({'description': {'suggested_value': self.config_entry.data[CONF_MAIN_CLIMATE_ENTITY]}}
                           if CONF_MAIN_CLIMATE_ENTITY in self.config_entry.data else {}),
                    ): selector.EntitySelector(
                        selector.EntitySelectorConfig(domain="climate")
                    ),
                    vol.Optional(
                        CONF_AUTO_CONTROL_MAIN_AC,
                        default=self.config_entry.data.get(
                            CONF_AUTO_CONTROL_MAIN_AC, DEFAULT_AUTO_CONTROL_MAIN_AC
                        ),
                    ): cv.boolean,
                    vol.Optional(
                        CONF_AUTO_CONTROL_AC_TEMPERATURE,
                        default=self.config_entry.data.get(
                            CONF_AUTO_CONTROL_AC_TEMPERATURE, DEFAULT_AUTO_CONTROL_AC_TEMPERATURE
                        ),
                    ): cv.boolean,
                    vol.Optional(
                        CONF_MAIN_FAN_ENTITY,
                        **({'description': {'suggested_value': self.config_entry.data[CONF_MAIN_FAN_ENTITY]}}
                           if CONF_MAIN_FAN_ENTITY in self.config_entry.data else {}),
                    ): selector.EntitySelector(
                        selector.EntitySelectorConfig(domain=["fan", "climate"])
                    ),
                    vol.Optional(
                        CONF_ENABLE_NOTIFICATIONS,
                        default=self.config_entry.data.get(
                            CONF_ENABLE_NOTIFICATIONS, DEFAULT_ENABLE_NOTIFICATIONS
                        ),
                    ): cv.boolean,
                }
            ),
        )

    async def async_step_manage_rooms(
        self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        """Manage room configurations."""
        if user_input is not None:
            if user_input.get("action") == "add":
                return await self.async_step_add_room()
            elif user_input.get("action") == "edit":
                return await self.async_step_select_room_to_edit()
            elif user_input.get("action") == "remove":
                return await self.async_step_remove_room()
            elif user_input.get("action") == "done":
                return self.async_create_entry(title="", data={})

        current_rooms = self.config_entry.data.get(CONF_ROOM_CONFIGS, [])
        room_list = "\n".join([f"- {room[CONF_ROOM_NAME]}" for room in current_rooms])

        return self.async_show_form(
            step_id="manage_rooms",
            data_schema=vol.Schema(
                {
                    vol.Required("action"): selector.SelectSelector(
                        selector.SelectSelectorConfig(
                            options=[
                                {"label": "Add new room", "value": "add"},
                                {"label": "Edit existing room", "value": "edit"},
                                {"label": "Remove existing room", "value": "remove"},
                                {"label": "Done", "value": "done"},
                            ],
                            mode=selector.SelectSelectorMode.LIST,
                        )
                    ),
                }
            ),
            description_placeholders={
                "current_rooms": room_list or "None configured",
            },
        )

    def _validate_entities(self, temp_sensor: str, cover_entity: str) -> dict[str, str] | None:
        """Validate that entities exist and are available."""
        return _validate_entities_common(self.hass, temp_sensor, cover_entity)

    async def async_step_add_room(
        self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        """Add a new room."""
        errors = {}

        if user_input is not None:
            # Check for duplicate room name
            current_rooms = list(self.config_entry.data.get(CONF_ROOM_CONFIGS, []))
            existing_names = [room[CONF_ROOM_NAME].lower() for room in current_rooms]
            if user_input[CONF_ROOM_NAME].strip().lower() in existing_names:
                errors["room_name"] = "duplicate_room_name"

            # Validate entities
            if not errors:
                validation_errors = self._validate_entities(
                    user_input[CONF_TEMPERATURE_SENSOR],
                    user_input[CONF_COVER_ENTITY]
                )

                if validation_errors:
                    errors = validation_errors

            if not errors:
                # Add the room
                new_room = {
                    CONF_ROOM_NAME: user_input[CONF_ROOM_NAME].strip(),
                    CONF_TEMPERATURE_SENSOR: user_input[CONF_TEMPERATURE_SENSOR],
                    CONF_COVER_ENTITY: user_input[CONF_COVER_ENTITY],
                }

                # Add optional fields if provided
                if user_input.get(CONF_HUMIDITY_SENSOR):
                    new_room[CONF_HUMIDITY_SENSOR] = user_input[CONF_HUMIDITY_SENSOR]
                if user_input.get(CONF_ROOM_TARGET_TEMPERATURE) is not None:
                    new_room[CONF_ROOM_TARGET_TEMPERATURE] = user_input[CONF_ROOM_TARGET_TEMPERATURE]

                current_rooms = list(self.config_entry.data.get(CONF_ROOM_CONFIGS, []))
                current_rooms.append(new_room)

                # Update the config entry
                new_data = {**self.config_entry.data, CONF_ROOM_CONFIGS: current_rooms}
                self.hass.config_entries.async_update_entry(
                    self.config_entry, data=new_data
                )

                # Reload the integration
                await self.hass.config_entries.async_reload(self.config_entry.entry_id)

                return await self.async_step_manage_rooms()

        return self.async_show_form(
            step_id="add_room",
            data_schema=vol.Schema(
                {
                    vol.Required(CONF_ROOM_NAME): cv.string,
                    vol.Required(CONF_TEMPERATURE_SENSOR): selector.EntitySelector(
                        selector.EntitySelectorConfig(domain="sensor")
                    ),
                    vol.Required(CONF_COVER_ENTITY): selector.EntitySelector(
                        selector.EntitySelectorConfig(domain="cover")
                    ),
                    vol.Optional(CONF_HUMIDITY_SENSOR): selector.EntitySelector(
                        selector.EntitySelectorConfig(domain="sensor", device_class="humidity")
                    ),
                    vol.Optional(CONF_ROOM_TARGET_TEMPERATURE): selector.NumberSelector(
                        selector.NumberSelectorConfig(
                            min=10.0,
                            max=35.0,
                            step=0.5,
                            unit_of_measurement="°C",
                            mode=selector.NumberSelectorMode.BOX,
                        )
                    ),
                }
            ),
            errors=errors,
        )

    async def async_step_remove_room(
        self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        """Remove a room."""
        current_rooms = self.config_entry.data.get(CONF_ROOM_CONFIGS, [])

        if not current_rooms:
            return await self.async_step_manage_rooms()

        if user_input is not None:
            room_to_remove = user_input["room_to_remove"]

            # Remove the selected room
            updated_rooms = [
                room for room in current_rooms
                if room[CONF_ROOM_NAME] != room_to_remove
            ]

            # Update the config entry, cleaning up per-room config keyed by
            # room name so a future room reusing the name doesn't silently
            # inherit stale overrides / critical thresholds / sensors.
            new_data = {**self.config_entry.data, CONF_ROOM_CONFIGS: updated_rooms}

            overrides = dict(new_data.get(CONF_ROOM_OVERRIDES, {}))
            if overrides.pop(f"{room_to_remove}_enabled", None) is not None:
                new_data[CONF_ROOM_OVERRIDES] = overrides

            critical = dict(new_data.get(CONF_CRITICAL_ROOMS, {}))
            if critical.pop(room_to_remove, None) is not None:
                new_data[CONF_CRITICAL_ROOMS] = critical

            occupancy = dict(new_data.get(CONF_OCCUPANCY_SENSORS, {}))
            if occupancy.pop(room_to_remove, None) is not None:
                new_data[CONF_OCCUPANCY_SENSORS] = occupancy

            # Drop the room from any schedule's per-room targets
            schedules = [dict(s) for s in new_data.get(CONF_SCHEDULES, [])]
            for schedule in schedules:
                targets = schedule.get(CONF_SCHEDULE_ROOM_TARGETS)
                if targets and room_to_remove in targets:
                    targets = dict(targets)
                    targets.pop(room_to_remove)
                    schedule[CONF_SCHEDULE_ROOM_TARGETS] = targets
            new_data[CONF_SCHEDULES] = schedules

            self.hass.config_entries.async_update_entry(
                self.config_entry, data=new_data
            )

            # Reload the integration
            await self.hass.config_entries.async_reload(self.config_entry.entry_id)

            return await self.async_step_manage_rooms()

        # Create list of rooms to choose from
        room_options = [
            {"label": room[CONF_ROOM_NAME], "value": room[CONF_ROOM_NAME]}
            for room in current_rooms
        ]

        return self.async_show_form(
            step_id="remove_room",
            data_schema=vol.Schema(
                {
                    vol.Required("room_to_remove"): selector.SelectSelector(
                        selector.SelectSelectorConfig(
                            options=room_options,
                            mode=selector.SelectSelectorMode.DROPDOWN,
                        )
                    ),
                }
            ),
        )

    async def async_step_select_room_to_edit(
        self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        """Select which room to edit."""
        current_rooms = self.config_entry.data.get(CONF_ROOM_CONFIGS, [])

        if not current_rooms:
            return await self.async_step_manage_rooms()

        if user_input is not None:
            # Store the selected room name and show edit form
            self._room_to_edit = user_input["room_to_edit"]
            return await self.async_step_edit_room()

        # Create list of rooms to choose from
        room_options = [
            {"label": room[CONF_ROOM_NAME], "value": room[CONF_ROOM_NAME]}
            for room in current_rooms
        ]

        return self.async_show_form(
            step_id="select_room_to_edit",
            data_schema=vol.Schema(
                {
                    vol.Required("room_to_edit"): selector.SelectSelector(
                        selector.SelectSelectorConfig(
                            options=room_options,
                            mode=selector.SelectSelectorMode.DROPDOWN,
                        )
                    ),
                }
            ),
        )

    async def async_step_edit_room(
        self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        """Edit an existing room."""
        current_rooms = list(self.config_entry.data.get(CONF_ROOM_CONFIGS, []))
        room_to_edit_name = getattr(self, '_room_to_edit', None)

        # Find the room to edit
        room_to_edit = next(
            (room for room in current_rooms if room[CONF_ROOM_NAME] == room_to_edit_name),
            None
        )

        if not room_to_edit:
            return await self.async_step_manage_rooms()

        errors = {}

        if user_input is not None:
            # Check for duplicate room name (allow keeping the same name)
            new_name = user_input[CONF_ROOM_NAME].strip()
            if new_name.lower() != room_to_edit_name.lower():
                existing_names = [room[CONF_ROOM_NAME].lower() for room in current_rooms]
                if new_name.lower() in existing_names:
                    errors["room_name"] = "duplicate_room_name"

            # Validate entities
            if not errors:
                validation_errors = self._validate_entities(
                    user_input[CONF_TEMPERATURE_SENSOR],
                    user_input[CONF_COVER_ENTITY]
                )

                if validation_errors:
                    errors = validation_errors

            if not errors:
                # Update the room. A cleared optional field arrives as absent
                # (not None) in user_input, so an `in` check is the right way
                # to tell "user explicitly removed this" from "field omitted
                # from this step's schema entirely".
                updated_room = {
                    CONF_ROOM_NAME: new_name,
                    CONF_TEMPERATURE_SENSOR: user_input[CONF_TEMPERATURE_SENSOR],
                    CONF_COVER_ENTITY: user_input[CONF_COVER_ENTITY],
                }

                # Include optional fields if provided. If the user cleared
                # the field, voluptuous omits it from user_input — we
                # intentionally drop the key from updated_room so the override
                # is removed (rather than re-saving the old value).
                if user_input.get(CONF_HUMIDITY_SENSOR):
                    updated_room[CONF_HUMIDITY_SENSOR] = user_input[CONF_HUMIDITY_SENSOR]
                if user_input.get(CONF_ROOM_TARGET_TEMPERATURE) is not None:
                    updated_room[CONF_ROOM_TARGET_TEMPERATURE] = user_input[CONF_ROOM_TARGET_TEMPERATURE]

                # Replace the old room with updated one
                updated_rooms = [
                    updated_room if room[CONF_ROOM_NAME] == room_to_edit_name else room
                    for room in current_rooms
                ]

                new_data = {**self.config_entry.data, CONF_ROOM_CONFIGS: updated_rooms}

                # If room was renamed, migrate override and critical room settings
                if new_name != room_to_edit_name:
                    # Migrate room overrides (keyed as "{room_name}_enabled")
                    overrides = dict(new_data.get(CONF_ROOM_OVERRIDES, {}))
                    old_key = f"{room_to_edit_name}_enabled"
                    new_key = f"{new_name}_enabled"
                    if old_key in overrides:
                        overrides[new_key] = overrides.pop(old_key)
                        new_data[CONF_ROOM_OVERRIDES] = overrides

                    # Migrate critical room settings (keyed by room name)
                    critical = dict(new_data.get(CONF_CRITICAL_ROOMS, {}))
                    if room_to_edit_name in critical:
                        critical[new_name] = critical.pop(room_to_edit_name)
                        new_data[CONF_CRITICAL_ROOMS] = critical

                    # Migrate occupancy sensor mapping (keyed by room name)
                    occupancy = dict(new_data.get(CONF_OCCUPANCY_SENSORS, {}))
                    if room_to_edit_name in occupancy:
                        occupancy[new_name] = occupancy.pop(room_to_edit_name)
                        new_data[CONF_OCCUPANCY_SENSORS] = occupancy

                    # Migrate per-room schedule targets (keyed by room name)
                    schedules = [dict(s) for s in new_data.get(CONF_SCHEDULES, [])]
                    for schedule in schedules:
                        targets = schedule.get(CONF_SCHEDULE_ROOM_TARGETS)
                        if targets and room_to_edit_name in targets:
                            targets = dict(targets)
                            targets[new_name] = targets.pop(room_to_edit_name)
                            schedule[CONF_SCHEDULE_ROOM_TARGETS] = targets
                    new_data[CONF_SCHEDULES] = schedules
                self.hass.config_entries.async_update_entry(
                    self.config_entry, data=new_data
                )

                # Reload the integration
                await self.hass.config_entries.async_reload(self.config_entry.entry_id)

                return await self.async_step_manage_rooms()

        # Build schema with current values as defaults
        humidity_sensor = room_to_edit.get(CONF_HUMIDITY_SENSOR)
        schema_dict = {
            vol.Required(CONF_ROOM_NAME, default=room_to_edit[CONF_ROOM_NAME]): cv.string,
            vol.Required(CONF_TEMPERATURE_SENSOR, default=room_to_edit[CONF_TEMPERATURE_SENSOR]): selector.EntitySelector(
                selector.EntitySelectorConfig(domain="sensor")
            ),
            vol.Required(CONF_COVER_ENTITY, default=room_to_edit[CONF_COVER_ENTITY]): selector.EntitySelector(
                selector.EntitySelectorConfig(domain="cover")
            ),
        }

        # Add humidity sensor with suggested value (pre-fills the field for
        # editing but doesn't force the value back on an empty submit, so the
        # user can actually clear the field).
        if humidity_sensor:
            humidity_key = vol.Optional(
                CONF_HUMIDITY_SENSOR,
                description={"suggested_value": humidity_sensor},
            )
        else:
            humidity_key = vol.Optional(CONF_HUMIDITY_SENSOR)
        schema_dict[humidity_key] = selector.EntitySelector(
            selector.EntitySelectorConfig(domain="sensor", device_class="humidity")
        )

        # Same pattern for per-room target temperature: pre-fill via
        # suggested_value so clearing the field actually removes the override.
        # Using vol.Optional(..., default=...) would substitute the default
        # value back on empty submit, making removal impossible from the UI.
        room_target = room_to_edit.get(CONF_ROOM_TARGET_TEMPERATURE)
        if room_target is not None:
            target_key = vol.Optional(
                CONF_ROOM_TARGET_TEMPERATURE,
                description={"suggested_value": room_target},
            )
        else:
            target_key = vol.Optional(CONF_ROOM_TARGET_TEMPERATURE)
        schema_dict[target_key] = selector.NumberSelector(
            selector.NumberSelectorConfig(
                min=10.0, max=35.0, step=0.5,
                unit_of_measurement="°C",
                mode=selector.NumberSelectorMode.BOX,
            )
        )

        return self.async_show_form(
            step_id="edit_room",
            data_schema=vol.Schema(schema_dict),
            errors=errors,
            description_placeholders={
                "room_name": room_to_edit_name,
            },
        )

    async def async_step_room_overrides(
        self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        """Manage room overrides (enable/disable AI control per room)."""
        current_rooms = self.config_entry.data.get(CONF_ROOM_CONFIGS, [])
        current_overrides = self.config_entry.data.get(CONF_ROOM_OVERRIDES, {})

        if user_input is not None:
            # Convert flat user_input to nested structure for storage
            # user_input format: {"Living Room_enabled": True, "Bedroom_enabled": False}
            # storage format: {"Living Room_enabled": False, "Bedroom_enabled": True}
            # (we keep the flat structure since optimizer expects it this way)
            new_data = {**self.config_entry.data, CONF_ROOM_OVERRIDES: user_input}
            self.hass.config_entries.async_update_entry(
                self.config_entry, data=new_data
            )
            # Reload the integration
            await self.hass.config_entries.async_reload(self.config_entry.entry_id)
            return self.async_create_entry(title="", data={})

        # Build schema with a checkbox for each room
        schema_dict = {}
        for room in current_rooms:
            # Safely get room_name with error handling
            room_name = room.get(CONF_ROOM_NAME)
            if not room_name:
                _LOGGER.warning("Room missing name in config: %s", room)
                continue

            # Default to enabled (True) if not in overrides
            # current_overrides is flat: {"Living Room_enabled": False}
            is_enabled = current_overrides.get(f"{room_name}_enabled", True)
            schema_dict[vol.Optional(f"{room_name}_enabled", default=is_enabled)] = cv.boolean

        if not schema_dict:
            # No rooms configured or all rooms missing names
            _LOGGER.error("No valid rooms found for room overrides")
            return await self.async_step_init()

        return self.async_show_form(
            step_id="room_overrides",
            data_schema=vol.Schema(schema_dict),
            description_placeholders={
                "room_count": str(len(current_rooms)),
            },
        )

    async def async_step_weather(
        self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        """Handle weather integration configuration."""
        if user_input is not None:
            # Merge with existing data
            new_data = {**self.config_entry.data, **user_input}
            self.hass.config_entries.async_update_entry(
                self.config_entry, data=new_data
            )
            # Reload the integration to apply changes
            await self.hass.config_entries.async_reload(self.config_entry.entry_id)
            return self.async_create_entry(title="", data={})

        # Build schema with proper defaults (avoid None values in entity selectors)
        schema_dict = {
            vol.Optional(
                CONF_ENABLE_WEATHER_ADJUSTMENT,
                default=self.config_entry.data.get(CONF_ENABLE_WEATHER_ADJUSTMENT, False),
            ): cv.boolean,
        }

        # Pre-fill via suggested_value (not default=) so clearing the field
        # in the UI actually removes the entity. vol.Optional(..., default=X)
        # substitutes X back on empty submit, making removal impossible — same
        # pattern that broke per-room target removal in v2.16.2.
        weather_entity = self.config_entry.data.get(CONF_WEATHER_ENTITY)
        if weather_entity:
            weather_key = vol.Optional(
                CONF_WEATHER_ENTITY,
                description={"suggested_value": weather_entity},
            )
        else:
            weather_key = vol.Optional(CONF_WEATHER_ENTITY)
        schema_dict[weather_key] = selector.EntitySelector(
            selector.EntitySelectorConfig(domain="weather")
        )

        outdoor_sensor = self.config_entry.data.get(CONF_OUTDOOR_TEMP_SENSOR)
        if outdoor_sensor:
            outdoor_key = vol.Optional(
                CONF_OUTDOOR_TEMP_SENSOR,
                description={"suggested_value": outdoor_sensor},
            )
        else:
            outdoor_key = vol.Optional(CONF_OUTDOOR_TEMP_SENSOR)
        schema_dict[outdoor_key] = selector.EntitySelector(
            selector.EntitySelectorConfig(domain="sensor", device_class="temperature")
        )

        return self.async_show_form(
            step_id="weather",
            data_schema=vol.Schema(schema_dict),
            description_placeholders={
                "info": "Weather integration adjusts target temperature based on outdoor conditions. Provide either a weather entity or outdoor temperature sensor (or both for redundancy)."
            },
        )

    async def async_step_humidity(
        self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        """Handle humidity control configuration."""
        if user_input is not None:
            # Merge with existing data
            new_data = {**self.config_entry.data, **user_input}
            self.hass.config_entries.async_update_entry(
                self.config_entry, data=new_data
            )
            # Reload the integration to apply changes
            await self.hass.config_entries.async_reload(self.config_entry.entry_id)
            return self.async_create_entry(title="", data={})

        return self.async_show_form(
            step_id="humidity",
            data_schema=vol.Schema(
                {
                    vol.Optional(
                        CONF_ENABLE_HUMIDITY_CONTROL,
                        default=self.config_entry.data.get(CONF_ENABLE_HUMIDITY_CONTROL, DEFAULT_ENABLE_HUMIDITY_CONTROL),
                    ): cv.boolean,
                    vol.Optional(
                        CONF_TARGET_HUMIDITY,
                        default=self.config_entry.data.get(CONF_TARGET_HUMIDITY, DEFAULT_TARGET_HUMIDITY),
                    ): selector.NumberSelector(
                        selector.NumberSelectorConfig(
                            min=30, max=80, step=5, mode=selector.NumberSelectorMode.SLIDER, unit_of_measurement="%"
                        )
                    ),
                    vol.Optional(
                        CONF_HUMIDITY_DEADBAND,
                        default=self.config_entry.data.get(CONF_HUMIDITY_DEADBAND, DEFAULT_HUMIDITY_DEADBAND),
                    ): selector.NumberSelector(
                        selector.NumberSelectorConfig(
                            min=1, max=15, step=1, mode=selector.NumberSelectorMode.BOX, unit_of_measurement="%"
                        )
                    ),
                    vol.Optional(
                        CONF_DRY_MODE_HUMIDITY_THRESHOLD,
                        default=self.config_entry.data.get(CONF_DRY_MODE_HUMIDITY_THRESHOLD, DEFAULT_DRY_MODE_HUMIDITY_THRESHOLD),
                    ): selector.NumberSelector(
                        selector.NumberSelectorConfig(
                            min=50, max=90, step=5, mode=selector.NumberSelectorMode.SLIDER, unit_of_measurement="%"
                        )
                    ),
                }
            ),
            description_placeholders={
                "info": "Humidity control enables intelligent dehumidification. AC will switch to dry mode when humidity exceeds threshold but temperature is near target. Temperature always takes priority over humidity."
            },
        )

    async def async_step_schedules(
        self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        """Handle schedules configuration - show submenu."""
        return self.async_show_menu(
            step_id="schedules",
            menu_options=["enable_scheduling", "add_schedule", "edit_schedule", "delete_schedule"],
        )

    async def async_step_enable_scheduling(
        self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        """Enable or disable scheduling."""
        if user_input is not None:
            new_data = {**self.config_entry.data, **user_input}
            self.hass.config_entries.async_update_entry(
                self.config_entry, data=new_data
            )
            await self.hass.config_entries.async_reload(self.config_entry.entry_id)
            return self.async_create_entry(title="", data={})

        return self.async_show_form(
            step_id="enable_scheduling",
            data_schema=vol.Schema(
                {
                    vol.Optional(
                        CONF_ENABLE_SCHEDULING,
                        default=self.config_entry.data.get(CONF_ENABLE_SCHEDULING, False),
                    ): cv.boolean,
                }
            ),
        )

    async def async_step_add_schedule(
        self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        """Add a new schedule."""
        errors = {}
        if user_input is not None:
            # Get existing schedules
            current_schedules = list(self.config_entry.data.get(CONF_SCHEDULES, []))

            # Validate: no duplicate schedule names
            schedule_name = user_input[CONF_SCHEDULE_NAME].strip()
            existing_names = [s.get(CONF_SCHEDULE_NAME, "").lower() for s in current_schedules]
            if schedule_name.lower() in existing_names:
                errors["base"] = "duplicate_schedule_name"

            # Validate: start_time != end_time (an instantaneous schedule is
            # useless). Overnight schedules (start > end, e.g. 22:00 → 06:00)
            # are allowed — the optimizer's _get_active_schedule resolves them
            # via the yesterday-anchor logic added in v2.16.0.
            if not errors:
                start_time = user_input[CONF_SCHEDULE_START_TIME]
                end_time = user_input[CONF_SCHEDULE_END_TIME]
                if start_time == end_time:
                    errors["base"] = "schedule_start_equals_end"

            # Validate optional per-room targets ("Bedroom=18, Office=21.5")
            room_targets = {}
            if not errors:
                raw_targets = (user_input.get(CONF_SCHEDULE_ROOM_TARGETS) or "").strip()
                if raw_targets:
                    known_rooms = {
                        r[CONF_ROOM_NAME] for r in self.config_entry.data.get(CONF_ROOM_CONFIGS, [])
                    }
                    for part in raw_targets.split(","):
                        part = part.strip()
                        if not part:
                            continue
                        if "=" not in part:
                            errors["base"] = "invalid_room_targets_format"
                            break
                        name, _, value = part.partition("=")
                        name = name.strip()
                        if name not in known_rooms:
                            errors["base"] = "unknown_room_in_targets"
                            break
                        try:
                            temp = float(value.strip())
                        except ValueError:
                            errors["base"] = "invalid_room_targets_format"
                            break
                        if not (10.0 <= temp <= 35.0):
                            errors["base"] = "room_target_out_of_range"
                            break
                        room_targets[name] = temp

            if not errors:
                # Add new schedule
                new_schedule = {
                    CONF_SCHEDULE_NAME: schedule_name,
                    CONF_SCHEDULE_DAYS: user_input[CONF_SCHEDULE_DAYS],
                    CONF_SCHEDULE_START_TIME: user_input[CONF_SCHEDULE_START_TIME],
                    CONF_SCHEDULE_END_TIME: user_input[CONF_SCHEDULE_END_TIME],
                    CONF_SCHEDULE_TARGET_TEMP: user_input[CONF_SCHEDULE_TARGET_TEMP],
                    CONF_SCHEDULE_ENABLED: user_input.get(CONF_SCHEDULE_ENABLED, True),
                }
                if room_targets:
                    new_schedule[CONF_SCHEDULE_ROOM_TARGETS] = room_targets
                current_schedules.append(new_schedule)

                # Update config
                new_data = {**self.config_entry.data, CONF_SCHEDULES: current_schedules}
                self.hass.config_entries.async_update_entry(
                    self.config_entry, data=new_data
                )
                await self.hass.config_entries.async_reload(self.config_entry.entry_id)
                return self.async_create_entry(title="", data={})

        return self.async_show_form(
            step_id="add_schedule",
            data_schema=vol.Schema(
                {
                    vol.Required(CONF_SCHEDULE_NAME): cv.string,
                    vol.Required(CONF_SCHEDULE_DAYS): selector.SelectSelector(
                        selector.SelectSelectorConfig(
                            options=SCHEDULE_DAYS_OPTIONS,
                            multiple=True,
                            mode=selector.SelectSelectorMode.DROPDOWN,
                        )
                    ),
                    vol.Required(CONF_SCHEDULE_START_TIME): selector.TimeSelector(),
                    vol.Required(CONF_SCHEDULE_END_TIME): selector.TimeSelector(),
                    vol.Required(CONF_SCHEDULE_TARGET_TEMP, default=22): selector.NumberSelector(
                        selector.NumberSelectorConfig(
                            min=16, max=30, step=0.5, mode=selector.NumberSelectorMode.BOX, unit_of_measurement="°C"
                        )
                    ),
                    vol.Optional(CONF_SCHEDULE_ENABLED, default=True): cv.boolean,
                    # Optional per-room targets, e.g. "Bedroom=18, Office=21.5"
                    vol.Optional(CONF_SCHEDULE_ROOM_TARGETS): cv.string,
                }
            ),
            errors=errors if errors else None,
        )

    async def async_step_edit_schedule(
        self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        """Edit an existing schedule (redirect to scheduling menu)."""
        # Editing is done via delete+add; return to scheduling menu to avoid infinite loop
        return await self.async_step_schedules()

    async def async_step_delete_schedule(
        self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        """Delete a schedule."""
        current_schedules = list(self.config_entry.data.get(CONF_SCHEDULES, []))

        if not current_schedules:
            # No schedules to delete - return to scheduling menu
            return await self.async_step_schedules()

        if user_input is not None:
            # Remove the selected schedule
            schedule_name = user_input["schedule_to_delete"]
            current_schedules = [s for s in current_schedules if s.get(CONF_SCHEDULE_NAME) != schedule_name]

            # Update config
            new_data = {**self.config_entry.data, CONF_SCHEDULES: current_schedules}
            self.hass.config_entries.async_update_entry(
                self.config_entry, data=new_data
            )
            await self.hass.config_entries.async_reload(self.config_entry.entry_id)
            return self.async_create_entry(title="", data={})

        # Build list of schedule names for selection
        schedule_options = [s.get(CONF_SCHEDULE_NAME, "Unnamed") for s in current_schedules]

        return self.async_show_form(
            step_id="delete_schedule",
            data_schema=vol.Schema(
                {
                    vol.Required("schedule_to_delete"): selector.SelectSelector(
                        selector.SelectSelectorConfig(
                            options=schedule_options,
                            mode=selector.SelectSelectorMode.DROPDOWN,
                        )
                    ),
                }
            ),
        )

    async def async_step_occupancy(
        self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        """Configure occupancy control and presence-linked away mode."""
        rooms = self.config_entry.data.get(CONF_ROOM_CONFIGS, [])
        current_sensors = self.config_entry.data.get(CONF_OCCUPANCY_SENSORS, {})

        if user_input is not None:
            # Rebuild the room -> sensor map from the per-room fields. A field
            # left empty means "no occupancy sensor for this room" (cleared).
            occupancy_sensors = {}
            for room in rooms:
                room_name = room[CONF_ROOM_NAME]
                sensor = user_input.get(f"occupancy_sensor::{room_name}")
                if sensor:
                    occupancy_sensors[room_name] = sensor

            new_data = {
                **self.config_entry.data,
                CONF_ENABLE_OCCUPANCY_CONTROL: user_input.get(
                    CONF_ENABLE_OCCUPANCY_CONTROL, DEFAULT_ENABLE_OCCUPANCY_CONTROL
                ),
                CONF_OCCUPANCY_SENSORS: occupancy_sensors,
                CONF_VACANT_ROOM_SETBACK: user_input.get(
                    CONF_VACANT_ROOM_SETBACK, DEFAULT_VACANT_ROOM_SETBACK
                ),
                CONF_VACANCY_TIMEOUT: user_input.get(
                    CONF_VACANCY_TIMEOUT, DEFAULT_VACANCY_TIMEOUT
                ),
                CONF_ENABLE_AWAY_MODE: user_input.get(
                    CONF_ENABLE_AWAY_MODE, DEFAULT_ENABLE_AWAY_MODE
                ),
                CONF_AWAY_MODE_ENTITIES: user_input.get(CONF_AWAY_MODE_ENTITIES, []),
                CONF_AWAY_MODE_DELAY_MINUTES: user_input.get(
                    CONF_AWAY_MODE_DELAY_MINUTES, DEFAULT_AWAY_MODE_DELAY_MINUTES
                ),
            }
            self.hass.config_entries.async_update_entry(self.config_entry, data=new_data)
            await self.hass.config_entries.async_reload(self.config_entry.entry_id)
            return self.async_create_entry(title="", data={})

        schema_dict = {
            vol.Optional(
                CONF_ENABLE_OCCUPANCY_CONTROL,
                default=self.config_entry.data.get(
                    CONF_ENABLE_OCCUPANCY_CONTROL, DEFAULT_ENABLE_OCCUPANCY_CONTROL
                ),
            ): cv.boolean,
            vol.Optional(
                CONF_VACANT_ROOM_SETBACK,
                default=self.config_entry.data.get(
                    CONF_VACANT_ROOM_SETBACK, DEFAULT_VACANT_ROOM_SETBACK
                ),
            ): selector.NumberSelector(
                selector.NumberSelectorConfig(
                    min=0.5, max=5.0, step=0.5, unit_of_measurement="°C",
                    mode=selector.NumberSelectorMode.BOX,
                )
            ),
            vol.Optional(
                CONF_VACANCY_TIMEOUT,
                default=self.config_entry.data.get(
                    CONF_VACANCY_TIMEOUT, DEFAULT_VACANCY_TIMEOUT
                ),
            ): selector.NumberSelector(
                selector.NumberSelectorConfig(
                    min=60, max=3600, step=60, unit_of_measurement="seconds",
                    mode=selector.NumberSelectorMode.BOX,
                )
            ),
        }

        # One optional occupancy sensor per configured room
        for room in rooms:
            room_name = room[CONF_ROOM_NAME]
            key = f"occupancy_sensor::{room_name}"
            suggested = (
                {"description": {"suggested_value": current_sensors[room_name]}}
                if room_name in current_sensors else {}
            )
            schema_dict[vol.Optional(key, **suggested)] = selector.EntitySelector(
                selector.EntitySelectorConfig(
                    domain=["binary_sensor", "input_boolean", "device_tracker", "person"]
                )
            )

        # Presence-linked away mode
        schema_dict[vol.Optional(
            CONF_ENABLE_AWAY_MODE,
            default=self.config_entry.data.get(CONF_ENABLE_AWAY_MODE, DEFAULT_ENABLE_AWAY_MODE),
        )] = cv.boolean
        away_entities = self.config_entry.data.get(CONF_AWAY_MODE_ENTITIES, [])
        schema_dict[vol.Optional(
            CONF_AWAY_MODE_ENTITIES,
            **({"description": {"suggested_value": away_entities}} if away_entities else {}),
        )] = selector.EntitySelector(
            selector.EntitySelectorConfig(domain=["person", "device_tracker"], multiple=True)
        )
        schema_dict[vol.Optional(
            CONF_AWAY_MODE_DELAY_MINUTES,
            default=self.config_entry.data.get(
                CONF_AWAY_MODE_DELAY_MINUTES, DEFAULT_AWAY_MODE_DELAY_MINUTES
            ),
        )] = selector.NumberSelector(
            selector.NumberSelectorConfig(
                min=5, max=240, step=5, unit_of_measurement="minutes",
                mode=selector.NumberSelectorMode.BOX,
            )
        )

        return self.async_show_form(
            step_id="occupancy",
            data_schema=vol.Schema(schema_dict),
        )

    async def async_step_predictive(
        self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        """Configure predictive control and open-window detection."""
        if user_input is not None:
            new_data = {**self.config_entry.data, **user_input}
            self.hass.config_entries.async_update_entry(self.config_entry, data=new_data)
            await self.hass.config_entries.async_reload(self.config_entry.entry_id)
            return self.async_create_entry(title="", data={})

        data = self.config_entry.data
        return self.async_show_form(
            step_id="predictive",
            data_schema=vol.Schema(
                {
                    vol.Optional(
                        CONF_ENABLE_PREDICTIVE_CONTROL,
                        default=data.get(CONF_ENABLE_PREDICTIVE_CONTROL, DEFAULT_ENABLE_PREDICTIVE_CONTROL),
                    ): cv.boolean,
                    vol.Optional(
                        CONF_PREDICTIVE_LOOKAHEAD_MINUTES,
                        default=data.get(CONF_PREDICTIVE_LOOKAHEAD_MINUTES, DEFAULT_PREDICTIVE_LOOKAHEAD_MINUTES),
                    ): selector.NumberSelector(
                        selector.NumberSelectorConfig(
                            min=1, max=30, step=1, unit_of_measurement="minutes",
                            mode=selector.NumberSelectorMode.BOX,
                        )
                    ),
                    vol.Optional(
                        CONF_PREDICTIVE_BOOST_FACTOR,
                        default=data.get(CONF_PREDICTIVE_BOOST_FACTOR, DEFAULT_PREDICTIVE_BOOST_FACTOR),
                    ): selector.NumberSelector(
                        selector.NumberSelectorConfig(
                            min=0.0, max=1.0, step=0.05, mode=selector.NumberSelectorMode.BOX,
                        )
                    ),
                    vol.Optional(
                        CONF_ENABLE_OPEN_WINDOW_DETECTION,
                        default=data.get(CONF_ENABLE_OPEN_WINDOW_DETECTION, DEFAULT_ENABLE_OPEN_WINDOW_DETECTION),
                    ): cv.boolean,
                    vol.Optional(
                        CONF_OPEN_WINDOW_RATE_THRESHOLD,
                        default=data.get(CONF_OPEN_WINDOW_RATE_THRESHOLD, DEFAULT_OPEN_WINDOW_RATE_THRESHOLD),
                    ): selector.NumberSelector(
                        selector.NumberSelectorConfig(
                            min=0.1, max=2.0, step=0.05, unit_of_measurement="°C/min",
                            mode=selector.NumberSelectorMode.BOX,
                        )
                    ),
                    vol.Optional(
                        CONF_OPEN_WINDOW_PAUSE_MINUTES,
                        default=data.get(CONF_OPEN_WINDOW_PAUSE_MINUTES, DEFAULT_OPEN_WINDOW_PAUSE_MINUTES),
                    ): selector.NumberSelector(
                        selector.NumberSelectorConfig(
                            min=5, max=120, step=5, unit_of_measurement="minutes",
                            mode=selector.NumberSelectorMode.BOX,
                        )
                    ),
                }
            ),
        )

    async def async_step_protection(
        self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        """Configure compressor protection, AC thresholds, and idle shutdown."""
        errors = {}
        if user_input is not None:
            turn_on = user_input.get(CONF_AC_TURN_ON_THRESHOLD)
            turn_off = user_input.get(CONF_AC_TURN_OFF_THRESHOLD)
            if turn_on is not None and turn_off is not None and turn_off < turn_on:
                # Turn-off overshoot smaller than turn-on demand causes rapid cycling
                errors["base"] = "invalid_ac_threshold_ordering"

            if not errors:
                new_data = {**self.config_entry.data, **user_input}
                self.hass.config_entries.async_update_entry(self.config_entry, data=new_data)
                await self.hass.config_entries.async_reload(self.config_entry.entry_id)
                return self.async_create_entry(title="", data={})

        data = self.config_entry.data
        return self.async_show_form(
            step_id="protection",
            data_schema=vol.Schema(
                {
                    vol.Optional(
                        CONF_ENABLE_COMPRESSOR_PROTECTION,
                        default=data.get(CONF_ENABLE_COMPRESSOR_PROTECTION, DEFAULT_ENABLE_COMPRESSOR_PROTECTION),
                    ): cv.boolean,
                    vol.Optional(
                        CONF_COMPRESSOR_MIN_ON_TIME,
                        default=data.get(CONF_COMPRESSOR_MIN_ON_TIME, DEFAULT_COMPRESSOR_MIN_ON_TIME),
                    ): selector.NumberSelector(
                        selector.NumberSelectorConfig(
                            min=60, max=1800, step=30, unit_of_measurement="seconds",
                            mode=selector.NumberSelectorMode.BOX,
                        )
                    ),
                    vol.Optional(
                        CONF_COMPRESSOR_MIN_OFF_TIME,
                        default=data.get(CONF_COMPRESSOR_MIN_OFF_TIME, DEFAULT_COMPRESSOR_MIN_OFF_TIME),
                    ): selector.NumberSelector(
                        selector.NumberSelectorConfig(
                            min=60, max=1800, step=30, unit_of_measurement="seconds",
                            mode=selector.NumberSelectorMode.BOX,
                        )
                    ),
                    vol.Optional(
                        CONF_AC_TURN_ON_THRESHOLD,
                        default=data.get(CONF_AC_TURN_ON_THRESHOLD, DEFAULT_AC_TURN_ON_THRESHOLD),
                    ): selector.NumberSelector(
                        selector.NumberSelectorConfig(
                            min=0.5, max=5.0, step=0.5, unit_of_measurement="°C",
                            mode=selector.NumberSelectorMode.BOX,
                        )
                    ),
                    vol.Optional(
                        CONF_AC_TURN_OFF_THRESHOLD,
                        default=data.get(CONF_AC_TURN_OFF_THRESHOLD, DEFAULT_AC_TURN_OFF_THRESHOLD),
                    ): selector.NumberSelector(
                        selector.NumberSelectorConfig(
                            min=0.5, max=5.0, step=0.5, unit_of_measurement="°C",
                            mode=selector.NumberSelectorMode.BOX,
                        )
                    ),
                    vol.Optional(
                        CONF_MODE_CHANGE_HYSTERESIS_TIME,
                        default=data.get(CONF_MODE_CHANGE_HYSTERESIS_TIME, DEFAULT_MODE_CHANGE_HYSTERESIS_TIME),
                    ): selector.NumberSelector(
                        selector.NumberSelectorConfig(
                            min=0, max=1800, step=30, unit_of_measurement="seconds",
                            mode=selector.NumberSelectorMode.BOX,
                        )
                    ),
                    vol.Optional(
                        CONF_MODE_CHANGE_HYSTERESIS_TEMP,
                        default=data.get(CONF_MODE_CHANGE_HYSTERESIS_TEMP, DEFAULT_MODE_CHANGE_HYSTERESIS_TEMP),
                    ): selector.NumberSelector(
                        selector.NumberSelectorConfig(
                            min=0.0, max=2.0, step=0.1, unit_of_measurement="°C",
                            mode=selector.NumberSelectorMode.BOX,
                        )
                    ),
                    vol.Optional(
                        CONF_FAN_ONLY_IDLE_MINUTES,
                        default=data.get(CONF_FAN_ONLY_IDLE_MINUTES, DEFAULT_FAN_ONLY_IDLE_MINUTES),
                    ): selector.NumberSelector(
                        selector.NumberSelectorConfig(
                            min=0, max=240, step=5, unit_of_measurement="minutes",
                            mode=selector.NumberSelectorMode.BOX,
                        )
                    ),
                    vol.Optional(
                        CONF_ENABLE_ENHANCED_COMPRESSOR_PROTECTION,
                        default=data.get(CONF_ENABLE_ENHANCED_COMPRESSOR_PROTECTION, DEFAULT_ENABLE_ENHANCED_COMPRESSOR_PROTECTION),
                    ): cv.boolean,
                    vol.Optional(
                        CONF_COMPRESSOR_UNDERCOOL_MARGIN,
                        default=data.get(CONF_COMPRESSOR_UNDERCOOL_MARGIN, DEFAULT_COMPRESSOR_UNDERCOOL_MARGIN),
                    ): selector.NumberSelector(
                        selector.NumberSelectorConfig(
                            min=0.0, max=3.0, step=0.1, unit_of_measurement="°C",
                            mode=selector.NumberSelectorMode.BOX,
                        )
                    ),
                    vol.Optional(
                        CONF_COMPRESSOR_OVERHEAT_MARGIN,
                        default=data.get(CONF_COMPRESSOR_OVERHEAT_MARGIN, DEFAULT_COMPRESSOR_OVERHEAT_MARGIN),
                    ): selector.NumberSelector(
                        selector.NumberSelectorConfig(
                            min=0.0, max=3.0, step=0.1, unit_of_measurement="°C",
                            mode=selector.NumberSelectorMode.BOX,
                        )
                    ),
                    vol.Optional(
                        CONF_MIN_MODE_DURATION,
                        default=data.get(CONF_MIN_MODE_DURATION, DEFAULT_MIN_MODE_DURATION),
                    ): selector.NumberSelector(
                        selector.NumberSelectorConfig(
                            min=0, max=3600, step=60, unit_of_measurement="seconds",
                            mode=selector.NumberSelectorMode.BOX,
                        )
                    ),
                    vol.Optional(
                        CONF_MIN_COMPRESSOR_RUN_CYCLES,
                        default=data.get(CONF_MIN_COMPRESSOR_RUN_CYCLES, DEFAULT_MIN_COMPRESSOR_RUN_CYCLES),
                    ): selector.NumberSelector(
                        selector.NumberSelectorConfig(
                            min=0, max=20, step=1, mode=selector.NumberSelectorMode.BOX,
                        )
                    ),
                }
            ),
            errors=errors if errors else None,
        )

    async def async_step_learning(
        self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        """Handle adaptive learning configuration."""
        if user_input is not None:
            # Merge with existing data and update the config entry
            new_data = {**self.config_entry.data, **user_input}
            self.hass.config_entries.async_update_entry(
                self.config_entry, data=new_data
            )
            # Reload the integration to apply changes
            await self.hass.config_entries.async_reload(self.config_entry.entry_id)
            return self.async_create_entry(title="", data={})

        return self.async_show_form(
            step_id="learning",
            data_schema=vol.Schema(
                {
                    vol.Optional(
                        CONF_ENABLE_LEARNING,
                        default=self.config_entry.data.get(
                            CONF_ENABLE_LEARNING, DEFAULT_ENABLE_LEARNING
                        ),
                    ): cv.boolean,
                    vol.Optional(
                        CONF_LEARNING_MODE,
                        default=self.config_entry.data.get(
                            CONF_LEARNING_MODE, DEFAULT_LEARNING_MODE
                        ),
                    ): selector.SelectSelector(
                        selector.SelectSelectorConfig(
                            options=[
                                {"label": "Passive (Safe Data Collection)", "value": "passive"},
                                {"label": "Active (Apply Learned Optimizations)", "value": "active"},
                            ],
                            mode=selector.SelectSelectorMode.DROPDOWN,
                        )
                    ),
                    vol.Optional(
                        CONF_LEARNING_CONFIDENCE_THRESHOLD,
                        default=self.config_entry.data.get(
                            CONF_LEARNING_CONFIDENCE_THRESHOLD, DEFAULT_LEARNING_CONFIDENCE_THRESHOLD
                        ),
                    ): selector.NumberSelector(
                        selector.NumberSelectorConfig(
                            min=0.5,
                            max=0.95,
                            step=0.05,
                            mode=selector.NumberSelectorMode.SLIDER,
                        )
                    ),
                    vol.Optional(
                        CONF_LEARNING_MAX_ADJUSTMENT,
                        default=self.config_entry.data.get(
                            CONF_LEARNING_MAX_ADJUSTMENT, DEFAULT_LEARNING_MAX_ADJUSTMENT
                        ),
                    ): selector.NumberSelector(
                        selector.NumberSelectorConfig(
                            min=0.05,
                            max=0.30,
                            step=0.05,
                            mode=selector.NumberSelectorMode.SLIDER,
                        )
                    ),
                    vol.Optional(
                        CONF_SMOOTHING_FACTOR,
                        default=self.config_entry.data.get(
                            CONF_SMOOTHING_FACTOR, DEFAULT_SMOOTHING_FACTOR
                        ),
                    ): selector.NumberSelector(
                        selector.NumberSelectorConfig(
                            min=0.5,
                            max=0.95,
                            step=0.05,
                            mode=selector.NumberSelectorMode.SLIDER,
                        )
                    ),
                }
            ),
        )

    async def async_step_balancing(
        self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        """Handle inter-room balancing configuration."""
        errors = {}
        if user_input is not None:
            # Merge with existing data and update the config entry
            new_data = {**self.config_entry.data, **user_input}
            self.hass.config_entries.async_update_entry(
                self.config_entry, data=new_data
            )
            # Reload the integration to apply changes
            await self.hass.config_entries.async_reload(self.config_entry.entry_id)
            return self.async_create_entry(title="", data={})

        return self.async_show_form(
            step_id="balancing",
            data_schema=vol.Schema(
                {
                    vol.Optional(
                        CONF_ENABLE_ROOM_BALANCING,
                        default=self.config_entry.data.get(
                            CONF_ENABLE_ROOM_BALANCING, DEFAULT_ENABLE_ROOM_BALANCING
                        ),
                    ): cv.boolean,
                    vol.Optional(
                        CONF_TARGET_ROOM_VARIANCE,
                        default=self.config_entry.data.get(
                            CONF_TARGET_ROOM_VARIANCE, DEFAULT_TARGET_ROOM_VARIANCE
                        ),
                    ): selector.NumberSelector(
                        selector.NumberSelectorConfig(
                            min=0.5,
                            max=5.0,
                            step=0.5,
                            unit_of_measurement="°C",
                            mode=selector.NumberSelectorMode.BOX,
                        )
                    ),
                    vol.Optional(
                        CONF_BALANCING_AGGRESSIVENESS,
                        default=self.config_entry.data.get(
                            CONF_BALANCING_AGGRESSIVENESS, DEFAULT_BALANCING_AGGRESSIVENESS
                        ),
                    ): selector.NumberSelector(
                        selector.NumberSelectorConfig(
                            min=0.0,
                            max=0.5,
                            step=0.05,
                            mode=selector.NumberSelectorMode.SLIDER,
                        )
                    ),
                    vol.Optional(
                        CONF_MIN_AIRFLOW_PERCENT,
                        default=self.config_entry.data.get(
                            CONF_MIN_AIRFLOW_PERCENT, DEFAULT_MIN_AIRFLOW_PERCENT
                        ),
                    ): selector.NumberSelector(
                        selector.NumberSelectorConfig(
                            min=5,
                            max=50,
                            step=5,
                            unit_of_measurement="%",
                            mode=selector.NumberSelectorMode.BOX,
                        )
                    ),
                }
            ),
            errors=errors if errors else None,
        )

    async def async_step_critical_rooms(
        self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        """Handle critical room protection configuration."""
        # Get list of all rooms
        all_rooms = self.config_entry.data.get(CONF_ROOM_CONFIGS, [])

        if not all_rooms:
            # No rooms configured yet
            return self.async_show_form(
                step_id="critical_rooms",
                data_schema=vol.Schema({}),
                description_placeholders={"error": "No rooms configured. Please add rooms first."},
            )

        if user_input is not None:
            # User selected a room to configure or went back
            if user_input.get("configure_room"):
                self._critical_room_to_configure = user_input["configure_room"]
                return await self.async_step_configure_critical_room()
            else:
                # User clicked done/back
                return self.async_create_entry(title="", data={})

        # Get existing critical room configs
        critical_rooms = self.config_entry.data.get(CONF_CRITICAL_ROOMS, {})

        # Create list of rooms with their current status
        room_options = []
        for room in all_rooms:
            room_name = room[CONF_ROOM_NAME]
            if room_name in critical_rooms:
                label = f"{room_name} (Critical Protection ENABLED)"
            else:
                label = f"{room_name} (Protection Disabled)"
            room_options.append({"label": label, "value": room_name})

        return self.async_show_form(
            step_id="critical_rooms",
            data_schema=vol.Schema(
                {
                    vol.Optional("configure_room"): selector.SelectSelector(
                        selector.SelectSelectorConfig(
                            options=room_options,
                            mode=selector.SelectSelectorMode.DROPDOWN,
                        )
                    ),
                }
            ),
            description_placeholders={
                "info": "Select a room to configure critical temperature protection, or press Submit to go back."
            },
        )

    async def async_step_configure_critical_room(
        self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        """Configure critical protection for a specific room."""
        room_name = getattr(self, '_critical_room_to_configure', None)

        if not room_name:
            return await self.async_step_critical_rooms()

        # Get existing critical room configs
        critical_rooms = dict(self.config_entry.data.get(CONF_CRITICAL_ROOMS, {}))
        existing_config = critical_rooms.get(room_name, {})

        if user_input is not None:
            # Check if user wants to disable protection
            if not user_input.get("enable_protection", False):
                # Remove this room from critical rooms
                if room_name in critical_rooms:
                    del critical_rooms[room_name]

                new_data = {**self.config_entry.data, CONF_CRITICAL_ROOMS: critical_rooms}
                self.hass.config_entries.async_update_entry(
                    self.config_entry, data=new_data
                )
                await self.hass.config_entries.async_reload(self.config_entry.entry_id)

                # Go back to critical rooms menu
                return await self.async_step_critical_rooms()

            # Parse notify services from comma-separated string
            notify_services_str = user_input.get(CONF_CRITICAL_NOTIFY_SERVICES, "")
            if notify_services_str:
                # Split by comma and strip whitespace
                notify_services = [s.strip() for s in notify_services_str.split(",") if s.strip()]
            else:
                notify_services = []

            # Validate temp_safe < temp_max, and min-side thresholds when given
            temp_max = user_input[CONF_CRITICAL_TEMP_MAX]
            temp_safe = user_input[CONF_CRITICAL_TEMP_SAFE]
            temp_min = user_input.get(CONF_CRITICAL_TEMP_MIN)
            temp_min_safe = user_input.get(CONF_CRITICAL_TEMP_MIN_SAFE)
            min_side_invalid = (
                temp_min is not None and (
                    temp_min >= temp_max
                    or (temp_min_safe is not None and temp_min_safe <= temp_min)
                )
            )
            if temp_safe >= temp_max or min_side_invalid:
                return self.async_show_form(
                    step_id="configure_critical_room",
                    data_schema=vol.Schema(
                        {
                            vol.Required("enable_protection", default=True): cv.boolean,
                            vol.Required(
                                CONF_CRITICAL_TEMP_MAX,
                                default=temp_max,
                            ): selector.NumberSelector(
                                selector.NumberSelectorConfig(
                                    min=20, max=40, step=0.5,
                                    unit_of_measurement="°C",
                                    mode=selector.NumberSelectorMode.BOX,
                                )
                            ),
                            vol.Required(
                                CONF_CRITICAL_TEMP_SAFE,
                                default=temp_safe,
                            ): selector.NumberSelector(
                                selector.NumberSelectorConfig(
                                    min=18, max=35, step=0.5,
                                    unit_of_measurement="°C",
                                    mode=selector.NumberSelectorMode.BOX,
                                )
                            ),
                            vol.Optional(
                                CONF_CRITICAL_WARNING_OFFSET,
                                default=user_input.get(CONF_CRITICAL_WARNING_OFFSET, DEFAULT_CRITICAL_WARNING_OFFSET),
                            ): selector.NumberSelector(
                                selector.NumberSelectorConfig(
                                    min=0.5, max=5.0, step=0.5,
                                    unit_of_measurement="°C",
                                    mode=selector.NumberSelectorMode.BOX,
                                )
                            ),
                            vol.Optional(
                                CONF_CRITICAL_TEMP_MIN,
                                **({"description": {"suggested_value": temp_min}} if temp_min is not None else {}),
                            ): selector.NumberSelector(
                                selector.NumberSelectorConfig(
                                    min=0, max=20, step=0.5,
                                    unit_of_measurement="°C",
                                    mode=selector.NumberSelectorMode.BOX,
                                )
                            ),
                            vol.Optional(
                                CONF_CRITICAL_TEMP_MIN_SAFE,
                                **({"description": {"suggested_value": temp_min_safe}} if temp_min_safe is not None else {}),
                            ): selector.NumberSelector(
                                selector.NumberSelectorConfig(
                                    min=2, max=25, step=0.5,
                                    unit_of_measurement="°C",
                                    mode=selector.NumberSelectorMode.BOX,
                                )
                            ),
                            vol.Optional(
                                CONF_CRITICAL_NOTIFY_SERVICES,
                                default=user_input.get(CONF_CRITICAL_NOTIFY_SERVICES, ""),
                            ): cv.string,
                        }
                    ),
                    description_placeholders={"room_name": room_name},
                    errors={"base": "critical_min_invalid" if min_side_invalid else "critical_safe_above_max"},
                )

            # Save the critical room configuration
            critical_rooms[room_name] = {
                CONF_CRITICAL_TEMP_MAX: temp_max,
                CONF_CRITICAL_TEMP_SAFE: temp_safe,
                CONF_CRITICAL_WARNING_OFFSET: user_input[CONF_CRITICAL_WARNING_OFFSET],
                CONF_CRITICAL_NOTIFY_SERVICES: notify_services,
            }
            # Optional freeze protection (under-temperature) bounds
            if temp_min is not None:
                critical_rooms[room_name][CONF_CRITICAL_TEMP_MIN] = temp_min
                if temp_min_safe is not None:
                    critical_rooms[room_name][CONF_CRITICAL_TEMP_MIN_SAFE] = temp_min_safe

            new_data = {**self.config_entry.data, CONF_CRITICAL_ROOMS: critical_rooms}
            self.hass.config_entries.async_update_entry(
                self.config_entry, data=new_data
            )
            await self.hass.config_entries.async_reload(self.config_entry.entry_id)

            # Go back to critical rooms menu
            return await self.async_step_critical_rooms()

        # Show configuration form
        is_enabled = room_name in critical_rooms

        return self.async_show_form(
            step_id="configure_critical_room",
            data_schema=vol.Schema(
                {
                    vol.Required("enable_protection", default=is_enabled): cv.boolean,
                    vol.Required(
                        CONF_CRITICAL_TEMP_MAX,
                        default=existing_config.get(CONF_CRITICAL_TEMP_MAX, 30),
                    ): selector.NumberSelector(
                        selector.NumberSelectorConfig(
                            min=20,
                            max=40,
                            step=0.5,
                            unit_of_measurement="°C",
                            mode=selector.NumberSelectorMode.BOX,
                        )
                    ),
                    vol.Required(
                        CONF_CRITICAL_TEMP_SAFE,
                        default=existing_config.get(CONF_CRITICAL_TEMP_SAFE, 24),
                    ): selector.NumberSelector(
                        selector.NumberSelectorConfig(
                            min=18,
                            max=35,
                            step=0.5,
                            unit_of_measurement="°C",
                            mode=selector.NumberSelectorMode.BOX,
                        )
                    ),
                    vol.Optional(
                        CONF_CRITICAL_WARNING_OFFSET,
                        default=existing_config.get(CONF_CRITICAL_WARNING_OFFSET, DEFAULT_CRITICAL_WARNING_OFFSET),
                    ): selector.NumberSelector(
                        selector.NumberSelectorConfig(
                            min=0.5,
                            max=5.0,
                            step=0.5,
                            unit_of_measurement="°C",
                            mode=selector.NumberSelectorMode.BOX,
                        )
                    ),
                    vol.Optional(
                        CONF_CRITICAL_TEMP_MIN,
                        **({"description": {"suggested_value": existing_config[CONF_CRITICAL_TEMP_MIN]}}
                           if CONF_CRITICAL_TEMP_MIN in existing_config else {}),
                    ): selector.NumberSelector(
                        selector.NumberSelectorConfig(
                            min=0,
                            max=20,
                            step=0.5,
                            unit_of_measurement="°C",
                            mode=selector.NumberSelectorMode.BOX,
                        )
                    ),
                    vol.Optional(
                        CONF_CRITICAL_TEMP_MIN_SAFE,
                        **({"description": {"suggested_value": existing_config[CONF_CRITICAL_TEMP_MIN_SAFE]}}
                           if CONF_CRITICAL_TEMP_MIN_SAFE in existing_config else {}),
                    ): selector.NumberSelector(
                        selector.NumberSelectorConfig(
                            min=2,
                            max=25,
                            step=0.5,
                            unit_of_measurement="°C",
                            mode=selector.NumberSelectorMode.BOX,
                        )
                    ),
                    vol.Optional(
                        CONF_CRITICAL_NOTIFY_SERVICES,
                        default=", ".join(existing_config.get(CONF_CRITICAL_NOTIFY_SERVICES, [])),
                    ): cv.string,
                }
            ),
            description_placeholders={
                "room_name": room_name,
            },
        )

    async def async_step_advanced(
        self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        """Handle advanced settings configuration."""
        errors = {}
        if user_input is not None:
            # Cross-validate tier ordering
            from .const import (
                CONF_OVERSHOOT_TIER1_THRESHOLD,
                CONF_OVERSHOOT_TIER2_THRESHOLD,
                CONF_OVERSHOOT_TIER3_THRESHOLD,
                CONF_MAIN_FAN_HIGH_THRESHOLD,
                CONF_MAIN_FAN_MEDIUM_THRESHOLD,
            )
            t1 = user_input.get(CONF_OVERSHOOT_TIER1_THRESHOLD)
            t2 = user_input.get(CONF_OVERSHOOT_TIER2_THRESHOLD)
            t3 = user_input.get(CONF_OVERSHOOT_TIER3_THRESHOLD)
            if t1 is not None and t2 is not None and t3 is not None:
                if not (t1 < t2 < t3):
                    errors["base"] = "invalid_tier_ordering"
            fan_med = user_input.get(CONF_MAIN_FAN_MEDIUM_THRESHOLD)
            fan_high = user_input.get(CONF_MAIN_FAN_HIGH_THRESHOLD)
            if fan_med is not None and fan_high is not None:
                if fan_med >= fan_high:
                    errors["base"] = "invalid_fan_threshold_ordering"

            if not errors:
                # Convert the CSV notify-services field into the stored list
                user_input = dict(user_input)
                notify_csv = user_input.pop("notify_services_csv", None)
                if notify_csv is not None:
                    user_input[CONF_NOTIFY_SERVICES] = [
                        s.strip() for s in notify_csv.split(",") if s.strip()
                    ]

                # Merge with existing data and update the config entry
                new_data = {**self.config_entry.data, **user_input}
                self.hass.config_entries.async_update_entry(
                    self.config_entry, data=new_data
                )
                # Reload the integration to apply changes
                await self.hass.config_entries.async_reload(self.config_entry.entry_id)
                return self.async_create_entry(title="", data={})

        from .const import (
            CONF_MAIN_FAN_HIGH_THRESHOLD,
            CONF_MAIN_FAN_MEDIUM_THRESHOLD,
            CONF_WEATHER_INFLUENCE_FACTOR,
            CONF_OVERSHOOT_TIER1_THRESHOLD,
            CONF_OVERSHOOT_TIER2_THRESHOLD,
            CONF_OVERSHOOT_TIER3_THRESHOLD,
            CONF_ENABLE_ADAPTIVE_DEADBAND,
            CONF_ADAPTIVE_DEADBAND_MAX_SCALE,
            CONF_ADAPTIVE_DEADBAND_RATE_THRESHOLD,
            DEFAULT_MAIN_FAN_HIGH_THRESHOLD,
            DEFAULT_MAIN_FAN_MEDIUM_THRESHOLD,
            DEFAULT_WEATHER_INFLUENCE_FACTOR,
            DEFAULT_OVERSHOOT_TIER1_THRESHOLD,
            DEFAULT_OVERSHOOT_TIER2_THRESHOLD,
            DEFAULT_OVERSHOOT_TIER3_THRESHOLD,
            DEFAULT_ENABLE_ADAPTIVE_DEADBAND,
            DEFAULT_ADAPTIVE_DEADBAND_MAX_SCALE,
            DEFAULT_ADAPTIVE_DEADBAND_RATE_THRESHOLD,
        )

        return self.async_show_form(
            step_id="advanced",
            data_schema=vol.Schema(
                {
                    vol.Optional(
                        CONF_MAIN_FAN_HIGH_THRESHOLD,
                        default=self.config_entry.data.get(
                            CONF_MAIN_FAN_HIGH_THRESHOLD, DEFAULT_MAIN_FAN_HIGH_THRESHOLD
                        ),
                    ): selector.NumberSelector(
                        selector.NumberSelectorConfig(
                            min=0.5,
                            max=5.0,
                            step=0.5,
                            unit_of_measurement="°C",
                            mode=selector.NumberSelectorMode.BOX,
                        )
                    ),
                    vol.Optional(
                        CONF_MAIN_FAN_MEDIUM_THRESHOLD,
                        default=self.config_entry.data.get(
                            CONF_MAIN_FAN_MEDIUM_THRESHOLD, DEFAULT_MAIN_FAN_MEDIUM_THRESHOLD
                        ),
                    ): selector.NumberSelector(
                        selector.NumberSelectorConfig(
                            min=0.5,
                            max=3.0,
                            step=0.5,
                            unit_of_measurement="°C",
                            mode=selector.NumberSelectorMode.BOX,
                        )
                    ),
                    vol.Optional(
                        CONF_WEATHER_INFLUENCE_FACTOR,
                        default=self.config_entry.data.get(
                            CONF_WEATHER_INFLUENCE_FACTOR, DEFAULT_WEATHER_INFLUENCE_FACTOR
                        ),
                    ): selector.NumberSelector(
                        selector.NumberSelectorConfig(
                            min=0.0,
                            max=1.0,
                            step=0.1,
                            mode=selector.NumberSelectorMode.SLIDER,
                        )
                    ),
                    vol.Optional(
                        CONF_OVERSHOOT_TIER1_THRESHOLD,
                        default=self.config_entry.data.get(
                            CONF_OVERSHOOT_TIER1_THRESHOLD, DEFAULT_OVERSHOOT_TIER1_THRESHOLD
                        ),
                    ): selector.NumberSelector(
                        selector.NumberSelectorConfig(
                            min=0.5,
                            max=2.0,
                            step=0.5,
                            unit_of_measurement="°C",
                            mode=selector.NumberSelectorMode.BOX,
                        )
                    ),
                    vol.Optional(
                        CONF_OVERSHOOT_TIER2_THRESHOLD,
                        default=self.config_entry.data.get(
                            CONF_OVERSHOOT_TIER2_THRESHOLD, DEFAULT_OVERSHOOT_TIER2_THRESHOLD
                        ),
                    ): selector.NumberSelector(
                        selector.NumberSelectorConfig(
                            min=1.0,
                            max=3.0,
                            step=0.5,
                            unit_of_measurement="°C",
                            mode=selector.NumberSelectorMode.BOX,
                        )
                    ),
                    vol.Optional(
                        CONF_OVERSHOOT_TIER3_THRESHOLD,
                        default=self.config_entry.data.get(
                            CONF_OVERSHOOT_TIER3_THRESHOLD, DEFAULT_OVERSHOOT_TIER3_THRESHOLD
                        ),
                    ): selector.NumberSelector(
                        selector.NumberSelectorConfig(
                            min=2.0,
                            max=5.0,
                            step=0.5,
                            unit_of_measurement="°C",
                            mode=selector.NumberSelectorMode.BOX,
                        )
                    ),
                    vol.Optional(
                        CONF_ENABLE_ADAPTIVE_DEADBAND,
                        default=self.config_entry.data.get(
                            CONF_ENABLE_ADAPTIVE_DEADBAND, DEFAULT_ENABLE_ADAPTIVE_DEADBAND
                        ),
                    ): selector.BooleanSelector(),
                    vol.Optional(
                        CONF_ADAPTIVE_DEADBAND_MAX_SCALE,
                        default=self.config_entry.data.get(
                            CONF_ADAPTIVE_DEADBAND_MAX_SCALE, DEFAULT_ADAPTIVE_DEADBAND_MAX_SCALE
                        ),
                    ): selector.NumberSelector(
                        selector.NumberSelectorConfig(
                            min=1.0,
                            max=5.0,
                            step=0.1,
                            mode=selector.NumberSelectorMode.BOX,
                        )
                    ),
                    vol.Optional(
                        CONF_ADAPTIVE_DEADBAND_RATE_THRESHOLD,
                        default=self.config_entry.data.get(
                            CONF_ADAPTIVE_DEADBAND_RATE_THRESHOLD,
                            DEFAULT_ADAPTIVE_DEADBAND_RATE_THRESHOLD,
                        ),
                    ): selector.NumberSelector(
                        selector.NumberSelectorConfig(
                            min=0.1,
                            max=5.0,
                            step=0.1,
                            unit_of_measurement="°C/min",
                            mode=selector.NumberSelectorMode.BOX,
                        )
                    ),
                    vol.Optional(
                        CONF_ENABLE_FAN_SMOOTHING,
                        default=self.config_entry.data.get(
                            CONF_ENABLE_FAN_SMOOTHING, DEFAULT_ENABLE_FAN_SMOOTHING
                        ),
                    ): selector.BooleanSelector(),
                    vol.Optional(
                        CONF_SMOOTHING_FACTOR,
                        default=self.config_entry.data.get(
                            CONF_SMOOTHING_FACTOR, DEFAULT_SMOOTHING_FACTOR
                        ),
                    ): selector.NumberSelector(
                        selector.NumberSelectorConfig(
                            min=0.1,
                            max=1.0,
                            step=0.05,
                            mode=selector.NumberSelectorMode.BOX,
                        )
                    ),
                    vol.Optional(
                        CONF_SMOOTHING_THRESHOLD,
                        default=self.config_entry.data.get(
                            CONF_SMOOTHING_THRESHOLD, DEFAULT_SMOOTHING_THRESHOLD
                        ),
                    ): selector.NumberSelector(
                        selector.NumberSelectorConfig(
                            min=1,
                            max=30,
                            step=1,
                            unit_of_measurement="%",
                            mode=selector.NumberSelectorMode.BOX,
                        )
                    ),
                    vol.Optional(
                        "notify_services_csv",
                        default=", ".join(self.config_entry.data.get(CONF_NOTIFY_SERVICES, []) or []),
                    ): cv.string,
                }
            ),
        )
