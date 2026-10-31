# Solarmax Hybrid Inverter (Modbus) for Home Assistant

[![HACS Custom](https://img.shields.io/badge/HACS-Custom-41BDF5.svg)](https://hacs.xyz/docs/faq/custom_repositories)
[![Release](https://img.shields.io/github/v/release/salmanahmadkk/ha-solarmax-modbus)](https://github.com/salmanahmadkk/ha-solarmax-modbus/releases)
[![Validate](https://github.com/salmanahmadkk/ha-solarmax-modbus/actions/workflows/validate.yml/badge.svg)](https://github.com/salmanahmadkk/ha-solarmax-modbus/actions/workflows/validate.yml)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)

A local, UI-configured Home Assistant integration for Solarmax hybrid inverters. It talks Modbus over your local network through an RS-485 to Wi-Fi/Ethernet gateway: no cloud, no YAML.

- **About 90 sensors:** solar per MPPT input, grid meter, loads, battery, inverter status, decoded faults
- **21 controls:** work mode, charge/discharge schedule, grid charging, SOC/power/current limits, export limit, inverter on/off, clock sync
- **Energy dashboard ready:** lifetime and daily energy counters, protected against the bad reads that corrupt energy statistics
- **Light on the inverter:** all live data comes from 3 Modbus requests per poll
- **Fault alerts:** 46 documented faults decoded into plain names, plus an event you can automate on

> **Unofficial.** This project is not affiliated with or endorsed by Solarmax. Changing inverter settings affects how your system charges, discharges and exports. Use the controls carefully, and at your own risk.

---

## Contents

- [Compatibility](#compatibility)
- [What you need](#what-you-need)
- [Installation](#installation)
- [Setup](#setup)
- [Entities](#entities)
- [Controls and safety](#controls-and-safety)
- [Energy dashboard](#energy-dashboard)
- [Data protection](#data-protection)
- [Fault events](#fault-events)
- [Examples](#examples)
- [Moving from a YAML `modbus:` setup](#moving-from-a-yaml-modbus-setup)
- [Known limitations](#known-limitations)
- [Troubleshooting](#troubleshooting)
- [Contributing](#contributing)

---

## Compatibility

The integration implements the **Solarmax Modbus Protocol V4.21** register map. Your inverter is very likely compatible if its Modbus documentation includes:

| Address | Register |
|---|---|
| `0x1001` | Phase A voltage |
| `0x2000` | Battery SOC |
| `0x2100` | Hybrid work mode |
| `0x1A00` | Device model (ASCII) |

| | Status |
|---|---|
| Single-phase hybrid, 3 MPPT (SM-ONYX-UL-10KW, firmware 01.06.05) | ✅ Tested |
| Other single-phase hybrids using the same protocol | Expected to work |
| Three-phase models | Phase B/C entities are created automatically but are **untested**. Reports welcome. |

The integration reads the model, serial number, firmware, MPPT count and phase count from the inverter. It only creates the entities your hardware has.

## What you need

- **Home Assistant** 2025.2 or newer
- **A Modbus gateway** connected to the inverter's RS-485 (Modbus) port, for example an Elfin EW11 or a similar RS-485 to Wi-Fi/Ethernet converter:
  - **Serial settings:** 9600 baud, 8 data bits, no parity, 1 stop bit
  - **Wiring:** inverter RS-485 A/B to gateway A/B. See your inverter manual for the port's pinout.
  - **Mode:** either a *Modbus TCP gateway* (the gateway converts the protocol) or *transparent* (raw RS-485 over TCP). You choose which in the setup form.
- **The inverter's Modbus address:** 1 by default

## Installation

### HACS (recommended)

[![Open your Home Assistant instance and open this repository in HACS.](https://my.home-assistant.io/badges/hacs_repository.svg)](https://my.home-assistant.io/redirect/hacs_repository/?owner=salmanahmadkk&repository=ha-solarmax-modbus&category=integration)

Or add it by hand:
1. Open **HACS**, then **⋮ → Custom repositories**.
2. Repository: `https://github.com/salmanahmadkk/ha-solarmax-modbus`. Type: **Integration**. Then **Add**.
3. Find **Solarmax Hybrid Inverter (Modbus)** and select **Download**.
4. Restart Home Assistant.

HACS lets you know when a new release is out.

### Manual

1. Download the latest [release](https://github.com/salmanahmadkk/ha-solarmax-modbus/releases).
2. Copy `custom_components/solarmax_modbus` into your Home Assistant `config/custom_components/` folder.
3. Restart Home Assistant.

## Setup

Go to **Settings → Devices & services → Add integration → Solarmax Hybrid Inverter (Modbus)**.

| Field | Value |
|---|---|
| Name | Used as the device name and the start of every entity ID. `Solarmax` gives `sensor.solarmax_battery_soc`. |
| Host / Port | The gateway, e.g. `192.168.1.50` / `502` |
| Modbus address | `1` unless changed on the inverter |
| Connection type | **Modbus TCP** if the gateway converts the protocol. **RTU over TCP** if it passes raw RS-485 data through. If one doesn't connect, try the other. |

Setup reads the inverter's identity block first, so a wrong address or connection type shows up straight away.

**Options** (**Configure** on the integration card):

| Option | Default | |
|---|---|---|
| Live data interval | 10 s | Minimum 5 s |
| Settings interval | 60 s | How often settings and the inverter clock are re-read |
| Enable control entities | On | Off makes the integration read-only |

**Reconfigure** on the integration card changes the host, port or address. You'd need it, for example, if the gateway gets a new IP address.

## Entities

Naming used by this integration:
- **Load:** the inverter's **backup (EPS) output**
- **Heavy load:** loads on the **grid side** of the inverter
- **Grid:** the meter at the grid connection

| Group | Entities |
|---|---|
| Inverter | AC voltage, current, power and frequency per phase; active and reactive power; power factor; daily peak power; inner temperature; **Status** (Standby / On-grid / Off-grid / Fault / Shutdown); **Faults** |
| Solar | Voltage, current and power per MPPT input; **PV Power** (sum); PV Daily Production; PV Total Production; Total Generation Time |
| Grid meter | **Grid Power** (positive = import, negative = export); voltage; current; frequency; Daily and Total Import/Export |
| Grid-side loads | Heavy Load power, voltage and current; daily and total consumption |
| Backup output | Load voltage, current, power and frequency; daily and total consumption |
| Battery | SOC; temperature; voltage; current; power (negative = charging); daily and total charge/discharge |
| Binary sensors | **Fault** (problem): on in Fault mode or with a critical fault. **Grid Available**: off during a grid outage. |
| Diagnostics | Inverter clock, grid standard (country code), battery type, export-limit source, rated power, production type, and the raw mode and fault registers. Installer settings are included but disabled by default. |

The device page shows the model, serial number and firmware versions read from the inverter.

## Controls and safety

| Control | Type | Register |
|---|---|---|
| Work mode: Self-use / Feed-in priority / Time-based control / Back-up / Battery discharge | Select | 0x2100 |
| Schedule repeat: Once / Every day | Select | 0x2101 |
| Charge start/end, discharge start/end (for Time-based control) | Time | 0x2102–0x2105 |
| Grid charging | Switch | 0x2115 |
| Max grid charge power, Grid charge stop SOC | Number | 0x2116, 0x2117 |
| Max charge power, Charge stop SOC | Number | 0x2118, 0x2119 |
| Max discharge power, Discharge cut-off SOC | Number | 0x211A, 0x211B |
| Off-grid mode, Off-grid start SOC | Switch, Number | 0x211C, 0x211F |
| Max charge/discharge current | Number | 0x2121, 0x2120 |
| Export limit | Number | 0x30B9 |
| Output derating | Number | 0x5104 |
| Inverter power (on/off) | Switch | 0x6001 |
| Sync inverter clock | Button | 0x3000–0x3003 |

**Built-in safeguards:**
- **Never written:** installer settings (battery type, BMS and meter setup, lead-acid voltages, off-grid output voltage and frequency) and every grid-code and protection register (0x5000–0x5118 apart from output derating). They are shown read-only at most.
- **Unchanged values are not re-written.**
- **At most one write per register every 5 s.** This protects the inverter's settings memory from automations that write in a loop.
- **Every write is read back,** so the entity shows what the inverter actually accepted. A rejected value shows as an error with the reason.

## Energy dashboard

**Settings → Dashboards → Energy:**

| Energy dashboard field | Sensor |
|---|---|
| Solar production | PV Total Production (`sensor.<name>_pv_total_production`) |
| Solar power | PV Power |
| Grid consumption | Total Import |
| Return to grid | Total Export |
| Grid power | **Grid Power**, used as-is (positive = import) |
| Battery energy in / out | Battery Total Charge / Battery Total Discharge |
| Battery power | Battery Power (negative = charging) |

## Data protection

Home Assistant's Energy dashboard treats a big drop in an energy total as a meter reset. It then counts the whole total again when the value comes back. A single bad Modbus read, such as a 0 during a Wi-Fi reconnect, can add thousands of kWh to one day. This integration protects against that in three layers.

**1. Bad reads are ignored**

| Problem | What happens |
|---|---|
| A register block comes back all zeros | The read is discarded. Values show as unavailable for that poll, never 0. |
| Impossible value (SOC 250 %, 900 V AC, 80 Hz, …) | That value shows as unavailable |
| A lifetime counter drops, reads 0, or jumps higher than the inverter could produce in the elapsed time | The last good value is kept |
| A daily counter drops in the middle of the day | The last good value is kept. Resets are accepted around midnight. |

The plausibility limit is 3 × the inverter's rated power (at least 30 kWh per hour), scaled by the time since the last good reading. A real increase after Home Assistant was off for a day is still accepted.

**2. Real changes heal themselves.** If a change persists for 6 readings over at least a minute (a replaced inverter, or a firmware update that resets the counters), it is accepted:
- Lifetime counters carry on from where they were: no dip, nothing counted twice.
- If readings return to the old values after a temporary fault, the energy produced in between is still counted.

The guard state is saved, so this survives restarts.

**3. Old spikes can be repaired.** The `solarmax_modbus.repair_energy_statistics` action finds hours where a total changed by more than is physically possible, and removes the spike from the statistics. It only previews unless you turn that off:

```yaml
action: solarmax_modbus.repair_energy_statistics
data:
  entity_id:            # optional. Default: this integration's lifetime energy counters
    - sensor.solarmax_total_import
    - sensor.solarmax_total_export
  start: "2026-10-01 00:00:00"   # optional. Default: 30 days ago
  dry_run: true                  # false = apply the fix
response_variable: result
```

Run it from **Developer tools → Actions** to see the list, then run it again with `dry_run: false`. It works on any total sensor, including helpers you built on top of these sensors. For a cost sensor, also pass `max_change_per_hour` in its currency. The equivalent manual fix is **Developer tools → Statistics → Adjust sum**.

The diagnostics download includes a `data_quality` section: rejected blocks, rejected readings per counter, and any rebases with the reason.

## Fault events

Each time a fault starts or clears, the integration fires `solarmax_modbus_fault`:

```yaml
event_type: solarmax_modbus_fault
data:
  code: c7              # c0–c31 = Error Code bits, m0–m15 = Error Message 4 bits
  name: Leakage current fault
  severity: critical    # critical / warning / info
  state: started        # started / cleared
  device_id: ...
```

The **Faults** sensor lists the active faults by name. Its attributes include each fault's code and severity, plus the raw register values.

## Examples

### Phone notification for critical faults

```yaml
alias: Inverter - critical fault
triggers:
  - trigger: event
    event_type: solarmax_modbus_fault
    event_data: {severity: critical, state: started}
actions:
  - action: notify.mobile_app_your_phone
    data:
      title: "Inverter: {{ trigger.event.data.name }}"
      message: "Active faults: {{ states('sensor.solarmax_faults') }}"
```

### Cap grid import during peak hours

The protocol has no grid-import limit, but you can emulate one. This automation adjusts **Max Discharge Power** so grid import stays near 1.5 kW while a peak-hours sensor of your own is on. Test it by hand first: set Max Discharge Power during peak and watch Grid Power.

```yaml
alias: Peak hours - cap grid import at 1.5 kW
mode: single
triggers:
  - trigger: time_pattern
    seconds: "/30"
conditions:
  - condition: state
    entity_id: binary_sensor.peak_hours   # your own peak-tariff sensor
    state: "on"
actions:
  - variables:
      grid: "{{ states('sensor.solarmax_grid_power') | float(0) }}"
      limit: "{{ states('number.solarmax_max_discharge_power') | float(0) }}"
      target: "{{ ([0, [limit + grid - 1500, state_attr('number.solarmax_max_discharge_power', 'max') | float(6000)] | min] | max / 100) | round(0) * 100 }}"
  - if:
      - condition: template
        value_template: "{{ (target - limit) | abs >= 200 }}"
    then:
      - action: number.set_value
        target: {entity_id: number.solarmax_max_discharge_power}
        data: {value: "{{ target }}"}
```

Add a second automation that sets Max Discharge Power back to its normal value when peak hours end.

## Moving from a YAML `modbus:` setup

Long-term statistics follow the **entity ID**. To keep your history, give the new entities the entity IDs your YAML sensors had:

1. Make a full backup (**Settings → System → Backups**).
2. Install the integration and restart. Don't add it yet.
3. Remove or comment out the `modbus:` hub for the inverter in `configuration.yaml`, then restart.
4. Go to **Settings → Entities**, filter by **Integrations → Modbus**, select the old inverter sensors (now marked as no longer provided), and choose **Remove selected**. This frees their entity IDs; the statistics are kept.
5. Add the integration.
6. If an entity's ID differs from your old one, open it, choose **⚙ → Entity ID**, and set it to the old ID. Its history reconnects.

With **Name** = `Solarmax`, entities are named like `sensor.solarmax_total_import`, `sensor.solarmax_battery_soc` and `sensor.solarmax_pv1_power`. If your YAML sensors used those names, the IDs match without renaming. Lifetime counters continue from the last value Home Assistant recorded, so the Energy dashboard shows no jump.

## Known limitations

- **Tested on single-phase hardware only.** Three-phase entities follow the protocol document but haven't been verified on a real inverter.
- **One charge window and one discharge window.** That's all the protocol offers for Time-based control. There's no grid-import limit either (see the example above).
- **The protocol document has a few quirks:**
  - Battery power (0x2009) is documented as unsigned but is signed on real inverters, so it's read as signed.
  - The DC/DC firmware address is printed as `0x1A6Fa`; `0x1A6F` is used.
  - Output derating (0x5104) has no read/write marking, and can read above 100 %.
- **Firmware differences seen so far:**
  - The decimals register for total solar production (0x104C) can read 0, so PV Total Production moves in whole kWh.
  - Battery temperature reads 0 when the BMS doesn't report it.
- **No energy history from the inverter.** The protocol has no history registers, so history comes from Home Assistant's recorder.

## Troubleshooting

| Symptom | Try |
|---|---|
| "Could not connect" during setup | Check the host and port; try the other connection type; check the gateway's serial settings (9600 8N1) |
| "Rejected the request" during setup | Check the Modbus address |
| Values go unavailable now and then | Usually Wi-Fi dropouts at the gateway. The integration reconnects by itself. |
| A setting change shows an error | The inverter rejected the value. The message includes its reason (for example "value out of limit"). |

- **Diagnostics** (device page → ⋮ → **Download diagnostics**) include the raw registers of every block and the data-quality section. Please attach them to bug reports.
- **Debug logging:**

  ```yaml
  logger:
    logs:
      custom_components.solarmax_modbus: debug
  ```

## Contributing

Issues and pull requests are welcome. When reporting a problem, please include:
- the inverter model and firmware (shown on the device page)
- whether it's single- or three-phase
- the diagnostics file

Tests run against a built-in inverter simulator, so no hardware is needed:

```bash
python -m venv venv && . venv/bin/activate
pip install pytest-homeassistant-custom-component "pymodbus==3.13.1"
python -m pytest                    # Home Assistant tests against the simulated inverter
python tests/run_client_tests.py    # Modbus client: TCP and RTU-over-TCP, normal and strict
```

`tests/sim_inverter.py` is a small Modbus TCP / RTU-over-TCP inverter simulator. It implements function codes 0x03, 0x06 and 0x10 with real exception codes. `tests/check_against_doc.py` cross-checks every register in `registers.py` against a text export of the protocol's register tables, if you have the document.

## License

[MIT](LICENSE). "Solarmax" is used only to identify compatible hardware.
