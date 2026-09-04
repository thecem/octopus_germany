"""Typed runtime models for Octopus Germany account capabilities."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True, slots=True)
class TariffCapabilities:
    """Features that are available for an account."""

    has_dynamic_prices: bool = False
    has_intelligent_dispatches: bool = False
    has_smart_meter: bool = False


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
    has_intelligent_dispatches = any(
        marker in product_text for marker in ("intelligent", "smart flex", "smartflex")
    ) or bool(account_data.get("intelligentDispatches"))

    return TariffCapabilities(
        has_dynamic_prices=has_dynamic_prices,
        has_intelligent_dispatches=has_intelligent_dispatches,
        has_smart_meter=has_smart_meter,
    )
