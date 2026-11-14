"""Warnings Home Assistant logged against this integration.

* reading manifest.json inside the event loop (device info);
* "Cover entity ... not found" for every room while Home Assistant starts.
"""
from __future__ import annotations

import asyncio
import logging
import sys
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))
sys.path.insert(0, str(Path(__file__).parent))

from homeassistant.core import CoreState  # noqa: E402

import custom_components.smart_aircon_manager as integration  # noqa: E402
from test_v302_fixes import make_cycle_optimizer  # noqa: E402


@pytest.fixture
def fresh_version(monkeypatch):
    monkeypatch.setattr(integration, "_CACHED_VERSION", None)


class TestDeviceInfoVersion:
    def test_device_info_never_reads_a_file(self, fresh_version):
        entry = SimpleNamespace(entry_id="e1")
        read = MagicMock(return_value='{"version": "9.9.9"}')
        with patch("pathlib.Path.read_text", read):
            info = integration.get_device_info(entry)
        assert not read.called
        assert info["sw_version"] == "unknown"

    def test_version_comes_from_the_loaded_integration(self, fresh_version):
        loaded = SimpleNamespace(version="3.6.0")
        with patch.object(integration, "async_get_integration", AsyncMock(return_value=loaded)):
            asyncio.run(integration._async_cache_version(MagicMock()))
        assert integration.get_device_info(SimpleNamespace(entry_id="e1"))["sw_version"] == "3.6.0"

    def test_lookup_failure_falls_back_to_unknown(self, fresh_version):
        with patch.object(integration, "async_get_integration", AsyncMock(side_effect=RuntimeError("boom"))):
            asyncio.run(integration._async_cache_version(MagicMock()))
        assert integration.get_device_info(SimpleNamespace(entry_id="e1"))["sw_version"] == "unknown"

    def test_cached_after_the_first_lookup(self, fresh_version):
        lookup = AsyncMock(return_value=SimpleNamespace(version="3.6.0"))
        with patch.object(integration, "async_get_integration", lookup):
            asyncio.run(integration._async_cache_version(MagicMock()))
            asyncio.run(integration._async_cache_version(MagicMock()))
        assert lookup.await_count == 1


def missing_cover_optimizer(hass_state):
    opt, calls, states = make_cycle_optimizer()
    del states["cover.bed"]
    opt.hass.state = hass_state
    return opt, calls, states


def not_found_warnings(caplog):
    return [r for r in caplog.records if r.levelno >= logging.WARNING and "not found" in r.getMessage()]


class TestMissingCover:
    def test_no_warning_while_home_assistant_is_starting(self, caplog):
        opt, _, _ = missing_cover_optimizer(CoreState.starting)
        with caplog.at_level(logging.DEBUG):
            delivered = asyncio.run(opt._apply_recommendations({"Bed": 40}))
        assert "Bed" in delivered          # nothing a retry can change
        assert not_found_warnings(caplog) == []
        assert any("not found" in r.getMessage() for r in caplog.records)   # still at debug

    def test_warned_once_after_startup(self, caplog):
        opt, _, _ = missing_cover_optimizer(CoreState.running)
        with caplog.at_level(logging.WARNING):
            for _ in range(3):
                asyncio.run(opt._apply_recommendations({"Bed": 40}))
        assert len(not_found_warnings(caplog)) == 1

    def test_warned_again_after_it_was_back(self, caplog):
        from test_v302_fixes import FakeState

        opt, _, states = missing_cover_optimizer(CoreState.running)
        with caplog.at_level(logging.WARNING):
            asyncio.run(opt._apply_recommendations({"Bed": 40}))
            states["cover.bed"] = FakeState("open", {"current_position": 40})
            asyncio.run(opt._apply_recommendations({"Bed": 40}))
            del states["cover.bed"]
            asyncio.run(opt._apply_recommendations({"Bed": 40}))
        assert len(not_found_warnings(caplog)) == 2


class TestClimateTemperatureApi:
    """Home Assistant 2026.11 moved climate temperatures to native_ names and
    warns about entities that still provide the old ones (they stop working
    in 2027.11). The entity provides both, so it works on 2024.12 and up."""

    @staticmethod
    def _entity(target=22.0):
        from homeassistant.util.unit_system import METRIC_SYSTEM

        from custom_components.smart_aircon_manager.climate import AirconAIClimate

        coordinator = MagicMock()
        coordinator.data = {
            "room_states": {
                "Bed": {"current_temperature": 23.0},
                "Living": {"current_temperature": 24.0},
                "Media": {"current_temperature": 30.0, "closed_off": True},
            }
        }
        optimizer = MagicMock()
        optimizer.target_temperature = target
        entry = SimpleNamespace(entry_id="e1", data={"hvac_mode": "cool"})
        entity = AirconAIClimate(coordinator, optimizer, entry)
        entity.hass = MagicMock()
        entity.hass.config.units = METRIC_SYSTEM
        return entity

    def test_no_deprecation_warning_when_the_class_is_created(self, caplog):
        import importlib

        from custom_components.smart_aircon_manager import climate

        with caplog.at_level(logging.WARNING):
            importlib.reload(climate)
        assert [r.getMessage() for r in caplog.records if "deprecated" in r.getMessage()] == []

    def test_state_attributes_show_the_temperatures(self):
        attrs = self._entity(target=22.0).state_attributes
        assert attrs["current_temperature"] == 23.5     # closed-off rooms left out
        assert attrs["temperature"] == 22.0

    def test_native_and_legacy_names_agree(self):
        entity = self._entity(target=21.5)
        assert entity.native_current_temperature == entity.current_temperature == 23.5
        assert entity.native_target_temperature == entity.target_temperature == 21.5
