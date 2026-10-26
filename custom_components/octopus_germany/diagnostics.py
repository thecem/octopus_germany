"""Read-only import diagnostics, deliberately excluding tokens and raw readings."""

from __future__ import annotations

from copy import deepcopy
from typing import TYPE_CHECKING, Any

from .const import DOMAIN
from .statistics import RECONCILIATION_VERSION

if TYPE_CHECKING:
    from homeassistant.config_entries import ConfigEntry
    from homeassistant.core import HomeAssistant


async def async_get_config_entry_diagnostics(
    hass: HomeAssistant, entry: ConfigEntry
) -> dict[str, Any]:
    """Expose progress/checkpoints without credentials or account identifiers."""
    importer = (
        hass.data.get(DOMAIN, {}).get(entry.entry_id, {}).get("statistics_reconciler")
    )
    if importer is None:
        return {"reconciliation": {"available": False}}
    task = importer.task
    return {
        "reconciliation": {
            "version": RECONCILIATION_VERSION,
            "running": task is not None and not task.done(),
            "halted": importer.stopped,
            "status": deepcopy(importer.status),
            "configuration_present": [
                {
                    "has_properties": bool(account.get("property_ids")),
                    "has_malo": bool(account.get("malo_number")),
                }
                for account in (importer.coordinator.data or {}).values()
            ],
            "task_location": [
                f"{frame.f_code.co_name}:{frame.f_lineno}" for frame in task.get_stack()
            ]
            if task and not task.done()
            else [],
            "accounts": [
                {
                    "interval_count": len(account.get("intervals", {})),
                    "last_success": account.get("last_success"),
                    "last_full_scan": account.get("last_full_scan"),
                    "diagnostics": deepcopy(account.get("diagnostics", {})),
                }
                for account in importer.data["accounts"].values()
            ],
        }
    }
