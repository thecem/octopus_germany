"""Statistics import helpers for Octopus Germany integration."""

from __future__ import annotations

import logging
from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING, Any

from homeassistant.util.dt import as_utc

from .const import DOMAIN

if TYPE_CHECKING:
    from homeassistant.core import HomeAssistant

    from .coordinator import OctopusDataCoordinator

try:
    from homeassistant.components.recorder import get_instance
    from homeassistant.components.recorder.models import (
        StatisticData,
        StatisticMeanType,
        StatisticMetaData,
    )
    from homeassistant.components.recorder.statistics import (
        async_add_external_statistics,
        statistics_during_period,
    )

    HAS_RECORDER = True
except ImportError:
    HAS_RECORDER = False

_LOGGER = logging.getLogger(__name__)


_BACKFILL_START_DAY_OFFSET = 2
_BACKFILL_END_DAY_OFFSET = 8
_HISTORICAL_LOOKBACK_DAYS = 7


def _determine_dates_to_import(
    account_num: str,
    imported_stats_dates: dict[str, set[str]],
) -> list[str]:
    """Determine daily date strings that should be imported for one account."""
    yesterday = (datetime.now(UTC).date() - timedelta(days=1)).isoformat()
    imported_dates = imported_stats_dates.setdefault(account_num, set())

    dates_to_import: list[str] = []
    if yesterday not in imported_dates:
        dates_to_import.append(yesterday)

    # On first run, backfill a small history window.
    if not imported_dates:
        for days_back in range(_BACKFILL_START_DAY_OFFSET, _BACKFILL_END_DAY_OFFSET):
            backfill_date = (
                datetime.now(UTC).date() - timedelta(days=days_back)
            ).isoformat()
            dates_to_import.append(backfill_date)

    return dates_to_import


async def _get_last_running_sum(
    hass: HomeAssistant,
    statistic_id: str,
    dates_to_import: list[str],
) -> float:
    """Get the last recorder sum prior to the import window."""
    if not dates_to_import:
        return 0.0

    earliest_date = datetime.fromisoformat(min(dates_to_import))
    try:
        last_stat = await get_instance(hass).async_add_executor_job(
            statistics_during_period,
            hass,
            earliest_date - timedelta(days=_HISTORICAL_LOOKBACK_DAYS),
            earliest_date,
            {statistic_id},
            "hour",
            None,
            {"sum"},
        )
        history = last_stat.get(statistic_id) or []
        return float(history[-1].get("sum", 0.0)) if history else 0.0
    except (TypeError, ValueError, KeyError) as err:
        _LOGGER.debug("Could not get last statistics sum: %s", err)
        return 0.0


def _build_hourly_buckets(readings: list[dict[str, Any]]) -> dict[str, float]:
    """Aggregate quarter-hour readings into hourly buckets."""
    hourly_buckets: dict[str, float] = {}
    for reading in readings:
        start_str = reading.get("start_time", "")
        if not start_str:
            continue
        try:
            start_dt = datetime.fromisoformat(start_str)
            hour_key = start_dt.replace(minute=0, second=0, microsecond=0).isoformat()
            value = float(reading.get("value", 0) or 0)
        except TypeError, ValueError:
            continue
        hourly_buckets[hour_key] = hourly_buckets.get(hour_key, 0.0) + value
    return hourly_buckets


def _build_statistic_entries(
    hourly_buckets: dict[str, float],
    running_sum: float,
) -> tuple[list[StatisticData], float]:
    """Build recorder StatisticData entries and return updated running sum."""
    entries: list[StatisticData] = []
    for hour_key in sorted(hourly_buckets):
        consumption = hourly_buckets[hour_key]
        running_sum += consumption
        hour_dt = as_utc(datetime.fromisoformat(hour_key))
        entries.append(
            StatisticData(
                start=hour_dt,
                state=round(consumption, 6),
                sum=round(running_sum, 6),
            )
        )
    return entries, running_sum


async def async_import_consumption_statistics(
    hass: HomeAssistant,
    api: Any,
    coordinator: OctopusDataCoordinator,
    account_numbers: list[str],
    imported_stats_dates: dict[str, set[str]],
) -> None:
    """Import smart-meter data into HA long-term statistics."""
    if not HAS_RECORDER:
        return

    for account_num in account_numbers:
        if not coordinator.data or account_num not in coordinator.data:
            continue

        account_data = coordinator.data[account_num]
        property_ids = account_data.get("property_ids", [])
        if not property_ids:
            continue

        property_id = property_ids[0]
        safe_account = account_num.replace("-", "_").lower()
        statistic_id = f"{DOMAIN}:electricity_{safe_account}_consumption"

        dates_to_import = _determine_dates_to_import(account_num, imported_stats_dates)

        if not dates_to_import:
            continue

        running_sum = await _get_last_running_sum(hass, statistic_id, dates_to_import)

        all_statistics = []

        for date_str in sorted(dates_to_import):
            if date_str in imported_stats_dates[account_num]:
                continue

            try:
                readings = await api.fetch_electricity_15min_readings(
                    account_num, property_id, date_str
                )
            except (RuntimeError, ValueError, TypeError) as err:
                _LOGGER.warning(
                    "Failed to fetch 15-min readings for %s: %s", date_str, err
                )
                continue

            if not readings:
                continue

            hourly_buckets = _build_hourly_buckets(readings)
            entries, running_sum = _build_statistic_entries(hourly_buckets, running_sum)
            all_statistics.extend(entries)

            imported_stats_dates[account_num].add(date_str)
            _LOGGER.debug(
                "Prepared %d hourly statistics for %s on %s (running sum: %.3f)",
                len(hourly_buckets),
                account_num,
                date_str,
                running_sum,
            )

        if all_statistics:
            meter_info = account_data.get("meter", {})
            meter_number = (
                meter_info.get("number", account_num) if meter_info else account_num
            )

            async_add_external_statistics(
                hass,
                StatisticMetaData(
                    has_mean=False,
                    mean_type=StatisticMeanType.NONE,
                    has_sum=True,
                    name=f"Electricity Consumption ({meter_number}/{account_num})",
                    source=DOMAIN,
                    statistic_id=statistic_id,
                    unit_of_measurement="kWh",
                    unit_class="energy",
                ),
                all_statistics,
            )
            _LOGGER.info(
                "Imported %d hourly statistics for account %s into energy dashboard",
                len(all_statistics),
                account_num,
            )


async def _safe_import_statistics(
    hass: HomeAssistant,
    api: Any,
    coordinator: OctopusDataCoordinator,
    account_numbers: list[str],
    imported_stats_dates: dict[str, set[str]],
) -> None:
    """Run statistics import with guarded error handling."""
    try:
        await async_import_consumption_statistics(
            hass,
            api,
            coordinator,
            account_numbers,
            imported_stats_dates,
        )
    except (RuntimeError, ValueError, TypeError, KeyError) as err:
        _LOGGER.warning("Error importing consumption statistics: %s", err)


async def async_setup_statistics_import(
    hass: HomeAssistant,
    api: Any,
    coordinator: OctopusDataCoordinator,
    account_numbers: list[str],
) -> None:
    """Set up coordinator listener and initial statistics import."""
    imported_stats_dates: dict[str, set[str]] = {acc: set() for acc in account_numbers}

    def _on_coordinator_update() -> None:
        """Schedule statistics import when coordinator data updates."""
        hass.async_create_task(
            _safe_import_statistics(
                hass,
                api,
                coordinator,
                account_numbers,
                imported_stats_dates,
            )
        )

    coordinator.async_add_listener(_on_coordinator_update)

    if HAS_RECORDER and coordinator.data:
        try:
            await async_import_consumption_statistics(
                hass,
                api,
                coordinator,
                account_numbers,
                imported_stats_dates,
            )
        except (RuntimeError, ValueError, TypeError, KeyError) as err:
            _LOGGER.warning("Error during initial statistics import: %s", err)
