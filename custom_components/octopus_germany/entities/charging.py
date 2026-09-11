"""Charging-related sensor entities for the Octopus Germany integration."""

from __future__ import annotations

import contextlib
import logging
from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING, Any

from homeassistant.components.sensor import (
    RestoreEntity,
    SensorDeviceClass,
    SensorEntity,
    SensorStateClass,
)
from homeassistant.const import STATE_UNAVAILABLE, STATE_UNKNOWN, UnitOfEnergy
from homeassistant.helpers.device_registry import DeviceEntryType
from homeassistant.helpers.entity import DeviceInfo
from homeassistant.helpers.update_coordinator import CoordinatorEntity
from homeassistant.util.dt import as_utc

from custom_components.octopus_germany.const import DOMAIN

if TYPE_CHECKING:
    from custom_components.octopus_germany.coordinator import OctopusDataCoordinator

_LOGGER = logging.getLogger(__name__)


def _get_account_device_info(account_number: str) -> DeviceInfo:
    """Get device info for account service."""
    return DeviceInfo(
        identifiers={(DOMAIN, account_number)},
        name=f"Octopus Energy Germany ({account_number})",
        manufacturer="Octopus Energy Germany",
        configuration_url="https://my.octopusenergy.de/",
        entry_type=DeviceEntryType.SERVICE,
    )


class OctopusElectricitySmartMeterReadingsSensor(
    CoordinatorEntity, SensorEntity, RestoreEntity
):
    """Sensor for previous-day accumulative electricity smart meter consumption."""

    def __init__(
        self, account_number: str, coordinator: OctopusDataCoordinator
    ) -> None:
        """Initialize the sensor."""
        super().__init__(coordinator)
        self._account_number = account_number

        # Use fallback values during initialization.
        # Values are refreshed once coordinator data is available.
        self._attr_name = (
            f"Previous Accumulative Consumption Electricity ({account_number})"
        )
        self._attr_unique_id = (
            f"octopus_germany_electricity_{account_number}_"
            "previous_accumulative_consumption"
        )
        self._attr_icon = "mdi:lightning-bolt"
        self._attr_device_class = SensorDeviceClass.ENERGY
        self._attr_native_unit_of_measurement = UnitOfEnergy.KILO_WATT_HOUR
        self._attr_state_class = SensorStateClass.TOTAL

        # Base attributes - will be updated when data is available
        self._attributes = {
            "account_number": account_number,
            "is_smart_meter": True,
        }

        self._state = None
        self._last_reset = None
        self._meter_info_cached = None

    def _get_meter_info(self) -> dict:
        """Get meter information from coordinator data."""
        if (
            self.coordinator.data
            and self._account_number in self.coordinator.data
            and "meter" in self.coordinator.data[self._account_number]
        ):
            return self.coordinator.data[self._account_number]["meter"]
        return {}

    @property
    def name(self) -> str:
        """Return the name of the sensor."""
        meter_info = self._get_meter_info()
        if meter_info and meter_info.get("number"):
            meter_number = meter_info["number"]
            return (
                "Previous Accumulative Consumption Electricity "
                f"({meter_number}/{self._account_number})"
            )
        return f"Previous Accumulative Consumption Electricity ({self._account_number})"

    @property
    def entity_registry_enabled_default(self) -> bool:
        """Return if the entity should be enabled when first added."""
        # Always enable - data availability will be handled by the available property
        return True

    @property
    def native_value(self) -> float | None:
        """Return the total consumption for the previous available day."""
        if (
            self.coordinator.data
            and self._account_number in self.coordinator.data
            and "electricity_smart_meter_readings"
            in self.coordinator.data[self._account_number]
        ):
            readings = self.coordinator.data[self._account_number][
                "electricity_smart_meter_readings"
            ]
            if readings and len(readings) > 0:
                # Calculate total consumption for the day, converting values to float
                total_consumption = 0.0
                for reading in readings:
                    value = reading.get("value", 0)
                    try:
                        # Convert string or numeric value to float
                        if isinstance(value, str):
                            total_consumption += float(value)
                        else:
                            total_consumption += float(value or 0)
                    except ValueError, TypeError:
                        # Skip invalid values
                        continue
                return round(total_consumption, 3)
        return None

    @property
    def last_reset(self) -> datetime | None:
        """Return the time when the sensor was last reset."""
        return self._last_reset

    @property
    def extra_state_attributes(self) -> dict[str, Any] | None:
        """Return detailed attributes following Octopus Energy pattern."""
        if (
            self.coordinator.data
            and self._account_number in self.coordinator.data
            and "electricity_smart_meter_readings"
            in self.coordinator.data[self._account_number]
        ):
            readings = self.coordinator.data[self._account_number][
                "electricity_smart_meter_readings"
            ]
            if readings:
                # Calculate totals and create detailed breakdown
                total_consumption = 0.0
                for reading in readings:
                    value = reading.get("value", 0)
                    try:
                        # Convert string or numeric value to float
                        if isinstance(value, str):
                            total_consumption += float(value)
                        else:
                            total_consumption += float(value or 0)
                    except ValueError, TypeError:
                        # Skip invalid values
                        continue

                # Create charges array similar to Octopus Energy
                charges = []
                for reading in readings:
                    value = reading.get("value", 0)
                    try:
                        # Convert to float for consistency
                        if isinstance(value, str):
                            consumption_value = float(value)
                        else:
                            consumption_value = float(value or 0)
                    except ValueError, TypeError:
                        consumption_value = 0.0

                    charges.append(
                        {
                            "start": reading.get("start_time"),
                            "end": reading.get("end_time"),
                            "consumption": consumption_value,
                        }
                    )

                # Get date information
                date_info = self.coordinator.data[self._account_number].get(
                    "electricity_smart_meter_readings_date"
                )
                date_label = self.coordinator.data[self._account_number].get(
                    "electricity_smart_meter_readings_label", "previous day"
                )

                # Get meter info for attributes
                meter_info = self._get_meter_info()

                # Update base attributes with current data
                self._attributes.update(
                    {
                        "meter_id": meter_info.get("id"),
                        "meter_number": meter_info.get("number"),
                        "meter_type": meter_info.get("type"),
                        "total": round(
                            total_consumption, 6
                        ),  # More precision for total
                        "total_readings": len(readings),
                        "reading_date": date_info,
                        "reading_period": date_label,
                        "charges": charges,
                        "data_last_retrieved": self.coordinator.data[
                            self._account_number
                        ].get("last_updated"),
                    }
                )

                # Set last reset time to start of the day
                if readings and readings[0].get("start_time"):
                    try:
                        first_reading_time = datetime.fromisoformat(
                            readings[0]["start_time"]
                        )
                        self._last_reset = first_reading_time.replace(
                            hour=0, minute=0, second=0, microsecond=0
                        )
                    except ValueError, TypeError:
                        pass

                return self._attributes

        return self._attributes

    @property
    def available(self) -> bool:
        """Return True if entity is available."""
        return (
            self.coordinator is not None
            and self.coordinator.last_update_success
            and isinstance(self.coordinator.data, dict)
            and self._account_number in self.coordinator.data
        )

    async def async_added_to_hass(self) -> None:
        """Call when entity about to be added to hass."""
        await super().async_added_to_hass()

        # Restore previous state if available
        if (
            state := await self.async_get_last_state()
        ) is not None and state.state not in (STATE_UNAVAILABLE, STATE_UNKNOWN):
            with contextlib.suppress(ValueError, TypeError):
                self._state = float(state.state)

            # Restore attributes
            if state.attributes:
                self._attributes.update(state.attributes)

        _LOGGER.debug("Restored smart meter sensor state: %s", self._state)

    @property
    def device_info(self) -> DeviceInfo:
        """Return device information."""
        return _get_account_device_info(self._account_number)


class OctopusSmartChargingSessionsSensor(CoordinatorEntity, SensorEntity):
    """Sensor exposing historical smart charging sessions for one device."""

    def _get_sessions(self) -> list[dict[str, Any]]:
        """Return the latest sessions for this device from coordinator data."""
        if not self.coordinator or not isinstance(self.coordinator.data, dict):
            return []
        account_data = self.coordinator.data.get(self._account_number, {})
        return [
            session
            for session in account_data.get("charging_sessions", []) or []
            if session.get("device_id") == self._device_id
            or session.get("device_name") == self._device_name
        ]

    @property
    def extra_state_attributes(self) -> dict:
        """Return the attributes for the smart charging sessions sensor."""
        sessions = self._get_sessions()
        current_month = datetime.now(UTC).strftime("%Y-%m")
        smart_sessions_sorted = sorted(
            sessions,
            key=lambda s: s.get("start") or "",
            reverse=True,
        )
        now = datetime.now(UTC)
        min_date = now - timedelta(days=730)
        sessions_list = []
        sessions_by_month = {}
        total_energy = 0.0
        for session in smart_sessions_sorted:
            start_str = session.get("start")
            try:
                start_dt = datetime.fromisoformat(start_str) if start_str else None
                if start_dt and start_dt.tzinfo is None:
                    start_dt = as_utc(start_dt)
            except TypeError, ValueError:
                start_dt = None
            if start_dt and start_dt < min_date:
                continue
            energy = session.get("energyAdded", {}) or {}
            energy_kwh = float(energy.get("value", 0) or 0)
            if energy_kwh == 0.0:
                continue
            cost = session.get("cost") or {}
            sessions_list.append(
                {
                    "start": session.get("start"),
                    "end": session.get("end"),
                    "energy_kwh": energy_kwh,
                    "cost_eur": cost.get("amount", 0) if cost else 0,
                    "device_name": session.get("device_name", "Unknown"),
                    "type": session.get("type", "UNKNOWN"),
                    "is_successful": session.get("is_successful", True),
                    "has_error": session.get("has_error", False),
                    "has_truncation": session.get("has_truncation", False),
                    "has_ended": session.get("has_ended", True),
                    "has_energy": session.get("has_energy", False),
                    "dispatches_utilized": session.get("dispatches_utilized", True),
                    "soc_final": session.get("soc_final"),
                    "error_cause": session.get("error_cause"),
                    "truncation_cause": session.get("truncation_cause"),
                }
            )
            # For monthly stats
            if start_dt:
                month_key = start_dt.strftime("%Y-%m")
                sessions_by_month.setdefault(month_key, []).append(session)
            total_energy += energy_kwh
        # Determine the full range of months from the earliest session to now
        current_month_count = len(sessions_by_month.get(current_month, []))
        current_month_qualified = current_month_count >= 5
        return {
            "smart_sessions_count": len(sessions_list),
            "total_energy_kwh": round(total_energy, 2),
            "current_month_count": current_month_count,
            "current_month_qualified": current_month_qualified,
            "recent_sessions": sessions_list,
        }

    def __init__(
        self,
        account_number: str,
        coordinator: OctopusDataCoordinator,
        device_name: str,
        device_id: str,
        sessions: list[dict[str, Any]],
    ) -> None:
        """Initialize the smart charging sessions sensor for a specific device."""
        super().__init__(coordinator)

        self._account_number = account_number
        self._device_name = device_name
        self._device_id = device_id
        norm_name = device_name.lower().replace(" ", "_")
        for ch in [
            "/",
            "\\",
            ",",
            ".",
            ":",
            ";",
            "|",
            "[",
            "]",
            "{",
            "}",
            "(",
            ")",
            "'",
            '"',
            "#",
            "?",
            "!",
            "@",
            "=",
            "+",
            "*",
            "%",
            "&",
            "<",
            ">",
        ]:
            norm_name = norm_name.replace(ch, "_")
        self._attr_name = (
            f"Octopus {account_number} {device_name} Smart Charging Sessions"
        )
        self._attr_unique_id = (
            f"octopus_{account_number}_{norm_name}_smart_charging_sessions"
        )
        self._attr_icon = "mdi:ev-station"
        self._attr_state_class = SensorStateClass.MEASUREMENT
        self._attr_has_entity_name = False

        # Keep the initial argument for compatibility.
        # Live session data comes from the coordinator.
        self._sessions = sessions or []

    @property
    def native_value(self) -> int:
        """Return the count of smart charging sessions in the current month."""
        sessions = self._get_sessions()
        current_month = datetime.now(UTC).strftime("%Y-%m")
        # Sort sessions by start date descending (most recent first)
        smart_sessions_sorted = sorted(
            sessions,
            key=lambda s: s.get("start") or "",
            reverse=True,
        )
        smart_sessions_current_month = []
        for session in smart_sessions_sorted:
            start_str = session.get("start")
            try:
                start_dt = datetime.fromisoformat(start_str) if start_str else None
                # Stelle sicher, dass start_dt offset-aware ist
                if start_dt and start_dt.tzinfo is None:
                    start_dt = as_utc(start_dt)
            except TypeError, ValueError:
                start_dt = None
            # min_date is only used in attributes.
            # Skip that filter in native_value.
            energy = session.get("energyAdded", {}) or {}
            energy_kwh = float(energy.get("value", 0) or 0)
            if energy_kwh == 0.0:
                continue
            # Only count sessions in the current month
            if start_dt and start_dt.strftime("%Y-%m") == current_month:
                smart_sessions_current_month.append(session)
        return len(smart_sessions_current_month)

    @property
    def available(self) -> bool:
        """Return True if entity is available."""
        return (
            self.coordinator is not None
            and self.coordinator.last_update_success
            and isinstance(self.coordinator.data, dict)
            and self._account_number in self.coordinator.data
        )

    @property
    def device_info(self) -> DeviceInfo:
        """Return device information."""
        return _get_account_device_info(self._account_number)
