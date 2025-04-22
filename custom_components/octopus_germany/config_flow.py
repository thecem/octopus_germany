"""Config flow for Octopus Germany integration."""

import logging
import voluptuous as vol

from homeassistant import config_entries
from homeassistant.core import HomeAssistant
from homeassistant.helpers import aiohttp_client
from homeassistant.data_entry_flow import FlowResult

from .const import CONF_EMAIL, CONF_PASSWORD, DOMAIN
from .octopus_germany import OctopusGermany

_LOGGER = logging.getLogger(__name__)


async def validate_credentials(
    hass: HomeAssistant, email: str, password: str
) -> tuple[bool, str | None, str | None]:
    """Validate the user credentials by attempting API login."""
    octopus_api = OctopusGermany(email, password)
    try:
        login_success = await octopus_api.login()

        if not login_success:
            return False, "invalid_auth", None

        # Get the first account if login is successful
        accounts = await octopus_api.fetch_accounts_with_initial_data()

        if not accounts:
            return False, "no_accounts", None

        account_number = accounts[0]["number"]
        return True, None, account_number
    except Exception as ex:
        _LOGGER.exception("Unexpected error while validating credentials")
        return False, "unknown", None


class OctopusGermanyConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    """Handle a config flow for Octopus Germany."""

    VERSION = 1
    CONNECTION_CLASS = config_entries.CONN_CLASS_CLOUD_POLL

    async def async_step_user(self, user_input=None) -> FlowResult:
        """Handle the initial step."""
        errors = {}

        if user_input is not None:
            email = user_input[CONF_EMAIL]
            password = user_input[CONF_PASSWORD]

            valid, error, account_number = await validate_credentials(
                self.hass, email, password
            )

            if valid:
                # Add account number to the user input
                user_input["account_number"] = account_number
                return self.async_create_entry(
                    title=f"Octopus Germany ({email})", data=user_input
                )

            if error:
                errors["base"] = error

        return self.async_show_form(
            step_id="user",
            data_schema=vol.Schema(
                {
                    vol.Required(CONF_EMAIL): str,
                    vol.Required(CONF_PASSWORD): str,
                }
            ),
            errors=errors,
        )
