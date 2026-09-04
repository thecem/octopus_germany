"""Constants for the Octopus Germany integration."""

DOMAIN = "octopus_germany"

CONF_EMAIL = "email"
CONF_PASSWORD = "password"
CONF_UPDATE_INTERVAL = "update_interval"
CONF_INTELLIGENT_UPDATE_INTERVAL = "intelligent_update_interval"

# Default polling intervals in minutes
UPDATE_INTERVAL = 30
INTELLIGENT_UPDATE_INTERVAL = 3

# Schema exploration (run once for debugging)
EXPLORE_SCHEMA_ONCE = False  # Enable only while debugging the OEG schema

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
