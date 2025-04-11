"""Provide the OctopusGermany class for interacting with the Octopus Energy API.

Includes methods for authentication, fetching account details, managing devices, and retrieving
various data related to electricity usage and tariffs.
"""

import logging
from datetime import datetime, timedelta
import asyncio
from homeassistant.exceptions import ConfigEntryNotReady
from python_graphql_client import GraphqlClient

_LOGGER = logging.getLogger(__name__)

GRAPH_QL_ENDPOINT = "https://api.oeg-kraken.energy/v1/graphql/"
ELECTRICITY_LEDGER = "ELECTRICITY_LEDGER"


class OctopusGermany:
    def __init__(self, email: str, password: str):
        self._email = email
        self._password = password
        self._session = None
        self._token = None

    async def login(self) -> bool:
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
                response = await client.execute_async(query=query, variables=variables)
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
                            "Retrying login due to rate limit: attempt %s", attempt + 1
                        )
                        await asyncio.sleep(delay)
                        delay *= 2  # Exponential backoff
                        continue
                    else:
                        _LOGGER.error("Login failed: %s", response["errors"])
                        return False

                self._token = response["data"]["obtainKrakenToken"]["token"]
                return True

            except Exception as e:
                _LOGGER.error("Error during login attempt %s: %s", attempt + 1, e)
                await asyncio.sleep(delay)
                delay *= 2

        _LOGGER.error("All login attempts failed.")
        return False

    async def accounts(self):
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
            response = await client.execute_async(query=query, variables=variables)
            _LOGGER.debug("Fetch all data response: %s", response)
            data = response.get("data", {})
            account_data = data.get("account", {})
            _LOGGER.debug("Account data: %s", account_data)
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
        _LOGGER.debug(
            "Sending API request to change device suspension: device_id=%s, action=%s",
            device_id,
            action,
        )
        _LOGGER.debug("GraphQL Mutation: %s", query)
        _LOGGER.debug("Variables: %s", variables)
        headers = {"authorization": self._token}
        client = GraphqlClient(endpoint=GRAPH_QL_ENDPOINT, headers=headers)
        try:
            response = await client.execute_async(query=query, variables=variables)
            _LOGGER.debug("Change device suspension response: %s", response)
            if "errors" in response:
                _LOGGER.error("API returned errors: %s", response["errors"])
                return None
            return (
                response.get("data", {}).get("updateDeviceSmartControl", {}).get("id")
            )
        except Exception as e:
            _LOGGER.error("Error changing device suspension: %s", e)
            return None
