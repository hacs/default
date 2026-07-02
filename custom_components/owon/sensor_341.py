"""PCT341 sensor definitions and hex-payload parsers."""

from __future__ import annotations

from collections.abc import Iterable
import contextlib
from dataclasses import dataclass
import logging
import struct
from typing import Any

from homeassistant.components.sensor import (
    SensorDeviceClass,
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
)

_LOGGER = logging.getLogger(__name__)

# --------------------------------------------------------------------------- #
# Measurement-type enum (DP 120)
# --------------------------------------------------------------------------- #
MEASUREMENT_TYPE_MAP: dict[int, str] = {
    0: "identifying",
    1: "three_phase",
    2: "single_phase",
    3: "two_phase_three_wire",
    4: "other",
}

# Sub-circuit phase map (DP 127 values)
SUBCIRCUIT_PHASE_MAP: dict[int, str] = {
    0: "unknown",
    1: "phase_a",
    2: "phase_b",
    3: "phase_c",
    4: "phase_a_auto",
    5: "phase_b_auto",
    6: "phase_c_auto",
}


# --------------------------------------------------------------------------- #
# Hex parsing helpers
# --------------------------------------------------------------------------- #


def _hex_bytes(raw: Any) -> bytes | None:
    """Convert a hex-string DP value to bytes; return None on failure."""
    try:
        return bytes.fromhex(str(raw))
    except ValueError:
        _LOGGER.debug("Cannot decode hex value: %s", raw)
        return None


def _u32le(data: bytes, offset: int) -> int:
    """Read unsigned 32-bit little-endian integer."""
    return struct.unpack_from("<I", data, offset)[0]


def _i32le(data: bytes, offset: int) -> int:
    """Read signed 32-bit little-endian integer."""
    return struct.unpack_from("<i", data, offset)[0]


def parse_phase_data(raw: Any) -> dict[str, float | None]:
    """Parse a 13-byte phase hex DP (DP 121/122/123).

    Returns: voltage_v, current_a, power_kw, power_factor_pct
    """
    result: dict[str, float | None] = {
        "voltage_v": None,
        "current_a": None,
        "power_kw": None,
        "power_factor_pct": None,
    }
    data = _hex_bytes(raw)
    if data is None or len(data) < 13:
        return result
    result["voltage_v"] = round(_u32le(data, 0) * 0.1, 2)
    result["current_a"] = round(_u32le(data, 4) * 0.001, 4)
    result["power_kw"] = round(_u32le(data, 8) * 0.001, 4)
    result["power_factor_pct"] = round(data[12] * 0.01, 4)
    return result


def parse_combined_data(raw: Any) -> dict[str, float | None]:
    """Parse the 17-byte combined hex DP (DP 124).

    Returns: total_current_a, total_power_kw, frequency_hz,
             total_energy_consumed_kwh, total_energy_generated_kwh
    """
    result: dict[str, float | None] = {
        "total_current_a": None,
        "total_power_kw": None,
        "frequency_hz": None,
        "total_energy_consumed_kwh": None,
        "total_energy_generated_kwh": None,
    }
    data = _hex_bytes(raw)
    if data is None or len(data) < 17:
        return result
    result["total_current_a"] = round(_u32le(data, 0) * 0.001, 4)
    result["total_power_kw"] = round(_u32le(data, 4) * 0.001, 4)
    result["frequency_hz"] = float(data[8])
    result["total_energy_consumed_kwh"] = round(_u32le(data, 9) * 0.01, 4)
    result["total_energy_generated_kwh"] = round(_u32le(data, 13) * 0.01, 4)
    return result


def parse_subcircuit_power_current(raw: Any) -> dict[int, dict[str, float]]:
    """Parse DP 125 – sub-circuit current & power.

    Each circuit record: 1B circuit_id + 4B power (0.001kW) + 4B current (0.001A)
    Returns: {circuit_id: {"power_kw": ..., "current_a": ...}}
    """
    result: dict[int, dict[str, float]] = {}
    data = _hex_bytes(raw)
    if data is None or len(data) < 1:
        return result
    count = data[0]
    offset = 1
    for _ in range(count):
        if offset + 9 > len(data):
            break
        cid = data[offset]
        power = round(_u32le(data, offset + 1) * 0.001, 4)
        current = round(_u32le(data, offset + 5) * 0.001, 4)
        result[cid] = {"power_kw": power, "current_a": current}
        offset += 9
    return result


def parse_subcircuit_energy(raw: Any) -> dict[int, dict[str, float]]:
    """Parse DP 126 – sub-circuit consumed & generated energy.

    Each record: 1B circuit_id + 4B consumed (0.01kWh) + 4B generated (0.01kWh)
    Returns: {circuit_id: {"energy_consumed_kwh": ..., "energy_generated_kwh": ...}}
    """
    result: dict[int, dict[str, float]] = {}
    data = _hex_bytes(raw)
    if data is None or len(data) < 1:
        return result
    count = data[0]
    offset = 1
    for _ in range(count):
        if offset + 9 > len(data):
            break
        cid = data[offset]
        consumed = round(_u32le(data, offset + 1) * 0.01, 4)
        generated = round(_u32le(data, offset + 5) * 0.01, 4)
        result[cid] = {
            "energy_consumed_kwh": consumed,
            "energy_generated_kwh": generated,
        }
        offset += 9
    return result


def parse_subcircuit_phase(raw: Any) -> dict[int, int]:
    """Parse DP 127 – sub-circuit phase assignment.

    Returns: {circuit_id: phase_enum}
    """
    result: dict[int, int] = {}
    data = _hex_bytes(raw)
    if data is None or len(data) < 1:
        return result
    count = data[0]
    offset = 1
    for _ in range(count):
        if offset + 2 > len(data):
            break
        cid = data[offset]
        phase = data[offset + 1]
        result[cid] = phase
        offset += 2
    return result


# --------------------------------------------------------------------------- #
# Helper: flatten parsed 341 data into the same device data dict used by
# OwonMeterDataManager so that generic sensor lookup (by "dp_id") still works.
# We store synthetic keys like "341_voltage_a", "341_total_energy_consumed", etc.
# --------------------------------------------------------------------------- #


def expand_341_payload(dp_data: dict[str, Any]) -> dict[str, Any]:
    """Expand raw 341 DP hex values into flat named keys.

    The result is merged back into manager.devices[device_id] so the normal
    sensor native_value lookup path can use plain string keys.
    """
    expanded: dict[str, Any] = {}

    # --- DP 120: device measurement type ---
    if "120" in dp_data:
        val = dp_data["120"]
        with contextlib.suppress(ValueError, TypeError):
            expanded["341_measurement_type"] = MEASUREMENT_TYPE_MAP.get(
                int(val), str(val)
            )

    # --- DP 121/122/123: A/B/C phase data ---
    for dp, prefix in (("121", "a"), ("122", "b"), ("123", "c")):
        if dp in dp_data:
            parsed = parse_phase_data(dp_data[dp])
            expanded[f"341_voltage_{prefix}"] = parsed["voltage_v"]
            expanded[f"341_current_{prefix}"] = parsed["current_a"]
            expanded[f"341_power_{prefix}"] = parsed["power_kw"]
            expanded[f"341_power_factor_{prefix}"] = parsed["power_factor_pct"]

    # --- DP 124: combined / total data ---
    if "124" in dp_data:
        parsed = parse_combined_data(dp_data["124"])
        expanded["341_current_total"] = parsed["total_current_a"]
        expanded["341_power_total"] = parsed["total_power_kw"]
        expanded["341_frequency"] = parsed["frequency_hz"]
        expanded["341_energy_consumed_total"] = parsed["total_energy_consumed_kwh"]
        expanded["341_energy_generated_total"] = parsed["total_energy_generated_kwh"]

    # --- DP 125: sub-circuit current & power (default 0 when DP absent) ---
    if "125" in dp_data:
        sub_power_current = parse_subcircuit_power_current(dp_data["125"])
    else:
        sub_power_current = {}
    for cid in range(1, 17):
        vals = sub_power_current.get(cid, {"power_kw": 0.0, "current_a": 0.0})
        expanded[f"341_sub{cid}_power"] = vals["power_kw"]
        expanded[f"341_sub{cid}_current"] = vals["current_a"]

    # --- DP 126: sub-circuit energy (default 0 when DP absent) ---
    if "126" in dp_data:
        sub_energy = parse_subcircuit_energy(dp_data["126"])
    else:
        sub_energy = {}
    for cid in range(1, 17):
        vals = sub_energy.get(
            cid, {"energy_consumed_kwh": 0.0, "energy_generated_kwh": 0.0}
        )
        expanded[f"341_sub{cid}_energy_consumed"] = vals["energy_consumed_kwh"]
        expanded[f"341_sub{cid}_energy_generated"] = vals["energy_generated_kwh"]

    # --- DP 127: sub-circuit phase ---
    if "127" in dp_data:
        for cid, phase in parse_subcircuit_phase(dp_data["127"]).items():
            expanded[f"341_sub{cid}_phase"] = SUBCIRCUIT_PHASE_MAP.get(
                phase, str(phase)
            )

    # --- DP 128: CT insertion bitmap ---
    if "128" in dp_data:
        with contextlib.suppress(ValueError, TypeError):
            expanded["341_ct_insertion"] = int(dp_data["128"])

    # --- DP 129: RSSI ---
    if "129" in dp_data:
        with contextlib.suppress(ValueError, TypeError):
            expanded["341_rssi"] = int(dp_data["129"])

    return expanded


# --------------------------------------------------------------------------- #
# Sensor entity descriptions for PCT341 fixed/summary sensors
# (sub-circuit sensors are created dynamically in sensor.py)
# --------------------------------------------------------------------------- #


@dataclass(frozen=True, kw_only=True)
class Owon341SensorEntityDescription(SensorEntityDescription):
    """Sensor description for PCT341 data."""

    data_key: str  # key inside expanded 341 data dict
    deviceinfo_key: str | None = None  # if set, read from manager.device_info instead
    scale: float = 1.0
    is_enum: bool = False
    is_string: bool = False


PHASE_341_SENSORS: tuple[Owon341SensorEntityDescription, ...] = (
    # --- Phase A ---
    Owon341SensorEntityDescription(
        key="341_voltage_a",
        data_key="341_voltage_a",
        translation_key="voltage_a",
        native_unit_of_measurement=UnitOfElectricPotential.VOLT,
        device_class=SensorDeviceClass.VOLTAGE,
        state_class=SensorStateClass.MEASUREMENT,
    ),
    Owon341SensorEntityDescription(
        key="341_current_a",
        data_key="341_current_a",
        translation_key="current_a",
        native_unit_of_measurement=UnitOfElectricCurrent.AMPERE,
        device_class=SensorDeviceClass.CURRENT,
        state_class=SensorStateClass.MEASUREMENT,
    ),
    Owon341SensorEntityDescription(
        key="341_power_a",
        data_key="341_power_a",
        translation_key="active_power_a",
        native_unit_of_measurement=UnitOfPower.KILO_WATT,
        device_class=SensorDeviceClass.POWER,
        state_class=SensorStateClass.MEASUREMENT,
    ),
    Owon341SensorEntityDescription(
        key="341_power_factor_a",
        data_key="341_power_factor_a",
        translation_key="power_factor_a",
        native_unit_of_measurement=PERCENTAGE,
        device_class=SensorDeviceClass.POWER_FACTOR,
        state_class=SensorStateClass.MEASUREMENT,
    ),
    # --- Phase B ---
    Owon341SensorEntityDescription(
        key="341_voltage_b",
        data_key="341_voltage_b",
        translation_key="voltage_b",
        native_unit_of_measurement=UnitOfElectricPotential.VOLT,
        device_class=SensorDeviceClass.VOLTAGE,
        state_class=SensorStateClass.MEASUREMENT,
    ),
    Owon341SensorEntityDescription(
        key="341_current_b",
        data_key="341_current_b",
        translation_key="current_b",
        native_unit_of_measurement=UnitOfElectricCurrent.AMPERE,
        device_class=SensorDeviceClass.CURRENT,
        state_class=SensorStateClass.MEASUREMENT,
    ),
    Owon341SensorEntityDescription(
        key="341_power_b",
        data_key="341_power_b",
        translation_key="active_power_b",
        native_unit_of_measurement=UnitOfPower.KILO_WATT,
        device_class=SensorDeviceClass.POWER,
        state_class=SensorStateClass.MEASUREMENT,
    ),
    Owon341SensorEntityDescription(
        key="341_power_factor_b",
        data_key="341_power_factor_b",
        translation_key="power_factor_b",
        native_unit_of_measurement=PERCENTAGE,
        device_class=SensorDeviceClass.POWER_FACTOR,
        state_class=SensorStateClass.MEASUREMENT,
    ),
    # --- Phase C ---
    Owon341SensorEntityDescription(
        key="341_voltage_c",
        data_key="341_voltage_c",
        translation_key="voltage_c",
        native_unit_of_measurement=UnitOfElectricPotential.VOLT,
        device_class=SensorDeviceClass.VOLTAGE,
        state_class=SensorStateClass.MEASUREMENT,
    ),
    Owon341SensorEntityDescription(
        key="341_current_c",
        data_key="341_current_c",
        translation_key="current_c",
        native_unit_of_measurement=UnitOfElectricCurrent.AMPERE,
        device_class=SensorDeviceClass.CURRENT,
        state_class=SensorStateClass.MEASUREMENT,
    ),
    Owon341SensorEntityDescription(
        key="341_power_c",
        data_key="341_power_c",
        translation_key="active_power_c",
        native_unit_of_measurement=UnitOfPower.KILO_WATT,
        device_class=SensorDeviceClass.POWER,
        state_class=SensorStateClass.MEASUREMENT,
    ),
    Owon341SensorEntityDescription(
        key="341_power_factor_c",
        data_key="341_power_factor_c",
        translation_key="power_factor_c",
        native_unit_of_measurement=PERCENTAGE,
        device_class=SensorDeviceClass.POWER_FACTOR,
        state_class=SensorStateClass.MEASUREMENT,
    ),
)

TOTAL_341_SENSORS: tuple[Owon341SensorEntityDescription, ...] = (
    Owon341SensorEntityDescription(
        key="341_current_total",
        data_key="341_current_total",
        translation_key="current_total",
        native_unit_of_measurement=UnitOfElectricCurrent.AMPERE,
        device_class=SensorDeviceClass.CURRENT,
        state_class=SensorStateClass.MEASUREMENT,
    ),
    Owon341SensorEntityDescription(
        key="341_power_total",
        data_key="341_power_total",
        translation_key="active_power_total",
        native_unit_of_measurement=UnitOfPower.KILO_WATT,
        device_class=SensorDeviceClass.POWER,
        state_class=SensorStateClass.MEASUREMENT,
    ),
    Owon341SensorEntityDescription(
        key="341_frequency",
        data_key="341_frequency",
        translation_key="frequency",
        native_unit_of_measurement=UnitOfFrequency.HERTZ,
        device_class=SensorDeviceClass.FREQUENCY,
        state_class=SensorStateClass.MEASUREMENT,
    ),
    Owon341SensorEntityDescription(
        key="341_energy_consumed_total",
        data_key="341_energy_consumed_total",
        translation_key="energy_consumed_total",
        native_unit_of_measurement=UnitOfEnergy.KILO_WATT_HOUR,
        device_class=SensorDeviceClass.ENERGY,
        state_class=SensorStateClass.TOTAL_INCREASING,
    ),
    Owon341SensorEntityDescription(
        key="341_energy_generated_total",
        data_key="341_energy_generated_total",
        translation_key="energy_generated_total",
        native_unit_of_measurement=UnitOfEnergy.KILO_WATT_HOUR,
        device_class=SensorDeviceClass.ENERGY,
        state_class=SensorStateClass.TOTAL_INCREASING,
    ),
)

DIAG_341_SENSORS: tuple[Owon341SensorEntityDescription, ...] = (
    Owon341SensorEntityDescription(
        key="device_id",
        data_key="device_id",
        deviceinfo_key="device_id",
        translation_key="device_id",
        entity_category=EntityCategory.DIAGNOSTIC,
        is_string=True,
    ),
    Owon341SensorEntityDescription(
        key="device_model",
        data_key="device_model",
        deviceinfo_key="model",
        translation_key="device_model",
        entity_category=EntityCategory.DIAGNOSTIC,
        is_string=True,
    ),
    Owon341SensorEntityDescription(
        key="device_sub_model",
        data_key="device_sub_model",
        deviceinfo_key="subModel",
        translation_key="device_sub_model",
        entity_category=EntityCategory.DIAGNOSTIC,
        is_string=True,
    ),
    Owon341SensorEntityDescription(
        key="firmware_version",
        data_key="1",
        deviceinfo_key="fw_version",
        translation_key="firmware_version",
        entity_category=EntityCategory.DIAGNOSTIC,
        is_string=True,
    ),
    Owon341SensorEntityDescription(
        key="341_measurement_type",
        data_key="341_measurement_type",
        translation_key="measurement_type",
        entity_category=EntityCategory.DIAGNOSTIC,
        is_string=True,
    ),
)

ALL_341_FIXED_SENSORS: tuple[Owon341SensorEntityDescription, ...] = (
    *PHASE_341_SENSORS,
    *TOTAL_341_SENSORS,
    *DIAG_341_SENSORS,
)


def get_341_subcircuit_sensors(
    circuit_ids: Iterable[int] | None = None,
    max_circuits: int = 16,
) -> tuple[Owon341SensorEntityDescription, ...]:
    """Return sub-circuit sensor descriptions for PCT341, grouped by circuit.

    For each circuit the order is: power, current, energy consumed, energy generated.
    DP125 supplies power/current; DP126 supplies energy (defaults to 0 when absent).
    """
    sensors: list[Owon341SensorEntityDescription] = []
    if circuit_ids is None:
        selected_ids = range(1, max_circuits + 1)
    else:
        selected_ids = sorted(
            {
                circuit_id
                for circuit_id in circuit_ids
                if 1 <= circuit_id <= max_circuits
            }
        )

    for circuit_id in selected_ids:
        sensors.append(
            Owon341SensorEntityDescription(
                key=f"341_sub{circuit_id}_power",
                data_key=f"341_sub{circuit_id}_power",
                translation_key="sub_circuit_active_power",
                native_unit_of_measurement=UnitOfPower.KILO_WATT,
                device_class=SensorDeviceClass.POWER,
                state_class=SensorStateClass.MEASUREMENT,
            )
        )
        sensors.append(
            Owon341SensorEntityDescription(
                key=f"341_sub{circuit_id}_current",
                data_key=f"341_sub{circuit_id}_current",
                translation_key="sub_circuit_current",
                native_unit_of_measurement=UnitOfElectricCurrent.AMPERE,
                device_class=SensorDeviceClass.CURRENT,
                state_class=SensorStateClass.MEASUREMENT,
            )
        )
        sensors.append(
            Owon341SensorEntityDescription(
                key=f"341_sub{circuit_id}_energy_consumed",
                data_key=f"341_sub{circuit_id}_energy_consumed",
                translation_key="sub_circuit_energy_consumed",
                native_unit_of_measurement=UnitOfEnergy.KILO_WATT_HOUR,
                device_class=SensorDeviceClass.ENERGY,
                state_class=SensorStateClass.TOTAL_INCREASING,
            )
        )
        sensors.append(
            Owon341SensorEntityDescription(
                key=f"341_sub{circuit_id}_energy_generated",
                data_key=f"341_sub{circuit_id}_energy_generated",
                translation_key="sub_circuit_energy_generated",
                native_unit_of_measurement=UnitOfEnergy.KILO_WATT_HOUR,
                device_class=SensorDeviceClass.ENERGY,
                state_class=SensorStateClass.TOTAL_INCREASING,
            )
        )
    return tuple(sensors)
