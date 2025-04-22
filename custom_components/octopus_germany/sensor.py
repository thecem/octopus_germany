"""
This module provides integration with Octopus Germany for Home Assistant.

It defines the coordinator and binary sensor entities to fetch and display
data related to electricity accounts, dispatches, and devices.
"""

import logging
from datetime import datetime, timedelta
from typing import Any, Dict
from collections.abc import Mapping

from homeassistant.components.binary_sensor import (
    BinarySensorEntity,
    BinarySensorDeviceClass,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ConfigEntryNotReady
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity
from homeassistant.util.dt import as_local

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
    if not coordinator.data:
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

    @property
    def is_on(self) -> bool:
        """Determine if the binary sensor is currently active."""
        if (
            not self.coordinator.data
            or self._account_number not in self.coordinator.data
        ):
            return False

        account_data = self.coordinator.data[self._account_number]
        planned_dispatches = account_data.get("planned_dispatches", [])
        now = datetime.now()

        for dispatch in planned_dispatches:
            try:
                start = datetime.fromisoformat(dispatch.get("start"))
                end = datetime.fromisoformat(dispatch.get("end"))
                if start <= now <= end:
                    return True
            except (ValueError, TypeError):
                continue
        return False

    def _update_attributes(self) -> None:
        """Update the internal attributes dictionary."""
        if (
            not self.coordinator.data
            or self._account_number not in self.coordinator.data
        ):
            _LOGGER.debug("No data available for account %s", self._account_number)
            self._attributes = {
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
            return

        # Process data from the coordinator
        account_data = self.coordinator.data[self._account_number]

        # Extract all required data
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
        meter = account_data.get("meter", {})

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
        for dispatch in planned_dispatches:
            try:
                start = datetime.fromisoformat(dispatch.get("start"))
                end = datetime.fromisoformat(dispatch.get("end"))
                formatted_planned_dispatches.append(
                    {
                        "start": as_local(start).strftime("%Y-%m-%d %H:%M:%S"),
                        "end": as_local(end).strftime("%Y-%m-%d %H:%M:%S"),
                        "charge_in_kwh": float(dispatch.get("deltaKwh", 0)),
                        "source": dispatch.get("meta", {}).get("source", "Unknown"),
                        "location": dispatch.get("meta", {}).get("location", "Unknown"),
                    }
                )
            except (ValueError, TypeError) as e:
                _LOGGER.error("Error formatting dispatch: %s - %s", dispatch, e)

        formatted_completed_dispatches = []
        for dispatch in completed_dispatches:
            try:
                start = datetime.fromisoformat(dispatch.get("start"))
                end = datetime.fromisoformat(dispatch.get("end"))
                formatted_completed_dispatches.append(
                    {
                        "start": as_local(start).strftime("%Y-%m-%d %H:%M:%S"),
                        "end": as_local(end).strftime("%Y-%m-%d %H:%M:%S"),
                        "charge_in_kwh": float(dispatch.get("deltaKwh", 0)),
                        "source": dispatch.get("meta", {}).get("source", "Unknown"),
                        "location": dispatch.get("meta", {}).get("location", "Unknown"),
                    }
                )
            except (ValueError, TypeError) as e:
                _LOGGER.error("Error formatting dispatch: %s - %s", dispatch, e)

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
            "devices": devices,
            "products": products,
            "malo_number": malo_number,
            "melo_number": melo_number,
            "meter": meter or {},
            "current_state": current_state,
        }

    @property
    def extra_state_attributes(self) -> Dict[str, Any]:
        """Return additional state attributes for the binary sensor."""
        self._update_attributes()
        return self._attributes

    async def async_update(self) -> None:
        """Update the entity."""
        await super().async_update()
        self._update_attributes()

    @property
    def available(self) -> bool:
        """Return True if entity is available."""
        return (
            self.coordinator.last_update_success
            and self._account_number in self.coordinator.data
        )
