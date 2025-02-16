import logging
from datetime import timedelta, datetime
from typing import Mapping, Any

from homeassistant.helpers.typing import StateType
from homeassistant.helpers.update_coordinator import (
    DataUpdateCoordinator,
    CoordinatorEntity,
)
from homeassistant.util.dt import utcnow, as_local
from .const import CONF_PASSWORD, CONF_EMAIL, UPDATE_INTERVAL

from homeassistant.components.sensor import (
    SensorEntityDescription,
    SensorEntity,
    SensorDeviceClass,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from .lib.octopus_germany import OctopusGermany
from homeassistant.exceptions import ConfigEntryNotReady

_LOGGER = logging.getLogger(__name__)

DOMAIN_NAME = "Octopus"  # First part of the name from manifest.json


async def async_setup_entry(
    hass: HomeAssistant, entry: ConfigEntry, async_add_entities: AddEntitiesCallback
) -> None:
    email = entry.data[CONF_EMAIL]
    password = entry.data[CONF_PASSWORD]

    sensors = []
    coordinator = OctopusCoordinator(hass, email, password)
    await coordinator.async_config_entry_first_refresh()

    accounts = coordinator.data.keys()
    for account in accounts:
        sensors.append(
            OctopusAccountNumberSensor(account, coordinator, len(accounts) == 1)
        )
        sensors.append(
            OctopusElectricityBalanceSensor(account, coordinator, len(accounts) == 1)
        )
        sensors.append(
            OctopusPlannedDispatchDeltaSensor(account, coordinator, len(accounts) == 1)
        )
        sensors.append(
            OctopusPlannedDispatchDeltaKwhSensor(
                account, coordinator, len(accounts) == 1
            )
        )
        sensors.append(
            OctopusPlannedDispatchTimeRangeSensor(
                account, coordinator, len(accounts) == 1
            )
        )
        devices = await coordinator._api.devices(account)
        for device in devices:
            sensors.append(
                OctopusDeviceSensor(account, device, coordinator, len(accounts) == 1)
            )

    async_add_entities(sensors)


class OctopusCoordinator(DataUpdateCoordinator):
    def __init__(self, hass: HomeAssistant, email: str, password: str):
        super().__init__(
            hass=hass,
            logger=_LOGGER,
            name="Octopus Germany",
            update_interval=timedelta(hours=UPDATE_INTERVAL),
        )
        self._api = OctopusGermany(email, password)
        self._data = {}

    async def _async_update_data(self):
        if await self._api.login():
            self._data = {}
            accounts = await self._api.accounts()
            if isinstance(accounts, list):
                for account in accounts:
                    account_data = await self._api.account(account)
                    planned_dispatches = await self._api.planned_dispatches(account)
                    property_ids = await self._api.property_ids(account)
                    devices = await self._api.devices(account)
                    self._data[account] = {
                        "account_number": account,
                        "electricity_balance": account_data.get("balance"),
                        "ledger_type": account_data.get("ledgerType"),
                        "ledger_number": account_data.get("number"),
                        "planned_dispatches": planned_dispatches,
                        "property_ids": property_ids,
                        "devices": devices,
                    }
            else:
                _LOGGER.error("Unexpected API response structure: %s", accounts)
                raise ConfigEntryNotReady("Unexpected API response structure")

        return self._data


class OctopusAccountNumberSensor(CoordinatorEntity, SensorEntity):
    def __init__(self, account: str, coordinator, single: bool):
        super().__init__(coordinator=coordinator)
        self._state = None
        self._account = account
        self._attrs: Mapping[str, Any] = {}
        self._attr_name = f"{DOMAIN_NAME} {account} Account Number"
        self._attr_unique_id = f"account_number_{account}"
        self.entity_description = SensorEntityDescription(
            key=f"account_number_{account}",
            icon="mdi:account",
        )

    async def async_added_to_hass(self) -> None:
        await super().async_added_to_hass()
        self._handle_coordinator_update()

    @callback
    def _handle_coordinator_update(self) -> None:
        """Handle updated data from the coordinator."""
        self._state = self.coordinator.data[self._account]["account_number"]
        self._attrs = {
            "property_ids": self.coordinator.data[self._account]["property_ids"]
        }
        self.async_write_ha_state()

    @property
    def native_value(self) -> StateType:
        return self._state

    @property
    def extra_state_attributes(self) -> Mapping[str, Any] | None:
        return self._attrs


class OctopusElectricityBalanceSensor(CoordinatorEntity, SensorEntity):
    def __init__(self, account: str, coordinator, single: bool):
        super().__init__(coordinator=coordinator)
        self._state = None
        self._account = account
        self._attrs: Mapping[str, Any] = {}
        self._attr_name = f"{DOMAIN_NAME} {account} Electricity Konto"
        self._attr_unique_id = f"electricity_balance_{account}"
        self.entity_description = SensorEntityDescription(
            key=f"electricity_balance_{account}",
            icon="mdi:currency-eur",
            device_class=SensorDeviceClass.MONETARY,
        )
        self._attr_unit_of_measurement = "€"

    async def async_added_to_hass(self) -> None:
        await super().async_added_to_hass()
        self._handle_coordinator_update()

    @callback
    def _handle_coordinator_update(self) -> None:
        """Handle updated data from the coordinator."""
        balance_cents = self.coordinator.data[self._account]["electricity_balance"]
        self._state = balance_cents / 100  # Convert cents to euros
        self._attrs = {
            "ledger_type": self.coordinator.data[self._account]["ledger_type"],
            "ledger_number": self.coordinator.data[self._account]["ledger_number"],
        }
        self.async_write_ha_state()

    @property
    def native_value(self) -> StateType:
        return self._state

    @property
    def extra_state_attributes(self) -> Mapping[str, Any] | None:
        return self._attrs


class OctopusPlannedDispatchDeltaSensor(CoordinatorEntity, SensorEntity):
    def __init__(self, account: str, coordinator, single: bool):
        super().__init__(coordinator=coordinator)
        self._state = None
        self._account = account
        self._attrs: Mapping[str, Any] = {}
        self._attr_name = f"{DOMAIN_NAME} {account} Planned Dispatch Delta"
        self._attr_unique_id = f"planned_dispatch_delta_{account}"
        self.entity_description = SensorEntityDescription(
            key=f"planned_dispatch_delta_{account}",
            icon="mdi:flash",
        )

    async def async_added_to_hass(self) -> None:
        await super().async_added_to_hass()
        self._handle_coordinator_update()

    @callback
    def _handle_coordinator_update(self) -> None:
        """Handle updated data from the coordinator."""
        planned_dispatches = self.coordinator.data[self._account]["planned_dispatches"]
        self._state = planned_dispatches[0]["delta"] if planned_dispatches else None
        self._attrs = {
            "location": planned_dispatches[0]["meta"]["location"]
            if planned_dispatches
            else None,
            "source": planned_dispatches[0]["meta"]["source"]
            if planned_dispatches
            else None,
        }
        self.async_write_ha_state()

    @property
    def native_value(self) -> StateType:
        return self._state

    @property
    def extra_state_attributes(self) -> Mapping[str, Any] | None:
        return self._attrs


class OctopusPlannedDispatchDeltaKwhSensor(CoordinatorEntity, SensorEntity):
    def __init__(self, account: str, coordinator, single: bool):
        super().__init__(coordinator=coordinator)
        self._state = None
        self._account = account
        self._attrs: Mapping[str, Any] = {}
        self._attr_name = f"{DOMAIN_NAME} {account} Planned Dispatch Delta kWh"
        self._attr_unique_id = f"planned_dispatch_delta_kwh_{account}"
        self.entity_description = SensorEntityDescription(
            key=f"planned_dispatch_delta_kwh_{account}",
            icon="mdi:flash",
        )
        self._attr_unit_of_measurement = "kWh"

    async def async_added_to_hass(self) -> None:
        await super().async_added_to_hass()
        self._handle_coordinator_update()

    @callback
    def _handle_coordinator_update(self) -> None:
        """Handle updated data from the coordinator."""
        planned_dispatches = self.coordinator.data[self._account]["planned_dispatches"]
        self._state = planned_dispatches[0]["deltaKwh"] if planned_dispatches else None
        self._attrs = {
            "location": planned_dispatches[0]["meta"]["location"]
            if planned_dispatches
            else None,
            "source": planned_dispatches[0]["meta"]["source"]
            if planned_dispatches
            else None,
        }
        self.async_write_ha_state()

    @property
    def native_value(self) -> StateType:
        return self._state

    @property
    def extra_state_attributes(self) -> Mapping[str, Any] | None:
        return self._attrs


class OctopusPlannedDispatchTimeRangeSensor(CoordinatorEntity, SensorEntity):
    def __init__(self, account: str, coordinator, single: bool):
        super().__init__(coordinator=coordinator)
        self._state = None
        self._account = account
        self._attrs: Mapping[str, Any] = {}
        self._attr_name = f"{DOMAIN_NAME} {account} Planned Dispatch Time Range"
        self._attr_unique_id = f"planned_dispatch_time_range_{account}"
        self.entity_description = SensorEntityDescription(
            key=f"planned_dispatch_time_range_{account}",
            icon="mdi:clock",
        )

    async def async_added_to_hass(self) -> None:
        await super().async_added_to_hass()
        self._handle_coordinator_update()

    @callback
    def _handle_coordinator_update(self) -> None:
        """Handle updated data from the coordinator."""
        planned_dispatches = self.coordinator.data[self._account]["planned_dispatches"]
        if planned_dispatches:
            start_dt = datetime.fromisoformat(planned_dispatches[0]["startDt"])
            end_dt = datetime.fromisoformat(planned_dispatches[0]["endDt"])
            now = utcnow()
            self._state = start_dt <= now <= end_dt
            self._attrs = {
                "start": as_local(start_dt),
                "end": as_local(end_dt),
                "location": planned_dispatches[0]["meta"]["location"],
                "source": planned_dispatches[0]["meta"]["source"],
            }
        else:
            self._state = None
            self._attrs = {}
        self.async_write_ha_state()

    @property
    def native_value(self) -> StateType:
        return self._state

    @property
    def extra_state_attributes(self) -> Mapping[str, Any] | None:
        return self._attrs


class OctopusDeviceSensor(CoordinatorEntity, SensorEntity):
    def __init__(self, account: str, device: dict, coordinator, single: bool):
        super().__init__(coordinator=coordinator)
        self._state = None
        self._account = account
        self._device = device
        self._attrs: Mapping[str, Any] = {}
        self._attr_name = f"{DOMAIN_NAME} {account} {device['name']} Smart Control"
        self._attr_unique_id = f"device_{device['id']}"
        self.entity_description = SensorEntityDescription(
            key=f"device_{device['id']}",
            icon="mdi:car-electric",
        )

    async def async_added_to_hass(self) -> None:
        await super().async_added_to_hass()
        self._handle_coordinator_update()

    @callback
    def _handle_coordinator_update(self) -> None:
        """Handle updated data from the coordinator."""
        current_state = self._device["status"]["currentState"]
        self._state = (
            current_state.split("_", 2)[-1] if "_" in current_state else current_state
        )
        self._attrs = {
            "id": self._device["id"],
            "name": self._device["name"],
            "current": self._device["status"]["current"],
            "is_suspended": self._device["status"]["isSuspended"],
            "device_type": self._device["deviceType"],
        }
        self.async_write_ha_state()

    @property
    def native_value(self) -> StateType:
        return self._state

    @property
    def extra_state_attributes(self) -> Mapping[str, Any] | None:
        return self._attrs
