"""Switch platform for Octopus Germany."""

import logging
from datetime import datetime, timedelta
import asyncio
from typing import Any, Callable, Optional, Dict, List

from homeassistant.components.switch import SwitchEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity
from homeassistant.helpers.entity import DeviceInfo
from homeassistant.exceptions import HomeAssistantError
from homeassistant.const import STATE_ON, STATE_OFF, STATE_UNKNOWN

from .const import DOMAIN, UPDATE_INTERVAL
from .sensor import get_account_device_info

_LOGGER = logging.getLogger(__name__)


async def async_setup_entry(
    hass: HomeAssistant,
    config_entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up the Octopus switch from config entry."""
    _LOGGER.debug(
        "Setting up switch platform at %s", datetime.now().strftime("%H:%M:%S")
    )

    data = hass.data[DOMAIN][config_entry.entry_id]
    api = data["api"]
    account_number = data["account_number"]
    coordinator = data["coordinator"]

    # Check for valid data in coordinator
    if not coordinator.data:
        _LOGGER.info("No data in coordinator, not creating switches")
        return

    # Get all account numbers from entry data or coordinator data
    account_numbers = config_entry.data.get("account_numbers", [])
    if not account_numbers and account_number:
        account_numbers = [account_number]

    # If still no account numbers, try to get them from coordinator data
    if not account_numbers and coordinator.data:
        account_numbers = list(coordinator.data.keys())

    _LOGGER.debug("Creating switches for accounts: %s", account_numbers)

    switches = []

    for acc_num in account_numbers:
        if acc_num not in coordinator.data:
            _LOGGER.info(
                "No data for account %s found in coordinator data, not creating switches",
                acc_num,
            )
            continue

        # Extract devices from the coordinator data structure
        account_data = coordinator.data.get(acc_num, {})
        devices = account_data.get("devices", [])

        if not devices:
            _LOGGER.info(
                "No devices found for account %s, not creating switches", acc_num
            )
            continue

        # Only create switches if we have valid devices
        for device in devices:
            if "id" not in device:
                _LOGGER.warning("Device missing ID field: %s", device)
                continue
            switches.append(
                OctopusSwitch(api, device, coordinator, config_entry, acc_num)
            )

    # Only add entities if we have any
    if switches:
        async_add_entities(switches, update_before_add=True)
    else:
        _LOGGER.info("No valid devices to create switches for any account")

    # Setup boost charge switches (always enabled)
    await _setup_boost_charge_switches(
        hass, config_entry, async_add_entities, api, account_number
    )


async def _setup_boost_charge_switches(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
    client,
    account_number: str,
) -> None:
    """Set up boost charge switches."""
    try:
        # Use the existing main coordinator instead of creating a separate one
        # This avoids token management issues
        data = hass.data[DOMAIN][entry.entry_id]
        coordinator = data["coordinator"]

        # Get current data from main coordinator
        account_data = (
            coordinator.data.get(account_number, {}) if coordinator.data else {}
        )
        devices = account_data.get("devices", [])

        # Create switches for each electric vehicle/charge point
        switches = []

        for device in devices:
            device_id = device.get("id")
            device_type = device.get("deviceType")
            device_name = device.get("name", f"Device {device_id}")

            # Only create boost charge switches for electric vehicles and charge points
            if device_type in ["ELECTRIC_VEHICLES", "CHARGE_POINTS"] and device_id:
                switches.append(
                    BoostChargeSwitch(
                        coordinator, client, device_id, device_name, account_number
                    )
                )

        if switches:
            async_add_entities(switches)
            _LOGGER.info(
                "Set up %d boost charge switches for %d devices",
                len(switches),
                len(
                    [
                        d
                        for d in devices
                        if d.get("deviceType") in ["ELECTRIC_VEHICLES", "CHARGE_POINTS"]
                    ]
                ),
            )
        else:
            _LOGGER.info(
                "No electric vehicles or charge points found for boost charge switches"
            )

    except Exception as err:
        _LOGGER.error("Failed to set up boost charge switches: %s", err)


class OctopusSwitch(CoordinatorEntity, SwitchEntity):
    """Representation of an Octopus Switch entity."""

    def __init__(self, api, device, coordinator, config_entry, account_number) -> None:
        """Initialize the Octopus switch entity."""
        super().__init__(coordinator)
        self._api = api
        self._device = device
        self._config_entry = config_entry
        self._device_id = device["id"]
        self._device_name = device.get("name", f"Device_{self._device_id}")
        self._account_number = account_number
        self._current_state = not device.get("status", {}).get("isSuspended", True)

        # Add flag to track if switching is in progress
        self._is_switching = False
        self._pending_state = None
        self._pending_until = None

        # Normalisiere device name für unique_id
        norm_name = self._device_name.lower().replace(" ", "_")
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
            f"Octopus {self._account_number} {self._device_name} Smart Control"
        )
        self._attr_unique_id = (
            f"octopus_{self._account_number}_{norm_name}_smart_control"
        )
        self._update_attributes()

    def _update_attributes(self):
        """Update device attributes based on the latest data."""
        device = self._get_device()
        if not device:
            return

        # Update extra state attributes
        self._attr_extra_state_attributes = {
            "device_id": self._device_id,
            "name": device.get("name", "Unknown"),
            "model": device.get("vehicleVariant", {}).get("model", "Unknown"),
            "battery_size": device.get("vehicleVariant", {}).get(
                "batterySize", "Unknown"
            ),
            "provider": device.get("provider", "Unknown"),
            "status": device.get("status", {}).get("currentState", "Unknown"),
            "last_updated": datetime.now().isoformat(),
        }

    @callback
    def _handle_coordinator_update(self) -> None:
        """Handle updated data from the coordinator."""
        # Get fresh device data
        device = self._get_device()
        if device:
            # Check if state should change
            new_state = not device.get("status", {}).get("isSuspended", True)
            if new_state != self._current_state and not self._is_switching:
                _LOGGER.debug(
                    "Device state changed through API: %s -> %s (device_id=%s)",
                    self._current_state,
                    new_state,
                    self._device_id,
                )
                self._current_state = new_state

            # Update attributes with fresh data
            self._update_attributes()

            # Check if we're waiting for a state change and it's been confirmed
            if self._is_switching:
                status = device.get("status", {})
                is_suspended = status.get("isSuspended", True)
                actual_state = not is_suspended

                if actual_state == self._pending_state:
                    # API has confirmed state change, reset switching operation
                    _LOGGER.debug(
                        "API confirmed state change for device_id=%s to %s",
                        self._device_id,
                        "on" if actual_state else "off",
                    )
                    self._is_switching = False
                    self._pending_state = None
                    self._pending_until = None
                    self._current_state = actual_state

        # Mark entity for update
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
                    "Switch state change timeout reached for device_id=%s, reverting to API state",
                    self._device_id,
                )
            else:
                # Timeout not exceeded, return pending state
                return self._pending_state

        # Use API state if no switching operation is active
        device = self._get_device()
        if device:
            self._current_state = not device.get("status", {}).get("isSuspended", True)
            return self._current_state
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

        # Access account data first, then devices
        account_data = self.coordinator.data.get(self._account_number, {})
        devices = account_data.get("devices", [])

        if not devices:
            _LOGGER.debug("Devices list is empty for account %s", self._account_number)
            return None

        return next((d for d in devices if d["id"] == self._device_id), None)

    @property
    def available(self) -> bool:
        """Return if entity is available."""
        # The entity is available if the coordinator has data and the specific device exists
        coordinator_has_data = (
            self.coordinator.last_update_success
            and self._account_number in self.coordinator.data
        )
        device_exists = self._get_device() is not None
        return coordinator_has_data and device_exists

    @property
    def device_info(self) -> DeviceInfo:
        """Return device information."""
        return get_account_device_info(self._account_number)


class BoostChargeSwitch(CoordinatorEntity, SwitchEntity):
    """Switch to control boost charging for a specific device."""

    def __init__(
        self,
        coordinator,  # Now uses main coordinator
        client,
        device_id: str,
        device_name: str,
        account_number: str,
    ) -> None:
        """Initialize the switch."""
        super().__init__(coordinator)
        self.coordinator = coordinator
        self.client = client
        self.device_id = device_id
        self.device_name = device_name
        self.account_number = account_number
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
        self._attr_unique_id = f"{DOMAIN}_{account_number}_{norm_name}_boost_charge"
        self._attr_name = f"Octopus {account_number} {device_name} Boost Charge"
        self._attr_icon = "mdi:lightning-bolt"

    def _get_device_data(self) -> Dict[str, Any]:
        """Get device data from main coordinator."""
        if not self.coordinator.data:
            return {}

        account_data = self.coordinator.data.get(self.account_number, {})
        devices = account_data.get("devices", [])

        # Find our device in the devices list
        for device in devices:
            if device.get("id") == self.device_id:
                return device

        return {}

    @property
    def is_on(self) -> bool:
        """Return true if boost charging is active."""
        device_data = self._get_device_data()
        if not device_data:
            return False

        # Check device status for boost charge indicators
        status = device_data.get("status", {})
        current_state = status.get("currentState", "")

        # Consider boost charging active if state contains boost indicators
        return "BOOST" in current_state.upper()

    @property
    def available(self) -> bool:
        """Return if entity is available."""
        if not self.coordinator.last_update_success:
            return False

        device_data = self._get_device_data()
        if not device_data:
            return False

        # Device is available if we have valid data and it's not suspended
        status = device_data.get("status", {})
        return not status.get("isSuspended", True)

    @property
    def extra_state_attributes(self) -> Dict[str, Any]:
        """Return additional state attributes."""
        device_data = self._get_device_data()
        if not device_data:
            return {}

        status = device_data.get("status", {})

        # Calculate boost charge states
        current_state = status.get("currentState", "")
        boost_charge_active = "BOOST" in current_state.upper()

        # Calculate boost charge availability
        current = status.get("current", "")
        is_suspended = status.get("isSuspended", False)
        is_live = current == "LIVE"
        has_smart_control = "SMART_CONTROL_CAPABLE" in current_state
        has_boost_state = "BOOST" in current_state.upper()
        has_boost_charging = "BOOST_CHARGING" in current_state.upper()

        boost_charge_available = (
            is_live
            and (has_smart_control or has_boost_state or has_boost_charging)
            and not is_suspended
        )

        return {
            "device_type": device_data.get("deviceType"),
            "provider": device_data.get("provider"),
            "current_status": status.get("current"),
            "current_state": status.get("currentState"),
            "is_suspended": status.get("isSuspended"),
            "device_id": self.device_id,
            "account_number": self.account_number,
            "boost_charge_active": boost_charge_active,
            "boost_charge_available": boost_charge_available,
        }

    async def async_turn_on(self, **kwargs: Any) -> None:
        """Turn on boost charging."""
        await self._async_trigger_boost_charge()

    async def async_turn_off(self, **kwargs: Any) -> None:
        """Turn off boost charging."""
        await self._async_cancel_boost_charge()

    async def _async_trigger_boost_charge(self) -> None:
        """Trigger boost charging using updateBoostCharge mutation."""
        mutation = """
        mutation triggerBoostCharge($input: UpdateBoostChargeInput!) {
            updateBoostCharge(input: $input) {
                id
            }
        }
        """

        variables = {"input": {"deviceId": self.device_id, "action": "BOOST"}}

        try:
            # Use the OctopusGermany API client's method
            client = self.client._get_graphql_client()

            response = await client.execute_async(query=mutation, variables=variables)

            if "errors" in response:
                error_messages = [
                    error.get("message", "Unknown error")
                    for error in response["errors"]
                ]
                error_str = "; ".join(error_messages)
                _LOGGER.error("GraphQL errors triggering boost charge: %s", error_str)
                raise HomeAssistantError(f"GraphQL errors: {error_str}")

            result = response.get("data", {}).get("updateBoostCharge")
            if result is None:
                raise HomeAssistantError("No result from updateBoostCharge mutation")

            # Success case - mutation returned without GraphQL errors
            _LOGGER.info(
                "Successfully triggered boost charge for device %s", self.device_id
            )

            # Request coordinator refresh to update state
            await self.coordinator.async_request_refresh()

        except Exception as err:
            _LOGGER.error(
                "Failed to trigger boost charge for device %s: %s", self.device_id, err
            )
            raise HomeAssistantError(f"Failed to trigger boost charge: {err}")

    async def _async_cancel_boost_charge(self) -> None:
        """Cancel boost charging using updateBoostCharge mutation."""
        mutation = """
        mutation cancelBoostCharge($input: UpdateBoostChargeInput!) {
            updateBoostCharge(input: $input) {
                id
            }
        }
        """

        variables = {"input": {"deviceId": self.device_id, "action": "CANCEL"}}

        try:
            # Use the OctopusGermany API client's method
            client = self.client._get_graphql_client()

            response = await client.execute_async(query=mutation, variables=variables)

            if "errors" in response:
                error_messages = [
                    error.get("message", "Unknown error")
                    for error in response["errors"]
                ]
                error_str = "; ".join(error_messages)
                _LOGGER.error("GraphQL errors canceling boost charge: %s", error_str)
                raise HomeAssistantError(f"GraphQL errors: {error_str}")

            result = response.get("data", {}).get("updateBoostCharge")
            if result is None:
                raise HomeAssistantError("No result from updateBoostCharge mutation")

            # Success case - mutation returned without GraphQL errors
            _LOGGER.info(
                "Successfully canceled boost charge for device %s", self.device_id
            )

            # Request coordinator refresh to update state
            await self.coordinator.async_request_refresh()

        except Exception as err:
            _LOGGER.error(
                "Failed to cancel boost charge for device %s: %s", self.device_id, err
            )
            raise HomeAssistantError(f"Failed to cancel boost charge: {err}")

    @property
    def device_info(self) -> DeviceInfo:
        """Return device information."""
        return get_account_device_info(self.account_number)
