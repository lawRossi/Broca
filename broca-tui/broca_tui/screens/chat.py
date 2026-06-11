"""
ChatScreen — Main chat interface.

Three-panel layout:
- Left: AgentSidebar (agent list & management)
- Center: MessageList + ChatInput
- Right: InfoSidebar (session info, runner, stats)

Manages Socket.IO lifecycle, event callbacks, and navigation.
"""

from __future__ import annotations

from typing import Any, Dict, Optional

from textual.app import ComposeResult
from textual.containers import Horizontal, Vertical
from textual.screen import Screen

from broca_tui.stores.agent_store import AgentStore
from broca_tui.stores.chat_store import ChatStore
from broca_tui.widgets.agent_query_dialog import AgentQueryDialog
from broca_tui.widgets.agent_sidebar import AbortAgent, AgentSidebar
from broca_tui.widgets.chat_header import ChatHeader
from broca_tui.widgets.chat_input import ChatInput
from broca_tui.widgets.info_sidebar import InfoSidebar
from broca_tui.widgets.message_list import MessageList
from broca_tui.widgets.permission_dialog import PermissionDialog


class ChatScreen(Screen):
    """Main chat interface with three-panel layout."""

    BINDINGS = [
        ("ctrl+s", "go_to_sessions", "会话列表"),
        ("ctrl+e", "go_to_crew", "编排管理"),
        ("ctrl+l", "toggle_left_sidebar", "左侧栏"),
        ("ctrl+r", "toggle_right_sidebar", "右侧栏"),
    ]

    def __init__(
        self,
        session_id: str = "",
        execution_id: Optional[str] = None,
        **kwargs,
    ):
        """Initialize chat screen.

        Args:
            session_id: Session ID to connect to
            execution_id: Optional execution ID for message filtering
        """
        super().__init__(**kwargs)
        self._session_id = session_id
        self._execution_id = execution_id
        self._category = "normal"

        # Stores
        self._chat_store = ChatStore()
        self._agent_store = AgentStore()

        # Update throttle
        self._last_message_count = -1  # -1 ensures first _on_chat_change always renders

    def compose(self) -> ComposeResult:
        """Create the three-panel layout."""
        with Vertical(classes="chat-screen"):
            # Header
            yield ChatHeader(session_id=self._session_id, id="chat-header")

            # Main content: three panels
            with Horizontal(classes="chat-content", id="chat-content"):
                # Left: Agent sidebar
                yield AgentSidebar(
                    store=self._agent_store, id="agent-sidebar", classes="sidebar"
                )

                # Center: Messages + Input
                with Vertical(classes="main-content"):
                    yield MessageList(id="message-list")
                    yield ChatInput(id="chat-input", classes="chat-input-container")

                # Right: Info sidebar
                yield InfoSidebar(
                    session_id=self._session_id,
                    chat_store=self._chat_store,
                    id="info-sidebar",
                    classes="sidebar sidebar-right",
                )

    def on_mount(self) -> None:
        """Connect to Socket.IO and load data on mount."""
        header = self.query_one("#chat-header", ChatHeader)

        # Set execution filter display
        if self._execution_id:
            header.set_execution_filter(self._execution_id)

        # Connect stores to widgets
        self._setup_connections()

        # Force the initial layout to be computed correctly.
        # During _setup_connections, widget queries and reactive updates can
        # cause Textual to compute MessageList size as (0, 0) because the CSS
        # cascade hasn't completed yet. Updating a widget here forces Textual
        # to recompute the layout with the correct constraints.

        # Load agents and connect Socket.IO after initial layout refresh.
        # call_after_refresh defers widget queries until layout is stable,
        # avoiding MessageList size (0, 0) during mount.
        self.call_after_refresh(self._deferred_connect)

    def _deferred_connect(self):
        """Deferred connection — runs after initial layout is stable."""
        self.run_worker(self._connect())

    async def _connect(self):
        """Connect Socket.IO and load all session data (independent paths)."""
        header = self.query_one("#chat-header", ChatHeader)
        message_list = self.query_one("#message-list", MessageList)
        info_sidebar = self.query_one("#info-sidebar", InfoSidebar)
        chat_input = self.query_one("#chat-input", ChatInput)
        agent_sidebar = self.query_one("#agent-sidebar", AgentSidebar)

        # Set session info
        header.set_session_id(self._session_id)
        message_list.set_session(self._session_id)
        info_sidebar.set_session(self._session_id)

        # ── Path 1: Connect Socket.IO (best-effort, independent of message loading) ──
        header.connection_status = "connecting"
        original_error_cb = self._chat_store._on_error
        self._chat_store._on_error = None
        try:
            await self._chat_store.connect(self._session_id, self._execution_id)
        except Exception:
            pass
        finally:
            self._chat_store._on_error = original_error_cb
            header.connection_status = "connected" if self._chat_store.connected else "disconnected"

        # ── Path 2: Load messages via HTTP (always, regardless of Socket.IO) ──
        await self._chat_store.load_history()

        # ── Path 3: Load agents via HTTP ──
        await self._agent_store.fetch_agents(self._session_id)

        # Default loaded agents to "idle"
        for agent in self._agent_store.agents:
            if agent.get("agent_status") in (None, "", "disconnected"):
                agent["agent_status"] = "idle"
        self._agent_store._notify_change()

        chat_input.set_agents(self._agent_store.agents)
        await agent_sidebar.load_agents(self._session_id)

    def _setup_connections(self):
        """Connect stores to widgets and register callbacks."""
        message_list = self.query_one("#message-list", MessageList)
        chat_input = self.query_one("#chat-input", ChatInput)

        # Chat store → MessageList
        self._chat_store.on_change(lambda: self._on_chat_change())
        self._chat_store.on_error(
            lambda msg: self.notify(msg, severity="error", timeout=5)
        )
        self._chat_store.on_permission_request(
            lambda d: self.run_worker(self._show_permission_dialog(d))
        )
        self._chat_store.on_agent_query(
            lambda d: self.run_worker(self._show_agent_query_dialog(d))
        )
        self._chat_store.on_message_received(lambda msg: self._on_message_received(msg))
        self._chat_store.on_connection_change(
            lambda connected: self._on_connection_change(connected)
        )

        # MessageList callbacks
        message_list.set_on_load_more(
            lambda: self.run_worker(self._load_more_history())
        )
        message_list.set_on_redo(
            lambda: self.run_worker(self._chat_store.send_user_message("/redo"))
        )

        # ChatInput callbacks
        chat_input.set_on_send(
            lambda text, target: self.run_worker(self._send_message(text, target))
        )

        # Set agents for @mention
        chat_input.set_agents(self._agent_store.agents)

    # ==================== Event Handlers ====================

    def _on_chat_change(self):
        """React to chat store state changes with throttled message updates."""
        # Defensive: widget queries may fail if callback fires before screen is fully mounted
        try:
            message_list = self.query_one("#message-list", MessageList)
            header = self.query_one("#chat-header", ChatHeader)
            info_sidebar = self.query_one("#info-sidebar", InfoSidebar)
            chat_input = self.query_one("#chat-input", ChatInput)
        except Exception:
            # Widgets not ready yet — skip this update cycle
            return

        # Sync loading state from chat store to message list
        message_list.loading = self._chat_store.loading

        # Throttled message list update: only replace when count changes.
        # _last_message_count starts at -1 so the first call always renders,
        # even when the API returns 0 messages (showing "等待消息..." empty state).
        current_count = len(self._chat_store.messages)
        if current_count != self._last_message_count:
            message_list.set_messages(self._chat_store.messages)
            self._last_message_count = current_count

        # Update connection status
        if self._chat_store.connected:
            header.connection_status = "connected"
        elif self._chat_store.connecting:
            header.connection_status = "connecting"
        else:
            header.connection_status = "disconnected"

        # Update redo button
        message_list.show_redo = self._chat_store.show_redo_button

        # Update runner status
        if self._chat_store.runner_alive:
            info_sidebar.runner_status = "alive"
            chat_input.disabled = False
        else:
            info_sidebar.runner_status = "dead"
            chat_input.disabled = True

        # Update message stats
        info_sidebar.update_message_stats(self._chat_store.messages)

    def _on_message_received(self, msg: Dict[str, Any]):
        """Handle new message from Socket.IO.

        Args:
            msg: Message dict
        """
        msg_type = msg.get("type", "")

        if msg_type == "turn_start":
            self._agent_store.update_agent_status(msg.get("agent_id", ""), "running")
        elif msg_type == "turn_end":
            self._agent_store.update_agent_status(msg.get("agent_id", ""), "idle")

    def _on_connection_change(self, connected: bool):
        """Handle connection state changes.

        Args:
            connected: Whether connected
        """
        if connected:
            self.run_worker(self._chat_store._fetch_runner_status())

    async def _load_more_history(self):
        """Load more message history."""
        await self._chat_store.load_history(is_load_more=True)

    async def _send_message(self, text: str, target_agent_id: Optional[str] = None):
        """Send a user message.

        Args:
            text: Message text
            target_agent_id: Optional target agent ID from @mention
        """
        await self._chat_store.send_user_message(
            content=text,
            target_agent_id=target_agent_id,
        )

    # ==================== Dialog Handlers ====================

    async def _show_permission_dialog(self, dialog_data: Dict[str, Any]):
        """Show permission request dialog.

        Args:
            dialog_data: Permission dialog state
        """
        dialog = PermissionDialog(
            message=dialog_data.get("message", ""),
            request_id=dialog_data.get("request_id"),
            sender_id=dialog_data.get("sender_id"),
            request_type=dialog_data.get("request_type", "general"),
        )
        result = await self.app.push_screen_wait(dialog)
        if result and result.get("action") == "permission_response":
            granted = result.get("granted", False)
            session_action = result.get("session_action")
            await self._chat_store.respond_permission(granted, session_action)

    async def _show_agent_query_dialog(self, dialog_data: Dict[str, Any]):
        """Show agent query dialog.

        Args:
            dialog_data: Query dialog state
        """
        dialog = AgentQueryDialog(
            question=dialog_data.get("question", ""),
            options=dialog_data.get("options", []),
            request_id=dialog_data.get("request_id"),
            sender_id=dialog_data.get("sender_id"),
        )
        result = await self.app.push_screen_wait(dialog)
        if result and result.get("action") == "user_answer":
            await self._chat_store.respond_user_answer(result.get("answer", ""))

    # ==================== Navigation ====================

    def action_go_to_sessions(self) -> None:
        """Navigate back to session list."""

        async def _go():
            await self._chat_store.disconnect()
            self.app.pop_screen()  # ChatScreen was pushed → pop returns to SessionListScreen

        self.run_worker(_go())

    def action_go_to_crew(self) -> None:
        """Navigate to crew execution management."""
        from broca_tui.screens.crew_executions import CrewExecutionsScreen

        async def _go():
            await self._chat_store.disconnect()
            # Pop ChatScreen, then push CrewExecutionsScreen
            self.app.pop_screen()
            crew_screen = CrewExecutionsScreen(session_id=self._session_id)
            self.app.push_screen(crew_screen)

        self.run_worker(_go())

    def action_toggle_left_sidebar(self) -> None:
        """Toggle left sidebar visibility."""
        sidebar = self.query_one("#agent-sidebar")
        sidebar.display = not sidebar.display

    def action_toggle_right_sidebar(self) -> None:
        """Toggle right sidebar visibility."""
        sidebar = self.query_one("#info-sidebar")
        sidebar.display = not sidebar.display

    # ==================== Message Handlers ====================

    def on_chat_header_navigate_to_sessions(
        self, event: ChatHeader.NavigateToSessions
    ) -> None:
        """Handle navigation to sessions from header."""
        self.action_go_to_sessions()

    def on_chat_header_navigate_to_crew(self, event: ChatHeader.NavigateToCrew) -> None:
        """Handle navigation to crew from header."""
        self.action_go_to_crew()

    def on_agent_sidebar_abort_agent(self, event: AbortAgent) -> None:
        """Handle agent abort from sidebar."""
        self.run_worker(self._chat_store.send_abort(event.agent_id))

    # ==================== Cleanup ====================

    async def stop_runner(self):
        """Stop the runner when exiting."""
        await self._chat_store.stop_runner()

    async def disconnect_all(self):
        """Disconnect all connections when exiting."""
        await self._chat_store.disconnect()

    def on_unmount(self) -> None:
        """Clean up on unmount."""
        self.run_worker(self._chat_store.close())
        self.run_worker(self._agent_store.close())
