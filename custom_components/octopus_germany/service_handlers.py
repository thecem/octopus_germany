"""Service handlers for Octopus Germany integration."""

from __future__ import annotations

import csv
import json
import logging
from calendar import monthrange
from datetime import UTC, date, datetime, time, timedelta
from pathlib import Path
from typing import TYPE_CHECKING, Any
from zoneinfo import ZoneInfo

from homeassistant.core import HomeAssistant, ServiceCall, SupportsResponse
from homeassistant.exceptions import HomeAssistantError, ServiceValidationError

from .api.smart_meter import SmartMeterFetchError
from .const import DOMAIN
from .services import async_request_intelligent_refresh

if TYPE_CHECKING:
    from collections.abc import Callable

    from homeassistant.config_entries import ConfigEntry

    from .coordinator import OctopusDataCoordinator

_LOGGER = logging.getLogger(__name__)

_TARGET_PERCENT_MIN = 20
_TARGET_PERCENT_MAX = 100
_TARGET_PERCENT_STEP = 5
_MIN_MONTH = 1
_MAX_MONTH = 12
_MINUTES_PER_QUARTER_HOUR = 15
_DEFAULT_PERIOD = "month"
_DEFAULT_LAYOUT = "wide"
_DEFAULT_RESOLUTION = "15min"
_SUPPORTED_RESOLUTIONS = frozenset({"15min", "hour"})
_TIME_PARTS_MIN = 2
_MAX_HOUR = 23
_MAX_MINUTE = 59
_SAMPLE_READINGS_COUNT = 3


def _raise_validation_error(msg: str) -> None:
    """Raise a service validation error with integration translation metadata."""
    raise ServiceValidationError(msg, translation_domain=DOMAIN)


def _require_field(value: Any, msg: str) -> Any:
    """Require that a service field is provided."""
    if value:
        return value
    _raise_validation_error(msg)
    raise ValueError(msg)


def _parse_iso_date(date_str: Any, field_name: str) -> date:
    """Parse an ISO date string (YYYY-MM-DD)."""
    try:
        return date.fromisoformat(str(date_str))
    except ValueError:
        _raise_validation_error(
            f"Invalid {field_name} format: {date_str}. Expected YYYY-MM-DD"
        )
    return date.min


def _resolve_account_context(
    hass: HomeAssistant,
    account_number: str,
) -> tuple[Any, Any]:
    """Resolve coordinator and API client for a given account number."""
    for data in hass.data.get(DOMAIN, {}).values():
        coordinator = data.get("coordinator")
        coordinator_data = coordinator.data if coordinator else None
        if coordinator_data and account_number in coordinator_data:
            client = data.get("api") or data.get("client")
            if client:
                return coordinator, client

    _raise_validation_error(f"Account {account_number} not found or not loaded")
    return None, None


def _normalize_target_time(value: str) -> str:
    """Normalize a user-provided time string to HH:MM format."""
    pieces = value.split(":")
    if len(pieces) < _TIME_PARTS_MIN:
        msg = f"Invalid time format: {value!s}"
        raise ValueError(msg)

    try:
        hours = int(pieces[0])
        minutes = int(pieces[1])
    except ValueError as err:
        msg = f"Invalid time format: {value!s}"
        raise ValueError(msg) from err

    if not 0 <= hours <= _MAX_HOUR or not 0 <= minutes <= _MAX_MINUTE:
        msg = f"Invalid time format: {value!s}"
        raise ValueError(msg)

    return f"{hours:02d}:{minutes:02d}"


def _measurement_range_bounds(
    start_date: date, end_date: date, timezone: str
) -> tuple[str, str]:
    """Return an inclusive local-date range as exclusive UTC instants."""
    local_timezone = ZoneInfo(timezone)
    start_at = datetime.combine(start_date, time.min, tzinfo=local_timezone)
    end_at = datetime.combine(
        end_date + timedelta(days=1), time.min, tzinfo=local_timezone
    )
    return start_at.astimezone(UTC).isoformat(), end_at.astimezone(UTC).isoformat()


def _group_readings_by_local_date(
    readings: list[dict[str, Any]], timezone: str
) -> dict[str, list[dict[str, Any]]]:
    """Group interval readings by their local start date."""
    local_timezone = ZoneInfo(timezone)
    grouped: dict[str, list[dict[str, Any]]] = {}
    for reading in readings:
        start_time = reading.get("start_time")
        if not start_time:
            continue
        try:
            local_date = (
                datetime.fromisoformat(start_time).astimezone(local_timezone).date()
            )
        except TypeError, ValueError:
            _LOGGER.warning("Ignoring measurement with invalid start time")
            continue
        grouped.setdefault(local_date.isoformat(), []).append(reading)
    return grouped


def _summarize_measurement_metadata(
    readings: list[dict[str, Any]],
) -> dict[str, Any]:
    """Summarize meter-assignment and quality metadata without altering readings."""

    def distinct_values(field: str) -> list[str]:
        return sorted(
            {str(reading[field]) for reading in readings if reading.get(field)}
        )

    return {
        "measurement_count": len(readings),
        "sources": distinct_values("source"),
        "reading_qualities": distinct_values("reading_quality"),
        "reading_frequencies": distinct_values("reading_frequency"),
        "device_ids": distinct_values("device_id"),
        "register_ids": distinct_values("register_id"),
        "missing_device_id_count": sum(
            not reading.get("device_id") for reading in readings
        ),
        "missing_register_id_count": sum(
            not reading.get("register_id") for reading in readings
        ),
    }


# Service schemas
SERVICE_SET_DEVICE_PREFERENCES = "set_device_preferences"
SERVICE_GET_SMART_METER_READINGS = "get_smart_meter_readings"
SERVICE_EXPORT_SMART_METER_CSV = "export_smart_meter_csv"
SERVICE_SUBMIT_METER_READINGS = "submit_meter_readings"
ATTR_ACCOUNT_NUMBER = "account_number"
ATTR_DEVICE_ID = "device_id"
ATTR_TARGET_PERCENTAGE = "target_percentage"
ATTR_TARGET_TIME = "target_time"
ATTR_DATE = "date"
ATTR_READING_DATE = "reading_date"
ATTR_METER_ID = "meter_id"
ATTR_METER_TYPE = "meter_type"
ATTR_READINGS_JSON = "readings_json"
ATTR_READING_VALUE = "reading_value"
ATTR_REGISTER_OBIS_CODE = "register_obis_code"
ATTR_PROPERTY_ID = "property_id"
ATTR_PERIOD = "period"
ATTR_YEAR = "year"
ATTR_MONTH = "month"
ATTR_FILENAME = "filename"
ATTR_LAYOUT = "layout"
ATTR_RESOLUTION = "resolution"
ATTR_SUMMARY = "summary"
ATTR_GO_WINDOW_START = "go_window_start"
ATTR_GO_WINDOW_END = "go_window_end"


async def async_register_services(
    hass: HomeAssistant,
    entry: ConfigEntry,
    api: Any,
    coordinator: OctopusDataCoordinator,
    intelligent_coordinator_getter: Callable[[], OctopusDataCoordinator] | None,
) -> None:
    """Register integration services with unchanged behavior."""

    async def handle_set_device_preferences(call: ServiceCall) -> dict[str, bool]:
        """Handle the set_device_preferences service call."""
        device_id = _require_field(
            call.data.get(ATTR_DEVICE_ID),
            "Device ID is required",
        )
        target_percentage = call.data.get(ATTR_TARGET_PERCENTAGE)
        target_time = call.data.get(ATTR_TARGET_TIME)

        # Validate percentage (20-100% in 5% steps)
        if not _TARGET_PERCENT_MIN <= target_percentage <= _TARGET_PERCENT_MAX:
            _LOGGER.error(
                "Invalid target percentage: %s. Must be between %s and %s",
                target_percentage,
                _TARGET_PERCENT_MIN,
                _TARGET_PERCENT_MAX,
            )
            _raise_validation_error(
                "Invalid target percentage: "
                f"{target_percentage}. Must be between "
                f"{_TARGET_PERCENT_MIN} and {_TARGET_PERCENT_MAX}"
            )

        if target_percentage % _TARGET_PERCENT_STEP != 0:
            _LOGGER.error(
                "Invalid target percentage: %s. Must be in %s%% steps",
                target_percentage,
                _TARGET_PERCENT_STEP,
            )
            _raise_validation_error(
                f"Invalid target percentage: {target_percentage}. Must be in 5% steps"
            )

        # Validate time format
        try:
            normalized_target_time = _normalize_target_time(str(target_time))
        except ValueError as time_error:
            _LOGGER.exception("Time validation error")
            _raise_validation_error(f"Invalid time format: {time_error!s}")

        _LOGGER.debug(
            "Service call set_device_preferences with device_id=%s, "
            "target_percentage=%s, target_time=%s",
            device_id,
            target_percentage,
            normalized_target_time,
        )

        try:
            success = await api.set_device_preferences(
                device_id,
                target_percentage,
                normalized_target_time,
            )
        except ValueError as e:
            _LOGGER.exception("Validation error while setting device preferences")
            _raise_validation_error(f"Invalid parameters: {e}")
        except Exception as e:
            _LOGGER.exception("Unexpected error setting device preferences")
            msg = f"Error setting device preferences: {e}"
            raise HomeAssistantError(msg) from e

        if success:
            _LOGGER.info("Successfully set device preferences")
            await async_request_intelligent_refresh(hass)
            return {"success": True}

        _LOGGER.error("Failed to set device preferences")
        _raise_validation_error(
            "Failed to set device preferences. Check the log for details."
        )
        return {"success": False}

    async def handle_get_smart_meter_readings(call: ServiceCall) -> dict[str, Any]:
        """Handle the get_smart_meter_readings service call."""
        account_number = _require_field(
            call.data.get(ATTR_ACCOUNT_NUMBER),
            "Account number is required",
        )
        date_str = _require_field(
            call.data.get(ATTR_DATE),
            "Date is required",
        )
        property_id = call.data.get(ATTR_PROPERTY_ID)

        # Validate date format
        _parse_iso_date(date_str, "date")

        # Get the coordinator for this account
        account_coordinator, client = _resolve_account_context(hass, account_number)

        # Use property_id from service call or get first property from account
        if not property_id:
            account_data = account_coordinator.data[account_number]
            property_ids = account_data.get("property_ids", [])
            if not property_ids:
                _raise_validation_error(
                    f"No properties found for account {account_number}"
                )
            property_id = property_ids[0]

        _LOGGER.info(
            "Fetching smart meter readings for account %s, property %s, date %s",
            account_number,
            property_id,
            date_str,
        )

        try:
            # Fetch smart meter readings
            readings = await client.fetch_electricity_smart_meter_readings_v2(
                account_number, property_id, date_str
            )

            if readings:
                result = {
                    "success": True,
                    "account_number": account_number,
                    "property_id": property_id,
                    "date": date_str,
                    "total_readings": len(readings),
                    "readings": readings,
                    "total_consumption": sum(
                        float(r.get("value", 0)) for r in readings
                    ),
                }
                _LOGGER.info(
                    "Successfully fetched %d smart meter readings for %s",
                    len(readings),
                    date_str,
                )

                # Log a sample of the readings for debugging
                sample_readings = (
                    readings[:_SAMPLE_READINGS_COUNT]
                    if len(readings) > _SAMPLE_READINGS_COUNT
                    else readings
                )
                _LOGGER.info("Sample readings: %s", sample_readings)
                _LOGGER.info("Total consumption: %.3f kWh", result["total_consumption"])
            else:
                result = {
                    "success": False,
                    "account_number": account_number,
                    "property_id": property_id,
                    "date": date_str,
                    "total_readings": 0,
                    "readings": [],
                    "message": f"No smart meter readings found for {date_str}",
                }
                _LOGGER.warning("No smart meter readings found for %s", date_str)

            # Fire an event with the results
            hass.bus.async_fire(f"{DOMAIN}_smart_meter_readings_result", result)

            return result

        except Exception as e:
            _LOGGER.exception("Error fetching smart meter readings")
            msg = f"Error fetching smart meter readings: {e}"
            raise HomeAssistantError(msg) from e

    async def handle_export_smart_meter_csv(call: ServiceCall) -> dict[str, Any]:
        """Handle the export_smart_meter_csv service call."""
        account_number = _require_field(
            call.data.get(ATTR_ACCOUNT_NUMBER),
            "Account number is required",
        )
        property_id = call.data.get(ATTR_PROPERTY_ID)
        period = call.data.get(ATTR_PERIOD, _DEFAULT_PERIOD)
        year = _require_field(call.data.get(ATTR_YEAR), "Year is required")
        month = call.data.get(ATTR_MONTH)
        filename = call.data.get(ATTR_FILENAME)
        layout = call.data.get(ATTR_LAYOUT, _DEFAULT_LAYOUT)
        resolution = call.data.get(ATTR_RESOLUTION, _DEFAULT_RESOLUTION)
        add_summary = call.data.get(ATTR_SUMMARY, False)
        go_window_start = call.data.get(ATTR_GO_WINDOW_START)
        go_window_end = call.data.get(ATTR_GO_WINDOW_END)

        if period == "month" and not month:
            _raise_validation_error("Month is required for monthly export")

        if resolution not in _SUPPORTED_RESOLUTIONS:
            _raise_validation_error("Resolution must be either 15min or hour")

        # Validate month
        if month and (month < _MIN_MONTH or month > _MAX_MONTH):
            _raise_validation_error(
                f"Invalid month: {month}. Must be between {_MIN_MONTH} and {_MAX_MONTH}"
            )

        # Get the coordinator for this account
        account_coordinator, client = _resolve_account_context(hass, account_number)
        account_data = account_coordinator.data[account_number]

        # Get property_id if not provided
        if not property_id:
            property_ids = account_data.get("property_ids", [])
            if not property_ids:
                _raise_validation_error(
                    f"No properties found for account {account_number}"
                )
            property_id = property_ids[0]

        market_supply_point_id = account_data.get("malo_number")
        if not market_supply_point_id:
            _raise_validation_error(
                f"No electricity market supply point found for account {account_number}"
            )

        year_value = int(year)

        # Determine date range
        if period == "month":
            start_date = date(year_value, month, 1)
            _, last_day = monthrange(year_value, month)
            end_date = date(year_value, month, last_day)
        else:  # year
            start_date = date(year_value, 1, 1)
            end_date = date(year_value, 12, 31)
            month = None  # Reset month for yearly export

        _LOGGER.info(
            "Exporting smart meter data for account %s, property %s, period %s to %s",
            account_number,
            property_id,
            start_date.isoformat(),
            end_date.isoformat(),
        )

        try:
            # Collect all readings for the period
            all_readings = {}
            total_days = (end_date - start_date).days + 1
            timezone = hass.config.time_zone
            range_start = start_date

            while range_start <= end_date:
                _, range_last_day = monthrange(range_start.year, range_start.month)
                range_end = min(
                    date(range_start.year, range_start.month, range_last_day),
                    end_date,
                )
                start_at, end_at = _measurement_range_bounds(
                    range_start, range_end, timezone
                )
                try:
                    readings = await client.fetch_electricity_measurements_range(
                        property_id,
                        market_supply_point_id,
                        start_at,
                        end_at,
                        timezone,
                        resolution,
                    )
                    grouped_readings = _group_readings_by_local_date(readings, timezone)
                    all_readings.update(grouped_readings)
                    if readings:
                        _LOGGER.debug(
                            "Fetched %d readings for %s to %s",
                            len(readings),
                            range_start,
                            range_end,
                        )
                except SmartMeterFetchError as err:
                    msg = (
                        "Smart meter data is temporarily unavailable. "
                        "Please retry the export later."
                    )
                    raise HomeAssistantError(msg) from err
                except (RuntimeError, ValueError, TypeError) as err:
                    _LOGGER.warning(
                        "Failed to fetch readings for %s to %s: %s",
                        range_start,
                        range_end,
                        err,
                    )

                range_start = range_end + timedelta(days=1)

            if not all_readings:
                _raise_validation_error(
                    "No smart meter readings found for the specified period"
                )

            # Generate filename with improved default naming
            if not filename:
                if period == "month":
                    # Format: octopus_A-12FD99BC_2025_01.csv
                    filename = (
                        f"octopus_{account_number}_{year}_{month:02d}_"
                        f"{layout}_{resolution}"
                    )
                else:  # year
                    # Format: octopus_A-12FD99BC_2025.csv
                    filename = f"octopus_{account_number}_{year}_{layout}_{resolution}"

            # Ensure filename ends with .csv
            if not filename.endswith(".csv"):
                filename = f"{filename}.csv"

            # Save to /config directory
            output_path = Path(hass.config.path()) / filename

            # Create CSV writing function to run in executor
            def write_csv() -> None:
                """Write CSV file (to be run in executor to avoid blocking)."""
                with output_path.open("w", newline="", encoding="utf-8-sig") as csvfile:
                    writer = csv.writer(csvfile, delimiter=";")

                    slot_minutes = 15 if resolution == "15min" else 60
                    time_slots = [
                        f"{hour:02d}:{minute:02d}"
                        for hour in range(24)
                        for minute in range(0, 60, slot_minutes)
                    ]

                    # Prepare data structures
                    readings_by_time = {time_slot: {} for time_slot in time_slots}
                    readings_by_day = {}
                    daily_totals = {}

                    # Optional GO window parsing
                    go_start = None
                    go_end = None
                    if go_window_start and go_window_end:
                        try:
                            go_start = time.fromisoformat(go_window_start)
                            go_end = time.fromisoformat(go_window_end)
                        except ValueError:
                            _LOGGER.warning(
                                "Invalid GO window times provided: %s - %s",
                                go_window_start,
                                go_window_end,
                            )

                    for date_str, readings in all_readings.items():
                        date_obj = date.fromisoformat(date_str)
                        day_key = f"{date_obj.day:02d}.{date_obj.month:02d}"
                        readings_by_day.setdefault(day_key, {})
                        day_total = 0.0
                        day_go = 0.0

                        for reading in readings:
                            # Handle both V1 (startAt) and V2 (start_time) keys
                            start_at = (
                                reading.get("start_time")
                                or reading.get("startAt")
                                or reading.get("start_at")
                                or ""
                            )
                            if start_at:
                                try:
                                    reading_time = datetime.fromisoformat(start_at)
                                    minute = reading_time.minute
                                    rounded_minute = (
                                        minute // slot_minutes
                                    ) * slot_minutes
                                    time_key = (
                                        f"{reading_time.hour:02d}:{rounded_minute:02d}"
                                    )

                                    value = float(reading.get("value", 0))
                                    day_total += value

                                    # GO/Standard split if window provided
                                    if go_start and go_end:
                                        t = reading_time.time()
                                        if go_start <= go_end:
                                            in_go = go_start <= t < go_end
                                        else:
                                            # window crosses midnight
                                            in_go = t >= go_start or t < go_end
                                        if in_go:
                                            day_go += value

                                    if time_key in readings_by_time:
                                        readings_by_time[time_key][day_key] = (
                                            f"{value:.3f}".replace(".", ",")
                                        )
                                    readings_by_day[day_key][time_key] = (
                                        f"{value:.3f}".replace(".", ",")
                                    )
                                except (TypeError, ValueError) as err:
                                    _LOGGER.warning(
                                        "Failed to parse reading time %s: %s",
                                        start_at,
                                        err,
                                    )

                        daily_totals[day_key] = {
                            "total_kwh": round(day_total, 3),
                            "go_kwh": round(day_go, 3) if go_start and go_end else None,
                        }

                    if layout == "wide":
                        # Header with dates as columns
                        if period == "month":
                            _, last_day = monthrange(year, month)
                            header = ["Zeit"] + [
                                f"{day:02d}.{month:02d}"
                                for day in range(1, last_day + 1)
                            ]
                        else:  # year
                            header = ["Zeit"]
                            for m in range(1, 13):
                                _, last_day = monthrange(year, m)
                                for day in range(1, last_day + 1):
                                    header.append(f"{day:02d}.{m:02d}")

                        writer.writerow(header)
                        for time_slot in time_slots:
                            row = [time_slot]
                            for col in header[1:]:
                                value = readings_by_time[time_slot].get(col, "")
                                row.append(value)
                            writer.writerow(row)
                    else:
                        # Tall layout: dates as rows, times as columns
                        header = ["Datum", *time_slots]
                        writer.writerow(header)
                        for day_key in sorted(
                            readings_by_day.keys(),
                            key=lambda d: (
                                int(d.split(".")[1]),
                                int(d.split(".")[0]),
                            ),
                        ):
                            row = [day_key]
                            for ts in time_slots:
                                row.append(readings_by_day[day_key].get(ts, ""))
                            writer.writerow(row)

                    if add_summary:
                        writer.writerow([])
                        writer.writerow(["Summary"])
                        summary_header = ["Datum", "Total kWh"]
                        include_go = any(
                            v.get("go_kwh") is not None for v in daily_totals.values()
                        )
                        if include_go:
                            summary_header += ["GO kWh", "Standard kWh"]
                        writer.writerow(summary_header)
                        for day_key, totals in sorted(
                            daily_totals.items(),
                            key=lambda item: (
                                int(item[0].split(".")[1]),
                                int(item[0].split(".")[0]),
                            ),
                        ):
                            row = [
                                day_key,
                                f"{totals['total_kwh']:.3f}".replace(".", ","),
                            ]
                            if include_go:
                                go_val = totals.get("go_kwh") or 0.0
                                std_val = totals["total_kwh"] - go_val
                                row += [
                                    f"{go_val:.3f}".replace(".", ","),
                                    f"{std_val:.3f}".replace(".", ","),
                                ]
                            writer.writerow(row)

            # Run file writing in executor to avoid blocking the event loop
            await hass.async_add_executor_job(write_csv)

            result = {
                "success": True,
                "account_number": account_number,
                "property_id": property_id,
                "period": period,
                "start_date": start_date.isoformat(),
                "end_date": end_date.isoformat(),
                "total_days": total_days,
                "days_with_data": len(all_readings),
                "output_file": str(output_path),
                "measurement_metadata": _summarize_measurement_metadata(
                    [
                        reading
                        for daily_readings in all_readings.values()
                        for reading in daily_readings
                    ]
                ),
            }

            _LOGGER.info(
                "Successfully exported smart meter data to %s "
                "(%d days with data out of %d total days)",
                str(output_path),
                len(all_readings),
                total_days,
            )

            # Fire an event with the results
            hass.bus.async_fire(f"{DOMAIN}_csv_export_result", result)

            return result

        except HomeAssistantError, ServiceValidationError:
            raise
        except Exception as e:
            _LOGGER.exception("Error exporting smart meter data to CSV")
            msg = f"Error exporting smart meter data: {e}"
            raise HomeAssistantError(msg) from e

    async def handle_submit_meter_readings(call: ServiceCall) -> dict[str, Any]:
        """Handle the submit_meter_readings service call."""
        meter_type = _require_field(
            call.data.get(ATTR_METER_TYPE),
            "Meter type is required",
        )
        account_number = _require_field(
            call.data.get(ATTR_ACCOUNT_NUMBER),
            "Account number is required",
        )
        meter_id = _require_field(call.data.get(ATTR_METER_ID), "Meter ID is required")
        reading_date = _require_field(
            call.data.get(ATTR_READING_DATE),
            "Reading date is required",
        )
        readings_json = call.data.get(ATTR_READINGS_JSON)
        reading_value = call.data.get(ATTR_READING_VALUE)
        register_obis_code = call.data.get(ATTR_REGISTER_OBIS_CODE)

        _parse_iso_date(reading_date, "reading date")

        readings = None
        if readings_json:
            try:
                parsed_readings = json.loads(readings_json)
            except json.JSONDecodeError as json_error:
                _raise_validation_error(f"Invalid JSON for readings_json: {json_error}")

            if not isinstance(parsed_readings, list):
                _raise_validation_error("readings_json must be a JSON array")

            readings = parsed_readings
        elif reading_value is not None:
            if not register_obis_code:
                _raise_validation_error(
                    "register_obis_code is required when reading_value is used"
                )

            readings = [
                {
                    "value": reading_value,
                    "registerObisCode": register_obis_code,
                }
            ]
        else:
            _raise_validation_error(
                "Either readings_json or reading_value must be provided"
            )

        _LOGGER.info(
            "Submitting meter readings for meter_id=%s, meter_type=%s, "
            "reading_date=%s, reading_count=%d",
            meter_id,
            meter_type,
            reading_date,
            len(readings),
        )

        try:
            result = await api.submit_meter_readings(
                meter_type,
                meter_id,
                reading_date,
                readings,
                account_number,
            )

            if result:
                hass.bus.async_fire(
                    f"{DOMAIN}_meter_readings_submission_result", result
                )
                return result
        except ValueError as e:
            _LOGGER.exception("Validation error submitting meter readings")
            _raise_validation_error(f"Invalid parameters: {e}")
        except Exception as e:
            _LOGGER.exception("Unexpected error submitting meter readings")
            msg = f"Error submitting meter readings: {e}"
            raise HomeAssistantError(msg) from e

        _raise_validation_error(
            "Failed to submit meter readings. Check the log for details."
        )
        return {"success": False}

    _ = (entry, coordinator, intelligent_coordinator_getter)

    hass.services.async_register(
        DOMAIN,
        SERVICE_SET_DEVICE_PREFERENCES,
        handle_set_device_preferences,
    )

    hass.services.async_register(
        DOMAIN,
        SERVICE_GET_SMART_METER_READINGS,
        handle_get_smart_meter_readings,
        supports_response=SupportsResponse.ONLY,
    )

    hass.services.async_register(
        DOMAIN,
        SERVICE_EXPORT_SMART_METER_CSV,
        handle_export_smart_meter_csv,
        supports_response=SupportsResponse.ONLY,
    )

    hass.services.async_register(
        DOMAIN,
        SERVICE_SUBMIT_METER_READINGS,
        handle_submit_meter_readings,
        supports_response=SupportsResponse.ONLY,
    )
