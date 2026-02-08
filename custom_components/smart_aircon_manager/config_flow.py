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
    CONF_CRITICAL_WARNING_OFFSET,
    CONF_CRITICAL_NOTIFY_SERVICES,
    DEFAULT_CRITICAL_WARNING_OFFSET,
)

_LOGGER = logging.getLogger(__name__)

STEP_USER_DATA_SCHEMA = vol.Schema(
    {
        vol.Optional(CONF_TARGET_TEMPERATURE, default=DEFAULT_TARGET_TEMPERATURE): cv.positive_int,
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

    VERSION = 1

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
            # Validate entities
            validation_errors = self._validate_entities(
                user_input[CONF_TEMPERATURE_SENSOR],
                user_input[CONF_COVER_ENTITY]
            )

            if validation_errors:
                errors = validation_errors
            else:
                # Add the current room to the list
                new_room = {
                    CONF_ROOM_NAME: user_input[CONF_ROOM_NAME],
                    CONF_TEMPERATURE_SENSOR: user_input[CONF_TEMPERATURE_SENSOR],
                    CONF_COVER_ENTITY: user_input[CONF_COVER_ENTITY],
                }

                # Add humidity sensor if provided
                if user_input.get(CONF_HUMIDITY_SENSOR):
                    new_room[CONF_HUMIDITY_SENSOR] = user_input[CONF_HUMIDITY_SENSOR]

                self._rooms.append(new_room)

                # Check if user wants to add another room
                if user_input.get("add_another"):
                    return await self.async_step_add_room()
                else:
                    # Done adding rooms
                    if len(self._rooms) == 0:
                        return self.async_show_form(
                            step_id="add_room",
                            data_schema=self._get_room_schema(),
                            description_placeholders={
                                "rooms_added": str(len(self._rooms)),
                            },
                            errors={"base": "no_rooms"},
                        )

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

    # Check temperature sensor
    temp_state = hass.states.get(temp_sensor)
    if not temp_state:
        errors["temperature_sensor"] = "entity_not_found"
    elif temp_state.state in ["unavailable", "unknown"]:
        errors["temperature_sensor"] = "entity_unavailable"
    else:
        try:
            temp_value = float(temp_state.state)
            if not (-50.0 <= temp_value <= 70.0):
                _LOGGER.warning(
                    "Temperature sensor %s has unrealistic value: %.1f°C",
                    temp_sensor, temp_value
                )
                errors["temperature_sensor"] = "unrealistic_temperature"
        except (ValueError, TypeError):
            _LOGGER.error("Temperature sensor %s has non-numeric state: %s", temp_sensor, temp_state.state)
            errors["temperature_sensor"] = "non_numeric_temperature"

        if not temp_state.entity_id.startswith("sensor."):
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

        if not cover_state.entity_id.startswith("cover."):
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
            menu_options=["settings", "manage_rooms", "room_overrides", "weather", "humidity", "schedules", "learning", "balancing", "critical_rooms", "advanced"],
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
                    ): cv.positive_int,
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
                        default=self.config_entry.data.get(CONF_MAIN_CLIMATE_ENTITY),
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
                        default=self.config_entry.data.get(CONF_MAIN_FAN_ENTITY),
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
            # Validate entities
            validation_errors = self._validate_entities(
                user_input[CONF_TEMPERATURE_SENSOR],
                user_input[CONF_COVER_ENTITY]
            )

            if validation_errors:
                errors = validation_errors
            else:
                # Add the room
                new_room = {
                    CONF_ROOM_NAME: user_input[CONF_ROOM_NAME],
                    CONF_TEMPERATURE_SENSOR: user_input[CONF_TEMPERATURE_SENSOR],
                    CONF_COVER_ENTITY: user_input[CONF_COVER_ENTITY],
                }

                # Add humidity sensor if provided
                if user_input.get(CONF_HUMIDITY_SENSOR):
                    new_room[CONF_HUMIDITY_SENSOR] = user_input[CONF_HUMIDITY_SENSOR]

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

            # Update the config entry
            new_data = {**self.config_entry.data, CONF_ROOM_CONFIGS: updated_rooms}
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
            # Validate entities
            validation_errors = self._validate_entities(
                user_input[CONF_TEMPERATURE_SENSOR],
                user_input[CONF_COVER_ENTITY]
            )

            if validation_errors:
                errors = validation_errors
            else:
                # Update the room
                updated_room = {
                    CONF_ROOM_NAME: user_input[CONF_ROOM_NAME],
                    CONF_TEMPERATURE_SENSOR: user_input[CONF_TEMPERATURE_SENSOR],
                    CONF_COVER_ENTITY: user_input[CONF_COVER_ENTITY],
                }

                # Include humidity sensor if provided
                if user_input.get(CONF_HUMIDITY_SENSOR):
                    updated_room[CONF_HUMIDITY_SENSOR] = user_input[CONF_HUMIDITY_SENSOR]

                # Replace the old room with updated one
                updated_rooms = [
                    updated_room if room[CONF_ROOM_NAME] == room_to_edit_name else room
                    for room in current_rooms
                ]

                # Update the config entry
                new_data = {**self.config_entry.data, CONF_ROOM_CONFIGS: updated_rooms}
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

        # Add humidity sensor with default if it exists
        if humidity_sensor:
            schema_dict[vol.Optional(CONF_HUMIDITY_SENSOR, default=humidity_sensor)] = selector.EntitySelector(
                selector.EntitySelectorConfig(domain="sensor", device_class="humidity")
            )
        else:
            schema_dict[vol.Optional(CONF_HUMIDITY_SENSOR)] = selector.EntitySelector(
                selector.EntitySelectorConfig(domain="sensor", device_class="humidity")
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

        # Only set default if weather entity exists
        weather_entity = self.config_entry.data.get(CONF_WEATHER_ENTITY)
        if weather_entity:
            schema_dict[vol.Optional(CONF_WEATHER_ENTITY, default=weather_entity)] = selector.EntitySelector(
                selector.EntitySelectorConfig(domain="weather")
            )
        else:
            schema_dict[vol.Optional(CONF_WEATHER_ENTITY)] = selector.EntitySelector(
                selector.EntitySelectorConfig(domain="weather")
            )

        # Only set default if outdoor temp sensor exists
        outdoor_sensor = self.config_entry.data.get(CONF_OUTDOOR_TEMP_SENSOR)
        if outdoor_sensor:
            schema_dict[vol.Optional(CONF_OUTDOOR_TEMP_SENSOR, default=outdoor_sensor)] = selector.EntitySelector(
                selector.EntitySelectorConfig(domain="sensor", device_class="temperature")
            )
        else:
            schema_dict[vol.Optional(CONF_OUTDOOR_TEMP_SENSOR)] = selector.EntitySelector(
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
        if user_input is not None:
            # Get existing schedules
            current_schedules = list(self.config_entry.data.get(CONF_SCHEDULES, []))
            # Add new schedule
            new_schedule = {
                CONF_SCHEDULE_NAME: user_input[CONF_SCHEDULE_NAME],
                CONF_SCHEDULE_DAYS: user_input[CONF_SCHEDULE_DAYS],
                CONF_SCHEDULE_START_TIME: user_input[CONF_SCHEDULE_START_TIME],
                CONF_SCHEDULE_END_TIME: user_input[CONF_SCHEDULE_END_TIME],
                CONF_SCHEDULE_TARGET_TEMP: user_input[CONF_SCHEDULE_TARGET_TEMP],
                CONF_SCHEDULE_ENABLED: user_input.get(CONF_SCHEDULE_ENABLED, True),
            }
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
                }
            ),
        )

    async def async_step_edit_schedule(
        self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        """Edit an existing schedule."""
        current_schedules = self.config_entry.data.get(CONF_SCHEDULES, [])

        if not current_schedules:
            return self.async_show_form(
                step_id="edit_schedule",
                data_schema=vol.Schema({}),
                description_placeholders={
                    "message": "No schedules configured. Add a schedule first."
                },
            )

        # For simplicity, show a message that editing is done via delete+add
        return self.async_show_form(
            step_id="edit_schedule",
            data_schema=vol.Schema({}),
            description_placeholders={
                "message": f"You have {len(current_schedules)} schedule(s). To edit, delete the old one and add a new one."
            },
        )

    async def async_step_delete_schedule(
        self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        """Delete a schedule."""
        current_schedules = list(self.config_entry.data.get(CONF_SCHEDULES, []))

        if not current_schedules:
            return self.async_show_form(
                step_id="delete_schedule",
                data_schema=vol.Schema({}),
                description_placeholders={
                    "message": "No schedules to delete."
                },
            )

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

            # Save the critical room configuration
            critical_rooms[room_name] = {
                CONF_CRITICAL_TEMP_MAX: user_input[CONF_CRITICAL_TEMP_MAX],
                CONF_CRITICAL_TEMP_SAFE: user_input[CONF_CRITICAL_TEMP_SAFE],
                CONF_CRITICAL_WARNING_OFFSET: user_input[CONF_CRITICAL_WARNING_OFFSET],
                CONF_CRITICAL_NOTIFY_SERVICES: notify_services,
            }

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
                    vol.Optional(
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
                    vol.Optional(
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
        if user_input is not None:
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
            DEFAULT_MAIN_FAN_HIGH_THRESHOLD,
            DEFAULT_MAIN_FAN_MEDIUM_THRESHOLD,
            DEFAULT_WEATHER_INFLUENCE_FACTOR,
            DEFAULT_OVERSHOOT_TIER1_THRESHOLD,
            DEFAULT_OVERSHOOT_TIER2_THRESHOLD,
            DEFAULT_OVERSHOOT_TIER3_THRESHOLD,
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
                }
            ),
        )
