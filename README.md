# Octopus Germany Integration for Home Assistant

[![hacs_badge](https://img.shields.io/badge/HACS-Custom-41BDF5.svg)](https://github.com/hacs/integration)
![installation_badge](https://img.shields.io/badge/dynamic/json?color=41BDF5&logo=home-assistant&label=integration%20usage&suffix=%20installs&cacheSeconds=15600&url=https://analytics.home-assistant.io/custom_integrations.json&query=$.octopus_germany.total)

This custom component integrates Octopus Germany services with Home Assistant, providing access to your energy account data, electricity prices, device control, and vehicle charging preferences.

*This integration is in no way affiliated with Octopus Energy.*

---

**💚 Support the Project**
[![ko-fi](https://ko-fi.com/img/githubbutton_sm.svg)](https://ko-fi.com/K3K71LPRM2)

**⚡ New to Octopus Energy Germany?**
[![Octopus Energy Referral](https://img.shields.io/badge/🐙_Get_100€_Bonus-Join_Octopus_Energy-00D9FF?style=for-the-badge&logoColor=white)](https://octopusenergy.de/empfehlungen?referralCode=free-cat-744)

## Features- **Account Information**: Electricity and gas balance tracking across multiple accounts
- **Energy Pricing**: Real-time electricity tariff prices with support for:
  - Simple tariffs (fixed rate)
  - Time of Use tariffs (GO, STANDARD rates)
  - Dynamic tariffs (with real-time pricing using unit rate forecasts)
  - Heat tariffs (for heat pumps)
- **Multi-Ledger Support**: Electricity, Gas, Heat, and other ledger types
- **Device Control**: Smart charging control for electric vehicles and charge points
- **Boost Charging**: Instant charge boost functionality (requires smart charging enabled)
- **Intelligent Dispatching**: Real-time status of Octopus Intelligent charge scheduling
- **Multi-Account**: Support for multiple Octopus accounts under one integration
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

## Entities

### Binary Sensors

#### Intelligent Dispatching
- **Entity ID**: `binary_sensor.octopus_<account_number>_intelligent_dispatching`
- **Description**: Shows whether Octopus Intelligent is currently dispatching (active charging schedule)
- **State**: `on` when dispatching is active, `off` when inactive
- **Attributes**:
  - `account_number`: Your Octopus Energy account number
  - `electricity_balance`: Current account balance in EUR
  - `planned_dispatches`: List of upcoming charging sessions
  - `completed_dispatches`: List of completed charging sessions
  - `devices`: Information about connected smart devices
  - `provider`: Energy provider information
  - `vehicle_battery_size_in_kwh`: Vehicle battery capacity (if available)
  - `current_start`: Start time of current dispatch
  - `current_end`: End time of current dispatch
  - `products`: Energy product details
  - `malo_number`: Electricity meter point number
  - `melo_number`: Electricity meter number
  - `meter`: Meter information

### Sensors

#### Electricity Price Sensor

- **Entity ID**: `sensor.octopus_<account_number>_electricity_price`
- **Description**: Shows the current electricity price in €/kWh
- **Tariff support**:
  - **Simple tariffs**: Displays the fixed rate
  - **Time of Use tariffs**: Automatically updates to show the currently active rate based on the time of day
  - **Dynamic tariffs**: Uses real-time pricing data from unit rate forecasts for the most accurate current price
  - **Heat tariffs**: Supports specific heat pump tariffs like Heat Light and shows the applicable rate
- **Attributes**:
  - `code`: Product code
  - `name`: Product name
  - `description`: Product description
  - `type`: Product type (Simple or TimeOfUse)
  - `valid_from`: Start date of validity
  - `valid_to`: End date of validity
  - `meter_id`: ID of your meter
  - `meter_number`: Number of your meter
  - `meter_type`: Type of your meter (MME, iMSys, etc.)
  - `account_number`: Your Octopus Energy account number
  - `malo_number`: Your electricity meter point number
  - `melo_number`: Your electricity meter number
  - `electricity_balance`: Your current account balance in EUR
  - `timeslots`: (For TimeOfUse tariffs) List of all time slots with their rates and activation times
  - `active_timeslot`: (For TimeOfUse tariffs) Currently active time slot name (e.g., "GO", "STANDARD")
  - `rates`: (For Dynamic tariffs) Rate data formatted for octopus-energy-rates-card compatibility
  - `rates_count`: (For Dynamic tariffs) Number of available rates
  - `unit_rate_forecast`: (For Dynamic tariffs) Native German API unit rate forecast data

#### Electricity Latest Reading Sensor

- **Entity ID**: `sensor.octopus_<account_number>_electricity_latest_reading`
- **Description**: Latest electricity meter reading with timestamp and origin information
- **Unit**: kWh
- **Attributes**:
  - `reading_value`: Reading value in kWh
  - `reading_units`: Reading units (kWh)
  - `reading_date`: Date of the reading (formatted)
  - `reading_origin`: Origin of the reading (CUSTOMER, ESTIMATED, etc.)
  - `reading_type`: Type of reading (ACTUAL, ESTIMATED, etc.)

#### Electricity Balance Sensor

- **Entity ID**: `sensor.octopus_<account_number>_electricity_balance`
- **Description**: Shows the current electricity account balance in EUR
- **Unit**: €
- **Note**: Only available for accounts with electricity service (MALO number present)

#### Gas Sensors

##### Gas Tariff Sensor
- **Entity ID**: `sensor.octopus_<account_number>_gas_tariff`
- **Description**: Shows the current gas product code and tariff details
- **Attributes**:
  - `code`: Product code
  - `name`: Product name
  - `description`: Product description
  - `type`: Product type
  - `valid_from`: Start date of validity
  - `valid_to`: End date of validity
  - `account_number`: Your Octopus Energy account number

##### Gas Balance Sensor
- **Entity ID**: `sensor.octopus_<account_number>_gas_balance`
- **Description**: Shows the current gas account balance in EUR
- **Unit**: €
- **Note**: Only available for accounts with gas service (gas MALO number present)

##### Gas Infrastructure Sensors
- **Entity ID**: `sensor.octopus_<account_number>_gas_malo_number`
- **Description**: Market location identifier for gas supply

- **Entity ID**: `sensor.octopus_<account_number>_gas_melo_number`
- **Description**: Meter location identifier for gas supply

- **Entity ID**: `sensor.octopus_<account_number>_gas_meter`
- **Description**: Current gas meter information with ID, number, and type
- **Attributes**:
  - `meter_id`: ID of your gas meter
  - `meter_number`: Number of your gas meter
  - `meter_type`: Type of your gas meter
  - `account_number`: Your Octopus Energy account number

##### Gas Reading and Price Sensors
- **Entity ID**: `sensor.octopus_<account_number>_gas_latest_reading`
- **Description**: Latest gas meter reading with timestamp and origin information
- **Unit**: m³
- **Attributes**:
  - `reading_value`: Reading value
  - `reading_units`: Reading units (m³)
  - `reading_date`: Date of the reading
  - `reading_origin`: Origin of the reading
  - `reading_type`: Type of reading
  - `register_obis_code`: OBIS code for the register
  - `meter_id`: ID of the meter
  - `account_number`: Your Octopus Energy account number

- **Entity ID**: `sensor.octopus_<account_number>_gas_price`
- **Description**: Current gas tariff rate from valid contracts
- **Unit**: €/kWh

- **Entity ID**: `sensor.octopus_<account_number>_gas_smart_reading`
- **Description**: Smart meter capability status (Enabled/Disabled)

##### Gas Contract Sensors
- **Entity ID**: `sensor.octopus_<account_number>_gas_contract_start`
- **Description**: Contract validity start date

- **Entity ID**: `sensor.octopus_<account_number>_gas_contract_end`
- **Description**: Contract validity end date

- **Entity ID**: `sensor.octopus_<account_number>_gas_contract_days_until_expiry`
- **Description**: Contract expiration countdown in days

#### Device Status Sensor

- **Entity ID**: `sensor.octopus_<account_number>_device_status`
- **Description**: Current status of your smart charging device (e.g., "PLUGGED_IN", "CHARGING", "FINISHED", etc.)
- **Attributes**:
  - `device_id`: Internal ID of the connected device
  - `device_name`: Name of the device
  - `device_model`: Vehicle model (if available)
  - `device_provider`: Device provider
  - `battery_size`: Battery capacity (if available)
  - `is_suspended`: Whether smart charging is currently suspended
  - `account_number`: Your Octopus Energy account number
  - `last_updated`: Timestamp of the last update

### Switches

#### Smart Charging Control
- **Entity ID**: `switch.octopus_<account_number>_device_smart_control`
- **Description**: Controls smart charging functionality for electric vehicles/charge points
- **Requirements**: Device must be connected and capable of smart control
- **Actions**:
  - Turn **ON** to enable smart charging (unsuspend device)
  - Turn **OFF** to disable smart charging (suspend device)
- **Attributes**:
  - `device_id`: Internal device identifier
  - `name`: Device name
  - `model`: Vehicle/charger model
  - `provider`: Device provider
  - `current_status`: Current device status
  - `is_suspended`: Whether device is suspended

#### Boost Charge
- **Entity ID**: `switch.octopus_<account_number>_<device_name>_boost_charge`
- **Description**: Instant charge boost for immediate charging needs
- **Requirements**:
  - **Smart charging must be enabled** (Smart Charging Control switch = ON)
  - Device must support boost charging
  - Device must be in LIVE status
- **Availability**: Only appears when smart charging is active and device supports boost
- **Actions**:
  - Turn **ON** to start immediate boost charging
  - Turn **OFF** to cancel boost charging
- **Attributes**:
  - `device_id`: Internal device identifier
  - `boost_charge_active`: Whether boost charging is currently active
  - `boost_charge_available`: Whether boost charging is available
  - `current_state`: Current device state
  - `device_type`: Type of device (ELECTRIC_VEHICLES, CHARGE_POINTS)
  - `account_number`: Associated account

**Important**: The Boost Charge switch will only be available in Home Assistant when:
1. Smart charging is enabled for the device
2. The device supports smart control capabilities
3. The device is online and not suspended

## Services

### set_device_preferences
- **Service ID**: `octopus_germany.set_device_preferences`
- **Description**: Configure charging preferences for an electric vehicle or charge point
- **Parameters**:
  - `device_id` (required): The device ID (available in device attributes)
  - `target_percentage` (required): Target state of charge (20-100% in 5% steps)
  - `target_time` (required): Target completion time (04:00-17:00)

**Example:**
```yaml
service: octopus_germany.set_device_preferences
data:
  device_id: "00000000-0002-4000-803c-0000000021c7"
  target_percentage: 80
  target_time: "07:00"
```

**Note**: The old `set_vehicle_charge_preferences` service has been removed. Use `set_device_preferences` instead with specific device IDs.
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
