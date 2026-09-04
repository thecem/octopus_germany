"""Helpers for normalizing Octopus Germany API responses."""

from __future__ import annotations

from typing import Any

from homeassistant.util.dt import as_utc, parse_datetime, utcnow


def create_empty_account_data(account_number: str) -> dict[str, dict[str, Any]]:
    """Create the stable normalized account data structure."""
    return {
        account_number: {
            "account_number": account_number,
            "electricity_balance": 0,
            "planned_dispatches": [],
            "completed_dispatches": [],
            "property_ids": [],
            "devices": [],
            "products": [],
            "gas_products": [],
            "vehicle_battery_size_in_kwh": None,
            "current_start": None,
            "current_end": None,
            "next_start": None,
            "next_end": None,
            "ledgers": [],
            "malo_number": None,
            "melo_number": None,
            "meter": None,
            "gas_malo_number": None,
            "gas_melo_number": None,
            "gas_meter": None,
        }
    }


def process_ledgers(ledgers: list[dict[str, Any]]) -> dict[str, Any]:
    """Convert ledger balances from cents to euros by ledger type."""
    balances = {
        "electricity_balance": 0,
        "gas_balance": 0,
        "heat_balance": 0,
        "other_ledgers": {},
    }

    for ledger in ledgers:
        ledger_type = ledger.get("ledgerType")
        balance_eur = ledger.get("balance", 0) / 100

        if ledger_type == "ELECTRICITY_LEDGER":
            balances["electricity_balance"] = balance_eur
        elif ledger_type == "GAS_LEDGER":
            balances["gas_balance"] = balance_eur
        elif ledger_type == "HEAT_LEDGER":
            balances["heat_balance"] = balance_eur
        else:
            balances["other_ledgers"][ledger_type] = balance_eur

    return balances


def normalize_direct_products(
    direct_products: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    """Normalize products returned directly by the API."""
    products = []
    for product in direct_products:
        gross_info = product.get("grossRateInformation", {})
        if isinstance(gross_info, list):
            gross_rate = gross_info[0].get("grossRate", "0") if gross_info else "0"
        else:
            gross_rate = (
                gross_info.get("grossRate", "0")
                if isinstance(gross_info, dict)
                else "0"
            )
        products.append(
            {
                "code": product.get("code", "Unknown"),
                "description": product.get("description", ""),
                "name": product.get("fullName", "Unknown"),
                "grossRate": gross_rate,
                "type": "Simple",
                "validFrom": None,
                "validTo": None,
                "isTimeOfUse": product.get("isTimeOfUse", False),
            }
        )
    return products


def extract_gross_rate(rate_info: Any, default: Any = "0") -> Any:
    """Extract a gross rate from the API's dict or list response shapes."""
    if isinstance(rate_info, dict):
        return rate_info.get("grossRate", default)
    if isinstance(rate_info, list) and rate_info:
        return rate_info[0].get("grossRate", default)
    return default


def normalize_timeslots(rates: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Normalize time-of-use rates and their activation rules."""
    timeslots = []
    for rate in rates:
        gross_rate = extract_gross_rate(rate.get("grossRateInformation"))
        if gross_rate == "0":
            gross_rate = rate.get("latestGrossUnitRateCentsPerKwh", "0")
        activation_rules = [
            {
                "from_time": rule.get("activeFromTime", "00:00:00"),
                "to_time": rule.get("activeToTime", "00:00:00"),
            }
            for rule in rate.get("timeslotActivationRules", [])
        ]
        timeslots.append(
            {
                "name": rate.get("timeslotName", "Unknown"),
                "rate": gross_rate,
                "activation_rules": activation_rules,
            }
        )
    return timeslots


def normalize_unit_rate_forecast(forecast: Any) -> list[dict[str, Any]]:
    """Keep only mapping entries from the optional unit-rate forecast."""
    if not isinstance(forecast, list):
        return []
    return [entry for entry in forecast if isinstance(entry, dict)]


def get_product_type(rate_info: Any) -> str:
    """Map the API unit-rate typename to the integration product type."""
    if isinstance(rate_info, dict) and rate_info.get("__typename"):
        return (
            "Simple"
            if rate_info["__typename"] == "SimpleProductUnitRateInformation"
            else "TimeOfUse"
        )
    return "Simple"


def extract_meter_data(account_data: dict[str, Any]) -> dict[str, Any]:
    """Extract property, market-location and meter data from an account."""
    properties = account_data.get("allProperties", []) or []
    electricity_malos = [
        malo
        for property_data in properties
        for malo in property_data.get("electricityMalos", []) or []
    ]
    gas_malos = [
        malo
        for property_data in properties
        for malo in property_data.get("gasMalos", []) or []
    ]

    def first_meter(malo: dict[str, Any]) -> dict[str, Any] | None:
        meters = malo.get("meters") or []
        return (meters[0] if meters else None) or malo.get("meter")

    def meter_number(malo: dict[str, Any], field: str) -> Any:
        meter = first_meter(malo) or {}
        return meter.get(field) or malo.get(field)

    return {
        "malo_number": next(
            (
                malo.get("maloNumber")
                for malo in electricity_malos
                if malo.get("maloNumber")
            ),
            None,
        ),
        "melo_number": next(
            (
                meter_number(malo, "meloNumber")
                for malo in electricity_malos
                if meter_number(malo, "meloNumber")
            ),
            None,
        ),
        "meter": next(
            (first_meter(malo) for malo in electricity_malos if first_meter(malo)),
            None,
        ),
        "gas_malo_number": next(
            (malo.get("maloNumber") for malo in gas_malos if malo.get("maloNumber")),
            None,
        ),
        "gas_melo_number": next(
            (
                meter_number(malo, "meloNumber")
                for malo in gas_malos
                if meter_number(malo, "meloNumber")
            ),
            None,
        ),
        "gas_meter": next(
            (first_meter(malo) for malo in gas_malos if first_meter(malo)),
            None,
        ),
        "property_ids": [property_data.get("id") for property_data in properties],
    }


def extract_device_data(data: dict[str, Any]) -> dict[str, Any]:
    """Extract devices and the first available vehicle battery size."""
    devices = data.get("devices", []) or []
    vehicle_battery_size = None

    for device in devices:
        vehicle_variant = device.get("vehicleVariant") or {}
        battery_size = vehicle_variant.get("batterySize")
        if battery_size:
            try:
                vehicle_battery_size = float(battery_size)
                break
            except ValueError, TypeError:
                continue

    return {
        "devices": devices,
        "vehicle_battery_size_in_kwh": vehicle_battery_size,
    }


def calculate_dispatch_state(
    planned_dispatches: list[dict[str, Any]],
) -> dict[str, Any]:
    """Calculate the current and next dispatch from planned dispatches."""
    now = utcnow()
    current_start = None
    current_end = None
    next_start = None
    next_end = None

    for dispatch in sorted(planned_dispatches, key=lambda item: item.get("start", "")):
        try:
            start_str = dispatch.get("start")
            end_str = dispatch.get("end")
            if not start_str or not end_str:
                continue

            parsed_start = parse_datetime(start_str)
            parsed_end = parse_datetime(end_str)
            if parsed_start is None or parsed_end is None:
                continue

            start = as_utc(parsed_start)
            end = as_utc(parsed_end)
            if start <= now <= end:
                current_start = start
                current_end = end
            elif now < start and not next_start:
                next_start = start
                next_end = end
        except ValueError, TypeError:
            continue

    return {
        "current_start": current_start,
        "current_end": current_end,
        "next_start": next_start,
        "next_end": next_end,
    }


def extract_charging_sessions(
    devices: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    """Flatten charging sessions and add their device context."""
    charging_sessions = []
    for device in devices:
        device_id = device.get("id")
        device_name = device.get("name", "Unknown Device")
        device_type = device.get("deviceType", "UNKNOWN")
        sessions = device.get("chargingSessions", {})
        if not sessions:
            continue

        for edge in sessions.get("edges", []):
            session = edge.get("node", {})
            if not session:
                continue
            if "soc_final" not in session and "stateOfChargeFinal" in session:
                session["soc_final"] = session.get("stateOfChargeFinal")
            if "soc_change" not in session and "stateOfChargeChange" in session:
                session["soc_change"] = session.get("stateOfChargeChange")
            session["device_id"] = device_id
            session["device_name"] = device_name
            session["device_type"] = device_type
            charging_sessions.append(session)

    return charging_sessions


def merge_graphql_responses(
    base_response: dict[str, Any],
    intelligent_response: dict[str, Any] | None,
) -> dict[str, Any]:
    """Merge optional Intelligent data into a base GraphQL response."""
    merged = dict(base_response)
    base_data = dict(base_response.get("data") or {})
    intelligent_data = (intelligent_response or {}).get("data") or {}
    base_data.update(intelligent_data)
    merged["data"] = base_data

    errors = [
        *base_response.get("errors", []),
        *(intelligent_response or {}).get("errors", []),
    ]
    if errors:
        merged["errors"] = errors
    else:
        merged.pop("errors", None)

    return merged


def merge_normalized_account_data(
    base_data: dict[str, Any],
    intelligent_data: dict[str, Any] | None,
) -> dict[str, Any]:
    """Merge optional normalized Intelligent data without losing base data."""
    merged = dict(base_data)
    if not intelligent_data:
        return merged

    for key in (
        "devices",
        "charging_sessions",
        "completed_dispatches",
        "planned_dispatches",
        "current_start",
        "current_end",
        "next_start",
        "next_end",
        "vehicle_battery_size_in_kwh",
    ):
        if key in intelligent_data and intelligent_data[key] is not None:
            merged[key] = intelligent_data[key]

    return merged
