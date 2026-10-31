"""Diagnostics download (Settings > Devices > Solarmax > Download diagnostics)."""

from __future__ import annotations

from dataclasses import asdict
from typing import Any

from homeassistant.components.diagnostics import async_redact_data
from homeassistant.const import CONF_HOST
from homeassistant.core import HomeAssistant

from .coordinator import SolarmaxConfigEntry

TO_REDACT = {CONF_HOST, "serial"}


async def async_get_config_entry_diagnostics(hass: HomeAssistant, entry: SolarmaxConfigEntry) -> dict[str, Any]:
    coordinator = entry.runtime_data
    data = dict(coordinator.data or {})
    data["active_faults"] = [asdict(f) for f in data.get("active_faults") or []]
    return {
        "entry": async_redact_data(dict(entry.data), TO_REDACT),
        "options": dict(entry.options),
        "info": async_redact_data(coordinator.info, TO_REDACT),
        "data": data,
        "raw_registers": {
            block: {f"0x{start:04X}": regs for start, regs in segments.items()}
            for block, segments in coordinator.raw.items()
        },
        "segmented_blocks": sorted(coordinator.client._segmented),  # noqa: SLF001
    }
