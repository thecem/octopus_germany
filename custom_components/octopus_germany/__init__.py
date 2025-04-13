"""Octopus Germany Integration.

This module provides integration with the Octopus Germany API for Home Assistant.
"""

from __future__ import annotations

import logging

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import Platform
from homeassistant.core import HomeAssistant

from .const import DOMAIN
from .octopus_germany import OctopusGermany

_LOGGER = logging.getLogger(__name__)

PLATFORMS: list[Platform] = [Platform.SENSOR, Platform.SWITCH]


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Set up Octopus Germany from a config entry."""
    email = entry.data["email"]
    password = entry.data["password"]

    api = OctopusGermany(email, password)
    if not await api.login():
        return False

    # Ensure DOMAIN is initialized in hass.data
    if DOMAIN not in hass.data:
        hass.data[DOMAIN] = {}

    # Ensure account_number is fetched and stored during setup
    account_number = entry.data.get("account_number")
    if not account_number:
        _LOGGER.error("No accounts found for the provided credentials")
        accounts = await api.fetch_accounts()
        if not accounts:
            _LOGGER.error("No accounts found for the provided credentials")
            return False
        account_number = accounts[0]["number"]  # Use the first account by default

        # Persist the account_number in the config entry
        hass.config_entries.async_update_entry(
            entry, data={**entry.data, "account_number": account_number}
        )

    hass.data[DOMAIN][entry.entry_id] = {"api": api, "account_number": account_number}

    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)

    entry.async_on_unload(entry.add_update_listener(_async_update_options))
    return True


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Unload a config entry."""
    if unload_ok := await hass.config_entries.async_unload_platforms(entry, ["switch"]):
        hass.data[DOMAIN].pop(entry.entry_id)

    return unload_ok


async def _async_update_options(hass: HomeAssistant, config_entry: ConfigEntry) -> None:
    """Handle options update."""
    # update entry replacing data with new options
    hass.config_entries.async_update_entry(
        config_entry, data={**config_entry.data, **config_entry.options}
    )
    await hass.config_entries.async_reload(config_entry.entry_id)
