"""Damper command feedback.

A zone that accepts a position but keeps reporting another one (an Advantage
Air controller holding a constant zone open, for example) used to get the
same command on every optimization pass, all night. After two accepted
commands it didn't follow, the position is held back with a backoff.
"""
from __future__ import annotations

import asyncio
import logging
import sys
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).parent.parent))
sys.path.insert(0, str(Path(__file__).parent))

from test_v302_fixes import make_cycle_optimizer, run_cycle  # noqa: E402

ROOMS = (("Media", 23.0, None), ("Bed", 23.0, None))


class Clock:
    """A settable stand-in for time.time()."""

    def __init__(self, start=1_000_000.0):
        self.now = start

    def __call__(self):
        return self.now


def cover_calls(calls, entity="cover.media"):
    return [c[2]["position"] for c in calls if c[1] == "set_cover_position" and c[2]["entity_id"] == entity]


def make(position=75):
    opt, calls, states = make_cycle_optimizer(rooms=ROOMS)
    opt._optimization_interval = 60
    states["cover.media"].attributes["current_position"] = position
    return opt, calls, states


def apply(opt, clock, at, recommendations):
    clock.now = at
    with patch("time.time", clock):
        return asyncio.run(opt._apply_recommendations(recommendations))


def held(opt, clock):
    with patch("time.time", clock):
        return opt._held_dampers()


class TestHeldZone:
    def test_zone_that_ignores_two_commands_is_held_with_backoff(self, caplog):
        opt, calls, _ = make(75)
        clock = Clock()
        t0 = clock.now
        with caplog.at_level(logging.WARNING):
            assert "Media" in apply(opt, clock, t0, {"Media": 0})        # sent
            assert "Media" in apply(opt, clock, t0 + 60, {"Media": 0})   # ignored once: sent again
            assert len(cover_calls(calls)) == 2
            delivered = apply(opt, clock, t0 + 120, {"Media": 0})       # ignored twice: held
        assert "Media" in delivered          # nothing a retry can change: counts as done
        assert len(cover_calls(calls)) == 2
        assert held(opt, clock) == ["Media"]
        warnings = [r for r in caplog.records if "holding it there" in r.getMessage()]
        assert len(warnings) == 1
        assert "still reports 75%" in warnings[0].getMessage()

        # Held for 5 minutes: no command in between
        for t in range(180, 420, 60):
            apply(opt, clock, t0 + t, {"Media": 0})
        assert len(cover_calls(calls)) == 2

        # The hold is over: one more try...
        apply(opt, clock, t0 + 421, {"Media": 0})
        assert len(cover_calls(calls)) == 3
        # ...still ignored: held again, twice as long
        apply(opt, clock, t0 + 481, {"Media": 0})
        assert len(cover_calls(calls)) == 3
        assert opt._cover_feedback["Media"].hold_seconds == 600
        apply(opt, clock, t0 + 481 + 599, {"Media": 0})
        assert len(cover_calls(calls)) == 3

    def test_hold_doubles_up_to_thirty_minutes(self):
        opt, calls, _ = make(75)
        clock = Clock()
        t = clock.now
        apply(opt, clock, t, {"Media": 0})
        t += 60
        apply(opt, clock, t, {"Media": 0})
        holds = []
        for _ in range(6):
            t += 60
            apply(opt, clock, t, {"Media": 0})            # judged: held
            feedback = opt._cover_feedback["Media"]
            holds.append(feedback.hold_seconds)
            t = feedback.hold_until + 1
            apply(opt, clock, t, {"Media": 0})            # retry after the hold
        assert holds == [300, 600, 1200, 1800, 1800, 1800]

    def test_zone_that_follows_clears_the_streak(self, caplog):
        opt, calls, states = make(75)
        clock = Clock()
        t0 = clock.now
        apply(opt, clock, t0, {"Media": 0})
        apply(opt, clock, t0 + 60, {"Media": 0})
        apply(opt, clock, t0 + 120, {"Media": 0})             # held
        assert held(opt, clock) == ["Media"]
        states["cover.media"].attributes["current_position"] = 0
        with caplog.at_level(logging.INFO):
            assert "Media" in apply(opt, clock, t0 + 180, {"Media": 0})
        assert held(opt, clock) == []
        assert "Media" not in opt._cover_feedback
        assert any("following commands again" in r.getMessage() for r in caplog.records)
        # Reopened later (a controller re-asserting a constant zone): a fresh
        # streak starts, so the close goes out again at once
        states["cover.media"].attributes["current_position"] = 75
        apply(opt, clock, t0 + 240, {"Media": 0})
        assert len(cover_calls(calls)) == 3

    def test_new_target_is_sent_at_once_during_a_hold(self):
        opt, calls, _ = make(75)
        clock = Clock()
        t0 = clock.now
        for t in (0, 60, 120):
            apply(opt, clock, t0 + t, {"Media": 0})
        assert held(opt, clock) == ["Media"]
        apply(opt, clock, t0 + 150, {"Media": 40})
        assert cover_calls(calls) == [0, 0, 40]
        assert held(opt, clock) == []

    def test_small_target_change_keeps_the_hold(self):
        opt, calls, _ = make(75)
        clock = Clock()
        t0 = clock.now
        for t in (0, 60, 120):
            apply(opt, clock, t0 + t, {"Media": 10})
        apply(opt, clock, t0 + 180, {"Media": 12})   # within the 3 % tolerance: same request
        assert cover_calls(calls) == [10, 10]

    def test_zone_moved_by_something_else_releases_the_hold(self):
        opt, calls, states = make(75)
        clock = Clock()
        t0 = clock.now
        for t in (0, 60, 120):
            apply(opt, clock, t0 + t, {"Media": 0})
        states["cover.media"].attributes["current_position"] = 100   # moved on its own
        apply(opt, clock, t0 + 180, {"Media": 0})
        assert cover_calls(calls) == [0, 0, 0]
        assert held(opt, clock) == []

    def test_failed_command_is_not_counted_as_ignored(self):
        opt, calls, _ = make(75)
        failures = []

        async def failing(domain, service, data, blocking=False):
            if service == "set_cover_position":
                failures.append(data)
                raise RuntimeError("Connection timed out.")

        opt.hass.services.async_call = failing
        clock = Clock()
        t0 = clock.now
        with patch("custom_components.smart_aircon_manager.optimizer.asyncio.sleep"):
            for t in (0, 60, 120, 180):
                assert "Media" not in apply(opt, clock, t0 + t, {"Media": 0})
        assert len(failures) == 4 * 3        # every pass tried (with its retries)
        assert opt._cover_feedback == {}
        assert held(opt, clock) == []

    def test_resends_too_close_together_are_not_judged(self):
        opt, calls, _ = make(75)
        clock = Clock()
        t0 = clock.now
        for t in (0, 5, 10, 15):
            apply(opt, clock, t0 + t, {"Media": 0})
        assert len(cover_calls(calls)) == 4
        assert opt._cover_feedback["Media"].misses == 0

    def test_command_judged_long_afterwards_starts_over(self):
        opt, calls, _ = make(75)
        clock = Clock()
        t0 = clock.now
        apply(opt, clock, t0, {"Media": 0})
        apply(opt, clock, t0 + 60, {"Media": 0})      # one miss
        # Nothing for 20 minutes (control paused, AC off): that gap says
        # nothing about the last command
        apply(opt, clock, t0 + 1260, {"Media": 0})
        assert len(cover_calls(calls)) == 3
        assert opt._cover_feedback["Media"].misses == 0

    def test_zone_that_moves_but_cannot_reach_the_position_is_held_quietly(self, caplog):
        # Coarse zones (10 % steps): asked for 45, it goes to 40 and stays
        opt, calls, states = make(70)
        clock = Clock()
        t0 = clock.now
        with caplog.at_level(logging.DEBUG):
            apply(opt, clock, t0, {"Media": 45})
            states["cover.media"].attributes["current_position"] = 40
            apply(opt, clock, t0 + 60, {"Media": 45})
            apply(opt, clock, t0 + 120, {"Media": 45})
        assert cover_calls(calls) == [45, 45]
        assert held(opt, clock) == ["Media"]
        assert not [r for r in caplog.records if r.levelno >= logging.WARNING]

    def test_warning_is_limited_per_room(self, caplog):
        opt, calls, states = make(75)
        clock = Clock()
        t0 = clock.now
        with caplog.at_level(logging.WARNING):
            for t in (0, 60, 120):
                apply(opt, clock, t0 + t, {"Media": 0})
            states["cover.media"].attributes["current_position"] = 0      # followed once
            apply(opt, clock, t0 + 180, {"Media": 0})
            states["cover.media"].attributes["current_position"] = 75     # reopened again
            for t in (240, 300, 360):
                apply(opt, clock, t0 + t, {"Media": 0})
        assert held(opt, clock) == ["Media"]
        assert len([r for r in caplog.records if "holding it there" in r.getMessage()]) == 1

    def test_other_rooms_are_unaffected(self):
        opt, calls, states = make(75)
        states["cover.bed"].attributes["current_position"] = 20
        clock = Clock()
        t0 = clock.now
        for t in (0, 60, 120, 180):
            apply(opt, clock, t0 + t, {"Media": 0, "Bed": 20 + t // 6})
        bed = cover_calls(calls, "cover.bed")
        assert bed == [30, 40, 50]     # each a new target, each sent at once


class TestNightModeCycles:
    """The case from the field: night mode closes a room the controller keeps open."""

    def test_closed_off_room_held_open_gets_a_few_commands_not_one_per_pass(self):
        opt, calls, states = make_cycle_optimizer(
            rooms=(("Media", 25.0, None), ("Bed", 25.0, None)),
            enable_night_mode=True, night_mode_rooms=["Bed"],
            auto_control_main_ac=False,
        )
        opt._optimization_interval = 60
        states["cover.media"].attributes["current_position"] = 75   # constant zone, held open
        record = opt.hass.services.async_call

        async def controller(domain, service, data, blocking=False):
            # Zones follow their commands, except the one held open
            await record(domain, service, data, blocking)
            if service == "set_cover_position" and data["entity_id"] != "cover.media":
                states[data["entity_id"]].attributes["current_position"] = data["position"]

        opt.hass.services.async_call = controller
        clock = Clock()
        with patch("time.time", clock):
            for _ in range(60):                 # an hour of passes
                run_cycle(opt)
                clock.now += 60
        media = cover_calls(calls)
        assert media and set(media) == {0}
        # 2 to start the hold, then one retry per hold (5, 10, 20, 30 min)
        assert len(media) <= 5
        assert held(opt, clock) == ["Media"]
