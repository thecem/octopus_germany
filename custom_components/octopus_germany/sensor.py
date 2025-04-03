import logging
from datetime import timedelta, datetime
from typing import Mapping, Any

from homeassistant.helpers.update_coordinator import DataUpdateCoordinator
from homeassistant.util.dt import as_local
from .const import CONF_PASSWORD, CONF_EMAIL, UPDATE_INTERVAL

from homeassistant.components.binary_sensor import BinarySensorEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from .octopus_germany import OctopusGermany
from homeassistant.exceptions import ConfigEntryNotReady

_LOGGER = logging.getLogger(__name__)

DOMAIN_NAME = "Octopus"


async def async_setup_entry(
    hass: HomeAssistant, entry: ConfigEntry, async_add_entities: AddEntitiesCallback
) -> None:
    email = entry.data[CONF_EMAIL]
    password = entry.data[CONF_PASSWORD]

    coordinator = OctopusCoordinator(hass, email, password)
    await coordinator.async_config_entry_first_refresh()

    sensors = [
        OctopusIntelligentDispatchingBinarySensor(account, coordinator)
        for account in coordinator.data.keys()
    ]

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
            accounts = await self._api.fetch_accounts()
            if accounts is None:
                _LOGGER.error("Failed to fetch accounts: response is None")
                raise ConfigEntryNotReady("Failed to fetch accounts: response is None")

            for account in accounts:
                account_number = account.get("number")
                if not account_number:
                    _LOGGER.error("Account number is missing in the response")
                    continue

                fetched_data = await self._api.fetch_all_data(account_number)
                account_data = fetched_data.get("account", {})
                planned_dispatches = fetched_data.get("plannedDispatches", [])
                completed_dispatches = fetched_data.get("completedDispatches", [])
                devices = fetched_data.get("devices", [])

                ledgers = account_data.get("ledgers", [])
                electricity_balance_cents = next(
                    (
                        ledger.get("balance", 0)
                        for ledger in ledgers
                        if ledger.get("ledgerType") == "ELECTRICITY_LEDGER"
                    ),
                    0,
                )
                electricity_balance_eur = electricity_balance_cents / 100

                current_dispatch = planned_dispatches[0] if planned_dispatches else {}
                next_dispatch = (
                    planned_dispatches[1] if len(planned_dispatches) > 1 else {}
                )

                products = [
                    {
                        "code": agreement["product"]["code"],
                        "description": agreement["product"]["description"],
                        "name": agreement["product"]["fullName"],
                        "grossRate": agreement.get("unitRateInformation", {}).get(
                            "latestGrossUnitRateCentsPerKwh", "0"
                        ),
                        "type": (
                            "Simple"
                            if agreement.get("unitRateInformation", {}).get(
                                "__typename"
                            )
                            == "SimpleProductUnitRateInformation"
                            else "TimeOfUse"
                        ),
                        "validFrom": agreement.get("validFrom"),
                        "validTo": agreement.get("validTo"),
                    }
                    for property in account_data.get("allProperties", [])
                    for malo in property.get("electricityMalos", [])
                    for agreement in malo.get("agreements", [])
                ]

                malo_number = next(
                    (
                        malo.get("maloNumber")
                        for property in account_data.get("allProperties", [])
                        for malo in property.get("electricityMalos", [])
                    ),
                    "Unbekannt",
                )

                melo_number = next(
                    (
                        malo.get("meloNumber")
                        for property in account_data.get("allProperties", [])
                        for malo in property.get("electricityMalos", [])
                    ),
                    "Unbekannt",
                )

                meter = next(
                    (
                        malo.get("meter")
                        for property in account_data.get("allProperties", [])
                        for malo in property.get("electricityMalos", [])
                    ),
                    {},
                )

                self._data[account_number] = {
                    "account_number": account_number,
                    "electricity_balance": electricity_balance_eur,
                    "planned_dispatches": planned_dispatches,
                    "completed_dispatches": completed_dispatches,
                    "property_ids": [
                        prop.get("id") for prop in account_data.get("allProperties", [])
                    ],
                    "devices": devices,
                    "products": products,
                    "vehicle_battery_size_in_kwh": next(
                        (
                            float(device["vehicleVariant"]["batterySize"])
                            for device in devices
                            if device.get("vehicleVariant")
                        ),
                        None,
                    ),
                    "current_start": as_local(
                        datetime.fromisoformat(current_dispatch.get("start"))
                    )
                    if current_dispatch
                    else None,
                    "current_end": as_local(
                        datetime.fromisoformat(current_dispatch.get("end"))
                    )
                    if current_dispatch
                    else None,
                    "next_start": as_local(
                        datetime.fromisoformat(next_dispatch.get("start"))
                    )
                    if next_dispatch
                    else None,
                    "next_end": as_local(
                        datetime.fromisoformat(next_dispatch.get("end"))
                    )
                    if next_dispatch
                    else None,
                    "ledgers": ledgers,
                    "malo_number": malo_number,
                    "melo_number": melo_number,
                    "meter": meter,
                }
                _LOGGER.debug(f"Coordinator data: {self._data}")

        return self._data


class OctopusIntelligentDispatchingBinarySensor(BinarySensorEntity):
    def __init__(self, account, coordinator):
        self._account = account
        self._coordinator = coordinator
        self._attr_name = f"Octopus Intelligent Dispatching {account}"
        self._attr_unique_id = f"octopus_intelligent_dispatching_{account}"

    @property
    def is_on(self) -> bool:
        data = self._coordinator.data.get(self._account, {})
        planned_dispatches = data.get("planned_dispatches", [])
        now = as_local(datetime.now())

        for dispatch in planned_dispatches:
            start = as_local(datetime.fromisoformat(dispatch.get("start")))
            end = as_local(datetime.fromisoformat(dispatch.get("end")))
            if start <= now <= end:
                return True
        return False

    @property
    def extra_state_attributes(self) -> Mapping[str, Any]:
        data = self._coordinator.data.get(self._account, {})
        meter_data = data.get("meter", {}).copy()
        meter_data.pop("submitMeterReadingUrl", None)
        devices = data.get("devices", [])
        planned_dispatches = data.get("planned_dispatches", [])
        completed_dispatches = data.get("completed_dispatches", [])
        first_dispatch = planned_dispatches[0] if planned_dispatches else {}
        current_state = (
            devices[0].get("status", {}).get("currentState", "Unbekannt")
            if devices
            else "Unbekannt"
        )
        return {
            "account_number": data.get("account_number"),
            "electricity_balance": f"{data.get('electricity_balance', 0):.2f} €",
            "planned_dispatches": [
                {
                    "start": as_local(datetime.fromisoformat(dispatch.get("start"))),
                    "end": as_local(datetime.fromisoformat(dispatch.get("end"))),
                    "charge_in_kwh": float(dispatch.get("deltaKwh", 0)),
                    "source": dispatch.get("meta", {}).get("source"),
                    "location": dispatch.get("meta", {}).get("location"),
                }
                for dispatch in planned_dispatches
            ],
            "completed_dispatches": [
                {
                    "start": as_local(datetime.fromisoformat(dispatch.get("start"))),
                    "end": as_local(datetime.fromisoformat(dispatch.get("end"))),
                    "charge_in_kwh": float(dispatch.get("deltaKwh", 0)),
                    "source": dispatch.get("meta", {}).get("source"),
                    "location": dispatch.get("meta", {}).get("location"),
                }
                for dispatch in completed_dispatches
            ],
            "provider": devices[0].get("provider", "Unbekannt")
            if devices
            else "Unbekannt",
            "vehicle_battery_size_in_kwh": data.get(
                "vehicle_battery_size_in_kwh", "Unbekannt"
            ),
            "charge_point_power_in_kw": data.get(
                "charge_point_power_in_kw", "Unbekannt"
            ),
            "current_start": data.get("current_start", "Unbekannt"),
            "current_end": data.get("current_end", "Unbekannt"),
            "next_start": data.get("next_start", "Unbekannt"),
            "next_end": data.get("next_end", "Unbekannt"),
            "devices": data.get("devices", []),
            "products": data.get("products", []),
            "malo_number": data.get("malo_number", "Unbekannt"),
            "melo_number": data.get("melo_number", "Unbekannt"),
            "meter": meter_data,
            "current_state": current_state,
        }

    async def async_update(self):
        await self._coordinator.async_request_refresh()
