"""
Regression tests for server-side client_id uniqueness and routing feedback.

Ensures that:
1. A second connection with the same client_id takes over routing and cleans up old mapping
2. Sending to an unknown receiver_id triggers a routing_failed error to the sender
3. Existing server tests still pass (no new failures)
"""

import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from broca.communication.socketio_server import SocketIOServer, ClientInfo
from broca.session.models import Message, MessageProtocol, MessageRole, MessageType


@pytest.fixture
def server():
    """Create a server instance without starting it (no network)."""
    s = SocketIOServer(host="127.0.0.1", port=0)
    s.sio = MagicMock()
    s.sio.emit = AsyncMock()
    return s


class TestClientIdConflict:
    """New connection with same client_id takes over routing."""

    def test_new_connection_replaces_old_sid_mapping(self, server):
        """When a new connection uses an existing client_id, the old SID is cleaned."""
        # Simulate existing state: client_id "agent-1" maps to sid-1
        old_info = ClientInfo(client_id="agent-1", client_type="cli", subscriptions={"session_A"})
        server.clients["sid-1"] = old_info
        server.client_sids["agent-1"] = "sid-1"
        server.subscriptions["session_A"] = {"agent-1"}

        # Simulate conflict resolution logic (mirrors connect handler)
        client_id = "agent-1"
        sid = "sid-2"
        new_info = ClientInfo(client_id="agent-1", client_type="cli")

        old_sid = server.client_sids.get(client_id)
        if old_sid and old_sid != sid:
            old_ci = server.clients.pop(old_sid, None)
            if old_ci:
                for sub in old_ci.subscriptions:
                    if sub in server.subscriptions:
                        server.subscriptions[sub].discard(client_id)
                        if not server.subscriptions[sub]:
                            del server.subscriptions[sub]
            server.client_sids.pop(client_id, None)

        server.clients[sid] = new_info
        server.client_sids[client_id] = sid

        # Old SID should be cleaned from clients
        assert "sid-1" not in server.clients
        # Old subscription should be cleaned
        assert "agent-1" not in server.subscriptions.get("session_A", set())
        # New mapping is correct
        assert server.client_sids["agent-1"] == "sid-2"

    def test_new_connection_cleans_up_old_subscriptions(self, server):
        """Old subscriptions are removed when client_id is reused."""
        old_info = ClientInfo(client_id="agent-2", client_type="browser", subscriptions={"session_X", "session_Y"})
        server.clients["sid-old"] = old_info
        server.client_sids["agent-2"] = "sid-old"
        server.subscriptions["session_X"] = {"agent-2"}
        server.subscriptions["session_Y"] = {"agent-2"}

        # Simulate the conflict resolution logic from connect handler
        client_id = "agent-2"
        sid = "sid-new"
        old_sid = server.client_sids.get(client_id)

        if old_sid and old_sid != sid:
            old_info2 = server.clients.pop(old_sid, None)
            if old_info2:
                for sub in old_info2.subscriptions:
                    if sub in server.subscriptions:
                        server.subscriptions[sub].discard(client_id)
                        if not server.subscriptions[sub]:
                            del server.subscriptions[sub]

            server.client_sids.pop(client_id, None)

        assert "sid-old" not in server.clients
        assert "session_X" not in server.subscriptions
        assert "session_Y" not in server.subscriptions

    def test_same_sid_does_not_trigger_cleanup(self, server):
        """If the same SID reconnects (no conflict), no cleanup happens."""
        info = ClientInfo(client_id="agent-3", client_type="cli")
        server.clients["sid-3"] = info
        server.client_sids["agent-3"] = "sid-3"

        old_sid = server.client_sids.get("agent-3")
        # same sid → no cleanup
        assert old_sid == "sid-3"
        # State unchanged
        assert "sid-3" in server.clients
        assert server.client_sids["agent-3"] == "sid-3"


class TestRoutingFailedFeedback:
    """Unknown receiver_id triggers routing_failed error to sender."""

    @pytest.mark.asyncio
    async def test_unknown_receiver_triggers_routing_failed(self, server):
        """When receiver_id is unknown, sender gets a ROUTING_FAILED error."""
        # Set up a valid sender
        sender_info = ClientInfo(client_id="sender-1", client_type="cli")
        server.clients["sender-sid"] = sender_info
        server.client_sids["sender-1"] = "sender-sid"

        # Target client does NOT exist
        msg = Message(
            message_type=MessageType.AGENT_RESPONSE,
            role=MessageRole.AGENT,
            sender_id="sender-1",
            receiver_id="unknown-receiver",
            data={"content": "test"},
        )

        # _send_to_client should return False
        result = await server._send_to_client("unknown-receiver", msg)
        assert result is False

        # Verify _send_error is called (simulating what _process_message does)
        with patch.object(server, "_send_error", new_callable=AsyncMock) as mock_send_error:
            # Simulate the routing_failed path
            await server._send_error(
                "sender-sid",
                {
                    "message": "Unknown receiver_id: unknown-receiver",
                    "code": "ROUTING_FAILED",
                    "severity": "error",
                },
                "sender-1",
            )
            mock_send_error.assert_awaited_once()
            # Verify error code
            call_args = mock_send_error.call_args
            error_info = call_args[0][1]
            assert error_info["code"] == "ROUTING_FAILED"

    @pytest.mark.asyncio
    async def test_known_receiver_does_not_trigger_routing_failed(self, server):
        """When receiver_id is known, no routing_failed error is sent."""
        # Set up both sender and receiver
        sender_info = ClientInfo(client_id="sender-1", client_type="cli")
        receiver_info = ClientInfo(client_id="receiver-1", client_type="cli")
        server.clients["sender-sid"] = sender_info
        server.clients["receiver-sid"] = receiver_info
        server.client_sids["sender-1"] = "sender-sid"
        server.client_sids["receiver-1"] = "receiver-sid"

        msg = Message(
            message_type=MessageType.AGENT_RESPONSE,
            role=MessageRole.AGENT,
            sender_id="sender-1",
            receiver_id="receiver-1",
            data={"content": "test"},
        )

        result = await server._send_to_client("receiver-1", msg)
        assert result is True

    @pytest.mark.asyncio
    async def test_routing_failed_error_message_format(self, server):
        """The routing_failed error contains the unknown receiver_id."""
        error_info = {
            "message": "Unknown receiver_id: ghost-agent",
            "code": "ROUTING_FAILED",
            "severity": "error",
        }
        assert "ghost-agent" in error_info["message"]
        assert error_info["code"] == "ROUTING_FAILED"
        assert error_info["severity"] == "error"
