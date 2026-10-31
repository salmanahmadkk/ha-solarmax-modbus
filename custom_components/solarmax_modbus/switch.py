"""Switch controls: grid charging, off-grid mode, inverter on/off."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from homeassistant.components.switch import SwitchEntity, SwitchEntityDescription
from homeassistant.const import EntityCategory
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from .coordinator import SolarmaxConfigEntry, SolarmaxCoordinator
from .entity import SolarmaxEntity

PARALLEL_UPDATES = 1


@dataclass(frozen=True, kw_only=True)
class SolarmaxSwitchDescription(SwitchEntityDescription):
    register_key: str
    on_value: int = 1
    off_value: int = 0


SWITCHES = (
    SolarmaxSwitchDescription(
        key="grid_charge", register_key="grid_charge", entity_category=EntityCategory.CONFIG,
        icon="mdi:transmission-tower-import",
    ),
    SolarmaxSwitchDescription(
        key="off_grid_mode", register_key="off_grid_mode", entity_category=EntityCategory.CONFIG,
        icon="mdi:home-battery-outline",
    ),
    # 0x6001: 0 = power on, 1 = shut down
    SolarmaxSwitchDescription(
        key="inverter_power", register_key="inverter_control", on_value=0, off_value=1,
        entity_category=EntityCategory.CONFIG, icon="mdi:power",
    ),
)


async def async_setup_entry(
    hass: HomeAssistant, entry: SolarmaxConfigEntry, async_add_entities: AddConfigEntryEntitiesCallback
) -> None:
    async_add_entities(SolarmaxSwitch(entry.runtime_data, d) for d in SWITCHES)


class SolarmaxSwitch(SolarmaxEntity, SwitchEntity):
    entity_description: SolarmaxSwitchDescription

    def __init__(self, coordinator: SolarmaxCoordinator, description: SolarmaxSwitchDescription) -> None:
        super().__init__(coordinator, description)

    @property
    def is_on(self) -> bool | None:
        value = self._value(self.entity_description.register_key)
        return None if value is None else value == self.entity_description.on_value

    @property
    def available(self) -> bool:
        return super().available and self.is_on is not None

    async def async_turn_on(self, **kwargs: Any) -> None:
        await self.coordinator.async_write_value(self.entity_description.register_key, self.entity_description.on_value)

    async def async_turn_off(self, **kwargs: Any) -> None:
        await self.coordinator.async_write_value(self.entity_description.register_key, self.entity_description.off_value)
