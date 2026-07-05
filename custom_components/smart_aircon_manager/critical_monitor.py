"""Critical Room Temperature Monitoring for Smart Aircon Manager."""
from __future__ import annotations

import logging
from datetime import timedelta

from homeassistant.util import dt as dt_util
from typing import Any

from homeassistant.core import HomeAssistant
from homeassistant.helpers.event import async_track_time_interval
from homeassistant.const import STATE_UNAVAILABLE, STATE_UNKNOWN
from homeassistant.components.climate.const import HVACMode

from .const import (
    CONF_CRITICAL_ROOMS,
    CONF_CRITICAL_TEMP_MAX,
    CONF_CRITICAL_TEMP_SAFE,
    CONF_CRITICAL_TEMP_MIN,
    CONF_CRITICAL_TEMP_MIN_SAFE,
    CONF_CRITICAL_WARNING_OFFSET,
    CONF_CRITICAL_NOTIFY_SERVICES,
    DEFAULT_CRITICAL_WARNING_OFFSET,
    CRITICAL_STATUS_NORMAL,
    CRITICAL_STATUS_WARNING,
    CRITICAL_STATUS_CRITICAL,
    CRITICAL_STATUS_RECOVERING,
)
from .temperature_utils import normalize_temperature

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

            # Get current temperature (normalized to Celsius)
            temp_sensor = room_config["temperature_sensor"]
            temp_state = self.hass.states.get(temp_sensor)
            current_temp = normalize_temperature(temp_state, f"critical room {room_name}")

            if current_temp is None:
                _LOGGER.warning(
                    "Temperature sensor %s for critical room %s is unavailable or invalid",
                    temp_sensor,
                    room_name,
                )
                continue

            # Update room state
            room_state = self._room_states.get(room_name, {})
            old_status = room_state.get("status", CRITICAL_STATUS_NORMAL)
            old_direction = room_state.get("direction", "hot")
            room_state["temperature"] = current_temp
            room_state["last_check"] = dt_util.now()

            # Determine current status (checks over-temp and, if configured,
            # under-temp/freeze bounds)
            new_status, direction = self._determine_status(
                current_temp, critical_config, old_status, old_direction
            )

            # Update status
            room_state["status"] = new_status
            room_state["direction"] = direction
            self._room_states[room_name] = room_state

            # Handle status changes
            if new_status != old_status:
                await self._handle_status_change(
                    room_name, old_status, new_status, current_temp, critical_config, direction
                )

            # If critical and AC is off, turn it on in the correct mode
            if new_status == CRITICAL_STATUS_CRITICAL:
                await self._ensure_ac_running(room_name, current_temp, critical_config, direction)

    @staticmethod
    def _side_status(
        distance_past_critical: float,
        distance_past_warning: float,
        distance_past_safe: float,
        old_status: str,
    ) -> str:
        """Status for one side (hot or cold) given signed distances past each
        threshold (positive = past the threshold in the dangerous direction)."""
        if distance_past_critical >= 0:
            return CRITICAL_STATUS_CRITICAL
        if distance_past_warning >= 0:
            if old_status in [CRITICAL_STATUS_CRITICAL, CRITICAL_STATUS_RECOVERING]:
                if distance_past_safe <= 0:
                    return CRITICAL_STATUS_NORMAL
                return CRITICAL_STATUS_RECOVERING
            return CRITICAL_STATUS_WARNING
        if old_status in [CRITICAL_STATUS_CRITICAL, CRITICAL_STATUS_RECOVERING]:
            if distance_past_safe <= 0:
                return CRITICAL_STATUS_NORMAL
            return CRITICAL_STATUS_RECOVERING
        return CRITICAL_STATUS_NORMAL

    def _determine_status(
        self,
        current_temp: float,
        critical_config: dict[str, Any],
        old_status: str,
        old_direction: str,
    ) -> tuple[str, str]:
        """Determine status considering both over-temp and under-temp bounds.

        Returns (status, direction) where direction is "hot" or "cold" — the
        side that produced the status, used to pick the AC response mode.
        """
        warning_offset = critical_config.get(
            CONF_CRITICAL_WARNING_OFFSET, DEFAULT_CRITICAL_WARNING_OFFSET
        )

        severity = {
            CRITICAL_STATUS_NORMAL: 0,
            CRITICAL_STATUS_RECOVERING: 1,
            CRITICAL_STATUS_WARNING: 2,
            CRITICAL_STATUS_CRITICAL: 3,
        }

        # Hot side (over-temperature)
        hot_status = CRITICAL_STATUS_NORMAL
        critical_max = critical_config.get(CONF_CRITICAL_TEMP_MAX)
        if critical_max is not None:
            safe_max = critical_config.get(CONF_CRITICAL_TEMP_SAFE, critical_max - warning_offset)
            hot_old = old_status if old_direction == "hot" else CRITICAL_STATUS_NORMAL
            hot_status = self._side_status(
                current_temp - critical_max,
                current_temp - (critical_max - warning_offset),
                current_temp - safe_max,
                hot_old,
            )

        # Cold side (under-temperature / freeze protection)
        cold_status = CRITICAL_STATUS_NORMAL
        critical_min = critical_config.get(CONF_CRITICAL_TEMP_MIN)
        if critical_min is not None:
            safe_min = critical_config.get(CONF_CRITICAL_TEMP_MIN_SAFE, critical_min + warning_offset)
            cold_old = old_status if old_direction == "cold" else CRITICAL_STATUS_NORMAL
            cold_status = self._side_status(
                critical_min - current_temp,
                (critical_min + warning_offset) - current_temp,
                safe_min - current_temp,
                cold_old,
            )

        if severity[cold_status] > severity[hot_status]:
            return cold_status, "cold"
        if severity[hot_status] > 0:
            return hot_status, "hot"
        return CRITICAL_STATUS_NORMAL, old_direction

    async def _handle_status_change(
        self,
        room_name: str,
        old_status: str,
        new_status: str,
        current_temp: float,
        critical_config: dict[str, Any],
        direction: str = "hot",
    ) -> None:
        """Handle status transition and send notifications."""
        if direction == "cold":
            threshold = critical_config.get(CONF_CRITICAL_TEMP_MIN)
        else:
            threshold = critical_config.get(CONF_CRITICAL_TEMP_MAX)
        notify_services = critical_config.get(CONF_CRITICAL_NOTIFY_SERVICES, [])

        _LOGGER.info(
            "Critical room %s status changed: %s -> %s (temp: %.1f°C, direction: %s)",
            room_name,
            old_status,
            new_status,
            current_temp,
            direction,
        )

        # Send notifications
        if not notify_services:
            return

        # Prepare notification message
        message = None
        title = None

        if new_status == CRITICAL_STATUS_WARNING and threshold is not None:
            trend = "Rising" if direction == "hot" else "Falling"
            title = f"⚠️ Warning: {room_name} Temperature {trend}"
            margin = abs(threshold - current_temp)
            message = (
                f"{room_name} temperature is {current_temp:.1f}°C, "
                f"approaching critical threshold of {threshold}°C "
                f"(margin: {margin:.1f}°C). Monitoring closely."
            )
        elif new_status == CRITICAL_STATUS_CRITICAL and threshold is not None:
            if direction == "hot":
                title = f"🚨 CRITICAL: {room_name} Over Temperature!"
                action = "AC is being turned on automatically!"
            else:
                title = f"🥶 CRITICAL: {room_name} Under Temperature!"
                action = "Heating is being turned on automatically!"
            message = (
                f"{room_name} has reached critical temperature: {current_temp:.1f}°C "
                f"(threshold: {threshold}°C). {action}"
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
            self._room_states[room_name]["last_notification"] = dt_util.now()

    async def _send_notifications(
        self, notify_services: list[str], title: str, message: str
    ) -> None:
        """Send notification to configured services."""
        # "title" is part of the base notify schema — services that can't
        # render it (SMS gateways etc.) simply ignore it, so a message-only
        # fallback call is never needed.
        for service in notify_services:
            try:
                # Extract service name (remove "notify." prefix if present)
                service_name = service.replace("notify.", "")
                await self.hass.services.async_call(
                    "notify",
                    service_name,
                    {
                        "title": title,
                        "message": message,
                    },
                )
                _LOGGER.debug("Sent notification via %s", service)
            except Exception as e:
                _LOGGER.error("Failed to send notification via %s: %s", service, e)

    async def _ensure_ac_running(
        self, room_name: str, current_temp: float, critical_config: dict[str, Any],
        direction: str = "hot",
    ) -> None:
        """Ensure AC is running when critical temperature is reached.

        Over-temperature responds with COOL; under-temperature (freeze
        protection) responds with HEAT.
        """
        if not self._main_climate_entity:
            _LOGGER.warning(
                "Critical room %s at %.1f°C but no main climate entity configured to control AC",
                room_name,
                current_temp,
            )
            return

        # Check cooldown to prevent rapid on/off cycling
        if self._last_ac_trigger:
            time_since_trigger = dt_util.now() - self._last_ac_trigger
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

        # If AC is off, turn it on in the mode that addresses the emergency
        if current_hvac_mode in ["off", STATE_UNAVAILABLE, STATE_UNKNOWN]:
            if direction == "cold":
                response_mode = HVACMode.HEAT
                threshold = critical_config.get(CONF_CRITICAL_TEMP_MIN)
            else:
                response_mode = HVACMode.COOL
                threshold = critical_config.get(CONF_CRITICAL_TEMP_MAX)

            _LOGGER.warning(
                "🚨 CRITICAL: Turning on AC (%s) for %s (temp: %.1f°C, threshold: %s°C)",
                response_mode,
                room_name,
                current_temp,
                threshold,
            )

            try:
                await self.hass.services.async_call(
                    "climate",
                    "set_hvac_mode",
                    {
                        "entity_id": self._main_climate_entity,
                        "hvac_mode": response_mode,
                    },
                )

                self._last_ac_trigger = dt_util.now()
                _LOGGER.info("AC turned on successfully for critical room %s", room_name)

            except Exception as e:
                _LOGGER.error("Failed to turn on AC: %s", e)
        else:
            _LOGGER.debug(
                "AC is already running (mode: %s), relying on normal optimization for %s",
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

        current_temp = room_state["temperature"]
        config = critical_rooms[room_name]
        critical_max = config.get(CONF_CRITICAL_TEMP_MAX)
        critical_min = config.get(CONF_CRITICAL_TEMP_MIN)

        # Margin to whichever bound is nearer (both are "distance to danger")
        margins = []
        if critical_max is not None:
            margins.append(critical_max - current_temp)
        if critical_min is not None:
            margins.append(current_temp - critical_min)
        return min(margins) if margins else None
