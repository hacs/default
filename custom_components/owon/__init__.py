"""The OWON meter WiFi MQTT integration (PCT321 / PCT341)."""

from __future__ import annotations

import json
import logging
from typing import Any

from homeassistant.components import mqtt
from homeassistant.components.mqtt import ReceiveMessage
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import Platform
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers import device_registry as dr
from homeassistant.helpers.dispatcher import async_dispatcher_send
from homeassistant.util import dt as dt_util

from .const import (
    DEFAULT_DEVICE_MODEL,
    DEVICE_MODEL_341,
    DEVICE_MODEL_PREFIXES,
    DEVICE_OFFLINE_TIMEOUT,
    DEVICEINFO_QUERY_INTERVAL,
    DOMAIN,
    DP_QUERY_INTERVAL,
    MQTT_TOPIC_CONTROL_TPL,
    MQTT_TOPIC_DEVICEINFO,
    MQTT_TOPIC_GET_DEVICEINFO_TPL,
    MQTT_TOPIC_REPLY,
    MQTT_TOPIC_REPORT,
    OWON_APP_CLIENT_ID,
    PCT341_QUERY_DPS,
    QUERY_DEVICEINFO_PAYLOAD,
    SIGNAL_DEVICE_MODEL_CHANGED,
    SIGNAL_DEVICE_UPDATE,
    SIGNAL_NEW_DEVICE,
)

_LOGGER = logging.getLogger(__name__)

PLATFORMS = [Platform.SENSOR]

type OwonMeterConfigEntry = ConfigEntry[OwonMeterDataManager]


def _log_mqtt_raw(msg: ReceiveMessage) -> None:
    """Log raw MQTT message for troubleshooting."""
    _LOGGER.info(
        "[MQTT RX] Topic: %s QoS: %s Retain: %s Payload: %s",
        msg.topic,
        getattr(msg, "qos", "?"),
        getattr(msg, "retain", "?"),
        msg.payload,
    )


def _log_mqtt_tx(topic: str, payload: str, qos: int, retain: bool) -> None:
    """Log raw outbound MQTT publish for troubleshooting."""
    _LOGGER.info(
        "[MQTT TX] Topic: %s QoS: %s Retain: %s Payload: %s",
        topic,
        qos,
        retain,
        payload,
    )


def _split_top_level_csv(text: str) -> list[str]:
    """Split comma-separated text while respecting quoted strings."""
    parts: list[str] = []
    buf: list[str] = []
    in_quotes = False
    quote_char = ""
    escape = False

    for ch in text:
        if escape:
            buf.append(ch)
            escape = False
            continue
        if in_quotes and ch == "\\":
            buf.append(ch)
            escape = True
            continue
        if ch in ('"', "'"):
            if not in_quotes:
                in_quotes = True
                quote_char = ch
            elif ch == quote_char:
                in_quotes = False
                quote_char = ""
            buf.append(ch)
            continue
        if ch == "," and not in_quotes:
            parts.append("".join(buf).strip())
            buf = []
            continue
        buf.append(ch)

    tail = "".join(buf).strip()
    if tail:
        parts.append(tail)
    return parts


def _parse_payload_object(payload_raw: str) -> dict[str, Any] | None:
    """Parse payload object with a tolerant fallback for non-standard JSON."""
    try:
        payload = json.loads(payload_raw)
    except (json.JSONDecodeError, TypeError):
        payload = None

    if isinstance(payload, dict):
        return payload

    text = str(payload_raw).strip()
    if not (text.startswith("{") and text.endswith("}")):
        return None

    body = text[1:-1].strip()
    if body == "":
        return {}

    result: dict[str, Any] = {}
    for item in _split_top_level_csv(body):
        if ":" not in item:
            return None

        key_raw, value_raw = item.split(":", 1)
        key = key_raw.strip().strip('"').strip("'")
        if not key:
            return None

        value_text = value_raw.strip()
        if value_text == "":
            result[key] = ""
            continue

        try:
            result[key] = json.loads(value_text)
            continue
        except (json.JSONDecodeError, TypeError):
            pass

        if (
            len(value_text) >= 2
            and value_text[0] in ('"', "'")
            and value_text[-1] == value_text[0]
        ):
            result[key] = value_text[1:-1]
        else:
            # Accept firmware's relaxed JSON style: bareword values become strings.
            result[key] = value_text

    return result


class OwonMeterDataManager:
    """Manage OWON meter device data from MQTT."""

    def __init__(self, hass: HomeAssistant) -> None:
        """Initialize the data manager."""
        self.hass = hass
        self.devices: dict[str, dict[str, Any]] = {}
        self.last_seen: dict[str, Any] = {}
        # model identifier per device: "321" | "341" (default: DEFAULT_DEVICE_MODEL)
        self.device_models: dict[str, str] = {}
        # devices with confirmed model from deviceinfo payload
        self.model_confirmed: set[str] = set()
        # raw deviceinfo payload fields per device
        self.device_info: dict[str, dict[str, Any]] = {}
        # last time a getdeviceinfo query was sent per device
        self.deviceinfo_queried: dict[str, Any] = {}
        # last time a missing DP query was sent per device/dp
        self.dp_queried: dict[str, dict[str, Any]] = {}

    @staticmethod
    def _resolve_model(model_str: str) -> str:
        """Map a firmware model string (e.g. 'PC341') to '321' or '341'."""
        upper = model_str.upper()
        for prefix, model_id in DEVICE_MODEL_PREFIXES.items():
            if upper.startswith(prefix.upper()):
                return model_id
        return DEFAULT_DEVICE_MODEL

    def get_device_model(self, device_id: str) -> str:
        """Return resolved model identifier for a device (default: 321)."""
        return self.device_models.get(device_id, DEFAULT_DEVICE_MODEL)

    @callback
    def handle_deviceinfo(self, msg: ReceiveMessage) -> None:
        """Handle retained deviceinfo message."""
        _log_mqtt_raw(msg)
        parts = msg.topic.split("/")
        if len(parts) != 3:
            return
        device_id = parts[1]
        info = _parse_payload_object(msg.payload)
        if info is None:
            _LOGGER.warning(
                "Invalid deviceinfo JSON from %s: %s", device_id, msg.payload
            )
            return
        if not isinstance(info, dict):
            return

        self.device_info[device_id] = info
        # Store device_id itself so sensors can read it via deviceinfo_key
        self.device_info[device_id]["device_id"] = device_id
        self.model_confirmed.add(device_id)
        raw_model = str(info.get("model", ""))
        resolved = self._resolve_model(raw_model) if raw_model else DEFAULT_DEVICE_MODEL
        old_model = self.device_models.get(device_id)
        if old_model != resolved:
            self.device_models[device_id] = resolved
            _LOGGER.info(
                "OWON device %s model identified as %s (raw: '%s')",
                device_id,
                resolved,
                raw_model,
            )
            # Notify sensor platform to recreate entities for the new model
            async_dispatcher_send(
                self.hass, f"{SIGNAL_DEVICE_MODEL_CHANGED}_{device_id}"
            )
        # Update device registry so sw_version is shown in HA device info page
        fw_version = info.get("fw_version")
        if fw_version:
            dev_reg = dr.async_get(self.hass)
            device_entry = dev_reg.async_get_device(identifiers={(DOMAIN, device_id)})
            if device_entry is not None:
                dev_reg.async_update_device(device_entry.id, sw_version=str(fw_version))
        # Always notify entities so device registry picks up fw_version changes
        async_dispatcher_send(self.hass, f"{SIGNAL_DEVICE_UPDATE}_{device_id}")
        self._maybe_query_missing_dps(device_id)

    async def async_query_deviceinfo(self, device_id: str) -> None:
        """Ask the device to re-publish its deviceinfo."""
        topic = MQTT_TOPIC_GET_DEVICEINFO_TPL.format(device_id=device_id)
        qos = 0
        retain = False
        _log_mqtt_tx(topic, QUERY_DEVICEINFO_PAYLOAD, qos, retain)
        await mqtt.async_publish(
            self.hass, topic, QUERY_DEVICEINFO_PAYLOAD, qos, retain
        )
        _LOGGER.debug("Sent getdeviceinfo query to %s", device_id)

    async def async_query_dp(self, device_id: str, dp: str) -> None:
        """Ask the device to report a specific DP value."""
        topic = MQTT_TOPIC_CONTROL_TPL.format(
            device_id=device_id, app_client_id=OWON_APP_CLIENT_ID
        )
        payload = f'{{"{dp}"}}'
        qos = 0
        retain = False
        _log_mqtt_tx(topic, payload, qos, retain)
        await mqtt.async_publish(self.hass, topic, payload, qos, retain)
        _LOGGER.debug("Sent DP%s query to %s via control topic", dp, device_id)

    @callback
    def _maybe_query_missing_dps(self, device_id: str) -> None:
        """Actively query missing PCT341 DPs with interval throttling."""
        if self.get_device_model(device_id) != DEVICE_MODEL_341:
            return
        data = self.devices.get(device_id, {})
        now = dt_util.utcnow()
        dp_history = self.dp_queried.setdefault(device_id, {})

        for dp in PCT341_QUERY_DPS:
            value = data.get(dp)
            if value is not None and value != "":
                continue

            last_q = dp_history.get(dp)
            if last_q is not None and (now - last_q) < DP_QUERY_INTERVAL:
                continue

            dp_history[dp] = now
            self.hass.async_create_task(self.async_query_dp(device_id, dp))

    @callback
    def handle_reply(self, msg: ReceiveMessage) -> None:
        """Handle reply payloads from device control topics."""
        _log_mqtt_raw(msg)
        parts = msg.topic.split("/")
        if len(parts) != 4:
            _LOGGER.debug("Ignoring unexpected reply topic format: %s", msg.topic)
            return
        _, _, device_id, app_client_id = parts
        if app_client_id != OWON_APP_CLIENT_ID:
            _LOGGER.debug(
                "Ignoring reply for unsupported app client %s on device %s",
                app_client_id,
                device_id,
            )
            return

        payload = _parse_payload_object(msg.payload)
        if payload is None or not isinstance(payload, dict):
            _LOGGER.warning(
                "Invalid reply payload from device %s: %s", device_id, msg.payload
            )
            return

        if device_id not in self.devices:
            self.devices[device_id] = {}

        self.last_seen[device_id] = dt_util.utcnow()
        for key, value in payload.items():
            self.devices[device_id][str(key)] = value

        if "128" in payload:
            _LOGGER.info("Received DP128 reply for %s: %s", device_id, payload["128"])

        async_dispatcher_send(self.hass, f"{SIGNAL_DEVICE_UPDATE}_{device_id}")
        self._maybe_query_missing_dps(device_id)

    @callback
    def is_device_available(self, device_id: str) -> bool:
        """Return whether a device is still considered online."""
        last_seen = self.last_seen.get(device_id)
        return last_seen is not None and (
            dt_util.utcnow() - last_seen <= DEVICE_OFFLINE_TIMEOUT
        )

    @callback
    def handle_message(self, msg: ReceiveMessage) -> None:
        """Handle incoming MQTT message from device."""
        _log_mqtt_raw(msg)

        # Topic format: device/{deviceid}/report
        parts = msg.topic.split("/")
        if len(parts) != 3:
            _LOGGER.debug("Ignoring unexpected topic format: %s", msg.topic)
            return

        device_id = parts[1]

        payload = _parse_payload_object(msg.payload)
        if payload is None:
            _LOGGER.warning(
                "Invalid JSON payload from device %s: %s", device_id, msg.payload
            )
            return

        # Device firmware occasionally emits relaxed JSON (e.g. unquoted strings).
        # Keep processing those reports so entities can still be populated.
        if isinstance(msg.payload, str):
            with_json = False
            try:
                with_json = isinstance(json.loads(msg.payload), dict)
            except (json.JSONDecodeError, TypeError):
                with_json = False
            if not with_json:
                _LOGGER.warning(
                    "Non-standard JSON payload accepted from device %s: %s",
                    device_id,
                    msg.payload,
                )

        if not isinstance(payload, dict):
            _LOGGER.debug(
                "Ignoring non-object payload from device %s (type=%s)",
                device_id,
                type(payload).__name__,
            )
            return

        summary_keys = sorted(payload.keys(), key=str)
        summary_pairs = []
        for key in summary_keys[:6]:
            value = payload[key]
            value_preview = str(value)
            if len(value_preview) > 24:
                value_preview = f"{value_preview[:24]}..."
            summary_pairs.append(f"{key}={value_preview}")
        _LOGGER.debug(
            "Payload summary for %s: keys=%s preview=%s",
            device_id,
            len(payload),
            ", ".join(summary_pairs),
        )

        is_new = device_id not in self.devices
        if is_new:
            self.devices[device_id] = {}
            # Default to 321 until deviceinfo arrives or is queried
            self.device_models.setdefault(device_id, DEFAULT_DEVICE_MODEL)

        self.last_seen[device_id] = dt_util.utcnow()

        # Store DP values with string keys
        for key, value in payload.items():
            self.devices[device_id][str(key)] = value

        _LOGGER.debug("Updated device %s with %s datapoints", device_id, len(payload))

        if is_new:
            _LOGGER.info("Discovered new OWON meter device: %s", device_id)
            async_dispatcher_send(self.hass, SIGNAL_NEW_DEVICE, device_id)

        # Re-query deviceinfo on every report until the model is confirmed.
        # This handles devices that don't publish with retain=true and may have
        # been offline when the initial query was sent.
        if device_id not in self.model_confirmed:
            last_q = self.deviceinfo_queried.get(device_id)
            if (
                last_q is None
                or (dt_util.utcnow() - last_q) >= DEVICEINFO_QUERY_INTERVAL
            ):
                self.deviceinfo_queried[device_id] = dt_util.utcnow()
                self.hass.async_create_task(self.async_query_deviceinfo(device_id))

        self._maybe_query_missing_dps(device_id)

        async_dispatcher_send(self.hass, f"{SIGNAL_DEVICE_UPDATE}_{device_id}")
        _LOGGER.debug("Dispatched device update signal for %s", device_id)


async def async_setup_entry(hass: HomeAssistant, entry: OwonMeterConfigEntry) -> bool:
    """Set up OWON Meter PCT321 from a config entry."""
    _LOGGER.debug("Setting up OWON Meter config entry %s", entry.entry_id)

    if not await mqtt.async_wait_for_mqtt_client(hass):
        _LOGGER.error("MQTT client not available")
        return False

    manager = OwonMeterDataManager(hass)
    entry.runtime_data = manager

    _LOGGER.info("Subscribing to OWON MQTT topic: %s", MQTT_TOPIC_REPORT)
    entry.async_on_unload(
        await mqtt.async_subscribe(hass, MQTT_TOPIC_REPORT, manager.handle_message, 0)
    )
    # Subscribe to retained deviceinfo topic so model is known as early as possible
    entry.async_on_unload(
        await mqtt.async_subscribe(
            hass, MQTT_TOPIC_DEVICEINFO, manager.handle_deviceinfo, 0
        )
    )
    entry.async_on_unload(
        await mqtt.async_subscribe(hass, MQTT_TOPIC_REPLY, manager.handle_reply, 0)
    )

    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    _LOGGER.debug("OWON Meter config entry %s setup completed", entry.entry_id)

    return True


async def async_unload_entry(hass: HomeAssistant, entry: OwonMeterConfigEntry) -> bool:
    """Unload a config entry."""
    _LOGGER.debug("Unloading OWON Meter config entry %s", entry.entry_id)
    return await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
