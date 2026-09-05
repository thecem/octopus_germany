"""Tests for tariff capability detection and conditional API fields."""

import asyncio
import unittest
from datetime import UTC, datetime
from unittest.mock import AsyncMock, Mock

import voluptuous as vol

from custom_components.octopus_germany import _async_fetch_account_data
from custom_components.octopus_germany.binary_sensor import (
    _create_intelligent_binary_entities,
)
from custom_components.octopus_germany.config_flow import build_options_schema
from custom_components.octopus_germany.const import (
    CONF_EMAIL,
    CONF_INTELLIGENT_UPDATE_INTERVAL,
    CONF_PASSWORD,
    CONF_UPDATE_INTERVAL,
    INTELLIGENT_UPDATE_INTERVAL,
    UPDATE_INTERVAL,
)
from custom_components.octopus_germany.coordinator import normalize_update_interval
from custom_components.octopus_germany.data_processing import (
    calculate_dispatch_state,
    create_empty_account_data,
    extract_charging_sessions,
    extract_device_data,
    extract_gross_rate,
    extract_meter_data,
    get_product_type,
    merge_graphql_responses,
    merge_normalized_account_data,
    normalize_direct_products,
    normalize_timeslots,
    normalize_unit_rate_forecast,
    process_ledgers,
)
from custom_components.octopus_germany.models import (
    TariffCapabilities,
    detect_tariff_capabilities,
    filter_active_accounts,
    has_intelligent_capability,
    select_primary_account,
)
from custom_components.octopus_germany.octopus_germany import (
    ACCOUNT_DISCOVERY_QUERY,
    COMPREHENSIVE_QUERY,
    INTELLIGENT_DATA_QUERY,
    OctopusGermany,
    SmartMeterFetchError,
)
from custom_components.octopus_germany.sensor import _create_device_entities
from custom_components.octopus_germany.services import (
    async_handle_refresh_intelligent_data,
    async_request_intelligent_refresh,
)
from custom_components.octopus_germany.switch import _get_intelligent_devices
from custom_components.octopus_germany.tariff import (
    format_uk_rates,
    get_active_timeslot_rate,
    get_current_forecast_rate,
    parse_tariff_time,
)


class TariffCapabilitiesTest(unittest.TestCase):
    """Verify feature detection for supported account response shapes."""

    def test_standard_dynamic_tariff_has_no_intelligent_features(self) -> None:
        account_data = {
            "allProperties": [
                {
                    "electricityMalos": [
                        {
                            "meter": {"shouldReceiveSmartMeterData": True},
                            "agreements": [
                                {
                                    "product": {
                                        "code": "DYNAMIC-DE",
                                        "fullName": "Dynamic Electricity",
                                        "isTimeOfUse": True,
                                    }
                                }
                            ],
                        }
                    ]
                }
            ]
        }

        capabilities = detect_tariff_capabilities(account_data)

        self.assertTrue(capabilities.has_dynamic_prices)
        self.assertTrue(capabilities.has_smart_meter)
        self.assertFalse(capabilities.has_intelligent_dispatches)

    def test_normalize_update_interval_applies_default_and_bounds(self) -> None:
        self.assertEqual(normalize_update_interval("invalid", 30), 30)
        self.assertEqual(normalize_update_interval(0, 30), 1)
        self.assertEqual(normalize_update_interval(90, 30), 60)
        self.assertEqual(normalize_update_interval("5", 30), 5)

    def test_intelligent_entity_gate_requires_capability(self) -> None:
        self.assertFalse(has_intelligent_capability({"devices": [{"id": "x"}]}))
        self.assertTrue(
            has_intelligent_capability(
                {"tariff_capabilities": {"has_intelligent_dispatches": True}}
            )
        )

    def test_account_filter_excludes_terminal_accounts_and_prefers_electricity(
        self,
    ) -> None:
        accounts = [
            {
                "number": "gas",
                "status": "ACTIVE",
                "ledgers": [{"ledgerType": "GAS_LEDGER"}],
            },
            {
                "number": "closed",
                "status": "DORMANT",
                "ledgers": [{"ledgerType": "ELECTRICITY_LEDGER"}],
            },
            {
                "number": "electricity",
                "status": "ACTIVE",
                "ledgers": [{"ledgerType": "ELECTRICITY_LEDGER"}],
            },
        ]

        active_accounts = filter_active_accounts(accounts)

        self.assertEqual(
            [account["number"] for account in active_accounts], ["gas", "electricity"]
        )
        self.assertEqual(select_primary_account(active_accounts), "electricity")

    def test_device_entity_factory_skips_standard_tariffs(self) -> None:
        self.assertEqual(
            _create_device_entities(
                "account-1",
                {"devices": [{"id": "device-1"}]},
                Mock(),
            ),
            [],
        )

    def test_binary_entity_factory_skips_standard_tariffs(self) -> None:
        self.assertEqual(
            _create_intelligent_binary_entities(
                "account-1",
                {"devices": [{"id": "device-1"}]},
                Mock(),
            ),
            [],
        )

    def test_switch_device_gate_skips_standard_tariffs(self) -> None:
        self.assertEqual(
            _get_intelligent_devices({"devices": [{"id": "device-1"}]}),
            [],
        )

    def test_tariff_helpers_calculate_simple_and_timeslot_rates(self) -> None:
        self.assertEqual(
            get_active_timeslot_rate({"type": "Simple", "grossRate": "25"}),
            0.25,
        )
        self.assertEqual(
            get_active_timeslot_rate(
                {
                    "type": "TimeOfUse",
                    "timeslots": [
                        {
                            "rate": "10",
                            "activation_rules": [
                                {"from_time": "00:00:00", "to_time": "04:00:00"}
                            ],
                        }
                    ],
                },
                parse_tariff_time("02:00:00"),
            ),
            0.1,
        )

    def test_tariff_helper_reads_current_forecast_rate(self) -> None:
        rate = get_current_forecast_rate(
            {
                "unitRateForecast": [
                    {
                        "validFrom": "2026-01-01T00:00:00+00:00",
                        "validTo": "2026-01-01T01:00:00+00:00",
                        "unitRateInformation": {"latestGrossUnitRateCentsPerKwh": "20"},
                    }
                ]
            },
            datetime.fromisoformat("2026-01-01T00:30:00+00:00"),
        )

        self.assertEqual(rate, 0.2)

    def test_format_uk_rates_preserves_card_compatibility_shape(self) -> None:
        rates = format_uk_rates(
            {
                "unitRateForecast": [
                    {
                        "validFrom": "2026-01-01T01:00:00+00:00",
                        "validTo": "2026-01-01T02:00:00+00:00",
                        "unitRateInformation": {"latestGrossUnitRateCentsPerKwh": "20"},
                    }
                ]
            }
        )

        self.assertEqual(
            rates,
            [
                {
                    "start": "2026-01-01T01:00:00+00:00",
                    "end": "2026-01-01T02:00:00+00:00",
                    "value_inc_vat": 0.2,
                }
            ],
        )

    def test_options_schema_applies_defaults_and_coerces_intervals(self) -> None:
        schema = build_options_schema("user@example.test", 30, 3)
        validated = schema(
            {
                CONF_EMAIL: "user@example.test",
                CONF_PASSWORD: "secret",
                CONF_UPDATE_INTERVAL: "15",
                CONF_INTELLIGENT_UPDATE_INTERVAL: "5",
            }
        )

        self.assertEqual(validated[CONF_UPDATE_INTERVAL], 15)
        self.assertEqual(validated[CONF_INTELLIGENT_UPDATE_INTERVAL], 5)

    def test_options_schema_rejects_intervals_outside_bounds(self) -> None:
        schema = build_options_schema("user@example.test", 30, 3)

        with self.assertRaises(vol.Invalid):
            schema(
                {
                    CONF_EMAIL: "user@example.test",
                    CONF_PASSWORD: "secret",
                    CONF_UPDATE_INTERVAL: 0,
                    CONF_INTELLIGENT_UPDATE_INTERVAL: 3,
                }
            )

    def test_legacy_options_use_current_polling_defaults(self) -> None:
        schema = build_options_schema(
            "user@example.test",
            UPDATE_INTERVAL,
            INTELLIGENT_UPDATE_INTERVAL,
        )
        validated = schema(
            {
                CONF_EMAIL: "user@example.test",
                CONF_PASSWORD: "secret",
            }
        )

        self.assertEqual(validated[CONF_UPDATE_INTERVAL], 30)
        self.assertEqual(validated[CONF_INTELLIGENT_UPDATE_INTERVAL], 3)

    def test_refresh_service_updates_only_intelligent_coordinators(self) -> None:
        intelligent = Mock()
        intelligent.async_request_refresh = AsyncMock()
        hass = Mock()
        hass.data = {
            "octopus_germany": {
                "entry-1": {"intelligent_coordinator": intelligent},
                "entry-2": {"intelligent_coordinator": None},
            }
        }

        asyncio.run(async_handle_refresh_intelligent_data(hass, Mock()))

        intelligent.async_request_refresh.assert_awaited_once_with()

    def test_refresh_helper_can_target_an_account(self) -> None:
        intelligent = Mock()
        intelligent.async_request_refresh = AsyncMock()
        hass = Mock()
        hass.data = {
            "octopus_germany": {
                "entry-1": {
                    "account_numbers": ["account-1"],
                    "intelligent_coordinator": intelligent,
                },
                "entry-2": {
                    "account_numbers": ["account-2"],
                    "intelligent_coordinator": Mock(),
                },
            }
        }

        refreshed = asyncio.run(async_request_intelligent_refresh(hass, "account-1"))

        self.assertEqual(refreshed, 1)
        intelligent.async_request_refresh.assert_awaited_once_with()

    def test_fetch_account_data_keeps_successful_accounts_when_one_fails(self) -> None:
        api = Mock()
        api.fetch_tariff_capabilities = AsyncMock(
            side_effect=[
                TariffCapabilities(has_dynamic_prices=True),
                RuntimeError("temporary failure"),
            ]
        )
        api.fetch_data_for_account = AsyncMock(return_value={"account": {}})

        async def process_api_data(data, account_number, api_client):
            return {account_number: {"account_number": account_number}}

        capabilities_by_account = {}
        result = asyncio.run(
            _async_fetch_account_data(
                api,
                ["account-1", "account-2"],
                process_api_data,
                capabilities_by_account,
            )
        )

        self.assertIn("account-1", result)
        self.assertNotIn("account-2", result)
        self.assertIn("account-1", capabilities_by_account)

    def test_intelligent_product_enables_dispatches(self) -> None:
        account_data = {
            "allProperties": [
                {
                    "electricityMalos": [
                        {
                            "agreements": [
                                {
                                    "product": {
                                        "code": "INTELLIGENT-DE",
                                        "fullName": "Intelligent Octopus",
                                    }
                                }
                            ]
                        }
                    ]
                }
            ]
        }

        capabilities = detect_tariff_capabilities(account_data)

        self.assertTrue(capabilities.has_intelligent_dispatches)

    def test_devices_enable_intelligent_capability(self) -> None:
        capabilities = detect_tariff_capabilities({"devices": [{"id": "vehicle-1"}]})

        self.assertTrue(capabilities.has_intelligent_dispatches)

    def test_15min_server_error_enters_backoff(self) -> None:
        api = object.__new__(OctopusGermany)
        api._15min_retry_until = None
        api.ensure_token = AsyncMock(return_value=True)
        client = Mock()
        client.execute_async = AsyncMock(side_effect=RuntimeError("502 HTML"))
        api._get_graphql_client = Mock(return_value=client)

        self.assertIsNone(
            asyncio.run(
                api.fetch_electricity_15min_readings(
                    "account-1", "property-1", "2026-09-04"
                )
            )
        )
        self.assertIsNotNone(api._15min_retry_until)

        self.assertIsNone(
            asyncio.run(
                api.fetch_electricity_15min_readings(
                    "account-1", "property-1", "2026-09-04"
                )
            )
        )
        client.execute_async.assert_awaited_once()

    def test_comprehensive_query_makes_intelligent_fields_conditional(self) -> None:
        self.assertIn(
            "$includeIntelligent: Boolean!",
            COMPREHENSIVE_QUERY,
        )
        self.assertIn(
            "completedDispatches(accountNumber: $accountNumber)",
            INTELLIGENT_DATA_QUERY,
        )
        self.assertIn("devices(accountNumber: $accountNumber)", INTELLIGENT_DATA_QUERY)

    def test_capability_api_error_disables_intelligent_features(self) -> None:
        api = object.__new__(OctopusGermany)
        api._capabilities_by_account = {}
        api.ensure_token = AsyncMock(return_value=True)
        api._get_graphql_client = Mock(
            return_value=Mock(
                execute_async=AsyncMock(
                    return_value={"errors": [{"message": "temporary failure"}]}
                )
            )
        )

        capabilities = asyncio.run(api.fetch_tariff_capabilities("account-123"))

        self.assertFalse(capabilities.has_intelligent_dispatches)
        self.assertFalse(capabilities.has_dynamic_prices)
        self.assertFalse(capabilities.has_smart_meter)

    def test_data_fetch_uses_cached_capability_to_select_fields(self) -> None:
        api = object.__new__(OctopusGermany)
        api.fetch_tariff_capabilities = AsyncMock(
            return_value=TariffCapabilities(has_intelligent_dispatches=False)
        )
        api.fetch_all_data = AsyncMock(return_value={"account": {}})

        result = asyncio.run(api.fetch_data_for_account("account-123"))

        self.assertEqual(result, {"account": {}})
        api.fetch_all_data.assert_awaited_once_with(
            "account-123",
            include_intelligent=False,
        )

    def test_submit_meter_readings_sends_account_number(self) -> None:
        api = object.__new__(OctopusGermany)
        api.ensure_token = AsyncMock(return_value=True)
        api._get_graphql_client = Mock(
            return_value=Mock(
                execute_async=AsyncMock(
                    return_value={
                        "data": {
                            "createElectricityMeterReadings": {
                                "readingDate": "2026-09-04",
                                "numberOfReadingsCreated": 1,
                            }
                        }
                    }
                )
            )
        )

        result = asyncio.run(
            api.submit_meter_readings(
                "electricity",
                "meter-1",
                "2026-09-04",
                [{"value": 1234, "registerObisCode": "1-0:1.8.0"}],
                "account-1",
            )
        )

        variables = (
            api._get_graphql_client.return_value.execute_async.await_args.kwargs[
                "variables"
            ]
        )
        self.assertEqual(variables["input"]["accountNumber"], "account-1")
        self.assertTrue(result["success"])

    def test_smart_meter_server_error_enters_backoff(self) -> None:
        api = object.__new__(OctopusGermany)
        api._smart_meter_retry_until = None
        api.ensure_token = AsyncMock(return_value=True)
        client = Mock()
        client.execute_async = AsyncMock(
            return_value={"errors": [{"message": "upstream failure"}]}
        )
        api._get_graphql_client = Mock(return_value=client)

        with self.assertRaises(SmartMeterFetchError):
            asyncio.run(
                api.fetch_electricity_smart_meter_readings(
                    "account-1", "property-1", "2026-09-04"
                )
            )
        with self.assertRaises(SmartMeterFetchError):
            asyncio.run(
                api.fetch_electricity_smart_meter_readings(
                    "account-1", "property-1", "2026-09-04"
                )
            )

        client.execute_async.assert_awaited_once()

    def test_smart_meter_success_clears_previous_backoff(self) -> None:
        api = object.__new__(OctopusGermany)
        api._smart_meter_retry_until = datetime.now(UTC)
        api.ensure_token = AsyncMock(return_value=True)
        api._get_graphql_client = Mock(
            return_value=Mock(
                execute_async=AsyncMock(
                    return_value={
                        "data": {
                            "account": {
                                "property": {
                                    "measurements": {
                                        "edges": [
                                            {
                                                "node": {
                                                    "startAt": "2026-09-04T00:00:00+00:00",
                                                    "endAt": "2026-09-04T01:00:00+00:00",
                                                    "value": "1",
                                                    "unit": "kWh",
                                                }
                                            }
                                        ]
                                    }
                                }
                            }
                        }
                    }
                )
            )
        )

        readings = asyncio.run(
            api.fetch_electricity_smart_meter_readings(
                "account-1", "property-1", "2026-09-04"
            )
        )

        self.assertEqual(len(readings), 1)
        self.assertIsNone(api._smart_meter_retry_until)

    def test_account_discovery_query_requests_account_status(self) -> None:
        self.assertIn("status", ACCOUNT_DISCOVERY_QUERY)

    def test_no_fake_product_placeholder_remains(self) -> None:
        from pathlib import Path

        source = Path("custom_components/octopus_germany/__init__.py").read_text()
        self.assertNotIn('"code": "TEST_PRODUCT"', source)

    def test_intelligent_data_is_skipped_for_standard_tariff(self) -> None:
        api = object.__new__(OctopusGermany)
        api.fetch_tariff_capabilities = AsyncMock(
            return_value=TariffCapabilities(has_intelligent_dispatches=False)
        )

        result = asyncio.run(api.fetch_intelligent_data("account-123"))

        self.assertIsNone(result)

    def test_merge_graphql_responses_adds_intelligent_data(self) -> None:
        base_response = {"data": {"account": {"id": "account-1"}}}
        intelligent_response = {
            "data": {
                "devices": [{"id": "device-1"}],
                "completedDispatches": [],
            }
        }

        merged = merge_graphql_responses(base_response, intelligent_response)

        self.assertEqual(merged["data"]["account"], {"id": "account-1"})
        self.assertEqual(merged["data"]["devices"], [{"id": "device-1"}])
        self.assertNotIn("errors", merged)
        self.assertNotIn("devices", base_response["data"])

    def test_merge_graphql_responses_preserves_errors(self) -> None:
        merged = merge_graphql_responses(
            {"data": {}, "errors": [{"message": "base"}]},
            {"data": {}, "errors": [{"message": "intelligent"}]},
        )

        self.assertEqual(
            [error["message"] for error in merged["errors"]],
            ["base", "intelligent"],
        )

    def test_merge_normalized_account_data_preserves_base_fields(self) -> None:
        merged = merge_normalized_account_data(
            {
                "account_number": "account-1",
                "electricity_balance": 12.5,
                "devices": [],
            },
            {
                "devices": [{"id": "device-1"}],
                "charging_sessions": [{"device_id": "device-1"}],
                "completed_dispatches": [],
            },
        )

        self.assertEqual(merged["account_number"], "account-1")
        self.assertEqual(merged["electricity_balance"], 12.5)
        self.assertEqual(merged["devices"], [{"id": "device-1"}])
        self.assertEqual(merged["charging_sessions"], [{"device_id": "device-1"}])

    def test_empty_account_data_preserves_sensor_data_contract(self) -> None:
        account_data = create_empty_account_data("account-123")["account-123"]

        self.assertEqual(account_data["account_number"], "account-123")
        self.assertEqual(account_data["products"], [])
        self.assertEqual(account_data["devices"], [])
        self.assertIsNone(account_data["meter"])
        self.assertIsNone(account_data["gas_meter"])

    def test_process_ledgers_converts_and_groups_balances(self) -> None:
        balances = process_ledgers(
            [
                {"ledgerType": "ELECTRICITY_LEDGER", "balance": 1234},
                {"ledgerType": "GAS_LEDGER", "balance": 500},
                {"ledgerType": "HEAT_LEDGER", "balance": -75},
                {"ledgerType": "OTHER_LEDGER", "balance": 25},
            ]
        )

        self.assertEqual(balances["electricity_balance"], 12.34)
        self.assertEqual(balances["gas_balance"], 5)
        self.assertEqual(balances["heat_balance"], -0.75)
        self.assertEqual(balances["other_ledgers"], {"OTHER_LEDGER": 0.25})

    def test_normalize_direct_products_preserves_rate_and_identity(self) -> None:
        products = normalize_direct_products(
            [
                {
                    "code": "DYNAMIC-DE",
                    "fullName": "Dynamic Electricity",
                    "grossRateInformation": {"grossRate": "27.3"},
                    "isTimeOfUse": True,
                }
            ]
        )

        self.assertEqual(products[0]["code"], "DYNAMIC-DE")
        self.assertEqual(products[0]["grossRate"], "27.3")
        self.assertTrue(products[0]["isTimeOfUse"])

    def test_normalize_timeslots_preserves_rates_and_activation_rules(self) -> None:
        timeslots = normalize_timeslots(
            [
                {
                    "timeslotName": "GO",
                    "grossRateInformation": [{"grossRate": "12.5"}],
                    "timeslotActivationRules": [
                        {"activeFromTime": "00:00:00", "activeToTime": "04:00:00"}
                    ],
                },
                {
                    "timeslotName": "STANDARD",
                    "latestGrossUnitRateCentsPerKwh": "30.0",
                },
            ]
        )

        self.assertEqual(extract_gross_rate({"grossRate": "1.5"}), "1.5")
        self.assertEqual(timeslots[0]["rate"], "12.5")
        self.assertEqual(timeslots[0]["activation_rules"][0]["from_time"], "00:00:00")
        self.assertEqual(timeslots[1]["rate"], "30.0")

    def test_normalize_unit_rate_forecast_filters_invalid_entries(self) -> None:
        forecast = normalize_unit_rate_forecast(
            [{"validFrom": "2026-01-01"}, "invalid", None]
        )

        self.assertEqual(forecast, [{"validFrom": "2026-01-01"}])
        self.assertEqual(normalize_unit_rate_forecast(None), [])

    def test_get_product_type_handles_simple_and_time_of_use_rates(self) -> None:
        self.assertEqual(
            get_product_type({"__typename": "SimpleProductUnitRateInformation"}),
            "Simple",
        )
        self.assertEqual(
            get_product_type({"__typename": "TimeOfUseProductUnitRateInformation"}),
            "TimeOfUse",
        )
        self.assertEqual(get_product_type({}), "Simple")

    def test_extract_meter_data_preserves_electricity_and_gas_fields(self) -> None:
        meter_data = extract_meter_data(
            {
                "allProperties": [
                    {
                        "id": "property-1",
                        "electricityMalos": [
                            {
                                "maloNumber": "DE0001",
                                "meters": [
                                    {
                                        "id": "meter-1",
                                        "meloNumber": "DE0002",
                                    }
                                ],
                            }
                        ],
                        "gasMalos": [
                            {
                                "maloNumber": "DE0003",
                                "meters": [
                                    {
                                        "id": "meter-2",
                                        "meloNumber": "DE0004",
                                    }
                                ],
                            }
                        ],
                    }
                ]
            }
        )

        self.assertEqual(meter_data["property_ids"], ["property-1"])
        self.assertEqual(meter_data["malo_number"], "DE0001")
        self.assertEqual(meter_data["melo_number"], "DE0002")
        self.assertEqual(
            meter_data["meter"],
            {"id": "meter-1", "meloNumber": "DE0002"},
        )
        self.assertEqual(meter_data["gas_malo_number"], "DE0003")
        self.assertEqual(meter_data["gas_melo_number"], "DE0004")
        self.assertEqual(
            meter_data["gas_meter"],
            {"id": "meter-2", "meloNumber": "DE0004"},
        )

    def test_extract_device_data_uses_first_valid_battery_size(self) -> None:
        device_data = extract_device_data(
            {
                "devices": [
                    {"id": "vehicle-1", "vehicleVariant": {"batterySize": "bad"}},
                    {"id": "vehicle-2", "vehicleVariant": {"batterySize": "54.5"}},
                ]
            }
        )

        self.assertEqual(device_data["devices"][0]["id"], "vehicle-1")
        self.assertEqual(device_data["vehicle_battery_size_in_kwh"], 54.5)

    def test_calculate_dispatch_state_skips_invalid_dates(self) -> None:
        state = calculate_dispatch_state(
            [
                {"start": "not-a-date", "end": "not-a-date"},
                {
                    "start": "2099-01-01T10:00:00+00:00",
                    "end": "2099-01-01T11:00:00+00:00",
                },
            ]
        )

        self.assertIsNone(state["current_start"])
        self.assertIsNone(state["current_end"])
        self.assertIsNotNone(state["next_start"])
        self.assertIsNotNone(state["next_end"])

    def test_extract_charging_sessions_adds_compatibility_fields(self) -> None:
        sessions = extract_charging_sessions(
            [
                {
                    "id": "vehicle-1",
                    "name": "Car",
                    "deviceType": "VEHICLE",
                    "chargingSessions": {
                        "edges": [
                            {
                                "node": {
                                    "stateOfChargeFinal": 80,
                                    "stateOfChargeChange": 20,
                                }
                            }
                        ]
                    },
                }
            ]
        )

        self.assertEqual(len(sessions), 1)
        self.assertEqual(sessions[0]["soc_final"], 80)
        self.assertEqual(sessions[0]["soc_change"], 20)
        self.assertEqual(sessions[0]["device_id"], "vehicle-1")
        self.assertIn(
            "completedDispatches(accountNumber: $accountNumber) "
            "@include(if: $includeIntelligent)",
            COMPREHENSIVE_QUERY,
        )
        self.assertIn(
            "devices(accountNumber: $accountNumber) @include(if: $includeIntelligent)",
            COMPREHENSIVE_QUERY,
        )


if __name__ == "__main__":
    unittest.main()
