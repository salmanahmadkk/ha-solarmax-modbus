"""Constants for the Solarmax Modbus integration."""

from __future__ import annotations

DOMAIN = "solarmax_modbus"
MANUFACTURER = "Solarmax"

CONF_DEVICE_ADDRESS = "device_address"
CONF_CONNECTION_TYPE = "connection_type"
CONF_SCAN_INTERVAL = "scan_interval"
CONF_SETTINGS_INTERVAL = "settings_interval"
CONF_ENABLE_CONTROLS = "enable_controls"

DEFAULT_NAME = "Solarmax"
DEFAULT_PORT = 502
DEFAULT_DEVICE_ADDRESS = 1
DEFAULT_SCAN_INTERVAL = 10  # seconds, live values
DEFAULT_SETTINGS_INTERVAL = 60  # seconds, settings / clock
DEFAULT_ENABLE_CONTROLS = True

MIN_SCAN_INTERVAL = 5
MIN_SETTINGS_INTERVAL = 30

EVENT_FAULT = f"{DOMAIN}_fault"

# Minimum seconds between two writes to the same register. Protects the
# inverter's settings memory (EEPROM) from automations writing in a loop.
WRITE_MIN_INTERVAL = 5
