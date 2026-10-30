"""Service handlers for Octopus Germany integration."""

from __future__ import annotations

import csv
import json
import logging
import re
from calendar import monthrange
from datetime import UTC, date, datetime, time, timedelta
from decimal import Decimal, InvalidOperation
from pathlib import Path
from tempfile import TemporaryDirectory
from typing import TYPE_CHECKING, Any
from zoneinfo import ZoneInfo

from homeassistant.core import HomeAssistant, ServiceCall, SupportsResponse
from homeassistant.exceptions import HomeAssistantError, ServiceValidationError
from homeassistant.helpers import device_registry as dr
from xlsxwriter.exceptions import XlsxWriterException

from .api.smart_meter import SmartMeterFetchError
from .const import DOMAIN
from .cost_report import (
    COST_REPORT_HEADERS,
    agreement_key,
    build_cost_report_basis_rows,
    build_daily_cost_report,
    build_monthly_cost_summaries,
    cost_report_headers,
    format_cost_report_value,
)
from .cost_report_export import (
    prepare_package_readings,
    write_cost_workbook,
    write_measurements_csv,
)
from .file_exports import (
    async_notify_export_package_ready,
    async_notify_export_ready,
    async_register_export_download_view,
    export_file_path,
)
from .grid_fee_schedule import (
    contract_start_basis_period,
    load_grid_fee_schedule,
)
from .services import async_request_intelligent_refresh
from .tariff import (
    normalize_variable_grid_fees,
    parse_product_datetime,
    parse_tariff_time,
)

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
_EAM_GRID_OPERATOR_CODE = "9900330000004"
_EAM_2025_MODULE3_VALID_FROM = "2025-04-01T00:00:00+02:00"
_EAM_2025_MODULE3_VALID_TO = "2026-01-01T00:00:00+01:00"
_EAM_2025_MODULE3_RATE_SIGNATURE = frozenset(
    {
        ("OFFPEAK", "23:00:00", "06:00:00", "1.99"),
        ("STANDARD", "06:00:00", "11:00:00", "6.64"),
        ("OFFPEAK", "11:00:00", "15:00:00", "1.99"),
        ("STANDARD", "15:00:00", "17:00:00", "6.64"),
        ("PEAK", "17:00:00", "22:00:00", "12.75"),
        ("STANDARD", "22:00:00", "23:00:00", "6.64"),
    }
)


def _decimal_service_value(value: Any, field_name: str) -> Decimal:
    """Parse a numeric service field as Decimal for billing calculations."""
    try:
        result = Decimal(str(value))
    except (InvalidOperation, TypeError, ValueError) as err:
        _raise_validation_error(f"{field_name} must be a number")
        raise ValueError(f"{field_name} must be a number") from err
    if not result.is_finite():
        _raise_validation_error(f"{field_name} must be finite")
    return result


def _is_negative_optional_decimal(value: Decimal | None) -> bool:
    return value is not None and value < 0


def _optional_service_date(value: Any, field_name: str) -> date | None:
    """Parse an optional date service field."""
    if value in (None, ""):
        return None
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    try:
        return date.fromisoformat(str(value))
    except ValueError as err:
        _raise_validation_error(f"{field_name} must use YYYY-MM-DD format")
        raise ValueError(f"Invalid {field_name}") from err


def _parse_manual_module3_rates(value: Any) -> list[dict[str, Any]]:
    """Parse user-provided Module 3 grid-fee windows from service JSON."""
    if value in (None, ""):
        return []
    try:
        entries = json.loads(value) if isinstance(value, str) else value
    except json.JSONDecodeError as err:
        _raise_validation_error(f"module3_rates_json is invalid JSON: {err}")
        raise ValueError("Invalid module3_rates_json") from err
    if not isinstance(entries, list):
        _raise_validation_error("module3_rates_json must be a JSON array")

    rates = []
    for index, entry in enumerate(entries):
        field_prefix = f"module3_rates_json[{index}]"
        if not isinstance(entry, dict):
            _raise_validation_error(f"{field_prefix} must be an object")
        rate_type = str(entry.get("rate_type") or "").upper()
        if rate_type not in {"OFFPEAK", "STANDARD", "PEAK"}:
            _raise_validation_error(
                f"{field_prefix}.rate_type must be OFFPEAK, STANDARD, or PEAK"
            )
        start_time = entry.get("start_time")
        end_time = entry.get("end_time")
        if not start_time or not end_time:
            _raise_validation_error(f"{field_prefix} requires start_time and end_time")
        if (
            parse_tariff_time(str(start_time)) is None
            or parse_tariff_time(str(end_time)) is None
        ):
            _raise_validation_error(
                f"{field_prefix} start_time/end_time must use HH:MM:SS"
            )
        cents = _decimal_service_value(
            entry.get("rate_cents_per_kwh"),
            f"{field_prefix}.rate_cents_per_kwh",
        )
        if cents < 0:
            _raise_validation_error(
                f"{field_prefix}.rate_cents_per_kwh cannot be negative"
            )
        valid_from = entry.get("valid_from")
        valid_to = entry.get("valid_to")
        parsed_from = parse_product_datetime(valid_from) if valid_from else None
        parsed_to = parse_product_datetime(valid_to) if valid_to else None
        if valid_from and parsed_from is None:
            _raise_validation_error(f"{field_prefix}.valid_from must be ISO date/time")
        if valid_to and parsed_to is None:
            _raise_validation_error(f"{field_prefix}.valid_to must be ISO date/time")
        if parsed_from and parsed_to and parsed_to <= parsed_from:
            _raise_validation_error(f"{field_prefix}.valid_to must follow valid_from")
        rates.append(
            {
                "rate_type": rate_type,
                "start_time": str(start_time),
                "end_time": str(end_time),
                "valid_from": valid_from,
                "valid_to": valid_to,
                "rate_cents_per_kwh": str(cents),
                "rate_eur_per_kwh": cents / Decimal(100),
                "module": "MODULE_3",
            }
        )
    return rates


def _is_eam_2025_module3_prefill(rates: list[dict[str, Any]]) -> bool:
    """Recognize the service form's prefilled EAM sample, not arbitrary rates."""
    if len(rates) != len(_EAM_2025_MODULE3_RATE_SIGNATURE):
        return False
    signature = {
        (
            rate["rate_type"],
            rate["start_time"],
            rate["end_time"],
            format(Decimal(rate["rate_cents_per_kwh"]), "f"),
        )
        for rate in rates
    }
    return signature == _EAM_2025_MODULE3_RATE_SIGNATURE


def _raise_validation_error(msg: str) -> None:
    """Raise a service validation error with integration translation metadata."""
    raise ServiceValidationError(msg, translation_domain=DOMAIN)


def _require_field(value: Any, msg: str) -> Any:
    """Require that a service field is provided."""
    if value:
        return value
    _raise_validation_error(msg)
    raise ValueError(msg)


def _resolve_octopus_device_id(hass: HomeAssistant, device_id: str) -> str:
    """Resolve a Home Assistant device selector ID to the Octopus device ID."""
    try:
        device = dr.async_get(hass).devices.get(device_id)
    except RuntimeError:
        return device_id

    if device is None:
        return device_id

    for domain, identifier in device.identifiers:
        prefix = "device_"
        if domain == DOMAIN and identifier.startswith(prefix):
            return identifier.removeprefix(prefix)

    _raise_validation_error(
        "Selected Home Assistant device is not an Octopus SmartFlex device"
    )
    raise ValueError(
        "Selected Home Assistant device is not an Octopus SmartFlex device"
    )


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


async def _fetch_grid_fee_schedules(
    client: Any,
    account_number: str,
    grid_operator_code: str | None,
    grid_operator_name: str | None,
    start_date: date,
    end_date: date,
    timezone: str,
) -> dict[str, Any]:
    """Fetch fee schedules for a date range, following API validity changes."""
    fee_data: dict[str, Any] = {
        "module": None,
        "grid_operator_code": grid_operator_code,
        "grid_operator_name": grid_operator_name,
        "rates": [],
    }
    if not grid_operator_code:
        return fee_data

    fee_query_date = start_date
    while fee_query_date <= end_date:
        raw_fees = await client.fetch_variable_grid_fees(
            account_number, grid_operator_code, fee_query_date
        )
        segment = normalize_variable_grid_fees(raw_fees, grid_operator_name)
        if segment is None:
            break
        if not fee_data["rates"]:
            fee_data["module"] = segment.get("module")
        fee_data["rates"].extend(segment.get("rates") or [])
        valid_ends = [
            parse_product_datetime(rate.get("valid_to"))
            for rate in segment.get("rates") or []
        ]
        valid_ends = [
            valid_end
            for valid_end in valid_ends
            if valid_end is not None
            and valid_end.astimezone(ZoneInfo(timezone)).date() > fee_query_date
        ]
        if not valid_ends:
            break
        next_date = min(valid_ends).astimezone(ZoneInfo(timezone)).date()
        if next_date <= fee_query_date or next_date > end_date:
            break
        fee_query_date = next_date
    return fee_data


# Service schemas
SERVICE_SET_DEVICE_PREFERENCES = "set_device_preferences"
SERVICE_GET_SMART_METER_READINGS = "get_smart_meter_readings"
SERVICE_EXPORT_SMART_METER_CSV = "export_smart_meter_csv"
SERVICE_EXPORT_COST_REPORT = "export_cost_report"
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
ATTR_CONTRACT_START_NETWORK_CHARGE = "contract_start_network_charge_ct_kwh"
ATTR_MODULE3_START_DATE = "module3_start_date"
ATTR_MODULE3_RATES_JSON = "module3_rates_json"
ATTR_MODULE1_START_DATE = "module1_start_date"
ATTR_MODULE1_ANNUAL_CREDIT = "module1_annual_credit_net_eur"
ATTR_VAT_PERCENT = "vat_percent"
ATTR_MODULE3_ENABLED = "module3_enabled"


async def _resolve_contract_start_baselines(  # noqa: PLR0913
    hass: HomeAssistant,
    products: list[dict[str, Any]],
    baseline: Decimal | None,
    schedule_path: Path,
    grid_operator_code: str | None,
    timezone: str,
    report_year: int,
    report_schedule: dict[str, Any] | None,
) -> tuple[
    dict[tuple[str, str], Decimal | None],
    list[dict[str, Any]],
    list[dict[str, Any]],
    list[str],
]:
    """Resolve each agreement's baseline from its start-year schedule."""
    schedule_by_year: dict[int, dict[str, Any] | None] = {report_year: report_schedule}
    contract_baselines: dict[tuple[str, str], Decimal | None] = {}
    details: list[dict[str, Any]] = []
    warnings = []
    if baseline is not None:
        for product in products:
            start = parse_product_datetime(product.get("validFrom"))
            details.append(
                {
                    "agreement": product.get("name")
                    or product.get("code")
                    or "Unknown",
                    "validFrom": product.get("validFrom"),
                    "contract_start_date": (
                        start.astimezone(ZoneInfo(timezone)).date()
                        if start is not None
                        else None
                    ),
                    "value": baseline,
                    "source": "service input",
                }
            )
    else:
        for product in products:
            key = agreement_key(product)
            start = parse_product_datetime(product.get("validFrom"))
            detail: dict[str, Any] = {
                "agreement": product.get("name") or product.get("code") or "Unknown",
                "validFrom": product.get("validFrom"),
                "contract_start_date": None,
                "value": None,
                "source": "missing",
            }
            if start is not None:
                contract_start_date = start.astimezone(ZoneInfo(timezone)).date()
                contract_year = contract_start_date.year
                detail["contract_start_date"] = contract_start_date
                schedule = schedule_by_year.get(contract_year)
                if contract_year not in schedule_by_year:
                    schedule = None
                    if await hass.async_add_executor_job(schedule_path.is_file):
                        try:
                            schedule = await hass.async_add_executor_job(
                                load_grid_fee_schedule,
                                schedule_path,
                                grid_operator_code,
                                contract_year,
                                timezone,
                            )
                        except (OSError, json.JSONDecodeError, ValueError) as err:
                            warnings.append(
                                "The contract-start grid-fee schedule for "
                                f"{contract_year} could not be used: {err}. "
                                "Enter contract_start_network_charge_ct_kwh manually "
                                "or correct "
                                "/config/octopus_germany/grid_fee_schedules.json."
                            )
                    schedule_by_year[contract_year] = schedule
                detail["schedule_year"] = contract_year
                if schedule is not None:
                    try:
                        period_data = contract_start_basis_period(
                            schedule, contract_start_date
                        )
                    except ValueError as err:
                        period_data = None
                        warnings.append(
                            f"Contract-start net fee for {detail['agreement']} is not "
                            f"unique: {err}. Enter "
                            "contract_start_network_charge_ct_kwh manually."
                        )
                    if period_data is not None:
                        value = period_data["basis_rate_net_ct_per_kwh"]
                        contract_baselines[key] = value
                        detail.update(
                            {
                                "value": value,
                                "source": str(schedule_path),
                                "valid_from": period_data.get("valid_from"),
                                "valid_to": period_data.get("valid_to"),
                            }
                        )
            if key not in contract_baselines:
                contract_baselines[key] = None
                if detail["source"] == "missing":
                    contract_start_label = (
                        detail["contract_start_date"] or "unknown contract start"
                    )
                    warnings.append(
                        "No unique contract-start basis net fee was found for "
                        f"{detail['agreement']} at {contract_start_label} "
                        "in /config/octopus_germany/grid_fee_schedules.json. "
                        "Enter contract_start_network_charge_ct_kwh manually; "
                        "affected calculations will be incomplete."
                    )
            details.append(detail)

    schedule_period_rows = [
        {
            "year": schedule_year,
            "valid_from": period.get("valid_from"),
            "valid_to": period.get("valid_to"),
            "basis_rate_net_ct_per_kwh": period.get("basis_rate_net_ct_per_kwh"),
        }
        for schedule_year, schedule in sorted(schedule_by_year.items())
        if schedule is not None
        for period in schedule.get("schedules", [])
    ]
    return contract_baselines, details, schedule_period_rows, warnings


async def async_register_services(
    hass: HomeAssistant,
    entry: ConfigEntry,
    api: Any,
    coordinator: OctopusDataCoordinator,
    intelligent_coordinator_getter: Callable[[], OctopusDataCoordinator] | None,
) -> None:
    """Register integration services with unchanged behavior."""
    await async_register_export_download_view(hass)

    async def handle_set_device_preferences(call: ServiceCall) -> dict[str, bool]:
        """Handle the set_device_preferences service call."""
        device_id = _resolve_octopus_device_id(
            hass,
            _require_field(call.data.get(ATTR_DEVICE_ID), "Device ID is required"),
        )
        target_percentage = _require_field(
            call.data.get(ATTR_TARGET_PERCENTAGE), "Target percentage is required"
        )
        target_time = _require_field(
            call.data.get(ATTR_TARGET_TIME), "Target time is required"
        )
        try:
            target_percentage = int(target_percentage)
            if (
                target_percentage < _TARGET_PERCENT_MIN
                or target_percentage > _TARGET_PERCENT_MAX
                or target_percentage % _TARGET_PERCENT_STEP
            ):
                _raise_validation_error("Target percentage must be 20-100 in 5% steps")
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
                        "Smart meter data is temporarily unavailable for "
                        f"{range_start.isoformat()} to {range_end.isoformat()} "
                        f"at {resolution} resolution: {err}"
                    )
                    _LOGGER.exception("%s", msg)
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

            output_path = export_file_path(hass, filename)
            filename = output_path.name

            # Create CSV writing function to run in executor
            def write_csv() -> None:
                """Write CSV file (to be run in executor to avoid blocking)."""
                output_path.parent.mkdir(parents=True, exist_ok=True)
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

            download_url = await async_notify_export_ready(
                hass, output_path.name, "Smart meter CSV export"
            )
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
                "download_url": download_url,
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

    async def handle_export_cost_report(call: ServiceCall) -> dict[str, Any]:
        """Create a cost CSV or a measurement CSV and offline XLSX package."""
        account_number = _require_field(
            call.data.get(ATTR_ACCOUNT_NUMBER), "Account number is required"
        )
        period = call.data.get(ATTR_PERIOD, _DEFAULT_PERIOD)
        year = int(_require_field(call.data.get(ATTR_YEAR), "Year is required"))
        month_value = call.data.get(ATTR_MONTH)
        property_id = call.data.get(ATTR_PROPERTY_ID)
        filename = call.data.get(ATTR_FILENAME)
        export_format = call.data.get("format", "csv")
        comparison = call.data.get("network_comparison", "contract_start")
        if export_format not in {"csv", "package"}:
            _raise_validation_error("format must be csv or package")
        if comparison not in {"contract_start", "current_year"}:
            _raise_validation_error(
                "network_comparison must be contract_start or current_year"
            )
        current_network_input = call.data.get("standard_network_charge_ct_kwh")
        current_network = (
            _decimal_service_value(
                current_network_input, "standard_network_charge_ct_kwh"
            )
            if current_network_input not in (None, "")
            else None
        )
        if current_network is not None and current_network < 0:
            _raise_validation_error(
                "standard_network_charge_ct_kwh must be non-negative"
            )
        if (
            export_format == "package"
            and comparison == "current_year"
            and current_network is None
        ):
            _raise_validation_error(
                "standard_network_charge_ct_kwh is required for current_year; "
                "the Module 3 ST rate is not the normal annual grid fee"
            )
        if period not in {"month", "year"}:
            _raise_validation_error("Period must be month or year")
        if period == "month" and month_value is None:
            _raise_validation_error("Month is required for a monthly cost report")
        if month_value is not None and not _MIN_MONTH <= int(month_value) <= _MAX_MONTH:
            _raise_validation_error("Month must be between 1 and 12")

        baseline_input = call.data.get(ATTR_CONTRACT_START_NETWORK_CHARGE)
        baseline = (
            _decimal_service_value(baseline_input, ATTR_CONTRACT_START_NETWORK_CHARGE)
            if baseline_input not in (None, "")
            else None
        )
        module3_start = _optional_service_date(
            call.data.get(ATTR_MODULE3_START_DATE), ATTR_MODULE3_START_DATE
        )
        manual_module3_rates = _parse_manual_module3_rates(
            call.data.get(ATTR_MODULE3_RATES_JSON)
        )
        eam_2025_prefill = _is_eam_2025_module3_prefill(manual_module3_rates)
        has_manual_module3_rates = bool(manual_module3_rates)
        module1_start = _optional_service_date(
            call.data.get(ATTR_MODULE1_START_DATE), ATTR_MODULE1_START_DATE
        )
        module1_annual_input = call.data.get(ATTR_MODULE1_ANNUAL_CREDIT)
        vat_percent = _decimal_service_value(
            call.data.get(ATTR_VAT_PERCENT, 19), ATTR_VAT_PERCENT
        )
        if _is_negative_optional_decimal(baseline) or not 0 <= vat_percent <= 100:
            _raise_validation_error(
                "Network baseline and Module 1 must be non-negative; VAT must be 0-100"
            )
        vat_fraction = vat_percent / 100
        account_coordinator, client = _resolve_account_context(hass, account_number)
        account_data = account_coordinator.data[account_number]
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

        timezone = hass.config.time_zone
        local_today = datetime.now(ZoneInfo(timezone)).date()
        latest_available_day = local_today - timedelta(days=2)
        if period == "month":
            start_date = date(year, int(month_value), 1)
            end_date = date(
                year, int(month_value), monthrange(year, int(month_value))[1]
            )
        else:
            start_date = date(year, 1, 1)
            end_date = date(year, 12, 31)
        if end_date < start_date:
            _raise_validation_error(
                "No readings should be available for the selected period yet"
            )
        if year == local_today.year:
            end_date = min(end_date, latest_available_day)
        if end_date < start_date:
            _raise_validation_error("The selected period has no available dates yet")

        products = account_data.get("products") or []
        grid_operator_code = account_data.get("grid_operator_code")
        grid_operator_name = account_data.get("grid_operator_name")
        preset_warnings = []
        if eam_2025_prefill and grid_operator_code != _EAM_GRID_OPERATOR_CODE:
            manual_module3_rates = []
            if module3_start is not None:
                preset_warnings.append(
                    "The prefilled 2025 sample Module 3 rates were not applied because "
                    "the detected network operator is "
                    f"{grid_operator_name or grid_operator_code or 'unknown'}, "
                    "not the operator for those example rates. Enter this operator's "
                    "rates in "
                    "module3_rates_json."
                )
        schedule_path = Path(
            hass.config.path("octopus_germany/grid_fee_schedules.json")
        )
        user_schedule = None
        schedule_error = False
        schedule_file_status = "missing"
        if await hass.async_add_executor_job(schedule_path.is_file):
            try:
                user_schedule = await hass.async_add_executor_job(
                    load_grid_fee_schedule,
                    schedule_path,
                    grid_operator_code,
                    year,
                    timezone,
                )
            except (OSError, json.JSONDecodeError, ValueError) as err:
                schedule_error = True
                schedule_file_status = "invalid"
                preset_warnings.append(
                    "The user grid-fee schedule file could not be used: "
                    f"{err}. Check /config/octopus_germany/grid_fee_schedules.json."
                )
            if user_schedule is None and not schedule_error:
                schedule_file_status = "unmatched"
                preset_warnings.append(
                    "No user grid-fee schedule matches the detected network-operator "
                    "code and report year "
                    f"({grid_operator_code or 'unknown'}, {year}). "
                    "Add that operator and year to "
                    "/config/octopus_germany/grid_fee_schedules.json if needed."
                )
            else:
                if user_schedule is not None:
                    schedule_file_status = "matched"
                    if eam_2025_prefill:
                        manual_module3_rates = list(user_schedule["rates"])
                    else:
                        manual_module3_rates.extend(user_schedule["rates"])
                if (
                    user_schedule is not None
                    and user_schedule.get("status") == "provisional"
                ):
                    preset_warnings.append(
                        f"The {year} user grid-fee schedule is marked provisional; "
                        "verify its final published rates before relying on the report."
                    )
        else:
            preset_warnings.append(
                "No user grid-fee schedule file was found at "
                "/config/octopus_germany/grid_fee_schedules.json. If you need "
                "operator-specific hourly or historical rates, create it from "
                "docs/examples/grid_fee_schedules.example.json."
            )

        (
            contract_start_baselines,
            contract_start_details,
            schedule_period_rows,
            baseline_warnings,
        ) = await _resolve_contract_start_baselines(
            hass,
            products,
            baseline,
            schedule_path,
            grid_operator_code,
            timezone,
            year,
            user_schedule,
        )
        preset_warnings.extend(baseline_warnings)
        if user_schedule is not None:
            if module1_start is None:
                module1_start = user_schedule.get("module1_start_date")
            if module3_start is None:
                module3_start = user_schedule.get("module3_start_date")
        if has_manual_module3_rates and module3_start is None and not eam_2025_prefill:
            _raise_validation_error(
                "module3_start_date is required when manual Module 3 rates are entered"
            )
        if module1_annual_input in (None, ""):
            schedule_module1_credit = (
                user_schedule.get("module1_credit_net_eur")
                if user_schedule is not None
                else None
            )
            module1_annual = schedule_module1_credit
            if module1_start is not None and schedule_module1_credit is None:
                preset_warnings.append(
                    "No Module 1 annual credit was entered or found in the matching "
                    "schedule file; no credit is applied. Verify the credit or "
                    "enter it in module1_annual_credit_net_eur."
                )
        else:
            module1_annual = _decimal_service_value(
                module1_annual_input, ATTR_MODULE1_ANNUAL_CREDIT
            )
        if module1_annual is not None and module1_annual < 0:
            _raise_validation_error("Module 1 must be non-negative")
        readings_by_date: dict[str, list[dict[str, Any]]] = {}
        grid_fees_by_month: dict[tuple[int, int], dict[str, Any] | None] = {}
        range_start = start_date
        while range_start <= end_date:
            range_end = min(
                date(
                    range_start.year,
                    range_start.month,
                    monthrange(range_start.year, range_start.month)[1],
                ),
                end_date,
            )
            fee_data = await _fetch_grid_fee_schedules(
                client,
                account_number,
                grid_operator_code,
                grid_operator_name,
                range_start,
                range_end,
                timezone,
            )
            grid_fees_by_month[(range_start.year, range_start.month)] = fee_data

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
                    "15min",
                )
            except SmartMeterFetchError as err:
                msg = (
                    "Unable to fetch cost-report readings "
                    f"{range_start} to {range_end}: {err}"
                )
                _LOGGER.exception("%s", msg)
                raise HomeAssistantError(msg) from err
            readings_by_date.update(_group_readings_by_local_date(readings, timezone))
            range_start = range_end + timedelta(days=1)

        if (
            user_schedule is not None
            and module3_start is None
            and not any(
                str(fee_data.get("module") or "").upper() == "MODULE_3"
                for fee_data in grid_fees_by_month.values()
                if fee_data
            )
        ):
            preset_warnings.append(
                "The matching file schedule was found, but Module 3 has no selected "
                "effective date and the API does not report MODULE_3. Set "
                "module3_start_date after confirming the declared effective date; "
                "the file's hourly rates were not used."
            )

        if not readings_by_date:
            _raise_validation_error(
                "No smart meter readings found for the selected period"
            )

        interval_details: list[dict[str, Any]] = []
        reading_issues: dict[str, str] = {}
        if export_format == "package":
            readings_by_date, reading_issues = prepare_package_readings(
                readings_by_date, start_date, end_date, timezone
            )
        report_rows = build_daily_cost_report(
            readings_by_date=readings_by_date,
            products=products,
            grid_fees_by_month=grid_fees_by_month,
            start_date=start_date,
            end_date=end_date,
            timezone=timezone,
            contract_start_network_charge_ct_kwh=baseline,
            module1_start_date=module1_start,
            module1_annual_net_eur=module1_annual,
            fallback_vat_fraction=vat_fraction,
            module3_start_date=module3_start,
            manual_module3_rates=manual_module3_rates,
            interval_details=interval_details if export_format == "package" else None,
            normal_network_charge_ct_kwh=(
                current_network if export_format == "package" else None
            ),
            strict_standard_grid_fee=export_format == "package",
            contract_start_baselines=contract_start_baselines,
        )
        if export_format == "package":
            priced_instants = {
                item["start"]
                for item in interval_details
                if item["network_rate"] is not None
                and item["contract_start_network_charge_ct_kwh"] is not None
            }
            for row in report_rows:
                day = row["date"]
                if day in reading_issues:
                    row["status"] = f"incomplete: {reading_issues[day]}"
                elif row["status"] == "complete" and any(
                    datetime.fromisoformat(reading["start_time"]) not in priced_instants
                    for reading in readings_by_date[day]
                ):
                    row["status"] = "incomplete: interval price missing"
                if row["status"] != "complete":
                    row["total_before_module1_gross_eur"] = None
                    row["total_after_module1_gross_eur"] = None
        monthly_summaries = build_monthly_cost_summaries(report_rows)
        csv_rows = [*report_rows, *monthly_summaries]
        basis_rows = build_cost_report_basis_rows(
            products=products,
            grid_fees_by_month=grid_fees_by_month,
            contract_start_network_charge_ct_kwh=baseline,
            module3_start_date=module3_start,
            manual_module3_rates=manual_module3_rates,
            module1_start_date=module1_start,
            module1_annual_net_eur=module1_annual,
            vat_percent=vat_percent,
        )
        basis_rows.append(
            {
                "record_type": "BASIS",
                "date": "BASIS",
                "basis_key": "contract_start_baseline_resolution",
                "basis_value": json.dumps(
                    contract_start_details,
                    ensure_ascii=False,
                    separators=(",", ":"),
                    default=str,
                ),
            }
        )
        if export_format == "package":
            basis_rows.append(
                {
                    "record_type": "BASIS",
                    "date": "BASIS",
                    "basis_key": "export_package",
                    "basis_value": json.dumps(
                        {
                            "network_comparison": comparison,
                            "standard_network_charge_net_ct_per_kwh": (
                                str(current_network)
                                if current_network is not None
                                else None
                            ),
                            "measurement_timezone": timezone,
                            "intervals": (
                                "15min; local days may contain 92, 96 or 100 slots"
                            ),
                        },
                    ),
                }
            )
        if user_schedule is not None:
            basis_rows.append(
                {
                    "record_type": "BASIS",
                    "date": "BASIS",
                    "basis_key": "user_grid_fee_schedule",
                    "basis_value": json.dumps(
                        {
                            "file": str(schedule_path),
                            "grid_operator_code": user_schedule["grid_operator_code"],
                            "year": user_schedule["year"],
                            "status": user_schedule.get("status"),
                            "source_note": user_schedule.get("source_note"),
                            "module1_credit_net_eur": user_schedule.get(
                                "module1_credit_net_eur"
                            ),
                            "module1_start_date": user_schedule.get(
                                "module1_start_date"
                            ),
                            "module3_start_date": user_schedule.get(
                                "module3_start_date"
                            ),
                            "schedules": user_schedule.get("schedules"),
                        },
                        ensure_ascii=False,
                        separators=(",", ":"),
                        default=str,
                    ),
                }
            )
        module1_fallback_days = sum(
            "API STANDARD grid fee fallback" in str(row.get("module3_rate_basis") or "")
            for row in report_rows
        )
        unavailable_module3_days = sum(
            "Module 3 rate unavailable" in str(row.get("module3_rate_basis") or "")
            for row in report_rows
        )
        warnings = list(preset_warnings)
        if reading_issues:
            warnings.append(
                f"{len(reading_issues)} day(s) have missing, duplicate or invalid "
                "quarter-hour readings; inspect the exported statuses."
            )
        if export_format == "package" and any(
            "Normal grid fee unavailable" in str(row.get("module3_rate_basis"))
            for row in report_rows
        ):
            warnings.append(
                "The variable Module 3 ST band is not a normal annual grid fee. "
                "Supply standard_network_charge_ct_kwh for periods before Module 3; "
                "those interval costs remain incomplete."
            )
        if module1_fallback_days:
            warnings.append(
                f"Module 3 rates were unavailable for {module1_fallback_days} day(s); "
                "the API STANDARD grid fee was used. Supply module3_rates_json "
                "to calculate those periods from manually entered rates."
            )
        if unavailable_module3_days:
            warnings.append(
                f"No API, manual, or STANDARD grid-fee rate was available for "
                f"{unavailable_module3_days} day(s); those costs are incomplete."
            )
        safe_filename = re.sub(r"[^A-Za-z0-9_.-]+", "_", str(filename or "")).strip(
            "._"
        )
        if not safe_filename:
            period_label = (
                f"{year}_{int(month_value):02d}" if period == "month" else f"{year}"
            )
            safe_filename = f"octopus_cost_report_{account_number}_{period_label}"
        if export_format == "package" and safe_filename.lower().endswith(".xlsx"):
            safe_filename = safe_filename[:-5]
        if not safe_filename.lower().endswith(".csv"):
            safe_filename += ".csv"
        output_path = export_file_path(hass, safe_filename)
        safe_filename = output_path.name

        def write_cost_csv(target: Path = output_path) -> None:
            headers = cost_report_headers([*csv_rows, *basis_rows])
            output_path.parent.mkdir(parents=True, exist_ok=True)
            with target.open("w", newline="", encoding="utf-8-sig") as csvfile:
                writer = csv.DictWriter(
                    csvfile,
                    fieldnames=headers,
                    delimiter=";",
                    extrasaction="ignore",
                )
                writer.writeheader()
                for row in csv_rows:
                    writer.writerow(
                        {
                            key: format_cost_report_value(key, value)
                            for key, value in row.items()
                        }
                    )
                totals: dict[str, Any] = {
                    "record_type": "TOTAL",
                    "date": "TOTAL",
                    "tariff_agreement": "Selected period",
                }
                incomplete_days = sum(
                    row["status"] != "complete" for row in report_rows
                )
                period_is_complete = incomplete_days == 0
                for key in headers:
                    if (
                        key.endswith("_kwh") or key.endswith("_eur")
                    ) and not key.endswith("_per_kwh"):
                        totals[key] = sum(
                            (
                                row.get(key, Decimal(0)) or Decimal(0)
                                for row in report_rows
                            ),
                            Decimal(0),
                        )
                totals["monthly_total_gross_eur"] = (
                    sum(
                        (row["total_after_module1_gross_eur"] for row in report_rows),
                        Decimal(0),
                    )
                    if period_is_complete
                    else None
                )
                if not period_is_complete:
                    totals["total_before_module1_gross_eur"] = None
                    totals["total_after_module1_gross_eur"] = None
                totals["status"] = (
                    f"{incomplete_days} incomplete day(s); inspect daily rows"
                )
                writer.writerow(
                    {
                        key: format_cost_report_value(key, value)
                        for key, value in totals.items()
                    }
                )
                for row in basis_rows:
                    writer.writerow(row)

        description = "Electricity cost report" + (
            f". Warning: {' '.join(warnings)}" if warnings else ""
        )
        package_files: list[dict[str, str]] = []
        if export_format == "package":
            measurement_path = export_file_path(
                hass, f"{output_path.stem}_measurements_15min.csv"
            )
            workbook_path = export_file_path(hass, f"{output_path.stem}.xlsx")

            def write_package() -> None:
                output_path.parent.mkdir(parents=True, exist_ok=True)
                with TemporaryDirectory(dir=output_path.parent) as directory:
                    staging = Path(directory)
                    write_measurements_csv(
                        staging / measurement_path.name,
                        readings_by_date,
                        timezone,
                        reading_issues,
                    )
                    write_cost_workbook(
                        staging / workbook_path.name,
                        readings_by_date,
                        interval_details,
                        report_rows,
                        basis_rows,
                        timezone,
                        baseline,
                        module1_annual,
                        module1_start,
                        vat_fraction,
                        comparison,
                        current_network,
                        warnings,
                        contract_start_details,
                        schedule_period_rows,
                    )
                    for target in (measurement_path, workbook_path):
                        (staging / target.name).replace(target)

            try:
                await hass.async_add_executor_job(write_package)
            except (OSError, ValueError, XlsxWriterException) as err:
                _LOGGER.exception("Unable to create electricity export package")
                msg = "Unable to create electricity export package; check the log"
                raise HomeAssistantError(msg) from err
            urls = await async_notify_export_package_ready(
                hass,
                [workbook_path.name, measurement_path.name],
                description,
            )
            download_url = urls[workbook_path.name]
            package_files = [
                {
                    "type": kind,
                    "output_file": str(path),
                    "download_url": urls[path.name],
                }
                for kind, path in (
                    ("xlsx", workbook_path),
                    ("measurements_csv", measurement_path),
                )
            ]
            output_path = workbook_path
        else:
            await hass.async_add_executor_job(write_cost_csv)
            download_url = await async_notify_export_ready(
                hass, output_path.name, description
            )
        result = {
            "success": True,
            "account_number": account_number,
            "property_id": property_id,
            "period": period,
            "start_date": start_date.isoformat(),
            "end_date": end_date.isoformat(),
            "days": len(report_rows),
            "incomplete_days": sum(row["status"] != "complete" for row in report_rows),
            "output_file": str(output_path),
            "download_url": download_url,
            "warnings": warnings,
            "grid_fee_schedule_file": str(schedule_path),
            "grid_fee_schedule_file_status": schedule_file_status,
        }
        if export_format == "package":
            result["files"] = package_files
            result["format"] = export_format
        hass.bus.async_fire(f"{DOMAIN}_cost_report_result", result)
        return result

    async def _handle_export_cost_report_legacy(call: ServiceCall) -> dict[str, Any]:
        """Legacy cost-report implementation retained temporarily for compatibility."""
        account_number = _require_field(
            call.data.get(ATTR_ACCOUNT_NUMBER), "Account number is required"
        )
        period = call.data.get(ATTR_PERIOD, _DEFAULT_PERIOD)
        year = int(_require_field(call.data.get(ATTR_YEAR), "Year is required"))
        month = call.data.get(ATTR_MONTH)
        property_id = call.data.get(ATTR_PROPERTY_ID)
        filename = call.data.get(ATTR_FILENAME)

        if period not in {"month", "year"}:
            _raise_validation_error("Period must be month or year")
        if period == "month" and month is None:
            _raise_validation_error("Month is required for monthly cost report")
        if month is not None and not _MIN_MONTH <= int(month) <= _MAX_MONTH:
            _raise_validation_error("Month must be between 1 and 12")

        baseline = _decimal_service_value(
            call.data.get(ATTR_CONTRACT_START_NETWORK_CHARGE),
            ATTR_CONTRACT_START_NETWORK_CHARGE,
        )
        module3_start = _optional_service_date(
            call.data.get(ATTR_MODULE3_START_DATE), ATTR_MODULE3_START_DATE
        )
        module1_start = _optional_service_date(
            call.data.get(ATTR_MODULE1_START_DATE), ATTR_MODULE1_START_DATE
        )
        module1_annual = _decimal_service_value(
            call.data.get(ATTR_MODULE1_ANNUAL_CREDIT, 0),
            ATTR_MODULE1_ANNUAL_CREDIT,
        )
        vat_percent = _decimal_service_value(
            call.data.get(ATTR_VAT_PERCENT, 19), ATTR_VAT_PERCENT
        )
        if baseline < 0 or module1_annual < 0 or not 0 <= vat_percent <= 100:
            _raise_validation_error(
                "Baseline/Module 1 must be non-negative; VAT must be 0-100"
            )
        vat_fraction = vat_percent / 100

        go_start = time.fromisoformat(
            _normalize_target_time(call.data.get(ATTR_GO_WINDOW_START, "00:00"))
        )
        go_end = time.fromisoformat(
            _normalize_target_time(call.data.get(ATTR_GO_WINDOW_END, "05:00"))
        )
        if go_start == go_end:
            _raise_validation_error("GO window start and end must differ")

        account_coordinator, client = _resolve_account_context(hass, account_number)
        account_data = account_coordinator.data[account_number]
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

        timezone = hass.config.time_zone
        if period == "month":
            start_date = date(year, int(month), 1)
            end_date = date(year, int(month), monthrange(year, int(month))[1])
            month_starts = [start_date]
        else:
            start_date = date(year, 1, 1)
            end_date = date(year, 12, 31)
            month_starts = [date(year, m, 1) for m in range(1, 13)]

        readings_by_date: dict[str, list[dict[str, Any]]] = {}
        grid_fees_by_month = {}
        grid_operator_code = account_data.get("grid_operator_code")
        grid_operator_name = account_data.get("grid_operator_name")
        for range_start in month_starts:
            if range_start > end_date:
                continue
            range_end = min(
                date(
                    range_start.year,
                    range_start.month,
                    monthrange(range_start.year, range_start.month)[1],
                ),
                end_date,
            )
            fee_data = None
            if grid_operator_code:
                raw_fees = await client.fetch_variable_grid_fees(
                    account_number, grid_operator_code, range_start
                )
                fee_data = normalize_variable_grid_fees(raw_fees, grid_operator_name)
            grid_fees_by_month[(range_start.year, range_start.month)] = fee_data

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
                    "15min",
                )
            except SmartMeterFetchError as err:
                msg = (
                    f"Unable to fetch readings for cost report {range_start} to "
                    f"{range_end}: {err}"
                )
                _LOGGER.exception("%s", msg)
                raise HomeAssistantError(msg) from err
            for local_date, day_readings in _group_readings_by_local_date(
                readings, timezone
            ).items():
                readings_by_date[local_date] = day_readings

        if not readings_by_date:
            _raise_validation_error(
                "No smart meter readings found for the selected period"
            )

        report_rows = build_daily_cost_report(
            readings_by_date=readings_by_date,
            products=account_data.get("products") or [],
            grid_fees_by_month=grid_fees_by_month,
            start_date=start_date,
            end_date=end_date,
            timezone=timezone,
            contract_start_network_charge_ct_kwh=baseline,
            module3_start_date=module3_start,
            module1_start_date=module1_start,
            module1_annual_net_eur=module1_annual,
            fallback_vat_fraction=vat_fraction,
            go_start=go_start,
            go_end=go_end,
        )
        safe_name = re.sub(r"[^A-Za-z0-9_.-]+", "_", str(filename or "")).strip("._")
        if not safe_name:
            suffix = f"{year}_{int(month):02d}" if period == "month" else str(year)
            safe_name = f"octopus_cost_{account_number}_{suffix}"
        if not safe_name.lower().endswith(".csv"):
            safe_name += ".csv"
        output_path = Path(hass.config.path()) / safe_name

        def write_cost_report() -> None:
            with output_path.open("w", newline="", encoding="utf-8-sig") as csvfile:
                writer = csv.DictWriter(
                    csvfile,
                    fieldnames=COST_REPORT_HEADERS,
                    delimiter=";",
                    extrasaction="ignore",
                )
                writer.writeheader()
                for row in report_rows:
                    writer.writerow(
                        {
                            key: format(value, "f")
                            if isinstance(value, Decimal)
                            else value
                            for key, value in row.items()
                        }
                    )
                writer.writerow({})
                writer.writerow(
                    {
                        "date": "TOTAL",
                        "total_kwh": format(
                            sum((row["total_kwh"] for row in report_rows), Decimal(0)),
                            "f",
                        ),
                        "total_before_module1_gross_eur": format(
                            sum(
                                (
                                    row["total_before_module1_gross_eur"]
                                    for row in report_rows
                                ),
                                Decimal(0),
                            ),
                            "f",
                        ),
                        "total_after_module1_gross_eur": format(
                            sum(
                                (
                                    row["total_after_module1_gross_eur"]
                                    for row in report_rows
                                ),
                                Decimal(0),
                            ),
                            "f",
                        ),
                        "unpriced_kwh": format(
                            sum(
                                (row["unpriced_kwh"] for row in report_rows), Decimal(0)
                            ),
                            "f",
                        ),
                        "status": "summary; review daily status for completeness",
                    }
                )

        await hass.async_add_executor_job(write_cost_report)
        result = {
            "success": True,
            "account_number": account_number,
            "property_id": property_id,
            "period": period,
            "start_date": start_date.isoformat(),
            "end_date": end_date.isoformat(),
            "days": len(report_rows),
            "incomplete_days": sum(row["status"] != "complete" for row in report_rows),
            "output_file": str(output_path),
        }
        hass.bus.async_fire(f"{DOMAIN}_cost_report_result", result)
        return result

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
        SERVICE_EXPORT_COST_REPORT,
        handle_export_cost_report,
        supports_response=SupportsResponse.ONLY,
    )

    hass.services.async_register(
        DOMAIN,
        SERVICE_SUBMIT_METER_READINGS,
        handle_submit_meter_readings,
        supports_response=SupportsResponse.ONLY,
    )
