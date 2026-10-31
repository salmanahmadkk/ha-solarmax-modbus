"""Time controls for the charge / discharge window."""

from __future__ import annotations

from datetime import time

from homeassistant.components.time import TimeEntity, TimeEntityDescription
from homeassistant.const import EntityCategory
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from . import registers as R
from .coordinator import SolarmaxConfigEntry, SolarmaxCoordinator
from .entity import SolarmaxEntity

PARALLEL_UPDATES = 1

TIMES = tuple(
    TimeEntityDescription(key=key, entity_category=EntityCategory.CONFIG, icon=icon)
    for key, icon in (
        ("charge_start", "mdi:battery-clock"),
        ("charge_end", "mdi:battery-clock"),
        ("discharge_start", "mdi:battery-clock-outline"),
        ("discharge_end", "mdi:battery-clock-outline"),
    )
)


async def async_setup_entry(
    hass: HomeAssistant, entry: SolarmaxConfigEntry, async_add_entities: AddConfigEntryEntitiesCallback
) -> None:
    async_add_entities(SolarmaxTime(entry.runtime_data, d) for d in TIMES)


class SolarmaxTime(SolarmaxEntity, TimeEntity):
    def __init__(self, coordinator: SolarmaxCoordinator, description: TimeEntityDescription) -> None:
        super().__init__(coordinator, description)

    @property
    def native_value(self) -> time | None:
        return R.decode_hhmm(self._value())

    @property
    def available(self) -> bool:
        return super().available and self._value() is not None

    async def async_set_value(self, value: time) -> None:
        await self.coordinator.async_write_value(self.entity_description.key, R.encode_hhmm(value))
