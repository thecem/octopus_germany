# Octopus Germany Integration - Technical Documentation

## Architecture Overview

### Core Components
- **Base Coordinator**: Account, tariff, meter and optional grid-fee data using `DataUpdateCoordinator`
- **Intelligent Coordinator**: Optional device and dispatch polling for eligible accounts
- **API Client** (`octopus_germany.py` plus `api/` mixins): Handles GraphQL authentication, token refresh, and endpoint-specific API calls
- **Platforms**: binary_sensor, sensor and switch consume the shared coordinator data
- **Token Management**: Automatic refresh with 50-minute intervals, robust error handling

### Key Implementation Details

#### GraphQL Endpoints and Schemas

- **Kraken API**: `https://api.oeg-kraken.energy/v1/graphql/`
   - Schema snapshot: `custom_components/octopus_germany/oeg_graphql_schema.yaml`
- **OE Backend API**: `https://api.backend.octopusenergy.de/v1/graphql/`
   - Used for `variableGridFees` and authenticated with the shared Kraken token
   - Schema snapshot: `custom_components/octopus_germany/oe_backend_graphql_schema.json`
- The customer portal proxies these endpoints through separate same-origin routes. Integration code calls the upstream APIs directly and never forwards browser cookies.

#### Token Management & Authentication
- **Shared Token Strategy**: All platforms use `hass.data[DOMAIN][entry.entry_id]["coordinator"]`
- **Auto-Refresh**: Background task refreshes tokens every 50 minutes
- **Error Handling**: 5 retry attempts with exponential backoff on login failures
- **GraphQL Clients**: `_get_graphql_client()` for Kraken and `_get_oe_backend_graphql_client()` for OE backend operations, both using shared authentication

#### Data Flow Architecture
```
API Client (octopus_germany.py)
    ↓ (GraphQL + Token Management)
Base Coordinator + optional Intelligent Coordinator
    ↓ (Shared Data)
├── Binary Sensor (intelligent dispatching)
├── Sensors (price, balance, meter readings, device status)
└── Switches (device suspension, boost charge)
```

#### Critical Implementation Rules

1. **Coordinator Access Pattern**:
   ```python
   # CORRECT - All platforms must use this pattern
   data = hass.data[DOMAIN][entry.entry_id]
   coordinator = data["coordinator"]

   # WRONG - Never create separate coordinators inside platforms
   # coordinator = SeparateCoordinator(hass, client, account)
   ```

2. **Token Sharing**:
   - Never create separate GraphQL clients in platform entities
   - Use the API client's endpoint-specific GraphQL client; platform entities must not create clients
   - Let the main API client handle all token management

3. **Data Structure**:
   ```python
   coordinator.data = {
       "account_number": {
           "devices": [...],
           "products": [...],
           "planned_dispatches": [...],
           # ... other account data
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

- **Update Interval**: 1 minute (configurable)
- **API Call Throttling**: Prevents excessive requests
- **Cached Data Fallback**: Returns last known data on API failures
- **Efficient GraphQL**: Single query fetches all account data

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
3. **GraphQL Schema Evolution**: Monitor both endpoint schemas for field additions/deprecations; do not merge their distinct Query roots

## Future Considerations

- **WebSocket Support**: Real-time updates from Octopus API
- **Advanced Scheduling**: More complex charge scheduling options
- **Energy Dashboard**: Integration with HA Energy features
- **Automation Templates**: Pre-built automations for common scenarios