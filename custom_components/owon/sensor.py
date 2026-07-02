"""Sensor platform entry point – delegates to sensor_321."""

from .sensor_321 import async_setup_entry

__all__ = ["async_setup_entry"]
