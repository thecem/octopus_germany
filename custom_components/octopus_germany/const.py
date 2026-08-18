"""Constants for the Octopus Germany integration."""

import os

DOMAIN = "octopus_germany"

CONF_EMAIL = "email"
CONF_PASSWORD = "password"

# Account/device polling (balances, dispatch, tariffs). Override in minutes
# with OCTOPUS_GERMANY_UPDATE_INTERVAL for local testing.
_DEFAULT_UPDATE_INTERVAL_MINUTES = 15
UPDATE_INTERVAL = int(
    os.environ.get("OCTOPUS_GERMANY_UPDATE_INTERVAL", _DEFAULT_UPDATE_INTERVAL_MINUTES)
)

# Smart meter interval data at Octopus is ingested in a batch every 3-4 hours.
MEASUREMENTS_UPDATE_INTERVAL_HOURS = 3

# Schema exploration (run once for debugging)
EXPLORE_SCHEMA_ONCE = True  # Set to True to run schema exploration once

# Token management
TOKEN_REFRESH_MARGIN = (
    300  # Refresh token if less than 300 seconds (5 minutes) remaining
)
TOKEN_AUTO_REFRESH_INTERVAL = 50 * 60  # Auto refresh token every 50 minutes

# Debug options
DEBUG_ENABLED = True
LOG_API_RESPONSES = False  # Set to True to log full API responses
LOG_TOKEN_RESPONSES = (
    False  # Set to True to log token-related responses (login, refresh)
)
