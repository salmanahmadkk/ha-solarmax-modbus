"""Base entity."""

from __future__ import annotations

from homeassistant.helpers.entity import EntityDescription
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .coordinator import SolarmaxCoordinator


class SolarmaxEntity(CoordinatorEntity[SolarmaxCoordinator]):
    """Common device info, unique id and naming."""

    _attr_has_entity_name = True

    def __init__(self, coordinator: SolarmaxCoordinator, description: EntityDescription) -> None:
        super().__init__(coordinator)
        self.entity_description = description
        self._attr_translation_key = description.translation_key or description.key
        self._attr_unique_id = f"{coordinator.unique_base}_{description.key}"
        self._attr_device_info = coordinator.device_info

    def _value(self, key: str | None = None):
        return (self.coordinator.data or {}).get(key or self.entity_description.key)


def requirement_met(coordinator: SolarmaxCoordinator, requires: str | None) -> bool:
    """Skip entities for phases / MPPT inputs the inverter does not have."""
    if requires is None:
        return True
    if requires == "three_phase":
        return coordinator.three_phase
    if requires.startswith("mppt"):
        return coordinator.mppt_count >= int(requires[4:])
    return True
