"""Upgrade path: values restored from v1.0 or the YAML modbus sensor."""

from __future__ import annotations

from homeassistant.core import HomeAssistant, State
from homeassistant.util import dt as dt_util
from pytest_homeassistant_custom_component.common import mock_restore_cache_with_extra_data

from conftest import make_entry
from sim_inverter import SimInverter, _s32


async def _setup(hass, sim):
    entry = make_entry(sim)
    entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    return entry


async def test_upgrade_from_yaml_value_never_dips(hass: HomeAssistant, sim: SimInverter) -> None:
    """Old YAML sensor stored 12630 (rounded); the inverter now reads 12629.65."""
    sim.regs.update(dict(zip((0x1306, 0x1307), _s32(1262965), strict=True)))
    mock_restore_cache_with_extra_data(
        hass,
        [(State("sensor.solarmax_total_import", "12630"), {"native_value": 12630, "native_unit_of_measurement": "kWh"})],
    )
    entry = await _setup(hass, sim)
    assert hass.states.get("sensor.solarmax_total_import").state == "12630.0"
    sim.regs.update(dict(zip((0x1306, 0x1307), _s32(1263010), strict=True)))
    await entry.runtime_data.async_refresh()
    await hass.async_block_till_done()
    assert hass.states.get("sensor.solarmax_total_import").state == "12630.1"
    await hass.config_entries.async_unload(entry.entry_id)
    await hass.async_block_till_done()


async def test_guard_state_survives_restart(hass: HomeAssistant, sim: SimInverter) -> None:
    guard = {"published": 12700.0, "cur": [69.53, 12630.47, dt_util.utcnow().timestamp() - 60],
             "prev": None, "rejected": 2, "rebased": 1}
    mock_restore_cache_with_extra_data(
        hass,
        [(State("sensor.solarmax_total_import", "12700.0"),
          {"native_value": 12700.0, "native_unit_of_measurement": "kWh", "guard": guard})],
    )
    entry = await _setup(hass, sim)
    # the earlier rebase offset is kept: 12630.47 raw + 69.53 = 12700.0
    assert hass.states.get("sensor.solarmax_total_import").state == "12700.0"
    assert entry.runtime_data.guards["total_import"].rebased == 1
    await hass.config_entries.async_unload(entry.entry_id)
    await hass.async_block_till_done()
