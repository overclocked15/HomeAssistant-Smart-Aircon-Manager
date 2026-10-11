"""Tests for battery-aware mode and efficient operation (v3.1.0)."""
from __future__ import annotations

import asyncio
import sys
import tempfile
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))
sys.path.insert(0, str(Path(__file__).parent))

from custom_components.smart_aircon_manager import battery as bat  # noqa: E402
from test_v302_fixes import (  # noqa: E402
    FakeState,
    hvac_commands,
    make_cycle_optimizer,
    run_cycle,
    set_room_temps,
)

TZ = timezone(timedelta(hours=10))
DAY = datetime(2026, 1, 10, tzinfo=TZ)


def feed(learner, start, minutes, soc_at, step_min=1, power_at=None, sign="auto", mode="cool",
         reserve=10.0, sunrise=None):
    """Feed a synthetic trace: soc_at(minute) -> SOC, power_at(minute) -> W."""
    flow = None
    for m in range(0, minutes, step_min):
        local = start + timedelta(minutes=m)
        ts = local.timestamp()
        soc = soc_at(m)
        learner.add_sample(ts, soc, power_at(m) if power_at else None, sign)
        flow = learner.flow_state(ts)
        learner.observe(ts, local, soc, flow, mode, reserve, sunrise)
    return flow


class TestFlowAndSign:
    def test_flow_from_soc_slope(self):
        learner = bat.BatteryLearner()
        assert feed(learner, DAY.replace(hour=20), 60, lambda m: 80 - m * 0.05) == "discharging"
        learner = bat.BatteryLearner()
        assert feed(learner, DAY.replace(hour=10), 60, lambda m: 40 + m * 0.05) == "charging"
        learner = bat.BatteryLearner()
        assert feed(learner, DAY.replace(hour=12), 60, lambda m: 100.0) == "idle"
        assert bat.BatteryLearner().flow_state(DAY.timestamp()) == "unknown"

    def test_power_sign_learned_and_used(self):
        learner = bat.BatteryLearner()
        # Sensor reports negative while discharging
        feed(learner, DAY.replace(hour=18), 300, lambda m: 90 - m * 0.05, power_at=lambda m: -1500.0)
        assert learner._effective_sign("auto") == "positive_charging"
        end = DAY.replace(hour=18).timestamp() + 299 * 60
        assert learner.mean_discharge_w(end) == pytest.approx(1500.0)
        assert learner.flow_state(end) == "discharging"

    def test_configured_sign_used_immediately(self):
        learner = bat.BatteryLearner()
        learner.add_sample(DAY.timestamp(), 80, 1200.0, "positive_discharging")
        assert learner.mean_discharge_w(DAY.timestamp()) == pytest.approx(1200.0)


class TestNightLearning:
    def test_night_recovery_and_profile_learned(self):
        learner = bat.BatteryLearner()
        start = DAY.replace(hour=17)
        sunrise = (DAY + timedelta(days=1)).replace(hour=6, minute=0)

        def soc_at(m):
            if m < 60:
                return 95.0                                   # solar covers the house until 18:00
            if m < 60 + 13 * 60:
                return float(int(95 - 5 * (m - 60) / 60.0))  # 18:00-07:00 draining 5 %/h
            return float(int(30 + 10 * (m - 60 - 13 * 60) / 60.0))  # solar from 07:00

        feed(learner, start, 16 * 60, soc_at, sunrise=sunrise)
        assert learner.night is None, "night should close at the morning recovery"
        assert len(learner.nights) == 1
        night = learner.nights[0]
        # Whole-percent SOC steps make the drain detectable a few minutes late
        assert 18 * 60 <= night["start_minute"] <= 18 * 60 + 20
        assert 7 * 60 <= night["recovery_minute"] <= 7 * 60 + 20
        assert night["min_soc"] <= 31
        profile = learner.drain_profile["cool"]
        assert profile, "hourly drain profile should be learned"
        assert all(3.0 <= rate <= 7.0 for rate in profile.values())

    def test_no_recovery_same_evening(self):
        """A cloudy-afternoon start must not be closed the same day."""
        learner = bat.BatteryLearner()
        feed(learner, DAY.replace(hour=14, minute=30), 4 * 60, lambda m: float(int(80 - 3 * m / 60.0)))
        assert learner.night is not None
        assert learner.nights == []

    def test_grid_charging_before_sunrise_is_not_recovery(self):
        learner = bat.BatteryLearner()
        sunrise = (DAY + timedelta(days=1)).replace(hour=6, minute=0)

        def soc_at(m):
            if m < 7 * 60:
                return float(int(90 - 5 * m / 60.0))              # 18:00-01:00 draining
            if m < 9 * 60:
                return float(int(55 + 10 * (m - 7 * 60) / 60.0))  # 01:00-03:00 grid charging
            return float(int(75 - 5 * (m - 9 * 60) / 60.0))       # draining again

        feed(learner, DAY.replace(hour=18), 11 * 60, soc_at, sunrise=sunrise)
        assert learner.night is not None
        assert learner.recovery_minutes == []


class TestRecoveryAndProjection:
    def test_sunrise_fallback(self):
        learner = bat.BatteryLearner()
        evening = DAY.replace(hour=21)
        sunrise_tomorrow = (DAY + timedelta(days=1)).replace(hour=6, minute=10)
        rec, source = learner.expected_recovery(evening, sunrise_tomorrow, 2.0)
        assert source == "sunrise" and rec == sunrise_tomorrow + timedelta(hours=2)
        # 07:00, after sunrise: next_rising is tomorrow, recovery is still today 08:10
        morning = (DAY + timedelta(days=1)).replace(hour=7)
        rec, _ = learner.expected_recovery(morning, sunrise_tomorrow + timedelta(days=1), 2.0)
        assert rec == morning.replace(hour=8, minute=10)

    def test_learned_recovery_wins_after_three_nights(self):
        learner = bat.BatteryLearner()
        for i in range(3):
            learner.recovery_minutes.append({"date": (DAY - timedelta(days=i)).date().isoformat(), "minute": 450})
        rec, source = learner.expected_recovery(DAY.replace(hour=22), None, 2.0)
        assert source == "learned" and (rec.hour, rec.minute) == (7, 30)

    def test_overdue_recovery_is_imminent(self):
        learner = bat.BatteryLearner()
        for i in range(3):
            learner.recovery_minutes.append({"date": (DAY - timedelta(days=i)).date().isoformat(), "minute": 420})
        learner.night = {"date": DAY.date().isoformat(), "start_ts": 0, "start_soc": 90, "min_soc": 40}
        late = (DAY + timedelta(days=1)).replace(hour=8, minute=30)
        rec, source = learner.recovery_for_projection(late, None, 2.0)
        assert source == "overdue" and rec == late + timedelta(hours=1)

    def test_projection_uses_profile_scaled_by_tonight(self):
        learner = bat.BatteryLearner()
        learner.drain_profile["cool"] = {str(h): 4.0 for h in range(24)}
        now = DAY.replace(hour=23)
        rec = (DAY + timedelta(days=1)).replace(hour=7)
        projected, rate = learner.project_soc(now, 60.0, "cool", rec, observed_rate=6.0)
        assert rate == pytest.approx(6.0)                 # 4 %/h x factor 1.5
        assert projected == pytest.approx(60.0 - 8 * 6.0)
        projected, _ = learner.project_soc(now, 60.0, "cool", rec, observed_rate=None)
        assert projected == pytest.approx(60.0 - 8 * 4.0)
        assert bat.BatteryLearner().project_soc(now, 60.0, "cool", rec, None) == (None, None)


def decide(learner, local, soc, **kw):
    params = dict(
        now_ts=local.timestamp(), local_now=local, reading=bat.BatteryReading(soc=soc, soc_age_s=0),
        enabled=True, strategy="balanced", reserve_pct=10.0, comfort_limit=2.0, priority_configured=False,
        mode="cool", power_sign="auto", sunrise_local=None, recovery_offset_hours=2.0,
    )
    params.update(kw)
    return bat.decide(learner, **params)


def draining_learner(start, soc0, rate):
    learner = bat.BatteryLearner()
    for m in range(60):
        local = start + timedelta(minutes=m)
        learner.add_sample(local.timestamp(), soc0 - rate * m / 60.0, None, "auto")
    return learner


class TestLevels:
    def test_off_unavailable_stale_and_override(self):
        learner = bat.BatteryLearner()
        evening = DAY.replace(hour=20)
        assert decide(learner, evening, 50.0, enabled=False).status == "off"
        assert decide(learner, evening, None).status == "unavailable"
        stale = decide(learner, evening, 50.0, reading=bat.BatteryReading(soc=50.0, soc_age_s=3 * 3600))
        assert stale.status == "unavailable" and stale.level == 0
        assert decide(learner, evening, 50.0, safety_override="critical-room emergency").level == 0

    def test_on_battery_goes_efficient_immediately(self):
        start = DAY.replace(hour=20)
        learner = draining_learner(start, 90.0, 3.0)
        d = decide(learner, start + timedelta(minutes=60), 87.0)
        assert d.on_battery and d.level == 1 and d.status == "efficient"
        assert d.relax_other == 0.0 and d.main_fan_cap is None

    def test_short_projection_escalates_after_dwell(self):
        start = DAY.replace(hour=20)
        learner = draining_learner(start, 40.0, 6.0)   # ~34% at 21:00, ~11h to recovery
        d = decide(learner, start + timedelta(minutes=60), 34.0)
        assert d.level == 1 and d.projected_soc is not None and d.projected_soc < 15
        for i in range(1, 12):
            local = start + timedelta(minutes=60 + i)
            learner.add_sample(local.timestamp(), 34.0 - 0.1 * i, None, "auto")
            d = decide(learner, local, 34.0 - 0.1 * i)
        assert d.level == 3, d.reason
        assert d.suppress_dry and d.main_fan_cap == "low" and d.relax_other == 2.0

    def test_efficient_strategy_never_relaxes(self):
        start = DAY.replace(hour=20)
        learner = draining_learner(start, 40.0, 6.0)
        for i in range(30):
            local = start + timedelta(minutes=60 + i)
            learner.add_sample(local.timestamp(), 34.0 - 0.1 * i, None, "auto")
            d = decide(learner, local, 34.0 - 0.1 * i, strategy="efficient")
        assert d.level == 1 and d.relax_other == 0.0

    def test_near_reserve_forces_max_saving(self):
        start = DAY.replace(hour=2)
        learner = draining_learner(start, 14.0, 1.0)
        for i in range(12):
            d = decide(learner, start + timedelta(minutes=60 + i), 12.0)
        assert d.level == 3

    def test_levers(self):
        levers = bat.levers_for_level(2, 2.0, priority_configured=True)
        assert levers["zone_focus"] and levers["relax_other"] == 2.0 and levers["relax_priority"] == 0.0
        assert bat.levers_for_level(3, 2.0, priority_configured=True)["relax_priority"] == 1.0
        levers = bat.levers_for_level(2, 2.0, priority_configured=False)
        assert not levers["zone_focus"] and levers["relax_other"] == 1.0
        assert bat.levers_for_level(1, 2.0, False)["relax_other"] == 0.0


class TestBufferAdaptation:
    def _close(self, min_soc, max_level, strategy="balanced"):
        learner = bat.BatteryLearner()
        learner.strategy = strategy
        learner.night = {"date": "2026-01-10", "start_ts": 0, "start_minute": 1080, "start_soc": 90,
                         "min_soc": min_soc, "max_level": max_level}
        learner._close_night(DAY.replace(hour=7), 10.0)
        return learner.buffer_pct

    def test_rises_when_saving_earlier_could_help(self):
        assert self._close(10.5, max_level=1) == bat.DEFAULT_BUFFER + 3

    def test_unchanged_for_unwinnable_night(self):
        assert self._close(10.0, max_level=3) == bat.DEFAULT_BUFFER

    def test_unchanged_for_efficient_strategy(self):
        assert self._close(10.0, max_level=1, strategy="efficient") == bat.DEFAULT_BUFFER

    def test_falls_after_comfortable_night(self):
        assert self._close(45.0, max_level=1) == bat.DEFAULT_BUFFER - 1


class TestPersistenceAndParsing:
    def test_round_trip(self):
        learner = bat.BatteryLearner()
        feed(learner, DAY.replace(hour=19), 120, lambda m: 80 - m * 0.05)
        learner.recovery_minutes.append({"date": "2026-01-09", "minute": 450})
        learner.buffer_pct = 8.0
        restored = bat.BatteryLearner.from_dict(learner.to_dict())
        assert restored.recovery_minutes == learner.recovery_minutes
        assert restored.buffer_pct == 8.0
        assert len(restored.samples) == len(learner.samples)
        assert bat.BatteryLearner.from_dict(None).buffer_pct == bat.DEFAULT_BUFFER

    def test_manager_save_and_load(self):
        hass = MagicMock()

        async def executor(func, *args):
            return func(*args)

        hass.async_add_executor_job = executor
        storage = Path(tempfile.mkdtemp())
        manager = bat.BatteryManager(hass, "entry", storage)
        manager.learner.buffer_pct = 12.0
        asyncio.run(manager.async_save())
        other = bat.BatteryManager(hass, "entry", storage)
        asyncio.run(other.async_load())
        assert other.learner.buffer_pct == 12.0

    def test_read_power_and_soc(self):
        assert bat.read_power_w(FakeState("1.5", {"unit_of_measurement": "kW"})) == pytest.approx(1500.0)
        assert bat.read_power_w(FakeState("-800", {"unit_of_measurement": "W"})) == pytest.approx(-800.0)
        assert bat.read_power_w(FakeState("unavailable")) is None
        assert bat.read_soc(FakeState("57"), None) == (57.0, None)
        assert bat.read_soc(FakeState("157"), None) == (None, None)
        state = FakeState("40")
        state.last_updated = datetime.now(timezone.utc) - timedelta(minutes=30)
        soc, age = bat.read_soc(state, datetime.now(timezone.utc))
        assert soc == 40.0 and 1700 < age < 1900


def with_decision(opt, level, priority=False, limit=2.0):
    """Inject a battery decision (skips sensor reading for the cycle)."""
    decision = bat.BatteryDecision(level=level, **bat.levers_for_level(level, limit, priority))
    opt.enable_battery_mode = True
    opt._update_battery_state = AsyncMock()
    opt._battery_decision = decision
    return decision


class TestOptimizerIntegration:
    def test_saving_relaxes_whole_house_without_priority_rooms(self):
        opt, calls, states = make_cycle_optimizer(rooms=(("Bed", 23.5, None), ("Living", 23.5, None)))
        with_decision(opt, 2)
        result = run_cycle(opt)
        assert result["effective_target_temperature"] == pytest.approx(24.0)
        assert result["comfort_relaxation_sources"] == ["battery"]

    def test_priority_rooms_keep_target_and_drive_decisions(self):
        opt, calls, states = make_cycle_optimizer(
            rooms=(("Bed", 23.4, None), ("Living", 26.5, None)), battery_priority_rooms=["Bed"],
        )
        with_decision(opt, 2, priority=True)
        result = run_cycle(opt)
        assert result["room_states"]["Bed"]["target_temperature"] == pytest.approx(23.0)
        assert result["room_states"]["Living"]["target_temperature"] == pytest.approx(25.0)
        assert result["room_states"]["Living"].get("zone_excluded") is True
        assert result["effective_target_temperature"] == pytest.approx(23.0)

    def test_max_saving_caps_main_fan_and_suppresses_dry(self):
        opt, calls, states = make_cycle_optimizer(
            rooms=(("Bed", 27.0, None), ("Living", 27.0, None)),
            climate_attrs={"fan_mode": "high", "fan_modes": ["low", "medium", "high"]},
        )
        opt.main_fan_entity = "climate.ac"
        with_decision(opt, 3)
        run_cycle(opt)
        assert [c[2]["fan_mode"] for c in calls if c[1] == "set_fan_mode"] == ["low"]
        assert opt._dry_mode_suppressed() is True

    def test_relaxation_in_auto_never_selects_opposite_mode(self):
        opt, calls, states = make_cycle_optimizer(hvac_mode="auto", rooms=(("Bed", 23.6, None), ("Living", 23.6, None)))
        with_decision(opt, 3)
        for _ in range(3):
            run_cycle(opt)
        assert "heat" not in hvac_commands(calls)

    def test_heat_mode_relaxes_downward(self):
        opt, calls, states = make_cycle_optimizer(
            hvac_mode="heat", ac_state="heat", target=21.0, rooms=(("Bed", 20.5, None), ("Living", 20.5, None)),
        )
        with_decision(opt, 3)
        assert run_cycle(opt)["effective_target_temperature"] == pytest.approx(19.0)

    def test_weather_adjustment_skipped_while_saving(self):
        opt, calls, states = make_cycle_optimizer(enable_weather_adjustment=True, outdoor_temp_sensor="sensor.outdoor")
        states["sensor.outdoor"] = FakeState("35", {"unit_of_measurement": "°C"})
        with_decision(opt, 2)
        assert run_cycle(opt)["weather_adjustment"] == 0.0

    def test_mode_disabled_means_no_levers(self):
        opt, calls, states = make_cycle_optimizer()
        with_decision(opt, 3)
        opt.enable_battery_mode = False
        assert opt._efficiency_active() is False
        assert opt._compute_comfort_relaxation({"Bed": {}, "Living": {}})["global"] == 0.0

    def test_emergency_beats_battery_relaxation(self):
        opt, calls, states = make_cycle_optimizer()
        with_decision(opt, 3)
        monitor = MagicMock()
        monitor.get_all_statuses.return_value = {"Bed": {"status": "critical", "direction": "hot"}}
        opt._get_critical_monitor = lambda: monitor
        assert opt._compute_comfort_relaxation({"Bed": {}, "Living": {}})["global"] == 0.0

    def test_end_to_end_with_real_soc_sensor(self):
        """SOC sensor -> learner -> decision -> coordinator data, no injection."""
        opt, calls, states = make_cycle_optimizer(enable_battery_mode=True, battery_soc_entity="sensor.battery_soc")
        states["sensor.battery_soc"] = FakeState("60", {"unit_of_measurement": "%"})
        opt.battery_manager = bat.BatteryManager(opt.hass, "t", Path(tempfile.mkdtemp()))
        result = run_cycle(opt)
        assert result["battery"]["soc"] == 60.0
        assert result["battery"]["status"] in ("normal", "efficient")


class TestEfficientOperation:
    def test_switches_off_once_satisfied_for_dwell(self):
        opt, calls, states = make_cycle_optimizer(
            rooms=(("Bed", 22.9, None), ("Living", 22.8, None)), enable_efficiency_mode=True,
        )
        now = [time.time()]
        with patch("time.time", side_effect=lambda: now[0]):
            run_cycle(opt)
            assert hvac_commands(calls) == []
            now[0] += 400
            opt._last_optimization = None
            run_cycle(opt)
        assert hvac_commands(calls) == ["off"]

    def test_dwell_resets_when_a_room_needs_conditioning(self):
        opt, calls, states = make_cycle_optimizer(
            rooms=(("Bed", 22.9, None), ("Living", 22.8, None)), enable_efficiency_mode=True,
        )
        now = [time.time()]
        with patch("time.time", side_effect=lambda: now[0]):
            run_cycle(opt)
            now[0] += 200
            set_room_temps(states, Bed=23.4)
            run_cycle(opt)
            now[0] += 200
            set_room_temps(states, Bed=22.9)
            run_cycle(opt)
        assert hvac_commands(calls) == []

    def test_gentle_setpoint(self):
        opt, calls, states = make_cycle_optimizer(
            rooms=(("Bed", 26.0, None), ("Living", 26.0, None)), auto_control_ac_temperature=True,
            enable_efficiency_mode=True,
        )
        run_cycle(opt)
        assert [c[2]["temperature"] for c in calls if c[1] == "set_temperature"] == [21.0]  # 23 - 2, not 23 - 4

    def test_fan_only_idle_capped(self):
        opt, _, _ = make_cycle_optimizer(enable_efficiency_mode=True)
        assert opt._effective_fan_only_idle_minutes() == 10
        opt.fan_only_idle_minutes = 5
        assert opt._effective_fan_only_idle_minutes() == 5
