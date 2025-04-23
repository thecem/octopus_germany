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

_LOGGER = logging.getLogger(__name__)

PLATFORMS: list[Platform] = [Platform.SENSOR, Platform.SWITCH]


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

        account_data = data.get("account", {})
        devices = data.get("devices", [])
        planned_dispatches = data.get("plannedDispatches", [])
        completed_dispatches = data.get("completedDispatches", [])

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

        melo_number = next(
            (
                malo.get("meloNumber")
                for prop in account_data.get("allProperties", [])
                for malo in prop.get("electricityMalos", [])
                if malo.get("meloNumber")
            ),
            None,
        )

        # Get meter data
        meter = None
        for prop in account_data.get("allProperties", []):
            for malo in prop.get("electricityMalos", []):
                if malo.get("meter"):
                    meter = malo.get("meter")
                    break
            if meter:
                break

        # Extract products
        products = []
        for prop in account_data.get("allProperties", []):
            for malo in prop.get("electricityMalos", []):
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

                    # Get the gross rate - Handle different possible data structures
                    gross_rate = "0"

                    # First case: grossRateInformation exists and is a dictionary
                    if "grossRateInformation" in unit_rate_info:
                        # Check if it's a list or a dictionary
                        if isinstance(unit_rate_info["grossRateInformation"], dict):
                            gross_rate = unit_rate_info["grossRateInformation"].get(
                                "grossRate", "0"
                            )
                        elif (
                            isinstance(unit_rate_info["grossRateInformation"], list)
                            and unit_rate_info["grossRateInformation"]
                        ):
                            # Get the first item from the list if it exists
                            gross_rate = (
                                unit_rate_info["grossRateInformation"][0].get(
                                    "grossRate", "0"
                                )
                                if unit_rate_info["grossRateInformation"]
                                else "0"
                            )
                    # Second case: latestGrossUnitRateCentsPerKwh exists
                    elif "latestGrossUnitRateCentsPerKwh" in unit_rate_info:
                        gross_rate = unit_rate_info["latestGrossUnitRateCentsPerKwh"]
                    # Third case: unitRateGrossRateInformation exists
                    elif "unitRateGrossRateInformation" in agreement:
                        if isinstance(agreement["unitRateGrossRateInformation"], dict):
                            gross_rate = agreement["unitRateGrossRateInformation"].get(
                                "grossRate", "0"
                            )
                        elif (
                            isinstance(agreement["unitRateGrossRateInformation"], list)
                            and agreement["unitRateGrossRateInformation"]
                        ):
                            gross_rate = (
                                agreement["unitRateGrossRateInformation"][0].get(
                                    "grossRate", "0"
                                )
                                if agreement["unitRateGrossRateInformation"]
                                else "0"
                            )

                    products.append(
                        {
                            "code": product.get("code"),
                            "description": product.get("description", ""),
                            "name": product.get("fullName", "Unknown"),
                            "grossRate": gross_rate,
                            "type": product_type,
                            "validFrom": agreement.get("validFrom"),
                            "validTo": agreement.get("validTo"),
                        }
                    )

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

        # Extract property IDs
        property_ids = [
            prop.get("id") for prop in account_data.get("allProperties", [])
        ]

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

        # Build structured data response
        return {
            account_number: {
                "account_number": account_number,
                "electricity_balance": electricity_balance_eur,
                "planned_dispatches": planned_dispatches,
                "completed_dispatches": completed_dispatches,
                "property_ids": property_ids,
                "devices": devices,
                "products": products,
                "vehicle_battery_size_in_kwh": vehicle_battery_size,
                "current_start": current_start,
                "current_end": current_end,
                "next_start": next_start,
                "next_end": next_end,
                "ledgers": ledgers,
                "malo_number": malo_number,
                "melo_number": melo_number,
                "meter": meter,
            }
        }

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
