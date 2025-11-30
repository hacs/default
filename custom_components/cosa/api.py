"""API client for COSA integration."""

import logging
from typing import Any, Dict, Optional
import aiohttp

from .const import (
    API_BASE_URL,
    API_TIMEOUT,
    ENDPOINT_LOGIN,
    ENDPOINT_GET_ENDPOINT,
    ENDPOINT_SET_MODE,
    ENDPOINT_SET_TARGET_TEMPERATURES,
    ENDPOINT_LIST_ENDPOINTS,
    ENDPOINT_SET_OPTION,
    USER_AGENT,
    CONTENT_TYPE,
)

_LOGGER = logging.getLogger(__name__)


class CosaAPIError(Exception):
    """Exception raised for API errors."""

    pass


class CosaAPIClient:
    """Client for COSA API."""

    def __init__(
        self,
        username: str | None = None,
        password: str | None = None,
        endpoint_id: Optional[str] = None,
        token: Optional[str] = None,
        session: Optional[aiohttp.ClientSession] = None,
    ):
        """Initialize the API client."""
        self._username = username
        self._password = password
        self._endpoint_id = endpoint_id
        self._token: Optional[str] = None
        # Allow passing a pre-existing token (e.g. from a proxy or manual config)
        if token:
            self._token = token
        # allow passing an existing aiohttp session (recommended: async_get_clientsession(hass))
        self._session: Optional[aiohttp.ClientSession] = session
        # Whether the session is created (owned) by this client. If a session is passed in
        # (e.g., from Home Assistant's async_get_clientsession), we must NOT close it.
        # This flag will be set to True when we create a new session inside _get_session().
        self._own_session: bool = False
        self._retry_count = 3  # Retry count for failed requests

    async def _get_session(self) -> aiohttp.ClientSession:
        """Get or create aiohttp session."""
        if self._session is None or (hasattr(self._session, "closed") and self._session.closed):
            # If no session provided, create a new ClientSession with timeout
            self._session = aiohttp.ClientSession(
                timeout=aiohttp.ClientTimeout(total=API_TIMEOUT)
            )
            # We created this session; we are responsible for closing it later
            self._own_session = True
        return self._session

    async def close(self):
        """Close the session."""
        if self._session and not self._session.closed and self._own_session:
            # Only close if we created the session in _get_session; don't close a session
            # passed in by Home Assistant (async_get_clientsession)
            await self._session.close()
            self._session = None
            self._own_session = False

    async def login(self) -> bool:
        """Login and get authentication token."""
        # Try different login endpoints and payload formats
        login_endpoints = [
            "/users/login",
            "/auth/login",
            "/login",
        ]
        
        payload_formats = [
            {"username": self._username, "password": self._password},
            {"email": self._username, "password": self._password},
            {"user": self._username, "password": self._password},
        ]

        session = await self._get_session()
        last_error = None

        for endpoint in login_endpoints:
            for payload in payload_formats:
                try:
                    url = f"{API_BASE_URL}{endpoint}"
                    headers = {
                        "User-Agent": USER_AGENT,
                        "Content-Type": CONTENT_TYPE,
                    }

                    _LOGGER.debug("Attempting login to %s with payload keys: %s", url, list(payload.keys()))
                    async with session.post(url, json=payload, headers=headers) as response:
                        _LOGGER.debug("Login response status %s from %s", response.status, url)
                        if response.status == 200:
                            data = await response.json()
                            
                            # Try to extract token from various response formats
                            def find_token(obj):
                                # Recursively search for token strings in nested structures
                                if isinstance(obj, dict):
                                    for k, v in obj.items():
                                        if k and isinstance(k, str) and k.lower() in ("authtoken", "authtoken", "authtoken", "token", "accesstoken", "access_token", "auth_token"):
                                            return v
                                        if isinstance(v, (dict, list)):
                                            res = find_token(v)
                                            if res:
                                                return res
                                elif isinstance(obj, list):
                                    for i in obj:
                                        res = find_token(i)
                                        if res:
                                            return res
                                return None

                            token = find_token(data)

                            # Log response for debugging if token not found
                            if not token:
                                _LOGGER.debug("Response data keys: %s", list(data.keys()) if isinstance(data, dict) else "Not a dict")
                                _LOGGER.debug("Response preview: %s", str(data)[:200] if data else "Empty response")

                            if token:
                                self._token = token
                                
                                # Try to extract endpoint ID from response
                                if not self._endpoint_id:
                                    def find_endpoint_id(obj):
                                        if isinstance(obj, dict):
                                            # endpoint or endpoints keys
                                            if "endpoint" in obj:
                                                endpoint_data = obj.get("endpoint")
                                                if isinstance(endpoint_data, list) and len(endpoint_data) > 0:
                                                    return endpoint_data[0].get("id") or endpoint_data[0].get("_id") or endpoint_data[0].get("endpoint")
                                                elif isinstance(endpoint_data, dict):
                                                    return endpoint_data.get("id") or endpoint_data.get("_id") or endpoint_data.get("endpoint")
                                            if "endpoints" in obj:
                                                endpoints = obj.get("endpoints")
                                                if isinstance(endpoints, list) and len(endpoints) > 0:
                                                    return endpoints[0].get("id") or endpoints[0].get("_id") or endpoints[0].get("endpoint")
                                            # nested data
                                            if "data" in obj and isinstance(obj["data"], (dict, list)):
                                                return find_endpoint_id(obj["data"])
                                            # try nested keys
                                            for v in obj.values():
                                                if isinstance(v, (dict, list)):
                                                    res = find_endpoint_id(v)
                                                    if res:
                                                        return res
                                        elif isinstance(obj, list):
                                            for item in obj:
                                                res = find_endpoint_id(item)
                                                if res:
                                                    return res
                                        return None

                                    found_id = find_endpoint_id(data)
                                    if found_id:
                                        self._endpoint_id = found_id

                                _LOGGER.info("Successfully logged in to COSA API")
                                return True
                            else:
                                _LOGGER.debug("Token not found in response from %s", endpoint)
                                continue
                        elif response.status == 401:
                            # Invalid credentials, don't try other formats
                            error_text = await response.text()
                            _LOGGER.error("Invalid credentials: %s", error_text)
                            raise CosaAPIError("Invalid username or password")
                        else:
                            error_text = await response.text()
                            _LOGGER.debug("Login response status %s from %s", response.status, url)
                            _LOGGER.debug(
                                "Login attempt failed with status %s: %s", response.status, error_text
                            )
                            last_error = f"Status {response.status}: {error_text}"
                            continue

                except aiohttp.ClientError as err:
                    _LOGGER.debug("Error connecting to %s: %s", endpoint, err)
                    last_error = f"Connection error: {err}"
                    continue
                except CosaAPIError:
                    # Re-raise authentication errors
                    raise
                except Exception as err:
                    _LOGGER.debug("Unexpected error during login: %s", err)
                    last_error = f"Unexpected error: {err}"
                    continue

        # If we get here, all login attempts failed
        raise CosaAPIError(f"Login failed. Last error: {last_error}")

    def _get_headers(self) -> Dict[str, str]:
        """Get headers for API requests."""
        if not self._token:
            raise CosaAPIError("Not authenticated. Please login first.")

        # API expects authtoken (lowercase) in headers based on working config
        # Some servers use authToken camelCase, some use authtoken lowercase; include both to be tolerant
        headers = {
            "authToken": self._token,
            "authtoken": self._token,
            "User-Agent": USER_AGENT,
            "Content-Type": CONTENT_TYPE,
        }
        return headers

    async def get_endpoint_status(self, endpoint_id: Optional[str] = None) -> Dict[str, Any]:
        """Get endpoint status."""
        endpoint = endpoint_id or self._endpoint_id
        if not endpoint:
            raise CosaAPIError("Endpoint ID is required")

        for attempt in range(self._retry_count):
            try:
                session = await self._get_session()
                url = f"{API_BASE_URL}{ENDPOINT_GET_ENDPOINT}"

                payload = {"endpoint": endpoint}
                headers = self._get_headers()

                async with session.post(url, json=payload, headers=headers) as response:
                    if response.status == 200:
                        data = await response.json()
                        # Normalize nested data - other integration style
                        if isinstance(data, dict):
                            if "endpoint" in data:
                                return data["endpoint"]
                            elif "data" in data and isinstance(data["data"], dict):
                                nested = data["data"]
                                if "endpoint" in nested:
                                    return nested["endpoint"]
                                else:
                                    return nested
                            else:
                                return data
                        return data
                    elif response.status == 401:
                        # Token expired, try to re-login
                        _LOGGER.warning("Token expired, attempting to re-login")
                        await self.login()
                        if attempt < self._retry_count - 1:
                            continue
                    else:
                        error_text = await response.text()
                        _LOGGER.error(
                            "Get endpoint status failed with status %s: %s",
                            response.status,
                            error_text,
                        )
                        if attempt < self._retry_count - 1:
                            continue
                        raise CosaAPIError(f"Get status failed: {response.status}")

            except aiohttp.ClientError as err:
                _LOGGER.error("Error getting endpoint status (attempt %d): %s", attempt + 1, err)
                if attempt < self._retry_count - 1:
                    continue
                raise CosaAPIError(f"Connection error: {err}") from err

        raise CosaAPIError("Failed to get endpoint status after retries")

    async def set_mode(
        self,
        mode: str,
        option: str,
        endpoint_id: Optional[str] = None,
    ) -> bool:
        """Set endpoint mode."""
        endpoint = endpoint_id or self._endpoint_id
        if not endpoint:
            raise CosaAPIError("Endpoint ID is required")

        try:
            session = await self._get_session()
            url = f"{API_BASE_URL}{ENDPOINT_SET_MODE}"

            payload = {
                "endpoint": endpoint,
                "mode": mode,
            }
            
            # Add option only if provided (for manual mode)
            if option:
                payload["option"] = option

            headers = self._get_headers()
            headers["provider"] = "cosa"
            headers["content-type"] = CONTENT_TYPE  # Ensure content-type is set

            async with session.post(url, json=payload, headers=headers) as response:
                if response.status == 200:
                    _LOGGER.info("Successfully set mode to %s%s", mode, f" with option {option}" if option else "")
                    return True
                else:
                    error_text = await response.text()
                    _LOGGER.error(
                        "Set mode failed with status %s: %s", response.status, error_text
                    )
                    raise CosaAPIError(f"Set mode failed: {response.status}")

        except aiohttp.ClientError as err:
            _LOGGER.error("Error setting mode: %s", err)
            raise CosaAPIError(f"Connection error: {err}") from err

    async def set_option(
        self,
        option: str,
        endpoint_id: Optional[str] = None,
    ) -> bool:
        """Set endpoint option."""
        endpoint = endpoint_id or self._endpoint_id
        if not endpoint:
            raise CosaAPIError("Endpoint ID is required")

        try:
            session = await self._get_session()
            url = f"{API_BASE_URL}/endpoints/setOption"

            payload = {
                "endpoint": endpoint,
                "option": option,
            }

            headers = self._get_headers()
            headers["provider"] = "cosa"

            async with session.post(url, json=payload, headers=headers) as response:
                if response.status == 200:
                    _LOGGER.info("Successfully set option to %s", option)
                    return True
                else:
                    error_text = await response.text()
                    _LOGGER.error(
                        "Set option failed with status %s: %s", response.status, error_text
                    )
                    raise CosaAPIError(f"Set option failed: {response.status}")

        except aiohttp.ClientError as err:
            _LOGGER.error("Error setting option: %s", err)
            raise CosaAPIError(f"Connection error: {err}") from err

    async def set_target_temperatures(
        self,
        home_temp: float,
        away_temp: float,
        sleep_temp: float,
        custom_temp: float,
        endpoint_id: Optional[str] = None,
    ) -> bool:
        """Set target temperatures."""
        endpoint = endpoint_id or self._endpoint_id
        if not endpoint:
            raise CosaAPIError("Endpoint ID is required")

        try:
            session = await self._get_session()
            url = f"{API_BASE_URL}{ENDPOINT_SET_TARGET_TEMPERATURES}"

            payload = {
                "endpoint": endpoint,
                "targetTemperatures": {
                    "home": home_temp,
                    "away": away_temp,
                    "sleep": sleep_temp,
                    "custom": custom_temp,
                },
            }

            headers = self._get_headers()
            headers["provider"] = "cosa"

            async with session.post(url, json=payload, headers=headers) as response:
                if response.status == 200:
                    _LOGGER.info("Successfully set target temperatures")
                    return True
                else:
                    error_text = await response.text()
                    _LOGGER.error(
                        "Set target temperatures failed with status %s: %s",
                        response.status,
                        error_text,
                    )
                    raise CosaAPIError(f"Set temperatures failed: {response.status}")

        except aiohttp.ClientError as err:
            _LOGGER.error("Error setting target temperatures: %s", err)
            raise CosaAPIError(f"Connection error: {err}") from err

    async def list_endpoints(self) -> list[Dict[str, Any]]:
        """List all endpoints for the user.

        This function tries multiple API endpoints and both GET/POST to maximize
        compatibility with different API versions.
        """
        if not self._token:
            await self.login()

        session = await self._get_session()
        possible_list_endpoints = [ENDPOINT_LIST_ENDPOINTS, "/endpoints/getEndpoints", "/endpoints/getEndpoints/"]
        headers = self._get_headers()

        last_error = None
        for list_endpoint in possible_list_endpoints:
            url = f"{API_BASE_URL}{list_endpoint}"

            # Try GET then POST
            for method in ("get", "post"):
                try:
                    _LOGGER.debug("Listing endpoints using %s %s", method.upper(), url)
                    if method == "get":
                        async with session.get(url, headers=headers) as response:
                            status = response.status
                            text = await response.text()
                            if status != 200:
                                # If 401 attempt login and retry once later
                                last_error = f"Status {status}: {text}"
                                if status == 401:
                                    break
                                continue
                            data = await response.json()
                    else:
                        async with session.post(url, json={}, headers=headers) as response:
                            status = response.status
                            text = await response.text()
                            if status != 200:
                                last_error = f"Status {status}: {text}"
                                if status == 401:
                                    break
                                continue
                            data = await response.json()

                    # Normalize response
                    if isinstance(data, list):
                        return data
                    if isinstance(data, dict) and "data" in data and isinstance(data["data"], (list, dict)):
                        nested = data["data"]
                        if isinstance(nested, list):
                            return nested
                        if isinstance(nested, dict):
                            if "endpoints" in nested:
                                endpoints = nested["endpoints"]
                                return endpoints if isinstance(endpoints, list) else [endpoints]
                            if "endpoint" in nested:
                                endpoint = nested["endpoint"]
                                return endpoint if isinstance(endpoint, list) else [endpoint]
                            return [nested]
                    if isinstance(data, dict):
                        if "endpoints" in data:
                            endpoints = data["endpoints"]
                            return endpoints if isinstance(endpoints, list) else [endpoints]
                        if "endpoint" in data:
                            endpoint = data["endpoint"]
                            return endpoint if isinstance(endpoint, list) else [endpoint]
                    # Unrecognized structure, continue to next method/endpoint
                    continue
                except CosaAPIError:
                    raise
                except aiohttp.ClientError as err:
                    _LOGGER.debug("Connection error on list_endpoints: %s", err)
                    last_error = str(err)
                    continue

        # If we get here, all attempts failed
        if last_error:
            # Authentication issue? try to re-login if possible
            if "401" in last_error or "invalid" in last_error.lower():
                _LOGGER.warning("Token expired or invalid while listing endpoints, attempting re-login")
                await self.login()
                # Try again with primary endpoint using POST
                try:
                    async with session.post(f"{API_BASE_URL}{ENDPOINT_GET_ENDPOINT}", json={}, headers=self._get_headers()) as retry_resp:
                        if retry_resp.status == 200:
                            data = await retry_resp.json()
                            if isinstance(data, list):
                                return data
                            if isinstance(data, dict) and "endpoints" in data:
                                return data["endpoints"] if isinstance(data["endpoints"], list) else [data["endpoints"]]
                except Exception:
                    pass
            raise CosaAPIError(f"Failed to list endpoints: {last_error}")

