"""
Octopus Germany Integration.

This module provides integration with the Octopus Germany API for Home Assistant.
"""

from __future__ import annotations

import inspect
import logging
from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING, Any

from homeassistant.const import Platform
from homeassistant.helpers import device_registry as dr

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
    extract_meter_data,
    merge_normalized_account_data,
    normalize_agreement_products,
    normalize_direct_products,
    process_ledgers,
)
from .models import (
    CoordinatorData,
    account_has_electricity,
    detect_tariff_capabilities,
    filter_active_accounts,
    select_primary_account,
)
from .octopus_germany import OctopusGermany
from .sensor import get_account_device_info
from .service_handlers import async_register_services
from .services import async_handle_refresh_intelligent_data
from .statistics import async_setup_statistics_import
from .tariff import is_product_current

if TYPE_CHECKING:
    from homeassistant.config_entries import ConfigEntry
    from homeassistant.core import HomeAssistant

_LOGGER = logging.getLogger(__name__)

PLATFORMS: list[Platform] = [Platform.BINARY_SENSOR, Platform.SENSOR, Platform.SWITCH]

API_URL = "https://api.octopus.energy/v1/graphql/"


async def _async_fetch_account_data(
    api: OctopusGermany,
    account_numbers: list[str],
    process_api_data: Any,
    capabilities_by_account: dict,
) -> CoordinatorData:
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


def _merge_intelligent_coordinator_data(
    coordinator: OctopusDataCoordinator,
    intelligent_coordinator: OctopusDataCoordinator | None,
) -> None:
    """Merge Intelligent data without resetting base refresh scheduling."""
    if coordinator is None or intelligent_coordinator is None:
        return
    if not coordinator.data or not intelligent_coordinator.data:
        return

    merged_data = dict(coordinator.data)
    for account_num, intelligent_data in intelligent_coordinator.data.items():
        if account_num in merged_data:
            merged_data[account_num] = merge_normalized_account_data(
                merged_data[account_num], intelligent_data
            )

    coordinator.data = merged_data
    coordinator.last_update_success = True
    coordinator.async_update_listeners()


SERVICE_REFRESH_INTELLIGENT_DATA = "refresh_intelligent_data"


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
    electricity_accounts: set[str] = set()
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
        electricity_accounts = {
            account["number"]
            for account in active_accounts
            if account_has_electricity(account)
        }
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
    async def async_update_data() -> CoordinatorData:
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
            "Coordinator update called at %s "
            "(Update interval: %s minutes, "
            "Time since last API call: %.1f seconds, Caller: %s)",
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
                    "Failed to fetch data from API for any account, "
                    "returning last known data"
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

        except Exception:
            _LOGGER.exception("Unexpected error during data update")
            # Return previous data if available, empty dict otherwise
            return coordinator.data if hasattr(coordinator, "data") else {}

    async def process_api_data(
        data: dict[str, Any],
        account_number: str,
        api: OctopusGermany,
        *,
        include_meter_readings: bool = True,
    ) -> CoordinatorData:
        """Process raw API response into structured data."""
        if not data:
            return {}

        result_data = create_empty_account_data(account_number)

        # Extract account data.
        # This should be available even if device-related endpoints fail.
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
            "Processed %d ledgers for account %s: "
            "electricity=%.2f, gas=%.2f, heat=%.2f, other=%d",
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
                    "API missing plannedDispatches for %s, "
                    "using cached data (%d dispatches)",
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
            products = normalize_agreement_products(account_data, "electricityMalos")

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
        elif account_number in electricity_accounts:
            _LOGGER.warning("No products found for account %s", account_number)
        else:
            _LOGGER.debug(
                "Account %s has no electricity ledger; skipping product warning",
                account_number,
            )

        result_data[account_number]["products"] = products

        # Extract gas products using the same agreement normalization contract.
        gas_products = normalize_agreement_products(account_data, "gasMalos")

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
            valid_gas_products = []

            for product in gas_products:
                valid_from = product.get("validFrom")

                if not valid_from:
                    continue

                if is_product_current(product):
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
                    "Attempting to fetch electricity meter reading for "
                    "account %s, meter %s",
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
                    "Failed to fetch electricity meter reading for "
                    "account %s, meter %s: %s",
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

    async def async_update_intelligent_data() -> CoordinatorData:
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
        _merge_intelligent_coordinator_data(coordinator, intelligent_coordinator)

        def _merge_intelligent_update() -> None:
            _merge_intelligent_coordinator_data(coordinator, intelligent_coordinator)

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

    await async_setup_statistics_import(hass, api, coordinator, account_numbers)

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

    await async_register_services(
        hass,
        entry,
        api,
        coordinator,
        lambda: hass.data[DOMAIN][entry.entry_id].get("intelligent_coordinator"),
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
