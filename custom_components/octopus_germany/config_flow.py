"""Config flow for Octopus Germany integration."""

import logging
import voluptuous as vol

from homeassistant import config_entries
from homeassistant.core import HomeAssistant

from .const import CONF_EMAIL, CONF_PASSWORD, DOMAIN
from .octopus_germany import OctopusGermany

_LOGGER = logging.getLogger(__name__)


async def validate_credentials(
    hass: HomeAssistant, email: str, password: str
) -> tuple[bool, str | None, dict | None]:
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

        # Return the complete first account data instead of just the number
        account_data = accounts[0]
        return True, None, account_data
    except Exception:
        _LOGGER.exception("Unexpected error while validating credentials")
        return False, "unknown", None


class OctopusGermanyConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    """Handle a config flow for Octopus Germany."""

    VERSION = 1
    CONNECTION_CLASS = config_entries.CONN_CLASS_CLOUD_POLL

    @staticmethod
    def async_get_options_flow(config_entry):
        """Get the options flow for this handler."""
        return OctopusGermanyOptionsFlow()

    async def async_step_user(self, user_input: dict | None = None):
        """Handle the initial step."""
        errors = {}

        if user_input is not None:
            email = user_input[CONF_EMAIL]
            password = user_input[CONF_PASSWORD]

            valid, error, account_data = await validate_credentials(
                self.hass, email, password
            )

            if valid:
                # Store the complete account data in user_input
                user_input["account_data"] = account_data
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

    async def async_step_reconfigure(self, user_input: dict | None = None):
        """Handle reconfiguration of the integration."""
        errors = {}

        # Get the entry from the context
        entry_id = self.context.get("entry_id")
        if not entry_id:
            # Try to get from unique_id if entry_id is not available
            entries = self.hass.config_entries.async_entries(DOMAIN)
            if not entries:
                return self.async_abort(reason="reconfigure_failed")
            reconfigure_entry = entries[0]  # Use first entry if only one exists
        else:
            reconfigure_entry = self.hass.config_entries.async_get_entry(entry_id)
            if reconfigure_entry is None:
                return self.async_abort(reason="reconfigure_failed")

        if user_input is not None:
            email = user_input[CONF_EMAIL]
            password = user_input[CONF_PASSWORD]

            # Validate the new credentials
            valid, error, account_data = await validate_credentials(
                self.hass, email, password
            )

            if valid:
                # Update the config entry with new credentials
                new_data = {
                    **reconfigure_entry.data,
                    CONF_EMAIL: email,
                    CONF_PASSWORD: password,
                }
                if account_data:
                    new_data["account_data"] = account_data

                return self.async_update_reload_and_abort(
                    reconfigure_entry,
                    data=new_data,
                    title=f"Octopus Germany ({email})",
                    reason="reconfigure_successful",
                )

            if error:
                errors["base"] = error

        # Pre-populate with current credentials
        current_email = reconfigure_entry.data.get(CONF_EMAIL, "")

        return self.async_show_form(
            step_id="reconfigure",
            data_schema=vol.Schema(
                {
                    vol.Required(CONF_EMAIL, default=current_email): str,
                    vol.Required(CONF_PASSWORD): str,
                }
            ),
            errors=errors,
            description_placeholders={
                "current_email": current_email,
            },
        )


class OctopusGermanyOptionsFlow(config_entries.OptionsFlow):
    """Handle an options flow for Octopus Germany."""

    async def async_step_init(self, user_input: dict | None = None):
        """Manage the options."""
        errors = {}

        if user_input is not None:
            email = user_input[CONF_EMAIL]
            password = user_input[CONF_PASSWORD]

            # Validate the new credentials
            valid, error, account_data = await validate_credentials(
                self.hass, email, password
            )

            if valid:
                # Update the config entry with new credentials
                new_data = {
                    **self.config_entry.data,
                    CONF_EMAIL: email,
                    CONF_PASSWORD: password,
                }
                if account_data:
                    new_data["account_data"] = account_data

                # Update the entry
                self.hass.config_entries.async_update_entry(
                    self.config_entry, data=new_data, title=f"Octopus Germany ({email})"
                )

                # Return updated options (empty since we store in data)
                return self.async_create_entry(title="", data={})

            if error:
                errors["base"] = error

        # Pre-populate with current credentials
        current_email = self.config_entry.data.get(CONF_EMAIL, "")

        return self.async_show_form(
            step_id="init",
            data_schema=vol.Schema(
                {
                    vol.Required(CONF_EMAIL, default=current_email): str,
                    vol.Required(CONF_PASSWORD): str,
                }
            ),
            errors=errors,
        )
