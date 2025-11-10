"""Adaptive learning module for Smart Aircon Manager.

This module implements logic-based learning using statistical analysis
to optimize HVAC performance over time. No AI/LLMs involved - pure math.
"""
from __future__ import annotations

import json
import logging
import statistics
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

_LOGGER = logging.getLogger(__name__)


class PerformanceTracker:
    """Tracks performance metrics for adaptive learning."""

    def __init__(self, hass, config_entry_id: str, storage_path: Path):
        """Initialize performance tracker."""
        self.hass = hass
        self.config_entry_id = config_entry_id
        self.storage_path = storage_path
        self._data_points = {}  # room_name -> list of data points
        self._max_data_points_per_room = 1000  # Limit in-memory data points
        self._max_persisted_data_points = 200  # Only persist recent data (reduces file size by 80%)

    def track_cycle(
        self,
        room_name: str,
        temp_before: float,
        temp_after: float | None,
        fan_speed: int,
        target_temp: float,
        cycle_duration: float,
    ) -> None:
        """Track a single optimization cycle for a room.

        Args:
            room_name: Name of the room
            temp_before: Temperature before this cycle
            temp_after: Temperature after cycle (None if not yet measured)
            fan_speed: Fan speed applied (0-100%)
            target_temp: Target temperature
            cycle_duration: Time since last cycle (seconds)
        """
        if room_name not in self._data_points:
            self._data_points[room_name] = []

        data_point = {
            "timestamp": time.time(),
            "temp_before": temp_before,
            "temp_after": temp_after,
            "fan_speed": fan_speed,
            "target_temp": target_temp,
            "cycle_duration": cycle_duration,
            "temp_diff_from_target": temp_before - target_temp,
        }

        # Add to room's data
        self._data_points[room_name].append(data_point)

        # Limit data points to prevent memory issues
        if len(self._data_points[room_name]) > self._max_data_points_per_room:
            self._data_points[room_name].pop(0)

        _LOGGER.debug(
            "Tracked cycle for %s: temp=%.1f°C, fan=%d%%, target=%.1f°C",
            room_name, temp_before, fan_speed, target_temp
        )

    def get_convergence_rate(self, room_name: str, time_window_hours: int = 24) -> float | None:
        """Calculate average temperature convergence rate (°C/minute).

        Returns how fast temperature moves toward target on average.
        """
        if room_name not in self._data_points:
            return None

        cutoff_time = time.time() - (time_window_hours * 3600)
        recent_points = [
            p for p in self._data_points[room_name]
            if p["timestamp"] > cutoff_time and p["temp_after"] is not None
        ]

        if len(recent_points) < 10:
            return None

        convergence_rates = []
        for point in recent_points:
            temp_change = abs(point["temp_after"] - point["temp_before"])
            time_minutes = point["cycle_duration"] / 60.0
            if time_minutes > 0:
                rate = temp_change / time_minutes
                convergence_rates.append(rate)

        return statistics.mean(convergence_rates) if convergence_rates else None

    def get_overshoot_frequency(self, room_name: str, time_window_hours: int = 24) -> float:
        """Calculate how often temperature overshoots target (overshoots per day)."""
        if room_name not in self._data_points:
            return 0.0

        cutoff_time = time.time() - (time_window_hours * 3600)
        recent_points = [
            p for p in self._data_points[room_name]
            if p["timestamp"] > cutoff_time
        ]

        if len(recent_points) < 10:
            return 0.0

        overshoot_count = 0
        for i in range(1, len(recent_points)):
            prev = recent_points[i - 1]
            curr = recent_points[i]

            # Check if we crossed from above target to below target (or vice versa)
            prev_diff = prev["temp_diff_from_target"]
            curr_diff = curr["temp_diff_from_target"]

            if (prev_diff > 0 and curr_diff < -0.3) or (prev_diff < 0 and curr_diff > 0.3):
                overshoot_count += 1

        # Convert to overshoots per day
        hours_observed = len(recent_points) * (recent_points[0]["cycle_duration"] / 3600)
        if hours_observed > 0:
            return (overshoot_count / hours_observed) * 24
        return 0.0

    def estimate_thermal_mass(self, room_name: str) -> float | None:
        """Estimate thermal mass (0.0-1.0, higher = slower temperature change).

        Analyzes cooldown/warmup curves to determine thermal inertia.
        """
        if room_name not in self._data_points:
            return None

        points = self._data_points[room_name]
        if len(points) < 50:
            return None

        # Look at periods with consistent fan speed
        cooldown_rates = []
        for i in range(10, len(points)):
            # Get last 10 points
            window = points[i-10:i]

            # Check if fan speed was consistent
            fan_speeds = [p["fan_speed"] for p in window]
            if max(fan_speeds) - min(fan_speeds) > 10:
                continue  # Skip inconsistent periods

            # Calculate temperature change rate
            temp_change = abs(window[-1]["temp_before"] - window[0]["temp_before"])
            time_minutes = sum(p["cycle_duration"] for p in window) / 60.0

            if time_minutes > 0:
                rate = temp_change / time_minutes
                cooldown_rates.append(rate)

        if len(cooldown_rates) < 5:
            return None

        # Average rate: lower rate = higher thermal mass
        avg_rate = statistics.mean(cooldown_rates)

        # Normalize to 0-1 scale (assume 0.5°C/min is middle, 1.0°C/min is low mass)
        thermal_mass = max(0.0, min(1.0, 1.0 - (avg_rate / 1.0)))

        return round(thermal_mass, 2)

    def estimate_cooling_efficiency(self, room_name: str) -> float | None:
        """Estimate cooling efficiency (0.0-1.0, higher = more effective).

        Measures how well fan speed changes affect temperature.
        """
        if room_name not in self._data_points:
            return None

        points = self._data_points[room_name]
        if len(points) < 50:
            return None

        # Correlate fan speed with temperature change
        efficiency_samples = []

        for i in range(1, len(points)):
            prev = points[i - 1]
            curr = points[i]

            if curr["temp_after"] is None:
                continue

            # Temperature moved toward target
            prev_diff = abs(prev["temp_diff_from_target"])
            curr_diff = abs(curr["temp_diff_from_target"])

            if curr_diff < prev_diff:  # Improvement
                improvement = prev_diff - curr_diff
                fan_effect = curr["fan_speed"] / 100.0

                if fan_effect > 0.1:  # Ignore very low fan speeds
                    efficiency = improvement / fan_effect
                    efficiency_samples.append(efficiency)

        if len(efficiency_samples) < 10:
            return None

        # Normalize: assume 0.05°C improvement per 10% fan is middle efficiency
        avg_efficiency = statistics.mean(efficiency_samples)
        normalized = min(1.0, avg_efficiency / 0.5)

        return round(normalized, 2)

    def get_data_point_count(self, room_name: str) -> int:
        """Get number of data points collected for a room."""
        return len(self._data_points.get(room_name, []))

    def clear_room_data(self, room_name: str) -> None:
        """Clear all data for a specific room."""
        if room_name in self._data_points:
            self._data_points[room_name] = []
            _LOGGER.info("Cleared learning data for %s", room_name)

    def clear_all_data(self) -> None:
        """Clear all tracked data."""
        self._data_points = {}
        _LOGGER.info("Cleared all learning data")

    async def async_save_data_points(self) -> None:
        """Save tracker data points to storage (only recent data to limit file size)."""
        storage_file = self.storage_path / f"tracker_data_{self.config_entry_id}.json"

        try:
            # Ensure directory exists
            storage_file.parent.mkdir(parents=True, exist_ok=True)

            # Only save the most recent N data points per room to limit file size
            # Older data has diminishing value for learning calculations
            pruned_data = {}
            for room_name, points in self._data_points.items():
                if len(points) > self._max_persisted_data_points:
                    # Keep only the most recent data points
                    pruned_data[room_name] = points[-self._max_persisted_data_points:]
                else:
                    pruned_data[room_name] = points

            # Write to file
            storage_file.write_text(json.dumps(pruned_data, indent=2))
            total_points = sum(len(points) for points in pruned_data.values())
            _LOGGER.debug("Saved %d data points across %d rooms (pruned to recent data)", total_points, len(pruned_data))
        except Exception as e:
            _LOGGER.error("Failed to save tracker data points: %s", e)

    async def async_load_data_points(self) -> None:
        """Load tracker data points from storage.

        Note: We only persist the most recent 200 data points per room to:
        - Limit file size (reduces by ~80%)
        - Minimize startup load time
        - Reduce SD card wear (important for Raspberry Pi)
        - Keep relevant data (old data has diminishing value)

        200 points = ~1.6 hours of data at 30-second cycles, which is sufficient
        for calculating confidence (min 1.0, data_count / 200.0).
        """
        storage_file = self.storage_path / f"tracker_data_{self.config_entry_id}.json"

        if not storage_file.exists():
            _LOGGER.debug("No existing tracker data found")
            return

        try:
            self._data_points = json.loads(storage_file.read_text())
            total_points = sum(len(points) for points in self._data_points.values())
            _LOGGER.info("Loaded %d data points across %d rooms", total_points, len(self._data_points))
        except Exception as e:
            _LOGGER.error("Failed to load tracker data points: %s", e)


class LearningProfile:
    """Stores and manages learned parameters for a room."""

    def __init__(self, room_name: str):
        """Initialize learning profile."""
        self.room_name = room_name
        self.last_updated = None
        self.confidence = 0.0  # 0.0-1.0

        # Thermal characteristics
        self.thermal_mass = 0.5  # Default middle value
        self.cooling_efficiency = 0.6  # Default

        # Learned parameters
        self.optimal_smoothing_factor = 0.7  # Default from const.py
        self.optimal_smoothing_threshold = 10  # Default

        # Performance stats
        self.avg_convergence_time_seconds = None
        self.overshoot_rate_per_day = None

    def update_from_tracker(self, tracker: PerformanceTracker) -> bool:
        """Update profile from performance tracker data.

        Returns True if update was successful, False if insufficient data.
        """
        # Always update confidence based on data points collected
        data_count = tracker.get_data_point_count(self.room_name)
        self.confidence = min(1.0, data_count / 200.0)  # Full confidence at 200+ points

        # Estimate thermal characteristics
        thermal_mass = tracker.estimate_thermal_mass(self.room_name)
        cooling_efficiency = tracker.estimate_cooling_efficiency(self.room_name)

        if thermal_mass is None or cooling_efficiency is None:
            _LOGGER.debug(
                "Insufficient data to update thermal characteristics for %s (need 50+ data points), confidence=%.2f (%d points)",
                self.room_name, self.confidence, data_count
            )
            return False

        self.thermal_mass = thermal_mass
        self.cooling_efficiency = cooling_efficiency

        # Get performance stats
        convergence_rate = tracker.get_convergence_rate(self.room_name)
        overshoot_freq = tracker.get_overshoot_frequency(self.room_name)

        if convergence_rate:
            # Convergence rate is °C/min, convert to estimated time to reach 0.5°C
            self.avg_convergence_time_seconds = int((0.5 / convergence_rate) * 60)

        self.overshoot_rate_per_day = overshoot_freq

        # Adjust smoothing based on observed behavior
        if overshoot_freq > 2.0:  # More than 2 overshoots per day
            # Increase smoothing to reduce oscillation
            self.optimal_smoothing_factor = min(0.85, self.optimal_smoothing_factor + 0.05)
            self.optimal_smoothing_threshold = min(15, self.optimal_smoothing_threshold + 2)
        elif overshoot_freq < 0.5:  # Very stable
            # Decrease smoothing for faster response
            self.optimal_smoothing_factor = max(0.6, self.optimal_smoothing_factor - 0.05)
            self.optimal_smoothing_threshold = max(5, self.optimal_smoothing_threshold - 2)

        # Confidence was already updated at the start of this method
        self.last_updated = datetime.now(timezone.utc).isoformat()

        _LOGGER.info(
            "Updated learning profile for %s: thermal_mass=%.2f, efficiency=%.2f, confidence=%.2f",
            self.room_name, self.thermal_mass, self.cooling_efficiency, self.confidence
        )

        return True

    def to_dict(self) -> dict[str, Any]:
        """Convert profile to dictionary for storage."""
        return {
            "room_name": self.room_name,
            "last_updated": self.last_updated,
            "confidence": self.confidence,
            "thermal_mass": self.thermal_mass,
            "cooling_efficiency": self.cooling_efficiency,
            "optimal_smoothing_factor": self.optimal_smoothing_factor,
            "optimal_smoothing_threshold": self.optimal_smoothing_threshold,
            "avg_convergence_time_seconds": self.avg_convergence_time_seconds,
            "overshoot_rate_per_day": self.overshoot_rate_per_day,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> LearningProfile:
        """Create profile from dictionary."""
        profile = cls(data["room_name"])
        profile.last_updated = data.get("last_updated")
        profile.confidence = data.get("confidence", 0.0)
        profile.thermal_mass = data.get("thermal_mass", 0.5)
        profile.cooling_efficiency = data.get("cooling_efficiency", 0.6)
        profile.optimal_smoothing_factor = data.get("optimal_smoothing_factor", 0.7)
        profile.optimal_smoothing_threshold = data.get("optimal_smoothing_threshold", 10)
        profile.avg_convergence_time_seconds = data.get("avg_convergence_time_seconds")
        profile.overshoot_rate_per_day = data.get("overshoot_rate_per_day")
        return profile


class LearningManager:
    """Manages adaptive learning for all rooms."""

    def __init__(self, hass, config_entry_id: str, storage_path: Path):
        """Initialize learning manager."""
        self.hass = hass
        self.config_entry_id = config_entry_id
        self.storage_path = storage_path
        self.tracker = PerformanceTracker(hass, config_entry_id, storage_path)
        self.profiles = {}  # room_name -> LearningProfile

        # Learning configuration (defaults - will be overridden by config entry)
        self.enabled = False  # Disabled by default (opt-in)
        self.learning_mode = "passive"  # passive, active
        self.confidence_threshold = 0.7
        self.max_adjustment_per_update = 0.10  # 10% max change

    async def async_load_profiles(self) -> None:
        """Load learning profiles and tracker data from storage."""
        # Load profiles
        storage_file = self.storage_path / f"learning_{self.config_entry_id}.json"

        if not storage_file.exists():
            _LOGGER.debug("No existing learning profiles found")
        else:
            try:
                data = json.loads(storage_file.read_text())
                for room_name, profile_data in data.items():
                    self.profiles[room_name] = LearningProfile.from_dict(profile_data)
                _LOGGER.info("Loaded %d learning profiles", len(self.profiles))
            except Exception as e:
                _LOGGER.error("Failed to load learning profiles: %s", e)

        # Load tracker data points
        await self.tracker.async_load_data_points()

    async def async_save_profiles(self) -> None:
        """Save learning profiles and tracker data to storage."""
        # Save profiles
        storage_file = self.storage_path / f"learning_{self.config_entry_id}.json"

        try:
            # Ensure directory exists
            storage_file.parent.mkdir(parents=True, exist_ok=True)

            # Convert profiles to dict
            data = {
                room_name: profile.to_dict()
                for room_name, profile in self.profiles.items()
            }

            # Write to file
            storage_file.write_text(json.dumps(data, indent=2))
            _LOGGER.debug("Saved %d learning profiles", len(self.profiles))
        except Exception as e:
            _LOGGER.error("Failed to save learning profiles: %s", e)

        # Save tracker data points
        await self.tracker.async_save_data_points()

    async def async_update_profiles(self) -> list[str]:
        """Update learning profiles from tracker data.

        Returns list of room names that were updated.
        """
        updated_rooms = []
        any_profile_modified = False

        for room_name in self.tracker._data_points.keys():
            if room_name not in self.profiles:
                self.profiles[room_name] = LearningProfile(room_name)
                any_profile_modified = True

            profile = self.profiles[room_name]
            # update_from_tracker now always updates confidence, even if insufficient data
            # Returns True only if thermal characteristics were successfully calculated
            if profile.update_from_tracker(self.tracker):
                updated_rooms.append(room_name)
                any_profile_modified = True
            else:
                # Even if full update failed, confidence was updated - save it
                any_profile_modified = True

        # Save profiles if any were created or modified (including confidence-only updates)
        if any_profile_modified:
            await self.async_save_profiles()

        return updated_rooms

    def get_profile(self, room_name: str) -> LearningProfile | None:
        """Get learning profile for a room."""
        return self.profiles.get(room_name)

    def should_apply_learning(self, room_name: str) -> bool:
        """Check if learning should be applied for a room."""
        if not self.enabled or self.learning_mode != "active":
            return False

        profile = self.get_profile(room_name)
        if not profile:
            return False

        return profile.confidence >= self.confidence_threshold
