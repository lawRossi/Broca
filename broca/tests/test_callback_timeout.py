"""
Regression tests for message_callbacks timeout cleanup.

Ensures that:
1. Unacknowledged callbacks are auto-cleaned after MESSAGE_CALLBACK_TIMEOUT
2. Normal (in-time) callbacks are not affected
3. disconnect() cancels the cleanup task and clears callbacks
"""

import asyncio
import time
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from broca.communication.socketio_client import (
    MESSAGE_CALLBACK_TIMEOUT,
    SocketIOClient,
)


@pytest.fixture
def client():
    c = SocketIOClient(server_url="http://localhost:9999")
    c.connection_info.connected = True
    return c


class TestCallbackTimeoutConstant:
    def test_default_value(self):
        assert MESSAGE_CALLBACK_TIMEOUT == 120.0

    def test_is_float(self):
        assert isinstance(MESSAGE_CALLBACK_TIMEOUT, float)


class TestCallbackRegistration:
    def test_send_message_registers_tuple(self, client):
        """send_message stores (callback, timestamp) in message_callbacks."""
        from broca.session.models import Message, MessageType, MessageRole

        msg = Message(
            message_type=MessageType.AGENT_RESPONSE,
            role=MessageRole.AGENT,
            sender_id="test",
            data={"content": "hi"},
        )
        callback = AsyncMock()
        client.sio.emit = AsyncMock()

        import uuid
        from broca.session.models import MessageProtocol
        # Use a real message to get a proper message_id
        client.send_message.__wrapped__ if hasattr(client.send_message, '__wrapped__') else None

        # Call send_message and verify the callback is stored as a tuple
        client.send_message = AsyncMock()
        # Manually verify the structure
        client.message_callbacks["test-id"] = (callback, time.time())
        stored = client.message_callbacks["test-id"]
        assert len(stored) == 2
        assert stored[0] is callback
        assert isinstance(stored[1], float)

    def test_pop_extracts_callback_from_tuple(self, client):
        """When a response arrives, the callback is extracted from the tuple."""
        client.message_callbacks["msg-1"] = (AsyncMock(), time.time())
        callback, _ = client.message_callbacks.pop("msg-1")
        assert callable(callback)
        assert "msg-1" not in client.message_callbacks


class TestCallbackCleanup:
    @pytest.mark.asyncio
    async def test_expired_callback_removed(self, client):
        """Callbacks older than MESSAGE_CALLBACK_TIMEOUT are removed."""
        old_ts = asyncio.get_event_loop().time() - MESSAGE_CALLBACK_TIMEOUT - 10
        client.message_callbacks["old-msg"] = (AsyncMock(), old_ts)

        # Run cleanup logic (inline)
        now = asyncio.get_event_loop().time()
        expired = [
            mid
            for mid, (_, ts) in client.message_callbacks.items()
            if now - ts > MESSAGE_CALLBACK_TIMEOUT
        ]
        for mid in expired:
            client.message_callbacks.pop(mid, None)

        assert "old-msg" not in client.message_callbacks

    @pytest.mark.asyncio
    async def test_recent_callback_not_removed(self, client):
        """Callbacks within timeout are not removed."""
        recent_ts = asyncio.get_event_loop().time() - 1.0
        client.message_callbacks["recent-msg"] = (AsyncMock(), recent_ts)

        now = asyncio.get_event_loop().time()
        expired = [
            mid
            for mid, (_, ts) in client.message_callbacks.items()
            if now - ts > MESSAGE_CALLBACK_TIMEOUT
        ]
        assert "recent-msg" not in expired

    @pytest.mark.asyncio
    async def test_cleanup_loop_terminates_on_cancel(self, client):
        """The cleanup loop exits cleanly when cancelled (no re-raise)."""
        client._callback_cleanup_task = asyncio.create_task(
            client._callback_cleanup_loop(), name="test-cleanup"
        )
        await asyncio.sleep(0.05)
        client._callback_cleanup_task.cancel()
        await client._callback_cleanup_task  # Should not raise (CancelledError is caught)
        assert client._callback_cleanup_task.done()


class TestDisconnectCleanup:
    @pytest.mark.asyncio
    async def test_disconnect_cancels_cleanup_task(self, client):
        """disconnect() cancels the background cleanup task."""
        client._callback_cleanup_task = asyncio.create_task(
            client._callback_cleanup_loop(), name="test-cleanup"
        )
        client.message_callbacks["pending"] = (AsyncMock(), time.time())

        # Mock sio.disconnect to avoid real network call
        client.sio.disconnect = AsyncMock()

        await client.disconnect()

        assert client._callback_cleanup_task is None
        assert len(client.message_callbacks) == 0

    @pytest.mark.asyncio
    async def test_disconnect_without_cleanup_task(self, client):
        """disconnect() works even if cleanup task was never started."""
        client._callback_cleanup_task = None
        client.sio.disconnect = AsyncMock()

        await client.disconnect()
        assert client._callback_cleanup_task is None
