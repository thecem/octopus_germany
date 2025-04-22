"""Provide the OctopusGermany class for interacting with the Octopus Energy API.

Includes methods for authentication, fetching account details, managing devices, and retrieving
various data related to electricity usage and tariffs.
"""

import logging
from datetime import datetime, timedelta
import asyncio
import jwt
from homeassistant.exceptions import ConfigEntryNotReady
from python_graphql_client import GraphqlClient

_LOGGER = logging.getLogger(__name__)

GRAPH_QL_ENDPOINT = "https://api.oeg-kraken.energy/v1/graphql/"
ELECTRICITY_LEDGER = "ELECTRICITY_LEDGER"
TOKEN_REFRESH_MARGIN = 300  # Refresh token 5 minutes before expiry


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

    def set_token(self, token):
        """Set a new token and extract its expiry time."""
        self._token = token

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
        self._token_manager = TokenManager()

    @property
    def _token(self):
        """Get the current token from the token manager."""
        return self._token_manager.token

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
                  }
                }
            """
            variables = {"email": self._email, "password": self._password}
            client = GraphqlClient(endpoint=GRAPH_QL_ENDPOINT)

            retries = 5
            delay = 1  # Start with 1 second delay

            for attempt in range(retries):
                try:
                    response = await client.execute_async(
                        query=query, variables=variables
                    )
                    _LOGGER.debug("Login response: %s", response)

                    if "errors" in response:
                        error_code = (
                            response["errors"][0].get("extensions", {}).get("errorCode")
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
                        else:
                            _LOGGER.error("Login failed: %s", response["errors"])
                            return False

                    token = response["data"]["obtainKrakenToken"]["token"]
                    self._token_manager.set_token(token)
                    return True

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

    async def accounts(self):
        """Fetch account numbers."""
        await self.ensure_token()
        response = await self._fetch_accounts()
        if response is None:
            _LOGGER.error("Failed to fetch accounts: response is None")
            raise ConfigEntryNotReady("Failed to fetch accounts: response is None")

        _LOGGER.debug("Accounts response: %s", response)

        if isinstance(response, list):
            # Handle the case where the response is a list of account numbers
            return [account["number"] for account in response]

        if (
            "data" in response
            and "viewer" in response["data"]
            and "accounts" in response["data"]["viewer"]
        ):
            return [
                account["number"] for account in response["data"]["viewer"]["accounts"]
            ]
        else:
            _LOGGER.error("Unexpected API response structure: %s", response)
            return [
                account["number"] for account in response
            ]  # Handle the list of account numbers

    async def _fetch_accounts(self):
        query = """
            query {
              viewer {
                accounts {
                  number
                  ledgers {
                    balance
                    number
                    ledgerType
                  }
                }
              }
            }
        """
        headers = {"authorization": self._token}
        client = GraphqlClient(endpoint=GRAPH_QL_ENDPOINT, headers=headers)
        try:
            response = await client.execute_async(query=query)
            _LOGGER.debug("Fetch accounts response: %s", response)
            return response["data"]["viewer"]["accounts"]
        except Exception as e:
            _LOGGER.error("Error fetching accounts: %s", e)
            return None

    async def fetch_accounts(self):
        await self.ensure_token()
        query = """
            query {
              viewer {
                accounts {
                  number
                }
              }
            }
        """
        headers = {"authorization": self._token}
        client = GraphqlClient(endpoint=GRAPH_QL_ENDPOINT, headers=headers)
        try:
            response = await client.execute_async(query=query)
            _LOGGER.debug("Fetch accounts response: %s", response)
            accounts = response.get("data", {}).get("viewer", {}).get("accounts", [])
            if not accounts:
                _LOGGER.error(
                    "No accounts found for the provided credentials. Response: %s",
                    response,
                )
                return None
            return accounts
        except Exception as e:
            _LOGGER.error("Error fetching accounts: %s", e)
            return None

    async def account(self, account_number: str):
        await self.ensure_token()
        query = """
            query ($accountNumber: String!) {
              account(accountNumber: $accountNumber) {
                ledgers {
                  balance
                  number
                  ledgerType
                }
              }
            }
        """
        headers = {"authorization": self._token}
        client = GraphqlClient(endpoint=GRAPH_QL_ENDPOINT, headers=headers)
        response = await client.execute_async(query, {"accountNumber": account_number})

        if "data" not in response or "account" not in response["data"]:
            _LOGGER.error("Unexpected API response structure: %s", response)
            raise ConfigEntryNotReady("Unexpected API response structure")

        ledgers = response["data"]["account"]["ledgers"]
        electricity = next(
            filter(lambda x: x["ledgerType"] == ELECTRICITY_LEDGER, ledgers), None
        )

        if not electricity:
            _LOGGER.warning(
                "Electricity ledger not found in account: %s", account_number
            )
            return {"balance": 0, "ledgerType": None, "number": None}

        return {
            "balance": electricity["balance"],
            "ledgerType": electricity["ledgerType"],
            "number": electricity["number"],
        }

    async def planned_dispatches(self, account_number: str):
        await self.ensure_token()
        """Fetch planned dispatches for a given account.

        Parameters
        ----------
        account_number : str
            The account number for which to fetch planned dispatches.

        Returns
        -------
        list
            A list of planned dispatches with their details, or an empty list if none are found.
        """
        query = """
            query ($accountNumber: String!) {
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
        headers = {"authorization": self._token}
        client = GraphqlClient(endpoint=GRAPH_QL_ENDPOINT, headers=headers)
        response = await client.execute_async(query, {"accountNumber": account_number})

        if "data" not in response or "plannedDispatches" not in response["data"]:
            _LOGGER.error("Unexpected API response structure: %s", response)
            return []

        return response["data"]["plannedDispatches"]

    async def property_ids(self, account_number: str):
        await self.ensure_token()
        """Fetch the property IDs associated with the given account number.

        Parameters
        ----------
        account_number : str
            The account number for which to fetch property IDs.

        Returns
        -------
        list
            A list of property IDs, or an empty list if no properties are found.
        """
        query = """
            query getPropertyIds($accountNumber: String!) {
              account(accountNumber: $accountNumber) {
                properties {
                  id
                }
              }
            }
        """
        headers = {"authorization": self._token}
        client = GraphqlClient(endpoint=GRAPH_QL_ENDPOINT, headers=headers)
        response = await client.execute_async(query, {"accountNumber": account_number})

        if "data" not in response or "account" not in response["data"]:
            _LOGGER.error("Unexpected API response structure: %s", response)
            return []

        return [prop["id"] for prop in response["data"]["account"]["properties"]]

    async def devices(self, account_number: str):
        await self.ensure_token()
        """Fetch the list of devices associated with the given account number.

        Parameters
        ----------
        account_number : str
            The account number for which to fetch devices.

        Returns
        -------
        list
            A list of devices with their details, or an empty list if no devices are found.

        """
        query = """
            query ($accountNumber: String!) {
              devices(accountNumber: $accountNumber) {
                deviceType
                id
                integrationDeviceId
                name
                preferences {
                  mode
                  targetType
                  schedules {
                    max
                    min
                    time
                    dayOfWeek
                  }
                  unit
                }
                provider
                status {
                  current
                  isSuspended
                  currentState
                }
              }
            }
        """
        headers = {"authorization": self._token}
        client = GraphqlClient(endpoint=GRAPH_QL_ENDPOINT, headers=headers)
        response = await client.execute_async(query, {"accountNumber": account_number})

        if "data" not in response or "devices" not in response["data"]:
            _LOGGER.error("Unexpected API response structure: %s", response)
            return []

        return response["data"]["devices"]

    async def timeslot_data(self, account_number: str):
        await self.ensure_token()
        query = """
            query AccountNumber($accountNumber: String = "") {
              account(accountNumber: $accountNumber) {
                allProperties {
                  electricityMalos {
                    agreements {
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
                    }
                  }
                }
              }
            }
        """
        headers = {"authorization": self._token}
        client = GraphqlClient(endpoint=GRAPH_QL_ENDPOINT, headers=headers)
        response = await client.execute_async(query, {"accountNumber": account_number})

        if "data" not in response or "account" not in response["data"]:
            _LOGGER.error("Unexpected API response structure: %s", response)
            return []

        timeslot_data = []
        for prop in response["data"]["account"]["allProperties"]:
            for malo in prop["electricityMalos"]:
                for agreement in malo["agreements"]:
                    if "unitRateInformation" in agreement:
                        unit_rate_info = agreement["unitRateInformation"]
                        if (
                            unit_rate_info["__typename"]
                            == "TimeOfUseProductUnitRateInformation"
                        ):
                            timeslot_data.extend(unit_rate_info["rates"])

        return timeslot_data

    async def fetch_and_use_account(self):
        await self.ensure_token()
        """Fetch the first account and retrieve its details.

        This method fetches all account numbers associated with the user,
        selects the first account, and retrieves its details.

        Returns
        -------
        dict or None
            A dictionary containing account details if successful, or None if no accounts are found.
        """
        account_numbers = await self.accounts()
        if not account_numbers:
            _LOGGER.error("No account numbers found")
            return None

        account_number = account_numbers[0]  # Use the first account number
        return await self.account(account_number)

    async def fetch_all_data(self, account_number: str):
        """Fetch all data for an account including devices, dispatches and account details."""
        if not await self.ensure_token():
            _LOGGER.error("Failed to ensure valid token for fetch_all_data")
            return None

        query = """
            query MyQuery($accountNumber: String = "") {
              account(accountNumber: $accountNumber) {
                allProperties {
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
        headers = {"authorization": self._token}
        client = GraphqlClient(endpoint=GRAPH_QL_ENDPOINT, headers=headers)
        try:
            _LOGGER.debug(
                "Making API request to fetch_all_data for account %s", account_number
            )
            response = await client.execute_async(query=query, variables=variables)

            # Log detailed response information
            _LOGGER.debug("Fetch all data response status: %s", response is not None)
            if response is None:
                _LOGGER.error("API returned None response")
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
                        return await self.fetch_all_data(account_number)

                _LOGGER.error("API returned errors: %s", response.get("errors"))
                return None

            # Log specific data parts existence
            data = response.get("data", {})
            _LOGGER.debug("Response contains account data: %s", "account" in data)
            _LOGGER.debug("Response contains devices data: %s", "devices" in data)
            _LOGGER.debug(
                "Response contains plannedDispatches data: %s",
                "plannedDispatches" in data,
            )

            account_data = data.get("account", {})
            return {
                "account": account_data,
                "completedDispatches": data.get("completedDispatches", []),
                "devices": data.get("devices", []),
                "plannedDispatches": data.get("plannedDispatches", []),
            }
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
        headers = {"authorization": self._token}
        client = GraphqlClient(endpoint=GRAPH_QL_ENDPOINT, headers=headers)
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
