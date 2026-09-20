"""Tariff and electricity price calculation helpers."""

from __future__ import annotations

from datetime import UTC, datetime, time, timedelta
from decimal import Decimal, InvalidOperation
from typing import Any

from homeassistant.util.dt import now as local_now


def parse_product_datetime(value: str | None) -> datetime | None:
    """Parse an API product timestamp into an aware UTC datetime."""
    if not value:
        return None
    try:
        parsed = datetime.fromisoformat(value)
    except TypeError, ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=UTC)
    return parsed.astimezone(UTC)


def is_product_current(
    product: dict[str, Any], current_time: datetime | None = None
) -> bool:
    """Return whether a product is valid at the supplied instant."""
    valid_from = parse_product_datetime(product.get("validFrom"))
    valid_to = parse_product_datetime(product.get("validTo"))
    if valid_from is None:
        return False
    current_time = current_time or datetime.now(UTC)
    if current_time.tzinfo is None:
        current_time = current_time.replace(tzinfo=UTC)
    current_time = current_time.astimezone(UTC)
    return valid_from <= current_time and (valid_to is None or current_time <= valid_to)


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

    current_time = current_time or local_now().time()
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


def get_next_price_change(
    product: dict[str, Any], current_time: datetime | None = None
) -> datetime | None:
    """Return the next local boundary that can change a product price."""
    if not product:
        return None
    current_time = current_time or local_now()
    if current_time.tzinfo is None:
        current_time = current_time.replace(tzinfo=UTC)

    candidates: list[datetime] = []
    local_time = current_time.timetz().replace(tzinfo=None)
    for timeslot in product.get("timeslots", []):
        for rule in timeslot.get("activation_rules", []):
            for boundary in (rule.get("from_time"), rule.get("to_time")):
                boundary_time = parse_tariff_time(boundary)
                if boundary_time is None:
                    continue
                boundary_date = current_time.date()
                if boundary_time <= local_time:
                    boundary_date += timedelta(days=1)
                candidates.append(
                    datetime.combine(
                        boundary_date, boundary_time, tzinfo=current_time.tzinfo
                    )
                )

    for forecast in product.get("unitRateForecast", []):
        for field in ("validFrom", "validTo"):
            boundary = parse_product_datetime(forecast.get(field))
            if boundary and boundary > current_time.astimezone(UTC):
                candidates.append(boundary.astimezone(current_time.tzinfo))

    return min(candidates) if candidates else None


def normalize_variable_grid_fees(
    value: dict[str, Any] | None,
    grid_operator_name: str | None = None,
) -> dict[str, Any] | None:
    """Normalize OE backend variable grid fee data."""
    if not value:
        return None

    rates = []
    for rate in value.get("gridFees") or []:
        try:
            cents = Decimal(str(rate["gridFeeInCentsPerKwh"]))
        except InvalidOperation, KeyError, TypeError:
            continue
        rates.append(
            {
                "rate_type": rate.get("gridFeeKwhRateType"),
                "start_time": rate.get("rateTypeIntervalStart"),
                "end_time": rate.get("rateTypeIntervalEnd"),
                "valid_from": rate.get("validFrom"),
                "valid_to": rate.get("validTo"),
                "grid_operator_code": rate.get("gridOperatorCode"),
                "rate_cents_per_kwh": str(cents),
                "rate_eur_per_kwh": float(cents / Decimal(100)),
            }
        )

    if not value.get("module") and not rates:
        return None
    return {
        "module": value.get("module"),
        "grid_operator_code": next(
            (
                rate.get("grid_operator_code")
                for rate in rates
                if rate.get("grid_operator_code")
            ),
            None,
        ),
        "grid_operator_name": grid_operator_name,
        "rates": rates,
    }


def get_active_grid_fee(
    grid_fee_data: dict[str, Any] | None,
    current_time: datetime | None = None,
) -> dict[str, Any] | None:
    """Return the variable grid fee active at the supplied local time."""
    if not grid_fee_data:
        return None
    current_time = current_time or local_now()
    if current_time.tzinfo is None:
        current_time = current_time.replace(tzinfo=UTC)
    current_utc = current_time.astimezone(UTC)
    wall_time = current_time.time().replace(tzinfo=None)

    for rate in grid_fee_data.get("rates", []):
        valid_from = parse_product_datetime(rate.get("valid_from"))
        valid_to = parse_product_datetime(rate.get("valid_to"))
        if valid_from and current_utc < valid_from:
            continue
        if valid_to and current_utc >= valid_to:
            continue
        start = parse_tariff_time(rate.get("start_time"))
        end = parse_tariff_time(rate.get("end_time"))
        if start and end and is_time_between(wall_time, start, end):
            return rate
    return None


def get_next_grid_fee_change(
    grid_fee_data: dict[str, Any] | None,
    current_time: datetime | None = None,
) -> datetime | None:
    """Return the next local boundary for the active variable grid fee."""
    current_time = current_time or local_now()
    if current_time.tzinfo is None:
        current_time = current_time.replace(tzinfo=UTC)
    active_rate = get_active_grid_fee(grid_fee_data, current_time)
    if not active_rate:
        return None
    end_time = parse_tariff_time(active_rate.get("end_time"))
    if end_time is None:
        return None
    change_date = current_time.date()
    if end_time <= current_time.time().replace(tzinfo=None):
        change_date += timedelta(days=1)
    return datetime.combine(change_date, end_time, tzinfo=current_time.tzinfo)


def get_current_forecast_rate(
    product: dict[str, Any], current_time: datetime | None = None
) -> float | None:
    """Return the current forecast rate in EUR per kWh."""
    if not product:
        return None
    current_time = current_time or local_now()
    if current_time.tzinfo is None:
        current_time = current_time.replace(tzinfo=UTC)
    current_time_utc = current_time.astimezone(UTC)

    for forecast in product.get("unitRateForecast", []):
        valid_from = forecast.get("validFrom")
        valid_to = forecast.get("validTo")
        if not valid_from or not valid_to:
            continue
        try:
            start = datetime.fromisoformat(valid_from)
            end = datetime.fromisoformat(valid_to)
            if start.tzinfo is None:
                start = start.replace(tzinfo=UTC)
            if end.tzinfo is None:
                end = end.replace(tzinfo=UTC)
            if not start.astimezone(UTC) <= current_time_utc < end.astimezone(UTC):
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
