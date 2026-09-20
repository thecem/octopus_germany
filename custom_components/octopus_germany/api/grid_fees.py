"""Variable grid fee API support for the Octopus Germany OE backend."""

from __future__ import annotations

import logging
from datetime import date
from typing import Any

from .queries import VARIABLE_GRID_FEES_QUERY

_LOGGER = logging.getLogger(__name__)


class GridFeeApiMixin:
    """Mixin that retrieves optional variable grid fee information."""

    async def fetch_variable_grid_fees(
        self,
        account_number: str,
        grid_operator_code: str,
        on_date: date,
    ) -> dict[str, Any] | None:
        """Fetch variable grid fees once per account, operator and local date."""
        cache_key = (account_number, grid_operator_code, on_date.isoformat())
        cache = getattr(self, "_variable_grid_fees_cache", {})
        if cache_key in cache:
            return cache[cache_key]

        if not await self.ensure_token():
            return None

        try:
            response = await self._get_oe_backend_graphql_client().execute_async(
                query=VARIABLE_GRID_FEES_QUERY,
                variables={
                    "accountNumber": account_number,
                    "gridOperatorCode": grid_operator_code,
                    "date": on_date.isoformat(),
                },
            )
        except Exception as err:
            _LOGGER.warning("Unable to fetch variable grid fees: %s", err)
            return None

        errors = response.get("errors") or []
        if errors:
            error_codes = [
                error.get("extensions", {}).get("errorCode") for error in errors
            ]
            _LOGGER.warning("Variable grid fee request failed: %s", error_codes)
            return None

        result = (response.get("data") or {}).get("variableGridFees")
        if not result:
            return None

        cache[cache_key] = result
        self._variable_grid_fees_cache = cache
        return result
