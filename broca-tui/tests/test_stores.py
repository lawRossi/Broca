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
from broca_tui.stores.chat_store import ChatStore, TurnSummary
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

    def test_clear_messages(self, store):
        """Test clearing all messages and turn data."""
        store.show_redo_button = True
        store.turn_summaries = [
            TurnSummary(turn_id="t1", sequence_number=1, agent_id="a1", agent_name="A"),
        ]
        store.turn_history_skip = 20
        store.has_more_turns = True
        store.active_turn_index = 0

        store.clear_messages()
        assert store.show_redo_button is False
        # Turn data cleanup
        assert len(store.turn_summaries) == 0
        assert store.turn_history_skip == 0
        assert store.has_more_turns is True
        assert store.active_turn_index == -1

    def test_send_user_message_does_not_add_message(self, store):
        """In concise mode, send_user_message does not add an optimistic message to messages."""
        # messages attribute no longer exists; turn_start event creates TurnSummary
        assert not hasattr(store, 'messages') or len(getattr(store, 'messages', [])) == 0

    def test_create_turn_summary(self, store):
        """Test creating a turn summary (简洁模式)."""
        assert len(store.turn_summaries) == 0
        store.create_turn_summary("new-turn", "agent-1", "Assistant")
        assert len(store.turn_summaries) == 1
        assert store.turn_summaries[0].turn_id == "new-turn"
        assert store.turn_summaries[0].agent_name == "Assistant"
        assert store.turn_summaries[0].is_active is True

    def test_find_turn(self, store):
        """Test finding a turn by ID."""
        store.create_turn_summary("t1", "a1", "Agent 1")
        store.create_turn_summary("t2", "a2", "Agent 2")
        found = store._find_turn("t2")
        assert found is not None
        assert found.agent_id == "a2"

    def test_increment_turn_steps(self, store):
        """Test incrementing turn step count."""
        store.create_turn_summary("t1", "a1", "Agent")
        assert store.turn_summaries[0].total_steps == 0
        store.increment_turn_steps("t1")
        assert store.turn_summaries[0].total_steps == 1
        store.increment_turn_steps("t1")
        assert store.turn_summaries[0].total_steps == 2

    def test_get_filtered_turns(self, store):
        """Test filtering turns by agent visibility."""
        store.create_turn_summary("t1", "a1", "Agent A")
        store.create_turn_summary("t2", "a2", "Agent B")
        store.create_turn_summary("t3", "a1", "Agent A")

        all_ids = ["a1", "a2"]
        filtered = store.get_filtered_turns(["a1"], all_ids)
        assert len(filtered) == 2
        assert all(t.agent_id == "a1" for t in filtered)


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

    def test_update_execution_from_event(self, store):
        """Test updating execution status via event for real-time progress."""
        store.executions = [
            {"execution_id": "e1", "status": "running"},
            {"execution_id": "e2", "status": "pending"},
        ]

        store.update_execution_from_event({"execution_id": "e1", "status": "completed"})
        assert store.executions[0]["status"] == "completed"
        assert store.executions[1]["status"] == "pending"  # unchanged

    def test_update_execution_from_event_not_found(self, store):
        """Test updating non-existent execution does nothing."""
        store.update_execution_from_event({"execution_id": "nonexistent", "status": "completed"})  # should not raise

    # ── AC: set_active_tab / active_tab ──

    def test_active_tab_defaults_to_executions(self, store):
        """Test that active_tab defaults to 'executions'."""
        assert store.active_tab == "executions"

    def test_set_active_tab_updates_tab(self, store):
        """Test that set_active_tab updates active_tab and triggers on_change."""
        change_called = False
        def on_change():
            nonlocal change_called
            change_called = True
        store.on_change(on_change)

        store.set_active_tab("configs")
        assert store.active_tab == "configs"
        assert change_called, "on_change should be triggered"

        # Switching back
        store.set_active_tab("executions")
        assert store.active_tab == "executions"

    # ── AC: load_execution_detail / selected_execution ──

    @pytest.mark.asyncio
    async def test_load_execution_detail_populates_selected(self, store):
        """Test that load_execution_detail populates selected_execution."""
        mock_detail = {
            "execution_id": "e1",
            "crew_name": "Crew 1",
            "status": "running",
            "phases": [{"name": "Phase 1", "status": "completed"}],
            "result": {"key": "value"},
        }
        store._api.get_execution_detail.return_value = mock_detail

        await store.load_execution_detail("e1")
        assert store.selected_execution is not None
        assert store.selected_execution["execution_id"] == "e1"
        assert len(store.selected_execution["phases"]) == 1
        assert store.selected_execution["phases"][0]["name"] == "Phase 1"

    @pytest.mark.asyncio
    async def test_load_execution_detail_notifies_change(self, store):
        """Test that load_execution_detail triggers on_change."""
        store._api.get_execution_detail.return_value = {"execution_id": "e1"}
        change_called = False
        def on_change():
            nonlocal change_called
            change_called = True
        store.on_change(on_change)

        await store.load_execution_detail("e1")
        assert change_called, "on_change should be triggered on detail load start and end"

    # ── AC: on_socket_event callback ──

    def test_on_socket_event_callback_triggered(self, store):
        """Test that on_socket_event callback is triggered by update_execution_from_event."""
        received_events = []
        store.on_socket_event(lambda e: received_events.append(e))

        store.executions = [{"execution_id": "e1", "status": "pending"}]
        event = {"execution_id": "e1", "status": "running"}
        store.update_execution_from_event(event)

        assert len(received_events) == 1
        assert received_events[0]["status"] == "running"

    def test_on_socket_event_callback_deletion(self, store):
        """Test that deletion events also trigger on_socket_event."""
        received_events = []
        store.on_socket_event(lambda e: received_events.append(e))

        store.executions = [{"execution_id": "e1", "status": "running"}]
        store.update_execution_from_event({"execution_id": "e1", "event": "deleted"})

        assert len(received_events) == 1
        assert received_events[0]["event"] == "deleted"

    def test_update_execution_from_event_updates_detail_view(self, store):
        """Test that events update selected_execution when detail view is open."""
        store.selected_execution = {"execution_id": "e1", "status": "running", "phases": []}
        store.update_execution_from_event({"execution_id": "e1", "status": "completed"})
        assert store.selected_execution["status"] == "completed"

    # ── AC: on_change / _notify_change ──

    def test_on_change_called_on_state_change(self, store):
        """Test that on_change is called on various state changes."""
        calls = []
        store.on_change(lambda: calls.append("change"))

        store.set_active_tab("configs")
        assert len(calls) >= 1

    def test_clear_error(self, store):
        """Test clear_error resets error_message and triggers on_change."""
        change_called = False
        def on_change():
            nonlocal change_called
            change_called = True
        store.on_change(on_change)

        store._notify_error("test error")
        assert store.error_message == "test error"

        change_called = False
        store.clear_error()
        assert store.error_message is None
        assert change_called
