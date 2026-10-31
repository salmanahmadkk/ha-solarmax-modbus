"""Solarmax hybrid inverter over Modbus TCP."""

from __future__ import annotations

from homeassistant.const import CONF_HOST, CONF_PORT, Platform
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ConfigEntryNotReady

from .const import CONF_CONNECTION_TYPE, CONF_DEVICE_ADDRESS, CONF_ENABLE_CONTROLS, DEFAULT_ENABLE_CONTROLS
from .coordinator import SolarmaxConfigEntry, SolarmaxCoordinator
from .modbus import CONNECTION_TCP, SolarmaxError, SolarmaxModbusClient

READ_PLATFORMS = [Platform.SENSOR, Platform.BINARY_SENSOR]
CONTROL_PLATFORMS = [Platform.NUMBER, Platform.SELECT, Platform.SWITCH, Platform.TIME, Platform.BUTTON]


def _platforms(entry: SolarmaxConfigEntry) -> list[Platform]:
    if entry.options.get(CONF_ENABLE_CONTROLS, DEFAULT_ENABLE_CONTROLS):
        return READ_PLATFORMS + CONTROL_PLATFORMS
    return READ_PLATFORMS


async def async_setup_entry(hass: HomeAssistant, entry: SolarmaxConfigEntry) -> bool:
    client = SolarmaxModbusClient(
        entry.data[CONF_HOST],
        entry.data[CONF_PORT],
        entry.data[CONF_DEVICE_ADDRESS],
        entry.data.get(CONF_CONNECTION_TYPE, CONNECTION_TCP),
    )
    coordinator = SolarmaxCoordinator(hass, entry, client)
    try:
        await coordinator.async_load_info()
        await coordinator.async_config_entry_first_refresh()
    except SolarmaxError as err:
        client.close()
        raise ConfigEntryNotReady(f"Cannot reach the inverter: {err}") from err
    except Exception:
        client.close()
        raise

    entry.runtime_data = coordinator
    coordinator.platforms = _platforms(entry)
    await hass.config_entries.async_forward_entry_setups(entry, coordinator.platforms)
    entry.async_on_unload(entry.add_update_listener(_async_options_updated))
    return True


async def _async_options_updated(hass: HomeAssistant, entry: SolarmaxConfigEntry) -> None:
    await hass.config_entries.async_reload(entry.entry_id)


async def async_unload_entry(hass: HomeAssistant, entry: SolarmaxConfigEntry) -> bool:
    unloaded = await hass.config_entries.async_unload_platforms(entry, entry.runtime_data.platforms)
    if unloaded:
        entry.runtime_data.client.close()
    return unloaded
