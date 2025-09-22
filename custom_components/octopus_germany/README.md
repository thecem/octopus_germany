# Octopus Germany Integration for Home Assistant

This custom component integrates Octopus Germany services with Home Assistant, providing access to your energy account data, electricity prices, device control, and vehicle charging preferences.


[![hacs_badge](https://img.shields.io/badge/HACS-Custom-41BDF5.svg)](https://github.com/hacs/integration)
![installation_badge](https://img.shields.io/badge/dynamic/json?color=41BDF5&logo=home-assistant&label=integration%20usage&suffix=%20installs&cacheSeconds=15600&url=https://analytics.home-assistant.io/custom_integrations.json&query=$.octopus_germany.total)

This integration is in no way affiliated with Octopus Energy.

If you find this useful and are planning on moving to Octopus Energy Germany, why not use my [referral link](https://share.octopusenergy.de/free-cat-744)?

## Features

- **Account Information**: Electricity and gas balance tracking across multiple accounts
- **Energy Pricing**: Real-time electricity tariff prices with support for:
  - Simple tariffs (fixed rate)
  - Time of Use tariffs (GO, STANDARD rates)
  - Heat tariffs (for heat pumps)
- **Multi-Ledger Support**: Electricity, Gas, Heat, and other ledger types
- **Device Control**: Smart charging control for electric vehicles and charge points
- **Boost Charging**: Instant charge boost functionality (requires smart charging enabled)
- **Intelligent Dispatching**: Real-time status of Octopus Intelligent charge scheduling
- **Multi-Account**: Support for multiple Octopus accounts under one integration

## Installation

### HACS (Home Assistant Community Store)

[![hacs_badge](https://img.shields.io/badge/HACS-Default-41BDF5.svg?style=for-the-badge)](https://github.com/hacs/integration)

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

#### Electricity Price
- **Entity ID**: `sensor.octopus_<account_number>_electricity_price`
- **Description**: Current electricity rate per kWh
- **Unit**: EUR/kWh
- **Attributes**:
  - `code`: Product code
  - `name`: Product name
  - `description`: Product description
  - `type`: Product type (Simple or TimeOfUse)
  - `timeslot`: Current timeslot (GO/STANDARD for Time of Use tariffs)
  - `valid_from`: Start date of validity
  - `valid_to`: End date of validity

#### Electricity Balance
- **Entity ID**: `sensor.octopus_<account_number>_electricity_balance`
- **Description**: Current account balance
- **Unit**: EUR
- **Note**: Negative values indicate credit, positive values indicate debt

#### Electricity Latest Reading
- **Entity ID**: `sensor.octopus_<account_number>_electricity_latest_reading`
- **Description**: Most recent meter reading
- **Unit**: kWh
- **Attributes**:
  - `reading_date`: When the reading was taken
  - `meter_number`: Physical meter identifier

#### Device Status
- **Entity ID**: `sensor.octopus_<account_number>_device_status`
- **Description**: Status of connected smart devices (vehicles, charge points)
- **Attributes**: Device-specific information including battery status, charging state, etc.

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
  - `name`: Name of the device
  - `model`: Vehicle model (if available)
  - `battery_size`: Battery capacity (if available)
  - `provider`: Device provider
  - `status`: Current status of the device
  - `last_updated`: Timestamp of the last update

## Services

Services are available for configuring device preferences. See the Developer Tools > Services section in Home Assistant for available services and their parameters.

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

## Support

For bug reports and feature requests, please open an issue on the GitHub repository.
Before raising anything, please read through the [discussion](https://thecem.github.io/octopus_germany/discussions).
If you have found a bug or have a feature request please [raise it](https://thecem.github.io/octopus_germany/issues) using the appropriate report template.

## Sponsorship

If you are enjoying the integration, why not use my [referral link](https://share.octopusenergy.de/free-cat-744)

## License

This project is licensed under the MIT License - see the LICENSE file for details.

## Disclaimer

This integration is not officially affiliated with Octopus Energy Germany. Use at your own risk.
