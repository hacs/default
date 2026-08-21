"""Dercvne Bus integration for Home Assistant."""

import asyncio
import logging

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers import config_validation as cv
from homeassistant.config import ConfigType
from homeassistant.helpers import device_registry as dr

from .const import DOMAIN
from .config_flow import _migrate_data

_LOGGER = logging.getLogger(__name__)

PLATFORMS = ["switch", "light", "scene", "cover", "sensor", "binary_sensor", "climate", "fan"]

CONFIG_SCHEMA = cv.empty_config_schema(DOMAIN)


async def async_setup(hass: HomeAssistant, config: ConfigType) -> bool:
    """Set up the Dercvne Bus component."""
    return True


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Set up Dercvne Bus from a config entry."""
    hass.data.setdefault(DOMAIN, {})

    from .transport import create_transport

    # Migrate legacy single-connection data if needed
    connections, devices = _migrate_data(dict(entry.data))

    # Write migrated data back so future loads use the new format
    if "connections" not in entry.data:
        new_data = dict(entry.data)
        new_data["connections"] = connections
        new_data["devices"] = devices
        hass.config_entries.async_update_entry(entry, data=new_data)

    conn_data = {}

    for conn_cfg in connections:
        conn_id = conn_cfg["id"]
        try:
            transport = create_transport(hass, conn_cfg)
            await transport.connect()
            entity_registry = {}
            listener_task = asyncio.create_task(
                _feedback_listener(hass, entry, conn_id, transport, entity_registry)
            )
            conn_data[conn_id] = {
                "transport": transport,
                "entity_registry": entity_registry,
                "listener_task": listener_task,
                "config": conn_cfg,
            }
            _LOGGER.info(
                "Connected to DALI module via %s (%s)",
                conn_cfg.get("name", conn_id),
                conn_cfg.get("connection_type", "?"),
            )
        except Exception as e:
            _LOGGER.error(
                "Failed to connect to %s: %s",
                conn_cfg.get("name", conn_id),
                e,
            )
            # Still store an entry so platforms don't crash on key lookup
            conn_data[conn_id] = {
                "transport": None,
                "entity_registry": {},
                "listener_task": None,
                "config": conn_cfg,
            }

    hass.data[DOMAIN][entry.entry_id] = {
        "connections": conn_data,
    }

    # ── VRV Controller setup ──
    vrv_data = await _setup_vrv_controllers(hass, entry)

    hass.data[DOMAIN][entry.entry_id]["vrv_controllers"] = vrv_data

    # ── Thermostat panel setup ──
    thermostat_data = await _setup_thermostats(hass, entry)
    hass.data[DOMAIN][entry.entry_id]["thermostats"] = thermostat_data

    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)

    # ── Thermostat polling task ──
    if thermostat_data:
        poll_task = asyncio.create_task(_thermostat_polling_task(hass, entry))
        hass.data[DOMAIN][entry.entry_id]["thermostat_poll_task"] = poll_task
        _LOGGER.info(
            "Started thermostat polling for %d device(s)",
            len(thermostat_data),
        )

    # Clean up orphaned switch_as_x helpers left over by device type changes
    await _cleanup_orphaned_switch_as_x(hass, entry)

    # ── Post-setup: remove orphaned device registry entries ──
    # After platforms are reloaded, devices that no longer have any
    # entities (because they were deleted from config) will still have
    # device registry entries.  Remove them so they don't linger in
    # the UI or break automations that reference old device_ids.
    await _cleanup_orphaned_devices(hass, entry)

    _LOGGER.info(
        "Dercvne Bus entry %s setup complete (%d connections, %d devices, %d VRV controllers, %d thermostats)",
        entry.entry_id, len(connections), len(devices), len(vrv_data), len(thermostat_data),
    )

    return True


async def _cleanup_orphaned_switch_as_x(hass, entry):
    """Remove orphaned switch_as_x helpers after device type changes.

    When a user changes a device's type (e.g. relay -> light), our old
    entity is removed and a new one is created. But HA's auto-created
    switch_as_x helper config entries referencing the old entity_id
    persist as orphans, showing "已隐藏 / hidden" in the UI.

    This function scans all switch_as_x entries and removes any whose
    source entity no longer exists in the entity registry.
    """
    from homeassistant.helpers import entity_registry as er

    try:
        from homeassistant.components.switch_as_x import DOMAIN as SX_DOMAIN
    except ImportError:
        _LOGGER.debug("switch_as_x integration not available, skipping cleanup")
        return

    registry = er.async_get(hass)

    # Collect current entity IDs that belong to our config entry
    our_entity_ids = set()
    for reg_entity in registry.entities.values():
        if reg_entity.config_entry_id == entry.entry_id:
            our_entity_ids.add(reg_entity.entity_id)

    removed = 0
    for sx_entry in list(hass.config_entries.async_entries(SX_DOMAIN)):
        # switch_as_x stores the wrapped entity_id in data
        source_entity_id = (
            sx_entry.data.get("entity_id", "")
            or sx_entry.options.get("entity_id", "")
        )
        if not source_entity_id:
            continue

        # If the source entity still exists anywhere in registry, it's valid
        source = registry.async_get(source_entity_id)
        if source is not None:
            continue

        # Source entity no longer exists — switch_as_x is orphaned
        _LOGGER.info(
            "Removing orphaned switch_as_x helper '%s' (source '%s' no longer exists)",
            sx_entry.title, source_entity_id,
        )

        # Remove any entity registry entries created by this switch_as_x
        for reg_entity in list(registry.entities.values()):
            if reg_entity.config_entry_id == sx_entry.entry_id:
                registry.async_remove(reg_entity.entity_id)

        await hass.config_entries.async_remove(sx_entry.entry_id)
        removed += 1

    if removed:
        _LOGGER.info("Cleaned up %d orphaned switch_as_x helper(s)", removed)


async def _cleanup_orphaned_devices(hass, entry):
    """Remove device registry entries that have no entities after reload.

    When devices are deleted from config and the entry is reloaded,
    entities for those devices are removed but the device registry
    entries can linger.  This function removes them so the UI
    (and automations) reflect reality.
    """
    from homeassistant.helpers import entity_registry as er

    dev_registry = dr.async_get(hass)
    ent_registry = er.async_get(hass)

    # Collect entity-owned device_ids for this config entry
    live_device_ids = set()
    for entity_entry in ent_registry.entities.values():
        if entity_entry.config_entry_id == entry.entry_id:
            if entity_entry.device_id:
                live_device_ids.add(entity_entry.device_id)

    # Find device registry entries for this entry that have zero entities
    orphaned = []
    for device in dev_registry.devices.values():
        if (device.config_entries
                and entry.entry_id in device.config_entries
                and device.id not in live_device_ids):
            orphaned.append(device.id)

    for device_id in orphaned:
        if device_id in dev_registry.devices:
            dev_name = dev_registry.devices[device_id].name
            dev_registry.async_remove_device(device_id)
            _LOGGER.info("Removed orphaned device: %s (id=%s)", dev_name, device_id)

    if orphaned:
        _LOGGER.info(
            "Cleaned up %d orphaned device registry entr%s",
            len(orphaned), "y" if len(orphaned) == 1 else "ies",
        )


# ──────────────────────────────────────────────────────────────────
# VRV Controller (CoolMaster) setup and polling
# ──────────────────────────────────────────────────────────────────


async def _setup_vrv_controllers(hass, entry):
    """Set up VRV controllers from config entry data.

    Creates VRVController instances that share the bus transport,
    registers VRV response handlers, and starts polling tasks.
    Returns a dict keyed by VRV controller UUID.
    """
    from .const import DEVICE_TYPE_VRV_CONTROLLER
    from .device.vrv_controller import VRVController

    # Parse VRV controller configs
    vrv_configs = []
    connections, devices = _migrate_data(dict(entry.data))
    for dev in devices:
        if dev.get("device_type") == DEVICE_TYPE_VRV_CONTROLLER:
            vrv_configs.append(dev)

    if not vrv_configs:
        return {}

    vrv_data = {}
    entry_data = hass.data[DOMAIN].get(entry.entry_id, {})
    conn_data_map = entry_data.get("connections", {})

    for cfg in vrv_configs:
        vrv_id = cfg.get("id", "")
        if not vrv_id:
            continue

        # Resolve the bus transport from the connection
        conn_id = cfg.get("connection_id", "")
        conn = conn_data_map.get(conn_id, {})
        transport = conn.get("transport") if conn else None

        if transport is None:
            _LOGGER.warning(
                "VRV controller '%s': connection '%s' not found or not connected",
                cfg.get("name", vrv_id), conn_id,
            )

        # Create controller that shares the bus transport
        controller = VRVController(transport)
        connected = transport is not None and transport.is_connected

        # Register VRV response handler on the connection so the
        # feedback listener can route CoolMaster status data back.
        if conn:
            conn["vrv_handler"] = controller.handle_response

        poll_task = asyncio.create_task(
            _vrv_polling_task(hass, controller, vrv_id, entry.entry_id)
        )

        vrv_data[vrv_id] = {
            "controller": controller,
            "config": cfg,
            "poll_task": poll_task,
            "entities": [],
            "connected": connected,
        }

        if connected:
            _LOGGER.info(
                "VRV controller '%s' bound to connection '%s'",
                cfg.get("name", vrv_id), conn_id,
            )
        else:
            _LOGGER.warning(
                "VRV controller '%s' offline — connection '%s' is not connected",
                cfg.get("name", vrv_id), conn_id,
            )

    return vrv_data


# ──────────────────────────────────────────────────────────────────
# Thermostat Panel (X1-29-S) setup
# ──────────────────────────────────────────────────────────────────


async def _setup_thermostats(hass, entry):
    """Set up thermostat panel devices from config entry data.

    Creates ThermostatDevice instances that manage transport and
    sub-function communication, storing them in hass.data so entities
    can find them during platform setup.

    Returns a dict keyed by device UUID.
    """
    from .const import DEVICE_TYPE_THERMOSTAT
    from .device.thermostat import ThermostatDevice

    # Parse thermostat device configs from entry data
    thermostat_configs = []
    connections, devices = _migrate_data(dict(entry.data))
    for dev in devices:
        if dev.get("device_type") == DEVICE_TYPE_THERMOSTAT:
            thermostat_configs.append(dev)

    if not thermostat_configs:
        return {}

    thermostat_data = {}
    entry_data = hass.data[DOMAIN].get(entry.entry_id, {})
    conn_data_map = entry_data.get("connections", {})

    for cfg in thermostat_configs:
        device_id = cfg.get("id", "")
        if not device_id:
            continue

        # Resolve the bus transport from the connection
        conn_id = cfg.get("connection_id", "")
        conn = conn_data_map.get(conn_id, {})
        transport = conn.get("transport") if conn else None

        if transport is None:
            _LOGGER.warning(
                "Thermostat '%s': connection '%s' not found or not connected",
                cfg.get("name", device_id), conn_id,
            )

        # Create thermostat device
        try:
            thermostat = ThermostatDevice(cfg, transport)
            thermostat_data[device_id] = thermostat
        except Exception as e:
            _LOGGER.error(
                "Failed to create thermostat device '%s': %s",
                cfg.get("name", device_id), e,
            )
            continue

        if transport is not None and thermostat.is_connected:
            _LOGGER.info(
                "Thermostat '%s' bound to connection '%s'",
                cfg.get("name", device_id), conn_id,
            )
        else:
            _LOGGER.warning(
                "Thermostat '%s' may be offline — transport for '%s' is not fully connected",
                cfg.get("name", device_id), conn_id,
            )

    return thermostat_data


async def _vrv_polling_task(hass, controller, vrv_id, entry_id):
    """Background task: periodically poll VRV controller status.

    Sends stat2 every 5 seconds and updates all registered indoor unit
    climate entities with the parsed status.  Emits VRV state-change events
    for device_trigger automation support.
    """
    from .const import VRV_POLL_INTERVAL
    from .device.vrv_controller import parse_status_response
    from .device_trigger import EVENT_VRV_STATE_CHANGED

    _LOGGER.info("VRV polling started for controller %s", vrv_id)

    # Track previous state per unit_id to detect changes
    _prev_state: dict[str, dict] = {}

    while True:
        try:
            if not controller.is_connected:
                await asyncio.sleep(VRV_POLL_INTERVAL)
                continue

            raw = await controller.query_status(vrv_id)
            if raw:
                statuses = parse_status_response(raw)

                # Update all registered entities
                entry_data = hass.data.get(DOMAIN, {}).get(entry_id, {})
                vrv_data = entry_data.get("vrv_controllers", {}).get(vrv_id, {})
                entities = vrv_data.get("entities", [])

                for entity in entities:
                    unit_id = getattr(entity, "_unit_id", None)
                    if unit_id:
                        new_status = statuses.get(unit_id)
                        entity.update_status(new_status)

                        # ── State change detection for device triggers ──
                        if new_status:
                            prev = _prev_state.get(unit_id, {})
                            new_state = new_status.get("state", "")
                            new_mode = new_status.get("mode", "")

                            # Detect changes
                            prev_state = prev.get("state", "")
                            prev_mode = prev.get("mode", "")

                            changes = []
                            if new_state == "ON" and prev_state != "ON":
                                changes.append("unit_on")
                            if new_state != "ON" and prev_state == "ON":
                                changes.append("unit_off")
                            if new_mode and new_mode != prev_mode and new_state == "ON":
                                changes.append(f"mode_{new_mode}")

                            # Update previous state
                            _prev_state[unit_id] = {"state": new_state, "mode": new_mode}

                            # Fire events for each detected change
                            if changes:
                                device_registry = dr.async_get(hass)
                                # Use the stable device_id (UUID) for identifier lookup,
                                # matching what the climate entity sets in device_info.
                                stable_id = getattr(entity, "_device_id", None) or unit_id
                                device_ident = (DOMAIN, f"{entry_id}_{vrv_id}_{stable_id}")
                                device_entry = device_registry.async_get_device(identifiers={device_ident})
                                device_id = device_entry.id if device_entry else None

                                for change in changes:
                                    hass.bus.async_fire(
                                        EVENT_VRV_STATE_CHANGED,
                                        {
                                            "device_id": device_id,
                                            "change": change,
                                            "vrv_id": vrv_id,
                                            "unit_id": unit_id,
                                        },
                                    )

            await asyncio.sleep(VRV_POLL_INTERVAL)

        except asyncio.CancelledError:
            _LOGGER.info("VRV polling cancelled for controller %s", vrv_id)
            break
        except Exception as e:
            _LOGGER.error("VRV polling error [%s]: %s", vrv_id, e, exc_info=True)
            await asyncio.sleep(VRV_POLL_INTERVAL)


# ──────────────────────────────────────────────────────────────────
# Thermostat Panel (X1-29-S) polling and entity update helpers
# ──────────────────────────────────────────────────────────────────

async def _thermostat_polling_task(hass, entry):
    """Background task: poll all thermostat sub-functions every 10 seconds."""
    _LOGGER.info("Thermostat polling started for entry %s", entry.entry_id)

    while True:
        try:
            th_data = hass.data.get(DOMAIN, {}).get(entry.entry_id, {}).get("thermostats", {})
            if not th_data:
                await asyncio.sleep(30)
                continue

            for device_id, thermostat in list(th_data.items()):
                if not thermostat.is_connected:
                    continue
                for sub in ["ac", "floor_heating", "fresh_air"]:
                    if sub in thermostat.sub_funcs:
                        await thermostat.query_status(sub)
                        await asyncio.sleep(0.15)  # 100ms min interval between queries

            await asyncio.sleep(10)

        except asyncio.CancelledError:
            _LOGGER.info("Thermostat polling cancelled for entry %s", entry.entry_id)
            break
        except Exception as e:
            _LOGGER.error("Thermostat polling error [%s]: %s", entry.entry_id, e)
            await asyncio.sleep(30)


def _update_thermostat_entities(entry_data, parsed):
    """Route parsed Sicoo response to matching climate/fan entities.

    Scans the entity registry for thermostat climate entities and
    their thermostat device, matching by sub-function type and dev_id.
    """
    if parsed is None:
        return

    sub = parsed.get("sub", "")
    th_data = entry_data.get("thermostats", {})
    for th in th_data.values():
        th.update_state(parsed)


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Unload a config entry.

    Always cleans up internal state (tasks, transports) regardless of
    platform unload success.  Lingering entity registry entries are also
    removed as a safety net.

    Device registry entries are NOT touched here — they are cleaned up
    on the next async_setup_entry so existing device_ids survive reload.
    """
    from homeassistant.helpers import entity_registry as er

    entry_id = entry.entry_id
    unload_ok = await hass.config_entries.async_unload_platforms(entry, PLATFORMS)

    # ── Safety net: remove lingering entity registry entries ──
    ent_registry = er.async_get(hass)
    for entity_entry in list(ent_registry.entities.values()):
        if entity_entry.config_entry_id == entry_id:
            ent_registry.async_remove(entity_entry.entity_id)
            _LOGGER.debug(
                "Removed lingering entity registry entry: %s",
                entity_entry.entity_id,
            )

    # ── Always clean up our internal state ──
    entry_data = hass.data[DOMAIN].pop(entry_id, {})
    for conn_id, conn in entry_data.get("connections", {}).items():
        task = conn.get("listener_task")
        if task:
            task.cancel()
        transport = conn.get("transport")
        if transport:
            try:
                await transport.disconnect()
            except Exception:
                pass

    # ── Clean up VRV controllers ──
    for vrv_id, vrv in entry_data.get("vrv_controllers", {}).items():
        poll_task = vrv.get("poll_task")
        if poll_task:
            poll_task.cancel()
        controller = vrv.get("controller")
        if controller:
            try:
                await controller.disconnect()
            except Exception:
                pass

    # ── Clean up thermostat polling task ──
    thermostat_poll_task = entry_data.get("thermostat_poll_task")
    if thermostat_poll_task:
        thermostat_poll_task.cancel()
    # ────────────────────────────────

    if not unload_ok:
        _LOGGER.warning(
            "Platform unload failed for entry %s, but cleanup was performed",
            entry_id,
        )

    return unload_ok


def _parse_feedback_message(raw: str) -> list:
    """Parse a DALI feedback message into a list of event dicts.

    Supported formats (after stripping the leading ``*V;``):

    Relay / simple on-off / Keypad button event::

        @1*S,0,0,1A;          → {type:'on',  group:'0', addr:'1A'}
        @1*C,0,0,1A;          → {type:'off', group:'0', addr:'1A'}

        Keypad button events share the same format:
        @1*S,0,0,AA;           (key 1 short press, panel_address=AA)
        @1*S,0,C,AA;           (key 5 long press, panel_address=AA)
        → dispatched by checking if addr is a registered panel_address.

    Dimmer / CCT light (brightness or colour-temp adjust)::

        @1*A,0,0,02;@1*Z,019;
        → {type:'adjust', class_:0, group:'0', addr:'02', z_value:25}

        @1*A,0,1,02;@1*Z,02F;
        → {type:'adjust', class_:0, group:'1', addr:'02', z_value:47}
        （group=1 = brightness_group(0) + 1 → CT channel）

    The ``*Z`` segment carries the brightness/CT raw value (0x00–0xFF).
    It always immediately follows the ``*A`` segment in the module's output,
    so we pair them up while iterating.

    Returns a list of event dicts (may be empty if nothing meaningful found).
    """
    import re

    # Strip leading *V; if present
    if raw.startswith("*V;"):
        raw = raw[3:]

    segments = []
    for part in raw.split("@"):
        part = part.strip()
        if not part:
            continue
        star_idx = part.find("*")
        if star_idx < 0:
            continue
        cmd_body = part[star_idx + 1:]  # e.g. "S,0,0,1A;" or "A,0,0,02;" or "Z,019;"
        if ";" in cmd_body:
            cmd_body = cmd_body.split(";")[0]
        segments.append(cmd_body)

    events = []
    i = 0
    while i < len(segments):
        seg = segments[i]
        fields = seg.split(",")
        cmd_type = fields[0] if fields else ""

        if cmd_type in ("S", "C") and len(fields) >= 4:
            # Relay / simple on-off: S,class,group,addr  or  C,class,group,addr
            events.append({
                "type": "on" if cmd_type == "S" else "off",
                "group": fields[2],
                "addr": fields[3],
            })
            i += 1

        elif cmd_type == "A" and len(fields) >= 4:
            # DALI adjust: A,class,group,addr
            class_ = int(fields[1])
            group = fields[2]
            addr = fields[3]

            if class_ == 4:
                # RGB feedback (Class=4): multi-byte Z segments
                # Format: A,4,G,AA; Z,1RR; Z,1GG; Z,1BB; Z,000;
                rgb_values = []
                j = i + 1
                while j < len(segments):
                    z_fields = segments[j].split(",")
                    if z_fields[0] == "Z" and len(z_fields) >= 2:
                        z_str = z_fields[1]
                        if len(z_str) >= 2:
                            x = int(z_str[0], 16)
                            val = int(z_str[1:], 16) if len(z_str) >= 3 else 0
                            if x == 0:
                                break  # end marker (x=0)
                            rgb_values.append(val)
                    j += 1
                if len(rgb_values) >= 3:
                    events.append({
                        "type": "rgb",
                        "group": group,
                        "addr": addr,
                        "r": rgb_values[0],
                        "g": rgb_values[1],
                        "b": rgb_values[2],
                    })
                i = j  # advance past all Z segments

            else:
                # Normal adjust (brightness, CT, saturation, etc.)
                z_value = None
                if i + 1 < len(segments):
                    next_seg = segments[i + 1]
                    z_fields = next_seg.split(",")
                    if z_fields[0] == "Z" and len(z_fields) >= 2:
                        try:
                            z_value = int(z_fields[1], 16)
                        except ValueError:
                            pass
                        i += 1  # consume the Z segment
                events.append({
                    "type": "adjust",
                    "class_": class_,
                    "group": group,
                    "addr": addr,
                    "z_value": z_value,
                })
                i += 1

        else:
            i += 1

    return events


async def _feedback_listener(hass, entry, conn_id, transport, entity_registry):
    """Background task: continuously read feedback for one connection.

    Auto-reconnect: when read() detects a disconnection (empty data or
    connection error), it calls mark_disconnected().  The next loop
    iteration enters the reconnect branch and reconnects transparently.

    DALI feedback formats handled:
      *V;@1*S,0,0,1A;             → relay/switch device(0,1A) turned ON
      *V;@1*C,0,0,1A;             → relay/switch device(0,1A) turned OFF
      *V;@1*A,0,0,02;@1*Z,019;   → light brightness = 25/255 (class=0, group=G)
      *V;@1*A,0,1,02;@1*Z,02F;   → light CT = 47/255 (class=0, group=G+1 → routed back to G)
      @1*S,0,X,AA;                → keypad button event (X=0-7 short, 8-F long, AA=panel_address)
                                     fires HA event "dercvne_bus_keypad_pressed" for automations
    """
    from .const import COLOR_TEMP_MIN_K, COLOR_TEMP_MAX_K
    from .device.vrv_controller import is_vrv_response, extract_vrv_lines
    from .device_trigger import EVENT_KEYPAD_PRESSED, EVENT_IO_MODULE_PRESSED

    _LOGGER.info("Feedback listener started for connection %s", conn_id)

    reconnect_delay = 5  # seconds between reconnect attempts

    while True:
        try:
            # --- Reconnect branch ---
            if transport is None or not transport.is_connected:
                _LOGGER.warning(
                    "Transport %s disconnected, attempting reconnect...", conn_id
                )
                if transport is not None:
                    connected = await transport.connect()
                    if connected:
                        _LOGGER.info(
                            "Reconnected successfully for %s, resuming feedback", conn_id
                        )
                        await asyncio.sleep(0.5)
                        continue
                _LOGGER.debug(
                    "Reconnect failed for %s, retrying in %ds", conn_id, reconnect_delay
                )
                await asyncio.sleep(reconnect_delay)
                continue

            # --- Read branch ---
            data = await transport.read(256)
            if not data:
                continue

            _LOGGER.debug("Raw feedback [%s]: %s", conn_id, data)
            # DIAG: log raw data type and full hex dump (first 32 bytes)
            if data:
                if isinstance(data, bytes):
                    fb = data[0]
                    hex_dump = data[:32].hex(" ")
                    if len(data) > 32:
                        hex_dump += " ..."
                else:
                    fb = ord(data[0])
                    hex_dump = data[:32].encode("latin-1").hex(" ")
                _LOGGER.debug(
                    "[DIAG] [%s]: %d bytes, type=%s, hex=%s",
                    conn_id, len(data), type(data).__name__, hex_dump,
                )

            # Convert latin-1 str to bytes for binary protocol detection (Sicoo)
            data_bytes = data.encode("latin-1") if isinstance(data, str) else data

            # _parse_feedback_message expects str (DALI text protocol)
            data_str = data.decode("latin-1") if isinstance(data, bytes) else data
            events = _parse_feedback_message(data_str)

            for evt in events:
                evt_type = evt["type"]

                if evt_type in ("on", "off"):
                    group = evt["group"]
                    addr = evt["addr"]
                    status = evt_type == "on"

                    # --- IO Module event (check BEFORE keypad: group range A-D overlaps keypad long-press 8-F) ---
                    # Format: *S,0,X,ADDR  where X=0-3 (short) or A-D (long),
                    # ADDR is the module address (00-FF).  Only fire on *S.
                    io_key = ("__io_module__", addr.upper())
                    if status and io_key in entity_registry:
                        try:
                            group_val = int(group, 16)
                        except ValueError:
                            group_val = -1

                        # Map group value to channel + action
                        if 0 <= group_val <= 3:
                            channel = group_val + 1
                            press_action = "short"
                        elif 10 <= group_val <= 13:
                            channel = group_val - 9
                            press_action = "long"
                        else:
                            channel = 0
                            press_action = "unknown"

                        if channel > 0:
                            # Look up HA device ID
                            hw_device_id = None
                            dev_registry = dr.async_get(hass)
                            io_ident = (DOMAIN, f"{entry.entry_id}_{conn_id}_{addr.upper()}")
                            hw_device = dev_registry.async_get_device({io_ident})
                            if hw_device is not None:
                                hw_device_id = hw_device.id

                            # 1) Fire HA event for device triggers
                            hass.bus.async_fire(
                                EVENT_IO_MODULE_PRESSED,
                                {
                                    "device_id": hw_device_id,
                                    "conn_id": conn_id,
                                    "address": addr.upper(),
                                    "channel": channel,
                                    "action": press_action,
                                },
                            )
                            _LOGGER.info(
                                "IO Module [%s] A=%s fired: channel=%d action=%s",
                                conn_id, addr.upper(), channel, press_action,
                            )

                            # 2) Notify the sensor entity
                            io_entity = entity_registry[io_key]
                            event_id = f"ch_{channel}_{press_action}"
                            io_entity.handle_feedback(event_id)

                        continue  # Don't also try to match as keypad or regular device

                    # --- Keypad button event ---
                    # Format: @1*S,0,X,AA  where AA is the panel_address
                    # Only fire on *S (on) events — keypad only reports button down
                    kp_key = ("__keypad__", addr)
                    if status and kp_key in entity_registry:
                        try:
                            group_val = int(group, 16)
                        except ValueError:
                            group_val = -1

                        # Map group value to button action string
                        if 0 <= group_val <= 7:
                            button_id = f"key_{group_val + 1}_short"
                        elif 8 <= group_val <= 15:
                            button_id = f"key_{group_val - 7}_long"
                        else:
                            button_id = "unknown"

                        # 1) Fire HA event for device triggers & automation
                        #    Look up the HA device registry ID for this keypad device
                        hw_device_id = None
                        dev_registry = dr.async_get(hass)
                        keypad_ident = (DOMAIN, f"{entry.entry_id}_{conn_id}_{addr}")
                        hw_device = dev_registry.async_get_device({keypad_ident})
                        if hw_device is not None:
                            hw_device_id = hw_device.id

                        button_num = group_val + 1 if 0 <= group_val <= 7 else group_val - 7
                        press_action = "short" if 0 <= group_val <= 7 else "long"

                        hass.bus.async_fire(
                            EVENT_KEYPAD_PRESSED,
                            {
                                "device_id": hw_device_id,
                                "conn_id": conn_id,
                                "panel_address": addr,
                                "button": button_num,
                                "action": press_action,
                                "button_id": button_id,
                            },
                        )
                        _LOGGER.debug(
                            "Keypad [%s] PA=%s fired event: button=%d action=%s",
                            conn_id, addr, button_num, press_action,
                        )

                        # 2) Notify the legacy sensor entity
                        keypad_entity = entity_registry[kp_key]
                        keypad_entity.handle_feedback(button_id)

                        continue  # Don't also try to match as regular device

                    # --- Regular device feedback ---
                    key = (group, addr)
                    if key in entity_registry:
                        entity_registry[key].handle_feedback(status)
                        _LOGGER.debug(
                            "Feedback [%s] G=%s A=%s -> %s",
                            conn_id, group, addr, "ON" if status else "OFF",
                        )
                    else:
                        _LOGGER.debug("No entity for [%s] G=%s A=%s", conn_id, group, addr)

                elif evt_type == "adjust":
                    group = evt["group"]
                    addr = evt["addr"]
                    class_ = evt.get("class_", CLASS_BRIGHTNESS)
                    z_value = evt.get("z_value")  # 0-255 raw device value
                    key = (group, addr)

                    if key in entity_registry:
                        entity = entity_registry[key]
                        # Check if this is a DM2 protocol entity with Class=1 (CT feedback)
                        if class_ == CLASS_CT and getattr(entity, 'uses_dm2_protocol', False):
                            # DM2 CCT: Class=1 feedback → color temperature
                            if z_value is not None:
                                kelvin = round(
                                    COLOR_TEMP_MIN_K
                                    + z_value / 255 * (COLOR_TEMP_MAX_K - COLOR_TEMP_MIN_K)
                                )
                            else:
                                kelvin = None
                            entity.handle_feedback(color_temp_kelvin=kelvin)
                            _LOGGER.debug(
                                "DM2 CT Feedback [%s] G=%s A=%s color_temp=%s K",
                                conn_id, group, addr, kelvin,
                            )
                        elif class_ == CLASS_COLOR:  # Class 2 = color wheel
                            if z_value is not None:
                                entity.handle_feedback(color_wheel=z_value)
                                _LOGGER.debug(
                                    "RGBCW Color Wheel [%s] G=%s A=%s wheel=0x%02X",
                                    conn_id, group, addr, z_value,
                                )
                        elif class_ == CLASS_SATURATION:  # Class 3 = saturation
                            if z_value is not None:
                                entity.handle_feedback(saturation=z_value)
                                _LOGGER.debug(
                                    "RGBCW Saturation [%s] G=%s A=%s sat=%d",
                                    conn_id, group, addr, z_value,
                                )
                        else:
                            # Normal brightness feedback (Class=0 or legacy DALI)
                            brightness = z_value if z_value is not None else None
                            entity.handle_feedback(
                                status=(brightness is not None and brightness > 0),
                                brightness=brightness,
                            )
                            _LOGGER.debug(
                                "Feedback [%s] G=%s A=%s brightness=%s",
                                conn_id, group, addr, brightness,
                            )
                    else:
                        # CT channel fallback for legacy DALI CCT (group+1 trick)
                        # e.g. feedback *A,0,1,02; -> try entity at ('0','02')
                        try:
                            prev_group = format(int(group, 16) - 1, 'X')
                        except ValueError:
                            prev_group = None
                        ct_key = (prev_group, addr) if prev_group is not None else None
                        if ct_key and ct_key in entity_registry:
                            entity = entity_registry[ct_key]
                            if z_value is not None:
                                kelvin = round(
                                    COLOR_TEMP_MIN_K
                                    + z_value / 255 * (COLOR_TEMP_MAX_K - COLOR_TEMP_MIN_K)
                                )
                            else:
                                kelvin = None
                            entity.handle_feedback(
                                status=entity.is_on,
                                color_temp_kelvin=kelvin,
                            )
                            _LOGGER.debug(
                                "Feedback [%s] G=%s->%s A=%s color_temp=%s K",
                                conn_id, group, prev_group, addr, kelvin,
                            )

                        else:
                            _LOGGER.debug(
                                "No entity for adjust [%s] G=%s A=%s",
                                conn_id, group, addr,
                            )

                elif evt_type == "rgb":
                    # RGBCW RGB feedback: R, G, B values
                    group = evt.get("group", "")
                    addr = evt.get("addr", "")
                    r = evt.get("r", 0)
                    g = evt.get("g", 0)
                    b = evt.get("b", 0)
                    key = (group, addr)
                    if key in entity_registry:
                        entity = entity_registry[key]
                        entity.handle_feedback(r=r, g=g, b=b)
                        _LOGGER.debug(
                            "RGB Feedback [%s] G=%s A=%s -> R=%d G=%d B=%d",
                            conn_id, group, addr, r, g, b,
                        )
                    else:
                        _LOGGER.debug(
                            "No entity for RGB [%s] G=%s A=%s",
                            conn_id, group, addr,
                        )

            # ── Parse occupancy sensor (SH-808R-S) status frames ──
            # Status frame format (9 bytes):
            #   00 00 00 00 00 XX YY TT SS
            #   XX YY = device address (2-byte hex)
            #   TT = sensor type (0x01 or 0x02)
            #   SS = occupancy status (0x01=有人, 0x00=无人)
            raw_bytes = None
            if isinstance(data, bytes):
                raw_bytes = data
            elif isinstance(data, str):
                try:
                    raw_bytes = data.encode("latin-1")
                except Exception:
                    raw_bytes = None

            if raw_bytes and len(raw_bytes) >= 9:
                for i in range(len(raw_bytes) - 8):
                    if raw_bytes[i:i+5] == b"\x00\x00\x00\x00\x00":
                        xx = raw_bytes[i+5]
                        yy = raw_bytes[i+6]
                        tt = raw_bytes[i+7]
                        ss = raw_bytes[i+8]
                        address = f"{xx:02X}{yy:02X}"
                        key = ("__occupancy__", address)
                        if key in entity_registry:
                            entity = entity_registry[key]
                            entity._sensor.handle_status_frame(tt, ss)
                            _LOGGER.debug(
                                "Sensor [%s] addr=%s TT=%d SS=%d -> %s",
                                conn_id, address, tt, ss,
                                "有人" if ss == 0x01 else "无人",
                            )
                        # Advance past this frame to avoid duplicate detection
                        i += 8

            # ── Route Sicoo (Thermostat) responses ──
            # X1-29-S panel responses start with F1/F2/F3 and are 11 bytes.
            # Must resolve entry_data first (also used by VRV routing below).
            entry_data_route = hass.data.get(DOMAIN, {}).get(entry.entry_id, {})

            from .device.thermostat import ThermostatDevice
            from .protocol.encoder import SicooCommandEncoder

            # Always try to extract Sicoo frames (sliding-window search
            # inside extract_sicoo_frames handles mixed data correctly).
            # is_sicoo_response() only checks data[0] which fails when
            # DALI text and Sicoo binary are in the same TCP read.
            frames = ThermostatDevice.extract_sicoo_frames(data_bytes)
            if frames:
                _LOGGER.debug(
                    "[DIAG] Sicoo frames detected: %d frame(s), %d bytes total",
                    len(frames), len(data_bytes),
                )
                th_data = entry_data_route.get("thermostats", {})
                for frame in frames:
                    parsed = SicooCommandEncoder.parse_response(frame)
                    if parsed is None:
                        _LOGGER.debug("[DIAG] parse_response returned None for frame=%s", frame.hex())
                        continue
                    _LOGGER.debug(
                        "[DIAG] Parsed response: sub=%s dev_id=%d power=%s",
                        parsed.get("sub"), parsed.get("dev_id"), parsed.get("power"),
                    )
                    # Route to the correct thermostat device instance
                    for th in th_data.values():
                        th.update_state(parsed)
                    # Also update climate/fan entities directly
                    _update_thermostat_entities(entry_data_route, parsed)

            # ── Route VRV (CoolMaster) responses ──
            # CoolMaster status lines have the form "UID ON/OFF ..." and
            # are > 30 chars.  They arrive on the same RS485 bus as DALI
            # feedback.  The feedback listener is the sole reader, so it
            # must detect and route these responses to the VRV handler.
            #
            # Because DALI and VRV data can arrive in the same TCP read
            # (mixed frames), we extract pure VRV lines with
            # extract_vrv_lines() before routing and parsing.
            #
            # Two paths for entity updates:
            #   1. Polling wait: _vrv_polling_task is waiting on
            #      _response_event → handle_response wakes it → it
            #      parses & updates entities.
            #   2. Unsolicited: data arrives between poll cycles.
            #      handle_response sets _response_event but nobody
            #      reads it until the next stat2.  To avoid losing
            #      the status, we ALSO parse & update entities here
            #      directly (idempotent — safe to double-update).
            conn_data_route = entry_data_route.get("connections", {}).get(conn_id, {})
            vrv_handler = conn_data_route.get("vrv_handler")
            if vrv_handler and is_vrv_response(data_str):
                vrv_data = extract_vrv_lines(data_str)
                _LOGGER.debug("VRV data routed [%s]: %s", conn_id, vrv_data[:120])
                vrv_handler(vrv_data)

                # Direct entity update for unsolicited VRV responses
                from .device.vrv_controller import parse_status_response
                from .device_trigger import EVENT_VRV_STATE_CHANGED
                vrv_controllers = entry_data_route.get("vrv_controllers", {})
                for vrv_id, vrv_info in vrv_controllers.items():
                    statuses = parse_status_response(vrv_data)
                    entities = vrv_info.get("entities", [])
                    # Track previous state for this VRV controller
                    prev_state = vrv_info.setdefault("_prev_state", {})
                    for entity in entities:
                        unit_id = getattr(entity, "_unit_id", None)
                        if not unit_id:
                            continue
                        new_status = statuses.get(unit_id)
                        entity.update_status(new_status)

                        # ── Fire VRV state-change events ──
                        if new_status:
                            prev = prev_state.get(unit_id, {})
                            new_state = new_status.get("state", "")
                            new_mode = new_status.get("mode", "")
                            prev_s = prev.get("state", "")
                            prev_m = prev.get("mode", "")

                            changes = []
                            if new_state == "ON" and prev_s != "ON":
                                changes.append("unit_on")
                            if new_state != "ON" and prev_s == "ON":
                                changes.append("unit_off")
                            if new_mode and new_mode != prev_m and new_state == "ON":
                                changes.append(f"mode_{new_mode}")

                            prev_state[unit_id] = {"state": new_state, "mode": new_mode}

                            if changes:
                                device_registry = dr.async_get(hass)
                                stable_id = getattr(entity, "_device_id", None) or unit_id
                                device_ident = (DOMAIN, f"{entry.entry_id}_{vrv_id}_{stable_id}")
                                device_entry = device_registry.async_get_device(
                                    identifiers={device_ident})
                                device_id = device_entry.id if device_entry else None
                                for change in changes:
                                    hass.bus.async_fire(
                                        EVENT_VRV_STATE_CHANGED,
                                        {
                                            "device_id": device_id,
                                            "change": change,
                                            "vrv_id": vrv_id,
                                            "unit_id": unit_id,
                                        },
                                    )

        except asyncio.CancelledError:
            _LOGGER.info("Feedback listener cancelled for connection %s", conn_id)
            break
        except Exception as e:
            _LOGGER.error(
                "Feedback listener error [%s]: %s", conn_id, e, exc_info=True
            )
            await asyncio.sleep(2)
