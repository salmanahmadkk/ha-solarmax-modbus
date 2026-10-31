"""Service: find and fix impossible spikes in energy statistics."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
import logging
from typing import Any

import voluptuous as vol

from homeassistant.components.recorder import get_instance
from homeassistant.components.recorder.statistics import list_statistic_ids, statistics_during_period
from homeassistant.core import HomeAssistant, ServiceCall, ServiceResponse, SupportsResponse
from homeassistant.exceptions import ServiceValidationError
from homeassistant.helpers import config_validation as cv, entity_registry as er
from homeassistant.util import dt as dt_util

from .const import DOMAIN

_LOGGER = logging.getLogger(__name__)

SERVICE_REPAIR = "repair_energy_statistics"
ATTR_ENTITY_ID = "entity_id"
ATTR_START = "start"
ATTR_MAX = "max_change_per_hour"
ATTR_DRY_RUN = "dry_run"

SCHEMA = vol.Schema(
    {
        vol.Optional(ATTR_ENTITY_ID): cv.entity_ids,
        vol.Optional(ATTR_START): cv.datetime,
        vol.Optional(ATTR_MAX): vol.All(vol.Coerce(float), vol.Range(min=0.1)),
        vol.Optional(ATTR_DRY_RUN, default=True): cv.boolean,
    }
)


def _default_entities(hass: HomeAssistant) -> list[str]:
    """The integration's own lifetime energy counters."""
    registry = er.async_get(hass)
    out = []
    for entry in hass.config_entries.async_loaded_entries(DOMAIN):
        coordinator = entry.runtime_data
        for key, guard in coordinator.guards.items():
            if guard.__class__.__name__ != "LifetimeGuard" or key == "total_generation_time":
                continue
            entity_id = registry.async_get_entity_id("sensor", DOMAIN, f"{coordinator.unique_base}_{key}")
            if entity_id:
                out.append(entity_id)
    return out


def _default_max(hass: HomeAssistant) -> float:
    rates = [e.runtime_data.max_energy_rate for e in hass.config_entries.async_loaded_entries(DOMAIN)]
    return max(rates or [30.0])


async def _async_repair(call: ServiceCall) -> ServiceResponse:
    hass = call.hass
    if "recorder" not in hass.config.components:
        raise ServiceValidationError("The recorder is not running, so there are no statistics to repair.")
    entity_ids: list[str] = call.data.get(ATTR_ENTITY_ID) or _default_entities(hass)
    if not entity_ids:
        raise ServiceValidationError("No energy sensors to check. Pass entity_id.")
    start: datetime = call.data.get(ATTR_START) or dt_util.utcnow() - timedelta(days=30)
    start = dt_util.as_utc(start if start.tzinfo else start.replace(tzinfo=dt_util.get_default_time_zone()))
    maximum: float = call.data.get(ATTR_MAX) or _default_max(hass)
    dry_run: bool = call.data[ATTR_DRY_RUN]

    instance = get_instance(hass)
    metadata = await instance.async_add_executor_job(list_statistic_ids, hass, set(entity_ids))
    found: dict[str, Any] = {}
    for meta in metadata:
        statistic_id = meta["statistic_id"]
        if not meta.get("has_sum"):
            found[statistic_id] = "skipped: not a total (no sum statistics)"
            continue
        if meta.get("unit_class") == "energy":
            units, unit = {"energy": "kWh"}, "kWh"
        else:
            units, unit = None, meta.get("statistics_unit_of_measurement")
        rows = await instance.async_add_executor_job(
            statistics_during_period, hass, start, None, {statistic_id}, "hour", units, {"change"}
        )
        spikes = []
        for row in rows.get(statistic_id, []):
            change = row.get("change")
            if change is None or abs(change) <= maximum:
                continue
            hour = datetime.fromtimestamp(row["start"], UTC)
            spikes.append({
                "hour": dt_util.as_local(hour).isoformat(),
                "change": round(change, 3),
                "unit": unit,
                "action": "would subtract" if dry_run else "subtracted",
            })
            if not dry_run:
                _LOGGER.warning("Removing %.3f %s from %s at %s", change, unit, statistic_id, hour.isoformat())
                instance.async_adjust_statistics(statistic_id, hour, -change, unit)
        found[statistic_id] = spikes
    for entity_id in set(entity_ids) - {m["statistic_id"] for m in metadata}:
        found[entity_id] = "skipped: no statistics recorded"
    return {"dry_run": dry_run, "max_change_per_hour": maximum, "since": start.isoformat(), "statistics": found}


def async_setup_services(hass: HomeAssistant) -> None:
    hass.services.async_register(
        DOMAIN, SERVICE_REPAIR, _async_repair, schema=SCHEMA, supports_response=SupportsResponse.OPTIONAL
    )
