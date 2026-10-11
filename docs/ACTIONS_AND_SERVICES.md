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
  {"rate_type":"OFFPEAK","start_time":"23:00:00","end_time":"06:00:00","rate_cents_per_kwh":1.99,"valid_from":"2025-04-01T00:00:00+02:00","valid_to":"2026-01-01T00:00:00+01:00"},
  {"rate_type":"STANDARD","start_time":"06:00:00","end_time":"11:00:00","rate_cents_per_kwh":6.64,"valid_from":"2025-04-01T00:00:00+02:00","valid_to":"2026-01-01T00:00:00+01:00"},
  {"rate_type":"OFFPEAK","start_time":"11:00:00","end_time":"15:00:00","rate_cents_per_kwh":1.99,"valid_from":"2025-04-01T00:00:00+02:00","valid_to":"2026-01-01T00:00:00+01:00"},
  {"rate_type":"STANDARD","start_time":"15:00:00","end_time":"17:00:00","rate_cents_per_kwh":6.64,"valid_from":"2025-04-01T00:00:00+02:00","valid_to":"2026-01-01T00:00:00+01:00"},
  {"rate_type":"PEAK","start_time":"17:00:00","end_time":"22:00:00","rate_cents_per_kwh":12.75,"valid_from":"2025-04-01T00:00:00+02:00","valid_to":"2026-01-01T00:00:00+01:00"},
  {"rate_type":"STANDARD","start_time":"22:00:00","end_time":"23:00:00","rate_cents_per_kwh":6.64,"valid_from":"2025-04-01T00:00:00+02:00","valid_to":"2026-01-01T00:00:00+01:00"}
The account service device is excluded, and Home Assistant resolves the
selection to its Octopus device ID. YAML calls may use either the Home Assistant
device registry ID or the Octopus device UUID; entity IDs are not accepted.
The example values are from one VNB's 2025 price sheet, effective 1 April 2025: OFFPEAK 1.99 ct/kWh, STANDARD 6.64 ct/kWh, and PEAK 12.75 ct/kWh. Set `module3_start_date` to the date you declared/selected Module 3 for your metering point. The prefilled preset is applied only to its matching network-operator code; replace it with your VNB's own values if different. API-returned OFFPEAK/STANDARD/PEAK schedules are usable from the selected effective date even when the API labels the selected module `MODULE_1`.
Both settings apply to all seven days. Success confirms acceptance by the Octopus
API, not propagation to the vehicle. API errors or missing update confirmations
cause the service call to fail.

Parameters:

- `device_id` (required): The dropdown selects by name. YAML may use either the Home Assistant device registry ID or the Octopus device UUID.
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

The file is saved under `/config/octopus_germany/exports`. A persistent Home Assistant notification includes a same-origin browser-download link that opens in a new tab, also returned in the service response and result event. Using the current HA origin avoids exposing internal container addresses. Its file-specific token is stored in Home Assistant's private storage and expires after 30 days.

The export uses paginated monthly range requests and local calendar boundaries from the configured Home Assistant timezone. A yearly export is split into monthly requests. Meter source and quality metadata are retained while loading, but the CSV contains consumption values only; metadata should be used separately before treating values as confirmed physical meter readings.

The service response contains `measurement_metadata` with `sources`, `reading_qualities`, `reading_frequencies`, `device_ids`, `register_ids`, `missing_device_id_count` and `missing_register_id_count`. Missing IDs are normal for some aggregated property measurements and do not by themselves identify estimated data; use `sources` and `reading_qualities` for classification.

Parameters:

- `account_number` (required)
- `property_id` (optional): uses the first electricity property when omitted
- `period` (required): `month` or `year`
- `year` (required)
- `month` (optional for period `month`)
- `filename` (optional)
- `layout` (optional): `wide` or `tall`
- `resolution` (optional): `15min` or `hour`; defaults to `15min`
- `summary` (optional): `true/false`
- `go_window_start` and `go_window_end` (optional): local `HH:MM` boundaries used for the summary split

### `octopus_germany.export_cost_report`

Create a daily cost calculation CSV under `/config/octopus_germany/exports` for one calendar month or year. A persistent Home Assistant notification includes a same-origin browser-download link that opens in a new tab, also returned by the service and result event. Using the current HA origin avoids exposing internal container addresses. Its file-specific token is stored in Home Assistant's private storage and expires after 30 days. Agreement price names and activation rules define the tariff blocks; the report does not assume GO/Standard labels and supports heat tariffs. The network operator is taken from the electricity metering-point data. Its API-reported module, rate types, time windows and `validFrom`/`validTo` periods drive the network-fee calculation; the service re-queries at reported validity boundaries, including shorter quarterly periods. A totals row is appended.

The CSV includes one `MONTH_TOTAL YYYY-MM` row per calendar month. It sums each tariff/network time block and makes the monthly equation explicit: adjusted energy cost + standing charge - gross Module 1 credit = monthly gross total. A monthly total remains blank if any day is incomplete; the status identifies how many days need review.

For every tariff/network block, daily rows also show the applied grid-fee rate in net and gross ct/kWh columns (`*_grid_fee_net_ct_per_kwh` and `*_grid_fee_gross_ct_per_kwh`). Monthly rows show the consumption-weighted average if the rate changes during the month.

After the `TOTAL` row, `BASIS` rows record the service inputs, agreement prices and standing-charge rates, plus each month's API grid-fee schedule as JSON. This makes the values and validity periods used for the calculation auditable.

Monthly standing charges from the API are converted to their daily contractual rate using the annualized `12 / 365` basis, then charged for each actual calendar day in the selected period. This matches tariffs invoiced per day rather than forcing every month to the same total standing charge.

Parameters:

- `account_number` (required)
- `property_id` (optional): defaults to the first electricity property
- `period` (required): `month` or `year`
- `year` (required); `month` is required for monthly reports
- `contract_start_network_charge_ct_kwh` (required, default `7.65`): the **net** network-fee component in ct/kWh that the original contract price sheet says is already included in the gross contract AP. The report replaces this baseline with the valid VNB rate; it does not add the full grid fee again. `7.65` is a reference value from one VNB's 2024 price sheet, not a universal or legal default; use it only if your contract's price breakdown supports it.
- `module3_start_date` (optional): date the customer declared/selected Module 3 for this metering point; when provided, time-variable API rates are used from this date even if the API's `module` field still says `MODULE_1`
- `module3_rates_json` (optional): JSON array of manual rate entries for historical intervals missing from the API; the rate is net ct/kWh, and times are local
- `module1_start_date` (optional): date from which to prorate the user-supplied Module 1 credit
- `module1_annual_credit_net_eur` (required, default `0`): applicable network operator's net annual credit for the selected report year
- `vat_percent` (required, default `19`): fallback if the agreement price has no VAT rate
- `filename` (optional): CSV filename in `/config`

Manual rate example for a historical period:

```json
[
  {"rate_type":"OFFPEAK","start_time":"00:00:00","end_time":"06:00:00","rate_cents_per_kwh":1.99,"valid_from":"2025-04-01T00:00:00+02:00"},
  {"rate_type":"STANDARD","start_time":"06:00:00","end_time":"11:00:00","rate_cents_per_kwh":6.64,"valid_from":"2025-04-01T00:00:00+02:00"},
  {"rate_type":"OFFPEAK","start_time":"11:00:00","end_time":"15:00:00","rate_cents_per_kwh":1.99,"valid_from":"2025-04-01T00:00:00+02:00"},
  {"rate_type":"STANDARD","start_time":"15:00:00","end_time":"17:00:00","rate_cents_per_kwh":6.64,"valid_from":"2025-04-01T00:00:00+02:00"},
  {"rate_type":"PEAK","start_time":"17:00:00","end_time":"22:00:00","rate_cents_per_kwh":12.75,"valid_from":"2025-04-01T00:00:00+02:00"},
  {"rate_type":"STANDARD","start_time":"22:00:00","end_time":"23:00:00","rate_cents_per_kwh":6.64,"valid_from":"2025-04-01T00:00:00+02:00"}
]
```

The prefilled example uses one VNB's 2025 price sheet, effective 1 April 2025: OFFPEAK 1.99 ct/kWh, STANDARD 6.64 ct/kWh, and PEAK 12.75 ct/kWh. Set `module3_start_date` to the date you declared/selected Module 3 for your metering point. The preset is applied only to its matching network operator; replace it with your VNB's price sheet if different. API-returned OFFPEAK/STANDARD/PEAK schedules are usable from the selected effective date even when the API labels the selected module `MODULE_1`.

If Module 3 is selected but neither the API nor manual input provides a matching time-variable rate, the report uses the available API `STANDARD` grid-fee rate and marks `module3_rate_basis` as `API STANDARD grid fee fallback`. It also reports the fallback day count in the service response, event, and notification. This fallback is explicitly a grid-fee rate, not a separate “Module 1 ST” price.

Calculation basis under §14a EnWG: the contractual gross AP is adjusted only by the difference between the current applicable net grid fee and this net contract-start baseline, with VAT applied to that difference:

`adjusted gross AP [EUR/kWh] = contract gross AP [EUR/kWh] + ((current net grid fee - baseline net grid fee) [ct/kWh] / 100) × (1 + VAT)`

Rates are converted consistently from ct/kWh to EUR/kWh by the integration. The regulatory context is BNetzA determination BK6-22-300 for the §14a market process and BK8-22/010-A for network-charge rules/calculation. These determinations do not provide the user's contract baseline or prove that Module 3 was selected; confirm the baseline against the original contract/price sheet and the effective date against the customer's declaration and VNB records.

Example:

```yaml
action: octopus_germany.export_cost_report
data:
  account_number: "A-12345678"
  period: month
  year: 2026
  month: 9
  contract_start_network_charge_ct_kwh: 7.65
  module3_start_date: "2025-07-01"
  # Add module3_rates_json when the API has no rates for the selected period.
  module1_start_date: "2025-03-19"
  module1_annual_credit_net_eur: 108.33
  vat_percent: 19
```

The implementation uses the market-process framework in BNetzA determination BK6-22-300 and the network-charge rules and calculation framework in BK8-22/010-A as regulatory context. It is a transparent calculation from returned API values and explicit user inputs, not a legal decision on eligibility, enrollment, or a supplier invoice. The network-charge baseline and Module 1 inputs must be checked against the applicable contract and network-operator documents. Missing tariff, network rate, or standing-charge data are reported as incomplete instead of being treated as zero. The current calendar year is limited to readings expected to be available (through two days ago).

In the semicolon-delimited CSV, numeric values use the German decimal comma. Consumption is shown to three decimal places, Euro amounts to cents, and €/kWh rates to six decimal places. Calculations and totals retain full internal precision.

### `octopus_germany.submit_meter_readings`

Submit electricity or gas meter readings to the OE API.

Parameters:

- `account_number` (required): Account that owns the meter
- `meter_type` (required): `electricity` or `gas`
- `meter_id` (required): OE meter ID from the meter entity attributes
- `reading_date` (required): `YYYY-MM-DD`
- `readings_json` (optional): JSON array of readings, each containing `value` and `register_obis_code`
- `reading_value` and `register_obis_code` (optional): helper fields for a single register reading

Example:

```yaml
service: octopus_germany.submit_meter_readings
data:
  meter_type: electricity
  meter_id: "1234567890"
  reading_date: "2026-06-01"
  readings_json: >-
    [{"value": 1234.56, "register_obis_code": "1-0:1.8.0"}]
```

Important limitation:

- The OE mutation accepts a date and register values, not per-entry timestamps.
- Only **daily values** should be submitted here, not 15-minute intervals.

Practical example:

- [Daily meter reading upload automation](UPLOAD_DAILY_METER_READING_AUTOMATION.md)

## iMSys / SMGW-HAN Recommendation

For direct local HAN meter telemetry, use this integration in parallel:

- https://github.com/TRON4R/ha-ppc-smgw-han

Recommended split:

- `octopus_germany`: account, tariff, dispatch and SmartFlex controls, plus read access to Octopus-stored historical consumption and meter data
- `ha-ppc-smgw-han`: direct HAN data from your smart meter gateway
