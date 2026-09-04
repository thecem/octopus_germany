"""Tariff and electricity price calculation helpers."""

from __future__ import annotations

from datetime import UTC, datetime, time
from typing import Any


def parse_tariff_time(value: str) -> time | None:
    """Parse an HH:MM:SS tariff time."""
    try:
        hour, minute, second = map(int, value.split(":"))
        return time(hour=hour, minute=minute, second=second)
    except ValueError, AttributeError:
        return None


def is_time_between(current: time, start: time, end: time) -> bool:
    """Return whether current is inside a tariff time range."""
    if end == time.min:
        return start == time.min or current >= start
    if start <= end:
        return start <= current < end
    return current >= start or current < end


def get_active_timeslot_rate(
    product: dict[str, Any], current_time: time | None = None
) -> float | None:
    """Return the active Time-of-Use rate in EUR per kWh."""
    if not product:
        return None
    if product.get("type") == "Simple":
        try:
            return float(product.get("grossRate", "0")) / 100
        except ValueError, TypeError:
            return None
    if product.get("type") != "TimeOfUse":
        return None

    current_time = current_time or datetime.now(UTC).time()
    for timeslot in product.get("timeslots", []):
        for rule in timeslot.get("activation_rules", []):
            start = parse_tariff_time(rule.get("from_time", "00:00:00"))
            end = parse_tariff_time(rule.get("to_time", "00:00:00"))
            if start and end and is_time_between(current_time, start, end):
                try:
                    return float(timeslot.get("rate", "0")) / 100
                except ValueError, TypeError:
                    continue
    return None


def get_current_forecast_rate(
    product: dict[str, Any], current_time: datetime | None = None
) -> float | None:
    """Return the current forecast rate in EUR per kWh."""
    if not product:
        return None
    current_time = current_time or datetime.now(UTC)
    for forecast in product.get("unitRateForecast", []):
        valid_from = forecast.get("validFrom")
        valid_to = forecast.get("validTo")
        if not valid_from or not valid_to:
            continue
        try:
            start = datetime.fromisoformat(valid_from)
            end = datetime.fromisoformat(valid_to)
            if not start <= current_time < end:
                continue
            rate_info = forecast.get("unitRateInformation", {})
            rates = rate_info.get("rates", [])
            rate = (
                rates[0].get("latestGrossUnitRateCentsPerKwh")
                if rates
                else rate_info.get("latestGrossUnitRateCentsPerKwh")
            )
            return float(rate) / 100 if rate is not None else None
        except ValueError, TypeError:
            continue
    return None


def format_uk_rates(product: dict[str, Any]) -> list[dict[str, Any]]:
    """Format German forecast data for octopus-energy-rates-card compatibility."""
    rates = []
    for forecast in product.get("unitRateForecast", []):
        valid_from = forecast.get("validFrom")
        valid_to = forecast.get("validTo")
        if not valid_from or not valid_to:
            continue

        rate_info = forecast.get("unitRateInformation", {})
        rate_values = rate_info.get("rates", [])
        rate_cents = (
            rate_values[0].get("latestGrossUnitRateCentsPerKwh")
            if rate_values
            else rate_info.get("latestGrossUnitRateCentsPerKwh")
        )
        if rate_cents is None:
            continue
        try:
            rates.append(
                {
                    "start": valid_from,
                    "end": valid_to,
                    "value_inc_vat": round(float(rate_cents) / 100, 4),
                }
            )
        except ValueError, TypeError:
            continue
    return sorted(rates, key=lambda rate: rate["start"])
