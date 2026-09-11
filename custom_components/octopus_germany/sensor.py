"""
Provide sensors for the Octopus Germany Home Assistant integration.

The entities fetch and display electricity price and account information.
"""

from __future__ import annotations

import logging
from datetime import datetime
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

if TYPE_CHECKING:
    from homeassistant.config_entries import ConfigEntry
    from homeassistant.core import HomeAssistant
    from homeassistant.helpers.entity_platform import AddEntitiesCallback

    from .coordinator import OctopusDataCoordinator

from .const import DOMAIN
from .entities.charging import (
    OctopusElectricitySmartMeterReadingsSensor,
    OctopusSmartChargingSessionsSensor,
)
from .entities.devices import (
    OctopusDeviceStatusSensor,
    OctopusVehicleActivePowerSensor,
    OctopusVehicleBatterySizeSensor,
    OctopusVehicleLastSessionSocSensor,
)
from .entities.electricity import OctopusElectricityPriceSensor
from .entities.gas import (
    OctopusGasBalanceSensor,
    OctopusGasContractEndSensor,
    OctopusGasContractExpiryDaysSensor,
    OctopusGasContractStartSensor,
    OctopusGasLatestReadingSensor,
    OctopusGasMaloSensor,
    OctopusGasMeloSensor,
    OctopusGasMeterSensor,
    OctopusGasPriceSensor,
    OctopusGasSmartReadingSensor,
    OctopusGasTariffSensor,
)
from .models import AccountData, CoordinatorData, has_intelligent_capability

_LOGGER = logging.getLogger(__name__)


def _create_device_entities(
    account_number: str,
    account_data: AccountData,
    coordinator: OctopusDataCoordinator,
) -> list[SensorEntity]:
    """Create device and charging-session entities for an eligible account."""
    if not has_intelligent_capability(account_data):
        return []

    devices = account_data.get("devices", [])
    entities: list[SensorEntity] = []
    for device in devices:
        device_id = device.get("id")
        if not device_id:
            continue
        entities.append(
            OctopusDeviceStatusSensor(account_number, coordinator, device_id)
        )
        if device.get("deviceType") == "ELECTRIC_VEHICLES":
            entities.extend(
                (
                    OctopusVehicleLastSessionSocSensor(
                        account_number, coordinator, device_id
                    ),
                    OctopusVehicleBatterySizeSensor(
                        account_number, coordinator, device_id
                    ),
                    OctopusVehicleActivePowerSensor(
                        account_number, coordinator, device_id
                    ),
                )
            )

    device_sessions: dict[str, list[dict[str, Any]]] = {}
    for session in account_data.get("charging_sessions") or []:
        device_name = session.get("device_name")
        if device_name:
            device_sessions.setdefault(device_name, []).append(session)

    entities.extend(
        OctopusSmartChargingSessionsSensor(
            account_number,
            coordinator,
            device.get("name", f"Device_{device.get('id')}"),
            device.get("id"),
            device_sessions.get(device.get("name", f"Device_{device.get('id')}"), []),
        )
        for device in devices
    )
    return entities


def get_electricity_meter_device_info(
    coordinator_data: CoordinatorData, account_number: str
) -> DeviceInfo:
    """Get device info for electricity meter."""
    if (
        coordinator_data
        and account_number in coordinator_data
        and "meter" in coordinator_data[account_number]
    ):
        meter_info = coordinator_data[account_number]["meter"]
        meter_number = meter_info.get("number", "unknown")
        meter_type = meter_info.get("type", "Smart Meter")
        return DeviceInfo(
            identifiers={(DOMAIN, f"electricity_meter_{account_number}")},
            name=f"Electricity Meter ({meter_number})",
            manufacturer="Octopus Energy Germany",
            model=meter_type,
        )
    return DeviceInfo(
        identifiers={(DOMAIN, f"electricity_meter_{account_number}")},
        name=f"Electricity Meter ({account_number})",
        manufacturer="Octopus Energy Germany",
        model="Smart Meter",
    )


def get_gas_meter_device_info(
    coordinator_data: CoordinatorData, account_number: str
) -> DeviceInfo:
    """Get device info for gas meter."""
    if (
        coordinator_data
        and account_number in coordinator_data
        and "gas_meter" in coordinator_data[account_number]
    ):
        gas_meter_info = coordinator_data[account_number]["gas_meter"]
        gas_meter_number = gas_meter_info.get("number", "unknown")
        gas_meter_type = gas_meter_info.get("type", "Gas Meter")
        return DeviceInfo(
            identifiers={(DOMAIN, f"gas_meter_{account_number}")},
            name=f"Gas Meter ({gas_meter_number})",
            manufacturer="Octopus Energy Germany",
            model=gas_meter_type,
        )
    return DeviceInfo(
        identifiers={(DOMAIN, f"gas_meter_{account_number}")},
        name=f"Gas Meter ({account_number})",
        manufacturer="Octopus Energy Germany",
        model="Gas Meter",
    )


def get_account_device_info(account_number: str) -> DeviceInfo:
    """Get device info for account service."""
    return DeviceInfo(
        identifiers={(DOMAIN, account_number)},
        name=f"Octopus Energy Germany ({account_number})",
        manufacturer="Octopus Energy Germany",
        configuration_url="https://my.octopusenergy.de/",
        entry_type=DeviceEntryType.SERVICE,
    )


def get_device_specific_device_info(
    coordinator_data: CoordinatorData,
    account_number: str,
    device_id: str,
) -> DeviceInfo:
    """Get device info for a specific device (e.g., Electric Vehicle, Charge Point)."""
    if (
        coordinator_data
        and account_number in coordinator_data
        and "devices" in coordinator_data[account_number]
    ):
        devices = coordinator_data[account_number]["devices"]
        for device in devices:
            if device.get("id") == device_id:
                device_name = device.get("name", f"Device {device_id}")
                device_type = device.get("deviceType", "Unknown Device")
                device_model = device.get("vehicleVariant", {}).get(
                    "model", "Unknown Model"
                )
                device_provider = device.get("provider", "Unknown Provider")

                return DeviceInfo(
                    identifiers={(DOMAIN, f"device_{device_id}")},
                    name=f"{device_name} ({device_type})",
                    manufacturer=device_provider,
                    model=device_model,
                )

    # Fallback if device not found
    return DeviceInfo(
        identifiers={(DOMAIN, f"device_{device_id}")},
        name=f"Device ({device_id})",
        manufacturer="Octopus Energy Germany",
        model="Unknown Device",
    )


async def async_setup_entry(
    hass: HomeAssistant, entry: ConfigEntry, async_add_entities: AddEntitiesCallback
) -> None:
    """Set up Octopus Germany price sensors from a config entry."""
    # Using existing coordinator from hass.data[DOMAIN] to avoid duplicate API calls
    data = hass.data[DOMAIN][entry.entry_id]
    coordinator: OctopusDataCoordinator = data["coordinator"]
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
        if coordinator.data and acc_num in coordinator.data:
            account_data = coordinator.data[acc_num]

            # Create electricity sensors if account has electricity service
            if account_data.get("malo_number"):
                products = account_data.get("products", [])
                if products:
                    _LOGGER.debug(
                        "Creating electricity price sensor for account %s "
                        "with %d products",
                        acc_num,
                        len(products),
                    )
                    entities.append(OctopusElectricityPriceSensor(acc_num, coordinator))

                # Create electricity latest reading sensor when data exists.
                if account_data.get("electricity_latest_reading"):
                    entities.append(
                        OctopusElectricityLatestReadingSensor(acc_num, coordinator)
                    )

                # Create electricity smart-meter readings sensor for
                # electricity-enabled accounts.
                if account_data.get("malo_number"):
                    entities.append(
                        OctopusElectricitySmartMeterReadingsSensor(acc_num, coordinator)
                    )

            # Create electricity balance sensor for electricity-enabled accounts
            # with an electricity ledger.
            if "electricity_balance" in account_data and account_data.get(
                "malo_number"
            ):
                entities.append(OctopusElectricityBalanceSensor(acc_num, coordinator))

            # Create gas sensors if account has gas service
            if account_data.get("gas_malo_number"):
                # Create gas balance sensor if gas ledger exists
                if "gas_balance" in account_data and account_data.get(
                    "gas_malo_number"
                ):
                    entities.append(OctopusGasBalanceSensor(acc_num, coordinator))

                # Create gas tariff sensor if gas products exist
                gas_products = account_data.get("gas_products", [])
                if gas_products:
                    _LOGGER.debug(
                        "Creating gas tariff sensor for account %s "
                        "with %d gas products",
                        acc_num,
                        len(gas_products),
                    )
                    entities.append(OctopusGasTariffSensor(acc_num, coordinator))

                # Create gas infrastructure sensors
                entities.append(OctopusGasMaloSensor(acc_num, coordinator))

                if account_data.get("gas_melo_number"):
                    entities.append(OctopusGasMeloSensor(acc_num, coordinator))

                if account_data.get("gas_meter"):
                    entities.append(OctopusGasMeterSensor(acc_num, coordinator))

                # Create gas latest reading sensor if gas reading data exists
                if account_data.get("gas_latest_reading"):
                    entities.append(OctopusGasLatestReadingSensor(acc_num, coordinator))

                # Create gas price sensor if gas price data exists
                if account_data.get("gas_price") is not None:
                    entities.append(OctopusGasPriceSensor(acc_num, coordinator))

                # Create gas meter smart reading capability sensor if data exists
                if account_data.get("gas_meter_smart_reading") is not None:
                    entities.append(OctopusGasSmartReadingSensor(acc_num, coordinator))

                # Create gas contract date sensors if contract data exists
                if account_data.get("gas_contract_start"):
                    entities.append(OctopusGasContractStartSensor(acc_num, coordinator))

                if account_data.get("gas_contract_end"):
                    entities.append(OctopusGasContractEndSensor(acc_num, coordinator))

                if account_data.get("gas_contract_days_until_expiry") is not None:
                    entities.append(
                        OctopusGasContractExpiryDaysSensor(acc_num, coordinator)
                    )

            device_entities = _create_device_entities(
                acc_num, account_data, coordinator
            )
            if device_entities:
                _LOGGER.debug(
                    "Creating %d device entities for account %s",
                    len(device_entities),
                    acc_num,
                )
                entities.extend(device_entities)

            # Create heat balance sensor if heat ledger exists and has non-zero balance
            if (
                "heat_balance" in account_data
                and account_data.get("heat_balance", 0) != 0
            ):
                entities.append(OctopusHeatBalanceSensor(acc_num, coordinator))

            # Create sensors for other ledgers
            other_ledgers = account_data.get("other_ledgers", {})
            entities.extend(
                OctopusLedgerBalanceSensor(acc_num, coordinator, ledger_type)
                for ledger_type in other_ledgers
            )
        elif coordinator.data is None:
            _LOGGER.error("No coordinator data available")
        elif acc_num not in coordinator.data:
            _LOGGER.warning("Account %s missing from coordinator data", acc_num)
        elif "products" not in coordinator.data[acc_num]:
            _LOGGER.warning(
                "No 'products' key in coordinator data for account %s", acc_num
            )
        else:
            _LOGGER.warning("Unknown issue detecting products for account %s", acc_num)

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


class OctopusElectricityBalanceSensor(CoordinatorEntity, SensorEntity):
    """Sensor for Octopus Germany electricity balance."""

    def __init__(
        self, account_number: str, coordinator: OctopusDataCoordinator
    ) -> None:
        """Initialize the electricity balance sensor."""
        super().__init__(coordinator)

        self._account_number = account_number
        self._attr_name = f"Octopus {account_number} Electricity Balance"
        self._attr_unique_id = f"octopus_{account_number}_electricity_balance"
        self._attr_device_class = SensorDeviceClass.MONETARY
        self._attr_native_unit_of_measurement = "€"
        self._attr_state_class = SensorStateClass.TOTAL
        self._attr_has_entity_name = False

    @property
    def native_value(self) -> float:
        """Return the electricity balance."""
        if (
            not self.coordinator.data
            or not isinstance(self.coordinator.data, dict)
            or self._account_number not in self.coordinator.data
        ):
            return None

        account_data = self.coordinator.data[self._account_number]
        return account_data.get("electricity_balance", 0.0)

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
        return get_account_device_info(self._account_number)


class OctopusHeatBalanceSensor(CoordinatorEntity, SensorEntity):
    """Sensor for Octopus Germany heat balance."""

    def __init__(
        self, account_number: str, coordinator: OctopusDataCoordinator
    ) -> None:
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

    @property
    def device_info(self) -> DeviceInfo:
        """Return device information."""
        return get_account_device_info(self._account_number)


class OctopusLedgerBalanceSensor(CoordinatorEntity, SensorEntity):
    """Sensor for Octopus Germany generic ledger balance."""

    def __init__(
        self,
        account_number: str,
        coordinator: OctopusDataCoordinator,
        ledger_type: str,
    ) -> None:
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

    @property
    def device_info(self) -> DeviceInfo:
        """Return device information."""
        return get_account_device_info(self._account_number)


class OctopusElectricityLatestReadingSensor(CoordinatorEntity, SensorEntity):
    """Sensor for Octopus Germany latest electricity meter reading."""

    def __init__(
        self, account_number: str, coordinator: OctopusDataCoordinator
    ) -> None:
        """Initialize the electricity latest reading sensor."""
        super().__init__(coordinator)

        self._account_number = account_number
        self._attr_name = f"Octopus {account_number} Electricity Latest Reading"
        self._attr_unique_id = f"octopus_{account_number}_electricity_latest_reading"
        self._attr_device_class = SensorDeviceClass.ENERGY
        self._attr_state_class = SensorStateClass.TOTAL_INCREASING
        self._attr_has_entity_name = False
        self._attributes = {}

        # Initialize attributes right after creation
        self._update_attributes()

    @property
    def native_value(self) -> float | None:
        """Return the latest electricity meter reading value."""
        if (
            not self.coordinator.data
            or not isinstance(self.coordinator.data, dict)
            or self._account_number not in self.coordinator.data
        ):
            return None

        account_data = self.coordinator.data[self._account_number]
        electricity_reading = account_data.get("electricity_latest_reading")

        if electricity_reading and isinstance(electricity_reading, dict):
            try:
                reading_value = electricity_reading.get("value")
                if reading_value is not None:
                    return float(reading_value)
            except ValueError, TypeError:
                _LOGGER.warning(
                    "Invalid electricity meter reading value: %s", reading_value
                )

        return None

    @property
    def native_unit_of_measurement(self) -> str | None:
        """Return the unit of measurement."""
        # Default to kWh which is the standard for electricity consumption in Germany
        return "kWh"

    def _update_attributes(self) -> None:
        """Update the internal attributes dictionary."""
        default_attributes = {
            "reading_value": "Unknown",
            "reading_units": "kWh",
            "reading_date": "Unknown",
            "reading_origin": "Unknown",
            "reading_type": "Unknown",
            "register_obis_code": "Unknown",
            "register_type": "Unknown",
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
        electricity_reading = account_data.get("electricity_latest_reading")

        if electricity_reading and isinstance(electricity_reading, dict):
            # Extract reading date from readAt
            reading_date = electricity_reading.get("readAt")

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
                "reading_value": electricity_reading.get("value", "Unknown"),
                "reading_units": "kWh",
                "reading_date": reading_date or "Unknown",
                "reading_origin": electricity_reading.get("origin", "Unknown"),
                "reading_type": electricity_reading.get("typeOfRead", "Unknown"),
                "register_obis_code": electricity_reading.get(
                    "registerObisCode", "Unknown"
                ),
                "register_type": electricity_reading.get("registerType", "Unknown"),
                "meter_id": electricity_reading.get("meterId", "Unknown"),
                "read_at": electricity_reading.get("readAt", "Unknown"),
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
            and self.coordinator.data[self._account_number].get(
                "electricity_latest_reading"
            )
            is not None
        )

    @property
    def device_info(self) -> DeviceInfo:
        """Return device information."""
        return get_account_device_info(self._account_number)
