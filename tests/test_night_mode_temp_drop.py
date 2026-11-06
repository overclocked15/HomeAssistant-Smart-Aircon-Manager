"""Tests for night mode's optional temperature drop (v3.3.0).

The drop is applied once each time night mode turns on (switch or options
page); the target it replaced is stored and restored when night mode turns
off. Adjustments made during the night stand until then.
"""
from __future__ import annotations

import asyncio
import sys
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

sys.path.insert(0, str(Path(__file__).parent.parent))
sys.path.insert(0, str(Path(__file__).parent))

from custom_components.smart_aircon_manager.night_mode import night_mode_entry_data  # noqa: E402
from test_v302_fixes import make_cycle_optimizer, run_cycle  # noqa: E402

ON, OFF = True, False


def entry_data(**overrides):
    data = {
        "target_temperature": 23.0,
        "night_mode_temp_drop": 2.0,
        "enable_night_mode": False,
        "night_mode_rooms": ["Bed"],
        "room_configs": [
            {"room_name": "Bed", "temperature_sensor": "sensor.bed", "cover_entity": "cover.bed"},
            {"room_name": "Living", "temperature_sensor": "sensor.living", "cover_entity": "cover.living"},
        ],
    }
    data.update(overrides)
    return data


class FakeEntry:
    """Config entry whose data is replaced by async_update_entry, like HA's."""

    def __init__(self, data, entry_id="entry1"):
        self.data = data
        self.entry_id = entry_id


def fake_hass(entry):
    hass = MagicMock()

    def update_entry(target_entry, data=None, **_kwargs):
        target_entry.data = dict(data)
        return True

    hass.config_entries.async_update_entry = MagicMock(side_effect=update_entry)
    hass.config_entries.async_reload = AsyncMock()
    hass.config_entries.async_get_known_entry = lambda entry_id: entry
    return hass


class TestTransitions:
    def test_turning_on_drops_once_and_remembers_the_target(self):
        new = night_mode_entry_data(entry_data(), ON)
        assert new["enable_night_mode"] is True
        assert new["target_temperature"] == 21.0
        assert new["night_mode_saved_target"] == 23.0

    def test_turning_on_while_on_changes_nothing(self):
        on = night_mode_entry_data(entry_data(), ON)
        again = night_mode_entry_data(on, ON)
        assert again["target_temperature"] == 21.0
        assert again["night_mode_saved_target"] == 23.0

    def test_turning_off_restores_even_after_a_manual_change(self):
        on = night_mode_entry_data(entry_data(), ON)
        on["target_temperature"] = 22.0          # warmed it up during the night
        off = night_mode_entry_data(on, OFF)
        assert off["target_temperature"] == 23.0
        assert "night_mode_saved_target" not in off
        assert off["enable_night_mode"] is False

    def test_no_compounding_night_after_night(self):
        data = entry_data()
        targets = []
        for _ in range(3):
            data = night_mode_entry_data(data, ON)
            targets.append(data["target_temperature"])
            data = night_mode_entry_data(data, OFF)
            targets.append(data["target_temperature"])
        assert targets == [21.0, 23.0] * 3

    def test_zero_drop_leaves_the_target_alone(self):
        new = night_mode_entry_data(entry_data(night_mode_temp_drop=0), ON)
        assert new["target_temperature"] == 23.0
        assert "night_mode_saved_target" not in new
        off = night_mode_entry_data(new, OFF)
        assert off["target_temperature"] == 23.0

    def test_drop_is_clamped_to_the_minimum_target(self):
        new = night_mode_entry_data(entry_data(target_temperature=11.0), ON)
        assert new["target_temperature"] == 10.0
        assert night_mode_entry_data(new, OFF)["target_temperature"] == 11.0

    def test_half_degree_drop(self):
        assert night_mode_entry_data(entry_data(night_mode_temp_drop=1.5), ON)["target_temperature"] == 21.5

    def test_live_target_wins_over_stored_target(self):
        new = night_mode_entry_data(entry_data(target_temperature=23.0), ON, current_target=24.0)
        assert new["target_temperature"] == 22.0
        assert new["night_mode_saved_target"] == 24.0

    def test_turning_off_while_off_changes_nothing(self):
        data = entry_data()
        assert night_mode_entry_data(data, OFF)["target_temperature"] == 23.0


class TestSwitch:
    @staticmethod
    def _switch(data):
        from custom_components.smart_aircon_manager.switch import NightModeSwitch

        opt, _, _ = make_cycle_optimizer(
            rooms=(("Bed", 23.0, None), ("Living", 23.0, None)),
            target=float(data["target_temperature"]),
            enable_night_mode=data["enable_night_mode"], night_mode_rooms=["Bed"],
        )
        entry = FakeEntry(data)
        switch = NightModeSwitch(opt, entry)
        switch.hass = fake_hass(entry)
        switch.async_write_ha_state = MagicMock()
        return switch, opt, entry

    def test_switch_on_lowers_target_and_off_restores_it(self):
        switch, opt, entry = self._switch(entry_data())
        asyncio.run(switch.async_turn_on())
        assert opt.enable_night_mode is True
        assert opt.target_temperature == 21.0
        assert entry.data["target_temperature"] == 21.0
        assert entry.data["night_mode_saved_target"] == 23.0
        assert switch.extra_state_attributes["restores_target"] == 23.0
        assert switch.extra_state_attributes["temperature_drop"] == 2.0

        # Warmer during the night, as the climate card does it
        opt.target_temperature = 22.0
        entry.data = {**entry.data, "target_temperature": 22.0}
        asyncio.run(switch.async_turn_on())       # automation fires again: no second drop
        assert opt.target_temperature == 22.0

        asyncio.run(switch.async_turn_off())
        assert opt.enable_night_mode is False
        assert opt.target_temperature == 23.0
        assert entry.data["target_temperature"] == 23.0
        assert "night_mode_saved_target" not in entry.data
        assert switch.extra_state_attributes["restores_target"] is None

    def test_restart_during_the_night_still_restores(self):
        # Entry data as left by switching on, then Home Assistant restarted
        data = entry_data(enable_night_mode=True, target_temperature=21.0, night_mode_saved_target=23.0)
        switch, opt, entry = self._switch(data)
        assert opt.target_temperature == 21.0
        asyncio.run(switch.async_turn_off())
        assert opt.target_temperature == 23.0

    def test_dropped_target_drives_the_next_cycle(self):
        switch, opt, _ = self._switch(entry_data())
        asyncio.run(switch.async_turn_on())
        result = run_cycle(opt)
        assert result["effective_target_temperature"] == 21.0

    def test_no_drop_configured_keeps_target(self):
        switch, opt, entry = self._switch(entry_data(night_mode_temp_drop=0.0))
        asyncio.run(switch.async_turn_on())
        assert opt.target_temperature == 23.0
        assert "night_mode_saved_target" not in entry.data


class TestOptionsPage:
    @staticmethod
    def _flow(data):
        from custom_components.smart_aircon_manager.config_flow import OptionsFlowHandler

        entry = FakeEntry(data)
        flow = OptionsFlowHandler(entry)
        flow.hass = fake_hass(entry)
        flow.handler = entry.entry_id
        flow.flow_id = "flow1"
        flow.context = {}
        return flow, entry

    @staticmethod
    def _submit(flow, **fields):
        user_input = {"night_mode_rooms": ["Bed"], "night_mode_closed_position": 0}
        user_input.update(fields)
        return asyncio.run(flow.async_step_night_mode(user_input))

    def test_form_shows_the_drop_field(self):
        flow, _ = self._flow(entry_data())
        form = asyncio.run(flow.async_step_night_mode(None))
        assert "night_mode_temp_drop" in [str(k) for k in form["data_schema"].schema]

    def test_ticking_night_mode_on_applies_the_submitted_drop(self):
        flow, entry = self._flow(entry_data(night_mode_temp_drop=0.0))
        result = self._submit(flow, enable_night_mode=True, night_mode_temp_drop=3.0)
        assert result["type"] == "create_entry"
        assert entry.data["target_temperature"] == 20.0
        assert entry.data["night_mode_saved_target"] == 23.0
        flow.hass.config_entries.async_reload.assert_awaited_once()

    def test_unticking_night_mode_restores(self):
        flow, entry = self._flow(entry_data(
            enable_night_mode=True, target_temperature=22.0, night_mode_saved_target=23.0,
        ))
        self._submit(flow, enable_night_mode=False, night_mode_temp_drop=2.0)
        assert entry.data["target_temperature"] == 23.0
        assert "night_mode_saved_target" not in entry.data

    def test_changing_the_drop_while_on_does_not_move_the_target(self):
        flow, entry = self._flow(entry_data(
            enable_night_mode=True, target_temperature=21.0, night_mode_saved_target=23.0,
        ))
        self._submit(flow, enable_night_mode=True, night_mode_temp_drop=4.0)
        assert entry.data["target_temperature"] == 21.0
        assert entry.data["night_mode_saved_target"] == 23.0
        assert entry.data["night_mode_temp_drop"] == 4.0


class TestReviewHardening:
    """Fixes from the v3.3.0 pre-release bug check."""

    @staticmethod
    def _switch(data, hass=None, coordinator=None):
        from custom_components.smart_aircon_manager.switch import NightModeSwitch

        opt, _, _ = make_cycle_optimizer(
            rooms=(("Bed", 23.0, None), ("Living", 23.0, None)),
            target=float(data["target_temperature"]),
            enable_night_mode=data["enable_night_mode"], night_mode_rooms=["Bed"],
        )
        entry = FakeEntry(data)
        switch = NightModeSwitch(opt, entry, coordinator)
        switch.hass = hass or fake_hass(entry)
        switch.async_write_ha_state = MagicMock()
        return switch, opt, entry

    def test_failed_save_changes_nothing_and_cannot_compound(self):
        switch, opt, entry = self._switch(entry_data())
        working = switch.hass
        broken = fake_hass(entry)
        broken.config_entries.async_update_entry = MagicMock(side_effect=RuntimeError("entry not loaded"))
        switch.hass = broken
        asyncio.run(switch.async_turn_on())
        assert opt.enable_night_mode is False
        assert opt.target_temperature == 23.0
        assert entry.data["target_temperature"] == 23.0
        switch.async_write_ha_state.assert_called()      # state re-shown as unchanged
        # Saving works again: one clean night, no drift
        switch.hass = working
        asyncio.run(switch.async_turn_on())
        asyncio.run(switch.async_turn_off())
        asyncio.run(switch.async_turn_on())
        assert opt.target_temperature == 21.0
        asyncio.run(switch.async_turn_off())
        assert opt.target_temperature == 23.0

    def test_feature_switch_failed_save_leaves_feature_alone(self):
        from custom_components.smart_aircon_manager.switch import OptimizerFeatureSwitch

        opt, _, _ = make_cycle_optimizer()
        entry = FakeEntry({"enable_efficiency_mode": False})
        switch = OptimizerFeatureSwitch(
            opt, entry, "enable_efficiency_mode", "enable_efficiency_mode", "Efficient Operation", "mdi:leaf",
        )
        switch.hass = fake_hass(entry)
        switch.hass.config_entries.async_update_entry = MagicMock(side_effect=RuntimeError("boom"))
        switch.async_write_ha_state = MagicMock()
        asyncio.run(switch.async_turn_on())
        assert opt.enable_efficiency_mode is False

    def test_climate_card_updates_immediately(self):
        coordinator = MagicMock()
        coordinator.async_request_refresh = AsyncMock()
        switch, _, _ = self._switch(entry_data(), coordinator=coordinator)
        asyncio.run(switch.async_turn_on())
        coordinator.async_update_listeners.assert_called_once()
        coordinator.async_request_refresh.assert_awaited_once()

    def test_removing_the_last_night_room_turns_night_mode_off_and_restores(self):
        flow, entry = TestOptionsPage._flow(entry_data(
            enable_night_mode=True, target_temperature=21.0, night_mode_saved_target=23.0,
        ))
        asyncio.run(flow.async_step_remove_room({"room_to_remove": "Bed"}))
        assert entry.data["night_mode_rooms"] == []
        assert entry.data["enable_night_mode"] is False
        assert entry.data["target_temperature"] == 23.0
        assert "night_mode_saved_target" not in entry.data

    def test_removing_another_night_room_keeps_night_mode_on(self):
        flow, entry = TestOptionsPage._flow(entry_data(
            enable_night_mode=True, night_mode_rooms=["Bed", "Living"],
            target_temperature=21.0, night_mode_saved_target=23.0,
        ))
        asyncio.run(flow.async_step_remove_room({"room_to_remove": "Living"}))
        assert entry.data["enable_night_mode"] is True
        assert entry.data["target_temperature"] == 21.0

    def test_stale_night_mode_form_does_not_reverse_the_switch(self):
        flow, entry = TestOptionsPage._flow(entry_data())
        asyncio.run(flow.async_step_night_mode(None))        # opened at 21:55, shows "off"
        entry.data = night_mode_entry_data(entry.data, ON)   # 22:00 automation turns it on
        TestOptionsPage._submit(flow, enable_night_mode=False, night_mode_temp_drop=2.0)
        assert entry.data["enable_night_mode"] is True
        assert entry.data["target_temperature"] == 21.0
        assert entry.data["night_mode_saved_target"] == 23.0

    def test_tick_survives_a_validation_error(self):
        flow, entry = TestOptionsPage._flow(entry_data())
        asyncio.run(flow.async_step_night_mode(None))
        retry = asyncio.run(flow.async_step_night_mode(
            {"enable_night_mode": True, "night_mode_rooms": [], "night_mode_temp_drop": 2.0}
        ))
        assert retry["errors"] == {"night_mode_rooms": "night_mode_rooms_required"}
        TestOptionsPage._submit(flow, enable_night_mode=True, night_mode_temp_drop=2.0)
        assert entry.data["enable_night_mode"] is True
        assert entry.data["target_temperature"] == 21.0

    def test_clearing_the_drop_box_turns_the_drop_off(self):
        flow, entry = TestOptionsPage._flow(entry_data(night_mode_temp_drop=2.0))
        form = asyncio.run(flow.async_step_night_mode(None))
        # The frontend leaves a cleared box out; HA validates against the schema
        validated = form["data_schema"](
            {"enable_night_mode": False, "night_mode_rooms": ["Bed"], "night_mode_closed_position": 0}
        )
        assert "night_mode_temp_drop" not in validated
        asyncio.run(flow.async_step_night_mode(validated))
        assert entry.data["night_mode_temp_drop"] == 0.0

    def test_untouched_drop_box_keeps_its_value(self):
        flow, entry = TestOptionsPage._flow(entry_data(night_mode_temp_drop=2.0))
        TestOptionsPage._submit(flow, enable_night_mode=False, night_mode_temp_drop=2.0)
        assert entry.data["night_mode_temp_drop"] == 2.0

    def test_stale_settings_form_does_not_overwrite_the_target(self):
        flow, entry = TestOptionsPage._flow(entry_data(
            enable_night_mode=True, target_temperature=21.0, night_mode_saved_target=23.0,
        ))
        asyncio.run(flow.async_step_settings(None))           # opened during the night: shows 21
        entry.data = night_mode_entry_data(entry.data, OFF)   # morning: back to 23
        asyncio.run(flow.async_step_settings({"target_temperature": 21.0, "temperature_deadband": 0.5}))
        assert entry.data["target_temperature"] == 23.0
        assert entry.data["temperature_deadband"] == 0.5

    def test_settings_form_target_change_still_applies(self):
        flow, entry = TestOptionsPage._flow(entry_data())
        asyncio.run(flow.async_step_settings(None))           # shows 23
        asyncio.run(flow.async_step_settings({"target_temperature": 24.0}))
        assert entry.data["target_temperature"] == 24.0
