# Octopus Germany Integration for Home Assistant

This custom component integrates Octopus Germany services with Home Assistant, providing access to your energy account data, electricity prices, device control, and vehicle charging preferences.


[![hacs_badge](https://img.shields.io/badge/HACS-Custom-41BDF5.svg)](https://github.com/hacs/integration)
![installation_badge](https://img.shields.io/badge/dynamic/json?color=41BDF5&logo=home-assistant&label=integration%20usage&suffix=%20installs&cacheSeconds=15600&url=https://analytics.home-assistant.io/custom_integrations.json&query=$.octopus_germany.total)

This integration is in no way affiliated with Octopus Energy.

If you find this useful and are planning on moving to Octopus Energy Germany, why not use my [referral link](https://share.octopusenergy.de/free-cat-744)?

## Features

- Account information display with electricity and gas balances
- Current electricity and gas tariff prices
- Support for Octopus tariff types:
  - Simple tariffs (fixed rate)
  - Time of Use tariffs (different rates at different times)
  - Dynamic tariffs (with real-time pricing using unit rate forecasts)
  - Heat tariffs (for heat pumps)
- Gas infrastructure monitoring (MALO/MELO numbers, meters, readings)
- Latest Electricity meter reading
- Gas contract tracking with expiry countdown
- Device smart control (suspend/unsuspend charging)
- Electric vehicle charging preferences management
- Intelligent dispatching status tracking

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
  - `is_dynamic_tariff`: Boolean flag indicating whether this is a dynamic pricing tariff with real-time rates

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
  - `register_obis_code`: OBIS code for the register
  - `register_type`: Type of the register
  - `meter_id`: ID of the electricity meter
  - `read_at`: Raw timestamp from API
  - `account_number`: Your Octopus Energy account number

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

#### Intelligent Dispatching Binary Sensor

- **Entity ID**: `binary_sensor.octopus_<account_number>_intelligent_dispatching`
- **Description**: Shows whether intelligent dispatching (smart charging) is currently active
- **State**: `on` when a dispatch is active, `off` otherwise
- **Attributes**:
  - `planned_dispatches`: List of upcoming charging sessions
  - `completed_dispatches`: List of past charging sessions
  - `devices`: List of connected devices
  - `current_state`: Current state of your smart charging device
  - `last_updated`: Timestamp of the last update

### Switches

#### Device Smart Control

- **Entity ID**: `switch.octopus_<account_number>_device_smart_control`
- **Description**: Controls whether smart charging is enabled for your vehicle
- **Actions**:
  - Turn **ON** to enable smart charging (unsuspend)
  - Turn **OFF** to disable smart charging (suspend)
- **Attributes**:
  - `device_id`: Internal ID of the connected device
  - `name`: Name of the device
  - `model`: Vehicle model (if available)
  - `battery_size`: Battery capacity (if available)
  - `provider`: Device provider
  - `status`: Current status of the device
  - `last_updated`: Timestamp of the last update

## Services

### Set Vehicle Charge Preferences

- **Service ID**: `octopus_germany.set_vehicle_charge_preferences`
- **Description**: Configure your vehicle's charging preferences
- **Parameters**:
  - `account_number` (optional): Your Octopus Energy account number (uses account from configuration if not specified)
  - `weekday_target_soc` (required): Target state of charge (in %) for weekdays
  - `weekend_target_soc` (required): Target state of charge (in %) for weekends
  - `weekday_target_time` (required): Target time for weekday charging (HH:MM)
  - `weekend_target_time` (required): Target time for weekend charging (HH:MM)

**Example:**

```yaml
# Example automation to set vehicle charging preferences to 80% by 7:30 AM on weekdays and 90% by 9:00 AM on weekends
service: octopus_germany.set_vehicle_charge_preferences
data:
  weekday_target_soc: 80
  weekend_target_soc: 90
  weekday_target_time: "07:30"
  weekend_target_time: "09:00"
```
## Automation

[Octopus Intelligent Go mit EVCC](https://github.com/ha-puzzles/homeassistant-puzzlepieces/blob/main/use-cases/stromtarife/octopus-intelligent-go/README.md)

## Debugging

If you encounter issues, you can enable debug logging by adding the following to your `configuration.yaml`:

```yaml
logger:
  logs:
    custom_components.octopus_germany: debug
```
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

## Sponsorship

If you are enjoying the integration, why not use my [referral link](https://share.octopusenergy.de/free-cat-744)

## License

This project is licensed under the MIT License - see the LICENSE file for details.

## Disclaimer

This integration is not officially affiliated with Octopus Energy Germany. Use at your own risk.

# OEG Kraken Energy API Client

A comprehensive Python client for interacting with the OEG Kraken Energy API, based on the official developer documentation at https://developer.oeg-kraken.energy/.

## Features

- **Complete API Coverage**: Supports all major endpoints including account management, consumption data, tariff rates, meter readings, and billing information
- **REST & GraphQL Support**: Both REST API and GraphQL interfaces for maximum flexibility
- **Type Safety**: Fully typed with modern Python type hints
- **Flexible Authentication**: Support for environment variables and configuration files
- **Utility Functions**: Built-in functions for common operations like cost calculations and data analysis
- **Error Handling**: Comprehensive error handling with proper logging
- **Data Models**: Structured data classes for clean data handling
- **Advanced Analytics**: Energy insights, weather correlation, and tariff optimization

## Installation

1. Clone this repository or copy the `kraken_api` folder to your project
2. Install required dependencies:

```bash
pip install requests
```

## Quick Start

### 1. Set up credentials

You can configure your API credentials in two ways:

#### Option A: Environment Variables
```bash
export KRAKEN_API_KEY="your-api-key-here"
export KRAKEN_ACCOUNT_NUMBER="your-account-number"
export KRAKEN_BASE_URL="https://api.oeg-kraken.energy"  # Optional, defaults to this
```

#### Option B: Configuration File
Create a file at `~/.config/octopus_germany/kraken_config.json`:
```json
{
  "api_key": "your-api-key-here",
  "account_number": "your-account-number",
  "base_url": "https://api.oeg-kraken.energy"
}
```

### 2. Basic Usage

#### REST API Client
```python
from kraken_api import KrakenApiClient
from kraken_api.config import load_credentials
from datetime import datetime, timedelta

# Load credentials
credentials = load_credentials()

# Create client
client = KrakenApiClient(credentials)

# Get account information
account_info = client.get_account_info()
print(f"Account: {account_info['number']}")

# Get consumption data
if properties:
    prop = properties[0]
    electricity_meters = prop.get('electricity_meter_points', [])
    if electricity_meters:
        mpan = electricity_meters[0]['mpan']

        # Get last 30 days of consumption
        end_date = datetime.now()
        start_date = end_date - timedelta(days=30)

        consumption = client.get_electricity_consumption(
            mpan, start_date, end_date, 'day'
        )

        print(f"Consumption records: {len(consumption)}")
        if consumption:
            total = sum(record.consumption for record in consumption)
            print(f"Total consumption: {total:.2f} kWh")
```

#### GraphQL Client
```python
from kraken_api import KrakenGraphQLClient
from kraken_api.config import load_credentials

# Load credentials
credentials = load_credentials()

# Create GraphQL client
client = KrakenGraphQLClient(credentials)

# Get comprehensive account details with nested data
account_details = client.get_account_details()
account = account_details['account']

print(f"Account: {account['number']}")
print(f"Balance: €{account['balance']:.2f}")

# Get detailed consumption with statistics
consumption_data = client.get_consumption_data(
    mpan, start_date, end_date, "electricity", "DAY"
)

consumption = consumption_data['electricityMeterPoint']['consumption']
print(f"Total consumption: {consumption['totalConsumption']:.2f} kWh")
print(f"Total cost: €{consumption['totalCost']:.2f}")
print(f"Peak usage: {consumption['statistics']['peakConsumption']:.2f} kWh")
```

## API Methods

### REST API Methods
- `get_account_info()`: Get account information
- `get_properties()`: Get all properties associated with the account
- `get_electricity_consumption()`: Get electricity consumption data
- `get_gas_consumption()`: Get gas consumption data
- `get_electricity_tariff_rates()`: Get electricity tariff rates
- `get_gas_tariff_rates()`: Get gas tariff rates
- `submit_meter_reading()`: Submit meter reading
- `get_payments()`: Get payment history
- `get_bills()`: Get billing information
- `get_products()`: Get available products

### GraphQL API Methods
- `get_account_details()`: Get comprehensive account information with nested data
- `get_consumption_data()`: Get detailed consumption data with statistics
- `get_tariff_comparison()`: Compare costs across different tariffs
- `get_smart_devices()`: Get smart devices and their status
- `set_device_preferences()`: Set preferences for smart devices
- `get_products_and_tariffs()`: Get available products and tariffs
- `get_carbon_intensity()`: Get carbon intensity data
- `get_energy_insights()`: Get energy insights and recommendations
- `get_live_consumption()`: Get live consumption data
- `get_weather_data()`: Get weather data for energy analysis
- `get_grid_supply_points()`: Get grid supply point information

### Advanced Utility Functions
- `get_comprehensive_account_overview()`: Complete account overview
- `analyze_consumption_with_weather()`: Consumption analysis with weather correlation
- `compare_tariff_scenarios()`: Advanced tariff comparison
- `get_smart_charging_optimization()`: Smart charging optimization
- `get_energy_efficiency_report()`: Comprehensive efficiency report
- `get_grid_flexibility_opportunities()`: Grid flexibility analysis

## Data Models

### ApiCredentials
```python
@dataclass
class ApiCredentials:
    api_key: str
    account_number: str
    base_url: str = "https://api.oeg-kraken.energy"
```

### EnergyConsumption
```python
@dataclass
class EnergyConsumption:
    interval_start: datetime
    interval_end: datetime
    consumption: float
    unit: str
```

### TariffRate
```python
@dataclass
class TariffRate:
    valid_from: datetime
    valid_to: datetime | None
    value_exc_vat: float
    value_inc_vat: float
    unit: str
```

## Advanced Usage

### GraphQL vs REST

**GraphQL Advantages:**
- Request exactly the data you need
- Single request for complex nested data
- Built-in statistics and analytics
- Advanced filtering and grouping
- Real-time data capabilities

**Use GraphQL when:**
- You need detailed, nested data in one request
- You want consumption statistics and analytics
- You're building dashboards or reports
- You need real-time or live data
- You want to minimize API calls

**Use REST when:**
- You need simple, straightforward data
- You're doing basic CRUD operations
- You want to minimize complexity
- You're building simple integrations

### Energy Analytics with Weather Correlation

```python
from kraken_api.graphql_utils import analyze_consumption_with_weather

# Analyze consumption patterns with weather data
weather_analysis = analyze_consumption_with_weather(
    client, mpan, postcode, start_date, end_date
)

# Get high usage days with weather conditions
high_usage_days = weather_analysis["insights"]["high_usage_weather_conditions"]
for day in high_usage_days:
    print(f"High usage: {day['consumption']:.2f} kWh on {day['date']}")
    print(f"Temperature: {day['temperature']}°C")
    print(f"Conditions: {day['conditions']}")
```

### Smart Charging Optimization

```python
from kraken_api.graphql_utils import get_smart_charging_optimization

# Get smart charging optimization recommendations
optimization = get_smart_charging_optimization(client)

# Show current settings
for device_id, settings in optimization["current_settings"].items():
    print(f"Device {device_id}:")
    print(f"  Charging enabled: {settings['charging_enabled']}")
    print(f"  Target SoC: {settings['target_soc']}%")
    print(f"  Target time: {settings['target_time']}")

# Show performance metrics
metrics = optimization["performance_metrics"]
print(f"Average charging cost: €{metrics['average_charging_cost']:.2f}")
print(f"Carbon intensity: {metrics['carbon_intensity_average']:.0f} gCO2/kWh")
```

### Tariff Optimization

```python
from kraken_api.graphql_utils import compare_tariff_scenarios

# Compare different tariff scenarios
comparison = compare_tariff_scenarios(
    client, mpan, ["AGILE-FLEX-22-11-25", "INTELLIGENT-GO-22-11-25"]
)

best_tariff = comparison["recommendations"]["best_overall"]
print(f"Best tariff: {best_tariff['tariff_name']}")
print(f"Potential savings: €{best_tariff['potential_savings']:.2f}")
```

### Energy Efficiency Report

```python
from kraken_api.graphql_utils import get_energy_efficiency_report

# Generate comprehensive efficiency report
report = get_energy_efficiency_report(client, period_months=12)

print(f"Efficiency score: {report['efficiency_score']:.1f}/10")
print(f"Potential savings: €{report['cost_analysis']['potential_savings']:.2f}")

# Show recommendations
for rec in report["recommendations"]:
    print(f"• {rec['title']}: €{rec['potential_savings']:.2f} savings")
```

## Error Handling

Both clients include comprehensive error handling:

```python
from kraken_api import GraphQLError

try:
    # REST API
    consumption = client.get_electricity_consumption(mpan, start_date, end_date)

    # GraphQL API
    account_details = graphql_client.get_account_details()

except GraphQLError as e:
    print(f"GraphQL errors: {e.errors}")
except requests.exceptions.RequestException as e:
    print(f"API request failed: {e}")
except ValueError as e:
    print(f"Invalid parameters: {e}")
```

## Logging

Both clients use Python's built-in logging module:

```python
import logging
logging.basicConfig(level=logging.DEBUG)
```

## Example Scripts

- `example_usage.py`: Complete REST API example
- `example_graphql_usage.py`: Complete GraphQL API example

## Rate Limiting

Both clients automatically handle rate limiting according to the API's guidelines.

## Contributing

1. Follow the existing code style and type hints
2. Add appropriate error handling and logging
3. Include docstrings for all public methods
4. Add tests for new functionality

## License

This project is provided as-is for educational and development purposes. Please review the OEG Kraken Energy API terms of service before use.

## Support

For API-related questions, consult the official documentation:
- REST API: https://developer.oeg-kraken.energy/
- GraphQL API: https://developer.oeg-kraken.energy/graphql/

For client-specific issues, please check the code and error messages for troubleshooting guidance.
