"""
This module provides integration with Octopus Germany for Home Assistant.

It defines the coordinator and sensor entities to fetch and display
electricity price information.
"""

import logging
from typing import Any, Dict, List
from datetime import datetime, time

from homeassistant.components.sensor import (
    SensorEntity,
    SensorStateClass,
    SensorDeviceClass,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import DOMAIN

_LOGGER = logging.getLogger(__name__)


async def async_setup_entry(
    hass: HomeAssistant, entry: ConfigEntry, async_add_entities: AddEntitiesCallback
) -> None:
    """Set up Octopus Germany price sensors from a config entry."""
    # Using existing coordinator from hass.data[DOMAIN] to avoid duplicate API calls
    data = hass.data[DOMAIN][entry.entry_id]
    coordinator = data["coordinator"]
    account_number = data["account_number"]

    # Wait for coordinator refresh if needed
    if coordinator.data is None:
        _LOGGER.debug("No data in coordinator, triggering refresh")
        await coordinator.async_refresh()

    # Debug log to see the complete data structure
    if coordinator.data:
        _LOGGER.debug("Coordinator data keys: %s", coordinator.data.keys())

    # Initialize entities list
    entities = []

    # Get all account numbers from entry data or coordinator data
    account_numbers = entry.data.get("account_numbers", [])
    if not account_numbers and account_number:
        account_numbers = [account_number]

    # If still no account numbers, try to get them from coordinator data
    if not account_numbers and coordinator.data:
        account_numbers = list(coordinator.data.keys())

    _LOGGER.debug("Creating sensors for accounts: %s", account_numbers)

    # Create sensors for each account
    for acc_num in account_numbers:
        if (
            coordinator.data
            and acc_num in coordinator.data
            and "products" in coordinator.data[acc_num]
        ):
            products = coordinator.data[acc_num].get("products")
            if products:
                _LOGGER.debug(
                    "Creating electricity price sensor for account %s with %d products",
                    acc_num,
                    len(products),
                )
                entities.append(OctopusElectricityPriceSensor(acc_num, coordinator))

                # Also create sensors for other ledger types if they exist
                account_data = coordinator.data[acc_num]

                # Create gas balance sensor if gas ledger exists
                if account_data.get("gas_balance", 0) != 0:
                    entities.append(OctopusGasBalanceSensor(acc_num, coordinator))

                # Create gas tariff sensor if gas products exist
                gas_products = account_data.get("gas_products", [])
                if gas_products:
                    _LOGGER.debug(
                        "Creating gas tariff sensor for account %s with %d gas products",
                        acc_num,
                        len(gas_products),
                    )
                    entities.append(OctopusGasTariffSensor(acc_num, coordinator))

                # Create gas infrastructure sensors if gas data exists
                if account_data.get("gas_malo_number"):
                    entities.append(OctopusGasMaloSensor(acc_num, coordinator))

                if account_data.get("gas_melo_number"):
                    entities.append(OctopusGasMeloSensor(acc_num, coordinator))

                if account_data.get("gas_meter"):
                    entities.append(OctopusGasMeterSensor(acc_num, coordinator))

                # Create gas latest reading sensor if gas reading data exists
                if account_data.get("gas_latest_reading"):
                    entities.append(OctopusGasLatestReadingSensor(acc_num, coordinator))

                # Create heat balance sensor if heat ledger exists
                if account_data.get("heat_balance", 0) != 0:
                    entities.append(OctopusHeatBalanceSensor(acc_num, coordinator))

                # Create sensors for other ledgers
                other_ledgers = account_data.get("other_ledgers", {})
                for ledger_type, balance in other_ledgers.items():
                    if balance != 0:
                        entities.append(
                            OctopusLedgerBalanceSensor(
                                acc_num, coordinator, ledger_type
                            )
                        )

            else:
                _LOGGER.warning(
                    "Not creating electricity price sensor due to empty products list for account %s",
                    acc_num,
                )
        else:
            if coordinator.data is None:
                _LOGGER.error("No coordinator data available")
            elif acc_num not in coordinator.data:
                _LOGGER.warning("Account %s missing from coordinator data", acc_num)
            elif "products" not in coordinator.data[acc_num]:
                _LOGGER.warning(
                    "No 'products' key in coordinator data for account %s", acc_num
                )
            else:
                _LOGGER.warning(
                    "Unknown issue detecting products for account %s", acc_num
                )

    # Only add entities if we have any
    if entities:
        _LOGGER.debug(
            "Adding %d entities: %s",
            len(entities),
            [type(e).__name__ for e in entities],
        )
        async_add_entities(entities)
    else:
        _LOGGER.warning("No entities to add for any account")


class OctopusElectricityPriceSensor(CoordinatorEntity, SensorEntity):
    """Sensor for Octopus Germany electricity price."""

    def __init__(self, account_number, coordinator) -> None:
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

        # Initialize attributes right after creation
        self._update_attributes()

    def _parse_time(self, time_str: str) -> time:
        """Parse time string in HH:MM:SS format to time object."""
        try:
            hour, minute, second = map(int, time_str.split(":"))
            return time(hour=hour, minute=minute, second=second)
        except (ValueError, AttributeError):
            _LOGGER.error(f"Invalid time format: {time_str}")
            return None

    def _is_time_between(
        self, current_time: time, time_from: time, time_to: time
    ) -> bool:
        """Check if current_time is between time_from and time_to."""
        # Handle special case where time_to is 00:00:00 (midnight)
        if time_to.hour == 0 and time_to.minute == 0 and time_to.second == 0:
            # If time_from is also midnight, the slot is active all day
            if time_from.hour == 0 and time_from.minute == 0 and time_from.second == 0:
                return True
            # Otherwise, the slot is active from time_from until midnight, or from midnight until time_from
            return current_time >= time_from or current_time < time_to
        # Normal case: check if time is between start and end
        elif time_from <= time_to:
            return time_from <= current_time < time_to
        # Handle case where range crosses midnight
        else:
            return time_from <= current_time or current_time < time_to

    def _get_active_timeslot_rate(self, product):
        """Get the currently active timeslot rate for a time-of-use product."""
        if not product:
            return None

        # For SimpleProductUnitRateInformation, just return the single rate
        if product.get("type") == "Simple":
            try:
                # Convert to float but don't round - divide by 100 to convert from cents to euros
                return float(product.get("grossRate", "0")) / 100.0
            except (ValueError, TypeError):
                return None

        # For TimeOfUseProductUnitRateInformation, find the currently active timeslot
        if product.get("type") == "TimeOfUse" and "timeslots" in product:
            current_time = datetime.now().time()

            for timeslot in product["timeslots"]:
                for rule in timeslot.get("activation_rules", []):
                    from_time = self._parse_time(rule.get("from_time", "00:00:00"))
                    to_time = self._parse_time(rule.get("to_time", "00:00:00"))

                    if (
                        from_time
                        and to_time
                        and self._is_time_between(current_time, from_time, to_time)
                    ):
                        try:
                            # Convert to float but don't round - divide by 100 to convert from cents to euros
                            return float(timeslot.get("rate", "0")) / 100.0
                        except (ValueError, TypeError):
                            continue

        # If no active timeslot found or in case of errors, return None
        return None

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
        now = datetime.now().isoformat()
        valid_products = []

        # First filter products that are currently valid
        for product in products:
            valid_from = product.get("validFrom")
            valid_to = product.get("validTo")

            # Skip products without validity information
            if not valid_from:
                continue

            # Check if product is currently valid
            if valid_from <= now and (not valid_to or now <= valid_to):
                valid_products.append(product)

        # If we have valid products, use the one with the latest validFrom
        if valid_products:
            # Sort by validFrom in descending order to get the most recent one
            valid_products.sort(key=lambda p: p.get("validFrom", ""), reverse=True)
            current_product = valid_products[0]

            _LOGGER.debug(
                "Using product: %s, type: %s, valid from: %s",
                current_product.get("code", "Unknown"),
                current_product.get("type", "Unknown"),
                current_product.get("validFrom", "Unknown"),
            )

            # For time-of-use tariffs, get the currently active timeslot rate
            if current_product.get("type") == "TimeOfUse":
                active_rate = self._get_active_timeslot_rate(current_product)
                if active_rate is not None:
                    return active_rate

            # For simple tariffs or fallback, just use the gross rate
            try:
                gross_rate_str = current_product.get("grossRate", "0")
                gross_rate = float(gross_rate_str)
                # Convert from cents to EUR without rounding
                gross_rate_eur = gross_rate / 100.0

                _LOGGER.debug(
                    "Using price: %s cents = %s EUR for product %s",
                    gross_rate_str,
                    gross_rate_eur,
                    current_product.get("code", "Unknown"),
                )

                return gross_rate_eur
            except (ValueError, TypeError) as e:
                _LOGGER.warning(
                    "Failed to convert price for product %s: %s - %s",
                    current_product.get("code", "Unknown"),
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
                f"Found meter info: id={meter_id}, number={meter_number}, type={meter_type}"
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
        now = datetime.now().isoformat()
        valid_products = []

        # First filter products that are currently valid
        for product in products:
            valid_from = product.get("validFrom")
            valid_to = product.get("validTo")

            # Skip products without validity information
            if not valid_from:
                continue

            # Check if product is currently valid
            if valid_from <= now and (not valid_to or now <= valid_to):
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
            }

            # Add time-of-use specific information if available
            if (
                current_product.get("type") == "TimeOfUse"
                and "timeslots" in current_product
            ):
                current_time = datetime.now().time()
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
                            # Store the rate without rounding (convert from cents to euros)
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

            self._attributes = product_attributes
        else:
            # If no valid products, use default attributes
            self._attributes = {
                **default_attributes,
                "meter_id": meter_id,
                "meter_number": meter_number,
                "meter_type": meter_type,
            }

    @callback
    def _handle_coordinator_update(self) -> None:
        """Handle updated data from the coordinator."""
        self._update_attributes()
        self.async_write_ha_state()

    @property
    def extra_state_attributes(self) -> Dict[str, Any]:
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


class OctopusGasBalanceSensor(CoordinatorEntity, SensorEntity):
    """Sensor for Octopus Germany gas balance."""

    def __init__(self, account_number, coordinator) -> None:
        """Initialize the gas balance sensor."""
        super().__init__(coordinator)

        self._account_number = account_number
        self._attr_name = f"Octopus {account_number} Gas Balance"
        self._attr_unique_id = f"octopus_{account_number}_gas_balance"
        self._attr_device_class = SensorDeviceClass.MONETARY
        self._attr_native_unit_of_measurement = "€"
        self._attr_state_class = SensorStateClass.TOTAL
        self._attr_has_entity_name = False

    @property
    def native_value(self) -> float:
        """Return the gas balance."""
        if (
            not self.coordinator.data
            or not isinstance(self.coordinator.data, dict)
            or self._account_number not in self.coordinator.data
        ):
            return None

        account_data = self.coordinator.data[self._account_number]
        return account_data.get("gas_balance", 0.0)

    @property
    def available(self) -> bool:
        """Return True if entity is available."""
        return (
            self.coordinator is not None
            and self.coordinator.last_update_success
            and isinstance(self.coordinator.data, dict)
            and self._account_number in self.coordinator.data
        )


class OctopusHeatBalanceSensor(CoordinatorEntity, SensorEntity):
    """Sensor for Octopus Germany heat balance."""

    def __init__(self, account_number, coordinator) -> None:
        """Initialize the heat balance sensor."""
        super().__init__(coordinator)

        self._account_number = account_number
        self._attr_name = f"Octopus {account_number} Heat Balance"
        self._attr_unique_id = f"octopus_{account_number}_heat_balance"
        self._attr_device_class = SensorDeviceClass.MONETARY
        self._attr_native_unit_of_measurement = "€"
        self._attr_state_class = SensorStateClass.TOTAL
        self._attr_has_entity_name = False

    @property
    def native_value(self) -> float:
        """Return the heat balance."""
        if (
            not self.coordinator.data
            or not isinstance(self.coordinator.data, dict)
            or self._account_number not in self.coordinator.data
        ):
            return None

        account_data = self.coordinator.data[self._account_number]
        return account_data.get("heat_balance", 0.0)

    @property
    def available(self) -> bool:
        """Return True if entity is available."""
        return (
            self.coordinator is not None
            and self.coordinator.last_update_success
            and isinstance(self.coordinator.data, dict)
            and self._account_number in self.coordinator.data
        )


class OctopusLedgerBalanceSensor(CoordinatorEntity, SensorEntity):
    """Sensor for Octopus Germany generic ledger balance."""

    def __init__(self, account_number, coordinator, ledger_type) -> None:
        """Initialize the ledger balance sensor."""
        super().__init__(coordinator)

        self._account_number = account_number
        self._ledger_type = ledger_type
        ledger_name = ledger_type.replace("_LEDGER", "").replace("_", " ").title()
        self._attr_name = f"Octopus {account_number} {ledger_name} Balance"
        self._attr_unique_id = f"octopus_{account_number}_{ledger_type.lower()}_balance"
        self._attr_device_class = SensorDeviceClass.MONETARY
        self._attr_native_unit_of_measurement = "€"
        self._attr_state_class = SensorStateClass.TOTAL
        self._attr_has_entity_name = False

    @property
    def native_value(self) -> float:
        """Return the ledger balance."""
        if (
            not self.coordinator.data
            or not isinstance(self.coordinator.data, dict)
            or self._account_number not in self.coordinator.data
        ):
            return None

        account_data = self.coordinator.data[self._account_number]
        other_ledgers = account_data.get("other_ledgers", {})
        return other_ledgers.get(self._ledger_type, 0.0)

    @property
    def available(self) -> bool:
        """Return True if entity is available."""
        return (
            self.coordinator is not None
            and self.coordinator.last_update_success
            and isinstance(self.coordinator.data, dict)
            and self._account_number in self.coordinator.data
        )


class OctopusGasTariffSensor(CoordinatorEntity, SensorEntity):
    """Sensor for Octopus Germany gas tariff."""

    def __init__(self, account_number, coordinator) -> None:
        """Initialize the gas tariff sensor."""
        super().__init__(coordinator)

        self._account_number = account_number
        self._attr_name = f"Octopus {account_number} Gas Tariff"
        self._attr_unique_id = f"octopus_{account_number}_gas_tariff"
        self._attr_has_entity_name = False
        self._attributes = {}

        # Initialize attributes right after creation
        self._update_attributes()

    @property
    def native_value(self) -> str | None:
        """Return the current gas tariff code."""
        if (
            not self.coordinator.data
            or not isinstance(self.coordinator.data, dict)
            or self._account_number not in self.coordinator.data
        ):
            _LOGGER.warning("No valid coordinator data found for gas tariff sensor")
            return None

        account_data = self.coordinator.data[self._account_number]
        gas_products = account_data.get("gas_products", [])

        if not gas_products:
            _LOGGER.warning("No gas products found in coordinator data")
            return None

        # Find the current valid product based on validity dates
        now = datetime.now().isoformat()
        valid_products = []

        # First filter products that are currently valid
        for product in gas_products:
            valid_from = product.get("validFrom")
            valid_to = product.get("validTo")

            # Skip products without validity information
            if not valid_from:
                continue

            # Check if product is currently valid
            if valid_from <= now and (not valid_to or now <= valid_to):
                valid_products.append(product)

        # If we have valid products, use the one with the latest validFrom
        if valid_products:
            # Sort by validFrom in descending order to get the most recent one
            valid_products.sort(key=lambda p: p.get("validFrom", ""), reverse=True)
            current_product = valid_products[0]

            return current_product.get("code", "Unknown")

        _LOGGER.warning("No valid gas product found for current date")
        return None

    def _update_attributes(self) -> None:
        """Update the internal attributes dictionary."""
        # Default empty attributes - only tariff-specific info
        default_attributes = {
            "code": "Unknown",
            "name": "Unknown",
            "description": "Unknown",
            "type": "Unknown",
            "valid_from": "Unknown",
            "valid_to": "Unknown",
            "account_number": self._account_number,
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
        gas_products = account_data.get("gas_products", [])

        if not gas_products:
            self._attributes = default_attributes
            return

        # Find the current valid product based on validity dates
        now = datetime.now().isoformat()
        valid_products = []

        # First filter products that are currently valid
        for product in gas_products:
            valid_from = product.get("validFrom")
            valid_to = product.get("validTo")

            # Skip products without validity information
            if not valid_from:
                continue

            # Check if product is currently valid
            if valid_from <= now and (not valid_to or now <= valid_to):
                valid_products.append(product)

        # If we have valid products, use the one with the latest validFrom
        if valid_products:
            # Sort by validFrom in descending order to get the most recent one
            valid_products.sort(key=lambda p: p.get("validFrom", ""), reverse=True)
            current_product = valid_products[0]

            # Extract attribute values from the product - only tariff info
            product_attributes = {
                "code": current_product.get("code", "Unknown"),
                "name": current_product.get("name", "Unknown"),
                "description": current_product.get("description", "Unknown"),
                "type": current_product.get("type", "Unknown"),
                "valid_from": current_product.get("validFrom", "Unknown"),
                "valid_to": current_product.get("validTo", "Unknown"),
                "account_number": self._account_number,
            }

            # Add gas balance if available
            if "gas_balance" in account_data:
                product_attributes["gas_balance"] = (
                    f"{account_data['gas_balance']:.2f} €"
                )

            self._attributes = product_attributes
        else:
            # If no valid products, use default attributes
            self._attributes = default_attributes

    @callback
    def _handle_coordinator_update(self) -> None:
        """Handle updated data from the coordinator."""
        self._update_attributes()
        self.async_write_ha_state()

    @property
    def extra_state_attributes(self) -> Dict[str, Any]:
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


class OctopusGasMaloSensor(CoordinatorEntity, SensorEntity):
    """Sensor for Octopus Germany gas MALO number."""

    def __init__(self, account_number, coordinator) -> None:
        """Initialize the gas MALO sensor."""
        super().__init__(coordinator)

        self._account_number = account_number
        self._attr_name = f"Octopus {account_number} Gas MALO Number"
        self._attr_unique_id = f"octopus_{account_number}_gas_malo_number"
        self._attr_has_entity_name = False

    @property
    def native_value(self) -> str | None:
        """Return the gas MALO number."""
        if (
            not self.coordinator.data
            or not isinstance(self.coordinator.data, dict)
            or self._account_number not in self.coordinator.data
        ):
            return None

        account_data = self.coordinator.data[self._account_number]
        return account_data.get("gas_malo_number")

    @property
    def available(self) -> bool:
        """Return True if entity is available."""
        return (
            self.coordinator is not None
            and self.coordinator.last_update_success
            and isinstance(self.coordinator.data, dict)
            and self._account_number in self.coordinator.data
            and self.coordinator.data[self._account_number].get("gas_malo_number")
            is not None
        )


class OctopusGasMeloSensor(CoordinatorEntity, SensorEntity):
    """Sensor for Octopus Germany gas MELO number."""

    def __init__(self, account_number, coordinator) -> None:
        """Initialize the gas MELO sensor."""
        super().__init__(coordinator)

        self._account_number = account_number
        self._attr_name = f"Octopus {account_number} Gas MELO Number"
        self._attr_unique_id = f"octopus_{account_number}_gas_melo_number"
        self._attr_has_entity_name = False

    @property
    def native_value(self) -> str | None:
        """Return the gas MELO number."""
        if (
            not self.coordinator.data
            or not isinstance(self.coordinator.data, dict)
            or self._account_number not in self.coordinator.data
        ):
            return None

        account_data = self.coordinator.data[self._account_number]
        return account_data.get("gas_melo_number")

    @property
    def available(self) -> bool:
        """Return True if entity is available."""
        return (
            self.coordinator is not None
            and self.coordinator.last_update_success
            and isinstance(self.coordinator.data, dict)
            and self._account_number in self.coordinator.data
            and self.coordinator.data[self._account_number].get("gas_melo_number")
            is not None
        )


class OctopusGasMeterSensor(CoordinatorEntity, SensorEntity):
    """Sensor for Octopus Germany gas meter information."""

    def __init__(self, account_number, coordinator) -> None:
        """Initialize the gas meter sensor."""
        super().__init__(coordinator)

        self._account_number = account_number
        self._attr_name = f"Octopus {account_number} Gas Meter"
        self._attr_unique_id = f"octopus_{account_number}_gas_meter"
        self._attr_has_entity_name = False
        self._attributes = {}

        # Initialize attributes right after creation
        self._update_attributes()

    @property
    def native_value(self) -> str | None:
        """Return the gas meter number."""
        if (
            not self.coordinator.data
            or not isinstance(self.coordinator.data, dict)
            or self._account_number not in self.coordinator.data
        ):
            return None

        account_data = self.coordinator.data[self._account_number]
        gas_meter = account_data.get("gas_meter", {})

        if gas_meter and isinstance(gas_meter, dict):
            return gas_meter.get("number", None)

        return None

    def _update_attributes(self) -> None:
        """Update the internal attributes dictionary."""
        default_attributes = {
            "meter_id": "Unknown",
            "meter_number": "Unknown",
            "meter_type": "Unknown",
            "account_number": self._account_number,
        }

        if (
            not self.coordinator.data
            or not isinstance(self.coordinator.data, dict)
            or self._account_number not in self.coordinator.data
        ):
            self._attributes = default_attributes
            return

        account_data = self.coordinator.data[self._account_number]
        gas_meter = account_data.get("gas_meter", {})

        if gas_meter and isinstance(gas_meter, dict):
            self._attributes = {
                "meter_id": gas_meter.get("id", "Unknown"),
                "meter_number": gas_meter.get("number", "Unknown"),
                "meter_type": gas_meter.get("meterType", "Unknown"),
                "account_number": self._account_number,
            }
        else:
            self._attributes = default_attributes

    @callback
    def _handle_coordinator_update(self) -> None:
        """Handle updated data from the coordinator."""
        self._update_attributes()
        self.async_write_ha_state()

    @property
    def extra_state_attributes(self) -> Dict[str, Any]:
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
            and self.coordinator.data[self._account_number].get("gas_meter") is not None
        )


class OctopusGasLatestReadingSensor(CoordinatorEntity, SensorEntity):
    """Sensor for Octopus Germany latest gas meter reading."""

    def __init__(self, account_number, coordinator) -> None:
        """Initialize the gas latest reading sensor."""
        super().__init__(coordinator)

        self._account_number = account_number
        self._attr_name = f"Octopus {account_number} Gas Latest Reading"
        self._attr_unique_id = f"octopus_{account_number}_gas_latest_reading"
        self._attr_device_class = SensorDeviceClass.GAS
        self._attr_has_entity_name = False
        self._attributes = {}

        # Initialize attributes right after creation
        self._update_attributes()

    @property
    def native_value(self) -> float | None:
        """Return the latest gas meter reading value."""
        if (
            not self.coordinator.data
            or not isinstance(self.coordinator.data, dict)
            or self._account_number not in self.coordinator.data
        ):
            return None

        account_data = self.coordinator.data[self._account_number]
        gas_reading = account_data.get("gas_latest_reading")

        if gas_reading and isinstance(gas_reading, dict):
            try:
                reading_value = gas_reading.get("value")
                if reading_value is not None:
                    return float(reading_value)
            except (ValueError, TypeError):
                _LOGGER.warning("Invalid gas meter reading value: %s", reading_value)

        return None

    @property
    def native_unit_of_measurement(self) -> str | None:
        """Return the unit of measurement."""
        # Since the GraphQL API doesn't provide units directly for gas readings,
        # we default to m³ which is the standard for gas consumption in Germany
        return "m³"

    def _update_attributes(self) -> None:
        """Update the internal attributes dictionary."""
        default_attributes = {
            "reading_value": "Unknown",
            "reading_units": "m³",
            "reading_date": "Unknown",
            "reading_origin": "Unknown",
            "reading_type": "Unknown",
            "register_obis_code": "Unknown",
            "meter_id": "Unknown",
            "account_number": self._account_number,
        }

        if (
            not self.coordinator.data
            or not isinstance(self.coordinator.data, dict)
            or self._account_number not in self.coordinator.data
        ):
            self._attributes = default_attributes
            return

        account_data = self.coordinator.data[self._account_number]
        gas_reading = account_data.get("gas_latest_reading")

        if gas_reading and isinstance(gas_reading, dict):
            # Extract reading date from readAt
            reading_date = gas_reading.get("readAt")

            # Format the date if available
            if reading_date:
                try:
                    from datetime import datetime

                    # Try to parse and format the date
                    parsed_date = datetime.fromisoformat(
                        reading_date.replace("Z", "+00:00")
                    )
                    reading_date = parsed_date.strftime("%Y-%m-%d %H:%M:%S")
                except (ValueError, AttributeError):
                    # Keep original date if parsing fails
                    pass

            self._attributes = {
                "reading_value": gas_reading.get("value", "Unknown"),
                "reading_units": "m³",
                "reading_date": reading_date or "Unknown",
                "reading_origin": gas_reading.get("origin", "Unknown"),
                "reading_type": gas_reading.get("typeOfRead", "Unknown"),
                "register_obis_code": gas_reading.get("registerObisCode", "Unknown"),
                "meter_id": gas_reading.get("meterId", "Unknown"),
                "read_at": gas_reading.get("readAt", "Unknown"),
                "account_number": self._account_number,
            }
        else:
            self._attributes = default_attributes

    @callback
    def _handle_coordinator_update(self) -> None:
        """Handle updated data from the coordinator."""
        self._update_attributes()
        self.async_write_ha_state()

    @property
    def extra_state_attributes(self) -> Dict[str, Any]:
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
            and self.coordinator.data[self._account_number].get("gas_latest_reading")
            is not None
        )
