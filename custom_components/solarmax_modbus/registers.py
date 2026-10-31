"""Register map for Solarmax hybrid inverters (Modbus protocol V4.21).

Pure Python on purpose: no Home Assistant imports, so the map can be
unit-tested and cross-checked against the protocol document on its own.

All registers are holding registers read with function 0x03.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, time
import math

# Data types
U16 = "u16"
S16 = "s16"
U32 = "u32"
S32 = "s32"
STR = "str"

_WORDS = {U16: 1, S16: 1, U32: 2, S32: 2}

MAX_READ = 124  # protocol limit for one 0x03 request


@dataclass(frozen=True)
class Field:
    """One value inside a register block."""

    key: str
    address: int
    dtype: str = U16
    scale: float = 1
    length: int = 0  # words, only for STR

    @property
    def words(self) -> int:
        return self.length if self.dtype == STR else _WORDS[self.dtype]


@dataclass(frozen=True)
class Block:
    """A contiguous range read with one request (with a gap fallback)."""

    name: str
    start: int
    count: int
    group: str  # "fast", "slow" or "info"
    fields: tuple[Field, ...] = field(default_factory=tuple)

    def segments(self) -> list[tuple[int, int]]:
        """Contiguous defined ranges, used if the inverter rejects gaps."""
        spans = sorted((f.address, f.address + f.words) for f in self.fields)
        merged: list[list[int]] = []
        for start, end in spans:
            if merged and start <= merged[-1][1]:
                merged[-1][1] = max(merged[-1][1], end)
            else:
                merged.append([start, end])
        return [(s, e - s) for s, e in merged]


def _f(key, address, dtype=U16, scale=1, length=0) -> Field:
    return Field(key, address, dtype, scale, length)


# ---------------------------------------------------------------- fast blocks
INVERTER_BLOCK = Block(
    "inverter",
    0x1001,
    0x104C - 0x1001 + 1,
    "fast",
    (
        _f("phase_a_voltage", 0x1001, U16, 0.1),
        _f("phase_a_current", 0x1002, U16, 0.01),
        _f("phase_a_power", 0x1003, S32, 0.1),
        _f("phase_a_frequency", 0x1005, U16, 0.01),
        _f("phase_b_voltage", 0x1006, U16, 0.1),
        _f("phase_b_current", 0x1007, U16, 0.01),
        _f("phase_b_power", 0x1008, S32, 0.1),
        _f("phase_b_frequency", 0x100A, U16, 0.01),
        _f("phase_c_voltage", 0x100B, U16, 0.1),
        _f("phase_c_current", 0x100C, U16, 0.01),
        _f("phase_c_power", 0x100D, S32, 0.1),
        _f("phase_c_frequency", 0x100F, U16, 0.01),
        _f("pv1_voltage", 0x1010, U16, 0.1),
        _f("pv1_current", 0x1011, U16, 0.01),
        _f("pv1_power", 0x1012, U32, 0.1),
        _f("pv2_voltage", 0x1014, U16, 0.1),
        _f("pv2_current", 0x1015, U16, 0.01),
        _f("pv2_power", 0x1016, U32, 0.1),
        _f("pv3_voltage", 0x1018, U16, 0.1),
        _f("pv3_current", 0x1019, U16, 0.01),
        _f("pv3_power", 0x101A, U32, 0.1),
        _f("inner_temperature", 0x101C, S16, 1),
        _f("inverter_mode", 0x101D, U16),
        _f("error_code", 0x101E, U32),
        _f("pv_total_production_kwh", 0x1021, U32, 1),
        _f("total_generation_time", 0x1023, U32, 1),
        _f("pv_daily_production", 0x1027, U32, 0.001),  # Wh -> kWh
        _f("active_power", 0x1037, S32, 0.1),
        _f("reactive_power", 0x1039, S32, 0.1),
        _f("pv_daily_peak_power", 0x103B, S32, 0.1),
        _f("power_factor", 0x103D, S16, 0.001),
        _f("pv4_voltage", 0x103E, U16, 0.1),
        _f("pv4_current", 0x103F, U16, 0.01),
        _f("pv4_power", 0x1040, U32, 0.1),
        _f("pv_total_production_wh", 0x104C, U16, 1),  # decimals of 0x1021
    ),
)

GRID_BLOCK = Block(
    "grid",
    0x1300,
    0x1363 - 0x1300 + 1,
    "fast",
    (
        _f("grid_power", 0x1300, S32, 0.1),
        _f("grid_power_l2", 0x1302, S32, 0.1),
        _f("grid_power_l3", 0x1304, S32, 0.1),
        _f("total_import", 0x1306, U32, 0.01),  # 10 Wh -> kWh
        _f("total_export", 0x1308, U32, 0.01),
        _f("heavy_load_power", 0x130A, S32, 0.1),
        _f("heavy_load_power_l2", 0x130C, S32, 0.1),
        _f("heavy_load_power_l3", 0x130E, S32, 0.1),
        _f("total_heavy_load_consumption", 0x1310, U32, 0.01),
        _f("grid_voltage", 0x131A, U16, 0.1),
        _f("grid_voltage_l2", 0x131B, U16, 0.1),
        _f("grid_voltage_l3", 0x131C, U16, 0.1),
        _f("grid_current", 0x131D, S32, 0.01),
        _f("grid_current_l2", 0x131F, S32, 0.01),
        _f("grid_current_l3", 0x1321, S32, 0.01),
        _f("heavy_load_voltage", 0x1323, U16, 0.1),
        _f("heavy_load_voltage_l2", 0x1324, U16, 0.1),
        _f("heavy_load_voltage_l3", 0x1325, U16, 0.1),
        _f("heavy_load_current", 0x1326, S32, 0.01),
        _f("heavy_load_current_l2", 0x1328, S32, 0.01),
        _f("heavy_load_current_l3", 0x132A, S32, 0.01),
        _f("daily_import", 0x1332, U32, 0.01),
        _f("daily_export", 0x1334, U32, 0.01),
        _f("daily_heavy_load_consumption", 0x1336, U32, 0.01),
        _f("grid_frequency", 0x1338, U16, 0.01),
        _f("load_voltage", 0x1350, U16, 0.1),  # EPS (backup output) phase R
        _f("load_current", 0x1351, S32, 0.01),
        _f("load_power", 0x1353, S32, 0.1),
        _f("load_frequency", 0x1355, U16, 0.01),
        _f("load_voltage_l2", 0x1356, U16, 0.1),
        _f("load_current_l2", 0x1357, S32, 0.01),
        _f("load_power_l2", 0x1359, S32, 0.1),
        _f("load_voltage_l3", 0x135B, U16, 0.1),
        _f("load_current_l3", 0x135C, S32, 0.01),
        _f("load_power_l3", 0x135E, S32, 0.1),
        _f("daily_load_consumption", 0x1360, U32, 0.01),
        _f("total_load_consumption", 0x1362, U32, 0.01),
    ),
)

BATTERY_BLOCK = Block(
    "battery",
    0x2000,
    0x2013 - 0x2000 + 1,
    "fast",
    (
        _f("battery_soc", 0x2000, U16, 1),
        _f("battery_temperature", 0x2001, S16, 1),
        _f("battery_voltage", 0x2006, U16, 0.1),
        _f("battery_current", 0x2007, S32, 0.01),
        # The document says U32, but real inverters report charging as
        # negative, so it is read as signed.
        _f("battery_power", 0x2009, S32, 0.1),
        _f("battery_daily_charge", 0x200B, U32, 0.01),
        _f("battery_total_charge", 0x200D, U32, 0.01),
        _f("battery_daily_discharge", 0x200F, U32, 0.01),
        _f("battery_total_discharge", 0x2011, U32, 0.01),
        _f("error_message_4", 0x2013, U16),
    ),
)

# ---------------------------------------------------------------- slow blocks
SETTINGS_BLOCK = Block(
    "settings",
    0x2100,
    0x2121 - 0x2100 + 1,
    "slow",
    (
        _f("work_mode", 0x2100),
        _f("schedule_repeat", 0x2101),
        _f("charge_start", 0x2102),
        _f("charge_end", 0x2103),
        _f("discharge_start", 0x2104),
        _f("discharge_end", 0x2105),
        _f("battery_type", 0x2110),
        _f("bms_address", 0x2111),
        _f("lead_acid_capacity", 0x2112),
        _f("lead_acid_stop_discharge_voltage", 0x2113, U16, 0.1),
        _f("lead_acid_stop_charge_voltage", 0x2114, U16, 0.1),
        _f("grid_charge", 0x2115),
        _f("max_grid_charge_power", 0x2116),
        _f("grid_charge_end_soc", 0x2117),
        _f("max_charge_power", 0x2118),
        _f("charge_end_soc", 0x2119),
        _f("max_discharge_power", 0x211A),
        _f("discharge_end_soc", 0x211B),
        _f("off_grid_mode", 0x211C),
        _f("off_grid_output_voltage", 0x211D, U16, 0.1),
        _f("off_grid_output_frequency", 0x211E, U16, 0.01),
        _f("off_grid_start_soc", 0x211F),
        _f("max_discharge_current", 0x2120, U16, 0.01),
        _f("max_charge_current", 0x2121, U16, 0.01),
    ),
)

CLOCK_BLOCK = Block(
    "clock",
    0x3000,
    4,
    "slow",
    (
        _f("clock_year", 0x3000),
        _f("clock_month_day", 0x3001),
        _f("clock_hour_minute", 0x3002),
        _f("clock_second", 0x3003),
    ),
)

METER_BLOCK = Block(
    "meter",
    0x30B0,
    0x30BA - 0x30B0 + 1,
    "slow",
    (
        _f("meter_address", 0x30B0),
        _f("meter_type", 0x30B1),
        _f("meter_direction", 0x30B2),
        _f("power_limit_function", 0x30B3),
        _f("ct_ratio", 0x30B4),
        _f("power_limit_mode", 0x30B5),
        _f("export_limit", 0x30B9, U32, 1),
    ),
)

GRID_CODE_BLOCK = Block(
    "grid_code",
    0x5101,
    0x5104 - 0x5101 + 1,
    "slow",
    (
        _f("regulation_code", 0x5101),
        _f("derating_percent", 0x5104),
    ),
)

CONTROL_BLOCK = Block("control", 0x6001, 1, "slow", (_f("inverter_control", 0x6001),))

# ------------------------------------------------------------ device info
INFO_BLOCK = Block(
    "info",
    0x1A00,
    0x1A78 - 0x1A00 + 1,
    "info",
    (
        _f("model", 0x1A00, STR, length=8),
        _f("serial", 0x1A10, STR, length=8),
        _f("protocol_version", 0x1A18),
        _f("master_version", 0x1A1C, STR, length=3),
        _f("master_build", 0x1A23, STR, length=3),
        _f("slave_version", 0x1A26, STR, length=3),
        _f("slave_build", 0x1A2D, STR, length=3),
        _f("mppt_count", 0x1A3B),
        _f("rated_voltage", 0x1A44, U16, 0.1),
        _f("rated_frequency", 0x1A45, U16, 0.01),
        _f("rated_power", 0x1A46),
        _f("grid_phases", 0x1A48),
        _f("production_type", 0x1A5A),
        _f("ems_version", 0x1A60, STR, length=3),
        _f("ems_build", 0x1A67, STR, length=7),
        # The document prints this address as "0x1A6Fa"; 0x1A6F is the
        # only value that fits between the EMS build date and 0x1A76.
        _f("dcdc_version", 0x1A6F, STR, length=3),
        _f("dcdc_build", 0x1A76, STR, length=3),
    ),
)

FAST_BLOCKS = (INVERTER_BLOCK, GRID_BLOCK, BATTERY_BLOCK)
SLOW_BLOCKS = (SETTINGS_BLOCK, CLOCK_BLOCK, METER_BLOCK, GRID_CODE_BLOCK, CONTROL_BLOCK)
ALL_BLOCKS = FAST_BLOCKS + SLOW_BLOCKS + (INFO_BLOCK,)

FIELDS: dict[str, Field] = {f.key: f for b in ALL_BLOCKS for f in b.fields}
BLOCK_OF: dict[str, Block] = {f.key: b for b in ALL_BLOCKS for f in b.fields}

# Values outside these ranges are physically impossible and come from a
# corrupted read; they are shown as unavailable instead of being published.
_AC_V = (0, 500)
_HZ = (0, 70)
SANE_RANGES: dict[str, tuple[float, float]] = {
    "battery_soc": (0, 100),
    "inner_temperature": (-40, 150),
    "battery_temperature": (-40, 150),
    "battery_voltage": (0, 1000),
    "power_factor": (-1, 1),
    **{f"pv{i}_voltage": (0, 1500) for i in range(1, 5)},
    **{k: _AC_V for k in ("phase_a_voltage", "phase_b_voltage", "phase_c_voltage", "grid_voltage",
                          "grid_voltage_l2", "grid_voltage_l3", "load_voltage", "load_voltage_l2",
                          "load_voltage_l3", "heavy_load_voltage", "heavy_load_voltage_l2", "heavy_load_voltage_l3")},
    **{k: _HZ for k in ("phase_a_frequency", "phase_b_frequency", "phase_c_frequency", "grid_frequency",
                        "load_frequency")},
}


def sanitize(values: dict) -> int:
    """Blank out impossible values in place. Returns how many were removed."""
    removed = 0
    for key, (low, high) in SANE_RANGES.items():
        value = values.get(key)
        if value is not None and not low <= value <= high:
            values[key] = None
            removed += 1
    return removed


# ------------------------------------------------------------------ enums
INVERTER_MODES = {0: "initial", 1: "standby", 3: "on_grid", 4: "off_grid", 5: "fault", 9: "shutdown"}
FAULT_MODE = 5

WORK_MODES = {0: "self_use", 1: "feed_in_priority", 2: "time_based", 3: "backup", 4: "battery_discharge"}
SCHEDULE_REPEAT = {0: "once", 1: "every_day"}
BATTERY_TYPES = {
    0: "unavailable", 1: "lead_acid", 2: "pylon", 3: "dyness", 4: "aobo",
    5: "uz", 6: "vestmoods", 7: "xinyi",
}
METER_TYPES = {
    0: "unknown", 1: "gavazzi_em340", 2: "chint_dtsu666", 3: "acrel_dtsf1352",
    4: "lovato_dmg210", 5: "g2000", 6: "gavazzi_et112", 7: "ksem", 8: "chint_ddsu666",
}
METER_DIRECTIONS = {0: "positive", 1: "negative"}
POWER_LIMIT_FUNCTIONS = {0: "disabled", 1: "external_device", 2: "ct_sensor", 3: "digital_meter"}
CT_RATIOS = {
    0: "unknown", 1: "ratio_1000", 2: "ratio_2000", 3: "ratio_2500", 4: "ratio_3000",
    5: "ratio_4000", 6: "ratio_5000", 7: "ratio_6000", 8: "ratio_10000",
}
POWER_LIMIT_MODES = {0: "ct_on_grid", 1: "ct_on_load"}
PRODUCTION_TYPES = {
    0: "on_grid", 1: "ac_couple", 2: "hybrid", 3: "hybrid_smart_load", 4: "ac_couple_smart_load",
}

REGULATION_CODES = {
    0x01: "AU (AS/NZS 4777.2/.3)", 0x02: "DE (VDE 0126-1-1/A1)", 0x03: "TW (TW GRID)",
    0x04: "DE (VDE-AR-N 4105)", 0x05: "JP (JETGR0002-1-2.0)", 0x06: "IT (CEI 0-21)",
    0x07: "SE (Sweden grid)", 0x08: "UK (G98)", 0x09: "US (UL)", 0x0A: "TH (PEA)",
    0x0B: "SE (Sweden grid 2007)", 0x0C: "NL (EN50549-1 2019)", 0x0D: "TH (MEA)",
    0x0E: "CN (NB/T 32004)", 0x0F: "IN (IEC61727)", 0x10: "AU (AS/NZS 4777.2:2015)",
    0x11: "NZ (AS/NZS 4777.2:2015)", 0x12: "MX (IEEE1547)", 0x13: "UA (VDE-AR-N 4105)",
    0x14: "TW (CNS 15382:2018)", 0x15: "DE (VDE0126-1-1/08.13)", 0x16: "BR (ABNT NBR16149 2013)",
    0x17: "CZ (EN 50160)", 0x18: "UK (G99 Type A)", 0x19: "PT (EN50438)",
    0x1A: "ES (RD1699 / RD413)", 0x1B: "ES (RD661 / PO12.2)", 0x1C: "IT (CEI 0-21 ACEA)",
    0x1D: "DE (VDE-AR-N 4105:2018)", 0x1E: "BR (IEC61727)", 0x1F: "EU (EN50549-1:2019)",
    0x20: "BE (C10/11)", 0x21: "PL (EN50438 2013)", 0x22: "DE (VDE4110:2018)",
    0x23: "EU (EN50549-2:2019)", 0x24: "IT (CEI 0-16)", 0x25: "ZA (NRS097-2-1)",
    0x26: "GR (VDE0126 mainland)", 0x27: "GR (VDE0126 islands)", 0x28: "JO (IRR-DCC MV 2015)",
    0x29: "ES (UNE206007 / UNE206006)", 0x2A: "AU (AS4777.2:2015 South)", 0x2B: "UK (G99 Type B)",
    0x2C: "JO (IRR-TIC 2015)", 0x2D: "CZ (EN50549-1)", 0x2E: "AT (TOR Type A)",
    0x2F: "CY (Cyprus 2019)", 0x30: "MX (IEEE1547:2014)", 0x31: "CL (Chile 2021)",
    0x32: "FR (UTE C15-712-1)", 0x33: "CH (NA/EEA A2)", 0x34: "CH (NA/EEA B2)",
    0x35: "FR (UTE C15-712-1 island 50 Hz)", 0x36: "FR (UTE C15-712-1 island 60 Hz)",
    0x37: "FI (VJV Type A)", 0x38: "FI (VJV Type B)", 0x39: "NO (EN50549-1)",
    0x3A: "PL (NC RFG Type A)", 0x3B: "PL (NC RFG Type B)", 0x3C: "BE (C10/11 MV)",
    0x3D: "AT (TOR Type B)", 0x3E: "IL (IS 4777)", 0x3F: "DK1 (Type A & B LV)",
    0x40: "DK1 (Type B MV)", 0x41: "DK2 (Type A & B LV)", 0x42: "DK2 (Type B MV)",
    0xFFFF: "Not defined",
}

# ------------------------------------------------------------------ faults
CRITICAL = "critical"
WARNING = "warning"
INFO = "info"

# Error Code register 0x101E (U32), bit -> (name, severity)
ERROR_CODE_FAULTS: dict[int, tuple[str, str]] = {
    0: ("Grid over-voltage", INFO), 1: ("Grid under-voltage", INFO),
    2: ("Grid power absent", WARNING), 3: ("Grid over-frequency", INFO),
    4: ("Grid under-frequency", INFO), 5: ("PV over-voltage", CRITICAL),
    6: ("PV insulation fault", CRITICAL), 7: ("Leakage current fault", CRITICAL),
    8: ("Output power limited", INFO), 9: ("Control power low", WARNING),
    10: ("PV string fault", WARNING), 11: ("PV voltage too low", WARNING),
    12: ("Weak sunlight", INFO), 13: ("Grid abnormal", INFO),
    14: ("Arc fault detected", CRITICAL), 15: ("Grid voltage high (10-min avg)", INFO),
    16: ("DC current in AC output", WARNING), 17: ("Grid relay fault", CRITICAL),
    18: ("Switched off remotely", INFO), 19: ("Inverter over-temperature", WARNING),
    20: ("Leakage sensor fault", CRITICAL), 21: ("PV string reversed", CRITICAL),
    22: ("System type mismatch", WARNING), 23: ("Fan locked", WARNING),
    24: ("DC bus under-voltage", WARNING), 25: ("DC bus over-voltage", CRITICAL),
    26: ("Internal communication error", WARNING), 27: ("Firmware mismatch", WARNING),
    28: ("Settings memory (EEPROM) error", WARNING), 29: ("Self-check mismatch", WARNING),
    30: ("Inverter hardware fault", CRITICAL), 31: ("Boost (PV input) fault", CRITICAL),
}

# Error Message 4 register 0x2013 (U16), bit -> (name, severity)
MESSAGE_4_FAULTS: dict[int, tuple[str, str]] = {
    0: ("Battery not detected", CRITICAL), 1: ("Battery over-voltage", INFO),
    2: ("Battery under-voltage", WARNING), 3: ("Battery discharge over-current", WARNING),
    4: ("BMS communication lost", CRITICAL), 5: ("Backup output overload", CRITICAL),
    6: ("DC current abnormal", WARNING), 7: ("Backup output short circuit", CRITICAL),
    8: ("Neutral fault", CRITICAL), 9: ("Live/neutral reversed", CRITICAL),
    10: ("Backup capacitor wear", WARNING), 11: ("BMS communication error", WARNING),
    12: ("Internal comms lost (EMS-DSP)", WARNING), 13: ("Internal comms lost (DSP-DC/DC)", WARNING),
    14: ("Reserved bit 14", WARNING), 15: ("Reserved bit 15", WARNING),
}

GRID_ABSENT_BIT = 2


@dataclass(frozen=True)
class ActiveFault:
    code: str  # "c7" = error code bit 7, "m1" = message 4 bit 1
    name: str
    severity: str


def active_faults(error_code: int | None, message_4: int | None) -> list[ActiveFault]:
    """Decode both fault registers into a list of active faults."""
    out: list[ActiveFault] = []
    if error_code is not None:
        for bit in range(32):
            if error_code >> bit & 1:
                name, sev = ERROR_CODE_FAULTS[bit]
                out.append(ActiveFault(f"c{bit}", name, sev))
    if message_4 is not None:
        for bit in range(16):
            if message_4 >> bit & 1:
                name, sev = MESSAGE_4_FAULTS[bit]
                out.append(ActiveFault(f"m{bit}", name, sev))
    return out


# ------------------------------------------------------------------ decoding
def _decimals(scale: float) -> int:
    return 0 if scale >= 1 else max(0, -math.floor(math.log10(scale) + 1e-9))


def decode_field(fld: Field, regs: list[int], offset: int) -> int | float | str:
    """Decode one field from raw registers starting at offset."""
    if fld.dtype == STR:
        raw = bytearray()
        for word in regs[offset : offset + fld.length]:
            raw += bytes((word >> 8 & 0xFF, word & 0xFF))
        return raw.split(b"\x00", 1)[0].decode("ascii", "replace").strip()
    if fld.dtype in (U16, S16):
        value = regs[offset]
        if fld.dtype == S16 and value >= 0x8000:
            value -= 0x10000
    else:
        value = regs[offset] << 16 | regs[offset + 1]
        if fld.dtype == S32 and value >= 0x80000000:
            value -= 0x100000000
    if fld.scale == 1:
        return value
    return round(value * fld.scale, _decimals(fld.scale))


def decode_block(block: Block, start: int, regs: list[int]) -> dict:
    """Decode every field of block covered by regs (read from start)."""
    out = {}
    end = start + len(regs)
    for fld in block.fields:
        if fld.address >= start and fld.address + fld.words <= end:
            out[fld.key] = decode_field(fld, regs, fld.address - start)
    return out


def decode_hhmm(value: int | None) -> time | None:
    """High byte hour, low byte minute."""
    if value is None:
        return None
    hour, minute = value >> 8, value & 0xFF
    if hour > 23 or minute > 59:
        return None
    return time(hour, minute)


def encode_hhmm(value: time) -> int:
    return value.hour << 8 | value.minute


def decode_clock(data: dict) -> datetime | None:
    """Inverter clock from 0x3000-0x3003 (naive local time)."""
    try:
        year = data["clock_year"]
        md, hm, sec = data["clock_month_day"], data["clock_hour_minute"], data["clock_second"]
        return datetime(year, md >> 8, md & 0xFF, hm >> 8, hm & 0xFF, sec >> 8)
    except (KeyError, TypeError, ValueError):
        return None


def encode_clock(now: datetime) -> list[int]:
    return [now.year, now.month << 8 | now.day, now.hour << 8 | now.minute, now.second << 8]


def to_raw(fld: Field, value: float) -> list[int]:
    """Convert an engineering value to the register words to write."""
    raw = int(round(value / fld.scale))
    if fld.dtype in (U16, U32) and raw < 0:
        raise ValueError(f"{fld.key} cannot be negative")
    if fld.dtype == U16:
        if raw > 0xFFFF:
            raise ValueError(f"{fld.key} out of range")
        return [raw]
    if fld.dtype == S16:
        return [raw & 0xFFFF]
    if fld.dtype == U32 and raw > 0xFFFFFFFF:
        raise ValueError(f"{fld.key} out of range")
    raw &= 0xFFFFFFFF
    return [raw >> 16, raw & 0xFFFF]


# ------------------------------------------------------------------ controls
# Only the everyday settings are writable. Installer settings and the
# grid-code / protection registers (0x5000-0x5118 apart from derating) are
# deliberately never written by this integration.
WRITABLE_KEYS = frozenset({
    "work_mode", "schedule_repeat", "charge_start", "charge_end",
    "discharge_start", "discharge_end", "grid_charge", "max_grid_charge_power",
    "grid_charge_end_soc", "max_charge_power", "charge_end_soc",
    "max_discharge_power", "discharge_end_soc", "off_grid_mode",
    "off_grid_start_soc", "max_discharge_current", "max_charge_current",
    "export_limit", "derating_percent", "inverter_control",
})
CLOCK_ADDRESS = 0x3000  # written as one 4-register block by the clock button
