"""Adaptive learning module for Smart Aircon Manager.

This module implements logic-based learning using statistical analysis
to optimize HVAC performance over time. No AI/LLMs involved - pure math.
"""
from __future__ import annotations

import bisect
import json
import logging
import statistics
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

_LOGGER = logging.getLogger(__name__)

# Targets that differ by more than this between consecutive data points mark
# a target change rather than a room overshooting.
_TARGET_CHANGE_EPSILON = 0.25

# A room further than this from its target (°C) is being actively conditioned
ACTIVE_ERROR_C = 0.5
# Intervals longer than this (minutes) span downtime or an AC that was off
MAX_INTERVAL_MINUTES = 10.0
# Thermal mass: a room changing this fast (°C/min) while actively conditioned
# reads 0.0; one that barely moves reads 1.0. Conditioned rooms typically move
# 0.02 to 0.15 °C/min.
THERMAL_RATE_SCALE = 0.2
# Cooling efficiency: cooling this fast (°C/min) with the damper fully open reads 1.0
EFFICIENCY_SCALE = 0.1
# Below this damper position a room is "at low airflow" for passive drift
LOW_AIRFLOW_PERCENT = 30
# Balancing bias: a room whose mean shortfall from its target passes this (°C)
# moves its bias by one step per hourly update; otherwise the bias decays
BIAS_SHORTFALL_C = 0.3
BIAS_STEP = 0.05
# Profiles saved before this version were learned with the old estimators
PROFILE_VERSION = 2


def _target_changed(prev: dict[str, Any], curr: dict[str, Any]) -> bool:
    """True when the target moved between two consecutive data points."""
    prev_target = prev.get("target_temp")
    curr_target = curr.get("target_temp")
    if prev_target is None or curr_target is None:
        return False
    return abs(curr_target - prev_target) > _TARGET_CHANGE_EPSILON


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
        operating_mode: str | None = None,
    ) -> None:
        """Track a single optimization cycle for a room.

        Args:
            room_name: Name of the room
            temp_before: Temperature before this cycle
            temp_after: Temperature after cycle (None if not yet measured)
            fan_speed: Fan speed applied (0-100%)
            target_temp: Target temperature
            cycle_duration: Time since last cycle (seconds)
            operating_mode: "cool" or "heat" — lets analysis separate seasons
                so heating data doesn't pollute cooling metrics
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
            "operating_mode": operating_mode,
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

    def _intervals(
        self, room_name: str, mode: str | None = None, time_window_hours: float | None = None
    ):
        """Yield (previous, current, minutes) for consecutive data points.

        ``current`` records the temperature change since the previous tracked
        pass (temp_before → temp_after), and that change happened under the
        damper position applied at the previous pass, ``previous["fan_speed"]``
        (each point stores the position applied after its own measurement).
        Skips target changes, intervals longer than MAX_INTERVAL_MINUTES,
        points without a reading and, with ``mode``, points tagged with the
        other mode (legacy untagged points are kept).
        """
        points = self._data_points.get(room_name, [])
        cutoff = time.time() - time_window_hours * 3600 if time_window_hours else None
        for previous, current in zip(points, points[1:]):
            if current.get("temp_after") is None or current.get("temp_before") is None:
                continue
            if cutoff is not None and current.get("timestamp", 0) <= cutoff:
                continue
            if mode is not None and current.get("operating_mode") not in (None, mode):
                continue
            if _target_changed(previous, current):
                continue
            minutes = current.get("cycle_duration", 0) / 60.0
            if minutes <= 0 or minutes > MAX_INTERVAL_MINUTES:
                continue
            yield previous, current, minutes

    def get_convergence_rate(
        self, room_name: str, time_window_hours: int = 24, mode: str | None = None
    ) -> float | None:
        """Net speed (°C/min) at which the room closes on its target.

        Total progress toward the target over total time, for intervals that
        start more than ACTIVE_ERROR_C from the target. Intervals that move
        away count against it, so sensor noise averages out (clipping each
        interval at zero, as before, turned noise into apparent convergence).
        ``mode`` optionally filters to cool/heat data. None with fewer than
        5 qualifying intervals; 0.0 when the room isn't closing in.
        """
        progress = 0.0
        total_minutes = 0.0
        count = 0
        for _previous, current, minutes in self._intervals(room_name, mode, time_window_hours):
            target = current.get("target_temp")
            if target is None:
                continue
            dist_before = abs(current["temp_before"] - target)
            if dist_before <= ACTIVE_ERROR_C:
                continue
            progress += dist_before - abs(current["temp_after"] - target)
            total_minutes += minutes
            count += 1
        if count < 5 or total_minutes <= 0:
            return None
        return max(0.0, progress / total_minutes)

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

            # A target change (schedule switch, user change, comfort
            # relaxation) moves the reference, not the room — not an overshoot
            if _target_changed(prev, curr):
                continue

            # Check if we crossed from above target to below target (or vice versa)
            prev_diff = prev["temp_diff_from_target"]
            curr_diff = curr["temp_diff_from_target"]

            if (prev_diff > 0 and curr_diff < -0.3) or (prev_diff < 0 and curr_diff > 0.3):
                overshoot_count += 1

        # Convert to overshoots per day using actual total duration
        total_duration_seconds = sum(p["cycle_duration"] for p in recent_points)
        hours_observed = total_duration_seconds / 3600
        if hours_observed > 0:
            return (overshoot_count / hours_observed) * 24
        return 0.0

    def estimate_thermal_mass(self, room_name: str) -> float | None:
        """How slowly the room responds (0.0 fast to 1.0 slow).

        Median rate of change over 10-pass windows in which the room was being
        actively conditioned: further than ACTIVE_ERROR_C from its target
        throughout, and the damper positions in force during the window steady
        (within 10 points) and at least half open.

            thermal_mass = clamp(1 − median rate / THERMAL_RATE_SCALE, 0, 1)

        The old estimate used every steady window (mostly rooms sitting still
        at target) on a 1 °C/min scale, so every room read about 0.97.
        None until 50 points and 5 qualifying windows exist.
        """
        points = self._data_points.get(room_name, [])
        if len(points) < 50:
            return None

        rates = []
        for end in range(11, len(points) + 1):
            window = points[end - 10:end]
            # Each change in the window ran under the position stored on the
            # point before it (positions are stored after each measurement)
            fans = [p.get("fan_speed", 0) for p in points[end - 11:end - 1]]
            if max(fans) - min(fans) > 10 or min(fans) < 50:
                continue
            if any(abs(p.get("temp_diff_from_target", 0.0)) <= ACTIVE_ERROR_C for p in window):
                continue
            if any(p.get("temp_after") is None for p in window):
                continue
            durations = [p.get("cycle_duration", 0) / 60.0 for p in window]
            if min(durations) <= 0 or max(durations) > MAX_INTERVAL_MINUTES:
                continue
            change = abs(window[-1]["temp_after"] - window[0]["temp_before"])
            rates.append(change / sum(durations))

        if len(rates) < 5:
            return None
        rate = statistics.median(rates)
        return round(max(0.0, min(1.0, 1.0 - rate / THERMAL_RATE_SCALE)), 2)

    def estimate_cooling_efficiency(self, room_name: str) -> float | None:
        """How well airflow cools the room (0.0-1.0, higher = more effective).

        Net cooling per minute per unit of damper opening, over cool-mode
        intervals that start with the room more than ACTIVE_ERROR_C above its
        target, using the damper position in place during each interval:

            raw = Σ(T_before − T_after) / Σ(minutes × damper fraction)
            efficiency = clamp(raw / EFFICIENCY_SCALE, 0, 1)

        Every such interval counts, including ones where the room didn't
        cool. The old estimate averaged only the passes that improved, per
        pass, divided by the next pass's damper position: sensor noise over
        damper position. Cool-mode data only (legacy untagged points kept).
        None until 50 points and 20 qualifying intervals exist.
        """
        if len(self._data_points.get(room_name, [])) < 50:
            return None

        cooling = 0.0
        weight = 0.0
        count = 0
        for previous, current, minutes in self._intervals(room_name, "cool"):
            target = current.get("target_temp")
            if target is None or current["temp_before"] - target <= ACTIVE_ERROR_C:
                continue
            fraction = previous.get("fan_speed", 0) / 100.0
            if fraction <= 0.1:
                continue
            cooling += current["temp_before"] - current["temp_after"]
            weight += minutes * fraction
            count += 1

        if count < 20 or weight <= 0:
            return None
        return round(max(0.0, min(1.0, cooling / weight / EFFICIENCY_SCALE)), 2)

    def get_relative_convergence_rate(self, room_name: str, mode: str | None = None) -> float | None:
        """Calculate room's convergence rate relative to house average.

        ``mode`` optionally restricts the comparison to cool/heat season data.

        Returns:
            Value relative to 1.0 (house average):
            - > 1.0: Room converges faster than average
            - < 1.0: Room converges slower than average
            - None: Insufficient data
        """
        if room_name not in self._data_points:
            return None

        # Get this room's convergence rate
        room_rate = self.get_convergence_rate(room_name, mode=mode)
        if not room_rate:
            return None

        # Get average convergence rate across all rooms
        all_rates = []
        for rname in self._data_points.keys():
            rate = self.get_convergence_rate(rname, mode=mode)
            if rate:
                all_rates.append(rate)

        if len(all_rates) < 2:
            return None

        avg_rate = statistics.mean(all_rates)
        if avg_rate == 0:
            return None

        relative_rate = room_rate / avg_rate
        return round(relative_rate, 2)

    def _passive_drift_rate(self, room_name: str, mode: str) -> float | None:
        """Net drift rate (°C/min) away from target at low airflow.

        mode="cool": upward drift = heat gain (sun load, poor insulation).
        mode="heat": downward drift = heat loss.

        Total drift over total time across intervals spent at or below
        LOW_AIRFLOW_PERCENT, so the figure reflects the room's envelope rather
        than its duct supply. Intervals with no change, or a change the other
        way, count too: averaging only the rising intervals returned the
        sensor's step size (0.2 °C/min for any room with 0.1 °C sensors).
        None with fewer than 10 intervals or no net drift that way.
        """
        drift = 0.0
        total_minutes = 0.0
        count = 0
        for previous, current, minutes in self._intervals(room_name, mode):
            if previous.get("fan_speed", 100) > LOW_AIRFLOW_PERCENT:
                continue
            delta = current["temp_after"] - current["temp_before"]
            drift += delta if mode == "cool" else -delta
            total_minutes += minutes
            count += 1
        if count < 10 or total_minutes <= 0:
            return None
        rate = drift / total_minutes
        return rate if rate > 0 else None

    def get_chronic_shortfall(self, room_name: str, time_window_hours: int = 24) -> float | None:
        """Mean distance (°C) the room sits short of its target.

        Measured in the direction being conditioned: > 0 when the room runs
        warmer than its target while cooling (or cooler while heating) and so
        needs more air, < 0 when it is over-conditioned. Points without a
        cool/heat tag are skipped. None with fewer than 20 points.
        """
        cutoff = time.time() - time_window_hours * 3600
        values = []
        for point in self._data_points.get(room_name, []):
            mode = point.get("operating_mode")
            diff = point.get("temp_diff_from_target")
            if point.get("timestamp", 0) <= cutoff or mode not in ("cool", "heat") or diff is None:
                continue
            values.append(diff if mode == "cool" else -diff)
        if len(values) < 20:
            return None
        return statistics.mean(values)

    def get_relative_drift_rate(self, room_name: str, mode: str) -> float | None:
        """Room's passive drift rate relative to the house average.

        Returns > 1.0 when this room gains heat (mode="cool") or loses heat
        (mode="heat") faster than the average room, or None when there is not
        enough low-airflow data for a meaningful comparison.
        """
        room_rate = self._passive_drift_rate(room_name, mode)
        if not room_rate:
            return None

        all_rates = []
        for rname in list(self._data_points.keys()):
            rate = self._passive_drift_rate(rname, mode)
            if rate:
                all_rates.append(rate)

        if len(all_rates) < 2:
            return None

        avg_rate = statistics.mean(all_rates)
        if avg_rate == 0:
            return None

        return round(room_rate / avg_rate, 2)

    def detect_room_coupling(self, primary_room: str) -> dict[str, float]:
        """Detect which rooms are thermally coupled to this room.

        Coupling is detected when rooms' temperatures correlate strongly.

        Returns:
            Dict of room_name → coupling_factor (0.0-1.0)
            Higher values indicate stronger thermal coupling
        """
        if primary_room not in self._data_points:
            return {}

        primary_points = self._data_points[primary_room]
        if len(primary_points) < 50:
            return {}

        coupled_rooms = {}

        # Stride the windows instead of sliding by 1, and bisect the other
        # room's (chronologically appended) timestamps instead of scanning
        # every point per window. The naive version was O(rooms² × points²)
        # and could stall the event loop for seconds on an 8-room house.
        WINDOW = 10
        STRIDE = 10

        for other_room, other_points in list(self._data_points.items()):
            if other_room == primary_room or len(other_points) < 50:
                continue

            other_times = [p["timestamp"] for p in other_points]

            # Find overlapping time windows and calculate correlation
            correlations = []

            for i in range(0, len(primary_points) - WINDOW, STRIDE):
                primary_window = primary_points[i:i + WINDOW]

                min_time = primary_window[0]["timestamp"]
                max_time = primary_window[-1]["timestamp"]

                # Find matching time window in other room
                lo = bisect.bisect_left(other_times, min_time)
                hi = bisect.bisect_right(other_times, max_time)
                matching_points = other_points[lo:hi]

                if len(matching_points) < 5:
                    continue

                # Calculate temperature change correlation
                primary_changes = [
                    p["temp_before"] - primary_window[0]["temp_before"]
                    for p in primary_window
                ]
                other_changes = [
                    p["temp_before"] - matching_points[0]["temp_before"]
                    for p in matching_points[:len(primary_changes)]
                ]

                if len(primary_changes) == len(other_changes) and len(primary_changes) > 0:
                    # Simple correlation coefficient
                    correlation = self._calculate_correlation(primary_changes, other_changes)
                    if correlation is not None:
                        correlations.append(abs(correlation))

            if correlations:
                avg_correlation = statistics.mean(correlations)
                if avg_correlation > 0.5:  # Threshold for significant coupling
                    coupled_rooms[other_room] = round(avg_correlation, 2)

        return coupled_rooms

    def _calculate_correlation(self, x: list[float], y: list[float]) -> float | None:
        """Calculate Pearson correlation coefficient between two lists."""
        if len(x) != len(y) or len(x) < 2:
            return None

        n = len(x)
        mean_x = statistics.mean(x)
        mean_y = statistics.mean(y)

        # Calculate covariance and standard deviations
        # Use n-1 divisor consistently (sample statistics) to match statistics.stdev
        covariance = sum((x[i] - mean_x) * (y[i] - mean_y) for i in range(n)) / (n - 1)

        std_x = statistics.stdev(x) if len(x) > 1 else 0
        std_y = statistics.stdev(y) if len(y) > 1 else 0

        if std_x == 0 or std_y == 0:
            return None

        correlation = covariance / (std_x * std_y)
        return correlation

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
            # Ensure directory exists (non-blocking)
            await self.hass.async_add_executor_job(
                lambda: storage_file.parent.mkdir(parents=True, exist_ok=True)
            )

            # Only save the most recent N data points per room to limit file size
            # Older data has diminishing value for learning calculations
            pruned_data = {}
            for room_name, points in self._data_points.items():
                if len(points) > self._max_persisted_data_points:
                    # Keep only the most recent data points
                    pruned_data[room_name] = points[-self._max_persisted_data_points:]
                else:
                    pruned_data[room_name] = points

            # Atomic write via temp file + rename so a mid-write crash leaves
            # the previous file untouched instead of producing partial JSON.
            data_str = json.dumps(pruned_data, indent=2)

            def _atomic_write():
                tmp_file = storage_file.with_suffix(storage_file.suffix + ".tmp")
                tmp_file.write_text(data_str)
                tmp_file.replace(storage_file)

            await self.hass.async_add_executor_job(_atomic_write)
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

        exists = await self.hass.async_add_executor_job(storage_file.exists)
        if not exists:
            _LOGGER.debug("No existing tracker data found")
            return

        try:
            raw_data = await self.hass.async_add_executor_job(storage_file.read_text)
            self._data_points = json.loads(raw_data)
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

        # Adaptive balancing characteristics
        # Signed, -1.0 to +1.0: > 0 when the room chronically runs short of its
        # target (needs more conditioning air), < 0 when over-conditioned
        self.balancing_bias = 0.0
        self.relative_heat_gain_rate = 1.0  # Relative to house avg (0.5-2.0)
        self.relative_cool_rate = 1.0  # Relative to house avg (0.5-2.0)
        self.coupled_rooms = []  # List of thermally coupled room names
        self.coupling_factors = {}  # Dict: room_name → coupling factor (0.0-1.0)

    def update_from_tracker(self, tracker: PerformanceTracker, max_step: float | None = None) -> bool:
        """Update profile from performance tracker data.

        Each estimate updates on its own as soon as it has enough data.
        ``max_step`` (the "learning max adjustment" setting) limits how far
        one hourly update moves thermal mass and cooling efficiency (0 to 1
        scale) and the relative drift rates (scaled to their 0.5 to 2.0 range).

        Returns True if anything was learned, False if there wasn't enough data.
        """
        # Always update confidence based on data points collected, weighted by recency
        import time as time_module
        data_points = tracker._data_points.get(self.room_name, [])
        if not data_points:
            self.confidence = 0.0
        else:
            # Weight data points by recency: full weight within 24h, halving every 7 days
            now = time_module.time()
            HALF_LIFE_SECONDS = 7 * 24 * 3600  # 7 days
            weighted_count = 0.0
            for point in data_points:
                age = now - point.get("timestamp", 0)
                weight = 0.5 ** (age / HALF_LIFE_SECONDS)
                weighted_count += weight
            self.confidence = min(1.0, weighted_count / 200.0)

        def stepped(old: float, new: float, limit: float | None) -> float:
            if limit is None or limit <= 0:
                return new
            return old + max(-limit, min(limit, new - old))

        learned = []

        # Thermal characteristics (each only once it has enough data)
        thermal_mass = tracker.estimate_thermal_mass(self.room_name)
        if thermal_mass is not None:
            self.thermal_mass = round(stepped(self.thermal_mass, thermal_mass, max_step), 3)
            learned.append("thermal mass")
        cooling_efficiency = tracker.estimate_cooling_efficiency(self.room_name)
        if cooling_efficiency is not None:
            self.cooling_efficiency = round(stepped(self.cooling_efficiency, cooling_efficiency, max_step), 3)
            learned.append("cooling efficiency")

        convergence_rate = tracker.get_convergence_rate(self.room_name)
        if convergence_rate:
            # °C/min -> estimated time to close 0.5 °C
            self.avg_convergence_time_seconds = int((0.5 / convergence_rate) * 60)
            learned.append("convergence")
        self.overshoot_rate_per_day = tracker.get_overshoot_frequency(self.room_name)

        # Smoothing parameter learning: compare overshoots in the two halves
        # of the last 48 hours. The factor weights the NEW speed (1.0 = no
        # smoothing), so more damping means a LOWER factor; the threshold is
        # the largest change that gets smoothed, so more damping means a
        # HIGHER threshold. (The factor used to move the wrong way.)
        recent_points = [p for p in data_points if p.get("timestamp", 0) > time_module.time() - 48 * 3600]
        if len(recent_points) >= 40:
            midpoint = len(recent_points) // 2

            def half_overshoot_count(points):
                count = 0
                for i in range(1, len(points)):
                    if _target_changed(points[i - 1], points[i]):
                        continue
                    prev_diff = points[i - 1].get("temp_diff_from_target", 0)
                    curr_diff = points[i].get("temp_diff_from_target", 0)
                    if (prev_diff > 0 and curr_diff < -0.3) or (prev_diff < 0 and curr_diff > 0.3):
                        count += 1
                return count

            first_overshoots = half_overshoot_count(recent_points[:midpoint])
            second_overshoots = half_overshoot_count(recent_points[midpoint:])
            if second_overshoots > first_overshoots + 1:
                # More overshoots lately: damp more
                self.optimal_smoothing_factor = round(max(0.5, self.optimal_smoothing_factor - 0.02), 3)
                self.optimal_smoothing_threshold = min(20, self.optimal_smoothing_threshold + 1)
                learned.append("smoothing")
            elif second_overshoots < first_overshoots and first_overshoots > 0:
                # Fewer overshoots: cautiously respond faster
                self.optimal_smoothing_factor = round(min(0.95, self.optimal_smoothing_factor + 0.01), 3)
                self.optimal_smoothing_threshold = max(5, self.optimal_smoothing_threshold - 1)
                learned.append("smoothing")

        # Relative passive drift (heat gain while cooling, heat loss while
        # heating) at low airflow, for the balancing convergence adjustment:
        # > 1.0 = this room drifts faster than the average room
        drift_step = None if max_step is None else max_step * 1.5
        heat_gain = tracker.get_relative_drift_rate(self.room_name, mode="cool")
        heat_loss = tracker.get_relative_drift_rate(self.room_name, mode="heat")
        if heat_gain is not None:
            self.relative_heat_gain_rate = round(
                max(0.5, min(2.0, stepped(self.relative_heat_gain_rate, heat_gain, drift_step))), 3
            )
            learned.append("heat gain")
        if heat_loss is not None:
            self.relative_cool_rate = round(
                max(0.5, min(2.0, stepped(self.relative_cool_rate, heat_loss, drift_step))), 3
            )
            learned.append("heat loss")

        # Detect room coupling
        coupling = tracker.detect_room_coupling(self.room_name)
        if coupling:
            self.coupled_rooms = list(coupling.keys())
            self.coupling_factors = coupling
            learned.append("coupling")
            _LOGGER.debug(
                "Room %s coupled to: %s",
                self.room_name,
                ", ".join(f"{room}({factor:.2f})" for room, factor in coupling.items())
            )

        # Balancing bias: an integral-like correction for a room that sits
        # short of (or past) its target day after day. Signed, in "needs more
        # air" terms, and decaying once the room is fine. (It used to follow
        # overshoot frequency and push every "stable" room the same way, so
        # a room stuck below target while cooling got more cold air.)
        shortfall = tracker.get_chronic_shortfall(self.room_name)
        if shortfall is not None:
            if shortfall > BIAS_SHORTFALL_C:
                self.balancing_bias = min(1.0, self.balancing_bias + BIAS_STEP)
            elif shortfall < -BIAS_SHORTFALL_C:
                self.balancing_bias = max(-1.0, self.balancing_bias - BIAS_STEP)
            elif self.balancing_bias > 0:
                self.balancing_bias = max(0.0, self.balancing_bias - BIAS_STEP)
            else:
                self.balancing_bias = min(0.0, self.balancing_bias + BIAS_STEP)
            self.balancing_bias = round(self.balancing_bias, 3)
            learned.append("balancing bias")

        if not learned:
            _LOGGER.debug(
                "Not enough data to learn for %s yet, confidence=%.2f (%d points)",
                self.room_name, self.confidence, len(data_points)
            )
            return False

        self.last_updated = datetime.now(timezone.utc).isoformat()
        _LOGGER.info(
            "Updated learning profile for %s (%s): thermal_mass=%.2f, efficiency=%.2f, confidence=%.2f",
            self.room_name, ", ".join(learned), self.thermal_mass, self.cooling_efficiency, self.confidence
        )
        return True

    def to_dict(self) -> dict[str, Any]:
        """Convert profile to dictionary for storage."""
        return {
            "version": PROFILE_VERSION,
            "room_name": self.room_name,
            "last_updated": self.last_updated,
            "confidence": self.confidence,
            "thermal_mass": self.thermal_mass,
            "cooling_efficiency": self.cooling_efficiency,
            "optimal_smoothing_factor": self.optimal_smoothing_factor,
            "optimal_smoothing_threshold": self.optimal_smoothing_threshold,
            "avg_convergence_time_seconds": self.avg_convergence_time_seconds,
            "overshoot_rate_per_day": self.overshoot_rate_per_day,
            "balancing_bias": self.balancing_bias,
            "relative_heat_gain_rate": self.relative_heat_gain_rate,
            "relative_cool_rate": self.relative_cool_rate,
            "coupled_rooms": self.coupled_rooms,
            "coupling_factors": self.coupling_factors,
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
        profile.balancing_bias = data.get("balancing_bias", 0.0)
        profile.relative_heat_gain_rate = data.get("relative_heat_gain_rate", 1.0)
        profile.relative_cool_rate = data.get("relative_cool_rate", 1.0)
        profile.coupled_rooms = data.get("coupled_rooms", [])
        profile.coupling_factors = data.get("coupling_factors", {})
        if data.get("version", 1) < PROFILE_VERSION:
            # Learned by the old estimators (thermal mass saturated near 1,
            # efficiency measured sensor noise, the smoothing factor moved the
            # wrong way, the balancing bias ignored direction): start these
            # again. Coupling uses the same estimator and is kept.
            profile.thermal_mass = 0.5
            profile.cooling_efficiency = 0.6
            profile.optimal_smoothing_factor = 0.7
            profile.optimal_smoothing_threshold = 10
            profile.avg_convergence_time_seconds = None
            profile.balancing_bias = 0.0
            profile.relative_heat_gain_rate = 1.0
            profile.relative_cool_rate = 1.0
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

        exists = await self.hass.async_add_executor_job(storage_file.exists)
        if not exists:
            _LOGGER.debug("No existing learning profiles found")
        else:
            try:
                raw_data = await self.hass.async_add_executor_job(storage_file.read_text)
                data = json.loads(raw_data)
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
            # Ensure directory exists (non-blocking)
            await self.hass.async_add_executor_job(
                lambda: storage_file.parent.mkdir(parents=True, exist_ok=True)
            )

            # Convert profiles to dict
            data = {
                room_name: profile.to_dict()
                for room_name, profile in self.profiles.items()
            }

            # Atomic write: temp file + rename so a crash mid-write keeps the
            # previous valid file rather than half-writing the destination.
            data_str = json.dumps(data, indent=2)

            def _atomic_write():
                tmp_file = storage_file.with_suffix(storage_file.suffix + ".tmp")
                tmp_file.write_text(data_str)
                tmp_file.replace(storage_file)

            await self.hass.async_add_executor_job(_atomic_write)
            _LOGGER.debug("Saved %d learning profiles", len(self.profiles))
        except Exception as e:
            _LOGGER.error("Failed to save learning profiles: %s", e)

        # Save tracker data points
        await self.tracker.async_save_data_points()

    async def async_update_profiles(self) -> list[str]:
        """Update learning profiles from tracker data.

        Returns list of room names that were updated.
        """
        # Profile analysis is CPU-heavy (coupling detection alone is
        # O(rooms² × windows)); run it in the executor so the hourly update
        # can never stall Home Assistant's event loop.
        updated_rooms, any_profile_modified = await self.hass.async_add_executor_job(
            self._update_profiles_sync
        )

        # Save profiles only when something meaningfully changed, to avoid
        # rewriting identical JSON to flash storage every hour.
        if any_profile_modified:
            await self.async_save_profiles()

        return updated_rooms

    def _update_profiles_sync(self) -> tuple[list[str], bool]:
        """Synchronous profile update pass (runs in the executor)."""
        updated_rooms = []
        any_profile_modified = False

        for room_name in list(self.tracker._data_points.keys()):
            if room_name not in self.profiles:
                self.profiles[room_name] = LearningProfile(room_name)
                any_profile_modified = True

            profile = self.profiles[room_name]
            old_confidence = profile.confidence
            # update_from_tracker always refreshes confidence; it returns True
            # only if thermal characteristics were successfully calculated
            if profile.update_from_tracker(self.tracker, self.max_adjustment_per_update):
                updated_rooms.append(room_name)
                any_profile_modified = True
            elif abs(profile.confidence - old_confidence) > 0.005:
                # Confidence moved meaningfully even without a full update
                any_profile_modified = True

        return updated_rooms, any_profile_modified

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
