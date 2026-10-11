"""Load user-maintained, hourly grid-fee schedules."""

from __future__ import annotations

import json
from datetime import date, datetime, time
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

_RATE_TYPE_MAP = {
    "NT": "OFFPEAK",
    "ST": "STANDARD",
    "HT": "PEAK",
    "OFFPEAK": "OFFPEAK",
    "STANDARD": "STANDARD",
    "PEAK": "PEAK",
}
_RATE_TYPES = frozenset({"OFFPEAK", "STANDARD", "PEAK"})
_HOURS_PER_DAY = 24


def load_grid_fee_schedule(
    path: str | Path,
    grid_operator_code: str | None,
    year: int,
    timezone: str,
) -> dict[str, Any] | None:
    """Load a matching network-operator/year entry, keeping each hour distinct."""
    if not grid_operator_code:
        return None

    with Path(path).open(encoding="utf-8") as schedule_file:
        document = json.load(schedule_file)
    if not isinstance(document, dict) or document.get("format_version") != 1:
        raise ValueError("format_version must be 1")
    operators = document.get("grid_operators")
    if not isinstance(operators, list):
        raise ValueError("grid_operators must be an array")

    matching_operators = [
        operator
        for operator in operators
        if isinstance(operator, dict)
        and str(operator.get("grid_operator_code", "")).strip()
        == str(grid_operator_code).strip()
    ]
    if not matching_operators:
        return None
    if len(matching_operators) != 1:
        raise ValueError("grid_operator_code must be unique")

    years = matching_operators[0].get("years")
    if not isinstance(years, list):
        raise ValueError("years must be an array")
    matching_years = [
        item for item in years if isinstance(item, dict) and item.get("year") == year
    ]
    if not matching_years:
        return None
    if len(matching_years) != 1:
        raise ValueError("year must be unique for each grid operator")

    entry = matching_years[0]
    module1_credit = _optional_non_negative_decimal(
        entry.get("module1_credit_net_eur"), "module1_credit_net_eur"
    )
    local_timezone = ZoneInfo(timezone)
    rates = []
    schedule_periods = entry.get("schedules")
    if schedule_periods is None:
        schedule_periods = [entry]
    if not isinstance(schedule_periods, list) or not schedule_periods:
        raise ValueError("schedules must be a non-empty array")
    parsed_periods = []
    for schedule_index, schedule_period in enumerate(schedule_periods):
        if not isinstance(schedule_period, dict):
            raise ValueError(f"schedules[{schedule_index}] must be an object")
        parsed_period = _parse_schedule_period(
            schedule_period,
            entry,
            year,
            local_timezone,
            schedule_index,
        )
        parsed_periods.append(parsed_period)
        rates.extend(parsed_period["rates"])

    ordered_periods = sorted(
        parsed_periods,
        key=lambda period: period["valid_from"] or date(year, 1, 1),
    )
    for previous, current in zip(ordered_periods, ordered_periods[1:]):
        if previous["valid_to"] is None or current["valid_from"] is None:
            raise ValueError("multiple schedules require valid_from and valid_to")
        if previous["valid_to"] > current["valid_from"]:
            raise ValueError("schedule validity periods cannot overlap")
    return {
        "grid_operator_code": str(grid_operator_code),
        "grid_operator_name": matching_operators[0].get("grid_operator_name"),
        "year": year,
        "status": entry.get("status"),
        "source_note": entry.get("source_note"),
        "module1_credit_net_eur": module1_credit,
        "schedules": [
            {key: value for key, value in period.items() if key != "rates"}
            for period in parsed_periods
        ],
        "rates": rates,
    }


def _parse_schedule_period(
    schedule: dict[str, Any],
    year_entry: dict[str, Any],
    year: int,
    timezone: ZoneInfo,
    index: int,
) -> dict[str, Any]:
    prefix = f"schedules[{index}]"
    hourly_rate_types = schedule.get(
        "hourly_rate_types", year_entry.get("hourly_rate_types")
    )
    rates_by_type = schedule.get(
        "rates_net_ct_per_kwh", year_entry.get("rates_net_ct_per_kwh")
    )
    if (
        not isinstance(hourly_rate_types, list)
        or len(hourly_rate_types) != _HOURS_PER_DAY
    ):
        raise ValueError(f"{prefix}.hourly_rate_types must contain exactly 24 entries")
    if not isinstance(rates_by_type, dict):
        raise ValueError(f"{prefix}.rates_net_ct_per_kwh must be an object")

    converted_rates: dict[str, Decimal] = {}
    for rate_name, rate_value in rates_by_type.items():
        normalized_type = _RATE_TYPE_MAP.get(str(rate_name).upper())
        if normalized_type not in _RATE_TYPES:
            raise ValueError(f"unsupported grid-fee type: {rate_name}")
        parsed_rate = _optional_non_negative_decimal(
            rate_value, f"{prefix}.rates_net_ct_per_kwh.{rate_name}"
        )
        if parsed_rate is None:
            raise ValueError(f"rate for {rate_name} must be a number")
        converted_rates[normalized_type] = parsed_rate

    valid_from = _schedule_date(schedule.get("valid_from"), f"{prefix}.valid_from")
    valid_to = _schedule_date(schedule.get("valid_to"), f"{prefix}.valid_to")
    if any(hourly_rate_types):
        if valid_from is None or valid_to is None or valid_to <= valid_from:
            raise ValueError(
                f"{prefix} hourly rates require valid_from and exclusive valid_to"
            )
        report_year_start = date(year, 1, 1)
        report_year_end = date(year + 1, 1, 1)
        if valid_to <= report_year_start or valid_from >= report_year_end:
            raise ValueError(f"{prefix} validity does not overlap calendar year {year}")

    rates = []
    for hour, rate_name in enumerate(hourly_rate_types):
        if rate_name in (None, "", "-", "—"):
            continue
        normalized_type = _RATE_TYPE_MAP.get(str(rate_name).upper())
        if normalized_type not in _RATE_TYPES:
            raise ValueError(
                f"{prefix}.hourly_rate_types[{hour}] has an unsupported type"
            )
        rate_cents = converted_rates.get(normalized_type)
        if rate_cents is None:
            raise ValueError(f"missing rate for hourly type {rate_name}")
        end_hour = (hour + 1) % _HOURS_PER_DAY
        rates.append(
            {
                "rate_type": normalized_type,
                "start_time": f"{hour:02d}:00:00",
                "end_time": f"{end_hour:02d}:00:00",
                "valid_from": _local_midnight(valid_from, timezone),
                "valid_to": _local_midnight(valid_to, timezone),
                "rate_cents_per_kwh": str(rate_cents),
                "rate_eur_per_kwh": rate_cents / Decimal(100),
                "module": "MODULE_3",
            }
        )
    return {
        "valid_from": valid_from.isoformat() if valid_from else None,
        "valid_to": valid_to.isoformat() if valid_to else None,
        "status": schedule.get("status", year_entry.get("status")),
        "basis_rate_net_ct_per_kwh": _optional_non_negative_decimal(
            schedule.get(
                "basis_rate_net_ct_per_kwh",
                year_entry.get("basis_rate_net_ct_per_kwh"),
            ),
            f"{prefix}.basis_rate_net_ct_per_kwh",
        ),
        "rates_net_ct_per_kwh": converted_rates,
        "hourly_rate_types": hourly_rate_types,
        "rates": rates,
    }


def _optional_non_negative_decimal(value: Any, field: str) -> Decimal | None:
    if value is None:
        return None
    try:
        parsed = Decimal(str(value))
    except (InvalidOperation, TypeError, ValueError) as err:
        raise ValueError(f"{field} must be numeric") from err
    if not parsed.is_finite() or parsed < 0:
        raise ValueError(f"{field} must be a finite, non-negative number")
    return parsed


def _schedule_date(value: Any, field: str) -> date | None:
    if value is None:
        return None
    try:
        return date.fromisoformat(str(value))
    except ValueError as err:
        raise ValueError(f"{field} must use YYYY-MM-DD format") from err


def _local_midnight(value: date | None, timezone: ZoneInfo) -> str | None:
    if value is None:
        return None
    return datetime.combine(value, time.min, tzinfo=timezone).isoformat()
