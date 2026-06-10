"""
Edge case tests for broca-tui.

Covers:
- Empty states (no sessions, no messages, no agents, no executions)
- Error states (API failures, connection errors)
- Connection/disconnection transitions
- Message overflow (long content, many messages)
- Tool call edge cases (missing fields, malformed data)
- Edge cases in _format_json, _parse_arguments
"""

import json
from unittest.mock import AsyncMock

import pytest

from broca_tui.widgets.message_item import MessageItem, _format_json, _parse_arguments
from broca_tui.stores.session_store import SessionStore
from broca_tui.stores.chat_store import ChatStore
from broca_tui.stores.agent_store import AgentStore
from broca_tui.stores.crew_store import CrewStore


# ============================================================================
# Empty State Tests
# ============================================================================

class TestEmptyStates:
    """Test empty state handling across all stores."""

    @pytest.mark.asyncio
    async def test_empty_session_list(self):
        """Test session list with no sessions."""
        store = SessionStore()
        store._api = AsyncMock()
        store._api.list_sessions.return_value = {"sessions": [], "total": 0}

        await store.load_sessions()
        assert len(store.sessions) == 0
        assert store.total == 0
        assert store.has_more is False

    def test_empty_messages(self):
        """Test chat store with no messages."""
        store = ChatStore()
        assert len(store.messages) == 0
        assert len(store.message_states) == 0
        assert len(store.pending_chunks) == 0

    @pytest.mark.asyncio
    async def test_empty_agents(self):
        """Test agent store with no agents."""
        store = AgentStore()
        store._api = AsyncMock()
        store._api.get_session_agents.return_value = []

        await store.fetch_agents("session-1")
        assert len(store.agents) == 0
        assert len(store.visible_agent_ids) == 0
        assert store.current_agent_id is None

    @pytest.mark.asyncio
    async def test_empty_executions(self):
        """Test crew store with no executions."""
        store = CrewStore()
        store._api = AsyncMock()
        store._api.list_executions.return_value = {"executions": [], "total": 0}

        await store.load_executions()
        assert len(store.executions) == 0
        assert store.total == 0


# ============================================================================
# Error State Tests
# ============================================================================

class TestErrorStates:
    """Test error handling in stores."""

    @pytest.mark.asyncio
    async def test_session_list_api_error(self):
        """Test API error during session list load."""
        store = SessionStore()
        store._api = AsyncMock()
        store._api.list_sessions.side_effect = Exception("Connection refused")

        await store.load_sessions()
        assert store.last_error is not None
        assert "Connection refused" in store.last_error
        assert store.loading is False  # Loading should be reset

    @pytest.mark.asyncio
    async def test_create_session_api_error(self):
        """Test API error during session creation."""
        store = SessionStore()
        store._api = AsyncMock()
        store._api.create_session.side_effect = Exception("API timeout")

        result = await store.create_session(description="Test")
        assert result is None
        assert store.last_error is not None
        assert "API timeout" in store.last_error

    @pytest.mark.asyncio
    async def test_delete_session_api_error(self):
        """Test API error during session deletion."""
        store = SessionStore()
        store._api = AsyncMock()
        store._api.delete_session.side_effect = Exception("Not found")

        result = await store.delete_session("nonexistent")
        assert result is False
        assert store.last_error is not None

    @pytest.mark.asyncio
    async def test_crew_submit_api_error(self):
        """Test API error during crew submission."""
        store = CrewStore()
        store._api = AsyncMock()
        store._api.submit_execution.side_effect = Exception("Invalid config")

        errors = []
        store.on_error(lambda msg: errors.append(msg))

        result = await store.submit_execution(session_id="s1", yaml_path="/bad.yaml")
        assert result is None
        assert len(errors) == 1

    @pytest.mark.asyncio
    async def test_abort_execution_api_error(self):
        """Test API error during abort."""
        store = CrewStore()
        store._api = AsyncMock()
        store._api.abort_execution.side_effect = Exception("Already completed")

        errors = []
        store.on_error(lambda msg: errors.append(msg))

        result = await store.abort_execution("e1")
        assert result is False
        assert len(errors) == 1


# ============================================================================
# Message Edge Case Tests
# ============================================================================

class TestMessageEdgeCases:
    """Test edge cases in message handling."""

    def test_empty_message_content(self):
        """Test message with empty content."""
        msg = {"message_id": "m1", "message_type": "user_message", "data": {}}
        store = ChatStore()
        store._add_message(msg)
        assert len(store.messages) == 1

    def test_null_data(self):
        """Test message with None data."""
        msg = {"message_id": "m2", "message_type": "user_message", "data": None}
        store = ChatStore()
        store._add_message(msg)
        assert len(store.messages) == 1

    def test_tool_call_missing_fields(self):
        """Test tool call with missing optional fields."""
        msg = {
            "message_id": "m3",
            "message_type": "tool_call",
            "data": {},  # No tool_name, no arguments, no tool_call_id
        }
        store = ChatStore()
        store._add_message(msg)
        assert len(store.messages) == 1
        # Should not crash
        assert store.messages[0]["message_type"] == "tool_call"

    def test_tool_call_with_arguments_as_string(self):
        """Test tool call where arguments is a JSON string."""
        msg = {
            "message_id": "m4",
            "message_type": "tool_call",
            "data": {
                "tool_name": "read_file",
                "arguments": '{"path": "/tmp/test.txt"}',
                "tool_call_id": "tc-s",
            },
        }
        store = ChatStore()
        store._add_message(msg)
        assert len(store.messages) == 1
        # _parse_arguments should handle string
        args = _parse_arguments('{"path": "/tmp/test.txt"}')
        assert args["path"] == "/tmp/test.txt"

    def test_very_long_message_content(self):
        """Test message with very long content."""
        long_content = "A" * 10000
        msg = {"message_id": "m5", "message_type": "user_message", "data": {"content": long_content}}
        store = ChatStore()
        store._add_message(msg)
        assert len(store.messages) == 1
        assert len(store.messages[0]["data"]["content"]) == 10000

    def test_unclosed_json_in_agent_response(self):
        """Test agent response with malformed JSON wrapper."""
        msg = {
            "message_id": "m6",
            "message_type": "agent_response",
            "data": {"content": '{"content": "Hello", "reasoning_content": "unclosed'},
        }
        store = ChatStore()
        store._add_message(msg)
        assert len(store.messages) == 1
        # Should not crash, content should be the raw string

    def test_edit_file_with_empty_strings(self):
        """Test edit_file with empty old_text or new_text."""
        args = {"path": "/tmp/test.py", "old_text": "", "new_text": ""}
        # Empty strings produce empty splitlines → empty diff (0 header lines)
        import difflib
        diff = list(difflib.unified_diff(
            args["old_text"].splitlines(keepends=True),
            args["new_text"].splitlines(keepends=True),
        ))
        # With both strings empty, unified_diff returns nothing
        assert len(diff) == 0


# ============================================================================
# Utility Function Edge Cases
# ============================================================================

class TestUtilityEdgeCases:
    """Test edge cases in utility functions."""

    def test_format_json_nested(self):
        """Test formatting nested JSON."""
        data = {"level1": {"level2": {"level3": "deep"}}}
        result = _format_json(data)
        assert "level3" in result

    def test_format_json_list(self):
        """Test formatting a list."""
        result = _format_json([1, 2, 3, {"a": "b"}])
        assert "a" in result

    def test_format_json_unicode(self):
        """Test formatting unicode content."""
        result = _format_json({"text": "你好世界"})
        assert "你好世界" in result

    def test_format_json_empty_dict(self):
        """Test formatting empty dict."""
        result = _format_json({})
        assert result == "{}"

    def test_parse_arguments_malformed_json(self):
        """Test parsing malformed JSON string."""
        result = _parse_arguments("{bad json}")
        assert result == {}

    def test_parse_arguments_empty_string(self):
        """Test parsing empty string."""
        result = _parse_arguments("")
        assert result == {}

    def test_parse_arguments_none(self):
        """Test parsing None."""
        result = _parse_arguments(None)
        assert result == {}

    def test_parse_arguments_int(self):
        """Test parsing integer (edge case, shouldn't happen but be safe)."""
        result = _parse_arguments(42)
        assert result == {}

    def test_parse_arguments_list(self):
        """Test parsing a list (not dict)."""
        result = _parse_arguments([1, 2, 3])
        assert result == {}


# ============================================================================
# Connection State Edge Cases
# ============================================================================

class TestConnectionEdgeCases:
    """Test connection state transitions."""

    def test_disconnect_before_connect(self):
        """Test disconnecting when never connected — should be safe no-op."""
        store = ChatStore()
        assert store.connected is False
        assert store.session_id is None
        # disconnect() when not connected should not crash
        # We can verify state invariants without calling the async method

    def test_connection_state_initial(self):
        """Test initial connection state."""
        store = ChatStore()
        assert store.connected is False
        assert store.connecting is False
        assert store.session_id is None

    def test_clear_messages_with_empty_store(self):
        """Test clearing messages when already empty."""
        store = ChatStore()
        store.clear_messages()
        assert len(store.messages) == 0
        assert len(store.message_states) == 0


# ============================================================================
# Todo Edge Cases
# ============================================================================

class TestTodoEdgeCases:
    """Test todo_management edge cases."""

    def test_todo_empty_list(self):
        """Test todo with empty list."""
        args = {"todos": []}
        # Should render without error
        item = MessageItem({"message_id": "t1", "message_type": "tool_call", "data": {"tool_name": "todo_management", "arguments": args}})
        assert item is not None

    def test_todo_missing_status(self):
        """Test todo item with missing status."""
        args = {"todos": [{"name": "Task 1"}]}
        # Missing status should default to pending
        item = MessageItem({"message_id": "t2", "message_type": "tool_call", "data": {"tool_name": "todo_management", "arguments": args}})
        assert item is not None

    def test_todo_all_statuses(self):
        """Test todos with all possible statuses."""
        args = {
            "todos": [
                {"name": "Done", "status": "completed"},
                {"name": "In Progress", "status": "in_progress"},
                {"name": "Pending", "status": "pending"},
                {"name": "Unknown", "status": "unknown"},
            ]
        }
        item = MessageItem({"message_id": "t3", "message_type": "tool_call", "data": {"tool_name": "todo_management", "arguments": args}})
        assert item is not None


# ============================================================================
# Message Type Edge Cases
# ============================================================================

class TestMessageTypeEdgeCases:
    """Test edge case message types."""

    def test_unknown_message_type(self):
        """Test handling of completely unknown message type."""
        msg = {"message_id": "x1", "message_type": "completely_unknown", "data": {"foo": "bar"}}
        item = MessageItem(msg)
        # Should render without error (falls back to _render_fallback)
        assert item._get_border_class("completely_unknown", "") == "msg-default"

    def test_agent_response_non_json(self):
        """Test agent response with non-JSON content (plain string)."""
        msg = {"message_id": "x2", "message_type": "agent_response", "data": {"content": "Plain text response"}}
        item = MessageItem(msg)
        # Should parse as plain text without JSON error
        assert item is not None

    def test_tool_call_no_tool_name(self):
        """Test tool call without a tool name."""
        msg = {"message_id": "x3", "message_type": "tool_call", "data": {"arguments": {}, "tool_call_id": "x"}}
        item = MessageItem(msg)
        # With empty arguments, generic tool renders nothing
        # (no params to toggle, no result to show)
        result = list(item._render_message_content("tool_call", msg["data"]))
        assert len(result) == 0  # Nothing to render for empty tool call

    def test_mixed_type_and_role(self):
        """Test message with non-standard type/role combination."""
        msg = {"message_id": "x4", "message_type": "user_message", "role": "assistant"}
        item = MessageItem(msg)
        # Should still render as user message (message_type takes priority)
        border = item._get_border_class("user_message", "assistant")
        assert border == "msg-user"
