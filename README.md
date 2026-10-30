# Octopus Germany Integration for Home Assistant

Language / Sprache: [English](README.md) | [Deutsch](README.de.md)

[![hacs_badge](https://img.shields.io/badge/HACS-Custom-41BDF5.svg)](https://github.com/hacs/integration)
![installation_badge](https://img.shields.io/badge/dynamic/json?color=41BDF5&logo=home-assistant&label=integration%20usage&suffix=%20installs&cacheSeconds=15600&url=https://analytics.home-assistant.io/custom_integrations.json&query=$.octopus_germany.total)

This custom component integrates Octopus Germany services with Home Assistant, providing access to your energy account data, electricity prices, device control, and vehicle charging preferences.

*This integration is in no way affiliated with Octopus Energy.*

Development and regression tests target Home Assistant **2026.10.1**.
The minimum supported version is declared separately in `hacs.json`.
Local brand icons are the existing integration assets from
[Home Assistant Brands](https://github.com/home-assistant/brands/tree/2f58791c0fcd701b195506a076f18e0248dc2ef9/custom_integrations/octopus_germany).
Validation and release workflows use Ubuntu 24.04 and Node-24-based checkout.

---

**💚 Support the Project**
[![ko-fi](https://ko-fi.com/img/githubbutton_sm.svg)](https://ko-fi.com/K3K71LPRM2)

**⚡ New to Octopus Energy Germany?**
[![Octopus Energy Referral](https://img.shields.io/badge/🐙_Get_150€_as_a_new_customer-Join_Octopus_Energy-00D9FF?style=for-the-badge&logoColor=white)](https://octopusenergy.de/empfehlungen?referralCode=free-cat-744)

Sign up through my referral link and receive **150 €** as a bill credit. Eligibility conditions apply.

## Features

- **Account Information**: Electricity and gas balance tracking across multiple accounts
- **Energy Pricing**: Real-time electricity tariff prices with support for:
  - Simple tariffs (fixed rate)
  - Time of Use tariffs (GO, STANDARD rates)
  - Dynamic tariffs (with real-time pricing using unit rate forecasts)
  - Heat tariffs (for heat pumps)
- **Section 14a Grid Fees**: OE-reported module and current variable grid fee with standardized NT/ST/HT attributes and full rate schedule, plus a combined gross price sensor with today's tariff/Module 3 price combinations and intervals
- **Cost Report Service**: Export a monthly or yearly daily tariff-block cost breakdown using agreement labels and the selected network operator's API-reported module and time-valid fees; heat tariffs are supported
- Generated smart-meter and cost-report CSVs are stored under `/config/octopus_germany/exports`; Home Assistant provides a persistent notification with an authenticated download link
- **Agreement History**: All agreements returned by OE, including past, active and scheduled entries, with gross/net unit prices, VAT, and net/gross monthly standing charges with validity dates in electricity price sensor attributes
- **Multi-Ledger Support**: Electricity, Gas, Heat, and other ledger types
- **Smart Charging Sessions**: Track sessions and reward-related data
- **Smart Meter Readings**: Previous-day consumption with an hourly breakdown from Octopus-stored meter data
- **Energy Dashboard Statistics**: Reconcile late or corrected Octopus consumption readings over the last 30 completed local days; incomplete or conflicting intervals do not overwrite existing hours.
- **Meter Register Sensors**: Per-meter entities are created only for OBIS registers with usable numeric readings; empty or invalid registers do not create sensors, while zero remains valid. Each sensor exposes the complete history for its register and raw meter classification fields. Devices use the reported type, or `Electricity Meter` when the API omits it.
- **Octopus Historical Data Readout**: Read historical consumption and meter readings stored by Octopus
- **Service Device Grouping**: All entities organized under single service device per account
- **Multi-Account**: Support for multiple Octopus accounts under one integration
- **Multi-Device**: Support for multiple Devices (EV, charger, heatpumps) under multiple accounts
- **Gas infrastructure monitoring** (MALO/MELO numbers, meters, readings)
- **Latest Electricity meter reading**
- **Gas contract tracking** with expiry countdown
- **[octopus-energy-rates-card](https://github.com/lozzd/octopus-energy-rates-card) compatibility** for dynamic tariff visualization

Electricity meter labels use API metadata requested from both account and per-meter queries: `hasSmartMeterGateway: true` identifies an iMSys (an mME connected to an SMGW), even when `meterType` is `MME`. Otherwise the reported `meterType` is used, or `Unknown` if absent. `shouldReceiveSmartMeterData` describes data availability expectations, not the physical meter type. Historical meters and their readings remain available.

## API Support

For API-related questions, consult the official Octopus Energy Germany documentation:

- REST API: [developer.oeg-kraken.energy](https://developer.oeg-kraken.energy/)
- GraphQL API (OEG Kraken backend): [developer.oeg-kraken.energy/graphql](https://developer.oeg-kraken.energy/graphql/)

This integration primarily uses the OEG Kraken GraphQL API. Variable grid-fee queries still use the legacy OE GraphQL backend.

## Installation

### HACS (Home Assistant Community Store)

1. Add this repository as a custom repository in HACS
2. Search for ["Octopus Germany"](https://my.home-assistant.io/redirect/hacs_repository/?owner=thecem&repository=octopus_germany&category=integration) in the HACS integrations
3. Install the integration
4. Restart Home Assistant
5. Add the integration via the UI under **Settings** > **Devices & Services** > **Add Integration**

### Manual Installation

1. Copy the `octopus_germany` directory to your Home Assistant `custom_components` directory
2. Restart Home Assistant
3. Add the integration via the UI under **Settings** > **Devices & Services** > **Add Integration**

## Configuration

The integration is configured via the Home Assistant UI:

1. Navigate to **Settings** > **Devices & Services**
2. Click **+ ADD INTEGRATION** and search for "Octopus Germany"
3. Enter your Octopus Energy Germany email and password
4. The integration will automatically fetch your account number and set up the entities

### Polling

The default base polling interval is 30 minutes. Accounts with detected Intelligent tariff support use a separate three-minute polling interval for device and dispatch data. Both intervals can be changed from the integration options and are validated between 1 and 60 minutes. Electricity price sensors also update locally at Time-of-Use tariff boundaries, without waiting for the next base poll. Variable grid-fee entries with a `00:00:00` to `00:00:00` interval are treated as fallbacks behind specific intervals.

All-day grid-fee intervals supplied by the Octopus Energy (OE) API are logged at DEBUG level, not as recurring warnings. The diagnostic includes the grid operator, module, rate and validity period. An all-day rate alone is not evidence of a backend error; if time-varying fees are expected, the API schedule may be incomplete.

Intelligent device and dispatch entities are created only when the account exposes the required tariff capability or connected Intelligent devices. Accounts without that capability do not receive the Intelligent polling coordinator.

## Documentation

To keep this start page compact, detailed documentation is split across focused pages:

- Full entities and attributes:
  - [`custom_components/octopus_germany/README.md`](custom_components/octopus_germany/README.md)
- Actions, switches and services with practical examples:
  - [`docs/ACTIONS_AND_SERVICES.md`](docs/ACTIONS_AND_SERVICES.md)
- Cost-report formulas, parameters, CSV fields, and regulatory context:
  - [`docs/COST_REPORT.md`](docs/COST_REPORT.md)
- Per-operator hourly grid-fee schedule file:
  - [`docs/examples/grid_fee_schedules.example.json`](docs/examples/grid_fee_schedules.example.json)
  - Each year may supply `module1_credit_net_eur`, `module1_start_date` (eligibility),
    and `module3_start_date` (effective date) when the action omits them.
    Explicit action values, including a zero credit, take precedence.
    Missing credits and dates remain unset; no credit is assumed.

### Quick Action Overview

- `switch.octopus_<account_number>_<device_id>_smart_control`
  - ON: smart control enabled
  - OFF: smart control suspended
- `switch.octopus_germany_<account_number>_<device_id>_boost_charge`
  - Starts/stops immediate boost charging (if available)
- `octopus_germany.set_device_preferences`
  - Set target SoC (%) and target time for a specific device
  - Applies to all seven days; success confirms Octopus API acceptance, not vehicle propagation
- `octopus_germany.get_smart_meter_readings`
  - Fetch historical iMSys readings for one day
- `octopus_germany.export_cost_report`
  - Export a daily/monthly electricity cost estimate for a month or year; see the [cost-report guide](docs/COST_REPORT.md)
  - Select `format: package` to create an offline formula XLSX and quarter-hour measurement CSV from one shared fetch, with two download links; no additional cost CSV is generated
  - Fields are available in Developer Tools > Actions; after updating, restart Home Assistant and reload the browser to refresh action descriptions
  - Contract zones are selected from the valid agreement (GO/STANDARD or Heat zones); network NT/ST/HT remains independent
  - XLSX invoices show bold total consumption/costs and consumption-weighted gross comparison-network and NT/ST/HT prices
- `octopus_germany.export_smart_meter_csv`
  - Export iMSys readings to CSV (month/year) using paginated monthly range queries
  - Uses the Home Assistant timezone and retains OE meter-quality metadata while loading
- `octopus_germany.submit_meter_readings`
  - Submit electricity or gas meter readings to the OE API
  - [Daily upload automation example](docs/UPLOAD_DAILY_METER_READING_AUTOMATION.md)
- `octopus_germany.refresh_intelligent_data`
  - Refresh Intelligent device and dispatch data on demand

Per-device entity IDs use the stable Octopus device UUID. Display names remain human-readable, so devices with identical names remain independently controllable.

### iMSys / SMGW HAN

For direct readings from an iMSys smart meter gateway (SMGW) over its HAN interface,
you can use this integration alongside:

- [`TRON4R/ha-ppc-smgw-han`](https://github.com/TRON4R/ha-ppc-smgw-han)

Recommended split:
- `octopus_germany` for account, tariff, SmartFlex and Octopus-stored historical consumption/meter data
- `ha-ppc-smgw-han` for direct local readings from the gateway

## Automation

[Octopus Intelligent Go mit EVCC](https://github.com/ha-puzzles/homeassistant-puzzlepieces/blob/main/use-cases/stromtarife/octopus-intelligent-go/README.md)

### Community Dashboard Example

[HWE70](https://github.com/HWE70) has shared a Lovelace dashboard example for
the Intelligent Go sensors in [Discussion #103](https://github.com/thecem/octopus_germany/discussions/103).
It combines tariff and balance information, dispatch windows, vehicle SoC and
target, charging preference, plugged status, meter identifiers, and charts for
dispatch history and charging sessions.

The dashboard requires the HACS frontend card
[`custom:apexcharts-card`](https://github.com/RomRider/apexcharts-card). Before
using the example, replace `a_xxxxxxxx` with your lower-case account number and
`your_vehicle` with the vehicle slug from your entity IDs.

## Debugging

If you encounter issues, you can enable debug logging by adding the following to your `configuration.yaml`:

```yaml
logger:
  logs:
    custom_components.octopus_germany: debug
    custom_components.octopus_germany.octopus_germany: debug
    custom_components.octopus_germany.switch: debug
```

### Common Issues

#### Boost Charge Switch Not Available
- **Cause**: Smart charging is not enabled or device doesn't support boost charging
- **Solution**:
  1. Ensure the Smart Charging Control switch is turned ON
  2. Check that your device supports smart control (appears in device attributes)
  3. Verify device is in LIVE status and not suspended

#### Token/Authentication Errors
- **Cause**: API token has expired or login credentials are invalid
- **Solution**: The integration automatically handles token refresh. If issues persist, try reloading the integration or re-entering credentials

#### No Devices Found
- **Cause**: No smart-capable devices connected to your Octopus account
- **Solution**: Ensure your electric vehicle or charge point is properly connected to Octopus Intelligent

### Debug Information
When reporting issues, please include:
- Home Assistant version
- Integration version
- Debug logs with sensitive information removed
- Device type and model (if applicable)

### API-Debug

If you need more information for API debug set in const:

`/config/custom_components/octopus_germany/const.py`

```yaml
LOG_API_RESPONSES = True
```
After restarting HA the API-Responses and additional information will be in debug log.


## Support

For bug reports and feature requests, please open an issue on the GitHub repository.
Before raising anything, please read through the [discussion](https://github.com/thecem/octopus_germany/discussions).
If you have found a bug or have a feature request please [raise it](https://github.com/thecem/octopus_germany/issues) using the appropriate report template.

## DeepWiki

[https://deepwiki.com/thecem/octopus_germany](https://deepwiki.com/thecem/octopus_germany)

## Sponsorship & Support

### ☕ Show Your Appreciation
This integration is developed and maintained in my free time. If you find it valuable and want to support its continued development, consider:

[![ko-fi](https://ko-fi.com/img/githubbutton_sm.svg)](https://ko-fi.com/K3K71LPRM2)

Your support helps cover development time, testing infrastructure, and keeps the project actively maintained with new features and bug fixes.

### 🚀 Join the Community
- **Contributing**: Pull requests are welcome! Whether it's bug fixes, new features, or documentation improvements
- **New to Octopus Energy?**: Receive **150 €** as a bill credit when you sign up through [my referral link](https://octopusenergy.de/empfehlungen?referralCode=free-cat-744), subject to eligibility conditions.
- **Found a bug or have an idea?**: Check the [discussions](https://github.com/thecem/octopus_germany/discussions) or [open an issue](https://github.com/thecem/octopus_germany/issues)

Every contribution, whether code, feedback, or financial support, helps make this integration better for everyone!

## License

This project is licensed under the MIT License - see the LICENSE file for details.

## Disclaimer

This integration is not officially affiliated with Octopus Energy Germany. Use at your own risk.
