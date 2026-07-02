"""Config flow for OWON."""

from __future__ import annotations

from homeassistant.config_entries import ConfigFlow, ConfigFlowResult

from .const import DOMAIN


class OwonConfigFlow(ConfigFlow, domain=DOMAIN):
    """Handle a config flow for OWON."""

    VERSION = 1

    async def async_step_user(self, user_input: dict | None = None) -> ConfigFlowResult:
        """Handle the initial step."""
        if user_input is not None:
            await self.async_set_unique_id(DOMAIN)
            self._abort_if_unique_id_configured()
            return self.async_create_entry(
                title="OWON",
                data={},
            )
        return self.async_show_form(step_id="user")
