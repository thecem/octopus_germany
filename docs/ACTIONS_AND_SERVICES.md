# Actions and Services

Language / Sprache: [English](ACTIONS_AND_SERVICES.md) | [Deutsch](ACTIONS_AND_SERVICES.de.md)

This page explains how to control EV charging entities and how to call the integration services reliably.

## Action Overview

### Smart Charging Control Switch

- Entity pattern: `switch.octopus_<account_number>_<device_id>_smart_control`
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

- Entity pattern: `switch.octopus_germany_<account_number>_<device_id>_boost_charge`
- Purpose: Trigger immediate charging boost

Behavior:

- Turn ON: Start boost charge
- Turn OFF: Cancel boost charge

Requirements:

- Smart control switch should be ON
- Device must support boost and be LIVE

### Plugged-In Binary Sensor

- Entity pattern: `binary_sensor.octopus_<account_number>_<device_id>_plugged`
- Purpose: Best-effort plugged state derived from SmartFlex API status

Decision logic:

- `is_suspended = true` -> `unknown`
- `is_suspended = false` and `current_state = SMART_CONTROL_NOT_AVAILABLE` -> `off`
- `is_suspended = false` and any other `current_state` -> `on`

Important limitation:

- The SmartFlex API does not provide a dedicated vehicle `isPlugged` boolean.
- When smart control is suspended, API state is ambiguous, so sensor is intentionally `unknown`.

## Services

### `octopus_germany.refresh_intelligent_data`

Request an immediate refresh of device and dispatch data for all configured accounts with Intelligent tariff support. Accounts without that capability are ignored.

Example:

```yaml
service: octopus_germany.refresh_intelligent_data
```
### `octopus_germany.set_device_preferences`
### `octopus_germany.set_device_preferences`

Sets a target for a vehicle or charge point. Both preferences apply to all seven days. A successful response confirms Octopus API acceptance, not propagation to the vehicle; the service then requests an Intelligent-data refresh.

- `device_id` (required): Home Assistant device registry ID or Octopus device UUID; entity IDs are not accepted.
- `target_percentage` (required): 20-100 in 5% steps.
- `target_time` (required): `HH:MM` between 04:00 and 17:00.

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

The file is saved under `/config/octopus_germany/exports`. A persistent Home Assistant notification includes a same-origin browser-download link that opens in a new tab, also returned in the service response and result event. Using the current HA origin avoids exposing internal container addresses. Its file-specific token is stored in Home Assistant's private storage and expires after 30 days.

The export uses paginated monthly range requests and local calendar boundaries from the configured Home Assistant timezone. A yearly export is split into monthly requests. Meter source and quality metadata are retained while loading, but the CSV contains consumption values only; metadata should be used separately before treating values as confirmed physical meter readings.

The service response contains `measurement_metadata` with `sources`, `reading_qualities`, `reading_frequencies`, `device_ids`, `register_ids`, `missing_device_id_count` and `missing_register_id_count`. Missing IDs are normal for some aggregated property measurements and do not by themselves identify estimated data; use `sources` and `reading_qualities` for classification.

Parameters:

- `account_number` (required)
- `property_id` (optional): uses the first electricity property when omitted
- `period` (required): `month` or `year`
- `year` (required)
- `month` (required for monthly exports)
- `filename` (optional)
- `layout` (optional): `wide` or `tall`
- `resolution` (optional): `15min` or `hour`; defaults to `15min`
- `summary` (optional): `true/false`
- `go_window_start` and `go_window_end` (optional): local `HH:MM` boundaries used for the summary split

### `octopus_germany.export_cost_report`

Exports a daily/monthly electricity-cost estimate for a month or calendar year. It uses agreement-specific price tiers and API grid fees for the metering point's network operator. Detailed calculations, parameter rationale, CSV structure, incomplete-data behavior, and legal context are in [Electricity Cost Report](COST_REPORT.md).


- `account_number` (required); `property_id` (optional)
- `period` and `year` (required); `month` required for monthly reports
- `contract_start_network_charge_ct_kwh` (required; default `7.65` is an unverified reference)
- `module3_start_date`, `module3_rates_json` (optional)
- `module1_start_date` (optional); `module1_annual_credit_net_eur` (optional; blank uses the matching file's yearly value, otherwise zero)
- `vat_percent` (fallback, default 19); `filename` (optional)
Example `module3_rates_json` for a historical schedule:

```json
[
  {"rate_type":"OFFPEAK","start_time":"23:00:00","end_time":"06:00:00","rate_cents_per_kwh":1.99,"valid_from":"2025-04-01T00:00:00+02:00","valid_to":"2026-01-01T00:00:00+01:00"},
  {"rate_type":"STANDARD","start_time":"06:00:00","end_time":"11:00:00","rate_cents_per_kwh":6.64,"valid_from":"2025-04-01T00:00:00+02:00","valid_to":"2026-01-01T00:00:00+01:00"},
  {"rate_type":"OFFPEAK","start_time":"11:00:00","end_time":"15:00:00","rate_cents_per_kwh":1.99,"valid_from":"2025-04-01T00:00:00+02:00","valid_to":"2026-01-01T00:00:00+01:00"},
  {"rate_type":"STANDARD","start_time":"15:00:00","end_time":"17:00:00","rate_cents_per_kwh":6.64,"valid_from":"2025-04-01T00:00:00+02:00","valid_to":"2026-01-01T00:00:00+01:00"},
  {"rate_type":"PEAK","start_time":"17:00:00","end_time":"22:00:00","rate_cents_per_kwh":12.75,"valid_from":"2025-04-01T00:00:00+02:00","valid_to":"2026-01-01T00:00:00+01:00"},
  {"rate_type":"STANDARD","start_time":"22:00:00","end_time":"23:00:00","rate_cents_per_kwh":6.64,"valid_from":"2025-04-01T00:00:00+02:00","valid_to":"2026-01-01T00:00:00+01:00"}
]
```

This is one network operator's 2025 schedule, valid only from 1 April through 31 December 2025, and the prefilled values are accepted only for their matching operator. Replace the rates and validity dates with the schedule for your metering point. Set `module3_start_date` to the effective date you declared or selected. `valid_to` is exclusive.

The service also checks `/config/octopus_germany/grid_fee_schedules.json`. If the file is missing or has no entry for the detected operator code and report year, the response warns that it can be created from the [schedule-file example](examples/grid_fee_schedules.example.json). Each validity period stores all 24 hours independently; the service never merges adjacent hours. API rates take precedence, then explicit JSON entries fill gaps, followed by file rates. The file's Module 1 amount is used only when `module1_annual_credit_net_eur` is left blank. The response includes the file path and match status.

The response and `octopus_germany_cost_report_result` event include the download URL, day counts, and warnings. A persistent download link expires after 30 days; an incomplete day leaves the monthly total blank.

### `octopus_germany.submit_meter_readings`

Submits electricity or gas register readings to the OE API. Results are returned by the service and fired as `octopus_germany_meter_readings_submission_result`.

- `account_number`, `meter_type`, `meter_id`, `reading_date` (required)
- `meter_type`: `electricity` or `gas`; `reading_date`: `YYYY-MM-DD`
- Supply either `readings_json` (array of `{ "value", "register_obis_code" }`) or the pair `reading_value` and `register_obis_code`.

Only daily readings are supported. The mutation accepts a date and register values, not per-reading timestamps; do not submit 15-minute intervals.

```yaml
service: octopus_germany.submit_meter_readings
data:
  account_number: "A-12345678"
  meter_type: electricity
  meter_id: "1234567890"
  reading_date: "2026-06-01"
  readings_json: >-
    [{"value": 1234.56, "register_obis_code": "1-0:1.8.0"}]
```

For an automation example, see [Daily Meter Reading Upload Example](UPLOAD_DAILY_METER_READING_AUTOMATION.md).

## iMSys / SMGW-HAN Recommendation

For direct local HAN meter telemetry, use this integration in parallel:

- https://github.com/TRON4R/ha-ppc-smgw-han

Recommended split:

- `octopus_germany`: account, tariff, dispatch and SmartFlex controls, plus read access to Octopus-stored historical consumption and meter data
- `ha-ppc-smgw-han`: direct HAN data from your smart meter gateway
