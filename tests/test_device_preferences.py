"""Regression tests for device charging preference updates."""

import asyncio
import unittest
from unittest.mock import AsyncMock, Mock, patch

from homeassistant.core import ServiceCall
from homeassistant.exceptions import ServiceValidationError

from custom_components.octopus_germany.binary_sensor import OctopusPluggedInBinarySensor
from custom_components.octopus_germany.const import DOMAIN
from custom_components.octopus_germany.octopus_germany import OctopusGermany
from custom_components.octopus_germany.service_handlers import (
    _resolve_octopus_device_id,
    async_register_services,
)

DEVICE_ID = "00000000-0002-4000-803c-000000000000"
DAYS = (
    "MONDAY",
    "TUESDAY",
    "WEDNESDAY",
    "THURSDAY",
    "FRIDAY",
    "SATURDAY",
    "SUNDAY",
)


class DevicePreferencesTest(unittest.TestCase):
    """Verify mutation serialization and service success handling."""

    def setUp(self) -> None:
        """Create an API client without starting background token refresh."""
        self.api = object.__new__(OctopusGermany)
        self.api.ensure_token = AsyncMock(return_value=True)
        self.client = Mock(
            execute_async=AsyncMock(
                return_value={"data": {"setDevicePreferences": {"id": DEVICE_ID}}}
            )
        )
        self.api._get_graphql_client = Mock(return_value=self.client)  # noqa: SLF001

    def test_all_weekday_targets_are_strings(self) -> None:
        for percentage in (20, 90, 100):
            with self.subTest(percentage=percentage):
                assert asyncio.run(
                    self.api.set_device_preferences(DEVICE_ID, percentage, "07:00:00")
                )
                query = self.client.execute_async.await_args.kwargs["query"]
                for day in DAYS:
                    assert (
                        f'{{ dayOfWeek: {day}, time: "07:00", max: "{percentage}" }}'
                        in query
                    )
                assert query.count("max:") == len(DAYS)
                assert f'deviceId: "{DEVICE_ID}"' in query
                assert "mode: CHARGE" in query
                assert "unit: PERCENTAGE" in query

    def test_missing_mutation_confirmation_is_failure(self) -> None:
        for response in (
            {},
            {"data": None},
            {"data": {}},
            {"data": {"setDevicePreferences": None}},
            {"data": {"setDevicePreferences": {}}},
            {"data": {"setDevicePreferences": {"id": None}}},
        ):
            with self.subTest(response=response):
                self.client.execute_async.return_value = response
                assert not asyncio.run(
                    self.api.set_device_preferences(DEVICE_ID, 90, "07:00")
                )

    def test_graphql_error_is_failure(self) -> None:
        self.client.execute_async.return_value = {
            "errors": [
                {
                    "message": "Unable to set device preferences",
                    "extensions": {"errorCode": "KT-CT-4374"},
                }
            ]
        }
        assert not asyncio.run(self.api.set_device_preferences(DEVICE_ID, 90, "07:00"))

    def test_invalid_percentage_is_not_sent(self) -> None:
        for percentage in (15, 91, 105):
            with self.subTest(percentage=percentage):
                assert not asyncio.run(
                    self.api.set_device_preferences(DEVICE_ID, percentage, "07:00")
                )
        self.client.execute_async.assert_not_awaited()

    def test_resolves_home_assistant_device_id_to_octopus_id(self) -> None:
        device_registry = Mock()
        device_registry.devices.get.return_value = Mock(
            identifiers={(DOMAIN, f"device_{DEVICE_ID}")}
        )

        with patch(
            "custom_components.octopus_germany.service_handlers.dr.async_get",
            return_value=device_registry,
        ):
            resolved = _resolve_octopus_device_id(Mock(), "ha-device-registry-id")

        assert resolved == DEVICE_ID

    def test_vehicle_plugged_sensor_has_selector_device_class(self) -> None:
        coordinator = Mock(
            data={
                "account-1": {
                    "devices": [{"id": DEVICE_ID}],
                }
            }
        )
        sensor = OctopusPluggedInBinarySensor(
            "account-1", coordinator, DEVICE_ID, "Volkswagen ID.4"
        )

        assert sensor.device_class.value == "plug"
        assert sensor.device_info["identifiers"] == {(DOMAIN, f"device_{DEVICE_ID}")}

    def test_preserves_legacy_octopus_device_id(self) -> None:
        device_registry = Mock()
        device_registry.devices.get.return_value = None

        with patch(
            "custom_components.octopus_germany.service_handlers.dr.async_get",
            return_value=device_registry,
        ):
            resolved = _resolve_octopus_device_id(Mock(), DEVICE_ID)

        assert resolved == DEVICE_ID

    def test_service_maps_dropdown_device_to_octopus_id(self) -> None:
        async def exercise_service() -> None:
            hass = Mock()
            await async_register_services(hass, Mock(), self.api, Mock(), None)
            handler = next(
                call.args[2]
                for call in hass.services.async_register.call_args_list
                if call.args[1] == "set_device_preferences"
            )
            registry = Mock()
            registry.devices.get.return_value = Mock(
                identifiers={(DOMAIN, f"device_{DEVICE_ID}")}
            )
            service_call = ServiceCall(
                hass,
                DOMAIN,
                "set_device_preferences",
                {
                    "device_id": "ha-device-registry-id",
                    "target_percentage": 90,
                    "target_time": "07:00",
                },
            )
            with (
                patch(
                    "custom_components.octopus_germany.service_handlers.dr.async_get",
                    return_value=registry,
                ),
                patch(
                    "custom_components.octopus_germany.service_handlers."
                    "async_request_intelligent_refresh",
                    new_callable=AsyncMock,
                ),
            ):
                assert await handler(service_call) == {"success": True}

            query = self.client.execute_async.await_args.kwargs["query"]
            assert f'deviceId: "{DEVICE_ID}"' in query

        asyncio.run(exercise_service())

    def test_service_refreshes_only_after_confirmed_success(self) -> None:
        async def exercise_service() -> None:
            hass = Mock()
            await async_register_services(hass, Mock(), self.api, Mock(), None)
            handler = next(
                call.args[2]
                for call in hass.services.async_register.call_args_list
                if call.args[1] == "set_device_preferences"
            )
            service_call = ServiceCall(
                hass,
                DOMAIN,
                "set_device_preferences",
                {
                    "device_id": DEVICE_ID,
                    "target_percentage": 90,
                    "target_time": "07:00",
                },
            )
            with (
                patch(
                    "custom_components.octopus_germany.service_handlers."
                    "async_request_intelligent_refresh",
                    new_callable=AsyncMock,
                ) as refresh,
                patch(
                    "custom_components.octopus_germany.service_handlers.dr.async_get",
                    return_value=Mock(devices=Mock(get=Mock(return_value=None))),
                ),
            ):
                assert await handler(service_call) == {"success": True}
                refresh.assert_awaited_once_with(hass)
                refresh.reset_mock()
                self.client.execute_async.return_value = {
                    "data": {"setDevicePreferences": None}
                }
                with self.assertRaises(ServiceValidationError):
                    await handler(service_call)
                refresh.assert_not_awaited()

        asyncio.run(exercise_service())
