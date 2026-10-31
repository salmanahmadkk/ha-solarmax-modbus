"""End-to-end tests: real integration + real client + simulated inverter."""

from __future__ import annotations

from datetime import timedelta


import pytest

from homeassistant import config_entries
from homeassistant.config_entries import ConfigEntryState
from homeassistant.const import STATE_UNAVAILABLE
from homeassistant.core import HomeAssistant
from homeassistant.data_entry_flow import FlowResultType
from homeassistant.exceptions import ServiceValidationError
from homeassistant.helpers import entity_registry as er
from homeassistant.util import dt as dt_util
from pytest_homeassistant_custom_component.common import async_capture_events

from custom_components.solarmax_modbus.const import DOMAIN, EVENT_FAULT
from custom_components.solarmax_modbus.diagnostics import async_get_config_entry_diagnostics

from conftest import make_entry
from sim_inverter import SimInverter, _s32

# Every entity ID of the user's existing YAML Modbus setup.
LEGACY_IDS = [
    "load_voltage", "load_current", "load_power", "battery_daily_charge", "battery_total_charge",
    "battery_daily_discharge", "battery_total_discharge", "battery_soc", "battery_voltage",
    "battery_current", "battery_power", "total_import", "total_export", "grid_frequency",
    "pv_total_production", "pv_daily_production", "daily_load_consumption", "total_load_consumption",
    "daily_export", "daily_import", "daily_heavy_load_consumption", "total_heavy_load_consumption",
    "total_generation_time", "phase_a_voltage", "phase_a_current", "phase_a_power", "phase_a_frequency",
    "pv1_voltage", "pv1_current", "pv1_power", "pv2_voltage", "pv2_current", "pv2_power",
    "pv3_voltage", "pv3_current", "pv3_power", "inner_temperature", "inverter_mode", "error_code",
    "power_factor", "error_message_4", "active_power", "reactive_power", "pv_daily_peak_power",
]


def st(hass: HomeAssistant, entity_id: str):
    state = hass.states.get(entity_id)
    assert state is not None, f"{entity_id} missing"
    return state


async def refresh(hass: HomeAssistant, entry) -> None:
    await entry.runtime_data.async_refresh()
    await hass.async_block_till_done()


# ------------------------------------------------------------------ setup
async def test_legacy_entity_ids_and_values(hass: HomeAssistant, entry, sim: SimInverter) -> None:
    assert entry.state is ConfigEntryState.LOADED
    for suffix in LEGACY_IDS:
        state = st(hass, f"sensor.solarmax_{suffix}")
        assert state.state != STATE_UNAVAILABLE, suffix
    expect = {
        "sensor.solarmax_phase_a_power": "7938.0", "sensor.solarmax_battery_power": "-153.0",
        "sensor.solarmax_battery_soc": "99", "sensor.solarmax_total_import": "12630.47",
        "sensor.solarmax_total_export": "18741.22", "sensor.solarmax_pv_total_production": "31124.836",
        "sensor.solarmax_pv_daily_production": "31.46", "sensor.solarmax_grid_power": "-7203.4",
        "sensor.solarmax_pv_power": "8929.4", "sensor.solarmax_status": "on_grid",
        "sensor.solarmax_faults": "No faults", "sensor.solarmax_inverter_mode": "3",
        "sensor.solarmax_power_factor": "1.0", "sensor.solarmax_battery_type": "pylon",
        "sensor.solarmax_regulation_code": None,  # renamed, see below
    }
    expect.pop("sensor.solarmax_regulation_code")
    for entity_id, value in expect.items():
        assert st(hass, entity_id).state == value, entity_id
    assert st(hass, "sensor.solarmax_grid_standard").state == "IN (IEC61727)"
    assert st(hass, "binary_sensor.solarmax_fault").state == "off"
    assert st(hass, "binary_sensor.solarmax_grid_available").state == "on"
    # single-phase, 3 MPPT: no phase B/C, no L2/L3, no PV4
    for missing in ("sensor.solarmax_phase_b_voltage", "sensor.solarmax_grid_power_l2", "sensor.solarmax_pv4_power"):
        assert hass.states.get(missing) is None, missing
    # energy sensors are usable by the Energy dashboard
    total = st(hass, "sensor.solarmax_total_import")
    assert total.attributes["state_class"] == "total_increasing"
    assert total.attributes["unit_of_measurement"] == "kWh"
    # device info from the identity block
    ent = er.async_get(hass).async_get("sensor.solarmax_total_import")
    assert ent.unique_id == "SM2309123456_total_import"
    # 3 fast blocks + 5 slow + info = 9 reads for setup, then 3 per poll
    reads = [r for r in sim.requests if r[0] == 3]
    assert len(reads) == 9 + 2 * 3
    await refresh(hass, entry)
    assert len([r for r in sim.requests if r[0] == 3]) == 18


async def test_controls_write_the_right_registers(hass: HomeAssistant, entry, sim: SimInverter) -> None:
    async def call(domain, service, entity_id, **data):
        await hass.services.async_call(domain, service, {"entity_id": entity_id, **data}, blocking=True)

    assert st(hass, "select.solarmax_work_mode").state == "self_use"
    await call("select", "select_option", "select.solarmax_work_mode", option="backup")
    assert sim.regs[0x2100] == 3
    assert st(hass, "select.solarmax_work_mode").state == "backup"

    await call("number", "set_value", "number.solarmax_max_discharge_power", value=4500)
    assert sim.regs[0x211A] == 4500
    await call("number", "set_value", "number.solarmax_discharge_cut_off_soc", value=35)
    assert sim.regs[0x211B] == 35
    await call("number", "set_value", "number.solarmax_max_charge_current", value=85)
    assert sim.regs[0x2121] == 8500
    await call("number", "set_value", "number.solarmax_export_limit", value=5000)
    assert (sim.regs[0x30B9], sim.regs[0x30BA]) == (0, 5000)
    await call("number", "set_value", "number.solarmax_output_derating", value=80)
    assert sim.regs[0x5104] == 80

    assert st(hass, "time.solarmax_discharge_start_time").state == "18:16:00"
    await call("time", "set_value", "time.solarmax_discharge_start_time", time="18:30:00")
    assert sim.regs[0x2104] == 0x121E

    await call("switch", "turn_on", "switch.solarmax_grid_charging")
    assert sim.regs[0x2115] == 1
    assert st(hass, "switch.solarmax_inverter_power").state == "on"
    await call("switch", "turn_off", "switch.solarmax_inverter_power")
    assert sim.regs[0x6001] == 1
    assert st(hass, "switch.solarmax_inverter_power").state == "off"

    await call("select", "select_option", "select.solarmax_schedule_repeat", option="once")
    assert sim.regs[0x2101] == 0

    before = len(sim.writes)
    await call("number", "set_value", "number.solarmax_max_charge_power", value=6000)  # unchanged
    assert len(sim.writes) == before, "unchanged value must not be written"

    with pytest.raises(ServiceValidationError):
        await call("number", "set_value", "number.solarmax_charge_stop_soc", value=150)

    now = dt_util.now()
    await call("button", "press", "button.solarmax_sync_inverter_clock")
    assert sim.regs[0x3000] == now.year
    assert sim.regs[0x3001] == now.month << 8 | now.day

    # nothing outside the everyday controls was ever written
    allowed = {0x2100, 0x2101, 0x2104, 0x2115, 0x211A, 0x211B, 0x2121, 0x30B9, 0x5104, 0x6001, 0x3000}
    assert {addr for addr, _ in sim.writes} <= allowed


async def test_rejected_write_shows_error(hass: HomeAssistant, entry, sim: SimInverter) -> None:
    sim.writable.discard(0x2118)
    from homeassistant.exceptions import HomeAssistantError

    with pytest.raises(HomeAssistantError, match="rejected"):
        await hass.services.async_call(
            "number", "set_value", {"entity_id": "number.solarmax_max_charge_power", "value": 3000}, blocking=True
        )


async def test_faults_and_events(hass: HomeAssistant, entry, sim: SimInverter) -> None:
    events = async_capture_events(hass, EVENT_FAULT)
    sim.regs.update({0x101D: 5, 0x101E: 0, 0x101F: 128, 0x2013: 2})  # Fault mode, leakage, battery OV
    await refresh(hass, entry)
    assert st(hass, "sensor.solarmax_status").state == "fault"
    faults = st(hass, "sensor.solarmax_faults")
    assert faults.state == "Leakage current fault, Battery over-voltage"
    assert [a["code"] for a in faults.attributes["active"]] == ["c7", "m1"]
    assert st(hass, "binary_sensor.solarmax_fault").state == "on"
    assert sorted((e.data["code"], e.data["state"]) for e in events) == [("c7", "started"), ("m1", "started")]
    assert events[0].data["device_id"] is not None

    sim.regs.update({0x101D: 4, 0x101F: 4, 0x2013: 0})  # off-grid, grid absent
    await refresh(hass, entry)
    assert st(hass, "binary_sensor.solarmax_grid_available").state == "off"
    assert st(hass, "binary_sensor.solarmax_fault").state == "off"
    new = [(e.data["code"], e.data["state"]) for e in events[2:]]
    assert sorted(new) == [("c2", "started"), ("c7", "cleared"), ("m1", "cleared")]


async def test_lifetime_counters_never_drop(hass: HomeAssistant, entry, sim: SimInverter) -> None:
    sim.regs.update(dict(zip((0x1306, 0x1307), _s32(0), strict=True)))  # glitch: total import reads 0
    await refresh(hass, entry)
    assert st(hass, "sensor.solarmax_total_import").state == "12630.47"
    sim.regs.update(dict(zip((0x1306, 0x1307), _s32(1263000), strict=True)))  # lower than before
    await refresh(hass, entry)
    assert st(hass, "sensor.solarmax_total_import").state == "12630.47"
    sim.regs.update(dict(zip((0x1306, 0x1307), _s32(1263100), strict=True)))  # real increase
    await refresh(hass, entry)
    assert st(hass, "sensor.solarmax_total_import").state == "12631.0"
    # a daily counter dropping to 0 in the middle of the day is a glitch ...
    sim.regs.update(dict(zip((0x1332, 0x1333), _s32(0), strict=True)))
    await refresh(hass, entry)
    assert st(hass, "sensor.solarmax_daily_import").state == "7.27"


async def test_daily_counter_resets_at_midnight(hass: HomeAssistant, sim: SimInverter) -> None:
    from unittest.mock import patch

    base = dt_util.now().replace(hour=23, minute=40, second=0, microsecond=0)
    clock = {"t": base}
    with patch(
        "custom_components.solarmax_modbus.sensor._clock",
        side_effect=lambda: (clock["t"].timestamp(), clock["t"]),
    ):
        entry = make_entry(sim)
        entry.add_to_hass(hass)
        await hass.config_entries.async_setup(entry.entry_id)
        await hass.async_block_till_done()
        assert st(hass, "sensor.solarmax_daily_import").state == "7.27"
        clock["t"] = base + timedelta(minutes=25)  # 00:05 next day
        sim.regs.update(dict(zip((0x1332, 0x1333), _s32(3), strict=True)))
        await refresh(hass, entry)
        assert st(hass, "sensor.solarmax_daily_import").state == "0.03"
        await hass.config_entries.async_unload(entry.entry_id)
        await hass.async_block_till_done()


async def test_all_zero_block_is_ignored(hass: HomeAssistant, entry, sim: SimInverter) -> None:
    for addr in range(0x1300, 0x1364):
        sim.regs[addr] = 0
    await refresh(hass, entry)
    # grid block values become unavailable instead of 0 ...
    assert st(hass, "sensor.solarmax_grid_power").state == STATE_UNAVAILABLE
    assert st(hass, "sensor.solarmax_total_import").state == STATE_UNAVAILABLE
    # ... other blocks keep working
    assert st(hass, "sensor.solarmax_battery_soc").state == "99"
    assert entry.runtime_data.rejected_blocks == 1


async def test_impossible_values_are_blanked(hass: HomeAssistant, entry, sim: SimInverter) -> None:
    sim.regs[0x2000] = 250  # SOC 250 %
    await refresh(hass, entry)
    assert st(hass, "sensor.solarmax_battery_soc").state == STATE_UNAVAILABLE
    assert st(hass, "sensor.solarmax_battery_voltage").state == "55.0"


async def test_offline_inverter_goes_unavailable_and_recovers(hass: HomeAssistant, entry, sim: SimInverter) -> None:
    sim.silent = True
    await refresh(hass, entry)
    assert st(hass, "sensor.solarmax_battery_soc").state == STATE_UNAVAILABLE
    assert st(hass, "sensor.solarmax_total_import").state == STATE_UNAVAILABLE
    sim.silent = False
    await refresh(hass, entry)
    assert st(hass, "sensor.solarmax_battery_soc").state == "99"
    assert st(hass, "sensor.solarmax_total_import").state == "12630.47"


@pytest.mark.parametrize("strict", [True])
async def test_strict_inverter_rejecting_gaps(hass: HomeAssistant, entry, sim: SimInverter) -> None:
    assert st(hass, "sensor.solarmax_total_load_consumption").state == "20717.12"
    assert st(hass, "select.solarmax_work_mode").state == "self_use"
    diag = await async_get_config_entry_diagnostics(hass, entry)
    assert "grid" in diag["segmented_blocks"]
    assert diag["info"]["serial"] == "**REDACTED**"


@pytest.mark.parametrize("framer", ["rtu"])
async def test_rtu_over_tcp(hass: HomeAssistant, entry, sim: SimInverter) -> None:
    assert st(hass, "sensor.solarmax_battery_power").state == "-153.0"
    await hass.services.async_call(
        "select", "select_option", {"entity_id": "select.solarmax_work_mode", "option": "time_based"}, blocking=True
    )
    assert sim.regs[0x2100] == 2


async def test_read_only_option_removes_controls(hass: HomeAssistant, entry, sim: SimInverter) -> None:
    assert hass.states.get("number.solarmax_export_limit") is not None
    result = await hass.config_entries.options.async_init(entry.entry_id)
    result = await hass.config_entries.options.async_configure(
        result["flow_id"], {"scan_interval": 15, "settings_interval": 120, "enable_controls": False}
    )
    assert result["type"] is FlowResultType.CREATE_ENTRY
    await hass.async_block_till_done()
    assert entry.state is ConfigEntryState.LOADED
    state = hass.states.get("number.solarmax_export_limit")
    assert state is None or state.state == STATE_UNAVAILABLE
    assert st(hass, "sensor.solarmax_battery_soc").state == "99"


# ------------------------------------------------------------- config flow
async def test_config_flow(hass: HomeAssistant, sim: SimInverter) -> None:
    result = await hass.config_entries.flow.async_init(DOMAIN, context={"source": config_entries.SOURCE_USER})
    assert result["type"] is FlowResultType.FORM
    bad = {"name": "Solarmax", "host": "127.0.0.1", "port": 1, "device_address": 1, "connection_type": "tcp"}
    result = await hass.config_entries.flow.async_configure(result["flow_id"], bad)
    assert result["errors"] == {"base": "cannot_connect"}
    good = {**bad, "port": sim.port}
    result = await hass.config_entries.flow.async_configure(result["flow_id"], good)
    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert result["title"] == "Solarmax"
    assert result["result"].unique_id == "SM2309123456"
    await hass.async_block_till_done()
    assert hass.states.get("sensor.solarmax_total_import") is not None

    # same inverter again -> abort
    result = await hass.config_entries.flow.async_init(DOMAIN, context={"source": config_entries.SOURCE_USER})
    result = await hass.config_entries.flow.async_configure(result["flow_id"], good)
    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == "already_configured"
    entry = hass.config_entries.async_entries(DOMAIN)[0]
    await hass.config_entries.async_unload(entry.entry_id)
    await hass.async_block_till_done()


async def test_setup_retries_when_offline(hass: HomeAssistant, sim: SimInverter) -> None:
    sim.silent = True
    entry = make_entry(sim)
    entry.add_to_hass(hass)
    await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    assert entry.state is ConfigEntryState.SETUP_RETRY
    await hass.config_entries.async_unload(entry.entry_id)
    await hass.async_block_till_done()


async def test_reconfigure_changes_port(hass: HomeAssistant, entry, sim: SimInverter) -> None:
    second = SimInverter()
    await second.start()
    try:
        result = await entry.start_reconfigure_flow(hass)
        assert result["type"] is FlowResultType.FORM
        result = await hass.config_entries.flow.async_configure(
            result["flow_id"], {"host": "127.0.0.1", "port": second.port, "device_address": 1, "connection_type": "tcp"}
        )
        assert result["type"] is FlowResultType.ABORT
        assert result["reason"] == "reconfigure_successful"
        await hass.async_block_till_done()
        assert entry.data["port"] == second.port
        assert entry.state is ConfigEntryState.LOADED
        assert st(hass, "sensor.solarmax_battery_soc").state == "99"
    finally:
        await hass.config_entries.async_unload(entry.entry_id)
        await hass.async_block_till_done()
        await second.stop()
