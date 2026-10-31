"""Config flow: set the inverter up from the UI."""

from __future__ import annotations

import logging
from typing import Any

import voluptuous as vol

from homeassistant.config_entries import ConfigFlow, ConfigFlowResult, OptionsFlow
from homeassistant.const import CONF_HOST, CONF_NAME, CONF_PORT
from homeassistant.core import callback
from homeassistant.helpers.selector import (
    BooleanSelector,
    NumberSelector,
    NumberSelectorConfig,
    NumberSelectorMode,
    SelectSelector,
    SelectSelectorConfig,
    SelectSelectorMode,
    TextSelector,
)

from . import registers as R
from .const import (
    CONF_CONNECTION_TYPE,
    CONF_DEVICE_ADDRESS,
    CONF_ENABLE_CONTROLS,
    CONF_SCAN_INTERVAL,
    CONF_SETTINGS_INTERVAL,
    DEFAULT_DEVICE_ADDRESS,
    DEFAULT_ENABLE_CONTROLS,
    DEFAULT_NAME,
    DEFAULT_PORT,
    DEFAULT_SCAN_INTERVAL,
    DEFAULT_SETTINGS_INTERVAL,
    DOMAIN,
    MIN_SCAN_INTERVAL,
    MIN_SETTINGS_INTERVAL,
)
from .modbus import CONNECTION_RTU_OVER_TCP, CONNECTION_TCP, SolarmaxConnectionError, SolarmaxModbusClient, SolarmaxModbusError

_LOGGER = logging.getLogger(__name__)

_CONNECTION_SELECTOR = SelectSelector(
    SelectSelectorConfig(
        options=[CONNECTION_TCP, CONNECTION_RTU_OVER_TCP],
        translation_key=CONF_CONNECTION_TYPE,
        mode=SelectSelectorMode.DROPDOWN,
    )
)
_INT = lambda lo, hi: NumberSelector(NumberSelectorConfig(min=lo, max=hi, step=1, mode=NumberSelectorMode.BOX))  # noqa: E731


def _connection_schema(defaults: dict[str, Any], with_name: bool) -> vol.Schema:
    fields: dict = {}
    if with_name:
        fields[vol.Required(CONF_NAME, default=defaults.get(CONF_NAME, DEFAULT_NAME))] = TextSelector()
    fields.update({
        vol.Required(CONF_HOST, default=defaults.get(CONF_HOST, "")): TextSelector(),
        vol.Required(CONF_PORT, default=defaults.get(CONF_PORT, DEFAULT_PORT)): _INT(1, 65535),
        vol.Required(CONF_DEVICE_ADDRESS, default=defaults.get(CONF_DEVICE_ADDRESS, DEFAULT_DEVICE_ADDRESS)): _INT(1, 247),
        vol.Required(CONF_CONNECTION_TYPE, default=defaults.get(CONF_CONNECTION_TYPE, CONNECTION_TCP)): _CONNECTION_SELECTOR,
    })
    return vol.Schema(fields)


async def _probe(data: dict[str, Any]) -> dict[str, Any]:
    """Connect and read the identity block. Raises on failure."""
    client = SolarmaxModbusClient(
        data[CONF_HOST], int(data[CONF_PORT]), int(data[CONF_DEVICE_ADDRESS]), data[CONF_CONNECTION_TYPE]
    )
    try:
        values, _raw = await client.read_block(R.INFO_BLOCK)
    finally:
        client.close()
    if not values:
        raise SolarmaxModbusError("read", R.INFO_BLOCK.start, 2)
    return values


def _unique_id(info: dict[str, Any], data: dict[str, Any]) -> str:
    return info.get("serial") or f"{data[CONF_HOST]}:{int(data[CONF_PORT])}:{int(data[CONF_DEVICE_ADDRESS])}"


class SolarmaxConfigFlow(ConfigFlow, domain=DOMAIN):
    VERSION = 1

    async def _validate(self, user_input: dict[str, Any]) -> tuple[dict | None, dict[str, str]]:
        try:
            return await _probe(user_input), {}
        except SolarmaxConnectionError:
            return None, {"base": "cannot_connect"}
        except SolarmaxModbusError:
            return None, {"base": "invalid_response"}
        except Exception:  # noqa: BLE001
            _LOGGER.exception("Unexpected error talking to the inverter")
            return None, {"base": "unknown"}

    @staticmethod
    def _clean(user_input: dict[str, Any]) -> dict[str, Any]:
        return {
            CONF_HOST: user_input[CONF_HOST].strip(),
            CONF_PORT: int(user_input[CONF_PORT]),
            CONF_DEVICE_ADDRESS: int(user_input[CONF_DEVICE_ADDRESS]),
            CONF_CONNECTION_TYPE: user_input[CONF_CONNECTION_TYPE],
        }

    async def async_step_user(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        errors: dict[str, str] = {}
        if user_input is not None:
            data = self._clean(user_input)
            info, errors = await self._validate(data)
            if info is not None:
                await self.async_set_unique_id(_unique_id(info, data))
                self._abort_if_unique_id_configured(updates=data)
                return self.async_create_entry(
                    title=user_input[CONF_NAME].strip() or DEFAULT_NAME,
                    data=data,
                    options={
                        CONF_SCAN_INTERVAL: DEFAULT_SCAN_INTERVAL,
                        CONF_SETTINGS_INTERVAL: DEFAULT_SETTINGS_INTERVAL,
                        CONF_ENABLE_CONTROLS: DEFAULT_ENABLE_CONTROLS,
                    },
                )
        return self.async_show_form(
            step_id="user", data_schema=_connection_schema(user_input or {}, with_name=True), errors=errors
        )

    async def async_step_reconfigure(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        entry = self._get_reconfigure_entry()
        errors: dict[str, str] = {}
        if user_input is not None:
            data = self._clean(user_input)
            info, errors = await self._validate(data)
            if info is not None:
                await self.async_set_unique_id(_unique_id(info, data))
                self._abort_if_unique_id_mismatch(reason="wrong_device")
                return self.async_update_reload_and_abort(entry, data_updates=data)
        return self.async_show_form(
            step_id="reconfigure",
            data_schema=_connection_schema(user_input or dict(entry.data), with_name=False),
            errors=errors,
        )

    @staticmethod
    @callback
    def async_get_options_flow(config_entry) -> SolarmaxOptionsFlow:
        return SolarmaxOptionsFlow()


class SolarmaxOptionsFlow(OptionsFlow):
    async def async_step_init(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        if user_input is not None:
            return self.async_create_entry(
                data={
                    CONF_SCAN_INTERVAL: int(user_input[CONF_SCAN_INTERVAL]),
                    CONF_SETTINGS_INTERVAL: int(user_input[CONF_SETTINGS_INTERVAL]),
                    CONF_ENABLE_CONTROLS: user_input[CONF_ENABLE_CONTROLS],
                }
            )
        opts = self.config_entry.options
        schema = vol.Schema({
            vol.Required(CONF_SCAN_INTERVAL, default=opts.get(CONF_SCAN_INTERVAL, DEFAULT_SCAN_INTERVAL)):
                _INT(MIN_SCAN_INTERVAL, 300),
            vol.Required(CONF_SETTINGS_INTERVAL, default=opts.get(CONF_SETTINGS_INTERVAL, DEFAULT_SETTINGS_INTERVAL)):
                _INT(MIN_SETTINGS_INTERVAL, 3600),
            vol.Required(CONF_ENABLE_CONTROLS, default=opts.get(CONF_ENABLE_CONTROLS, DEFAULT_ENABLE_CONTROLS)):
                BooleanSelector(),
        })
        return self.async_show_form(step_id="init", data_schema=schema)
