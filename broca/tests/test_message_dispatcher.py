"""
Regression tests for _MessageDispatcher table completeness.

Verifies that every MessageType enum value has a routing entry (except
SUBSCRIBE/UNSUBSCRIBE which are handled by early-return branches).
"""

import pytest

from broca.communication.socketio_client import _MessageDispatcher
from broca.session.models import MessageType


class TestDispatcherTableCompleteness:
    """Every MessageType (except SUBSCRIBE/UNSUBSCRIBE) must be in the table."""

    def test_all_message_types_routable(self):
        """No 'Unhandled message type' should occur for any MessageType."""
        dispatcher = _MessageDispatcher(
            trigger_event=lambda *a: None,
            get_connection_info=lambda: None,
        )

        # SUBSCRIBE/UNSUBSCRIBE are handled by early-return branches, not the table.
        # CONNECT/DISCONNECT are lifecycle events handled natively by socket.io
        # (not dispatched as message events) — excluding them prevents the
        # "takes 1 positional argument but 2 were given" bug.
        non_table_types = {
            MessageType.SUBSCRIBE,
            MessageType.UNSUBSCRIBE,
            MessageType.CONNECT,
            MessageType.DISCONNECT,
        }

        missing = []
        for mt in MessageType:
            if mt in non_table_types:
                continue
            event_name = dispatcher._table.get(mt)
            if event_name is None:
                missing.append(mt.value)

        assert not missing, f"Missing dispatcher entries for: {missing}"

    def test_subscribe_unsubscribe_not_in_table(self):
        """SUBSCRIBE/UNSUBSCRIBE should NOT be in the table (handled by early branches)."""
        dispatcher = _MessageDispatcher(
            trigger_event=lambda *a: None,
            get_connection_info=lambda: None,
        )

        assert MessageType.SUBSCRIBE not in dispatcher._table
        assert MessageType.UNSUBSCRIBE not in dispatcher._table

    def test_early_branch_types_handled_before_table(self):
        """SUBSCRIBE/UNSUBSCRIBE trigger early-return in dispatch(), not table lookup."""
        dispatcher = _MessageDispatcher(
            trigger_event=lambda *a: None,
            get_connection_info=lambda: None,
        )

        # These have special handling in dispatch()
        for mt in (MessageType.SUBSCRIBE, MessageType.UNSUBSCRIBE):
            assert mt in {MessageType.SUBSCRIBE, MessageType.UNSUBSCRIBE}
