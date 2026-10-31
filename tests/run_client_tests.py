"""Standalone tests of the Modbus client + decoder against the simulator.

Run: python tests/run_client_tests.py
"""

from __future__ import annotations

import asyncio
import sys
from datetime import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "tests"))

from custom_components.solarmax_modbus import registers as R  # noqa: E402
from custom_components.solarmax_modbus.modbus import (  # noqa: E402
    SolarmaxConnectionError,
    SolarmaxModbusClient,
    SolarmaxModbusError,
)
from sim_inverter import SimInverter  # noqa: E402

FAILS: list[str] = []


def check(cond: bool, msg: str) -> None:
    print(("  ok   " if cond else "  FAIL ") + msg)
    if not cond:
        FAILS.append(msg)


async def read_all(client: SolarmaxModbusClient) -> dict:
    data: dict = {}
    for block in R.ALL_BLOCKS:
        values, _raw = await client.read_block(block)
        data.update(values)
    return data


async def scenario(strict: bool, framer: str) -> None:
    print(f"\n== strict={strict} framer={framer}")
    sim = SimInverter(strict=strict, framer=framer)
    port = await sim.start()
    client = SolarmaxModbusClient("127.0.0.1", port, 1, "rtuovertcp" if framer == "rtu" else "tcp", timeout=2)
    try:
        data = await read_all(client)
        expected = {
            "phase_a_voltage": 255.3, "phase_a_current": 30.79, "phase_a_power": 7938.0,
            "pv1_power": 2999.1, "pv3_voltage": 355.4, "inner_temperature": 52, "inverter_mode": 3,
            "error_code": 0, "pv_total_production_kwh": 31124, "pv_total_production_wh": 836,
            "pv_daily_production": 31.46, "power_factor": 1.0, "grid_power": -7203.4,
            "total_import": 12630.47, "total_export": 18741.22, "grid_current": -28.3,
            "load_power": 734.6, "total_load_consumption": 20717.12, "battery_soc": 99,
            "battery_power": -153.0, "battery_current": 2.56, "battery_total_discharge": 2370.08,
            "work_mode": 0, "max_discharge_current": 120.0, "off_grid_output_frequency": 50.0,
            "export_limit": 10000, "regulation_code": 15, "derating_percent": 100,
            "model": "SM-HY10K", "serial": "SM2309123456", "ems_build": "20231105100530",
            "mppt_count": 3, "rated_power": 10000, "grid_phases": 1, "dcdc_build": "231101",
        }
        for key, val in expected.items():
            check(data.get(key) == val, f"{key} = {data.get(key)!r} (expected {val!r})")
        check(R.decode_hhmm(data["discharge_start"]) == time(18, 16), "discharge_start decodes to 18:16")
        clock = R.decode_clock(data)
        check(clock is not None and (clock.hour, clock.minute) == (13, 30), f"clock {clock}")
        reads = [r for r in sim.requests if r[0] == 3]
        if strict:
            check(len(reads) > len(R.ALL_BLOCKS), f"strict mode fell back to segments ({len(reads)} reads)")
            n_before = len(reads)
            await read_all(client)
            n_second = len([r for r in sim.requests if r[0] == 3]) - n_before
            check(n_second == sum(len(b.segments()) for b in R.ALL_BLOCKS), "second pass goes straight to segments")
        else:
            check(len(reads) == len(R.ALL_BLOCKS), f"one request per block ({len(reads)} reads)")

        # writes
        await client.write_registers(0x2100, [3])
        check(sim.regs[0x2100] == 3, "write single register (work mode -> backup)")
        await client.write_registers(0x30B9, R.to_raw(R.FIELDS["export_limit"], 5000))
        check(sim.regs[0x30B9] == 0 and sim.regs[0x30BA] == 5000, "write U32 export limit with 0x10")
        try:
            await client.write_registers(0x2119, [150])
            check(False, "out-of-range SOC should be rejected")
        except SolarmaxModbusError as err:
            check(err.code == 4, f"out-of-range write rejected with code 4: {err}")
        try:
            await client.write_registers(0x5002, [5100])
            check(False, "write to grid-code register should be rejected by sim")
        except SolarmaxModbusError as err:
            check(err.code == 4, "write to protected register rejected")
        # no response -> connection error, then recovery
        sim.silent = True
        try:
            await client.read_registers(0x2000, 1)
            check(False, "silent inverter should time out")
        except SolarmaxConnectionError:
            check(True, "silent inverter raises SolarmaxConnectionError")
        sim.silent = False
        regs = await client.read_registers(0x2000, 1)
        check(regs == [99], "client recovers after a timeout")
    finally:
        client.close()
        await sim.stop()


async def main() -> None:
    # pure decoder checks
    check(R.to_raw(R.FIELDS["max_charge_current"], 85.5) == [8550], "to_raw scales 0.01 A")
    check(R.encode_hhmm(time(22, 20)) == 0x1614, "encode 22:20")
    check(R.decode_hhmm(0x1900) is None, "invalid hour decodes to None")
    faults = R.active_faults(128 + 4, 2)
    check([f.code for f in faults] == ["c2", "c7", "m1"], f"fault decode {faults}")
    for b in R.ALL_BLOCKS:
        last = max(f.address + f.words for f in b.fields)
        check(b.count <= R.MAX_READ and b.start + b.count >= last, f"block {b.name} covers its fields ({b.count} regs)")
    for strict in (False, True):
        for framer in ("socket", "rtu"):
            await scenario(strict, framer)
    print("\nFAILURES:" if FAILS else "\nALL CLIENT TESTS PASSED", *FAILS, sep="\n  ")


asyncio.run(main())
