"""Select controls: work mode and schedule repeat."""

from __future__ import annotations

from dataclasses import dataclass

from homeassistant.components.select import SelectEntity, SelectEntityDescription
from homeassistant.const import EntityCategory
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from . import registers as R
from .coordinator import SolarmaxConfigEntry, SolarmaxCoordinator
from .entity import SolarmaxEntity

PARALLEL_UPDATES = 1


@dataclass(frozen=True, kw_only=True)
class SolarmaxSelectDescription(SelectEntityDescription):
    mapping: dict[int, str]


SELECTS = (
    SolarmaxSelectDescription(
        key="work_mode", mapping=R.WORK_MODES, options=list(R.WORK_MODES.values()),
        entity_category=EntityCategory.CONFIG, icon="mdi:home-lightning-bolt-outline",
    ),
    SolarmaxSelectDescription(
        key="schedule_repeat", mapping=R.SCHEDULE_REPEAT, options=list(R.SCHEDULE_REPEAT.values()),
        entity_category=EntityCategory.CONFIG, icon="mdi:calendar-sync",
    ),
)


async def async_setup_entry(
    hass: HomeAssistant, entry: SolarmaxConfigEntry, async_add_entities: AddConfigEntryEntitiesCallback
) -> None:
    async_add_entities(SolarmaxSelect(entry.runtime_data, d) for d in SELECTS)


class SolarmaxSelect(SolarmaxEntity, SelectEntity):
    entity_description: SolarmaxSelectDescription

    def __init__(self, coordinator: SolarmaxCoordinator, description: SolarmaxSelectDescription) -> None:
        super().__init__(coordinator, description)

    @property
    def current_option(self) -> str | None:
        return self.entity_description.mapping.get(self._value())

    @property
    def available(self) -> bool:
        return super().available and self._value() is not None

    async def async_select_option(self, option: str) -> None:
        raw = next(k for k, v in self.entity_description.mapping.items() if v == option)
        await self.coordinator.async_write_value(self.entity_description.key, raw)
