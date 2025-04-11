"""Switch platform for Octopus Germany."""

import asyncio
import logging
from collections.abc import Callable, Coroutine
from dataclasses import dataclass
from typing import Any

from homeassistant.components.switch import (
    SwitchDeviceClass,
    SwitchEntity,
    SwitchEntityDescription,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .const import DOMAIN
from .octopus_germany import OctopusGermany

_LOGGER = logging.getLogger(__name__)


@dataclass(frozen=True)
class OctopusRequiredKeysMixin:
    """Mixin for required keys."""

    value_fn: Callable[[Any], bool]
    switch_fn: Callable[[Any, str, str], Coroutine[Any, Any, Any]]


@dataclass(frozen=True)
class OctopusSwitchEntityDescription(SwitchEntityDescription, OctopusRequiredKeysMixin):
    """Describes Octopus switch entity."""


SWITCHES: list[OctopusSwitchEntityDescription] = [
    OctopusSwitchEntityDescription(
        key="device_suspension",
        device_class=SwitchDeviceClass.SWITCH,
        value_fn=lambda data: not data.get("status", {}).get("isSuspended", True),
        switch_fn=lambda api, device_id, action: api.change_device_suspension(
            device_id, action
        ),
    ),
]


async def async_setup_entry(
    hass: HomeAssistant,
    config_entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up the Octopus switch from config entry."""
    api_data = hass.data[DOMAIN][config_entry.entry_id]
    api = api_data["api"]
    account_number = api_data["account_number"]

    devices = await api.devices(account_number)

    switches = [OctopusSwitch(api, device, config_entry) for device in devices]

    async_add_entities(switches, update_before_add=True)


class OctopusSwitch(SwitchEntity):
    """Representation of an Octopus Switch entity."""

    def __init__(
        self, api: OctopusGermany, device: dict, config_entry: ConfigEntry
    ) -> None:
        """Initialize the Octopus switch entity.

        Args:
            api (OctopusGermany): The API instance for interacting with Octopus Germany.
            device (dict): The device information dictionary.
            config_entry (ConfigEntry): The configuration entry for this integration.

        """
        self._api = api
        self._device = device
        self._config_entry = config_entry
        self._device_id = device["id"]
        account_number = self._config_entry.data.get("account_number")
        self._attr_name = f"Octopus {account_number} Device Smart Control"
        self._attr_unique_id = f"octopus_{account_number}_device_smart_control"
        self._attr_extra_state_attributes = {
            "device_name": self._device.get("name", "Unknown"),
            "device_id": self._device_id,
        }
        self._is_on = not device.get("status", {}).get("isSuspended", True)

    @property
    def is_on(self) -> bool:
        """Return the current state of the switch."""
        return self._is_on

    async def async_turn_on(self, **kwargs) -> None:
        """Turn the switch on."""
        _LOGGER.debug(
            "Sending API request to change device suspension: device_id=%s, action=%s",
            self._device_id,
            "UNSUSPEND",
        )
        success = await self._api.change_device_suspension(self._device_id, "UNSUSPEND")
        if success:
            self._is_on = True
            self.async_write_ha_state()
            await asyncio.sleep(
                3
            )  # Wait for 3 seconds to ensure the API updates the state
        else:
            _LOGGER.error("Failed to turn on device: device_id=%s", self._device_id)

    async def async_turn_off(self, **kwargs) -> None:
        """Turn the switch off."""
        _LOGGER.debug(
            "Sending API request to change device suspension: device_id=%s, action=%s",
            self._device_id,
            "SUSPEND",
        )
        success = await self._api.change_device_suspension(self._device_id, "SUSPEND")
        if success:
            self._is_on = False
            self.async_write_ha_state()
            await asyncio.sleep(
                3
            )  # Wait for 3 seconds to ensure the API updates the state
        else:
            _LOGGER.error("Failed to turn off device: device_id=%s", self._device_id)

    async def async_update(self) -> None:
        """Fetch new state data for the switch."""
        api_data = self.hass.data[DOMAIN][self._config_entry.entry_id]
        account_number = api_data["account_number"]
        devices = await self._api.devices(account_number)
        device = next((d for d in devices if d["id"] == self._device_id), None)
        if device:
            self._is_on = not device.get("status", {}).get("isSuspended", True)
