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

_LOGGER = logging.getLogger(__name__)

GRAPH_QL_ENDPOINT = "https://api.oeg-kraken.energy/v1/graphql/"
ELECTRICITY_LEDGER = "ELECTRICITY_LEDGER"
TOKEN_REFRESH_MARGIN = 300  # Refresh token 5 minutes before expiry

# Global token manager to prevent multiple instances from making redundant token requests
_GLOBAL_TOKEN_MANAGER = None


class TokenManager:
    """Centralized token management for Octopus Germany API."""

    def __init__(self):
        """Initialize the token manager."""
        self._token = None
        self._expiry = None
        self._refresh_lock = asyncio.Lock()

    @property
    def token(self):
        """Get the current token."""
        return self._token

    @property
    def is_valid(self):
        """Check if the token is valid."""
        if not self._token or not self._expiry:
            return False

        now = datetime.utcnow().timestamp()
        # Return True if token is valid for at least TOKEN_REFRESH_MARGIN more seconds
        valid = now < (self._expiry - TOKEN_REFRESH_MARGIN)

        if not valid:
            remaining_time = self._expiry - now if self._expiry else 0
            _LOGGER.debug(
                "Token validity check: invalid (expiry in %s seconds, refresh margin: %s)",
                int(remaining_time),
                TOKEN_REFRESH_MARGIN,
            )
        else:
            remaining_time = self._expiry - now if self._expiry else 0
            _LOGGER.debug(
                "Token validity check: valid (expiry in %s seconds, refresh margin: %s)",
                int(remaining_time),
                TOKEN_REFRESH_MARGIN,
            )

        return valid

    def set_token(self, token, expiry=None):
        """Set a new token and extract its expiry time."""
        self._token = token

        if expiry:
            self._expiry = expiry
        else:
            # Decode token to get expiry time
            try:
                decoded = jwt.decode(token, options={"verify_signature": False})
                self._expiry = decoded.get("exp")
                now = datetime.utcnow().timestamp()
                token_lifetime = self._expiry - now if self._expiry else 0

                _LOGGER.debug(
                    "Token set with expiry timestamp %s (%s) - valid for %s seconds",
                    self._expiry,
                    datetime.fromtimestamp(self._expiry).strftime("%Y-%m-%d %H:%M:%S")
                    if self._expiry
                    else "unknown",
                    int(token_lifetime),
                )
            except Exception as e:
                _LOGGER.error("Failed to decode token: %s", e)
                self._expiry = None

    def clear(self):
        """Clear the token."""
        self._token = None
        self._expiry = None


class OctopusGermany:
    def __init__(self, email: str, password: str):
        self._email = email
        self._password = password
        self._session = None

        # Use global token manager to prevent redundant login attempts across instances
        global _GLOBAL_TOKEN_MANAGER
        if _GLOBAL_TOKEN_MANAGER is None:
            _GLOBAL_TOKEN_MANAGER = TokenManager()
        self._token_manager = _GLOBAL_TOKEN_MANAGER

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

            retries = 5
            delay = 1  # Start with 1 second delay

            for attempt in range(retries):
                try:
                    _LOGGER.debug("Making login attempt %s of %s", attempt + 1, retries)
                    response = await client.execute_async(
                        query=query, variables=variables
                    )
                    _LOGGER.debug("Login response received for attempt %s", attempt + 1)

                    if "errors" in response:
                        error_code = (
                            response["errors"][0].get("extensions", {}).get("errorCode")
                        )
                        error_message = response["errors"][0].get(
                            "message", "Unknown error"
                        )

                        if error_code == "KT-CT-1199":  # Too many requests
                            _LOGGER.warning(
                                "Rate limit hit. Retrying in %s seconds...", delay
                            )
                            _LOGGER.debug(
                                "Retrying login due to rate limit: attempt %s",
                                attempt + 1,
                            )
                            await asyncio.sleep(delay)
                            delay *= 2  # Exponential backoff
                            continue
                        elif error_code == "KT-CT-1124":  # Expired JWT
                            _LOGGER.warning(
                                "JWT expired during login attempt. Clearing token and retrying..."
                            )
                            self._token_manager.clear()
                            # Continue with the retry, don't return False yet
                            await asyncio.sleep(delay)
                            delay *= 2  # Exponential backoff
                            continue
                        else:
                            _LOGGER.error(
                                "Login failed: %s - %s",
                                error_message,
                                response["errors"],
                            )
                            return False

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
                                _LOGGER.debug(
                                    "Token received with expiration timestamp %s from payload",
                                    expiration,
                                )
                                self._token_manager.set_token(token, expiration)
                            else:
                                # Fall back to JWT decoding if no payload available
                                self._token_manager.set_token(token)

                            return True
                        else:
                            _LOGGER.error(
                                "No token in response despite successful request"
                            )
                    else:
                        _LOGGER.error("Unexpected API response format: %s", response)

                    return False

                except Exception as e:
                    _LOGGER.error("Error during login attempt %s: %s", attempt + 1, e)
                    await asyncio.sleep(delay)
                    delay *= 2

            _LOGGER.error("All login attempts failed.")
            return False

    async def ensure_token(self):
        """Ensure a valid token is available, refreshing if necessary."""
        if not self._token_manager.is_valid:
            _LOGGER.debug("Token invalid or expired, logging in again")
            return await self.login()
        return True

    # Consolidated query to get both accounts list and initial data in one API call
    async def fetch_accounts_with_initial_data(self):
        """Fetch accounts and initial data in a single API call.

        This consolidated query gets account numbers and basic info in one call,
        reducing API requests during component setup.
        """
        await self.ensure_token()

        query = """
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
        client = self._get_graphql_client()

        try:
            response = await client.execute_async(query=query)
            _LOGGER.debug("Fetch accounts with initial data response: %s", response)

            if "data" in response and "viewer" in response["data"]:
                accounts = response["data"]["viewer"]["accounts"]
                if not accounts:
                    _LOGGER.error("No accounts found")
                    return None

                # Return both the accounts and first account data
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

        query = """
            query ComprehensiveDataQuery($accountNumber: String!) {
              account(accountNumber: $accountNumber) {
                allProperties {
                  id
                  electricityMalos {
                    agreements {
                      product {
                        code
                        description
                        fullName
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
                id
                ledgers {
                  balance
                  ledgerType
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
              plannedDispatches(accountNumber: $accountNumber) {
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
            }
        """
        variables = {"accountNumber": account_number}
        client = self._get_graphql_client()

        try:
            _LOGGER.debug(
                "Making API request to fetch_all_data for account %s",
                account_number,
            )
            response = await client.execute_async(query=query, variables=variables)

            # Log the full API response for debugging
            _LOGGER.info("API Response: %s", json.dumps(response, indent=2))

            if response is None:
                _LOGGER.error("API returned None response")
                return None

            # Initialize the result structure
            result = {
                "account": {},
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

                if "plannedDispatches" in data:
                    result["plannedDispatches"] = (
                        data["plannedDispatches"]
                        if data["plannedDispatches"] is not None
                        else []
                    )

                # Only log errors but don't fail the whole request if we got at least account data
                if "errors" in response and result["account"]:
                    # Filter only the errors that are about missing devices
                    device_errors = [
                        error
                        for error in response["errors"]
                        if (
                            error.get("path", [])
                            and error.get("path")[0]
                            in ["completedDispatches", "plannedDispatches", "devices"]
                            and error.get("extensions", {}).get("errorCode")
                            == "KT-CT-4301"
                        )
                    ]

                    # Handle other errors that might affect the account data
                    other_errors = [
                        error
                        for error in response["errors"]
                        if error not in device_errors
                    ]

                    if device_errors:
                        _LOGGER.warning(
                            "API returned device-related errors (expected for accounts without devices): %s",
                            device_errors,
                        )

                    if other_errors:
                        _LOGGER.error(
                            "API returned non-device related errors: %s", other_errors
                        )

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

    async def set_vehicle_charge_preferences(
        self,
        account_number: str,
        weekday_target_soc: int,
        weekend_target_soc: int,
        weekday_target_time: str,
        weekend_target_time: str,
    ) -> bool:
        """Set vehicle charging preferences with account number."""
        if not await self.ensure_token():
            _LOGGER.error(
                "Failed to ensure valid token for set_vehicle_charge_preferences"
            )
            return False

        # Use the same GraphQL mutation format that has been confirmed to work
        query = """
        mutation setVehicleChargePreferences($accountNumber: String = "") {
          setVehicleChargePreferences(
            input: {accountNumber: $accountNumber, weekdayTargetSoc: %d, weekendTargetSoc: %d, weekdayTargetTime: "%s", weekendTargetTime: "%s"}
          ) {
            krakenflexDevice {
              provider
            }
          }
        }
        """ % (
            weekday_target_soc,
            weekend_target_soc,
            weekday_target_time,
            weekend_target_time,
        )

        variables = {"accountNumber": account_number}

        # Create a fresh GraphQL client with explicit authorization headers
        headers = {"Authorization": self._token}
        client = GraphqlClient(endpoint=GRAPH_QL_ENDPOINT, headers=headers)

        _LOGGER.debug(
            "Making set_vehicle_charge_preferences API request with account: %s",
            account_number,
        )

        try:
            response = await client.execute_async(query=query, variables=variables)
            _LOGGER.debug("Set vehicle charge preferences response: %s", response)

            if "errors" in response:
                error = response.get("errors", [{}])[0]
                error_code = error.get("extensions", {}).get("errorCode")
                error_message = error.get("message", "Unknown error")

                _LOGGER.error(
                    "API error setting vehicle charge preferences: %s (code: %s)",
                    error_message,
                    error_code,
                )

                # Check if token expired error
                if error_code == "KT-CT-1124":  # JWT expired
                    _LOGGER.warning(
                        "Token expired during setting vehicle charge preferences, refreshing..."
                    )
                    self._token_manager.clear()
                    success = await self.login()
                    if success:
                        # Retry with new token
                        return await self.set_vehicle_charge_preferences(
                            account_number,
                            weekday_target_soc,
                            weekend_target_soc,
                            weekday_target_time,
                            weekend_target_time,
                        )

                return False

            return True
        except Exception as e:
            _LOGGER.error("Error setting vehicle charge preferences: %s", e)
            return False

    async def _fetch_account_and_devices(self, account_number: str):
        """Fetch account and devices data."""
        if not await self.ensure_token():
            return None

        query = """
            query AccountAndDevicesQuery($accountNumber: String!) {
              account(accountNumber: $accountNumber) {
                allProperties {
                  id
                  electricityMalos {
                    agreements {
                      product {
                        code
                        description
                        fullName
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
                id
                ledgers {
                  balance
                  ledgerType
                }
              }
              products(accountNumber: $accountNumber) {
                code
                description
                fullName
                grossRateInformation {
                  grossRate
                }
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
        variables = {"accountNumber": account_number}
        client = self._get_graphql_client()

        try:
            _LOGGER.debug(
                "Making API request to fetch account and devices for account %s",
                account_number,
            )
            response = await client.execute_async(query=query, variables=variables)

            # Initialize result structure
            result = {
                "account": {},
                "devices": [],
            }

            if response is None:
                _LOGGER.error(
                    "API returned None response for account and devices query"
                )
                return result

            if "errors" in response:
                # Check for specific error cases we can handle
                errors = response.get("errors", [])
                for error in errors:
                    error_code = error.get("extensions", {}).get("errorCode")
                    error_path = error.get("path", [])

                    # Token expired error
                    if error_code == "KT-CT-1124":  # JWT expired
                        _LOGGER.warning(
                            "Token expired during account/devices fetch, refreshing..."
                        )
                        self._token_manager.clear()
                        success = await self.login()
                        if success:
                            # Retry with new token
                            return await self._fetch_account_and_devices(account_number)

                    # Log but continue for certain path-specific errors
                    if (
                        error_path
                        and error_path[0] == "devices"
                        and "Unable to find device" in error.get("message", "")
                    ):
                        _LOGGER.warning(
                            "No devices found for account %s: %s",
                            account_number,
                            error.get("message"),
                        )
                        # Continue with empty devices list
                    else:
                        _LOGGER.error("API error in account/devices query: %s", error)

            # Process data from response, safely handling missing fields
            data = response.get("data", {})

            # Extract account data if available
            if "account" in data:
                result["account"] = data.get("account", {})

            # Extract devices if available
            if "devices" in data:
                result["devices"] = data.get("devices", [])

            # Check if we got separate products data
            if "products" in data and data["products"]:
                _LOGGER.debug("Found direct products data in API response")
                result["direct_products"] = data["products"]

            return result

        except Exception as e:
            _LOGGER.error("Error fetching account and devices: %s", e)
            return {
                "account": {},
                "devices": [],
            }
