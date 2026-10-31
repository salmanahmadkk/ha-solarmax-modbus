"""Button: set the inverter clock to Home Assistant's time."""

from __future__ import annotations

from homeassistant.components.button import ButtonEntity, ButtonEntityDescription
from homeassistant.const import EntityCategory
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from .coordinator import SolarmaxConfigEntry
from .entity import SolarmaxEntity

PARALLEL_UPDATES = 1

SYNC_CLOCK = ButtonEntityDescription(key="sync_clock", entity_category=EntityCategory.CONFIG, icon="mdi:clock-check-outline")


async def async_setup_entry(
    hass: HomeAssistant, entry: SolarmaxConfigEntry, async_add_entities: AddConfigEntryEntitiesCallback
) -> None:
    async_add_entities([SolarmaxSyncClockButton(entry.runtime_data, SYNC_CLOCK)])


class SolarmaxSyncClockButton(SolarmaxEntity, ButtonEntity):
    async def async_press(self) -> None:
        await self.coordinator.async_sync_clock()
