# Solarmax Hybrid Inverter (Modbus) for Home Assistant

A custom integration for Solarmax hybrid inverters that speak the **Modbus Protocol V4.21** register map, connected through a Modbus TCP gateway (an RS-485 to Wi-Fi/Ethernet converter such as an Elfin EW11). It's set up entirely from the UI: no YAML.

- **Light on the inverter:** each poll reads 3 register blocks, where a typical YAML setup sends one request per sensor. Settings are read every 60 s.
- **Keeps your entity IDs:** names produce `sensor.solarmax_total_import`, `sensor.solarmax_battery_soc` and so on, so energy history, dashboards and automations carry on.
- **21 everyday controls:**
  - selects: work mode, schedule repeat
  - time pickers: charge and discharge window
  - switches: grid charging, off-grid mode, inverter on/off
  - numbers: power, SOC and current limits, export limit, output derating
  - button: clock sync
- **Faults decoded:** a `Faults` sensor, a `Fault` problem sensor, a `Grid Available` sensor, and a `solarmax_modbus_fault` event each time one of the 46 documented faults starts or clears.
- **Safe by design:**
  - Grid-code and protection settings are never written.
  - Unchanged values are not re-written.
  - Each register is written at most once every 5 s, to protect the inverter's settings memory.
  - An option turns the integration read-only.
- **Robust:**
  - If the inverter rejects block reads across undefined addresses, it falls back to smaller reads automatically.
  - Bad reads can't corrupt the Energy dashboard (see [Data protection](#data-protection)).
  - It reconnects by itself after Wi-Fi drops.

## Install

### With HACS (recommended)

[![Open your Home Assistant instance and open this repository in HACS.](https://my.home-assistant.io/badges/hacs_repository.svg)](https://my.home-assistant.io/redirect/hacs_repository/?owner=salmanahmadkk&repository=ha-solarmax-modbus&category=integration)

Or add it yourself:
1. Open **HACS**, then ⋮ → **Custom repositories**.
2. Repository: `https://github.com/salmanahmadkk/ha-solarmax-modbus`. Type: **Integration**. Then **Add**.
3. Search for **Solarmax Hybrid Inverter (Modbus)** and select **Download**.
4. Restart Home Assistant.

HACS tells you when a new release is out.

### Manual

Copy `custom_components/solarmax_modbus` from the latest release into your Home Assistant `config/custom_components/` folder, then restart.

Then go to **Settings → Devices & services → Add integration → Solarmax Hybrid Inverter (Modbus)** and enter:

| Field | Value |
|---|---|
| Name | `Solarmax`. This becomes the start of every entity ID. |
| Host / Port | Your gateway, e.g. `192.168.1.50` / `502` |
| Modbus address | `1` unless changed on the inverter |
| Connection type | **Modbus TCP** if the gateway converts the protocol (the same as `type: tcp` in YAML). **RTU over TCP** if it passes RS-485 data through unchanged. |

## Moving from the YAML `modbus:` setup and keeping history

Home Assistant's long-term statistics follow the **entity ID**. If the new entities get the same IDs as the old YAML ones, your Energy dashboard, the `*_fixed` helpers and your automations carry on as if nothing changed.

1. **Make a full backup** (Settings → System → Backups).
2. Install the integration with HACS (or manually) and restart. Don't add the integration yet.
3. In `configuration.yaml`, comment out the whole `modbus:` block (the `solarmax` hub and its sensors). Then restart.
4. Go to **Settings → Entities** and search `solarmax`. The old Modbus sensors now say *"This entity is no longer being provided"*. Select them all and **Remove selected**. This frees their entity IDs; the statistics are kept.
5. Add the integration with the name **Solarmax**, as shown above.
6. Check that `sensor.solarmax_total_import`, `sensor.solarmax_pv_total_production` and the others exist without a `_2` suffix, and that the Energy dashboard still shows past days.
7. If **Settings → Repairs** reports a changed *state class* for the daily counters, choose **Fix**. Daily counters are now `total_increasing`, which handles the midnight reset correctly.

What changes after the move:
- Totals have full resolution (12 630.47 kWh instead of 12 630). Solar total production includes the Wh decimals register, so hourly solar bars are smooth.
- New sensors include **Grid Power** (the meter, 0x1300), **Grid Voltage/Current**, **Heavy Load Power/Voltage/Current**, **Battery Temperature**, **PV Power** (sum), **Status**, **Faults**, **Inverter Clock** and **Grid Standard**.
- In the Energy dashboard, use `sensor.solarmax_grid_power` for live grid power. `phase_a_power` is the inverter's output, not the grid. Check the sign while exporting and choose *inverted* if needed.

## Entities

| Group | Entities |
|---|---|
| Inverter | Phase A voltage, current, power and frequency (B/C on three-phase models), active and reactive power, power factor, daily peak, inner temperature, status, faults |
| Solar | PV1–PV4 voltage, current and power (only the MPPTs your inverter reports), PV power, daily and total production, generation time |
| Grid meter | Grid power, voltage, current and frequency, daily and total import/export |
| Grid-side loads ("heavy load") | Power, voltage, current, daily and total consumption |
| Backup output (EPS, "load") | Voltage, current, power, frequency, daily and total consumption |
| Battery | SOC, temperature, voltage, current, power, daily and total charge/discharge |
| Diagnostics | Raw inverter mode, error code and error message 4, inverter clock, grid standard, battery type, export-limit source, rated power, production type. Installer settings are present but disabled by default. |
| Controls | Work mode, schedule repeat, charge and discharge start/end times, grid charging, max grid charge power, grid charge stop SOC, max charge/discharge power, charge stop SOC, discharge cut-off SOC, off-grid mode, off-grid start SOC, max charge/discharge current, export limit, output derating, inverter power, sync inverter clock |

**Never written:**
- installer settings (battery type, BMS and meter setup, lead-acid voltages, off-grid output voltage and frequency)
- every grid-code and protection register (0x5000–0x5118 apart from output derating)

They are shown read-only at most.

### Options

Go to **Settings → Devices & services → Solarmax → Configure**:
- live data interval (default 10 s, minimum 5 s)
- settings interval (default 60 s)
- **Enable control entities**: turn it off for a read-only integration

## Data protection

Home Assistant's Energy dashboard treats any big drop in an energy total as a meter reset. It then counts the whole total again when the value comes back. A single bad Modbus read, such as a 0 during a Wi-Fi reconnect, can add thousands of kWh to one day. The integration protects against this in three layers.

**1. Bad reads are ignored**

| Problem | What happens |
|---|---|
| A block comes back as all zeros | The read is discarded; values show as unavailable for that poll, never 0 |
| Impossible value (SOC 250 %, 900 V AC, 80 Hz) | That value shows as unavailable |
| Lifetime counter drops, reads 0, or jumps higher than the inverter could produce in the elapsed time | The last good value is kept |
| Daily counter drops in the middle of the day | The last good value is kept (resets are accepted around midnight) |

The plausibility limit is 3 × the inverter's rated power, and at least 30 kWh per hour. It scales with the elapsed time, so a real increase after Home Assistant was off for a day is still accepted.

**2. Real changes heal themselves.** If a change persists for 6 readings over at least a minute (for example a replaced inverter, or a firmware update that resets the counters), it is accepted:
- Lifetime counters carry on from where they were: no dip, nothing counted twice.
- If readings return to the old track after a temporary fault, the energy produced in between is still counted.

The guard state is saved, so this survives restarts. When upgrading from the YAML setup or v1.0, counters continue from the last value Home Assistant recorded.

**3. Old spikes can be repaired.** The `solarmax_modbus.repair_energy_statistics` service finds hours where a total changed by more than is physically possible, and removes the spike from the statistics. It previews by default:

```yaml
action: solarmax_modbus.repair_energy_statistics
data:
  entity_id:          # optional; default: this integration's lifetime energy counters
    - sensor.solarmax_total_import_fixed
    - sensor.solarmax_total_export_fixed
  start: "2026-10-01 00:00:00"   # optional; default: 30 days ago
  dry_run: true                  # set to false to apply
response_variable: result
```

Run it from **Developer tools → Actions** to see the list, then run it again with `dry_run: false`. It works on any total sensor, including template helpers built on these sensors. For a cost sensor, also pass `max_change_per_hour` in its currency. The equivalent manual fix is **Developer tools → Statistics → Adjust sum**.

The diagnostics download includes a `data_quality` section: rejected blocks, rejected readings per counter, and any rebases with their reason.

## Fault events

Each time a fault starts or clears, the integration fires the event `solarmax_modbus_fault`:

```yaml
event_type: solarmax_modbus_fault
data:
  code: c7              # c0–c31 = Error Code bits, m0–m15 = Error Message 4 bits
  name: Leakage current fault
  severity: critical    # critical / warning / info
  state: started        # started / cleared
  device_id: ...
```

Example trigger:

```yaml
triggers:
  - trigger: event
    event_type: solarmax_modbus_fault
    event_data: {severity: critical, state: started}
```

## Example: cap grid import during peak hours

This lowers or raises **Max Discharge Power** so grid import stays near 1.5 kW. It assumes `sensor.solarmax_grid_power` is positive when importing, so check the sign on your system first. Before automating it, test it by hand: set Max Discharge Power during peak and watch the grid power. The integration already skips unchanged values and limits writes to one every 5 s per register.

```yaml
alias: Peak hours - cap grid import at 1.5 kW
mode: single
triggers:
  - trigger: time_pattern
    seconds: "/30"
conditions:
  - condition: state
    entity_id: binary_sensor.peak_tariff_hours
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

## Notes on the register document

- **Battery power (0x2009)** is listed as U32. Real inverters report charging as negative, so it is read as signed.
- **DC/DC firmware version** is printed as `0x1A6Fa`. `0x1A6F` is used.
- **Output derating (0x5104)** has no R/W marking in the document. Test it once before relying on it.
- The **History log** and **Day/Month/Year energy** sections in the contents are not defined in the document, so history comes from Home Assistant's recorder.

## Troubleshooting

- **Cannot connect:** check the host and port, and try the other connection type.
- **Download diagnostics** (device page → ⋮): includes the raw registers for every block.
- **Debug logging:**

  ```yaml
  logger:
    logs:
      custom_components.solarmax_modbus: debug
  ```

## Development

```bash
python -m venv venv && . venv/bin/activate
pip install pytest-homeassistant-custom-component "pymodbus==3.13.1"
python -m pytest                      # Home Assistant tests against the simulated inverter
python tests/run_client_tests.py      # Modbus client tests, TCP and RTU-over-TCP, normal and strict
python tests/check_against_doc.py <your copy of the register tables, one table row per line>   # every address checked against the protocol PDF
```

`tests/sim_inverter.py` is a small Modbus TCP / RTU-over-TCP inverter simulator. It implements function codes 0x03, 0x06 and 0x10 with real exception codes.
