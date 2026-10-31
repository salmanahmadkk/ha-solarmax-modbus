"""Minimal Modbus TCP / RTU-over-TCP inverter simulator for tests.

Implements function codes 0x03, 0x06 and 0x10 with real exception codes,
an optional strict mode (undefined addresses -> exception 2), and RO
protection (writes to read-only registers -> exception 4).
"""

from __future__ import annotations

import asyncio
import struct
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "custom_components" / "solarmax_modbus"))
import registers as R  # noqa: E402


def _s32(v: int) -> list[int]:
    v &= 0xFFFFFFFF
    return [v >> 16, v & 0xFFFF]


def _str(text: str, words: int) -> list[int]:
    b = text.encode().ljust(words * 2, b"\x00")[: words * 2]
    return [b[i] << 8 | b[i + 1] for i in range(0, len(b), 2)]


def default_registers() -> dict[int, int]:
    """Realistic values from a single-phase 10 kW inverter with 3 MPPT inputs."""
    r: dict[int, int] = {}

    def put(addr, words):
        for i, w in enumerate(words):
            r[addr + i] = w & 0xFFFF

    put(0x1001, [2553, 3079]); put(0x1003, _s32(79380)); put(0x1005, [5009])
    put(0x1010, [3674, 833]); put(0x1012, _s32(29991))
    put(0x1014, [3230, 925]); put(0x1016, _s32(29269))
    put(0x1018, [3554, 862]); put(0x101A, _s32(30034))
    put(0x101C, [52, 3]); put(0x101E, _s32(0))
    put(0x1021, _s32(31124)); put(0x1023, _s32(12330)); put(0x1027, _s32(31460))
    put(0x1037, _s32(79328)); put(0x1039, _s32(1816)); put(0x103B, _s32(98720)); put(0x103D, [1000])
    put(0x104C, [836])
    put(0x1300, _s32(-72034)); put(0x1306, _s32(1263047)); put(0x1308, _s32(1874122))
    put(0x130A, _s32(0)); put(0x1310, _s32(37443))
    put(0x131A, [2551]); put(0x131D, _s32(-2830)); put(0x1323, [2551]); put(0x1326, _s32(0))
    put(0x1332, _s32(727)); put(0x1334, _s32(2529)); put(0x1336, _s32(90)); put(0x1338, [5009])
    put(0x1350, [2543]); put(0x1351, _s32(381)); put(0x1353, _s32(7346)); put(0x1355, [5000])
    put(0x1360, _s32(1033)); put(0x1362, _s32(2071712))
    put(0x2000, [99, 31]); put(0x2006, [550]); put(0x2007, _s32(256)); put(0x2009, _s32(-1530))
    put(0x200B, _s32(298)); put(0x200D, _s32(438951)); put(0x200F, _s32(12)); put(0x2011, _s32(237008))
    put(0x2013, [0])
    put(0x2100, [0, 1, 0x0A00, 0x0F00, 0x1210, 0x1614])
    put(0x2110, [2, 1, 200, 480, 576, 0, 3000, 90, 6000, 100, 6000, 20, 1, 2300, 5000, 30, 12000, 10000])
    put(0x3000, [2026, 10 << 8 | 31, 13 << 8 | 30, 15 << 8])
    put(0x30B0, [1, 2, 0, 3, 0, 0]); put(0x30B9, _s32(10000))
    put(0x5101, [0x0F]); put(0x5104, [100]); put(0x6001, [0])
    put(0x1A00, _str("SM-HY10K", 8)); put(0x1A10, _str("SM2309123456", 8)); put(0x1A18, [0x0421])
    put(0x1A1C, _str("V1.23", 3)); put(0x1A23, _str("230915", 3))
    put(0x1A26, _str("S2.10", 3)); put(0x1A2D, _str("230901", 3))
    put(0x1A3B, [3]); put(0x1A44, [2300, 5000, 10000]); put(0x1A48, [1]); put(0x1A5A, [2])
    put(0x1A60, _str("E1.05", 3)); put(0x1A67, _str("20231105100530", 7))
    put(0x1A6F, _str("D1.02", 3)); put(0x1A76, _str("231101", 3))
    return r


def defined_addresses() -> set[int]:
    return {f.address + i for b in R.ALL_BLOCKS for f in b.fields for i in range(f.words)}


def writable_addresses() -> set[int]:
    out = {R.CLOCK_ADDRESS + i for i in range(4)}
    for key in R.WRITABLE_KEYS:
        f = R.FIELDS[key]
        out |= {f.address + i for i in range(f.words)}
    # Installer settings are RW in the document too
    for key in ("battery_type", "bms_address", "lead_acid_capacity", "meter_type"):
        out.add(R.FIELDS[key].address)
    return out


LIMITS = {0x2117: (0, 100), 0x2119: (0, 100), 0x211B: (0, 100), 0x211F: (0, 100), 0x5104: (10, 100), 0x2100: (0, 4)}


def crc16(data: bytes) -> int:
    crc = 0xFFFF
    for b in data:
        crc ^= b
        for _ in range(8):
            crc = (crc >> 1) ^ 0xA001 if crc & 1 else crc >> 1
    return crc


class SimInverter:
    def __init__(self, strict: bool = False, framer: str = "socket", unit: int = 1) -> None:
        self.regs = default_registers()
        self.strict = strict
        self.framer = framer
        self.unit = unit
        self.defined = defined_addresses()
        self.writable = writable_addresses()
        self.requests: list[tuple[int, int, int]] = []  # (fc, address, count)
        self.writes: list[tuple[int, list[int]]] = []
        self.silent = False  # simulate no response
        self._server: asyncio.base_events.Server | None = None
        self.port = 0

    # ----------------------------------------------------------- pdu logic
    def handle(self, unit: int, pdu: bytes) -> bytes | None:
        if self.silent or unit != self.unit:
            return None
        fc = pdu[0]
        if fc == 0x03:
            addr, count = struct.unpack(">HH", pdu[1:5])
            self.requests.append((fc, addr, count))
            if not 1 <= count <= 125:
                return bytes([0x83, 3])
            rng = range(addr, addr + count)
            if self.strict and any(a not in self.defined for a in rng):
                return bytes([0x83, 2])
            vals = [self.regs.get(a, 0) for a in rng]
            return bytes([0x03, count * 2]) + struct.pack(f">{count}H", *vals)
        if fc in (0x06, 0x10):
            if fc == 0x06:
                addr, value = struct.unpack(">HH", pdu[1:5])
                values = [value]
            else:
                addr, count, nbytes = struct.unpack(">HHB", pdu[1:6])
                values = list(struct.unpack(f">{count}H", pdu[6 : 6 + nbytes]))
            self.requests.append((fc, addr, len(values)))
            for i, v in enumerate(values):
                a = addr + i
                if a not in self.writable:
                    return bytes([fc | 0x80, 4])
                lo_hi = LIMITS.get(a)
                if lo_hi and not lo_hi[0] <= v <= lo_hi[1]:
                    return bytes([fc | 0x80, 4])
            for i, v in enumerate(values):
                self.regs[addr + i] = v
            self.writes.append((addr, values))
            if fc == 0x06:
                return pdu[:5]
            return bytes([0x10]) + struct.pack(">HH", addr, len(values))
        return bytes([fc | 0x80, 1])

    # ------------------------------------------------------------ transport
    async def _serve(self, reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
        try:
            while True:
                if self.framer == "socket":
                    head = await reader.readexactly(7)
                    tid, _pid, length, unit = struct.unpack(">HHHB", head)
                    pdu = await reader.readexactly(length - 1)
                    resp = self.handle(unit, pdu)
                    if resp is not None:
                        writer.write(struct.pack(">HHHB", tid, 0, len(resp) + 1, unit) + resp)
                else:
                    head = await reader.readexactly(2)
                    unit, fc = head
                    if fc in (0x03, 0x06):
                        rest = await reader.readexactly(6)
                    else:
                        part = await reader.readexactly(5)
                        rest = part + await reader.readexactly(part[4] + 2)
                    frame = head + rest
                    if crc16(frame[:-2]) != struct.unpack("<H", frame[-2:])[0]:
                        continue
                    resp = self.handle(unit, frame[1:-2])
                    if resp is not None:
                        out = bytes([unit]) + resp
                        writer.write(out + struct.pack("<H", crc16(out)))
                await writer.drain()
        except (asyncio.IncompleteReadError, ConnectionResetError):
            pass
        finally:
            writer.close()

    async def start(self) -> int:
        self._server = await asyncio.start_server(self._serve, "127.0.0.1", 0)
        self.port = self._server.sockets[0].getsockname()[1]
        return self.port

    async def stop(self) -> None:
        if self._server:
            self._server.close()
            await self._server.wait_closed()
