"""Sensor platform for OWON Meter (PCT321 / PCT341) WiFi MQTT."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
import logging
import re
from typing import Any

from homeassistant.components.sensor import (
    SensorDeviceClass,
    SensorEntity,
    SensorEntityDescription,
    SensorStateClass,
)
from homeassistant.const import (
    PERCENTAGE,
    EntityCategory,
    UnitOfElectricCurrent,
    UnitOfElectricPotential,
    UnitOfEnergy,
    UnitOfFrequency,
    UnitOfPower,
    UnitOfTemperature,
)
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers import entity_registry as er
from homeassistant.helpers.dispatcher import (
    async_dispatcher_connect,
    async_dispatcher_send,
)
from homeassistant.helpers.entity import DeviceInfo
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.event import async_track_time_interval

from . import OwonMeterConfigEntry
from .const import (
    AVAILABILITY_CHECK_INTERVAL,
    DEVICE_MODEL_341,
    DOMAIN,
    MANUFACTURER,
    MODEL,
    PHASE_SEQ_MAP,
    SIGNAL_DEVICE_MODEL_CHANGED,
    SIGNAL_DEVICE_UPDATE,
    SIGNAL_NEW_DEVICE,
)
from .sensor_341 import (
    ALL_341_FIXED_SENSORS,
    Owon341SensorEntityDescription,
    expand_341_payload,
    get_341_subcircuit_sensors,
)

_LOGGER = logging.getLogger(__name__)
_SUBCIRCUIT_KEY_RE = re.compile(
    r"^341_sub(?P<circuit_id>\d+)_(power|current|energy_consumed|energy_generated)$"
)


def _prune_stale_341_subcircuit_registry_entries(
    hass: HomeAssistant,
    config_entry_id: str,
    device_id: str,
    expected_sub_keys: set[str],
) -> None:
    """Remove stale 341 sub-circuit entities left in registry.

    This handles restart scenarios where old entities are not part of
    runtime memory anymore, but still exist in entity registry.
    """
    entity_reg = er.async_get(hass)
    expected_unique_ids = {f"{device_id}_{sub_key}" for sub_key in expected_sub_keys}
    sub_prefix = f"{device_id}_341_sub"
    for reg_entry in er.async_entries_for_config_entry(entity_reg, config_entry_id):
        if not reg_entry.unique_id.startswith(sub_prefix):
            continue
        if reg_entry.unique_id in expected_unique_ids:
            continue
        _LOGGER.info(
            "Removing stale sub-circuit entity %s (unique_id=%s)",
            reg_entry.entity_id,
            reg_entry.unique_id,
        )
        entity_reg.async_remove(reg_entry.entity_id)


@dataclass(frozen=True, kw_only=True)
class OwonSensorEntityDescription(SensorEntityDescription):
    """Describe an OWON meter sensor entity."""

    dp_id: str
    deviceinfo_key: str | None = None
    scale: float = 1.0
    is_enum: bool = False
    is_string: bool = False


# --- Phase A sensors ---
PHASE_A_SENSORS: tuple[OwonSensorEntityDescription, ...] = (
    OwonSensorEntityDescription(
        key="voltage_a",
        dp_id="101",
        translation_key="voltage_a",
        native_unit_of_measurement=UnitOfElectricPotential.VOLT,
        device_class=SensorDeviceClass.VOLTAGE,
        state_class=SensorStateClass.MEASUREMENT,
        scale=0.1,
    ),
    OwonSensorEntityDescription(
        key="current_a",
        dp_id="102",
        translation_key="current_a",
        native_unit_of_measurement=UnitOfElectricCurrent.AMPERE,
        device_class=SensorDeviceClass.CURRENT,
        state_class=SensorStateClass.MEASUREMENT,
        scale=0.001,
    ),
    OwonSensorEntityDescription(
        key="active_power_a",
        dp_id="103",
        translation_key="active_power_a",
        native_unit_of_measurement=UnitOfPower.WATT,
        device_class=SensorDeviceClass.POWER,
        state_class=SensorStateClass.MEASUREMENT,
    ),
    OwonSensorEntityDescription(
        key="power_factor_a",
        dp_id="104",
        translation_key="power_factor_a",
        native_unit_of_measurement=PERCENTAGE,
        device_class=SensorDeviceClass.POWER_FACTOR,
        state_class=SensorStateClass.MEASUREMENT,
    ),
    OwonSensorEntityDescription(
        key="energy_consumed_a",
        dp_id="106",
        translation_key="energy_consumed_a",
        native_unit_of_measurement=UnitOfEnergy.KILO_WATT_HOUR,
        device_class=SensorDeviceClass.ENERGY,
        state_class=SensorStateClass.TOTAL_INCREASING,
        scale=0.001,
    ),
    OwonSensorEntityDescription(
        key="reverse_energy_a",
        dp_id="107",
        translation_key="reverse_energy_a",
        native_unit_of_measurement=UnitOfEnergy.KILO_WATT_HOUR,
        device_class=SensorDeviceClass.ENERGY,
        state_class=SensorStateClass.TOTAL_INCREASING,
        scale=0.001,
    ),
)

# --- Phase B sensors ---
PHASE_B_SENSORS: tuple[OwonSensorEntityDescription, ...] = (
    OwonSensorEntityDescription(
        key="voltage_b",
        dp_id="111",
        translation_key="voltage_b",
        native_unit_of_measurement=UnitOfElectricPotential.VOLT,
        device_class=SensorDeviceClass.VOLTAGE,
        state_class=SensorStateClass.MEASUREMENT,
        scale=0.1,
    ),
    OwonSensorEntityDescription(
        key="current_b",
        dp_id="112",
        translation_key="current_b",
        native_unit_of_measurement=UnitOfElectricCurrent.AMPERE,
        device_class=SensorDeviceClass.CURRENT,
        state_class=SensorStateClass.MEASUREMENT,
        scale=0.001,
    ),
    OwonSensorEntityDescription(
        key="active_power_b",
        dp_id="113",
        translation_key="active_power_b",
        native_unit_of_measurement=UnitOfPower.WATT,
        device_class=SensorDeviceClass.POWER,
        state_class=SensorStateClass.MEASUREMENT,
    ),
    OwonSensorEntityDescription(
        key="power_factor_b",
        dp_id="114",
        translation_key="power_factor_b",
        native_unit_of_measurement=PERCENTAGE,
        device_class=SensorDeviceClass.POWER_FACTOR,
        state_class=SensorStateClass.MEASUREMENT,
    ),
    OwonSensorEntityDescription(
        key="energy_consumed_b",
        dp_id="116",
        translation_key="energy_consumed_b",
        native_unit_of_measurement=UnitOfEnergy.KILO_WATT_HOUR,
        device_class=SensorDeviceClass.ENERGY,
        state_class=SensorStateClass.TOTAL_INCREASING,
        scale=0.001,
    ),
    OwonSensorEntityDescription(
        key="reverse_energy_b",
        dp_id="117",
        translation_key="reverse_energy_b",
        native_unit_of_measurement=UnitOfEnergy.KILO_WATT_HOUR,
        device_class=SensorDeviceClass.ENERGY,
        state_class=SensorStateClass.TOTAL_INCREASING,
        scale=0.001,
    ),
)

# --- Phase C sensors ---
PHASE_C_SENSORS: tuple[OwonSensorEntityDescription, ...] = (
    OwonSensorEntityDescription(
        key="voltage_c",
        dp_id="121",
        translation_key="voltage_c",
        native_unit_of_measurement=UnitOfElectricPotential.VOLT,
        device_class=SensorDeviceClass.VOLTAGE,
        state_class=SensorStateClass.MEASUREMENT,
        scale=0.1,
    ),
    OwonSensorEntityDescription(
        key="current_c",
        dp_id="122",
        translation_key="current_c",
        native_unit_of_measurement=UnitOfElectricCurrent.AMPERE,
        device_class=SensorDeviceClass.CURRENT,
        state_class=SensorStateClass.MEASUREMENT,
        scale=0.001,
    ),
    OwonSensorEntityDescription(
        key="active_power_c",
        dp_id="123",
        translation_key="active_power_c",
        native_unit_of_measurement=UnitOfPower.WATT,
        device_class=SensorDeviceClass.POWER,
        state_class=SensorStateClass.MEASUREMENT,
    ),
    OwonSensorEntityDescription(
        key="power_factor_c",
        dp_id="124",
        translation_key="power_factor_c",
        native_unit_of_measurement=PERCENTAGE,
        device_class=SensorDeviceClass.POWER_FACTOR,
        state_class=SensorStateClass.MEASUREMENT,
    ),
    OwonSensorEntityDescription(
        key="energy_consumed_c",
        dp_id="126",
        translation_key="energy_consumed_c",
        native_unit_of_measurement=UnitOfEnergy.KILO_WATT_HOUR,
        device_class=SensorDeviceClass.ENERGY,
        state_class=SensorStateClass.TOTAL_INCREASING,
        scale=0.001,
    ),
    OwonSensorEntityDescription(
        key="reverse_energy_c",
        dp_id="127",
        translation_key="reverse_energy_c",
        native_unit_of_measurement=UnitOfEnergy.KILO_WATT_HOUR,
        device_class=SensorDeviceClass.ENERGY,
        state_class=SensorStateClass.TOTAL_INCREASING,
        scale=0.001,
    ),
)

# --- Total / summary sensors ---
TOTAL_SENSORS: tuple[OwonSensorEntityDescription, ...] = (
    OwonSensorEntityDescription(
        key="energy_consumed_total",
        dp_id="131",
        translation_key="energy_consumed_total",
        native_unit_of_measurement=UnitOfEnergy.KILO_WATT_HOUR,
        device_class=SensorDeviceClass.ENERGY,
        state_class=SensorStateClass.TOTAL_INCREASING,
        scale=0.001,
    ),
    OwonSensorEntityDescription(
        key="current_total",
        dp_id="132",
        translation_key="current_total",
        native_unit_of_measurement=UnitOfElectricCurrent.AMPERE,
        device_class=SensorDeviceClass.CURRENT,
        state_class=SensorStateClass.MEASUREMENT,
        scale=0.001,
    ),
    OwonSensorEntityDescription(
        key="active_power_total",
        dp_id="133",
        translation_key="active_power_total",
        native_unit_of_measurement=UnitOfPower.WATT,
        device_class=SensorDeviceClass.POWER,
        state_class=SensorStateClass.MEASUREMENT,
    ),
    OwonSensorEntityDescription(
        key="reverse_energy_total",
        dp_id="139",
        translation_key="reverse_energy_total",
        native_unit_of_measurement=UnitOfEnergy.KILO_WATT_HOUR,
        device_class=SensorDeviceClass.ENERGY,
        state_class=SensorStateClass.TOTAL_INCREASING,
        scale=0.001,
    ),
    OwonSensorEntityDescription(
        key="frequency",
        dp_id="135",
        translation_key="frequency",
        native_unit_of_measurement=UnitOfFrequency.HERTZ,
        device_class=SensorDeviceClass.FREQUENCY,
        state_class=SensorStateClass.MEASUREMENT,
    ),
    OwonSensorEntityDescription(
        key="temperature",
        dp_id="136",
        translation_key="temperature",
        native_unit_of_measurement=UnitOfTemperature.CELSIUS,
        device_class=SensorDeviceClass.TEMPERATURE,
        state_class=SensorStateClass.MEASUREMENT,
        scale=0.1,
    ),
)

# --- Diagnostic sensors ---
DIAGNOSTIC_SENSORS: tuple[OwonSensorEntityDescription, ...] = (
    OwonSensorEntityDescription(
        key="device_id",
        dp_id="device_id",
        deviceinfo_key="device_id",
        translation_key="device_id",
        entity_category=EntityCategory.DIAGNOSTIC,
        is_string=True,
    ),
    OwonSensorEntityDescription(
        key="device_model",
        dp_id="device_model",
        deviceinfo_key="model",
        translation_key="device_model",
        entity_category=EntityCategory.DIAGNOSTIC,
        is_string=True,
    ),
    OwonSensorEntityDescription(
        key="device_sub_model",
        dp_id="device_sub_model",
        deviceinfo_key="subModel",
        translation_key="device_sub_model",
        entity_category=EntityCategory.DIAGNOSTIC,
        is_string=True,
    ),
    OwonSensorEntityDescription(
        key="firmware_version",
        dp_id="1",
        deviceinfo_key="fw_version",
        translation_key="firmware_version",
        entity_category=EntityCategory.DIAGNOSTIC,
        is_string=True,
    ),
)

ALL_SENSORS: tuple[OwonSensorEntityDescription, ...] = (
    *PHASE_A_SENSORS,
    *PHASE_B_SENSORS,
    *PHASE_C_SENSORS,
    *TOTAL_SENSORS,
    *DIAGNOSTIC_SENSORS,
)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: OwonMeterConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up OWON meter sensor entities."""
    manager = entry.runtime_data
    _LOGGER.debug(
        "Setting up OWON sensor platform for %s known devices", len(manager.devices)
    )

    # Track which devices already have entities and which model was used
    known_devices: set[str] = set()
    device_entities: dict[str, list[SensorEntity]] = {}
    device_model_used: dict[str, str] = {}
    device_ct_bitmap_used: dict[str, int | None] = {}
    model_listener_registered: set[str] = set()
    ct_listener_registered: set[str] = set()

    def _get_ct_insertion_bitmap(device_id: str) -> int | None:
        """Return DP128 bitmap for a device, or None when unavailable/invalid."""
        raw = manager.devices.get(device_id, {}).get("128")
        if raw is None:
            return None
        try:
            return int(raw)
        except ValueError, TypeError:
            return None

    def _get_inserted_subcircuits(
        device_id: str, max_circuits: int = 16
    ) -> tuple[int, ...]:
        """Return inserted sub-circuit IDs from DP128 bitmap."""
        bitmap = _get_ct_insertion_bitmap(device_id)
        if bitmap is None:
            return ()
        return tuple(
            circuit_id
            for circuit_id in range(1, max_circuits + 1)
            if bitmap & (1 << (circuit_id - 1))
        )

    def _remove_device_entities(device_id: str) -> None:
        """Remove entities from registry and entity platform for a device."""
        old_entities = device_entities.pop(device_id, [])
        entity_reg = er.async_get(hass)
        for entity in old_entities:
            if entity.entity_id:
                entity_reg.async_remove(entity.entity_id)
            hass.async_create_task(entity.async_remove())

    @callback
    def _add_device_entities(device_id: str) -> None:
        """Create sensor entities for a newly discovered device."""
        if device_id in known_devices:
            _LOGGER.debug(
                "Device %s already initialized, skipping entity creation", device_id
            )
            return
        known_devices.add(device_id)
        device_model = manager.get_device_model(device_id)
        if device_model == DEVICE_MODEL_341:
            inserted_subcircuits = _get_inserted_subcircuits(device_id)
            subcircuit_sensors = get_341_subcircuit_sensors(
                circuit_ids=inserted_subcircuits
            )
            _prune_stale_341_subcircuit_registry_entries(
                hass,
                entry.entry_id,
                device_id,
                {desc.key for desc in subcircuit_sensors},
            )
            entities: list[SensorEntity] = [
                Owon341Sensor(device_id, desc, manager)
                for desc in (*ALL_341_FIXED_SENSORS, *subcircuit_sensors)
            ]
            bitmap = _get_ct_insertion_bitmap(device_id)
            device_ct_bitmap_used[device_id] = bitmap
            _LOGGER.info(
                "Creating %s sensor entities for PCT341 device %s (ct_bitmap=%s, inserted=%s)",
                len(entities),
                device_id,
                bitmap,
                list(inserted_subcircuits),
            )
        else:
            _prune_stale_341_subcircuit_registry_entries(
                hass, entry.entry_id, device_id, set()
            )
            entities = [
                Owon321Sensor(device_id, description, manager)
                for description in ALL_SENSORS
            ]
            device_ct_bitmap_used.pop(device_id, None)
            _LOGGER.info(
                "Creating %s sensor entities for PCT321 device %s",
                len(entities),
                device_id,
            )
        device_entities[device_id] = entities
        device_model_used[device_id] = device_model
        async_add_entities(entities)

        @callback
        def _handle_model_changed() -> None:
            """Recreate entities when deviceinfo confirms a different model."""
            new_model = manager.get_device_model(device_id)
            if device_model_used.get(device_id) == new_model:
                return
            _LOGGER.info(
                "Device %s model changed to %s, recreating entities",
                device_id,
                new_model,
            )
            _remove_device_entities(device_id)
            known_devices.discard(device_id)
            _add_device_entities(device_id)

        @callback
        def _handle_ct_insertion_changed() -> None:
            """Recreate 341 sub-circuit entities when DP128 bitmap changes."""
            if manager.get_device_model(device_id) != DEVICE_MODEL_341:
                return
            new_bitmap = _get_ct_insertion_bitmap(device_id)
            if device_ct_bitmap_used.get(device_id) == new_bitmap:
                return
            _LOGGER.info(
                "Device %s CT insertion bitmap changed from %s to %s, recreating entities",
                device_id,
                device_ct_bitmap_used.get(device_id),
                new_bitmap,
            )
            _remove_device_entities(device_id)
            known_devices.discard(device_id)
            _add_device_entities(device_id)

        if device_id not in model_listener_registered:
            entry.async_on_unload(
                async_dispatcher_connect(
                    hass,
                    f"{SIGNAL_DEVICE_MODEL_CHANGED}_{device_id}",
                    _handle_model_changed,
                )
            )
            model_listener_registered.add(device_id)

        if device_id not in ct_listener_registered:
            entry.async_on_unload(
                async_dispatcher_connect(
                    hass,
                    f"{SIGNAL_DEVICE_UPDATE}_{device_id}",
                    _handle_ct_insertion_changed,
                )
            )
            ct_listener_registered.add(device_id)

    # Add entities for already discovered devices
    for device_id in manager.devices:
        _add_device_entities(device_id)

    # Listen for newly discovered devices
    entry.async_on_unload(
        async_dispatcher_connect(hass, SIGNAL_NEW_DEVICE, _add_device_entities)
    )

    @callback
    def _refresh_availability(_: datetime) -> None:
        """Refresh entities so availability can expire without new MQTT messages."""
        _LOGGER.debug(
            "Running OWON availability refresh for %s devices", len(manager.devices)
        )
        for device_id in manager.devices:
            async_dispatcher_send(hass, f"{SIGNAL_DEVICE_UPDATE}_{device_id}")

    entry.async_on_unload(
        async_track_time_interval(
            hass, _refresh_availability, AVAILABILITY_CHECK_INTERVAL
        )
    )


class Owon321Sensor(SensorEntity):
    """Representation of an OWON meter sensor."""

    entity_description: OwonSensorEntityDescription
    _attr_has_entity_name = True

    def __init__(
        self,
        device_id: str,
        description: OwonSensorEntityDescription,
        manager: Any,
    ) -> None:
        """Initialize the sensor."""
        self.entity_description = description
        self._device_id = device_id
        self._manager = manager
        self._attr_unique_id = f"{device_id}_{description.key}"

    @property
    def device_info(self) -> DeviceInfo:
        """Return device info including firmware version when available."""
        fw_version = self._manager.device_info.get(self._device_id, {}).get(
            "fw_version"
        )
        return DeviceInfo(
            identifiers={(DOMAIN, self._device_id)},
            name=f"{MANUFACTURER} {MODEL} {self._device_id}",
            manufacturer=MANUFACTURER,
            model=MODEL,
            sw_version=fw_version,
        )

    async def async_added_to_hass(self) -> None:
        """Subscribe to device updates when added to hass."""

        @callback
        def _update_callback() -> None:
            self.async_write_ha_state()

        self.async_on_remove(
            async_dispatcher_connect(
                self.hass,
                f"{SIGNAL_DEVICE_UPDATE}_{self._device_id}",
                _update_callback,
            )
        )

    @property
    def available(self) -> bool:
        """Return whether the source device is considered online."""
        return self._manager.is_device_available(self._device_id)

    @property
    def native_value(self) -> Any | None:
        """Return the sensor value."""
        if self.entity_description.deviceinfo_key is not None:
            info_raw = self._manager.device_info.get(self._device_id, {}).get(
                self.entity_description.deviceinfo_key
            )
            if info_raw is None:
                return None
            return str(info_raw)

        data = self._manager.devices.get(self._device_id, {})
        raw = data.get(self.entity_description.dp_id)
        if raw is None:
            return None

        # String sensors (firmware/hardware versions)
        if self.entity_description.is_string:
            return str(raw)

        # Enum sensors (voltage phase sequence)
        if self.entity_description.is_enum:
            try:
                return PHASE_SEQ_MAP.get(int(raw), str(raw))
            except ValueError, TypeError:
                return None

        # Numeric sensors with scale factor
        try:
            numeric = float(raw)
        except ValueError, TypeError:
            return None
        if self.entity_description.scale != 1.0:
            return round(numeric * self.entity_description.scale, 3)

        return numeric


class Owon341Sensor(SensorEntity):
    """Representation of a PCT341 meter sensor."""

    entity_description: Owon341SensorEntityDescription
    _attr_has_entity_name = True

    def __init__(
        self,
        device_id: str,
        description: Owon341SensorEntityDescription,
        manager: Any,
    ) -> None:
        """Initialize the sensor."""
        self.entity_description = description
        self._device_id = device_id
        self._manager = manager
        self._attr_unique_id = f"{device_id}_{description.key}"

        match = _SUBCIRCUIT_KEY_RE.match(description.key)
        if match:
            self._attr_translation_placeholders = {
                "circuit_id": match.group("circuit_id")
            }

    @property
    def device_info(self) -> DeviceInfo:
        """Return device info including firmware version when available."""
        fw_version = self._manager.device_info.get(self._device_id, {}).get(
            "fw_version"
        )
        return DeviceInfo(
            identifiers={(DOMAIN, self._device_id)},
            name=f"{MANUFACTURER} PCT341 {self._device_id}",
            manufacturer=MANUFACTURER,
            model="PCT341",
            sw_version=fw_version,
        )

    async def async_added_to_hass(self) -> None:
        """Subscribe to device updates when added to hass."""

        @callback
        def _update_callback() -> None:
            self.async_write_ha_state()

        self.async_on_remove(
            async_dispatcher_connect(
                self.hass,
                f"{SIGNAL_DEVICE_UPDATE}_{self._device_id}",
                _update_callback,
            )
        )

    @property
    def available(self) -> bool:
        """Return whether the source device is considered online."""
        return self._manager.is_device_available(self._device_id)

    @property
    def native_value(self) -> Any | None:
        """Return the sensor value from expanded 341 data or deviceinfo."""
        # If deviceinfo_key is set, read from deviceinfo payload first
        if self.entity_description.deviceinfo_key is not None:
            raw = self._manager.device_info.get(self._device_id, {}).get(
                self.entity_description.deviceinfo_key
            )
            if raw is not None:
                return str(raw)
        data = self._manager.devices.get(self._device_id, {})
        # Expand raw hex DPs into named flat keys on every read (lightweight)
        expanded = expand_341_payload(data)
        raw = expanded.get(self.entity_description.data_key)
        if raw is None:
            return None
        if self.entity_description.is_string:
            return str(raw)
        return raw
