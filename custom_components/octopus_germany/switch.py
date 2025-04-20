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

from .const import DOMAIN

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

    # Warten auf die ersten Daten vom Coordinator
    await coordinator.async_config_entry_first_refresh()

    # Geräte aus den Coordinator-Daten abrufen
    devices = coordinator.data.get("devices", [])

    switches = []
    for device in devices:
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

        # Füge ein Flag hinzu, um zu verfolgen, ob die Umschaltung noch läuft
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

    @property
    def is_on(self) -> bool:
        """Return the current state of the switch."""
        # Wenn ein Umschaltvorgang aktiv ist, gib den ausstehenden Zustand zurück
        if self._is_switching and self._pending_state is not None:
            # Überprüfe, ob das Timeout überschritten wurde
            if self._pending_until and datetime.now() > self._pending_until:
                # Timeout wurde überschritten, zurück zum API-Status
                self._is_switching = False
                self._pending_state = None
                self._pending_until = None
                _LOGGER.warning(
                    "Switch state change timeout reached for device_id=%s. Reverting to API state.",
                    self._device_id,
                )
            else:
                # Timeout noch nicht überschritten, gib den ausstehenden Zustand zurück
                return self._pending_state

        # Verwende den API-Zustand, wenn kein Umschaltvorgang aktiv ist
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

        # Setze den ausstehenden Zustand sofort
        self._is_switching = True
        self._pending_state = True
        self._pending_until = datetime.now() + timedelta(minutes=5)  # 5 Minuten Timeout
        self.async_write_ha_state()

        # Sende die API-Anfrage
        success = await self._api.change_device_suspension(self._device_id, "UNSUSPEND")
        if success:
            _LOGGER.debug(
                "Successfully turned on device: device_id=%s", self._device_id
            )
            # Wir behalten den ausstehenden Zustand bei, bis die API bestätigt

            # Trigger a coordinator refresh after a delay to get updated data
            await asyncio.sleep(3)  # Warte 3 Sekunden, damit die API Zeit hat
            await self.coordinator.async_request_refresh()
        else:
            _LOGGER.error("Failed to turn on device: device_id=%s", self._device_id)
            # Bei Fehler: Zurücksetzen des ausstehenden Zustands
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

        # Setze den ausstehenden Zustand sofort
        self._is_switching = True
        self._pending_state = False
        self._pending_until = datetime.now() + timedelta(minutes=5)  # 5 Minuten Timeout
        self.async_write_ha_state()

        # Sende die API-Anfrage
        success = await self._api.change_device_suspension(self._device_id, "SUSPEND")
        if success:
            _LOGGER.debug(
                "Successfully turned off device: device_id=%s", self._device_id
            )
            # Wir behalten den ausstehenden Zustand bei, bis die API bestätigt

            # Trigger a coordinator refresh after a delay to get updated data
            await asyncio.sleep(3)  # Warte 3 Sekunden, damit die API Zeit hat
            await self.coordinator.async_request_refresh()
        else:
            _LOGGER.error("Failed to turn off device: device_id=%s", self._device_id)
            # Bei Fehler: Zurücksetzen des ausstehenden Zustands
            self._is_switching = False
            self._pending_state = None
            self._pending_until = None
            self.async_write_ha_state()

    def _get_device(self):
        """Get the device data from the coordinator data."""
        if not self.coordinator.data:
            return None

        devices = self.coordinator.data.get("devices", [])
        device = next((d for d in devices if d["id"] == self._device_id), None)

        # Wenn wir ein Gerät haben und der Umschaltvorgang noch läuft
        if device and self._is_switching:
            status = device.get("status", {})
            is_suspended = status.get("isSuspended", True)
            actual_state = not is_suspended

            # Überprüfe, ob der API-Zustand mit dem ausstehenden Zustand übereinstimmt
            if actual_state == self._pending_state:
                # API hat den Zustandswechsel bestätigt, setze Umschaltvorgang zurück
                self._is_switching = False
                self._pending_state = None
                self._pending_until = None
                _LOGGER.debug(
                    "API confirmed state change for device_id=%s to %s",
                    self._device_id,
                    "on" if actual_state else "off",
                )

        return device
