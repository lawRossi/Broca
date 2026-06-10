"""
Tests for broca_tui.stores module.

Covers:
- SessionStore: list loading, create, delete, pagination
- ChatStore: message handling, chunk merging, history loading
- AgentStore: agent management, @mention parsing, visibility
- CrewStore: execution list, submit with running check, abort
"""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from broca_tui.stores.session_store import SessionStore
from broca_tui.stores.chat_store import ChatStore
from broca_tui.stores.agent_store import AgentStore
from broca_tui.stores.crew_store import CrewStore


# ============================================================================
# SessionStore Tests
# ============================================================================

class TestSessionStore:
    """Test SessionStore functionality."""

    @pytest.fixture
    def store(self):
        s = SessionStore()
        s._api = AsyncMock()
        return s

    @pytest.mark.asyncio
    async def test_load_sessions_populates_list(self, store):
        """Test that load_sessions populates sessions list."""
        mock_sessions = [
            {"session_id": "s1", "description": "Session 1"},
            {"session_id": "s2", "description": "Session 2"},
        ]
        store._api.list_sessions.return_value = {
            "sessions": mock_sessions,
            "total": 2,
        }

        await store.load_sessions()
        assert len(store.sessions) == 2
        assert store.total == 2
        assert store.skip == 10  # limit
        assert store.has_more is False  # skip=20 >= total=2

    @pytest.mark.asyncio
    async def test_load_sessions_with_keyword(self, store):
        """Test load_sessions with keyword resets pagination."""
        store.sessions = [{"session_id": "old"}]
        store.skip = 20

        store._api.list_sessions.return_value = {
            "sessions": [{"session_id": "s1"}],
            "total": 1,
        }

        await store.load_sessions(keyword="test")
        assert len(store.sessions) == 1
        assert store.skip == 10
        assert store.keyword == "test"

    @pytest.mark.asyncio
    async def test_load_more_appends(self, store):
        """Test that load_more appends to existing sessions."""
        store.sessions = [{"session_id": "s1"}]
        store.skip = 20
        store.has_more = True
        store.total = 25

        store._api.list_sessions.return_value = {
            "sessions": [{"session_id": "s2"}],
            "total": 25,
        }

        await store.load_more()
        assert len(store.sessions) == 2
        assert store.skip == 30

    @pytest.mark.asyncio
    async def test_create_session_refreshes_list(self, store):
        """Test that create_session refreshes the list."""
        store._api.create_session.return_value = {
            "session_id": "new-session",
            "workspace": "/tmp",
        }
        store._api.list_sessions.return_value = {
            "sessions": [{"session_id": "new-session"}],
            "total": 1,
        }

        result = await store.create_session(description="Test", category="normal")
        assert result is not None
        assert result["session_id"] == "new-session"
        assert len(store.sessions) == 1

    @pytest.mark.asyncio
    async def test_delete_session_removes_from_list(self, store):
        """Test that delete_session removes session from local list."""
        store.sessions = [
            {"session_id": "s1"},
            {"session_id": "s2"},
            {"session_id": "s3"},
        ]
        store.total = 3
        store._api.delete_session = AsyncMock()

        result = await store.delete_session("s2")
        assert result is True
        assert len(store.sessions) == 2
        assert store.total == 2

    @pytest.mark.asyncio
    async def test_on_change_callback(self, store):
        """Test that on_change callback is fired."""
        calls = []
        store.on_change(lambda: calls.append("changed"))

        store._api.list_sessions.return_value = {
            "sessions": [],
            "total": 0,
        }

        await store.load_sessions()
        assert len(calls) >= 1  # at least loading + done

    @pytest.mark.asyncio
    async def test_last_error_on_api_error(self, store):
        """Test that last_error is set on API error."""
        store._api.list_sessions.side_effect = Exception("Connection refused")

        await store.load_sessions()
        assert store.last_error is not None
        assert "Connection refused" in store.last_error


# ============================================================================
# AgentStore Tests
# ============================================================================

class TestAgentStore:
    """Test AgentStore functionality."""

    @pytest.fixture
    def store(self):
        s = AgentStore()
        s._api = AsyncMock()
        return s

    @pytest.fixture
    def sample_agents(self):
        return [
            {"agent_id": "a1", "name": "Alice", "role": "assistant", "agent_status": "idle"},
            {"agent_id": "a2", "name": "Bob", "role": "code_assistant", "agent_status": "idle"},
        ]

    @pytest.mark.asyncio
    async def test_fetch_agents_populates_list(self, store, sample_agents):
        """Test that fetch_agents populates agents and visibility."""
        store._api.get_session_agents.return_value = sample_agents

        await store.fetch_agents("session-1")
        assert len(store.agents) == 2
        assert len(store.visible_agent_ids) == 2
        assert store.current_agent_id == "a1"

    @pytest.mark.asyncio
    async def test_fetch_agents_with_no_agents(self, store):
        """Test fetch_agents with empty response."""
        store._api.get_session_agents.return_value = []

        await store.fetch_agents("session-1")
        assert len(store.agents) == 0
        assert len(store.visible_agent_ids) == 0
        assert store.current_agent_id is None

    def test_update_agent_status(self, store, sample_agents):
        """Test updating agent status."""
        store.agents = sample_agents
        store.update_agent_status("a1", "running")
        assert store.agents[0]["agent_status"] == "running"
        assert store.agents[1]["agent_status"] == "idle"  # unchanged

    def test_set_current_agent(self, store):
        """Test setting current agent."""
        store.set_current_agent("a2")
        assert store.current_agent_id == "a2"

    def test_toggle_agent_visibility(self, store, sample_agents):
        """Test toggling agent visibility."""
        store.agents = sample_agents
        store.visible_agent_ids = ["a1", "a2"]

        store.toggle_agent_visibility("a1")
        assert "a1" not in store.visible_agent_ids
        assert "a2" in store.visible_agent_ids

        store.toggle_agent_visibility("a1")
        assert "a1" in store.visible_agent_ids

    def test_set_all_visible(self, store, sample_agents):
        """Test setting all agents visible/invisible."""
        store.agents = sample_agents
        store.visible_agent_ids = ["a1", "a2"]

        store.set_all_visible(False)
        assert len(store.visible_agent_ids) == 0

        store.set_all_visible(True)
        assert len(store.visible_agent_ids) == 2

    def test_get_agent_by_id(self, store, sample_agents):
        """Test getting agent by ID."""
        store.agents = sample_agents
        agent = store.get_agent("a2")
        assert agent is not None
        assert agent["name"] == "Bob"

    def test_get_agent_not_found(self, store):
        """Test getting non-existent agent returns None."""
        agent = store.get_agent("nonexistent")
        assert agent is None

    def test_get_agent_name(self, store, sample_agents):
        """Test getting agent display name."""
        store.agents = sample_agents
        assert store.get_agent_name("a1") == "Alice"
        assert store.get_agent_name("nonexistent") == "nonexistent"

    def test_parse_mention_at_start(self, store, sample_agents):
        """Test @mention at the start of text."""
        store.agents = sample_agents
        result = store.parse_mention("@Alice hello world")
        assert result["targetAgentId"] == "a1"
        assert result["cleanText"] == "hello world"

    def test_parse_mention_in_middle(self, store, sample_agents):
        """Test @mention in the middle of text (fix for issue #5)."""
        store.agents = sample_agents
        result = store.parse_mention("please @Bob help me")
        assert result["targetAgentId"] == "a2"
        assert result["cleanText"] == "please help me"

    def test_parse_mention_no_match(self, store):
        """Test text without @mention returns original."""
        result = store.parse_mention("hello world")
        assert result["targetAgentId"] is None
        assert result["cleanText"] == "hello world"

    def test_parse_mention_unknown_agent(self, store):
        """Test @mention for unknown agent returns None."""
        result = store.parse_mention("@UnknownAgent hello")
        assert result["targetAgentId"] is None

    def test_clear_cache(self, store, sample_agents):
        """Test clearing all cached data."""
        store.agents = sample_agents
        store.current_agent_id = "a1"
        store.visible_agent_ids = ["a1", "a2"]

        store.clear_cache()
        assert len(store.agents) == 0
        assert store.current_agent_id is None
        assert len(store.visible_agent_ids) == 0

    def test_current_agent_property(self, store, sample_agents):
        """Test current_agent property."""
        store.agents = sample_agents
        store.current_agent_id = "a1"
        assert store.current_agent["name"] == "Alice"

        store.current_agent_id = None
        assert store.current_agent is None


# ============================================================================
# ChatStore Tests
# ============================================================================

class TestChatStore:
    """Test ChatStore functionality (message handling, not socket-dependent)."""

    @pytest.fixture
    def store(self):
        s = ChatStore()
        s._api = AsyncMock()
        return s

    def test_init_message_state(self, store):
        """Test initializing message display state."""
        store._init_message_state("msg-1")
        assert "msg-1" in store.message_states
        assert store.message_states["msg-1"]["showParameters"] is False
        assert store.message_states["msg-1"]["showResult"] is False
        assert store.message_states["msg-1"]["showReasoning"] is False

    def test_init_message_state_empty_id(self, store):
        """Test init with empty message ID."""
        store._init_message_state("")
        assert "" not in store.message_states

    def test_toggle_tool_parameters(self, store):
        """Test toggling tool parameter display."""
        store.message_states["msg-1"] = {
            "showParameters": False,
            "showResult": False,
            "showReasoning": False,
        }
        store.toggle_tool_parameters("msg-1")
        assert store.message_states["msg-1"]["showParameters"] is True
        store.toggle_tool_parameters("msg-1")
        assert store.message_states["msg-1"]["showParameters"] is False

    def test_toggle_tool_result(self, store):
        """Test toggling tool result display."""
        store.message_states["msg-1"] = {
            "showParameters": False,
            "showResult": False,
            "showReasoning": False,
        }
        store.toggle_tool_result("msg-1")
        assert store.message_states["msg-1"]["showResult"] is True

    def test_toggle_reasoning(self, store):
        """Test toggling reasoning display."""
        store.message_states["msg-1"] = {
            "showParameters": False,
            "showResult": False,
            "showReasoning": False,
        }
        store.toggle_reasoning("msg-1")
        assert store.message_states["msg-1"]["showReasoning"] is True

    def test_clear_messages(self, store):
        """Test clearing all messages."""
        store.messages = [{"message_id": "msg-1"}]
        store.message_states["msg-1"] = {"showParameters": False, "showResult": False, "showReasoning": False}
        store.show_redo_button = True

        store.clear_messages()
        assert len(store.messages) == 0
        assert len(store.message_states) == 0
        assert len(store.pending_chunks) == 0
        assert store.show_redo_button is False

    def test_add_user_message(self, store):
        """Test adding a user message."""
        msg = {
            "message_id": "msg-1",
            "message_type": "user_message",
            "role": "user",
            "data": {"content": "hello"},
        }
        store._add_message(msg)
        assert len(store.messages) == 1
        assert store.messages[0]["message_type"] == "user_message"

    def test_add_tool_call_message(self, store):
        """Test adding a tool call message."""
        msg = {
            "message_id": "msg-2",
            "message_type": "tool_call",
            "role": "tool",
            "data": {
                "tool_call_id": "tc-1",
                "tool_name": "read_file",
                "arguments": {"path": "/tmp/test.txt"},
            },
        }
        store._add_message(msg)
        assert len(store.messages) == 1
        assert store.messages[0]["data"]["tool_name"] == "read_file"

    def test_merge_tool_call_updates(self, store):
        """Test merging tool call updates (same tool_call_id)."""
        # First message: tool call started
        msg1 = {
            "message_id": "msg-2",
            "message_type": "tool_call",
            "data": {
                "tool_call_id": "tc-1",
                "tool_name": "read_file",
                "arguments": {"path": "/tmp/test.txt"},
                # no result yet
            },
        }
        # Second message: tool call completed with result
        msg2 = {
            "message_id": "msg-2",
            "message_type": "tool_call",
            "data": {
                "tool_call_id": "tc-1",
                "result": "file content here",
                "status": True,
            },
        }

        store._add_message(msg1)
        assert len(store.messages) == 1
        assert "result" not in store.messages[0]["data"]

        store._add_message(msg2)
        assert len(store.messages) == 1  # still one message (merged)
        assert store.messages[0]["data"]["result"] == "file content here"
        assert store.messages[0]["data"]["status"] is True

    def test_merge_agent_chunks(self, store):
        """Test merging agent response chunks."""
        chunks = [
            {
                "message_id": "msg-3",
                "message_type": "agent_response",
                "data": {"content": '{"content": "Hello ", "reasoning_content": "", "index": 0}'},
            },
            {
                "message_id": "msg-3",
                "message_type": "agent_response",
                "data": {"content": '{"content": "World!", "reasoning_content": "", "index": 1}'},
            },
        ]

        merged = store._merge_agent_chunks(chunks)
        assert merged["content"] == "Hello World!"
        assert merged["reasoning_content"] == ""

    def test_merge_agent_chunks_with_reasoning(self, store):
        """Test merging agent response chunks with reasoning."""
        chunks = [
            {
                "message_id": "msg-4",
                "message_type": "agent_response",
                "data": {"content": '{"content": "Answer", "reasoning_content": "Think ", "index": 0}'},
            },
            {
                "message_id": "msg-4",
                "message_type": "agent_response",
                "data": {"content": '{"content": "", "reasoning_content": "step by step", "index": 1}'},
            },
        ]

        merged = store._merge_agent_chunks(chunks)
        assert merged["content"] == "Answer"
        assert merged["reasoning_content"] == "Think step by step"

    def test_agent_response_chunk_merging(self, store):
        """Test that agent response chunks are merged in the messages list."""
        msg1 = {
            "message_id": "msg-3",
            "message_type": "agent_response",
            "data": {"content": '{"content": "Hello ", "reasoning_content": "", "index": 0}'},
        }
        msg2 = {
            "message_id": "msg-3",
            "message_type": "agent_response",
            "data": {"content": '{"content": "World!", "reasoning_content": "", "index": 1}'},
        }

        store._add_message(msg1)
        assert len(store.messages) == 1

        store._add_message(msg2)
        assert len(store.messages) == 1  # still one message (merged)
        import json
        merged_content = json.loads(store.messages[0]["data"]["content"])
        assert merged_content["content"] == "Hello World!"


# ============================================================================
# CrewStore Tests
# ============================================================================

class TestCrewStore:
    """Test CrewStore functionality."""

    @pytest.fixture
    def store(self):
        s = CrewStore()
        s._api = AsyncMock()
        return s

    @pytest.mark.asyncio
    async def test_load_executions_populates_list(self, store):
        """Test that load_executions populates execution list."""
        mock_execs = [
            {"execution_id": "e1", "crew_name": "Crew 1", "status": "completed"},
            {"execution_id": "e2", "crew_name": "Crew 2", "status": "running"},
        ]
        store._api.list_executions.return_value = {
            "executions": mock_execs,
            "total": 2,
        }

        await store.load_executions(session_id="session-1")
        assert len(store.executions) == 2
        assert store.total == 2
        assert store.session_id_filter == "session-1"

    @pytest.mark.asyncio
    async def test_load_executions_with_status_filter(self, store):
        """Test loading executions with status filter."""
        store._api.list_executions.return_value = {"executions": [], "total": 0}

        await store.load_executions(status="running")
        assert store.status_filter == "running"

    @pytest.mark.asyncio
    async def test_submit_execution_with_running_check(self, store):
        """Test that submit blocks when a running execution exists."""
        store.executions = [
            {"execution_id": "e1", "session_id": "session-1", "status": "running"},
        ]

        result = await store.submit_execution(session_id="session-1", yaml_path="/tmp/test.yaml")
        assert result is None  # blocked

    @pytest.mark.asyncio
    async def test_submit_execution_success(self, store):
        """Test successful submission."""
        store._api.submit_execution.return_value = {
            "execution_id": "e-new",
            "status": "pending",
        }
        store._api.list_executions.return_value = {
            "executions": [{"execution_id": "e-new", "status": "pending"}],
            "total": 1,
        }

        result = await store.submit_execution(session_id="session-1", yaml_path="/tmp/test.yaml")
        assert result is not None
        assert result["execution_id"] == "e-new"

    @pytest.mark.asyncio
    async def test_abort_execution_updates_local_state(self, store):
        """Test that abort updates local execution status."""
        store.executions = [
            {"execution_id": "e1", "status": "running"},
        ]
        store._api.abort_execution.return_value = {"execution_id": "e1"}

        result = await store.abort_execution("e1")
        assert result is True
        assert store.executions[0]["status"] == "aborted"

    @pytest.mark.asyncio
    async def test_delete_execution_removes_from_list(self, store):
        """Test that delete removes execution from local list."""
        store.executions = [
            {"execution_id": "e1"},
            {"execution_id": "e2"},
        ]
        store.total = 2
        store._api.delete_execution.return_value = {"execution_id": "e1"}

        result = await store.delete_execution("e1")
        assert result is True
        assert len(store.executions) == 1
        assert store.total == 1

    def test_update_execution_status(self, store):
        """Test updating execution status for real-time progress."""
        store.executions = [
            {"execution_id": "e1", "status": "running"},
            {"execution_id": "e2", "status": "pending"},
        ]

        store.update_execution_status("e1", "completed")
        assert store.executions[0]["status"] == "completed"
        assert store.executions[1]["status"] == "pending"  # unchanged

    def test_update_execution_status_not_found(self, store):
        """Test updating non-existent execution does nothing."""
        store.update_execution_status("nonexistent", "completed")  # should not raise
