"""The repair_energy_statistics service against a real recorder database."""

from __future__ import annotations

from datetime import timedelta

import pytest

from homeassistant.components.recorder import get_instance
from homeassistant.components.recorder.models import StatisticMeanType
from homeassistant.components.recorder.statistics import async_import_statistics, statistics_during_period
from homeassistant.core import HomeAssistant
from homeassistant.util import dt as dt_util
from pytest_homeassistant_custom_component.components.recorder.common import async_wait_recording_done

from conftest import make_entry
from sim_inverter import SimInverter


@pytest.fixture(autouse=True)
def auto_enable_custom_integrations(recorder_mock, enable_custom_integrations):
    """Recorder must start before hass in this module."""
    yield


async def _setup(hass, sim):
    entry = make_entry(sim)
    entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    return entry


async def test_repair_service_finds_and_fixes_spike(hass: HomeAssistant, sim: SimInverter) -> None:
    entry = await _setup(hass, sim)
    statistic_id = "sensor.house_grid_import_total"
    start = dt_util.utcnow().replace(minute=0, second=0, microsecond=0) - timedelta(hours=6)
    sums = [0, 1, 2, 12619, 12620, 12621]  # +12617 kWh spike in hour 3
    async_import_statistics(
        hass,
        {"has_sum": True, "mean_type": StatisticMeanType.NONE, "name": None, "source": "recorder",
         "statistic_id": statistic_id, "unit_class": "energy", "unit_of_measurement": "kWh"},
        [{"start": start + timedelta(hours=i), "state": 12600 + s, "sum": s} for i, s in enumerate(sums)],
    )
    await async_wait_recording_done(hass)

    preview = await hass.services.async_call(
        "solarmax_modbus", "repair_energy_statistics",
        {"entity_id": [statistic_id], "start": start - timedelta(hours=1)}, blocking=True, return_response=True,
    )
    spikes = preview["statistics"][statistic_id]
    assert preview["dry_run"] is True and len(spikes) == 1
    assert spikes[0]["change"] == 12617 and spikes[0]["action"] == "would subtract"

    await hass.services.async_call(
        "solarmax_modbus", "repair_energy_statistics",
        {"entity_id": [statistic_id], "start": start - timedelta(hours=1), "dry_run": False},
        blocking=True, return_response=True,
    )
    await async_wait_recording_done(hass)
    rows = await get_instance(hass).async_add_executor_job(
        statistics_during_period, hass, start - timedelta(hours=1), None, {statistic_id}, "hour", None, {"change"}
    )
    changes = [round(r["change"], 3) for r in rows[statistic_id]]
    assert max(changes) <= 1, changes
    assert sum(changes) == 4  # 5 real hours of ~1 kWh minus the first baseline row

    again = await hass.services.async_call(
        "solarmax_modbus", "repair_energy_statistics",
        {"entity_id": [statistic_id], "start": start - timedelta(hours=1)}, blocking=True, return_response=True,
    )
    assert again["statistics"][statistic_id] == []
    await hass.config_entries.async_unload(entry.entry_id)
    await hass.async_block_till_done()
