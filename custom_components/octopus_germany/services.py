"""Service handlers for the Octopus Germany integration."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from .const import DOMAIN

if TYPE_CHECKING:
    from homeassistant.core import HomeAssistant


async def async_request_intelligent_refresh(
    hass: HomeAssistant, account_number: str | None = None
) -> int:
    """Refresh Intelligent coordinators, optionally limited to an account."""
    refreshed = 0
    for entry_data in hass.data.get(DOMAIN, {}).values():
        if account_number and account_number not in entry_data.get(
            "account_numbers", []
        ):
            continue
        intelligent = entry_data.get("intelligent_coordinator")
        if intelligent is not None:
            await intelligent.async_request_refresh()
            refreshed += 1
    return refreshed


async def async_handle_refresh_intelligent_data(
    hass: HomeAssistant, _call: Any
) -> None:
    """Request an immediate refresh of available Intelligent data."""
    await async_request_intelligent_refresh(hass)
