"""Tests for the per-room "In Use" switches (v3.4.0).

A room switched out of use keeps its configuration, but its zone closes and
it stops counting toward every AC decision until it's switched back in.
"""
from __future__ import annotations

import asyncio
import sys
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))
sys.path.insert(0, str(Path(__file__).parent))

from test_night_mode_temp_drop import FakeEntry, entry_data, fake_hass  # noqa: E402
from test_v302_fixes import hvac_commands, make_cycle_optimizer, run_cycle  # noqa: E402

ROOMS = (("Bed", 23.0, None), ("Guest", 23.0, None), ("Living", 23.0, None))
HOT_GUEST = (("Bed", 23.0, None), ("Guest", 29.0, None), ("Living", 23.0, None))


def cover_positions(calls):
    positions = {}
    for domain, service, data in calls:
        if domain == "cover" and service == "set_cover_position":
            positions[data["entity_id"]] = data["position"]
    return positions


class TestOutOfUse:
    def test_out_of_use_room_is_closed_and_ignored(self):
        # In use, the hot guest room starts the AC
        opt, calls, _ = make_cycle_optimizer(rooms=HOT_GUEST, ac_state="off")
        run_cycle(opt)
        assert "cool" in hvac_commands(calls)
        # Out of use it doesn't, and its zone closes
        opt, calls, _ = make_cycle_optimizer(rooms=HOT_GUEST, ac_state="off", excluded_rooms=["Guest"])
        result = run_cycle(opt)
        assert hvac_commands(calls) == []
        assert cover_positions(calls)["cover.guest"] == 0
        assert result["room_states"]["Guest"]["closed_off"] is True
        assert result["room_states"]["Guest"]["current_temperature"] == 29.0   # still reported
        assert result["excluded_rooms"] == ["Guest"]
        assert result["closed_off_rooms"] == ["Guest"]
        assert result["night_mode_closed_rooms"] == []

    def test_uses_the_closed_off_position(self):
        opt, calls, _ = make_cycle_optimizer(rooms=ROOMS, excluded_rooms=["Guest"], night_mode_closed_position=10)
        run_cycle(opt)
        assert cover_positions(calls)["cover.guest"] == 10

    def test_climate_temperature_leaves_out_of_use_rooms_out(self):
        from custom_components.smart_aircon_manager.climate import AirconAIClimate

        opt, _, _ = make_cycle_optimizer(rooms=HOT_GUEST, excluded_rooms=["Guest"])
        entity = object.__new__(AirconAIClimate)
        entity.coordinator = type("Coordinator", (), {"data": run_cycle(opt)})()
        assert entity.current_temperature == 23.0

    def test_unknown_rooms_are_dropped(self):
        opt, _, _ = make_cycle_optimizer(rooms=ROOMS, excluded_rooms=["Ghost"])
        assert opt.excluded_rooms == []

    def test_every_room_out_of_use_manages_them_all(self):
        opt, calls, _ = make_cycle_optimizer(
            rooms=HOT_GUEST, ac_state="off", excluded_rooms=["Bed", "Guest", "Living"],
        )
        result = run_cycle(opt)
        assert result["closed_off_rooms"] == []
        assert "cool" in hvac_commands(calls)        # the hot guest room counts again

    def test_critical_emergency_opens_an_out_of_use_room(self):
        opt, _, _ = make_cycle_optimizer(rooms=ROOMS, excluded_rooms=["Guest"])
        with patch.object(type(opt), "_critical_emergency_rooms", return_value={"Guest"}):
            result = run_cycle(opt)
        assert result["closed_off_rooms"] == []
        assert result["recommendations"]["Guest"] > 0


class TestWithNightMode:
    def test_out_of_use_night_room_stays_closed(self):
        opt, _, _ = make_cycle_optimizer(
            rooms=ROOMS, excluded_rooms=["Guest"], enable_night_mode=True, night_mode_rooms=["Bed", "Guest"],
        )
        result = run_cycle(opt)
        assert result["closed_off_rooms"] == ["Guest", "Living"]
        assert result["night_mode_closed_rooms"] == ["Living"]
        assert result["night_mode_active"] is True

    def test_night_mode_does_nothing_when_all_its_rooms_are_out_of_use(self):
        opt, _, _ = make_cycle_optimizer(
            rooms=ROOMS, excluded_rooms=["Guest"], enable_night_mode=True, night_mode_rooms=["Guest"],
        )
        result = run_cycle(opt)
        assert result["night_mode_active"] is False
        assert result["closed_off_rooms"] == ["Guest"]   # Bed and Living stay managed


class TestSwitch:
    @staticmethod
    def _switch(room="Guest", excluded=(), coordinator=None):
        from custom_components.smart_aircon_manager.switch import RoomInUseSwitch

        opt, calls, states = make_cycle_optimizer(rooms=ROOMS, excluded_rooms=list(excluded))
        entry = FakeEntry(entry_data(excluded_rooms=list(excluded)))
        switch = RoomInUseSwitch(opt, entry, room, coordinator)
        switch.hass = fake_hass(entry)
        switch.async_write_ha_state = MagicMock()
        return switch, opt, entry, calls, states

    def test_switch_takes_a_room_out_and_back(self):
        coordinator = MagicMock()
        coordinator.async_request_refresh = AsyncMock()
        switch, opt, entry, _, _ = self._switch(coordinator=coordinator)
        assert switch.is_on is True
        asyncio.run(switch.async_turn_off())
        assert switch.is_on is False
        assert switch.icon == "mdi:door-closed"
        assert opt.excluded_rooms == ["Guest"]
        assert entry.data["excluded_rooms"] == ["Guest"]
        coordinator.async_update_listeners.assert_called_once()
        coordinator.async_request_refresh.assert_awaited_once()
        asyncio.run(switch.async_turn_on())
        assert switch.is_on is True
        assert opt.excluded_rooms == []
        assert entry.data["excluded_rooms"] == []

    def test_the_last_room_in_use_cannot_be_taken_out(self):
        from homeassistant.exceptions import HomeAssistantError

        switch, opt, entry, _, _ = self._switch(room="Guest", excluded=("Bed", "Living"))
        with pytest.raises(HomeAssistantError):
            asyncio.run(switch.async_turn_off())
        assert opt.excluded_rooms == ["Bed", "Living"]
        assert entry.data["excluded_rooms"] == ["Bed", "Living"]

    def test_failed_save_leaves_the_room_alone(self):
        switch, opt, _, _, _ = self._switch()
        switch.hass.config_entries.async_update_entry = MagicMock(side_effect=RuntimeError("boom"))
        asyncio.run(switch.async_turn_off())
        assert opt.excluded_rooms == []
        switch.async_write_ha_state.assert_called()

    def test_back_in_use_reopens_on_the_next_cycle(self):
        switch, opt, _, calls, states = self._switch(excluded=("Guest",))
        run_cycle(opt)
        assert cover_positions(calls)["cover.guest"] == 0
        states["cover.guest"].attributes["current_position"] = 0
        calls.clear()
        asyncio.run(switch.async_turn_on())
        run_cycle(opt)
        assert cover_positions(calls).get("cover.guest", 0) > 0

    def test_naming(self):
        switch, _, _, _, _ = self._switch(room="Guest Room")
        assert switch.has_entity_name is True
        assert switch.name == "Guest Room In Use"
        assert switch.unique_id == "entry1_guest_room_in_use"

    def test_one_switch_per_room_is_set_up(self):
        from custom_components.smart_aircon_manager import switch as switch_platform
        from custom_components.smart_aircon_manager.const import DOMAIN

        opt, _, _ = make_cycle_optimizer(rooms=ROOMS)
        hass = MagicMock()
        hass.data = {DOMAIN: {"entry1": {"optimizer": opt, "coordinator": MagicMock()}}}
        added = []
        asyncio.run(switch_platform.async_setup_entry(hass, FakeEntry({}), added.extend))
        names = sorted(e.name for e in added if isinstance(e, switch_platform.RoomInUseSwitch))
        assert names == ["Bed In Use", "Guest In Use", "Living In Use"]


class TestRoomChanges:
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
    def _data(excluded, rooms=("Bed", "Guest", "Living")):
        return entry_data(
            excluded_rooms=list(excluded),
            night_mode_rooms=[],
            room_configs=[
                {"room_name": r, "temperature_sensor": f"sensor.{r.lower()}", "cover_entity": f"cover.{r.lower()}"}
                for r in rooms
            ],
        )

    def test_removing_a_room_drops_it_from_out_of_use(self):
        flow, entry = self._flow(self._data(["Guest"]))
        asyncio.run(flow.async_step_remove_room({"room_to_remove": "Guest"}))
        assert entry.data["excluded_rooms"] == []

    def test_removing_the_last_room_in_use_puts_the_others_back(self):
        flow, entry = self._flow(self._data(["Guest", "Living"]))
        asyncio.run(flow.async_step_remove_room({"room_to_remove": "Bed"}))
        assert entry.data["excluded_rooms"] == []

    def test_renaming_keeps_a_room_out_of_use(self):
        flow, entry = self._flow(self._data(["Guest"]))
        flow._room_to_edit = "Guest"
        flow._validate_entities = MagicMock(return_value={})
        asyncio.run(flow.async_step_edit_room({
            "room_name": "Spare Room", "temperature_sensor": "sensor.guest", "cover_entity": "cover.guest",
        }))
        assert entry.data["excluded_rooms"] == ["Spare Room"]
