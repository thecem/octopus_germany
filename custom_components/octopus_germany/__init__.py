"""Octopus Germany Integration.

This module provides integration with the Octopus Germany API for Home Assistant.
"""

from __future__ import annotations

import logging
from datetime import timedelta, datetime
import inspect

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import Platform
from homeassistant.core import HomeAssistant
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator
from homeassistant.util.dt import utcnow, as_utc, parse_datetime

from .const import DOMAIN, CONF_EMAIL, CONF_PASSWORD, UPDATE_INTERVAL, DEBUG_ENABLED
from .octopus_germany import OctopusGermany

import voluptuous as vol
from homeassistant.core import ServiceCall
from homeassistant.helpers import config_validation as cv
from homeassistant.helpers.aiohttp_client import async_get_clientsession
import aiohttp

_LOGGER = logging.getLogger(__name__)

PLATFORMS: list[Platform] = [Platform.SENSOR, Platform.BINARY_SENSOR, Platform.SWITCH]

API_URL = "https://api.octopus.energy/v1/graphql/"

# Service schemas
SERVICE_SET_VEHICLE_CHARGE_PREFERENCES = "set_vehicle_charge_preferences"
ATTR_ACCOUNT_NUMBER = "account_number"
ATTR_WEEKDAY_TARGET_SOC = "weekday_target_soc"
ATTR_WEEKEND_TARGET_SOC = "weekend_target_soc"
ATTR_WEEKDAY_TARGET_TIME = "weekday_target_time"
ATTR_WEEKEND_TARGET_TIME = "weekend_target_time"


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

    # Ensure account_number is fetched and stored during setup
    account_number = entry.data.get("account_number")
    if not account_number:
        _LOGGER.debug("Account number not found in entry data, fetching from API")
        accounts = await api.fetch_accounts()
        if not accounts:
            _LOGGER.error("No accounts found for the provided credentials")
            return False
        account_number = accounts[0]["number"]  # Use the first account by default
        _LOGGER.debug("Using account number: %s", account_number)

        # Persist the account_number in the config entry
        hass.config_entries.async_update_entry(
            entry, data={**entry.data, "account_number": account_number}
        )

    # Create data update coordinator with improved error handling and retry logic
    async def async_update_data():
        """Fetch data from API with improved error handling."""
        current_time = datetime.now()

        # Add throttling to prevent too frequent API calls
        # Store last successful API call time on the function object
        if not hasattr(async_update_data, "last_api_call"):
            async_update_data.last_api_call = datetime.now() - timedelta(
                minutes=UPDATE_INTERVAL
            )

        # Calculate time since last API call
        time_since_last_call = (
            current_time - async_update_data.last_api_call
        ).total_seconds()
        min_interval = (
            UPDATE_INTERVAL * 60 * 0.9
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
            UPDATE_INTERVAL,
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

            # Fetch all data in one call to minimize API requests
            data = await api.fetch_all_data(account_number)

            # Update last API call timestamp only on successful calls
            async_update_data.last_api_call = datetime.now()

            if data is None:
                _LOGGER.error(
                    "Failed to fetch data from API, returning last known data"
                )
                return coordinator.data if hasattr(coordinator, "data") else {}

            # Process the raw API data into a more usable format
            try:
                processed_data = await process_api_data(data, account_number)

                _LOGGER.debug(
                    "Successfully fetched data from API at %s",
                    datetime.now().strftime("%H:%M:%S"),
                )
                return processed_data
            except Exception as e:
                _LOGGER.exception("Error processing API data: %s", str(e))
                return coordinator.data if hasattr(coordinator, "data") else {}

        except Exception as e:
            _LOGGER.exception("Unexpected error during data update: %s", e)
            # Return previous data if available, empty dict otherwise
            return coordinator.data if hasattr(coordinator, "data") else {}

    async def process_api_data(data, account_number):
        """Process raw API response into structured data."""
        if not data:
            return {}

        # Initialize the data structure
        result_data = {
            account_number: {
                "account_number": account_number,
                "electricity_balance": 0,
                "planned_dispatches": [],
                "completed_dispatches": [],
                "property_ids": [],
                "devices": [],
                "products": [],
                "vehicle_battery_size_in_kwh": None,
                "current_start": None,
                "current_end": None,
                "next_start": None,
                "next_end": None,
                "ledgers": [],
                "malo_number": None,
                "melo_number": None,
                "meter": None,
            }
        }

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
        else:
            _LOGGER.warning("Account data is missing or invalid: %s", account_data)
            # Return the basic structure with default values
            return result_data

        # Extract electricity balance from ledgers
        ledgers = account_data.get("ledgers", [])
        electricity_balance_cents = next(
            (
                ledger.get("balance", 0)
                for ledger in ledgers
                if ledger.get("ledgerType") == "ELECTRICITY_LEDGER"
            ),
            0,
        )
        electricity_balance_eur = electricity_balance_cents / 100
        result_data[account_number]["electricity_balance"] = electricity_balance_eur
        result_data[account_number]["ledgers"] = ledgers

        # Extract MALO and MELO numbers
        malo_number = next(
            (
                malo.get("maloNumber")
                for prop in account_data.get("allProperties", [])
                for malo in prop.get("electricityMalos", [])
                if malo.get("maloNumber")
            ),
            None,
        )
        result_data[account_number]["malo_number"] = malo_number

        melo_number = next(
            (
                malo.get("meloNumber")
                for prop in account_data.get("allProperties", [])
                for malo in prop.get("electricityMalos", [])
                if malo.get("meloNumber")
            ),
            None,
        )
        result_data[account_number]["melo_number"] = melo_number

        # Get meter data
        meter = None
        for prop in account_data.get("allProperties", []):
            for malo in prop.get("electricityMalos", []):
                if malo.get("meter"):
                    meter = malo.get("meter")
                    break
            if meter:
                break
        result_data[account_number]["meter"] = meter

        # Extract property IDs
        property_ids = [
            prop.get("id") for prop in account_data.get("allProperties", [])
        ]
        result_data[account_number]["property_ids"] = property_ids

        # Handle device-related data if it exists (may be missing with KT-CT-4301 error)
        devices = data.get("devices", [])
        result_data[account_number]["devices"] = devices

        # Extract vehicle battery size if available
        vehicle_battery_size = None
        for device in devices:
            if device.get("vehicleVariant") and device["vehicleVariant"].get(
                "batterySize"
            ):
                try:
                    vehicle_battery_size = float(
                        device["vehicleVariant"]["batterySize"]
                    )
                    break
                except (ValueError, TypeError):
                    pass
        result_data[account_number]["vehicle_battery_size_in_kwh"] = (
            vehicle_battery_size
        )

        # Handle dispatch data if it exists
        planned_dispatches = data.get("plannedDispatches", [])
        if planned_dispatches is None:  # Handle explicit None value (from API error)
            planned_dispatches = []
        result_data[account_number]["planned_dispatches"] = planned_dispatches

        completed_dispatches = data.get("completedDispatches", [])
        if completed_dispatches is None:  # Handle explicit None value (from API error)
            completed_dispatches = []
        result_data[account_number]["completed_dispatches"] = completed_dispatches

        # Calculate current and next dispatches
        now = utcnow()  # Use timezone-aware UTC now
        current_start = None
        current_end = None
        next_start = None
        next_end = None

        for dispatch in sorted(planned_dispatches, key=lambda x: x.get("start", "")):
            try:
                # Convert string to timezone-aware datetime objects
                start_str = dispatch.get("start")
                end_str = dispatch.get("end")

                if not start_str or not end_str:
                    continue

                # Parse string to datetime and ensure it's UTC timezone-aware
                start = as_utc(parse_datetime(start_str))
                end = as_utc(parse_datetime(end_str))

                if start <= now <= end:
                    current_start = start
                    current_end = end
                elif now < start and not next_start:
                    next_start = start
                    next_end = end
            except (ValueError, TypeError) as e:
                _LOGGER.error("Error parsing dispatch dates: %s - %s", dispatch, str(e))

        result_data[account_number]["current_start"] = current_start
        result_data[account_number]["current_end"] = current_end
        result_data[account_number]["next_start"] = next_start
        result_data[account_number]["next_end"] = next_end

        # Extract products - ensure we always have product data
        products = []
        direct_products = data.get("direct_products", [])

        # Check if we have direct products data first
        if direct_products:
            _LOGGER.debug("Found %d direct products", len(direct_products))
            for product in direct_products:
                # Get the gross rate from the direct products data
                gross_rate = "0"
                if "grossRateInformation" in product:
                    gross_info = product.get("grossRateInformation", {})
                    if isinstance(gross_info, dict):
                        gross_rate = gross_info.get("grossRate", "0")
                    elif isinstance(gross_info, list) and gross_info:
                        gross_rate = gross_info[0].get("grossRate", "0")

                products.append(
                    {
                        "code": product.get("code", "Unknown"),
                        "description": product.get("description", ""),
                        "name": product.get("fullName", "Unknown"),
                        "grossRate": gross_rate,
                        "type": "Simple",  # Default type for direct products
                        "validFrom": None,  # We don't have this info from direct products
                        "validTo": None,  # We don't have this info from direct products
                    }
                )

        # If no direct products, try to extract from the account data
        if not products:
            _LOGGER.debug("Extracting products from account data")

            # This tracks if we've found any gross rates to help with debugging
            found_any_gross_rate = False

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
                        product_type = "Simple"
                        if "__typename" in unit_rate_info:
                            product_type = (
                                "Simple"
                                if unit_rate_info["__typename"]
                                == "SimpleProductUnitRateInformation"
                                else "TimeOfUse"
                            )

                        # For Simple product types
                        if product_type == "Simple":
                            # Get the gross rate from various possible sources
                            gross_rate = "0"

                            # Check different possible sources for gross rate
                            if "grossRateInformation" in unit_rate_info:
                                found_any_gross_rate = True
                                if isinstance(
                                    unit_rate_info["grossRateInformation"], dict
                                ):
                                    gross_rate = unit_rate_info[
                                        "grossRateInformation"
                                    ].get("grossRate", "0")
                                elif (
                                    isinstance(
                                        unit_rate_info["grossRateInformation"], list
                                    )
                                    and unit_rate_info["grossRateInformation"]
                                ):
                                    gross_rate = (
                                        unit_rate_info["grossRateInformation"][0].get(
                                            "grossRate", "0"
                                        )
                                        if unit_rate_info["grossRateInformation"]
                                        else "0"
                                    )
                            elif "latestGrossUnitRateCentsPerKwh" in unit_rate_info:
                                found_any_gross_rate = True
                                gross_rate = unit_rate_info[
                                    "latestGrossUnitRateCentsPerKwh"
                                ]
                            elif "unitRateGrossRateInformation" in agreement:
                                found_any_gross_rate = True
                                if isinstance(
                                    agreement["unitRateGrossRateInformation"], dict
                                ):
                                    gross_rate = agreement[
                                        "unitRateGrossRateInformation"
                                    ].get("grossRate", "0")
                                elif (
                                    isinstance(
                                        agreement["unitRateGrossRateInformation"], list
                                    )
                                    and agreement["unitRateGrossRateInformation"]
                                ):
                                    gross_rate = (
                                        agreement["unitRateGrossRateInformation"][
                                            0
                                        ].get("grossRate", "0")
                                        if agreement["unitRateGrossRateInformation"]
                                        else "0"
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
                                }
                            )

                        # For TimeOfUse product types
                        elif product_type == "TimeOfUse" and "rates" in unit_rate_info:
                            # Process time-of-use rates
                            timeslots = []

                            for rate in unit_rate_info["rates"]:
                                gross_rate = "0"

                                # Extract the gross rate
                                if (
                                    "grossRateInformation" in rate
                                    and rate["grossRateInformation"]
                                ):
                                    if isinstance(rate["grossRateInformation"], dict):
                                        gross_rate = rate["grossRateInformation"].get(
                                            "grossRate", "0"
                                        )
                                    elif (
                                        isinstance(rate["grossRateInformation"], list)
                                        and rate["grossRateInformation"]
                                    ):
                                        gross_rate = rate["grossRateInformation"][
                                            0
                                        ].get("grossRate", "0")
                                elif "latestGrossUnitRateCentsPerKwh" in rate:
                                    gross_rate = rate["latestGrossUnitRateCentsPerKwh"]

                                # Create activation rules
                                activation_rules = []
                                if "timeslotActivationRules" in rate and isinstance(
                                    rate["timeslotActivationRules"], list
                                ):
                                    for rule in rate["timeslotActivationRules"]:
                                        activation_rules.append(
                                            {
                                                "from_time": rule.get(
                                                    "activeFromTime", "00:00:00"
                                                ),
                                                "to_time": rule.get(
                                                    "activeToTime", "00:00:00"
                                                ),
                                            }
                                        )

                                # Add timeslot data
                                timeslots.append(
                                    {
                                        "name": rate.get("timeslotName", "Unknown"),
                                        "rate": gross_rate,
                                        "activation_rules": activation_rules,
                                    }
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
            # Add a test product so we at least get a sensor for testing
            products.append(
                {
                    "code": "TEST_PRODUCT",
                    "description": "Test Product for debugging",
                    "name": "Test Product",
                    "grossRate": "30",  # 30 cents as a reasonable default
                    "type": "Simple",
                    "validFrom": None,
                    "validTo": None,
                }
            )

        result_data[account_number]["products"] = products

        return result_data

    coordinator = DataUpdateCoordinator(
        hass,
        _LOGGER,
        name=f"{DOMAIN}_{account_number}",
        update_method=async_update_data,
        update_interval=timedelta(minutes=UPDATE_INTERVAL),
    )

    # Initial data refresh - only once to prevent duplicate API calls
    await coordinator.async_config_entry_first_refresh()

    # Store API, account number and coordinator in hass.data
    hass.data[DOMAIN][entry.entry_id] = {
        "api": api,
        "account_number": account_number,
        "coordinator": coordinator,
    }

    # Forward setup to platforms - no need to wait for another refresh
    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)

    entry.async_on_unload(entry.add_update_listener(_async_update_options))

    # Register services
    async def handle_set_vehicle_charge_preferences(call: ServiceCall):
        """Handle the service call."""
        # Use account number from service call or fall back to the one from config
        call_account_number = call.data.get(ATTR_ACCOUNT_NUMBER)
        used_account_number = call_account_number or account_number
        weekday_target_soc = call.data.get(ATTR_WEEKDAY_TARGET_SOC)
        weekend_target_soc = call.data.get(ATTR_WEEKEND_TARGET_SOC)
        weekday_target_time = call.data.get(ATTR_WEEKDAY_TARGET_TIME)
        weekend_target_time = call.data.get(ATTR_WEEKEND_TARGET_TIME)

        # Call the method on the API class
        success = await api.set_vehicle_charge_preferences(
            used_account_number,
            weekday_target_soc,
            weekend_target_soc,
            weekday_target_time,
            weekend_target_time,
        )

        if success:
            _LOGGER.info("Successfully set vehicle charge preferences")
            return True
        else:
            _LOGGER.error("Failed to set vehicle charge preferences")
            return False

    hass.services.async_register(
        DOMAIN,
        SERVICE_SET_VEHICLE_CHARGE_PREFERENCES,
        handle_set_vehicle_charge_preferences,
    )

    return True


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Unload a config entry."""
    if unload_ok := await hass.config_entries.async_unload_platforms(entry, PLATFORMS):
        hass.data[DOMAIN].pop(entry.entry_id)

    return unload_ok


async def _async_update_options(hass: HomeAssistant, config_entry: ConfigEntry) -> None:
    """Handle options update."""
    # update entry replacing data with new options
    hass.config_entries.async_update_entry(
        config_entry, data={**config_entry.data, **config_entry.options}
    )
    await hass.config_entries.async_reload(config_entry.entry_id)
