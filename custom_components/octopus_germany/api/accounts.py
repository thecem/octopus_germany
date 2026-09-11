"""Account, capability, and orchestration methods for the Octopus Germany API client."""

from __future__ import annotations

import json
import logging
from datetime import UTC, datetime, timedelta
from typing import Any

from homeassistant.exceptions import ConfigEntryNotReady

from custom_components.octopus_germany.const import (
    EXPLORE_SCHEMA_ONCE,
    LOG_API_RESPONSES,
)
from custom_components.octopus_germany.data_processing import extract_charging_sessions
from custom_components.octopus_germany.models import (
    TariffCapabilities,
    detect_tariff_capabilities,
)

from .queries import (
    ACCOUNT_CAPABILITIES_QUERY,
    ACCOUNT_DISCOVERY_QUERY,
    ACCOUNT_DISCOVERY_QUERY_LEGACY,
    COMPREHENSIVE_QUERY,
    INTELLIGENT_DATA_QUERY,
)

_LOGGER = logging.getLogger(__name__)


class AccountApiMixin:
    """Mixin that provides account/capability and orchestration API calls."""

    # Consolidated query to get both accounts list and initial data in one API call
    async def fetch_accounts_with_initial_data(self) -> list[dict[str, Any]] | None:
        """Fetch accounts and initial data in a single API call."""
        await self.ensure_token()

        client = self._get_graphql_client()

        try:
            response = await client.execute_async(query=ACCOUNT_DISCOVERY_QUERY)
            _LOGGER.debug("Fetch accounts with initial data response: %s", response)

            viewer = (response.get("data") or {}).get("viewer")
            accounts = viewer.get("accounts") if viewer else None
            if accounts:
                return accounts

            if not accounts:
                _LOGGER.warning(
                    "Account discovery with status failed; retrying compatible query"
                )
                response = await client.execute_async(
                    query=ACCOUNT_DISCOVERY_QUERY_LEGACY
                )
                viewer = (response.get("data") or {}).get("viewer")
                accounts = viewer.get("accounts") if viewer else None

            if accounts:
                return accounts

            _LOGGER.error("No accounts found")
            return None
        except Exception:
            _LOGGER.exception("Error fetching accounts with initial data")
            return None

    # Legacy methods maintained for backward compatibility
    async def accounts(self) -> list[str]:
        """Fetch account numbers."""
        accounts = await self.fetch_accounts_with_initial_data()
        if not accounts:
            _LOGGER.error("Failed to fetch accounts")
            msg = "Failed to fetch accounts"
            raise ConfigEntryNotReady(msg)

        return [account["number"] for account in accounts]

    async def fetch_accounts(self) -> list[dict[str, Any]] | None:
        """Fetch accounts data."""
        return await self.fetch_accounts_with_initial_data()

    async def fetch_tariff_capabilities(
        self, account_number: str
    ) -> TariffCapabilities:
        """Fetch and cache the features available for an account."""
        if account_number in self._capabilities_by_account:
            return self._capabilities_by_account[account_number]

        if not await self.ensure_token():
            return TariffCapabilities()

        try:
            response = await self._get_graphql_client().execute_async(
                query=ACCOUNT_CAPABILITIES_QUERY,
                variables={"accountNumber": account_number},
            )
            response_data = response.get("data") or {}
            account_data = response_data.get("account") or {}
            if response_data.get("devices"):
                account_data = {
                    **account_data,
                    "devices": response_data["devices"],
                }
            capabilities = detect_tariff_capabilities(account_data)
        except Exception as err:
            _LOGGER.warning(
                "Unable to determine tariff capabilities for account %s: %s",
                account_number,
                err,
            )
            capabilities = TariffCapabilities()

        self._capabilities_by_account[account_number] = capabilities
        return capabilities

    async def fetch_data_for_account(
        self, account_number: str
    ) -> dict[str, Any] | None:
        """Fetch base account data without Intelligent-specific fields."""
        await self.fetch_tariff_capabilities(account_number)
        return await self.fetch_all_data(account_number, include_intelligent=False)

    async def fetch_intelligent_data(
        self, account_number: str
    ) -> dict[str, Any] | None:
        """Fetch device and dispatch data for an Intelligent account."""
        capabilities = await self.fetch_tariff_capabilities(account_number)
        if not capabilities.has_intelligent_dispatches:
            return None

        if not await self.ensure_token():
            return None

        try:
            return await self._get_graphql_client().execute_async(
                query=INTELLIGENT_DATA_QUERY,
                variables={"accountNumber": account_number},
            )
        except Exception as err:
            _LOGGER.warning(
                "Unable to fetch intelligent data for account %s: %s",
                account_number,
                err,
            )
            return None

    # Comprehensive data fetch in a single query
    async def fetch_all_data(
        self,
        account_number: str,
        include_intelligent: bool = True,
        include_meter_readings: bool = True,
    ) -> dict[str, Any] | None:
        """
        Fetch all data for an account including devices, dispatches and account details.

        This comprehensive query consolidates multiple separate queries into one
        to minimize API calls and improve performance.
        """
        if not await self.ensure_token():
            _LOGGER.error("Failed to ensure valid token for fetch_all_data")
            return None

        capabilities = await self.fetch_tariff_capabilities(account_number)

        variables = {"accountNumber": account_number}
        client = self._get_graphql_client()

        try:
            _LOGGER.debug(
                "Making API request to fetch_all_data for account %s",
                account_number,
            )
            response = await client.execute_async(
                query=COMPREHENSIVE_QUERY,
                variables={
                    **variables,
                    "includeIntelligent": include_intelligent,
                },
            )

            # Log the full API response only when LOG_API_RESPONSES is enabled.
            if LOG_API_RESPONSES:
                _LOGGER.info("API Response: %s", json.dumps(response, indent=2))
            else:
                _LOGGER.debug(
                    "API request completed. Set LOG_API_RESPONSES=True "
                    "for full response logging"
                )

            if response is None:
                _LOGGER.error("API returned None response")
                return None

            # Initialize the result structure - note that 'products' is an empty list
            # since we removed that field from the query
            result = {
                "account": {},
                "products": [],  # This will stay empty as we removed the property field
                "completedDispatches": [],
                "devices": [],
                "plannedDispatches": [],
            }

            # Check for partial data availability.
            # Continue even if there are some errors.
            if "data" in response:
                data = response["data"]

                # Process available data fields
                if "account" in data:
                    result["account"] = data["account"]

                    # Extract product information from account agreements when available.
                    # This keeps compatibility for code expecting the products field.
                    if (
                        result["account"]
                        and "allProperties" in result["account"]
                        and result["account"]["allProperties"]
                    ):
                        try:
                            # Try to extract products from electricityMalos agreements
                            products = []
                            for property_data in result["account"]["allProperties"]:
                                if "electricityMalos" in property_data:
                                    for malo in property_data["electricityMalos"]:
                                        if "agreements" in malo:
                                            products.extend(
                                                agreement["product"]
                                                for agreement in malo["agreements"]
                                                if "product" in agreement
                                            )

                            # Only update if we found products
                            if products:
                                result["products"] = products
                                _LOGGER.debug(
                                    "Extracted %d products from account data",
                                    len(products),
                                )
                        except Exception as extract_error:
                            _LOGGER.warning(
                                "Error extracting products from account data: %s",
                                extract_error,
                            )

                if "devices" in data:
                    result["devices"] = (
                        data["devices"] if data["devices"] is not None else []
                    )

                    # Check if there are errors specifically for chargingSessions
                    # If so, set to None to preserve cached sensor values
                    has_charging_sessions_error = False
                    if "errors" in response:
                        for error in response["errors"]:
                            error_path = error.get("path", [])
                            # Check if error is in chargingSessions path
                            if "chargingSessions" in error_path:
                                has_charging_sessions_error = True
                                error_code = error.get("extensions", {}).get(
                                    "errorCode"
                                )
                                _LOGGER.debug(
                                    "Error in chargingSessions path [%s], "
                                    "will use cached data",
                                    error_code,
                                )
                                break

                    charging_sessions = (
                        None
                        if has_charging_sessions_error
                        else extract_charging_sessions(result["devices"])
                    )

                    # Store charging sessions in result
                    result["charging_sessions"] = charging_sessions
                    if charging_sessions is None:
                        _LOGGER.debug(
                            "Charging sessions set to None due to API error "
                            "(sensor will use cached data)"
                        )
                    elif charging_sessions:
                        _LOGGER.debug(
                            "Extracted %d charging sessions from %d devices",
                            len(charging_sessions),
                            len(result["devices"]),
                        )
                    else:
                        _LOGGER.debug(
                            "No charging sessions found in %d devices",
                            len(result["devices"]),
                        )

                if "completedDispatches" in data:
                    result["completedDispatches"] = (
                        data["completedDispatches"]
                        if data["completedDispatches"] is not None
                        else []
                    )

                # Fetch flex planned dispatches for all devices with the new API
                result["plannedDispatches"] = []
                has_dispatch_fetch_error = False
                if result["devices"]:
                    _LOGGER.debug(
                        "Fetching flex planned dispatches for %d devices",
                        len(result["devices"]),
                    )
                    for device in result["devices"]:
                        device_id = device.get("id")
                        device_name = device.get("name", "Unknown")
                        if device_id:
                            try:
                                flex_dispatches = (
                                    await self.fetch_flex_planned_dispatches(device_id)
                                )
                                # If None returned, it means API error - keep old data
                                if flex_dispatches is None:
                                    has_dispatch_fetch_error = True
                                    _LOGGER.debug(
                                        "Skipping device %s due to API error "
                                        "(will use cached data)",
                                        device_id,
                                    )
                                    continue
                                if flex_dispatches:
                                    # Transform the new API format to match
                                    # the old format for backward compatibility.
                                    for dispatch in flex_dispatches:
                                        # Map new fields to old field names.
                                        transformed_dispatch = {
                                            "start": dispatch.get("start"),
                                            "startDt": dispatch.get(
                                                "start"
                                            ),  # Same as start
                                            "end": dispatch.get("end"),
                                            "endDt": dispatch.get("end"),  # Same as end
                                            "deltaKwh": dispatch.get("energyAddedKwh"),
                                            "delta": dispatch.get(
                                                "energyAddedKwh"
                                            ),  # Same as deltaKwh
                                            "type": dispatch.get(
                                                "type", "UNKNOWN"
                                            ),  # Add type as top-level attribute
                                            "meta": {
                                                "source": "flex_api",
                                                "type": dispatch.get("type", "UNKNOWN"),
                                                "deviceId": device_id,
                                            },
                                        }
                                        result["plannedDispatches"].append(
                                            transformed_dispatch
                                        )
                                    _LOGGER.debug(
                                        "Added %d flex planned dispatches "
                                        "from device %s (%s)",
                                        len(flex_dispatches),
                                        device_id,
                                        device_name,
                                    )
                            except Exception as e:
                                _LOGGER.warning(
                                    "Failed to fetch flex planned dispatches "
                                    "for device %s: %s",
                                    device_id,
                                    e,
                                )
                else:
                    _LOGGER.debug(
                        "No devices found, skipping flex planned dispatches fetch"
                    )

                # Preserve cached dispatch data when fetch errors occurred.
                if has_dispatch_fetch_error:
                    _LOGGER.debug(
                        "Planned dispatches fetch had errors, will preserve cached data"
                    )
                    # Let coordinator keep cached data by omitting the key.
                    if (
                        "plannedDispatches" in result
                        and not result["plannedDispatches"]
                    ):
                        result.pop("plannedDispatches")

                # Log errors without failing when account data is available.
                if "errors" in response and result["account"]:
                    # Define non-critical error codes that should not fail the request
                    # These are temporary API issues or expected missing data scenarios
                    non_critical_error_codes = [
                        # Resource not found (expected when no data exists)
                        "KT-CT-4301",
                        # Unable to fetch flex planned dispatches (temporary)
                        "KT-CT-4340",
                        "KT-CT-4382",  # Unable to fetch charging sessions (temporary)
                        "KT-CT-7899",  # Internal server error (temporary API issue)
                        # Unauthorized for specific query (permission issue)
                        "KT-CT-1111",
                    ]

                    # Filter non-critical errors (missing resources, temporary
                    # API issues).
                    non_critical_errors = [
                        error
                        for error in response["errors"]
                        if error.get("extensions", {}).get("errorCode")
                        in non_critical_error_codes
                    ]

                    # Handle other errors that might affect the account data
                    other_errors = [
                        error
                        for error in response["errors"]
                        if error not in non_critical_errors
                    ]

                    if non_critical_errors:
                        # Log non-critical errors at DEBUG level with clear context
                        for error in non_critical_errors:
                            error_code = error.get("extensions", {}).get("errorCode")
                            error_path = ".".join(str(p) for p in error.get("path", []))
                            error_msg = error.get("message", "No message")
                            _LOGGER.debug(
                                "Non-critical API error [%s] at path '%s': %s "
                                "(using cached data)",
                                error_code,
                                error_path,
                                error_msg,
                            )

                    if other_errors:
                        _LOGGER.error("API returned critical errors: %s", other_errors)

                        # Check for token expiry in the other errors
                        for error in other_errors:
                            error_code = error.get("extensions", {}).get("errorCode")
                            if error_code == "KT-CT-1124":  # JWT expired
                                _LOGGER.warning("Token expired, refreshing...")
                                self._token_manager.clear()
                                success = await self.login()
                                if success:
                                    # Retry with new token
                                    return await self.fetch_all_data(account_number)

                # Fetch electricity smart meter readings only when supported.
                try:
                    if (
                        include_meter_readings
                        and capabilities.has_smart_meter
                        and result.get("account")
                        and "allProperties" in result["account"]
                        and result["account"]["allProperties"]
                    ):
                        # Try to get property ID from the first property
                        property_data = result["account"]["allProperties"][0]
                        property_id = property_data.get("id")

                        if property_id:
                            # Optionally explore property schema once for
                            # smart-meter debugging.
                            if EXPLORE_SCHEMA_ONCE and not hasattr(
                                self, "_schema_explored"
                            ):
                                _LOGGER.info(
                                    "Exploring property schema for debugging "
                                    "smart meter issues..."
                                )
                                await self.explore_property_schema(
                                    account_number, property_id
                                )

                                # Mark as explored to prevent repeated exploration
                                self._schema_explored = True

                            # Meter readings are published with a delay; check
                            # the most recent available dates.
                            now_date = datetime.now(UTC).date()
                            yesterday = now_date - timedelta(days=1)
                            test_dates = [
                                (yesterday, "yesterday"),
                                (now_date - timedelta(days=2), "two_days_ago"),
                            ]

                            _LOGGER.debug(
                                "Fetching smart meter readings for recent dates: %s",
                                [date.isoformat() for date, _ in test_dates],
                            )

                            smart_meter_readings = None
                            successful_date = None

                            # Test each date until we find data.
                            for date_value, date_label in test_dates:
                                date_str = date_value.isoformat()
                                _LOGGER.debug(
                                    "Fetching electricity smart meter readings "
                                    "for property %s on %s (%s)",
                                    property_id,
                                    date_str,
                                    date_label,
                                )

                                readings = (
                                    await self.fetch_electricity_smart_meter_readings(
                                        account_number, property_id, date_str
                                    )
                                )

                                if readings:
                                    smart_meter_readings = readings
                                    successful_date = (date_str, date_label)
                                    _LOGGER.info(
                                        "Successfully fetched %d smart meter "
                                        "readings for %s (%s)",
                                        len(readings),
                                        date_label,
                                        date_str,
                                    )
                                    break
                                _LOGGER.debug(
                                    "No smart meter readings found for %s (%s)",
                                    date_label,
                                    date_str,
                                )

                            if smart_meter_readings:
                                result["electricity_smart_meter_readings"] = (
                                    smart_meter_readings
                                )
                                result["electricity_smart_meter_readings_date"] = (
                                    successful_date[0]
                                )
                                result["electricity_smart_meter_readings_label"] = (
                                    successful_date[1]
                                )
                            else:
                                _LOGGER.warning(
                                    "No smart meter readings found for any tested date"
                                )

                                # Try V2 query with yesterday's date as fallback
                                _LOGGER.info(
                                    "Trying V2 query with yesterday's date as fallback"
                                )
                                smart_meter_readings_v2 = await self.fetch_electricity_smart_meter_readings_v2(
                                    account_number,
                                    property_id,
                                    yesterday.isoformat(),
                                )

                                if smart_meter_readings_v2:
                                    result["electricity_smart_meter_readings"] = (
                                        smart_meter_readings_v2
                                    )
                                    result["electricity_smart_meter_readings_date"] = (
                                        yesterday.isoformat()
                                    )
                                    result["electricity_smart_meter_readings_label"] = (
                                        "yesterday_v2"
                                    )
                                    _LOGGER.info(
                                        "Successfully fetched %d smart meter "
                                        "readings with V2 query for yesterday",
                                        len(smart_meter_readings_v2),
                                    )
                                else:
                                    _LOGGER.warning(
                                        "No smart meter readings available "
                                        "with any query or date - checking "
                                        "property structure"
                                    )
                                    # Log the entire property structure for debugging
                                    _LOGGER.info(
                                        "Property data structure: %s",
                                        json.dumps(property_data, indent=2),
                                    )
                        else:
                            _LOGGER.debug(
                                "No property ID found for smart meter readings"
                            )
                    else:
                        _LOGGER.debug(
                            "No property data available for smart meter readings"
                        )
                except Exception as smart_meter_error:
                    _LOGGER.warning(
                        "Error fetching smart meter readings (non-critical): %s",
                        smart_meter_error,
                    )
                    # Continue without smart meter readings as this is not critical

                return result
            if "errors" in response:
                # Handle critical errors that prevent any data from being returned
                error = response.get("errors", [{}])[0]
                error_code = error.get("extensions", {}).get("errorCode")

                # Check if token expired error
                if error_code == "KT-CT-1124":  # JWT expired
                    _LOGGER.warning("Token expired, refreshing...")
                    self._token_manager.clear()
                    success = await self.login()
                    if success:
                        # Retry with new token
                        return await self.fetch_all_data(account_number)

                _LOGGER.error(
                    "API returned critical errors with no data: %s",
                    response.get("errors"),
                )
                return None
            _LOGGER.error("API response contains neither data nor errors")
            return None

        except Exception:
            _LOGGER.exception("Error fetching all data")
            return None
