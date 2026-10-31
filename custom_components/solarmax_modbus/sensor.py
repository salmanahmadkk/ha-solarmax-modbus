"""Sensors."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from homeassistant.components.sensor import (
    RestoreSensor,
    SensorDeviceClass,
    SensorEntityDescription,
    SensorStateClass,
)
from homeassistant.const import (
    PERCENTAGE,
    EntityCategory,
    UnitOfElectricCurrent,
    UnitOfElectricPotential,
    UnitOfEnergy,
    UnitOfFrequency,
    UnitOfPower,
    UnitOfReactivePower,
    UnitOfTemperature,
    UnitOfTime,
)
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback
from homeassistant.util import dt as dt_util

from . import registers as R
from .coordinator import SolarmaxConfigEntry, SolarmaxCoordinator
from .entity import SolarmaxEntity, requirement_met

PARALLEL_UPDATES = 0

M = SensorStateClass.MEASUREMENT
TI = SensorStateClass.TOTAL_INCREASING
DIAG = EntityCategory.DIAGNOSTIC


@dataclass(frozen=True, kw_only=True)
class SolarmaxSensorDescription(SensorEntityDescription):
    value_fn: Callable[[SolarmaxCoordinator], Any] | None = None
    attrs_fn: Callable[[SolarmaxCoordinator], dict[str, Any]] | None = None
    requires: str | None = None
    monotonic: bool = False  # lifetime counter: never allowed to go down


def _d(key, dc=None, unit=None, sc=M, prec=None, req=None, **kw) -> SolarmaxSensorDescription:
    return SolarmaxSensorDescription(
        key=key, device_class=dc, native_unit_of_measurement=unit, state_class=sc,
        suggested_display_precision=prec, requires=req, **kw,
    )


def V(key, req=None, **kw):
    return _d(key, SensorDeviceClass.VOLTAGE, UnitOfElectricPotential.VOLT, prec=1, req=req, **kw)


def A(key, req=None, **kw):
    return _d(key, SensorDeviceClass.CURRENT, UnitOfElectricCurrent.AMPERE, prec=2, req=req, **kw)


def W(key, req=None, **kw):
    return _d(key, SensorDeviceClass.POWER, UnitOfPower.WATT, prec=0, req=req, **kw)


def HZ(key, req=None, **kw):
    return _d(key, SensorDeviceClass.FREQUENCY, UnitOfFrequency.HERTZ, prec=2, req=req, **kw)


def KWH(key, total=False, prec=2, **kw):
    return _d(key, SensorDeviceClass.ENERGY, UnitOfEnergy.KILO_WATT_HOUR, TI, prec=prec, monotonic=total, **kw)


def ENUM(key, options: dict, source: str | None = None, **kw):
    src = source or key
    return SolarmaxSensorDescription(
        key=key, device_class=SensorDeviceClass.ENUM, options=list(dict.fromkeys(options.values())),
        value_fn=lambda c, o=options, s=src: o.get((c.data or {}).get(s)) if (c.data or {}).get(s) is not None else None,
        **kw,
    )


def _info(key):
    return lambda c: c.info.get(key)


def _faults_text(c: SolarmaxCoordinator) -> str | None:
    if (c.data or {}).get("error_code") is None:
        return None
    faults = c.data.get("active_faults") or []
    return (", ".join(f.name for f in faults) or "No faults")[:255]


def _faults_attrs(c: SolarmaxCoordinator) -> dict[str, Any]:
    faults = (c.data or {}).get("active_faults") or []
    return {
        "active": [{"code": f.code, "name": f.name, "severity": f.severity} for f in faults],
        "error_code": (c.data or {}).get("error_code"),
        "error_message_4": (c.data or {}).get("error_message_4"),
    }


def _clock(c: SolarmaxCoordinator):
    naive = R.decode_clock(c.data or {})
    return naive.replace(tzinfo=dt_util.get_default_time_zone()) if naive else None


_INV_MODES = {**R.INVERTER_MODES}

SENSORS: tuple[SolarmaxSensorDescription, ...] = (
    # --- inverter AC output
    V("phase_a_voltage"), A("phase_a_current"), W("phase_a_power"), HZ("phase_a_frequency"),
    V("phase_b_voltage", "three_phase"), A("phase_b_current", "three_phase"),
    W("phase_b_power", "three_phase"), HZ("phase_b_frequency", "three_phase"),
    V("phase_c_voltage", "three_phase"), A("phase_c_current", "three_phase"),
    W("phase_c_power", "three_phase"), HZ("phase_c_frequency", "three_phase"),
    W("active_power"),
    _d("reactive_power", SensorDeviceClass.REACTIVE_POWER, UnitOfReactivePower.VOLT_AMPERE_REACTIVE, prec=0),
    _d("power_factor", SensorDeviceClass.POWER_FACTOR, None, prec=3),
    W("pv_daily_peak_power"),
    _d("inner_temperature", SensorDeviceClass.TEMPERATURE, UnitOfTemperature.CELSIUS, prec=0),
    # --- solar
    V("pv1_voltage"), A("pv1_current"), W("pv1_power"),
    V("pv2_voltage", "mppt2"), A("pv2_current", "mppt2"), W("pv2_power", "mppt2"),
    V("pv3_voltage", "mppt3"), A("pv3_current", "mppt3"), W("pv3_power", "mppt3"),
    V("pv4_voltage", "mppt4"), A("pv4_current", "mppt4"), W("pv4_power", "mppt4"),
    W("pv_power"),
    KWH("pv_total_production", total=True, prec=3),
    KWH("pv_daily_production"),
    _d("total_generation_time", SensorDeviceClass.DURATION, UnitOfTime.HOURS, TI, prec=0, monotonic=True),
    # --- grid (meter)
    W("grid_power"), W("grid_power_l2", "three_phase"), W("grid_power_l3", "three_phase"),
    V("grid_voltage"), V("grid_voltage_l2", "three_phase"), V("grid_voltage_l3", "three_phase"),
    A("grid_current"), A("grid_current_l2", "three_phase"), A("grid_current_l3", "three_phase"),
    HZ("grid_frequency"),
    KWH("total_import", total=True), KWH("total_export", total=True),
    KWH("daily_import"), KWH("daily_export"),
    # --- loads on the grid side ("heavy load")
    W("heavy_load_power"), W("heavy_load_power_l2", "three_phase"), W("heavy_load_power_l3", "three_phase"),
    V("heavy_load_voltage"), V("heavy_load_voltage_l2", "three_phase"), V("heavy_load_voltage_l3", "three_phase"),
    A("heavy_load_current"), A("heavy_load_current_l2", "three_phase"), A("heavy_load_current_l3", "three_phase"),
    KWH("daily_heavy_load_consumption"), KWH("total_heavy_load_consumption", total=True),
    # --- loads on the backup output (EPS)
    V("load_voltage"), A("load_current"), W("load_power"), HZ("load_frequency"),
    V("load_voltage_l2", "three_phase"), A("load_current_l2", "three_phase"), W("load_power_l2", "three_phase"),
    V("load_voltage_l3", "three_phase"), A("load_current_l3", "three_phase"), W("load_power_l3", "three_phase"),
    KWH("daily_load_consumption"), KWH("total_load_consumption", total=True),
    # --- battery
    _d("battery_soc", SensorDeviceClass.BATTERY, PERCENTAGE, prec=0),
    _d("battery_temperature", SensorDeviceClass.TEMPERATURE, UnitOfTemperature.CELSIUS, prec=0),
    V("battery_voltage"), A("battery_current"), W("battery_power"),
    KWH("battery_daily_charge"), KWH("battery_total_charge", total=True),
    KWH("battery_daily_discharge"), KWH("battery_total_discharge", total=True),
    # --- status and faults
    ENUM("status", _INV_MODES, source="inverter_mode"),
    SolarmaxSensorDescription(key="faults", value_fn=_faults_text, attrs_fn=_faults_attrs, icon="mdi:alert-octagon-outline"),
    _d("inverter_mode", sc=None, entity_category=DIAG),
    _d("error_code", sc=None, entity_category=DIAG),
    _d("error_message_4", sc=None, entity_category=DIAG),
    # --- diagnostics / installer settings (read-only)
    SolarmaxSensorDescription(
        key="inverter_clock", device_class=SensorDeviceClass.TIMESTAMP, value_fn=_clock, entity_category=DIAG
    ),
    SolarmaxSensorDescription(
        key="regulation_code", entity_category=DIAG,
        value_fn=lambda c: None if (c.data or {}).get("regulation_code") is None
        else R.REGULATION_CODES.get(c.data["regulation_code"], f"Code 0x{c.data['regulation_code']:04X}"),
    ),
    ENUM("battery_type", R.BATTERY_TYPES, entity_category=DIAG),
    ENUM("power_limit_function", R.POWER_LIMIT_FUNCTIONS, entity_category=DIAG),
    ENUM("meter_type", R.METER_TYPES, entity_category=DIAG, entity_registry_enabled_default=False),
    ENUM("meter_direction", R.METER_DIRECTIONS, entity_category=DIAG, entity_registry_enabled_default=False),
    ENUM("ct_ratio", R.CT_RATIOS, entity_category=DIAG, entity_registry_enabled_default=False),
    ENUM("power_limit_mode", R.POWER_LIMIT_MODES, entity_category=DIAG, entity_registry_enabled_default=False),
    _d("meter_address", sc=None, entity_category=DIAG, entity_registry_enabled_default=False),
    _d("bms_address", sc=None, entity_category=DIAG, entity_registry_enabled_default=False),
    _d("lead_acid_capacity", None, "Ah", None, entity_category=DIAG, entity_registry_enabled_default=False),
    V("lead_acid_stop_discharge_voltage", sc=None, entity_category=DIAG, entity_registry_enabled_default=False),
    V("lead_acid_stop_charge_voltage", sc=None, entity_category=DIAG, entity_registry_enabled_default=False),
    V("off_grid_output_voltage", sc=None, entity_category=DIAG, entity_registry_enabled_default=False),
    HZ("off_grid_output_frequency", sc=None, entity_category=DIAG, entity_registry_enabled_default=False),
    SolarmaxSensorDescription(
        key="production_type", device_class=SensorDeviceClass.ENUM, entity_category=DIAG,
        options=list(R.PRODUCTION_TYPES.values()), value_fn=lambda c: R.PRODUCTION_TYPES.get(c.info.get("production_type")),
    ),
    SolarmaxSensorDescription(
        key="rated_power", device_class=SensorDeviceClass.POWER, native_unit_of_measurement=UnitOfPower.WATT,
        entity_category=DIAG, value_fn=_info("rated_power"),
    ),
)


async def async_setup_entry(
    hass: HomeAssistant, entry: SolarmaxConfigEntry, async_add_entities: AddConfigEntryEntitiesCallback
) -> None:
    coordinator = entry.runtime_data
    async_add_entities(
        SolarmaxSensor(coordinator, d) for d in SENSORS if requirement_met(coordinator, d.requires)
    )


class SolarmaxSensor(SolarmaxEntity, RestoreSensor):
    entity_description: SolarmaxSensorDescription

    def __init__(self, coordinator: SolarmaxCoordinator, description: SolarmaxSensorDescription) -> None:
        super().__init__(coordinator, description)
        self._floor: float | None = None
        self._read_ok = False
        self._update_value()

    async def async_added_to_hass(self) -> None:
        await super().async_added_to_hass()
        if self.entity_description.monotonic:
            last = await self.async_get_last_sensor_data()
            try:
                restored = float(last.native_value) if last and last.native_value is not None else None
            except (TypeError, ValueError):
                restored = None
            if restored is not None and restored > 0:
                self._floor = max(restored, self._floor or 0)
                self._update_value()

    def _update_value(self) -> None:
        desc = self.entity_description
        value = desc.value_fn(self.coordinator) if desc.value_fn else self._value()
        self._read_ok = value is not None
        if desc.monotonic and value is not None:
            # A lifetime counter never drops. A lower or zero reading is a read
            # glitch; keeping the last good value stops the Energy dashboard
            # from counting the whole total a second time.
            if value <= 0 or (self._floor is not None and value < self._floor):
                value = self._floor
            else:
                self._floor = value
        self._attr_native_value = value
        if desc.attrs_fn:
            self._attr_extra_state_attributes = desc.attrs_fn(self.coordinator)

    @callback
    def _handle_coordinator_update(self) -> None:
        self._update_value()
        super()._handle_coordinator_update()

    @property
    def available(self) -> bool:
        return super().available and self._read_ok
