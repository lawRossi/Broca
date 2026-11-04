"""
Regression tests for Communicator ABC completeness.

Verifies that:
1. SocketIOClient satisfies all abstract methods
2. A partial implementation cannot be instantiated
3. The ABC has exactly the expected number of abstract methods
"""

import pytest
from abc import ABC
from unittest.mock import MagicMock, patch


class TestCommunicatorABC:
    """Communicator ABC structure verification."""

    def test_abstract_method_count(self):
        """Communicator has 21 abstract methods covering all SocketIOClient methods."""
        from broca.components.communicator import Communicator

        abstract_methods = set()
        for attr_name in dir(Communicator):
            attr = getattr(Communicator, attr_name)
            if getattr(attr, "__isabstractmethod__", False):
                abstract_methods.add(attr_name)

        expected = {
            # Core lifecycle
            "connect", "disconnect", "is_connected", "initialize",
            # Core message
            "send_message", "send_user_message", "send_tool_call",
            # High-frequency
            "send_agent_response", "send_turn_start", "send_turn_end",
            "send_task_complete", "send_task_error", "send_task_start",
            "send_permission_request", "send_permission_response",
            # Command
            "send_command", "send_command_result",
            # Error
            "send_error",
            # Event/subscription
            "register_event_handler", "subscribe", "unsubscribe",
        }
        assert abstract_methods == expected, (
            f"Mismatch: extra={abstract_methods - expected}, missing={expected - abstract_methods}"
        )

    def test_socketio_client_satisfies_abc(self):
        """SocketIOClient can be instantiated (implements all abstract methods)."""
        from broca.components.communicator import Communicator
        from broca.communication.socketio_client import SocketIOClient

        assert issubclass(SocketIOClient, Communicator)
        # Should be instantiable without TypeError
        client = SocketIOClient(server_url="http://localhost:1")

    def test_partial_implementation_cannot_instantiate(self):
        """A class that doesn't implement all abstract methods raises TypeError."""
        from broca.components.communicator import Communicator

        class IncompleteComm(Communicator):
            # Only implements connect, everything else missing
            async def connect(self, timeout: float = 10.0) -> bool:
                return True

        with pytest.raises(TypeError, match="Can't instantiate abstract class"):
            IncompleteComm()

    def test_optional_methods_have_defaults(self):
        """Optional methods provide default implementations (not abstract)."""
        from broca.components.communicator import Communicator

        for method_name in [
            "send_user_answer",
            "send_broadcast",
            "send_agent_system_message",
        ]:
            method = getattr(Communicator, method_name)
            assert not getattr(method, "__isabstractmethod__", False), (
                f"{method_name} should NOT be abstract"
            )
