"""Battery-aware mode: vendor-agnostic home-battery monitoring, learning and levels.

Works with any home battery that exposes a state-of-charge (%) sensor in Home
Assistant; a battery power sensor is optional. Nothing here controls the
battery — it only decides how hard the aircon may work while the house runs
on it.

* ``BatteryLearner`` (pure Python, persisted as JSON) learns the household's
  battery habits from the SOC history: when the battery starts draining in the
  evening, when solar takes over again in the morning, how fast it drains each
  hour of the night (separately for cooling and heating seasons), how each
  night ended — and adapts a safety buffer from those outcomes.
* Each cycle it projects the SOC at the next solar recovery and picks a saving
  level (with hysteresis and dwell times):

    0 normal      — not running on the battery (or the mode is off)
    1 efficient   — on battery: no-comfort-cost levers only (the compressor
                    rests once every room is satisfied — fan-only while
                    cooling, off while heating — and a gentler setpoint).
                    Dehumidifying is never touched at any level.
    2 saving      — projected short: + main fan capped at medium,
                    comfort relaxed (non-priority rooms first)
    3 max saving  — well short / near reserve: + main fan low, comfort relaxed
                    up to the configured limit

* ``BatteryManager`` adds Home Assistant persistence around the learner.
"""
from __future__ import annotations

import json
import logging
import math
import statistics
import uuid
from dataclasses import dataclass, field, asdict
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

_LOGGER = logging.getLogger(__name__)

LEVEL_NAMES = {0: "normal", 1: "efficient", 2: "saving", 3: "max_saving"}

# Data handling
SAMPLE_SPACING_S = 60          # keep at most one SOC sample per minute
SAMPLE_WINDOW_S = 4 * 3600     # keep 4 hours of samples
SLOPE_WINDOW_S = 45 * 60       # SOC slope over the last 45 minutes
SLOPE_MIN_SPAN_S = 20 * 60
POWER_WINDOW_S = 10 * 60
STALE_SOC_S = 2 * 3600         # an SOC older than this is "unavailable"
POWER_FLOW_THRESHOLD_W = 80.0  # |power| above this = charging/discharging
SLOPE_FLOW_THRESHOLD = 0.5     # %/h; integer-step SOC sensors move slowly

# Event detection
NIGHT_START_EARLIEST_HOUR = 12      # evening discharge starts are tracked from noon
NIGHT_START_SUSTAIN_S = 20 * 60
RECOVERY_LATEST_HOUR = 14           # a night with no recovery by 14:00 is closed
RECOVERY_SUSTAIN_S = 10 * 60
DEFAULT_SUNRISE = (6, 30)           # when sun.sun is unavailable
NIGHT_WINDOW_START_HOUR = 15        # projections run from mid-afternoon

# Levels
ESCALATE_DWELL_S = 10 * 60
DEESCALATE_DWELL_S = 45 * 60
OFF_BATTERY_DWELL_S = 10 * 60
NIGHT_OFF_BATTERY_DWELL_S = 30 * 60 # around sunset the AC's own load tips charge/discharge
DEESCALATE_MARGIN = 10.0            # % above the threshold that raised the level
OBSERVED_RATE_WINDOW_S = 90 * 60
ASSUME_ON_BATTERY_HOUR = 18         # until learned: evening drain assumed from 18:00
SEVERE_SHORTFALL = 10.0             # % below threshold -> max saving
NEAR_RESERVE = 3.0                  # % above reserve -> max saving
DEFAULT_BUFFER = 5.0
MAX_BUFFER = 25.0

HISTORY_DAYS = 21
PROFILE_ALPHA = 0.3


@dataclass
class BatteryReading:
    """Raw sensor values for one cycle."""

    soc: float | None = None             # %, 0-100
    soc_age_s: float | None = None       # seconds since the SOC sensor last reported
    power_w: float | None = None         # battery power in W, sign as the sensor reports it


@dataclass
class BatteryDecision:
    """What battery-aware mode wants this cycle (consumed by the optimizer)."""

    level: int = 0
    status: str = "off"                  # off / unavailable / normal / efficient / saving / max_saving
    reason: str = ""
    soc: float | None = None
    soc_age_minutes: float | None = None
    flow: str = "unknown"                # discharging / charging / idle / unknown
    on_battery: bool = False
    drain_rate_pct_per_hour: float | None = None
    projected_soc: float | None = None
    target_soc: float | None = None      # reserve + learned buffer
    solar_recovery: str | None = None    # ISO local time
    hours_to_recovery: float | None = None
    recovery_source: str | None = None   # learned / sunrise
    # Levers for the optimizer
    main_fan_cap: str | None = None
    relax_priority: float = 0.0
    relax_other: float = 0.0
    zone_focus: bool = False

    def relax_global(self, priority_configured: bool) -> float:
        """Relaxation of the rooms that drive AC-level decisions."""
        return self.relax_priority if (priority_configured and self.zone_focus) else self.relax_other

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)


def levers_for_level(level: int, comfort_limit: float, priority_configured: bool) -> dict[str, Any]:
    """Map a level to optimizer levers (level 1 levers live in the optimizer's
    efficient operation, enabled whenever level >= 1)."""
    levers = {"main_fan_cap": None, "relax_priority": 0.0, "relax_other": 0.0, "zone_focus": False}
    if level >= 2:
        levers["main_fan_cap"] = "medium" if level == 2 else "low"
        if priority_configured:
            levers["zone_focus"] = True
            levers["relax_other"] = comfort_limit
            levers["relax_priority"] = 0.0 if level == 2 else round(comfort_limit / 2.0, 2)
        else:
            levers["relax_other"] = round(comfort_limit / 2.0, 2) if level == 2 else comfort_limit
            levers["relax_priority"] = levers["relax_other"]
    return levers


def _minute_of_day(dt: datetime) -> int:
    return dt.hour * 60 + dt.minute


def _median_minute(entries: list[dict[str, Any]], today: datetime, days: int = 14) -> int | None:
    """Median minute-of-day of entries recorded in the last ``days`` days."""
    cutoff = (today - timedelta(days=days)).date().isoformat()
    minutes = [e["minute"] for e in entries if e.get("date", "") >= cutoff and e.get("minute") is not None]
    if len(minutes) < 3:
        return None
    return int(statistics.median(minutes))


class BatteryLearner:
    """Learns battery habits from SOC (and optional power) history."""

    def __init__(self) -> None:
        self.samples: list[list[float | None]] = []      # [ts, soc, discharge_w | None]
        self.power_sign_votes = {"positive_discharging": 0, "positive_charging": 0}
        self._last_vote_ts: float | None = None
        self.flow_since: dict[str, float | None] = {"discharging": None, "charging": None}
        self.night: dict[str, Any] | None = None
        self.recovery_minutes: list[dict[str, Any]] = []
        self.evening_minutes: list[dict[str, Any]] = []
        self.drain_profile: dict[str, dict[str, float]] = {"cool": {}, "heat": {}}
        self.hour_bucket: dict[str, Any] | None = None
        self.nights: list[dict[str, Any]] = []
        self.buffer_pct = DEFAULT_BUFFER
        # Strategy in use (transient; set each cycle by decide())
        self.strategy = "balanced"
        # Level controller state
        self.level = 0
        self.level_since: float | None = None
        self.pending_level: int | None = None
        self.pending_since: float | None = None
        self.dirty = False

    # ------------------------------------------------------------------ data
    def _effective_sign(self, configured: str) -> str | None:
        if configured in ("positive_discharging", "positive_charging"):
            return configured
        votes = self.power_sign_votes
        total = votes["positive_discharging"] + votes["positive_charging"]
        if total < 12:
            return None
        winner = max(votes, key=votes.get)
        return winner if votes[winner] / total >= 0.8 else None

    def _discharge_w(self, power_w: float | None, configured_sign: str) -> float | None:
        """Battery power normalised to + = discharging (None if unknown)."""
        if power_w is None:
            return None
        sign = self._effective_sign(configured_sign)
        if sign is None:
            return None
        return power_w if sign == "positive_discharging" else -power_w

    def add_sample(self, now_ts: float, soc: float, power_w: float | None, configured_sign: str) -> None:
        """Record a reading (at most one per minute) and learn the power sign."""
        self._vote_power_sign(now_ts, power_w)
        discharge = self._discharge_w(power_w, configured_sign)
        if self.samples and now_ts - self.samples[-1][0] < SAMPLE_SPACING_S:
            # Keep the newest SOC within the minute so slopes stay current
            self.samples[-1] = [self.samples[-1][0], soc, discharge]
            return
        self.samples.append([now_ts, soc, discharge])
        cutoff = now_ts - SAMPLE_WINDOW_S
        while self.samples and self.samples[0][0] < cutoff:
            self.samples.pop(0)

    def _vote_power_sign(self, now_ts: float, power_w: float | None) -> None:
        """Learn the sensor's sign convention by comparing power with SOC slope."""
        if power_w is None or abs(power_w) < 100:
            return
        if self._last_vote_ts is not None and now_ts - self._last_vote_ts < 600:
            return
        slope = self.soc_slope(now_ts, window_s=30 * 60)
        if slope is None or abs(slope) < 1.0:
            return
        draining = slope < 0
        positive = power_w > 0
        key = "positive_discharging" if draining == positive else "positive_charging"
        self.power_sign_votes[key] += 1
        self._last_vote_ts = now_ts
        self.dirty = True

    def soc_slope(self, now_ts: float, window_s: float = SLOPE_WINDOW_S) -> float | None:
        """SOC trend in %/hour (least squares) over the window, or None."""
        pts = [(t, s) for t, s, _ in self.samples if t >= now_ts - window_s and s is not None]
        if len(pts) < 3 or pts[-1][0] - pts[0][0] < SLOPE_MIN_SPAN_S:
            return None
        t_mean = sum(t for t, _ in pts) / len(pts)
        s_mean = sum(s for _, s in pts) / len(pts)
        denom = sum((t - t_mean) ** 2 for t, _ in pts)
        if denom <= 0:
            return None
        slope_per_s = sum((t - t_mean) * (s - s_mean) for t, s in pts) / denom
        return slope_per_s * 3600.0

    def mean_discharge_w(self, now_ts: float) -> float | None:
        vals = [d for t, _, d in self.samples if t >= now_ts - POWER_WINDOW_S and d is not None]
        return sum(vals) / len(vals) if vals else None

    def flow_state(self, now_ts: float) -> str:
        """discharging / charging / idle / unknown."""
        power = self.mean_discharge_w(now_ts)
        if power is not None:
            if power >= POWER_FLOW_THRESHOLD_W:
                return "discharging"
            if power <= -POWER_FLOW_THRESHOLD_W:
                return "charging"
            return "idle"
        slope = self.soc_slope(now_ts)
        if slope is None:
            return "unknown"
        if slope <= -SLOPE_FLOW_THRESHOLD:
            return "discharging"
        if slope >= SLOPE_FLOW_THRESHOLD:
            return "charging"
        return "idle"

    def observed_drain_rate(self, now_ts: float) -> float | None:
        """Current drain in %/hour (positive while discharging)."""
        slope = self.soc_slope(now_ts, window_s=OBSERVED_RATE_WINDOW_S)
        if slope is None:
            return None
        return max(0.0, -slope)

    # ---------------------------------------------------------------- events
    def observe(
        self,
        now_ts: float,
        local_now: datetime,
        soc: float,
        flow: str,
        mode: str,
        reserve_pct: float,
        sunrise_local: datetime | None,
    ) -> None:
        """Track evening discharge start, morning recovery and hourly drain."""
        for name in ("discharging", "charging"):
            if flow == name:
                if self.flow_since[name] is None:
                    self.flow_since[name] = now_ts
            else:
                self.flow_since[name] = None

        self._update_hour_bucket(now_ts, local_now, soc, flow, mode)

        if self.night is None:
            since = self.flow_since["discharging"]
            if (
                since is not None
                and now_ts - since >= NIGHT_START_SUSTAIN_S
                and local_now.hour >= NIGHT_START_EARLIEST_HOUR
            ):
                start_local = local_now - timedelta(seconds=now_ts - since)
                self.night = {
                    "date": start_local.date().isoformat(),
                    "start_ts": since,
                    "start_minute": _minute_of_day(start_local),
                    "start_soc": soc,
                    "min_soc": soc,
                    "max_level": self.level,
                }
                self.evening_minutes.append({"date": start_local.date().isoformat(), "minute": _minute_of_day(start_local)})
                self.evening_minutes = self.evening_minutes[-HISTORY_DAYS:]
                self.dirty = True
            return

        night = self.night
        night["min_soc"] = min(night["min_soc"], soc)
        night["max_level"] = max(night.get("max_level", 0), self.level)

        # A night only ends on a later day than it started (solar can't take
        # over again the same evening; an afternoon start is a cloudy day)
        if local_now.date().isoformat() <= night["date"]:
            return
        earliest = 3 * 60
        if sunrise_local is not None:
            # Before sunrise a rising SOC is grid charging, not solar
            earliest = max(earliest, _minute_of_day(sunrise_local) - 60)
        minute = _minute_of_day(local_now)
        recovered = False
        if earliest <= minute < RECOVERY_LATEST_HOUR * 60:
            since = self.flow_since["charging"]
            if since is not None and now_ts - since >= RECOVERY_SUSTAIN_S:
                recovered = True
                recovery_local = local_now - timedelta(seconds=now_ts - since)
            elif soc >= night["min_soc"] + 2:
                recovered = True
                recovery_local = local_now
        if recovered:
            self._close_night(recovery_local, reserve_pct)
        elif minute >= RECOVERY_LATEST_HOUR * 60:
            self._close_night(None, reserve_pct)

    def _close_night(self, recovery_local: datetime | None, reserve_pct: float) -> None:
        night = self.night or {}
        hit_reserve = night.get("min_soc", 100) <= reserve_pct + 1
        if recovery_local is not None:
            self.recovery_minutes.append({"date": recovery_local.date().isoformat(), "minute": _minute_of_day(recovery_local)})
            self.recovery_minutes = self.recovery_minutes[-HISTORY_DAYS:]
        # Adapt the safety buffer from how the night ended. Raise it only when
        # saving earlier could have helped (the night never reached max
        # saving); a night the battery could not cover even at max saving
        # says nothing about the buffer.
        # (The "efficient" strategy never escalates, so it doesn't adapt it.)
        if self.strategy != "efficient":
            if hit_reserve and night.get("max_level", 0) < 3:
                self.buffer_pct = min(MAX_BUFFER, self.buffer_pct + 3.0)
            elif not hit_reserve and night.get("min_soc", 0) >= reserve_pct + 20:
                self.buffer_pct = max(0.0, self.buffer_pct - 1.0)
        self.nights.append({
            "date": night.get("date"),
            "start_minute": night.get("start_minute"),
            "start_soc": night.get("start_soc"),
            "min_soc": night.get("min_soc"),
            "recovery_minute": _minute_of_day(recovery_local) if recovery_local else None,
            "hit_reserve": hit_reserve,
            "max_level": night.get("max_level", 0),
        })
        self.nights = self.nights[-30:]
        self.night = None
        self.dirty = True
        _LOGGER.info(
            "Battery night closed: min SOC %.0f%%, recovery %s, hit reserve %s, buffer now %.0f%%",
            night.get("min_soc", float("nan")),
            recovery_local.strftime("%H:%M") if recovery_local else "none",
            hit_reserve, self.buffer_pct,
        )

    def _update_hour_bucket(self, now_ts: float, local_now: datetime, soc: float, flow: str, mode: str) -> None:
        key = local_now.strftime("%Y-%m-%dT%H")
        bucket = self.hour_bucket
        if bucket is None or bucket.get("key") != key:
            if bucket is not None:
                self._finish_hour_bucket(bucket, now_ts, soc)
            self.hour_bucket = {
                "key": key, "hour": local_now.hour, "start_ts": now_ts, "start_soc": soc,
                "mode": mode if mode in ("cool", "heat") else "cool", "samples": 0, "discharging": 0,
            }
            bucket = self.hour_bucket
        bucket["samples"] += 1
        if flow == "discharging":
            bucket["discharging"] += 1

    def _finish_hour_bucket(self, bucket: dict[str, Any], now_ts: float, end_soc: float) -> None:
        duration_h = (now_ts - bucket["start_ts"]) / 3600.0
        # Partial hours and hours spanning downtime don't give a clean rate
        if duration_h < 0.75 or duration_h > 1.5 or bucket["samples"] == 0:
            return
        if bucket["discharging"] / bucket["samples"] < 0.75:
            return
        rate = (bucket["start_soc"] - end_soc) / duration_h
        if rate < 0:
            return
        rate = min(40.0, rate)
        profile = self.drain_profile.setdefault(bucket["mode"], {})
        hour = str(bucket["hour"])
        old = profile.get(hour)
        profile[hour] = round(rate if old is None else (1 - PROFILE_ALPHA) * old + PROFILE_ALPHA * rate, 2)
        self.dirty = True

    # ------------------------------------------------------------ projection
    def expected_recovery(
        self, local_now: datetime, sunrise_local: datetime | None, offset_hours: float
    ) -> tuple[datetime, str]:
        """Next time solar is expected to take over (learned, else sunrise + offset)."""
        learned = _median_minute(self.recovery_minutes, local_now)
        if learned is not None:
            candidate = local_now.replace(hour=learned // 60, minute=learned % 60, second=0, microsecond=0)
            source = "learned"
        else:
            if sunrise_local is not None:
                base = sunrise_local
                # sun.sun's next_rising is tomorrow once today's sunrise passed
                if base - local_now > timedelta(hours=20):
                    base = base - timedelta(days=1)
            else:
                base = local_now.replace(hour=DEFAULT_SUNRISE[0], minute=DEFAULT_SUNRISE[1], second=0, microsecond=0)
            candidate = base + timedelta(hours=offset_hours)
            source = "sunrise"
        if candidate <= local_now:
            candidate = candidate + timedelta(days=1)
        return candidate, source

    def recovery_for_projection(
        self, local_now: datetime, sunrise_local: datetime | None, offset_hours: float
    ) -> tuple[datetime, str]:
        """Expected recovery, treating an overdue one as imminent.

        If the night is still open after today's expected recovery time
        (cloudy morning), the next "expected" time would be tomorrow — a
        24-hour projection that panics into max saving. Assume solar is about
        to take over instead.
        """
        recovery, source = self.expected_recovery(local_now, sunrise_local, offset_hours)
        if self.night is not None and local_now.date().isoformat() > self.night["date"]:
            today = recovery - timedelta(days=1)
            if today.date() == local_now.date() and today <= local_now:
                return local_now + timedelta(hours=1), "overdue"
        return recovery, source

    def assume_on_battery(self, local_now: datetime) -> bool:
        """Before the trend is known: is this when the battery normally drains?"""
        start = _median_minute(self.evening_minutes, local_now)
        start = ASSUME_ON_BATTERY_HOUR * 60 if start is None else start
        minute = _minute_of_day(local_now)
        return minute >= start or minute < 4 * 60

    def in_night_window(self, local_now: datetime, recovery: datetime) -> bool:
        """Evening/night until the expected recovery (or an open night)."""
        if self.night is not None:
            return True
        if local_now.hour >= NIGHT_WINDOW_START_HOUR:
            return True
        return (recovery - local_now) < timedelta(hours=12) and recovery.date() == local_now.date()

    def project_soc(
        self, local_now: datetime, soc: float, mode: str, recovery: datetime, observed_rate: float | None
    ) -> tuple[float | None, float | None]:
        """Projected SOC at recovery and the drain rate used now (%/h)."""
        profile = self.drain_profile.get(mode if mode in ("cool", "heat") else "cool", {})
        learned_now = profile.get(str(local_now.hour))
        factor = 1.0
        if observed_rate is not None and learned_now:
            factor = max(0.5, min(2.0, observed_rate / learned_now))
        total = 0.0
        t = local_now
        rate_now = None
        while t < recovery:
            next_hour = (t + timedelta(hours=1)).replace(minute=0, second=0, microsecond=0)
            step_end = min(next_hour, recovery)
            hours = (step_end - t).total_seconds() / 3600.0
            learned = profile.get(str(t.hour))
            rate = learned * factor if learned is not None else observed_rate
            if rate is None:
                return None, None
            if rate_now is None:
                rate_now = rate
            total += rate * hours
            t = step_end
        return soc - total, rate_now

    # ---------------------------------------------------------------- levels
    def choose_level(
        self,
        now_ts: float,
        target_level: int,
        immediate: bool = False,
        night: bool = False,
    ) -> int:
        """Apply dwell-time hysteresis to the requested level."""
        if self.level_since is None:
            self.level_since = now_ts
        if target_level == self.level:
            self.pending_level = None
            self.pending_since = None
            return self.level
        if immediate:
            self._set_level(target_level, now_ts)
            return self.level
        if self.pending_level != target_level:
            self.pending_level = target_level
            self.pending_since = now_ts
        if target_level > self.level:
            dwell = ESCALATE_DWELL_S
        elif target_level == 0:
            dwell = NIGHT_OFF_BATTERY_DWELL_S if night else OFF_BATTERY_DWELL_S
        else:
            dwell = DEESCALATE_DWELL_S
        if now_ts - (self.pending_since or now_ts) >= dwell:
            self._set_level(target_level, now_ts)
        return self.level

    def _set_level(self, level: int, now_ts: float) -> None:
        if level != self.level:
            _LOGGER.info("Battery-aware mode: %s -> %s", LEVEL_NAMES.get(self.level), LEVEL_NAMES.get(level))
            self.dirty = True
        self.level = level
        self.level_since = now_ts
        self.pending_level = None
        self.pending_since = None
        if self.night is not None:
            self.night["max_level"] = max(self.night.get("max_level", 0), level)

    # ------------------------------------------------------------ persistence
    def to_dict(self) -> dict[str, Any]:
        return {
            "version": 1,
            "samples": self.samples[-240:],
            "power_sign_votes": self.power_sign_votes,
            "night": self.night,
            "recovery_minutes": self.recovery_minutes,
            "evening_minutes": self.evening_minutes,
            "drain_profile": self.drain_profile,
            "hour_bucket": self.hour_bucket,
            "nights": self.nights,
            "buffer_pct": self.buffer_pct,
            "level": self.level,
            "level_since": self.level_since,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> BatteryLearner:
        learner = cls()
        if not isinstance(data, dict):
            return learner
        learner.samples = [list(s) for s in data.get("samples", []) if isinstance(s, (list, tuple)) and len(s) == 3]
        votes = data.get("power_sign_votes") or {}
        learner.power_sign_votes = {
            "positive_discharging": int(votes.get("positive_discharging", 0)),
            "positive_charging": int(votes.get("positive_charging", 0)),
        }
        learner.night = data.get("night")
        learner.recovery_minutes = list(data.get("recovery_minutes", []))[-HISTORY_DAYS:]
        learner.evening_minutes = list(data.get("evening_minutes", []))[-HISTORY_DAYS:]
        profile = data.get("drain_profile") or {}
        learner.drain_profile = {
            "cool": dict(profile.get("cool", {})),
            "heat": dict(profile.get("heat", {})),
        }
        learner.hour_bucket = data.get("hour_bucket")
        learner.nights = list(data.get("nights", []))[-30:]
        learner.buffer_pct = float(data.get("buffer_pct", DEFAULT_BUFFER))
        learner.level = int(data.get("level", 0))
        learner.level_since = data.get("level_since")
        return learner

    def summary(self, local_now: datetime) -> dict[str, Any]:
        """Learned habits, for sensors and diagnostics."""
        def fmt(minute: int | None) -> str | None:
            return None if minute is None else f"{minute // 60:02d}:{minute % 60:02d}"

        recent = self.nights[-14:]
        return {
            "nights_learned": len(self.nights),
            "typical_evening_start": fmt(_median_minute(self.evening_minutes, local_now)),
            "typical_solar_recovery": fmt(_median_minute(self.recovery_minutes, local_now)),
            "nights_reserve_hit_last_14": sum(1 for n in recent if n.get("hit_reserve")),
            "last_night_min_soc": recent[-1].get("min_soc") if recent else None,
            "safety_buffer_pct": round(self.buffer_pct, 1),
            "power_sign": self._effective_sign("auto"),
            "drain_profile_pct_per_hour": self.drain_profile,
        }


def decide(
    learner: BatteryLearner,
    *,
    now_ts: float,
    local_now: datetime,
    reading: BatteryReading,
    enabled: bool,
    strategy: str,
    reserve_pct: float,
    comfort_limit: float,
    priority_configured: bool,
    mode: str,
    power_sign: str,
    sunrise_local: datetime | None,
    recovery_offset_hours: float,
    safety_override: str | None = None,
) -> BatteryDecision:
    """Update the learner with this cycle's reading and decide the level.

    ``safety_override`` names a reason the mode must stand down this cycle
    (a critical-room emergency, boost/party) — learning continues regardless.
    """
    decision = BatteryDecision(
        soc=reading.soc,
        soc_age_minutes=None if reading.soc_age_s is None else round(reading.soc_age_s / 60.0, 1),
        target_soc=round(reserve_pct + learner.buffer_pct, 1),
    )

    learner.strategy = strategy
    soc_ok = reading.soc is not None and (reading.soc_age_s is None or reading.soc_age_s <= STALE_SOC_S)
    if soc_ok:
        learner.add_sample(now_ts, reading.soc, reading.power_w, power_sign)
        flow = learner.flow_state(now_ts)
        learner.observe(now_ts, local_now, reading.soc, flow, mode, reserve_pct, sunrise_local)
    else:
        flow = "unknown"
    decision.flow = flow

    recovery, source = learner.recovery_for_projection(local_now, sunrise_local, recovery_offset_hours)
    decision.solar_recovery = recovery.isoformat()
    decision.recovery_source = source
    decision.hours_to_recovery = round((recovery - local_now).total_seconds() / 3600.0, 2)

    if not enabled:
        decision.status = "off"
        decision.reason = "battery-aware mode is off (still learning)" if soc_ok else "battery-aware mode is off"
        learner.choose_level(now_ts, 0, immediate=True)
        return decision
    if not soc_ok:
        decision.status = "unavailable"
        decision.reason = "battery state of charge unavailable or stale - normal operation"
        learner.choose_level(now_ts, 0, immediate=True)
        return decision
    if safety_override:
        decision.status = "normal"
        decision.reason = safety_override
        learner.choose_level(now_ts, 0, immediate=True)
        return decision

    soc = reading.soc
    in_night = learner.in_night_window(local_now, recovery)
    on_battery = flow == "discharging"
    assumed = False
    if flow == "unknown" and in_night and soc < 98 and learner.assume_on_battery(local_now):
        # Not enough history yet (e.g. just after a restart): assume the
        # evening/night drain until the slope is known
        on_battery = True
        assumed = True
    decision.on_battery = on_battery

    observed = learner.observed_drain_rate(now_ts) if on_battery else None
    reasons = []
    if not on_battery:
        target = 0
        reasons.append("battery not discharging" if flow != "unknown" else "battery flow unknown")
    else:
        base = {"efficient": 1, "balanced": 1, "max_saving": 2}.get(strategy, 1)
        target = base
        reasons.append("running on battery" + (" (assumed until the trend is known)" if assumed else ""))
        if in_night:
            projected, rate = learner.project_soc(local_now, soc, mode, recovery, observed)
            decision.projected_soc = None if projected is None else round(projected, 1)
            decision.drain_rate_pct_per_hour = None if rate is None else round(rate, 2)
            if projected is not None and strategy != "efficient":
                margin = projected - (reserve_pct + learner.buffer_pct)
                if margin < 0:
                    reasons.append(
                        f"projected {projected:.0f}% at solar recovery, below {reserve_pct + learner.buffer_pct:.0f}%"
                    )
                # Level -> margin below which it engages. A raised level is
                # held until the margin clears its threshold by
                # DEESCALATE_MARGIN, so the level doesn't flap on noise.
                thresholds = {2: 0.0, 3: -SEVERE_SHORTFALL} if strategy == "balanced" else {3: 0.0}
                for lvl, threshold in thresholds.items():
                    if margin < threshold or (learner.level >= lvl and margin < threshold + DEESCALATE_MARGIN):
                        target = max(target, lvl)
        elif observed is not None:
            decision.drain_rate_pct_per_hour = round(observed, 2)
        if strategy != "efficient" and soc <= reserve_pct + NEAR_RESERVE:
            target = 3
            reasons.append("battery near its reserve")

    # The free levers (level 1) start at once; comfort-relaxing levels wait
    # out the escalation dwell from there.
    if learner.level == 0 and target >= 1:
        learner.choose_level(now_ts, 1, immediate=True)
    level = learner.choose_level(now_ts, target, night=in_night)
    decision.level = level
    decision.status = LEVEL_NAMES[level]
    if level != target:
        reasons.append(f"moving towards {LEVEL_NAMES[target]} (dwell)")
    decision.reason = "; ".join(reasons)
    for key, value in levers_for_level(level, comfort_limit, priority_configured).items():
        setattr(decision, key, value)
    return decision


class BatteryManager:
    """Home Assistant persistence around a BatteryLearner."""

    SAVE_INTERVAL_S = 15 * 60

    def __init__(self, hass, config_entry_id: str, storage_path: Path) -> None:
        self.hass = hass
        self.file = storage_path / f"smart_aircon_manager.{config_entry_id}.battery.json"
        self.learner = BatteryLearner()
        self._last_save: float | None = None

    async def async_load(self) -> None:
        def _load():
            if not self.file.exists():
                return None
            return json.loads(self.file.read_text())

        try:
            data = await self.hass.async_add_executor_job(_load)
        except Exception as err:  # corrupt file: start fresh
            _LOGGER.warning("Could not load battery learning data: %s", err)
            data = None
        if data:
            self.learner = BatteryLearner.from_dict(data)
            _LOGGER.info("Loaded battery learning data (%d nights)", len(self.learner.nights))

    async def async_save(self) -> None:
        data = self.learner.to_dict()
        target = self.file

        def _save():
            target.parent.mkdir(parents=True, exist_ok=True)
            tmp = target.with_suffix(f"{target.suffix}.{uuid.uuid4().hex}.tmp")
            try:
                tmp.write_text(json.dumps(data))
                tmp.replace(target)
            finally:
                if tmp.exists():
                    tmp.unlink()

        try:
            await self.hass.async_add_executor_job(_save)
            self.learner.dirty = False
        except Exception as err:
            _LOGGER.warning("Could not save battery learning data: %s", err)

    async def async_save_if_due(self, now_ts: float) -> None:
        if not self.learner.dirty:
            return
        if self._last_save is not None and now_ts - self._last_save < self.SAVE_INTERVAL_S:
            return
        self._last_save = now_ts
        await self.async_save()

    async def async_reset(self) -> None:
        self.learner = BatteryLearner()
        await self.async_save()


def read_power_w(state: Any) -> float | None:
    """Parse a power sensor state to watts (handles W and kW)."""
    if state is None or state.state in (None, "", "unknown", "unavailable"):
        return None
    try:
        value = float(state.state)
    except (TypeError, ValueError):
        return None
    if math.isnan(value):
        return None
    unit = str((getattr(state, "attributes", {}) or {}).get("unit_of_measurement") or "W").strip()
    if unit.lower() == "kw":
        value *= 1000.0
    elif unit.lower() == "mw":
        value *= 1_000_000.0
    return value


def read_soc(state: Any, now_utc: datetime | None) -> tuple[float | None, float | None]:
    """Parse an SOC sensor state: (percent, seconds since it last reported)."""
    if state is None or state.state in (None, "", "unknown", "unavailable"):
        return None, None
    try:
        value = float(state.state)
    except (TypeError, ValueError):
        return None, None
    if not 0.0 <= value <= 100.0:
        return None, None
    age = None
    reported = getattr(state, "last_reported", None) or getattr(state, "last_updated", None)
    if isinstance(reported, datetime) and now_utc is not None:
        try:
            age = max(0.0, (now_utc - reported).total_seconds())
        except TypeError:
            age = None
    return value, age
