"""Regression tests for the v3.2.2 production-readiness review.

Each test reproduces a defect found in the review (most predate night mode)
and fails on the code before the fix.
"""
from __future__ import annotations

import asyncio
import sys
import time
from pathlib import Path
from unittest.mock import MagicMock, patch

sys.path.insert(0, str(Path(__file__).parent.parent))
sys.path.insert(0, str(Path(__file__).parent))

from test_v302_fixes import (  # noqa: E402
    FakeState,
    hvac_commands,
    make_cycle_optimizer,
    run_cycle,
)


def notifications(calls, title_part=""):
    """Notify-service pushes (persistent notifications excluded)."""
    return [c for c in calls if c[0] == "notify" and title_part in c[2].get("title", "")]


async def _no_sleep(*_args, **_kwargs):
    return None


class TestCyclesDoNotOverlap:
    def test_concurrent_refreshes_run_one_after_the_other(self):
        opt, calls, states = make_cycle_optimizer(
            rooms=(("Bed", 26.0, None), ("Living", 26.0, None)), ac_state="off",
        )
        record = opt.hass.services.async_call

        async def slow_device(domain, service, data, blocking=False):
            await record(domain, service, data, blocking)
            if domain in ("cover", "climate"):
                await asyncio.sleep(0.02)  # zone motor / cloud round trip
            if service == "set_hvac_mode":
                states["climate.ac"].state = data["hvac_mode"]

        opt.hass.services.async_call = slow_device

        async def two_refreshes():
            await asyncio.gather(opt.async_optimize(), opt.async_optimize())

        asyncio.run(two_refreshes())
        assert hvac_commands(calls) == ["cool"]
        turned_on = [c for c in calls if c[0] == "persistent_notification" and "Turned On" in c[2]["title"]]
        assert len(turned_on) == 1

    def test_lock_survives_a_new_event_loop(self):
        opt, _, _ = make_cycle_optimizer()
        run_cycle(opt)
        run_cycle(opt)  # asyncio.run creates a new loop each time


class TestUnavailableMainAC:
    def test_no_commands_or_notifications_while_unavailable(self):
        opt, calls, states = make_cycle_optimizer(
            rooms=(("Bed", 20.0, None), ("Living", 20.0, None)),
            notify_services=["notify.phone"], auto_control_ac_temperature=True,
        )
        states["climate.ac"].state = "unavailable"
        states["climate.ac"].attributes = {}
        stamped = opt._ac_last_turned_off
        for _ in range(3):
            run_cycle(opt)
        assert [c for c in calls if c[0] == "climate"] == []
        assert notifications(calls) == []
        assert opt._ac_last_turned_off == stamped   # restart isn't delayed

    def test_hot_house_with_unavailable_ac_sends_nothing(self):
        opt, calls, states = make_cycle_optimizer(rooms=(("Bed", 27.0, None), ("Living", 27.0, None)))
        states["climate.ac"].state = "unavailable"
        states["climate.ac"].attributes = {}
        run_cycle(opt)
        assert [c for c in calls if c[0] == "climate"] == []

    def test_control_resumes_when_the_ac_returns(self):
        opt, calls, states = make_cycle_optimizer(rooms=(("Bed", 27.0, None), ("Living", 27.0, None)), ac_state="off")
        attrs = dict(states["climate.ac"].attributes)
        states["climate.ac"].state = "unavailable"
        states["climate.ac"].attributes = {}
        run_cycle(opt)
        states["climate.ac"].state = "off"
        states["climate.ac"].attributes = attrs
        run_cycle(opt)
        assert hvac_commands(calls) == ["cool"]

    def test_unknown_state_is_still_commanded(self):
        # Available entity without a reported mode (some IR units until their
        # first command): commands are delivered, so keep sending them
        opt, calls, states = make_cycle_optimizer(rooms=(("Bed", 20.0, None), ("Living", 20.0, None)))
        states["climate.ac"].state = "unknown"
        run_cycle(opt)
        assert hvac_commands(calls) == ["off"]


class TestNoDataNotification:
    def test_notified_once_per_outage(self):
        opt, calls, states = make_cycle_optimizer(
            rooms=(("Bed", "unavailable", None), ("Living", "unavailable", None)),
            notify_services=["notify.phone"],
        )
        for _ in range(4):
            run_cycle(opt)
        assert len(notifications(calls, "No Temperature Data")) == 1
        # Readings return, then a new outage notifies again
        states["sensor.bed"].state = "23.0"
        states["sensor.living"].state = "23.0"
        run_cycle(opt)
        states["sensor.bed"].state = "unavailable"
        states["sensor.living"].state = "unavailable"
        run_cycle(opt)
        run_cycle(opt)
        assert len(notifications(calls, "No Temperature Data")) == 2

    def test_night_mode_outage_notified_once(self):
        opt, calls, _ = make_cycle_optimizer(
            rooms=(("Bed", "unavailable", None), ("Living", 27.0, None)),
            notify_services=["notify.phone"], enable_night_mode=True, night_mode_rooms=["Bed"],
        )
        for _ in range(3):
            run_cycle(opt)
        assert len(notifications(calls, "No Temperature Data")) == 1


class TestCoverFailureNotification:
    def test_failing_zone_notifies_once_per_cooldown(self):
        opt, calls, states = make_cycle_optimizer(
            rooms=(("Bed", 26.0, None), ("Living", 26.0, None)), notify_services=["notify.phone"],
        )
        record = opt.hass.services.async_call

        async def zone_rejects(domain, service, data, blocking=False):
            if domain == "cover" and data.get("entity_id") == "cover.living":
                raise RuntimeError("zone controller error")
            return await record(domain, service, data, blocking)

        opt.hass.services.async_call = zone_rejects
        with patch("asyncio.sleep", new=_no_sleep):
            for _ in range(3):
                opt._last_optimization = None   # a full pass every cycle
                run_cycle(opt)
            assert len(notifications(calls, "Cover Control Error")) == 1
            # The zone recovers, then fails again: notified promptly
            opt.hass.services.async_call = record
            states["cover.living"].attributes["current_position"] = 0
            opt._last_optimization = None
            run_cycle(opt)
            opt.hass.services.async_call = zone_rejects
            states["cover.living"].attributes["current_position"] = 0
            opt._last_optimization = None
            run_cycle(opt)
        assert len(notifications(calls, "Cover Control Error")) == 2


class TestAwayMode:
    def test_person_in_a_named_zone_counts_as_away(self):
        opt, _, states = make_cycle_optimizer(
            enable_away_mode=True, away_mode_entities=["person.a", "person.b"], away_mode_delay_minutes=1,
        )
        states["person.a"] = FakeState("Work")
        states["person.b"] = FakeState("not_home")
        opt._process_away_mode()
        opt._all_away_since -= 120
        opt._process_away_mode()
        assert opt._quick_action_mode == "vacation"

    def test_anyone_home_prevents_vacation(self):
        opt, _, states = make_cycle_optimizer(
            enable_away_mode=True, away_mode_entities=["person.a", "person.b"], away_mode_delay_minutes=1,
        )
        states["person.a"] = FakeState("Work")
        states["person.b"] = FakeState("home")
        opt._process_away_mode()
        assert opt._all_away_since is None
        assert opt._quick_action_mode is None


class TestOccupancySensorOutage:
    def test_unavailable_sensor_does_not_mark_room_vacant(self):
        opt, _, states = make_cycle_optimizer(
            enable_occupancy_control=True,
            occupancy_sensors={"Bed": "binary_sensor.bed_motion"},
            vacancy_timeout=0,
        )
        states["binary_sensor.bed_motion"] = FakeState("on")
        asyncio.run(opt._update_occupancy_state())
        asyncio.run(opt._update_occupancy_state())
        states["binary_sensor.bed_motion"] = FakeState("unavailable")
        asyncio.run(opt._update_occupancy_state())
        assert opt._room_occupancy_state["Bed"]["occupied"] is True
        assert opt._get_room_effective_target("Bed", 23.0) == 23.0
        # A real "off" still counts toward vacancy
        states["binary_sensor.bed_motion"] = FakeState("off")
        asyncio.run(opt._update_occupancy_state())
        assert opt._room_occupancy_state["Bed"]["occupied"] is False


class TestCriticalMonitorUnavailableAC:
    @staticmethod
    def _monitor(ac_state):
        from custom_components.smart_aircon_manager.critical_monitor import CriticalRoomMonitor

        calls = []

        async def service_call(domain, service, data, blocking=False):
            calls.append((domain, service, dict(data)))

        hass = MagicMock()
        hass.services.async_call = service_call
        hass.states.get = lambda entity_id: FakeState(ac_state)
        monitor = CriticalRoomMonitor(hass, {}, [], "climate.ac")
        return monitor, calls

    def test_unavailable_ac_is_not_falsely_turned_on(self):
        monitor, calls = self._monitor("unavailable")
        asyncio.run(monitor._ensure_ac_running("Server", 31.0, {"critical_temp_max": 28}, "hot"))
        assert calls == []

    def test_off_and_unknown_ac_are_turned_on(self):
        for state in ("off", "unknown"):
            monitor, calls = self._monitor(state)
            asyncio.run(monitor._ensure_ac_running("Server", 31.0, {"critical_temp_max": 28}, "hot"))
            assert [c[2]["hvac_mode"] for c in calls] == ["cool"], state


class TestCriticalMonitorRecovery:
    """An AC outage must never delay the critical-room response (review of #3)."""

    @staticmethod
    def _monitor():
        from custom_components.smart_aircon_manager.critical_monitor import CriticalRoomMonitor

        calls = []
        ac = {"state": "off"}

        async def service_call(domain, service, data, blocking=False):
            calls.append((domain, service, dict(data)))

        hass = MagicMock()
        hass.services.async_call = service_call
        hass.states.get = lambda entity_id: FakeState(ac["state"])
        return CriticalRoomMonitor(hass, {}, [], "climate.ac"), calls, ac

    @staticmethod
    def _ensure(monitor):
        asyncio.run(monitor._ensure_ac_running("Server", 31.0, {"critical_temp_max": 28}, "hot"))

    def test_ac_back_from_unavailable_is_turned_on_at_once(self):
        monitor, calls, ac = self._monitor()
        ac["state"] = "unavailable"
        self._ensure(monitor)
        assert calls == []
        ac["state"] = "off"          # back on the next 30 s poll
        self._ensure(monitor)
        assert [c[2]["hvac_mode"] for c in calls] == ["cool"]

    def test_outage_clears_an_earlier_cooldown(self):
        monitor, calls, ac = self._monitor()
        self._ensure(monitor)        # turned on: cooldown armed
        ac["state"] = "unavailable"  # unit drops out and power-cycles
        self._ensure(monitor)
        ac["state"] = "off"
        self._ensure(monitor)
        assert [c[2]["hvac_mode"] for c in calls] == ["cool", "cool"]

    def test_cooldown_still_stops_fighting_an_off_switch(self):
        monitor, calls, ac = self._monitor()
        self._ensure(monitor)
        ac["state"] = "off"          # someone switched it off again, no outage
        self._ensure(monitor)
        assert [c[2]["hvac_mode"] for c in calls] == ["cool"]

    def test_unavailable_warning_is_rate_limited(self, caplog):
        import logging
        monitor, _, ac = self._monitor()
        ac["state"] = "unavailable"
        with caplog.at_level(logging.WARNING):
            for _ in range(3):
                self._ensure(monitor)
        warnings = [r for r in caplog.records if "unavailable" in r.getMessage()]
        assert len(warnings) == 1
        # Back, then a new outage warns again
        ac["state"] = "cool"
        self._ensure(monitor)
        ac["state"] = "unavailable"
        with caplog.at_level(logging.WARNING):
            self._ensure(monitor)
        warnings = [r for r in caplog.records if "unavailable" in r.getMessage()]
        assert len(warnings) == 2


def test_minimum_home_assistant_version_matches_used_apis():
    """OptionsFlow.config_entry (used by every options step) arrived in 2024.12."""
    import json
    hacs = json.loads((Path(__file__).parent.parent / "hacs.json").read_text())
    major, minor = (int(x) for x in hacs["homeassistant"].split(".")[:2])
    assert (major, minor) >= (2024, 12)
