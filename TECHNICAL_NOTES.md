# Octopus Germany Integration - Technical Documentation

## Architecture Overview

### Core Components
- **Account Coordinator** (`coordinator`): Polls slow-changing data (tariffs, balance, meter info) every 30 minutes using `DataUpdateCoordinator`.
- **Device Coordinator** (`device_coordinator`): Polls fast-changing data (device status, dispatches, charging sessions) every 5 minutes using a separate `DataUpdateCoordinator`.
- **API Client** (`octopus_germany.py`): Handles GraphQL authentication, token refresh, and all API calls.
- **Platforms**: binary_sensor, sensor, switch — slow entities subscribe to `coordinator`, fast device entities subscribe to `device_coordinator`.
- **Token Management**: Automatic refresh with 50-minute intervals, robust error handling.

### Key Implementation Details

#### Token Management & Authentication
- **Shared Token Strategy**: Both coordinators share the same `OctopusGermany` API client instance, which manages token state internally.
- **Auto-Refresh**: Background task refreshes tokens every 50 minutes.
- **Error Handling**: 5 retry attempts with exponential backoff on login failures.
- **GraphQL Client**: Centralized `_get_graphql_client()` method for consistent authentication.

#### Data Flow Architecture
```
API Client (octopus_germany.py)
    ↓ (GraphQL + Token Management)
    ├── Account Coordinator  (30 min)       ← slow-changing data
    │       ↓ (Shared Data)
    │   ├── Sensors: electricity/gas price, balance, meter readings
    │   └── Sensors: infrastructure (MALO, MELO, meter info)
    │
    └── Device Coordinator  (5 min)         ← fast-changing data
            ↓ (Shared Data)
        ├── Binary Sensor: intelligent dispatching
        ├── Sensors: device status, smart charging sessions
        └── Switches: device suspension, boost charge
```

#### Data the Octopus Kraken API does NOT push
The Kraken GraphQL API is purely poll-based — there are no webhooks or subscriptions available for Germany accounts at this time.  The two-coordinator split is therefore the most efficient approach: frequent polls for state that changes in real time, infrequent polls for data that changes at most daily.

#### Critical Implementation Rules

1. **Coordinator Access Pattern**:
   ```python
   # CORRECT
   data = hass.data[DOMAIN][entry.entry_id]
   coordinator        = data["coordinator"]         # slow data
   device_coordinator = data["device_coordinator"]  # fast data

   # WRONG - Never create additional coordinators inside a platform setup
   # coordinator = SeparateCoordinator(hass, client, account)
   ```

2. **Which coordinator to use**:
   | Entity / Data | Coordinator |
   |---|---|
   | Electricity/gas price, tariff rates | `coordinator` |
   | Account balance, ledgers | `coordinator` |
   | Meter numbers (MALO/MELO), meter info | `coordinator` |
   | Smart meter consumption readings | `coordinator` |
   | Device status / suspension state | `device_coordinator` |
   | Planned dispatches, completed dispatches | `device_coordinator` |
   | Charging sessions | `device_coordinator` |
   | Device suspension switch, boost charge switch | `device_coordinator` |
   | Intelligent dispatching binary sensor | `device_coordinator` |

3. **Token Sharing**:
   - Never create separate GraphQL clients in platform entities.
   - Always use `self.client._get_graphql_client()` for mutations.
   - Let the main API client handle all token management.

4. **Data Structure**:
   ```python
   # Slow coordinator
   coordinator.data = {
       "account_number": {
           "products": [...],
           "electricity_balance": ...,
           "malo_number": ...,
           # ... other slow account data
       }
   }

   # Fast coordinator
   device_coordinator.data = {
       "account_number": {
           "devices": [...],
           "charging_sessions": [...],
           "planned_dispatches": [...],
           "completed_dispatches": [...],
           "current_start": ...,
           "current_end": ...,
           "next_start": ...,
           "next_end": ...,
       }
   }
   ```

#### Switch Platform Specifics

##### Device Suspension Switches
- Created for each device in coordinator data
- Uses `change_device_suspension()` API method
- Pending state management with 5-minute timeout

##### Boost Charge Switches
- **CRITICAL**: Only available when Smart Charge is enabled
- Created only for devices with `deviceType` in `["ELECTRIC_VEHICLES", "CHARGE_POINTS"]`
- Uses GraphQL `updateBoostCharge` mutations
- **Availability Logic**:
  ```python
  # Device must be LIVE and either:
  # - SMART_CONTROL_CAPABLE, OR
  # - Already in BOOST state, OR
  # - Currently BOOST_CHARGING
  is_available = (
      current == "LIVE" and
      (has_smart_control or has_boost_state or has_boost_charging) and
      not is_suspended
  )
  ```

#### Services

##### set_device_preferences
- **Current Service**: Uses new SmartFlexDeviceInterface API
- **Parameters**: device_id, target_percentage (20-100%), target_time (04:00-17:00)
- **GraphQL Mutation**: `setDevicePreferences`
- **Validation**: Time format handling, percentage validation

##### ~~set_vehicle_charge_preferences~~ (DEPRECATED)
- **Status**: Completely removed as of v0.0.61
- **Replacement**: Use `set_device_preferences` instead
- **Migration**: Users must update automations to use device_id instead of account-level settings

#### Error Handling Patterns

1. **Token Expiry**:
   - Automatic retry with fresh token
   - Graceful degradation to cached data
   - User notification via logs

2. **GraphQL Errors**:
   - Parse error messages from response
   - Raise `HomeAssistantError` with user-friendly messages
   - Log technical details for debugging

3. **API Rate Limiting**:
   - Respect 90% of update interval before new API calls
   - Throttling mechanism in coordinator

#### Testing & Validation

##### Critical Test Scenarios
1. **Token Expiry Recovery**: Simulate expired tokens, verify auto-refresh
2. **Boost Switch Availability**: Test with/without Smart Charge enabled
3. **Service Calls**: Validate both services with various parameters
4. **Multi-Account Support**: Test with multiple Octopus accounts
5. **Error Resilience**: Network issues, API errors, malformed responses

##### Debug Settings
```yaml
logger:
  logs:
    custom_components.octopus_germany: debug
    custom_components.octopus_germany.octopus_germany: debug
    custom_components.octopus_germany.switch: debug
```

#### Performance Considerations

- **Account coordinator interval**: 30 minutes (slow-changing tariff and balance data)
- **Device coordinator interval**: 5 minutes (fast-changing device status and dispatches)
- **API Call Throttling**: HA's built-in coordinator debouncing prevents burst requests
- **Cached Data Fallback**: Returns last known data on API failures
- **Efficient GraphQL**: Separate queries for slow and fast data reduce payload size per poll

#### Security Notes

- **Token Storage**: Tokens stored in memory only, not persisted
- **Credential Handling**: Email/password from config entry, not logged
- **GraphQL Endpoint**: Uses official Octopus Energy Kraken API
- **HTTPS Only**: All API communication over TLS

#### Migration & Compatibility

- **Breaking Changes**: Document in release notes
- **Config Migration**: Handle old config entries gracefully
- **API Versioning**: Monitor for Octopus API changes
- **Backward Compatibility**: Maintain for at least 2 major versions

#### Maintenance Checklist

1. **Regular Updates**:
   - Monitor Octopus API changes
   - Update GraphQL schema if needed
   - Test with Home Assistant core updates

2. **Code Quality**:
   - Follow Home Assistant coding standards
   - Maintain test coverage
   - Document all public APIs

3. **User Support**:
   - Clear error messages
   - Comprehensive documentation
   - Migration guides for breaking changes

## Known Issues & Workarounds

1. **Device Type Mapping**: Some devices may have unexpected `deviceType` values
2. **Time Zone Handling**: API uses UTC, local conversion needed for UI
3. **GraphQL Schema Evolution**: Monitor for field additions/deprecations

## Future Considerations

- **WebSocket Support**: Real-time updates from Octopus API
- **Advanced Scheduling**: More complex charge scheduling options
- **Energy Dashboard**: Integration with HA Energy features
- **Automation Templates**: Pre-built automations for common scenarios