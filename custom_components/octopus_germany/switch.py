"""Switch platform for Octopus Germany."""

import logging
from datetime import datetime, timedelta
import asyncio
from typing import Any, Callable, Optional

from homeassistant.components.switch import SwitchEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import DOMAIN, UPDATE_INTERVAL

_LOGGER = logging.getLogger(__name__)


async def async_setup_entry(
    hass: HomeAssistant,
    config_entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up the Octopus switch from config entry."""
    data = hass.data[DOMAIN][config_entry.entry_id]
    api = data["api"]
    account_number = data["account_number"]
    coordinator = data["coordinator"]

    # Wait for initial data from coordinator
    await coordinator.async_config_entry_first_refresh()

    # Retrieve devices from coordinator data
    if not coordinator.data or "devices" not in coordinator.data:
        _LOGGER.error("No devices found in coordinator data")
        return

    devices = coordinator.data.get("devices", [])
    if not devices:
        _LOGGER.info("No devices found for account %s", account_number)
        return

    switches = []
    for device in devices:
        if "id" not in device:
            _LOGGER.warning("Device missing ID field: %s", device)
            continue
        switches.append(OctopusSwitch(api, device, coordinator, config_entry))

    async_add_entities(switches, update_before_add=False)


class OctopusSwitch(CoordinatorEntity, SwitchEntity):
    """Representation of an Octopus Switch entity."""

    def __init__(self, api, device, coordinator, config_entry):
        """Initialize the Octopus switch entity."""
        super().__init__(coordinator)
        self._api = api
        self._device = device
        self._config_entry = config_entry
        self._device_id = device["id"]
        self._last_update = None
        self._next_update = None

        # Add flag to track if switching is in progress
        self._is_switching = False
        self._pending_state = None
        self._pending_until = None

        account_number = self._config_entry.data.get("account_number")
        self._attr_name = f"Octopus {account_number} Device Smart Control"
        self._attr_unique_id = f"octopus_{account_number}_device_smart_control"

        # Set extra state attributes
        self._attr_extra_state_attributes = {
            "device_id": self._device_id,
            "name": self._attr_name,
            "device": self._device.get("name", "Unknown"),
        }

        # Set up callback for coordinator updates
        self.coordinator.async_add_listener(self._handle_coordinator_update)
        self._force_update_time = datetime.now() + timedelta(minutes=UPDATE_INTERVAL)
        _LOGGER.debug(
            "Switch created: %s with next update at %s",
            self._attr_name,
            self._force_update_time,
        )

    def _handle_coordinator_update(self) -> None:
        """Handle updated data from the coordinator."""
        _LOGGER.debug("Coordinator updated for switch %s", self._attr_name)
        now = datetime.now()

        if self._next_update and now < self._next_update:
            _LOGGER.debug("Skipping update, next update at %s", self._next_update)
            return

        # Check if coordinator data is valid
        if not self.coordinator.data:
            _LOGGER.error("Coordinator data is None for switch %s", self._attr_name)
            return

        # Check if devices exists in coordinator data
        if "devices" not in self.coordinator.data:
            _LOGGER.error(
                "No devices in coordinator data for switch %s", self._attr_name
            )
            return

        # Check if devices is not None
        devices = self.coordinator.data.get("devices")
        if devices is None:
            _LOGGER.error(
                "Devices list is None for switch %s - possible token timeout",
                self._attr_name,
            )
            # Request API token refresh on next update
            self._next_update = datetime.now() + timedelta(
                minutes=1
            )  # Try sooner than regular interval
            self.async_write_ha_state()
            return

        # Update cached data
        device = next(
            (d for d in devices if d["id"] == self._device_id),
            None,
        )
        if device:
            self._device = device
            _LOGGER.debug(
                "Device status updated: %s, isSuspended=%s",
                self._device_id,
                device.get("status", {}).get("isSuspended", True),
            )
        else:
            _LOGGER.warning(
                "Device with ID %s not found in devices list", self._device_id
            )

        self._next_update = datetime.now() + timedelta(minutes=UPDATE_INTERVAL)
        _LOGGER.debug("Next update scheduled for %s", self._next_update)
        self.async_write_ha_state()

    @property
    def is_on(self) -> bool:
        """Return the current state of the switch."""
        # If a switching operation is active, return the pending state
        if self._is_switching and self._pending_state is not None:
            # Check if timeout has been exceeded
            if self._pending_until and datetime.now() > self._pending_until:
                # Timeout exceeded, revert to API status
                self._is_switching = False
                self._pending_state = None
                self._pending_until = None
                _LOGGER.warning(
                    "Switch state change timeout reached for device_id=%s. Reverting to API state.",
                    self._device_id,
                )
            else:
                # Timeout not exceeded, return pending state
                return self._pending_state

        # Use API state if no switching operation is active
        device = self._get_device()
        if device:
            return not device.get("status", {}).get("isSuspended", True)
        return False

    async def async_turn_on(self, **kwargs) -> None:
        """Turn the switch on."""
        _LOGGER.debug(
            "Sending API request to change device suspension: device_id=%s, action=%s",
            self._device_id,
            "UNSUSPEND",
        )

        # Set pending state immediately
        self._is_switching = True
        self._pending_state = True
        self._pending_until = datetime.now() + timedelta(minutes=5)  # 5 minute timeout
        self.async_write_ha_state()

        # Send API request with retry logic
        try:
            # Send the API request
            success = await self._api.change_device_suspension(
                self._device_id, "UNSUSPEND"
            )
            if success:
                _LOGGER.debug(
                    "Successfully turned on device: device_id=%s", self._device_id
                )
                # We maintain pending state until API confirms

                # Trigger a coordinator refresh after a delay to get updated data
                await asyncio.sleep(3)  # Wait 3 seconds to give API time
                await self.coordinator.async_request_refresh()

                # Force our state update
                self._next_update = None
                self._handle_coordinator_update()
            else:
                _LOGGER.error("Failed to turn on device: device_id=%s", self._device_id)
                # On failure: Reset pending state
                self._is_switching = False
                self._pending_state = None
                self._pending_until = None
                self.async_write_ha_state()
        except Exception as ex:
            _LOGGER.exception("Error turning on device %s: %s", self._device_id, ex)
            # On exception: Reset pending state
            self._is_switching = False
            self._pending_state = None
            self._pending_until = None
            self.async_write_ha_state()

    async def async_turn_off(self, **kwargs) -> None:
        """Turn the switch off."""
        _LOGGER.debug(
            "Sending API request to change device suspension: device_id=%s, action=%s",
            self._device_id,
            "SUSPEND",
        )

        # Set pending state immediately
        self._is_switching = True
        self._pending_state = False
        self._pending_until = datetime.now() + timedelta(minutes=5)  # 5 minute timeout
        self.async_write_ha_state()

        try:
            # Send the API request
            success = await self._api.change_device_suspension(
                self._device_id, "SUSPEND"
            )
            if success:
                _LOGGER.debug(
                    "Successfully turned off device: device_id=%s", self._device_id
                )
                # We maintain pending state until API confirms

                # Trigger a coordinator refresh after a delay to get updated data
                await asyncio.sleep(3)  # Wait 3 seconds to give API time
                await self.coordinator.async_request_refresh()

                # Force our state update
                self._next_update = None
                self._handle_coordinator_update()
            else:
                _LOGGER.error(
                    "Failed to turn off device: device_id=%s", self._device_id
                )
                # On failure: Reset pending state
                self._is_switching = False
                self._pending_state = None
                self._pending_until = None
                self.async_write_ha_state()
        except Exception as ex:
            _LOGGER.exception("Error turning off device %s: %s", self._device_id, ex)
            # On exception: Reset pending state
            self._is_switching = False
            self._pending_state = None
            self._pending_until = None
            self.async_write_ha_state()

    def _get_device(self):
        """Get the device data from the coordinator data."""
        if not self.coordinator or not self.coordinator.data:
            return None

        devices = self.coordinator.data.get("devices", [])
        if devices is None:
            _LOGGER.debug("Devices list is None for device_id=%s", self._device_id)
            return None

        device = next((d for d in devices if d["id"] == self._device_id), None)

        # If we have a device and switching operation is still in progress
        if device and self._is_switching:
            status = device.get("status", {})
            is_suspended = status.get("isSuspended", True)
            actual_state = not is_suspended

            # Check if API state matches pending state
            if actual_state == self._pending_state:
                # API has confirmed state change, reset switching operation
                self._is_switching = False
                self._pending_state = None
                self._pending_until = None
                _LOGGER.debug(
                    "API confirmed state change for device_id=%s to %s",
                    self._device_id,
                    "on" if actual_state else "off",
                )

        return device

    async def async_update(self) -> None:
        """Request refresh if update interval has passed."""
        now = datetime.now()
        if self._force_update_time and now > self._force_update_time:
            _LOGGER.debug("Forcing update for switch %s", self._attr_name)
            self._force_update_time = now + timedelta(minutes=UPDATE_INTERVAL)
            await self.coordinator.async_request_refresh()

        # Reset next update time to ensure we handle the next update
        self._next_update = None
