"""Device and vehicle sensor entities for the Octopus Germany integration."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any

from homeassistant.components.sensor import SensorDeviceClass, SensorEntity
from homeassistant.const import PERCENTAGE, UnitOfEnergy, UnitOfPower
from homeassistant.core import callback
from homeassistant.helpers.device_registry import DeviceEntryType
from homeassistant.helpers.entity import DeviceInfo
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from custom_components.octopus_germany.const import DOMAIN

if TYPE_CHECKING:
    from custom_components.octopus_germany.coordinator import OctopusDataCoordinator


def _get_account_device_info(account_number: str) -> DeviceInfo:
    """Get device info for account service."""
    return DeviceInfo(
        identifiers={(DOMAIN, account_number)},
        name=f"Octopus Energy Germany ({account_number})",
        manufacturer="Octopus Energy Germany",
        configuration_url="https://my.octopusenergy.de/",
        entry_type=DeviceEntryType.SERVICE,
    )


def _get_device_specific_device_info(
    coordinator_data: dict, account_number: str, device_id: str
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


class OctopusDeviceStatusSensor(CoordinatorEntity, SensorEntity):
    """Sensor for Octopus Germany device status."""

    def __init__(
        self,
        account_number: str,
        coordinator: OctopusDataCoordinator,
        device_id: str,
    ) -> None:
        """Initialize the device status sensor."""
        super().__init__(coordinator)

        self._account_number = account_number
        self._device_id = device_id
        # Device name ermitteln
        device_name = None
        if (
            coordinator.data
            and isinstance(coordinator.data, dict)
            and account_number in coordinator.data
        ):
            account_data = coordinator.data[account_number]
            devices = account_data.get("devices", [])
            for device in devices:
                if device.get("id") == device_id:
                    device_name = device.get("name", f"Device_{device_id}")
                    break
        if not device_name:
            device_name = f"Device_{device_id}"
        self._attr_name = f"Octopus {account_number} {device_name} Status"
        self._attr_unique_id = f"octopus_{account_number}_{device_id}_status"
        self._attr_has_entity_name = False
        self._attributes = {}

        # Initialize attributes right after creation
        self._update_attributes()

    def _get_device_data(self) -> dict | None:
        """Get device data for this specific device_id."""
        if (
            not self.coordinator.data
            or not isinstance(self.coordinator.data, dict)
            or self._account_number not in self.coordinator.data
        ):
            return None

        account_data = self.coordinator.data[self._account_number]
        devices = account_data.get("devices", [])

        for device in devices:
            if device.get("id") == self._device_id:
                return device
        return None

    @property
    def native_value(self) -> str | None:
        """Return the current device status."""
        device = self._get_device_data()
        if device:
            status = device.get("status", {})
            return status.get("currentState", "Unknown")
        return None

    def _update_attributes(self) -> None:
        """Update the internal attributes dictionary."""
        default_attributes = {
            "device_id": "Unknown",
            "device_name": "Unknown",
            "device_model": "Unknown",
            "device_provider": "Unknown",
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
        devices = account_data.get("devices", [])

        if not devices:
            self._attributes = default_attributes
            return

        device = self._get_device_data()
        if not device:
            self._attributes = default_attributes
            return

        self._attributes = {
            "device_id": device.get("id", "Unknown"),
            "device_name": device.get("name", "Unknown"),
            "device_model": device.get("vehicleVariant", {}).get("model", "Unknown"),
            "device_provider": device.get("provider", "Unknown"),
            "battery_size": device.get("vehicleVariant", {}).get(
                "batterySize", "Unknown"
            ),
            "is_suspended": device.get("status", {}).get("isSuspended", False),
            "account_number": self._account_number,
            "last_updated": datetime.now(UTC).isoformat(),
        }

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
            and self._get_device_data() is not None
        )

    @property
    def device_info(self) -> DeviceInfo:
        """Return device information."""
        return _get_account_device_info(self._account_number)


class OctopusVehicleDataSensor(CoordinatorEntity, SensorEntity):
    """Base sensor for per-vehicle metrics."""

    _metric_name = "Metric"
    _metric_unique_id = "metric"
    _metric_icon = "mdi:car-electric"
    _metric_device_class = None
    _metric_unit = None

    def __init__(
        self,
        account_number: str,
        coordinator: OctopusDataCoordinator,
        device_id: str,
    ) -> None:
        """Initialize a vehicle data sensor."""
        super().__init__(coordinator)

        self._account_number = account_number
        self._device_id = device_id
        self._device_name = self._resolve_device_name()
        self._attr_name = (
            f"Octopus {account_number} {self._device_name} {self._metric_name}"
        )
        self._attr_unique_id = (
            f"octopus_{account_number}_{device_id}_{self._metric_unique_id}"
        )
        self._attr_has_entity_name = False
        self._attr_icon = self._metric_icon
        self._attr_device_class = self._metric_device_class
        self._attr_native_unit_of_measurement = self._metric_unit
        self._attributes = {}

    def _resolve_device_name(self) -> str:
        """Resolve the current device name from coordinator data."""
        device = self._get_device_data()
        if device:
            return device.get("name", f"Device_{self._device_id}")
        return f"Device_{self._device_id}"

    def _get_device_data(self) -> dict | None:
        """Get the current device payload for this sensor."""
        if (
            not self.coordinator.data
            or not isinstance(self.coordinator.data, dict)
            or self._account_number not in self.coordinator.data
        ):
            return None

        account_data = self.coordinator.data[self._account_number]
        devices = account_data.get("devices")
        if not isinstance(devices, list):
            devices = []

        for device in devices:
            if device.get("id") == self._device_id:
                return device
        return None

    def _get_latest_session(self) -> dict | None:
        """Return the latest charging session for this device."""
        if (
            not self.coordinator.data
            or not isinstance(self.coordinator.data, dict)
            or self._account_number not in self.coordinator.data
        ):
            return None

        account_data = self.coordinator.data[self._account_number]
        sessions = account_data.get("charging_sessions")
        if not isinstance(sessions, list):
            return None

        device_sessions = [
            session
            for session in sessions
            if isinstance(session, dict) and session.get("device_id") == self._device_id
        ]

        if not device_sessions:
            return None

        return max(device_sessions, key=lambda s: s.get("start") or "")

    @staticmethod
    def _to_float(value: Any) -> float | None:
        """Convert a value to float when possible."""
        if value is None:
            return None
        try:
            return float(value)
        except TypeError, ValueError:
            return None

    def _get_metric_value(self) -> Any:
        """Return the concrete metric value for subclasses."""
        raise NotImplementedError

    @property
    def native_value(self) -> Any:
        """Return the metric value."""
        return self._get_metric_value()

    @property
    def available(self) -> bool:
        """Return True if entity is available."""
        return (
            self.coordinator is not None
            and self.coordinator.last_update_success
            and isinstance(self.coordinator.data, dict)
            and self._account_number in self.coordinator.data
            and self._get_device_data() is not None
            and self.native_value is not None
        )

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        """Return additional state attributes for the sensor."""
        latest_session = self._get_latest_session() or {}
        return {
            "device_id": self._device_id,
            "device_name": self._resolve_device_name(),
            "account_number": self._account_number,
            "latest_session_start": latest_session.get("start"),
            "latest_session_end": latest_session.get("end"),
            "last_updated": datetime.now(UTC).isoformat(),
        }

    @property
    def device_info(self) -> DeviceInfo:
        """Return device information."""
        return _get_device_specific_device_info(
            self.coordinator.data, self._account_number, self._device_id
        )


class OctopusVehicleLastSessionSocSensor(OctopusVehicleDataSensor):
    """Sensor for last known vehicle SoC from charging sessions."""

    _metric_name = "SoC"
    _metric_unique_id = "soc"
    _metric_icon = "mdi:battery"
    _metric_device_class = SensorDeviceClass.BATTERY
    _metric_unit = PERCENTAGE

    def _get_metric_value(self) -> float | None:
        """
        Return latest SoC for this vehicle.

        Prefer live SoC from device status and fall back to last charging session.
        """
        device = self._get_device_data()
        if device:
            status = device.get("status", {}) or {}
            soc_reading = status.get("stateOfCharge")
            if isinstance(soc_reading, dict):
                live_soc = self._to_float(soc_reading.get("value"))
            else:
                live_soc = self._to_float(soc_reading)
            if live_soc is not None:
                return live_soc

        latest_session = self._get_latest_session()
        if not latest_session:
            return None

        value = latest_session.get(
            "stateOfChargeFinal", latest_session.get("soc_final")
        )
        return self._to_float(value)


class OctopusVehicleBatterySizeSensor(OctopusVehicleDataSensor):
    """Sensor for EV battery size in kWh."""

    _metric_name = "Battery Size"
    _metric_unique_id = "battery_size"
    _metric_icon = "mdi:car-electric"
    _metric_unit = UnitOfEnergy.KILO_WATT_HOUR

    def _get_metric_value(self) -> float | None:
        """Return battery size for this vehicle."""
        device = self._get_device_data()
        if not device:
            return None

        vehicle_variant = device.get("vehicleVariant", {}) or {}
        return self._to_float(vehicle_variant.get("batterySize"))


class OctopusVehicleActivePowerSensor(OctopusVehicleDataSensor):
    """Sensor for current EV charging power in kW."""

    _metric_name = "Active Power"
    _metric_unique_id = "active_power"
    _metric_icon = "mdi:lightning-bolt"
    _metric_device_class = SensorDeviceClass.POWER
    _metric_unit = UnitOfPower.KILO_WATT

    def _get_metric_value(self) -> float | None:
        device = self._get_device_data()
        if not device:
            return None
        status = device.get("status", {}) or {}
        active_power = status.get("activePower", {}) or {}
        return self._to_float(active_power.get("value"))
