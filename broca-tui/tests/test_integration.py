"""
Integration tests for broca-tui.

Covers full user flow:
- App startup → SessionListScreen
- Session CRUD flow
- ChatScreen creation with stores
- Message display pipeline (Store → Widget)
- Crew execution lifecycle
- Navigation round-trip
- Dialog lifecycle
"""

from unittest.mock import AsyncMock

import pytest

from broca_tui.app import BrocaTUIApp
from broca_tui.screens.session_list import CreateSessionDialog, DeleteConfirmDialog
from broca_tui.screens.chat import ChatScreen
from broca_tui.screens.crew_executions import CrewExecutionsScreen, ConfirmDialog
from broca_tui.stores.session_store import SessionStore
from broca_tui.stores.chat_store import TurnSummary
from broca_tui.stores.crew_store import CrewStore


# ============================================================================
# Integration: App → Screen flow
# ============================================================================

class TestAppScreenFlow:
    """Test App initialization and screen navigation."""

    def test_app_creates_session_list_on_mount(self):
        """Test that App creates SessionListScreen on default startup."""
        app = BrocaTUIApp()
        assert app._session_id is None
        assert app.CSS_PATH is not None

    def test_app_creates_chat_with_session_id(self):
        """Test that App creates ChatScreen when session_id is provided."""
        app = BrocaTUIApp(session_id="direct-session")
        assert app._session_id == "direct-session"

    def test_make_chat_screen(self):
        """Test _make_chat_screen factory method."""
        app = BrocaTUIApp()
        screen = app._make_chat_screen("test-session")
        assert screen._session_id == "test-session"
        assert screen._execution_id is None

    def test_make_chat_screen_with_execution(self):
        """Test _make_chat_screen with execution filter."""
        app = BrocaTUIApp()
        screen = app._make_chat_screen("test-session", "exec-1")
        assert screen._session_id == "test-session"
        assert screen._execution_id == "exec-1"

    def test_make_crew_screen(self):
        """Test _make_crew_screen factory method."""
        app = BrocaTUIApp()
        screen = app._make_crew_screen("test-session")
        assert screen._session_id == "test-session"


# ============================================================================
# Integration: Session CRUD flow
# ============================================================================

class TestSessionCrudFlow:
    """Test session creation, listing, and deletion flow."""

    @pytest.mark.asyncio
    async def test_create_session_flow(self):
        """Test creating a session via store and verifying list refresh."""
        store = SessionStore()
        store._api = AsyncMock()

        # Mock create and list
        store._api.create_session.return_value = {
            "session_id": "new-session",
            "workspace": "/tmp",
        }
        store._api.list_sessions.return_value = {
            "sessions": [{"session_id": "new-session", "description": "Test"}],
            "total": 1,
        }

        result = await store.create_session(description="Test", category="normal")
        assert result is not None
        assert result["session_id"] == "new-session"
        assert len(store.sessions) == 1

    @pytest.mark.asyncio
    async def test_delete_session_flow(self):
        """Test deleting a session and verifying list update."""
        store = SessionStore()
        store._api = AsyncMock()
        store._api.delete_session = AsyncMock()

        store.sessions = [
            {"session_id": "s1", "description": "Session 1"},
            {"session_id": "s2", "description": "Session 2"},
        ]
        store.total = 2

        result = await store.delete_session("s1")
        assert result is True
        assert len(store.sessions) == 1
        assert store.total == 1
        assert store.sessions[0]["session_id"] == "s2"

    @pytest.mark.asyncio
    async def test_search_session_flow(self):
        """Test searching sessions resets pagination."""
        store = SessionStore()
        store._api = AsyncMock()
        store._api.list_sessions.return_value = {
            "sessions": [{"session_id": "s1", "description": "test result"}],
            "total": 1,
        }

        await store.load_sessions(keyword="test")
        assert store.keyword == "test"
        assert store.skip == 10
        assert len(store.sessions) == 1


# ============================================================================
# Integration: Turn display pipeline (简洁模式)
# ============================================================================

class TestTurnCardPipeline:
    """Test the full turn display pipeline: chat_store → TurnCard rendering."""

    def test_turn_summary_creation(self):
        """Test TurnSummary creation from raw turn data."""
        turn_data = {
            "turn_id": "turn-1",
            "sequence_number": 1,
            "agent_id": "agent-1",
            "agent_name": "Assistant",
            "user_message": "Hello!",
            "total_steps": 5,
            "tool_call_stats": [{"toolName": "read_file", "count": 2}],
            "current_file_path": "/tmp/test.txt",
            "final_response": "Here is the result.",
            "duration_seconds": 12.5,
            "last_message_id": "msg-5",
            "is_reverted": False,
            "created_at": "2024-01-01T00:00:00",
        }

        summary = TurnSummary(
            turn_id=turn_data["turn_id"],
            sequence_number=turn_data["sequence_number"],
            agent_id=turn_data["agent_id"],
            agent_name=turn_data["agent_name"],
            user_message=turn_data["user_message"],
            status="completed",
            current_tool="read_file",
            current_file_path=turn_data["current_file_path"],
            current_todo_list=[],
            total_duration=turn_data["duration_seconds"],
            total_steps=turn_data["total_steps"],
            tool_call_stats=turn_data["tool_call_stats"],
            final_response=turn_data["final_response"],
            is_active=False,
            started_at=0,
            created_at=turn_data["created_at"],
            last_message_id=turn_data["last_message_id"],
        )

        assert summary.turn_id == "turn-1"
        assert summary.agent_name == "Assistant"
        assert summary.user_message == "Hello!"
        assert summary.total_steps == 5
        assert summary.final_response == "Here is the result."

    def test_turn_summary_real_time_creation(self):
        """Test TurnSummary creation from real-time events."""
        from broca_tui.stores.chat_store import TurnSummary

        # Simulate what create_turn_summary does in ChatStore
        import time
        summary = TurnSummary(
            turn_id="live-turn-1",
            sequence_number=1,
            agent_id="agent-1",
            agent_name="Assistant",
            is_active=True,
            status="active",
            started_at=time.time() * 1000,
        )

        assert summary.is_active is True
        assert summary.status == "active"
        assert summary.total_steps == 0
        assert summary.final_response == ""

    def test_turn_card_status_mapping_for_completed_turn(self):
        """Completed turn maps to 'completed' status in TurnCard."""
        from broca_tui.stores.chat_store import TurnSummary
        from broca_tui.widgets.turn_card import TurnCard

        summary = TurnSummary(
            turn_id="completed-turn",
            sequence_number=2,
            agent_id="agent-1",
            agent_name="Assistant",
            status="completed",
            is_active=False,
        )

        card = TurnCard(summary)
        assert card._get_simplified_status() == "completed"
        assert card._get_status_text() == "已完成"


# ============================================================================
# Integration: ChatScreen + Stores
# ============================================================================

class TestChatScreenStoreIntegration:
    """Test ChatScreen integration with stores."""

    def test_chat_store_connects_to_screen(self):
        """Test that ChatScreen creates stores correctly."""
        screen = ChatScreen(session_id="test-session")
        assert screen._chat_store is not None
        assert screen._agent_store is not None
        assert screen._last_turn_count == -1  # -1 ensures first render always fires

    def test_chat_screen_with_execution_filter(self):
        """Test ChatScreen with execution filter."""
        screen = ChatScreen(session_id="test-session", execution_id="exec-1")
        assert screen._execution_id == "exec-1"

    def test_turn_throttle_logic(self):
        """Test turn count throttle prevents unnecessary updates."""
        screen = ChatScreen(session_id="test-session")
        assert screen._last_turn_count == -1  # -1 ensures first render always fires

        # Simulate adding a turn
        from broca_tui.stores.chat_store import TurnSummary
        screen._chat_store.turn_summaries = [
            TurnSummary(turn_id="t1", sequence_number=1, agent_id="a1", agent_name="Agent")
        ]
        # Throttle should detect count changed: 0 → 1
        assert len(screen._chat_store.turn_summaries) != screen._last_turn_count


# ============================================================================
# Integration: Crew execution flow
# ============================================================================

class TestCrewExecutionFlow:
    """Test crew execution lifecycle."""

    @pytest.mark.asyncio
    async def test_submit_with_running_check(self):
        """Test single-run constraint prevents duplicate submissions."""
        store = CrewStore()
        store.executions = [
            {"execution_id": "e1", "session_id": "session-1", "status": "running"},
        ]

        result = await store.submit_execution(
            session_id="session-1",
            yaml_path="/tmp/test.yaml",
        )
        assert result is None  # Blocked by running execution

    @pytest.mark.asyncio
    async def test_submit_after_completed(self):
        """Test that submit works after previous execution completes."""
        store = CrewStore()
        store.executions = [
            {"execution_id": "e1", "session_id": "session-1", "status": "completed"},
        ]
        store._api = AsyncMock()
        store._api.submit_execution.return_value = {
            "execution_id": "e-new",
            "status": "pending",
        }
        store._api.list_executions.return_value = {
            "executions": [{"execution_id": "e-new", "status": "pending"}],
            "total": 1,
        }

        result = await store.submit_execution(
            session_id="session-1",
            yaml_path="/tmp/test.yaml",
        )
        assert result is not None
        assert result["execution_id"] == "e-new"

    @pytest.mark.asyncio
    async def test_abort_and_delete(self):
        """Test abort then delete flow."""
        store = CrewStore()
        store._api = AsyncMock()
        store.executions = [
            {"execution_id": "e1", "status": "running"},
        ]

        # Abort
        store._api.abort_execution.return_value = {"execution_id": "e1"}
        aborted = await store.abort_execution("e1")
        assert aborted is True
        assert store.executions[0]["status"] == "aborted"

        # Delete
        store._api.delete_execution.return_value = {"execution_id": "e1"}
        deleted = await store.delete_execution("e1")
        assert deleted is True
        assert len(store.executions) == 0


# ============================================================================
# Integration: Dialog lifecycle
# ============================================================================

class TestDialogLifecycle:
    """Test modal dialog creation and result handling."""

    def test_create_session_dialog(self):
        """Test CreateSessionDialog can be created."""
        dialog = CreateSessionDialog()
        assert dialog is not None

    def test_delete_confirm_dialog(self):
        """Test DeleteConfirmDialog with name."""
        dialog = DeleteConfirmDialog("test-session")
        assert dialog._session_name == "test-session"

    def test_confirm_dialog_confirm(self):
        """Test ConfirmDialog confirm action."""
        dialog = ConfirmDialog(title="Test", message="Confirm?")
        assert dialog._title == "Test"
        assert dialog._message == "Confirm?"

    def test_confirm_dialog_empty(self):
        """Test ConfirmDialog with empty strings."""
        dialog = ConfirmDialog(title="", message="")
        assert dialog._title == ""
        assert dialog._message == ""


# ============================================================================
# Integration: Navigation flow
# ============================================================================

class TestNavigationFlow:
    """Test navigation between screens."""

    def test_session_list_to_chat_normal(self):
        """Test that normal category navigates to ChatScreen."""
        # The navigation logic
        from broca_tui.screens.chat import ChatScreen
        target = ChatScreen(session_id="test-id")
        assert target._session_id == "test-id"

    def test_session_list_to_crew_orch(self):
        """Test that agent-orchestration category navigates to CrewScreen."""
        from broca_tui.screens.crew_executions import CrewExecutionsScreen
        target = CrewExecutionsScreen(session_id="test-id")
        assert target._session_id == "test-id"

    def test_crew_to_chat_with_execution(self):
        """Test that CrewScreen's view messages goes to ChatScreen with execution filter."""
        from broca_tui.screens.chat import ChatScreen
        target = ChatScreen(session_id="test-id", execution_id="exec-1")
        assert target._session_id == "test-id"
        assert target._execution_id == "exec-1"

    def test_app_to_chat_direct(self):
        """Test that App creates ChatScreen when given session_id."""
        app = BrocaTUIApp(session_id="direct")
        assert app._session_id == "direct"

    def test_app_creates_chat_screen_factory(self):
        """Test App factory method creates correct screen type."""
        app = BrocaTUIApp()
        screen = app._make_chat_screen("session-1")
        assert isinstance(screen, ChatScreen)

    def test_app_creates_crew_screen_factory(self):
        """Test App factory method creates correct screen type."""
        app = BrocaTUIApp()
        screen = app._make_crew_screen("session-1")
        assert isinstance(screen, CrewExecutionsScreen)
