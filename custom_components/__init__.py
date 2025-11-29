"""The COSA integration."""

from __future__ import annotations

import logging

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import Platform
from homeassistant.core import HomeAssistant

from .const import DOMAIN

_LOGGER = logging.getLogger(__name__)

PLATFORMS: list[Platform] = [Platform.CLIMATE, Platform.SENSOR]


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Set up COSA from a config entry."""
    hass.data.setdefault(DOMAIN, {})
    hass.data[DOMAIN][entry.entry_id] = {}

    _LOGGER.debug("Setting up COSA entry: %s", entry.entry_id)
    # Create coordinator and store it
    from .climate import CosaDataUpdateCoordinator

    coordinator = CosaDataUpdateCoordinator(hass, entry)
    hass.data[DOMAIN][entry.entry_id]["coordinator"] = coordinator
    _LOGGER.debug("Coordinator created for entry %s", entry.entry_id)
    # Ensure the coordinator performs the first data refresh before setting up platforms
    try:
        await coordinator.async_config_entry_first_refresh()
        _LOGGER.debug("Coordinator initial refresh completed for entry %s", entry.entry_id)
    except Exception as err:
        _LOGGER.error("Initial coordinator refresh failed for entry %s: %s", entry.entry_id, err)

    # Forward the setup to all platforms
    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)

    return True


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Unload a config entry."""
    unload_ok = await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
    if unload_ok:
        hass.data[DOMAIN].pop(entry.entry_id)

    return unload_ok

