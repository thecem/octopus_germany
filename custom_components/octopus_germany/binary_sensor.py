"""Binary sensors for the Octopus Germany integration."""

from datetime import datetime
import logging
from typing import Any

from homeassistant.components.binary_sensor import BinarySensorEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity
from homeassistant.util.dt import as_local, as_utc, parse_datetime, utcnow

from .const import DOMAIN

_LOGGER = logging.getLogger(__name__)


async def async_setup_entry(
    hass: HomeAssistant, entry: ConfigEntry, async_add_entities: AddEntitiesCallback
) -> None:
    """Set up Octopus Germany binary sensors from a config entry."""
    data = hass.data[DOMAIN][entry.entry_id]
    coordinator = data["coordinator"]
    account_number = data["account_number"]

    # Only add the binary sensors if we have devices
    if (
        coordinator.data
        and account_number in coordinator.data
        and coordinator.data[account_number].get("devices")
    ):
        entities = [
            OctopusIntelligentDispatchingBinarySensor(account_number, coordinator),
        ]
        async_add_entities(entities)
        _LOGGER.info(
            "Added intelligent dispatching binary sensor for account %s", account_number
        )

        # Log out the keys in coordinator data for debugging
        _LOGGER.info(
            "Available keys in coordinator for %s: %s",
            account_number,
            list(coordinator.data[account_number].keys()),
        )
        if "plannedDispatches" in coordinator.data[account_number]:
            _LOGGER.info(
                "Found %d planned dispatches in coordinator data",
                len(coordinator.data[account_number]["plannedDispatches"]),
            )
    else:
        _LOGGER.info(
            "Not creating intelligent dispatching sensor due to missing devices data for account %s",
            account_number,
        )


class OctopusIntelligentDispatchingBinarySensor(CoordinatorEntity, BinarySensorEntity):
    """Binary sensor for Octopus Intelligent Dispatching."""

    def __init__(self, account_number, coordinator) -> None:
        """Initialize the binary sensor for intelligent dispatching."""
        super().__init__(coordinator)

        self._account_number = account_number
        self._attr_name = f"Octopus {account_number} Intelligent Dispatching"
        self._attr_unique_id = f"octopus_{account_number}_intelligent_dispatching"
        self._attr_device_class = None
        self._attr_has_entity_name = False
        self._attributes = {}

        # Initialize attributes right after creation
        self._update_attributes()

    @property
    def is_on(self) -> bool:
        """Determine if the binary sensor is currently active.

        The sensor is 'on' (true) when at least one planned dispatch
        exists that encompasses the current time.
        """
        if (
            not self.coordinator.data
            or not isinstance(self.coordinator.data, dict)
            or self._account_number not in self.coordinator.data
        ):
            _LOGGER.debug("No valid data structure in coordinator for is_on check")
            return False

        account_data = self.coordinator.data[self._account_number]

        # Check for both camelCase and snake_case keys
        planned_dispatches = account_data.get("plannedDispatches", [])
        if not planned_dispatches:
            planned_dispatches = account_data.get("planned_dispatches", [])

        if not planned_dispatches:
            _LOGGER.debug("No planned dispatches found")
            return False

        _LOGGER.debug(
            "Checking %d planned dispatches for active status", len(planned_dispatches)
        )

        # Get current time in UTC
        now = utcnow()
        _LOGGER.debug("Current time (UTC): %s", now.isoformat())

        # Check all planned dispatches to see if one is currently active
        for dispatch in planned_dispatches:
            try:
                # Extract start and end time
                start_str = dispatch.get("start")
                end_str = dispatch.get("end")

                if not start_str or not end_str:
                    _LOGGER.debug("Dispatch missing start or end time: %s", dispatch)
                    continue

                # Convert strings to datetime objects and ensure they are timezone-aware UTC
                start = as_utc(parse_datetime(start_str))
                end = as_utc(parse_datetime(end_str))

                if not start or not end:
                    _LOGGER.debug(
                        "Failed to parse start or end time for dispatch: %s", dispatch
                    )
                    continue

                _LOGGER.debug(
                    "Checking dispatch: start=%s, end=%s, current=%s",
                    start.isoformat(),
                    end.isoformat(),
                    now.isoformat(),
                )

                # If current time is between start and end, the dispatch is active
                if start <= now <= end:
                    _LOGGER.info(
                        "Active dispatch found! From %s to %s (current: %s)",
                        start.isoformat(),
                        end.isoformat(),
                        now.isoformat(),
                    )
                    return True
                else:
                    time_to_start = (
                        (start - now).total_seconds() if start > now else None
                    )
                    time_since_end = (now - end).total_seconds() if now > end else None

                    if time_to_start is not None:
                        _LOGGER.debug(
                            "Dispatch not yet active - starts in %d seconds (%s)",
                            int(time_to_start),
                            start.isoformat(),
                        )
                    elif time_since_end is not None:
                        _LOGGER.debug(
                            "Dispatch already ended - ended %d seconds ago (%s)",
                            int(time_since_end),
                            end.isoformat(),
                        )

            except (ValueError, TypeError) as e:
                _LOGGER.error("Error parsing dispatch data: %s - %s", dispatch, str(e))
                continue

        # If no active dispatch was found, the sensor is 'off'
        _LOGGER.debug("No active dispatches found, sensor is OFF")
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

            # Add source and location if available
            meta = dispatch.get("meta", {})
            if meta:
                if "source" in meta:
                    formatted["source"] = meta["source"]
                if "location" in meta:
                    formatted["location"] = meta["location"]

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
