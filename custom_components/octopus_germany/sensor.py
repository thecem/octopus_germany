"""
This module provides integration with Octopus Germany for Home Assistant.

It defines the coordinator and binary sensor entities to fetch and display
data related to electricity accounts, dispatches, and devices.
"""

import logging
from datetime import datetime, timedelta
from typing import Any, Dict
from collections.abc import Mapping
import json

from homeassistant.components.binary_sensor import (
    BinarySensorEntity,
    BinarySensorDeviceClass,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant, callback
from homeassistant.exceptions import ConfigEntryNotReady
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity
from homeassistant.util.dt import as_local, utcnow, parse_datetime, as_utc

from .const import DOMAIN, UPDATE_INTERVAL
from .octopus_germany import OctopusGermany

_LOGGER = logging.getLogger(__name__)


async def async_setup_entry(
    hass: HomeAssistant, entry: ConfigEntry, async_add_entities: AddEntitiesCallback
) -> None:
    """Set up Octopus Germany from a config entry."""
    # Using existing coordinator from hass.data[DOMAIN] to avoid duplicate API calls
    data = hass.data[DOMAIN][entry.entry_id]
    coordinator = data["coordinator"]
    account_number = data["account_number"]

    # Wait for coordinator refresh if needed
    if coordinator.data is None:
        _LOGGER.debug("No data in coordinator, triggering refresh")
        await coordinator.async_refresh()

    sensors = [OctopusIntelligentDispatchingBinarySensor(account_number, coordinator)]

    # Add any additional sensors you might want here

    async_add_entities(sensors)


class OctopusIntelligentDispatchingBinarySensor(CoordinatorEntity, BinarySensorEntity):
    """Binary sensor for Octopus Intelligent Dispatching."""

    def __init__(self, account_number, coordinator) -> None:
        """Initialize the binary sensor for intelligent dispatching."""
        super().__init__(coordinator)

        self._account_number = account_number
        self._attr_name = f"Octopus {account_number} Intelligent Dispatching"
        self._attr_unique_id = f"octopus_{account_number}_intelligent_dispatching"
        self._attr_device_class = BinarySensorDeviceClass.PLUG
        self._attr_has_entity_name = False
        self._attributes = {}

        # Initialize attributes right after creation
        self._update_attributes()

    @property
    def is_on(self) -> bool:
        """Determine if the binary sensor is currently active."""
        if (
            not self.coordinator.data
            or not isinstance(self.coordinator.data, dict)
            or self._account_number not in self.coordinator.data
        ):
            return False

        account_data = self.coordinator.data[self._account_number]
        planned_dispatches = account_data.get("planned_dispatches", [])
        now = utcnow()  # Use timezone-aware datetime

        for dispatch in planned_dispatches:
            try:
                start_str = dispatch.get("start")
                end_str = dispatch.get("end")

                if not start_str or not end_str:
                    continue

                # Parse string to datetime and ensure it's UTC timezone-aware
                start = as_utc(parse_datetime(start_str))
                end = as_utc(parse_datetime(end_str))

                if start and end and start <= now <= end:
                    return True
            except (ValueError, TypeError):
                continue
        return False

    def _format_dispatch(self, dispatch, is_planned=True):
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
            "account_number": self._account_number,
            "electricity_balance": "0.00 €",
            "planned_dispatches": [],
            "completed_dispatches": [],
            "provider": "Unknown",
            "vehicle_battery_size_in_kwh": "Unknown",
            "current_start": "Unknown",
            "current_end": "Unknown",
            "devices": [],
            "products": [],
            "malo_number": "Unknown",
            "melo_number": "Unknown",
            "meter": {},
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

        # Extract all required data with safe fallbacks
        electricity_balance = account_data.get("electricity_balance", 0)
        planned_dispatches = account_data.get("planned_dispatches", [])
        completed_dispatches = account_data.get("completed_dispatches", [])
        devices = account_data.get("devices", [])
        products = account_data.get("products", [])
        vehicle_battery_size = account_data.get("vehicle_battery_size_in_kwh")
        current_start = account_data.get("current_start")
        current_end = account_data.get("current_end")
        malo_number = account_data.get("malo_number", "Unknown")
        melo_number = account_data.get("melo_number", "Unknown")
        meter = account_data.get("meter", {}) or {}

        # Get current state from devices if available
        current_state = "Unknown"
        provider = "Unknown"
        if devices:
            current_state = (
                devices[0].get("status", {}).get("currentState", "Unknown")
                if devices
                else "Unknown"
            )
            provider = devices[0].get("provider", "Unknown") if devices else "Unknown"

        # Format dispatches for display
        formatted_planned_dispatches = []
        if planned_dispatches:
            for dispatch in planned_dispatches:
                formatted = self._format_dispatch(dispatch, is_planned=True)
                if formatted:
                    formatted_planned_dispatches.append(formatted)

        formatted_completed_dispatches = []
        if completed_dispatches:
            for dispatch in completed_dispatches:
                formatted = self._format_dispatch(dispatch, is_planned=False)
                if formatted:
                    formatted_completed_dispatches.append(formatted)

        # Format current_start and current_end if available
        formatted_current_start = "Unknown"
        if current_start:
            try:
                formatted_current_start = as_local(current_start).strftime(
                    "%Y-%m-%d %H:%M:%S"
                )
            except (ValueError, TypeError, AttributeError) as e:
                _LOGGER.error(
                    "Error formatting current_start: %s - %s", current_start, e
                )

        formatted_current_end = "Unknown"
        if current_end:
            try:
                formatted_current_end = as_local(current_end).strftime(
                    "%Y-%m-%d %H:%M:%S"
                )
            except (ValueError, TypeError, AttributeError) as e:
                _LOGGER.error("Error formatting current_end: %s - %s", current_end, e)

        # Process products to ensure they are serializable
        processed_products = []
        for product in products:
            if not isinstance(product, dict):
                continue
            processed_products.append(
                {
                    "code": product.get("code", "Unknown"),
                    "name": product.get("name", "Unknown"),
                    "description": product.get("description", ""),
                    "gross_rate": product.get("grossRate", "0"),
                    "type": product.get("type", "Unknown"),
                    "valid_from": product.get("validFrom", ""),
                    "valid_to": product.get("validTo", ""),
                }
            )

        # Simplify device data to ensure it's serializable and include preferences
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
            }

            # Process preferences if available
            if "preferences" in device:
                device_preferences = self._process_device_preferences(device)
                if device_preferences:
                    simple_device["preferences"] = device_preferences

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
            "account_number": self._account_number,
            "electricity_balance": f"{electricity_balance:.2f} €",
            "planned_dispatches": formatted_planned_dispatches,
            "completed_dispatches": formatted_completed_dispatches,
            "provider": provider,
            "vehicle_battery_size_in_kwh": vehicle_battery_size
            if vehicle_battery_size is not None
            else "Unknown",
            "current_start": formatted_current_start,
            "current_end": formatted_current_end,
            "devices": simplified_devices,
            "products": processed_products,
            "malo_number": malo_number,
            "melo_number": melo_number,
            "meter": meter or {},
            "current_state": current_state,
            "last_updated": datetime.now().isoformat(),
        }

    @callback
    def _handle_coordinator_update(self) -> None:
        """Handle updated data from the coordinator."""
        self._update_attributes()
        self.async_write_ha_state()

    @property
    def extra_state_attributes(self) -> Dict[str, Any]:
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
