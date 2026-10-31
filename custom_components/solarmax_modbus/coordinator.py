"""Data coordinator: polls the inverter in a handful of block reads."""

from __future__ import annotations

import asyncio
from datetime import datetime, timedelta
import logging
import time as _time
from typing import Any

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import CONF_HOST, CONF_PORT
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers import device_registry as dr
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed
from homeassistant.util import dt as dt_util

from . import registers as R
from .const import (
    CONF_DEVICE_ADDRESS,
    CONF_SCAN_INTERVAL,
    CONF_SETTINGS_INTERVAL,
    DEFAULT_SCAN_INTERVAL,
    DEFAULT_SETTINGS_INTERVAL,
    DOMAIN,
    EVENT_FAULT,
    MANUFACTURER,
    WRITE_MIN_INTERVAL,
)
from .modbus import SolarmaxConnectionError, SolarmaxError, SolarmaxModbusClient, SolarmaxModbusError

_LOGGER = logging.getLogger(__name__)

type SolarmaxConfigEntry = ConfigEntry[SolarmaxCoordinator]


class SolarmaxCoordinator(DataUpdateCoordinator[dict[str, Any]]):
    """Polls live values every scan interval and settings less often."""

    config_entry: SolarmaxConfigEntry

    def __init__(self, hass: HomeAssistant, entry: SolarmaxConfigEntry, client: SolarmaxModbusClient) -> None:
        scan = entry.options.get(CONF_SCAN_INTERVAL, DEFAULT_SCAN_INTERVAL)
        super().__init__(
            hass,
            _LOGGER,
            config_entry=entry,
            name=f"{DOMAIN} {entry.title}",
            update_interval=timedelta(seconds=scan),
        )
        self.client = client
        self.info: dict[str, Any] = {}
        self.raw: dict[str, dict[int, list[int]]] = {}
        self._settings_interval = entry.options.get(CONF_SETTINGS_INTERVAL, DEFAULT_SETTINGS_INTERVAL)
        self._last_slow = 0.0
        self._prev_faults: set[str] | None = None
        self._last_write: dict[int, float] = {}
        self._write_lock = asyncio.Lock()
        self.platforms: list = []
        self.guards: dict[str, Any] = {}  # counter guards, registered by the sensors
        self.rejected_blocks = 0
        self.rejected_values = 0

    # ----------------------------------------------------------- device info
    async def async_load_info(self) -> None:
        """Read the identity block once (raises SolarmaxError)."""
        values, raw = await self.client.read_block(R.INFO_BLOCK)
        if "model" not in values and "serial" not in values:
            raise SolarmaxConnectionError("Device information block is not readable")
        self.info = values
        self.raw["info"] = raw

    @property
    def unique_base(self) -> str:
        serial = self.info.get("serial")
        if serial:
            return serial
        data = self.config_entry.data
        return f"{data[CONF_HOST]}:{data[CONF_PORT]}:{data[CONF_DEVICE_ADDRESS]}"

    @property
    def mppt_count(self) -> int:
        count = self.info.get("mppt_count")
        return count if isinstance(count, int) and 1 <= count <= 4 else 4

    @property
    def three_phase(self) -> bool:
        return self.info.get("grid_phases") == 3

    @property
    def rated_power(self) -> int | None:
        power = self.info.get("rated_power")
        return power if isinstance(power, int) and power > 0 else None

    @property
    def max_energy_rate(self) -> float:
        """Most kWh any counter can plausibly add per hour (grid can exceed the inverter)."""
        return max(30.0, 3 * (self.rated_power or 10000) / 1000)

    @property
    def device_info(self) -> DeviceInfo:
        info = self.info
        versions = [v for v in (info.get("master_version"),) if v]
        extra = ", ".join(f"{label} {info[k]}" for label, k in (("EMS", "ems_version"), ("DC/DC", "dcdc_version")) if info.get(k))
        sw = " ".join(versions) + (f" ({extra})" if extra else "") if versions or extra else None
        return DeviceInfo(
            identifiers={(DOMAIN, self.unique_base)},
            name=self.config_entry.title,
            manufacturer=MANUFACTURER,
            model=info.get("model") or None,
            serial_number=info.get("serial") or None,
            sw_version=sw,
        )

    # ---------------------------------------------------------------- polling
    async def _async_update_data(self) -> dict[str, Any]:
        data: dict[str, Any] = dict(self.data or {})
        ok = 0
        for block in R.FAST_BLOCKS:
            try:
                values, raw = await self.client.read_block(block)
            except SolarmaxConnectionError as err:
                raise UpdateFailed(f"Inverter not responding: {err}") from err
            except SolarmaxModbusError as err:
                _LOGGER.warning("Block %s could not be read: %s", block.name, err)
                values, raw = {}, {}
            if raw and all(word == 0 for regs in raw.values() for word in regs):
                # Every live block holds lifetime counters, so all zeros is
                # always a corrupted answer (seen after Wi-Fi reconnects).
                _LOGGER.warning("Block %s came back as all zeros; ignoring this read", block.name)
                self.rejected_blocks += 1
                values = {}
            if R.sanitize(values):
                self.rejected_values += 1
            for fld in block.fields:  # unread fields become unavailable, not stale
                data[fld.key] = values.get(fld.key)
            self.raw[block.name] = raw
            ok += bool(values)
        if not ok:
            raise UpdateFailed("No live data could be read from the inverter")

        if _time.monotonic() - self._last_slow >= self._settings_interval:
            await self._read_slow(data)

        self._derive(data)
        self._check_faults(data)
        return data

    async def _read_slow(self, data: dict[str, Any]) -> None:
        for block in R.SLOW_BLOCKS:
            try:
                values, raw = await self.client.read_block(block)
            except SolarmaxError as err:
                _LOGGER.debug("Settings block %s not read this cycle: %s", block.name, err)
                continue
            data.update(values)
            self.raw[block.name] = raw
        self._last_slow = _time.monotonic()

    def _derive(self, data: dict[str, Any]) -> None:
        kwh, wh = data.get("pv_total_production_kwh"), data.get("pv_total_production_wh")
        if kwh is None:
            data["pv_total_production"] = None
        else:
            # Both halves come from the same read, so no rollover mismatch.
            data["pv_total_production"] = round(kwh + (wh / 1000 if wh is not None and wh < 1000 else 0), 3)
        powers = [data.get(f"pv{i}_power") for i in range(1, self.mppt_count + 1)]
        data["pv_power"] = round(sum(powers), 1) if all(p is not None for p in powers) else None

    def _check_faults(self, data: dict[str, Any]) -> None:
        faults = R.active_faults(data.get("error_code"), data.get("error_message_4"))
        data["active_faults"] = faults
        current = {f.code: f for f in faults}
        if data.get("error_code") is None or data.get("error_message_4") is None:
            return  # keep the previous set; do not fire on a failed read
        previous = self._prev_faults
        self._prev_faults = set(current)
        if previous is None:
            return
        registry = dr.async_get(self.hass)
        if hasattr(registry, "async_get_device_by_identifier"):  # HA 2026.10+
            device = registry.async_get_device_by_identifier((DOMAIN, self.unique_base), self.config_entry.entry_id)
        else:
            device = registry.async_get_device(identifiers={(DOMAIN, self.unique_base)})
        names = {**{f"c{b}": v for b, v in R.ERROR_CODE_FAULTS.items()}, **{f"m{b}": v for b, v in R.MESSAGE_4_FAULTS.items()}}
        for code in sorted(set(current) ^ previous):
            name, severity = names[code]
            self.hass.bus.async_fire(
                EVENT_FAULT,
                {
                    "device_id": device.id if device else None,
                    "entry_id": self.config_entry.entry_id,
                    "code": code,
                    "name": name,
                    "severity": severity,
                    "state": "started" if code in current else "cleared",
                },
            )

    # ---------------------------------------------------------------- writes
    async def async_write_value(self, key: str, value: float) -> None:
        """Write an engineering value (W, %, A, raw enum ...) to a control."""
        if key not in R.WRITABLE_KEYS:
            raise HomeAssistantError(f"{key} is not writable")
        fld = R.FIELDS[key]
        try:
            words = R.to_raw(fld, value)
        except ValueError as err:
            raise HomeAssistantError(str(err)) from err
        await self._write(key, fld.address, words)

    async def async_sync_clock(self) -> None:
        now: datetime = dt_util.now()
        await self._write("clock", R.CLOCK_ADDRESS, R.encode_clock(now), skip_unchanged=False)

    async def _write(self, key: str, address: int, words: list[int], skip_unchanged: bool = True) -> None:
        async with self._write_lock:
            current = (self.data or {}).get(key)
            if skip_unchanged and current is not None and key in R.FIELDS:
                try:
                    if R.to_raw(R.FIELDS[key], current) == words:
                        _LOGGER.debug("%s already %s, not writing", key, current)
                        return
                except ValueError:
                    pass
            wait = WRITE_MIN_INTERVAL - (_time.monotonic() - self._last_write.get(address, -1e9))
            if wait > 0:
                await asyncio.sleep(wait)
            _LOGGER.info("Writing %s: 0x%04X <- %s", key, address, words)
            try:
                await self.client.write_registers(address, words)
            except SolarmaxModbusError as err:
                raise HomeAssistantError(f"Inverter rejected {key}: {err}") from err
            except SolarmaxConnectionError as err:
                raise HomeAssistantError(f"Could not write {key}: {err}") from err
            finally:
                self._last_write[address] = _time.monotonic()
            # Read the block back so the entity shows what the inverter accepted.
            block = R.CLOCK_BLOCK if key == "clock" else R.BLOCK_OF[key]
            data = dict(self.data or {})
            try:
                values, raw = await self.client.read_block(block)
                data.update(values)
                self.raw[block.name] = raw
            except SolarmaxError as err:
                _LOGGER.debug("Read-back of %s failed: %s", block.name, err)
            self.async_set_updated_data(data)
