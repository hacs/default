"""Sensor platform for COSA integration."""

import logging
from typing import Any, Optional

from homeassistant.components.sensor import (
    SensorEntity,
    SensorEntityDescription,
    SensorStateClass,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import (
    PERCENTAGE,
    UnitOfTemperature,
)
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity import DeviceInfo
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import DOMAIN, MODE_AWAY, MODE_CUSTOM, MODE_FROZEN, MODE_HOME, MODE_SLEEP
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator

_LOGGER = logging.getLogger(__name__)

SENSOR_DESCRIPTIONS: tuple[SensorEntityDescription, ...] = (
    SensorEntityDescription(
        key="combi_state",
        name="Kombi Durumu",
        icon="mdi:radiator",
        translation_key="combi_state",
    ),
    SensorEntityDescription(
        key="operation_mode",
        name="Kombi Çalışma Durumu",
        icon="mdi:thermostat",
        translation_key="operation_mode",
    ),
    SensorEntityDescription(
        key="temperature",
        name="Kombi Sıcaklık",
        native_unit_of_measurement=UnitOfTemperature.CELSIUS,
        state_class=SensorStateClass.MEASUREMENT,
        icon="mdi:thermometer",
        translation_key="temperature",
    ),
    SensorEntityDescription(
        key="target_temperature",
        name="Kombi Hedef Sıcaklık",
        native_unit_of_measurement=UnitOfTemperature.CELSIUS,
        state_class=SensorStateClass.MEASUREMENT,
        icon="mdi:target",
        translation_key="target_temperature",
    ),
    SensorEntityDescription(
        key="humidity",
        name="Kombi Nem",
        native_unit_of_measurement=PERCENTAGE,
        state_class=SensorStateClass.MEASUREMENT,
        icon="mdi:water-percent",
        translation_key="humidity",
    ),
)


async def async_setup_entry(
    hass: HomeAssistant,
    config_entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up COSA sensor platform."""
    coordinator: DataUpdateCoordinator = hass.data[DOMAIN][config_entry.entry_id][
        "coordinator"
    ]

    entities = [
        CosaSensor(coordinator, config_entry, description)
        for description in SENSOR_DESCRIPTIONS
    ]

    async_add_entities(entities)
    _LOGGER.info("COSA sensor entities added: %d", len(entities))


class CosaSensor(CoordinatorEntity, SensorEntity):
    """Representation of a COSA sensor."""

    def __init__(
        self,
        coordinator: DataUpdateCoordinator,
        config_entry: ConfigEntry,
        description: SensorEntityDescription,
    ) -> None:
        """Initialize the sensor."""
        super().__init__(coordinator)
        self.entity_description = description
        self._config_entry = config_entry
        self._attr_unique_id = f"{DOMAIN}_{config_entry.entry_id}_{description.key}"
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, config_entry.entry_id)},
            name=f"{config_entry.data.get('device_name') or ('COSA Termostat (' + config_entry.data.get('username', 'Unknown') + ')')}",
            manufacturer="COSA",
            model="Smart Thermostat",
        )

    @property
    def native_value(self) -> Optional[Any]:
        """Return the state of the sensor."""
        if not self.coordinator.data:
            return None

        data = self.coordinator.data

        if self.entity_description.key == "combi_state":
            combi_state = data.get("combi_state", "off")
            return "Kapalı" if combi_state == "off" else "Çalışıyor"

        elif self.entity_description.key == "operation_mode":
            option = data.get("option")
            operation_mode = data.get("operation_mode")
            if operation_mode:
                # Map operation mode directly (heating -> Isıtma, cooling -> Soğutma)
                if operation_mode.lower() == "heating":
                    return "Isıtma"
                if operation_mode.lower() == "cooling":
                    return "Soğutma"
            # Fall back to option label translations
            if option == MODE_HOME:
                return "Ev"
            elif option == MODE_AWAY:
                return "Dışarıda"
            elif option == MODE_SLEEP:
                return "Gece"
            elif option == MODE_CUSTOM:
                return "Kullanıcı"
            elif option == MODE_FROZEN:
                return "Kombi Kapalı"
            else:
                return "Bilinmiyor"

        elif self.entity_description.key == "temperature":
            return data.get("temperature")

        elif self.entity_description.key == "target_temperature":
            return data.get("target_temperature")

        elif self.entity_description.key == "humidity":
            return data.get("humidity")

        return None

