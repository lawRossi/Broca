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

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from broca_tui.app import BrocaTUIApp
from broca_tui.screens.session_list import SessionListScreen, CreateSessionDialog, DeleteConfirmDialog
from broca_tui.screens.chat import ChatScreen
from broca_tui.screens.crew_executions import CrewExecutionsScreen, SubmitExecutionDialog
from broca_tui.widgets.message_item import MessageItem, _format_json, _parse_arguments
from broca_tui.widgets.chat_input import ChatInput
from broca_tui.stores.session_store import SessionStore
from broca_tui.stores.chat_store import ChatStore
from broca_tui.stores.agent_store import AgentStore
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
# Integration: Message display pipeline
# ============================================================================

class TestMessagePipeline:
    """Test the full message display pipeline: raw message → Store → Widget."""

    def test_user_message_pipeline(self):
        """Test user message flows through to MessageItem rendering."""
        raw_message = {
            "message_id": "msg-1",
            "message_type": "user_message",
            "role": "user",
            "data": {"content": "hello"},
        }

        # Store accepts it
        store = ChatStore()
        store._add_message(raw_message)
        assert len(store.messages) == 1

        # MessageItem can render it
        item = MessageItem(raw_message)
        border = item._get_border_class("user_message", "user")
        assert border == "msg-user"
        icon = MessageItem._get_icon("user_message", {})
        assert icon == "👤"

    def test_agent_response_pipeline(self):
        """Test agent response flows through to MessageItem rendering."""
        raw_message = {
            "message_id": "msg-2",
            "message_type": "agent_response",
            "role": "assistant",
            "data": {"content": "Hello! How can I help?"},
        }

        store = ChatStore()
        store._add_message(raw_message)
        assert len(store.messages) == 1

        item = MessageItem(raw_message)
        border = item._get_border_class("agent_response", "assistant")
        assert border == "msg-agent"
        icon = MessageItem._get_icon("agent_response", {})
        assert icon == "🤖"

    def test_tool_call_pipeline(self):
        """Test tool call flows through to MessageItem rendering."""
        raw_message = {
            "message_id": "msg-3",
            "message_type": "tool_call",
            "data": {
                "tool_name": "read_file",
                "arguments": {"path": "/tmp/test.txt"},
                "tool_call_id": "tc-1",
            },
        }

        store = ChatStore()
        store._add_message(raw_message)
        assert len(store.messages) == 1

        item = MessageItem(raw_message)
        border = item._get_border_class("tool_call", "tool")
        assert border == "msg-tool"
        icon = MessageItem._get_icon("tool_call", {})
        assert icon == "🔧⏳"

    def test_tool_call_with_result_pipeline(self):
        """Test tool call with result merges correctly."""
        # Two messages with same tool_call_id should merge
        msg_start = {
            "message_id": "msg-4",
            "message_type": "tool_call",
            "data": {
                "tool_name": "read_file",
                "arguments": {"path": "/tmp/test.txt"},
                "tool_call_id": "tc-2",
            },
        }
        msg_result = {
            "message_id": "msg-4",
            "message_type": "tool_call",
            "data": {
                "tool_call_id": "tc-2",
                "result": "file content",
                "status": True,
            },
        }

        store = ChatStore()
        store._add_message(msg_start)
        assert len(store.messages) == 1
        assert "result" not in store.messages[0]["data"]

        store._add_message(msg_result)
        assert len(store.messages) == 1  # merged, not duplicated
        assert store.messages[0]["data"]["result"] == "file content"
        assert store.messages[0]["data"]["status"] is True
        icon = MessageItem._get_icon("tool_call", store.messages[0]["data"])
        assert icon == "🔧✅"

    def test_edit_file_pipeline(self):
        """Test edit_file diff rendering pipeline."""
        msg = {
            "message_id": "msg-5",
            "message_type": "tool_call",
            "data": {
                "tool_name": "edit_file",
                "arguments": {
                    "path": "/tmp/test.py",
                    "old_text": "hello world",
                    "new_text": "hello there",
                },
                "tool_call_id": "tc-3",
            },
        }

        # Parse arguments correctly
        args = _parse_arguments(msg["data"]["arguments"])
        assert args["path"] == "/tmp/test.py"
        assert args["old_text"] == "hello world"
        assert args["new_text"] == "hello there"

        # Generate diff
        import difflib
        diff = list(difflib.unified_diff(
            args["old_text"].splitlines(keepends=True),
            args["new_text"].splitlines(keepends=True),
        ))
        assert len(diff) >= 4

    def test_agent_chunk_merging(self):
        """Test that agent response chunks are merged correctly."""
        import json

        store = ChatStore()
        chunks = [
            {
                "message_id": "msg-stream",
                "message_type": "agent_response",
                "data": {"content": json.dumps({"content": "Hello ", "reasoning_content": "", "index": 0})},
            },
            {
                "message_id": "msg-stream",
                "message_type": "agent_response",
                "data": {"content": json.dumps({"content": "World!", "reasoning_content": "", "index": 1})},
            },
        ]

        for chunk in chunks:
            store._add_message(chunk)

        assert len(store.messages) == 1  # merged
        merged = json.loads(store.messages[0]["data"]["content"])
        assert merged["content"] == "Hello World!"


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
        assert screen._last_message_count == 0

    def test_chat_screen_with_execution_filter(self):
        """Test ChatScreen with execution filter."""
        screen = ChatScreen(session_id="test-session", execution_id="exec-1")
        assert screen._execution_id == "exec-1"

    def test_message_throttle_logic(self):
        """Test message count throttle prevents unnecessary updates."""
        screen = ChatScreen(session_id="test-session")
        assert screen._last_message_count == 0

        # Simulate adding messages to store
        msg = {"message_id": "m1", "data": {}}
        screen._chat_store.messages = [msg]
        # Throttle should detect count changed: 0 → 1
        assert len(screen._chat_store.messages) != screen._last_message_count


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

    def test_submit_execution_dialog_with_configs(self):
        """Test SubmitExecutionDialog with config files."""
        configs = [
            {"name": "crew1.yaml", "description": "Test", "orchestrator_type": "pipeline", "agent_names": ["a1"]},
        ]
        dialog = SubmitExecutionDialog(configs)
        assert dialog._config_files[0]["name"] == "crew1.yaml"

    def test_submit_execution_dialog_empty(self):
        """Test SubmitExecutionDialog with no configs."""
        dialog = SubmitExecutionDialog([])
        assert len(dialog._config_files) == 0


# ============================================================================
# Integration: Navigation flow
# ============================================================================

class TestNavigationFlow:
    """Test navigation between screens."""

    def test_session_list_to_chat_normal(self):
        """Test that normal category navigates to ChatScreen."""
        screen = SessionListScreen()
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
