import logging
from datetime import datetime, timedelta
from python_graphql_client import GraphqlClient
from homeassistant.exceptions import ConfigEntryNotReady

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
        response = await client.execute_async(query=query, variables=variables)

        _LOGGER.debug("Login response: %s", response)

        if "errors" in response:
            _LOGGER.error("Login failed: %s", response["errors"])
            return False

        self._token = response["data"]["obtainKrakenToken"]["token"]
        return True

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
        query = """
            query ($accountNumber: String!) {
              devices(accountNumber: $accountNumber) {
                id
                name
                status {
                  current
                  currentState
                  isSuspended
                }
                deviceType
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

    async def fetch_and_use_account(self):
        account_numbers = await self.accounts()
        if not account_numbers:
            _LOGGER.error("No account numbers found")
            return None

        account_number = account_numbers[0]  # Use the first account number
        return await self.account(account_number)
