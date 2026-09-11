"""Shared smart-meter error and backoff primitives for API mixins."""

from __future__ import annotations

from datetime import timedelta

SMART_METER_ERROR_BACKOFF = timedelta(hours=3)


class SmartMeterFetchError(RuntimeError):
    """Raised when the smart-meter endpoint fails instead of returning no data."""
