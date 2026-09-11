"""Gas and ledger sensor entities for the Octopus Germany integration."""

from __future__ import annotations

import logging
from datetime import date, datetime
from typing import TYPE_CHECKING, Any

from homeassistant.components.sensor import (
    SensorDeviceClass,
    SensorEntity,
    SensorStateClass,
)
from homeassistant.core import callback
from homeassistant.helpers.device_registry import DeviceEntryType
from homeassistant.helpers.entity import DeviceInfo
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from custom_components.octopus_germany.const import DOMAIN
from custom_components.octopus_germany.tariff import is_product_current

if TYPE_CHECKING:
    from custom_components.octopus_germany.coordinator import OctopusDataCoordinator

_LOGGER = logging.getLogger(__name__)


def _get_account_device_info(account_number: str) -> DeviceInfo:
    """Get device info for account service."""
    return DeviceInfo(
        identifiers={(DOMAIN, account_number)},
        name=f"Octopus Energy Germany ({account_number})",
        manufacturer="Octopus Energy Germany",
        configuration_url="https://my.octopusenergy.de/",
        entry_type=DeviceEntryType.SERVICE,
    )


class OctopusGasBalanceSensor(CoordinatorEntity, SensorEntity):
    """Sensor for Octopus Germany gas balance."""

    def __init__(
        self, account_number: str, coordinator: OctopusDataCoordinator
    ) -> None:
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

    @property
    def device_info(self) -> DeviceInfo:
        """Return device information."""
        return _get_account_device_info(self._account_number)


class OctopusGasTariffSensor(CoordinatorEntity, SensorEntity):
    """Sensor for Octopus Germany gas tariff."""

    def __init__(
        self, account_number: str, coordinator: OctopusDataCoordinator
    ) -> None:
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
        valid_products = []

        # First filter products that are currently valid
        for product in gas_products:
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
        valid_products = []

        # First filter products that are currently valid
        for product in gas_products:
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
        return _get_account_device_info(self._account_number)


class OctopusGasMaloSensor(CoordinatorEntity, SensorEntity):
    """Sensor for Octopus Germany gas MALO number."""

    def __init__(
        self, account_number: str, coordinator: OctopusDataCoordinator
    ) -> None:
        """Initialize the gas MALO sensor."""
        super().__init__(coordinator)

        self._account_number = account_number
        self._attr_name = f"Octopus {account_number} Gas MALO Number"
        self._attr_unique_id = f"octopus_{account_number}_gas_malo_number"
        self._attr_has_entity_name = False
        self._attr_entity_registry_enabled_default = False

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

    @property
    def device_info(self) -> DeviceInfo:
        """Return device information."""
        return _get_account_device_info(self._account_number)


class OctopusGasMeloSensor(CoordinatorEntity, SensorEntity):
    """Sensor for Octopus Germany gas MELO number."""

    def __init__(
        self, account_number: str, coordinator: OctopusDataCoordinator
    ) -> None:
        """Initialize the gas MELO sensor."""
        super().__init__(coordinator)

        self._account_number = account_number
        self._attr_name = f"Octopus {account_number} Gas MELO Number"
        self._attr_unique_id = f"octopus_{account_number}_gas_melo_number"
        self._attr_has_entity_name = False
        self._attr_entity_registry_enabled_default = False

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

    @property
    def device_info(self) -> DeviceInfo:
        """Return device information."""
        return _get_account_device_info(self._account_number)


class OctopusGasMeterSensor(CoordinatorEntity, SensorEntity):
    """Sensor for Octopus Germany gas meter information."""

    def __init__(
        self, account_number: str, coordinator: OctopusDataCoordinator
    ) -> None:
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
            and self.coordinator.data[self._account_number].get("gas_meter") is not None
        )

    @property
    def device_info(self) -> DeviceInfo:
        """Return device information."""
        return _get_account_device_info(self._account_number)


class OctopusGasLatestReadingSensor(CoordinatorEntity, SensorEntity):
    """Sensor for Octopus Germany latest gas meter reading."""

    def __init__(
        self, account_number: str, coordinator: OctopusDataCoordinator
    ) -> None:
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
            except ValueError, TypeError:
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
                    # Try to parse and format the date
                    parsed_date = datetime.fromisoformat(reading_date)
                    reading_date = parsed_date.strftime("%Y-%m-%d %H:%M:%S")
                except ValueError, AttributeError:
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
            and self.coordinator.data[self._account_number].get("gas_latest_reading")
            is not None
        )

    @property
    def device_info(self) -> DeviceInfo:
        """Return device information."""
        return _get_account_device_info(self._account_number)


class OctopusGasPriceSensor(CoordinatorEntity, SensorEntity):
    """Sensor for Octopus Germany gas price."""

    def __init__(
        self, account_number: str, coordinator: OctopusDataCoordinator
    ) -> None:
        """Initialize the gas price sensor."""
        super().__init__(coordinator)

        self._account_number = account_number
        self._attr_name = f"Octopus {account_number} Gas Price"
        self._attr_unique_id = f"octopus_{account_number}_gas_price"
        self._attr_device_class = SensorDeviceClass.MONETARY
        self._attr_native_unit_of_measurement = "€/kWh"
        self._attr_state_class = SensorStateClass.TOTAL
        self._attr_has_entity_name = False

    @property
    def native_value(self) -> float:
        """Return the gas price."""
        if (
            not self.coordinator.data
            or not isinstance(self.coordinator.data, dict)
            or self._account_number not in self.coordinator.data
        ):
            return None

        account_data = self.coordinator.data[self._account_number]
        return account_data.get("gas_price")

    @property
    def available(self) -> bool:
        """Return True if entity is available."""
        return (
            self.coordinator is not None
            and self.coordinator.last_update_success
            and isinstance(self.coordinator.data, dict)
            and self._account_number in self.coordinator.data
            and self.coordinator.data[self._account_number].get("gas_price") is not None
        )

    @property
    def device_info(self) -> DeviceInfo:
        """Return device information."""
        return _get_account_device_info(self._account_number)


class OctopusGasSmartReadingSensor(CoordinatorEntity, SensorEntity):
    """Binary sensor for Octopus Germany gas meter smart reading capability."""

    def __init__(
        self, account_number: str, coordinator: OctopusDataCoordinator
    ) -> None:
        """Initialize the gas smart reading sensor."""
        super().__init__(coordinator)

        self._account_number = account_number
        self._attr_name = f"Octopus {account_number} Gas Smart Reading"
        self._attr_unique_id = f"octopus_{account_number}_gas_smart_reading"
        self._attr_has_entity_name = False
        self._attr_entity_registry_enabled_default = False

    @property
    def native_value(self) -> str:
        """Return whether smart reading is enabled."""
        if (
            not self.coordinator.data
            or not isinstance(self.coordinator.data, dict)
            or self._account_number not in self.coordinator.data
        ):
            return "Unknown"

        account_data = self.coordinator.data[self._account_number]
        smart_reading = account_data.get("gas_meter_smart_reading")

        if smart_reading is None:
            return "Unknown"
        if smart_reading:
            return "Enabled"
        return "Disabled"

    @property
    def available(self) -> bool:
        """Return True if entity is available."""
        return (
            self.coordinator is not None
            and self.coordinator.last_update_success
            and isinstance(self.coordinator.data, dict)
            and self._account_number in self.coordinator.data
            and self.coordinator.data[self._account_number].get(
                "gas_meter_smart_reading"
            )
            is not None
        )

    @property
    def device_info(self) -> DeviceInfo:
        """Return device information."""
        return _get_account_device_info(self._account_number)


class OctopusGasContractStartSensor(CoordinatorEntity, SensorEntity):
    """Sensor for Octopus Germany gas contract start date."""

    def __init__(
        self, account_number: str, coordinator: OctopusDataCoordinator
    ) -> None:
        """Initialize the gas contract start sensor."""
        super().__init__(coordinator)

        self._account_number = account_number
        self._attr_name = f"Octopus {account_number} Gas Contract Start"
        self._attr_unique_id = f"octopus_{account_number}_gas_contract_start"
        self._attr_device_class = SensorDeviceClass.DATE
        self._attr_has_entity_name = False
        self._attr_entity_registry_enabled_default = False

    @property
    def native_value(self) -> date | None:
        """Return the gas contract start date."""
        if (
            not self.coordinator.data
            or not isinstance(self.coordinator.data, dict)
            or self._account_number not in self.coordinator.data
        ):
            return None

        account_data = self.coordinator.data[self._account_number]
        contract_start = account_data.get("gas_contract_start")

        if contract_start:
            try:
                # Parse ISO date and return date object for DATE device class
                parsed_date = datetime.fromisoformat(contract_start)
                return parsed_date.date()
            except ValueError, TypeError:
                return None

        return None

    @property
    def available(self) -> bool:
        """Return True if entity is available."""
        return (
            self.coordinator is not None
            and self.coordinator.last_update_success
            and isinstance(self.coordinator.data, dict)
            and self._account_number in self.coordinator.data
            and self.coordinator.data[self._account_number].get("gas_contract_start")
            is not None
        )

    @property
    def device_info(self) -> DeviceInfo:
        """Return device information."""
        return _get_account_device_info(self._account_number)


class OctopusGasContractEndSensor(CoordinatorEntity, SensorEntity):
    """Sensor for Octopus Germany gas contract end date."""

    def __init__(
        self, account_number: str, coordinator: OctopusDataCoordinator
    ) -> None:
        """Initialize the gas contract end sensor."""
        super().__init__(coordinator)

        self._account_number = account_number
        self._attr_name = f"Octopus {account_number} Gas Contract End"
        self._attr_unique_id = f"octopus_{account_number}_gas_contract_end"
        self._attr_device_class = SensorDeviceClass.DATE
        self._attr_has_entity_name = False
        self._attr_entity_registry_enabled_default = False

    @property
    def native_value(self) -> date | None:
        """Return the gas contract end date."""
        if (
            not self.coordinator.data
            or not isinstance(self.coordinator.data, dict)
            or self._account_number not in self.coordinator.data
        ):
            return None

        account_data = self.coordinator.data[self._account_number]
        contract_end = account_data.get("gas_contract_end")

        if contract_end:
            try:
                # Parse ISO date and return date object for DATE device class
                parsed_date = datetime.fromisoformat(contract_end)
                return parsed_date.date()
            except ValueError, TypeError:
                return None

        return None

    @property
    def available(self) -> bool:
        """Return True if entity is available."""
        return (
            self.coordinator is not None
            and self.coordinator.last_update_success
            and isinstance(self.coordinator.data, dict)
            and self._account_number in self.coordinator.data
            and self.coordinator.data[self._account_number].get("gas_contract_end")
            is not None
        )

    @property
    def device_info(self) -> DeviceInfo:
        """Return device information."""
        return _get_account_device_info(self._account_number)


class OctopusGasContractExpiryDaysSensor(CoordinatorEntity, SensorEntity):
    """Sensor for days until Octopus Germany gas contract expiry."""

    def __init__(
        self, account_number: str, coordinator: OctopusDataCoordinator
    ) -> None:
        """Initialize the gas contract expiry days sensor."""
        super().__init__(coordinator)

        self._account_number = account_number
        self._attr_name = f"Octopus {account_number} Gas Contract Days Until Expiry"
        self._attr_unique_id = f"octopus_{account_number}_gas_contract_expiry_days"
        self._attr_native_unit_of_measurement = "days"
        self._attr_state_class = SensorStateClass.MEASUREMENT
        self._attr_has_entity_name = False

    @property
    def native_value(self) -> int:
        """Return the days until gas contract expiry."""
        if (
            not self.coordinator.data
            or not isinstance(self.coordinator.data, dict)
            or self._account_number not in self.coordinator.data
        ):
            return None

        account_data = self.coordinator.data[self._account_number]
        return account_data.get("gas_contract_days_until_expiry")

    @property
    def available(self) -> bool:
        """Return True if entity is available."""
        return (
            self.coordinator is not None
            and self.coordinator.last_update_success
            and isinstance(self.coordinator.data, dict)
            and self._account_number in self.coordinator.data
            and self.coordinator.data[self._account_number].get(
                "gas_contract_days_until_expiry"
            )
            is not None
        )

    @property
    def device_info(self) -> DeviceInfo:
        """Return device information."""
        return _get_account_device_info(self._account_number)
