"""Constants for Octopus Energy Germany."""

DOMAIN = "octopus_germany"

CONF_EMAIL = "email"
CONF_PASSWORD = "password"

UPDATE_INTERVAL = 2  # 2 minutes The Octopus Energy APIs have a rate limit of 100 calls per hour, which is shared among all calls including through the app.
