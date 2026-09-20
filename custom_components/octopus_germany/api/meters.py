"""Meter reading methods for the Octopus Germany API client."""

from __future__ import annotations

import logging
from datetime import UTC, datetime
from typing import Any

from .queries import (
    ELECTRICITY_15MIN_READINGS_QUERY,
    ELECTRICITY_MEASUREMENTS_RANGE_QUERY,
    ELECTRICITY_METER_READINGS_QUERY,
    ELECTRICITY_SMART_METER_READINGS_QUERY,
    ELECTRICITY_SMART_METER_READINGS_QUERY_V2,
    GAS_METER_READINGS_QUERY,
)
from .smart_meter import SMART_METER_ERROR_BACKOFF, SmartMeterFetchError

_LOGGER = logging.getLogger(__name__)

_MEASUREMENT_PAGE_SIZE = 100
_READING_FREQUENCIES = {
    "15min": "RAW_INTERVAL",
    "hour": "HOUR_INTERVAL",
    "day": "DAY_INTERVAL",
}


class MeterApiMixin:
    """Mixin that provides meter-reading API calls."""

    async def fetch_gas_meter_reading(
        self, account_number: str, meter_id: str
    ) -> dict[str, Any] | None:
        """
        Fetch the latest gas meter reading for a specific meter.

        Args:
            account_number: The account number
            meter_id: The gas meter ID

        Returns:
            Dict containing the latest reading data or None if error

        """
        if not await self.ensure_token():
            _LOGGER.error("Failed to ensure valid token for fetch_gas_meter_reading")
            return None

        variables = {"accountNumber": account_number, "meterId": meter_id}
        client = self._get_graphql_client()

        try:
            _LOGGER.debug(
                "Fetching gas meter reading for account %s, meter %s",
                account_number,
                meter_id,
            )
            response = await client.execute_async(
                query=GAS_METER_READINGS_QUERY, variables=variables
            )

            if response is None:
                _LOGGER.error("API returned None response for gas meter reading")
                return None

            if "errors" in response:
                _LOGGER.error(
                    "GraphQL errors in gas meter reading response: %s",
                    response["errors"],
                )
                return None

            if "data" in response and "gasMeterReadings" in response["data"]:
                readings_data = response["data"]["gasMeterReadings"]

                if (
                    readings_data
                    and "edges" in readings_data
                    and readings_data["edges"]
                ):
                    # Get the first (latest) reading
                    latest_reading = readings_data["edges"][0]["node"]
                    _LOGGER.debug(
                        "Got gas meter reading: %s at %s (type: %s, origin: %s)",
                        latest_reading.get("value"),
                        latest_reading.get("readAt"),
                        latest_reading.get("typeOfRead"),
                        latest_reading.get("origin"),
                    )
                    return latest_reading
                _LOGGER.warning("No gas meter readings found for meter %s", meter_id)
                return None
            _LOGGER.error("Invalid response structure for gas meter reading")
            return None

        except Exception:
            _LOGGER.exception("Error fetching gas meter reading")
            return None

    async def fetch_electricity_meter_reading(
        self, account_number: str, meter_id: str
    ) -> dict[str, Any] | None:
        """
        Fetch the latest electricity meter reading for a specific meter.

        Args:
            account_number: The account number
            meter_id: The electricity meter ID

        Returns:
            Dict containing the latest reading data or None if error

        """
        if not await self.ensure_token():
            _LOGGER.error(
                "Failed to ensure valid token for fetch_electricity_meter_reading"
            )
            return None

        variables = {"accountNumber": account_number, "meterId": meter_id}
        client = self._get_graphql_client()

        try:
            _LOGGER.debug(
                "Fetching electricity meter reading for account %s, meter %s",
                account_number,
                meter_id,
            )
            response = await client.execute_async(
                query=ELECTRICITY_METER_READINGS_QUERY, variables=variables
            )

            if response is None:
                _LOGGER.error(
                    "API returned None response for electricity meter reading"
                )
                return None

            if "errors" in response:
                _LOGGER.error(
                    "GraphQL errors in electricity meter reading response: %s",
                    response["errors"],
                )
                return None

            if "data" in response and "electricityMeterReadings" in response["data"]:
                readings_data = response["data"]["electricityMeterReadings"]

                if (
                    readings_data
                    and "edges" in readings_data
                    and readings_data["edges"]
                ):
                    # Get the first (latest) reading
                    latest_reading = readings_data["edges"][0]["node"]
                    _LOGGER.debug(
                        "Got electricity meter reading: %s at %s "
                        "(type: %s, origin: %s)",
                        latest_reading.get("value"),
                        latest_reading.get("readAt"),
                        latest_reading.get("typeOfRead"),
                        latest_reading.get("origin"),
                    )
                    return latest_reading
                _LOGGER.warning(
                    "No electricity meter readings found for meter %s", meter_id
                )
                return None
            _LOGGER.error("Invalid response structure for electricity meter reading")
            return None

        except Exception:
            _LOGGER.exception("Error fetching electricity meter reading")
            return None

    async def fetch_electricity_smart_meter_readings(
        self, account_number: str, property_id: str, date: str
    ) -> list[dict[str, Any]] | None:
        """
        Fetch electricity smart meter readings for a specific date.

        Args:
            account_number: The account number
            property_id: The property ID
            date: Date in YYYY-MM-DD format

        Returns:
            Dict containing the hourly smart meter readings or None if error

        """
        if not await self.ensure_token():
            _LOGGER.error(
                "Failed to ensure valid token for "
                "fetch_electricity_smart_meter_readings"
            )
            return None

        now = datetime.now(UTC)
        if self._smart_meter_retry_until and now < self._smart_meter_retry_until:
            _LOGGER.debug(
                "Skipping smart-meter request until %s after a previous server error",
                self._smart_meter_retry_until.isoformat(),
            )
            msg = "Smart-meter request is in backoff"
            raise SmartMeterFetchError(msg)

        variables = {
            "accountNumber": account_number,
            "propertyId": property_id,
            "date": date,
        }

        client = self._get_graphql_client()

        try:
            _LOGGER.debug(
                "Fetching smart meter readings for account %s, property %s, date %s",
                account_number,
                property_id,
                date,
            )
            response = await client.execute_async(
                query=ELECTRICITY_SMART_METER_READINGS_QUERY, variables=variables
            )

            if response is None:
                self._smart_meter_retry_until = now + SMART_METER_ERROR_BACKOFF
                _LOGGER.error(
                    "API returned None response for electricity smart meter readings"
                )
                msg = "Smart-meter request returned no response"
                raise SmartMeterFetchError(msg)

            if "errors" in response:
                self._smart_meter_retry_until = now + SMART_METER_ERROR_BACKOFF
                _LOGGER.error(
                    "GraphQL errors in electricity smart meter readings response: %s",
                    response["errors"],
                )
                msg = "Smart-meter GraphQL request failed"
                raise SmartMeterFetchError(msg)

            if self._smart_meter_retry_until is not None:
                _LOGGER.info("Smart-meter endpoint recovered")
                self._smart_meter_retry_until = None

            if (
                "data" in response
                and "account" in response["data"]
                and response["data"]["account"]
                and "property" in response["data"]["account"]
                and response["data"]["account"]["property"]
                and "measurements" in response["data"]["account"]["property"]
            ):
                measurements = response["data"]["account"]["property"]["measurements"]

                if measurements and "edges" in measurements and measurements["edges"]:
                    readings = []
                    for edge in measurements["edges"]:
                        if edge.get("node"):
                            reading = edge["node"]
                            readings.append(
                                {
                                    "start_time": reading.get("startAt"),
                                    "end_time": reading.get("endAt"),
                                    "value": reading.get("value"),
                                    "unit": reading.get("unit"),
                                }
                            )

                    _LOGGER.debug(
                        "Found %d smart meter readings for property %s on %s",
                        len(readings),
                        property_id,
                        date,
                    )
                    return readings
                _LOGGER.debug(
                    "No smart meter readings for property %s on %s "
                    "(data may not be available yet)",
                    property_id,
                    date,
                )
                return []
            _LOGGER.error(
                "Invalid response structure for electricity smart meter readings"
            )
            return None

        except SmartMeterFetchError:
            raise
        except Exception as e:
            self._smart_meter_retry_until = now + SMART_METER_ERROR_BACKOFF
            _LOGGER.exception("Error fetching electricity smart meter readings")
            msg = "Smart-meter HTTP or response decoding failed"
            raise SmartMeterFetchError(msg) from e

    async def fetch_electricity_15min_readings(
        self, account_number: str, property_id: str, date: str
    ) -> list[dict[str, Any]] | None:
        """
        Fetch 15-minute interval smart meter readings for a specific date.

        Args:
            account_number: The account number
            property_id: The property ID
            date: Date in YYYY-MM-DD format

        Returns:
            List of 15-min readings with start_time, end_time, value,
            unit or None if error

        """
        if not await self.ensure_token():
            _LOGGER.error("Failed to ensure valid token for 15min readings")
            return None

        now = datetime.now(UTC)
        if self._15min_retry_until and now < self._15min_retry_until:
            _LOGGER.debug(
                "Skipping 15min smart-meter request until %s after a previous "
                "server error",
                self._15min_retry_until.isoformat(),
            )
            msg = "15-minute smart-meter request is in backoff"
            raise SmartMeterFetchError(msg)

        variables = {
            "accountNumber": account_number,
            "propertyId": property_id,
            "date": date,
        }

        client = self._get_graphql_client()

        try:
            response = await client.execute_async(
                query=ELECTRICITY_15MIN_READINGS_QUERY, variables=variables
            )
        except Exception as err:
            self._15min_retry_until = now + SMART_METER_ERROR_BACKOFF
            _LOGGER.exception("Error fetching 15min readings")
            msg = "15-minute smart-meter HTTP or response decoding failed"
            raise SmartMeterFetchError(msg) from err

        if response is None:
            self._15min_retry_until = now + SMART_METER_ERROR_BACKOFF
            msg = "15-minute smart-meter request returned no response"
            raise SmartMeterFetchError(msg)

        if "errors" in response:
            self._15min_retry_until = now + SMART_METER_ERROR_BACKOFF
            errors = response["errors"]
            error_code = errors[0].get("extensions", {}).get("errorCode")
            if error_code == "KT-CT-1199":
                _LOGGER.warning("15-minute smart-meter API rate limit reached")
                msg = "15-minute smart-meter API rate limit reached"
            else:
                _LOGGER.error("GraphQL errors in 15min readings: %s", errors)
                msg = "15-minute smart-meter GraphQL request failed"
            raise SmartMeterFetchError(msg)

        if self._15min_retry_until is not None:
            _LOGGER.info("15min smart-meter endpoint recovered")
            self._15min_retry_until = None

        measurements = (
            response.get("data", {})
            .get("account", {})
            .get("property", {})
            .get("measurements", {})
        )

        if measurements and "edges" in measurements and measurements["edges"]:
            readings = []
            for edge in measurements["edges"]:
                if edge.get("node"):
                    reading = edge["node"]
                    readings.append(
                        {
                            "start_time": reading.get("startAt"),
                            "end_time": reading.get("endAt"),
                            "value": reading.get("value"),
                            "unit": reading.get("unit"),
                        }
                    )
            _LOGGER.debug(
                "Found %d 15-min readings for property %s on %s",
                len(readings),
                property_id,
                date,
            )
            return readings

        return []

    async def fetch_electricity_measurements_range(
        self,
        property_id: str,
        market_supply_point_id: str,
        start_at: str,
        end_at: str,
        timezone: str,
        resolution: str,
    ) -> list[dict[str, Any]]:
        """Fetch and paginate electricity measurements for a time range."""
        if not await self.ensure_token():
            msg = "Failed to authenticate smart-meter measurement request"
            raise SmartMeterFetchError(msg)

        reading_frequency = _READING_FREQUENCIES.get(resolution)
        if reading_frequency is None:
            msg = f"Unsupported smart-meter resolution: {resolution}"
            raise ValueError(msg)

        now = datetime.now(UTC)
        if self._15min_retry_until and now < self._15min_retry_until:
            msg = "Smart-meter measurement request is in backoff"
            raise SmartMeterFetchError(msg)

        client = self._get_graphql_client()
        readings: list[dict[str, Any]] = []
        cursor = None

        while True:
            variables = {
                "propertyId": property_id,
                "first": _MEASUREMENT_PAGE_SIZE,
                "after": cursor,
                "utilityFilters": [
                    {
                        "electricityFilters": {
                            "marketSupplyPointId": market_supply_point_id,
                            "readingFrequencyType": reading_frequency,
                        }
                    }
                ],
                "startAt": start_at,
                "endAt": end_at,
                "timezone": timezone,
            }

            try:
                response = await client.execute_async(
                    query=ELECTRICITY_MEASUREMENTS_RANGE_QUERY,
                    variables=variables,
                )
            except Exception as err:
                self._15min_retry_until = now + SMART_METER_ERROR_BACKOFF
                msg = "Smart-meter measurement request failed"
                raise SmartMeterFetchError(msg) from err

            if response is None:
                self._15min_retry_until = now + SMART_METER_ERROR_BACKOFF
                msg = "Smart-meter measurement request returned no response"
                raise SmartMeterFetchError(msg)

            errors = response.get("errors") or []
            if errors:
                self._15min_retry_until = now + SMART_METER_ERROR_BACKOFF
                error_code = errors[0].get("extensions", {}).get("errorCode")
                if error_code == "KT-CT-1199":
                    msg = "Smart-meter measurement API rate limit reached"
                else:
                    msg = "Smart-meter measurement GraphQL request failed"
                raise SmartMeterFetchError(msg)

            property_data = (response.get("data") or {}).get("property") or {}
            measurements = property_data.get("measurements") or {}
            for edge in measurements.get("edges") or []:
                node = edge.get("node") or {}
                filters = (node.get("metaData") or {}).get("utilityFilters") or {}
                if node:
                    readings.append(
                        {
                            "start_time": node.get("startAt"),
                            "end_time": node.get("endAt"),
                            "duration_in_seconds": node.get("durationInSeconds"),
                            "value": node.get("value"),
                            "unit": node.get("unit"),
                            "source": node.get("source"),
                            "measurement_type": node.get("__typename"),
                            "market_supply_point_id": filters.get(
                                "marketSupplyPointId"
                            ),
                            "device_id": filters.get("deviceId"),
                            "register_id": filters.get("registerId"),
                            "reading_direction": filters.get("readingDirection"),
                            "reading_frequency": filters.get("readingFrequencyType"),
                            "reading_quality": filters.get("readingQuality"),
                        }
                    )

            page_info = measurements.get("pageInfo") or {}
            next_cursor = page_info.get("endCursor")
            if not page_info.get("hasNextPage"):
                break
            if not next_cursor or next_cursor == cursor:
                msg = "Smart-meter measurement pagination returned no new cursor"
                raise SmartMeterFetchError(msg)
            cursor = next_cursor

        if self._15min_retry_until is not None:
            _LOGGER.info("Smart-meter measurement endpoint recovered")
            self._15min_retry_until = None

        return readings

    async def fetch_electricity_smart_meter_readings_v2(
        self, account_number: str, property_id: str, date: str
    ) -> list[dict[str, Any]] | None:
        """
        Fetch electricity smart meter readings using the improved V2 query.

        Args:
            account_number: The account number
            property_id: The property ID
            date: The date in ISO format (YYYY-MM-DD)

        Returns:
            List of hourly readings with start_time, end_time, value, unit

        """
        if not await self.ensure_token():
            _LOGGER.error("Failed to ensure valid token for smart meter readings V2")
            return None

        variables = {
            "accountNumber": account_number,
            "propertyId": property_id,
            "date": date,
        }

        client = self._get_graphql_client()

        try:
            _LOGGER.debug(
                "Fetching smart meter readings V2 for account %s, property %s, date %s",
                account_number,
                property_id,
                date,
            )
            response = await client.execute_async(
                query=ELECTRICITY_SMART_METER_READINGS_QUERY_V2, variables=variables
            )

            if response.get("data"):
                account_data = response["data"].get("account")
                if (
                    account_data
                    and "property" in account_data
                    and account_data["property"]
                ):
                    property_data = account_data["property"]

                    # Log meter information from electricityMalos
                    if "electricityMalos" in property_data:
                        for malo in property_data["electricityMalos"]:
                            meters = malo.get("meters") or []
                            if not meters and malo.get("meter"):
                                meters = [malo["meter"]]
                            for meter in meters:
                                _LOGGER.info(
                                    "Meter info: id=%s, number=%s, type=%s, "
                                    "shouldReceiveSmartMeterData=%s",
                                    meter.get("id"),
                                    meter.get("number"),
                                    meter.get("meterType"),
                                    meter.get("shouldReceiveSmartMeterData"),
                                )

                    # Process measurements
                    measurements = property_data.get("measurements", {})
                    if measurements and "edges" in measurements:
                        readings = []
                        for edge in measurements["edges"]:
                            node = edge.get("node", {})
                            if node:
                                readings.append(
                                    {
                                        "start_time": node.get("startAt"),
                                        "end_time": node.get("endAt"),
                                        "value": node.get("value"),
                                        "unit": node.get("unit"),
                                    }
                                )

                        if readings:
                            _LOGGER.info(
                                "Successfully fetched %d smart meter readings V2",
                                len(readings),
                            )
                            return readings
                        _LOGGER.warning(
                            "No smart meter readings found in measurements for "
                            "property %s on %s",
                            property_id,
                            date,
                        )
                        return []
                    _LOGGER.warning(
                        "No measurements data found for property %s on %s",
                        property_id,
                        date,
                    )
                    return []
                _LOGGER.error(
                    "Invalid response structure for electricity smart meter readings V2"
                )
                return None
            _LOGGER.error("No data in response for electricity smart meter readings V2")

        except Exception:
            _LOGGER.exception("Error fetching electricity smart meter readings V2")
            return None
        return None
