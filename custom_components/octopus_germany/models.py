"""Typed runtime models for Octopus Germany account capabilities."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any, TypedDict


class TariffCapabilityData(TypedDict):
    """Serialized tariff capabilities stored in coordinator data."""

    has_dynamic_prices: bool
    has_intelligent_dispatches: bool
    has_smart_meter: bool


class AccountData(TypedDict, total=False):
    """Normalized data contract for one account."""

    account_number: str
    electricity_balance: float
    gas_balance: float
    heat_balance: float
    other_ledgers: dict[str, float]
    planned_dispatches: list[dict[str, Any]]
    completed_dispatches: list[dict[str, Any]]
    property_ids: list[str | None]
    devices: list[dict[str, Any]]
    products: list[dict[str, Any]]
    gas_products: list[dict[str, Any]]
    charging_sessions: list[dict[str, Any]] | None
    vehicle_battery_size_in_kwh: float | None
    current_start: Any
    current_end: Any
    next_start: Any
    next_end: Any
    ledgers: list[dict[str, Any]]
    malo_number: str | None
    melo_number: str | None
    meter: dict[str, Any] | None
    gas_malo_number: str | None
    gas_melo_number: str | None
    gas_meter: dict[str, Any] | None
    tariff_capabilities: TariffCapabilityData
    gas_price: float | None
    gas_contract_start: str | None
    gas_contract_end: str | None
    gas_contract_days_until_expiry: int | None
    gas_meter_smart_reading: bool | None
    gas_latest_reading: dict[str, Any] | None
    electricity_latest_reading: dict[str, Any] | None
    electricity_smart_meter_readings: list[dict[str, Any]]


CoordinatorData = dict[str, AccountData]


@dataclass(frozen=True, slots=True)
class TariffCapabilities:
    """Features that are available for an account."""

    has_dynamic_prices: bool = False
    has_intelligent_dispatches: bool = False
    has_smart_meter: bool = False


TERMINAL_ACCOUNT_STATUSES = frozenset({"DORMANT", "VOID", "WITHDRAWN"})
ELECTRICITY_LEDGER = "ELECTRICITY_LEDGER"


def account_has_electricity(account: Mapping[str, Any]) -> bool:
    """Return whether an account carries an electricity supply ledger."""
    return any(
        (ledger or {}).get("ledgerType") == ELECTRICITY_LEDGER
        for ledger in account.get("ledgers", []) or []
    )


def filter_active_accounts(
    accounts: list[Mapping[str, Any]],
) -> list[Mapping[str, Any]]:
    """Exclude accounts that are no longer active for polling."""
    return [
        account
        for account in accounts
        if account.get("status") not in TERMINAL_ACCOUNT_STATUSES
    ]


def select_primary_account(accounts: list[Mapping[str, Any]]) -> str | None:
    """Prefer an active account with an electricity ledger."""
    electricity_account = next(
        (account for account in accounts if account_has_electricity(account)),
        None,
    )
    account = electricity_account or (accounts[0] if accounts else None)
    return account.get("number") if account else None


def has_intelligent_capability(account_data: Mapping[str, Any]) -> bool:
    """Return whether normalized account data supports Intelligent entities."""
    return bool(
        account_data.get("tariff_capabilities", {}).get(
            "has_intelligent_dispatches", False
        )
    )


def detect_tariff_capabilities(account_data: Mapping[str, Any]) -> TariffCapabilities:
    """Detect available tariff features from an account response."""
    products: list[Mapping[str, Any]] = []
    has_smart_meter = False

    for property_data in account_data.get("allProperties", []) or []:
        for meter_data in property_data.get("electricityMalos", []) or []:
            meters = meter_data.get("meters") or []
            if not meters and meter_data.get("meter"):
                meters = [meter_data["meter"]]
            has_smart_meter |= any(
                bool(meter.get("shouldReceiveSmartMeterData")) for meter in meters
            )
            for agreement in meter_data.get("agreements", []) or []:
                product = agreement.get("product") or {}
                if isinstance(product, Mapping):
                    products.append(product)

    product_text = " ".join(
        str(product.get(field, ""))
        for product in products
        for field in ("code", "description", "fullName")
    ).lower()
    has_dynamic_prices = any(bool(product.get("isTimeOfUse")) for product in products)
    has_intelligent_dispatches = (
        any(
            marker in product_text
            for marker in ("intelligent", "smart flex", "smartflex")
        )
        or bool(account_data.get("intelligentDispatches"))
        or bool(account_data.get("devices"))
    )

    return TariffCapabilities(
        has_dynamic_prices=has_dynamic_prices,
        has_intelligent_dispatches=has_intelligent_dispatches,
        has_smart_meter=has_smart_meter,
    )
