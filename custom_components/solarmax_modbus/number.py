"""Number controls (power limits, SOC limits, currents, export limit)."""

from __future__ import annotations

from dataclasses import dataclass

from homeassistant.components.number import NumberDeviceClass, NumberEntity, NumberEntityDescription, NumberMode
from homeassistant.const import PERCENTAGE, EntityCategory, UnitOfElectricCurrent, UnitOfPower
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from .coordinator import SolarmaxConfigEntry, SolarmaxCoordinator
from .entity import SolarmaxEntity

PARALLEL_UPDATES = 1
FALLBACK_MAX_POWER = 30000


@dataclass(frozen=True, kw_only=True)
class SolarmaxNumberDescription(NumberEntityDescription):
    rated_power_max: bool = False  # cap at the inverter's rated power


def _power(key: str) -> SolarmaxNumberDescription:
    return SolarmaxNumberDescription(
        key=key, device_class=NumberDeviceClass.POWER, native_unit_of_measurement=UnitOfPower.WATT,
        native_min_value=0, native_max_value=FALLBACK_MAX_POWER, native_step=100, mode=NumberMode.BOX,
        rated_power_max=True, entity_category=EntityCategory.CONFIG,
    )


def _soc(key: str, minimum: int = 0) -> SolarmaxNumberDescription:
    return SolarmaxNumberDescription(
        key=key, device_class=NumberDeviceClass.BATTERY, native_unit_of_measurement=PERCENTAGE,
        native_min_value=minimum, native_max_value=100, native_step=1, mode=NumberMode.SLIDER,
        entity_category=EntityCategory.CONFIG,
    )


def _current(key: str) -> SolarmaxNumberDescription:
    return SolarmaxNumberDescription(
        key=key, device_class=NumberDeviceClass.CURRENT, native_unit_of_measurement=UnitOfElectricCurrent.AMPERE,
        native_min_value=0, native_max_value=300, native_step=1, mode=NumberMode.BOX,
        entity_category=EntityCategory.CONFIG,
    )


NUMBERS = (
    _power("max_grid_charge_power"),
    _soc("grid_charge_end_soc"),
    _power("max_charge_power"),
    _soc("charge_end_soc"),
    _power("max_discharge_power"),
    _soc("discharge_end_soc"),
    _soc("off_grid_start_soc"),
    _current("max_charge_current"),
    _current("max_discharge_current"),
    _power("export_limit"),
    SolarmaxNumberDescription(
        key="derating_percent", native_unit_of_measurement=PERCENTAGE, native_min_value=10,
        native_max_value=100, native_step=1, mode=NumberMode.SLIDER, entity_category=EntityCategory.CONFIG,
    ),
)


async def async_setup_entry(
    hass: HomeAssistant, entry: SolarmaxConfigEntry, async_add_entities: AddConfigEntryEntitiesCallback
) -> None:
    async_add_entities(SolarmaxNumber(entry.runtime_data, d) for d in NUMBERS)


class SolarmaxNumber(SolarmaxEntity, NumberEntity):
    entity_description: SolarmaxNumberDescription

    def __init__(self, coordinator: SolarmaxCoordinator, description: SolarmaxNumberDescription) -> None:
        super().__init__(coordinator, description)

    @property
    def native_value(self) -> float | None:
        return self._value()

    @property
    def native_max_value(self) -> float:
        maximum = self.entity_description.native_max_value
        if self.entity_description.rated_power_max and self.coordinator.rated_power:
            maximum = self.coordinator.rated_power
        current = self._value()
        return max(maximum, current) if isinstance(current, (int, float)) else maximum

    @property
    def available(self) -> bool:
        return super().available and self._value() is not None

    async def async_set_native_value(self, value: float) -> None:
        await self.coordinator.async_write_value(self.entity_description.key, value)
