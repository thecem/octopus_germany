"""Restart-safe, correction-aware Octopus external statistics reconciliation."""

from __future__ import annotations

import asyncio
import logging
from copy import deepcopy
from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING, Any
from zoneinfo import ZoneInfo

from homeassistant.components.recorder import get_instance
from homeassistant.components.recorder.models import (
    StatisticMeanType,
    StatisticMetaData,
)
from homeassistant.components.recorder.statistics import (
    async_add_external_statistics,
    statistics_during_period,
)
from homeassistant.helpers.storage import Store

from .const import DOMAIN
from .statistics_reconciliation import (
    complete_hours,
    merge_measurements,
    rebuild_statistics,
    utc_datetime,
    window_bounds,
)

if TYPE_CHECKING:
    from homeassistant.config_entries import ConfigEntry
    from homeassistant.core import HomeAssistant

    from .coordinator import OctopusDataCoordinator

_LOGGER = logging.getLogger(__name__)
RECONCILIATION_VERSION = 1
LOOKBACK_DAYS = 30
RECENT_DAYS = 7
FULL_SCAN_HOUR = 6
STATISTICS_TOLERANCE = 0.0000005


class StatisticsReconciler:
    """One serialized importer and managed interval cache per config entry."""

    def __init__(
        self,
        hass: HomeAssistant,
        api: Any,
        coordinator: OctopusDataCoordinator,
        account_numbers: list[str],
        entry_id: str,
    ) -> None:
        """Initialize the importer for one config entry."""
        self.hass = hass
        self.api = api
        self.coordinator = coordinator
        self.account_numbers = account_numbers
        self.store = Store(hass, 1, f"{DOMAIN}.statistics_reconciliation.{entry_id}")
        self.data: dict[str, Any] = {"accounts": {}}
        self.lock = asyncio.Lock()
        self.task: asyncio.Task | None = None
        self.stopped = False
        self.status: dict[str, Any] = {"phase": "idle"}

    async def async_load(self) -> None:
        """Restore intervals and successful full-scan date across restarts."""
        self.data = await self.store.async_load() or {"accounts": {}}

    def schedule(self) -> None:
        """Coalesce notifications rather than queue overlapping scans."""
        if not self.stopped and (self.task is None or self.task.done()):
            self.task = self.hass.async_create_background_task(
                self.async_run(), f"{DOMAIN} statistics reconciliation"
            )

    def stop(self) -> None:
        """Cancel the task when unloading; an interrupted run is never checkpointed."""
        self.stopped = True
        if self.task is not None:
            self.task.cancel()

    async def async_run(self, now: datetime | None = None) -> None:
        """Fetch -> validate -> recorder upsert -> read back -> checkpoint."""
        if self.stopped or self.lock.locked():
            return
        async with self.lock:
            for account_num in self.account_numbers:
                if self.stopped:
                    return
                try:
                    await self._async_reconcile(account_num, now or datetime.now(UTC))
                except asyncio.CancelledError:
                    raise
                except Exception:
                    self.status["phase"] = "failed"
                    # API, validation, storage and recorder failures never mark a
                    # scan successful; the next coordinator update retries.
                    _LOGGER.exception(
                        "Octopus statistics reconciliation failed for %s", account_num
                    )

    async def _async_reconcile(self, account_num: str, now: datetime) -> None:
        account = (self.coordinator.data or {}).get(account_num, {})
        properties = account.get("property_ids", [])
        malo = account.get("malo_number")
        if not properties or not malo:
            return
        self.status = {"phase": "fetching", "started_at": now.isoformat()}
        zone = self.hass.config.time_zone
        local_now = now.astimezone(ZoneInfo(zone))
        old = self.data["accounts"].get(account_num, {})
        full = not old.get("last_full_scan") or (
            local_now.hour >= FULL_SCAN_HOUR
            and old["last_full_scan"] != local_now.date().isoformat()
        )
        cutoff, end = window_bounds(now, zone, LOOKBACK_DAYS)
        start, _ = window_bounds(now, zone, LOOKBACK_DAYS if full else RECENT_DAYS)
        self.status.update(start=start.isoformat(), end=end.isoformat())
        async with asyncio.timeout(600):
            readings = await self.api.fetch_electricity_measurements_range(
                properties[0], malo, start.isoformat(), end.isoformat(), zone, "15min"
            )
        if not readings:
            self.status["phase"] = "empty_response"
            _LOGGER.warning(
                "Octopus %s: no intervals returned; statistics retained", account_num
            )
            return
        intervals, counts, conflicts = merge_measurements(
            old.get("intervals", {}), readings, start, end, cutoff, now, str(malo)
        )
        if not (
            counts["added"]
            + counts["corrected"]
            + counts["metadata_changed"]
            + counts["identical"]
        ):
            self.status["phase"] = "invalid_response"
            _LOGGER.warning(
                "Octopus %s: no valid unambiguous intervals; retry required (%s)",
                account_num,
                counts,
            )
            return
        hours = complete_hours(intervals, conflicts)
        incomplete = len(
            {utc_datetime(key).replace(minute=0) for key in intervals}
        ) - len(hours)
        if conflicts:
            _LOGGER.warning(
                "Octopus %s: conflicting intervals retained, not adopted: %s",
                account_num,
                sorted(conflicts)[:12],
            )
        safe_account = account_num.replace("-", "_").lower()
        statistic_id = f"{DOMAIN}:electricity_{safe_account}_consumption"
        recorder = get_instance(self.hass)
        self.status.update(phase="reading_statistics", received_intervals=len(readings))
        # Read the true preceding sum, never assume a seven-day baseline.
        history = await recorder.async_add_executor_job(
            statistics_during_period,
            self.hass,
            datetime(1970, 1, 1, tzinfo=UTC),
            None,
            {statistic_id},
            "hour",
            None,
            {"state", "sum"},
        )
        changes, unverified = rebuild_statistics(
            history.get(statistic_id, []), hours, cutoff, now
        )
        if changes:
            self.status.update(phase="writing_statistics", changed_hours=len(changes))
            meter = (account.get("meter") or {}).get("number", account_num)
            async_add_external_statistics(
                self.hass,
                StatisticMetaData(
                    has_mean=False,
                    mean_type=StatisticMeanType.NONE,
                    has_sum=True,
                    name=f"Electricity Consumption ({meter}/{account_num})",
                    source=DOMAIN,
                    statistic_id=statistic_id,
                    unit_of_measurement="kWh",
                    unit_class="energy",
                ),
                changes,
            )
            await recorder.async_block_till_done()
            written = await recorder.async_add_executor_job(
                statistics_during_period,
                self.hass,
                changes[0]["start"],
                None,
                {statistic_id},
                "hour",
                None,
                {"state", "sum"},
            )
            verified = {
                utc_datetime(row["start"]): row for row in written.get(statistic_id, [])
            }
            if any(
                row["start"] not in verified
                or any(
                    abs(float(verified[row["start"]][key]) - row[key])
                    > STATISTICS_TOLERANCE
                    for key in ("state", "sum")
                )
                for row in changes
            ):
                self.stopped = True
                message = "Recorder read-back differs; reconciliation halted"
                raise RuntimeError(message)
        candidate = deepcopy(self.data)
        candidate["accounts"][account_num] = {
            "intervals": intervals,
            "last_success": now.isoformat(),
            "last_full_scan": (
                local_now.date() - timedelta(days=local_now.hour < FULL_SCAN_HOUR)
            ).isoformat()
            if full
            else old.get("last_full_scan"),
            "diagnostics": {
                **counts,
                "written_hours": len(changes),
                "complete_hours": len(hours),
                "incomplete_hours": incomplete,
                "unverified_hours": unverified,
                "start": start.isoformat(),
                "end": end.isoformat(),
            },
        }
        self.status["phase"] = "saving_checkpoint"
        await self.store.async_save(candidate)
        self.data = candidate
        self.status["phase"] = "complete"
        log = (
            _LOGGER.warning
            if (
                counts["invalid"]
                or counts["conflicts"]
                or counts["missing"]
                or unverified
            )
            else _LOGGER.info
        )
        log(
            "Octopus %s %s-day reconciliation: %s; complete_hours=%s, "
            "unverified_legacy_hours=%s, written_hours=%s",
            account_num,
            LOOKBACK_DAYS if full else RECENT_DAYS,
            counts,
            len(hours),
            unverified,
            len(changes),
        )


async def async_setup_statistics_import(
    hass: HomeAssistant,
    api: Any,
    coordinator: OctopusDataCoordinator,
    account_numbers: list[str],
    entry: ConfigEntry,
) -> StatisticsReconciler:
    """Start in the background; pagination must not delay integration setup."""
    reconciler = StatisticsReconciler(
        hass, api, coordinator, account_numbers, entry.entry_id
    )
    await reconciler.async_load()
    entry.async_on_unload(coordinator.async_add_listener(reconciler.schedule))
    entry.async_on_unload(reconciler.stop)
    if coordinator.data:
        reconciler.schedule()
    return reconciler
