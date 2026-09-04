"""Coordinator helpers for the Octopus Germany integration."""

from __future__ import annotations

from datetime import timedelta
from typing import TYPE_CHECKING, Any

from homeassistant.helpers.update_coordinator import DataUpdateCoordinator

if TYPE_CHECKING:
    from collections.abc import Awaitable, Callable
    from logging import Logger

    from homeassistant.core import HomeAssistant


def normalize_update_interval(value: object, default: int) -> int:
    """Return a polling interval constrained to the supported range."""
    try:
        interval = int(value)
    except TypeError, ValueError:
        interval = default
    return max(1, min(60, interval))


class OctopusDataCoordinator(DataUpdateCoordinator[dict[str, Any]]):
    """Coordinate normalized account data for one config entry."""

    def __init__(
        self,
        hass: HomeAssistant,
        logger: Logger,
        name: str,
        update_method: Callable[[], Awaitable[dict[str, Any]]],
        update_interval_minutes: int,
    ) -> None:
        """Initialize the normalized account data coordinator."""
        super().__init__(
            hass,
            logger,
            name=name,
            update_method=update_method,
            update_interval=timedelta(minutes=update_interval_minutes),
        )
