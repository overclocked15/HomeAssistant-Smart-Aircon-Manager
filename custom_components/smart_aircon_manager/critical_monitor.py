"""Critical Room Temperature Monitoring for Smart Aircon Manager."""
from __future__ import annotations

import logging
from datetime import datetime, timedelta
from typing import Any

from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.event import async_track_time_interval
from homeassistant.const import STATE_UNAVAILABLE, STATE_UNKNOWN
from homeassistant.components.climate.const import HVACMode

from .const import (
    CONF_CRITICAL_ROOMS,
    CONF_CRITICAL_TEMP_MAX,
    CONF_CRITICAL_TEMP_SAFE,
    CONF_CRITICAL_WARNING_OFFSET,
    CONF_CRITICAL_NOTIFY_SERVICES,
    CRITICAL_STATUS_NORMAL,
    CRITICAL_STATUS_WARNING,
    CRITICAL_STATUS_CRITICAL,
    CRITICAL_STATUS_RECOVERING,
)

_LOGGER = logging.getLogger(__name__)


class CriticalRoomMonitor:
    """Monitor critical rooms and automatically trigger AC when needed."""

    def __init__(
        self,
        hass: HomeAssistant,
        config_data: dict[str, Any],
        room_configs: list[dict[str, Any]],
        main_climate_entity: str | None,
    ) -> None:
        """Initialize the critical room monitor."""
        self.hass = hass
        self._config_data = config_data
        self._room_configs = room_configs
        self._main_climate_entity = main_climate_entity

        # Track critical room states
        self._room_states = {}  # room_name -> {status, last_notification, temperature}

        # Track when we last triggered AC
        self._last_ac_trigger = None
        self._ac_trigger_cooldown = timedelta(minutes=5)  # Prevent rapid on/off cycling

        # Monitoring interval (fast polling for critical rooms)
        self._monitor_interval = timedelta(seconds=30)
        self._remove_timer = None

    async def async_start(self) -> None:
        """Start monitoring critical rooms."""
        critical_rooms = self._config_data.get(CONF_CRITICAL_ROOMS, {})

        if not critical_rooms:
            _LOGGER.debug("No critical rooms configured, monitor inactive")
            return

        # Initialize room states
        for room_name in critical_rooms:
            self._room_states[room_name] = {
                "status": CRITICAL_STATUS_NORMAL,
                "last_notification": None,
                "temperature": None,
                "last_check": None,
            }

        # Start monitoring timer
        self._remove_timer = async_track_time_interval(
            self.hass,
            self._async_monitor_critical_rooms,
            self._monitor_interval,
        )

        _LOGGER.info(
            "Critical room monitor started for %d room(s): %s",
            len(critical_rooms),
            ", ".join(critical_rooms.keys()),
        )

    async def async_stop(self) -> None:
        """Stop monitoring."""
        if self._remove_timer:
            self._remove_timer()
            self._remove_timer = None
        _LOGGER.debug("Critical room monitor stopped")

    @callback
    async def _async_monitor_critical_rooms(self, now=None) -> None:
        """Monitor critical rooms and take action if needed."""
        critical_rooms = self._config_data.get(CONF_CRITICAL_ROOMS, {})

        for room_name, critical_config in critical_rooms.items():
            # Find the room config
            room_config = next(
                (r for r in self._room_configs if r["room_name"] == room_name),
                None
            )

            if not room_config:
                continue

            # Get current temperature
            temp_sensor = room_config["temperature_sensor"]
            temp_state = self.hass.states.get(temp_sensor)

            if not temp_state or temp_state.state in [STATE_UNAVAILABLE, STATE_UNKNOWN]:
                _LOGGER.warning(
                    "Temperature sensor %s for critical room %s is unavailable",
                    temp_sensor,
                    room_name,
                )
                continue

            try:
                current_temp = float(temp_state.state)
            except (ValueError, TypeError):
                _LOGGER.warning(
                    "Invalid temperature value %s for critical room %s",
                    temp_state.state,
                    room_name,
                )
                continue

            # Get critical thresholds
            critical_temp_max = critical_config[CONF_CRITICAL_TEMP_MAX]
            critical_temp_safe = critical_config[CONF_CRITICAL_TEMP_SAFE]
            warning_offset = critical_config[CONF_CRITICAL_WARNING_OFFSET]

            # Calculate warning threshold
            warning_temp = critical_temp_max - warning_offset

            # Update room state
            room_state = self._room_states.get(room_name, {})
            old_status = room_state.get("status", CRITICAL_STATUS_NORMAL)
            room_state["temperature"] = current_temp
            room_state["last_check"] = datetime.now()

            # Determine current status
            new_status = self._determine_status(
                current_temp, critical_temp_max, warning_temp, critical_temp_safe, old_status
            )

            # Update status
            room_state["status"] = new_status
            self._room_states[room_name] = room_state

            # Handle status changes
            if new_status != old_status:
                await self._handle_status_change(
                    room_name, old_status, new_status, current_temp, critical_config
                )

            # If critical and AC is off, turn it on
            if new_status == CRITICAL_STATUS_CRITICAL:
                await self._ensure_ac_running(room_name, current_temp, critical_config)

    def _determine_status(
        self,
        current_temp: float,
        critical_temp: float,
        warning_temp: float,
        safe_temp: float,
        old_status: str,
    ) -> str:
        """Determine the current status based on temperature."""
        if current_temp >= critical_temp:
            return CRITICAL_STATUS_CRITICAL
        elif current_temp >= warning_temp:
            # Only transition to warning if not already in critical/recovering
            if old_status in [CRITICAL_STATUS_CRITICAL, CRITICAL_STATUS_RECOVERING]:
                # We're recovering from critical
                if current_temp <= safe_temp:
                    return CRITICAL_STATUS_NORMAL
                else:
                    return CRITICAL_STATUS_RECOVERING
            else:
                return CRITICAL_STATUS_WARNING
        elif old_status in [CRITICAL_STATUS_CRITICAL, CRITICAL_STATUS_RECOVERING]:
            # Recovering from critical state
            if current_temp <= safe_temp:
                return CRITICAL_STATUS_NORMAL
            else:
                return CRITICAL_STATUS_RECOVERING
        else:
            return CRITICAL_STATUS_NORMAL

    async def _handle_status_change(
        self,
        room_name: str,
        old_status: str,
        new_status: str,
        current_temp: float,
        critical_config: dict[str, Any],
    ) -> None:
        """Handle status transition and send notifications."""
        critical_temp_max = critical_config[CONF_CRITICAL_TEMP_MAX]
        notify_services = critical_config.get(CONF_CRITICAL_NOTIFY_SERVICES, [])

        _LOGGER.info(
            "Critical room %s status changed: %s -> %s (temp: %.1f°C)",
            room_name,
            old_status,
            new_status,
            current_temp,
        )

        # Send notifications
        if not notify_services:
            return

        # Prepare notification message
        message = None
        title = None

        if new_status == CRITICAL_STATUS_WARNING:
            title = f"⚠️ Warning: {room_name} Temperature Rising"
            margin = critical_temp_max - current_temp
            message = (
                f"{room_name} temperature is {current_temp:.1f}°C, "
                f"approaching critical threshold of {critical_temp_max}°C "
                f"(margin: {margin:.1f}°C). Monitoring closely."
            )
        elif new_status == CRITICAL_STATUS_CRITICAL:
            title = f"🚨 CRITICAL: {room_name} Over Temperature!"
            message = (
                f"{room_name} has reached critical temperature: {current_temp:.1f}°C "
                f"(threshold: {critical_temp_max}°C). AC is being turned on automatically!"
            )
        elif new_status == CRITICAL_STATUS_NORMAL and old_status in [
            CRITICAL_STATUS_CRITICAL,
            CRITICAL_STATUS_RECOVERING,
            CRITICAL_STATUS_WARNING,
        ]:
            title = f"✅ {room_name} Temperature Normalized"
            message = (
                f"{room_name} has returned to safe temperature: {current_temp:.1f}°C. "
                f"Protection monitoring continues."
            )

        if message and title:
            await self._send_notifications(notify_services, title, message)
            self._room_states[room_name]["last_notification"] = datetime.now()

    async def _send_notifications(
        self, notify_services: list[str], title: str, message: str
    ) -> None:
        """Send notification to configured services."""
        for service in notify_services:
            try:
                # Extract service name (remove "notify." prefix if present)
                service_name = service.replace("notify.", "")

                # Combine title and message for better compatibility
                # Some services (like ClickSend, Twilio) don't support separate title
                full_message = f"{title}\n\n{message}"

                # Try to send with both title and message first (for services that support it)
                # If that fails, send with message only
                try:
                    await self.hass.services.async_call(
                        "notify",
                        service_name,
                        {
                            "title": title,
                            "message": message,
                        },
                    )
                    _LOGGER.debug("Sent notification via %s (with title)", service)
                except Exception as title_error:
                    # Fallback: send as single message without title parameter
                    _LOGGER.debug("Title parameter not supported for %s, sending as single message", service)
                    await self.hass.services.async_call(
                        "notify",
                        service_name,
                        {
                            "message": full_message,
                        },
                    )
                    _LOGGER.debug("Sent notification via %s (message only)", service)

            except Exception as e:
                _LOGGER.error("Failed to send notification via %s: %s", service, e)

    async def _ensure_ac_running(
        self, room_name: str, current_temp: float, critical_config: dict[str, Any]
    ) -> None:
        """Ensure AC is running when critical temperature is reached."""
        if not self._main_climate_entity:
            _LOGGER.warning(
                "Critical room %s at %.1f°C but no main climate entity configured to control AC",
                room_name,
                current_temp,
            )
            return

        # Check cooldown to prevent rapid on/off cycling
        if self._last_ac_trigger:
            time_since_trigger = datetime.now() - self._last_ac_trigger
            if time_since_trigger < self._ac_trigger_cooldown:
                _LOGGER.debug(
                    "AC trigger on cooldown (%.1f seconds remaining)",
                    (self._ac_trigger_cooldown - time_since_trigger).total_seconds(),
                )
                return

        # Check if AC is already running
        climate_state = self.hass.states.get(self._main_climate_entity)

        if not climate_state:
            _LOGGER.error("Main climate entity %s not found", self._main_climate_entity)
            return

        current_hvac_mode = climate_state.state

        # If AC is off, turn it on
        if current_hvac_mode in ["off", STATE_UNAVAILABLE, STATE_UNKNOWN]:
            _LOGGER.warning(
                "🚨 CRITICAL: Turning on AC for %s (temp: %.1f°C, threshold: %.1f°C)",
                room_name,
                current_temp,
                critical_config[CONF_CRITICAL_TEMP_MAX],
            )

            try:
                # Turn on AC in cooling mode
                await self.hass.services.async_call(
                    "climate",
                    "set_hvac_mode",
                    {
                        "entity_id": self._main_climate_entity,
                        "hvac_mode": HVACMode.COOL,
                    },
                )

                self._last_ac_trigger = datetime.now()
                _LOGGER.info("AC turned on successfully for critical room %s", room_name)

            except Exception as e:
                _LOGGER.error("Failed to turn on AC: %s", e)
        else:
            _LOGGER.debug(
                "AC is already running (mode: %s), relying on normal optimization to cool %s",
                current_hvac_mode,
                room_name,
            )

    def get_room_status(self, room_name: str) -> dict[str, Any] | None:
        """Get the current status of a critical room."""
        return self._room_states.get(room_name)

    def get_all_statuses(self) -> dict[str, dict[str, Any]]:
        """Get statuses of all critical rooms."""
        return self._room_states.copy()

    def is_room_critical(self, room_name: str) -> bool:
        """Check if a room is currently in critical status."""
        room_state = self._room_states.get(room_name)
        if room_state:
            return room_state["status"] == CRITICAL_STATUS_CRITICAL
        return False

    def get_temperature_margin(self, room_name: str) -> float | None:
        """Get the temperature margin before critical threshold."""
        critical_rooms = self._config_data.get(CONF_CRITICAL_ROOMS, {})

        if room_name not in critical_rooms:
            return None

        room_state = self._room_states.get(room_name)
        if not room_state or room_state["temperature"] is None:
            return None

        critical_temp = critical_rooms[room_name][CONF_CRITICAL_TEMP_MAX]
        current_temp = room_state["temperature"]

        return critical_temp - current_temp
