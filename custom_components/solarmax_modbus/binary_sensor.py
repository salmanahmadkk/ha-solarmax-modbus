"""Binary sensors: inverter fault and grid availability."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass

from homeassistant.components.binary_sensor import (
    BinarySensorDeviceClass,
    BinarySensorEntity,
    BinarySensorEntityDescription,
)
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from . import registers as R
from .coordinator import SolarmaxConfigEntry, SolarmaxCoordinator
from .entity import SolarmaxEntity

PARALLEL_UPDATES = 0


@dataclass(frozen=True, kw_only=True)
class SolarmaxBinaryDescription(BinarySensorEntityDescription):
    is_on_fn: Callable[[dict], bool | None]


def _fault(data: dict) -> bool | None:
    if data.get("inverter_mode") is None or data.get("error_code") is None:
        return None
    critical = any(f.severity == R.CRITICAL for f in data.get("active_faults") or [])
    return data["inverter_mode"] == R.FAULT_MODE or critical


def _grid(data: dict) -> bool | None:
    code = data.get("error_code")
    return None if code is None else not code >> R.GRID_ABSENT_BIT & 1


BINARY_SENSORS = (
    SolarmaxBinaryDescription(key="fault", device_class=BinarySensorDeviceClass.PROBLEM, is_on_fn=_fault),
    SolarmaxBinaryDescription(key="grid_available", device_class=BinarySensorDeviceClass.POWER, is_on_fn=_grid),
)


async def async_setup_entry(
    hass: HomeAssistant, entry: SolarmaxConfigEntry, async_add_entities: AddConfigEntryEntitiesCallback
) -> None:
    async_add_entities(SolarmaxBinarySensor(entry.runtime_data, d) for d in BINARY_SENSORS)


class SolarmaxBinarySensor(SolarmaxEntity, BinarySensorEntity):
    entity_description: SolarmaxBinaryDescription

    def __init__(self, coordinator: SolarmaxCoordinator, description: SolarmaxBinaryDescription) -> None:
        super().__init__(coordinator, description)

    @property
    def is_on(self) -> bool | None:
        return self.entity_description.is_on_fn(self.coordinator.data or {})

    @property
    def available(self) -> bool:
        return super().available and self.is_on is not None

    @property
    def extra_state_attributes(self):
        if self.entity_description.key != "fault":
            return None
        return {"active_faults": [f.name for f in (self.coordinator.data or {}).get("active_faults") or []]}
