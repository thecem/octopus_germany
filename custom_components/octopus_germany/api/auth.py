"""Authentication and token lifecycle for the Octopus Germany API."""

from __future__ import annotations

import asyncio
import logging
from datetime import UTC, datetime
from typing import Any

import jwt

from custom_components.octopus_germany.const import (
    TOKEN_AUTO_REFRESH_INTERVAL,
    TOKEN_REFRESH_MARGIN,
)

_LOGGER = logging.getLogger(__name__)

_TOKEN_MANAGERS: dict[str, TokenManager] = {}


class TokenManager:
    """Manage one shared JWT and its refresh task."""

    def __init__(self) -> None:
        """Initialize the token manager."""
        self._token: str | None = None
        self._expiry: float | int | None = None
        self._refresh_lock = asyncio.Lock()
        self._refresh_callback: Any = None
        self._refresh_task: asyncio.Task[None] | None = None

    @property
    def token(self) -> str | None:
        """Return the current token."""
        return self._token

    def set_refresh_callback(self, callback: Any) -> None:
        """Set the callback used for scheduled token refreshes."""
        self._refresh_callback = callback

    async def start_auto_refresh(self) -> None:
        """Start the scheduled refresh task."""
        if self._refresh_task is not None:
            self._refresh_task.cancel()
        self._refresh_task = asyncio.create_task(self._auto_refresh_token())
        _LOGGER.debug("Started automatic token refresh task")

    async def _auto_refresh_token(self) -> None:
        """Refresh the token periodically and survive transient failures."""
        try:
            while True:
                await asyncio.sleep(TOKEN_AUTO_REFRESH_INTERVAL)
                _LOGGER.info("Performing scheduled token refresh")
                try:
                    if self._refresh_callback is None:
                        _LOGGER.warning(
                            "No refresh callback set, cannot auto-refresh token"
                        )
                        continue
                    self._expiry = 0
                    await self._refresh_callback()
                    _LOGGER.debug("Scheduled token refresh completed")
                except (RuntimeError, ValueError, TypeError) as err:
                    _LOGGER.warning(
                        "Scheduled token refresh failed; will retry: %s", err
                    )
        except asyncio.CancelledError:
            _LOGGER.debug("Token auto-refresh task cancelled")

    @property
    def is_valid(self) -> bool:
        """Return whether the token has enough lifetime remaining."""
        if not self._token or not self._expiry:
            return False

        now = datetime.now(UTC).timestamp()
        valid = now < self._expiry - TOKEN_REFRESH_MARGIN
        if not valid:
            _LOGGER.debug(
                "Token validity check: INVALID (expiry in %s seconds)",
                int(self._expiry - now),
            )
        return valid

    def set_token(self, token: str, expiry: float | None = None) -> None:
        """Store a token and derive its expiry when necessary."""
        self._token = token
        now = datetime.now(UTC).timestamp()
        if expiry:
            self._expiry = expiry
            source = "explicit"
        else:
            source = "decoded"
            try:
                decoded = jwt.decode(token, options={"verify_signature": False})
                self._expiry = decoded.get("exp")
            except (TypeError, ValueError, jwt.PyJWTError) as err:
                self._expiry = now + TOKEN_AUTO_REFRESH_INTERVAL
                source = "fallback"
                _LOGGER.warning("Failed to decode token expiry: %s", err)
        _LOGGER.debug(
            "Token set with %s expiry - valid for %s seconds",
            source,
            int(self._expiry - now) if self._expiry else 0,
        )

    def clear(self) -> None:
        """Clear the current token and expiry."""
        self._token = None
        self._expiry = None
