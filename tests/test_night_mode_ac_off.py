"""Night mode only lasts while the AC runs.

When the main AC is switched off by anything other than this integration
(its remote or app, a timer, another automation), night mode turns off and
stays off until the user turns it on again. It ends once the AC, having run
since night mode was turned on, reads off on two polls in a row.
"""
from __future__ import annotations

import asyncio
import logging
import sys
import time
from pathlib import Path
from unittest.mock import MagicMock, patch

sys.path.insert(0, str(Path(__file__).parent.parent))
sys.path.insert(0, str(Path(__file__).parent))

from test_night_mode_temp_drop import FakeEntry, entry_data  # noqa: E402
from test_v302_fixes import hvac_commands, make_cycle_optimizer, run_cycle, set_ac_mode, set_room_temps  # noqa: E402


def night_cycle_optimizer(ac_state="cool", auto_control_main_ac=False, night_mode=True, rooms_temp=23.0):
    """Optimizer in night mode with a config entry that saves like HA's."""
    if night_mode:
        data = entry_data(enable_night_mode=True, target_temperature=21.0, night_mode_saved_target=23.0)
        target = 21.0
    else:
        data = entry_data(enable_night_mode=False, target_temperature=23.0)
        target = 23.0
    opt, calls, states = make_cycle_optimizer(
        rooms=(("Bed", rooms_temp, None), ("Living", rooms_temp, None)),
        ac_state=ac_state, target=target,
        enable_night_mode=night_mode, night_mode_rooms=["Bed"],
        auto_control_main_ac=auto_control_main_ac,
    )
    entry = FakeEntry(data)
    opt.config_entry = entry

    def update_entry(target_entry, data=None, **_kwargs):
        target_entry.data = dict(data)
        return True

    opt.hass.config_entries.async_update_entry = MagicMock(side_effect=update_entry)
    return opt, calls, states, entry


def switch_off(opt, states):
    """The AC switched off by its remote, read on two polls."""
    set_ac_mode(states, "off")
    run_cycle(opt)
    return run_cycle(opt)


class TestAcSwitchedOff:
    def test_switching_the_ac_off_turns_night_mode_off_and_restores_the_target(self, caplog):
        opt, _, states, entry = night_cycle_optimizer()
        run_cycle(opt)                                   # AC running
        set_ac_mode(states, "off")                       # remote, app or timer
        run_cycle(opt)                                   # first off reading
        assert opt.enable_night_mode is True
        with caplog.at_level(logging.INFO):
            result = run_cycle(opt)                      # second: confirmed
        assert opt.enable_night_mode is False
        assert entry.data["enable_night_mode"] is False
        # The night temperature drop is undone, as with the switch
        assert opt.target_temperature == 23.0
        assert entry.data["target_temperature"] == 23.0
        assert "night_mode_saved_target" not in entry.data
        # This cycle already runs without night mode
        assert result["night_mode_active"] is False
        assert result["night_mode_closed_rooms"] == []
        assert any("night mode turned off" in r.getMessage() for r in caplog.records)

    def test_a_single_off_reading_is_not_enough(self):
        # A unit passing through "off" while changing mode
        opt, _, states, _ = night_cycle_optimizer()
        run_cycle(opt)
        set_ac_mode(states, "off")
        run_cycle(opt)
        set_ac_mode(states, "dry")
        run_cycle(opt)
        set_ac_mode(states, "off")
        run_cycle(opt)
        assert opt.enable_night_mode is True

    def test_stays_off_when_the_ac_comes_back_on(self):
        opt, _, states, entry = night_cycle_optimizer()
        run_cycle(opt)
        switch_off(opt, states)
        set_ac_mode(states, "cool")
        run_cycle(opt)
        assert opt.enable_night_mode is False
        assert entry.data["enable_night_mode"] is False

    def test_fan_only_and_dry_count_as_on(self):
        opt, _, states, _ = night_cycle_optimizer(ac_state="fan_only")
        run_cycle(opt)
        set_ac_mode(states, "dry")
        run_cycle(opt)
        assert opt.enable_night_mode is True
        switch_off(opt, states)
        assert opt.enable_night_mode is False

    def test_controller_outage_is_not_a_switch_off(self):
        opt, _, states, _ = night_cycle_optimizer()
        run_cycle(opt)
        set_ac_mode(states, "unavailable")
        run_cycle(opt)
        run_cycle(opt)
        set_ac_mode(states, "cool")
        run_cycle(opt)
        assert opt.enable_night_mode is True

    def test_off_after_an_outage_still_counts(self):
        opt, _, states, _ = night_cycle_optimizer()
        run_cycle(opt)
        set_ac_mode(states, "unavailable")
        run_cycle(opt)
        switch_off(opt, states)                          # switched off while unreachable
        assert opt.enable_night_mode is False

    def test_ac_already_off_at_startup_leaves_night_mode_alone(self):
        opt, _, states, _ = night_cycle_optimizer(ac_state="off")
        for _ in range(3):
            run_cycle(opt)
        assert opt.enable_night_mode is True

    def test_turned_on_while_the_ac_is_off_lasts_until_the_ac_is_next_switched_off(self):
        opt, _, states, _ = night_cycle_optimizer(ac_state="off")
        run_cycle(opt)
        set_ac_mode(states, "cool")                      # bedtime: AC on
        run_cycle(opt)
        assert opt.enable_night_mode is True
        switch_off(opt, states)                          # morning timer
        assert opt.enable_night_mode is False

    def test_failed_save_is_retried_on_the_next_poll(self, caplog):
        opt, _, states, entry = night_cycle_optimizer()
        working = opt.hass.config_entries.async_update_entry
        run_cycle(opt)
        opt.hass.config_entries.async_update_entry = MagicMock(side_effect=RuntimeError("entry not loaded"))
        with caplog.at_level(logging.WARNING):
            switch_off(opt, states)
            run_cycle(opt)                               # still failing
        assert opt.enable_night_mode is True
        assert opt.target_temperature == 21.0
        assert entry.data["enable_night_mode"] is True
        assert len([r for r in caplog.records if "couldn't be saved" in r.getMessage()]) == 1
        opt.hass.config_entries.async_update_entry = working
        run_cycle(opt)                                   # AC still off: tried again
        assert opt.enable_night_mode is False
        assert entry.data["enable_night_mode"] is False

    def test_nothing_saved_when_night_mode_is_off(self):
        opt, _, states, entry = night_cycle_optimizer()
        opt.enable_night_mode = False
        run_cycle(opt)
        switch_off(opt, states)
        opt.hass.config_entries.async_update_entry.assert_not_called()

    def test_switch_shows_the_change_after_the_cycle(self):
        from custom_components.smart_aircon_manager.switch import NightModeSwitch

        opt, _, states, entry = night_cycle_optimizer()
        switch = NightModeSwitch(opt, entry)
        run_cycle(opt)
        assert switch.is_on is True
        switch_off(opt, states)
        assert switch.is_on is False
        assert switch.extra_state_attributes["restores_target"] is None


class TestTurnedOnAroundASwitchOff:
    @staticmethod
    def _switch(opt, entry):
        from test_night_mode_temp_drop import fake_hass

        from custom_components.smart_aircon_manager.switch import NightModeSwitch

        switch = NightModeSwitch(opt, entry)
        switch.hass = fake_hass(entry)
        switch.async_write_ha_state = MagicMock()
        return switch

    def test_turned_on_just_after_the_ac_was_switched_off(self):
        # Bedtime automation: AC off by remote, night mode on within a poll,
        # before any cycle saw the AC off
        opt, _, states, entry = night_cycle_optimizer(night_mode=False)
        run_cycle(opt)                                   # AC seen running
        set_ac_mode(states, "off")
        asyncio.run(self._switch(opt, entry).async_turn_on())
        for _ in range(3):
            run_cycle(opt)
        assert opt.enable_night_mode is True
        # It ends the next time the AC runs and is switched off
        set_ac_mode(states, "cool")
        run_cycle(opt)
        switch_off(opt, states)
        assert opt.enable_night_mode is False

    def test_turning_it_on_again_while_on_keeps_the_ac_history(self):
        # An automation firing "on" twice must not forget the AC ran
        opt, _, states, entry = night_cycle_optimizer()
        run_cycle(opt)                                   # AC running in night mode
        asyncio.run(self._switch(opt, entry).async_turn_on())
        switch_off(opt, states)
        assert opt.enable_night_mode is False


class TestOwnSwitchOff:
    """Auto control idling the AC is part of the night, however it shows."""

    @staticmethod
    def _idle(opt, states, calls):
        """Rooms well below the night target: auto control switches the AC off."""
        set_room_temps(states, Bed=18.5, Living=18.5)
        run_cycle(opt)
        assert hvac_commands(calls)[-1] == "off"

    def test_own_switch_off_leaves_night_mode_on(self):
        opt, calls, states, entry = night_cycle_optimizer(auto_control_main_ac=True)
        run_cycle(opt)
        self._idle(opt, states, calls)
        switch_off(opt, states)
        run_cycle(opt)
        assert opt.enable_night_mode is True
        assert entry.data["enable_night_mode"] is True

    def test_own_switch_off_seen_only_after_a_long_outage(self):
        opt, calls, states, _ = night_cycle_optimizer(auto_control_main_ac=True)
        run_cycle(opt)
        self._idle(opt, states, calls)
        set_ac_mode(states, "unavailable")
        start = time.time()
        with patch("time.time", return_value=start + 600):   # 10 minutes later
            run_cycle(opt)
            switch_off(opt, states)
        assert opt.enable_night_mode is True

    def test_own_switch_off_reported_failed_but_carried_out(self):
        opt, calls, states, _ = night_cycle_optimizer(auto_control_main_ac=True)
        run_cycle(opt)
        record = opt.hass.services.async_call

        async def timing_out(domain, service, data, blocking=False):
            await record(domain, service, data, blocking)
            if service == "set_hvac_mode":
                raise RuntimeError("Connection timed out.")

        opt.hass.services.async_call = timing_out
        with patch("custom_components.smart_aircon_manager.optimizer.asyncio.sleep"):
            self._idle(opt, states, calls)
        opt.hass.services.async_call = record
        switch_off(opt, states)                          # the unit did switch off
        assert opt.enable_night_mode is True

    def test_restart_held_back_by_compressor_protection_keeps_night_mode(self):
        # Demand returns inside the minimum off-time: the AC stays off only
        # because the restart is held back, which is still the integration's
        # own idle (Codex review on #8)
        opt, calls, states, _ = night_cycle_optimizer(auto_control_main_ac=True)
        run_cycle(opt)
        self._idle(opt, states, calls)                   # own off: min off-time starts
        set_ac_mode(states, "off")
        set_room_temps(states, Bed=23.0, Living=23.0)    # demand is back
        for _ in range(3):
            run_cycle(opt)
        assert hvac_commands(calls)[-1] == "off"         # restart still held back
        assert opt.enable_night_mode is True
        # The min off-time passes: the AC restarts and night mode carries on
        later = time.time() + 600
        with patch("time.time", return_value=later):
            run_cycle(opt)
        restart_mode = hvac_commands(calls)[-1]
        assert restart_mode != "off"
        set_ac_mode(states, restart_mode)
        with patch("time.time", return_value=later + 30):
            run_cycle(opt)
        assert opt.enable_night_mode is True

    def test_restart_after_an_outage_keeps_night_mode(self):
        opt, calls, states, _ = night_cycle_optimizer(auto_control_main_ac=True)
        run_cycle(opt)
        self._idle(opt, states, calls)
        set_ac_mode(states, "unavailable")
        set_room_temps(states, Bed=23.0, Living=23.0)    # demand returns during the outage
        run_cycle(opt)
        switch_off(opt, states)                          # back, still off from the idle
        assert opt.enable_night_mode is True

    def test_failed_switch_off_that_left_the_ac_running_is_forgotten(self):
        # The off command failed and the AC kept running. Once auto control
        # wants it running again, a later switch-off is the user's
        opt, calls, states, _ = night_cycle_optimizer(auto_control_main_ac=True)
        run_cycle(opt)
        record = opt.hass.services.async_call

        async def timing_out(domain, service, data, blocking=False):
            await record(domain, service, data, blocking)
            if service == "set_hvac_mode":
                raise RuntimeError("Connection timed out.")

        opt.hass.services.async_call = timing_out
        with patch("custom_components.smart_aircon_manager.optimizer.asyncio.sleep"):
            self._idle(opt, states, calls)               # AC still running
        opt.hass.services.async_call = record
        set_room_temps(states, Bed=23.0, Living=23.0)    # wanted running again
        run_cycle(opt)
        switch_off(opt, states)                          # the user switches it off
        assert opt.enable_night_mode is False

    def test_user_switch_off_after_the_ac_came_back_on_ends_it(self):
        opt, calls, states, _ = night_cycle_optimizer(auto_control_main_ac=True)
        run_cycle(opt)
        self._idle(opt, states, calls)
        switch_off(opt, states)
        set_room_temps(states, Bed=23.0, Living=23.0)
        set_ac_mode(states, "cool")                      # back on (anyone)
        run_cycle(opt)
        assert opt.enable_night_mode is True
        # Auto control now wants it running; the user switches it off
        switch_off(opt, states)
        assert opt.enable_night_mode is False


class TestManagerTurnedOff:
    def test_turning_the_manager_off_ends_night_mode(self):
        opt, calls, states, entry = night_cycle_optimizer()
        run_cycle(opt)
        asyncio.run(opt.async_turn_off_main_ac())
        assert hvac_commands(calls)[-1] == "off"
        assert opt.enable_night_mode is False
        assert entry.data["enable_night_mode"] is False
        assert opt.target_temperature == 23.0

    def test_turning_it_back_on_does_not_rearm_the_min_off_timer(self):
        opt, calls, states, entry = night_cycle_optimizer()
        run_cycle(opt)
        asyncio.run(opt.async_turn_off_main_ac())
        stamped = opt._ac_last_turned_off
        set_ac_mode(states, "off")
        opt.is_enabled = False
        run_cycle(opt)                                   # skipped while off
        opt.is_enabled = True
        later = time.time() + 3600
        with patch("time.time", return_value=later):
            run_cycle(opt)
        assert opt._ac_last_turned_off == stamped
