"""X1-29-S Thermostat Panel device layer.

One physical panel can control up to 3 sub-functions:
  - AC (水机空调):  climate entity with cool/heat/dry/fan modes
  - FH (地暖):      climate entity with heat mode only
  - FA (新风):      fan entity with low/med/high/turbo speeds

Each sub-function has its own Sicoo address (1-64) on the same RS485 bus.
Protocol uses 7-byte binary command frames and 11-byte response frames.
"""

import asyncio
import logging

from ..protocol.encoder import SicooCommandEncoder

_LOGGER = logging.getLogger(__name__)


class ThermostatDevice:
    """Device abstraction for one X1-29-S thermostat panel.

    Manages the transport and command encoding for all enabled sub-functions.
    """

    def __init__(self, device_config: dict, transport):
        """Initialize thermostat device.

        Args:
            device_config: Device config dict with ac/fh/fa sub-configs.
            transport:     Async transport for RS485 communication.
        """
        self.name = device_config.get("name", "温控面板")
        self._device_id = device_config.get("id", "")
        self._transport = transport
        self._encoder = SicooCommandEncoder()

        # Parse sub-function configs
        self._sub_funcs = {}
        for sub in ("ac", "floor_heating", "fresh_air"):
            cfg = device_config.get(sub, {})
            if cfg and cfg.get("enabled"):
                addr = int(cfg.get("address", "1"))
                self._sub_funcs[sub] = {
                    "address": addr,
                    "name": cfg.get("name", ""),
                }

        # Current state per sub-function (updated by poll/feedback)
        self._states = {}
        # Entity references: sub -> entity (for state change notification)
        self._entities = {}

    @property
    def sub_funcs(self) -> dict:
        """Return enabled sub-function configs."""
        return self._sub_funcs

    @property
    def is_connected(self) -> bool:
        """Check if transport is connected."""
        return self._transport is not None and getattr(self._transport, "is_connected", False)

    def register_entity(self, sub: str, entity) -> None:
        """Register an entity to be notified on state changes.

        Called by the climate/fan entity's __init__ so that
        update_state() can push new data to the entity immediately.
        """
        self._entities[sub] = entity

    # ------------------------------------------------------------------
    # Command dispatch
    # ------------------------------------------------------------------

    _SUB_TO_FUNC = {
        "ac": "ac",
        "floor_heating": "fh",
        "fresh_air": "fa",
    }

    async def _send(self, sub: str, data: bytes) -> bool:
        """Send a binary frame and return success."""
        if not self.is_connected:
            _LOGGER.warning("Thermostat %s: transport not connected", self.name)
            return False
        try:
            return await self._transport.send_bytes(data)
        except Exception as e:
            _LOGGER.error("Thermostat %s send error: %s", self.name, e)
            return False

    def _dev_id(self, sub: str) -> int:
        return self._sub_funcs[sub]["address"]

    def _func_sub(self, sub: str) -> str:
        return self._SUB_TO_FUNC.get(sub, "ac")

    async def set_power(self, sub: str, power_on: bool) -> bool:
        """Turn a sub-function on or off."""
        code = self._func_sub(sub)
        frame = self._encoder.set_power(code, self._dev_id(sub), power_on)
        return await self._send(sub, frame)

    async def set_mode(self, sub: str, mode_str: str) -> bool:
        """Set AC working mode (cool/heat/fan_only/dry)."""
        code = self._func_sub(sub)
        frame = self._encoder.set_mode(code, self._dev_id(sub), mode_str)
        return await self._send(sub, frame)

    async def set_temperature(self, sub: str, temp_c: float) -> bool:
        """Set target temperature."""
        code = self._func_sub(sub)
        frame = self._encoder.set_temperature(code, self._dev_id(sub), temp_c)
        return await self._send(sub, frame)

    async def set_fan_speed(self, sub: str, speed_str: str) -> bool:
        """Set fan speed (low/medium/high/turbo)."""
        code = self._func_sub(sub)
        frame = self._encoder.set_fan_speed(code, self._dev_id(sub), speed_str)
        return await self._send(sub, frame)

    async def query_status(self, sub: str) -> bytes:
        """Send query status command and wait for response.

        Sends a query frame and waits briefly for the response to arrive.
        The response is parsed by the feedback listener and stored in _states.
        """
        code = self._func_sub(sub)
        frame = self._encoder.query_status(code, self._dev_id(sub))
        return await self._send(sub, frame)

    # ------------------------------------------------------------------
    # State management
    # ------------------------------------------------------------------

    def update_state(self, parsed: dict) -> None:
        """Update internal state from a parsed Sicoo response.

        Called by the feedback listener when it detects a Sicoo response.
        Also notifies the registered climate/fan entity if it exists.
        """
        if parsed is None:
            _LOGGER.warning("Thermostat %s: update_state called with None", self.name)
            return

        sub = parsed.get("sub", "")
        dev_id = parsed.get("dev_id", 0)
        power = parsed.get("power")
        mode = parsed.get("mode")

        if sub == "fa":
            sub = "fresh_air"
        elif sub == "fh":
            sub = "floor_heating"

        # Map dev_id back to our known sub-functions
        matched_sub = None
        for s_name, s_cfg in self._sub_funcs.items():
            if s_cfg["address"] == dev_id:
                matched_sub = s_name
                break

        if matched_sub:
            self._states[matched_sub] = parsed
            _LOGGER.debug(
                "Thermostat %s [%s] state: power=%s mode=%s temp=%.1f/%.1f fan=%s",
                self.name, matched_sub,
                parsed.get("power"), parsed.get("mode"),
                parsed.get("current_temp"), parsed.get("target_temp"),
                parsed.get("fan_speed"),
            )
            # Notify the registered entity so HA UI updates immediately
            entity = self._entities.get(matched_sub)
            if entity:
                entity.update_status(parsed)
            else:
                _LOGGER.debug(
                    "Thermostat %s: no entity registered for sub %s",
                    self.name, matched_sub,
                )

    def get_state(self, sub: str) -> dict:
        """Get the last known state for a sub-function."""
        return self._states.get(sub, {})

    # ------------------------------------------------------------------
    # Response detection (static helper for feedback listener)
    # ------------------------------------------------------------------

    @staticmethod
    def is_sicoo_response(data) -> bool:
        """Check if data looks like a Sicoo response frame.

        Accepts `bytes` or `str` (latin-1 encoded).
        Sicoo responses start with 0xF1/0xF2/0xF3 and are 11 bytes.
        """
        if isinstance(data, str):
            data = data.encode("latin-1")
        if isinstance(data, bytes) and len(data) >= 11:
            return data[0] in (0xF1, 0xF2, 0xF3)
        return False

    @staticmethod
    def extract_sicoo_frames(data) -> list:
        """Extract all 11-byte Sicoo response frames from data.

        Accepts `bytes` or `str` (latin-1).  Returns list of bytes frames.
        """
        if isinstance(data, str):
            data = data.encode("latin-1")
        if not isinstance(data, bytes):
            return []
        frames = []
        for i in range(len(data) - 10):
            if data[i] in (0xF1, 0xF2, 0xF3):
                frame = data[i:i + 11]
                if len(frame) == 11:
                    frames.append(frame)
        return frames
