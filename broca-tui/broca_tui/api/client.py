"""
Generic async HTTP client for Broca REST API.

Uses aiohttp for non-blocking HTTP requests.
"""

import json
from typing import Any, Dict, Optional

import aiohttp

from broca_tui.config import get_config


class APIClient:
    """Generic async HTTP client for the Broca REST API."""

    # Default timeout for HTTP requests (seconds)
    DEFAULT_TIMEOUT = 30

    def __init__(self, base_url: Optional[str] = None, timeout: Optional[int] = None):
        """Initialize API client.

        Args:
            base_url: Base URL for the REST API. Defaults to config value.
            timeout: Request timeout in seconds. Defaults to 30.
        """
        config = get_config()
        self._base_url = (base_url or config.api_server_url).rstrip("/") + "/api"
        self._timeout = aiohttp.ClientTimeout(total=timeout or self.DEFAULT_TIMEOUT)
        self._session: Optional[aiohttp.ClientSession] = None

    async def _get_session(self) -> aiohttp.ClientSession:
        """Get or create the aiohttp session."""
        if self._session is None or self._session.closed:
            self._session = aiohttp.ClientSession(
                headers={"Content-Type": "application/json"},
                timeout=self._timeout,
            )
        return self._session

    async def _request(
        self,
        method: str,
        path: str,
        params: Optional[Dict[str, Any]] = None,
        data: Optional[Any] = None,
    ) -> Any:
        """Make an HTTP request.

        Args:
            method: HTTP method (GET, POST, PUT, DELETE)
            path: API path (e.g., "/session/sessions")
            params: Query parameters
            data: Request body (will be JSON serialized)

        Returns:
            Parsed JSON response

        Raises:
            aiohttp.ClientError: On HTTP errors
        """
        session = await self._get_session()
        url = f"{self._base_url}{path}"

        kwargs: Dict[str, Any] = {}
        if params:
            kwargs["params"] = params
        if data is not None:
            kwargs["json"] = data

        async with session.request(method, url, **kwargs) as resp:
            if resp.status >= 400:
                error_text = await resp.text()
                if 400 <= resp.status < 500:
                    raise aiohttp.ClientResponseError(
                        resp.request_info, resp.history,
                        status=resp.status,
                        message=f"Client error {resp.status} for {method} {path}: {error_text}",
                        headers=resp.headers,
                    )
                else:
                    raise aiohttp.ClientResponseError(
                        resp.request_info, resp.history,
                        status=resp.status,
                        message=f"Server error {resp.status} for {method} {path}: {error_text}",
                        headers=resp.headers,
                    )
            if resp.status == 204:
                return None
            text = await resp.text()
            if text:
                try:
                    result = json.loads(text)
                    # Unwrap {code, msg, data} envelope from Broca REST API
                    if isinstance(result, dict) and "code" in result:
                        code = result.get("code", 200)
                        if code >= 400:
                            msg = result.get("msg", "Unknown API error")
                            raise aiohttp.ClientResponseError(
                                resp.request_info, resp.history,
                                status=code,
                                message=f"API error {code}: {msg}",
                                headers=resp.headers,
                            )
                        if "data" in result:
                            return result["data"]
                    return result
                except json.JSONDecodeError:
                    return text
            return None

    async def get(self, path: str, params: Optional[Dict[str, Any]] = None) -> Any:
        """GET request."""
        return await self._request("GET", path, params=params)

    async def post(self, path: str, data: Optional[Any] = None) -> Any:
        """POST request."""
        return await self._request("POST", path, data=data)

    async def put(self, path: str, data: Optional[Any] = None) -> Any:
        """PUT request."""
        return await self._request("PUT", path, data=data)

    async def delete(self, path: str, data: Optional[Any] = None) -> Any:
        """DELETE request."""
        return await self._request("DELETE", path, data=data)

    async def close(self):
        """Close the aiohttp session."""
        if self._session and not self._session.closed:
            await self._session.close()

    async def __aenter__(self):
        return self

    async def __aexit__(self, *args):
        await self.close()
