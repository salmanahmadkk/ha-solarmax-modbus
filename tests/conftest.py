"""Fixtures: a simulated inverter on localhost and a configured entry."""

from __future__ import annotations

from collections.abc import AsyncGenerator
import sys
from pathlib import Path
from unittest.mock import patch

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent))

from homeassistant.core import HomeAssistant  # noqa: E402
from pytest_homeassistant_custom_component.common import MockConfigEntry  # noqa: E402

from custom_components.solarmax_modbus.const import (  # noqa: E402
    CONF_CONNECTION_TYPE,
    CONF_DEVICE_ADDRESS,
    CONF_ENABLE_CONTROLS,
    CONF_SCAN_INTERVAL,
    CONF_SETTINGS_INTERVAL,
    DOMAIN,
)
from sim_inverter import SimInverter  # noqa: E402


@pytest.fixture(autouse=True)
def auto_enable_custom_integrations(enable_custom_integrations):
    yield


@pytest.fixture(autouse=True)
def fast_timing():
    with (
        patch("custom_components.solarmax_modbus.modbus.DEFAULT_TIMEOUT", 0.5),
        patch("custom_components.solarmax_modbus.coordinator.WRITE_MIN_INTERVAL", 0),
    ):
        yield


@pytest.fixture
def strict() -> bool:
    return False


@pytest.fixture
def framer() -> str:
    return "socket"


@pytest.fixture
async def sim(socket_enabled, strict, framer) -> AsyncGenerator[SimInverter]:
    inverter = SimInverter(strict=strict, framer=framer)
    await inverter.start()
    yield inverter
    await inverter.stop()


def make_entry(sim: SimInverter, controls: bool = True, framer: str = "socket") -> MockConfigEntry:
    return MockConfigEntry(
        domain=DOMAIN,
        title="Solarmax",
        unique_id="SM2309123456",
        data={
            "host": "127.0.0.1",
            "port": sim.port,
            CONF_DEVICE_ADDRESS: 1,
            CONF_CONNECTION_TYPE: "rtuovertcp" if framer == "rtu" else "tcp",
        },
        options={CONF_SCAN_INTERVAL: 10, CONF_SETTINGS_INTERVAL: 60, CONF_ENABLE_CONTROLS: controls},
    )


@pytest.fixture
async def entry(hass: HomeAssistant, sim: SimInverter, framer) -> AsyncGenerator[MockConfigEntry]:
    config_entry = make_entry(sim, framer=framer)
    config_entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(config_entry.entry_id)
    await hass.async_block_till_done()
    for _ in range(2):  # a brand-new counter publishes after 3 consistent polls
        await config_entry.runtime_data.async_refresh()
        await hass.async_block_till_done()
    yield config_entry
    if config_entry.state.recoverable:
        await hass.config_entries.async_unload(config_entry.entry_id)
        await hass.async_block_till_done()
