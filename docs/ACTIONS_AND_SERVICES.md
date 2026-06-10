# Actions and Services

Language / Sprache: [English](ACTIONS_AND_SERVICES.md) | [Deutsch](ACTIONS_AND_SERVICES.de.md)

This page explains how to control EV charging entities and how to call the integration services reliably.

## Action Overview

### Smart Charging Control Switch

- Entity pattern: `switch.octopus_<account_number>_<device_name>_smart_control`
- Purpose: Enable or suspend SmartFlex smart control for a device

Behavior:

- Turn ON:
  - Sends unsuspend command
  - Smart control can schedule charging again
- Turn OFF:
  - Sends suspend command
  - Smart control is paused

Requirements:

- Device must be registered in Octopus SmartFlex
- Device must be reachable via provider integration

### Boost Charge Switch

- Entity pattern: `switch.octopus_germany_<account_number>_<device_name>_boost_charge`
- Purpose: Trigger immediate charging boost

Behavior:

- Turn ON: Start boost charge
- Turn OFF: Cancel boost charge

Requirements:

- Smart control switch should be ON
- Device must support boost and be LIVE

### Plugged-In Binary Sensor

- Entity pattern: `binary_sensor.octopus_<account_number>_<device_name>_plugged`
- Purpose: Best-effort plugged state derived from SmartFlex API status

Decision logic:

- `is_suspended = true` -> `unknown`
- `is_suspended = false` and `current_state = SMART_CONTROL_NOT_AVAILABLE` -> `off`
- `is_suspended = false` and any other `current_state` -> `on`

Important limitation:

- The SmartFlex API does not provide a dedicated vehicle `isPlugged` boolean.
- When smart control is suspended, API state is ambiguous, so sensor is intentionally `unknown`.

## Services

### `octopus_germany.set_device_preferences`

Set target SoC and target time for a specific EV/charge point.

Parameters:

- `device_id` (required): Device UUID
- `target_percentage` (required): 20-100 in 5% steps
- `target_time` (required): `HH:MM` between 04:00 and 17:00

Example:

```yaml
service: octopus_germany.set_device_preferences
data:
  device_id: "00000000-0002-4000-803c-0000000021c7"
  target_percentage: 80
  target_time: "07:00"
```

### `octopus_germany.get_smart_meter_readings`

Fetch iMSys data for a specific date.

Parameters:

- `account_number` (required): `A-xxxxxxxx`
- `date` (required): `YYYY-MM-DD`
- `property_id` (optional)

Example:

```yaml
service: octopus_germany.get_smart_meter_readings
data:
  account_number: "A-12345678"
  date: "2026-06-01"
```

### `octopus_germany.export_smart_meter_csv`

Export meter readings to CSV.

Parameters:

- `account_number` (required)
- `period` (required): `month` or `year`
- `year` (required)
- `month` (optional for period `month`)
- `filename` (optional)
- `layout` (optional): `wide` or `tall`
- `summary` (optional): `true/false`

## iMSys / SMGW-HAN Recommendation

For direct local HAN meter telemetry, use this integration in parallel:

- https://github.com/TRON4R/ha-ppc-smgw-han

Recommended split:

- `octopus_germany`: account, tariff, dispatch and SmartFlex controls, plus read access to Octopus-stored historical consumption and meter data
- `ha-ppc-smgw-han`: direct HAN data from your smart meter gateway
