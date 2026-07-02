"""Constants for the OWON integration."""

from datetime import timedelta

DOMAIN = "owon"

MQTT_TOPIC_REPORT = "device/+/report"
# Retained metadata topic – device publishes once on connect with retain=true
MQTT_TOPIC_DEVICEINFO = "device/+/deviceinfo"
# HA sends this to ask the device to re-publish deviceinfo
MQTT_TOPIC_GET_DEVICEINFO_TPL = "device/{device_id}/getdeviceinfo"
QUERY_DEVICEINFO_PAYLOAD = '{"query":"deviceinfo"}'
OWON_APP_CLIENT_ID = "homeassistant"
MQTT_TOPIC_CONTROL_TPL = "api/device/{device_id}/{app_client_id}"
MQTT_TOPIC_REPLY = f"reply/device/+/{OWON_APP_CLIENT_ID}"
PCT341_QUERY_DPS: tuple[str, ...] = (
    "120",
    "121",
    "122",
    "123",
    "124",
    "125",
    "126",
    "127",
    "128",
    "129",
)

# Supported device model identifiers (as reported in deviceinfo "model" field)
DEVICE_MODEL_321 = "321"
DEVICE_MODEL_341 = "341"
# Model strings the firmware may send (prefix-match, case-insensitive)
DEVICE_MODEL_PREFIXES: dict[str, str] = {
    "PC321": DEVICE_MODEL_321,
    "PCT321": DEVICE_MODEL_321,
    "PC341": DEVICE_MODEL_341,
    "PCT341": DEVICE_MODEL_341,
}
DEFAULT_DEVICE_MODEL = DEVICE_MODEL_321

SIGNAL_NEW_DEVICE = f"{DOMAIN}_new_device"
SIGNAL_DEVICE_UPDATE = f"{DOMAIN}_device_update"
SIGNAL_DEVICE_MODEL_CHANGED = f"{DOMAIN}_device_model_changed"

DEVICE_OFFLINE_TIMEOUT = timedelta(seconds=300)
AVAILABILITY_CHECK_INTERVAL = timedelta(seconds=60)
# How often to re-query deviceinfo when the model is still unknown
DEVICEINFO_QUERY_INTERVAL = timedelta(seconds=60)
DP_QUERY_INTERVAL = timedelta(seconds=60)

MANUFACTURER = "OWON"
MODEL = "PCT321"

# Voltage phase sequence enum mapping
PHASE_SEQ_MAP: dict[int, str] = {
    0: "phase_missing",
    1: "abc_different",
    2: "abc_same",
    3: "ab_same_c_different",
    4: "bc_same_a_different",
    5: "ac_same_b_different",
}

# Device status bitmap bit definitions
DEVICE_STATUS_BITS: dict[int, str] = {
    0: "measurement_chip_error",
    1: "phase_a_ct_mismatch",
    2: "phase_b_ct_mismatch",
    3: "phase_c_ct_mismatch",
    4: "phase_a_voltage_disconnected",
    5: "phase_b_voltage_disconnected",
    6: "phase_c_voltage_disconnected",
}
