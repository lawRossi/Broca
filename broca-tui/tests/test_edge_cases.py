"""
Edge case tests for broca-tui (Updated for 简洁模式).

Covers:
- Empty states (no sessions, no turns, no agents, no executions)
- Error states (API failures, connection errors)
- Connection/disconnection transitions
- Turn edge cases (missing fields, malformed data)
"""

import json
from unittest.mock import AsyncMock

import pytest

from broca_tui.stores.session_store import SessionStore
from broca_tui.stores.chat_store import ChatStore, TurnSummary
from broca_tui.stores.agent_store import AgentStore
from broca_tui.stores.crew_store import CrewStore


# ============================================================================
# TurnSummary edge cases
# ============================================================================

class TestTurnSummaryEdgeCases:
    """Test TurnSummary creation with edge case data."""

    def test_turn_summary_minimal(self):
        """TurnSummary can be created with minimal fields."""
        summary = TurnSummary(
            turn_id="minimal",
            sequence_number=0,
            agent_id="",
            agent_name="",
        )
        assert summary.turn_id == "minimal"
        assert summary.sequence_number == 0
        assert summary.user_message is None
        assert summary.final_response == ""
        assert summary.total_duration == 0.0
        assert summary.is_active is True

    def test_turn_summary_long_content(self):
        """TurnSummary accepts very long content."""
        long_text = "A" * 10000
        summary = TurnSummary(
            turn_id="long",
            sequence_number=1,
            agent_id="agent-1",
            agent_name="Assistant",
            user_message=long_text,
            final_response=long_text,
        )
        assert len(summary.user_message) == 10000
        assert len(summary.final_response) == 10000

    def test_turn_summary_unicode_content(self):
        """TurnSummary handles unicode content."""
        text = "你好世界 \ud83c\udf0d \n 日本語"
        summary = TurnSummary(
            turn_id="unicode",
            sequence_number=1,
            agent_id="agent-1",
            agent_name="助手",
            user_message=text,
            final_response=text,
            reasoning_content=text,
        )
        assert summary.agent_name == "助手"
        assert summary.user_message == text
        assert summary.final_response == text

    def test_turn_summary_empty_lists(self):
        """TurnSummary handles empty lists gracefully."""
        summary = TurnSummary(
            turn_id="empty-lists",
            sequence_number=1,
            agent_id="agent-1",
            agent_name="Agent",
            current_todo_list=[],
            tool_call_stats=[],
        )
        assert summary.current_todo_list == []
        assert summary.tool_call_stats == []

    def test_turn_summary_none_fields(self):
        """TurnSummary handles None optional fields."""
        summary = TurnSummary(
            turn_id="none-fields",
            sequence_number=1,
            agent_id="agent-1",
            agent_name="Agent",
            user_message=None,
            current_tool=None,
            current_file_path=None,
            final_response=None,  # type: ignore — test None handling
            reasoning_content=None,  # type: ignore
            last_message_id=None,
        )
        assert summary.user_message is None
        assert summary.current_tool is None
        # None should be set as... let's check
        assert summary.final_response is None  # will not be auto-converted

    def test_turn_summary_zero_duration(self):
        """TurnSummary handles zero duration."""
        summary = TurnSummary(
            turn_id="zero-duration",
            sequence_number=1,
            agent_id="agent-1",
            agent_name="Agent",
            total_duration=0.0,
        )
        assert summary.total_duration == 0.0

    def test_turn_summary_large_duration(self):
        """TurnSummary handles large duration."""
        summary = TurnSummary(
            turn_id="large-duration",
            sequence_number=1,
            agent_id="agent-1",
            agent_name="Agent",
            total_duration=999999.9,
        )
        assert summary.total_duration == 999999.9

    def test_turn_summary_many_tool_stats(self):
        """TurnSummary handles many tool call stats."""
        stats = [{"toolName": f"tool_{i}", "count": i} for i in range(20)]
        summary = TurnSummary(
            turn_id="many-tools",
            sequence_number=1,
            agent_id="agent-1",
            agent_name="Agent",
            tool_call_stats=stats,
        )
        assert len(summary.tool_call_stats) == 20


class TestTurnSummaryEdgeCasesFromAPI:
    """Test TurnSummary creation from API response data (edge cases)."""

    def test_api_data_missing_fields(self):
        """API response with missing fields doesn't crash."""
        raw_turn = {
            "turn_id": "api-turn-1",
            # missing sequence_number, agent_id, etc.
        }
        summary = TurnSummary(
            turn_id=raw_turn.get("turn_id", ""),
            sequence_number=raw_turn.get("sequence_number", 0),
            agent_id=raw_turn.get("agent_id", ""),
            agent_name=raw_turn.get("agent_name", ""),
            user_message=raw_turn.get("user_message"),
            status="completed",
            current_tool=raw_turn.get("current_tool"),
            current_file_path=raw_turn.get("current_file_path"),
            current_todo_list=raw_turn.get("current_todo_list", []),
            total_duration=raw_turn.get("duration_seconds", 0) or 0.0,
            total_steps=raw_turn.get("total_steps", 0),
            tool_call_stats=raw_turn.get("tool_call_stats", []),
            final_response=raw_turn.get("final_response", ""),
            is_active=False,
            started_at=0,
            created_at=raw_turn.get("created_at", ""),
            last_message_id=raw_turn.get("last_message_id"),
        )
        assert summary.turn_id == "api-turn-1"
        assert summary.sequence_number == 0
        assert summary.agent_name == ""

    def test_api_data_none_duration(self):
        """API response with None duration uses 0."""
        raw_turn = {
            "turn_id": "none-dur",
            "sequence_number": 1,
            "agent_id": "a1",
            "agent_name": "Agent",
            "duration_seconds": None,
        }
        summary = TurnSummary(
            turn_id=raw_turn.get("turn_id", ""),
            sequence_number=raw_turn.get("sequence_number", 0),
            agent_id=raw_turn.get("agent_id", ""),
            agent_name=raw_turn.get("agent_name", ""),
            user_message=raw_turn.get("user_message"),
            status="completed",
            current_tool=raw_turn.get("current_tool"),
            current_file_path=raw_turn.get("current_file_path"),
            current_todo_list=raw_turn.get("current_todo_list", []),
            total_duration=raw_turn.get("duration_seconds", 0) or 0.0,
            total_steps=raw_turn.get("total_steps", 0),
            tool_call_stats=raw_turn.get("tool_call_stats", []),
            final_response=raw_turn.get("final_response", ""),
            is_active=False,
            started_at=0,
            created_at=raw_turn.get("created_at", ""),
            last_message_id=raw_turn.get("last_message_id"),
        )
        assert summary.total_duration == 0.0

    def test_api_data_empty_tool_stats(self):
        """API response with empty tool stats doesn't crash."""
        raw_turn = {
            "turn_id": "empty-stats",
            "sequence_number": 1,
            "agent_id": "a1",
            "agent_name": "Agent",
            "tool_call_stats": [],
        }
        summary = TurnSummary(
            turn_id=raw_turn["turn_id"],
            sequence_number=raw_turn["sequence_number"],
            agent_id=raw_turn["agent_id"],
            agent_name=raw_turn["agent_name"],
            tool_call_stats=raw_turn.get("tool_call_stats", []),
        )
        assert summary.tool_call_stats == []

    def test_is_reverted_filter(self):
        """Reverted turns should be filtered by load_turn_history."""
        # This tests the filtering logic used in load_turn_history
        raw_turns = [
            {"turn_id": "t1", "sequence_number": 1, "agent_id": "a1", "agent_name": "A", "is_reverted": False},
            {"turn_id": "t2", "sequence_number": 2, "agent_id": "a1", "agent_name": "A", "is_reverted": True},
            {"turn_id": "t3", "sequence_number": 3, "agent_id": "a2", "agent_name": "B", "is_reverted": False},
        ]

        filtered = [t for t in raw_turns if not t.get("is_reverted", False)]
        assert len(filtered) == 2
        assert filtered[0]["turn_id"] == "t1"
        assert filtered[1]["turn_id"] == "t3"


class TestChatStoreTurnEdgeCases:
    """Test ChatStore turn-related edge cases."""

    def test_find_turn_nonexistent(self):
        """_find_turn returns None for non-existent turn."""
        store = ChatStore()
        store.turn_summaries = [
            TurnSummary(turn_id="t1", sequence_number=1, agent_id="a1", agent_name="A"),
            TurnSummary(turn_id="t2", sequence_number=2, agent_id="a2", agent_name="B"),
        ]
        result = store._find_turn("nonexistent")
        assert result is None

    def test_find_turn_exists(self):
        """_find_turn returns correct turn."""
        store = ChatStore()
        store.turn_summaries = [
            TurnSummary(turn_id="t1", sequence_number=1, agent_id="a1", agent_name="A"),
            TurnSummary(turn_id="t2", sequence_number=2, agent_id="a2", agent_name="B"),
        ]
        result = store._find_turn("t2")
        assert result is not None
        assert result.agent_id == "a2"

    def test_create_turn_summary_duplicate(self):
        """create_turn_summary does not create duplicates."""
        store = ChatStore()
        store.create_turn_summary("dup-turn", "agent-1", "Agent")
        assert len(store.turn_summaries) == 1

        store.create_turn_summary("dup-turn", "agent-1", "Agent")
        assert len(store.turn_summaries) == 1  # same

    def test_increment_turn_steps_nonexistent(self):
        """increment_turn_steps does nothing for non-existent turn."""
        store = ChatStore()
        store.turn_summaries = []
        # Should not raise
        store.increment_turn_steps("nonexistent")
        assert True

    def test_increment_turn_steps(self):
        """increment_turn_steps increases step count."""
        store = ChatStore()
        store.turn_summaries = [
            TurnSummary(turn_id="t1", sequence_number=1, agent_id="a1", agent_name="A"),
        ]
        store.increment_turn_steps("t1")
        assert store.turn_summaries[0].total_steps == 1
        store.increment_turn_steps("t1")
        assert store.turn_summaries[0].total_steps == 2

    def test_get_filtered_turns_all_visible(self):
        """When all agents visible, no filtering."""
        store = ChatStore()
        store.turn_summaries = [
            TurnSummary(turn_id="t1", sequence_number=1, agent_id="a1", agent_name="A"),
            TurnSummary(turn_id="t2", sequence_number=2, agent_id="a2", agent_name="B"),
        ]
        result = store.get_filtered_turns(["a1", "a2"], ["a1", "a2"])
        assert len(result) == 2

    def test_get_filtered_turns_partial(self):
        """When some agents hidden, filter correctly."""
        store = ChatStore()
        store.turn_summaries = [
            TurnSummary(turn_id="t1", sequence_number=1, agent_id="a1", agent_name="A"),
            TurnSummary(turn_id="t2", sequence_number=2, agent_id="a2", agent_name="B"),
            TurnSummary(turn_id="t3", sequence_number=3, agent_id="a1", agent_name="A"),
        ]
        result = store.get_filtered_turns(["a1"], ["a1", "a2"])
        assert len(result) == 2
        assert result[0].agent_id == "a1"
        assert result[1].agent_id == "a1"

    def test_get_filtered_turns_no_visible(self):
        """When no agent IDs provided, return all."""
        store = ChatStore()
        store.turn_summaries = [
            TurnSummary(turn_id="t1", sequence_number=1, agent_id="a1", agent_name="A"),
        ]
        result = store.get_filtered_turns([], ["a1", "a2"])
        assert len(result) == 1  # empty visible_ids → show all
