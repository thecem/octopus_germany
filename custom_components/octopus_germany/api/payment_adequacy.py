"""Estimated annual consumption support for the Octopus Germany OE backend."""

from __future__ import annotations

import logging
import time
from typing import Any

from .queries import PAYMENT_ADEQUACY_QUERY

_LOGGER = logging.getLogger(__name__)

PAYMENT_ADEQUACY_CACHE_SECONDS = 3600


def _to_float(value: Any) -> float | None:
    """Convert a decimal string from the API to a float."""
    if value is None:
        return None
    try:
        return float(value)
    except TypeError, ValueError:
        return None


def normalize_estimated_annual_consumption(
    payment_adequacy: dict[str, Any] | None,
) -> dict[str, float | None] | None:
    """Return the estimated annual consumption in kWh, or None if unavailable."""
    estimate = (payment_adequacy or {}).get("estimatedAnnualConsumption") or {}
    current_year = _to_float(estimate.get("currentYear"))
    last_year = _to_float(estimate.get("lastYear"))
    if current_year is None and last_year is None:
        return None
    return {"current_year": current_year, "last_year": last_year}


class PaymentAdequacyApiMixin:
    """Mixin that retrieves the OE estimated annual consumption."""

    async def fetch_estimated_annual_consumption(
        self,
        account_number: str,
        property_id: str,
    ) -> dict[str, float | None] | None:
        """
        Fetch OE's estimated annual consumption for one account and property.

        The estimate changes slowly, so results (including unsupported accounts)
        are cached for one hour to avoid an extra request on every poll.
        """
        cache = getattr(self, "_payment_adequacy_cache", {})
        cache_key = (account_number, str(property_id))
        cached = cache.get(cache_key)
        if cached and time.monotonic() - cached[0] < PAYMENT_ADEQUACY_CACHE_SECONDS:
            return cached[1]

        if not await self.ensure_token():
            return None

        result: dict[str, float | None] | None = None
        try:
            response = await self._get_oe_backend_graphql_client().execute_async(
                query=PAYMENT_ADEQUACY_QUERY,
                variables={
                    "accountNumber": account_number,
                    "propertyId": str(property_id),
                },
            )
        except Exception as err:
            # Transient failure: do not cache, retry on the next poll.
            _LOGGER.debug("Unable to fetch estimated annual consumption: %s", err)
            return None

        errors = response.get("errors") or []
        if errors:
            # Expected for accounts without a simple single-tariff meter.
            _LOGGER.debug(
                "Estimated annual consumption not available: %s",
                [error.get("extensions", {}).get("errorCode") for error in errors],
            )
        else:
            result = normalize_estimated_annual_consumption(
                (response.get("data") or {}).get("paymentAdequacy")
            )

        cache[cache_key] = (time.monotonic(), result)
        self._payment_adequacy_cache = cache
        return result
