"""Tests for tariff capability detection and conditional API fields."""

import asyncio
import unittest
from datetime import UTC, date, datetime
from unittest.mock import AsyncMock, Mock, patch

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
    normalize_agreement_prices,
    normalize_agreement_products,
    normalize_direct_products,
    normalize_timeslots,
    normalize_unit_rate_forecast,
    process_ledgers,
)
from custom_components.octopus_germany.entities.electricity import (
    OctopusElectricityPriceSensor,
    OctopusSection14aModuleSensor,
    OctopusVariableGridFeeSensor,
)
from custom_components.octopus_germany.lifecycle import (
    _migrate_legacy_device_entity_ids,
)
from custom_components.octopus_germany.models import (
    TariffCapabilities,
    account_has_electricity,
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
    TokenManager,
)
from custom_components.octopus_germany.sensor import (
    OctopusSmartChargingSessionsSensor,
    _create_device_entities,
)
from custom_components.octopus_germany.service_handlers import (
    _group_readings_by_local_date,
    _measurement_range_bounds,
    _summarize_measurement_metadata,
)
from custom_components.octopus_germany.services import (
    async_handle_refresh_intelligent_data,
    async_request_intelligent_refresh,
)
from custom_components.octopus_germany.switch import (
    BoostChargeSwitch,
    OctopusSwitch,
    _get_intelligent_devices,
)
from custom_components.octopus_germany.tariff import (
    format_uk_rates,
    get_active_grid_fee,
    get_active_timeslot_rate,
    get_current_forecast_rate,
    get_next_grid_fee_change,
    get_next_price_change,
    is_product_current,
    normalize_variable_grid_fees,
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

        assert capabilities.has_dynamic_prices
        assert capabilities.has_smart_meter
        assert not capabilities.has_intelligent_dispatches

    def test_normalize_update_interval_applies_default_and_bounds(self) -> None:
        assert normalize_update_interval("invalid", 30) == 30
        assert normalize_update_interval(0, 30) == 1
        assert normalize_update_interval(90, 30) == 60
        assert normalize_update_interval("5", 30) == 5

    def test_intelligent_entity_gate_requires_capability(self) -> None:
        assert not has_intelligent_capability({"devices": [{"id": "x"}]})
        assert has_intelligent_capability(
            {"tariff_capabilities": {"has_intelligent_dispatches": True}}
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

        assert [account["number"] for account in active_accounts] == [
            "gas",
            "electricity",
        ]
        assert select_primary_account(active_accounts) == "electricity"

    def test_account_has_electricity_uses_discovery_ledgers(self) -> None:
        assert account_has_electricity(
            {"ledgers": [{"ledgerType": "ELECTRICITY_LEDGER"}]}
        )
        assert not account_has_electricity({"ledgers": [{"ledgerType": "GAS_LEDGER"}]})

    def test_device_entity_factory_skips_standard_tariffs(self) -> None:
        assert (
            _create_device_entities(
                "account-1", {"devices": [{"id": "device-1"}]}, Mock()
            )
            == []
        )

    def test_binary_entity_factory_skips_standard_tariffs(self) -> None:
        assert (
            _create_intelligent_binary_entities(
                "account-1", {"devices": [{"id": "device-1"}]}, Mock()
            )
            == []
        )

    def test_switch_device_gate_skips_standard_tariffs(self) -> None:
        assert _get_intelligent_devices({"devices": [{"id": "device-1"}]}) == []

    def test_tariff_helpers_calculate_simple_and_timeslot_rates(self) -> None:
        assert get_active_timeslot_rate({"type": "Simple", "grossRate": "25"}) == 0.25
        assert (
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
            )
            == 0.1
        )

    def test_product_validity_compares_instants_not_iso_strings(self) -> None:
        product = {
            "validFrom": "2026-09-07T00:00:00+00:00",
            "validTo": "2026-09-07T22:00:00+00:00",
        }

        assert is_product_current(
            product, datetime.fromisoformat("2026-09-07T21:00:00+00:00")
        )
        assert not is_product_current(
            product, datetime.fromisoformat("2026-09-07T23:00:00+00:00")
        )

    def test_next_price_change_uses_local_timeslot_boundary(self) -> None:
        product = {
            "type": "TimeOfUse",
            "timeslots": [
                {"activation_rules": [{"from_time": "00:00:00", "to_time": "05:00:00"}]}
            ],
        }

        current_time = datetime.fromisoformat("2026-09-07T04:40:00+02:00")

        assert get_next_price_change(product, current_time) == datetime.fromisoformat(
            "2026-09-07T05:00:00+02:00"
        )

    def test_timeslot_default_uses_home_assistant_local_time(self) -> None:
        local_time = datetime.fromisoformat("2026-07-01T02:30:00+02:00")
        product = {
            "type": "TimeOfUse",
            "timeslots": [
                {
                    "rate": "10",
                    "activation_rules": [
                        {"from_time": "02:00:00", "to_time": "05:00:00"}
                    ],
                }
            ],
        }

        with patch(
            "custom_components.octopus_germany.tariff.local_now",
            return_value=local_time,
        ):
            assert get_active_timeslot_rate(product) == 0.1

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

        assert rate == 0.2

    def test_forecast_rate_path_keeps_utc_clock_available(self) -> None:
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

        assert rate == 0.2

    def test_forecast_rate_uses_home_assistant_local_time(self) -> None:
        product = {
            "unitRateForecast": [
                {
                    "validFrom": "2025-12-31T23:00:00+00:00",
                    "validTo": "2026-01-01T00:40:00+00:00",
                    "unitRateInformation": {"latestGrossUnitRateCentsPerKwh": "20"},
                }
            ]
        }

        with patch(
            "custom_components.octopus_germany.tariff.local_now",
            return_value=datetime.fromisoformat("2026-01-01T00:30:00+01:00"),
        ):
            assert get_current_forecast_rate(product) == 0.2

    def test_token_validity_uses_epoch_safe_utc_time(self) -> None:
        manager = TokenManager()
        manager.set_token("test-token", datetime.now(UTC).timestamp() + 3600)

        assert manager.is_valid

    def test_token_refresh_retries_after_transient_failure(self) -> None:
        manager = TokenManager()
        refresh = AsyncMock(side_effect=RuntimeError("temporary failure"))
        manager.set_refresh_callback(refresh)

        with patch(
            "custom_components.octopus_germany.octopus_germany.asyncio.sleep",
            new=AsyncMock(side_effect=[None, asyncio.CancelledError()]),
        ):
            asyncio.run(manager._auto_refresh_token())

        refresh.assert_awaited_once_with()

    def test_charging_sessions_sensor_reads_updated_coordinator_data(self) -> None:
        start = datetime.now(UTC).replace(day=1, hour=12, minute=0, second=0)
        session = {
            "device_id": "device-1",
            "device_name": "Car",
            "start": start.isoformat(),
            "energyAdded": {"value": "5.5"},
        }
        coordinator = Mock()
        coordinator.data = {
            "account-1": {"charging_sessions": [session]},
        }
        coordinator.last_update_success = True
        sensor = OctopusSmartChargingSessionsSensor(
            "account-1", coordinator, "Car", "device-1", []
        )

        assert sensor.native_value == 1
        assert sensor.extra_state_attributes["smart_sessions_count"] == 1

        coordinator.data["account-1"]["charging_sessions"] = []

        assert sensor.native_value == 0
        assert sensor.extra_state_attributes["smart_sessions_count"] == 0

    def test_same_named_devices_have_distinct_switch_unique_ids(self) -> None:
        coordinator = Mock()
        coordinator.data = {"account-1": {"devices": []}}
        api = Mock()
        entry = Mock()

        first = {
            "id": "device-1",
            "name": "Tesla Model Y",
            "status": {"isSuspended": False},
        }
        second = {**first, "id": "device-2"}

        first_smart_control = OctopusSwitch(api, first, coordinator, entry, "account-1")
        second_smart_control = OctopusSwitch(
            api, second, coordinator, entry, "account-1"
        )
        first_boost = BoostChargeSwitch(
            coordinator, api, "device-1", "Tesla Model Y", "account-1"
        )
        second_boost = BoostChargeSwitch(
            coordinator, api, "device-2", "Tesla Model Y", "account-1"
        )

        assert first_smart_control.unique_id != second_smart_control.unique_id
        assert first_boost.unique_id != second_boost.unique_id
        assert "device-1" in first_smart_control.unique_id
        assert "device-2" in second_smart_control.unique_id

    def test_entity_id_migration_reuses_existing_id_after_duplicate_upgrade(
        self,
    ) -> None:
        class FakeRegistry:
            class FakeEntity(dict):
                @property
                def config_entry_id(self):
                    return self["config_entry_id"]

                @property
                def entity_id(self):
                    return self["entity_id"]

            def __init__(self) -> None:
                self.entities = {
                    "sensor.octopus_energy_germany_account_car_status": self.FakeEntity(
                        {
                            "entity_id": "sensor.octopus_energy_germany_account_car_status",
                            "unique_id": "octopus_account_car_status",
                            "config_entry_id": "entry-1",
                        }
                    ),
                    "sensor.octopus_energy_germany_account_car_status_2": self.FakeEntity(
                        {
                            "entity_id": "sensor.octopus_energy_germany_account_car_status_2",
                            "unique_id": "octopus_account_device-1_status",
                            "config_entry_id": "entry-1",
                        }
                    ),
                }

            def async_get_entity_id(
                self, domain: str, platform: str, unique_id: str
            ) -> str | None:
                del platform
                return next(
                    (
                        entity_id
                        for entity_id, entity in self.entities.items()
                        if entity_id.startswith(f"{domain}.")
                        and entity["unique_id"] == unique_id
                    ),
                    None,
                )

            def async_get(self, entity_id: str) -> dict | None:
                return self.entities.get(entity_id)

            def async_remove(self, entity_id: str) -> None:
                del self.entities[entity_id]

            def async_update_entity(
                self, entity_id: str, *, new_entity_id=None, new_unique_id=None
            ) -> None:
                entity = self.entities.pop(entity_id)
                if new_entity_id:
                    entity["entity_id"] = new_entity_id
                    entity_id = new_entity_id
                if new_unique_id:
                    entity["unique_id"] = new_unique_id
                self.entities[entity_id] = entity

        registry = FakeRegistry()
        hass = Mock()
        entry = Mock(entry_id="entry-1")
        account_data = {
            "devices": [
                {"id": "device-1", "name": "Car"},
            ]
        }

        with patch(
            "custom_components.octopus_germany.lifecycle.er.async_get",
            return_value=registry,
        ):
            _migrate_legacy_device_entity_ids(
                hass,
                entry,
                {"account": account_data},
                ["account"],
            )

        assert list(registry.entities) == [
            "sensor.octopus_energy_germany_account_car_status"
        ]
        assert (
            registry.entities["sensor.octopus_energy_germany_account_car_status"][
                "unique_id"
            ]
            == "octopus_account_device-1_status"
        )

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

        assert rates == [
            {
                "start": "2026-01-01T01:00:00+00:00",
                "end": "2026-01-01T02:00:00+00:00",
                "value_inc_vat": 0.2,
            }
        ]

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

        assert validated[CONF_UPDATE_INTERVAL] == 15
        assert validated[CONF_INTELLIGENT_UPDATE_INTERVAL] == 5

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

        assert validated[CONF_UPDATE_INTERVAL] == 30
        assert validated[CONF_INTELLIGENT_UPDATE_INTERVAL] == 3

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

        assert refreshed == 1
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

        assert "account-1" in result
        assert "account-2" not in result
        assert "account-1" in capabilities_by_account

    def test_fetch_account_data_adds_optional_variable_grid_fees(self) -> None:
        api = Mock()
        api.fetch_tariff_capabilities = AsyncMock(return_value=TariffCapabilities())
        api.fetch_data_for_account = AsyncMock(return_value={"account": {}})
        api.fetch_variable_grid_fees = AsyncMock(
            return_value={
                "module": "MODULE_1",
                "gridFees": [
                    {
                        "gridFeeKwhRateType": "STANDARD",
                        "rateTypeIntervalStart": "06:00:00",
                        "rateTypeIntervalEnd": "23:00:00",
                        "validFrom": "2026-01-01T00:00:00+01:00",
                        "validTo": None,
                        "gridOperatorCode": "operator-1",
                        "gridFeeInCentsPerKwh": "5.480000",
                    }
                ],
            }
        )

        async def process_api_data(data, account_number, api_client):
            return {
                account_number: {
                    "account_number": account_number,
                    "grid_operator_code": "operator-1",
                    "grid_operator_name": "Grid Operator",
                }
            }

        result = asyncio.run(
            _async_fetch_account_data(
                api,
                ["account-1"],
                process_api_data,
                {},
            )
        )

        grid_fees = result["account-1"]["variable_grid_fees"]
        assert grid_fees["module"] == "MODULE_1"
        assert grid_fees["rates"][0]["rate_eur_per_kwh"] == 0.0548
        api.fetch_variable_grid_fees.assert_awaited_once()

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

        assert capabilities.has_intelligent_dispatches

    def test_devices_enable_intelligent_capability(self) -> None:
        capabilities = detect_tariff_capabilities({"devices": [{"id": "vehicle-1"}]})

        assert capabilities.has_intelligent_dispatches

    def test_15min_server_error_enters_backoff(self) -> None:
        api = object.__new__(OctopusGermany)
        api._15min_retry_until = None
        api.ensure_token = AsyncMock(return_value=True)
        client = Mock()
        client.execute_async = AsyncMock(side_effect=RuntimeError("502 HTML"))
        api._get_graphql_client = Mock(return_value=client)

        with self.assertRaises(SmartMeterFetchError):
            asyncio.run(
                api.fetch_electricity_15min_readings(
                    "account-1", "property-1", "2026-09-04"
                )
            )
        assert api._15min_retry_until is not None

        with self.assertRaises(SmartMeterFetchError):
            asyncio.run(
                api.fetch_electricity_15min_readings(
                    "account-1", "property-1", "2026-09-04"
                )
            )
        client.execute_async.assert_awaited_once()

    def test_15min_rate_limit_is_not_reported_as_no_data(self) -> None:
        api = object.__new__(OctopusGermany)
        api._15min_retry_until = None
        api.ensure_token = AsyncMock(return_value=True)
        api._get_graphql_client = Mock(
            return_value=Mock(
                execute_async=AsyncMock(
                    return_value={
                        "errors": [
                            {
                                "message": "Too many requests.",
                                "extensions": {"errorCode": "KT-CT-1199"},
                            }
                        ]
                    }
                )
            )
        )

        with self.assertRaisesRegex(SmartMeterFetchError, "rate limit"):
            asyncio.run(
                api.fetch_electricity_15min_readings(
                    "account-1", "property-1", "2026-09-04"
                )
            )

        assert api._15min_retry_until is not None

    def test_measurement_range_paginates_and_preserves_metadata(self) -> None:
        api = object.__new__(OctopusGermany)
        api._15min_retry_until = None
        api.ensure_token = AsyncMock(return_value=True)
        client = Mock()
        client.execute_async = AsyncMock(
            side_effect=[
                {
                    "data": {
                        "property": {
                            "measurements": {
                                "edges": [
                                    {
                                        "node": {
                                            "__typename": "IntervalMeasurementType",
                                            "source": "meter",
                                            "value": "0E-18",
                                            "unit": "kwh",
                                            "startAt": "2026-09-19T00:00:00+02:00",
                                            "endAt": "2026-09-19T00:15:00+02:00",
                                            "durationInSeconds": 900,
                                            "metaData": {
                                                "utilityFilters": {
                                                    "marketSupplyPointId": "malo-1",
                                                    "deviceId": "meter-1",
                                                    "registerId": "register-1",
                                                    "readingDirection": "CONSUMPTION",
                                                    "readingFrequencyType": (
                                                        "RAW_INTERVAL"
                                                    ),
                                                    "readingQuality": "ACTUAL",
                                                }
                                            },
                                        }
                                    }
                                ],
                                "pageInfo": {
                                    "hasNextPage": True,
                                    "endCursor": "cursor-1",
                                },
                            }
                        }
                    }
                },
                {
                    "data": {
                        "property": {
                            "measurements": {
                                "edges": [],
                                "pageInfo": {
                                    "hasNextPage": False,
                                    "endCursor": "cursor-1",
                                },
                            }
                        }
                    }
                },
            ]
        )
        api._get_graphql_client = Mock(return_value=client)

        readings = asyncio.run(
            api.fetch_electricity_measurements_range(
                "property-1",
                "malo-1",
                "2026-09-18T22:00:00+00:00",
                "2026-09-19T22:00:00+00:00",
                "Europe/Berlin",
                "15min",
            )
        )

        assert len(readings) == 1
        assert readings[0]["value"] == "0E-18"
        assert readings[0]["device_id"] == "meter-1"
        assert readings[0]["reading_quality"] == "ACTUAL"
        assert client.execute_async.await_count == 2
        assert client.execute_async.await_args_list[1].kwargs["variables"]["after"] == (
            "cursor-1"
        )

    def test_measurement_range_reports_rate_limit(self) -> None:
        api = object.__new__(OctopusGermany)
        api._15min_retry_until = None
        api.ensure_token = AsyncMock(return_value=True)
        api._get_graphql_client = Mock(
            return_value=Mock(
                execute_async=AsyncMock(
                    return_value={
                        "errors": [
                            {
                                "message": "Too many requests.",
                                "extensions": {"errorCode": "KT-CT-1199"},
                            }
                        ]
                    }
                )
            )
        )

        with self.assertRaisesRegex(SmartMeterFetchError, "rate limit"):
            asyncio.run(
                api.fetch_electricity_measurements_range(
                    "property-1",
                    "malo-1",
                    "2026-09-18T22:00:00+00:00",
                    "2026-09-19T22:00:00+00:00",
                    "Europe/Berlin",
                    "15min",
                )
            )

        assert api._15min_retry_until is not None

    def test_measurement_range_uses_local_midnights_across_dst(self) -> None:
        assert _measurement_range_bounds(
            date(2026, 10, 25), date(2026, 10, 25), "Europe/Berlin"
        ) == ("2026-10-24T22:00:00+00:00", "2026-10-25T23:00:00+00:00")

    def test_measurements_are_grouped_by_local_start_date(self) -> None:
        grouped = _group_readings_by_local_date(
            [
                {
                    "start_time": "2026-09-18T22:00:00+00:00",
                    "value": "0E-18",
                }
            ],
            "Europe/Berlin",
        )

        assert list(grouped) == ["2026-09-19"]

    def test_measurement_metadata_reports_missing_optional_ids(self) -> None:
        summary = _summarize_measurement_metadata(
            [
                {
                    "source": "meter",
                    "reading_quality": "ACTUAL",
                    "reading_frequency": "RAW_INTERVAL",
                    "device_id": "meter-1",
                    "register_id": None,
                },
                {
                    "source": "estimated",
                    "reading_quality": "ESTIMATED",
                    "reading_frequency": "RAW_INTERVAL",
                    "device_id": None,
                    "register_id": None,
                },
            ]
        )

        assert summary["measurement_count"] == 2
        assert summary["sources"] == ["estimated", "meter"]
        assert summary["reading_qualities"] == ["ACTUAL", "ESTIMATED"]
        assert summary["device_ids"] == ["meter-1"]
        assert summary["missing_device_id_count"] == 1
        assert summary["missing_register_id_count"] == 2

    def test_variable_grid_fees_use_oe_backend_and_daily_cache(self) -> None:
        api = object.__new__(OctopusGermany)
        api._variable_grid_fees_cache = {}
        api.ensure_token = AsyncMock(return_value=True)
        client = Mock(
            execute_async=AsyncMock(
                return_value={
                    "data": {
                        "variableGridFees": {
                            "module": "MODULE_1",
                            "gridFees": [
                                {
                                    "gridFeeKwhRateType": "OFFPEAK",
                                    "gridFeeInCentsPerKwh": "1.64",
                                }
                            ],
                        }
                    }
                }
            )
        )
        api._get_oe_backend_graphql_client = Mock(return_value=client)

        first = asyncio.run(
            api.fetch_variable_grid_fees("account-1", "operator-1", date(2026, 9, 20))
        )
        second = asyncio.run(
            api.fetch_variable_grid_fees("account-1", "operator-1", date(2026, 9, 20))
        )

        assert first == second
        client.execute_async.assert_awaited_once()
        variables = client.execute_async.await_args.kwargs["variables"]
        assert variables == {
            "accountNumber": "account-1",
            "gridOperatorCode": "operator-1",
            "date": "2026-09-20",
        }

    def test_variable_grid_fees_normalize_and_select_local_rate(self) -> None:
        grid_fees = normalize_variable_grid_fees(
            {
                "module": "MODULE_1",
                "gridFees": [
                    {
                        "gridFeeKwhRateType": "PEAK",
                        "rateTypeIntervalStart": "17:00:00",
                        "rateTypeIntervalEnd": "22:00:00",
                        "validFrom": "2026-01-01T00:00:00+01:00",
                        "validTo": None,
                        "gridOperatorCode": "operator-1",
                        "gridFeeInCentsPerKwh": "10.520000",
                    },
                    {
                        "gridFeeKwhRateType": "OFFPEAK",
                        "rateTypeIntervalStart": "23:00:00",
                        "rateTypeIntervalEnd": "00:00:00",
                        "validFrom": "2026-01-01T00:00:00+01:00",
                        "validTo": None,
                        "gridOperatorCode": "operator-1",
                        "gridFeeInCentsPerKwh": "1.640000",
                    },
                ],
            },
            "Grid Operator",
        )

        assert grid_fees["module"] == "MODULE_1"
        assert grid_fees["grid_operator_code"] == "operator-1"
        assert grid_fees["grid_operator_name"] == "Grid Operator"
        assert grid_fees["rates"][0]["rate_eur_per_kwh"] == 0.1052
        assert (
            get_active_grid_fee(
                grid_fees, datetime.fromisoformat("2026-09-20T18:00:00+02:00")
            )["rate_type"]
            == "PEAK"
        )
        assert (
            get_active_grid_fee(
                grid_fees, datetime.fromisoformat("2026-09-20T23:30:00+02:00")
            )["rate_type"]
            == "OFFPEAK"
        )
        assert get_next_grid_fee_change(
            grid_fees, datetime.fromisoformat("2026-09-20T23:30:00+02:00")
        ) == datetime.fromisoformat("2026-09-21T00:00:00+02:00")

    def test_section_14a_sensors_expose_reported_module_and_active_fee(self) -> None:
        coordinator = Mock()
        coordinator.last_update_success = True
        coordinator.data = {
            "account-1": {
                "variable_grid_fees": {
                    "module": "MODULE_1",
                    "grid_operator_name": "Grid Operator",
                    "rates": [
                        {
                            "rate_type": "PEAK",
                            "start_time": "17:00:00",
                            "end_time": "22:00:00",
                            "valid_from": "2026-01-01T00:00:00+01:00",
                            "valid_to": None,
                            "grid_operator_code": "operator-1",
                            "rate_cents_per_kwh": "10.520000",
                            "rate_eur_per_kwh": 0.1052,
                        }
                    ],
                }
            }
        }
        module_sensor = OctopusSection14aModuleSensor("account-1", coordinator)
        fee_sensor = OctopusVariableGridFeeSensor("account-1", coordinator)

        with patch(
            "custom_components.octopus_germany.tariff.local_now",
            return_value=datetime.fromisoformat("2026-09-20T18:00:00+02:00"),
        ):
            assert module_sensor.native_value == "MODULE_1"
            assert module_sensor.extra_state_attributes["rate_count"] == 1
            assert fee_sensor.native_value == 0.1052
            assert fee_sensor.extra_state_attributes["rate_type"] == "PEAK"

    def test_grid_fee_fallback_does_not_override_specific_interval(self) -> None:
        grid_fees = normalize_variable_grid_fees(
            {
                "module": "MODULE_3",
                "gridFees": [
                    {
                        "gridFeeKwhRateType": "STANDARD",
                        "rateTypeIntervalStart": "00:00:00",
                        "rateTypeIntervalEnd": "00:00:00",
                        "gridOperatorCode": "operator-1",
                        "gridFeeInCentsPerKwh": "8.670000",
                    },
                    {
                        "gridFeeKwhRateType": "PEAK",
                        "rateTypeIntervalStart": "17:00:00",
                        "rateTypeIntervalEnd": "21:00:00",
                        "gridOperatorCode": "operator-1",
                        "gridFeeInCentsPerKwh": "13.460000",
                    },
                ],
            },
            "Grid Operator",
        )

        assert (
            get_active_grid_fee(
                grid_fees, datetime.fromisoformat("2026-09-21T17:25:00+02:00")
            )["rate_type"]
            == "PEAK"
        )

    def test_comprehensive_query_makes_intelligent_fields_conditional(self) -> None:
        assert "$includeIntelligent: Boolean!" in COMPREHENSIVE_QUERY
        assert "isActive" in COMPREHENSIVE_QUERY
        assert "isRevoked" in COMPREHENSIVE_QUERY
        assert "isTerminated" in COMPREHENSIVE_QUERY
        assert "netUnitRateCentsPerKwh" in COMPREHENSIVE_QUERY
        assert "vatRate" in COMPREHENSIVE_QUERY
        assert (
            "completedDispatches(accountNumber: $accountNumber)"
            in INTELLIGENT_DATA_QUERY
        )
        assert "devices(accountNumber: $accountNumber)" in INTELLIGENT_DATA_QUERY

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

        assert not capabilities.has_intelligent_dispatches
        assert not capabilities.has_dynamic_prices
        assert not capabilities.has_smart_meter

    def test_data_fetch_uses_cached_capability_to_select_fields(self) -> None:
        api = object.__new__(OctopusGermany)
        api.fetch_tariff_capabilities = AsyncMock(
            return_value=TariffCapabilities(has_intelligent_dispatches=False)
        )
        api.fetch_all_data = AsyncMock(return_value={"account": {}})

        result = asyncio.run(api.fetch_data_for_account("account-123"))

        assert result == {"account": {}}
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
        assert variables["input"]["accountNumber"] == "account-1"
        assert result["success"]

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

        assert len(readings) == 1
        assert api._smart_meter_retry_until is None

    def test_account_discovery_query_requests_account_status(self) -> None:
        assert "status" in ACCOUNT_DISCOVERY_QUERY

    def test_no_fake_product_placeholder_remains(self) -> None:
        from pathlib import Path

        source = Path("custom_components/octopus_germany/__init__.py").read_text()
        assert '"code": "TEST_PRODUCT"' not in source

    def test_intelligent_data_is_skipped_for_standard_tariff(self) -> None:
        api = object.__new__(OctopusGermany)
        api.fetch_tariff_capabilities = AsyncMock(
            return_value=TariffCapabilities(has_intelligent_dispatches=False)
        )

        result = asyncio.run(api.fetch_intelligent_data("account-123"))

        assert result is None

    def test_merge_graphql_responses_adds_intelligent_data(self) -> None:
        base_response = {"data": {"account": {"id": "account-1"}}}
        intelligent_response = {
            "data": {
                "devices": [{"id": "device-1"}],
                "completedDispatches": [],
            }
        }

        merged = merge_graphql_responses(base_response, intelligent_response)

        assert merged["data"]["account"] == {"id": "account-1"}
        assert merged["data"]["devices"] == [{"id": "device-1"}]
        assert "errors" not in merged
        assert "devices" not in base_response["data"]

    def test_merge_graphql_responses_preserves_errors(self) -> None:
        merged = merge_graphql_responses(
            {"data": {}, "errors": [{"message": "base"}]},
            {"data": {}, "errors": [{"message": "intelligent"}]},
        )

        assert [error["message"] for error in merged["errors"]] == [
            "base",
            "intelligent",
        ]

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

        assert merged["account_number"] == "account-1"
        assert merged["electricity_balance"] == 12.5
        assert merged["devices"] == [{"id": "device-1"}]
        assert merged["charging_sessions"] == [{"device_id": "device-1"}]

    def test_empty_account_data_preserves_sensor_data_contract(self) -> None:
        account_data = create_empty_account_data("account-123")["account-123"]

        assert account_data["account_number"] == "account-123"
        assert account_data["products"] == []
        assert account_data["devices"] == []
        assert account_data["meter"] is None
        assert account_data["gas_meter"] is None

    def test_process_ledgers_converts_and_groups_balances(self) -> None:
        balances = process_ledgers(
            [
                {"ledgerType": "ELECTRICITY_LEDGER", "balance": 1234},
                {"ledgerType": "GAS_LEDGER", "balance": 500},
                {"ledgerType": "HEAT_LEDGER", "balance": -75},
                {"ledgerType": "OTHER_LEDGER", "balance": 25},
            ]
        )

        assert balances["electricity_balance"] == 12.34
        assert balances["gas_balance"] == 5
        assert balances["heat_balance"] == -0.75
        assert balances["other_ledgers"] == {"OTHER_LEDGER": 0.25}

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

        assert products[0]["code"] == "DYNAMIC-DE"
        assert products[0]["grossRate"] == "27.3"
        assert products[0]["isTimeOfUse"]

    def test_normalize_agreement_products_handles_electricity_and_gas_shapes(
        self,
    ) -> None:
        account_data = {
            "allProperties": [
                {
                    "electricityMalos": [
                        {
                            "agreements": [
                                {
                                    "product": {"code": "ELEC"},
                                    "unitRateInformation": {
                                        "__typename": "SimpleProductUnitRateInformation",
                                        "latestGrossUnitRateCentsPerKwh": "25",
                                    },
                                    "validFrom": "2026-01-01T00:00:00+00:00",
                                }
                            ]
                        }
                    ],
                    "gasMalos": [
                        {
                            "agreements": [
                                {
                                    "product": {"code": "GAS"},
                                    "unitRateInformation": {
                                        "__typename": "SimpleProductUnitRateInformation",
                                        "grossRateInformation": {"grossRate": "8"},
                                    },
                                    "validFrom": "2026-01-01T00:00:00+00:00",
                                }
                            ]
                        }
                    ],
                }
            ]
        }

        electricity = normalize_agreement_products(account_data, "electricityMalos")
        gas = normalize_agreement_products(account_data, "gasMalos")

        assert electricity[0]["grossRate"] == "25"
        assert gas[0]["grossRate"] == "8"

    def test_agreements_preserve_status_and_gross_net_vat_prices(self) -> None:
        products = normalize_agreement_products(
            {
                "allProperties": [
                    {
                        "electricityMalos": [
                            {
                                "agreements": [
                                    {
                                        "isActive": True,
                                        "isRevoked": False,
                                        "isTerminated": True,
                                        "validFrom": "2025-07-01T00:00:00+02:00",
                                        "validTo": "2026-12-23T00:00:00+01:00",
                                        "product": {
                                            "code": "TOU",
                                            "fullName": "Time of Use",
                                            "isTimeOfUse": True,
                                        },
                                        "unitRateInformation": {
                                            "__typename": (
                                                "TimeOfUseProductUnitRateInformation"
                                            ),
                                            "rates": [
                                                {
                                                    "timeslotName": "GO",
                                                    "latestGrossUnitRateCentsPerKwh": (
                                                        "15.0654"
                                                    ),
                                                    "netUnitRateCentsPerKwh": "12.6600",
                                                    "grossRateInformation": {
                                                        "grossRate": "15.0654",
                                                        "vatRate": "19",
                                                    },
                                                    "timeslotActivationRules": [
                                                        {
                                                            "activeFromTime": (
                                                                "00:00:00"
                                                            ),
                                                            "activeToTime": "05:00:00",
                                                        }
                                                    ],
                                                }
                                            ],
                                        },
                                    },
                                    {
                                        "isActive": False,
                                        "isRevoked": False,
                                        "isTerminated": True,
                                        "validFrom": "2026-12-23T00:00:00+01:00",
                                        "validTo": "2027-12-23T00:00:00+01:00",
                                        "product": {
                                            "code": "FUTURE",
                                            "fullName": "Future Agreement",
                                        },
                                        "unitRateInformation": {
                                            "__typename": (
                                                "SimpleProductUnitRateInformation"
                                            ),
                                            "latestGrossUnitRateCentsPerKwh": (
                                                "33.6651"
                                            ),
                                            "netUnitRateCentsPerKwh": "28.2900",
                                            "grossRateInformation": {
                                                "grossRate": "33.6651",
                                                "vatRate": "19",
                                            },
                                        },
                                    },
                                ]
                            }
                        ]
                    }
                ]
            },
            "electricityMalos",
        )

        assert len(products) == 2
        assert products[0]["isActive"] is True
        assert products[0]["isTerminated"] is True
        assert products[0]["prices"][0]["gross_eur_per_kwh"] == 0.150654
        assert products[0]["prices"][0]["net_eur_per_kwh"] == 0.1266
        assert products[0]["prices"][0]["vat_percent"] == "19"

        coordinator = Mock(last_update_success=True)
        coordinator.data = {
            "account-1": {
                "products": products,
                "meter": {},
            }
        }
        with patch(
            "custom_components.octopus_germany.entities.electricity.is_product_current",
            side_effect=lambda product: product.get("code") == "TOU",
        ):
            sensor = OctopusElectricityPriceSensor("account-1", coordinator)

        agreements = sensor.extra_state_attributes["agreements"]
        assert len(agreements) == 2
        assert agreements[0]["is_active"] is True
        assert agreements[1]["code"] == "FUTURE"
        assert agreements[1]["prices"][0]["gross_eur_per_kwh"] == 0.336651

    def test_price_sensor_keeps_agreements_without_current_product(self) -> None:
        products = [
            {
                "code": "FUTURE",
                "name": "Future Agreement",
                "type": "Simple",
                "validFrom": "2027-01-01T00:00:00+01:00",
                "validTo": "2028-01-01T00:00:00+01:00",
                "prices": [{"gross_eur_per_kwh": 0.3}],
            }
        ]
        coordinator = Mock(
            last_update_success=True,
            data={"account-1": {"products": products, "meter": {}}},
        )

        with patch(
            "custom_components.octopus_germany.entities.electricity.is_product_current",
            return_value=False,
        ):
            sensor = OctopusElectricityPriceSensor("account-1", coordinator)

        assert sensor.extra_state_attributes["agreements"][0]["code"] == "FUTURE"

    def test_normalize_agreement_prices_handles_missing_values(self) -> None:
        prices = normalize_agreement_prices([{"timeslotName": "STANDARD"}])

        assert prices[0]["gross_eur_per_kwh"] is None
        assert prices[0]["net_eur_per_kwh"] is None

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

        assert extract_gross_rate({"grossRate": "1.5"}) == "1.5"
        assert timeslots[0]["rate"] == "12.5"
        assert timeslots[0]["activation_rules"][0]["from_time"] == "00:00:00"
        assert timeslots[1]["rate"] == "30.0"

    def test_normalize_unit_rate_forecast_filters_invalid_entries(self) -> None:
        forecast = normalize_unit_rate_forecast(
            [{"validFrom": "2026-01-01"}, "invalid", None]
        )

        assert forecast == [{"validFrom": "2026-01-01"}]
        assert normalize_unit_rate_forecast(None) == []

    def test_get_product_type_handles_simple_and_time_of_use_rates(self) -> None:
        assert (
            get_product_type({"__typename": "SimpleProductUnitRateInformation"})
            == "Simple"
        )
        assert (
            get_product_type({"__typename": "TimeOfUseProductUnitRateInformation"})
            == "TimeOfUse"
        )
        assert get_product_type({}) == "Simple"

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

        assert meter_data["property_ids"] == ["property-1"]
        assert meter_data["malo_number"] == "DE0001"
        assert meter_data["melo_number"] == "DE0002"
        assert meter_data["meter"] == {"id": "meter-1", "meloNumber": "DE0002"}
        assert meter_data["gas_malo_number"] == "DE0003"
        assert meter_data["gas_melo_number"] == "DE0004"
        assert meter_data["gas_meter"] == {"id": "meter-2", "meloNumber": "DE0004"}

    def test_extract_device_data_uses_first_valid_battery_size(self) -> None:
        device_data = extract_device_data(
            {
                "devices": [
                    {"id": "vehicle-1", "vehicleVariant": {"batterySize": "bad"}},
                    {"id": "vehicle-2", "vehicleVariant": {"batterySize": "54.5"}},
                ]
            }
        )

        assert device_data["devices"][0]["id"] == "vehicle-1"
        assert device_data["vehicle_battery_size_in_kwh"] == 54.5

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

        assert state["current_start"] is None
        assert state["current_end"] is None
        assert state["next_start"] is not None
        assert state["next_end"] is not None

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

        assert len(sessions) == 1
        assert sessions[0]["soc_final"] == 80
        assert sessions[0]["soc_change"] == 20
        assert sessions[0]["device_id"] == "vehicle-1"
        assert (
            "completedDispatches(accountNumber: $accountNumber) "
            "@include(if: $includeIntelligent)" in COMPREHENSIVE_QUERY
        )
        assert (
            "devices(accountNumber: $accountNumber) @include(if: $includeIntelligent)"
            in COMPREHENSIVE_QUERY
        )


if __name__ == "__main__":
    unittest.main()
