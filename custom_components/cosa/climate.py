"""Climate platform for COSA integration.

This module implements the DataUpdateCoordinator and entity for the COSA
thermostat integration. It normalizes differing API responses and provides
both async methods and synchronous wrappers for Home Assistant to call.
"""

from __future__ import annotations

import asyncio
import logging
from typing import Any, Dict, Optional

from homeassistant.components.climate import (
    ClimateEntity,
    ClimateEntityFeature,
    HVACMode,
)
from homeassistant.components.climate.const import (
    PRESET_AWAY,
    PRESET_HOME,
    PRESET_SLEEP,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import ATTR_TEMPERATURE, UnitOfTemperature
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity import DeviceInfo
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import (
    CoordinatorEntity,
    DataUpdateCoordinator,
)

from .api import CosaAPIClient, CosaAPIError
from .const import (
    DOMAIN,
    MODE_AWAY,
    MODE_AUTO,
    MODE_CUSTOM,
    MODE_FROZEN,
    MODE_HOME,
    MODE_SCHEDULE,
    MODE_SLEEP,
    PRESET_AUTO,
    PRESET_CUSTOM,
    PRESET_SCHEDULE,
    SCAN_INTERVAL,
    MIN_TEMP,
    MAX_TEMP,
    TEMP_STEP,
)

_LOGGER = logging.getLogger(__name__)


async def async_setup_entry(
    hass: HomeAssistant,
    config_entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up COSA climate platform."""
    coordinator: CosaDataUpdateCoordinator = hass.data[DOMAIN][config_entry.entry_id]["coordinator"]

    entity = CosaClimate(coordinator, config_entry)
    async_add_entities([entity])
    _LOGGER.info("COSA climate entity created: %s", entity.unique_id)

    # Try to refresh data if not already available
    if not coordinator.data:
        try:
            await coordinator.async_config_entry_first_refresh()
            _LOGGER.info("COSA coordinator refresh successful")
        except Exception as err:
            _LOGGER.error("Failed to refresh coordinator during setup: %s", err, exc_info=True)


class CosaDataUpdateCoordinator(DataUpdateCoordinator):
    """Class to manage fetching COSA data."""

    def __init__(self, hass: HomeAssistant, config_entry: ConfigEntry) -> None:
        self.config_entry = config_entry
        self.client: Optional[CosaAPIClient] = None
        self.endpoint_id: Optional[str] = None

        super().__init__(
            hass,
            _LOGGER,
            name=DOMAIN,
            update_interval=SCAN_INTERVAL,
        )

    async def _async_update_data(self) -> Dict[str, Any]:
        """Fetch data from COSA API and normalize different response shapes."""
        from homeassistant.helpers.aiohttp_client import async_get_clientsession

        if self.client is None:
            self.client = CosaAPIClient(
                username=self.config_entry.data.get("username"),
                password=self.config_entry.data.get("password"),
                endpoint_id=self.config_entry.data.get("endpoint_id"),
                token=self.config_entry.data.get("token"),
                session=async_get_clientsession(self.hass),
            )
            self.endpoint_id = self.config_entry.data.get("endpoint_id")
            if not self.client._token:  # type: ignore[attr-defined]
                await self.client.login()

        # If endpoint_id is not set, try to get it from API
        if not self.endpoint_id:
            endpoints = await self.client.list_endpoints()
            if endpoints and len(endpoints) > 0:
                first_endpoint = endpoints[0]
                self.endpoint_id = (
                    first_endpoint.get("id") or first_endpoint.get("_id") or first_endpoint.get("endpoint")
                )
                _LOGGER.info("Auto-detected endpoint ID: %s", self.endpoint_id)
            else:
                _LOGGER.error("No endpoints found for user")
                raise CosaAPIError("No endpoints found")

        if not self.endpoint_id:
            raise CosaAPIError("Endpoint ID is required but not available")

        try:
            status = await self.client.get_endpoint_status(self.endpoint_id)

            # Handle different response formats including nested 'data' wrappers
            endpoint_data = {}
            if isinstance(status, dict):
                if "endpoint" in status:
                    endpoint_data = status.get("endpoint") or {}
                elif "data" in status and isinstance(status["data"], dict):
                    data_inner = status["data"]
                    if "endpoint" in data_inner:
                        endpoint_data = data_inner.get("endpoint") or {}
                    else:
                        endpoint_data = data_inner if "temperature" in data_inner else {}
                elif "temperature" in status or "humidity" in status:
                    endpoint_data = status
                elif "endpoints" in status and isinstance(status["endpoints"], list) and status["endpoints"]:
                    endpoint_data = status["endpoints"][0]
            elif isinstance(status, list) and len(status) > 0:
                endpoint_data = status[0]

            _LOGGER.debug("Endpoint data received: %s", endpoint_data)

            if not endpoint_data:
                _LOGGER.warning("Empty endpoint data received. Full response: %s", status)
                # Return default values to prevent entity creation failure
                return {
                    "temperature": None,
                    "target_temperature": None,
                    "humidity": None,
                    "combi_state": "off",
                    "option": None,
                    "mode": None,
                    "target_temperatures": {"home": None, "away": None, "sleep": None, "custom": None},
                }

            raw_target_temps = endpoint_data.get("targetTemperatures") or {}
            raw_target_temp = endpoint_data.get("targetTemperature")
            option = endpoint_data.get("option")
            selected_target = None
            if raw_target_temp is not None:
                selected_target = raw_target_temp
            elif raw_target_temps:
                if option and option in raw_target_temps:
                    selected_target = raw_target_temps.get(option)
                else:
                    selected_target = raw_target_temps.get("home") or next(iter(raw_target_temps.values()), None)

            return {
                "temperature": endpoint_data.get("temperature"),
                "target_temperature": selected_target,
                "humidity": endpoint_data.get("humidity"),
                "combi_state": endpoint_data.get("combiState"),
                "option": option,
                "mode": endpoint_data.get("mode"),
                "target_temperatures": {
                    "home": raw_target_temps.get("home"),
                    "away": raw_target_temps.get("away"),
                    "sleep": raw_target_temps.get("sleep"),
                    "custom": raw_target_temps.get("custom"),
                },
                "name": endpoint_data.get("name"),
                "operation_mode": endpoint_data.get("operationMode"),
            }
        except CosaAPIError as err:
            _LOGGER.error("Error fetching COSA data: %s", err)
            if "401" in str(err) or "expired" in str(err).lower() or "authentication" in str(err).lower():
                _LOGGER.info("Authentication error detected, attempting to re-login")
                try:
                    await self.client.login()
                    # Retry once after re-login
                    status = await self.client.get_endpoint_status(self.endpoint_id)
                    endpoint_data = status.get("endpoint", {})
                    return {
                        "temperature": endpoint_data.get("temperature"),
                        "target_temperature": endpoint_data.get("targetTemperature"),
                        "humidity": endpoint_data.get("humidity"),
                        "combi_state": endpoint_data.get("combiState"),
                        "option": endpoint_data.get("option"),
                        "mode": endpoint_data.get("mode"),
                        "target_temperatures": {
                            "home": endpoint_data.get("targetTemperatures", {}).get("home"),
                            "away": endpoint_data.get("targetTemperatures", {}).get("away"),
                            "sleep": endpoint_data.get("targetTemperatures", {}).get("sleep"),
                            "custom": endpoint_data.get("targetTemperatures", {}).get("custom"),
                        },
                    }
                except Exception as retry_err:
                    _LOGGER.error("Re-login failed: %s", retry_err)
                    raise
            raise


class CosaClimate(CoordinatorEntity, ClimateEntity):
    """Representation of a COSA climate device."""

    _attr_temperature_unit = UnitOfTemperature.CELSIUS
    _attr_hvac_modes = [HVACMode.HEAT, HVACMode.OFF]
    _attr_supported_features = ClimateEntityFeature.TARGET_TEMPERATURE | ClimateEntityFeature.PRESET_MODE
    _attr_preset_modes = [
        PRESET_HOME,
        PRESET_AWAY,
        PRESET_SLEEP,
        PRESET_CUSTOM,
        PRESET_AUTO,
        PRESET_SCHEDULE,
    ]
    _attr_min_temp = MIN_TEMP
    _attr_max_temp = MAX_TEMP
    _attr_target_temperature_step = TEMP_STEP

    def __init__(self, coordinator: CosaDataUpdateCoordinator, config_entry: ConfigEntry) -> None:
        """Initialize the climate device."""
        super().__init__(coordinator)
        self._config_entry = config_entry
        self._attr_name = "COSA Termostat"
        self._attr_unique_id = f"{DOMAIN}_{config_entry.entry_id}_climate"
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, config_entry.entry_id)},
            name=f"{config_entry.data.get('device_name') or ('COSA Termostat (' + config_entry.data.get('username', 'Unknown') + ')')}",
            manufacturer="COSA",
            model="Smart Thermostat",
        )

    @property
    def current_temperature(self) -> Optional[float]:
        """Return the current temperature or None if no data yet."""
        if not self.coordinator.data:
            return None
        return self.coordinator.data.get("temperature")

    @property
    def target_temperature(self) -> Optional[float]:
        """Return the target temperature or None if no data yet."""
        if not self.coordinator.data:
            return None
        return self.coordinator.data.get("target_temperature")

    @property
    def hvac_mode(self) -> Optional[HVACMode]:
        """Return current HVAC mode or None if no data yet."""
        if not self.coordinator.data:
            return None

        mode = self.coordinator.data.get("mode")
        option = self.coordinator.data.get("option")

        # If mode is "manual" and option is "frozen", it's OFF
        if mode == "manual" and option == "frozen":
            return HVACMode.OFF

        # Otherwise, it's HEAT (assuming it's on)
        return HVACMode.HEAT

    @property
    def preset_mode(self) -> Optional[str]:
        """Return current preset mode or None if no data yet."""
        if not self.coordinator.data:
            return None
        option = self.coordinator.data.get("option")
        mode = self.coordinator.data.get("mode")

        if mode == "auto":
            return PRESET_AUTO
        elif mode == "schedule":
            return PRESET_SCHEDULE

        if option == MODE_HOME:
            return PRESET_HOME
        elif option == MODE_AWAY:
            return PRESET_AWAY
        elif option == MODE_SLEEP:
            return PRESET_SLEEP
        elif option == MODE_CUSTOM:
            return PRESET_CUSTOM
        elif option == MODE_AUTO:
            return PRESET_AUTO
        elif option == MODE_SCHEDULE:
            return PRESET_SCHEDULE

        return None

    @property
    def extra_state_attributes(self) -> Dict[str, Any]:
        """Return extra state attributes for the entity."""
        if not self.coordinator.data:
            return {}
        return {
            "humidity": self.coordinator.data.get("humidity"),
            "combi_state": self.coordinator.data.get("combi_state"),
            "option": self.coordinator.data.get("option"),
        }

    async def _ensure_coordinator_client(self) -> CosaAPIClient:
        """Ensure a working API client is available on the coordinator."""
        from homeassistant.helpers.aiohttp_client import async_get_clientsession

        if not self.coordinator.client:
            self.coordinator.client = CosaAPIClient(
                username=self._config_entry.data.get("username"),
                password=self._config_entry.data.get("password"),
                endpoint_id=self._config_entry.data.get("endpoint_id") or self.coordinator.endpoint_id,
                token=self._config_entry.data.get("token"),
                session=async_get_clientsession(self.hass),
            )

        # Always try to login if no token
        if not getattr(self.coordinator.client, "_token", None):
            try:
                await self.coordinator.client.login()
            except CosaAPIError as err:
                _LOGGER.error("Failed to login while ensuring client: %s", err)
                raise

        # Ensure endpoint_id is available
        if not self.coordinator.endpoint_id:
            try:
                endpoints = await self.coordinator.client.list_endpoints()
                if endpoints and len(endpoints) > 0:
                    first = endpoints[0]
                    self.coordinator.endpoint_id = first.get("id") or first.get("_id") or first.get("endpoint")
                    try:
                        self.coordinator.client._endpoint_id = self.coordinator.endpoint_id
                    except Exception:
                        pass
                else:
                    raise CosaAPIError("No endpoints found")
            except CosaAPIError as err:
                _LOGGER.error("Failed to get endpoint_id: %s", err)
                raise

        return self.coordinator.client

    async def async_set_temperature(self, **kwargs: Any) -> None:
        """Set new target temperature asynchronously."""
        temperature = kwargs.get(ATTR_TEMPERATURE)
        if temperature is None:
            return

        current_preset = self.preset_mode or PRESET_HOME

        try:
            client = await self._ensure_coordinator_client()

            # For COSA, set temperature via mode change
            option_map = {
                PRESET_HOME: MODE_HOME,
                PRESET_AWAY: MODE_AWAY,
                PRESET_SLEEP: MODE_SLEEP,
                PRESET_CUSTOM: MODE_CUSTOM,
            }
            option = option_map.get(current_preset, MODE_HOME)

            # Set mode with the new temperature
            await client.set_mode(
                mode="manual",
                option=option,
                temperature=temperature,
                endpoint_id=self.coordinator.endpoint_id,
            )

            await self.coordinator.async_request_refresh()
        except CosaAPIError as err:
            _LOGGER.error("Error setting temperature: %s", err)
            raise

    async def async_set_hvac_mode(self, hvac_mode: HVACMode) -> None:
        """Set new HVAC mode asynchronously."""
        try:
            if hvac_mode == HVACMode.OFF:
                client = await self._ensure_coordinator_client()
                await client.set_mode(
                    mode="manual",
                    option=MODE_FROZEN,
                    endpoint_id=self.coordinator.endpoint_id,
                )
            elif hvac_mode == HVACMode.HEAT:
                current_preset = self.preset_mode or PRESET_HOME
                option_map = {
                    PRESET_HOME: MODE_HOME,
                    PRESET_AWAY: MODE_AWAY,
                    PRESET_SLEEP: MODE_SLEEP,
                    PRESET_CUSTOM: MODE_CUSTOM,
                }
                option = option_map.get(current_preset, MODE_HOME)
                client = await self._ensure_coordinator_client()
                await client.set_mode(
                    mode="manual",
                    option=option,
                    endpoint_id=self.coordinator.endpoint_id,
                )
            await self.coordinator.async_request_refresh()
        except CosaAPIError as err:
            _LOGGER.error("Error setting HVAC mode: %s", err)
            raise

    async def async_set_preset_mode(self, preset_mode: str) -> None:
        """Set new preset mode asynchronously."""
        option_map = {
            PRESET_HOME: MODE_HOME,
            PRESET_AWAY: MODE_AWAY,
            PRESET_SLEEP: MODE_SLEEP,
            PRESET_CUSTOM: MODE_CUSTOM,
            PRESET_AUTO: MODE_AUTO,
            PRESET_SCHEDULE: MODE_SCHEDULE,
        }

        option = option_map.get(preset_mode)
        if not option:
            _LOGGER.error("Invalid preset mode: %s", preset_mode)
            return

        try:
            client = await self._ensure_coordinator_client()
            if preset_mode in [PRESET_AUTO, PRESET_SCHEDULE]:
                await client.set_mode(
                    mode=preset_mode,
                    option=option,
                    endpoint_id=self.coordinator.endpoint_id,
                )
            else:
                await client.set_mode(
                    mode="manual",
                    option=option,
                    endpoint_id=self.coordinator.endpoint_id,
                )
            await self.coordinator.async_request_refresh()
        except CosaAPIError as err:
            _LOGGER.error("Error setting preset mode: %s", err)
            raise

    def set_temperature(self, **kwargs: Any) -> None:
        """Synchronous wrapper for setting temperature."""
        try:
            fut = asyncio.run_coroutine_threadsafe(self.async_set_temperature(**kwargs), self.hass.loop)
            fut.result()
        except Exception as err:
            _LOGGER.error("Error in set_temperature wrapper: %s", err)

    def set_hvac_mode(self, hvac_mode: HVACMode) -> None:
        """Synchronous wrapper for setting HVAC mode."""
        try:
            fut = asyncio.run_coroutine_threadsafe(self.async_set_hvac_mode(hvac_mode), self.hass.loop)
            fut.result()
        except Exception as err:
            _LOGGER.error("Error in set_hvac_mode wrapper: %s", err)

    def set_preset_mode(self, preset_mode: str) -> None:
        """Synchronous wrapper for setting preset mode."""
        try:
            fut = asyncio.run_coroutine_threadsafe(self.async_set_preset_mode(preset_mode), self.hass.loop)
            fut.result()
        except Exception as err:
            _LOGGER.error("Error in set_preset_mode wrapper: %s", err)
