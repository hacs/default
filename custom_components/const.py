"""Constants for COSA integration."""
from datetime import timedelta

DOMAIN = "cosa"
PLATFORM = "climate"

# API Configuration
API_BASE_URL = "https://kiwi-api.nuvia.com.tr/api"
API_TIMEOUT = 30

# API Endpoints
ENDPOINT_LOGIN = "/users/login"
ENDPOINT_GET_ENDPOINT = "/endpoints/getEndpoint"
ENDPOINT_SET_MODE = "/endpoints/setMode"
ENDPOINT_SET_TARGET_TEMPERATURES = "/endpoints/setTargetTemperatures"
ENDPOINT_LIST_ENDPOINTS = "/endpoints/getEndpoints"
ENDPOINT_USER_INFO = "/users/getInfo"

# Headers
USER_AGENT = "Cosa/1 CFNetwork/1498.700.2 Darwin/23.6.0"
CONTENT_TYPE = "application/json"

# Climate Modes
MODE_HOME = "home"
MODE_SLEEP = "sleep"
MODE_AWAY = "away"
MODE_CUSTOM = "custom"
MODE_FROZEN = "frozen"  # Off mode
MODE_AUTO = "auto"
MODE_SCHEDULE = "schedule"

# Home Assistant Climate Modes
HA_MODE_HEAT = "heat"
HA_MODE_OFF = "off"

# Preset Modes
PRESET_HOME = "home"
PRESET_SLEEP = "sleep"
PRESET_AWAY = "away"
PRESET_CUSTOM = "custom"
PRESET_AUTO = "auto"
PRESET_SCHEDULE = "schedule"

# Temperature limits
MIN_TEMP = 5
MAX_TEMP = 32
TEMP_STEP = 0.1

# Update interval
SCAN_INTERVAL = timedelta(seconds=60)  # seconds; DataUpdateCoordinator expects a timedelta

