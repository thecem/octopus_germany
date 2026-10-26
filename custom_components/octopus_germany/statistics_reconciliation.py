"""Pure UTC/decimal validation and reconciliation of quarter-hour consumption."""

# Validation errors are intentionally local to each rejected API interval.
# ruff: noqa: EM101, TRY003, TRY301

from __future__ import annotations

from copy import deepcopy
from datetime import UTC, datetime, time, timedelta
from decimal import Decimal, InvalidOperation
from typing import Any
from zoneinfo import ZoneInfo

QUARTER = timedelta(minutes=15)
MILLISECONDS_THRESHOLD = 100_000_000_000
METADATA = (
    "source",
    "reading_quality",
    "reading_direction",
    "reading_frequency",
    "measurement_type",
    "market_supply_point_id",
    "device_id",
    "register_id",
)


def utc_datetime(value: Any) -> datetime:
    """Accept aware instants and recorder timestamps, never guess a timezone."""
    if isinstance(value, (int, float)):
        return datetime.fromtimestamp(
            value / 1000 if value > MILLISECONDS_THRESHOLD else value, UTC
        )
    parsed = value if isinstance(value, datetime) else datetime.fromisoformat(value)
    if parsed.tzinfo is None:
        raise ValueError("Naive timestamp")
    return parsed.astimezone(UTC)


def decimal_energy(value: Any) -> Decimal:
    """Zero is valid; missing, negative and non-finite values are not."""
    if value is None or isinstance(value, bool):
        raise ValueError("Missing or boolean energy")
    result = Decimal(str(value))
    if not result.is_finite() or result < 0:
        raise ValueError("Invalid energy")
    return result


def window_bounds(now: datetime, timezone: str, days: int) -> tuple[datetime, datetime]:
    """Return closed local days as a UTC range, including 23/25-hour days."""
    zone = ZoneInfo(timezone)
    today = now.astimezone(zone).date()
    return (
        datetime.combine(today - timedelta(days=days), time.min, zone).astimezone(UTC),
        datetime.combine(today, time.min, zone).astimezone(UTC),
    )


def merge_measurements(  # noqa: PLR0912, PLR0913
    cached: dict,
    readings: list[dict],
    start: datetime,
    end: datetime,
    retained_start: datetime,
    fetched_at: datetime,
    malo: str,
) -> tuple[dict, dict[str, int], set[str]]:
    """Upsert valid quarters, retain omissions and quarantine conflicting duplicates."""
    merged = {
        key: deepcopy(row)
        for key, row in cached.items()
        if retained_start <= utc_datetime(key) < end
    }
    counts = {
        "added": 0,
        "corrected": 0,
        "metadata_changed": 0,
        "identical": 0,
        "invalid": 0,
        "conflicts": 0,
        "missing": 0,
    }
    incoming: dict[str, dict] = {}
    conflicts: set[str] = set()
    for reading in readings:
        try:
            at = utc_datetime(reading.get("start_time"))
            until = utc_datetime(reading.get("end_time"))
            if not start <= at < end:
                continue
            if at.minute % 15 or at.second or at.microsecond or until - at != QUARTER:
                raise ValueError("Not an aligned quarter-hour")
            if reading.get("duration_in_seconds") not in (None, 900, 900.0):
                raise ValueError("Invalid interval duration")
            if reading.get("market_supply_point_id") not in (None, "", malo):
                raise ValueError("Wrong market supply point")
            if str(reading.get("reading_direction") or "").upper() in {
                "EXPORT",
                "FEED_IN",
                "GENERATION",
                "INJECTION",
            }:
                raise ValueError("Not an import measurement")
            value = decimal_energy(reading.get("value"))
            unit = str(reading.get("unit") or "").lower()
            if unit == "wh":
                value /= 1000
            elif unit != "kwh":
                raise ValueError("Unsupported energy unit")
            key = at.isoformat()
            row = {
                "start_time": key,
                "end_time": until.isoformat(),
                "value_kwh": str(value),
                "value": reading["value"],
                "unit": unit,
                **{field: reading.get(field) for field in METADATA},
            }
            previous = incoming.get(key)
            if previous is not None and (
                decimal_energy(previous["value_kwh"]) != value
                or any(previous.get(field) != row.get(field) for field in METADATA)
            ):
                conflicts.add(key)
            incoming[key] = row
        except ValueError, TypeError, InvalidOperation, OverflowError:
            counts["invalid"] += 1
    counts["conflicts"] = len(conflicts)
    for key, row in incoming.items():
        if key in conflicts:
            continue
        old = merged.get(key)
        if old is None:
            counts["added"] += 1
        elif decimal_energy(old["value_kwh"]) != decimal_energy(row["value_kwh"]):
            counts["corrected"] += 1
        elif any(old.get(field) != row.get(field) for field in METADATA):
            counts["metadata_changed"] += 1
        else:
            counts["identical"] += 1
        merged[key] = {**row, "fetched_at": fetched_at.isoformat()}
    counts["missing"] = int((end - start) / QUARTER) - len(incoming.keys() - conflicts)
    return merged, counts, conflicts


def complete_hours(intervals: dict, conflicts: set[str]) -> dict[datetime, Decimal]:
    """Four distinct UTC quarters, not a mere count, define a complete hour."""
    hours = {utc_datetime(key).replace(minute=0) for key in intervals}
    result = {}
    for hour in hours:
        keys = [(hour + offset * QUARTER).isoformat() for offset in range(4)]
        if any(key not in intervals or key in conflicts for key in keys):
            continue
        result[hour] = sum(
            (decimal_energy(intervals[key]["value_kwh"]) for key in keys), Decimal(0)
        )
    return result


def rebuild_statistics(
    existing: list[dict],
    hourly: dict[datetime, Decimal],
    cutoff: datetime,
    now: datetime,
) -> tuple[list[dict], int]:
    """
    Rebase from the preceding sum; retain unverified legacy hour consumption.

    This external statistic has interval consumption in ``state``. No row before
    cutoff is written, and all subsequent existing sums are corrected together.
    """
    replacements = {at: value for at, value in hourly.items() if cutoff <= at < now}
    if not replacements:
        return [], 0
    rows = {
        utc_datetime(row["start"]): row
        for row in existing
        if utc_datetime(row["start"]) < now
    }
    preceding = [at for at in rows if at < cutoff]
    if preceding:
        running = decimal_energy(rows[max(preceding)]["sum"])
    elif rows:
        first_at = min(rows)
        first = rows[first_at]
        running = decimal_energy(first["sum"]) - decimal_energy(first["state"])
        if running < 0:
            raise ValueError("Invalid legacy baseline")
        if min(replacements) < first_at and running:
            raise ValueError("Cannot safely insert before an unknown legacy baseline")
    else:
        running = Decimal(0)
    changes, unverified = [], 0
    for at in sorted({at for at in rows if at >= cutoff} | replacements.keys()):
        old = rows.get(at)
        if at in replacements:
            value = replacements[at]
        else:
            value = decimal_energy(old["state"])
            unverified += 1
        running += value
        state, total = round(value, 6), round(running, 6)
        if old is None or (
            decimal_energy(old["state"]) != state or decimal_energy(old["sum"]) != total
        ):
            changes.append({"start": at, "state": float(state), "sum": float(total)})
    return changes, unverified
