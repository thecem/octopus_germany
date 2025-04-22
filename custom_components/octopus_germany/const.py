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

# Create a debug constant to enable detailed logging
DEBUG_ENABLED = True

# Add a constant to track external update requests
EXTERNAL_UPDATE_COUNT = 0
LAST_EXTERNAL_UPDATE = None
