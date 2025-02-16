from homeassistant import config_entries
import voluptuous as vol
from .const import DOMAIN, CONF_EMAIL, CONF_PASSWORD


class OctopusGermanyConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    """Handle a config flow for Octopus Germany."""

    VERSION = 1
    CONNECTION_CLASS = config_entries.CONN_CLASS_CLOUD_POLL

    async def async_step_user(self, user_input=None):
        """Handle the initial step."""
        errors = {}
        if user_input is not None:
            # Validate the user input here
            return self.async_create_entry(title="Octopus Germany", data=user_input)

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
