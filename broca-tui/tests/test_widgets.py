"""
Tests for broca_tui.widgets module — Updated for 简洁模式 (TurnCard).

Covers:
- TurnCard: rendering with various TurnSummary states
- TurnCard: simplified status mapping (active/completed/error)
- TurnCard: formatting (duration, tool stats, agent name)
- ChatInput: _send_message @mention parsing
"""

from datetime import datetime, timezone, timedelta
from unittest.mock import MagicMock, patch, PropertyMock

import pytest

from broca_tui.stores.chat_store import TurnSummary
from broca_tui.widgets.turn_card import TurnCard


# ============================================================================
# TurnSummary creation helper
# ============================================================================

def make_turn(**kwargs):
    """Create a TurnSummary with sensible defaults."""
    defaults = {
        "turn_id": "test-turn-1",
        "sequence_number": 1,
        "agent_id": "agent-1",
        "agent_name": "TestAgent",
        "user_message": "Hello",
        "status": "completed",
        "current_tool": None,
        "current_file_path": None,
        "current_todo_list": [],
        "total_duration": 12.5,
        "total_steps": 5,
        "tool_call_stats": [],
        "final_response": "Here is the result.",
        "reasoning_content": "",
        "is_active": False,
        "started_at": 0.0,
        "created_at": "2024-01-01T00:00:00",
        "last_message_id": "msg-1",
    }
    defaults.update(kwargs)
    return TurnSummary(**defaults)


# ============================================================================
# TurnCard static/helper method tests
# ============================================================================

class TestTurnCardStatus:
    """Test TurnCard status simplification logic."""

    def test_status_completed(self):
        """Completed turn should return 'completed'."""
        turn = make_turn(status="completed")
        card = TurnCard(turn)
        assert card._get_simplified_status() == "completed"
        assert card._get_status_text() == "已完成"

    def test_status_error(self):
        """Error turn should return 'error'."""
        turn = make_turn(status="error")
        card = TurnCard(turn)
        assert card._get_simplified_status() == "error"
        assert card._get_status_text() == "中断"

    def test_status_active(self):
        """Active/thinking/calling_tool all simplify to 'active'."""
        for status in ("active", "thinking", "calling_tool"):
            turn = make_turn(status=status)
            card = TurnCard(turn)
            assert card._get_simplified_status() == "active", f"Status '{status}' should simplify to 'active'"
            assert card._get_status_text() == "进行中"

    def test_status_unknown(self):
        """Unknown status should fall back to '未知'."""
        turn = make_turn(status="unknown_status")
        card = TurnCard(turn)
        assert card._get_simplified_status() == "active"
        assert card._get_status_text() == "进行中"


class TestTurnCardDuration:
    """Test TurnCard duration formatting."""

    def test_duration_seconds(self):
        """Less than 60 seconds shows 'Xs'."""
        turn = make_turn(total_duration=5.2)
        card = TurnCard(turn)
        assert card._get_formatted_duration() == "5s"

    def test_duration_exact_minute(self):
        """Exactly 60 seconds shows '1分0秒'."""
        turn = make_turn(total_duration=60.0)
        card = TurnCard(turn)
        assert card._get_formatted_duration() == "1分0秒"

    def test_duration_minutes_seconds(self):
        """Minutes and seconds format."""
        turn = make_turn(total_duration=125.7)
        card = TurnCard(turn)
        assert card._get_formatted_duration() == "2分6秒"


class TestTurnCardToolExecution:
    """Test TurnCard tool execution detection and formatting."""

    def test_no_tool_execution(self):
        """Turn without tool calls should not show execution section."""
        turn = make_turn(tool_call_stats=[], current_tool=None,
                         current_file_path=None, current_todo_list=[])
        card = TurnCard(turn)
        assert card._has_tool_execution() is False

    def test_has_tool_stats(self):
        """Turn with tool call stats should show execution section."""
        turn = make_turn(tool_call_stats=[{"toolName": "read_file", "count": 2}])
        card = TurnCard(turn)
        assert card._has_tool_execution() is True

    def test_has_current_tool(self):
        """Turn with current tool should show execution section."""
        turn = make_turn(current_tool="read_file")
        card = TurnCard(turn)
        assert card._has_tool_execution() is True

    def test_tool_stats_text(self):
        """Tool stats formatting."""
        turn = make_turn(tool_call_stats=[
            {"toolName": "read_file", "count": 2},
            {"toolName": "edit_file", "count": 1},
        ])
        card = TurnCard(turn)
        assert card._get_tool_stats_text() == "read_file (2次), edit_file (1次)"

    def test_file_path_shown_for_file_tools(self):
        """File path shown only for read_file/edit_file/write_file tools."""
        for tool in ("read_file", "edit_file", "write_file"):
            turn = make_turn(current_tool=tool, current_file_path="/path/to/file.py")
            card = TurnCard(turn)
            assert card._show_file_path() is True

    def test_file_path_hidden_for_other_tools(self):
        """File path hidden for non-file tools."""
        turn = make_turn(current_tool="web_search", current_file_path="/path/to/file.py")
        card = TurnCard(turn)
        assert card._show_file_path() is False

    def test_todo_list_shown(self):
        """Todo list shown when todos exist."""
        turn = make_turn(current_todo_list=[
            {"name": "Task 1", "status": "completed"},
            {"name": "Task 2", "status": "pending"},
        ])
        card = TurnCard(turn)
        assert card._show_todo_list() is True

    def test_todo_list_hidden_when_empty(self):
        """Todo list hidden when empty."""
        turn = make_turn(current_todo_list=[])
        card = TurnCard(turn)
        assert card._show_todo_list() is False


class TestTurnCardAgentName:
    """Test TurnCard agent name resolution."""

    def test_name_from_map(self):
        """Agent name from agent_name_map should take priority."""
        turn = make_turn(agent_id="agent-1", agent_name="BackendAgent")
        card = TurnCard(turn, agent_name_map={"agent-1": "FrontendAgent"})
        assert card._get_agent_display_name() == "FrontendAgent"

    def test_name_from_turn(self):
        """Agent name from turn when map has no entry."""
        turn = make_turn(agent_id="agent-1", agent_name="BackendAgent")
        card = TurnCard(turn, agent_name_map={})
        assert card._get_agent_display_name() == "BackendAgent"

    def test_name_fallback_to_id(self):
        """Agent ID when no name is available."""
        turn = make_turn(agent_id="agent-1", agent_name="")
        card = TurnCard(turn, agent_name_map={})
        assert card._get_agent_display_name() == "agent-1"

    def test_empty_agent_name_map(self):
        """Empty agent_name_map should not cause errors."""
        turn = make_turn(agent_id="agent-1", agent_name="Agent")
        card = TurnCard(turn, agent_name_map=None)
        assert card._get_agent_display_name() == "Agent"


class TestTurnCardUndo:
    """Test TurnCard undo capability detection."""

    def test_can_undo_completed_with_last_message(self):
        """Completed turn with last_message_id should be undoable."""
        turn = make_turn(status="completed", last_message_id="msg-1")
        card = TurnCard(turn)
        assert card._can_undo() is True

    def test_cannot_undo_no_last_message(self):
        """Completed turn without last_message_id should not be undoable."""
        turn = make_turn(status="completed", last_message_id=None)
        card = TurnCard(turn)
        assert card._can_undo() is False

    def test_cannot_undo_active(self):
        """Active turn should not be undoable."""
        turn = make_turn(status="active", last_message_id="msg-1")
        card = TurnCard(turn)
        assert card._can_undo() is False

    def test_cannot_undo_error(self):
        """Error turn should not be undoable."""
        turn = make_turn(status="error", last_message_id="msg-1")
        card = TurnCard(turn)
        assert card._can_undo() is False
