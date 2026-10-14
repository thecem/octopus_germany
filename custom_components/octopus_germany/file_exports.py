"""Secure file storage and download notifications for integration exports."""

from __future__ import annotations

import re
import secrets
from datetime import UTC, datetime, timedelta
from html import escape
from pathlib import Path
from typing import TYPE_CHECKING
from urllib.parse import quote

from aiohttp import web
from homeassistant.components import persistent_notification
from homeassistant.helpers.http import HomeAssistantView
from homeassistant.helpers.storage import Store

from .const import DOMAIN

if TYPE_CHECKING:
    from homeassistant.core import HomeAssistant

_EXPORT_DIR = Path("octopus_germany") / "exports"
_VIEW_REGISTERED_KEY = f"{DOMAIN}_export_download_view_registered"
_TOKEN_STORE_KEY = f"{DOMAIN}_export_download_tokens"
_DOWNLOAD_TOKEN_TTL = timedelta(days=30)


class OctopusExportDownloadView(HomeAssistantView):
    """Serve integration exports with filename-scoped download tokens."""

    url = f"/api/{DOMAIN}/exports/{{filename}}"
    name = f"api:{DOMAIN}:exports"
    requires_auth = False

    def __init__(self, hass: HomeAssistant, export_directory: Path) -> None:
        """Initialize the view with the only directory it may serve."""
        self._hass = hass
        self._export_directory = export_directory.resolve()
        self._download_tokens: dict[str, tuple[str, datetime]] = {}
        self._token_store = Store(
            hass,
            1,
            _TOKEN_STORE_KEY,
            private=True,
        )
        self._tokens_loaded = False

    async def async_load_download_tokens(self) -> None:
        """Load unexpired download tokens from private Home Assistant storage."""
        stored_tokens = await self._token_store.async_load() or {}
        now = datetime.now(UTC)
        for filename, token_data in stored_tokens.items():
            try:
                token = token_data["token"]
                expires_at = datetime.fromisoformat(token_data["expires_at"])
            except KeyError, TypeError, ValueError:
                continue
            if expires_at.tzinfo is None:
                expires_at = expires_at.replace(tzinfo=UTC)
            if expires_at > now:
                self._download_tokens[filename] = (token, expires_at)
        self._tokens_loaded = True
        if len(self._download_tokens) != len(stored_tokens):
            await self._async_save_download_tokens()

    async def async_issue_download_token(self, filename: str) -> str:
        """Issue a short-lived, unguessable token scoped to one filename."""
        if not self._tokens_loaded:
            await self.async_load_download_tokens()
        token = secrets.token_urlsafe(32)
        expires_at = datetime.now(UTC) + _DOWNLOAD_TOKEN_TTL
        self._download_tokens[filename] = (token, expires_at)
        await self._async_save_download_tokens()
        return token

    async def _async_save_download_tokens(self) -> None:
        stored_tokens = {
            filename: {
                "token": token,
                "expires_at": expires_at.isoformat(),
            }
            for filename, (token, expires_at) in self._download_tokens.items()
        }
        await self._token_store.async_save(stored_tokens)

    def _has_valid_download_token(
        self, filename: str, supplied_token: str | None
    ) -> bool:
        """Check the unexpired query token issued for this filename."""
        entry = self._download_tokens.get(filename)
        if entry is None:
            return False
        expected_token, expires_at = entry
        if datetime.now(UTC) >= expires_at:
            self._download_tokens.pop(filename, None)
            return False
        return supplied_token is not None and secrets.compare_digest(
            supplied_token, expected_token
        )

    async def get(self, request: web.Request, filename: str) -> web.FileResponse:
        """Download one generated export file, without allowing path traversal."""
        if not self._has_valid_download_token(filename, request.query.get("token")):
            raise web.HTTPUnauthorized
        file_path = (self._export_directory / filename).resolve()
        if file_path.parent != self._export_directory or not file_path.is_file():
            raise web.HTTPNotFound
        return web.FileResponse(
            file_path,
            headers={"Content-Disposition": f'attachment; filename="{filename}"'},
        )


def export_file_path(hass: HomeAssistant, filename: str) -> Path:
    """Return a sanitized file path under the integration export directory."""
    safe_filename = re.sub(r"[^A-Za-z0-9_.-]+", "_", Path(filename).name).strip("._")
    if not safe_filename:
        msg = "Export filename contains no usable characters"
        raise ValueError(msg)
    return Path(hass.config.path(str(_EXPORT_DIR), safe_filename))


def export_download_url(filename: str, token: str) -> str:
    """Build the authenticated relative URL for one export."""
    encoded_filename = quote(filename, safe="")
    encoded_token = quote(token, safe="")
    return f"/api/{DOMAIN}/exports/{encoded_filename}?token={encoded_token}"


async def async_register_export_download_view(
    hass: HomeAssistant,
) -> OctopusExportDownloadView:
    """Register the authenticated export view once per Home Assistant instance."""
    if view := hass.data.get(_VIEW_REGISTERED_KEY):
        return view
    export_directory = Path(hass.config.path(str(_EXPORT_DIR)))
    view = OctopusExportDownloadView(hass, export_directory)
    await view.async_load_download_tokens()
    hass.http.register_view(view)
    hass.data[_VIEW_REGISTERED_KEY] = view
    return view


async def async_notify_export_ready(
    hass: HomeAssistant, filename: str, export_description: str
) -> str:
    """Create an HA persistent notification with a secure download link."""
    view = await async_register_export_download_view(hass)
    token = await view.async_issue_download_token(filename)
    url = export_download_url(filename, token)
    safe_url = escape(url, quote=True)
    safe_filename = escape(filename)
    persistent_notification.async_create(
        hass,
        f"{escape(export_description)} is ready. "
        f'<a href="{safe_url}" target="_blank">Download {safe_filename}</a>',
        title="Octopus Germany export ready",
        notification_id=f"{DOMAIN}_export_{filename}",
    )
    return url


async def async_notify_export_package_ready(
    hass: HomeAssistant, filenames: list[str], export_description: str
) -> dict[str, str]:
    """Create one notification with independently scoped links for a package."""
    view = await async_register_export_download_view(hass)
    urls = {}
    links = []
    for filename in filenames:
        token = await view.async_issue_download_token(filename)
        url = export_download_url(filename, token)
        urls[filename] = url
        links.append(
            f'<a href="{escape(url, quote=True)}" target="_blank">'
            f"Download {escape(filename)}</a>"
        )
    persistent_notification.async_create(
        hass,
        f"{escape(export_description)} is ready.\n\n" + "\n\n".join(links),
        title="Octopus Germany export package ready",
        notification_id=f"{DOMAIN}_export_{filenames[0]}",
    )
    return urls
