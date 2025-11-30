"""Config flow for COSA integration."""

import logging
from typing import Any, Dict, Optional

import voluptuous as vol

from homeassistant import config_entries
from homeassistant.core import HomeAssistant
from homeassistant.data_entry_flow import FlowResult
from homeassistant.exceptions import HomeAssistantError

from .api import CosaAPIClient, CosaAPIError
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from .const import DOMAIN

_LOGGER = logging.getLogger(__name__)

STEP_USER_DATA_SCHEMA = vol.Schema(
    {
        # Allow token-only flows so users don't need to provide username/password
        vol.Optional("username", description="Email veya kullanıcı adı"): str,
        vol.Optional("password"): str,
        vol.Optional("endpoint_id", description="Endpoint ID (opsiyonel - otomatik tespit edilebilir)"): str,
        vol.Optional("token", description="Auth token (opsiyonel - kullanıcının proxy veya dış token'ı varsa)"): str,
    }
)


async def validate_input(hass: HomeAssistant, data: Dict[str, Any]) -> Dict[str, Any]:
    """Validate the user input allows us to connect."""
    client = CosaAPIClient(
        username=data.get("username"),
        password=data.get("password"),
        endpoint_id=data.get("endpoint_id"),
        token=data.get("token"),
        session=async_get_clientsession(hass),
    )

    try:
        # Validate credentials: either token provided, or username+password set
        if not data.get("token") and not (data.get("username") and data.get("password")):
            raise InvalidAuth("Please provide token or username/password")

        # If token is not provided, try to login using username/password
        if not data.get("token"):
            if not await client.login():
                raise InvalidAuth
        else:
            # Token provided, validate by fetching user info
            try:
                await client.get_user_info()
            except Exception as err:
                _LOGGER.error("Token validation failed: %s", err)
                raise InvalidAuth from err

        # Get endpoint status and name to verify connection and store the device name
        device_name = None
        endpoint_data = {}
        if client._endpoint_id:
            status = await client.get_endpoint_status()
            if isinstance(status, dict) and "endpoint" in status:
                endpoint_data = status.get("endpoint") or {}
            elif isinstance(status, dict) and "data" in status and isinstance(status["data"], dict):
                endpoint_data = status["data"].get("endpoint") or status["data"]
            elif isinstance(status, dict) and "temperature" in status:
                endpoint_data = status
            elif isinstance(status, list) and len(status) > 0:
                endpoint_data = status[0]
            device_name = endpoint_data.get("name") if endpoint_data else None
        else:
            # If no endpoint_id provided, try to get endpoints list
            try:
                endpoints = await client.list_endpoints()
                if endpoints and len(endpoints) > 0:
                    # Use first endpoint if available
                    first_endpoint = endpoints[0]
                    client._endpoint_id = first_endpoint.get("id") or first_endpoint.get("_id") or first_endpoint.get("endpoint")
                    if client._endpoint_id:
                        status = await client.get_endpoint_status(client._endpoint_id)
                        if isinstance(status, dict) and "endpoint" in status:
                            endpoint_data = status.get("endpoint") or {}
                        elif isinstance(status, dict) and "data" in status and isinstance(status["data"], dict):
                            endpoint_data = status["data"].get("endpoint") or status["data"]
                        elif isinstance(status, dict) and "temperature" in status:
                            endpoint_data = status
                        elif isinstance(status, list) and len(status) > 0:
                            endpoint_data = status[0]
                        device_name = endpoint_data.get("name") if endpoint_data else None
                    else:
                        endpoint_data = {}
                else:
                    endpoint_data = {}
            except Exception:
                # If list_endpoints fails, just verify login works
                endpoint_data = {}

        _LOGGER.debug("validate_input: login successful, endpoint_id=%s", client._endpoint_id)
        await client.close()

        # Return info that will be stored in the config entry
        # Include device_name if we detected one for nicer device naming later
        entry_data = {
            "title": f"COSA Termostat ({data.get('username') or data.get('token') or 'COSA'})",
            "endpoint_id": client._endpoint_id or data.get("endpoint_id", ""),
        }
        if device_name:
            entry_data["device_name"] = device_name
        return entry_data
    except CosaAPIError as err:
        _LOGGER.error("API error during validation: %s", err)
        # Map authentication errors to InvalidAuth so the UI shows proper error
        msg = str(err).lower()
        if "invalid" in msg and ("auth" in msg or "username" in msg or "credentials" in msg):
            raise InvalidAuth from err
        # If server returned 404, it indicates invalid endpoint/path — treat as cannot connect
        if "status 404" in msg or "404" in msg:
            _LOGGER.warning("Login attempt returned 404 — check the API base URL or endpoint paths; consider using a token if available")
            raise CannotConnect from err
        raise CannotConnect from err
    except Exception as err:
        _LOGGER.error("Unexpected error during validation: %s", err)
        raise CannotConnect from err
    finally:
        await client.close()


class ConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    """Handle a config flow for COSA."""

    VERSION = 1

    async def async_step_user(
        self, user_input: Optional[Dict[str, Any]] = None
    ) -> FlowResult:
        """Handle the initial step."""
        if user_input is None:
            return self.async_show_form(
                step_id="user", data_schema=STEP_USER_DATA_SCHEMA
            )

        errors = {}

        try:
            info = await validate_input(self.hass, user_input)
        except CannotConnect:
            errors["base"] = "cannot_connect"
        except InvalidAuth:
            errors["base"] = "invalid_auth"
        except Exception:  # pylint: disable=broad-except
            _LOGGER.exception("Unexpected exception")
            errors["base"] = "unknown"
        else:
            # Check if already configured: use token or username as unique id
            unique_id = user_input.get("token") or user_input.get("username")
            await self.async_set_unique_id(unique_id)
            self._abort_if_unique_id_configured()

            # Add endpoint_id to user_input if it was found
            if info.get("endpoint_id"):
                user_input["endpoint_id"] = info["endpoint_id"]

            return self.async_create_entry(title=info["title"], data=user_input)

        return self.async_show_form(
            step_id="user", data_schema=STEP_USER_DATA_SCHEMA, errors=errors
        )


class CannotConnect(HomeAssistantError):
    """Error to indicate we cannot connect."""


class InvalidAuth(HomeAssistantError):
    """Error to indicate there is invalid auth."""

