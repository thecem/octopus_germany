"""
Provide the OctopusGermany class for interacting with the Octopus Energy API.

Includes methods for authentication, fetching account details, managing devices,
and retrieving
various data related to electricity usage and tariffs.
"""

import asyncio
import copy
import json
import logging
import time as time_module
from datetime import datetime, timedelta
from typing import TYPE_CHECKING, Any

from python_graphql_client import GraphqlClient

from .api.accounts import AccountApiMixin
from .api.auth import _TOKEN_MANAGERS, TokenManager
from .api.devices import DeviceApiMixin
from .api.meters import MeterApiMixin
from .api.queries import (
    ACCOUNT_CAPABILITIES_QUERY,
    ACCOUNT_DISCOVERY_QUERY,
    ACCOUNT_DISCOVERY_QUERY_LEGACY,
    ALTERNATIVE_METER_READINGS_QUERY_1,
    ALTERNATIVE_METER_READINGS_QUERY_2,
    COMPREHENSIVE_QUERY,
    ELECTRICITY_MALO_READINGS_QUERY,
    INTELLIGENT_DATA_QUERY,
    INTROSPECTION_QUERY,
    PROPERTY_SCHEMA_QUERY,
)
from .api.smart_meter import SMART_METER_ERROR_BACKOFF, SmartMeterFetchError
from .const import LOG_TOKEN_RESPONSES

_LOGGER = logging.getLogger(__name__)

# Backward-compatible module-level re-exports for historical imports.
_EXPORTED_QUERY_CONSTANTS = (
    ACCOUNT_CAPABILITIES_QUERY,
    ACCOUNT_DISCOVERY_QUERY,
    ACCOUNT_DISCOVERY_QUERY_LEGACY,
    ALTERNATIVE_METER_READINGS_QUERY_1,
    ALTERNATIVE_METER_READINGS_QUERY_2,
    COMPREHENSIVE_QUERY,
    ELECTRICITY_MALO_READINGS_QUERY,
    INTELLIGENT_DATA_QUERY,
)

__all__ = [
    "SMART_METER_ERROR_BACKOFF",
    "OctopusGermany",
    "SmartMeterFetchError",
]

GRAPH_QL_ENDPOINT = "https://api.oeg-kraken.energy/v1/graphql/"
ELECTRICITY_LEDGER = "ELECTRICITY_LEDGER"

if TYPE_CHECKING:
    from .models import TariffCapabilities


class OctopusGermany(AccountApiMixin, DeviceApiMixin, MeterApiMixin):
    """API client wrapper combining account, device, and meter mixins."""

    def __init__(self, email: str, password: str) -> None:
        """
        Initialize the OctopusGermany API client.

        Args:
            email: The email address for the Octopus Germany account
            password: The password for the Octopus Germany account

        """
        self._email = email
        self._password = password

        # Use shared token manager for this email to prevent redundant login attempts
        if email not in _TOKEN_MANAGERS:
            _TOKEN_MANAGERS[email] = TokenManager()
            _LOGGER.debug("Created new TokenManager for %s", email)
        else:
            _LOGGER.debug("Reusing existing TokenManager for %s", email)

        self._token_manager = _TOKEN_MANAGERS[email]
        self._capabilities_by_account: dict[str, TariffCapabilities] = {}
        self._smart_meter_retry_until: datetime | None = None
        self._15min_retry_until: datetime | None = None

        # Set up the token manager refresh callback
        self._token_manager.set_refresh_callback(self.login)

        # Start the auto-refresh task immediately
        self._auto_refresh_start_task = asyncio.create_task(
            self._token_manager.start_auto_refresh()
        )

    @property
    def _token(self) -> str | None:
        """Get the current token from the token manager."""
        return self._token_manager.token

    def _get_auth_headers(self) -> dict[str, str]:
        """Get headers with authorization token."""
        return {"Authorization": self._token} if self._token else {}

    def _get_graphql_client(
        self, additional_headers: dict[str, str] | None = None
    ) -> GraphqlClient:
        """Get a GraphQL client with authorization headers."""
        headers = self._get_auth_headers()
        if additional_headers:
            headers.update(additional_headers)
        return GraphqlClient(endpoint=GRAPH_QL_ENDPOINT, headers=headers)

    async def execute_graphql(
        self,
        query: str,
        variables: dict[str, Any] | None = None,
        additional_headers: dict[str, str] | None = None,
    ) -> dict[str, Any]:
        """Execute a GraphQL operation with current auth headers."""
        client = self._get_graphql_client(additional_headers)
        return await client.execute_async(query=query, variables=variables)

    async def login(self) -> bool:
        """Login and obtain a new token."""
        # Use a lock to prevent multiple concurrent login attempts
        async with self._token_manager._refresh_lock:
            # Check if token is still valid after waiting for the lock
            if self._token_manager.is_valid:
                _LOGGER.debug("Token still valid after lock, skipping login")
                return True

            # Clear the current token before attempting login to avoid sending
            # expired token.
            old_token = self._token_manager._token
            self._token_manager._token = None
            _LOGGER.debug("Cleared expired token for fresh login attempt")

            query = """
                mutation krakenTokenAuthentication($email: String!, $password: String!) {
                  obtainKrakenToken(input: { email: $email, password: $password }) {
                    token
                    payload
                  }
                }
            """
            variables = {"email": self._email, "password": self._password}
            # Create client without any authorization headers for login
            client = GraphqlClient(endpoint=GRAPH_QL_ENDPOINT, headers={})

            retries = 5  # Reduced from 10 to 5 retries for simpler logic
            attempt = 0
            delay = 1  # Start with 1 second delay
            max_delay = 30  # Cap the delay at 30 seconds

            while attempt < retries:
                attempt += 1
                try:
                    _LOGGER.debug("Making login attempt %s of %s", attempt, retries)
                    response = await client.execute_async(
                        query=query, variables=variables
                    )

                    # Log token response when LOG_TOKEN_RESPONSES is enabled
                    if LOG_TOKEN_RESPONSES:
                        # Create a safe copy of the response for logging.
                        safe_response = copy.deepcopy(response)
                        # Mask most of the token when token response logging
                        # is enabled.
                        if (
                            "data" in safe_response
                            and "obtainKrakenToken" in safe_response["data"]
                            and "token" in safe_response["data"]["obtainKrakenToken"]
                        ):
                            token = safe_response["data"]["obtainKrakenToken"]["token"]
                            if token and len(token) > 10:
                                # Keep first 5 and last 5 chars, mask the rest
                                mask_length = len(token) - 10
                                masked_token = (
                                    token[:5] + "*" * mask_length + token[-5:]
                                )
                                safe_response["data"]["obtainKrakenToken"]["token"] = (
                                    masked_token
                                )
                        _LOGGER.info(
                            "Token response (partial): %s",
                            json.dumps(safe_response, indent=2),
                        )

                    if "errors" in response:
                        error_code = (
                            response["errors"][0].get("extensions", {}).get("errorCode")
                        )
                        error_message = response["errors"][0].get(
                            "message", "Unknown error"
                        )

                        if error_code == "KT-CT-1199":  # Too many requests
                            _LOGGER.warning(
                                "Rate limit hit. Retrying in %s seconds... "
                                "(attempt %s of %s)",
                                delay,
                                attempt,
                                retries,
                            )
                            await asyncio.sleep(delay)
                            delay = min(
                                delay * 2, max_delay
                            )  # Exponential backoff with max cap
                            continue
                        _LOGGER.error(
                            "Login failed: %s (attempt %s of %s)",
                            error_message,
                            attempt,
                            retries,
                        )
                        # For other types of errors, continue with retries
                        await asyncio.sleep(delay)
                        delay = min(delay * 2, max_delay)
                        continue

                    if "data" in response and "obtainKrakenToken" in response["data"]:
                        token_data = response["data"]["obtainKrakenToken"]
                        token = token_data.get("token")
                        payload = token_data.get("payload")

                        if token:
                            # Pass both token and expiration time to the token manager
                            if (
                                payload
                                and isinstance(payload, dict)
                                and "exp" in payload
                            ):
                                expiration = payload["exp"]
                                self._token_manager.set_token(token, expiration)
                            else:
                                # Fall back to JWT decoding if no payload available
                                self._token_manager.set_token(token)

                            return True
                        _LOGGER.error(
                            "No token in response despite successful request "
                            "(attempt %s of %s)",
                            attempt,
                            retries,
                        )
                    else:
                        _LOGGER.error(
                            "Unexpected API response format at attempt %s: %s",
                            attempt,
                            response,
                        )

                    # If we got here with an invalid response, try again
                    await asyncio.sleep(delay)
                    delay = min(delay * 2, max_delay)

                except Exception:
                    _LOGGER.exception("Error during login attempt %s", attempt)
                    # If this is our last attempt, don't sleep
                    if attempt < retries:
                        await asyncio.sleep(delay)
                        delay = min(delay * 2, max_delay)

            _LOGGER.error("All %s login attempts failed.", retries)
            # Restore the previous token if login failed completely
            if old_token:
                self._token_manager._token = old_token
                _LOGGER.debug("Restored previous token after failed login attempts")
            return False

    async def ensure_token(self) -> bool:
        """Ensure a valid token is available, refreshing if necessary."""
        if not self._token_manager.is_valid:
            _LOGGER.debug("Token invalid or expired, logging in again")
            return await self.login()
        return True

    async def submit_meter_readings(
        self,
        meter_type: str,
        meter_id: str,
        reading_date: str,
        readings: list[dict[str, Any]],
        account_number: str,
    ) -> dict[str, Any] | None:
        """
        Submit meter readings for a gas or electricity meter.

        Args:
            meter_type: Either "electricity" or "gas".
            meter_id: The meter ID to submit readings for.
            reading_date: Reading date in YYYY-MM-DD format.
            readings: One or more register readings.
            account_number: The account that owns the meter.

        Returns:
            The API response payload or None if the submission failed.

        """
        if not await self.ensure_token():
            _LOGGER.error("Failed to ensure valid token for submit_meter_readings")
            return None

        if not account_number:
            _LOGGER.error("Account number is required for submit_meter_readings")
            return None

        normalized_meter_type = meter_type.strip().lower()
        if normalized_meter_type not in ("electricity", "gas"):
            _LOGGER.error("Invalid meter type: %s", meter_type)
            return None

        if not meter_id:
            _LOGGER.error("Meter ID is required for submit_meter_readings")
            return None

        if not reading_date:
            _LOGGER.error("Reading date is required for submit_meter_readings")
            return None

        if not readings:
            _LOGGER.error("At least one reading is required for submit_meter_readings")
            return None

        normalized_readings = []
        for reading in readings:
            register_obis_code = (
                reading.get("registerObisCode")
                or reading.get("register_obis_code")
                or reading.get("register_obiscode")
            )
            value = reading.get("value")

            if register_obis_code in (None, ""):
                _LOGGER.error("Each reading requires a register OBIS code")
                return None

            if value in (None, ""):
                _LOGGER.error("Each reading requires a value")
                return None

            normalized_readings.append(
                {
                    "registerObisCode": str(register_obis_code),
                    "value": str(value),
                }
            )

        mutation_name = (
            "createElectricityMeterReadings"
            if normalized_meter_type == "electricity"
            else "createGasMeterReadings"
        )

        query = f"""
        mutation SubmitMeterReadings($input: ReadingsInput!) {{
          {mutation_name}(input: $input) {{
            readingDate
            numberOfReadingsCreated
          }}
        }}
        """

        variables = {
            "input": {
                "accountNumber": account_number,
                "meterId": meter_id,
                "readingDate": reading_date,
                "readings": normalized_readings,
            }
        }

        client = self._get_graphql_client()

        try:
            _LOGGER.info(
                "Submitting %d %s meter readings for meter %s on %s",
                len(normalized_readings),
                normalized_meter_type,
                meter_id,
                reading_date,
            )

            response = await client.execute_async(query=query, variables=variables)
            _LOGGER.debug("Submit meter readings response: %s", response)

            if "errors" in response:
                error = response.get("errors", [{}])[0]
                error_code = error.get("extensions", {}).get("errorCode")

                if error_code == "KT-CT-1124":
                    _LOGGER.warning(
                        "Token expired during meter reading submission, refreshing..."
                    )
                    self._token_manager.clear()
                    success = await self.login()
                    if success:
                        return await self.submit_meter_readings(
                            meter_type,
                            meter_id,
                            reading_date,
                            readings,
                            account_number,
                        )

                _LOGGER.error("API returned errors: %s", response["errors"])
                return None

            result = response.get("data", {}).get(mutation_name)
            if not result:
                _LOGGER.error("No result returned from %s", mutation_name)
                return None

            return {
                "success": True,
                "meter_type": normalized_meter_type,
                "meter_id": meter_id,
                "reading_date": result.get("readingDate", reading_date),
                "number_of_readings_created": result.get("numberOfReadingsCreated", 0),
            }
        except Exception:
            _LOGGER.exception("Error submitting meter readings")
            return None

    def _format_time_to_hh_mm(self, time_str: str) -> str:
        """
        Format time to HH:MM format required by the API.

        Handles various input formats like "HH:MM:SS", "HH:MM",
        or time selector values from Home Assistant.

        Args:
            time_str: Time string in various formats

        Returns:
            Time formatted as "HH:MM"

        Raises:
            ValueError: If time_str cannot be parsed or contains invalid hours/minutes

        """
        if not time_str:
            msg = "Empty time value provided"
            raise ValueError(msg)

        # Try parsing with different formats
        try:
            # First try to split by colon
            parts = time_str.split(":")
            if len(parts) >= 2:
                # Extract hours and minutes
                try:
                    hours = int(parts[0])
                    minutes = int(parts[1])
                except ValueError as err:
                    msg = (
                        f"Invalid time format: '{time_str}' - "
                        "Hours and minutes must be numbers"
                    )
                    raise ValueError(msg) from err

                # Validate hours and minutes
                if not 0 <= hours <= 23:
                    msg = f"Invalid hour value: {hours}. Hours must be between 0 and 23"
                    raise ValueError(msg)
                if not 0 <= minutes <= 59:
                    msg = (
                        f"Invalid minute value: {minutes}. "
                        "Minutes must be between 0 and 59"
                    )
                    raise ValueError(msg)

                return f"{hours:02d}:{minutes:02d}"

            # Try different common formats
            formats = ["%H:%M:%S", "%H:%M", "%I:%M %p", "%I:%M:%S %p"]

            for fmt in formats:
                try:
                    parsed = time_module.strptime(time_str, fmt)
                except ValueError:
                    continue
                else:
                    return f"{parsed.tm_hour:02d}:{parsed.tm_min:02d}"

            # If we got here, none of the formats worked
            msg = (
                f"Could not parse time: '{time_str}'. "
                "Please use HH:MM format (e.g. '05:00')"
            )
            raise ValueError(msg)

        except Exception as e:
            if isinstance(e, ValueError):
                # Pass through ValueError with informative messages
                raise
            # Wrap other exceptions
            msg = f"Error processing time '{time_str}': {e!s}"
            raise ValueError(msg) from e

    async def test_historical_smart_meter_data_range(
        self, account_number: str, property_id: str
    ) -> list[dict[str, Any]] | None:
        """
        Test how far back smart meter data is available.

        This function tests various historical dates to understand the data
        availability range.
        """
        if not await self.ensure_token():
            _LOGGER.error("Failed to ensure valid token for historical data range test")
            return None

        today = datetime.now().astimezone().date()

        # Test various time periods
        test_periods = [
            (today - timedelta(days=1), "1_day_ago"),
            (today - timedelta(days=2), "2_days_ago"),
            (today - timedelta(days=3), "3_days_ago"),
            (today - timedelta(days=7), "1_week_ago"),
            (today - timedelta(days=14), "2_weeks_ago"),
            (today - timedelta(days=30), "1_month_ago"),
            (today - timedelta(days=60), "2_months_ago"),
            (today - timedelta(days=90), "3_months_ago"),
            (today - timedelta(days=180), "6_months_ago"),
            (today - timedelta(days=365), "1_year_ago"),
        ]

        _LOGGER.info(
            "Testing historical smart meter data range for property %s", property_id
        )

        available_dates = []

        for test_date, label in test_periods:
            date_str = test_date.isoformat()

            try:
                _LOGGER.debug(
                    "Testing smart meter data availability for %s (%s)", label, date_str
                )

                readings = await self.fetch_electricity_smart_meter_readings(
                    account_number, property_id, date_str
                )

                if readings and len(readings) > 0:
                    available_dates.append(
                        {
                            "date": date_str,
                            "label": label,
                            "readings_count": len(readings),
                            "first_reading": readings[0] if readings else None,
                            "last_reading": readings[-1] if readings else None,
                        }
                    )
                    _LOGGER.info(
                        "✅ Smart meter data available for %s (%s): %d readings",
                        label,
                        date_str,
                        len(readings),
                    )
                else:
                    _LOGGER.debug(
                        "❌ No smart meter data for %s (%s)",
                        label,
                        date_str,
                    )

            except Exception as e:
                _LOGGER.warning("Error testing date %s (%s): %s", label, date_str, e)

        if available_dates:
            _LOGGER.info(
                "📊 Smart meter data availability summary: "
                "Found data for %d out of %d tested dates",
                len(available_dates),
                len(test_periods),
            )
            _LOGGER.info(
                "📅 Available dates: %s",
                [f"{item['label']} ({item['date']})" for item in available_dates],
            )

            # Show the range
            oldest_date = available_dates[-1] if available_dates else None
            newest_date = available_dates[0] if available_dates else None

            if oldest_date and newest_date:
                _LOGGER.info(
                    "📈 Data range: From %s (%s) to %s (%s)",
                    oldest_date["date"],
                    oldest_date["label"],
                    newest_date["date"],
                    newest_date["label"],
                )
        else:
            _LOGGER.warning(
                "⚠️ No historical smart meter data found for any tested date"
            )

        return available_dates

    async def explore_property_schema(
        self, account_number: str, property_id: str
    ) -> dict[str, Any] | None:
        """
        Explore the property schema to understand available fields and data structures.

        This helps debug what data is actually available for smart meter readings.
        """
        if not await self.ensure_token():
            _LOGGER.error(
                "Failed to ensure valid token for property schema exploration"
            )
            return None

        variables = {
            "accountNumber": account_number,
            "propertyId": property_id,
        }

        client = self._get_graphql_client()

        try:
            _LOGGER.info(
                "Exploring property schema for account %s, property %s",
                account_number,
                property_id,
            )
            response = await client.execute_async(
                query=PROPERTY_SCHEMA_QUERY, variables=variables
            )

            _LOGGER.info("Property schema response: %s", json.dumps(response, indent=2))

            return response

        except Exception:
            _LOGGER.exception("Error exploring property schema")
            return None

    async def explore_graphql_schema(
        self,
    ) -> list[dict[str, Any]] | dict[str, Any] | None:
        """
        Explore the GraphQL schema to understand available types and fields.

        This helps understand what data structures are available in the API.
        """
        if not await self.ensure_token():
            _LOGGER.error("Failed to ensure valid token for schema exploration")
            return None

        client = self._get_graphql_client()

        try:
            _LOGGER.info("Exploring GraphQL schema...")
            response = await client.execute_async(query=INTROSPECTION_QUERY)

            # Filter for measurement-related types
            if "data" in response and "__schema" in response["data"]:
                schema = response["data"]["__schema"]
                measurement_types = []

                for type_def in schema.get("types", []):
                    type_name = type_def.get("name", "")
                    if any(
                        keyword in type_name.lower()
                        for keyword in [
                            "measurement",
                            "meter",
                            "reading",
                            "interval",
                            "smart",
                        ]
                    ):
                        measurement_types.append(
                            {
                                "name": type_name,
                                "kind": type_def.get("kind"),
                                "description": type_def.get("description"),
                                "fields": [
                                    {
                                        "name": field.get("name"),
                                        "description": field.get("description"),
                                        "type": field.get("type", {}).get("name"),
                                    }
                                    for field in type_def.get("fields", [])
                                ]
                                if type_def.get("fields")
                                else [],
                            }
                        )

                _LOGGER.info(
                    "Found %d measurement-related types: %s",
                    len(measurement_types),
                    json.dumps(measurement_types, indent=2),
                )

                return measurement_types

            return response

        except Exception:
            _LOGGER.exception("Error exploring GraphQL schema")
            return None
