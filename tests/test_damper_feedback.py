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

from test_v302_fixes import make_cycle_optimizer, run_cycle, set_room_temps  # noqa: E402

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


def hold_length(opt, room="Media"):
    return opt._cover_hold_history[room][1]


def holding_warnings(caplog):
    return [r for r in caplog.records if r.levelno >= logging.WARNING and "holding it there" in r.getMessage()]


def hold(opt, clock, t, position=0):
    """Three passes a minute apart: sent, ignored once (sent again), held."""
    for step in (0, 60, 120):
        apply(opt, clock, t + step, {"Media": position})
    return t + 120


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
        warnings = holding_warnings(caplog)
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
        assert hold_length(opt) == 600
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
            holds.append(hold_length(opt))
            t = opt._cover_feedback["Media"].hold_until + 1
            apply(opt, clock, t, {"Media": 0})            # retry after the hold
        assert holds == [300, 600, 1200, 1800, 1800, 1800]

    def test_zone_that_follows_clears_the_streak(self, caplog):
        opt, calls, states = make(75)
        clock = Clock()
        t0 = clock.now
        hold(opt, clock, t0)
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

    def test_reopened_soon_after_following_waits_longer(self):
        # A constant zone the controller closes and reopens as other zones
        # move: the backoff keeps building instead of restarting at 5 minutes
        opt, calls, states = make(75)
        clock = Clock()
        t0 = clock.now
        hold(opt, clock, t0)
        assert hold_length(opt) == 300
        states["cover.media"].attributes["current_position"] = 0        # allowed to close
        apply(opt, clock, t0 + 180, {"Media": 0})
        states["cover.media"].attributes["current_position"] = 75       # reopened
        hold(opt, clock, t0 + 240)
        assert hold_length(opt) == 600

    def test_backoff_starts_over_after_a_quiet_half_hour(self):
        opt, calls, states = make(75)
        clock = Clock()
        t0 = clock.now
        hold(opt, clock, t0)
        states["cover.media"].attributes["current_position"] = 0
        apply(opt, clock, t0 + 180, {"Media": 0})
        states["cover.media"].attributes["current_position"] = 75
        later = t0 + 120 + 300 + 1801      # well past the last hold's end
        hold(opt, clock, later)
        assert hold_length(opt) == 300

    def test_new_target_is_sent_at_once_during_a_hold(self):
        opt, calls, _ = make(75)
        clock = Clock()
        t0 = clock.now
        hold(opt, clock, t0)
        assert held(opt, clock) == ["Media"]
        apply(opt, clock, t0 + 150, {"Media": 40})
        assert cover_calls(calls) == [0, 0, 40]
        assert held(opt, clock) == []

    def test_small_target_change_keeps_the_hold(self):
        opt, calls, _ = make(75)
        clock = Clock()
        t0 = clock.now
        hold(opt, clock, t0, position=10)
        apply(opt, clock, t0 + 180, {"Media": 12})   # within the 3 % tolerance: same request
        assert cover_calls(calls) == [10, 10]

    def test_zone_moving_towards_its_position_releases_the_hold(self):
        opt, calls, states = make(75)
        clock = Clock()
        t0 = clock.now
        hold(opt, clock, t0)
        states["cover.media"].attributes["current_position"] = 40    # the controller let it part-close
        apply(opt, clock, t0 + 180, {"Media": 0})
        assert cover_calls(calls) == [0, 0, 0]
        assert held(opt, clock) == []

    def test_zone_moving_away_keeps_the_hold(self):
        # A controller varying a held constant zone's opening (75 <-> 80)
        # used to restart the streak each time: 24 closes an hour, not 5
        opt, calls, states = make(75)
        clock = Clock()
        t0 = clock.now
        hold(opt, clock, t0)
        for step, position in ((180, 80), (240, 75), (300, 80), (360, 75)):
            states["cover.media"].attributes["current_position"] = position
            apply(opt, clock, t0 + step, {"Media": 0})
        assert cover_calls(calls) == [0, 0]
        assert held(opt, clock) == ["Media"]

    def test_expired_hold_long_ago_starts_a_fresh_streak(self):
        opt, calls, _ = make(75)
        clock = Clock()
        t0 = clock.now
        hold(opt, clock, t0)
        # The hold ran out, then no damper pass for 3 hours (stable rooms)
        late = t0 + 120 + 300 + 3 * 3600
        apply(opt, clock, late, {"Media": 0})            # sent
        apply(opt, clock, late + 60, {"Media": 0})       # ignored once: sent again, not held yet
        assert len(cover_calls(calls)) == 4
        assert held(opt, clock) == []
        apply(opt, clock, late + 120, {"Media": 0})      # ignored twice: held, for 5 minutes
        assert held(opt, clock) == ["Media"]
        assert hold_length(opt) == 300

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

    def test_zone_that_cannot_land_exactly_is_held_quietly(self, caplog):
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

    def test_zone_opened_elsewhere_by_the_controller_is_warned_about(self, caplog):
        # Pre-positioned at 30 %, closed by night mode, opened to 100 % by the
        # controller: far from its position, so it gets the warning
        opt, calls, states = make(30)
        clock = Clock()
        t0 = clock.now
        with caplog.at_level(logging.WARNING):
            apply(opt, clock, t0, {"Media": 0})
            states["cover.media"].attributes["current_position"] = 100
            apply(opt, clock, t0 + 60, {"Media": 0})
            apply(opt, clock, t0 + 120, {"Media": 0})
        assert held(opt, clock) == ["Media"]
        warnings = holding_warnings(caplog)
        assert len(warnings) == 1
        assert "still reports 100%" in warnings[0].getMessage()

    def test_warning_is_limited_per_room(self, caplog):
        opt, calls, states = make(75)
        clock = Clock()
        t0 = clock.now
        with caplog.at_level(logging.WARNING):
            hold(opt, clock, t0)
            states["cover.media"].attributes["current_position"] = 0      # followed once
            apply(opt, clock, t0 + 180, {"Media": 0})
            states["cover.media"].attributes["current_position"] = 75     # reopened again
            hold(opt, clock, t0 + 240)
        assert held(opt, clock) == ["Media"]
        assert len(holding_warnings(caplog)) == 1

    def test_other_rooms_are_unaffected(self):
        opt, calls, states = make(75)
        states["cover.bed"].attributes["current_position"] = 20
        clock = Clock()
        t0 = clock.now
        for t in (0, 60, 120, 180):
            apply(opt, clock, t0 + t, {"Media": 0, "Bed": 20 + t // 6})
        bed = cover_calls(calls, "cover.bed")
        assert bed == [30, 40, 50]     # each a new target, each sent at once


class TestCoverPositionParsing:
    def test_damper_code_and_room_states_read_positions_the_same_way(self):
        from custom_components.smart_aircon_manager.optimizer import AirconOptimizer

        parse = AirconOptimizer._parse_cover_position
        assert parse(104) == 100            # clamped, as room states always did
        assert parse("-5") == 0
        assert parse("47.6") == 47
        for value in (None, "unknown", "unavailable", "none", "garbage"):
            assert parse(value) is None

    def test_out_of_range_position_is_clamped_before_the_debounce(self):
        opt, calls, states = make(104)
        clock = Clock()
        apply(opt, clock, clock.now, {"Media": 100})
        assert cover_calls(calls) == []     # 104 reads as 100: already there


class TestNightModeCycles:
    """The case from the field: night mode closes a room the controller keeps open."""

    @staticmethod
    def _night_optimizer():
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
        return opt, calls, states

    def test_closed_off_room_held_open_gets_a_few_commands_not_one_per_pass(self):
        opt, calls, states = self._night_optimizer()
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

    def test_held_dampers_reported_while_room_readings_are_missing(self):
        opt, calls, states = self._night_optimizer()
        clock = Clock()
        with patch("time.time", clock):
            for _ in range(3):
                run_cycle(opt)
                clock.now += 60
            set_room_temps(states, Media="unavailable", Bed="unavailable")
            result = run_cycle(opt)
        assert result["held_dampers"] == ["Media"]
