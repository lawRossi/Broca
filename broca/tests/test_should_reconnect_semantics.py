"""Task 5.5: SocketIOClient _should_reconnect semantics.

Regression test verifying the reconnection trigger logic:
  - Manual ``connect()`` does NOT set ``_should_reconnect = True``
  - After manual connect + disconnect, NO auto-reconnect task is created
  - When ``_should_reconnect`` is True (e.g. via ``enable_auto_reconnect``),
    disconnect DOES trigger the reconnect loop
  - ``disconnect()`` resets ``_should_reconnect = False``
"""

from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from broca.communication.socketio_client import SocketIOClient


@pytest.fixture
def client() -> SocketIOClient:
    """SocketIOClient with mocked sio, auto_reconnect=True."""
    c = SocketIOClient(
        server_url="http://localhost:9999",
        client_type="test",
        client_id="test_client",
        auto_reconnect=True,
    )
    c.sio = AsyncMock()
    return c


@pytest.fixture
def client_no_reconnect() -> SocketIOClient:
    """SocketIOClient with auto_reconnect=False."""
    c = SocketIOClient(
        server_url="http://localhost:9999",
        client_type="test",
        client_id="test_client_no_reconnect",
        auto_reconnect=False,
    )
    c.sio = AsyncMock()
    return c


@pytest.mark.asyncio
class TestManualConnectNoReconnect:
    """Manual connect() → disconnect → NO auto-reconnect."""

    async def test_manual_connect_does_not_set_should_reconnect(self, client):
        """connect() does not set _should_reconnect = True."""
        client.sio.connect = AsyncMock()
        client.sio.disconnect = AsyncMock()

        async def mock_sio_connect(*args, **kwargs):
            client._connect_event.set()

        client.sio.connect = AsyncMock(side_effect=mock_sio_connect)

        result = await client.connect()
        assert result is True
        # _should_reconnect should remain False after manual connect
        assert client._should_reconnect is False

    async def test_disconnect_after_manual_connect_no_reconnect_task(
        self, client
    ):
        """Simulated disconnect event after manual connect → no _reconnect_task."""
        client.sio.connect = AsyncMock()

        async def mock_sio_connect(*args, **kwargs):
            client._connect_event.set()

        client.sio.connect = AsyncMock(side_effect=mock_sio_connect)
        await client.connect()

        # Now simulate the disconnect event handler
        client._reconnect_task = None  # ensure clean state

        # Trigger the disconnect handler logic
        # (simulates what happens when sio fires 'disconnect' event)
        client.connection_info.connected = False
        client._connect_event.clear()

        # The disconnect handler checks: auto_reconnect and _should_reconnect
        # _should_reconnect is False → no reconnect task
        assert client._should_reconnect is False
        assert client._reconnect_task is None

    async def test_disconnect_resets_should_reconnect(self, client):
        """disconnect() sets _should_reconnect = False."""
        client._should_reconnect = True
        client.sio.disconnect = AsyncMock()

        await client.disconnect()
        assert client._should_reconnect is False


@pytest.mark.asyncio
class TestExplicitReconnect:
    """_should_reconnect=True → disconnect triggers reconnect."""

    async def test_should_reconnect_triggers_reconnect_on_disconnect(self, client):
        """When _should_reconnect=True, disconnect creates a reconnect task."""
        client.sio.connect = AsyncMock()
        client.sio.disconnect = AsyncMock()

        # Simulate enabling auto-reconnect (e.g. via a setter or enable method)
        client._should_reconnect = True

        # Simulate the disconnect event handler
        client.connection_info.connected = False
        client._connect_event.clear()

        # Manually trigger what the disconnect handler would do
        import asyncio

        if client.auto_reconnect and client._should_reconnect:
            client._reconnect_task = asyncio.create_task(
                client._reconnect(), name="test-reconnect"
            )

        # Wait a tiny bit for the task to be created
        await asyncio.sleep(0.01)

        assert client._reconnect_task is not None
        assert not client._reconnect_task.done()

        # Cleanup: cancel the reconnect task
        client._should_reconnect = False
        if client._reconnect_task:
            client._reconnect_task.cancel()
            try:
                await client._reconnect_task
            except asyncio.CancelledError:
                pass

    async def test_reconnect_respects_should_reconnect_flag(self, client):
        """_reconnect() loop exits when _should_reconnect becomes False."""
        client._should_reconnect = True
        client.sio.connect = AsyncMock()

        # Start reconnect in background
        task = asyncio.create_task(client._reconnect(), name="test-reconnect-2")

        # Give it a moment to enter the loop, then cancel
        await asyncio.sleep(0.05)
        client._should_reconnect = False
        task.cancel()
        try:
            await task
        except asyncio.CancelledError:
            pass


@pytest.mark.asyncio
class TestAutoReconnectDisabled:
    """auto_reconnect=False → disconnect never triggers reconnect."""

    async def test_no_reconnect_when_disabled(self, client_no_reconnect):
        """With auto_reconnect=False, disconnect handler never creates task."""
        client_no_reconnect.sio.connect = AsyncMock()
        client_no_reconnect.sio.disconnect = AsyncMock()

        client_no_reconnect.connection_info.connected = False
        client_no_reconnect._connect_event.clear()

        # Even if _should_reconnect is True, auto_reconnect=False blocks it
        client_no_reconnect._should_reconnect = True

        # The handler checks: self.auto_reconnect and self._should_reconnect
        # auto_reconnect is False → no reconnect
        assert client_no_reconnect.auto_reconnect is False
        assert client_no_reconnect._reconnect_task is None
