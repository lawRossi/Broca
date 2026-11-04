"""
Regression tests for SocketIOClient.connect() unified exception handling.

Bug: Previously `connect()` raised `CommunicationError` on timeout but returned
False for other exceptions. This inconsistency could crash `Agent.start()`.
Fix: All failure paths now return False uniformly.
"""

import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from broca.communication.socketio_client import SocketIOClient


@pytest.fixture
def client():
    """Create a SocketIOClient with mocked sio."""
    c = SocketIOClient(
        server_url="http://localhost:9999",
        client_type="test",
        client_id="test_client",
    )
    c.sio = AsyncMock()
    return c


@pytest.mark.asyncio
class TestConnectReturnsFalse:
    """connect() should return False (not raise) on all failure paths."""

    async def test_timeout_returns_false(self, client):
        """Connection timeout → return False, not raise."""
        client.sio.connect = AsyncMock()
        # Make _connect_event.wait() time out
        client._connect_event = asyncio.Event()  # not set

        result = await client.connect(timeout=0.01)
        assert result is False

    async def test_connection_refused_returns_false(self, client):
        """Network exception (ConnectionRefusedError) → return False."""
        client.sio.connect = AsyncMock(
            side_effect=ConnectionRefusedError("Connection refused")
        )

        result = await client.connect()
        assert result is False

    async def test_dns_error_returns_false(self, client):
        """DNS resolution failure → return False."""
        client.sio.connect = AsyncMock(
            side_effect=OSError("Name or service not known")
        )

        result = await client.connect()
        assert result is False

    async def test_generic_exception_returns_false(self, client):
        """Any other exception → return False."""
        client.sio.connect = AsyncMock(side_effect=RuntimeError("unexpected"))

        result = await client.connect()
        assert result is False


@pytest.mark.asyncio
class TestConnectReturnsTrue:
    """connect() should return True on success."""

    async def test_successful_connect(self, client):
        """Normal connection → return True."""
        client.sio.connect = AsyncMock()
        client.sio.disconnect = AsyncMock()

        # Simulate the connect event being set after sio.connect
        async def mock_connect(*args, **kwargs):
            # Set the event to simulate successful connection
            client._connect_event.set()

        client.sio.connect = AsyncMock(side_effect=mock_connect)

        result = await client.connect(timeout=5.0)
        assert result is True

    async def test_already_connected_returns_true(self, client):
        """If already connected, immediately return True."""
        client.connection_info.connected = True

        result = await client.connect()
        assert result is True
        # sio.connect should not be called
        client.sio.connect.assert_not_called()


@pytest.mark.asyncio
class TestConnectNoRaise:
    """Verify no exception propagates from connect()."""

    async def test_timeout_does_not_raise(self, client):
        """Regression: timeout must NOT raise CommunicationError."""
        from broca.errors import CommunicationError

        client.sio.connect = AsyncMock()
        client._connect_event = asyncio.Event()  # never set

        # Should return False, not raise
        try:
            result = await client.connect(timeout=0.01)
        except CommunicationError:
            pytest.fail("connect() should not raise CommunicationError on timeout")
        assert result is False

    async def test_network_error_does_not_raise(self, client):
        """Regression: network errors must NOT raise."""
        client.sio.connect = AsyncMock(
            side_effect=ConnectionRefusedError("refused")
        )

        # Should return False, not raise
        try:
            result = await client.connect()
        except Exception:
            pytest.fail("connect() should not raise on network errors")
        assert result is False


@pytest.mark.asyncio
class TestConnectCleanup:
    """Verify cleanup behavior on failed connections."""

    async def test_disconnect_called_on_timeout(self, client):
        """On timeout, sio.disconnect() should be attempted."""
        client.sio.connect = AsyncMock()
        client.sio.disconnect = AsyncMock()
        client._connect_event = asyncio.Event()  # never set

        await client.connect(timeout=0.01)

        client.sio.disconnect.assert_called_once()

    async def test_reconnect_task_created_on_error_if_enabled(self, client):
        """If auto_reconnect=True, a reconnect task is created on network error."""
        client.auto_reconnect = True
        client.sio.connect = AsyncMock(
            side_effect=ConnectionRefusedError("refused")
        )

        await client.connect()

        assert client._reconnect_task is not None
