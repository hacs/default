"""Config flow for Dercvne Bus integration."""

import asyncio
import glob
import logging
import os
import re
import uuid
from typing import Any, Dict, List, Optional

import voluptuous as vol
from homeassistant.helpers import config_validation as cv
from homeassistant import config_entries
from homeassistant.core import callback

from .const import (
    DOMAIN,
    CONN_TYPE_SERIAL,
    CONN_TYPE_TCP,
    DEFAULT_PORT,
    DEFAULT_BAUDRATE,
    DEVICE_TYPE_RELAY,
    DEVICE_TYPE_LIGHT_SINGLE,
    DEVICE_TYPE_LIGHT_CCT,
    DEVICE_TYPE_DM2_SINGLE,
    DEVICE_TYPE_DM2_CCT,
    DEVICE_TYPE_COVER,
    DEVICE_TYPE_DALI_SCENE,
    DEVICE_TYPE_KEYPAD,
    DEVICE_TYPE_OCCUPANCY,
    DEVICE_TYPE_IO_MODULE,
    DEVICE_TYPE_THERMOSTAT,
    DEVICE_TYPE_LIGHT_RGBCW,
    DEVICE_TYPE_VRV_CONTROLLER,
    DEVICE_TYPE_VRV_INDOOR,
    VRV_DEFAULT_PORT,
    IO_MODULE_CHANNEL_COUNT,
    SENSOR_MODEL_NAME,
    SENSOR_SEARCH_CMD,
    SENSOR_SEARCH_RESP_LEN,
    SENSOR_STATUS_FRAME_LEN,
    GROUP_PATTERN,
    ADDRESS_PATTERN,
    SICOO_ADDR_MIN,
    SICOO_ADDR_MAX,
)

_LOGGER = logging.getLogger(__name__)

DEVICE_TYPE_OPTIONS = {
    DEVICE_TYPE_RELAY: "继电器 (Relay / Switch)",
    DEVICE_TYPE_VRV_INDOOR: "VRV空调内机 (CoolMaster)",
    DEVICE_TYPE_LIGHT_SINGLE: "DALI 单色温灯 (DALI Single CT)",
    DEVICE_TYPE_LIGHT_CCT: "DALI 双色温灯 (DALI Dual CT)",
    DEVICE_TYPE_DM2_SINGLE: "DM2 单色温灯 (DM2 Single CT)",
    DEVICE_TYPE_DM2_CCT: "DM2 双色温灯 (DM2 Dual CT)",
    DEVICE_TYPE_LIGHT_RGBCW: "DM2 RGBCW 灯 (RGBCW Light)",
    DEVICE_TYPE_COVER: "窗帘 (Cover / Curtain)",
    DEVICE_TYPE_DALI_SCENE: "DALI场景 (DALI Scene >D)",
    DEVICE_TYPE_KEYPAD: "485面板 (Keypad Panel)",
    DEVICE_TYPE_OCCUPANCY: "感应器 SH-808R-S",
    DEVICE_TYPE_IO_MODULE: "4路IO模块 (干接点输入)",
    DEVICE_TYPE_THERMOSTAT: "温控面板 X1-29-S (水机/地暖/新风)",
}

DEVICE_TYPE_LABELS = {
    DEVICE_TYPE_RELAY: "继电器 (Relay / Switch)",
    DEVICE_TYPE_LIGHT_SINGLE: "DALI单色温灯",
    DEVICE_TYPE_LIGHT_CCT: "DALI双色温灯",
    DEVICE_TYPE_DM2_SINGLE: "DM2单色温灯",
    DEVICE_TYPE_DM2_CCT: "DM2双色温灯",
    DEVICE_TYPE_COVER: "窗帘 (Cover / Curtain)",
    DEVICE_TYPE_DALI_SCENE: "DALI场景 (DALI Scene >D)",
    DEVICE_TYPE_KEYPAD: "485面板 (Keypad Panel)",
    DEVICE_TYPE_OCCUPANCY: "感应器 SH-808R-S",
    DEVICE_TYPE_IO_MODULE: "4路IO模块 (干接点输入)",
    DEVICE_TYPE_VRV_CONTROLLER: "VRV空调控制器 (CoolMaster)",
    DEVICE_TYPE_VRV_INDOOR: "VRV室内机",
    DEVICE_TYPE_THERMOSTAT: "温控面板 X1-29-S",
    DEVICE_TYPE_LIGHT_RGBCW: "DM2 RGBCW灯",
}

CONN_TYPE_OPTIONS = {
    CONN_TYPE_TCP: "TCP 网络",
    CONN_TYPE_SERIAL: "串口 RS485",
}


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _new_id() -> str:
    return uuid.uuid4().hex[:12]


def _ensure_device_ids(devices: list) -> list:
    """Ensure every device has a stable 'id' field."""
    for dev in devices:
        if "id" not in dev or not dev["id"]:
            dev["id"] = _new_id()
    return devices


def _ensure_connection_ids(connections: list) -> list:
    """Ensure every connection has a stable 'id' field."""
    for conn in connections:
        if "id" not in conn or not conn["id"]:
            conn["id"] = _new_id()
    return connections


def _conn_label(conn: dict) -> str:
    """Short display label for a connection."""
    name = conn.get("name", "未命名")
    if conn.get("connection_type") == CONN_TYPE_TCP:
        host = conn.get("tcp_host", "?")
        port = conn.get("tcp_port", "?")
        return f"{name}  (TCP {host}:{port})"
    else:
        port = conn.get("serial_port", "?")
        baud = conn.get("baudrate", DEFAULT_BAUDRATE)
        return f"{name}  (串口 {port} @{baud})"


def _conn_label_for_vrv(vrv: dict, connections: list) -> str:
    """Display label for a VRV controller: connection name if available, else host:port."""
    conn_id = vrv.get("connection_id", "")
    conn = next((c for c in connections if c["id"] == conn_id), None)
    if conn:
        return _conn_label(conn)
    return f"{vrv.get('host', '?')}:{vrv.get('port', '?')}"


def _device_info(dev: dict, connections: list = None) -> str:
    """Format device info for display."""
    label = DEVICE_TYPE_LABELS.get(dev.get("device_type", ""), dev.get("device_type", "?"))
    if dev.get("device_type") == DEVICE_TYPE_KEYPAD:
        pa = dev.get("panel_address", "?")
        base = f"{dev['name']} [{label}] PA={pa}"
    elif dev.get("device_type") == DEVICE_TYPE_IO_MODULE:
        addr = dev.get("address", "?")
        base = f"{dev['name']} [{label}] A={addr}"
    elif dev.get("device_type") == DEVICE_TYPE_VRV_CONTROLLER:
        host = dev.get("host", "?")
        port = dev.get("port", "?")
        base = f"{dev['name']} [{label}] {host}:{port}"
    elif dev.get("device_type") == DEVICE_TYPE_VRV_INDOOR:
        unit_id = dev.get("unit_id", "?")
        base = f"{dev['name']} [{label}] ID={unit_id}"
    elif dev.get("device_type") == DEVICE_TYPE_DALI_SCENE:
        p = dev.get("port", "0")
        g = dev.get("group", "00")
        s = dev.get("scene", "09")
        base = f"{dev['name']} [{label}] 路={p} 组={g} 场景={s}"
    elif dev.get("device_type") == DEVICE_TYPE_THERMOSTAT:
        parts = []
        if dev.get("ac", {}).get("enabled"):
            parts.append(f"空调({dev['ac'].get('address', '?')})")
        if dev.get("floor_heating", {}).get("enabled"):
            parts.append(f"地暖({dev['floor_heating'].get('address', '?')})")
        if dev.get("fresh_air", {}).get("enabled"):
            parts.append(f"新风({dev['fresh_air'].get('address', '?')})")
        base = f"{dev['name']} [{label}] " + " ".join(parts)
    else:
        base = f"{dev['name']} [{label}] G={dev['group']} A={dev['address']}"
    if connections:
        conn_id = dev.get("connection_id", "")
        conn = next((c for c in connections if c["id"] == conn_id), None)
        if conn:
            base += f" 连接={conn['name']}"
    return base


def _get_serial_ports(current_port: str = None, all_connections: list = None) -> dict:
    """Scan system for serial ports and return {path: label} for dropdown.

    Priority:
    1. /dev/serial/by-id/  (stable, device-bound, preferred)
    2. /dev/ttyUSB*          (unstable, order may change after reboot)
    3. /dev/ttyACM*         (CDC ACM devices, e.g. Arduino)

    Ports already used by OTHER connections are marked with "（已占用 - 连接名）".
    The current connection's own port is always shown normally (even if
    the device is currently unplugged — we still show it so the user
    can keep the existing config).
    """
    import os
    import glob

    all_connections = all_connections or []

    # Build {realpath: conn_name} for ports used by OTHER connections
    used_real = {}  # realpath -> conn_name
    used_orig = {}  # original path -> conn_name
    for c in all_connections:
        if c.get("connection_type") == CONN_TYPE_SERIAL:
            p = c.get("serial_port", "")
            if p:
                used_orig[p] = c.get("name", "?")
                try:
                    used_real[os.path.realpath(p)] = c.get("name", "?")
                except OSError:
                    pass

    ports = {}  # path -> label
    ports_real = {}  # realpath -> path (for deduplication)

    # Helper: check if a path (or its realpath) is used by others
    def _is_used(path: str, real: str) -> tuple:
        if path in used_orig and path != (current_port or ""):
            return True, used_orig[path]
        if real in used_real and real not in (os.path.realpath(current_port or ""), ""):
            return True, used_real[real]
        return False, ""

    # ---- 1. /dev/serial/by-id/ (preferred) ----
    by_id_dir = "/dev/serial/by-id"
    if os.path.exists(by_id_dir):
        try:
            for name in sorted(os.listdir(by_id_dir)):
                path = os.path.join(by_id_dir, name)
                try:
                    real = os.path.realpath(path)
                except OSError:
                    real = path
                label = name
                is_used, conn_name = _is_used(path, real)
                if is_used and path != (current_port or ""):
                    label += f"（已占用 - {conn_name}）"
                ports[path] = label
                ports_real[real] = path
        except OSError:
            pass

    # ---- 2. Fallback: /dev/ttyUSB* and /dev/ttyACM* ----
    if not ports:
        for pattern in ["/dev/ttyUSB*", "/dev/ttyACM*"]:
            for path in sorted(glob.glob(pattern)):
                try:
                    real = os.path.realpath(path)
                except OSError:
                    real = path
                if real in ports_real:
                    continue  # already have this device via by-id
                label = path
                is_used, conn_name = _is_used(path, real)
                if is_used:
                    label += f"（已占用 - {conn_name}）"
                ports[path] = label
                ports_real[real] = path

    # ---- 3. Always include the current port (device may be unplugged) ----
    if current_port and current_port not in ports:
        try:
            real = os.path.realpath(current_port)
            if real in ports_real:
                # Device is actually present, just via a different path
                # Update the existing entry to show the current path as alias
                existing = ports_real[real]
                ports[existing] += f"（别名：{current_port}）"
            else:
                ports[current_port] = f"{current_port}（设备未连接）"
        except OSError:
            ports[current_port] = f"{current_port}（设备未连接）"

    return ports


def _validate_group(group: str) -> str:
    """Validate a group is a single hex digit 0-F.

    Returns the canonical (uppercase) form, or raises ValueError.
    """
    s = str(group).strip().upper()
    if not GROUP_PATTERN.match(s):
        raise ValueError(f"Group must be a single hex digit 0-F, got: {group}")
    return s


def _check_duplicate(devices: list, connection_id: str, group: str, address: str,
                     exclude_device_id: str = None) -> str:
    """Check if (group, address) already exists on the same connection.

    Scans all device types (relay, light, cover, scene, keypad functions).
    For keypad devices, also checks lock/sleep/backlight function addresses.

    Returns the conflicting device name, or empty string if no conflict.
    """
    g = group.strip().upper()
    a = address.strip().upper()

    for dev in devices:
        if exclude_device_id and dev.get("id") == exclude_device_id:
            continue
        if dev.get("connection_id") != connection_id:
            continue

        # Check main group+address for non-keypad, non-dali_scene devices
        dt = dev.get("device_type", "")
        if dt != DEVICE_TYPE_KEYPAD and dt != DEVICE_TYPE_DALI_SCENE:
            if dev.get("group", "").strip().upper() == g and dev.get("address", "").strip().upper() == a:
                return dev["name"]

        # For keypad devices, check function addresses
        if dt == DEVICE_TYPE_KEYPAD:
            for prefix, label in [("lock", "儿童锁"), ("sleep", "休眠"), ("backlight", "背光")]:
                fg = dev.get(f"{prefix}_group", "").strip().upper()
                fa = dev.get(f"{prefix}_address", "").strip().upper()
                if fg == g and fa == a:
                    return f"{dev['name']} ({label})"

    return ""


def _check_dali_scene_duplicate(devices: list, connection_id: str,
                                 port: str, group: str, scene: str,
                                 exclude_device_id: str = None) -> str:
    """Check if (port, group, scene) triplet already exists for a dali_scene.

    Returns the conflicting device name, or empty string if no conflict.
    """
    p = port.strip().upper()
    g = group.strip().upper()
    s = scene.strip().upper()

    for dev in devices:
        if dev.get("device_type") != DEVICE_TYPE_DALI_SCENE:
            continue
        if exclude_device_id and dev.get("id") == exclude_device_id:
            continue
        if dev.get("connection_id") != connection_id:
            continue
        if (dev.get("port", "").strip().upper() == p
                and dev.get("group", "").strip().upper() == g
                and dev.get("scene", "").strip().upper() == s):
            return dev["name"]

    return ""





def _check_address_conflict(devices: list, connection_id: str,
                           address: str, exclude_device_id: str = None) -> str:
    """Check if address (00-FF) conflicts with ANY device on the same connection.

    Scans all device types that use 00-FF address format:
    - relay/light/cover: main address field
    - keypad: panel_address field
    - io_module: address field

    Returns the conflicting device name, or empty string if no conflict.
    """
    a = address.strip().upper()
    for dev in devices:
        if exclude_device_id and dev.get("id") == exclude_device_id:
            continue
        if dev.get("connection_id") != connection_id:
            continue
        dt = dev.get("device_type", "")
        # Check relay/light/cover address
        if dt not in (DEVICE_TYPE_KEYPAD, DEVICE_TYPE_DALI_SCENE,
                       DEVICE_TYPE_OCCUPANCY, DEVICE_TYPE_IO_MODULE,
                       DEVICE_TYPE_THERMOSTAT,
    DEVICE_TYPE_LIGHT_RGBCW, DEVICE_TYPE_VRV_CONTROLLER,
                       DEVICE_TYPE_VRV_INDOOR):
            if dev.get("address", "").strip().upper() == a:
                return dev["name"]
        # Check keypad panel_address
        if dt == DEVICE_TYPE_KEYPAD:
            if dev.get("panel_address", "").strip().upper() == a:
                return f"{dev['name']} (面板地址)"
        # Check io_module address
        if dt == DEVICE_TYPE_IO_MODULE:
            if dev.get("address", "").strip().upper() == a:
                return dev["name"]
    return ""


async def _search_occupancy_sensors(hass, conn_cfg, exclude_addresses: set = None) -> list:
    """Search for SH-808R-S sensors on the bus.

    Sends SENSOR_SEARCH_CMD and parses 17-byte response frames.
    Filters out addresses present in exclude_addresses.
    Returns list of dicts: [{"address": "XXYY", "type": 1}, ...]
    """
    from .transport import create_transport

    results = []
    exclude = exclude_addresses or set()
    try:
        transport = create_transport(hass, conn_cfg)
        await transport.connect()
        # Send search command
        await transport.send_bytes(SENSOR_SEARCH_CMD)
        await asyncio.sleep(2)  # Wait for responses

        # Try to read responses (may be multiple sensors)
        raw = await transport.read(1024)
        if raw and len(raw) >= SENSOR_SEARCH_RESP_LEN:
            # Parse 17-byte response frames
            # Address at bytes 11-12 (0-indexed), convert to hex string XXYY
            for i in range(0, len(raw) - SENSOR_SEARCH_RESP_LEN + 1, SENSOR_SEARCH_RESP_LEN):
                frame = raw[i:i+SENSOR_SEARCH_RESP_LEN]
                if len(frame) == SENSOR_SEARCH_RESP_LEN:
                    addr_bytes = frame[11:13]  # bytes 11,12
                    addr_str = addr_bytes.hex().upper()  # -> "XXYY"
                    if addr_str in exclude:
                        continue  # Skip already-added sensors
                    sensor_type = frame[13] if len(frame) > 13 else 1
                    results.append({"address": addr_str, "type": sensor_type})
        await transport.disconnect()
    except Exception as e:
        _LOGGER.warning("Sensor search failed on %s: %s", conn_cfg.get("name", "?"), e)
    return results


# ---------------------------------------------------------------------------
# Config Flow (first-time setup)
# ---------------------------------------------------------------------------

class DALIConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    """Handle a config flow for Dercvne Bus."""

    VERSION = 1

    def __init__(self):
        self._connections: List[dict] = []  # list of connection dicts
        self._devices: List[dict] = []
        self._current_connection_id: Optional[str] = None  # used when adding conn during setup
        self._keypad_temp: Optional[dict] = None  # partial keypad data between steps
        self._device_temp: Optional[dict] = None  # partial non-keypad data between steps
        self._dup_device_name: Optional[str] = None

    def _build_serial_port_schema(self, errors: dict, current_port: str = None):
        """Build the vol validator for the serial-port dropdown field.

        Scans available serial ports and returns a ``vol.In(...)`` validator,
        or ``str`` when none are found (recording a ``no_serial_ports`` error).
        Shared by every connection step so the scan/presentation logic lives
        in exactly one place.
        """
        port_options = _get_serial_ports(
            current_port=current_port, all_connections=self._connections
        )
        if not port_options:
            errors["base"] = "no_serial_ports"
            return str
        return vol.In(port_options)

    # ---- step 1: add first connection ----

    async def async_step_user(self, user_input: Optional[Dict[str, Any]] = None):
        """Start: ask connection type for the first connection."""
        if user_input is not None:
            self._current_connection_id = _new_id()
            self._pending_conn_type = user_input["connection_type"]
            return await self.async_step_connection_params()

        return self.async_show_form(
            step_id="user",
            data_schema=vol.Schema({
                vol.Required("connection_type"): vol.In(CONN_TYPE_OPTIONS),
            }),
        )

    async def async_step_connection_params(self, user_input: Optional[Dict[str, Any]] = None):
        """Enter connection parameters - show ONLY fields for selected type."""
        errors = {}

        if user_input is not None:
            conn_type = user_input["connection_type"]
            conn = {
                "id": self._current_connection_id or _new_id(),
                "name": user_input.get("name", "连接1"),
                "connection_type": conn_type,
            }
            if conn_type == CONN_TYPE_TCP:
                conn["tcp_host"] = user_input.get("tcp_host", "")
                conn["tcp_port"] = user_input.get("tcp_port", DEFAULT_PORT)
                conn["serial_port"] = ""
                conn["baudrate"] = DEFAULT_BAUDRATE
            else:
                conn["serial_port"] = user_input.get("serial_port", "")
                conn["baudrate"] = user_input.get("baudrate", DEFAULT_BAUDRATE)
                conn["tcp_host"] = ""
                conn["tcp_port"] = DEFAULT_PORT
            self._connections.append(conn)
            return await self.async_step_device()

        pending_type = self._pending_conn_type or CONN_TYPE_TCP

        if pending_type == CONN_TYPE_TCP:
            # TCP only
            schema = vol.Schema({
                vol.Required("name", default="连接1"): str,
                vol.Required("connection_type", default=pending_type): vol.In(CONN_TYPE_OPTIONS),
                vol.Required("tcp_host"): str,
                vol.Required("tcp_port", default=DEFAULT_PORT): int,
            })
        else:
            # Serial only
            port_validator = self._build_serial_port_schema(errors)

            schema = vol.Schema({
                vol.Required("name", default="连接1"): str,
                vol.Required("connection_type", default=pending_type): vol.In(CONN_TYPE_OPTIONS),
                vol.Required("serial_port"): port_validator,
                vol.Optional("baudrate", default=DEFAULT_BAUDRATE): int,
            })

        return self.async_show_form(
            step_id="connection_params",
            data_schema=schema,
            errors=errors,
        )

    # ---- step 2: add devices ----

    async def async_step_device(self, user_input: Optional[Dict[str, Any]] = None):
        """Add a device — first step: pick type + name (no group/address yet)."""
        errors = {}
        conn_options = {c["id"]: _conn_label(c) for c in self._connections}

        if user_input is not None:
            device_type = user_input["device_type"]
            conn_id = user_input["connection_id"]

            if device_type == DEVICE_TYPE_OCCUPANCY:
                self._device_temp = {
                    "connection_id": conn_id,
                    "name": user_input.get("name", ""),
                    "device_type": DEVICE_TYPE_OCCUPANCY,
                }
                return await self.async_step_device_occupancy()

            if device_type == DEVICE_TYPE_IO_MODULE:
                self._device_temp = {
                    "connection_id": conn_id,
                    "name": user_input.get("name", ""),
                    "device_type": DEVICE_TYPE_IO_MODULE,
                }
                return await self.async_step_device_io_module()

            if device_type == DEVICE_TYPE_KEYPAD:
                self._keypad_temp = {
                    "connection_id": conn_id,
                    "name": user_input.get("name", ""),
                    "device_type": DEVICE_TYPE_KEYPAD,
                }
                return await self.async_step_device_keypad()
            else:
                self._device_temp = {
                    "connection_id": conn_id,
                    "name": user_input.get("name", ""),
                    "device_type": device_type,
                }
                return await self.async_step_device_config()

        default_conn = self._connections[0]["id"] if self._connections else None
        return self.async_show_form(
            step_id="device",
            data_schema=vol.Schema({
                vol.Required("connection_id", default=default_conn): vol.In(conn_options),
                vol.Required("name"): str,
                vol.Required("device_type"): vol.In(DEVICE_TYPE_OPTIONS),
            }),
            errors=errors,
        )

    async def async_step_device_config(self, user_input: Optional[Dict[str, Any]] = None):
        """Second step for non-keypad devices: Group + Address."""
        errors = {}
        self._dup_device_name = None  # Reset on each submit

        if user_input is not None and self._device_temp:
            conn_id = self._device_temp["connection_id"]

            try:
                group = _validate_group(user_input["group"])
            except ValueError:
                errors["group"] = "group_hex"

            address = user_input.get("address", "").strip().upper()
            if not ADDRESS_PATTERN.match(address):
                errors["address"] = "invalid_device_address"

            if not errors:
                dup = _check_duplicate(self._devices, conn_id, group, address)
                if dup:
                    errors["group"] = "duplicate_device"
                    self._dup_device_name = dup

            # Cross-type address conflict check
            if not errors:
                conflict = _check_address_conflict(self._devices, conn_id, address)
                if conflict:
                    errors["address"] = "duplicate_device"
                    self._dup_device_name = conflict

            if not errors:
                device = {
                    "id": _new_id(),
                    "connection_id": conn_id,
                    "name": self._device_temp["name"],
                    "device_type": self._device_temp["device_type"],
                    "group": group,
                    "address": address,
                }
                self._devices.append(device)
                self._device_temp = None
                return await self.async_step_add_more()

        ph = {}
        if self._dup_device_name:
            ph["dup_name"] = self._dup_device_name
            self._dup_device_name = None
        else:
            ph["dup_name"] = ""

        return self.async_show_form(
            step_id="device_config",
            data_schema=vol.Schema({
                vol.Required("group"): cv.string,
                vol.Required("address"): cv.string,
            }),
            errors=errors,
            description_placeholders=ph,
        )

    async def async_step_device_keypad(self, user_input: Optional[Dict[str, Any]] = None):
        """Add keypad-specific fields: panel_address + 3 optional function addresses."""
        errors = {}
        self._dup_device_name = None  # Reset on each submit

        if user_input is not None and self._keypad_temp:
            conn_id = self._keypad_temp["connection_id"]

            # Collect enabled functions from user input
            panel_addr = user_input["panel_address"].strip().upper()
            if not ADDRESS_PATTERN.match(panel_addr):
                errors["panel_address"] = "invalid_device_address"

            # Check duplicate panel_address
            if not errors:
                for dev in self._devices:
                    if (dev.get("connection_id") == conn_id
                            and dev.get("device_type") == DEVICE_TYPE_KEYPAD
                            and dev.get("panel_address", "").strip().upper() == panel_addr):
                        errors["panel_address"] = "duplicate_device"
                        self._dup_device_name = dev["name"]
                        break

            # Cross-type address conflict check for panel_address
            if not errors:
                conflict = _check_address_conflict(self._devices, conn_id, panel_addr)
                if conflict:
                    errors["panel_address"] = "duplicate_device"
                    self._dup_device_name = conflict

            functions = []
            if user_input.get("enable_lock"):
                functions.append(("lock", user_input.get("lock_group", ""),
                                  user_input.get("lock_address", ""), "儿童锁 (Child Lock)"))
            if user_input.get("enable_sleep"):
                functions.append(("sleep", user_input.get("sleep_group", ""),
                                  user_input.get("sleep_address", ""), "休眠 (Sleep)"))
            if user_input.get("enable_backlight"):
                functions.append(("backlight", user_input.get("backlight_group", ""),
                                  user_input.get("backlight_address", ""), "背光 (Backlight)"))

            # Validate each enabled function
            validated_funcs = []
            for prefix, group_str, addr_str, label in functions:
                if not group_str.strip() or not addr_str.strip():
                    errors[f"{prefix}_group"] = "keypad_func_required"
                    break
                try:
                    group_val = _validate_group(group_str)
                except ValueError:
                    errors[f"{prefix}_group"] = "group_hex"
                    break
                addr_val = addr_str.strip().upper()
                if not ADDRESS_PATTERN.match(addr_val):
                    errors[f"{prefix}_address"] = "invalid_device_address"
                    break
                validated_funcs.append((prefix, group_val, addr_val, label))

                # Check duplicates with existing devices (same type)
                dup = _check_duplicate(self._devices, conn_id, group_val, addr_val)
                if dup:
                    errors[f"{prefix}_group"] = "duplicate_device"
                    self._dup_device_name = dup
                    break

                # Cross-type address conflict check for function address
                conflict = _check_address_conflict(self._devices, conn_id, addr_val)
                if conflict:
                    errors[f"{prefix}_group"] = "duplicate_device"
                    self._dup_device_name = conflict
                    break

                # Check duplicates with other functions in same form
                for other_prefix, other_group, other_addr, other_label in validated_funcs[:-1]:
                    if group_val == other_group and addr_val == other_addr:
                        errors[f"{prefix}_group"] = "duplicate_device"
                        self._dup_device_name = f"({other_label})"
                        break
                if errors:
                    break

            if not errors:
                device = {
                    "id": _new_id(),
                    "connection_id": conn_id,
                    "name": self._keypad_temp["name"],
                    "device_type": DEVICE_TYPE_KEYPAD,
                    "panel_address": panel_addr,
                }
                for prefix, group_val, addr_val, _ in validated_funcs:
                    device[f"{prefix}_group"] = group_val
                    device[f"{prefix}_address"] = addr_val
                self._devices.append(device)
                self._keypad_temp = None
                return await self.async_step_add_more()

        ph = {}
        if hasattr(self, "_dup_device_name") and self._dup_device_name:
            ph["dup_name"] = self._dup_device_name
            self._dup_device_name = None
        else:
            ph["dup_name"] = ""

        return self.async_show_form(
            step_id="device_keypad",
            data_schema=vol.Schema({
                vol.Required("panel_address"): cv.string,
                vol.Optional("enable_lock", default=False): bool,
                vol.Optional("lock_group", default=""): cv.string,
                vol.Optional("lock_address", default=""): cv.string,
                vol.Optional("enable_sleep", default=False): bool,
                vol.Optional("sleep_group", default=""): cv.string,
                vol.Optional("sleep_address", default=""): cv.string,
                vol.Optional("enable_backlight", default=False): bool,
                vol.Optional("backlight_group", default=""): cv.string,
                vol.Optional("backlight_address", default=""): cv.string,
            }),
            errors=errors,
            description_placeholders=ph,
        )

    async def async_step_device_occupancy(self, user_input: Optional[Dict[str, Any]] = None):
        """Add SH-808R-S occupancy sensor: choose search or manual mode."""
        if user_input is not None:
            mode = user_input["mode"]
            if mode == "search":
                return await self.async_step_device_occupancy_search()
            else:
                return await self.async_step_device_occupancy_manual()

        return self.async_show_form(
            step_id="device_occupancy",
            data_schema=vol.Schema({
                vol.Required("mode", default="search"): vol.In({
                    "search": "🔍 搜索添加（自动发现感应器）",
                    "manual": "✏️ 手动添加（输入XXYY地址）",
                }),
            }),
            description_placeholders={"model_name": SENSOR_MODEL_NAME},
        )

    async def async_step_device_occupancy_search(self, user_input: Optional[Dict[str, Any]] = None):
        """Search for SH-808R-S sensors and let user pick one."""
        errors = {}
        conn_id = self._device_temp["connection_id"]
        conn_cfg = next((c for c in self._connections if c["id"] == conn_id), None)

        # Gather existing occupancy sensor addresses on this connection
        existing_addrs = {
            d["address"].strip().upper()
            for d in self._devices
            if d.get("connection_id") == conn_id and d.get("device_type") == DEVICE_TYPE_OCCUPANCY
        }

        if user_input is not None:
            address = user_input.get("select_sensor", "").strip().upper()
            if not address:
                errors["select_sensor"] = "invalid_address"
            if not errors:
                device = {
                    "id": _new_id(),
                    "connection_id": conn_id,
                    "name": self._device_temp["name"],
                    "device_type": DEVICE_TYPE_OCCUPANCY,
                    "address": address,
                }
                self._devices.append(device)
                self._device_temp = None
                return await self.async_step_add_more()

        # Perform search
        found_sensors = []
        if conn_cfg:
            found_sensors = await _search_occupancy_sensors(self.hass, conn_cfg, existing_addrs)

        if not found_sensors:
            return self.async_show_form(
                step_id="device_occupancy_search",
                data_schema=vol.Schema({}),
                errors={"base": "no_sensors_found"},
                description_placeholders={"model_name": SENSOR_MODEL_NAME},
            )

        sensor_options = {s["address"]: f"SH-808R-S ({s['address']})" for s in found_sensors}
        return self.async_show_form(
            step_id="device_occupancy_search",
            data_schema=vol.Schema({
                vol.Required("select_sensor"): vol.In(sensor_options),
            }),
            errors=errors,
            description_placeholders={"model_name": SENSOR_MODEL_NAME},
        )

    async def async_step_device_occupancy_manual(self, user_input: Optional[Dict[str, Any]] = None):
        """Manually enter XXYY address for SH-808R-S sensor."""
        errors = {}
        conn_id = self._device_temp["connection_id"]

        if user_input is not None:
            address = user_input.get("address", "").strip().upper()
            if not re.match(r'^[0-9A-Fa-f]{4}$', address):
                errors["address"] = "invalid_address"
            if not errors:
                device = {
                    "id": _new_id(),
                    "connection_id": conn_id,
                    "name": self._device_temp["name"],
                    "device_type": DEVICE_TYPE_OCCUPANCY,
                    "address": address,
                }
                self._devices.append(device)
                self._device_temp = None
                return await self.async_step_add_more()

        return self.async_show_form(
            step_id="device_occupancy_manual",
            data_schema=vol.Schema({
                vol.Required("address"): cv.string,
            }),
            errors=errors,
            description_placeholders={"model_name": SENSOR_MODEL_NAME},
        )

    async def async_step_device_io_module(self, user_input: Optional[Dict[str, Any]] = None):
        """Add IO module — enter module address (00-FF)."""
        errors = {}
        conn_id = self._device_temp["connection_id"]

        if user_input is not None:
            addr = user_input.get("address", "").strip().upper()
            if not re.match(r"^[0-9A-F]{2}$", addr):
                errors["address"] = "invalid_io_address"
            # Check duplicate IO module address on same connection
            if not errors:
                for d in self._devices:
                    if (d.get("connection_id") == conn_id
                            and d.get("device_type") == DEVICE_TYPE_IO_MODULE
                            and d.get("address", "").upper() == addr):
                        errors["address"] = "duplicate_device"
                        self._dup_device_name = d["name"]
                        break

            # Cross-type address conflict check
            if not errors:
                conflict = _check_address_conflict(self._devices, conn_id, addr)
                if conflict:
                    errors["address"] = "duplicate_device"
                    self._dup_device_name = conflict

            if not errors:
                device = {
                    "id": _new_id(),
                    "connection_id": conn_id,
                    "name": self._device_temp["name"],
                    "device_type": DEVICE_TYPE_IO_MODULE,
                    "address": addr,
                }
                self._devices.append(device)
                self._device_temp = None
                return await self.async_step_add_more()

        ph = {}
        if self._dup_device_name:
            ph["dup_name"] = self._dup_device_name
            self._dup_device_name = None
        else:
            ph["dup_name"] = ""

        return self.async_show_form(
            step_id="device_io_module",
            data_schema=vol.Schema({
                vol.Required("address"): cv.string,
            }),
            errors=errors,
            description_placeholders=ph,
        )

    async def async_step_add_more(self, user_input: Optional[Dict[str, Any]] = None):
        """Ask if user wants to add more devices."""
        if user_input is not None:
            if user_input["add_more"]:
                return await self.async_step_device()
            return self.async_create_entry(
                title="Dercvne Bus",
                data={
                    "connections": self._connections,
                    "devices": self._devices,
                },
            )

        return self.async_show_form(
            step_id="add_more",
            data_schema=vol.Schema({
                vol.Required("add_more", default=False): bool,
            }),
        )

    @staticmethod
    @callback
    def async_get_options_flow(config_entry):
        return DALIOptionsFlow(config_entry)


# ---------------------------------------------------------------------------
# Options Flow (edit after setup)
# ---------------------------------------------------------------------------

class DALIOptionsFlow(config_entries.OptionsFlow):
    """Full options flow: manage connections and devices."""

    PAGE_SIZE = 20

    def __init__(self, config_entry):
        self._config_entry = config_entry

        # Load + migrate data
        raw_data = dict(config_entry.data)
        self._connections, self._devices = _migrate_data(raw_data)

        # State for pagination/editing
        self._manage_dev_page: int = 0
        self._manage_conn_page: int = 0
        self._editing_dev_index: Optional[int] = None
        self._editing_conn_index: Optional[int] = None

        # For add-connection sub-flow
        self._pending_conn_type: Optional[str] = None
        self._pending_conn_id: Optional[str] = None

        # For keypad sub-flow
        self._keypad_temp: Optional[dict] = None
        self._device_temp: Optional[dict] = None
        self._dup_device_name: Optional[str] = None

    # ------------------------------------------------------------------ helpers

    async def _apply_and_reload(self):
        """Save current state back to entry.data and reload.

        Uses HA's official config-entries API only — never touches the
        .storage/core.config_entries file directly (which can corrupt a
        user's setup). See HACS review feedback on PR #8426.
        """
        import logging
        entry = self._config_entry
        new_data = dict(entry.data)
        new_data["connections"] = self._connections
        new_data["devices"] = self._devices

        _LOGGER.debug(
            "Options: saving %d devices",
            len(self._devices),
        )

        # Update entry via the official API. HA will persist to
        # .storage/core.config_entries through its own debounced save.
        self.hass.config_entries.async_update_entry(entry, data=new_data)

        await self.hass.config_entries.async_reload(entry.entry_id)
        return self.async_create_entry(title="", data={})

    # ------------------------------------------------------------------ main menu

    async def async_step_init(self, user_input: Optional[Dict[str, Any]] = None):
        """Main options menu."""
        if user_input is not None:
            action = user_input["action"]
            if action == "add_device":
                return await self.async_step_add_device()
            if action == "manage_devices":
                self._manage_dev_page = 0
                return await self.async_step_manage_devices()
            if action == "manage_connections":
                self._manage_conn_page = 0
                return await self.async_step_manage_connections()
            if action == "manage_vrv":
                return await self.async_step_manage_vrv()
            if action == "done":
                return await self._apply_and_reload()
            return self.async_create_entry(title="", data={})

        return self.async_show_form(
            step_id="init",
            data_schema=vol.Schema({
                vol.Required("action"): vol.In({
                    "add_device": "添加设备",
                    "manage_devices": "查看 / 编辑 / 删除设备",
                    "manage_connections": "管理连接",
                    "done": "完成",
                })
            }),
            description_placeholders={
                "device_count": str(sum(1 for d in self._devices if d.get("device_type") != DEVICE_TYPE_VRV_CONTROLLER)),
                "conn_count": str(len(self._connections)),
            },
        )

    # ================================================================== DEVICES

    # ---- add device ----

    async def async_step_add_device(self, user_input: Optional[Dict[str, Any]] = None):
        """Add a new device — first step: pick type + name + connection.

        VRV indoor units go through the same connection flow as other devices;
        a vrv_controller record is auto-created if one doesn't exist yet for
        the selected connection.
        """
        errors = {}
        conn_options = {c["id"]: _conn_label(c) for c in self._connections}

        if user_input is not None:
            device_type = user_input["device_type"]
            conn_id = user_input.get("connection_id")
            name = user_input.get("name", "")

            # ── VRV Indoor Unit: pick connection, auto-create controller, go to indoor mgmt ──
            if device_type == DEVICE_TYPE_VRV_INDOOR:
                if not conn_id:
                    errors["connection_id"] = "no_connections"
                else:
                    vrv_id = self._ensure_vrv_controller(conn_id)
                    self._editing_vrv_id = vrv_id
                    return await self.async_step_vrv_action()

            # All other device types require a bus connection
            if not conn_id:
                errors["connection_id"] = "no_connections"
            else:
                if device_type == DEVICE_TYPE_OCCUPANCY:
                    self._device_temp = {
                        "connection_id": conn_id,
                        "name": user_input.get("name", ""),
                        "device_type": DEVICE_TYPE_OCCUPANCY,
                    }
                    return await self.async_step_add_device_occupancy()

                if device_type == DEVICE_TYPE_IO_MODULE:
                    self._device_temp = {
                        "connection_id": conn_id,
                        "name": user_input.get("name", ""),
                        "device_type": DEVICE_TYPE_IO_MODULE,
                    }
                    return await self.async_step_add_device_io_module()

                if device_type == DEVICE_TYPE_KEYPAD:
                    self._keypad_temp = {
                        "connection_id": conn_id,
                        "name": user_input.get("name", ""),
                        "device_type": DEVICE_TYPE_KEYPAD,
                    }
                    return await self.async_step_add_device_keypad()

                if device_type == DEVICE_TYPE_DALI_SCENE:
                    self._device_temp = {
                        "connection_id": conn_id,
                        "name": user_input.get("name", ""),
                        "device_type": DEVICE_TYPE_DALI_SCENE,
                    }
                    return await self.async_step_add_device_dali_scene()

                if device_type == DEVICE_TYPE_THERMOSTAT:
                    self._device_temp = {
                        "connection_id": conn_id,
                        "name": user_input.get("name", ""),
                        "device_type": DEVICE_TYPE_THERMOSTAT,
                    }
                    return await self.async_step_add_device_thermostat()

                # All other device types (relay, light, cover, scene)
                self._device_temp = {
                    "connection_id": conn_id,
                    "name": user_input.get("name", ""),
                    "device_type": device_type,
                }
                return await self.async_step_add_device_config()

        # Show form — connection_id is required for all devices
        default_conn = self._connections[0]["id"] if self._connections else None
        schema_fields = {}
        if conn_options:
            schema_fields[vol.Required("connection_id", default=default_conn)] = vol.In(conn_options)
        else:
            schema_fields[vol.Required("connection_id")] = str
        schema_fields[vol.Optional("name", default="")] = str
        schema_fields[vol.Required("device_type")] = vol.In(DEVICE_TYPE_OPTIONS)

        return self.async_show_form(
            step_id="add_device",
            data_schema=vol.Schema(schema_fields),
            errors=errors,
            description_placeholders={},
        )

    async def async_step_add_device_config(self, user_input: Optional[Dict[str, Any]] = None):
        """Second step for non-keypad devices: Group + Address."""
        errors = {}
        self._dup_device_name = None

        if user_input is not None and self._device_temp:
            conn_id = self._device_temp["connection_id"]

            try:
                group = _validate_group(user_input["group"])
            except ValueError:
                errors["group"] = "group_hex"

            address = user_input.get("address", "").strip().upper()
            if not ADDRESS_PATTERN.match(address):
                errors["address"] = "invalid_device_address"

            if not errors:
                dup = _check_duplicate(self._devices, conn_id, group, address)
                if dup:
                    errors["group"] = "duplicate_device"
                    self._dup_device_name = dup

            # Cross-type address conflict check
            if not errors:
                conflict = _check_address_conflict(self._devices, conn_id, address)
                if conflict:
                    errors["address"] = "duplicate_device"
                    self._dup_device_name = conflict

            if not errors:
                device = {
                    "id": _new_id(),
                    "connection_id": conn_id,
                    "name": self._device_temp["name"],
                    "device_type": self._device_temp["device_type"],
                    "group": group,
                    "address": address,
                }
                self._devices.append(device)
                self._device_temp = None
                return await self.async_step_add_device_more()

        ph = {}
        if self._dup_device_name:
            ph["dup_name"] = self._dup_device_name
            self._dup_device_name = None
        else:
            ph["dup_name"] = ""

        return self.async_show_form(
            step_id="add_device_config",
            data_schema=vol.Schema({
                vol.Required("group"): cv.string,
                vol.Required("address"): cv.string,
            }),
            errors=errors,
            description_placeholders=ph,
        )

    async def async_step_add_device_dali_scene(
        self, user_input: Optional[Dict[str, Any]] = None
    ):
        """Add DALI scene — port (0-3), group (00-15), scene (09-18)."""
        errors = {}

        if user_input is not None and self._device_temp:
            conn_id = self._device_temp["connection_id"]
            port = user_input.get("port", "0").strip()
            group = user_input.get("group", "").strip().upper()
            scene = user_input.get("scene", "").strip().upper()

            # Validate port: 0-3
            if not re.match(r"^[0-3]$", port):
                errors["port"] = "invalid_port"

            # Validate group: 00-15 (hex, 2 digits)
            if not re.match(r"^(0[0-9A-F]|1[0-5])$", group):
                errors["group"] = "invalid_group"

            # Validate scene: 09-18 (hex, 2 digits)
            if not re.match(r"^(0[9A-F]|1[0-8])$", scene):
                errors["scene"] = "invalid_scene"

            # Check duplicate triplet
            if not errors:
                dup = _check_dali_scene_duplicate(
                    self._devices, conn_id, port, group, scene,
                )
                if dup:
                    errors["group"] = "duplicate_device"
                    self._dup_device_name = dup

            if not errors:
                device = {
                    "id": _new_id(),
                    "connection_id": conn_id,
                    "name": self._device_temp["name"],
                    "device_type": DEVICE_TYPE_DALI_SCENE,
                    "port": port,
                    "group": group,
                    "scene": scene,
                }
                self._devices.append(device)
                self._device_temp = None
                return await self.async_step_add_device_more()

        ph = {}
        if self._dup_device_name:
            ph["dup_name"] = self._dup_device_name
            self._dup_device_name = None
        else:
            ph["dup_name"] = ""

        return self.async_show_form(
            step_id="add_device_dali_scene",
            data_schema=vol.Schema({
                vol.Required("port", default="0"): vol.In({
                    "0": "0 - 第1路", "1": "1 - 第2路",
                    "2": "2 - 第3路", "3": "3 - 第4路",
                }),
                vol.Required("group", default="00"): cv.string,
                vol.Required("scene", default="09"): cv.string,
            }),
            errors=errors,
            description_placeholders=ph,
        )

    async def async_step_add_device_thermostat(self, user_input: Optional[Dict[str, Any]] = None):
        """Add thermostat panel — configure sub-functions (AC/FH/FA) and addresses.

        At least one sub-function must be enabled. Each gets a Sicoo address (1-64).
        """
        errors = {}

        if user_input is not None and self._device_temp:
            conn_id = self._device_temp["connection_id"]

            ac_enabled = user_input.get("enable_ac", False)
            fh_enabled = user_input.get("enable_fh", False)
            fa_enabled = user_input.get("enable_fa", False)

            if not any([ac_enabled, fh_enabled, fa_enabled]):
                errors["base"] = "至少需要启用一个子功能（空调/地暖/新风）"

            if ac_enabled and fa_enabled:
                errors["base"] = "空调和新风不能同时使用（面板不支持同时启用）"

            # Validate addresses
            ac_addr = None
            fh_addr = None
            fa_addr = None

            if ac_enabled:
                try:
                    ac_addr = int(user_input.get("ac_address", ""))
                    if not (SICOO_ADDR_MIN <= ac_addr <= SICOO_ADDR_MAX):
                        errors["ac_address"] = "invalid_thermostat_address"
                except (ValueError, TypeError):
                    errors["ac_address"] = "invalid_thermostat_address"

            if fh_enabled:
                try:
                    fh_addr = int(user_input.get("fh_address", ""))
                    if not (SICOO_ADDR_MIN <= fh_addr <= SICOO_ADDR_MAX):
                        errors["fh_address"] = "invalid_thermostat_address"
                except (ValueError, TypeError):
                    errors["fh_address"] = "invalid_thermostat_address"

            if fa_enabled:
                try:
                    fa_addr = int(user_input.get("fa_address", ""))
                    if not (SICOO_ADDR_MIN <= fa_addr <= SICOO_ADDR_MAX):
                        errors["fa_address"] = "invalid_thermostat_address"
                except (ValueError, TypeError):
                    errors["fa_address"] = "invalid_thermostat_address"

            # Check for duplicate addresses among enabled sub-functions
            seen = {}
            if ac_enabled and ac_addr is not None:
                seen[ac_addr] = "ac"
            if fh_enabled and fh_addr is not None:
                if fh_addr in seen:
                    errors["fh_address"] = "duplicate_thermostat_address"
                    self._dup_device_name = f"空调({seen[fh_addr]})与地暖地址相同"
                else:
                    seen[fh_addr] = "fh"
            if fa_enabled and fa_addr is not None:
                if fa_addr in seen:
                    errors["fa_address"] = "duplicate_thermostat_address"
                    self._dup_device_name = f"{'空调' if seen[fa_addr] == 'ac' else '地暖'}({seen[fa_addr]})与新风地址相同"
                else:
                    seen[fa_addr] = "fa"

            if not errors:
                device = {
                    "id": _new_id(),
                    "connection_id": conn_id,
                    "name": self._device_temp["name"],
                    "device_type": DEVICE_TYPE_THERMOSTAT,
                    "ac": {"enabled": ac_enabled, "address": str(ac_addr) if ac_addr else "1"},
                    "floor_heating": {"enabled": fh_enabled, "address": str(fh_addr) if fh_addr else "1"},
                    "fresh_air": {"enabled": fa_enabled, "address": str(fa_addr) if fa_addr else "1"},
                }
                self._devices.append(device)
                self._device_temp = None
                return await self.async_step_add_device_more()

        # Build form with defaults from device_temp
        pre_ac = {"enabled": True, "address": "1"}
        pre_fh = {"enabled": False, "address": "1"}
        pre_fa = {"enabled": False, "address": "1"}
        if self._device_temp:
            pre_ac = self._device_temp.get("ac", pre_ac)
            pre_fh = self._device_temp.get("floor_heating", pre_fh)
            pre_fa = self._device_temp.get("fresh_air", pre_fa)

        ph = {}
        if self._dup_device_name:
            ph["dup_name"] = self._dup_device_name
            self._dup_device_name = None
        else:
            ph["dup_name"] = ""

        return self.async_show_form(
            step_id="add_device_thermostat",
            data_schema=vol.Schema({
                vol.Required("enable_ac", default=pre_ac.get("enabled", True)): bool,
                vol.Optional("ac_address", default=str(pre_ac.get("address", "1"))):  cv.string,
                vol.Required("enable_fh", default=pre_fh.get("enabled", False)): bool,
                vol.Optional("fh_address", default=str(pre_fh.get("address", "1"))):  cv.string,
                vol.Required("enable_fa", default=pre_fa.get("enabled", False)): bool,
                vol.Optional("fa_address", default=str(pre_fa.get("address", "1"))):  cv.string,
            }),
            errors=errors,
            description_placeholders=ph,
        )

    async def async_step_add_device_keypad(self, user_input: Optional[Dict[str, Any]] = None):
        """Add keypad-specific fields for a new keypad device (optional functions)."""
        errors = {}
        self._dup_device_name = None

        if user_input is not None and self._keypad_temp:
            conn_id = self._keypad_temp["connection_id"]

            # Collect enabled functions from user input
            panel_addr = user_input["panel_address"].strip().upper()
            if not ADDRESS_PATTERN.match(panel_addr):
                errors["panel_address"] = "invalid_device_address"

            # Check duplicate panel_address (options flow)
            if not errors:
                for dev in self._devices:
                    if (dev.get("connection_id") == conn_id
                            and dev.get("device_type") == DEVICE_TYPE_KEYPAD
                            and dev.get("panel_address", "").strip().upper() == panel_addr):
                        errors["panel_address"] = "duplicate_device"
                        self._dup_device_name = dev["name"]
                        break

            # Cross-type address conflict check for panel_address
            if not errors:
                conflict = _check_address_conflict(self._devices, conn_id, panel_addr)
                if conflict:
                    errors["panel_address"] = "duplicate_device"
                    self._dup_device_name = conflict

            functions = []
            if user_input.get("enable_lock"):
                functions.append(("lock", user_input.get("lock_group", ""),
                                  user_input.get("lock_address", ""), "儿童锁 (Child Lock)"))
            if user_input.get("enable_sleep"):
                functions.append(("sleep", user_input.get("sleep_group", ""),
                                  user_input.get("sleep_address", ""), "休眠 (Sleep)"))
            if user_input.get("enable_backlight"):
                functions.append(("backlight", user_input.get("backlight_group", ""),
                                  user_input.get("backlight_address", ""), "背光 (Backlight)"))

            # Validate each enabled function
            validated_funcs = []
            for prefix, group_str, addr_str, label in functions:
                if not group_str.strip() or not addr_str.strip():
                    errors[f"{prefix}_group"] = "keypad_func_required"
                    break
                try:
                    group_val = _validate_group(group_str)
                except ValueError:
                    errors[f"{prefix}_group"] = "group_hex"
                    break
                addr_val = addr_str.strip().upper()
                if not ADDRESS_PATTERN.match(addr_val):
                    errors[f"{prefix}_address"] = "invalid_device_address"
                    break
                validated_funcs.append((prefix, group_val, addr_val, label))

                # Check duplicates with existing devices (same type)
                dup = _check_duplicate(self._devices, conn_id, group_val, addr_val)
                if dup:
                    errors[f"{prefix}_group"] = "duplicate_device"
                    self._dup_device_name = dup
                    break

                # Cross-type address conflict check for function address
                conflict = _check_address_conflict(self._devices, conn_id, addr_val)
                if conflict:
                    errors[f"{prefix}_group"] = "duplicate_device"
                    self._dup_device_name = conflict
                    break

                # Check duplicates with other functions in same form
                for other_prefix, other_group, other_addr, other_label in validated_funcs[:-1]:
                    if group_val == other_group and addr_val == other_addr:
                        errors[f"{prefix}_group"] = "duplicate_device"
                        self._dup_device_name = f"({other_label})"
                        break
                if errors:
                    break

            if not errors:
                device = {
                    "id": _new_id(),
                    "connection_id": conn_id,
                    "name": self._keypad_temp["name"],
                    "device_type": DEVICE_TYPE_KEYPAD,
                    "panel_address": panel_addr,
                }
                for prefix, group_val, addr_val, _ in validated_funcs:
                    device[f"{prefix}_group"] = group_val
                    device[f"{prefix}_address"] = addr_val
                self._devices.append(device)
                self._keypad_temp = None
                return await self.async_step_add_device_more()

        ph = {}
        if self._dup_device_name:
            ph["dup_name"] = self._dup_device_name
            self._dup_device_name = None
        else:
            ph["dup_name"] = ""

        return self.async_show_form(
            step_id="add_device_keypad",
            data_schema=vol.Schema({
                vol.Required("panel_address"): cv.string,
                vol.Optional("enable_lock", default=False): bool,
                vol.Optional("lock_group", default=""): cv.string,
                vol.Optional("lock_address", default=""): cv.string,
                vol.Optional("enable_sleep", default=False): bool,
                vol.Optional("sleep_group", default=""): cv.string,
                vol.Optional("sleep_address", default=""): cv.string,
                vol.Optional("enable_backlight", default=False): bool,
                vol.Optional("backlight_group", default=""): cv.string,
                vol.Optional("backlight_address", default=""): cv.string,
            }),
            errors=errors,
            description_placeholders=ph,
        )

    async def async_step_add_device_occupancy(self, user_input: Optional[Dict[str, Any]] = None):
        """Add SH-808R-S occupancy sensor in options flow: choose search or manual mode."""
        if user_input is not None:
            mode = user_input["mode"]
            if mode == "search":
                return await self.async_step_add_device_occupancy_search()
            else:
                return await self.async_step_add_device_occupancy_manual()

        return self.async_show_form(
            step_id="add_device_occupancy",
            data_schema=vol.Schema({
                vol.Required("mode", default="search"): vol.In({
                    "search": "🔍 搜索添加（自动发现感应器）",
                    "manual": "✏️ 手动添加（输入XXYY地址）",
                }),
            }),
            description_placeholders={"model_name": SENSOR_MODEL_NAME},
        )

    async def async_step_add_device_occupancy_search(self, user_input: Optional[Dict[str, Any]] = None):
        """Search for SH-808R-S sensors in options flow and let user pick one."""
        errors = {}
        conn_id = self._device_temp["connection_id"]
        conn_cfg = next((c for c in self._connections if c["id"] == conn_id), None)

        # Gather existing occupancy sensor addresses on this connection
        existing_addrs = {
            d["address"].strip().upper()
            for d in self._devices
            if d.get("connection_id") == conn_id and d.get("device_type") == DEVICE_TYPE_OCCUPANCY
        }

        if user_input is not None:
            address = user_input.get("select_sensor", "").strip().upper()
            if not address:
                errors["select_sensor"] = "invalid_address"
            if not errors:
                device = {
                    "id": _new_id(),
                    "connection_id": conn_id,
                    "name": self._device_temp["name"],
                    "device_type": DEVICE_TYPE_OCCUPANCY,
                    "address": address,
                }
                self._devices.append(device)
                self._device_temp = None
                return await self.async_step_add_device_more()

        # Perform search
        found_sensors = []
        if conn_cfg:
            found_sensors = await _search_occupancy_sensors(self.hass, conn_cfg, existing_addrs)

        if not found_sensors:
            return self.async_show_form(
                step_id="add_device_occupancy_search",
                data_schema=vol.Schema({}),
                errors={"base": "no_sensors_found"},
                description_placeholders={"model_name": SENSOR_MODEL_NAME},
            )

        sensor_options = {s["address"]: f"SH-808R-S ({s['address']})" for s in found_sensors}
        return self.async_show_form(
            step_id="add_device_occupancy_search",
            data_schema=vol.Schema({
                vol.Required("select_sensor"): vol.In(sensor_options),
            }),
            errors=errors,
            description_placeholders={"model_name": SENSOR_MODEL_NAME},
        )

    async def async_step_add_device_occupancy_manual(self, user_input: Optional[Dict[str, Any]] = None):
        """Manually enter XXYY address for SH-808R-S sensor in options flow."""
        errors = {}
        conn_id = self._device_temp["connection_id"]

        if user_input is not None:
            address = user_input.get("address", "").strip().upper()
            if not re.match(r'^[0-9A-Fa-f]{4}$', address):
                errors["address"] = "invalid_address"
            if not errors:
                device = {
                    "id": _new_id(),
                    "connection_id": conn_id,
                    "name": self._device_temp["name"],
                    "device_type": DEVICE_TYPE_OCCUPANCY,
                    "address": address,
                }
                self._devices.append(device)
                self._device_temp = None
                return await self.async_step_add_device_more()

        return self.async_show_form(
            step_id="add_device_occupancy_manual",
            data_schema=vol.Schema({
                vol.Required("address"): cv.string,
            }),
            errors=errors,
            description_placeholders={"model_name": SENSOR_MODEL_NAME},
        )

    async def async_step_add_device_io_module(self, user_input: Optional[Dict[str, Any]] = None):
        """Add IO module in options flow — enter module address (00-FF)."""
        errors = {}
        conn_id = self._device_temp["connection_id"]

        if user_input is not None:
            addr = user_input.get("address", "").strip().upper()
            if not re.match(r"^[0-9A-F]{2}$", addr):
                errors["address"] = "invalid_io_address"
            # Check duplicate IO module address on same connection
            if not errors:
                for d in self._devices:
                    if (d.get("connection_id") == conn_id
                            and d.get("device_type") == DEVICE_TYPE_IO_MODULE
                            and d.get("address", "").upper() == addr):
                        errors["address"] = "duplicate_device"
                        self._dup_device_name = d["name"]
                        break

            # Cross-type address conflict check
            if not errors:
                conflict = _check_address_conflict(self._devices, conn_id, addr)
                if conflict:
                    errors["address"] = "duplicate_device"
                    self._dup_device_name = conflict

            if not errors:
                device = {
                    "id": _new_id(),
                    "connection_id": conn_id,
                    "name": self._device_temp["name"],
                    "device_type": DEVICE_TYPE_IO_MODULE,
                    "address": addr,
                }
                self._devices.append(device)
                self._device_temp = None
                return await self.async_step_add_device_more()

        ph = {}
        if self._dup_device_name:
            ph["dup_name"] = self._dup_device_name
            self._dup_device_name = None
        else:
            ph["dup_name"] = ""

        return self.async_show_form(
            step_id="add_device_io_module",
            data_schema=vol.Schema({
                vol.Required("address"): cv.string,
            }),
            errors=errors,
            description_placeholders=ph,
        )

    async def async_step_add_device_more(self, user_input: Optional[Dict[str, Any]] = None):
        """Ask if user wants to add another device."""
        if user_input is not None:
            if user_input["add_more"]:
                return await self.async_step_add_device()
            return await self._apply_and_reload()

        return self.async_show_form(
            step_id="add_device_more",
            data_schema=vol.Schema({
                vol.Required("add_more", default=False): bool,
            }),
        )

    # ---- manage devices (paginated list) ----

    async def async_step_manage_devices(self, user_input: Optional[Dict[str, Any]] = None):
        """Paginated device list."""
        if not self._devices:
            return self.async_show_form(
                step_id="manage_devices",
                data_schema=vol.Schema({
                    vol.Required("action"): vol.In({"back": "← 返回主菜单（暂无设备）"})
                }),
                description_placeholders={"page_info": "", "device_list": "（暂无设备）"},
            )

        total_pages = (len(self._devices) + self.PAGE_SIZE - 1) // self.PAGE_SIZE
        self._manage_dev_page = max(0, min(self._manage_dev_page, total_pages - 1))
        page = self._manage_dev_page
        start = page * self.PAGE_SIZE
        end = min(start + self.PAGE_SIZE, len(self._devices))

        if user_input is not None:
            action = user_input["action"]
            if action == "back":
                return await self.async_step_init()
            if action == "next":
                self._manage_dev_page = min(page + 1, total_pages - 1)
                return await self.async_step_manage_devices()
            if action == "prev":
                self._manage_dev_page = max(page - 1, 0)
                return await self.async_step_manage_devices()
            self._editing_dev_index = int(action)
            return await self.async_step_device_action()

        # Build display lines
        lines = []
        for i in range(start, end):
            dev = self._devices[i]
            label = DEVICE_TYPE_LABELS.get(dev.get("device_type", ""), "?")
            conn_id = dev.get("connection_id", "")
            conn = next((c for c in self._connections if c["id"] == conn_id), None)
            conn_name = conn["name"] if conn else "?"
            if dev.get("device_type") == DEVICE_TYPE_KEYPAD:
                pa = dev.get("panel_address", "?")
                lines.append(
                    f"  #{i + 1}  {dev['name']}  [{label}]  PA={pa}  [{conn_name}]"
                )
            elif dev.get("device_type") == DEVICE_TYPE_OCCUPANCY:
                lines.append(
                    f"  #{i + 1}  {dev['name']}  [感应器 SH-808R-S]  XXYY={dev['address']}  [{conn_name}]"
                )
            elif dev.get("device_type") == DEVICE_TYPE_IO_MODULE:
                lines.append(
                    f"  #{i + 1}  {dev['name']}  [4路IO模块]  A={dev['address']}  [{conn_name}]"
                )
            elif dev.get("device_type") == DEVICE_TYPE_VRV_INDOOR:
                unit_id = dev.get("unit_id", "?")
                lines.append(
                    f"  #{i + 1}  {dev['name']}  [VRV内机]  UID={unit_id}  [{conn_name}]"
                )
            elif dev.get("device_type") == DEVICE_TYPE_VRV_CONTROLLER:
                # Skip VRV controller records — they are internal, managed via manage_vrv
                continue
            elif dev.get("device_type") == DEVICE_TYPE_DALI_SCENE:
                p = dev.get("port", "0")
                g = dev.get("group", "00")
                s = dev.get("scene", "09")
                lines.append(
                    f"  #{i + 1}  {dev['name']}  [DALI场景]  路={p} 组={g} 场景={s}  [{conn_name}]"
                )
            elif dev.get("device_type") == DEVICE_TYPE_THERMOSTAT:
                parts = []
                for sub, sub_label in [("ac", "空调"), ("floor_heating", "地暖"), ("fresh_air", "新风")]:
                    if dev.get(sub, {}).get("enabled"):
                        parts.append(f"{sub_label}({dev[sub].get('address', '?')})")
                sub_info = " ".join(parts) if parts else "未启用"
                lines.append(
                    f"  #{i + 1}  {dev['name']}  [{label}]  {sub_info}  [{conn_name}]"
                )
            else:
                lines.append(
                    f"  #{i + 1}  {dev['name']}  [{label}]  G={dev.get('group', '?')}  A={dev.get('address', '?')}  [{conn_name}]"
                )

        options = {}
        for i in range(start, end):
            dev = self._devices[i]
            if dev.get("device_type") == DEVICE_TYPE_VRV_CONTROLLER:
                # Skip VRV controller records — they are internal, managed via manage_vrv
                continue
            label = DEVICE_TYPE_LABELS.get(dev.get("device_type", ""), "?")
            options[str(i)] = f"#{i + 1}  {dev['name']}  ({label})"

        if total_pages > 1:
            if page > 0:
                options["prev"] = "◀ 上一页"
            if page < total_pages - 1:
                options["next"] = "下一页 ▶"
        options["back"] = "← 返回主菜单"

        return self.async_show_form(
            step_id="manage_devices",
            data_schema=vol.Schema({vol.Required("action"): vol.In(options)}),
            description_placeholders={
                "device_list": "\n".join(lines),
                "page_info": f"第 {page + 1}/{total_pages} 页，共 {len(self._devices)} 个设备",
            },
        )

    async def async_step_device_action(self, user_input: Optional[Dict[str, Any]] = None):
        """Edit or delete a device."""
        idx = self._editing_dev_index
        if idx is None or idx >= len(self._devices):
            return await self.async_step_manage_devices()

        dev = self._devices[idx]
        label = DEVICE_TYPE_LABELS.get(dev.get("device_type", ""), "?")
        conn_id = dev.get("connection_id", "")
        conn = next((c for c in self._connections if c["id"] == conn_id), None)
        conn_name = conn["name"] if conn else "?"

        if user_input is not None:
            action = user_input["action"]
            if action == "back":
                return await self.async_step_manage_devices()
            if action == "edit":
                return await self.async_step_edit_device()
            if action == "delete":
                return await self.async_step_confirm_delete_device()

        if dev.get("device_type") == DEVICE_TYPE_OCCUPANCY:
            actions = {
                "edit": f"编辑: {dev['name']}",
                "delete": f"删除: {dev['name']}",
                "back": "← 返回设备列表",
            }
        elif dev.get("device_type") in (DEVICE_TYPE_VRV_CONTROLLER, DEVICE_TYPE_VRV_INDOOR):
            actions = {
                "edit": f"编辑: {dev['name']}",
                "delete": f"删除: {dev['name']}",
                "back": "← 返回设备列表",
            }
        else:
            actions = {
                "edit": f"编辑: {dev['name']}",
                "delete": f"删除: {dev['name']}",
                "back": "← 返回设备列表",
            }

        # Build placeholder values
        if dev.get("device_type") == DEVICE_TYPE_DALI_SCENE:
            device_group = f"路={dev.get('port', '?')} 组={dev.get('group', '?')}"
            device_address = f"场景={dev.get('scene', '?')}"
        elif dev.get("device_type") == DEVICE_TYPE_THERMOSTAT:
            parts = []
            for sub, label in [("ac", "空调"), ("floor_heating", "地暖"), ("fresh_air", "新风")]:
                if dev.get(sub, {}).get("enabled"):
                    parts.append(f"{label}({dev[sub].get('address', '?')})")
            device_group = "子功能"
            device_address = " ".join(parts)
        else:
            device_group = dev.get("group", dev.get("panel_address", dev.get("host", "?")))
            device_address = dev.get("address", dev.get("lock_address", dev.get("unit_id", "?")))

        return self.async_show_form(
            step_id="device_action",
            data_schema=vol.Schema({
                vol.Required("action"): vol.In(actions)
            }),
            description_placeholders={
                "device_name": dev["name"],
                "device_type": label,
                "device_group": device_group,
                "device_address": device_address,
                "conn_name": conn_name,
            },
        )

    async def async_step_edit_device(self, user_input: Optional[Dict[str, Any]] = None):
        """Edit an existing device."""
        errors = {}
        idx = self._editing_dev_index
        if idx is None or idx >= len(self._devices):
            return await self.async_step_manage_devices()

        dev = self._devices[idx]

        # Redirect VRV devices to the VRV management flow
        if dev.get("device_type") in (DEVICE_TYPE_VRV_CONTROLLER, DEVICE_TYPE_VRV_INDOOR):
            if dev.get("device_type") == DEVICE_TYPE_VRV_CONTROLLER:
                self._editing_vrv_id = dev.get("id")
                return await self.async_step_vrv_action()
            else:
                # VRV indoor unit
                parent_id = dev.get("parent_id")
                if parent_id:
                    self._editing_vrv_id = parent_id
                    self._editing_vrv_unit_id = dev.get("id")
                    return await self.async_step_vrv_indoor_action()
                return await self.async_step_manage_devices()

        conn_options = {c["id"]: _conn_label(c) for c in self._connections}

        if user_input is not None:
            device_type = user_input["device_type"]
            conn_id = user_input["connection_id"]
            dev_id = dev.get("id", _new_id())

            if device_type == DEVICE_TYPE_KEYPAD:
                # Collect enabled functions from user input
                panel_addr = user_input["panel_address"].strip().upper()
                if not ADDRESS_PATTERN.match(panel_addr):
                    errors["panel_address"] = "invalid_device_address"
                if not errors:
                    conflict = _check_address_conflict(
                        self._devices, conn_id, panel_addr, exclude_device_id=dev_id)
                    if conflict:
                        errors["panel_address"] = "duplicate_device"
                        self._dup_device_name = conflict
                functions = []
                if user_input.get("enable_lock"):
                    functions.append(("lock", user_input.get("lock_group", ""),
                                      user_input.get("lock_address", ""), "儿童锁 (Child Lock)"))
                if user_input.get("enable_sleep"):
                    functions.append(("sleep", user_input.get("sleep_group", ""),
                                      user_input.get("sleep_address", ""), "休眠 (Sleep)"))
                if user_input.get("enable_backlight"):
                    functions.append(("backlight", user_input.get("backlight_group", ""),
                                      user_input.get("backlight_address", ""), "背光 (Backlight)"))

                # Validate each enabled function
                validated_funcs = []
                for prefix, group_str, addr_str, label in functions:
                    if not group_str.strip() or not addr_str.strip():
                        errors[f"{prefix}_group"] = "keypad_func_required"
                        break
                    try:
                        group_val = _validate_group(group_str)
                    except ValueError:
                        errors[f"{prefix}_group"] = "group_hex"
                        break
                    addr_val = addr_str.strip().upper()
                    validated_funcs.append((prefix, group_val, addr_val, label))

                    # Check duplicates with existing devices
                    dup = _check_duplicate(self._devices, conn_id, group_val, addr_val,
                                           exclude_device_id=dev_id)
                    if dup:
                        errors[f"{prefix}_group"] = "duplicate_device"
                        self._dup_device_name = dup
                        break

                    # Check duplicates with other functions in same form
                    for other_prefix, other_group, other_addr, other_label in validated_funcs[:-1]:
                        if group_val == other_group and addr_val == other_addr:
                            errors[f"{prefix}_group"] = "duplicate_device"
                            self._dup_device_name = f"({other_label})"
                            break
                    if errors:
                        break

                if not errors:
                    self._devices[idx] = {
                        "id": dev_id,
                        "connection_id": conn_id,
                        "name": user_input.get("name", ""),
                        "device_type": DEVICE_TYPE_KEYPAD,
                        "panel_address": panel_addr,
                    }
                    for prefix, group_val, addr_val, _ in validated_funcs:
                        self._devices[idx][f"{prefix}_group"] = group_val
                        self._devices[idx][f"{prefix}_address"] = addr_val
                    return await self._apply_and_reload()
            elif device_type == DEVICE_TYPE_OCCUPANCY:
                # Occupancy sensor — only name + address (no group)
                address = user_input.get("address", "").strip().upper()
                if not re.match(r"^[0-9A-F]{4}$", address):
                    errors["address"] = "invalid_address"
                if not errors:
                    self._devices[idx] = {
                        "id": dev_id,
                        "connection_id": conn_id,
                        "name": user_input.get("name", ""),
                        "device_type": DEVICE_TYPE_OCCUPANCY,
                        "address": address,
                    }
                    return await self._apply_and_reload()
            elif device_type == DEVICE_TYPE_IO_MODULE:
                # IO module — only name + address (00-FF), no group
                addr = user_input.get("address", "").strip().upper()
                if not re.match(r"^[0-9A-F]{2}$", addr):
                    errors["address"] = "invalid_address"
                # Check duplicate IO module address on same connection
                if not errors:
                    for d in self._devices:
                        if (d.get("connection_id") == conn_id
                                and d.get("device_type") == DEVICE_TYPE_IO_MODULE
                                and d.get("address", "").upper() == addr
                                and d.get("id") != dev_id):
                            errors["address"] = "duplicate_device"
                            self._dup_device_name = d["name"]
                            break
                # Cross-type address conflict check
                if not errors:
                    conflict = _check_address_conflict(
                        self._devices, conn_id, addr, exclude_device_id=dev_id)
                    if conflict:
                        errors["address"] = "duplicate_device"
                        self._dup_device_name = conflict
                if not errors:
                    self._devices[idx] = {
                        "id": dev_id,
                        "connection_id": conn_id,
                        "name": user_input.get("name", ""),
                        "device_type": DEVICE_TYPE_IO_MODULE,
                        "address": addr,
                    }
                    return await self._apply_and_reload()
            elif device_type == DEVICE_TYPE_DALI_SCENE:
                # DALI scene — port, group, scene triad
                port = user_input.get("port", "0").strip()
                group = user_input.get("group", "").strip().upper()
                scene = user_input.get("scene", "").strip().upper()

                if not re.match(r"^[0-3]$", port):
                    errors["port"] = "invalid_port"
                if not re.match(r"^(0[0-9A-F]|1[0-5])$", group):
                    errors["group"] = "invalid_group"
                if not re.match(r"^(0[9A-F]|1[0-8])$", scene):
                    errors["scene"] = "invalid_scene"

                if not errors:
                    dup = _check_dali_scene_duplicate(
                        self._devices, conn_id, port, group, scene,
                        exclude_device_id=dev_id,
                    )
                    if dup:
                        errors["group"] = "duplicate_device"
                        self._dup_device_name = dup

                if not errors:
                    self._devices[idx] = {
                        "id": dev_id,
                        "connection_id": conn_id,
                        "name": user_input.get("name", ""),
                        "device_type": DEVICE_TYPE_DALI_SCENE,
                        "port": port,
                        "group": group,
                        "scene": scene,
                    }
                    return await self._apply_and_reload()
            elif device_type == DEVICE_TYPE_THERMOSTAT:
                # Thermostat panel — validate sub-functions (same logic as add)
                ac_enabled = user_input.get("enable_ac", False)
                fh_enabled = user_input.get("enable_fh", False)
                fa_enabled = user_input.get("enable_fa", False)

                if not any([ac_enabled, fh_enabled, fa_enabled]):
                    errors["base"] = "至少需要启用一个子功能（空调/地暖/新风）"

                if ac_enabled and fa_enabled:
                    errors["base"] = "空调和新风不能同时使用（面板不支持同时启用）"

                ac_addr = fh_addr = fa_addr = None
                if ac_enabled:
                    try:
                        ac_addr = int(user_input.get("ac_address", ""))
                        if not (SICOO_ADDR_MIN <= ac_addr <= SICOO_ADDR_MAX):
                            errors["ac_address"] = "invalid_thermostat_address"
                    except (ValueError, TypeError):
                        errors["ac_address"] = "invalid_thermostat_address"
                if fh_enabled:
                    try:
                        fh_addr = int(user_input.get("fh_address", ""))
                        if not (SICOO_ADDR_MIN <= fh_addr <= SICOO_ADDR_MAX):
                            errors["fh_address"] = "invalid_thermostat_address"
                    except (ValueError, TypeError):
                        errors["fh_address"] = "invalid_thermostat_address"
                if fa_enabled:
                    try:
                        fa_addr = int(user_input.get("fa_address", ""))
                        if not (SICOO_ADDR_MIN <= fa_addr <= SICOO_ADDR_MAX):
                            errors["fa_address"] = "invalid_thermostat_address"
                    except (ValueError, TypeError):
                        errors["fa_address"] = "invalid_thermostat_address"

                # Check duplicate addresses among enabled sub-functions
                seen = {}
                if ac_enabled and ac_addr is not None:
                    seen[ac_addr] = "ac"
                if fh_enabled and fh_addr is not None:
                    if fh_addr in seen:
                        errors["fh_address"] = "duplicate_thermostat_address"
                        self._dup_device_name = "空调与地暖地址相同"
                    else:
                        seen[fh_addr] = "fh"
                if fa_enabled and fa_addr is not None:
                    if fa_addr in seen:
                        errors["fa_address"] = "duplicate_thermostat_address"
                        self._dup_device_name = f"{'空调' if seen[fa_addr] == 'ac' else '地暖'}与新风地址相同"
                    else:
                        seen[fa_addr] = "fa"

                if not errors:
                    self._devices[idx] = {
                        "id": dev_id,
                        "connection_id": conn_id,
                        "name": user_input.get("name", ""),
                        "device_type": DEVICE_TYPE_THERMOSTAT,
                        "ac": {"enabled": ac_enabled, "address": str(ac_addr) if ac_addr else "1"},
                        "floor_heating": {"enabled": fh_enabled, "address": str(fh_addr) if fh_addr else "1"},
                        "fresh_air": {"enabled": fa_enabled, "address": str(fa_addr) if fa_addr else "1"},
                    }
                    return await self._apply_and_reload()
            else:
                # Non-keypad, non-occupancy device
                try:
                    group = _validate_group(user_input["group"])
                except ValueError:
                    errors["group"] = "group_hex"

                address = user_input.get("address", "").strip().upper()
                if not ADDRESS_PATTERN.match(address):
                    errors["address"] = "invalid_device_address"

                if not errors:
                    dup = _check_duplicate(self._devices, conn_id, group, address,
                                           exclude_device_id=dev_id)
                    if dup:
                        errors["group"] = "duplicate_device"
                        self._dup_device_name = dup

                if not errors:
                    conflict = _check_address_conflict(
                        self._devices, conn_id, address, exclude_device_id=dev_id)
                    if conflict:
                        errors["address"] = "duplicate_device"
                        self._dup_device_name = conflict

                if not errors:
                    self._devices[idx] = {
                        "id": dev_id,
                        "connection_id": conn_id,
                        "name": user_input.get("name", ""),
                        "device_type": device_type,
                        "group": group,
                        "address": address,
                    }
                    return await self._apply_and_reload()

        # --- Build form (keypad vs non-keypad) ---
        is_keypad = dev.get("device_type") == DEVICE_TYPE_KEYPAD
        is_occupancy = dev.get("device_type") == DEVICE_TYPE_OCCUPANCY
        is_io_module = dev.get("device_type") == DEVICE_TYPE_IO_MODULE
        is_dali_scene = dev.get("device_type") == DEVICE_TYPE_DALI_SCENE
        is_thermostat = dev.get("device_type") == DEVICE_TYPE_THERMOSTAT
        ph = {}
        if self._dup_device_name:
            ph["dup_name"] = self._dup_device_name
            self._dup_device_name = None
        else:
            ph["dup_name"] = ""

        if is_keypad:
            has_lock = bool(dev.get("lock_group") and dev.get("lock_address"))
            has_sleep = bool(dev.get("sleep_group") and dev.get("sleep_address"))
            has_backlight = bool(dev.get("backlight_group") and dev.get("backlight_address"))
            schema = vol.Schema({
                vol.Required("connection_id", default=dev.get("connection_id", "")): vol.In(conn_options),
                vol.Required("name", default=dev["name"]): str,
                vol.Required("device_type", default=DEVICE_TYPE_KEYPAD): vol.In(DEVICE_TYPE_OPTIONS),
                vol.Required("panel_address", default=dev.get("panel_address", "")): cv.string,
                vol.Optional("enable_lock", default=has_lock): bool,
                vol.Optional("lock_group", default=dev.get("lock_group", "")): cv.string,
                vol.Optional("lock_address", default=dev.get("lock_address", "")): cv.string,
                vol.Optional("enable_sleep", default=has_sleep): bool,
                vol.Optional("sleep_group", default=dev.get("sleep_group", "")): cv.string,
                vol.Optional("sleep_address", default=dev.get("sleep_address", "")): cv.string,
                vol.Optional("enable_backlight", default=has_backlight): bool,
                vol.Optional("backlight_group", default=dev.get("backlight_group", "")): cv.string,
                vol.Optional("backlight_address", default=dev.get("backlight_address", "")): cv.string,
            })
        elif is_occupancy:
            schema = vol.Schema({
                vol.Required("connection_id", default=dev.get("connection_id", "")): vol.In(conn_options),
                vol.Required("name", default=dev["name"]): str,
                vol.Required("device_type", default=DEVICE_TYPE_OCCUPANCY): vol.In(DEVICE_TYPE_OPTIONS),
                vol.Required("address", default=dev.get("address", "")): cv.string,
            })
        elif is_io_module:
            schema = vol.Schema({
                vol.Required("connection_id", default=dev.get("connection_id", "")): vol.In(conn_options),
                vol.Required("name", default=dev["name"]): str,
                vol.Required("device_type", default=DEVICE_TYPE_IO_MODULE): vol.In(DEVICE_TYPE_OPTIONS),
                vol.Required("address", default=dev.get("address", "")): cv.string,
            })
        elif is_dali_scene:
            schema = vol.Schema({
                vol.Required("connection_id", default=dev.get("connection_id", "")): vol.In(conn_options),
                vol.Required("name", default=dev["name"]): str,
                vol.Required("device_type", default=DEVICE_TYPE_DALI_SCENE): vol.In(DEVICE_TYPE_OPTIONS),
                vol.Required("port", default=dev.get("port", "0")): vol.In({
                    "0": "0 - 第1路", "1": "1 - 第2路",
                    "2": "2 - 第3路", "3": "3 - 第4路",
                }),
                vol.Required("group", default=dev.get("group", "00")): cv.string,
                vol.Required("scene", default=dev.get("scene", "09")): cv.string,
            })
        elif is_thermostat:
            ac = dev.get("ac", {})
            fh = dev.get("floor_heating", {})
            fa = dev.get("fresh_air", {})
            schema = vol.Schema({
                vol.Required("connection_id", default=dev.get("connection_id", "")): vol.In(conn_options),
                vol.Required("name", default=dev["name"]): str,
                vol.Required("device_type", default=DEVICE_TYPE_THERMOSTAT): vol.In(DEVICE_TYPE_OPTIONS),
                vol.Required("enable_ac", default=ac.get("enabled", True)): bool,
                vol.Optional("ac_address", default=str(ac.get("address", "1"))):  cv.string,
                vol.Required("enable_fh", default=fh.get("enabled", False)): bool,
                vol.Optional("fh_address", default=str(fh.get("address", "1"))):  cv.string,
                vol.Required("enable_fa", default=fa.get("enabled", False)): bool,
                vol.Optional("fa_address", default=str(fa.get("address", "1"))):  cv.string,
            })
        else:
            # Non-keypad, non-occupancy device
            schema = vol.Schema({
                vol.Required("connection_id", default=dev.get("connection_id", "")): vol.In(conn_options),
                vol.Required("name", default=dev["name"]): str,
                vol.Required("device_type", default=dev["device_type"]): vol.In(DEVICE_TYPE_OPTIONS),
                vol.Required("group", default=dev["group"]): cv.string,
                vol.Required("address", default=dev["address"]): cv.string,
            })

        return self.async_show_form(
            step_id="edit_device",
            data_schema=schema,
            errors=errors,
            description_placeholders=ph,
        )

    async def async_step_confirm_delete_device(self, user_input: Optional[Dict[str, Any]] = None):
        """Confirm device deletion."""
        idx = self._editing_dev_index
        if idx is None or idx >= len(self._devices):
            return await self.async_step_manage_devices()

        dev = self._devices[idx]

        if user_input is not None:
            if user_input.get("confirm"):
                dev_id = dev.get("id")
                # If deleting a VRV controller, also delete its indoor units
                if dev.get("device_type") == DEVICE_TYPE_VRV_CONTROLLER:
                    self._devices = [d for d in self._devices if d.get("parent_id") != dev_id]
                # If deleting a VRV indoor unit, also remove its parent controller
                # if this was the last indoor unit for that controller.
                if dev.get("device_type") == DEVICE_TYPE_VRV_INDOOR:
                    parent_id = dev.get("parent_id")
                    if parent_id:
                        remaining = [
                            d for d in self._devices
                            if d.get("parent_id") == parent_id
                            and d.get("device_type") == DEVICE_TYPE_VRV_INDOOR
                        ]
                        if len(remaining) <= 1:
                            self._devices = [
                                d for d in self._devices
                                if d.get("id") != parent_id
                            ]
                self._devices.pop(idx)
                return await self._apply_and_reload()
            return await self.async_step_manage_devices()

        # Extra warning for VRV controllers
        extra_msg = ""
        if dev.get("device_type") == DEVICE_TYPE_VRV_CONTROLLER:
            unit_count = sum(1 for d in self._devices if d.get("parent_id") == dev.get("id"))
            if unit_count > 0:
                extra_msg = f"\n\n⚠ 将同时删除 {unit_count} 台内机！"

        return self.async_show_form(
            step_id="confirm_delete_device",
            data_schema=vol.Schema({vol.Required("confirm", default=False): bool}),
            description_placeholders={
                "device_name": dev["name"],
                "device_type": DEVICE_TYPE_LABELS.get(dev.get("device_type", ""), "?"),
            },
        )

    # ================================================================== CONNECTIONS

    async def async_step_manage_connections(self, user_input: Optional[Dict[str, Any]] = None):
        """Paginated connection list."""
        if not self._connections:
            return self.async_show_form(
                step_id="manage_connections",
                data_schema=vol.Schema({
                    vol.Required("action"): vol.In({
                        "add": "添加连接",
                        "back": "← 返回主菜单（暂无连接）",
                    })
                }),
                description_placeholders={"page_info": "", "conn_list": "（暂无连接）"},
            )

        total_pages = (len(self._connections) + self.PAGE_SIZE - 1) // self.PAGE_SIZE
        self._manage_conn_page = max(0, min(self._manage_conn_page, total_pages - 1))
        page = self._manage_conn_page
        start = page * self.PAGE_SIZE
        end = min(start + self.PAGE_SIZE, len(self._connections))

        if user_input is not None:
            action = user_input["action"]
            if action == "back":
                return await self.async_step_init()
            if action == "add":
                return await self.async_step_add_connection()
            if action == "next":
                self._manage_conn_page = min(page + 1, total_pages - 1)
                return await self.async_step_manage_connections()
            if action == "prev":
                self._manage_conn_page = max(page - 1, 0)
                return await self.async_step_manage_connections()
            self._editing_conn_index = int(action)
            return await self.async_step_connection_action()

        # Build display lines
        lines = []
        for i in range(start, end):
            conn = self._connections[i]
            dev_count = sum(1 for d in self._devices if d.get("connection_id") == conn["id"])
            lines.append(f"  #{i + 1}  {_conn_label(conn)}  ({dev_count} 个设备)")

        options = {}
        for i in range(start, end):
            conn = self._connections[i]
            options[str(i)] = f"#{i + 1}  {conn['name']}"

        options["add"] = "＋ 添加连接"
        if total_pages > 1:
            if page > 0:
                options["prev"] = "◀ 上一页"
            if page < total_pages - 1:
                options["next"] = "下一页 ▶"
        options["back"] = "← 返回主菜单"

        return self.async_show_form(
            step_id="manage_connections",
            data_schema=vol.Schema({vol.Required("action"): vol.In(options)}),
            description_placeholders={
                "conn_list": "\n".join(lines),
                "page_info": f"第 {page + 1}/{total_pages} 页，共 {len(self._connections)} 个连接",
            },
        )

    async def async_step_connection_action(self, user_input: Optional[Dict[str, Any]] = None):
        """Edit or delete a connection."""
        idx = self._editing_conn_index
        if idx is None or idx >= len(self._connections):
            return await self.async_step_manage_connections()

        conn = self._connections[idx]
        dev_count = sum(1 for d in self._devices if d.get("connection_id") == conn["id"])

        if user_input is not None:
            action = user_input["action"]
            if action == "back":
                return await self.async_step_manage_connections()
            if action == "edit":
                return await self.async_step_edit_connection()
            if action == "delete":
                return await self.async_step_confirm_delete_connection()

        return self.async_show_form(
            step_id="connection_action",
            data_schema=vol.Schema({
                vol.Required("action"): vol.In({
                    "edit": f"编辑: {conn['name']}",
                    "delete": f"删除: {conn['name']}",
                    "back": "← 返回连接列表",
                })
            }),
            description_placeholders={
                "conn_name": conn["name"],
                "conn_detail": _conn_label(conn),
                "dev_count": str(dev_count),
            },
        )

    async def async_step_edit_connection(self, user_input: Optional[Dict[str, Any]] = None):
        """Edit a connection - support arbitrary type switching.

        If user changes connection_type and submits, we detect the change,
        persist the new type immediately (clearing old-type fields),
        then re-render the form with fields for the NEW type.
        This works no matter how many times the user switches back and forth.
        """
        errors = {}
        idx = self._editing_conn_index
        if idx is None or idx >= len(self._connections):
            return await self.async_step_manage_connections()

        conn = self._connections[idx]

        if user_input is not None:
            new_conn_type = user_input["connection_type"]
            old_conn_type = conn.get("connection_type", CONN_TYPE_TCP)

            # ── Type switched? ──
            if new_conn_type != old_conn_type:
                # 1. Update connection type in memory
                conn["connection_type"] = new_conn_type

                # 2. Clear old-type fields
                if new_conn_type == CONN_TYPE_TCP:
                    # Switching TO tcp: clear serial fields
                    conn["serial_port"] = ""
                    conn["baudrate"] = DEFAULT_BAUDRATE
                else:
                    # Switching TO serial: clear tcp fields
                    conn["tcp_host"] = ""
                    conn["tcp_port"] = DEFAULT_PORT

                # 3. Update name if provided
                if user_input.get("name"):
                    conn["name"] = user_input["name"]

                # 4. Persist immediately (so re-render reads correct type)
                new_data = dict(self._config_entry.data)
                new_data["connections"] = self._connections
                self.hass.config_entries.async_update_entry(self._config_entry, data=new_data)

                _LOGGER.debug(
                    "Connection type switched: %s → %s, re-rendering form",
                    old_conn_type, new_conn_type,
                )
                # 5. Re-render form with new type's fields
                return await self.async_step_edit_connection()

            # ── Type unchanged = save ──
            conn["name"] = user_input.get("name", conn["name"])
            if new_conn_type == CONN_TYPE_TCP:
                conn["tcp_host"] = user_input.get("tcp_host", "")
                conn["tcp_port"] = user_input.get("tcp_port", DEFAULT_PORT)
                conn["serial_port"] = ""
                conn["baudrate"] = DEFAULT_BAUDRATE
            else:
                conn["serial_port"] = user_input.get("serial_port", "")
                conn["baudrate"] = user_input.get("baudrate", DEFAULT_BAUDRATE)
                conn["tcp_host"] = ""
                conn["tcp_port"] = DEFAULT_PORT

            self._connections[idx] = conn
            return await self._apply_and_reload()

        # ── Render form ──
        conn_type = conn.get("connection_type", CONN_TYPE_TCP)
        current_port = conn.get("serial_port", "")

        if conn_type == CONN_TYPE_TCP:
            schema = vol.Schema({
                vol.Required("name", default=conn.get("name", "")): str,
                vol.Required("connection_type", default=conn_type): vol.In(CONN_TYPE_OPTIONS),
                vol.Required("tcp_host", default=conn.get("tcp_host", "")): str,
                vol.Required("tcp_port", default=conn.get("tcp_port", DEFAULT_PORT)): int,
            })
        else:
            # Serial: build port options for dropdown
            port_validator = self._build_serial_port_schema(
                errors, current_port=current_port
            )

            schema = vol.Schema({
                vol.Required("name", default=conn.get("name", "")): str,
                vol.Required("connection_type", default=conn_type): vol.In(CONN_TYPE_OPTIONS),
                vol.Required("serial_port", default=current_port or ""): port_validator,
                vol.Optional("baudrate", default=conn.get("baudrate", DEFAULT_BAUDRATE)): int,
            })

        return self.async_show_form(
            step_id="edit_connection",
            data_schema=schema,
            errors=errors,
            description_placeholders={
                "conn_name": conn["name"],
                "dev_count": str(sum(1 for d in self._devices if d.get("connection_id") == conn["id"])),
            },
        )

    async def async_step_add_connection(self, user_input: Optional[Dict[str, Any]] = None):
        """Select type for new connection."""
        if user_input is not None:
            self._pending_conn_type = user_input["connection_type"]
            self._pending_conn_id = _new_id()
            return await self.async_step_add_connection_params()

        return self.async_show_form(
            step_id="add_connection",
            data_schema=vol.Schema({
                vol.Required("connection_type"): vol.In(CONN_TYPE_OPTIONS),
            }),
        )

    async def async_step_add_connection_params(self, user_input: Optional[Dict[str, Any]] = None):
        """Enter params for new connection - show ONLY fields for selected type."""
        errors = {}

        if user_input is not None:
            conn_type = user_input["connection_type"]
            conn = {
                "id": self._pending_conn_id or _new_id(),
                "name": user_input.get("name", f"连接{len(self._connections) + 1}"),
                "connection_type": conn_type,
            }
            if conn_type == CONN_TYPE_TCP:
                conn["tcp_host"] = user_input.get("tcp_host", "")
                conn["tcp_port"] = user_input.get("tcp_port", DEFAULT_PORT)
                conn["serial_port"] = ""
                conn["baudrate"] = DEFAULT_BAUDRATE
            else:
                conn["serial_port"] = user_input.get("serial_port", "")
                conn["baudrate"] = user_input.get("baudrate", DEFAULT_BAUDRATE)
                conn["tcp_host"] = ""
                conn["tcp_port"] = DEFAULT_PORT
            self._connections.append(conn)

            # Persist without closing the options flow
            new_data = dict(self._config_entry.data)
            new_data["connections"] = self._connections
            new_data["devices"] = self._devices
            self.hass.config_entries.async_update_entry(self._config_entry, data=new_data)

            return await self.async_step_manage_connections()

        pending_type = self._pending_conn_type or CONN_TYPE_TCP

        if pending_type == CONN_TYPE_TCP:
            # TCP only: show name, type, host, port
            schema = vol.Schema({
                vol.Required("name", default=f"连接{len(self._connections) + 1}"): str,
                vol.Required("connection_type", default=pending_type): vol.In(CONN_TYPE_OPTIONS),
                vol.Required("tcp_host"): str,
                vol.Required("tcp_port", default=DEFAULT_PORT): int,
            })
        else:
            # Serial only: show name, type, serial_port, baudrate
            port_validator = self._build_serial_port_schema(errors)

            schema = vol.Schema({
                vol.Required("name", default=f"连接{len(self._connections) + 1}"): str,
                vol.Required("connection_type", default=pending_type): vol.In(CONN_TYPE_OPTIONS),
                vol.Required("serial_port"): port_validator,
                vol.Optional("baudrate", default=DEFAULT_BAUDRATE): int,
            })

        return self.async_show_form(
            step_id="add_connection_params",
            data_schema=schema,
            errors=errors,
        )

    async def async_step_confirm_delete_connection(self, user_input: Optional[Dict[str, Any]] = None):
        """Confirm connection deletion. Warns about affected devices."""
        idx = self._editing_conn_index
        if idx is None or idx >= len(self._connections):
            return await self.async_step_manage_connections()

        conn = self._connections[idx]
        affected = [d for d in self._devices if d.get("connection_id") == conn["id"]]

        if user_input is not None:
            if user_input.get("confirm"):
                self._connections.pop(idx)
                # Remove devices that belonged to this connection
                self._devices = [d for d in self._devices if d.get("connection_id") != conn["id"]]
                return await self._apply_and_reload()
            return await self.async_step_manage_connections()

        return self.async_show_form(
            step_id="confirm_delete_connection",
            data_schema=vol.Schema({vol.Required("confirm", default=False): bool}),
            description_placeholders={
                "conn_name": conn["name"],
                "affected_count": str(len(affected)),
                "affected_names": ", ".join(d["name"] for d in affected) or "无",
            },
        )

    # ================================================================== VRV CONTROLLER

    def _ensure_vrv_controller(self, connection_id: str) -> str:
        """Ensure a VRV controller record exists for the given connection.

        If one already exists, return its id.  Otherwise create a new record
        and return the new id.  The controller uses the connection's host/port
        at runtime — no separate IP config is needed.
        """
        existing = [
            d for d in self._devices
            if d.get("device_type") == DEVICE_TYPE_VRV_CONTROLLER
            and d.get("connection_id") == connection_id
        ]
        if existing:
            return existing[0]["id"]

        conn = next((c for c in self._connections if c["id"] == connection_id), None)
        name = f"{conn['name']} 空调" if conn else "VRV控制器"
        vrv_id = _new_id()
        self._devices.append({
            "id": vrv_id,
            "name": name,
            "device_type": DEVICE_TYPE_VRV_CONTROLLER,
            "connection_id": connection_id,
            "host": conn.get("host", "") if conn else "",
            "port": conn.get("port", 0) if conn else 0,
        })
        return vrv_id

    async def async_step_manage_vrv(self, user_input: Optional[Dict[str, Any]] = None):
        """Manage VRV controllers: list, add, edit, delete."""
        vrv_list = [d for d in self._devices if d.get("device_type") == DEVICE_TYPE_VRV_CONTROLLER]

        if user_input is not None:
            action = user_input["action"]
            if action == "add":
                return await self.async_step_add_vrv()
            if action == "back":
                return await self.async_step_init()
            # Select a VRV controller
            self._editing_vrv_id = action
            return await self.async_step_vrv_action()

        options = {}
        for vrv in vrv_list:
            conn_id = vrv.get("connection_id", "")
            conn = next((c for c in self._connections if c["id"] == conn_id), None)
            conn_label = _conn_label(conn) if conn else f"{vrv.get('host', '?')}:{vrv.get('port', '?')}"
            unit_count = sum(1 for d in self._devices if d.get("parent_id") == vrv["id"])
            options[vrv["id"]] = f"{vrv.get('name', '?')}  [{conn_label}]  ({unit_count}台内机)"
        options["add"] = "＋ 添加VRV控制器"
        options["back"] = "← 返回"

        vrv_info = "暂无VRV控制器" if not vrv_list else f"共 {len(vrv_list)} 台VRV控制器"

        return self.async_show_form(
            step_id="manage_vrv",
            data_schema=vol.Schema({vol.Required("action"): vol.In(options)}),
            description_placeholders={"vrv_info": vrv_info},
        )

    async def async_step_add_vrv(self, user_input: Optional[Dict[str, Any]] = None):
        """Add a new VRV controller — pick a bus connection to bind to."""
        errors = {}
        conn_options = {c["id"]: _conn_label(c) for c in self._connections}
        if user_input is not None:
            conn_id = user_input["connection_id"]
            name = user_input.get("name", "").strip()
            if not name:
                errors["name"] = "name_required"
            if not conn_id:
                errors["connection_id"] = "no_connections"
            if not errors:
                # Check duplicate: one connection = one VRV controller max
                conn = next((c for c in self._connections if c["id"] == conn_id), None)
                existing = [
                    d for d in self._devices
                    if d.get("device_type") == DEVICE_TYPE_VRV_CONTROLLER
                    and d.get("connection_id") == conn_id
                ]
                if existing:
                    errors["connection_id"] = "duplicate_vrv"
                else:
                    vrv_id = _new_id()
                    self._devices.append({
                        "id": vrv_id,
                        "name": name,
                        "device_type": DEVICE_TYPE_VRV_CONTROLLER,
                        "connection_id": conn_id,
                        "host": conn.get("host", "") if conn else "",
                        "port": conn.get("port", 0) if conn else 0,
                    })
                    self._editing_vrv_id = vrv_id
                    return await self.async_step_vrv_action()

        return self.async_show_form(
            step_id="add_vrv",
            data_schema=vol.Schema({
                vol.Required("name", default=""): str,
                vol.Required("connection_id"): vol.In(conn_options) if conn_options else str,
            }),
            errors=errors,
        )

    async def async_step_vrv_action(self, user_input: Optional[Dict[str, Any]] = None):
        """Actions for a selected VRV controller."""
        vrv_id = self._editing_vrv_id
        vrv = next((d for d in self._devices if d.get("id") == vrv_id), None)
        if not vrv:
            return await self.async_step_manage_vrv()

        indoor_units = [d for d in self._devices if d.get("parent_id") == vrv_id]

        if user_input is not None:
            action = user_input["action"]
            if action == "scan":
                return await self.async_step_vrv_scan()
            if action == "add_manual":
                return await self.async_step_vrv_add_indoor()
            if action == "back":
                return await self.async_step_init()
            if action == "done":
                return await self._apply_and_reload()
            # Select indoor unit
            self._editing_vrv_unit_id = action
            return await self.async_step_vrv_indoor_action()

        options = {"scan": "🔍 自动搜索内机", "add_manual": "✏️ 手动添加内机",
                   "done": "💾 保存并退出", "back": "← 返回主菜单"}
        if indoor_units:
            for unit in indoor_units:
                options[unit["id"]] = f"编辑/删除: {unit.get('name', '?')} (ID={unit.get('unit_id', '?')})"

        unit_info = f"已添加 {len(indoor_units)} 台内机" if indoor_units else "暂无内机"

        return self.async_show_form(
            step_id="vrv_action",
            data_schema=vol.Schema({vol.Required("action"): vol.In(options)}),
            description_placeholders={
                "vrv_name": vrv.get("name", ""),
                "unit_count": str(len(indoor_units)),
                "unit_info": unit_info,
                "conn_info": _conn_label_for_vrv(vrv, self._connections),
            },
        )

    async def async_step_edit_vrv(self, user_input: Optional[Dict[str, Any]] = None):
        """Edit VRV controller properties."""
        vrv_id = self._editing_vrv_id
        vrv_idx = None
        for i, d in enumerate(self._devices):
            if d.get("id") == vrv_id:
                vrv_idx = i
                break

        if vrv_idx is None:
            return await self.async_step_manage_vrv()

        vrv = self._devices[vrv_idx]
        conn_options = {c["id"]: _conn_label(c) for c in self._connections}
        errors = {}
        if user_input is not None:
            name = user_input.get("name", "").strip()
            conn_id = user_input.get("connection_id", "")
            if not name:
                errors["name"] = "name_required"
            if not errors:
                self._devices[vrv_idx]["name"] = name
                if conn_id:
                    conn_real = next((c for c in self._connections if c["id"] == conn_id), None)
                    if conn_real:
                        self._devices[vrv_idx]["connection_id"] = conn_id
                        self._devices[vrv_idx]["host"] = conn_real.get("host", "")
                        self._devices[vrv_idx]["port"] = conn_real.get("port", 0)
                return await self.async_step_vrv_action()

        return self.async_show_form(
            step_id="edit_vrv",
            data_schema=vol.Schema({
                vol.Required("name", default=vrv.get("name", "")): str,
                vol.Optional("connection_id", default=vrv.get("connection_id", "")): vol.In(conn_options) if conn_options else str,
            }),
            errors=errors,
        )

    async def async_step_delete_vrv_confirm(self, user_input: Optional[Dict[str, Any]] = None):
        """Confirm deletion of a VRV controller and all its indoor units."""
        vrv_id = self._editing_vrv_id
        if user_input is not None:
            if user_input.get("confirm"):
                # Remove VRV controller
                self._devices = [d for d in self._devices if d.get("id") != vrv_id]
                # Remove all associated indoor units
                self._devices = [d for d in self._devices if d.get("parent_id") != vrv_id]
                return await self.async_step_manage_vrv()
            return await self.async_step_vrv_action()

        vrv = next((d for d in self._devices if d.get("id") == vrv_id), {})
        unit_count = sum(1 for d in self._devices if d.get("parent_id") == vrv_id)

        return self.async_show_form(
            step_id="delete_vrv_confirm",
            data_schema=vol.Schema({vol.Required("confirm"): bool}),
            description_placeholders={
                "vrv_name": vrv.get("name", "?"),
                "unit_count": str(unit_count),
            },
        )

    async def async_step_vrv_scan(self, user_input: Optional[Dict[str, Any]] = None):
        """Scan for indoor units on a VRV controller."""
        vrv_id = self._editing_vrv_id
        vrv = next((d for d in self._devices if d.get("id") == vrv_id), None)
        if not vrv:
            return await self.async_step_manage_vrv()

        if user_input is not None:
            if user_input.get("action") == "back":
                return await self.async_step_vrv_action()

            # Add selected indoor units
            selected = user_input.get("selected_units", [])
            existing_ids = {d.get("unit_id", "") for d in self._devices if d.get("parent_id") == vrv_id}
            for unit_id in selected:
                if unit_id not in existing_ids:
                    self._devices.append({
                        "id": _new_id(),
                        "name": f"室内机 {unit_id}",
                        "device_type": DEVICE_TYPE_VRV_INDOOR,
                        "parent_id": vrv_id,
                        "unit_id": unit_id,
                    })
            return await self.async_step_vrv_action()

        # Perform scan — create a temporary transport for discovery
        from .device.vrv_controller import discover_indoor_units
        from .transport.tcp_transport import TCPTransport

        # Resolve connection host from the VRV controller's binding
        conn_id = vrv.get("connection_id", "")
        conn = next((c for c in self._connections if c["id"] == conn_id), None)
        host = conn.get("host", "") if conn else vrv.get("host", "")
        port = conn.get("port", 0) if conn else vrv.get("port", 0)

        tmp_transport = TCPTransport(host, port)
        try:
            connected = await tmp_transport.connect()
            if not connected:
                return self.async_show_form(
                    step_id="vrv_scan",
                    data_schema=vol.Schema({vol.Required("action"): vol.In({"back": "← 返回（连接失败）"})}),
                    description_placeholders={"scan_result": "无法连接到VRV控制器"},
                )
            # Send stat2 and read response directly (no feedback listener
            # on this temporary transport)
            await tmp_transport.send_command("stat2\r\n")
            await asyncio.sleep(0.5)
            raw = await tmp_transport.read(4096) or ""
            await tmp_transport.disconnect()
        except Exception as e:
            _LOGGER.error("VRV scan error: %s", e)
            return self.async_show_form(
                step_id="vrv_scan",
                data_schema=vol.Schema({vol.Required("action"): vol.In({"back": "← 返回（扫描失败）"})}),
                description_placeholders={"scan_result": f"扫描出错: {e}"},
            )

        found_ids = discover_indoor_units(raw)
        existing_ids = {d.get("unit_id", "") for d in self._devices if d.get("parent_id") == vrv_id}

        if not found_ids:
            return self.async_show_form(
                step_id="vrv_scan",
                data_schema=vol.Schema({vol.Required("action"): vol.In({
                    "back": "← 返回",
                })}),
                description_placeholders={"scan_result": "未发现内机，请确认控制器已开机并有内机在线"},
            )

        # Show found units, allow multi-select
        new_units = [uid for uid in found_ids if uid not in existing_ids]
        already_added = [uid for uid in found_ids if uid in existing_ids]

        scan_info = f"发现 {len(found_ids)} 台内机"
        if new_units:
            scan_info += f"，{len(new_units)} 台未添加"
        if already_added:
            scan_info += f"，{len(already_added)} 台已添加"

        if not new_units:
            return self.async_show_form(
                step_id="vrv_scan",
                data_schema=vol.Schema({vol.Required("action"): vol.In({"back": "← 返回"})}),
                description_placeholders={"scan_result": "所有内机已添加"},
            )

        unit_options = {uid: f"ID={uid}" for uid in new_units}

        return self.async_show_form(
            step_id="vrv_scan",
            data_schema=vol.Schema({
                vol.Required("selected_units"): cv.multi_select(unit_options),
            }),
            description_placeholders={"scan_result": scan_info},
        )

    async def async_step_vrv_add_indoor(self, user_input: Optional[Dict[str, Any]] = None):
        """Manually add an indoor unit."""
        vrv_id = self._editing_vrv_id
        errors = {}
        if user_input is not None:
            unit_id = user_input["unit_id"].strip()
            name = user_input.get("name", "").strip() or f"室内机 {unit_id}"
            if not unit_id:
                errors["unit_id"] = "id_required"
            existing = any(
                d.get("parent_id") == vrv_id and d.get("unit_id", "").upper() == unit_id.upper()
                for d in self._devices
            )
            if existing:
                errors["unit_id"] = "duplicate_unit"
            if not errors:
                self._devices.append({
                    "id": _new_id(),
                    "name": name,
                    "device_type": DEVICE_TYPE_VRV_INDOOR,
                    "parent_id": vrv_id,
                    "unit_id": unit_id.upper(),
                })
                return await self.async_step_vrv_action()

        return self.async_show_form(
            step_id="vrv_add_indoor",
            data_schema=vol.Schema({
                vol.Required("unit_id", default=""): str,
                vol.Optional("name", default=""): str,
            }),
            errors=errors,
        )

    async def async_step_vrv_indoor_action(self, user_input: Optional[Dict[str, Any]] = None):
        """Edit or delete an indoor unit."""
        unit_dev_id = self._editing_vrv_unit_id
        unit = next((d for d in self._devices if d.get("id") == unit_dev_id), None)
        if not unit:
            return await self.async_step_vrv_action()

        if user_input is not None:
            action = user_input["action"]
            if action == "edit":
                return await self.async_step_vrv_edit_indoor()
            if action == "delete":
                self._devices = [d for d in self._devices if d.get("id") != unit_dev_id]
                return await self.async_step_vrv_action()
            if action == "back":
                return await self.async_step_vrv_action()

        return self.async_show_form(
            step_id="vrv_indoor_action",
            data_schema=vol.Schema({
                vol.Required("action"): vol.In({
                    "edit": "编辑",
                    "delete": "删除此内机",
                    "back": "← 返回",
                }),
            }),
            description_placeholders={
                "unit_name": unit.get("name", ""),
                "unit_id": unit.get("unit_id", "?"),
            },
        )

    async def async_step_vrv_edit_indoor(self, user_input: Optional[Dict[str, Any]] = None):
        """Edit indoor unit name and/or address."""
        unit_dev_id = self._editing_vrv_unit_id
        unit_idx = None
        for i, d in enumerate(self._devices):
            if d.get("id") == unit_dev_id:
                unit_idx = i
                break

        if unit_idx is None:
            return await self.async_step_vrv_action()

        unit = self._devices[unit_idx]
        vrv_id = unit.get("parent_id", "")

        errors = {}
        if user_input is not None:
            name = user_input.get("name", "").strip()
            unit_id = user_input.get("unit_id", "").strip().upper()

            if not name:
                errors["name"] = "name_required"
            if not unit_id:
                errors["unit_id"] = "id_required"

            # Check for duplicate address among OTHER indoor units of the same VRV controller
            if unit_id and unit_id != unit.get("unit_id", "").upper():
                duplicate = any(
                    d.get("id") != unit_dev_id
                    and d.get("parent_id") == vrv_id
                    and d.get("unit_id", "").upper() == unit_id
                    for d in self._devices
                )
                if duplicate:
                    errors["unit_id"] = "duplicate_unit"

            if not errors:
                self._devices[unit_idx]["name"] = name
                self._devices[unit_idx]["unit_id"] = unit_id
                return await self._apply_and_reload()

        return self.async_show_form(
            step_id="vrv_edit_indoor",
            data_schema=vol.Schema({
                vol.Required("name", default=unit.get("name", "")): str,
                vol.Required("unit_id", default=unit.get("unit_id", "")): str,
            }),
            errors=errors,
        )


# ---------------------------------------------------------------------------
# Migration helper: convert old single-connection format to new multi-connection
# ---------------------------------------------------------------------------

def _migrate_data(raw_data: dict):
    """Return (connections, devices) from entry.data.

    If the data already has 'connections' key, use it directly.
    Otherwise, wrap the legacy single-connection fields into the new format.
    """
    if "connections" in raw_data:
        connections = _ensure_connection_ids(list(raw_data["connections"]))
        devices = _ensure_device_ids(list(raw_data.get("devices", [])))
        # Ensure all non-VRV devices have a connection_id pointing to an existing connection
        conn_ids = {c["id"] for c in connections}
        default_conn_id = connections[0]["id"] if connections else None
        for dev in devices:
            if dev.get("device_type") not in (DEVICE_TYPE_VRV_CONTROLLER, DEVICE_TYPE_VRV_INDOOR):
                if dev.get("connection_id") not in conn_ids:
                    dev["connection_id"] = default_conn_id
        return connections, devices

    # Legacy format: single connection
    conn_id = _new_id()
    conn = {"id": conn_id, "name": "默认连接", "connection_type": raw_data.get("connection_type", CONN_TYPE_TCP)}
    if conn["connection_type"] == CONN_TYPE_TCP:
        conn["tcp_host"] = raw_data.get("tcp_host", "")
        conn["tcp_port"] = raw_data.get("tcp_port", DEFAULT_PORT)
    else:
        conn["serial_port"] = raw_data.get("serial_port", "")
        conn["baudrate"] = raw_data.get("baudrate", DEFAULT_BAUDRATE)

    connections = [conn]
    devices = _ensure_device_ids(list(raw_data.get("devices", [])))
    for dev in devices:
        if dev.get("device_type") not in (DEVICE_TYPE_VRV_CONTROLLER, DEVICE_TYPE_VRV_INDOOR):
            if "connection_id" not in dev:
                dev["connection_id"] = conn_id

    return connections, devices
