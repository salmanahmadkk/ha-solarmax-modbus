"""Thin async Modbus client for the inverter (no Home Assistant imports)."""

from __future__ import annotations

import asyncio
import inspect
import logging
import time as _time

from pymodbus import FramerType
from pymodbus.client import AsyncModbusTcpClient
from pymodbus.exceptions import ModbusException

from .registers import MAX_READ, Block, decode_block

_LOGGER = logging.getLogger(__name__)

CONNECTION_TCP = "tcp"
CONNECTION_RTU_OVER_TCP = "rtuovertcp"

DEFAULT_TIMEOUT = 5.0

# Modbus exception codes that mean "this address range is not readable".
_ADDRESS_ERRORS = {2, 3}


class SolarmaxError(Exception):
    """Base error."""


class SolarmaxConnectionError(SolarmaxError):
    """No connection or no response."""


class SolarmaxModbusError(SolarmaxError):
    """The inverter answered with a Modbus exception."""

    def __init__(self, function: str, address: int, code: int) -> None:
        self.code = code
        meaning = {
            1: "function not supported",
            2: "too many registers",
            3: "address out of range",
            4: "value out of limit or register is write-protected",
        }.get(code, "unknown error")
        super().__init__(f"{function} 0x{address:04X} rejected: {meaning} (code {code})")


class SolarmaxModbusClient:
    """Serialises all requests to one inverter."""

    def __init__(
        self,
        host: str,
        port: int,
        device_address: int,
        connection_type: str = CONNECTION_TCP,
        timeout: float | None = None,
        request_gap: float = 0.05,
    ) -> None:
        self.host = host
        self.port = port
        self.device_address = device_address
        self._framer = FramerType.RTU if connection_type == CONNECTION_RTU_OVER_TCP else FramerType.SOCKET
        self._timeout = timeout or DEFAULT_TIMEOUT
        self._gap = request_gap
        self._client: AsyncModbusTcpClient | None = None
        self._lock = asyncio.Lock()
        self._last_request = 0.0
        self._segmented: set[str] = set()  # blocks the inverter will not read in one go
        self._id_kw: str | None = None

    # ------------------------------------------------------------ connection
    async def _ensure_connected(self) -> AsyncModbusTcpClient:
        if self._client is not None and self._client.connected:
            return self._client
        if self._client is not None:
            self._client.close()
        self._client = AsyncModbusTcpClient(
            self.host,
            port=self.port,
            framer=self._framer,
            timeout=self._timeout,
            retries=1,
            reconnect_delay=0,  # we reconnect ourselves on the next request
        )
        try:
            ok = await asyncio.wait_for(self._client.connect(), self._timeout + 1)
        except (TimeoutError, OSError) as err:
            ok = False
            _LOGGER.debug("Connect to %s:%s failed: %s", self.host, self.port, err)
        if not ok:
            self._client.close()
            self._client = None
            raise SolarmaxConnectionError(f"Cannot connect to {self.host}:{self.port}")
        if self._id_kw is None:
            params = inspect.signature(self._client.read_holding_registers).parameters
            self._id_kw = "device_id" if "device_id" in params else "slave"
        return self._client

    def close(self) -> None:
        if self._client is not None:
            self._client.close()
            self._client = None

    async def _call(self, method: str, address: int, **kwargs):
        """Run one request with the lock held, mapping errors."""
        client = await self._ensure_connected()
        wait = self._gap - (_time.monotonic() - self._last_request)
        if wait > 0:
            await asyncio.sleep(wait)
        kwargs[self._id_kw] = self.device_address
        try:
            result = await getattr(client, method)(address, **kwargs)
        except (ModbusException, OSError, TimeoutError) as err:
            self.close()
            raise SolarmaxConnectionError(f"{method} 0x{address:04X}: {err}") from err
        finally:
            self._last_request = _time.monotonic()
        if result.isError():
            code = getattr(result, "exception_code", 0)
            raise SolarmaxModbusError(method, address, code)
        return result

    # ------------------------------------------------------------------ reads
    async def read_registers(self, address: int, count: int) -> list[int]:
        if not 1 <= count <= MAX_READ:
            raise ValueError("count out of range")
        async with self._lock:
            result = await self._call("read_holding_registers", address, count=count)
        regs = list(result.registers)
        if len(regs) != count:
            raise SolarmaxConnectionError(f"Short response at 0x{address:04X}: {len(regs)}/{count}")
        return regs

    async def read_block(self, block: Block) -> tuple[dict, dict[int, list[int]]]:
        """Read and decode a block.

        Returns (values, raw) where raw maps start address -> registers.
        If the inverter refuses to read across undefined addresses, the block
        is re-read as its defined segments and remembered for next time.
        """
        if block.name not in self._segmented:
            try:
                regs = await self.read_registers(block.start, block.count)
            except SolarmaxModbusError as err:
                if err.code not in _ADDRESS_ERRORS:
                    raise
                _LOGGER.info("Block %s rejected as a whole (%s); reading it in segments", block.name, err)
                self._segmented.add(block.name)
            else:
                return decode_block(block, block.start, regs), {block.start: regs}

        values: dict = {}
        raw: dict[int, list[int]] = {}
        for start, count in block.segments():
            try:
                regs = await self.read_registers(start, count)
            except SolarmaxModbusError as err:
                _LOGGER.debug("Segment 0x%04X/%d of %s unreadable: %s", start, count, block.name, err)
                continue
            raw[start] = regs
            values.update(decode_block(block, start, regs))
        return values, raw

    # ----------------------------------------------------------------- writes
    async def write_registers(self, address: int, values: list[int]) -> None:
        async with self._lock:
            if len(values) == 1:
                await self._call("write_register", address, value=values[0])
            else:
                await self._call("write_registers", address, values=values)
