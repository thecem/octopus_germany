"""Regression coverage for combined-price forecasts and Recorder serialization."""

# ruff: noqa: INP001, PT009

import json
import unittest
from unittest.mock import Mock, patch

import homeassistant  # noqa: F401
from homeassistant.components.recorder.db_schema import (
    MAX_STATE_ATTRS_BYTES,
    StateAttributes,
)
from homeassistant.core import Event, State

from custom_components.octopus_germany.entities.electricity import (
    OctopusCombinedElectricityPriceSensor,
)


class CombinedPriceRecorderTest(unittest.TestCase):
    """Verify the live forecast stays available without overflowing Recorder."""

    def test_large_forecast_is_live_but_not_recorded(self) -> None:
        """Check live state, unit retention, and excluded Recorder attributes."""
        sensor = OctopusCombinedElectricityPriceSensor(
            "account-test", Mock(last_update_success=True, data={})
        )
        forecast = [
            {
                "label": f"Tariff interval {index}",
                "combined_price_gross_eur_per_kwh": 0.25 + index / 10000,
                "combined_price_gross_eur_per_kwh_display": "0.25000000",
                "base_price_gross_eur_per_kwh_display": "0.25000000",
                "active_grid_fee_net_eur_per_kwh_display": "0.05000000",
                "intervals": [
                    {
                        "start": "2026-10-22T00:00:00+02:00",
                        "end": "2026-10-22T00:15:00+02:00",
                    }
                ],
            }
            for index in range(96)
        ]
        components = {
            "combined_price_eur_per_kwh": 0.25,
            "price_combinations": forecast,
        }
        with patch.object(sensor, "_price_components", return_value=components):
            attributes = {
                **sensor.extra_state_attributes,
                "unit_of_measurement": sensor.native_unit_of_measurement,
                "state_class": sensor.state_class,
            }
            self.assertGreater(
                len(json.dumps(attributes).encode()), MAX_STATE_ATTRS_BYTES
            )
            self.assertEqual(sensor.native_value, 0.25)
            self.assertIs(sensor.extra_state_attributes["price_combinations"], forecast)

            before = State("sensor.test_combined_price", "0.25", attributes)
            event = Event("state_changed", {"new_state": before})
            with self.assertLogs(
                "homeassistant.components.recorder.db_schema", "WARNING"
            ):
                self.assertEqual(
                    StateAttributes.shared_attrs_bytes_from_event(event, None), b"{}"
                )

            after = State(
                "sensor.test_combined_price",
                str(sensor.native_value),
                attributes,
                state_info={
                    "unrecorded_attributes": sensor._unrecorded_attributes,  # noqa: SLF001
                },
            )
            event = Event("state_changed", {"new_state": after})
            with self.assertNoLogs(
                "homeassistant.components.recorder.db_schema", "WARNING"
            ):
                encoded = StateAttributes.shared_attrs_bytes_from_event(event, None)

        recorded = json.loads(encoded)
        self.assertLess(len(encoded), MAX_STATE_ATTRS_BYTES)
        self.assertNotIn("price_combinations", recorded)
        self.assertEqual(recorded["unit_of_measurement"], "€/kWh")
        self.assertEqual(recorded["state_class"], sensor.state_class)
        self.assertEqual(recorded["combined_price_eur_per_kwh"], 0.25)
        self.assertEqual(after.state, "0.25")
        self.assertEqual(len(after.attributes["price_combinations"]), 96)
