"""Provide the OctopusGermany class for interacting with the Octopus Energy API.

Includes methods for authentication, fetching account details, managing devices, and retrieving
various data related to electricity usage and tariffs.
"""

import logging
import json
from datetime import datetime, timedelta
from typing import Any, Dict, List, Optional, Tuple, Union, cast
import asyncio
import jwt
from homeassistant.exceptions import ConfigEntryNotReady
from python_graphql_client import GraphqlClient
from .const import TOKEN_AUTO_REFRESH_INTERVAL, TOKEN_REFRESH_MARGIN

_LOGGER = logging.getLogger(__name__)

GRAPH_QL_ENDPOINT = "https://api.oeg-kraken.energy/v1/graphql/"
ELECTRICITY_LEDGER = "ELECTRICITY_LEDGER"

# Global token manager to prevent multiple instances from making redundant token requests
_GLOBAL_TOKEN_MANAGER = None

# Comprehensive query that gets all data in one go
COMPREHENSIVE_QUERY = """
query ComprehensiveDataQuery($accountNumber: String!) {
  account(accountNumber: $accountNumber) {
    id
    ledgers {
      balance
      ledgerType
    }
    allProperties {
      id
      electricityMalos {
        agreements {
          product {
            code
            description
            fullName
            isTimeOfUse
          }
          unitRateGrossRateInformation {
            grossRate
          }
          unitRateInformation {
            ... on SimpleProductUnitRateInformation {
              __typename
              grossRateInformation {
                date
                grossRate
                rateValidToDate
                vatRate
              }
              latestGrossUnitRateCentsPerKwh
              netUnitRateCentsPerKwh
            }
            ... on TimeOfUseProductUnitRateInformation {
              __typename
              rates {
                grossRateInformation {
                  date
                  grossRate
                  rateValidToDate
                  vatRate
                }
                latestGrossUnitRateCentsPerKwh
                netUnitRateCentsPerKwh
                timeslotActivationRules {
                  activeFromTime
                  activeToTime
                }
                timeslotName
              }
            }
          }
          unitRateForecast {
            validFrom
            validTo
            unitRateInformation {
              __typename
              ... on SimpleProductUnitRateInformation {
                latestGrossUnitRateCentsPerKwh
              }
              ... on TimeOfUseProductUnitRateInformation {
                rates {
                  latestGrossUnitRateCentsPerKwh
                }
              }
            }
          }
          validFrom
          validTo
        }
        maloNumber
        meloNumber
        meter {
          id
          meterType
          number
          shouldReceiveSmartMeterData
          submitMeterReadingUrl
        }
        referenceConsumption
      }
      gasMalos {
        agreements {
          product {
            code
            description
            fullName
            isTimeOfUse
          }
          unitRateGrossRateInformation {
            grossRate
          }
          unitRateInformation {
            ... on SimpleProductUnitRateInformation {
              __typename
              grossRateInformation {
                date
                grossRate
                rateValidToDate
                vatRate
              }
              latestGrossUnitRateCentsPerKwh
              netUnitRateCentsPerKwh
            }
            ... on TimeOfUseProductUnitRateInformation {
              __typename
              rates {
                grossRateInformation {
                  date
                  grossRate
                  rateValidToDate
                  vatRate
                }
                latestGrossUnitRateCentsPerKwh
                netUnitRateCentsPerKwh
                timeslotActivationRules {
                  activeFromTime
                  activeToTime
                }
                timeslotName
              }
            }
          }
          validFrom
          validTo
        }
        maloNumber
        meloNumber
        meter {
          id
          meterType
          number
          shouldReceiveSmartMeterData
          submitMeterReadingUrl
        }
        referenceConsumption
      }
    }
  }
  completedDispatches(accountNumber: $accountNumber) {
    delta
    deltaKwh
    end
    endDt
    meta {
      location
      source
    }
    start
    startDt
  }
  devices(accountNumber: $accountNumber) {
    status {
      current
      currentState
      isSuspended
    }
    provider
    preferences {
      mode
      schedules {
        dayOfWeek
        max
        min
        time
      }
      targetType
      unit
      gridExport
    }
    preferenceSetting {
      deviceType
      id
      mode
      scheduleSettings {
        id
        max
        min
        step
        timeFrom
        timeStep
        timeTo
      }
      unit
    }
    name
    integrationDeviceId
    id
    deviceType
    alerts {
      message
      publishedAt
    }
    ... on SmartFlexVehicle {
      id
      name
      status {
        current
        currentState
        isSuspended
      }
      vehicleVariant {
        model
        batterySize
      }
    }
  }
}
"""

# Query to get latest gas meter readings
GAS_METER_READINGS_QUERY = """
query GasMeterReadings($accountNumber: String!, $meterId: ID!) {
  gasMeterReadings(accountNumber: $accountNumber, meterId: $meterId, first: 1) {
    edges {
      node {
        value
        readAt
        registerObisCode
        typeOfRead
        origin
        meterId
      }
    }
  }
}
"""

# Query to get latest electricity meter readings
ELECTRICITY_METER_READINGS_QUERY = """
query ElectricityMeterReadings($accountNumber: String!, $meterId: ID!) {
  electricityMeterReadings(accountNumber: $accountNumber, meterId: $meterId, first: 1) {
    edges {
      node {
        value
        readAt
        registerObisCode
        typeOfRead
        origin
        meterId
        registerType
      }
    }
  }
}
"""

# Query to get vehicle device details with preference settings
VEHICLE_DETAILS_QUERY = """
query Vehicle($accountNumber: String = "") {
  devices(accountNumber: $accountNumber) {
    deviceType
    id
    integrationDeviceId
    name
    preferenceSetting {
      deviceType
      id
      mode
      scheduleSettings {
        id
        max
        min
        step
        timeFrom
        timeStep
        timeTo
      }
      unit
    }
    preferences {
      gridExport
      mode
      targetType
      unit
    }
  }
}
"""

# Simple account discovery query
ACCOUNT_DISCOVERY_QUERY = """
query {
  viewer {
    accounts {
      number
      ledgers {
        balance
        ledgerType
      }
    }
  }
}
"""


class TokenManager:
    """Centralized token management for Octopus Germany API."""

    def __init__(self):
        """Initialize the token manager."""
        self._token = None
        self._expiry = None
        self._refresh_lock = asyncio.Lock()
        self._refresh_callback = None
        self._refresh_task = None

    @property
    def token(self):
        """Get the current token."""
        return self._token

    def set_refresh_callback(self, callback):
        """Set a callback function to be called when token needs refreshing."""
        self._refresh_callback = callback

    async def start_auto_refresh(self):
        """Start the automatic token refresh process."""
        if self._refresh_task is not None:
            self._refresh_task.cancel()

        # Create a new task for token refresh
        self._refresh_task = asyncio.create_task(self._auto_refresh_token())
        _LOGGER.debug("Started automatic token refresh task")

    async def _auto_refresh_token(self):
        """Automatically refresh the token every TOKEN_AUTO_REFRESH_INTERVAL seconds."""
        try:
            while True:
                # Wait for the configured refresh interval
                await asyncio.sleep(TOKEN_AUTO_REFRESH_INTERVAL)

                _LOGGER.info("Performing scheduled token refresh")

                if self._refresh_callback is not None:
                    # Force token refresh by temporarily invalidating the token expiry
                    self._expiry = 0  # Set to expired
                    await self._refresh_callback()
                    _LOGGER.debug("Scheduled token refresh completed")
                else:
                    _LOGGER.warning(
                        "No refresh callback set, cannot auto-refresh token"
                    )
        except asyncio.CancelledError:
            _LOGGER.debug("Token auto-refresh task cancelled")
        except Exception as e:
            _LOGGER.error("Error in token auto-refresh task: %s", e)

    @property
    def is_valid(self):
        """Check if the token is valid."""
        # Fast path: If there is no token, it's definitely invalid
        if not self._token or not self._expiry:
            return False

        now = datetime.utcnow().timestamp()

        # Token is valid if it has at least TOKEN_REFRESH_MARGIN seconds left before expiry
        valid = now < (self._expiry - TOKEN_REFRESH_MARGIN)

        if not valid:
            remaining_time = self._expiry - now if self._expiry else 0
            _LOGGER.debug(
                "Token validity check: INVALID (expiry in %s seconds)",
                int(remaining_time),
            )

        return valid

    def set_token(self, token, expiry=None):
        """Set a new token and extract its expiry time."""
        self._token = token

        if expiry:
            # Use expiry directly if provided
            self._expiry = expiry
            now = datetime.utcnow().timestamp()
            token_lifetime = self._expiry - now if self._expiry else 0
            _LOGGER.debug(
                "Token set with explicit expiry - valid for %s seconds",
                int(token_lifetime),
            )
        else:
            # Decode token to get expiry time
            try:
                decoded = jwt.decode(token, options={"verify_signature": False})
                self._expiry = decoded.get("exp")
                now = datetime.utcnow().timestamp()
                token_lifetime = self._expiry - now if self._expiry else 0
                _LOGGER.debug(
                    "Token set with decoded expiry - valid for %s seconds",
                    int(token_lifetime),
                )
            except Exception as e:
                # Fallback: If token decoding fails, set expiry to TOKEN_AUTO_REFRESH_INTERVAL from now
                now = datetime.utcnow().timestamp()
                self._expiry = now + TOKEN_AUTO_REFRESH_INTERVAL
                _LOGGER.warning(
                    "Failed to decode token expiry: %s. Setting fallback expiry to %s minutes",
                    e,
                    TOKEN_AUTO_REFRESH_INTERVAL // 60,
                )

    def clear(self):
        """Clear token and expiry."""
        self._token = None
        self._expiry = None


class OctopusGermany:
    def __init__(self, email: str, password: str):
        """Initialize the OctopusGermany API client.

        Args:
            email: The email address for the Octopus Germany account
            password: The password for the Octopus Germany account
        """
        self._email = email
        self._password = password

        # Use global token manager to prevent redundant login attempts across instances
        global _GLOBAL_TOKEN_MANAGER
        if _GLOBAL_TOKEN_MANAGER is None:
            _GLOBAL_TOKEN_MANAGER = TokenManager()
        self._token_manager = _GLOBAL_TOKEN_MANAGER

        # Set up the token manager refresh callback
        self._token_manager.set_refresh_callback(self.login)

        # Start the auto-refresh task immediately
        asyncio.create_task(self._token_manager.start_auto_refresh())

    @property
    def _token(self):
        """Get the current token from the token manager."""
        return self._token_manager.token

    def _get_auth_headers(self):
        """Get headers with authorization token."""
        return {"Authorization": self._token} if self._token else {}

    def _get_graphql_client(self, additional_headers=None):
        """Get a GraphQL client with authorization headers."""
        headers = self._get_auth_headers()
        if additional_headers:
            headers.update(additional_headers)
        return GraphqlClient(endpoint=GRAPH_QL_ENDPOINT, headers=headers)

    async def login(self) -> bool:
        """Login and obtain a new token."""
        # Import constants for logging options
        from .const import LOG_TOKEN_RESPONSES

        # Use a lock to prevent multiple concurrent login attempts
        async with self._token_manager._refresh_lock:
            # Check if token is still valid after waiting for the lock
            if self._token_manager.is_valid:
                _LOGGER.debug("Token still valid after lock, skipping login")
                return True

            query = """
                mutation krakenTokenAuthentication($email: String!, $password: String!) {
                  obtainKrakenToken(input: { email: $email, password: $password }) {
                    token
                    payload
                  }
                }
            """
            variables = {"email": self._email, "password": self._password}
            client = self._get_graphql_client()

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
                        # Create a safe copy of the response for logging
                        import copy

                        safe_response = copy.deepcopy(response)
                        # Check if we have a token in the response and mask most of it for logging
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
                                "Rate limit hit. Retrying in %s seconds... (attempt %s of %s)",
                                delay,
                                attempt,
                                retries,
                            )
                            await asyncio.sleep(delay)
                            delay = min(
                                delay * 2, max_delay
                            )  # Exponential backoff with max cap
                            continue
                        else:
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
                        else:
                            _LOGGER.error(
                                "No token in response despite successful request (attempt %s of %s)",
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

                except Exception as e:
                    _LOGGER.error("Error during login attempt %s: %s", attempt, e)
                    await asyncio.sleep(delay)
                    delay = min(delay * 2, max_delay)

            _LOGGER.error("All %s login attempts failed.", retries)
            return False

    async def ensure_token(self):
        """Ensure a valid token is available, refreshing if necessary."""
        if not self._token_manager.is_valid:
            _LOGGER.debug("Token invalid or expired, logging in again")
            return await self.login()
        return True

    # Consolidated query to get both accounts list and initial data in one API call
    async def fetch_accounts_with_initial_data(self):
        """Fetch accounts and initial data in a single API call."""
        await self.ensure_token()

        client = self._get_graphql_client()

        try:
            response = await client.execute_async(query=ACCOUNT_DISCOVERY_QUERY)
            _LOGGER.debug("Fetch accounts with initial data response: %s", response)

            if "data" in response and "viewer" in response["data"]:
                accounts = response["data"]["viewer"]["accounts"]
                if not accounts:
                    _LOGGER.error("No accounts found")
                    return None

                # Return the accounts data
                return accounts
            else:
                _LOGGER.error("Unexpected API response structure: %s", response)
                return None
        except Exception as e:
            _LOGGER.error("Error fetching accounts with initial data: %s", e)
            return None

    # Legacy methods maintained for backward compatibility
    async def accounts(self):
        """Fetch account numbers."""
        accounts = await self.fetch_accounts_with_initial_data()
        if not accounts:
            _LOGGER.error("Failed to fetch accounts")
            raise ConfigEntryNotReady("Failed to fetch accounts")

        return [account["number"] for account in accounts]

    async def fetch_accounts(self):
        """Fetch accounts data."""
        return await self.fetch_accounts_with_initial_data()

    # Comprehensive data fetch in a single query
    async def fetch_all_data(self, account_number: str):
        """Fetch all data for an account including devices, dispatches and account details.

        This comprehensive query consolidates multiple separate queries into one
        to minimize API calls and improve performance.
        """
        if not await self.ensure_token():
            _LOGGER.error("Failed to ensure valid token for fetch_all_data")
            return None

        variables = {"accountNumber": account_number}
        client = self._get_graphql_client()

        try:
            _LOGGER.debug(
                "Making API request to fetch_all_data for account %s",
                account_number,
            )
            response = await client.execute_async(
                query=COMPREHENSIVE_QUERY, variables=variables
            )

            # Log the full API response only when LOG_API_RESPONSES is enabled
            from .const import LOG_API_RESPONSES

            if LOG_API_RESPONSES:
                _LOGGER.info("API Response: %s", json.dumps(response, indent=2))
            else:
                _LOGGER.debug(
                    "API request completed. Set LOG_API_RESPONSES=True for full response logging"
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

            # Now check for partial data availability - we'll continue even if there are some errors
            if "data" in response:
                data = response["data"]

                # Process available data fields
                if "account" in data:
                    result["account"] = data["account"]

                    # Extract product information from the account agreements if available
                    # This helps maintain compatibility with code expecting the products field
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
                                            for agreement in malo["agreements"]:
                                                if "product" in agreement:
                                                    products.append(
                                                        agreement["product"]
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

                if "completedDispatches" in data:
                    result["completedDispatches"] = (
                        data["completedDispatches"]
                        if data["completedDispatches"] is not None
                        else []
                    )

                # Fetch flex planned dispatches for all devices with the new API
                result["plannedDispatches"] = []
                if result["devices"]:
                    _LOGGER.debug("Fetching flex planned dispatches for %d devices", len(result["devices"]))
                    for device in result["devices"]:
                        device_id = device.get("id")
                        device_name = device.get("name", "Unknown")
                        if device_id:
                            try:
                                flex_dispatches = await self.fetch_flex_planned_dispatches(device_id)
                                if flex_dispatches:
                                    # Transform the new API format to match the old format for backward compatibility
                                    for dispatch in flex_dispatches:
                                        # Map new fields to old field names where possible
                                        transformed_dispatch = {
                                            "start": dispatch.get("start"),
                                            "startDt": dispatch.get("start"),  # Same as start
                                            "end": dispatch.get("end"),
                                            "endDt": dispatch.get("end"),  # Same as end
                                            "deltaKwh": dispatch.get("energyAddedKwh"),
                                            "delta": dispatch.get("energyAddedKwh"),  # Same as deltaKwh
                                            "type": dispatch.get("type", "UNKNOWN"),  # Add type as top-level attribute
                                            "meta": {
                                                "source": "flex_api",
                                                "type": dispatch.get("type", "UNKNOWN"),
                                                "deviceId": device_id
                                            }
                                        }
                                        result["plannedDispatches"].append(transformed_dispatch)
                                    _LOGGER.debug(
                                        "Added %d flex planned dispatches from device %s (%s)",
                                        len(flex_dispatches),
                                        device_id,
                                        device_name
                                    )
                            except Exception as e:
                                _LOGGER.warning(
                                    "Failed to fetch flex planned dispatches for device %s: %s",
                                    device_id,
                                    e
                                )
                else:
                    _LOGGER.debug("No devices found, skipping flex planned dispatches fetch")

                # Only log errors but don't fail the whole request if we got at least account data
                if "errors" in response and result["account"]:
                    # Filter only the errors that are about missing devices or dispatches
                    non_critical_errors = [
                        error
                        for error in response["errors"]
                        if (
                            error.get("path", [])
                            and error.get("path")[0]
                            in ["completedDispatches", "devices"]
                            and error.get("extensions", {}).get("errorCode")
                            == "KT-CT-4301"
                        )
                    ]

                    # Handle other errors that might affect the account data
                    other_errors = [
                        error
                        for error in response["errors"]
                        if error not in non_critical_errors
                    ]

                    if non_critical_errors:
                        _LOGGER.warning(
                            "API returned non-critical errors (expected for accounts without devices/dispatches): %s",
                            non_critical_errors,
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

                return result
            elif "errors" in response:
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
            else:
                _LOGGER.error("API response contains neither data nor errors")
                return None

        except Exception as e:
            _LOGGER.error("Error fetching all data: %s", e)
            return None

    async def change_device_suspension(self, device_id: str, action: str):
        """Change device suspension state."""
        if not await self.ensure_token():
            _LOGGER.error("Failed to ensure valid token for change_device_suspension")
            return None

        query = """
            mutation ChangeDeviceSuspension($deviceId: ID = "", $action: SmartControlAction!) {
              updateDeviceSmartControl(input: {deviceId: $deviceId, action: $action}) {
                id
              }
            }
        """
        variables = {"deviceId": device_id, "action": action}
        _LOGGER.debug(
            "Executing change_device_suspension: device_id=%s, action=%s",
            device_id,
            action,
        )
        client = self._get_graphql_client()
        try:
            response = await client.execute_async(query=query, variables=variables)
            _LOGGER.debug("Change device suspension response: %s", response)

            if "errors" in response:
                error = response.get("errors", [{}])[0]
                error_code = error.get("extensions", {}).get("errorCode")

                # Check if token expired error
                if error_code == "KT-CT-1124":  # JWT expired
                    _LOGGER.warning(
                        "Token expired during device suspension change, refreshing..."
                    )
                    self._token_manager.clear()
                    success = await self.login()
                    if success:
                        # Retry with new token
                        return await self.change_device_suspension(device_id, action)

                _LOGGER.error("API returned errors: %s", response["errors"])
                return None

            return (
                response.get("data", {}).get("updateDeviceSmartControl", {}).get("id")
            )
        except Exception as e:
            _LOGGER.error("Error changing device suspension: %s", e)
            return None

    async def set_device_preferences(
        self,
        device_id: str,
        target_percentage: int,
        target_time: str,
    ) -> bool:
        """Set device charging preferences using the new setDevicePreferences API.

        Args:
            device_id: The device ID to set preferences for
            target_percentage: Target state of charge (20-100%)
            target_time: Time in HH:MM format (04:00-17:00)

        Returns:
            True if successful, False otherwise
        """
        if not await self.ensure_token():
            _LOGGER.error(
                "Failed to ensure valid token for set_device_preferences"
            )
            return False

        # Validate percentage range (20-100% in 5% steps)
        if not 20 <= target_percentage <= 100:
            _LOGGER.error(
                "Invalid target percentage: %s. Must be between 20 and 100.",
                target_percentage,
            )
            return False

        if target_percentage % 5 != 0:
            _LOGGER.error(
                "Invalid target percentage: %s. Must be in 5%% steps.",
                target_percentage,
            )
            return False

        # Format and validate the target time
        try:
            formatted_time = self._format_time_to_hh_mm(target_time)

            # Validate time range (04:00-17:00)
            hour = int(formatted_time.split(":")[0])
            if not 4 <= hour <= 17:
                _LOGGER.error(
                    "Invalid target time: %s. Must be between 04:00 and 17:00.",
                    formatted_time,
                )
                return False

            _LOGGER.debug(
                "Formatted time for API: %s",
                formatted_time,
            )
        except ValueError as e:
            _LOGGER.error("Time format validation error: %s", e)
            return False

        # Use the new setDevicePreferences mutation - based on the exact working example
        # No variables, everything inline as shown in the working example
        query = f"""
        mutation setDevicePreferences {{
          setDevicePreferences(
            input: {{
              deviceId: "{device_id}",
              mode: CHARGE,
              unit: PERCENTAGE,
              schedules: [
                {{ dayOfWeek: MONDAY, time: "{formatted_time}", max: {target_percentage} }},
                {{ dayOfWeek: TUESDAY, time: "{formatted_time}", max: {target_percentage} }},
                {{ dayOfWeek: WEDNESDAY, time: "{formatted_time}", max: {target_percentage} }},
                {{ dayOfWeek: THURSDAY, time: "{formatted_time}", max: {target_percentage} }},
                {{ dayOfWeek: FRIDAY, time: "{formatted_time}", max: {target_percentage} }},
                {{ dayOfWeek: SATURDAY, time: "{formatted_time}", max: {target_percentage} }},
                {{ dayOfWeek: SUNDAY, time: "{formatted_time}", max: {target_percentage} }}
              ]
            }}
          ) {{
            id
          }}
        }}
        """

        variables = {}

        client = self._get_graphql_client()

        _LOGGER.debug(
            "Making set_device_preferences API request with device_id: %s, target: %s%%, time: %s",
            device_id,
            target_percentage,
            formatted_time,
        )

        try:
            response = await client.execute_async(query=query, variables=variables)
            _LOGGER.debug("Set device preferences response: %s", response)

            if "errors" in response:
                error = response.get("errors", [{}])[0]
                error_code = error.get("extensions", {}).get("errorCode")
                error_message = error.get("message", "Unknown error")

                _LOGGER.error(
                    "API error setting device preferences: %s (code: %s)",
                    error_message,
                    error_code,
                )

                # Check if token expired error
                if error_code == "KT-CT-1124":  # JWT expired
                    _LOGGER.warning(
                        "Token expired during setting device preferences, refreshing..."
                    )
                    self._token_manager.clear()
                    success = await self.login()
                    if success:
                        # Retry with new token
                        return await self.set_device_preferences(
                            device_id,
                            target_percentage,
                            target_time,
                        )

                return False

            return True
        except Exception as e:
            _LOGGER.error("Error setting device preferences: %s", e)
            return False

    async def get_vehicle_devices(self, account_number: str):
        """Get vehicle device details with preference settings.

        Args:
            account_number: The account number

        Returns:
            List of vehicle devices with their settings or None if error
        """
        if not await self.ensure_token():
            _LOGGER.error("Failed to ensure valid token for get_vehicle_devices")
            return None

        variables = {"accountNumber": account_number}
        client = self._get_graphql_client()

        try:
            _LOGGER.debug(
                "Fetching vehicle devices for account %s",
                account_number,
            )
            response = await client.execute_async(
                query=VEHICLE_DETAILS_QUERY, variables=variables
            )

            if response is None:
                _LOGGER.error("API returned None response for vehicle devices")
                return None

            if "errors" in response:
                error = response.get("errors", [{}])[0]
                error_code = error.get("extensions", {}).get("errorCode")

                # Check if token expired error
                if error_code == "KT-CT-1124":  # JWT expired
                    _LOGGER.warning("Token expired, refreshing...")
                    self._token_manager.clear()
                    success = await self.login()
                    if success:
                        # Retry with new token
                        return await self.get_vehicle_devices(account_number)

                _LOGGER.error(
                    "GraphQL errors in vehicle devices response: %s",
                    response["errors"],
                )
                return None

            if "data" in response and "devices" in response["data"]:
                devices = response["data"]["devices"]

                # Filter for electric vehicle devices
                vehicle_devices = [
                    device for device in devices
                    if device.get("deviceType") == "ELECTRIC_VEHICLES"
                ]

                _LOGGER.debug(
                    "Found %d vehicle devices",
                    len(vehicle_devices),
                )
                return vehicle_devices
            else:
                _LOGGER.error("Invalid response structure for vehicle devices")
                return None

        except Exception as e:
            _LOGGER.error("Error fetching vehicle devices: %s", e)
            return None

    async def fetch_flex_planned_dispatches(self, device_id: str):
        """Fetch planned dispatches for a specific device using the new flexPlannedDispatches API.

        Args:
            device_id: The device ID to fetch planned dispatches for

        Returns:
            List of planned dispatches for the device or None if error
        """
        if not await self.ensure_token():
            _LOGGER.error("Failed to ensure valid token for fetch_flex_planned_dispatches")
            return None

        # Use inline query with device ID as shown in the working example
        query = f"""
        query flexPlannedDispatches {{
          flexPlannedDispatches(deviceId: "{device_id}") {{
            end
            energyAddedKwh
            start
            type
          }}
        }}
        """

        client = self._get_graphql_client()

        try:
            _LOGGER.debug(
                "Fetching flex planned dispatches for device %s",
                device_id,
            )
            response = await client.execute_async(query=query, variables={})

            if response is None:
                _LOGGER.error("API returned None response for flex planned dispatches")
                return None

            if "errors" in response:
                error = response.get("errors", [{}])[0]
                error_code = error.get("extensions", {}).get("errorCode")
                error_message = error.get("message", "Unknown error")

                # Check if token expired error
                if error_code == "KT-CT-1124":  # JWT expired
                    _LOGGER.warning("Token expired, refreshing...")
                    self._token_manager.clear()
                    success = await self.login()
                    if success:
                        # Retry with new token
                        return await self.fetch_flex_planned_dispatches(device_id)

                # Log but don't fail for non-critical errors (device might not support flex dispatches)
                if error_code == "KT-CT-4301":  # Resource not found
                    _LOGGER.debug(
                        "Device %s does not support flex planned dispatches: %s",
                        device_id,
                        error_message,
                    )
                    return []
                else:
                    _LOGGER.error(
                        "GraphQL errors in flex planned dispatches response: %s",
                        response["errors"],
                    )
                    return None

            if "data" in response and "flexPlannedDispatches" in response["data"]:
                dispatches = response["data"]["flexPlannedDispatches"]
                if dispatches is None:
                    dispatches = []

                _LOGGER.debug(
                    "Found %d flex planned dispatches for device %s",
                    len(dispatches),
                    device_id,
                )
                return dispatches
            else:
                _LOGGER.error("Invalid response structure for flex planned dispatches")
                return None

        except Exception as e:
            _LOGGER.error("Error fetching flex planned dispatches: %s", e)
            return None

    def _format_time_to_hh_mm(self, time_str: str) -> str:
        """Format time to HH:MM format required by the API.

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
            raise ValueError("Empty time value provided")

        # Try parsing with different formats
        try:
            # First try to split by colon
            parts = time_str.split(":")
            if len(parts) >= 2:
                # Extract hours and minutes
                try:
                    hours = int(parts[0])
                    minutes = int(parts[1])
                except ValueError:
                    raise ValueError(
                        f"Invalid time format: '{time_str}' - Hours and minutes must be numbers"
                    )

                # Validate hours and minutes
                if not 0 <= hours <= 23:
                    raise ValueError(
                        f"Invalid hour value: {hours}. Hours must be between 0 and 23"
                    )
                if not 0 <= minutes <= 59:
                    raise ValueError(
                        f"Invalid minute value: {minutes}. Minutes must be between 0 and 59"
                    )

                return f"{hours:02d}:{minutes:02d}"

            else:
                # For other formats, try using datetime
                from datetime import datetime

                # Try different common formats
                formats = ["%H:%M:%S", "%H:%M", "%I:%M %p", "%I:%M:%S %p"]

                for fmt in formats:
                    try:
                        dt = datetime.strptime(time_str, fmt)
                        return f"{dt.hour:02d}:{dt.minute:02d}"
                    except ValueError:
                        continue

                # If we got here, none of the formats worked
                raise ValueError(
                    f"Could not parse time: '{time_str}'. Please use HH:MM format (e.g. '05:00')"
                )

        except Exception as e:
            if isinstance(e, ValueError):
                # Pass through ValueError with informative messages
                raise
            else:
                # Wrap other exceptions
                raise ValueError(f"Error processing time '{time_str}': {str(e)}")

    # Remove redundant _fetch_account_and_devices method since fetch_all_data does the same thing
    # The method below is kept only for backward compatibility
    async def _fetch_account_and_devices(self, account_number: str):
        """Fetch account and devices data using the comprehensive query.

        This method is kept for backward compatibility but now uses the same
        comprehensive query as fetch_all_data.
        """
        _LOGGER.info(
            "Using _fetch_account_and_devices (deprecated - using comprehensive query)"
        )
        all_data = await self.fetch_all_data(account_number)

        if not all_data:
            return {
                "account": {},
                "devices": [],
            }

        # Return just the parts needed by the legacy method
        return {
            "account": all_data["account"],
            "devices": all_data["devices"],
        }

    async def fetch_gas_meter_reading(self, account_number: str, meter_id: str):
        """Fetch the latest gas meter reading for a specific meter.

        Args:
            account_number: The account number
            meter_id: The gas meter ID

        Returns:
            Dict containing the latest reading data or None if error
        """
        if not await self.ensure_token():
            _LOGGER.error("Failed to ensure valid token for fetch_gas_meter_reading")
            return None

        variables = {"accountNumber": account_number, "meterId": meter_id}
        client = self._get_graphql_client()

        try:
            _LOGGER.debug(
                "Fetching gas meter reading for account %s, meter %s",
                account_number,
                meter_id,
            )
            response = await client.execute_async(
                query=GAS_METER_READINGS_QUERY, variables=variables
            )

            if response is None:
                _LOGGER.error("API returned None response for gas meter reading")
                return None

            if "errors" in response:
                _LOGGER.error(
                    "GraphQL errors in gas meter reading response: %s",
                    response["errors"],
                )
                return None

            if "data" in response and "gasMeterReadings" in response["data"]:
                readings_data = response["data"]["gasMeterReadings"]

                if (
                    readings_data
                    and "edges" in readings_data
                    and readings_data["edges"]
                ):
                    # Get the first (latest) reading
                    latest_reading = readings_data["edges"][0]["node"]
                    _LOGGER.debug(
                        "Got gas meter reading: %s at %s (type: %s, origin: %s)",
                        latest_reading.get("value"),
                        latest_reading.get("readAt"),
                        latest_reading.get("typeOfRead"),
                        latest_reading.get("origin"),
                    )
                    return latest_reading
                else:
                    _LOGGER.warning(
                        "No gas meter readings found for meter %s", meter_id
                    )
                    return None
            else:
                _LOGGER.error("Invalid response structure for gas meter reading")
                return None

        except Exception as e:
            _LOGGER.error("Error fetching gas meter reading: %s", e)
            return None

    async def fetch_electricity_meter_reading(self, account_number: str, meter_id: str):
        """Fetch the latest electricity meter reading for a specific meter.

        Args:
            account_number: The account number
            meter_id: The electricity meter ID

        Returns:
            Dict containing the latest reading data or None if error
        """
        if not await self.ensure_token():
            _LOGGER.error("Failed to ensure valid token for fetch_electricity_meter_reading")
            return None

        variables = {"accountNumber": account_number, "meterId": meter_id}
        client = self._get_graphql_client()

        try:
            _LOGGER.debug(
                "Fetching electricity meter reading for account %s, meter %s",
                account_number,
                meter_id,
            )
            response = await client.execute_async(
                query=ELECTRICITY_METER_READINGS_QUERY, variables=variables
            )

            if response is None:
                _LOGGER.error("API returned None response for electricity meter reading")
                return None

            if "errors" in response:
                _LOGGER.error(
                    "GraphQL errors in electricity meter reading response: %s",
                    response["errors"],
                )
                return None

            if "data" in response and "electricityMeterReadings" in response["data"]:
                readings_data = response["data"]["electricityMeterReadings"]

                if (
                    readings_data
                    and "edges" in readings_data
                    and readings_data["edges"]
                ):
                    # Get the first (latest) reading
                    latest_reading = readings_data["edges"][0]["node"]
                    _LOGGER.debug(
                        "Got electricity meter reading: %s at %s (type: %s, origin: %s)",
                        latest_reading.get("value"),
                        latest_reading.get("readAt"),
                        latest_reading.get("typeOfRead"),
                        latest_reading.get("origin"),
                    )
                    return latest_reading
                else:
                    _LOGGER.warning(
                        "No electricity meter readings found for meter %s", meter_id
                    )
                    return None
            else:
                _LOGGER.error("Invalid response structure for electricity meter reading")
                return None

        except Exception as e:
            _LOGGER.error("Error fetching electricity meter reading: %s", e)
            return None
