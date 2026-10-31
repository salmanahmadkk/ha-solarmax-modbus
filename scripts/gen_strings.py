"""Generate strings.json + translations/en.json from one name table.

Entity names are chosen so Home Assistant generates exactly the entity IDs
the old YAML Modbus setup used (sensor.solarmax_total_import, ...).
"""

import json
from pathlib import Path

OUT = Path(__file__).resolve().parents[1] / "custom_components" / "solarmax_modbus"


def phase(prefix, title, keys=("voltage", "current", "power", "frequency")):
    return {f"{prefix}_{k}": f"{title} {k.title()}" for k in keys}


sensor = {}
for p in "abc":
    sensor |= phase(f"phase_{p}", f"Phase {p.upper()}")
sensor |= {
    "active_power": "Active Power", "reactive_power": "Reactive Power", "power_factor": "Power Factor",
    "pv_daily_peak_power": "PV Daily Peak Power", "inner_temperature": "Inner Temperature",
}
for i in range(1, 5):
    sensor |= {f"pv{i}_voltage": f"PV{i} Voltage", f"pv{i}_current": f"PV{i} Current", f"pv{i}_power": f"PV{i} Power"}
sensor |= {
    "pv_power": "PV Power", "pv_total_production": "PV Total Production",
    "pv_daily_production": "PV Daily Production", "total_generation_time": "Total Generation Time",
    "grid_frequency": "Grid Frequency", "total_import": "Total Import", "total_export": "Total Export",
    "daily_import": "Daily Import", "daily_export": "Daily Export",
    "daily_heavy_load_consumption": "Daily Heavy Load Consumption",
    "total_heavy_load_consumption": "Total Heavy Load Consumption",
    "load_frequency": "Load Frequency", "daily_load_consumption": "Daily Load Consumption",
    "total_load_consumption": "Total Load Consumption",
    "battery_soc": "Battery SOC", "battery_temperature": "Battery Temperature",
    "battery_voltage": "Battery Voltage", "battery_current": "Battery Current", "battery_power": "Battery Power",
    "battery_daily_charge": "Battery Daily Charge", "battery_total_charge": "Battery Total Charge",
    "battery_daily_discharge": "Battery Daily Discharge", "battery_total_discharge": "Battery Total Discharge",
    "faults": "Faults", "inverter_mode": "Inverter Mode", "error_code": "Error Code",
    "error_message_4": "Error Message 4", "inverter_clock": "Inverter Clock", "regulation_code": "Grid Standard",
    "meter_address": "Meter Address", "bms_address": "BMS Address", "lead_acid_capacity": "Lead-Acid Capacity",
    "lead_acid_stop_discharge_voltage": "Lead-Acid Stop Discharge Voltage",
    "lead_acid_stop_charge_voltage": "Lead-Acid Stop Charge Voltage",
    "off_grid_output_voltage": "Off-Grid Output Voltage", "off_grid_output_frequency": "Off-Grid Output Frequency",
    "rated_power": "Rated Power",
}
for base, title in (("grid", "Grid"), ("heavy_load", "Heavy Load"), ("load", "Load")):
    for k in ("voltage", "current", "power"):
        sensor[f"{base}_{k}"] = f"{title} {k.title()}"
        for n in (2, 3):
            sensor[f"{base}_{k}_l{n}"] = f"{title} {k.title()} L{n}"
sensor = {k: {"name": v} for k, v in sensor.items()}

enums = {
    "status": ("Status", {"initial": "Initial", "standby": "Standby", "on_grid": "On-grid",
                           "off_grid": "Off-grid (backup)", "fault": "Fault", "shutdown": "Shutdown"}),
    "battery_type": ("Battery Type", {"unavailable": "None", "lead_acid": "Lead-acid", "pylon": "Pylontech lithium",
                                      "dyness": "Dyness lithium", "aobo": "Aobo lithium", "uz": "UZ lithium",
                                      "vestmoods": "VestMoods lithium", "xinyi": "XinYi lithium"}),
    "meter_type": ("Meter Type", {"unknown": "Unknown", "gavazzi_em340": "Gavazzi EM340", "chint_dtsu666": "CHINT DTSU666",
                                  "acrel_dtsf1352": "Acrel DTSF1352-C", "lovato_dmg210": "Lovato DMG210", "g2000": "G2000",
                                  "gavazzi_et112": "Gavazzi ET112", "ksem": "KSEM", "chint_ddsu666": "CHINT DDSU666"}),
    "meter_direction": ("Meter Direction", {"positive": "Positive", "negative": "Negative"}),
    "power_limit_function": ("Export Limit Source", {"disabled": "Disabled", "external_device": "External device (G2000)",
                                                     "ct_sensor": "CT sensor", "digital_meter": "Digital meter"}),
    "ct_ratio": ("CT Ratio", {"unknown": "Unknown", **{f"ratio_{n}": f"{n}:1" for n in (1000, 2000, 2500, 3000, 4000, 5000, 6000, 10000)}}),
    "power_limit_mode": ("CT Position", {"ct_on_grid": "On grid", "ct_on_load": "On load"}),
    "production_type": ("Production Type", {"on_grid": "On-grid", "ac_couple": "AC-coupled", "hybrid": "Hybrid",
                                            "hybrid_smart_load": "Hybrid with smart load",
                                            "ac_couple_smart_load": "AC-coupled with smart load"}),
}
for key, (name, states) in enums.items():
    sensor[key] = {"name": name, "state": states}

strings = {
    "config": {
        "step": {
            "user": {
                "title": "Connect to your Solarmax inverter",
                "description": "Enter the Modbus gateway (RS-485 to Wi-Fi/Ethernet converter) the inverter is connected to.",
                "data": {"name": "Name", "host": "Host", "port": "Port", "device_address": "Modbus address",
                         "connection_type": "Connection type"},
                "data_description": {
                    "name": "Used as the device name and the start of every entity ID.",
                    "host": "IP address or host name of the gateway.",
                    "device_address": "The inverter's Modbus address (usually 1).",
                    "connection_type": "Modbus TCP if the gateway converts the protocol; RTU over TCP if it passes RS-485 data through unchanged.",
                },
            },
            "reconfigure": {
                "title": "Change connection settings",
                "data": {"host": "Host", "port": "Port", "device_address": "Modbus address", "connection_type": "Connection type"},
            },
        },
        "error": {
            "cannot_connect": "Could not connect, or the inverter did not answer. Check the host, port and connection type.",
            "invalid_response": "The device answered but rejected the request. Check the Modbus address.",
            "unknown": "Unexpected error, see the logs.",
        },
        "abort": {
            "already_configured": "This inverter is already set up.",
            "reconfigure_successful": "Connection settings updated.",
            "wrong_device": "That address belongs to a different inverter.",
        },
    },
    "options": {
        "step": {
            "init": {
                "title": "Polling and controls",
                "data": {"scan_interval": "Live data interval (seconds)", "settings_interval": "Settings interval (seconds)",
                         "enable_controls": "Enable control entities"},
                "data_description": {
                    "enable_controls": "Off = read-only: no work mode, limits, schedule or on/off controls are created.",
                },
            }
        }
    },
    "selector": {"connection_type": {"options": {"tcp": "Modbus TCP", "rtuovertcp": "RTU over TCP (transparent gateway)"}}},
    "entity": {
        "sensor": sensor,
        "binary_sensor": {"fault": {"name": "Fault"}, "grid_available": {"name": "Grid Available"}},
        "number": {k: {"name": v} for k, v in {
            "max_grid_charge_power": "Max Grid Charge Power", "grid_charge_end_soc": "Grid Charge Stop SOC",
            "max_charge_power": "Max Charge Power", "charge_end_soc": "Charge Stop SOC",
            "max_discharge_power": "Max Discharge Power", "discharge_end_soc": "Discharge Cut-off SOC",
            "off_grid_start_soc": "Off-Grid Start SOC", "max_charge_current": "Max Charge Current",
            "max_discharge_current": "Max Discharge Current", "export_limit": "Export Limit",
            "derating_percent": "Output Derating"}.items()},
        "select": {
            "work_mode": {"name": "Work Mode", "state": {
                "self_use": "Self-use", "feed_in_priority": "Feed-in priority", "time_based": "Time-based control",
                "backup": "Back-up", "battery_discharge": "Battery discharge"}},
            "schedule_repeat": {"name": "Schedule Repeat", "state": {"once": "Once", "every_day": "Every day"}},
        },
        "switch": {"grid_charge": {"name": "Grid Charging"}, "off_grid_mode": {"name": "Off-Grid Mode"},
                   "inverter_power": {"name": "Inverter Power"}},
        "time": {"charge_start": {"name": "Charge Start Time"}, "charge_end": {"name": "Charge End Time"},
                 "discharge_start": {"name": "Discharge Start Time"}, "discharge_end": {"name": "Discharge End Time"}},
        "button": {"sync_clock": {"name": "Sync Inverter Clock"}},
    },
}

strings["services"] = {
    "repair_energy_statistics": {
        "name": "Repair energy statistics",
        "description": "Finds hours where an energy total jumped by more than is physically possible, for example after a bad read, and removes the spike. Runs as a preview unless Preview only is turned off.",
        "fields": {
            "entity_id": {"name": "Energy sensors", "description": "Sensors to check. Default: this integration's lifetime energy counters. You can add helpers built on them, such as template sensors used by the Energy dashboard."},
            "start": {"name": "Check from", "description": "Default: 30 days ago."},
            "max_change_per_hour": {"name": "Largest real change per hour", "description": "Hours that change by more than this are treated as spikes: kWh for energy sensors, the sensor's own unit otherwise. Default: 3 times the inverter's rated power, at least 30 kWh."},
            "dry_run": {"name": "Preview only", "description": "On: only list the spikes. Off: remove them."},
        },
    }
}

text = json.dumps(strings, indent=2, ensure_ascii=False) + "\n"
(OUT / "strings.json").write_text(text)
(OUT / "translations").mkdir(exist_ok=True)
(OUT / "translations" / "en.json").write_text(text)
print("sensor names:", len(sensor))
