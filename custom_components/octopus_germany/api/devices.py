"""Device, charging, and dispatch methods for the Octopus Germany API client."""

from __future__ import annotations

import logging
from typing import Any

from .queries import CHARGING_SESSIONS_QUERY, VEHICLE_DETAILS_QUERY

_LOGGER = logging.getLogger(__name__)

_EXPIRED_ERROR_CODE = "KT-CT-1124"
_RESOURCE_NOT_FOUND_ERROR_CODE = "KT-CT-4301"
_TEMPORARY_DEVICE_ERROR_CODE = "KT-CT-4340"
_TARGET_PERCENTAGE_MIN = 20
_TARGET_PERCENTAGE_MAX = 100
_TARGET_PERCENTAGE_STEP = 5
_MIN_ALLOWED_TARGET_HOUR = 4
_MAX_ALLOWED_TARGET_HOUR = 17


class DeviceApiMixin:
    """Mixin that provides device-related API calls."""

    async def fetch_charging_sessions(
        self, account_number: str
    ) -> list[dict[str, Any]] | None:
        """
        Fetch charging sessions for smart charging rewards tracking.

        Returns:
            list: List of charging sessions, or empty list if no sessions/devices
            None: Only on actual API errors (token issues, network problems, etc.)

        """
        if not await self.ensure_token():
            _LOGGER.warning(
                "Failed to ensure valid token for fetch_charging_sessions "
                "(account: %s)",
                account_number,
            )
            return None

        client = self._get_graphql_client()
        variables = {"accountNumber": account_number}

        try:
            response = await client.execute_async(
                query=CHARGING_SESSIONS_QUERY, variables=variables
            )

            if response.get("data"):
                devices = response["data"].get("devices", [])
                all_sessions = []

                for device in devices:
                    device_id = device.get("id")
                    device_name = device.get("name", "Unknown Device")
                    device_type = device.get("deviceType", "UNKNOWN")

                    charging_sessions = device.get("chargingSessions", {})
                    if charging_sessions:
                        edges = charging_sessions.get("edges", [])
                        for edge in edges:
                            session = edge.get("node", {})
                            if session:
                                # Normalize SoC fields to snake_case for
                                # internal consumers.
                                if (
                                    "soc_final" not in session
                                    and "stateOfChargeFinal" in session
                                ):
                                    session["soc_final"] = session.get(
                                        "stateOfChargeFinal"
                                    )
                                if (
                                    "soc_change" not in session
                                    and "stateOfChargeChange" in session
                                ):
                                    session["soc_change"] = session.get(
                                        "stateOfChargeChange"
                                    )
                                # Add device context to session
                                session["device_id"] = device_id
                                session["device_name"] = device_name
                                session["device_type"] = device_type
                                all_sessions.append(session)

                return all_sessions
            if "errors" in response:
                error = response.get("errors", [{}])[0]
                error_code = error.get("extensions", {}).get("errorCode")

                # Check if token expired error
                if error_code == _EXPIRED_ERROR_CODE:  # JWT expired
                    _LOGGER.warning("Token expired, refreshing...")
                    self._token_manager.clear()
                    success = await self.login()
                    if success:
                        # Retry with new token
                        return await self.fetch_charging_sessions(account_number)

                _LOGGER.info(
                    "No charging sessions available for account %s "
                    "(may not have SmartFlex devices): %s",
                    account_number,
                    response.get("errors"),
                )
                return []  # Empty list is valid - means no devices/sessions

        except Exception:
            _LOGGER.exception(
                "Error fetching charging sessions for account %s",
                account_number,
            )
            return None  # None signals error - caller should use cached data
        return []

    async def change_device_suspension(self, device_id: str, action: str) -> str | None:
        """Change device suspension state."""
        if not await self.ensure_token():
            _LOGGER.error("Failed to ensure valid token for change_device_suspension")
            return None

        query = """
            mutation ChangeDeviceSuspension($deviceId: ID = "", $action: SmartControlAction!) {
              updateDeviceSmartControl(input: {deviceId: $deviceId, action: $action}) {
                id
              }
            }
        """
        variables = {"deviceId": device_id, "action": action}
        _LOGGER.debug(
            "Executing change_device_suspension: device_id=%s, action=%s",
            device_id,
            action,
        )
        client = self._get_graphql_client()
        try:
            response = await client.execute_async(query=query, variables=variables)
            _LOGGER.debug("Change device suspension response: %s", response)

            if "errors" in response:
                error = response.get("errors", [{}])[0]
                error_code = error.get("extensions", {}).get("errorCode")

                # Check if token expired error
                if error_code == _EXPIRED_ERROR_CODE:  # JWT expired
                    _LOGGER.warning(
                        "Token expired during device suspension change, refreshing..."
                    )
                    self._token_manager.clear()
                    success = await self.login()
                    if success:
                        # Retry with new token
                        return await self.change_device_suspension(device_id, action)

                _LOGGER.error("API returned errors: %s", response["errors"])
                return None

            return (
                response.get("data", {}).get("updateDeviceSmartControl", {}).get("id")
            )
        except Exception:
            _LOGGER.exception("Error changing device suspension")
            return None

    async def set_device_preferences(
        self,
        device_id: str,
        target_percentage: int,
        target_time: str,
    ) -> bool:
        """
        Set device charging preferences using the new setDevicePreferences API.

        Args:
            device_id: The device ID to set preferences for
            target_percentage: Target state of charge (20-100%)
            target_time: Time in HH:MM format (04:00-17:00)

        Returns:
            True if successful, False otherwise

        """
        if not await self.ensure_token():
            _LOGGER.error("Failed to ensure valid token for set_device_preferences")
            return False

        # Validate percentage range (20-100% in 5% steps)
        if not 20 <= target_percentage <= 100:
            _LOGGER.error(
                "Invalid target percentage: %s. Must be between 20 and 100.",
                target_percentage,
            )
            return False

        if target_percentage % 5 != 0:
            _LOGGER.error(
                "Invalid target percentage: %s. Must be in 5%% steps.",
                target_percentage,
            )
            return False

        # Format and validate the target time
        try:
            formatted_time = self._format_time_to_hh_mm(target_time)

            # Validate time range (04:00-17:00)
            hour = int(formatted_time.split(":")[0])
            if not 4 <= hour <= 17:
                _LOGGER.error(
                    "Invalid target time: %s. Must be between 04:00 and 17:00.",
                    formatted_time,
                )
                return False

            _LOGGER.debug(
                "Formatted time for API: %s",
                formatted_time,
            )
        except ValueError:
            _LOGGER.exception("Time format validation error")
            return False

        # Use the new setDevicePreferences mutation - based on the exact working example
        # No variables, everything inline as shown in the working example
        query = f"""
        mutation setDevicePreferences {{
          setDevicePreferences(
            input: {{
              deviceId: "{device_id}",
              mode: CHARGE,
              unit: PERCENTAGE,
              schedules: [
                {{ dayOfWeek: MONDAY, time: "{formatted_time}", max: {target_percentage} }},
                {{ dayOfWeek: TUESDAY, time: "{formatted_time}", max: {target_percentage} }},
                {{ dayOfWeek: WEDNESDAY, time: "{formatted_time}", max: {target_percentage} }},
                {{ dayOfWeek: THURSDAY, time: "{formatted_time}", max: {target_percentage} }},
                {{ dayOfWeek: FRIDAY, time: "{formatted_time}", max: {target_percentage} }},
                {{ dayOfWeek: SATURDAY, time: "{formatted_time}", max: {target_percentage} }},
                {{ dayOfWeek: SUNDAY, time: "{formatted_time}", max: {target_percentage} }}
              ]
            }}
          ) {{
            id
          }}
        }}
        """

        variables = {}

        client = self._get_graphql_client()

        _LOGGER.debug(
            "Making set_device_preferences API request with device_id: %s, "
            "target: %s%%, time: %s",
            device_id,
            target_percentage,
            formatted_time,
        )

        try:
            response = await client.execute_async(query=query, variables=variables)
            _LOGGER.debug("Set device preferences response: %s", response)

            if "errors" in response:
                error = response.get("errors", [{}])[0]
                error_code = error.get("extensions", {}).get("errorCode")
                error_message = error.get("message", "Unknown error")

                _LOGGER.error(
                    "API error setting device preferences: %s (code: %s)",
                    error_message,
                    error_code,
                )

                # Check if token expired error
                if error_code == _EXPIRED_ERROR_CODE:  # JWT expired
                    _LOGGER.warning(
                        "Token expired during setting device preferences, refreshing..."
                    )
                    self._token_manager.clear()
                    success = await self.login()
                    if success:
                        # Retry with new token
                        return await self.set_device_preferences(
                            device_id,
                            target_percentage,
                            target_time,
                        )

                return False

        except Exception:
            _LOGGER.exception("Error setting device preferences")
            return False
        return True

    async def get_vehicle_devices(
        self, account_number: str
    ) -> list[dict[str, Any]] | None:
        """
        Get vehicle device details with preference settings.

        Args:
            account_number: The account number

        Returns:
            List of vehicle devices with their settings or None if error

        """
        if not await self.ensure_token():
            _LOGGER.error("Failed to ensure valid token for get_vehicle_devices")
            return None

        variables = {"accountNumber": account_number}
        client = self._get_graphql_client()

        try:
            _LOGGER.debug(
                "Fetching vehicle devices for account %s",
                account_number,
            )
            response = await client.execute_async(
                query=VEHICLE_DETAILS_QUERY, variables=variables
            )

            if response is None:
                _LOGGER.error("API returned None response for vehicle devices")
                return None

            if "errors" in response:
                error = response.get("errors", [{}])[0]
                error_code = error.get("extensions", {}).get("errorCode")

                # Check if token expired error
                if error_code == _EXPIRED_ERROR_CODE:  # JWT expired
                    _LOGGER.warning("Token expired, refreshing...")
                    self._token_manager.clear()
                    success = await self.login()
                    if success:
                        # Retry with new token
                        return await self.get_vehicle_devices(account_number)

                _LOGGER.error(
                    "GraphQL errors in vehicle devices response: %s",
                    response["errors"],
                )
                return None

            if "data" in response and "devices" in response["data"]:
                devices = response["data"]["devices"]

                # Filter for electric vehicle devices
                vehicle_devices = [
                    device
                    for device in devices
                    if device.get("deviceType") == "ELECTRIC_VEHICLES"
                ]

                _LOGGER.debug(
                    "Found %d vehicle devices",
                    len(vehicle_devices),
                )
                return vehicle_devices
            _LOGGER.error("Invalid response structure for vehicle devices")

        except Exception:
            _LOGGER.exception("Error fetching vehicle devices")
            return None
        return None

    async def fetch_flex_planned_dispatches(
        self, device_id: str
    ) -> list[dict[str, Any]] | None:
        """
        Fetch planned dispatches for a specific device using the new

        flexPlannedDispatches API.

        Args:
            device_id: The device ID to fetch planned dispatches for

        Returns:
            List of planned dispatches for the device or None if error

        """
        if not await self.ensure_token():
            _LOGGER.error(
                "Failed to ensure valid token for fetch_flex_planned_dispatches"
            )
            return None

        # Use inline query with device ID as shown in the working example
        query = f"""
        query flexPlannedDispatches {{
          flexPlannedDispatches(deviceId: "{device_id}") {{
            end
            energyAddedKwh
            start
            type
          }}
        }}
        """

        client = self._get_graphql_client()

        try:
            _LOGGER.debug(
                "Fetching flex planned dispatches for device %s",
                device_id,
            )
            response = await client.execute_async(query=query, variables={})

            if response is None:
                _LOGGER.error("API returned None response for flex planned dispatches")
                return None

            if "errors" in response:
                error = response.get("errors", [{}])[0]
                error_code = error.get("extensions", {}).get("errorCode")
                error_message = error.get("message", "Unknown error")

                # Check if token expired error
                if error_code == _EXPIRED_ERROR_CODE:  # JWT expired
                    _LOGGER.warning("Token expired, refreshing...")
                    self._token_manager.clear()
                    success = await self.login()
                    if success:
                        # Retry with new token
                        return await self.fetch_flex_planned_dispatches(device_id)

                # Log but don't fail for non-critical errors (device might not
                # support flex dispatches).
                if error_code == _RESOURCE_NOT_FOUND_ERROR_CODE:  # Resource not found
                    _LOGGER.debug(
                        "Device %s does not support flex planned dispatches: %s",
                        device_id,
                        error_message,
                    )
                    return []
                if error_code == _TEMPORARY_DEVICE_ERROR_CODE:  # Temporary API error
                    _LOGGER.debug(
                        "Temporary API error fetching dispatches for device %s: %s "
                        "(will use cached data)",
                        device_id,
                        error_message,
                    )
                    # Return None to signal error so the coordinator keeps
                    # cached data.
                    return None
                _LOGGER.error(
                    "GraphQL errors in flex planned dispatches response: %s",
                    response["errors"],
                )
                return None

            if "data" in response and "flexPlannedDispatches" in response["data"]:
                dispatches = response["data"]["flexPlannedDispatches"]
                if dispatches is None:
                    dispatches = []

                _LOGGER.debug(
                    "Found %d flex planned dispatches for device %s",
                    len(dispatches),
                    device_id,
                )
                return dispatches
            _LOGGER.error("Invalid response structure for flex planned dispatches")

        except Exception:
            _LOGGER.exception("Error fetching flex planned dispatches")
            return None
        return None

    # Remove redundant _fetch_account_and_devices method because
    # fetch_all_data already provides the same data.
    # The method below is kept only for backward compatibility
    async def _fetch_account_and_devices(self, account_number: str) -> dict[str, Any]:
        """
        Fetch account and devices data using the comprehensive query.

        This method is kept for backward compatibility but now uses the same
        comprehensive query as fetch_all_data.
        """
        _LOGGER.info(
            "Using _fetch_account_and_devices (deprecated - using comprehensive query)"
        )
        all_data = await self.fetch_all_data(account_number)

        if not all_data:
            return {
                "account": {},
                "devices": [],
            }

        # Return just the parts needed by the legacy method
        return {
            "account": all_data["account"],
            "devices": all_data["devices"],
        }
