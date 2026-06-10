# Octopus Germany Integration for Home Assistant

Language / Sprache: [English](README.md) | [Deutsch](README.de.md)

[![hacs_badge](https://img.shields.io/badge/HACS-Custom-41BDF5.svg)](https://github.com/hacs/integration)
![installation_badge](https://img.shields.io/badge/dynamic/json?color=41BDF5&logo=home-assistant&label=integration%20usage&suffix=%20installs&cacheSeconds=15600&url=https://analytics.home-assistant.io/custom_integrations.json&query=$.octopus_germany.total)

This custom component integrates Octopus Germany services with Home Assistant, providing access to your energy account data, electricity prices, device control, and vehicle charging preferences.

*This integration is in no way affiliated with Octopus Energy.*

---

**💚 Support the Project**
[![ko-fi](https://ko-fi.com/img/githubbutton_sm.svg)](https://ko-fi.com/K3K71LPRM2)

**⚡ New to Octopus Energy Germany?**
[![Octopus Energy Referral](https://img.shields.io/badge/🐙_Get_100€_Bonus-Join_Octopus_Energy-00D9FF?style=for-the-badge&logoColor=white)](https://octopusenergy.de/empfehlungen?referralCode=free-cat-744)

## Features

- **Account Information**: Electricity and gas balance tracking across multiple accounts
- **Energy Pricing**: Real-time electricity tariff prices with support for:
  - Simple tariffs (fixed rate)
  - Time of Use tariffs (GO, STANDARD rates)
  - Dynamic tariffs (with real-time pricing using unit rate forecasts)
  - Heat tariffs (for heat pumps)
- **Multi-Ledger Support**: Electricity, Gas, Heat, and other ledger types
- **Device Control**: Smart charging control for electric vehicles and charge points
- **Boost Charging**: Instant charge boost functionality (requires smart charging enabled)
- **Intelligent Dispatching**: Real-time status of Octopus Intelligent charge scheduling
- **Smart Charging Sessions**: Track smart charges for Octopus rewards (30€/month with ≥5 charges)
- **Smart Meter Readings**: Previous day accumulative consumption with hourly breakdown
- **Service Device Grouping**: All entities organized under single service device per account
- **Multi-Account**: Support for multiple Octopus accounts under one integration
- **Multi-Device**: Support for multiple Devices (EV, charger, heatpumps) under multiple accounts
- **Gas infrastructure monitoring** (MALO/MELO numbers, meters, readings)
- **Latest Electricity meter reading**
- **Gas contract tracking** with expiry countdown
- **[octopus-energy-rates-card](https://github.com/lozzd/octopus-energy-rates-card) compatibility** for dynamic tariff visualization

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

## Documentation

To keep this start page compact, detailed documentation is split across focused pages:

- Full entities and attributes:
  - [`custom_components/octopus_germany/README.md`](custom_components/octopus_germany/README.md)
- Actions, switches and services with practical examples:
  - [`docs/ACTIONS_AND_SERVICES.md`](docs/ACTIONS_AND_SERVICES.md)

### Quick Action Overview

- `switch.octopus_<account_number>_<device_name>_smart_control`
  - ON: smart control enabled
  - OFF: smart control suspended
- `switch.octopus_germany_<account_number>_<device_name>_boost_charge`
  - Starts/stops immediate boost charging (if available)
- `octopus_germany.set_device_preferences`
  - Set target SoC (%) and target time for a specific device
- `octopus_germany.get_smart_meter_readings`
  - Fetch historical iMSys readings for one day
- `octopus_germany.export_smart_meter_csv`
  - Export iMSys readings to CSV (month/year)

### iMSys / SMGW HAN Hinweis

Wenn du Zählerdaten direkt über die HAN-Schnittstelle deines iMSys (SMGW) einlesen willst,
kannst du diese Integration parallel nutzen:

- [`TRON4R/ha-ppc-smgw-han`](https://github.com/TRON4R/ha-ppc-smgw-han)

Empfehlung:
- `octopus_germany` für Vertrags-/Tarif-/Account- und SmartFlex-Daten
- `ha-ppc-smgw-han` für lokale, direkte HAN-Messwerte vom Gateway

## Automation

[Octopus Intelligent Go mit EVCC](https://github.com/ha-puzzles/homeassistant-puzzlepieces/blob/main/use-cases/stromtarife/octopus-intelligent-go/README.md)

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


## API Support

For API-related questions, consult the official documentation:
- REST API: https://developer.oeg-kraken.energy/
- GraphQL API: https://developer.oeg-kraken.energy/graphql/

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
- **New to Octopus Energy?**: Get 100€ bonus with my [referral link](https://octopusenergy.de/empfehlungen?referralCode=free-cat-744) when signing up
- **Found a bug or have an idea?**: Check the [discussions](https://github.com/thecem/octopus_germany/discussions) or [open an issue](https://github.com/thecem/octopus_germany/issues)

Every contribution, whether code, feedback, or financial support, helps make this integration better for everyone!

## License

This project is licensed under the MIT License - see the LICENSE file for details.

## Disclaimer

This integration is not officially affiliated with Octopus Energy Germany. Use at your own risk.
