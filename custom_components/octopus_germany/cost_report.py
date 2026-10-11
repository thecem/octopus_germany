"""Cost-report calculations for the Octopus CSV export service."""

from __future__ import annotations

import re
from datetime import UTC, date, datetime, time, timedelta
from decimal import ROUND_HALF_UP, Decimal, InvalidOperation
from typing import Any
from zoneinfo import ZoneInfo

from .tariff import (
    get_active_grid_fee,
    is_time_between,
    parse_product_datetime,
    parse_tariff_time,
)

_MONTHS_PER_YEAR = Decimal(12)
_DAYS_PER_STANDING_CHARGE_YEAR = Decimal(365)

COST_REPORT_HEADERS = [
    "date",
    "tariff_agreement",
    "grid_operator",
    "grid_operator_code",
    "network_module",
    "total_kwh",
    "network_adjustment_gross_eur",
    "energy_cost_after_adjustment_gross_eur",
    "standing_charge_gross_eur",
    "module1_credit_net_eur",
    "module1_credit_gross_eur",
    "total_before_module1_gross_eur",
    "total_after_module1_gross_eur",
    "monthly_total_gross_eur",
    "unpriced_kwh",
    "network_rate_missing_kwh",
    "status",
]


def cost_report_headers(rows: list[dict[str, Any]]) -> list[str]:
    """Return stable summary columns plus the tariff blocks present in the report."""
    dynamic = sorted(
        {key for row in rows for key in row if key not in COST_REPORT_HEADERS}
    )
    return [*COST_REPORT_HEADERS, *dynamic]


def format_cost_report_value(field: str, value: Any) -> Any:
    """Format Decimal values for CSV display without changing calculations."""
    if not isinstance(value, Decimal):
        return value
    if field.endswith("_eur_per_kwh"):
        quantum = Decimal("0.000001")
    elif field.endswith("_eur"):
        quantum = Decimal("0.01")
    elif field.endswith("_kwh"):
        quantum = Decimal("0.001")
    else:
        return format(value, "f")
    rounded = value.quantize(quantum, rounding=ROUND_HALF_UP)
    if rounded.is_zero():
        rounded = abs(rounded)
    return format(rounded, "f").replace(".", ",")


def build_monthly_cost_summaries(
    rows: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    """Aggregate daily rows into classic monthly billing summaries."""
    rows_by_month: dict[str, list[dict[str, Any]]] = {}
    for row in rows:
        month = str(row.get("date", ""))[:7]
        if len(month) == 7 and month[4] == "-":
            rows_by_month.setdefault(month, []).append(row)

    summaries = []
    for month, month_rows in sorted(rows_by_month.items()):
        summary: dict[str, Any] = {
            "date": f"MONTH_TOTAL {month}",
            "tariff_agreement": " | ".join(
                sorted(
                    {
                        name
                        for row in month_rows
                        for name in str(row.get("tariff_agreement") or "").split(" | ")
                        if name
                    }
                )
            ),
            "grid_operator": " | ".join(
                sorted(
                    {
                        str(row["grid_operator"])
                        for row in month_rows
                        if row.get("grid_operator")
                    }
                )
            ),
            "grid_operator_code": " | ".join(
                sorted(
                    {
                        str(row["grid_operator_code"])
                        for row in month_rows
                        if row.get("grid_operator_code")
                    }
                )
            ),
            "network_module": " | ".join(
                sorted(
                    {
                        str(row["network_module"])
                        for row in month_rows
                        if row.get("network_module")
                    }
                )
            ),
        }
        fields = {field for row in month_rows for field in row}
        for field in fields:
            if field.endswith(("_kwh", "_eur")) and not field.endswith("_per_kwh"):
                values = [row.get(field) for row in month_rows]
                if all(isinstance(value, Decimal) for value in values):
                    summary[field] = sum(values, Decimal(0))
        rate_prefix = "_contract_ap_gross_eur_per_kwh"
        for field in fields:
            if not field.startswith("tariff_") or not field.endswith(rate_prefix):
                continue
            prefix = field.removesuffix(rate_prefix)
            quantity = summary.get(f"{prefix}_kwh", Decimal(0))
            cost = summary.get(f"{prefix}_contract_cost_gross_eur", Decimal(0))
            summary[field] = cost / quantity if quantity else None

        incomplete_days = sum(row.get("status") != "complete" for row in month_rows)
        summary["status"] = (
            "complete"
            if not incomplete_days
            else f"incomplete: {incomplete_days} of {len(month_rows)} day(s)"
        )
        month_is_complete = incomplete_days == 0
        monthly_total = (
            summary.get("total_after_module1_gross_eur") if month_is_complete else None
        )
        summary["total_before_module1_gross_eur"] = (
            summary.get("total_before_module1_gross_eur") if month_is_complete else None
        )
        summary["total_after_module1_gross_eur"] = monthly_total
        summary["monthly_total_gross_eur"] = monthly_total
        summaries.append(summary)
    return summaries


def _decimal(value: Any) -> Decimal | None:
    if value is None or value == "":
        return None
    try:
        return Decimal(str(value))
    except InvalidOperation, TypeError, ValueError:
        return None


def _vat_fraction(value: Any, fallback: Decimal) -> Decimal:
    parsed = _decimal(value)
    if parsed is None:
        return fallback
    return parsed / 100 if parsed > 1 else parsed


def _agreement_is_valid(product: dict[str, Any], at: datetime) -> bool:
    start = parse_product_datetime(product.get("validFrom"))
    end = parse_product_datetime(product.get("validTo"))
    at_utc = at.astimezone(UTC)
    return start is not None and start <= at_utc and (end is None or at_utc < end)


def _select_product(
    products: list[dict[str, Any]], at: datetime
) -> dict[str, Any] | None:
    matches = [product for product in products if _agreement_is_valid(product, at)]
    if not matches:
        return None
    return max(matches, key=lambda item: item.get("validFrom") or "")


def _rule_matches(rate: dict[str, Any], at: datetime) -> bool:
    local_time = at.timetz().replace(tzinfo=None)
    rules = rate.get("activation_rules") or []
    if not rules:
        return True
    for rule in rules:
        start = parse_tariff_time(rule.get("from_time") or "00:00:00")
        end = parse_tariff_time(rule.get("to_time") or "00:00:00")
        if (
            start is not None
            and end is not None
            and is_time_between(local_time, start, end)
        ):
            return True
    return False


def _price_is_valid(rate: dict[str, Any], at: datetime) -> bool:
    start = parse_product_datetime(rate.get("price_valid_from"))
    end = parse_product_datetime(rate.get("price_valid_to"))
    at_utc = at.astimezone(UTC)
    return (start is None or start <= at_utc) and (end is None or at_utc < end)


def _forecast_price(product: dict[str, Any], at: datetime) -> Decimal | None:
    at_utc = at.astimezone(UTC)
    for forecast in product.get("unitRateForecast") or []:
        start = parse_product_datetime(forecast.get("validFrom"))
        end = parse_product_datetime(forecast.get("validTo"))
        if start is None or end is None or not start <= at_utc < end:
            continue
        info = forecast.get("unitRateInformation") or {}
        rates = info.get("rates") or []
        cents = (
            rates[0].get("latestGrossUnitRateCentsPerKwh")
            if rates
            else info.get("latestGrossUnitRateCentsPerKwh")
        )
        amount = _decimal(cents)
        return amount / 100 if amount is not None else None
    return None


def _tariff_rate(
    product: dict[str, Any],
    at: datetime,
    fallback_vat: Decimal,
) -> tuple[str, Decimal | None, Decimal]:
    """Return the agreement's own price label, gross EUR/kWh and VAT fraction."""
    applicable = [
        rate
        for rate in (product.get("prices") or [])
        if _price_is_valid(rate, at) and _rule_matches(rate, at)
    ]
    selected = applicable[0] if applicable else {}
    label = str(selected.get("name") or "").strip()
    vat = _vat_fraction(selected.get("vat_percent"), fallback_vat)

    gross = _decimal(selected.get("gross_eur_per_kwh"))
    if gross is None and product.get("type") == "TimeOfUse":
        for timeslot in product.get("timeslots") or []:
            if not _rule_matches(timeslot, at):
                continue
            cents = _decimal(timeslot.get("rate"))
            if cents is not None:
                gross = cents / 100
                vat = _vat_fraction(timeslot.get("vat_rate"), fallback_vat)
                if not label:
                    label = str(timeslot.get("name") or "").strip()
                break
    forecast = _forecast_price(product, at)
    if forecast is not None:
        gross = forecast
    if gross is None and product.get("type") == "Simple":
        cents = _decimal(product.get("grossRate"))
        if cents is not None:
            gross = cents / 100
    return (
        label or str(product.get("name") or product.get("code") or "Unlabelled"),
        gross,
        vat,
    )


def _standard_grid_fee(
    grid_fee_data: dict[str, Any], at: datetime
) -> dict[str, Any] | None:
    """Find one valid STANDARD reference rate for periods outside Module 3."""
    at_utc = at.astimezone(UTC)
    matches = []
    for rate in grid_fee_data.get("rates") or []:
        if str(rate.get("rate_type") or "").upper() != "STANDARD":
            continue
        start = parse_product_datetime(rate.get("valid_from"))
        end = parse_product_datetime(rate.get("valid_to"))
        if start is not None and at_utc < start:
            continue
        if end is not None and at_utc >= end:
            continue
        value = _decimal(rate.get("rate_eur_per_kwh"))
        if value is not None:
            matches.append((rate, value))
    unique = {value for _, value in matches}
    return matches[0][0] if len(unique) == 1 else None


def _column_slug(value: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "_", value.lower()).strip("_")
    return slug or "unlabelled"


def _standing_charge(
    product: dict[str, Any] | None, at: datetime, vat: Decimal
) -> Decimal | None:
    if product is None:
        return None
    at_date = at.date()
    for rate in product.get("standing_charge_gross_rates") or []:
        start = parse_product_datetime(rate.get("valid_from"))
        end = parse_product_datetime(rate.get("valid_to"))
        instant = datetime.combine(at_date, time.min, tzinfo=at.tzinfo).astimezone(UTC)
        if start is not None and instant < start:
            continue
        if end is not None and instant >= end:
            continue
        gross_monthly = _decimal(rate.get("gross_eur_per_month"))
        if gross_monthly is not None:
            return gross_monthly * _MONTHS_PER_YEAR / _DAYS_PER_STANDING_CHARGE_YEAR
    net_monthly = _decimal(product.get("standing_charge_net_eur_per_month"))
    if net_monthly is not None:
        return (
            net_monthly
            * _MONTHS_PER_YEAR
            * (Decimal(1) + vat)
            / _DAYS_PER_STANDING_CHARGE_YEAR
        )
    return None


def build_daily_cost_report(
    readings_by_date: dict[str, list[dict[str, Any]]],
    products: list[dict[str, Any]],
    grid_fees_by_month: dict[tuple[int, int], dict[str, Any] | None],
    start_date: date,
    end_date: date,
    timezone: str,
    contract_start_network_charge_ct_kwh: Decimal,
    module1_start_date: date | None,
    module1_annual_net_eur: Decimal,
    fallback_vat_fraction: Decimal,
) -> list[dict[str, Any]]:
    """Build one detailed billing CSV row per local day."""
    contract_start_network_charge_ct_kwh = _decimal(
        contract_start_network_charge_ct_kwh
    ) or Decimal(0)
    module1_annual_net_eur = _decimal(module1_annual_net_eur) or Decimal(0)
    fallback_vat_fraction = _decimal(fallback_vat_fraction) or Decimal("0.19")
    local_timezone = ZoneInfo(timezone)
    rows = []
    current_date = start_date
    while current_date <= end_date:
        day_readings = readings_by_date.get(current_date.isoformat(), [])
        quantities: dict[tuple[str, str], Decimal] = {}
        base_costs: dict[tuple[str, str], Decimal] = {}
        adjustments: dict[tuple[str, str], Decimal] = {}
        final_costs: dict[tuple[str, str], Decimal] = {}
        tariff_labels: dict[str, str] = {}
        unpriced_kwh = Decimal(0)
        missing_network_kwh = Decimal(0)
        agreement_names: set[str] = set()
        modules_seen: set[str] = set()
        grid_fee_data = (
            grid_fees_by_month.get((current_date.year, current_date.month)) or {}
        )
        for reading in day_readings:
            start_value = reading.get("start_time")
            quantity = _decimal(reading.get("value"))
            if not start_value or quantity is None:
                continue
            try:
                start_at = datetime.fromisoformat(start_value)
                if start_at.tzinfo is None:
                    start_at = start_at.replace(tzinfo=UTC)
                local_at = start_at.astimezone(local_timezone)
            except ValueError:
                continue
            product = _select_product(products, local_at)
            if product is None:
                unpriced_kwh += quantity
                continue
            agreement_names.add(
                str(product.get("name") or product.get("code") or "Unknown")
            )
            tariff, base_rate, vat = _tariff_rate(
                product, local_at, fallback_vat_fraction
            )
            if base_rate is None:
                unpriced_kwh += quantity
                continue

            active = get_active_grid_fee(grid_fee_data, local_at)
            module_name = str(
                (active or {}).get("module") or grid_fee_data.get("module") or "UNKNOWN"
            ).upper()
            modules_seen.add(module_name)
            module3_active = module_name == "MODULE_3"
            network_rate = None
            band = "BASE"
            if module3_active:
                if active is not None:
                    network_rate = _decimal(active.get("rate_eur_per_kwh"))
                    band = str(active.get("rate_type") or "BASE").upper()
            else:
                standard = _standard_grid_fee(grid_fee_data, local_at)
                if standard is not None:
                    network_rate = _decimal(standard.get("rate_eur_per_kwh"))
                    band = str(standard.get("rate_type") or "BASE").upper()
            tariff_slug = _column_slug(tariff)
            tariff_labels[tariff_slug] = tariff
            block = (tariff_slug, _column_slug(band))
            base_cost = quantity * base_rate
            if network_rate is None:
                missing_network_kwh += quantity
                gross_adjustment = Decimal(0)
                final_cost = Decimal(0)
            else:
                gross_adjustment = (
                    quantity
                    * (
                        network_rate * Decimal(100)
                        - contract_start_network_charge_ct_kwh
                    )
                    * (Decimal(1) + vat)
                    / Decimal(100)
                )
                final_rate = base_rate + (
                    network_rate * Decimal(100) - contract_start_network_charge_ct_kwh
                ) * (Decimal(1) + vat) / Decimal(100)
                final_cost = quantity * final_rate
            quantities[block] = quantities.get(block, Decimal(0)) + quantity
            base_costs[block] = base_costs.get(block, Decimal(0)) + base_cost
            adjustments[block] = adjustments.get(block, Decimal(0)) + gross_adjustment
            final_costs[block] = final_costs.get(block, Decimal(0)) + final_cost

        noon = datetime.combine(current_date, time(12), tzinfo=local_timezone)
        current_product = _select_product(products, noon)
        standing = _standing_charge(current_product, noon, fallback_vat_fraction)
        module1_net = Decimal(0)
        if module1_start_date is not None and current_date >= module1_start_date:
            days_in_year = (
                date(current_date.year + 1, 1, 1) - date(current_date.year, 1, 1)
            ).days
            module1_net = module1_annual_net_eur / Decimal(days_in_year)
        module1_gross = module1_net * (Decimal(1) + fallback_vat_fraction)
        total_energy = sum(final_costs.values(), Decimal(0))
        network_adjustment = sum(adjustments.values(), Decimal(0))
        network_operator = grid_fee_data.get("grid_operator_name")
        network_operator_code = grid_fee_data.get("grid_operator_code")
        status = "complete"
        if not day_readings:
            status = "missing readings"
        elif unpriced_kwh > 0:
            status = "incomplete: tariff price missing"
        elif missing_network_kwh > 0:
            status = "incomplete: network rate missing"
        elif standing is None:
            status = "incomplete: standing charge missing"

        row: dict[str, Any] = {
            "date": current_date.isoformat(),
            "tariff_agreement": " | ".join(sorted(agreement_names)),
            "grid_operator": network_operator or "Unknown",
            "grid_operator_code": network_operator_code or "",
            "network_module": " | ".join(sorted(modules_seen))
            or grid_fee_data.get("module")
            or "Unknown",
            "total_kwh": sum(quantities.values(), Decimal(0)) + unpriced_kwh,
            "network_adjustment_gross_eur": network_adjustment,
            "energy_cost_after_adjustment_gross_eur": total_energy,
            "standing_charge_gross_eur": standing,
            "module1_credit_net_eur": module1_net,
            "module1_credit_gross_eur": module1_gross,
            "total_before_module1_gross_eur": total_energy + (standing or Decimal(0)),
            "total_after_module1_gross_eur": total_energy
            + (standing or Decimal(0))
            - module1_gross,
            "unpriced_kwh": unpriced_kwh,
            "network_rate_missing_kwh": missing_network_kwh,
            "status": status,
        }
        for (tariff_slug, band_slug), quantity in quantities.items():
            prefix = f"{tariff_slug}_{band_slug}"
            block = (tariff_slug, band_slug)
            row[f"{prefix}_kwh"] = quantity
            row[f"{prefix}_contract_cost_gross_eur"] = base_costs[block]
            row[f"{prefix}_network_adjustment_gross_eur"] = adjustments[block]
            row[f"{prefix}_final_cost_gross_eur"] = final_costs[block]
        for tariff_slug, tariff_label in tariff_labels.items():
            tariff_blocks = [block for block in quantities if block[0] == tariff_slug]
            tariff_quantity = sum(
                (quantities[block] for block in tariff_blocks), Decimal(0)
            )
            tariff_cost = sum(
                (base_costs[block] for block in tariff_blocks), Decimal(0)
            )
            prefix = f"tariff_{tariff_slug}"
            row[f"{prefix}_label"] = tariff_label
            row[f"{prefix}_kwh"] = tariff_quantity
            row[f"{prefix}_contract_ap_gross_eur_per_kwh"] = (
                tariff_cost / tariff_quantity if tariff_quantity else None
            )
            row[f"{prefix}_contract_cost_gross_eur"] = tariff_cost
        rows.append(row)
        current_date += timedelta(days=1)
    return rows
