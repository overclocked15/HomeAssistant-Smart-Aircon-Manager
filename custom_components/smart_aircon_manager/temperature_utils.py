"""Temperature utility functions for Smart Aircon Manager."""
from __future__ import annotations

import logging
from typing import Any

from homeassistant.const import STATE_UNAVAILABLE, STATE_UNKNOWN

_LOGGER = logging.getLogger(__name__)


def normalize_temperature(
    temp_state: Any,
    entity_name: str = "sensor",
) -> float | None:
    """Normalize temperature sensor reading to Celsius.

    Handles Fahrenheit to Celsius conversion and validates the reading.
    Returns None if the sensor is unavailable or has invalid state.

    Args:
        temp_state: The state object from hass.states.get()
        entity_name: Human-readable name for logging (e.g., room name)

    Returns:
        Temperature in Celsius, or None if unavailable/invalid
    """
    if not temp_state or temp_state.state in [STATE_UNAVAILABLE, STATE_UNKNOWN, "unknown", "unavailable", "none"]:
        return None

    try:
        raw_value = temp_state.state
        current_temp = float(raw_value)

        # Check unit and convert if needed
        unit = temp_state.attributes.get("unit_of_measurement", "°C")
        if unit in ["°F", "fahrenheit", "F"]:
            # Convert Fahrenheit to Celsius
            current_temp = (current_temp - 32) * 5.0 / 9.0
            _LOGGER.debug(
                "Converted %s temperature from %.1f°F to %.1f°C",
                entity_name,
                float(raw_value),
                current_temp
            )

        return current_temp

    except (ValueError, TypeError) as err:
        _LOGGER.warning(
            "Could not parse temperature for %s: %s (error: %s)",
            entity_name,
            temp_state.state,
            err
        )
        return None


def validate_temperature_range(
    temp_celsius: float,
    min_temp: float = -50.0,
    max_temp: float = 70.0,
) -> bool:
    """Validate that a temperature in Celsius is within realistic range.

    Args:
        temp_celsius: Temperature in Celsius to validate
        min_temp: Minimum realistic temperature (default -50°C)
        max_temp: Maximum realistic temperature (default 70°C)

    Returns:
        True if temperature is within range, False otherwise
    """
    return min_temp <= temp_celsius <= max_temp
