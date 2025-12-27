"""Binary sensors for the Octopus Germany integration."""

from datetime import datetime
import logging
from typing import Any

from homeassistant.components.binary_sensor import BinarySensorEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity
from homeassistant.helpers.entity import DeviceInfo
from homeassistant.util.dt import as_local, as_utc, parse_datetime, utcnow

from .const import DOMAIN
from .sensor import get_account_device_info

_LOGGER = logging.getLogger(__name__)


async def async_setup_entry(
    hass: HomeAssistant, entry: ConfigEntry, async_add_entities: AddEntitiesCallback
) -> None:
    """Set up Octopus Germany binary sensors from a config entry."""
    data = hass.data[DOMAIN][entry.entry_id]
    coordinator = data["coordinator"]
    account_number = data["account_number"]

    # Get all account numbers from entry data or coordinator data
    account_numbers = entry.data.get("account_numbers", [])
    if not account_numbers and account_number:
        account_numbers = [account_number]

    # If still no account numbers, try to get them from coordinator data
    if not account_numbers and coordinator.data:
        account_numbers = list(coordinator.data.keys())

    _LOGGER.debug("Creating binary sensors for accounts: %s", account_numbers)

    entities = []

    # Create device-specific binary sensors for Intelligent Dispatching
    for acc_num in account_numbers:
        if (
            coordinator.data
            and acc_num in coordinator.data
            and coordinator.data[acc_num].get("devices")
        ):
            devices = coordinator.data[acc_num]["devices"]
            for device in devices:
                device_id = device.get("id")
                device_name = device.get("name", f"Device_{device_id}")
                if not device_id:
                    continue
                entities.append(
                    OctopusIntelligentDispatchingBinarySensor(
                        acc_num, coordinator, device_id, device_name
                    )
                )
                _LOGGER.info(
                    "Added intelligent dispatching binary sensor for account %s, device %s",
                    acc_num,
                    device_name,
                )
        else:
            _LOGGER.info(
                "Not creating intelligent dispatching sensor due to missing devices data for account %s",
                acc_num,
            )

    if entities:
        async_add_entities(entities)
    else:
        _LOGGER.info("No binary sensors to add for any account")


class OctopusIntelligentDispatchingBinarySensor(CoordinatorEntity, BinarySensorEntity):
    """Device-specific binary sensor for Octopus Intelligent Dispatching."""

    def __init__(self, account_number, coordinator, device_id, device_name) -> None:
        """Initialize the device-specific binary sensor for intelligent dispatching."""
        super().__init__(coordinator)
        self._account_number = account_number
        self._device_id = device_id
        self._device_name = device_name
        norm_name = device_name.lower().replace(" ", "_")
        for ch in [
            "/",
            "\\",
            ",",
            ".",
            ":",
            ";",
            "|",
            "[",
            "]",
            "{",
            "}",
            "(",
            ")",
            "'",
            '"',
            "#",
            "?",
            "!",
            "@",
            "=",
            "+",
            "*",
            "%",
            "&",
            "<",
            ">",
        ]:
            norm_name = norm_name.replace(ch, "_")
        self._attr_name = (
            f"Octopus {account_number} {device_name} Intelligent Dispatching"
        )
        self._attr_unique_id = (
            f"octopus_{account_number}_{norm_name}_{device_id}_intelligent_dispatching"
        )
        self._attr_device_class = None
        self._attr_has_entity_name = False
        self._attributes = {}
        self._update_attributes()

    @property
    def is_on(self) -> bool:
        """Return True if a planned dispatch for this device is currently active."""
        if (
            not self.coordinator.data
            or not isinstance(self.coordinator.data, dict)
            or self._account_number not in self.coordinator.data
        ):
            _LOGGER.debug("No valid data structure in coordinator for is_on check")
            return False

        account_data = self.coordinator.data[self._account_number]
        planned_dispatches = account_data.get("plannedDispatches", [])
        if not planned_dispatches:
            planned_dispatches = account_data.get("planned_dispatches", [])

        if not planned_dispatches:
            _LOGGER.debug("No planned dispatches found")
            return False

        # Only consider dispatches for this device
        device_dispatches = [
            d for d in planned_dispatches if d.get("deviceId") == self._device_id
        ]
        if not device_dispatches:
            _LOGGER.debug(f"No planned dispatches for device {self._device_id}")
            return False

        now = utcnow()
        for dispatch in device_dispatches:
            try:
                start_str = dispatch.get("start")
                end_str = dispatch.get("end")
                if not start_str or not end_str:
                    continue
                start = as_utc(parse_datetime(start_str))
                end = as_utc(parse_datetime(end_str))
                if not start or not end:
                    continue
                if start <= now <= end:
                    _LOGGER.info(
                        f"Active dispatch found for device {self._device_id}! From {start.isoformat()} to {end.isoformat()} (current: {now.isoformat()})"
                    )
                    return True
            except Exception as e:
                _LOGGER.error(
                    f"Error parsing dispatch data for device {self._device_id}: {dispatch} - {e}"
                )
                continue
        return False

    def _format_dispatch(self, dispatch):
        """Format a dispatch entry for display."""
        try:
            # Get start and end as strings
            start_str = dispatch.get("start")
            end_str = dispatch.get("end")

            if not start_str or not end_str:
                return None

            # Parse string to datetime and ensure timezone aware
            start = parse_datetime(start_str)
            end = parse_datetime(end_str)

            if not start or not end:
                return None

            # Create a simpler format for the attribute
            formatted = {
                "start": start_str,
                "end": end_str,
                "start_time": as_local(start).strftime("%Y-%m-%d %H:%M:%S")
                if start
                else "Unknown",
                "end_time": as_local(end).strftime("%Y-%m-%d %H:%M:%S")
                if end
                else "Unknown",
                "charge_kwh": float(dispatch.get("deltaKwh", 0)),
            }

            # Add type if available (from new flex API)
            if "type" in dispatch:
                formatted["type"] = dispatch["type"]

            # Add source and location if available
            meta = dispatch.get("meta", {})
            if meta:
                if "source" in meta:
                    formatted["source"] = meta["source"]
                if "location" in meta:
                    formatted["location"] = meta["location"]
                # Also check for type in meta for backward compatibility
                if "type" in meta and "type" not in formatted:
                    formatted["type"] = meta["type"]

            return formatted
        except (ValueError, TypeError) as e:
            _LOGGER.error("Error formatting dispatch: %s - %s", dispatch, e)
            return None

    def _process_device_preferences(self, device):
        """Process and format device preferences for display."""
        if not isinstance(device, dict):
            return {}

        preferences = device.get("preferences", {})
        if not preferences:
            return {}

        processed_prefs = {}

        # Process mode preference if available
        if "mode" in preferences:
            processed_prefs["mode"] = preferences["mode"]

        # Process schedules if available
        if "schedules" in preferences and isinstance(preferences["schedules"], list):
            schedules = []
            for schedule in preferences["schedules"]:
                if isinstance(schedule, dict):
                    formatted_schedule = {
                        "day": schedule.get("dayOfWeek", ""),
                        "time": schedule.get("time", ""),
                        "min": schedule.get("min", 0),
                        "max": schedule.get("max", 100),
                    }
                    schedules.append(formatted_schedule)

            if schedules:
                processed_prefs["schedules"] = schedules

        return processed_prefs

    def _update_attributes(self) -> None:
        """Update the internal attributes dictionary."""
        # Default empty attributes
        default_attributes = {
            "planned_dispatches": [],
            "completed_dispatches": [],
            "devices": [],
            "current_state": "Unknown",
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
        if not account_data:
            self._attributes = default_attributes
            return

        _LOGGER.debug(
            "Available keys in account_data: %s",
            list(account_data.keys())
            if isinstance(account_data, dict)
            else "Not a dict",
        )

        # Extract all required data with consistent field names
        # First try camelCase names (API response format)
        planned_dispatches = account_data.get("plannedDispatches", [])
        if not planned_dispatches:
            # Try snake_case as a fallback (processed data format)
            planned_dispatches = account_data.get("planned_dispatches", [])

        completed_dispatches = account_data.get("completedDispatches", [])
        if not completed_dispatches:
            completed_dispatches = account_data.get("completed_dispatches", [])

        devices = account_data.get("devices", [])

        _LOGGER.debug(
            "Found %d planned dispatches, %d completed dispatches, %d devices",
            len(planned_dispatches),
            len(completed_dispatches),
            len(devices),
        )

        # Get current state from devices if available
        current_state = "Unknown"
        if devices and devices[0].get("status"):
            current_state = devices[0]["status"].get("currentState", "Unknown")

        # Format dispatches for display
        formatted_planned_dispatches = []
        for dispatch in planned_dispatches:
            formatted = self._format_dispatch(dispatch)
            if formatted:
                formatted_planned_dispatches.append(formatted)

        formatted_completed_dispatches = []
        for dispatch in completed_dispatches:
            formatted = self._format_dispatch(dispatch)
            if formatted:
                formatted_completed_dispatches.append(formatted)

        _LOGGER.debug(
            "Formatted %d planned dispatches, %d completed dispatches for attributes",
            len(formatted_planned_dispatches),
            len(formatted_completed_dispatches),
        )

        # Simplify device data to ensure it's serializable
        simplified_devices = []
        for device in devices:
            if not isinstance(device, dict):
                continue

            simple_device = {
                "id": device.get("id", ""),
                "name": device.get("name", "Unknown"),
                "device_type": device.get("deviceType", "Unknown"),
                "provider": device.get("provider", "Unknown"),
                "status": device.get("status", {}).get("currentState", "Unknown")
                if isinstance(device.get("status"), dict)
                else "Unknown",
                "is_suspended": device.get("status", {}).get("isSuspended", True)
                if isinstance(device.get("status"), dict)
                else True,
            }

            # Add preferences if available
            if "preferences" in device:
                # Use the existing _process_device_preferences method
                preferences = self._process_device_preferences(device)
                if preferences:
                    simple_device["preferences"] = preferences
                else:
                    # If our processor didn't extract anything useful, use the raw preferences
                    simple_device["preferences"] = device.get("preferences", {})

            # Add vehicle-specific info if available
            if "vehicleVariant" in device and isinstance(
                device["vehicleVariant"], dict
            ):
                simple_device["model"] = device["vehicleVariant"].get(
                    "model", "Unknown"
                )
                simple_device["battery_size"] = device["vehicleVariant"].get(
                    "batterySize", "Unknown"
                )

            simplified_devices.append(simple_device)

        # Build and update attributes
        self._attributes = {
            "planned_dispatches": formatted_planned_dispatches,
            "completed_dispatches": formatted_completed_dispatches,
            "devices": simplified_devices,
            "current_state": current_state,
            "last_updated": datetime.now().isoformat(),
        }

        # Special log to confirm attributes are correctly set
        _LOGGER.debug(
            "Binary sensor attributes updated with %d planned dispatches, %d completed dispatches, %d devices",
            len(formatted_planned_dispatches),
            len(formatted_completed_dispatches),
            len(simplified_devices),
        )

    @callback
    def _handle_coordinator_update(self) -> None:
        """Handle updated data from the coordinator."""
        self._update_attributes()
        self.async_write_ha_state()

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        """Return additional state attributes for the binary sensor."""
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
        """Return device information for the Octopus account (service device)."""
        from .sensor import get_account_device_info

        return get_account_device_info(self._account_number)
