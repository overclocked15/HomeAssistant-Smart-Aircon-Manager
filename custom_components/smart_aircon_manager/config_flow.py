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
        errors = {}

        # Check temperature sensor
        temp_state = self.hass.states.get(temp_sensor)
        if not temp_state:
            errors["temperature_sensor"] = "entity_not_found"
        elif temp_state.state in ["unavailable", "unknown"]:
            errors["temperature_sensor"] = "entity_unavailable"
        else:
            # Validate temperature sensor has numeric value
            try:
                temp_value = float(temp_state.state)
                # Sanity check: realistic temperature range
                if not (-50.0 <= temp_value <= 70.0):
                    _LOGGER.warning(
                        "Temperature sensor %s has unrealistic value: %.1f°C",
                        temp_sensor, temp_value
                    )
                    errors["temperature_sensor"] = "unrealistic_temperature"
            except (ValueError, TypeError):
                _LOGGER.error("Temperature sensor %s has non-numeric state: %s", temp_sensor, temp_state.state)
                errors["temperature_sensor"] = "non_numeric_temperature"

            # Check for temperature sensor domain
            if not temp_state.entity_id.startswith("sensor."):
                _LOGGER.warning("Temperature entity %s is not a sensor domain", temp_sensor)
                errors["temperature_sensor"] = "invalid_domain"

        # Check cover entity
        cover_state = self.hass.states.get(cover_entity)
        if not cover_state:
            errors["cover_entity"] = "entity_not_found"
        elif cover_state.state in ["unavailable", "unknown"]:
            errors["cover_entity"] = "entity_unavailable"
        else:
            # Validate cover has position attribute
            if "current_position" not in cover_state.attributes:
                _LOGGER.warning("Cover entity %s missing current_position attribute", cover_entity)
                errors["cover_entity"] = "missing_position_attribute"
            else:
                # Validate position is numeric and in range
                try:
                    position = int(cover_state.attributes["current_position"])
                    if not (0 <= position <= 100):
                        _LOGGER.warning("Cover %s position %d outside valid range (0-100)", cover_entity, position)
                        errors["cover_entity"] = "invalid_position_range"
                except (ValueError, TypeError):
                    _LOGGER.error("Cover %s has non-numeric position", cover_entity)
                    errors["cover_entity"] = "non_numeric_position"

            # Check for cover domain
            if not cover_state.entity_id.startswith("cover."):
                _LOGGER.warning("Cover entity %s is not a cover domain", cover_entity)
                errors["cover_entity"] = "invalid_domain"

        return errors if errors else None

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
                self._rooms.append(
                    {
                        CONF_ROOM_NAME: user_input[CONF_ROOM_NAME],
                        CONF_TEMPERATURE_SENSOR: user_input[CONF_TEMPERATURE_SENSOR],
                        CONF_COVER_ENTITY: user_input[CONF_COVER_ENTITY],
                    }
                )

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
                        title="AI Aircon Manager", data=self._data
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
            menu_options=["settings", "manage_rooms", "room_overrides", "weather", "schedules", "advanced"],
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
                            min=1, max=60, step=1, mode=selector.NumberSelectorMode.BOX, unit_of_measurement="minutes"
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
        errors = {}

        # Check temperature sensor
        temp_state = self.hass.states.get(temp_sensor)
        if not temp_state:
            errors["temperature_sensor"] = "entity_not_found"
        elif temp_state.state in ["unavailable", "unknown"]:
            errors["temperature_sensor"] = "entity_unavailable"

        # Check cover entity
        cover_state = self.hass.states.get(cover_entity)
        if not cover_state:
            errors["cover_entity"] = "entity_not_found"
        elif cover_state.state in ["unavailable", "unknown"]:
            errors["cover_entity"] = "entity_unavailable"

        return errors if errors else None

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
