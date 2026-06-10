# Release Notes

## Version 0.0.96 (2026-06-10)

### 🔧 Fixes

#### Service Response in Home Assistant Actions UI
- `get_smart_meter_readings` and `export_smart_meter_csv` are now registered as
  response-capable services (`SupportsResponse.ONLY`).
- The returned data is visible directly in the **Actions** window in Home Assistant,
  in addition to the existing fired events
  (`octopus_germany_smart_meter_readings_result` and `octopus_germany_csv_export_result`).

---

## Version 0.0.95 (2026-06-08)

### 🎉 New Features

#### Plugged-In Binary Sensor (pro Device)
- **Neuer Sensor**: `binary_sensor.octopus_<account_number>_<device_name>_plugged`
- Zeigt an, ob das Fahrzeug eingesteckt ist — **jedoch nur zuverlässig wenn Smart Control aktiviert ist**

##### Wie der Sensor funktioniert
Die Octopus-API liefert kein dediziertes `isPlugged`-Feld für Fahrzeuge.
Der Sensor leitet den Steckstatus aus zwei API-Feldern ab:

| `isSuspended` | `currentState` | Sensor-Zustand |
|---|---|---|
| `true` (Smart Control aus) | beliebig | `unknown` — nicht zuverlässig bestimmbar |
| `false` | `SMART_CONTROL_NOT_AVAILABLE` | `off` — nicht eingesteckt / nicht zuhause |
| `false` | alles andere | `on` — eingesteckt, Smart Control bereit |

> **Wichtig:** Wenn Smart Control manuell deaktiviert ist (`isSuspended = true`),
> kann die API nicht zwischen „eingesteckt aber pausiert" und „abgesteckt" unterscheiden.
> Der Sensor gibt in diesem Fall `unknown` zurück.

### 🔧 Korrekturen am Plugged-Sensor
- Mapping auf korrekte `SmartFlexDeviceState`-Enum-Werte umgestellt
  (vorher fehlerhafte String-Hints wie `"PLUGGED"`, `"CHARGING"` die die API nie liefert)
- `SMART_CONTROL_OFF` korrekt auf `unknown` gesetzt statt fälschlicherweise `on`
- Lifecycle-Guard: Bei `current != LIVE` liefert der Sensor ebenfalls `unknown`

### ℹ️ Bekannte API-Einschränkungen (Stand 2026-06)

Nach vollständiger Schema-Introspection der OEG-Kraken-API wurden folgende Felder
gesucht und **nicht gefunden bzw. nicht nutzbar**:

| Feature | Status |
|---|---|
| **Odometer / Kilometerstand** | ❌ Nicht vorhanden — weder in `SmartFlexVehicle` noch anderswo |
| **GPS-Koordinaten** | ❌ `locationLatitude`/`locationLongitude` existieren nicht für Fahrzeug-Statustypen |
| **Dispatch-Standort** | ⚠️ `completedDispatches.meta.location` ist ein einfacher String, kein Koordinatenobjekt |
| **Ziel-SoC (`upperSocLimit`)** | ⚠️ Im Schema definiert, liefert für VW ID.4 aktuell `null` — Provider übermittelt diesen Wert nicht |
| **`isPlugged` als Boolean** | ❌ Nur für `BatteryDeviceType` (Hausspeicher) vorhanden, nicht für Fahrzeuge |

## Version 0.0.94 (2026-06-07)

### 🎉 New Features

#### Plugged-In Binary Sensor
- **New Sensor**: `binary_sensor.octopus_<account_number>_<device_name>_plugged`
  - Per-device plugged-in state derived from SmartFlex `status.currentState`
  - Uses robust state hint mapping (`PLUGGED`, `CHARGING`, `FINISHED`, `SMART_CONTROL`)
  - Adds transparent debug attributes (`current_state`, `current`, `is_suspended`, `plugged_in_inferred`)

### 🔧 Improvements

#### Dispatch Location Clarification
- Confirmed `completedDispatches.meta.location` is exposed by API as `String`
- Clarified this is not a coordinate payload (`latitude`/`longitude`) in the current dispatch metadata path

## Version 0.0.93 (2026-06-07)

### 🎉 New Features

#### Vehicle Data Sensors
- **New Sensor**: `sensor.octopus_<account_number>_<device_name>_soc`
  - Per-vehicle state of charge (SoC) in `%`
  - Uses live status data (`stateOfCharge.value`) when available
  - Falls back to latest charging session (`stateOfChargeFinal`) if needed

- **New Sensor**: `sensor.octopus_<account_number>_<device_name>_battery_size`
  - Per-vehicle battery size in `kWh`

### 🔧 Improvements

#### GraphQL / API Compatibility
- Fixed SmartFlex status query to use inline fragments for type-specific fields
  - `SmartFlexVehicleStatus`
  - `SmartFlexChargePointStatus`
- Fixed `stateOfCharge` query shape to match API type `DecimalReading`
  - now queried as `stateOfCharge { value timestamp }`

#### Sensor Robustness
- Prevented coordinator listener crashes when `charging_sessions` is `null`
- Added defensive handling for missing/partial device and session payloads

### ❌ Removed

- Removed `SoC Change` sensor (`..._soc_change`)
- Removed `SoC Limit` sensor (`..._soc_limit`)

Reason:
- These values are not reliably provided by all providers/devices and caused confusion (`Nicht verfügbar`) in normal operation.

### 📝 Documentation Updates

- Updated both README files to document current vehicle sensors (`SoC`, `Battery Size`)
- Removed documentation for `SoC Change` and `SoC Limit`

### ⚙️ Release Automation

- Updated release workflow in `.github/workflows/tag-and-release.yaml`
  - Releases now use the matching section from `RELEASE_NOTES.md` as primary content
  - Auto-generated GitHub notes are appended as additional context
  - Fallback to auto-generated notes remains in place if a matching version section is missing

Result:
- New features and removals are now reliably visible in GitHub releases.

## Version 0.0.66 (2025-11-22)

### 🎉 New Features

#### Smart Charging Sessions Tracking
- **New Sensor**: `sensor.octopus_<account>_smart_charging_sessions`
  - Tracks smart charging sessions for Octopus SmartFlex rewards (30€/month with ≥5 smart charges)
  - Shows current month count and progress toward reward eligibility
  - Attributes include: session history, energy totals, qualified months, rewards earned
  - Auto-filters SMART vs BOOST charging types

#### Smart Meter Readings
- **New Sensor**: `sensor.octopus_<account>_previous_accumulative_consumption_electricity`
  - Displays previous day's total electricity consumption from smart meter
  - Hourly breakdown in attributes for detailed analysis
  - Persistent state restoration on Home Assistant restart
  - Auto-updates when smart meter data becomes available (typically 2+ days lag)

- **New Service**: `octopus_germany.get_smart_meter_readings`
  - Fetch historical smart meter data for any date (YYYY-MM-DD format)
  - Useful for backfilling data or analyzing specific periods
  - Results available via event: `octopus_germany_smart_meter_readings_result`

#### Device Organization
- **Service Device Grouping**: All entities now grouped under single service device per account
  - Device name: "Octopus Energy Germany (A-xxxxxxx)"
  - Type: SERVICE (cloud service, not hardware)
  - Configuration link to https://my.octopusenergy.de/
  - Cleaner device registry - no more scattered entities

### 🔧 Improvements

#### API Enhancements
- Added comprehensive GraphQL schema exploration (54,000+ lines)
- New charging sessions query with device type filtering
- Smart meter readings query with property-based filtering
- Multiple date range testing for data availability
- Enhanced error handling with detailed logging

#### Token Management
- Fixed token refresh logic to clear expired tokens before login
- Improved retry mechanism with exponential backoff
- Better handling of concurrent token refresh attempts
- Restored previous token on complete login failure

#### Code Quality
- All 22 entities now have consistent `device_info` property
- Proper use of `DeviceEntryType.SERVICE` enum
- Improved typing with `RestoreEntity` for persistent sensors
- Cleaner imports and consistent code formatting
- Fixed `OctopusGermanyOptionsFlow` initialization

### 📝 Configuration Changes

#### New Constants
- `EXPLORE_SCHEMA_ONCE`: Control schema exploration (debug feature)
- Service constants for smart meter readings:
  - `SERVICE_GET_SMART_METER_READINGS`
  - `ATTR_DATE`
  - `ATTR_PROPERTY_ID`

#### Updated Services Definition
- Added `get_smart_meter_readings` service configuration
- Includes validation for date format (YYYY-MM-DD)
- Optional property_id (uses first property if not specified)

### 🐛 Bug Fixes

- **Device Status Sensor**: Now properly filters by device_id (previously showed only first device)
- **Binary Sensor**: Added missing `device_info` property
- **Switches**: Added missing `device_info` property
- **Options Flow**: Fixed initialization to accept config_entry parameter correctly
- **Formatting**: Cleaned up line wrapping and improved readability

### 📖 Documentation Updates

- Updated README with:
  - Smart charging sessions sensor documentation
  - Smart meter readings sensor and service documentation
  - Device grouping explanation
  - Service examples and automation ideas
- Added detailed attribute descriptions for new sensors
- Clarified data availability timelines (smart meter data lag)

### 🔄 Migration Notes

**Automatic Migration** (no action required):
- Existing entities will automatically be grouped under service device on next HA restart
- All entity IDs remain unchanged
- Historical data is preserved

**New Functionality**:
- Smart charging sessions: Automatically created if you have SmartFlex devices
- Smart meter readings: Automatically created if you have electricity service
- Service device: Visible in Devices & Services after restart

### 🎯 Requirements

- Home Assistant 2024.1.0 or newer
- Python 3.11 or newer
- `python-graphql-client==0.4.3` (unchanged)

### 📊 Statistics

- **New Sensors**: 2 (Smart Charging Sessions, Smart Meter Readings)
- **New Services**: 1 (Get Smart Meter Readings)
- **Code Changes**: ~2,500+ lines added/modified
- **Files Changed**: 9 core files
- **Device Info Coverage**: 100% (22/22 entities)

### 🙏 Acknowledgments

Thanks to all users providing feedback and testing the integration!

### 📞 Support

For issues or questions:
- GitHub Issues: https://github.com/thecem/octopus_germany/issues
- Discussions: https://github.com/thecem/octopus_germany/discussions

---

## Previous Releases

### Version 0.0.65 (2025-11-22)

**Note**: Version 0.0.65 was released on GitHub with partial features.
Version 0.0.66 completes the implementation with all features fully documented.

### Version 0.0.64 (2025-09-22)

**Highlights**
 - Fix: Boost Charge switch could become unavailable due to independent coordinator using an expired JWT. The boost switch now uses the main coordinator and shared token handling.
 - Fix: Restored `boost_charge_active` and `boost_charge_available` attributes on the Boost Charge switch.
 - Cleanup: Removed remnants of deprecated `set_vehicle_charge_preferences` service and consolidated to `set_device_preferences`.
 - Docs: Updated `custom_components/octopus_germany/README.md` and added `TECHNICAL_NOTES.md` describing architecture, token management, and availability rules for the boost switch.
 - Repository: Rebased local `main` onto `origin/main` to reconcile divergent branches.

**Notes for integrators**
 - Boost Charge switch availability depends on the device being LIVE, not suspended, and supporting smart control/smart charging on the account.
 - If you maintain CI or local clones, consider choosing a default pull behavior to avoid repeated hints from Git. Example to set rebase as default:

  git config pull.rebase true

**Contact**
 - For questions or if you observe regressions, open an issue or attach logs from your Home Assistant instance.
