"""
Regression tests for unified exception types in send_message/subscribe/unsubscribe.

Ensures that:
1. send_message() raises CommunicationError when all retries fail
2. subscribe() raises CommunicationError when emit fails
3. unsubscribe() raises CommunicationError when emit fails
4. CommunicationError can catch all failure paths
"""

import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from broca.communication.socketio_client import SocketIOClient
from broca.errors import CommunicationError
from broca.session.models import Message, MessageProtocol, MessageRole, MessageType


@pytest.fixture
def client():
    c = SocketIOClient(server_url="http://localhost:9999")
    c.connection_info.connected = True
    c.sio.emit = AsyncMock()
    return c


def _make_message():
    return Message(
        message_type=MessageType.AGENT_RESPONSE,
        role=MessageRole.AGENT,
        sender_id="test-agent",
        data={"content": "hello"},
    )


class TestSendMessageExceptionUnification:
    """send_message() must raise CommunicationError on all failure paths."""

    @pytest.mark.asyncio
    async def test_not_connected_raises_communication_error(self, client):
        """When not connected and no reconnect, raises CommunicationError."""
        client.connection_info.connected = False
        client.auto_reconnect = False

        msg = _make_message()
        with pytest.raises(CommunicationError, match="Not connected"):
            await client.send_message(msg, retry_on_disconnect=False)

    @pytest.mark.asyncio
    async def test_retries_exhausted_raises_communication_error(self, client):
        """After max retries, raises CommunicationError (not raw Exception)."""
        client.sio.emit = AsyncMock(side_effect=OSError("network error"))

        msg = _make_message()
        with pytest.raises(CommunicationError, match="Failed to send message"):
            await client.send_message(msg, retry_on_disconnect=False)

    @pytest.mark.asyncio
    async def test_retries_exhausted_preserves_cause(self, client):
        """CommunicationError preserves the original exception as __cause__."""
        client.sio.emit = AsyncMock(side_effect=OSError("network error"))

        msg = _make_message()
        with pytest.raises(CommunicationError) as exc_info:
            await client.send_message(msg, retry_on_disconnect=False)

        assert exc_info.value.__cause__ is not None
        assert isinstance(exc_info.value.__cause__, OSError)

    @pytest.mark.asyncio
    async def test_successful_send_returns_message_id(self, client):
        """Successful send returns message_id (no exception)."""
        client.sio.emit = AsyncMock(return_value=None)

        msg = _make_message()
        result = await client.send_message(msg, retry_on_disconnect=False)
        assert result == msg.message_id

    @pytest.mark.asyncio
    async def test_retry_succeeds_on_second_attempt(self, client):
        """If first attempt fails but second succeeds, no exception raised."""
        client.sio.emit = AsyncMock(
            side_effect=[OSError("first fail"), None]
        )

        msg = _make_message()
        result = await client.send_message(msg, retry_on_disconnect=False)
        assert result == msg.message_id
        assert client.sio.emit.call_count == 2


class TestSubscribeExceptionUnification:
    """subscribe() must raise CommunicationError on emit failure."""

    @pytest.mark.asyncio
    async def test_subscribe_not_connected(self, client):
        """Not connected raises CommunicationError."""
        client.connection_info.connected = False

        with pytest.raises(CommunicationError, match="Not connected"):
            await client.subscribe("session_123")

    @pytest.mark.asyncio
    async def test_subscribe_emit_failure_raises_communication_error(self, client):
        """Emit failure wraps in CommunicationError."""
        client.sio.emit = AsyncMock(side_effect=RuntimeError("socket broken"))

        with pytest.raises(CommunicationError, match="Failed to subscribe"):
            await client.subscribe("session_123")

    @pytest.mark.asyncio
    async def test_subscribe_communication_error_passthrough(self, client):
        """CommunicationError is not double-wrapped."""
        client.sio.emit = AsyncMock(
            side_effect=CommunicationError("already wrapped")
        )

        with pytest.raises(CommunicationError, match="already wrapped"):
            await client.subscribe("session_123")

    @pytest.mark.asyncio
    async def test_subscribe_success(self, client):
        """Successful subscribe returns message_id."""
        client.sio.emit = AsyncMock(return_value=None)

        result = await client.subscribe("session_123")
        assert isinstance(result, str)


class TestUnsubscribeExceptionUnification:
    """unsubscribe() must raise CommunicationError on emit failure."""

    @pytest.mark.asyncio
    async def test_unsubscribe_not_connected(self, client):
        """Not connected raises CommunicationError."""
        client.connection_info.connected = False

        with pytest.raises(CommunicationError, match="Not connected"):
            await client.unsubscribe("session_123")

    @pytest.mark.asyncio
    async def test_unsubscribe_emit_failure_raises_communication_error(self, client):
        """Emit failure wraps in CommunicationError."""
        client.sio.emit = AsyncMock(side_effect=RuntimeError("socket broken"))

        with pytest.raises(CommunicationError, match="Failed to unsubscribe"):
            await client.unsubscribe("session_123")

    @pytest.mark.asyncio
    async def test_unsubscribe_communication_error_passthrough(self, client):
        """CommunicationError is not double-wrapped."""
        client.sio.emit = AsyncMock(
            side_effect=CommunicationError("already wrapped")
        )

        with pytest.raises(CommunicationError, match="already wrapped"):
            await client.unsubscribe("session_123")

    @pytest.mark.asyncio
    async def test_unsubscribe_success(self, client):
        """Successful unsubscribe returns message_id."""
        client.sio.emit = AsyncMock(return_value=None)

        result = await client.unsubscribe("session_123")
        assert isinstance(result, str)
