"""Night mode only lasts while the AC runs.

When the main AC is switched off by anything other than this integration
(its remote or app, a timer, another automation), night mode turns off and
stays off until the user turns it on again.
"""
from __future__ import annotations

import logging
import sys
import time
from pathlib import Path
from unittest.mock import MagicMock

sys.path.insert(0, str(Path(__file__).parent.parent))
sys.path.insert(0, str(Path(__file__).parent))

from test_night_mode_temp_drop import FakeEntry, entry_data  # noqa: E402
from test_v302_fixes import make_cycle_optimizer, run_cycle, set_ac_mode  # noqa: E402


def night_cycle_optimizer(ac_state="cool", auto_control_main_ac=False, **data_overrides):
    """Optimizer in night mode with a config entry that saves like HA's."""
    data = entry_data(
        enable_night_mode=True, target_temperature=21.0, night_mode_saved_target=23.0, **data_overrides
    )
    opt, calls, states = make_cycle_optimizer(
        rooms=(("Bed", 23.0, None), ("Living", 23.0, None)),
        ac_state=ac_state, target=21.0,
        enable_night_mode=True, night_mode_rooms=["Bed"],
        auto_control_main_ac=auto_control_main_ac,
    )
    entry = FakeEntry(data)
    opt.config_entry = entry

    def update_entry(target_entry, data=None, **_kwargs):
        target_entry.data = dict(data)
        return True

    opt.hass.config_entries.async_update_entry = MagicMock(side_effect=update_entry)
    return opt, calls, states, entry


class TestAcSwitchedOff:
    def test_switching_the_ac_off_turns_night_mode_off_and_restores_the_target(self, caplog):
        opt, _, states, entry = night_cycle_optimizer()
        run_cycle(opt)                                   # baseline: AC running
        assert opt.enable_night_mode is True

        set_ac_mode(states, "off")                       # remote, app or timer
        with caplog.at_level(logging.INFO):
            result = run_cycle(opt)
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

    def test_stays_off_when_the_ac_comes_back_on(self):
        opt, _, states, entry = night_cycle_optimizer()
        run_cycle(opt)
        set_ac_mode(states, "off")
        run_cycle(opt)
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
        set_ac_mode(states, "off")
        run_cycle(opt)
        assert opt.enable_night_mode is False

    def test_own_switch_off_leaves_night_mode_on(self):
        # With auto control the integration idles the AC itself; that is
        # part of running the night, not the user ending it
        opt, _, states, entry = night_cycle_optimizer(auto_control_main_ac=True)
        run_cycle(opt)
        opt._ac_last_turned_off = time.time()           # stamped by our own off command
        set_ac_mode(states, "off")
        run_cycle(opt)
        assert opt.enable_night_mode is True
        assert entry.data["enable_night_mode"] is True

    def test_controller_outage_is_not_a_switch_off(self):
        opt, _, states, _ = night_cycle_optimizer()
        run_cycle(opt)
        set_ac_mode(states, "unavailable")
        run_cycle(opt)
        set_ac_mode(states, "cool")
        run_cycle(opt)
        assert opt.enable_night_mode is True

    def test_off_after_an_outage_still_counts(self):
        opt, _, states, _ = night_cycle_optimizer()
        run_cycle(opt)
        set_ac_mode(states, "unavailable")
        run_cycle(opt)
        set_ac_mode(states, "off")                       # switched off while unreachable
        run_cycle(opt)
        assert opt.enable_night_mode is False

    def test_ac_already_off_at_startup_leaves_night_mode_alone(self):
        opt, _, states, _ = night_cycle_optimizer(ac_state="off")
        run_cycle(opt)                                   # first reading: baseline only
        run_cycle(opt)
        assert opt.enable_night_mode is True

    def test_turned_on_while_the_ac_is_off_lasts_until_the_ac_is_next_switched_off(self):
        opt, _, states, _ = night_cycle_optimizer(ac_state="off")
        run_cycle(opt)
        set_ac_mode(states, "cool")                      # bedtime: AC on
        run_cycle(opt)
        assert opt.enable_night_mode is True
        set_ac_mode(states, "off")                       # morning timer
        run_cycle(opt)
        assert opt.enable_night_mode is False

    def test_failed_save_leaves_night_mode_on(self, caplog):
        opt, _, states, entry = night_cycle_optimizer()
        run_cycle(opt)
        opt.hass.config_entries.async_update_entry = MagicMock(side_effect=RuntimeError("entry not loaded"))
        set_ac_mode(states, "off")
        with caplog.at_level(logging.WARNING):
            run_cycle(opt)
        assert opt.enable_night_mode is True
        assert opt.target_temperature == 21.0
        assert entry.data["enable_night_mode"] is True
        assert any("couldn't be saved" in r.getMessage() for r in caplog.records)

    def test_nothing_saved_when_night_mode_is_off(self):
        opt, _, states, entry = night_cycle_optimizer()
        opt.enable_night_mode = False
        run_cycle(opt)
        set_ac_mode(states, "off")
        run_cycle(opt)
        opt.hass.config_entries.async_update_entry.assert_not_called()

    def test_switch_shows_the_change_after_the_cycle(self):
        from custom_components.smart_aircon_manager.switch import NightModeSwitch

        opt, _, states, entry = night_cycle_optimizer()
        switch = NightModeSwitch(opt, entry)
        run_cycle(opt)
        assert switch.is_on is True
        set_ac_mode(states, "off")
        run_cycle(opt)
        assert switch.is_on is False
        assert switch.extra_state_attributes["restores_target"] is None
