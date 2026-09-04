"""
Octopus Germany Integration.

This module provides integration with the Octopus Germany API for Home Assistant.
"""

from __future__ import annotations

import inspect
import json
import logging
from datetime import UTC, datetime, timedelta

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import Platform
from homeassistant.core import HomeAssistant, ServiceCall, SupportsResponse
from homeassistant.util.dt import as_utc

from .const import (
    CONF_INTELLIGENT_UPDATE_INTERVAL,
    CONF_UPDATE_INTERVAL,
    DEBUG_ENABLED,
    DOMAIN,
    INTELLIGENT_UPDATE_INTERVAL,
    UPDATE_INTERVAL,
)
from .coordinator import OctopusDataCoordinator, normalize_update_interval
from .data_processing import (
    calculate_dispatch_state,
    create_empty_account_data,
    extract_device_data,
    extract_gross_rate,
    extract_meter_data,
    get_product_type,
    merge_normalized_account_data,
    normalize_direct_products,
    normalize_timeslots,
    normalize_unit_rate_forecast,
    process_ledgers,
)
from .models import (
    detect_tariff_capabilities,
    filter_active_accounts,
    select_primary_account,
)
from .octopus_germany import OctopusGermany
from .services import (
    async_handle_refresh_intelligent_data,
    async_request_intelligent_refresh,
)

try:
    from homeassistant.components.recorder import get_instance
    from homeassistant.components.recorder.models import (
        StatisticData,
        StatisticMeanType,
        StatisticMetaData,
    )
    from homeassistant.components.recorder.statistics import (
        async_add_external_statistics,
        statistics_during_period,
    )

    HAS_RECORDER = True
except ImportError:
    HAS_RECORDER = False

_LOGGER = logging.getLogger(__name__)

PLATFORMS: list[Platform] = [Platform.BINARY_SENSOR, Platform.SENSOR, Platform.SWITCH]

API_URL = "https://api.octopus.energy/v1/graphql/"


async def _async_fetch_account_data(
    api: OctopusGermany,
    account_numbers: list[str],
    process_api_data: Any,
    capabilities_by_account: dict,
) -> dict:
    """Fetch and normalize base data for all configured accounts."""
    all_accounts_data = {}
    for account_number in account_numbers:
        try:
            capabilities = await api.fetch_tariff_capabilities(account_number)
            capabilities_by_account[account_number] = capabilities
            account_data = await api.fetch_data_for_account(account_number)
            if not account_data:
                _LOGGER.warning("Failed to fetch data for account %s", account_number)
                continue

            processed = await process_api_data(account_data, account_number, api)
            processed[account_number]["tariff_capabilities"] = {
                "has_dynamic_prices": capabilities.has_dynamic_prices,
                "has_intelligent_dispatches": capabilities.has_intelligent_dispatches,
                "has_smart_meter": capabilities.has_smart_meter,
            }
            all_accounts_data.update(processed)
        except Exception:
            _LOGGER.exception("Error fetching data for account %s", account_number)
    return all_accounts_data


# Service schemas
SERVICE_SET_DEVICE_PREFERENCES = "set_device_preferences"
SERVICE_GET_SMART_METER_READINGS = "get_smart_meter_readings"
SERVICE_EXPORT_SMART_METER_CSV = "export_smart_meter_csv"
SERVICE_SUBMIT_METER_READINGS = "submit_meter_readings"
SERVICE_REFRESH_INTELLIGENT_DATA = "refresh_intelligent_data"
ATTR_ACCOUNT_NUMBER = "account_number"
ATTR_DEVICE_ID = "device_id"
ATTR_TARGET_PERCENTAGE = "target_percentage"
ATTR_TARGET_TIME = "target_time"
ATTR_DATE = "date"
ATTR_READING_DATE = "reading_date"
ATTR_METER_ID = "meter_id"
ATTR_METER_TYPE = "meter_type"
ATTR_READINGS_JSON = "readings_json"
ATTR_READING_VALUE = "reading_value"
ATTR_REGISTER_OBIS_CODE = "register_obis_code"
ATTR_PROPERTY_ID = "property_id"
ATTR_PERIOD = "period"
ATTR_YEAR = "year"
ATTR_MONTH = "month"
ATTR_FILENAME = "filename"
ATTR_LAYOUT = "layout"
ATTR_SUMMARY = "summary"
ATTR_GO_WINDOW_START = "go_window_start"
ATTR_GO_WINDOW_END = "go_window_end"


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Set up Octopus Germany from a config entry."""
    email = entry.data["email"]
    password = entry.data["password"]

    # Initialize API
    api = OctopusGermany(email, password)

    # Log in only once and reuse the token through the global token manager
    if not await api.login():
        _LOGGER.error("Failed to authenticate with Octopus Germany API")
        return False

    # Ensure DOMAIN is initialized in hass.data
    if DOMAIN not in hass.data:
        hass.data[DOMAIN] = {}

    # Enhanced multi-account support with all ledgers
    account_numbers = entry.data.get("account_numbers", [])
    active_accounts = []
    polling_interval = entry.options.get(
        CONF_UPDATE_INTERVAL,
        entry.data.get(CONF_UPDATE_INTERVAL, UPDATE_INTERVAL),
    )
    polling_interval = normalize_update_interval(polling_interval, UPDATE_INTERVAL)
    intelligent_polling_interval = entry.options.get(
        CONF_INTELLIGENT_UPDATE_INTERVAL,
        entry.data.get(CONF_INTELLIGENT_UPDATE_INTERVAL, INTELLIGENT_UPDATE_INTERVAL),
    )
    intelligent_polling_interval = normalize_update_interval(
        intelligent_polling_interval, INTELLIGENT_UPDATE_INTERVAL
    )
    accounts = await api.fetch_accounts()
    if accounts:
        active_accounts = filter_active_accounts(accounts)
        if not active_accounts:
            _LOGGER.error("No active accounts found for the provided credentials")
            return False
        account_numbers = [account["number"] for account in active_accounts]
        _LOGGER.info("Found %d active accounts", len(account_numbers))
        if account_numbers != entry.data.get("account_numbers", []):
            hass.config_entries.async_update_entry(
                entry, data={**entry.data, "account_numbers": account_numbers}
            )
    elif not account_numbers:
        single_account = entry.data.get("account_number")
        if single_account:
            account_numbers = [single_account]
        else:
            _LOGGER.error("No accounts found for the provided credentials")
            return False

    primary_account_number = select_primary_account(active_accounts) or (
        account_numbers[0] if account_numbers else None
    )
    if not entry.data.get("account_number"):
        hass.config_entries.async_update_entry(
            entry, data={**entry.data, "account_number": primary_account_number}
        )

    capabilities_by_account = {}
    intelligent_coordinator = None

    # Create data update coordinator with improved error handling and retry logic
    async def async_update_data():
        """Fetch data from API with improved error handling for all accounts."""
        current_time = datetime.now(UTC)

        # Add throttling to prevent too frequent API calls
        # Store last successful API call time on the function object
        if not hasattr(async_update_data, "last_api_call"):
            async_update_data.last_api_call = datetime.now(UTC) - timedelta(
                minutes=polling_interval
            )

        # Calculate time since last API call
        time_since_last_call = (
            current_time - async_update_data.last_api_call
        ).total_seconds()
        min_interval = (
            polling_interval * 60 * 0.9
        )  # 90% of the update interval in seconds

        # Get simplified caller information instead of full stack trace
        caller_info = "Unknown caller"
        if DEBUG_ENABLED:
            # Get the caller's frame (2 frames up from current)
            try:
                frame = inspect.currentframe()
                if frame:
                    frame = (
                        frame.f_back.f_back
                    )  # Go up two frames to find the actual caller
                    if frame:
                        # Extract useful caller information
                        caller_module = frame.f_globals.get(
                            "__name__", "unknown_module"
                        )
                        caller_function = frame.f_code.co_name
                        caller_line = frame.f_lineno
                        caller_info = f"{caller_module}.{caller_function}:{caller_line}"
                    del frame  # Clean up reference to avoid memory issues
            except Exception:
                caller_info = "Error getting caller info"

        _LOGGER.debug(
            "Coordinator update called at %s (Update interval: %s minutes, Time since last API call: %.1f seconds, Caller: %s)",
            current_time.strftime("%H:%M:%S"),
            polling_interval,
            time_since_last_call,
            caller_info,
        )

        # If called too soon after last API call, return cached data
        if (
            time_since_last_call < min_interval
            and hasattr(coordinator, "data")
            and coordinator.data
        ):
            _LOGGER.debug(
                "Throttling API call - returning cached data from %s",
                async_update_data.last_api_call.strftime("%H:%M:%S"),
            )
            return coordinator.data

        try:
            # Let the API class handle token validation
            _LOGGER.debug(
                "Fetching data from API at %s", current_time.strftime("%H:%M:%S")
            )

            all_accounts_data = await _async_fetch_account_data(
                api,
                account_numbers,
                process_api_data,
                capabilities_by_account,
            )

            # Update last API call timestamp only on successful calls
            if all_accounts_data:
                async_update_data.last_api_call = datetime.now(UTC)

            if not all_accounts_data:
                _LOGGER.error(
                    "Failed to fetch data from API for any account, returning last known data"
                )
                return coordinator.data if hasattr(coordinator, "data") else {}

            if intelligent_coordinator and intelligent_coordinator.data:
                for (
                    account_num,
                    intelligent_data,
                ) in intelligent_coordinator.data.items():
                    if account_num in all_accounts_data:
                        all_accounts_data[account_num] = merge_normalized_account_data(
                            all_accounts_data[account_num], intelligent_data
                        )

            _LOGGER.debug(
                "Successfully fetched data from API at %s for %d accounts",
                datetime.now(UTC).strftime("%H:%M:%S"),
                len(all_accounts_data),
            )
            return all_accounts_data

        except Exception as e:
            _LOGGER.exception("Unexpected error during data update: %s", e)
            # Return previous data if available, empty dict otherwise
            return coordinator.data if hasattr(coordinator, "data") else {}

    async def process_api_data(
        data, account_number, api, *, include_meter_readings=True
    ):
        """Process raw API response into structured data."""
        if not data:
            return {}

        result_data = create_empty_account_data(account_number)

        # Extract account data - this should be available even if device-related endpoints fail
        account_data = data.get("account", {})

        # Log what data we have - safely handle None values
        _LOGGER.debug(
            "Processing API data - fields available: %s",
            list(data.keys()) if data else [],
        )

        # Only try to access account_data keys if it's not None and is a dictionary
        if account_data and isinstance(account_data, dict):
            _LOGGER.debug("Account data fields: %s", list(account_data.keys()))
            capabilities = detect_tariff_capabilities(account_data)
            result_data[account_number]["tariff_capabilities"] = {
                "has_dynamic_prices": capabilities.has_dynamic_prices,
                "has_intelligent_dispatches": capabilities.has_intelligent_dispatches,
                "has_smart_meter": capabilities.has_smart_meter,
            }
        else:
            _LOGGER.warning("Account data is missing or invalid: %s", account_data)
            # Return the basic structure with default values
            return result_data

        # Extract ALL ledger data (not just electricity)
        ledgers = account_data.get("ledgers", [])
        result_data[account_number]["ledgers"] = ledgers

        ledger_balances = process_ledgers(ledgers)
        result_data[account_number].update(ledger_balances)

        _LOGGER.debug(
            "Processed %d ledgers for account %s: electricity=%.2f, gas=%.2f, heat=%.2f, other=%d",
            len(ledgers),
            account_number,
            ledger_balances["electricity_balance"],
            ledger_balances["gas_balance"],
            ledger_balances["heat_balance"],
            len(ledger_balances["other_ledgers"]),
        )

        result_data[account_number].update(extract_meter_data(account_data))

        result_data[account_number].update(extract_device_data(data))

        # Handle dispatch data if it exists
        # Try to fall back to cached data from coordinator if API omits the field
        cached_account = {}
        try:
            cached_coordinator = (
                hass.data.get(DOMAIN, {}).get(entry.entry_id, {}).get("coordinator")
            )
            if cached_coordinator and cached_coordinator.data:
                cached_account = cached_coordinator.data.get(account_number, {}) or {}
        except Exception:
            cached_account = {}

        if "plannedDispatches" not in data:
            planned_dispatches = cached_account.get("planned_dispatches", [])
            if planned_dispatches:
                _LOGGER.debug(
                    "API missing plannedDispatches for %s, using cached data (%d dispatches)",
                    account_number,
                    len(planned_dispatches),
                )
            else:
                planned_dispatches = []  # No previous data available
        else:
            planned_dispatches = data.get("plannedDispatches") or []
        result_data[account_number]["planned_dispatches"] = planned_dispatches

        completed_dispatches = data.get("completedDispatches")
        if completed_dispatches is None:
            completed_dispatches = cached_account.get("completed_dispatches", [])
        result_data[account_number]["completed_dispatches"] = completed_dispatches

        result_data[account_number].update(calculate_dispatch_state(planned_dispatches))

        # Extract charging sessions from comprehensive query data
        # Sessions are now included in the devices query, no separate API call needed!
        charging_sessions = data.get("charging_sessions", [])
        if charging_sessions:
            _LOGGER.debug(
                "Found %d charging sessions for account %s from comprehensive query",
                len(charging_sessions),
                account_number,
            )
        result_data[account_number]["charging_sessions"] = charging_sessions

        # Extract products - ensure we always have product data
        direct_products = data.get("direct_products", [])
        products = normalize_direct_products(direct_products)

        # Check if we have direct products data first
        if direct_products:
            _LOGGER.debug("Found %d direct products", len(direct_products))

        # If no direct products, try to extract from the account data
        if not products:
            _LOGGER.debug("Extracting products from account data")

            for prop in account_data.get("allProperties", []):
                for malo in prop.get("electricityMalos", []):
                    for agreement in malo.get("agreements", []):
                        product = agreement.get("product", {})
                        unit_rate_info = agreement.get("unitRateInformation", {})

                        # Log what fields are available to help debug
                        if unit_rate_info:
                            _LOGGER.debug(
                                "Unit rate info keys: %s", list(unit_rate_info.keys())
                            )

                        # Determine the product type
                        product_type = get_product_type(unit_rate_info)

                        # For Simple product types
                        if product_type == "Simple":
                            agreement_rate = extract_gross_rate(
                                agreement.get("unitRateGrossRateInformation")
                            )
                            gross_rate = extract_gross_rate(
                                unit_rate_info.get("grossRateInformation"),
                                unit_rate_info.get(
                                    "latestGrossUnitRateCentsPerKwh", agreement_rate
                                ),
                            )

                            # Add unitRateForecast for TimeOfUse products
                            unit_rate_forecast = normalize_unit_rate_forecast(
                                agreement.get("unitRateForecast")
                            )

                            products.append(
                                {
                                    "code": product.get("code", "Unknown"),
                                    "description": product.get("description", ""),
                                    "name": product.get("fullName", "Unknown"),
                                    "grossRate": gross_rate,
                                    "type": product_type,
                                    "validFrom": agreement.get("validFrom"),
                                    "validTo": agreement.get("validTo"),
                                    "isTimeOfUse": product.get("isTimeOfUse", False),
                                    "unitRateForecast": unit_rate_forecast,
                                }
                            )

                        # For TimeOfUse product types
                        elif product_type == "TimeOfUse" and "rates" in unit_rate_info:
                            timeslots = normalize_timeslots(unit_rate_info["rates"])

                            # Add unitRateForecast for TimeOfUse products
                            unit_rate_forecast = normalize_unit_rate_forecast(
                                agreement.get("unitRateForecast")
                            )

                            # Create a TimeOfUse product with timeslots
                            products.append(
                                {
                                    "code": product.get("code", "Unknown"),
                                    "description": product.get("description", ""),
                                    "name": product.get("fullName", "Unknown"),
                                    "type": product_type,
                                    "validFrom": agreement.get("validFrom"),
                                    "validTo": agreement.get("validTo"),
                                    "timeslots": timeslots,
                                    "isTimeOfUse": product.get("isTimeOfUse", False),
                                    "unitRateForecast": unit_rate_forecast,
                                }
                            )

                            _LOGGER.debug(
                                "Found TimeOfUse product with %d timeslots: %s",
                                len(timeslots),
                                [ts.get("name") for ts in timeslots],
                            )

        # Log whether we found products
        if products:
            _LOGGER.debug(
                "Found %d products for account %s", len(products), account_number
            )
            for idx, product in enumerate(products):
                _LOGGER.debug(
                    "Product %d: code=%s, grossRate=%s",
                    idx + 1,
                    product.get("code"),
                    product.get("grossRate"),
                )
        else:
            _LOGGER.warning("No products found for account %s", account_number)

        result_data[account_number]["products"] = products

        # Extract gas products - similar process to electricity products
        gas_products = []

        for prop in account_data.get("allProperties", []):
            for malo in prop.get("gasMalos", []):
                for agreement in malo.get("agreements", []):
                    product = agreement.get("product", {})
                    unit_rate_info = agreement.get("unitRateInformation", {})

                    # Determine the product type
                    product_type = get_product_type(unit_rate_info)

                    # For Simple product types
                    if product_type == "Simple":
                        agreement_rate = extract_gross_rate(
                            agreement.get("unitRateGrossRateInformation")
                        )
                        gross_rate = extract_gross_rate(
                            unit_rate_info.get("grossRateInformation"),
                            unit_rate_info.get(
                                "latestGrossUnitRateCentsPerKwh", agreement_rate
                            ),
                        )

                        gas_products.append(
                            {
                                "code": product.get("code", "Unknown"),
                                "description": product.get("description", ""),
                                "name": product.get("fullName", "Unknown"),
                                "grossRate": gross_rate,
                                "type": product_type,
                                "validFrom": agreement.get("validFrom"),
                                "validTo": agreement.get("validTo"),
                                "isTimeOfUse": product.get("isTimeOfUse", False),
                            }
                        )

                    # For TimeOfUse product types (if gas supports it)
                    elif product_type == "TimeOfUse" and "rates" in unit_rate_info:
                        timeslots = normalize_timeslots(unit_rate_info["rates"])

                        gas_products.append(
                            {
                                "code": product.get("code", "Unknown"),
                                "description": product.get("description", ""),
                                "name": product.get("fullName", "Unknown"),
                                "grossRate": "0",  # For TimeOfUse, this is not used
                                "type": product_type,
                                "validFrom": agreement.get("validFrom"),
                                "validTo": agreement.get("validTo"),
                                "timeslots": timeslots,
                                "isTimeOfUse": product.get("isTimeOfUse", False),
                            }
                        )

        # Log gas products found
        if gas_products:
            _LOGGER.debug(
                "Found %d gas products for account %s",
                len(gas_products),
                account_number,
            )
            for idx, product in enumerate(gas_products):
                _LOGGER.debug(
                    "Gas Product %d: code=%s, grossRate=%s",
                    idx + 1,
                    product.get("code"),
                    product.get("grossRate"),
                )
        else:
            _LOGGER.debug("No gas products found for account %s", account_number)

        result_data[account_number]["gas_products"] = gas_products

        # Extract additional gas information
        # Gas price from current valid gas product
        gas_price = None
        gas_contract_start = None
        gas_contract_end = None

        if gas_products:
            # Find current valid gas product based on validity dates
            now = datetime.now(UTC).isoformat()
            valid_gas_products = []

            for product in gas_products:
                valid_from = product.get("validFrom")
                valid_to = product.get("validTo")

                if not valid_from:
                    continue

                if valid_from <= now and (not valid_to or now <= valid_to):
                    valid_gas_products.append(product)

            if valid_gas_products:
                # Sort by validFrom to get the most recent one
                valid_gas_products.sort(
                    key=lambda p: p.get("validFrom", ""), reverse=True
                )
                current_gas_product = valid_gas_products[0]

                # Extract gas price
                try:
                    gross_rate_str = current_gas_product.get("grossRate", "0")
                    gas_price = (
                        float(gross_rate_str) / 100.0
                    )  # Convert from cents to EUR
                except ValueError, TypeError:
                    gas_price = None

                # Extract contract dates
                gas_contract_start = current_gas_product.get("validFrom")
                gas_contract_end = current_gas_product.get("validTo")

        result_data[account_number]["gas_price"] = gas_price
        result_data[account_number]["gas_contract_start"] = gas_contract_start
        result_data[account_number]["gas_contract_end"] = gas_contract_end

        # Calculate days until contract expiry
        gas_contract_days_until_expiry = None
        if gas_contract_end:
            try:
                end_date = datetime.fromisoformat(gas_contract_end)
                now_date = datetime.now(end_date.tzinfo)
                days_diff = (end_date - now_date).days
                gas_contract_days_until_expiry = max(
                    0, days_diff
                )  # Don't show negative days
            except (ValueError, TypeError) as e:
                _LOGGER.warning("Error calculating gas contract expiry days: %s", e)

        result_data[account_number]["gas_contract_days_until_expiry"] = (
            gas_contract_days_until_expiry
        )

        meter = result_data[account_number]["meter"]

        # Gas meter smart reading capability
        gas_meter = result_data[account_number]["gas_meter"]
        gas_meter_smart_reading = None
        if gas_meter and isinstance(gas_meter, dict):
            gas_meter_smart_reading = gas_meter.get("shouldReceiveSmartMeterData", None)

        result_data[account_number]["gas_meter_smart_reading"] = gas_meter_smart_reading

        # Fetch latest gas meter reading if gas meter exists
        gas_latest_reading = None
        if include_meter_readings and gas_meter and gas_meter.get("id"):
            try:
                gas_meter_id = gas_meter.get("id")
                _LOGGER.debug(
                    "Attempting to fetch gas meter reading for account %s, meter %s",
                    account_number,
                    gas_meter_id,
                )
                gas_latest_reading = await api.fetch_gas_meter_reading(
                    account_number, gas_meter_id
                )

                if gas_latest_reading:
                    _LOGGER.debug(
                        "Successfully fetched gas meter reading: %s %s at %s",
                        gas_latest_reading.get("value"),
                        gas_latest_reading.get("units"),
                        gas_latest_reading.get("intervalEnd"),
                    )
                else:
                    _LOGGER.debug(
                        "No gas meter reading returned for meter %s", gas_meter_id
                    )

            except Exception as e:
                _LOGGER.warning(
                    "Failed to fetch gas meter reading for account %s, meter %s: %s",
                    account_number,
                    gas_meter_id,
                    str(e),
                )

        result_data[account_number]["gas_latest_reading"] = gas_latest_reading

        # Fetch latest electricity meter reading if electricity meter exists
        electricity_latest_reading = None
        if include_meter_readings and meter and meter.get("id"):
            try:
                electricity_meter_id = meter.get("id")
                _LOGGER.debug(
                    "Attempting to fetch electricity meter reading for account %s, meter %s",
                    account_number,
                    electricity_meter_id,
                )
                electricity_latest_reading = await api.fetch_electricity_meter_reading(
                    account_number, electricity_meter_id
                )

                if electricity_latest_reading:
                    _LOGGER.debug(
                        "Successfully fetched electricity meter reading: %s at %s",
                        electricity_latest_reading.get("value"),
                        electricity_latest_reading.get("readAt"),
                    )
                else:
                    _LOGGER.debug(
                        "No electricity meter reading returned for meter %s",
                        electricity_meter_id,
                    )

            except Exception as e:
                _LOGGER.warning(
                    "Failed to fetch electricity meter reading for account %s, meter %s: %s",
                    account_number,
                    electricity_meter_id,
                    str(e),
                )

        result_data[account_number]["electricity_latest_reading"] = (
            electricity_latest_reading
        )

        # Extract smart meter readings if available
        electricity_smart_meter_readings = data.get(
            "electricity_smart_meter_readings", []
        )
        result_data[account_number]["electricity_smart_meter_readings"] = (
            electricity_smart_meter_readings
        )

        if electricity_smart_meter_readings:
            _LOGGER.debug(
                "Processed %d smart meter readings for account %s",
                len(electricity_smart_meter_readings),
                account_number,
            )

        return result_data

    # --- Statistics import for HA energy dashboard ---
    # Tracks which dates have been imported per account to avoid redundant API calls
    imported_stats_dates: dict[str, set[str]] = {acc: set() for acc in account_numbers}

    async def async_import_consumption_statistics():
        """Import 15-min smart meter data into HA long-term statistics for the energy dashboard."""
        if not HAS_RECORDER:
            return

        for account_num in account_numbers:
            if not coordinator.data or account_num not in coordinator.data:
                continue

            account_data = coordinator.data[account_num]
            property_ids = account_data.get("property_ids", [])
            if not property_ids:
                continue

            property_id = property_ids[0]
            safe_account = account_num.replace("-", "_").lower()
            statistic_id = f"{DOMAIN}:electricity_{safe_account}_consumption"

            # Determine which dates to import
            yesterday = (datetime.now(UTC).date() - timedelta(days=1)).isoformat()
            dates_to_import = []

            if account_num not in imported_stats_dates:
                imported_stats_dates[account_num] = set()

            if yesterday not in imported_stats_dates[account_num]:
                dates_to_import.append(yesterday)

            # On first run, also try to backfill the last 7 days
            if not imported_stats_dates[account_num]:
                for days_back in range(2, 8):
                    d = (
                        datetime.now(UTC).date() - timedelta(days=days_back)
                    ).isoformat()
                    dates_to_import.append(d)

            if not dates_to_import:
                return

            # Get the last known sum from HA recorder
            try:
                earliest_date = datetime.fromisoformat(min(dates_to_import))
                last_stat = await get_instance(hass).async_add_executor_job(
                    statistics_during_period,
                    hass,
                    earliest_date - timedelta(days=7),
                    earliest_date,
                    {statistic_id},
                    "hour",
                    None,
                    {"sum"},
                )
                running_sum = (
                    last_stat[statistic_id][-1]["sum"]
                    if statistic_id in last_stat and len(last_stat[statistic_id]) > 0
                    else 0.0
                )
            except Exception as e:
                _LOGGER.debug("Could not get last statistics sum: %s", e)
                running_sum = 0.0

            all_statistics = []

            for date_str in sorted(dates_to_import):
                if date_str in imported_stats_dates[account_num]:
                    continue

                try:
                    readings = await api.fetch_electricity_15min_readings(
                        account_num, property_id, date_str
                    )
                except Exception as e:
                    _LOGGER.warning(
                        "Failed to fetch 15-min readings for %s: %s", date_str, e
                    )
                    continue

                if not readings:
                    continue

                # Aggregate 15-min readings into hourly StatisticData entries
                hourly_buckets: dict[str, float] = {}
                for reading in readings:
                    start_str = reading.get("start_time", "")
                    if not start_str:
                        continue
                    try:
                        start_dt = datetime.fromisoformat(start_str)
                        hour_key = start_dt.replace(
                            minute=0, second=0, microsecond=0
                        ).isoformat()
                        value = float(reading.get("value", 0) or 0)
                        hourly_buckets[hour_key] = (
                            hourly_buckets.get(hour_key, 0.0) + value
                        )
                    except ValueError, TypeError:
                        continue

                for hour_key in sorted(hourly_buckets.keys()):
                    consumption = hourly_buckets[hour_key]
                    running_sum += consumption
                    hour_dt = as_utc(datetime.fromisoformat(hour_key))
                    all_statistics.append(
                        StatisticData(
                            start=hour_dt,
                            state=round(consumption, 6),
                            sum=round(running_sum, 6),
                        )
                    )

                imported_stats_dates[account_num].add(date_str)
                _LOGGER.debug(
                    "Prepared %d hourly statistics for %s on %s (running sum: %.3f)",
                    len(hourly_buckets),
                    account_num,
                    date_str,
                    running_sum,
                )

            if all_statistics:
                meter_info = account_data.get("meter", {})
                meter_number = (
                    meter_info.get("number", account_num) if meter_info else account_num
                )

                async_add_external_statistics(
                    hass,
                    StatisticMetaData(
                        has_mean=False,
                        mean_type=StatisticMeanType.NONE,
                        has_sum=True,
                        name=f"Electricity Consumption ({meter_number}/{account_num})",
                        source=DOMAIN,
                        statistic_id=statistic_id,
                        unit_of_measurement="kWh",
                        unit_class="energy",
                    ),
                    all_statistics,
                )
                _LOGGER.info(
                    "Imported %d hourly statistics for account %s into energy dashboard",
                    len(all_statistics),
                    account_num,
                )

    async def async_update_intelligent_data():
        """Fetch and normalize Intelligent data for eligible accounts."""
        intelligent_data = {}
        for account_num, capabilities in capabilities_by_account.items():
            if not capabilities.has_intelligent_dispatches:
                continue
            try:
                account_data = await api.fetch_all_data(
                    account_num,
                    include_intelligent=True,
                    include_meter_readings=False,
                )
                if account_data:
                    intelligent_data.update(
                        await process_api_data(
                            account_data,
                            account_num,
                            api,
                            include_meter_readings=False,
                        )
                    )
            except Exception as err:
                _LOGGER.warning(
                    "Error fetching Intelligent data for account %s: %s",
                    account_num,
                    err,
                )
        return intelligent_data

    coordinator = OctopusDataCoordinator(
        hass,
        _LOGGER,
        name=f"{DOMAIN}_{primary_account_number}",
        update_method=async_update_data,
        update_interval_minutes=polling_interval,
    )

    # Initial data refresh - only once to prevent duplicate API calls
    await coordinator.async_config_entry_first_refresh()

    if any(
        capabilities.has_intelligent_dispatches
        for capabilities in capabilities_by_account.values()
    ):
        intelligent_coordinator = OctopusDataCoordinator(
            hass,
            _LOGGER,
            name=f"{DOMAIN}_{primary_account_number}_intelligent",
            update_method=async_update_intelligent_data,
            update_interval_minutes=intelligent_polling_interval,
        )
        await intelligent_coordinator.async_config_entry_first_refresh()
        merged_data = dict(coordinator.data or {})
        for account_num, intelligent_data in intelligent_coordinator.data.items():
            if account_num in merged_data:
                merged_data[account_num] = merge_normalized_account_data(
                    merged_data[account_num], intelligent_data
                )
        coordinator.async_set_updated_data(merged_data)

        def _merge_intelligent_update() -> None:
            if not coordinator.data or not intelligent_coordinator.data:
                return
            merged_data = dict(coordinator.data)
            for account_num, intelligent_data in intelligent_coordinator.data.items():
                if account_num in merged_data:
                    merged_data[account_num] = merge_normalized_account_data(
                        merged_data[account_num], intelligent_data
                    )
            coordinator.async_set_updated_data(merged_data)

        intelligent_coordinator.async_add_listener(_merge_intelligent_update)

    # Log the account data after update to help diagnose attribute issues
    if coordinator.data and primary_account_number in coordinator.data:
        _LOGGER.info(
            "Account %s data keys: %s",
            primary_account_number,
            list(coordinator.data[primary_account_number].keys()),
        )
        if "plannedDispatches" in coordinator.data[primary_account_number]:
            _LOGGER.info(
                "Found %d planned dispatches",
                len(coordinator.data[primary_account_number]["plannedDispatches"]),
            )
            _LOGGER.info(
                "First planned dispatch: %s",
                coordinator.data[primary_account_number]["plannedDispatches"][0]
                if coordinator.data[primary_account_number]["plannedDispatches"]
                else "None",
            )

    # Import consumption statistics after each coordinator refresh
    async def _safe_import_statistics():
        try:
            await async_import_consumption_statistics()
        except Exception as e:
            _LOGGER.warning("Error importing consumption statistics: %s", e)

    def _on_coordinator_update() -> None:
        """Schedule statistics import when coordinator data updates."""
        hass.async_create_task(_safe_import_statistics())

    coordinator.async_add_listener(_on_coordinator_update)

    # Also run the initial statistics import now
    if HAS_RECORDER and coordinator.data:
        try:
            await async_import_consumption_statistics()
        except Exception as e:
            _LOGGER.warning("Error during initial statistics import: %s", e)

    # Store API, account number and coordinator in hass.data
    hass.data[DOMAIN][entry.entry_id] = {
        "api": api,
        "account_number": primary_account_number,
        "account_numbers": account_numbers,
        "capabilities_by_account": capabilities_by_account,
        "coordinator": coordinator,
        "intelligent_coordinator": intelligent_coordinator,
    }

    # Register account service devices before setting up platforms
    from homeassistant.helpers import device_registry as dr

    from .sensor import get_account_device_info

    device_registry = dr.async_get(hass)
    for account_number in account_numbers:
        account_device_info = get_account_device_info(account_number)
        device_registry.async_get_or_create(
            config_entry_id=entry.entry_id,
            **account_device_info,
        )
        _LOGGER.debug("Registered account service device for %s", account_number)

    # Forward setup to platforms - no need to wait for another refresh
    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)

    entry.async_on_unload(entry.add_update_listener(_async_update_options))

    # Register services
    async def handle_set_device_preferences(call: ServiceCall):
        """Handle the set_device_preferences service call."""
        device_id = call.data.get(ATTR_DEVICE_ID)
        target_percentage = call.data.get(ATTR_TARGET_PERCENTAGE)
        target_time = call.data.get(ATTR_TARGET_TIME)

        if not device_id:
            _LOGGER.error("Device ID is required for set_device_preferences")
            from homeassistant.exceptions import ServiceValidationError

            raise ServiceValidationError(
                "Device ID is required",
                translation_domain=DOMAIN,
            )

        # Validate percentage (20-100% in 5% steps)
        if not 20 <= target_percentage <= 100:
            _LOGGER.error(
                f"Invalid target percentage: {target_percentage}. Must be between 20 and 100"
            )
            from homeassistant.exceptions import ServiceValidationError

            raise ServiceValidationError(
                f"Invalid target percentage: {target_percentage}. Must be between 20 and 100",
                translation_domain=DOMAIN,
            )

        if target_percentage % 5 != 0:
            _LOGGER.error(
                f"Invalid target percentage: {target_percentage}. Must be in 5% steps"
            )
            from homeassistant.exceptions import ServiceValidationError

            raise ServiceValidationError(
                f"Invalid target percentage: {target_percentage}. Must be in 5% steps",
                translation_domain=DOMAIN,
            )

        # Validate time format
        try:
            api._format_time_to_hh_mm(target_time)
        except ValueError as time_error:
            _LOGGER.error("Time validation error: %s", time_error)
            from homeassistant.exceptions import ServiceValidationError

            raise ServiceValidationError(
                f"Invalid time format: {time_error!s}",
                translation_domain=DOMAIN,
            )

        _LOGGER.debug(
            "Service call set_device_preferences with device_id=%s, target_percentage=%s, target_time=%s",
            device_id,
            target_percentage,
            target_time,
        )

        try:
            success = await api.set_device_preferences(
                device_id,
                target_percentage,
                target_time,
            )

            if success:
                _LOGGER.info("Successfully set device preferences")
                await async_request_intelligent_refresh(hass)
                return {"success": True}
            _LOGGER.error("Failed to set device preferences")
            from homeassistant.exceptions import ServiceValidationError

            raise ServiceValidationError(
                "Failed to set device preferences. Check the log for details.",
                translation_domain=DOMAIN,
            )
        except ValueError as e:
            _LOGGER.error("Validation error: %s", e)
            from homeassistant.exceptions import ServiceValidationError

            raise ServiceValidationError(
                f"Invalid parameters: {e}",
                translation_domain=DOMAIN,
            )
        except Exception as e:
            _LOGGER.exception("Unexpected error setting device preferences: %s", e)
            from homeassistant.exceptions import HomeAssistantError

            raise HomeAssistantError(f"Error setting device preferences: {e}")

    async def handle_get_smart_meter_readings(call: ServiceCall) -> dict:
        """Handle the get_smart_meter_readings service call."""
        account_number = call.data.get(ATTR_ACCOUNT_NUMBER)
        date_str = call.data.get(ATTR_DATE)
        property_id = call.data.get(ATTR_PROPERTY_ID)

        # Validate inputs
        if not account_number:
            from homeassistant.exceptions import ServiceValidationError

            raise ServiceValidationError(
                "Account number is required",
                translation_domain=DOMAIN,
            )

        if not date_str:
            from homeassistant.exceptions import ServiceValidationError

            raise ServiceValidationError(
                "Date is required",
                translation_domain=DOMAIN,
            )

        # Validate date format
        try:
            from datetime import datetime

            datetime.strptime(date_str, "%Y-%m-%d").date()
        except ValueError:
            from homeassistant.exceptions import ServiceValidationError

            raise ServiceValidationError(
                f"Invalid date format: {date_str}. Expected YYYY-MM-DD",
                translation_domain=DOMAIN,
            )

        try:
            # Get the coordinator for this account
            coordinator = None
            client = None
            for data in hass.data[DOMAIN].values():
                if (
                    data["coordinator"].data
                    and account_number in data["coordinator"].data
                ):
                    coordinator = data["coordinator"]
                    client = data.get("api") or data.get("client")  # Try both keys
                    break

            if not coordinator or not client:
                from homeassistant.exceptions import ServiceValidationError

                raise ServiceValidationError(
                    f"Account {account_number} not found or not loaded",
                    translation_domain=DOMAIN,
                )

            # Use property_id from service call or get first property from account
            if not property_id:
                account_data = coordinator.data[account_number]
                property_ids = account_data.get("property_ids", [])
                if not property_ids:
                    from homeassistant.exceptions import ServiceValidationError

                    raise ServiceValidationError(
                        f"No properties found for account {account_number}",
                        translation_domain=DOMAIN,
                    )
                property_id = property_ids[0]

            _LOGGER.info(
                "Fetching smart meter readings for account %s, property %s, date %s",
                account_number,
                property_id,
                date_str,
            )

            # Fetch smart meter readings
            readings = await client.fetch_electricity_smart_meter_readings_v2(
                account_number, property_id, date_str
            )

            if readings:
                result = {
                    "success": True,
                    "account_number": account_number,
                    "property_id": property_id,
                    "date": date_str,
                    "total_readings": len(readings),
                    "readings": readings,
                    "total_consumption": sum(
                        float(r.get("value", 0)) for r in readings
                    ),
                }
                _LOGGER.info(
                    "Successfully fetched %d smart meter readings for %s",
                    len(readings),
                    date_str,
                )

                # Log a sample of the readings for debugging
                sample_readings = readings[:3] if len(readings) > 3 else readings
                _LOGGER.info("Sample readings: %s", sample_readings)
                _LOGGER.info("Total consumption: %.3f kWh", result["total_consumption"])
            else:
                result = {
                    "success": False,
                    "account_number": account_number,
                    "property_id": property_id,
                    "date": date_str,
                    "total_readings": 0,
                    "readings": [],
                    "message": f"No smart meter readings found for {date_str}",
                }
                _LOGGER.warning("No smart meter readings found for %s", date_str)

            # Fire an event with the results
            hass.bus.async_fire(f"{DOMAIN}_smart_meter_readings_result", result)

            return result

        except Exception as e:
            _LOGGER.exception("Error fetching smart meter readings: %s", e)
            from homeassistant.exceptions import HomeAssistantError

            raise HomeAssistantError(f"Error fetching smart meter readings: {e}")

    async def handle_export_smart_meter_csv(call: ServiceCall) -> dict:
        """Handle the export_smart_meter_csv service call."""
        import csv
        import os
        from calendar import monthrange

        account_number = call.data.get(ATTR_ACCOUNT_NUMBER)
        property_id = call.data.get(ATTR_PROPERTY_ID)
        period = call.data.get(ATTR_PERIOD, "month")
        year = call.data.get(ATTR_YEAR)
        month = call.data.get(ATTR_MONTH)
        filename = call.data.get(ATTR_FILENAME)
        layout = call.data.get(ATTR_LAYOUT, "wide")
        add_summary = call.data.get(ATTR_SUMMARY, False)
        go_window_start = call.data.get(ATTR_GO_WINDOW_START)
        go_window_end = call.data.get(ATTR_GO_WINDOW_END)

        # Validate inputs
        if not account_number:
            from homeassistant.exceptions import ServiceValidationError

            raise ServiceValidationError(
                "Account number is required",
                translation_domain=DOMAIN,
            )

        if not year:
            from homeassistant.exceptions import ServiceValidationError

            raise ServiceValidationError(
                "Year is required",
                translation_domain=DOMAIN,
            )

        if period == "month" and not month:
            from homeassistant.exceptions import ServiceValidationError

            raise ServiceValidationError(
                "Month is required for monthly export",
                translation_domain=DOMAIN,
            )

        # Validate month
        if month and (month < 1 or month > 12):
            from homeassistant.exceptions import ServiceValidationError

            raise ServiceValidationError(
                f"Invalid month: {month}. Must be between 1 and 12",
                translation_domain=DOMAIN,
            )

        try:
            # Get the coordinator for this account
            coordinator = None
            client = None
            for data in hass.data[DOMAIN].values():
                if (
                    data["coordinator"].data
                    and account_number in data["coordinator"].data
                ):
                    coordinator = data["coordinator"]
                    client = data.get("api") or data.get("client")
                    break

            if not coordinator or not client:
                from homeassistant.exceptions import ServiceValidationError

                raise ServiceValidationError(
                    f"Account {account_number} not found or not loaded",
                    translation_domain=DOMAIN,
                )

            # Get property_id if not provided
            if not property_id:
                account_data = coordinator.data[account_number]
                property_ids = account_data.get("property_ids", [])
                if not property_ids:
                    from homeassistant.exceptions import ServiceValidationError

                    raise ServiceValidationError(
                        f"No properties found for account {account_number}",
                        translation_domain=DOMAIN,
                    )
                property_id = property_ids[0]

            # Determine date range
            if period == "month":
                start_date = datetime(year, month, 1)
                _, last_day = monthrange(year, month)
                end_date = datetime(year, month, last_day)
            else:  # year
                start_date = datetime(year, 1, 1)
                end_date = datetime(year, 12, 31)
                month = None  # Reset month for yearly export

            _LOGGER.info(
                "Exporting smart meter data for account %s, property %s, period %s to %s",
                account_number,
                property_id,
                start_date.strftime("%Y-%m-%d"),
                end_date.strftime("%Y-%m-%d"),
            )

            # Collect all readings for the period
            all_readings = {}
            current_date = start_date
            total_days = (end_date - start_date).days + 1

            while current_date <= end_date:
                date_str = current_date.strftime("%Y-%m-%d")
                try:
                    readings = await client.fetch_electricity_smart_meter_readings_v2(
                        account_number, property_id, date_str
                    )
                    if readings:
                        all_readings[date_str] = readings
                        _LOGGER.debug(
                            "Fetched %d readings for %s", len(readings), date_str
                        )
                except Exception as e:
                    _LOGGER.warning("Failed to fetch readings for %s: %s", date_str, e)

                current_date += timedelta(days=1)

            if not all_readings:
                from homeassistant.exceptions import ServiceValidationError

                raise ServiceValidationError(
                    "No smart meter readings found for the specified period",
                    translation_domain=DOMAIN,
                )

            # Generate filename with improved default naming
            if not filename:
                if period == "month":
                    # Format: octopus_A-12FD99BC_2025_01.csv
                    filename = f"octopus_{account_number}_{year}_{month:02d}"
                else:  # year
                    # Format: octopus_A-12FD99BC_2025.csv
                    filename = f"octopus_{account_number}_{year}"

            # Ensure filename ends with .csv
            if not filename.endswith(".csv"):
                filename = f"{filename}.csv"

            # Save to /config directory
            output_path = os.path.join(hass.config.path(), filename)

            # Create CSV writing function to run in executor
            def write_csv():
                """Write CSV file (to be run in executor to avoid blocking)."""
                with open(output_path, "w", newline="", encoding="utf-8") as csvfile:
                    writer = csv.writer(csvfile, delimiter=";")

                    # Create time slots (15-minute intervals)
                    time_slots = [
                        f"{hour:02d}:{minute:02d}"
                        for hour in range(24)
                        for minute in [0, 15, 30, 45]
                    ]

                    # Prepare data structures
                    readings_by_time = {time_slot: {} for time_slot in time_slots}
                    readings_by_day = {}
                    daily_totals = {}

                    # Optional GO window parsing
                    go_start = None
                    go_end = None
                    if go_window_start and go_window_end:
                        try:
                            go_start = datetime.strptime(
                                go_window_start, "%H:%M"
                            ).time()
                            go_end = datetime.strptime(go_window_end, "%H:%M").time()
                        except Exception:
                            _LOGGER.warning(
                                "Invalid GO window times provided: %s - %s",
                                go_window_start,
                                go_window_end,
                            )

                    for date_str, readings in all_readings.items():
                        date_obj = datetime.strptime(date_str, "%Y-%m-%d")
                        day_key = f"{date_obj.day:02d}.{date_obj.month:02d}"
                        readings_by_day.setdefault(day_key, {})
                        day_total = 0.0
                        day_go = 0.0

                        for reading in readings:
                            # Handle both V1 (startAt) and V2 (start_time) keys
                            start_at = (
                                reading.get("start_time")
                                or reading.get("startAt")
                                or reading.get("start_at")
                                or ""
                            )
                            if start_at:
                                try:
                                    reading_time = datetime.fromisoformat(start_at)
                                    time_key = reading_time.strftime("%H:%M")
                                    minute = reading_time.minute
                                    rounded_minute = (minute // 15) * 15
                                    time_key = (
                                        f"{reading_time.hour:02d}:{rounded_minute:02d}"
                                    )

                                    value = float(reading.get("value", 0))
                                    day_total += value

                                    # GO/Standard split if window provided
                                    if go_start and go_end:
                                        t = reading_time.time()
                                        if go_start <= go_end:
                                            in_go = go_start <= t < go_end
                                        else:
                                            # window crosses midnight
                                            in_go = t >= go_start or t < go_end
                                        if in_go:
                                            day_go += value

                                    if time_key in readings_by_time:
                                        readings_by_time[time_key][day_key] = (
                                            f"{value:.3f}".replace(".", ",")
                                        )
                                    readings_by_day[day_key][time_key] = (
                                        f"{value:.3f}".replace(".", ",")
                                    )
                                except Exception as e:
                                    _LOGGER.warning(
                                        "Failed to parse reading time %s: %s",
                                        start_at,
                                        e,
                                    )

                        daily_totals[day_key] = {
                            "total_kwh": round(day_total, 3),
                            "go_kwh": round(day_go, 3) if go_start and go_end else None,
                        }

                    if layout == "wide":
                        # Header with dates as columns
                        if period == "month":
                            _, last_day = monthrange(year, month)
                            header = ["Zeit"] + [
                                f"{day:02d}.{month:02d}"
                                for day in range(1, last_day + 1)
                            ]
                        else:  # year
                            header = ["Zeit"]
                            for m in range(1, 13):
                                _, last_day = monthrange(year, m)
                                for day in range(1, last_day + 1):
                                    header.append(f"{day:02d}.{m:02d}")

                        writer.writerow(header)
                        for time_slot in time_slots:
                            row = [time_slot]
                            for col in header[1:]:
                                value = readings_by_time[time_slot].get(col, "")
                                row.append(value)
                            writer.writerow(row)
                    else:
                        # Tall layout: dates as rows, times as columns
                        header = ["Datum"] + time_slots
                        writer.writerow(header)
                        for day_key in sorted(
                            readings_by_day.keys(),
                            key=lambda d: datetime.strptime(d, "%d.%m"),
                        ):
                            row = [day_key]
                            for ts in time_slots:
                                row.append(readings_by_day[day_key].get(ts, ""))
                            writer.writerow(row)

                    if add_summary:
                        writer.writerow([])
                        writer.writerow(["Summary"])
                        summary_header = ["Datum", "Total kWh"]
                        include_go = any(
                            v.get("go_kwh") is not None for v in daily_totals.values()
                        )
                        if include_go:
                            summary_header += ["GO kWh", "Standard kWh"]
                        writer.writerow(summary_header)
                        for day_key, totals in sorted(
                            daily_totals.items(),
                            key=lambda item: datetime.strptime(item[0], "%d.%m"),
                        ):
                            row = [
                                day_key,
                                f"{totals['total_kwh']:.3f}".replace(".", ","),
                            ]
                            if include_go:
                                go_val = totals.get("go_kwh") or 0.0
                                std_val = totals["total_kwh"] - go_val
                                row += [
                                    f"{go_val:.3f}".replace(".", ","),
                                    f"{std_val:.3f}".replace(".", ","),
                                ]
                            writer.writerow(row)

            # Run file writing in executor to avoid blocking the event loop
            await hass.async_add_executor_job(write_csv)

            result = {
                "success": True,
                "account_number": account_number,
                "property_id": property_id,
                "period": period,
                "start_date": start_date.strftime("%Y-%m-%d"),
                "end_date": end_date.strftime("%Y-%m-%d"),
                "total_days": total_days,
                "days_with_data": len(all_readings),
                "output_file": output_path,
            }

            _LOGGER.info(
                "Successfully exported smart meter data to %s (%d days with data out of %d total days)",
                output_path,
                len(all_readings),
                total_days,
            )

            # Fire an event with the results
            hass.bus.async_fire(f"{DOMAIN}_csv_export_result", result)

            return result

        except Exception as e:
            _LOGGER.exception("Error exporting smart meter data to CSV: %s", e)
            from homeassistant.exceptions import HomeAssistantError

            raise HomeAssistantError(f"Error exporting smart meter data: {e}")

    async def handle_submit_meter_readings(call: ServiceCall) -> dict:
        """Handle the submit_meter_readings service call."""
        meter_type = call.data.get(ATTR_METER_TYPE)
        account_number = call.data.get(ATTR_ACCOUNT_NUMBER)
        meter_id = call.data.get(ATTR_METER_ID)
        reading_date = call.data.get(ATTR_READING_DATE)
        readings_json = call.data.get(ATTR_READINGS_JSON)
        reading_value = call.data.get(ATTR_READING_VALUE)
        register_obis_code = call.data.get(ATTR_REGISTER_OBIS_CODE)

        if not meter_type:
            from homeassistant.exceptions import ServiceValidationError

            raise ServiceValidationError(
                "Meter type is required",
                translation_domain=DOMAIN,
            )

        if not account_number:
            from homeassistant.exceptions import ServiceValidationError

            raise ServiceValidationError(
                "Account number is required",
                translation_domain=DOMAIN,
            )

        if not meter_id:
            from homeassistant.exceptions import ServiceValidationError

            raise ServiceValidationError(
                "Meter ID is required",
                translation_domain=DOMAIN,
            )

        try:
            datetime.strptime(reading_date, "%Y-%m-%d")
        except ValueError:
            from homeassistant.exceptions import ServiceValidationError

            raise ServiceValidationError(
                f"Invalid reading date format: {reading_date}. Expected YYYY-MM-DD",
                translation_domain=DOMAIN,
            )

        readings = None
        if readings_json:
            try:
                parsed_readings = json.loads(readings_json)
            except json.JSONDecodeError as json_error:
                from homeassistant.exceptions import ServiceValidationError

                raise ServiceValidationError(
                    f"Invalid JSON for readings_json: {json_error}",
                    translation_domain=DOMAIN,
                )

            if not isinstance(parsed_readings, list):
                from homeassistant.exceptions import ServiceValidationError

                raise ServiceValidationError(
                    "readings_json must be a JSON array",
                    translation_domain=DOMAIN,
                )

            readings = parsed_readings
        elif reading_value is not None:
            if not register_obis_code:
                from homeassistant.exceptions import ServiceValidationError

                raise ServiceValidationError(
                    "register_obis_code is required when reading_value is used",
                    translation_domain=DOMAIN,
                )

            readings = [
                {
                    "value": reading_value,
                    "registerObisCode": register_obis_code,
                }
            ]
        else:
            from homeassistant.exceptions import ServiceValidationError

            raise ServiceValidationError(
                "Either readings_json or reading_value must be provided",
                translation_domain=DOMAIN,
            )

        _LOGGER.info(
            "Submitting meter readings for meter_id=%s, meter_type=%s, reading_date=%s, reading_count=%d",
            meter_id,
            meter_type,
            reading_date,
            len(readings),
        )

        try:
            result = await api.submit_meter_readings(
                meter_type,
                meter_id,
                reading_date,
                readings,
                account_number,
            )

            if result:
                hass.bus.async_fire(
                    f"{DOMAIN}_meter_readings_submission_result", result
                )
                return result

            from homeassistant.exceptions import ServiceValidationError

            raise ServiceValidationError(
                "Failed to submit meter readings. Check the log for details.",
                translation_domain=DOMAIN,
            )
        except ValueError as e:
            _LOGGER.error("Validation error submitting meter readings: %s", e)
            from homeassistant.exceptions import ServiceValidationError

            raise ServiceValidationError(
                f"Invalid parameters: {e}",
                translation_domain=DOMAIN,
            )
        except Exception as e:
            _LOGGER.exception("Unexpected error submitting meter readings: %s", e)
            from homeassistant.exceptions import HomeAssistantError

            raise HomeAssistantError(f"Error submitting meter readings: {e}")

    # Register services
    hass.services.async_register(
        DOMAIN,
        SERVICE_SET_DEVICE_PREFERENCES,
        handle_set_device_preferences,
    )

    hass.services.async_register(
        DOMAIN,
        SERVICE_GET_SMART_METER_READINGS,
        handle_get_smart_meter_readings,
        supports_response=SupportsResponse.ONLY,
    )

    hass.services.async_register(
        DOMAIN,
        SERVICE_EXPORT_SMART_METER_CSV,
        handle_export_smart_meter_csv,
        supports_response=SupportsResponse.ONLY,
    )

    hass.services.async_register(
        DOMAIN,
        SERVICE_SUBMIT_METER_READINGS,
        handle_submit_meter_readings,
        supports_response=SupportsResponse.ONLY,
    )

    if not hass.services.has_service(DOMAIN, SERVICE_REFRESH_INTELLIGENT_DATA):
        hass.services.async_register(
            DOMAIN,
            SERVICE_REFRESH_INTELLIGENT_DATA,
            lambda call: async_handle_refresh_intelligent_data(hass, call),
        )

    return True


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Unload a config entry."""
    if unload_ok := await hass.config_entries.async_unload_platforms(entry, PLATFORMS):
        data = hass.data[DOMAIN].get(entry.entry_id, {})
        if intelligent_coordinator := data.get("intelligent_coordinator"):
            await intelligent_coordinator.async_shutdown()
        await data["coordinator"].async_shutdown()
        hass.data[DOMAIN].pop(entry.entry_id)
        if not hass.data[DOMAIN] and hass.services.has_service(
            DOMAIN, SERVICE_REFRESH_INTELLIGENT_DATA
        ):
            hass.services.async_remove(DOMAIN, SERVICE_REFRESH_INTELLIGENT_DATA)

    return unload_ok


async def _async_update_options(hass: HomeAssistant, config_entry: ConfigEntry) -> None:
    """Handle options update."""
    # update entry replacing data with new options
    hass.config_entries.async_update_entry(
        config_entry, data={**config_entry.data, **config_entry.options}
    )
    await hass.config_entries.async_reload(config_entry.entry_id)
