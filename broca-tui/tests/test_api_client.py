"""
Tests for broca_tui.api.client module.

Covers:
- Request URL construction
- HTTP method dispatch (GET/POST/PUT/DELETE)
- Error handling (4xx vs 5xx)
- Timeout configuration
"""

import json
from unittest.mock import AsyncMock, MagicMock, patch

import aiohttp
import pytest

from broca_tui.api.client import APIClient


class _AsyncContextManagerMock:
    """Helper to create async context managers for mocking."""

    def __init__(self, response):
        self._response = response

    async def __aenter__(self):
        return self._response

    async def __aexit__(self, *args):
        pass


class MockResponse:
    """Mock aiohttp response for testing."""

    def __init__(self, status=200, text_data="{}"):
        self.status = status
        self._text_data = text_data
        self.headers = {"Content-Type": "application/json"}
        self.request_info = MagicMock()
        self.history = None

    async def text(self):
        return self._text_data

    async def __aenter__(self):
        return self

    async def __aexit__(self, *args):
        pass


def _make_mock_session():
    """Create a properly configured mock aiohttp session."""
    session = AsyncMock(spec=aiohttp.ClientSession)
    session.closed = False
    session.close = AsyncMock()
    return session


def _make_request_mock(mock_session, response):
    """Configure session.request to return an async context manager yielding response."""
    mock_session.request.return_value = _AsyncContextManagerMock(response)


class TestAPIClient:
    """Test APIClient base functionality."""

    @pytest.fixture
    def client(self):
        return APIClient(base_url="http://test:9000")

    @pytest.mark.asyncio
    async def test_url_construction(self, client):
        """Test that URLs are correctly constructed."""
        mock_session = _make_mock_session()
        _make_request_mock(mock_session, MockResponse())

        with patch.object(client, '_get_session', return_value=mock_session):
            await client.get("/session/sessions", params={"skip": 0, "limit": 10})

            # Verify the request was made to the correct URL
            mock_session.request.assert_called_once()
            call_args = mock_session.request.call_args
            assert call_args[0][0] == "GET"  # method
            assert "http://test:9000/api/session/sessions" in call_args[0][1]  # url
            # Verify params
            assert call_args[1]["params"] == {"skip": 0, "limit": 10}

    @pytest.mark.asyncio
    async def test_get_method(self, client):
        """Test GET request dispatch."""
        mock_session = _make_mock_session()
        _make_request_mock(mock_session, MockResponse(text_data=json.dumps({"key": "value"})))

        with patch.object(client, '_get_session', return_value=mock_session):
            result = await client.get("/test")
            assert result == {"key": "value"}
            mock_session.request.assert_called_once()
            assert mock_session.request.call_args[0][0] == "GET"

    @pytest.mark.asyncio
    async def test_post_method(self, client):
        """Test POST request dispatch."""
        mock_session = _make_mock_session()
        _make_request_mock(mock_session, MockResponse(text_data=json.dumps({"id": "42"})))

        with patch.object(client, '_get_session', return_value=mock_session):
            result = await client.post("/test", data={"name": "test"})
            assert result == {"id": "42"}
            assert mock_session.request.call_args[0][0] == "POST"
            assert mock_session.request.call_args[1]["json"] == {"name": "test"}

    @pytest.mark.asyncio
    async def test_put_method(self, client):
        """Test PUT request dispatch."""
        mock_session = _make_mock_session()
        _make_request_mock(mock_session, MockResponse())

        with patch.object(client, '_get_session', return_value=mock_session):
            await client.put("/test/1", data={"name": "updated"})
            assert mock_session.request.call_args[0][0] == "PUT"

    @pytest.mark.asyncio
    async def test_delete_method(self, client):
        """Test DELETE request dispatch."""
        mock_session = _make_mock_session()
        _make_request_mock(mock_session, MockResponse(status=204))

        with patch.object(client, '_get_session', return_value=mock_session):
            result = await client.delete("/test/1")
            assert result is None
            assert mock_session.request.call_args[0][0] == "DELETE"

    @pytest.mark.asyncio
    async def test_empty_response_body(self, client):
        """Test handling of empty response body."""
        mock_session = _make_mock_session()
        _make_request_mock(mock_session, MockResponse(status=200, text_data=""))

        with patch.object(client, '_get_session', return_value=mock_session):
            result = await client.get("/test")
            assert result is None

    @pytest.mark.asyncio
    async def test_204_no_content(self, client):
        """Test handling of 204 No Content."""
        mock_session = _make_mock_session()
        _make_request_mock(mock_session, MockResponse(status=204))

        with patch.object(client, '_get_session', return_value=mock_session):
            result = await client.delete("/test")
            assert result is None

    @pytest.mark.asyncio
    async def test_404_client_error(self, client):
        """Test that 4xx errors raise ClientResponseError."""
        mock_session = _make_mock_session()
        error_resp = MockResponse(status=404, text_data='{"detail": "Not found"}')
        _make_request_mock(mock_session, error_resp)

        with patch.object(client, '_get_session', return_value=mock_session):
            with pytest.raises(aiohttp.ClientResponseError) as exc_info:
                await client.get("/session/nonexistent")
            assert exc_info.value.status == 404
            assert "Client error" in str(exc_info.value.message)

    @pytest.mark.asyncio
    async def test_500_server_error(self, client):
        """Test that 5xx errors raise ClientResponseError."""
        mock_session = _make_mock_session()
        error_resp = MockResponse(status=500, text_data='Internal server error')
        _make_request_mock(mock_session, error_resp)

        with patch.object(client, '_get_session', return_value=mock_session):
            with pytest.raises(aiohttp.ClientResponseError) as exc_info:
                await client.get("/session/error")
            assert exc_info.value.status == 500
            assert "Server error" in str(exc_info.value.message)


class TestAPIClientTimeout:
    """Test APIClient timeout configuration."""

    def test_default_timeout(self):
        """Test default timeout value."""
        client = APIClient(base_url="http://test:9000")
        assert client._timeout.total == 30

    def test_custom_timeout(self):
        """Test custom timeout value."""
        client = APIClient(base_url="http://test:9000", timeout=60)
        assert client._timeout.total == 60

    def test_zero_timeout(self):
        """Test setting timeout to None uses default."""
        client = APIClient(base_url="http://test:9000", timeout=None)
        assert client._timeout.total == 30


class TestAPIClientSessionManagement:
    """Test APIClient session lifecycle."""

    @pytest.mark.asyncio
    async def test_session_created_on_first_request(self):
        """Test that session is lazily created."""
        client = APIClient(base_url="http://test:9000")
        assert client._session is None

        mock_session = _make_mock_session()

        with patch('aiohttp.ClientSession', return_value=mock_session):
            session = await client._get_session()
            assert session is not None
            # Second call returns same session
            session2 = await client._get_session()
            assert session2 is session

    @pytest.mark.asyncio
    async def test_close_cleans_up_session(self):
        """Test that close() properly cleans up."""
        client = APIClient(base_url="http://test:9000")
        mock_session = _make_mock_session()

        client._session = mock_session
        await client.close()
        mock_session.close.assert_called_once()


class TestAPIClientEnvelope:
    """Test API response envelope {code, msg, data} unwrapping."""

    @pytest.mark.asyncio
    async def test_unwraps_envelope_success(self):
        """Test that {code: 200, data: ...} returns data."""
        client = APIClient(base_url="http://test:9000")
        mock_session = _make_mock_session()
        _make_request_mock(mock_session, MockResponse(
            text_data=json.dumps({"code": 200, "msg": "ok", "data": {"sessions": [], "total": 0}})
        ))

        with patch.object(client, '_get_session', return_value=mock_session):
            result = await client.get("/test")
            assert result == {"sessions": [], "total": 0}

    @pytest.mark.asyncio
    async def test_unwraps_envelope_list_data(self):
        """Test that {code: 200, data: [...]} returns the list."""
        client = APIClient(base_url="http://test:9000")
        mock_session = _make_mock_session()
        _make_request_mock(mock_session, MockResponse(
            text_data=json.dumps({"code": 200, "msg": "", "data": [{"id": 1}]})
        ))

        with patch.object(client, '_get_session', return_value=mock_session):
            result = await client.get("/test")
            assert result == [{"id": 1}]

    @pytest.mark.asyncio
    async def test_passes_through_plain_response(self):
        """Test that non-envelope responses pass through unchanged."""
        client = APIClient(base_url="http://test:9000")
        mock_session = _make_mock_session()
        _make_request_mock(mock_session, MockResponse(
            text_data=json.dumps({"plain": "response"})
        ))

        with patch.object(client, '_get_session', return_value=mock_session):
            result = await client.get("/test")
            assert result == {"plain": "response"}

    @pytest.mark.asyncio
    async def test_envelope_api_error(self):
        """Test that {code: 400, msg: ...} raises an error."""
        client = APIClient(base_url="http://test:9000")
        mock_session = _make_mock_session()
        _make_request_mock(mock_session, MockResponse(
            status=200,  # HTTP status is 200 but API code is 400
            text_data=json.dumps({"code": 400, "msg": "Bad request"}),
        ))

        with patch.object(client, '_get_session', return_value=mock_session):
            with pytest.raises(aiohttp.ClientResponseError) as exc_info:
                await client.get("/test")
            assert "API error 400" in str(exc_info.value.message)

