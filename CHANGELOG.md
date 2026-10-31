# Changelog

## v1.1.0

- Energy counters are protected from bad Modbus reads:
  - drops, zeros and physically impossible jumps are ignored
  - real changes that persist are accepted without a dip or double counting
  - daily counters accept resets around midnight only
- All-zero register blocks and impossible values (SOC, voltages, frequency, temperature, power factor) are rejected
- New action `solarmax_modbus.repair_energy_statistics`: find and remove impossible hourly spikes in energy statistics (preview by default)
- Diagnostics include a data-quality section
- Counters continue from the last recorded value when upgrading from v1.0 or a YAML `modbus:` setup

## v1.0.0

- First release: UI setup with reconfigure and options flows
- Live data from 3 block reads per poll; automatic fallback for inverters that reject reads across undefined addresses
- About 90 sensors, 21 controls, decoded faults and `solarmax_modbus_fault` events
- Modbus TCP and RTU-over-TCP gateways
