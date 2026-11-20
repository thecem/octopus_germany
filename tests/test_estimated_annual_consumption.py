"""Tests for the OE estimated annual consumption sensor."""

import asyncio
import unittest
from unittest.mock import AsyncMock, Mock, patch

# HA 2026.10 installs its validation alias before integrations import voluptuous.
import homeassistant  # noqa: F401

from custom_components.octopus_germany import _async_fetch_account_data
from custom_components.octopus_germany.api.payment_adequacy import (
    normalize_estimated_annual_consumption,
)
from custom_components.octopus_germany.entities.electricity import (
    OctopusEstimatedAnnualConsumptionSensor,
)
from custom_components.octopus_germany.models import TariffCapabilities
from custom_components.octopus_germany.octopus_germany import OctopusGermany


def _api_with_response(response: dict) -> tuple[OctopusGermany, Mock]:
    api = object.__new__(OctopusGermany)
    api._payment_adequacy_cache = {}
    api.ensure_token = AsyncMock(return_value=True)
    client = Mock(execute_async=AsyncMock(return_value=response))
    api._get_oe_backend_graphql_client = Mock(return_value=client)
    return api, client


class EstimatedAnnualConsumptionTest(unittest.TestCase):
    def test_normalize_converts_decimal_strings(self) -> None:
        result = normalize_estimated_annual_consumption(
            {
                "estimatedAnnualConsumption": {
                    "currentYear": "5208.587610457285065934812982",
                    "lastYear": None,
                }
            }
        )

        assert result == {"current_year": 5208.587610457285, "last_year": None}

    def test_normalize_returns_none_without_values(self) -> None:
        assert normalize_estimated_annual_consumption(None) is None
        assert normalize_estimated_annual_consumption({}) is None
        assert (
            normalize_estimated_annual_consumption(
                {"estimatedAnnualConsumption": {"currentYear": None, "lastYear": None}}
            )
            is None
        )
        assert (
            normalize_estimated_annual_consumption(
                {"estimatedAnnualConsumption": {"currentYear": "n/a"}}
            )
            is None
        )

    def test_fetch_uses_oe_backend_and_caches_result(self) -> None:
        api, client = _api_with_response(
            {
                "data": {
                    "paymentAdequacy": {
                        "estimatedAnnualConsumption": {
                            "currentYear": "5208.5876",
                            "lastYear": "4800",
                        }
                    }
                }
            }
        )

        first = asyncio.run(api.fetch_estimated_annual_consumption("account-1", "42"))
        second = asyncio.run(api.fetch_estimated_annual_consumption("account-1", "42"))

        assert first == second == {"current_year": 5208.5876, "last_year": 4800.0}
        client.execute_async.assert_awaited_once()
        assert client.execute_async.await_args.kwargs["variables"] == {
            "accountNumber": "account-1",
            "propertyId": "42",
        }

    def test_fetch_caches_unsupported_accounts(self) -> None:
        api, client = _api_with_response(
            {"errors": [{"extensions": {"errorCode": "KT-CT-0000"}}], "data": None}
        )

        first = asyncio.run(api.fetch_estimated_annual_consumption("account-1", "42"))
        second = asyncio.run(api.fetch_estimated_annual_consumption("account-1", "42"))

        assert first is None
        assert second is None
        client.execute_async.assert_awaited_once()

    def test_fetch_does_not_cache_transient_failures(self) -> None:
        api, client = _api_with_response({})
        client.execute_async.side_effect = [
            OSError("boom"),
            {
                "data": {
                    "paymentAdequacy": {
                        "estimatedAnnualConsumption": {"currentYear": "100"}
                    }
                }
            },
        ]

        first = asyncio.run(api.fetch_estimated_annual_consumption("account-1", "42"))
        second = asyncio.run(api.fetch_estimated_annual_consumption("account-1", "42"))

        assert first is None
        assert second == {"current_year": 100.0, "last_year": None}
        assert client.execute_async.await_count == 2

    def test_fetch_account_data_adds_estimated_annual_consumption(self) -> None:
        api = Mock()
        api.fetch_tariff_capabilities = AsyncMock(return_value=TariffCapabilities())
        api.fetch_data_for_account = AsyncMock(return_value={"account": {}})
        api.fetch_estimated_annual_consumption = AsyncMock(
            return_value={"current_year": 5208.59, "last_year": None}
        )

        async def process_api_data(data, account_number, api_client):
            return {
                account_number: {
                    "account_number": account_number,
                    "malo_number": "malo-1",
                    "property_ids": [None, "42"],
                }
            }

        result = asyncio.run(
            _async_fetch_account_data(api, ["account-1"], process_api_data, {})
        )

        assert result["account-1"]["estimated_annual_consumption"] == {
            "current_year": 5208.59,
            "last_year": None,
        }
        api.fetch_estimated_annual_consumption.assert_awaited_once_with(
            "account-1", "42"
        )

    def test_fetch_account_data_skips_accounts_without_electricity(self) -> None:
        api = Mock()
        api.fetch_tariff_capabilities = AsyncMock(return_value=TariffCapabilities())
        api.fetch_data_for_account = AsyncMock(return_value={"account": {}})
        api.fetch_estimated_annual_consumption = AsyncMock()

        async def process_api_data(data, account_number, api_client):
            return {account_number: {"property_ids": ["42"]}}

        result = asyncio.run(
            _async_fetch_account_data(api, ["account-1"], process_api_data, {})
        )

        assert "estimated_annual_consumption" not in result["account-1"]
        api.fetch_estimated_annual_consumption.assert_not_awaited()

    def test_sensor_exposes_estimate_and_availability(self) -> None:
        coordinator = Mock(
            data={
                "account-1": {
                    "estimated_annual_consumption": {
                        "current_year": 5208.59,
                        "last_year": 4800.0,
                    }
                }
            }
        )
        sensor = OctopusEstimatedAnnualConsumptionSensor("account-1", coordinator)

        assert sensor.unique_id == "octopus_account-1_estimated_annual_consumption"
        assert sensor.native_unit_of_measurement == "kWh"
        assert sensor.native_value == 5208.59
        assert sensor.available is True
        assert sensor.extra_state_attributes == {
            "last_year": 4800.0,
            "source": "OE backend",
        }

        coordinator.data["account-1"]["estimated_annual_consumption"] = None
        assert sensor.native_value is None
        assert sensor.available is False


if __name__ == "__main__":
    unittest.main()
