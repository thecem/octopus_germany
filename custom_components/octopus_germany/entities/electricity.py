"""Electricity entities for the Octopus Germany integration."""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any

from homeassistant.components.sensor import (
    SensorDeviceClass,
    SensorEntity,
    SensorStateClass,
)
from homeassistant.core import callback
from homeassistant.helpers.device_registry import DeviceEntryType
from homeassistant.helpers.entity import DeviceInfo, EntityCategory
from homeassistant.helpers.event import async_track_point_in_time
from homeassistant.helpers.update_coordinator import CoordinatorEntity
from homeassistant.util.dt import now as local_now

from custom_components.octopus_germany.const import DOMAIN
from custom_components.octopus_germany.tariff import (
    format_uk_rates,
    get_active_grid_fee,
    get_active_timeslot_rate,
    get_current_forecast_rate,
    get_next_grid_fee_change,
    get_next_price_change,
    is_product_current,
    is_time_between,
    parse_tariff_time,
)

if TYPE_CHECKING:
    from datetime import time

    from custom_components.octopus_germany.coordinator import OctopusDataCoordinator

_LOGGER = logging.getLogger(__name__)


def _account_device_info(account_number: str) -> DeviceInfo:
    """Return the account service device shared by electricity entities."""
    return DeviceInfo(
        identifiers={(DOMAIN, account_number)},
        name=f"Octopus Energy Germany ({account_number})",
        manufacturer="Octopus Energy Germany",
        configuration_url="https://my.octopusenergy.de/",
        entry_type=DeviceEntryType.SERVICE,
    )


def _agreement_attributes(products: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Return compact attributes for all historical and scheduled agreements."""
    return [
        {
            "code": product.get("code"),
            "name": product.get("name"),
            "type": product.get("type"),
            "is_active": product.get("isActive"),
            "is_revoked": product.get("isRevoked"),
            "is_terminated": product.get("isTerminated"),
            "valid_from": product.get("validFrom"),
            "valid_to": product.get("validTo"),
            "prices": product.get("prices") or [],
        }
        for product in products
    ]


class OctopusSection14aModuleSensor(CoordinatorEntity, SensorEntity):
    """Expose the section 14a module reported by the OE backend."""

    def __init__(
        self, account_number: str, coordinator: OctopusDataCoordinator
    ) -> None:
        """Initialize the module sensor."""
        super().__init__(coordinator)
        self._account_number = account_number
        self._attr_name = f"Octopus {account_number} Section 14a Module"
        self._attr_unique_id = f"octopus_{account_number}_14a_module"
        self._attr_icon = "mdi:transmission-tower"
        self._attr_entity_category = EntityCategory.DIAGNOSTIC
        self._attr_has_entity_name = False

    def _data(self) -> dict[str, Any]:
        """Return the current normalized grid fee data."""
        if not self.coordinator.data:
            return {}
        return (
            self.coordinator.data.get(self._account_number, {}).get(
                "variable_grid_fees"
            )
            or {}
        )

    @property
    def native_value(self) -> str | None:
        """Return the module exactly as reported by OE."""
        return self._data().get("module")

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        """Return the source and grid operator information."""
        data = self._data()
        return {
            "source": "OE backend",
            "grid_operator_code": data.get("grid_operator_code"),
            "grid_operator_name": data.get("grid_operator_name"),
            "rate_count": len(data.get("rates") or []),
        }

    @property
    def available(self) -> bool:
        """Return whether OE supplied a module value."""
        return bool(self._data().get("module"))

    @property
    def device_info(self) -> DeviceInfo:
        """Return account device information."""
        return _account_device_info(self._account_number)


class OctopusVariableGridFeeSensor(CoordinatorEntity, SensorEntity):
    """Expose the currently active variable grid fee component."""

    def __init__(
        self, account_number: str, coordinator: OctopusDataCoordinator
    ) -> None:
        """Initialize the variable grid fee sensor."""
        super().__init__(coordinator)
        self._account_number = account_number
        self._attr_name = f"Octopus {account_number} Variable Grid Fee"
        self._attr_unique_id = f"octopus_{account_number}_variable_grid_fee"
        self._attr_device_class = SensorDeviceClass.MONETARY
        self._attr_native_unit_of_measurement = "€/kWh"
        self._attr_icon = "mdi:transmission-tower-export"
        self._attr_suggested_display_precision = 4
        self._attr_has_entity_name = False
        self._cancel_boundary_update = None

    def _data(self) -> dict[str, Any]:
        """Return the current normalized grid fee data."""
        if not self.coordinator.data:
            return {}
        return (
            self.coordinator.data.get(self._account_number, {}).get(
                "variable_grid_fees"
            )
            or {}
        )

    @property
    def native_value(self) -> float | None:
        """Return the currently active grid fee in EUR per kWh."""
        active_rate = get_active_grid_fee(self._data())
        return active_rate.get("rate_eur_per_kwh") if active_rate else None

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        """Return active period and complete daily grid fee schedule."""
        data = self._data()
        active_rate = get_active_grid_fee(data)
        next_change = get_next_grid_fee_change(data)
        return {
            "module": data.get("module"),
            "rate_type": active_rate.get("rate_type") if active_rate else None,
            "interval_start": active_rate.get("start_time") if active_rate else None,
            "interval_end": active_rate.get("end_time") if active_rate else None,
            "next_change": next_change.isoformat() if next_change else None,
            "valid_from": active_rate.get("valid_from") if active_rate else None,
            "valid_to": active_rate.get("valid_to") if active_rate else None,
            "grid_operator_code": data.get("grid_operator_code"),
            "grid_operator_name": data.get("grid_operator_name"),
            "rates": data.get("rates") or [],
        }

    @property
    def available(self) -> bool:
        """Return whether a grid fee is active."""
        return get_active_grid_fee(self._data()) is not None

    async def async_added_to_hass(self) -> None:
        """Schedule the first local tariff-boundary update."""
        await super().async_added_to_hass()
        self._schedule_boundary_update()

    async def async_will_remove_from_hass(self) -> None:
        """Cancel the local tariff-boundary update."""
        if self._cancel_boundary_update:
            self._cancel_boundary_update()
            self._cancel_boundary_update = None
        await super().async_will_remove_from_hass()

    @callback
    def _handle_coordinator_update(self) -> None:
        """Refresh state and reschedule the next tariff boundary."""
        self._schedule_boundary_update()
        self.async_write_ha_state()

    @callback
    def _handle_boundary_update(self, _now: Any) -> None:
        """Write state when the locally calculated tariff period changes."""
        self._cancel_boundary_update = None
        self.async_write_ha_state()
        self._schedule_boundary_update()

    @callback
    def _schedule_boundary_update(self) -> None:
        """Schedule an update at the end of the active tariff period."""
        if self._cancel_boundary_update:
            self._cancel_boundary_update()
            self._cancel_boundary_update = None
        next_change = get_next_grid_fee_change(self._data())
        if next_change and self.hass:
            self._cancel_boundary_update = async_track_point_in_time(
                self.hass, self._handle_boundary_update, next_change
            )

    @property
    def device_info(self) -> DeviceInfo:
        """Return account device information."""
        return _account_device_info(self._account_number)


class OctopusElectricityPriceSensor(CoordinatorEntity, SensorEntity):
    """Sensor for Octopus Germany electricity price."""

    def __init__(
        self, account_number: str, coordinator: OctopusDataCoordinator
    ) -> None:
        """Initialize the electricity price sensor."""
        super().__init__(coordinator)

        self._account_number = account_number
        self._attr_name = f"Octopus {account_number} Electricity Price"
        self._attr_unique_id = f"octopus_{account_number}_electricity_price"
        self._attr_device_class = SensorDeviceClass.MONETARY
        self._attr_native_unit_of_measurement = "€/kWh"
        self._attr_state_class = SensorStateClass.TOTAL
        self._attr_has_entity_name = False
        self._attributes = {}
        self._cancel_price_update = None

        # Initialize attributes right after creation
        self._update_attributes()

    async def async_added_to_hass(self) -> None:
        """Schedule the first local price-boundary update."""
        await super().async_added_to_hass()
        self._schedule_price_update()

    async def async_will_remove_from_hass(self) -> None:
        """Cancel the local price-boundary update."""
        if self._cancel_price_update:
            self._cancel_price_update()
            self._cancel_price_update = None
        await super().async_will_remove_from_hass()

    def _parse_time(self, time_str: str) -> time:
        """Parse time string in HH:MM:SS format to time object."""
        return parse_tariff_time(time_str)

    def _is_time_between(
        self, current_time: time, time_from: time, time_to: time
    ) -> bool:
        """Check if current_time is between time_from and time_to."""
        return is_time_between(current_time, time_from, time_to)

    @property
    def native_value(self) -> float:
        """Return the current electricity price."""
        if (
            not self.coordinator.data
            or not isinstance(self.coordinator.data, dict)
            or self._account_number not in self.coordinator.data
        ):
            _LOGGER.warning("No valid coordinator data found for price sensor")
            return None

        account_data = self.coordinator.data[self._account_number]
        products = account_data.get("products", [])

        if not products:
            _LOGGER.warning("No products found in coordinator data")
            return None

        # Find the current valid product based on validity dates
        valid_products = []

        # First filter products that are currently valid
        for product in products:
            valid_from = product.get("validFrom")

            # Skip products without validity information
            if not valid_from:
                continue

            # Check if product is currently valid
            if is_product_current(product):
                valid_products.append(product)

        # If we have valid products, use the one with the latest validFrom
        if valid_products:
            # Sort by validFrom in descending order to get the most recent one
            valid_products.sort(key=lambda p: p.get("validFrom", ""), reverse=True)
            current_product = valid_products[0]

            product_code = current_product.get("code", "Unknown")
            product_type = current_product.get("type", "Unknown")

            _LOGGER.debug(
                "Using product: %s, type: %s, valid from: %s",
                product_code,
                product_type,
                current_product.get("validFrom", "Unknown"),
            )

            if current_product.get("isTimeOfUse", False):
                # For dynamic TimeOfUse tariffs, use unitRateForecast data
                forecast_rate = get_current_forecast_rate(current_product)
                if forecast_rate is not None:
                    _LOGGER.debug(
                        "Dynamic forecast price: %.4f EUR/kWh for product %s",
                        forecast_rate,
                        product_code,
                    )
                    return forecast_rate

                # Fallback to timeslot rate if no forecast available
                if product_type == "TimeOfUse":
                    active_rate = get_active_timeslot_rate(current_product)
                    if active_rate is not None:
                        _LOGGER.debug(
                            "Fallback timeslot price: %.4f EUR/kWh for product %s",
                            active_rate,
                            product_code,
                        )
                        return active_rate

            # For simple tariffs or fallback, use the gross rate
            try:
                gross_rate_str = current_product.get("grossRate", "0")
                gross_rate = float(gross_rate_str)
                # Convert from cents to EUR without rounding
                base_rate_eur = gross_rate / 100.0

                _LOGGER.debug(
                    "Price: %.4f EUR/kWh for product %s", base_rate_eur, product_code
                )
                return base_rate_eur
            except (ValueError, TypeError) as e:
                _LOGGER.warning(
                    "Failed to convert price for product %s: %s - %s",
                    product_code,
                    current_product.get("grossRate", "Unknown"),
                    str(e),
                )

        _LOGGER.warning("No valid product found for current date")
        return None

    def _update_attributes(self) -> None:
        """Update the internal attributes dictionary."""
        # Default empty attributes
        default_attributes = {
            "code": "Unknown",
            "name": "Unknown",
            "description": "Unknown",
            "type": "Unknown",
            "valid_from": "Unknown",
            "valid_to": "Unknown",
            "meter_id": "Unknown",
            "meter_number": "Unknown",
            "meter_type": "Unknown",
            "account_number": self._account_number,
            "agreements": [],
        }

        # Check if coordinator has valid data
        if (
            not self.coordinator
            or not self.coordinator.data
            or not isinstance(self.coordinator.data, dict)
        ):
            _LOGGER.debug("No valid data structure in coordinator")
            self._attributes = default_attributes
            return

        # Check if account number exists in the data
        if self._account_number not in self.coordinator.data:
            _LOGGER.debug(
                "Account %s not found in coordinator data", self._account_number
            )
            self._attributes = default_attributes
            return

        # Process data from the coordinator
        account_data = self.coordinator.data[self._account_number]
        products = account_data.get("products", [])

        # Extract meter information directly
        meter_data = account_data.get("meter", {})
        meter_id = "Unknown"
        meter_number = "Unknown"
        meter_type = "Unknown"

        if meter_data and isinstance(meter_data, dict):
            meter_id = meter_data.get("id", "Unknown")
            meter_number = meter_data.get("number", "Unknown")
            meter_type = meter_data.get("meterType", "Unknown")
            _LOGGER.debug(
                "Found meter info: id=%s, number=%s, type=%s",
                meter_id,
                meter_number,
                meter_type,
            )

        if not products:
            self._attributes = {
                **default_attributes,
                "meter_id": meter_id,
                "meter_number": meter_number,
                "meter_type": meter_type,
            }
            return

        # Find the current valid product based on validity dates
        valid_products = []

        # First filter products that are currently valid
        for product in products:
            valid_from = product.get("validFrom")

            # Skip products without validity information
            if not valid_from:
                continue

            # Check if product is currently valid
            if is_product_current(product):
                valid_products.append(product)

        # If we have valid products, use the one with the latest validFrom
        if valid_products:
            # Sort by validFrom in descending order to get the most recent one
            valid_products.sort(key=lambda p: p.get("validFrom", ""), reverse=True)
            current_product = valid_products[0]

            # Extract attribute values from the product
            product_attributes = {
                "code": current_product.get("code", "Unknown"),
                "name": current_product.get("name", "Unknown"),
                "description": current_product.get("description", "Unknown"),
                "type": current_product.get("type", "Unknown"),
                "valid_from": current_product.get("validFrom", "Unknown"),
                "valid_to": current_product.get("validTo", "Unknown"),
                "meter_id": meter_id,
                "meter_number": meter_number,
                "meter_type": meter_type,
                "account_number": self._account_number,
                "active_tariff_type": current_product.get("type", "Unknown"),
                "agreement_is_active": current_product.get("isActive"),
                "agreement_is_revoked": current_product.get("isRevoked"),
                "agreement_is_terminated": current_product.get("isTerminated"),
                "agreement_prices": current_product.get("prices") or [],
                "agreements": _agreement_attributes(products),
            }

            # Add time-of-use specific information if available
            if (
                current_product.get("type") == "TimeOfUse"
                and "timeslots" in current_product
            ):
                current_time = local_now().time()
                active_timeslot = None
                timeslots_data = []

                # Get information about all timeslots and find active one
                for timeslot in current_product.get("timeslots", []):
                    timeslot_data = {
                        "name": timeslot.get("name", "Unknown"),
                        "rate": timeslot.get("rate", "0"),
                        "activation_rules": [],
                    }

                    # Add all activation rules
                    for rule in timeslot.get("activation_rules", []):
                        from_time = rule.get("from_time", "00:00:00")
                        to_time = rule.get("to_time", "00:00:00")
                        timeslot_data["activation_rules"].append(
                            {"from_time": from_time, "to_time": to_time}
                        )

                        # Check if this is the active timeslot
                        from_time_obj = self._parse_time(from_time)
                        to_time_obj = self._parse_time(to_time)
                        if (
                            from_time_obj
                            and to_time_obj
                            and self._is_time_between(
                                current_time, from_time_obj, to_time_obj
                            )
                        ):
                            active_timeslot = timeslot.get("name", "Unknown")
                            product_attributes["active_timeslot"] = active_timeslot
                            # Store the rate without rounding.
                            # Convert from cents to euros.
                            product_attributes["active_timeslot_rate"] = (
                                float(timeslot.get("rate", "0")) / 100.0
                            )
                            product_attributes["active_timeslot_from"] = from_time
                            product_attributes["active_timeslot_to"] = to_time

                    timeslots_data.append(timeslot_data)

                product_attributes["timeslots"] = timeslots_data

            # Add any additional information from account data
            product_attributes["malo_number"] = account_data.get(
                "malo_number", "Unknown"
            )
            product_attributes["melo_number"] = account_data.get(
                "melo_number", "Unknown"
            )

            # Add electricity balance if available
            if "electricity_balance" in account_data:
                product_attributes["electricity_balance"] = (
                    f"{account_data['electricity_balance']:.2f} €"
                )

            # Add dual format rate data for compatibility
            if current_product.get("isTimeOfUse", False):
                # UK format for octopus-energy-rates-card compatibility
                uk_rates = format_uk_rates(current_product)
                product_attributes["rates"] = uk_rates
                product_attributes["rates_count"] = len(uk_rates)

                # German format for native tools
                product_attributes["unit_rate_forecast"] = current_product.get(
                    "unitRateForecast", []
                )

            self._attributes = product_attributes
        else:
            # If no valid products, use default attributes
            self._attributes = {
                **default_attributes,
                "meter_id": meter_id,
                "meter_number": meter_number,
                "meter_type": meter_type,
                "agreements": _agreement_attributes(products),
            }

    def _format_uk_rates(self, product: dict[str, Any]) -> list[dict[str, Any]]:
        """Format unitRateForecast data into UK-style rates attribute."""
        if not product:
            return []

        unit_rate_forecast = product.get("unitRateForecast", [])
        if not unit_rate_forecast:
            return []

        all_rates = []

        for forecast_entry in unit_rate_forecast:
            valid_from_str = forecast_entry.get("validFrom")
            valid_to_str = forecast_entry.get("validTo")

            if not valid_from_str or not valid_to_str:
                continue

            try:
                # Extract rate information
                unit_rate_info = forecast_entry.get("unitRateInformation", {})
                price_eur_kwh = None

                if (
                    unit_rate_info.get("__typename")
                    == "SimpleProductUnitRateInformation"
                ):
                    rate_cents = unit_rate_info.get("latestGrossUnitRateCentsPerKwh")
                    if rate_cents is not None:
                        price_eur_kwh = float(rate_cents) / 100.0

                elif (
                    unit_rate_info.get("__typename")
                    == "TimeOfUseProductUnitRateInformation"
                ):
                    rates = unit_rate_info.get("rates", [])
                    if rates and len(rates) > 0:
                        rate_cents = rates[0].get("latestGrossUnitRateCentsPerKwh")
                        if rate_cents is not None:
                            price_eur_kwh = float(rate_cents) / 100.0

                if price_eur_kwh is not None:
                    all_rates.append(
                        {
                            "start": valid_from_str,
                            "end": valid_to_str,
                            "value_inc_vat": round(price_eur_kwh, 4),
                        }
                    )

            except (ValueError, TypeError) as e:
                _LOGGER.debug("Error processing forecast entry: %s", e)
                continue

        # Sort by start time
        all_rates.sort(key=lambda x: x["start"])

        _LOGGER.debug("Formatted %d rates for UK compatibility", len(all_rates))
        return all_rates

    @callback
    def _handle_coordinator_update(self) -> None:
        """Handle updated data from the coordinator."""
        self._update_attributes()
        self._schedule_price_update()
        self.async_write_ha_state()

    @callback
    def _handle_price_update(self, _now: Any) -> None:
        """Write state when the active product price period changes."""
        self._cancel_price_update = None
        self._update_attributes()
        self.async_write_ha_state()
        self._schedule_price_update()

    @callback
    def _schedule_price_update(self) -> None:
        """Schedule a local update at the next product price boundary."""
        if self._cancel_price_update:
            self._cancel_price_update()
            self._cancel_price_update = None
        if not self.hass or not self.coordinator.data:
            return
        account_data = self.coordinator.data.get(self._account_number, {})
        products = account_data.get("products", [])
        current_product = next(
            (
                product
                for product in sorted(
                    products,
                    key=lambda product: product.get("validFrom", ""),
                    reverse=True,
                )
                if is_product_current(product)
            ),
            None,
        )
        if current_product:
            next_change = get_next_price_change(current_product)
            if next_change:
                self._cancel_price_update = async_track_point_in_time(
                    self.hass, self._handle_price_update, next_change
                )

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        """Return additional state attributes for the sensor."""
        return self._attributes

    async def async_update(self) -> None:
        """Update the entity."""
        await super().async_update()
        self._update_attributes()

    @property
    def available(self) -> bool:
        """Return True if entity is available."""
        return (
            self.coordinator is not None
            and self.coordinator.last_update_success
            and isinstance(self.coordinator.data, dict)
            and self._account_number in self.coordinator.data
        )

    @property
    def device_info(self) -> DeviceInfo:
        """Return device information."""
        return DeviceInfo(
            identifiers={(DOMAIN, self._account_number)},
            name=f"Octopus Energy Germany ({self._account_number})",
            manufacturer="Octopus Energy Germany",
            configuration_url="https://my.octopusenergy.de/",
            entry_type=DeviceEntryType.SERVICE,
        )
