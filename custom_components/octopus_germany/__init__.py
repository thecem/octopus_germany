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

PLATFORMS: list[Platform] = [Platform.BINARY_SENSOR, Platform.SENSOR, Platform.SWITCH]

API_URL = "https://api.octopus.energy/v1/graphql/"

# Service schemas
SERVICE_SET_DEVICE_PREFERENCES = "set_device_preferences"
SERVICE_GET_SMART_METER_READINGS = "get_smart_meter_readings"
ATTR_ACCOUNT_NUMBER = "account_number"
ATTR_DEVICE_ID = "device_id"
ATTR_TARGET_PERCENTAGE = "target_percentage"
ATTR_TARGET_TIME = "target_time"
ATTR_DATE = "date"
ATTR_PROPERTY_ID = "property_id"


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
    if not account_numbers:
        # Backward compatibility: try single account_number
        single_account = entry.data.get("account_number")
        if single_account:
            account_numbers = [single_account]
        else:
            _LOGGER.debug("No account numbers found in entry data, fetching from API")
            accounts = await api.fetch_accounts()
            if not accounts:
                _LOGGER.error("No accounts found for the provided credentials")
                return False

            # Store all accounts, not just the first one with electricity ledger
            account_numbers = [acc["number"] for acc in accounts]
            _LOGGER.info("Found %d accounts: %s", len(account_numbers), account_numbers)

            # Update config entry with all account numbers
            hass.config_entries.async_update_entry(
                entry, data={**entry.data, "account_numbers": account_numbers}
            )

    # For backward compatibility, set primary account_number to first account
    primary_account_number = account_numbers[0] if account_numbers else None
    if not entry.data.get("account_number"):
        hass.config_entries.async_update_entry(
            entry, data={**entry.data, "account_number": primary_account_number}
        )

    # Create data update coordinator with improved error handling and retry logic
    async def async_update_data():
        """Fetch data from API with improved error handling for all accounts."""
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

            # Fetch data for all accounts
            all_accounts_data = {}
            for account_num in account_numbers:
                try:
                    # Fetch all data in one call to minimize API requests
                    account_data = await api.fetch_all_data(account_num)
                    if account_data:
                        # Process the raw API data into a more usable format
                        processed_account_data = await process_api_data(
                            account_data, account_num, api
                        )
                        all_accounts_data.update(processed_account_data)
                    else:
                        _LOGGER.warning(
                            "Failed to fetch data for account %s", account_num
                        )
                except Exception as e:
                    _LOGGER.error(
                        "Error fetching data for account %s: %s", account_num, e
                    )
                    continue

            # Update last API call timestamp only on successful calls
            if all_accounts_data:
                async_update_data.last_api_call = datetime.now()

            if not all_accounts_data:
                _LOGGER.error(
                    "Failed to fetch data from API for any account, returning last known data"
                )
                return coordinator.data if hasattr(coordinator, "data") else {}

            _LOGGER.debug(
                "Successfully fetched data from API at %s for %d accounts",
                datetime.now().strftime("%H:%M:%S"),
                len(all_accounts_data),
            )
            return all_accounts_data

        except Exception as e:
            _LOGGER.exception("Unexpected error during data update: %s", e)
            # Return previous data if available, empty dict otherwise
            return coordinator.data if hasattr(coordinator, "data") else {}

    async def process_api_data(data, account_number, api):
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
                "gas_products": [],
                "vehicle_battery_size_in_kwh": None,
                "current_start": None,
                "current_end": None,
                "next_start": None,
                "next_end": None,
                "ledgers": [],
                "malo_number": None,
                "melo_number": None,
                "meter": None,
                "gas_malo_number": None,
                "gas_melo_number": None,
                "gas_meter": None,
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

        # Extract ALL ledger data (not just electricity)
        ledgers = account_data.get("ledgers", [])
        result_data[account_number]["ledgers"] = ledgers

        # Initialize all ledger balances
        electricity_balance_eur = 0
        gas_balance_eur = 0
        heat_balance_eur = 0
        other_ledgers = {}

        # Process all available ledgers
        for ledger in ledgers:
            ledger_type = ledger.get("ledgerType")
            balance_cents = ledger.get("balance", 0)
            balance_eur = balance_cents / 100

            if ledger_type == "ELECTRICITY_LEDGER":
                electricity_balance_eur = balance_eur
            elif ledger_type == "GAS_LEDGER":
                gas_balance_eur = balance_eur
            elif ledger_type == "HEAT_LEDGER":
                heat_balance_eur = balance_eur
            else:
                # Store any other ledger types we might encounter
                other_ledgers[ledger_type] = balance_eur
                _LOGGER.debug(
                    "Found additional ledger type: %s with balance: %.2f EUR",
                    ledger_type,
                    balance_eur,
                )

        # Store all ledger balances in result
        result_data[account_number]["electricity_balance"] = electricity_balance_eur
        result_data[account_number]["gas_balance"] = gas_balance_eur
        result_data[account_number]["heat_balance"] = heat_balance_eur
        result_data[account_number]["other_ledgers"] = other_ledgers

        _LOGGER.debug(
            "Processed %d ledgers for account %s: electricity=%.2f, gas=%.2f, heat=%.2f, other=%d",
            len(ledgers),
            account_number,
            electricity_balance_eur,
            gas_balance_eur,
            heat_balance_eur,
            len(other_ledgers),
        )

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

        # Extract gas MALO and MELO numbers
        gas_malo_number = next(
            (
                malo.get("maloNumber")
                for prop in account_data.get("allProperties", [])
                for malo in prop.get("gasMalos", [])
                if malo.get("maloNumber")
            ),
            None,
        )
        result_data[account_number]["gas_malo_number"] = gas_malo_number

        gas_melo_number = next(
            (
                malo.get("meloNumber")
                for prop in account_data.get("allProperties", [])
                for malo in prop.get("gasMalos", [])
                if malo.get("meloNumber")
            ),
            None,
        )
        result_data[account_number]["gas_melo_number"] = gas_melo_number

        # Get gas meter data
        gas_meter = None
        for prop in account_data.get("allProperties", []):
            for malo in prop.get("gasMalos", []):
                if malo.get("meter"):
                    gas_meter = malo.get("meter")
                    break
            if gas_meter:
                break
        result_data[account_number]["gas_meter"] = gas_meter

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
        # Check if key exists at all - if not, API had error and we should cache
        if "plannedDispatches" not in data:
            # API error - plannedDispatches was removed from result, use cached data
            if (
                account_number in self.data
                and "planned_dispatches" in self.data[account_number]
            ):
                planned_dispatches = self.data[account_number]["planned_dispatches"]
                _LOGGER.debug(
                    "API error fetching planned dispatches for %s, using cached data (%d dispatches)",
                    account_number,
                    len(planned_dispatches),
                )
            else:
                planned_dispatches = []  # No previous data available
        else:
            planned_dispatches = data.get("plannedDispatches")
            if planned_dispatches is None:  # Explicit None from API
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
                        "isTimeOfUse": product.get("isTimeOfUse", False),
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

                            # Add unitRateForecast for TimeOfUse products
                            unit_rate_forecast = agreement.get("unitRateForecast", [])

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

                            # Add unitRateForecast for TimeOfUse products
                            unit_rate_forecast = agreement.get("unitRateForecast", [])

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
                    "isTimeOfUse": False,
                }
            )

        result_data[account_number]["products"] = products

        # Extract gas products - similar process to electricity products
        gas_products = []

        for prop in account_data.get("allProperties", []):
            for malo in prop.get("gasMalos", []):
                for agreement in malo.get("agreements", []):
                    product = agreement.get("product", {})
                    unit_rate_info = agreement.get("unitRateInformation", {})

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
                            if isinstance(unit_rate_info["grossRateInformation"], dict):
                                gross_rate = unit_rate_info["grossRateInformation"].get(
                                    "grossRate", "0"
                                )
                            elif (
                                isinstance(unit_rate_info["grossRateInformation"], list)
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
                            gross_rate = unit_rate_info[
                                "latestGrossUnitRateCentsPerKwh"
                            ]
                        elif "unitRateGrossRateInformation" in agreement:
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
                                    agreement["unitRateGrossRateInformation"][0].get(
                                        "grossRate", "0"
                                    )
                                    if agreement["unitRateGrossRateInformation"]
                                    else "0"
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
                        # Process time-of-use rates for gas
                        timeslots = []

                        for rate in unit_rate_info["rates"]:
                            gross_rate = "0"

                            # Get the gross rate for this timeslot
                            if "grossRateInformation" in rate:
                                if isinstance(rate["grossRateInformation"], dict):
                                    gross_rate = rate["grossRateInformation"].get(
                                        "grossRate", "0"
                                    )
                                elif (
                                    isinstance(rate["grossRateInformation"], list)
                                    and rate["grossRateInformation"]
                                ):
                                    gross_rate = (
                                        rate["grossRateInformation"][0].get(
                                            "grossRate", "0"
                                        )
                                        if rate["grossRateInformation"]
                                        else "0"
                                    )
                            elif "latestGrossUnitRateCentsPerKwh" in rate:
                                gross_rate = rate["latestGrossUnitRateCentsPerKwh"]

                            # Process activation rules
                            activation_rules = []
                            for rule in rate.get("timeslotActivationRules", []):
                                activation_rules.append(
                                    {
                                        "from_time": rule.get(
                                            "activeFromTime", "00:00:00"
                                        ),
                                        "to_time": rule.get("activeToTime", "00:00:00"),
                                    }
                                )

                            timeslots.append(
                                {
                                    "name": rate.get("timeslotName", "Unknown"),
                                    "rate": gross_rate,
                                    "activation_rules": activation_rules,
                                }
                            )

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
            now = datetime.now().isoformat()
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
                except (ValueError, TypeError):
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
                end_date = datetime.fromisoformat(
                    gas_contract_end.replace("Z", "+00:00")
                )
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

        # Gas meter smart reading capability
        gas_meter_smart_reading = None
        if gas_meter and isinstance(gas_meter, dict):
            gas_meter_smart_reading = gas_meter.get("shouldReceiveSmartMeterData", None)

        result_data[account_number]["gas_meter_smart_reading"] = gas_meter_smart_reading

        # Fetch latest gas meter reading if gas meter exists
        gas_latest_reading = None
        if gas_meter and gas_meter.get("id"):
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
        if meter and meter.get("id"):
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

    coordinator = DataUpdateCoordinator(
        hass,
        _LOGGER,
        name=f"{DOMAIN}_{primary_account_number}",
        update_method=async_update_data,
        update_interval=timedelta(minutes=UPDATE_INTERVAL),
    )

    # Initial data refresh - only once to prevent duplicate API calls
    await coordinator.async_config_entry_first_refresh()

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

    # Store API, account number and coordinator in hass.data
    hass.data[DOMAIN][entry.entry_id] = {
        "api": api,
        "account_number": primary_account_number,
        "account_numbers": account_numbers,
        "coordinator": coordinator,
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
                f"Invalid time format: {str(time_error)}",
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
                return {"success": True}
            else:
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

            parsed_date = datetime.strptime(date_str, "%Y-%m-%d").date()
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
            for entry_id, data in hass.data[DOMAIN].items():
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
