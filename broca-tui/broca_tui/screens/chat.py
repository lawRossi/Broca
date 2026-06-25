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
from broca_tui.widgets.agent_sidebar import AgentSidebar
from broca_tui.widgets.chat_header import ChatHeader
from broca_tui.widgets.chat_input import ChatInput
from broca_tui.widgets.info_sidebar import InfoSidebar
from broca_tui.widgets.message_list import MessageList
from broca_tui.widgets.orchestration_banner import OrchestrationBanner
from broca_tui.widgets.permission_dialog import PermissionDialog
from broca_tui.widgets.turn_card import TurnCard

from broca_tui.debug_log import log, clear as debug_clear


class ChatScreen(Screen):
    """Main chat interface with three-panel layout (简洁模式：TurnCard)."""

    BINDINGS = [
        ("ctrl+s", "go_to_sessions", "会话列表"),
        ("ctrl+l", "toggle_left_sidebar", "左侧栏"),
        ("ctrl+r", "toggle_right_sidebar", "右侧栏"),
    ]

    def __init__(
        self,
        session_id: str = "",
        execution_id: Optional[str] = None,
        category: str = "normal",
        **kwargs,
    ):
        """Initialize chat screen.

        Args:
            session_id: Session ID to connect to
            execution_id: Optional execution ID for message filtering
            category: Session category ('normal' or 'agent-orchestration')
        """
        super().__init__(**kwargs)
        self._session_id = session_id
        self._execution_id = execution_id
        self._category = category

        # Stores
        self._chat_store = ChatStore()
        self._agent_store = AgentStore()

        # Track last rendered turn count
        self._last_turn_count = -1

        # Track active dialog for auto-dismiss on new task messages
        self._active_dialog: Optional["ModalScreen"] = None

    def compose(self) -> ComposeResult:
        """Create the three-panel layout."""
        is_orch = self._category == "agent-orchestration"
        with Vertical(classes="chat-screen"):
            # Header
            header = ChatHeader(session_id=self._session_id, id="chat-header")
            header.is_agent_orchestration = is_orch
            yield header

            # Main content: three panels
            with Horizontal(classes="chat-content", id="chat-content"):
                # Left: Agent sidebar
                yield AgentSidebar(
                    store=self._agent_store, id="agent-sidebar", classes="sidebar"
                )

                # Center: Messages (TurnCards) + Input
                with Vertical(classes="main-content"):
                    yield MessageList(id="message-list")
                    if is_orch:
                        yield OrchestrationBanner(
                            session_id=self._session_id,
                            id="orchestration-banner",
                            classes="chat-input-container",
                        )
                    else:
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

        # Start periodic connection health check (every 15s)
        self.set_interval(15, self._check_connection_health)

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
        is_orch = self._category == "agent-orchestration"
        if not is_orch:
            chat_input = self.query_one("#chat-input", ChatInput)
        agent_sidebar = self.query_one("#agent-sidebar", AgentSidebar)

        # Set session info
        header.set_session_id(self._session_id)
        header.is_agent_orchestration = is_orch
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

            if not is_orch:
                chat_input.set_agents(
                    self._agent_store.agents,
                    main_agent_id=self._agent_store.current_agent_id or "",
                )
            await agent_sidebar.load_agents(self._session_id)
        except Exception as e:
            self.notify(f"Agent 加载失败: {e}", severity="warning", timeout=5, markup=False)

        # ── Path 3: Load turn history via HTTP — 即使 agents 加载失败也应继续
        try:
            await self._chat_store.load_turn_history(filter_execution_id=self._execution_id)
        except Exception as e:
            self.notify(f"加载 Turn 历史失败: {e}", severity="error", timeout=5, markup=False)
        finally:
            # 确保 loading 状态被清除，避免"消息加载中"卡死
            self._chat_store.loading = False
            # 确保 agent name 回调可用
            self._chat_store.on_get_agent_name(
                lambda agent_id: self._agent_store.get_agent_name(agent_id)
            )

    def _check_connection_health(self) -> None:
        """Periodic connection health check (every 15s).

        Web 版使用浏览器原生 socket.io-client，断连时 WebSocket 的 close 事件
        会立即触发 disconnect。但 Python 版使用 python-socketio，其 engine.io
        客户端的读写循环依赖超时检测（ping_interval + ping_timeout = 45s），
        断连后最多需要 45s 才能触发 disconnect 事件。

        此方法通过直接查询 engine.io 的底层连接状态来提前发现断连：
        - eio.state 在读写循环检测到错误后会立即变为 'disconnected'
        - socket.sio.connected 在 _handle_eio_disconnect 中被设为 False
        """
        try:
            socket = self._chat_store._socket
            if socket is None:
                return
            # 查询 engine.io 底层状态（比 socket.sio.connected 更及时）
            eio = socket.sio.eio if hasattr(socket, 'sio') and hasattr(socket.sio, 'eio') else None
            if eio is None:
                return
            is_connected = eio.state == 'connected' if hasattr(eio, 'state') else False
            # 如果 engine.io 认为已断开但 ChatStore 仍标记为已连接，同步状态
            if not is_connected and self._chat_store.connected:
                self._chat_store.connected = False
                header = self.query_one("#chat-header", ChatHeader)
                header.connection_status = "disconnected"
                if self._chat_store._on_connection_change:
                    self._chat_store._on_connection_change(False)
        except Exception:
            pass

    def _setup_connections(self):
        """Connect stores to widgets and register callbacks."""
        is_orch = self._category == "agent-orchestration"
        message_list = self.query_one("#message-list", MessageList)

        # Chat store → MessageList
        self._chat_store.on_change(lambda: self._on_chat_change())
        self._chat_store.on_error(
            lambda msg: self.notify(msg, severity="error", timeout=5, markup=False)
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

        # 收到 agent 任务进展时自动关闭对话框
        self._chat_store.on_dismiss_dialogs(
            lambda: self._dismiss_active_dialog()
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

        # Agent store → agent 状态/列表变化由 AgentSidebar 的 _render_agents 处理
        self._agent_store.on_visibility_change(
            lambda: self._on_visibility_changed()
        )

        # ChatInput callbacks (only in normal sessions)
        if not is_orch:
            try:
                chat_input = self.query_one("#chat-input", ChatInput)
                chat_input.set_on_send(
                    lambda text, target: self.run_worker(self._send_message(text, target))
                )
                chat_input.set_agents(
                    self._agent_store.agents,
                    main_agent_id=self._agent_store.current_agent_id or "",
                )
            except Exception:
                pass

    # ==================== Event Handlers ====================

    def _on_chat_change(self):
        """React to chat store state changes — 每次更新立即渲染，不 throttle。

        增量更新（update_turn）只更新内容不重建 DOM，不会闪烁，
        因此不需要 throttle 合并更新。
        """
        try:
            message_list = self.query_one("#message-list", MessageList)
        except Exception:
            return

        # Sync loading/has_more/redo state to message list
        message_list.loading = self._chat_store.loading
        message_list.has_more = self._chat_store.has_more_turns
        message_list.show_redo = self._chat_store.show_redo_button

        # ChatInput disabled state: 需要同时 connected + runner_alive
        try:
            chat_input = self.query_one("#chat-input", ChatInput)
            chat_input.disabled = not (
                self._chat_store.connected and self._chat_store.runner_alive
            )
        except Exception:
            pass

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
            filtered_turns = self._chat_store.get_filtered_turns(visible_ids, all_ids)
            # 立即渲染，不 throttle
            message_list.set_turn_summaries(filtered_turns, agent_name_map)
            self._last_turn_count = len(filtered_turns)

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
        agent_id = msg.get("agent_id", "")

        # 对齐 Web 行为：turn_start / agent_active / agent_response / tool_call 均标记为 running
        if msg_type in ("turn_start", "agent_active", "agent_response", "tool_call"):
            self._agent_store.update_agent_status(agent_id, "running")
        elif msg_type == "turn_end":
            self._agent_store.update_agent_status(agent_id, "idle")

    def _on_connection_change(self, connected: bool):
        """Handle connection state changes — update header + agent status.

        Aligns with Web behavior:
        - connected → all agents 'idle'
        - disconnected → all agents 'disconnected'

        Args:
            connected: Whether connected
        """
        try:
            header = self.query_one("#chat-header", ChatHeader)
            header.connection_status = "connected" if connected else "disconnected"
        except Exception:
            pass

        # Update all agents' status on connect/disconnect (align with Web)
        status = "idle" if connected else "disconnected"
        for agent in self._agent_store.agents:
            agent["agent_status"] = status
        self._agent_store._notify_change()

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

    def on_turn_card_file_diff_requested(self, event: TurnCard.FileDiffRequested):
        """处理 TurnCard 发起的文件 diff 请求（点击文件名 → 直接弹 DiffViewer）。"""
        event.stop()
        self.run_worker(self._show_file_diff(event.turn_id, event.file_path))

    async def _show_file_diff(self, turn_id: str, file_path: str):
        """获取并展示文件的 unified diff。"""
        from broca_tui.api.session import SessionAPI
        from broca_tui.widgets.diff_viewer import DiffViewer

        try:
            api = SessionAPI()
            session_id = self._chat_store.session_id
            if not session_id:
                return

            diff_text = await api.get_file_diff(session_id, turn_id, file_path)
            await self.app.push_screen(DiffViewer(file_path, diff_text or "(无变更)"))
        except Exception as e:
            from broca_tui.debug_log import log
            log(f"_show_file_diff error: {e}")
            self.notify(f"获取 diff 失败: {e}", severity="error", timeout=5, markup=False)

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
        self._active_dialog = dialog
        try:
            result = await self.app.push_screen_wait(dialog)
            if result and result.get("action") == "permission_response":
                granted = result.get("granted", False)
                session_action = result.get("session_action")
                await self._chat_store.respond_permission(granted, session_action)
        finally:
            self._active_dialog = None

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
        self._active_dialog = dialog
        try:
            result = await self.app.push_screen_wait(dialog)
            if result and result.get("action") == "user_answer":
                await self._chat_store.respond_user_answer(result.get("answer", ""))
        finally:
            self._active_dialog = None

    def _dismiss_active_dialog(self):
        """Dismiss the currently active dialog (if any) when new task messages arrive."""
        if self._active_dialog is not None:
            self._active_dialog.dismiss(None)
            self._active_dialog = None

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

    def on_orchestration_banner_navigate_to_crew(
        self, event: OrchestrationBanner.NavigateToCrew
    ) -> None:
        """Handle navigation to crew from orchestration banner."""
        self.action_go_to_crew()

    def _abort_agent(self, agent_id: str) -> None:
        """Handle agent abort from sidebar button (called directly by AgentCard)."""
        self.run_worker(self._chat_store.send_abort(agent_id))

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
