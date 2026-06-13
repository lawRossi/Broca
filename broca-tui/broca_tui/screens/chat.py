"""
ChatScreen — Main chat interface (简洁模式).

Three-panel layout:
- Left: AgentSidebar (agent list & management)
- Center: MessageList (TurnCards) + ChatInput
- Right: InfoSidebar (session info, runner, stats via API)

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

from broca_tui.debug_log import log, clear as debug_clear


class ChatScreen(Screen):
    """Main chat interface with three-panel layout (简洁模式：TurnCard)."""

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

        # Update throttle (for filtered turn count)
        self._last_turn_count = -1

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

                # Center: Messages (TurnCards) + Input
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

        # Defer connection to after layout is stable
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

        # ── Path 1: Connect Socket.IO (best-effort, independent of turn loading) ──
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

        # ── Path 2: Load agents FIRST (so agent_name_map is ready when turns arrive) ──
        try:
            await self._agent_store.fetch_agents(self._session_id)

            # Default loaded agents to "idle"
            for agent in self._agent_store.agents:
                if agent.get("agent_status") in (None, "", "disconnected"):
                    agent["agent_status"] = "idle"
            self._agent_store._notify_change()

            chat_input.set_agents(
                self._agent_store.agents,
                main_agent_id=self._agent_store.current_agent_id or "",
            )
            await agent_sidebar.load_agents(self._session_id)
        except Exception as e:
            self.notify(f"Agent 加载失败: {e}", severity="warning", timeout=5)

        # ── Path 3: Load turn history via HTTP — 即使 agents 加载失败也应继续
        try:
            await self._chat_store.load_turn_history()
        except Exception as e:
            self.notify(f"加载 Turn 历史失败: {e}", severity="error", timeout=5)
        finally:
            # 确保 loading 状态被清除，避免"消息加载中"卡死
            self._chat_store.loading = False
            # 确保 agent name 回调可用
            self._chat_store.on_get_agent_name(
                lambda agent_id: self._agent_store.get_agent_name(agent_id)
            )

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

        # 简洁模式：注入 agent name 查询回调
        self._chat_store.on_get_agent_name(
            lambda agent_id: self._agent_store.get_agent_name(agent_id)
        )

        # MessageList callbacks (turn-based)
        message_list.set_on_load_more_turns(
            lambda: self.run_worker(self._load_more_turns())
        )
        message_list.set_on_undo(
            lambda turn_id: self.run_worker(self._handle_turn_undo(turn_id))
        )
        message_list.set_on_redo(
            lambda: self.run_worker(self._chat_store.send_redo(
                target_agent_id=self._agent_store.current_agent_id or "",
            ))
        )

        # Agent store → re-render turns when agent list/visibility changes
        self._agent_store.on_change(lambda: self._on_chat_change())
        self._agent_store.on_visibility_change(
            lambda: self._on_visibility_changed()
        )

        # ChatInput callbacks
        chat_input.set_on_send(
            lambda text, target: self.run_worker(self._send_message(text, target))
        )

        # Set agents for @mention, with main agent as default target
        chat_input.set_agents(
            self._agent_store.agents,
            main_agent_id=self._agent_store.current_agent_id or "",
        )

    # ==================== Event Handlers ====================

    def _on_chat_change(self):
        """React to chat store state changes with throttled turn updates."""
        try:
            message_list = self.query_one("#message-list", MessageList)
            header = self.query_one("#chat-header", ChatHeader)
            info_sidebar = self.query_one("#info-sidebar", InfoSidebar)
            chat_input = self.query_one("#chat-input", ChatInput)
        except Exception:
            return

        # Sync loading state from chat store to message list
        message_list.loading = self._chat_store.loading

        # Sync has_more so scroll check doesn't keep triggering
        message_list.has_more = self._chat_store.has_more_turns

        # Build agent_id → display_name map
        agent_name_map = {
            a.get("agent_id", ""): a.get("name", a.get("agent_id", ""))
            for a in self._agent_store.agents if a.get("agent_id")
        }

        # Get visible agent IDs
        visible_ids = self._agent_store.visible_agent_ids
        all_ids = [a.get("agent_id", "") for a in self._agent_store.agents if a.get("agent_id")]

        # 加载中时只更新 loading 状态，跳过 turn 渲染
        if not self._chat_store.loading:
            # Filter turns by agent visibility
            filtered_turns = self._chat_store.get_filtered_turns(visible_ids, all_ids)

            # 始终更新 turn 数据，不依赖 count throttling：
            # - 历史加载时 count 变化，需要渲染
            # - 实时更新时 turn 内部字段变化（tool_call / agent_response / turn_end），
            #   但 count 不变，仍需要重新渲染以反映最新数据
            current_count = len(filtered_turns)
            log(f" _on_chat_change: loading={self._chat_store.loading}, turn_count={current_count}, last_count={self._last_turn_count}, visible_ids={visible_ids}")
            message_list.set_turn_summaries(filtered_turns, agent_name_map)
            self._last_turn_count = current_count

        # Update connection status
        if self._chat_store.connected:
            header.connection_status = "connected"
        elif self._chat_store.connecting:
            header.connection_status = "connecting"
        else:
            header.connection_status = "disconnected"

        # Update redo button
        message_list.show_redo = self._chat_store.show_redo_button

        # Update runner status from ChatStore
        if self._chat_store.runner_alive:
            info_sidebar.runner_status = "alive"
            chat_input.disabled = False
        elif info_sidebar.runner_status == "alive":
            chat_input.disabled = False
        elif self._chat_store.runner_info:
            info_sidebar.runner_status = "dead"
            chat_input.disabled = True

        # ⚠️ InfoSidebar 消息统计不再通过本地 messages 计算
        # 改由 InfoSidebar 自己的 _poll_runner_status 中调用
        # GET /session/{id}/stats API 获取（见 Task 3.3）

    def _on_visibility_changed(self):
        """React to agent visibility changes — immediately refresh turn list."""
        try:
            message_list = self.query_one("#message-list", MessageList)
        except Exception:
            return

        # Build agent_name_map
        agent_name_map = {
            a.get("agent_id", ""): a.get("name", a.get("agent_id", ""))
            for a in self._agent_store.agents if a.get("agent_id")
        }

        visible_ids = self._agent_store.visible_agent_ids
        all_ids = [a.get("agent_id", "") for a in self._agent_store.agents if a.get("agent_id")]
        filtered_turns = self._chat_store.get_filtered_turns(visible_ids, all_ids)

        message_list.set_turn_summaries(filtered_turns, agent_name_map)
        self._last_turn_count = len(filtered_turns)

    def _on_message_received(self, msg: Dict[str, Any]):
        """Handle new message from Socket.IO (agent status updates).

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

    async def _load_more_turns(self):
        """Load more turn history."""
        await self._chat_store.load_turn_history(is_load_more=True)

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

    async def _handle_turn_undo(self, turn_id: str):
        """Handle turn-level undo.

        Finds the target turn from chat_store and sends turn-level undo.

        Args:
            turn_id: Turn ID to undo
        """
        target_agent_id = None
        last_message_id = None

        for turn in self._chat_store.turn_summaries:
            if turn.turn_id == turn_id:
                target_agent_id = turn.agent_id
                last_message_id = turn.last_message_id
                break

        if last_message_id:
            await self._chat_store.send_undo(
                target_message_id=last_message_id,
                target_agent_id=target_agent_id,
                level="turn",
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
            self.app.pop_screen()

        self.run_worker(_go())

    def action_go_to_crew(self) -> None:
        """Navigate to crew execution management."""
        from broca_tui.screens.crew_executions import CrewExecutionsScreen

        async def _go():
            await self._chat_store.disconnect()
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
        self.call_later(self._cleanup_api)

    async def _cleanup_api(self):
        """Close API sessions synchronously."""
        for store in (self._chat_store, self._agent_store):
            try:
                await store.close()
            except Exception:
                pass
