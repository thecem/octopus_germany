"""Constants for the Octopus Germany integration."""

DOMAIN = "octopus_germany"

CONF_EMAIL = "email"
CONF_PASSWORD = "password"

# Debug interval settings
UPDATE_INTERVAL = 1  # Update interval in minutes

# Token management
TOKEN_REFRESH_MARGIN = (
    300  # Refresh token if less than 300 seconds (5 minutes) remaining
)

# Debug options
DEBUG_ENABLED = True
LOG_API_RESPONSES = False  # Set to True to log full API responses

# Add a constant to track external update requests
EXTERNAL_UPDATE_COUNT = 0
LAST_EXTERNAL_UPDATE = None
