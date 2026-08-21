"""Climate platform entity for Dercvne Bus.

Supports:
- VRV Controller (CoolMaster) indoor units
- X1-29-S Thermostat Panel — AC (水机空调) and FH (地暖) sub-functions
"""

import asyncio
import logging

from homeassistant.components.climate import (
    ClimateEntity,
    ClimateEntityFeature,
    HVACMode,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import UnitOfTemperature
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from ..const import (
    DOMAIN,
    DEVICE_TYPE_VRV_CONTROLLER,
    DEVICE_TYPE_VRV_INDOOR,
    DEVICE_TYPE_THERMOSTAT,
)
from ..device.vrv_controller import VRVController
from ..config_flow import _migrate_data

_LOGGER = logging.getLogger(__name__)

# Supported HVAC modes for VRV indoor units
VRV_HVAC_MODES = [
    HVACMode.OFF,
    HVACMode.COOL,
    HVACMode.HEAT,
    HVACMode.DRY,
    HVACMode.FAN_ONLY,
]

# Supported fan modes
VRV_FAN_MODES = ["low", "medium", "high", "auto"]

# Thermostat AC modes
TH_AC_HVAC_MODES = [
    HVACMode.OFF,
    HVACMode.COOL,
    HVACMode.HEAT,
    HVACMode.DRY,
    HVACMode.FAN_ONLY,
]
TH_AC_FAN_MODES = ["low", "medium", "high"]

# Thermostat FH modes (floor heating — heat only)
TH_FH_HVAC_MODES = [
    HVACMode.OFF,
    HVACMode.HEAT,
]


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up VRV and Thermostat climate entities."""
    _, devices = _migrate_data(dict(entry.data))
    entry_data = hass.data[DOMAIN].get(entry.entry_id, {})
    vrv_controllers = entry_data.get("vrv_controllers", {})

    entities = []

    for device_config in devices:
        device_type = device_config.get("device_type", "")

        # ── VRV indoor units ──
        if device_type in (DEVICE_TYPE_VRV_INDOOR, "vrv_indoor"):
            parent_id = device_config.get("parent_id", "")
            vrv_data = vrv_controllers.get(parent_id)
            if vrv_data is None:
                _LOGGER.warning(
                    "VRV indoor unit '%s' references unknown parent '%s', skipping",
                    device_config.get("name"), parent_id,
                )
                continue

            controller = vrv_data.get("controller")
            if controller is None:
                _LOGGER.warning("VRV controller '%s' not connected, skipping", parent_id)
                continue

            entity = VRVIndoorUnit(
                controller=controller,
                vrv_id=parent_id,
                unit_config=device_config,
                entry_id=entry.entry_id,
                conn_id=parent_id,
            )
            entities.append(entity)
            vrv_data.setdefault("entities", []).append(entity)
            continue

        # ── Thermostat panel AC / FH ──
        if device_type == DEVICE_TYPE_THERMOSTAT:
            ac_cfg = device_config.get("ac", {})
            fh_cfg = device_config.get("floor_heating", {})

            conn_id = device_config.get("connection_id", "")
            connections_data = hass.data[DOMAIN][entry.entry_id]["connections"]
            conn = connections_data.get(conn_id)
            if conn is None:
                _LOGGER.warning(
                    "Thermostat %s: conn %s not found",
                    device_config.get("name"), conn_id,
                )
                continue

            transport = conn.get("transport")
            if transport is None:
                continue

            # Look up thermostat device wrapper
            th_data = hass.data[DOMAIN][entry.entry_id].setdefault("thermostats", {})
            device_id = device_config.get("id", "")
            if device_id not in th_data:
                from .device.thermostat import ThermostatDevice
                th_data[device_id] = ThermostatDevice(device_config, transport)

            thermostat = th_data[device_id]

            if ac_cfg.get("enabled"):
                entity = ThermostatACEntity(
                    thermostat, entry.entry_id, device_id, device_config, conn_id,
                )
                entities.append(entity)

            if fh_cfg.get("enabled"):
                entity = ThermostatFHEntity(
                    thermostat, entry.entry_id, device_id, device_config, conn_id,
                )
                entities.append(entity)

    if entities:
        async_add_entities(entities)
        _LOGGER.info("Added %d climate entities", len(entities))
    else:
        _LOGGER.debug("No climate entities to add")


# ---------------------------------------------------------------------------
# VRV Controller — Indoor Unit Climate Entity
# ---------------------------------------------------------------------------

class VRVIndoorUnit(ClimateEntity):
    """Representation of a VRV indoor unit as a climate entity."""

    _attr_should_poll = False
    _attr_has_entity_name = True
    _attr_temperature_unit = UnitOfTemperature.CELSIUS
    _attr_hvac_modes = VRV_HVAC_MODES
    _attr_fan_modes = VRV_FAN_MODES
    _attr_supported_features = (
        ClimateEntityFeature.TARGET_TEMPERATURE
        | ClimateEntityFeature.FAN_MODE
        | ClimateEntityFeature.TURN_OFF
        | ClimateEntityFeature.TURN_ON
    )
    _attr_target_temperature_step = 1
    _attr_min_temp = 16
    _attr_max_temp = 30
    _attr_target_temperature = 24.0
    _attr_current_temperature = 24.0

    def __init__(
        self,
        controller: VRVController,
        vrv_id: str,
        unit_config: dict,
        entry_id: str,
        conn_id: str,
    ):
        """Initialize the VRV indoor unit climate entity."""
        self._controller = controller
        self._vrv_id = vrv_id
        self._device_id = unit_config.get("id", "")
        self._unit_id = unit_config.get("unit_id", "")
        self._unit_name = unit_config.get("name", f"室内机 {self._unit_id}")
        self._entry_id = entry_id
        self._conn_id = conn_id

        self._attr_name = self._unit_name
        if self._device_id:
            self._attr_unique_id = f"{entry_id}_{vrv_id}_{self._device_id}"
        else:
            self._attr_unique_id = f"{entry_id}_{vrv_id}_{self._unit_id}"
        self._attr_hvac_mode = HVACMode.OFF
        self._attr_fan_mode = "auto"

    @property
    def device_info(self):
        """Return device info — each indoor unit gets its own device entry."""
        stable_id = self._device_id or self._unit_id
        return {
            "identifiers": {
                (DOMAIN, f"{self._entry_id}_{self._vrv_id}_{stable_id}"),
            },
            "name": self._unit_name,
            "manufacturer": "Dercvne",
            "model": "CoolMaster VRV Controller",
            "sw_version": "1.1.0",
        }

    # ------------------------------------------------------------------ update from poller

    def update_status(self, status):
        """Update entity state from VRV status data.

        Called by the VRV coordinator/poller after each stat2 query,
        and directly by the feedback listener for unsolicited responses.
        If status is None, the indoor unit was not found in the response
        (e.g. powered off at the breaker).

        Args:
            status: Status dict from parse_status_response() or None.
        """
        if status is None:
            return

        state = status.get("state", "OFF")
        if state == "ON":
            mode = status.get("mode", "cool")
            self._attr_hvac_mode = HVACMode(mode) if mode in VRV_HVAC_MODES else HVACMode.COOL
            self._attr_fan_mode = status.get("fan_speed", "auto")
            set_temp = status.get("set_temp")
            if set_temp is not None:
                self._attr_target_temperature = float(set_temp)
        else:
            self._attr_hvac_mode = HVACMode.OFF

        room_temp = status.get("room_temp")
        if room_temp is not None:
            self._attr_current_temperature = float(room_temp)
        self.async_write_ha_state()

    # ------------------------------------------------------------------ HVAC control

    async def async_set_hvac_mode(self, hvac_mode: HVACMode):
        """Set HVAC mode."""
        if hvac_mode == HVACMode.OFF:
            await self._controller.turn_off(self._unit_id)
            self._attr_hvac_mode = HVACMode.OFF
            self.async_write_ha_state()
            return

        await self._controller.turn_on(self._unit_id)
        await asyncio.sleep(0.15)

        if hvac_mode == HVACMode.COOL:
            await self._controller.set_mode_cool(self._unit_id)
        elif hvac_mode == HVACMode.HEAT:
            await self._controller.set_mode_heat(self._unit_id)
        elif hvac_mode == HVACMode.DRY:
            await self._controller.set_mode_dry(self._unit_id)
        elif hvac_mode == HVACMode.FAN_ONLY:
            await self._controller.set_mode_fan(self._unit_id)

        self._attr_hvac_mode = hvac_mode
        self.async_write_ha_state()

    async def async_set_fan_mode(self, fan_mode: str):
        """Set fan speed."""
        speed_map = {"low": "l", "medium": "m", "high": "h", "auto": "a"}
        speed_char = speed_map.get(fan_mode, "a")
        await self._controller.set_fan_speed(self._unit_id, speed_char)
        self._attr_fan_mode = fan_mode
        self.async_write_ha_state()

    async def async_set_temperature(self, **kwargs):
        """Set target temperature."""
        temp = kwargs.get("temperature")
        if temp is not None:
            await self._controller.set_temperature(self._unit_id, int(temp))
            self._attr_target_temperature = float(temp)
            self.async_write_ha_state()


# ---------------------------------------------------------------------------
# X1-29-S Thermostat Panel — AC (水机空调) Climate Entity
# ---------------------------------------------------------------------------

class ThermostatACEntity(ClimateEntity):
    """Representation of thermostat panel AC sub-function as a climate entity.

    Supports: Off, Cool, Heat, Dry, Fan Only
    """

    _attr_should_poll = False
    _attr_has_entity_name = True
    _attr_temperature_unit = UnitOfTemperature.CELSIUS
    _attr_hvac_modes = TH_AC_HVAC_MODES
    _attr_fan_modes = TH_AC_FAN_MODES
    _attr_supported_features = (
        ClimateEntityFeature.TARGET_TEMPERATURE
        | ClimateEntityFeature.FAN_MODE
        | ClimateEntityFeature.TURN_OFF
        | ClimateEntityFeature.TURN_ON
    )
    _attr_target_temperature_step = 1
    _attr_min_temp = 17
    _attr_max_temp = 30

    def __init__(self, thermostat, entry_id, device_id, device_config, conn_id):
        """Initialize thermostat AC climate entity."""
        self._thermostat = thermostat
        self._entry_id = entry_id
        self._device_uuid = device_id
        self._conn_id = conn_id
        self._panel_name = device_config.get("name", "温控面板")

        self._attr_name = f"{self._panel_name} 空调"
        self._attr_unique_id = f"{entry_id}_{device_id}_ac"
        self._attr_hvac_mode = HVACMode.OFF
        self._attr_fan_mode = "low"
        self._attr_current_temperature = None
        self._attr_target_temperature = 26
        self._thermostat.register_entity("ac", self)

    @property
    def device_info(self):
        return {
            "identifiers": {
                (DOMAIN, f"{self._entry_id}_{self._device_uuid}"),
            },
            "name": self._panel_name,
            "manufacturer": "Dercvne",
            "model": "X1-29-S Thermostat Panel",
        }

    # ------------------------------------------------------------------ update

    def update_status(self, parsed: dict) -> None:
        """Update state from parsed Sicoo response."""
        if not parsed or parsed.get("sub") != "ac":
            return

        power = parsed.get("power", False)
        if power:
            mode_str = parsed.get("mode", "cool")
            try:
                self._attr_hvac_mode = HVACMode(mode_str)
            except ValueError:
                self._attr_hvac_mode = HVACMode.COOL
            self._attr_fan_mode = parsed.get("fan_speed", "low")
            self._attr_target_temperature = parsed.get("target_temp")
        else:
            self._attr_hvac_mode = HVACMode.OFF

        self._attr_current_temperature = parsed.get("current_temp")
        self.async_write_ha_state()

    # ------------------------------------------------------------------ control

    async def async_set_hvac_mode(self, hvac_mode: HVACMode) -> None:
        """Set HVAC mode."""
        if hvac_mode == HVACMode.OFF:
            await self._thermostat.set_power("ac", False)
            self._attr_hvac_mode = HVACMode.OFF
            self.async_write_ha_state()
            return

        await self._thermostat.set_power("ac", True)
        await asyncio.sleep(0.1)

        mode_map = {
            HVACMode.COOL: "cool",
            HVACMode.HEAT: "heat",
            HVACMode.DRY: "dry",
            HVACMode.FAN_ONLY: "fan_only",
        }
        mode_str = mode_map.get(hvac_mode, "cool")
        await self._thermostat.set_mode("ac", mode_str)
        self._attr_hvac_mode = hvac_mode
        self.async_write_ha_state()

    async def async_set_fan_mode(self, fan_mode: str) -> None:
        """Set fan speed."""
        await self._thermostat.set_fan_speed("ac", fan_mode)
        self._attr_fan_mode = fan_mode
        self.async_write_ha_state()

    async def async_set_temperature(self, **kwargs) -> None:
        """Set target temperature."""
        temp = kwargs.get("temperature")
        if temp is not None:
            await self._thermostat.set_temperature("ac", float(temp))
            self._attr_target_temperature = float(temp)
            self.async_write_ha_state()


# ---------------------------------------------------------------------------
# X1-29-S Thermostat Panel — FH (地暖) Climate Entity
# ---------------------------------------------------------------------------

class ThermostatFHEntity(ClimateEntity):
    """Representation of thermostat panel floor heating sub-function.

    Supports: Off, Heat
    """

    _attr_should_poll = False
    _attr_has_entity_name = True
    _attr_temperature_unit = UnitOfTemperature.CELSIUS
    _attr_hvac_modes = TH_FH_HVAC_MODES
    _attr_supported_features = (
        ClimateEntityFeature.TARGET_TEMPERATURE
        | ClimateEntityFeature.TURN_OFF
        | ClimateEntityFeature.TURN_ON
    )
    _attr_target_temperature_step = 1
    _attr_min_temp = 17
    _attr_max_temp = 30

    def __init__(self, thermostat, entry_id, device_id, device_config, conn_id):
        """Initialize thermostat FH climate entity."""
        self._thermostat = thermostat
        self._entry_id = entry_id
        self._device_uuid = device_id
        self._conn_id = conn_id
        self._panel_name = device_config.get("name", "温控面板")

        self._attr_name = f"{self._panel_name} 地暖"
        self._attr_unique_id = f"{entry_id}_{device_id}_fh"
        self._attr_hvac_mode = HVACMode.OFF
        self._attr_current_temperature = None
        self._attr_target_temperature = 22
        self._thermostat.register_entity("floor_heating", self)

    @property
    def device_info(self):
        return {
            "identifiers": {
                (DOMAIN, f"{self._entry_id}_{self._device_uuid}"),
            },
            "name": self._panel_name,
            "manufacturer": "Dercvne",
            "model": "X1-29-S Thermostat Panel",
        }

    # ------------------------------------------------------------------ update

    def update_status(self, parsed: dict) -> None:
        """Update state from parsed Sicoo response."""
        if not parsed or parsed.get("sub") != "fh":
            return

        power = parsed.get("power", False)
        if power:
            self._attr_hvac_mode = HVACMode.HEAT
            self._attr_target_temperature = parsed.get("target_temp")
        else:
            self._attr_hvac_mode = HVACMode.OFF

        self._attr_current_temperature = parsed.get("current_temp")
        self.async_write_ha_state()

    # ------------------------------------------------------------------ control

    async def async_set_hvac_mode(self, hvac_mode: HVACMode) -> None:
        """Set HVAC mode (Off or Heat only)."""
        if hvac_mode == HVACMode.OFF:
            await self._thermostat.set_power("floor_heating", False)
            self._attr_hvac_mode = HVACMode.OFF
            self.async_write_ha_state()
            return

        if hvac_mode == HVACMode.HEAT:
            await self._thermostat.set_power("floor_heating", True)
            self._attr_hvac_mode = HVACMode.HEAT
            self.async_write_ha_state()

    async def async_set_temperature(self, **kwargs) -> None:
        """Set target temperature."""
        temp = kwargs.get("temperature")
        if temp is not None:
            await self._thermostat.set_temperature("floor_heating", float(temp))
            self._attr_target_temperature = float(temp)
            self.async_write_ha_state()
