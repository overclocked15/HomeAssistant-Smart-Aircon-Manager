"""Diagnostics support for Smart Aircon Manager."""
from __future__ import annotations

from typing import Any

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant

from .const import DOMAIN

REDACT_KEYS = {
    "api_key",
    "notify_services",
    "critical_notify_services",
}


def _redact_data(data: dict[str, Any]) -> dict[str, Any]:
    """Redact sensitive data from diagnostics."""
    redacted = {}
    for key, value in data.items():
        if key in REDACT_KEYS:
            redacted[key] = "**REDACTED**"
        elif isinstance(value, dict):
            redacted[key] = _redact_data(value)
        elif isinstance(value, list) and value and isinstance(value[0], dict):
            redacted[key] = [_redact_data(item) if isinstance(item, dict) else item for item in value]
        else:
            redacted[key] = value
    return redacted


async def async_get_config_entry_diagnostics(
    hass: HomeAssistant, entry: ConfigEntry
) -> dict[str, Any]:
    """Return diagnostics for a config entry."""
    entry_data = hass.data.get(DOMAIN, {}).get(entry.entry_id, {})
    optimizer = entry_data.get("optimizer")
    coordinator = entry_data.get("coordinator")

    diag: dict[str, Any] = {
        "config_entry": _redact_data(dict(entry.data)),
        "version": entry.version,
    }

    if optimizer:
        diag["optimizer"] = {
            "target_temperature": optimizer.target_temperature,
            "temperature_deadband": optimizer.temperature_deadband,
            "hvac_mode": optimizer.hvac_mode,
            "is_enabled": optimizer.is_enabled,
            "auto_control_main_ac": optimizer.auto_control_main_ac,
            "auto_control_ac_temperature": optimizer.auto_control_ac_temperature,
            "enable_room_balancing": optimizer.enable_room_balancing,
            "enable_humidity_control": optimizer.enable_humidity_control,
            "enable_predictive_control": optimizer.enable_predictive_control,
            "enable_weather_adjustment": optimizer.enable_weather_adjustment,
            "enable_scheduling": optimizer.enable_scheduling,
            "enable_occupancy_control": optimizer.enable_occupancy_control,
            "enable_compressor_protection": optimizer.enable_compressor_protection,
            "enable_enhanced_compressor_protection": optimizer.enable_enhanced_compressor_protection,
            "enable_adaptive_bands": optimizer.enable_adaptive_bands,
            "enable_adaptive_efficiency": optimizer.enable_adaptive_efficiency,
            "ac_turn_on_threshold": optimizer.ac_turn_on_threshold,
            "ac_turn_off_threshold": optimizer.ac_turn_off_threshold,
            "main_fan_high_threshold": optimizer.main_fan_high_threshold,
            "main_fan_medium_threshold": optimizer.main_fan_medium_threshold,
            "overshoot_tier1_threshold": optimizer.overshoot_tier1_threshold,
            "overshoot_tier2_threshold": optimizer.overshoot_tier2_threshold,
            "overshoot_tier3_threshold": optimizer.overshoot_tier3_threshold,
            "room_count": len(optimizer.room_configs),
            "total_optimizations_run": optimizer._total_optimizations_run,
            "error_count": optimizer._error_count,
            "last_error": optimizer._last_error,
            "quick_action_mode": optimizer._quick_action_mode,
            "manual_override": getattr(optimizer, 'manual_override_enabled', False),
        }

    if coordinator and coordinator.data:
        room_states = coordinator.data.get("room_states", {})
        diag["room_states"] = {
            room: {
                "current_temperature": state.get("current_temperature"),
                "target_temperature": state.get("target_temperature"),
                "cover_position": state.get("cover_position"),
                "current_humidity": state.get("current_humidity"),
            }
            for room, state in room_states.items()
        }
        diag["recommendations"] = coordinator.data.get("recommendations", {})
        diag["main_climate_state"] = coordinator.data.get("main_climate_state")
        diag["main_fan_speed"] = coordinator.data.get("main_fan_speed")
        diag["needs_ac"] = coordinator.data.get("needs_ac")

    if optimizer and optimizer.learning_manager:
        lm = optimizer.learning_manager
        profiles = {}
        for room_config in optimizer.room_configs:
            room_name = room_config["room_name"]
            profile = lm.get_profile(room_name)
            if profile:
                profiles[room_name] = {
                    "confidence": round(profile.confidence, 3),
                    "thermal_mass": profile.thermal_mass,
                    "cooling_efficiency": profile.cooling_efficiency,
                    "optimal_smoothing_factor": profile.optimal_smoothing_factor,
                    "optimal_smoothing_threshold": profile.optimal_smoothing_threshold,
                    "avg_convergence_time_seconds": profile.avg_convergence_time_seconds,
                    "overshoot_rate_per_day": profile.overshoot_rate_per_day,
                    "balancing_bias": profile.balancing_bias,
                    "data_points": lm.tracker.get_data_point_count(room_name),
                }
        diag["learning_profiles"] = profiles

    return diag
