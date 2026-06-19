"""
CrewExecutionsScreen — Crew execution management page.

Features:
- Tabbed interface: "执行记录" + "已有编排"
- Execution list with status badges, orchestrator type tags, progress bars
- DAG detail view with phase timeline
- Config file browser with direct submit
- Real-time socket updates (independent Socket.IO connection)
"""

from __future__ import annotations

import asyncio
from typing import Any, Dict, List, Optional

from textual.app import ComposeResult
from textual.containers import Horizontal, ScrollableContainer, Vertical
from textual.screen import ModalScreen, Screen
from textual.widgets import Button, Label, Select, Static

from broca_tui.config import get_config
from broca_tui.stores.crew_store import CrewStore


# ============================================================================
# Orchestrator type labels (matching VS Code CrewApp.vue)
# ============================================================================

ORCHESTRATOR_LABELS: Dict[str, str] = {
    "pipeline": "流水线",
    "supervisor-worker": "主管-工人",
    "round-table": "圆桌讨论",
    "broadcast": "广播分发",
    "consensus": "共识评估",
    "composite": "组合嵌套",
}

STATUS_LABELS: Dict[str, str] = {
    "pending": "待执行",
    "running": "运行中",
    "completed": "已完成",
    "failed": "已失败",
    "aborted": "已中止",
}


# ============================================================================
# ConfirmDialog
# ============================================================================

class ConfirmDialog(ModalScreen):
    """Simple confirmation dialog."""

    DEFAULT_CSS = """
    ConfirmDialog {
        align: center middle;
    }

    ConfirmDialog > .dialog {
        width: 40;
        height: auto;
        background: #f8fafc;
        border: thick #0ea5e9;
        padding: 1 2;
    }

    ConfirmDialog .dialog-title {
        text-style: bold;
        padding: 0 0 1 0;
        text-align: center;
    }

    ConfirmDialog .dialog-content {
        padding: 0 0 1 0;
        text-align: center;
    }

    ConfirmDialog .dialog-actions {
        height: auto;
        align: center middle;
    }

    ConfirmDialog .confirm-btn {
        background: #ef4444;
        color: white;
        margin-right: 1;
    }

    ConfirmDialog .cancel-btn {
        background: #cbd5e1;
        color: #334155;
        min-width: 8;
    }
    """

    def __init__(self, title: str, message: str, **kwargs):
        super().__init__(**kwargs)
        self._title = title
        self._message = message

    def compose(self) -> ComposeResult:
        with Vertical(classes="dialog"):
            yield Label(self._title, classes="dialog-title")
            yield Label(self._message, classes="dialog-content")
            with Horizontal(classes="dialog-actions"):
                yield Button("取消", id="btn-cancel", classes="cancel-btn")
                yield Button("确认", id="btn-confirm", classes="confirm-btn")

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "btn-confirm":
            self.dismiss({"confirmed": True})
        else:
            self.dismiss({"confirmed": False})


# ============================================================================
# CrewExecutionsScreen
# ============================================================================

class CrewExecutionsScreen(Screen):
    """Crew execution management screen."""

    BINDINGS = [
        ("ctrl+s", "go_to_sessions", "会话列表"),
    ]

    def __init__(self, session_id: str = "", **kwargs):
        super().__init__(**kwargs)
        self._session_id = session_id
        self._store = CrewStore()
        self._selected_execution_id: Optional[str] = None

    def compose(self) -> ComposeResult:
        with Vertical(classes="crew-screen"):
            # Header
            with Horizontal(classes="crew-header"):
                yield Button("← 会话列表", id="btn-back", classes="nav-button")
                yield Label("编排执行管理", classes="screen-title")
                yield Label("", id="exec-count", classes="session-count")

            # Tab bar
            with Horizontal(classes="crew-tab-bar"):
                yield Button("执行记录", id="tab-executions", classes="crew-tab active")
                yield Button("已有编排", id="tab-configs", classes="crew-tab")

            # Executions tab
            with Vertical(id="executions-tab", classes="tab-content"):
                # Filter bar
                with Horizontal(classes="crew-filter-bar"):
                    yield Select(
                        [
                            ("全部状态", "all"),
                            ("运行中", "running"),
                            ("已完成", "completed"),
                            ("失败", "failed"),
                            ("已中止", "aborted"),
                            ("待执行", "pending"),
                        ],
                        value="all",
                        id="status-filter",
                        classes="status-filter",
                    )
                    yield Button("刷新", id="btn-refresh", classes="refresh-btn")
                    yield Label("", id="filter-count", classes="filter-count")

                # Execution list
                with ScrollableContainer(id="execution-list", classes="execution-list"):
                    yield Static("加载中...", classes="crew-loading")

            # Configs tab (hidden by default via CSS or post-mount)
            with Vertical(id="configs-tab", classes="tab-content"):
                with Horizontal(classes="crew-filter-bar"):
                    yield Label("", id="configs-count", classes="filter-count")

                with ScrollableContainer(id="configs-list", classes="execution-list"):
                    yield Static("暂无编排配置文件", classes="crew-empty")

            # Detail view (hidden by default)
            with Vertical(id="detail-view", classes="detail-view"):
                with Horizontal(classes="detail-header"):
                    yield Button("← 返回", id="btn-back-to-list", classes="nav-button")
                    yield Label("", id="detail-title", classes="detail-title")

                # Summary section
                with Vertical(id="detail-summary", classes="detail-summary"):
                    with Horizontal(classes="detail-summary-row"):
                        yield Label("", id="detail-status", classes="detail-status-badge")
                        yield Label("", id="detail-orch-type", classes="detail-orch-label")
                    with Horizontal(classes="detail-progress-row"):
                        yield Static("", id="detail-progress", classes="detail-progress")
                    yield Label("", id="detail-duration", classes="detail-duration")

                # DAG Timeline
                with ScrollableContainer(id="dag-timeline", classes="dag-scroll"):
                    yield Static("加载阶段信息...", classes="crew-loading")

                # Result section
                with Vertical(id="detail-result", classes="detail-result"):
                    yield Label("执行结果", classes="detail-section-title")
                    yield Static("", id="result-json", classes="result-json")

    def on_mount(self) -> None:
        """Load executions on mount, bind store, and connect socket."""
        # Bind store changes (use app.call_later for thread safety)
        self._store.on_change(lambda: self._on_store_change())
        self._store.on_error(lambda msg: self._show_error(msg))

        # Initial load
        self.run_worker(self._load_executions())

        # Connect Socket.IO for real-time updates
        self.run_worker(self._connect_socket())

        # Set initial visibility (configs tab and detail view hidden)
        try:
            self.query_one("#configs-tab", Vertical).display = "none"
            self.query_one("#detail-view", Vertical).display = "none"
        except Exception:
            pass

    # ── Store change handler ──

    def _on_store_change(self):
        """React to store state changes and selectively re-render."""
        # If detail view is active and detail data changed
        if self._selected_execution_id is not None:
            if self._store.selected_execution:
                self._render_detail_view(self._store.selected_execution)
            elif not self._store.detail_loading:
                # Detail was cleared (e.g. by deletion event)
                self._exit_detail_view()

        # Update executions tab if visible
        if self._store.active_tab == "executions" or self._selected_execution_id is None:
            # Only re-render if data changed (executions list modified)
            self._render_executions_tab()

        # Update configs tab if visible
        if self._store.active_tab == "configs":
            self._render_configs_tab()

    def _show_error(self, message: str):
        """Show error notification.

        Args:
            message: Error message
        """
        self.notify(message, severity="error", timeout=5)

    # ── Socket.IO Connection (independent, not shared with ChatStore) ──

    async def _connect_socket(self):
        """Establish independent Socket.IO connection for crew events."""
        from broca.communication.socketio_client import SocketIOClient

        config = get_config()
        self._crew_socket: Optional[SocketIOClient] = None

        try:
            self._crew_socket = SocketIOClient(
                server_url=config.socket_server_url,
                client_type="tui",
                client_id=f"crew_{id(self)}",
                user_id=config.user_id,
                auto_reconnect=True,
                reconnect_delay=2.0,
                max_reconnect_attempts=3,
            )

            @self._crew_socket.on_message
            async def handle_message(message):
                """Handle incoming crew socket messages."""
                await self._process_crew_message(message)

            await self._crew_socket.connect()
            if self._session_id:
                await self._crew_socket.subscribe(self._session_id)
        except Exception as e:
            # Socket connection is best-effort for real-time updates
            self.log(f"Crew socket connection failed: {e}")

    async def _process_crew_message(self, message) -> None:
        """Process an incoming crew socket message.

        Args:
            message: Socket message object
        """
        try:
            msg_type = getattr(message, "type", None) or (
                message.get("type") if isinstance(message, dict) else None
            )
            msg_data = getattr(message, "data", None) or (
                message.get("data") if isinstance(message, dict) else {}
            )

            if msg_type == "crew_event" and isinstance(msg_data, dict):
                self._store.update_execution_from_event(msg_data)
        except Exception as e:
            self.log(f"Error processing crew message: {e}")

    def on_unmount(self) -> None:
        """Clean up socket connection on unmount."""
        if hasattr(self, '_crew_socket') and self._crew_socket:
            try:
                # Schedule disconnect in a fire-and-forget manner
                asyncio.ensure_future(self._crew_socket.disconnect())
            except Exception:
                pass

    # ── Confirmation Dialog ──

    async def _confirm_action(self, title: str, message: str) -> bool:
        """Show a confirmation dialog and wait for user response.

        Args:
            title: Dialog title
            message: Confirmation message

        Returns:
            True if confirmed, False otherwise.
        """
        dialog = ConfirmDialog(title=title, message=message)
        result = await self.app.push_screen_wait(dialog)
        return result and result.get("confirmed", False)

    # ── Executions Tab ──

    async def _load_executions(self, status: Optional[str] = None):
        """Load executions from store.

        Args:
            status: Optional status filter
        """
        await self._store.load_executions(
            session_id=self._session_id or None,
            status=status,
        )

    def _render_executions_tab(self):
        """Render the executions tab content."""
        # Check if executions-tab exists and is visible
        try:
            container = self.query_one("#execution-list", ScrollableContainer)
            count_label = self.query_one("#filter-count", Label)
        except Exception:
            return

        container.remove_children()

        executions = self._store.executions
        count_label.update(f"共 {self._store.total} 条记录")

        if self._store.loading and not executions:
            container.mount(Static("加载中...", classes="crew-loading"))
            return

        if not executions:
            container.mount(Static("暂无编排执行记录\n提交编排 YAML 配置以开始执行", classes="crew-empty"))
            return

        for exec_item in executions:
            self._render_execution_card(container, exec_item)

    def _render_execution_card(self, container: ScrollableContainer, exec_item: Dict[str, Any]):
        """Render a single execution card.

        Builds the widget tree bottom-up, mounting each level before adding children.

        Args:
            container: Container to mount into
            exec_item: Execution dict
        """
        exec_id = exec_item.get("execution_id", "")
        crew_name = exec_item.get("crew_name", "Unknown Crew")
        orch_type = exec_item.get("orchestrator_type", "?")
        status = exec_item.get("status", "pending")
        created_at = (exec_item.get("created_at", "") or "")[:19]
        agent_count = exec_item.get("agent_count", 0)
        description = exec_item.get("description", "")
        progress = exec_item.get("progress")

        status_class = f"status-{status}"
        orch_label = ORCHESTRATOR_LABELS.get(orch_type, orch_type)
        status_text = STATUS_LABELS.get(status, status)

        # Create and mount card to container first (card must be in DOM before children)
        card = Vertical(classes="crew-card")
        container.mount(card)

        # Card header: status badge + name (clickable) + type tag
        header = Horizontal(classes="crew-card-header")
        card.mount(header)
        title_row = Horizontal(classes="crew-card-title-row")
        header.mount(title_row)
        title_row.mount(Label(status_text, classes=f"crew-status-badge {status_class}"))
        title_row.mount(Button(crew_name, id=f"detail-{exec_id}", classes="crew-card-name-btn"))
        title_row.mount(Label(orch_label, classes="crew-card-type"))

        # Description
        if description:
            card.mount(Label(description, classes="crew-card-desc"))

        # Meta info
        meta = Horizontal(classes="crew-card-meta")
        card.mount(meta)
        meta.mount(Label(f"Agent: {agent_count} 个", classes="crew-meta-item"))
        if exec_item.get("phases"):
            phases = exec_item["phases"]
            phases_total = exec_item.get("phases_total", len(phases))
            meta.mount(Label(f"阶段: {len(phases)}/{phases_total}", classes="crew-meta-item"))
        meta.mount(Label(f"{created_at}", classes="crew-meta-item"))

        # Progress bar
        if progress is not None:
            pct = round(progress * 100)
            prog_row = Horizontal(classes="crew-progress-row")
            card.mount(prog_row)
            bar_container = Horizontal(classes="crew-progress-bar-container")
            prog_row.mount(bar_container)
            bar_container.mount(Static("", classes=f"crew-progress-bar {status_class}", id=f"prog-{exec_id}"))
            prog_row.mount(Label(f"{pct}%", classes="crew-progress-text"))

        # Action buttons
        actions = Horizontal(classes="crew-card-actions")
        card.mount(actions)
        actions.mount(Button("查看聊天日志", id=f"view-{exec_id}", classes="btn btn-sm btn-secondary"))
        if status == "running":
            actions.mount(Button("中止", id=f"abort-{exec_id}", classes="btn btn-sm btn-danger"))
        if status in ("completed", "failed", "aborted"):
            actions.mount(Button("删除", id=f"del-{exec_id}", classes="btn btn-sm btn-danger"))

    # ── Configs Tab ──

    def _render_configs_tab(self):
        """Render the configs tab content."""
        try:
            container = self.query_one("#configs-list", ScrollableContainer)
            count_label = self.query_one("#configs-count", Label)
        except Exception:
            return

        container.remove_children()

        config_files = self._store.config_files
        count_label.update(f"{len(config_files)} 个配置文件")

        if self._store.config_files_loading and not config_files:
            container.mount(Static("加载中...", classes="crew-loading"))
            return

        if not config_files:
            container.mount(Static(
                "该工作空间下没有编排配置文件\n请在 workspace 的 crew_configs/ 目录下创建 .yaml 文件",
                classes="crew-empty",
            ))
            return

        for cfg in config_files:
            self._render_config_card(container, cfg)

    @staticmethod
    def _sanitize_id(raw: str) -> str:
        """Sanitize a string for use as a Textual widget ID.

        Textual IDs must contain only letters, numbers, underscores, or hyphens.
        Replaces dots and other invalid characters with hyphens.

        Args:
            raw: Raw string to sanitize

        Returns:
            Sanitized ID string
        """
        import re
        return re.sub(r'[^a-zA-Z0-9_-]', '-', raw)

    def _render_config_card(self, container: ScrollableContainer, cfg: Dict[str, Any]):
        """Render a single config file card.

        Builds the widget tree bottom-up, mounting each level before adding children.

        Args:
            container: Container to mount into
            cfg: Config file dict
        """
        name = cfg.get("name", "Unknown")
        orch_type = cfg.get("orchestrator_type", "?")
        filename = cfg.get("filename", "")
        description = cfg.get("description", "")
        agent_names = cfg.get("agent_names", [])
        parse_error = cfg.get("parse_error")
        modified_time = cfg.get("modified_time", 0)

        orch_label = ORCHESTRATOR_LABELS.get(orch_type, orch_type)
        safe_id = self._sanitize_id(filename)

        # Create and mount card to container first
        card = Vertical(classes="crew-card")
        container.mount(card)

        # Header
        header = Horizontal(classes="crew-card-header")
        card.mount(header)
        title_row = Horizontal(classes="crew-card-title-row")
        header.mount(title_row)
        title_row.mount(Label(name, classes="crew-card-name"))
        title_row.mount(Label(orch_label, classes="crew-card-type"))
        if parse_error:
            title_row.mount(Label("解析失败", classes="crew-status-badge status-failed"))
        header.mount(Label(filename, classes="crew-card-filename"))

        # Description
        if description:
            card.mount(Label(description, classes="crew-card-desc"))

        # Meta info
        meta = Horizontal(classes="crew-card-meta")
        card.mount(meta)
        agents_str = ", ".join(agent_names[:5])
        if agent_names:
            meta.mount(Label(f"Agent: {agents_str}", classes="crew-meta-item"))
        if modified_time:
            import datetime
            mt = datetime.datetime.fromtimestamp(modified_time).strftime("%m-%d %H:%M")
            meta.mount(Label(mt, classes="crew-meta-item"))

        # Action buttons
        actions = Horizontal(classes="crew-card-actions")
        card.mount(actions)
        is_running = self._store.is_executing(name)
        actions.mount(Button(
            "执行中..." if is_running else "执行",
            id=f"submit-{safe_id}",
            classes="btn btn-sm btn-primary",
            disabled=is_running,
        ))

    # ── Detail View ──

    def _render_detail_view(self, execution: Dict[str, Any]):
        """Render the detail/DAG view for a selected execution.

        Args:
            execution: Execution detail dict
        """
        try:
            title_label = self.query_one("#detail-title", Label)
            status_label = self.query_one("#detail-status", Label)
            orch_label = self.query_one("#detail-orch-type", Label)
            progress_static = self.query_one("#detail-progress", Static)
            duration_label = self.query_one("#detail-duration", Label)
            dag_container = self.query_one("#dag-timeline", ScrollableContainer)
            result_section = self.query_one("#detail-result", Vertical)
            result_json = self.query_one("#result-json", Static)
        except Exception:
            return

        # Header
        crew_name = execution.get("crew_name", "Unknown")
        title_label.update(crew_name)

        # Status
        status = execution.get("status", "pending")
        status_text = STATUS_LABELS.get(status, status)
        status_label.update(status_text)
        status_label.classes = f"crew-status-badge status-{status}"

        # Orchestrator type
        orch_type = execution.get("orchestrator_type", "")
        orch_label.update(f"拓扑: {ORCHESTRATOR_LABELS.get(orch_type, orch_type)}")

        # Progress
        progress = execution.get("progress")
        if progress is not None:
            pct = round(progress * 100)
            progress_static.update(f"进度: {pct}%")
        else:
            progress_static.update("")

        # Duration
        duration = self._get_duration(execution)
        duration_label.update(duration)

        # DAG Timeline
        dag_container.remove_children()
        phases = execution.get("phases", [])
        if phases:
            phases_total = execution.get("phases_total", len(phases))
            # Mount dag-list to container FIRST, then add children
            dag_list = Vertical(classes="crew-dag-list")
            dag_container.mount(dag_list)
            for i, phase in enumerate(phases):
                self._render_phase_node(dag_list, phase, i, phases_total)
        else:
            dag_container.mount(Static("暂无阶段信息", classes="crew-empty"))

        # Result
        result = execution.get("result")
        if result:
            import json
            result_section.display = "block"
            result_json.update(json.dumps(result, indent=2, ensure_ascii=False))
        else:
            result_section.display = "none"

    def _render_phase_node(self, parent: Vertical, phase: Dict[str, Any], index: int, total: int):
        """Render a single DAG phase node as a child of the dag-list Vertical.

        Builds the widget tree bottom-up, mounting each level before adding children.

        Args:
            parent: The crew-dag-list Vertical to mount into
            phase: Phase dict
            index: Phase index (0-based)
            total: Total number of phases
        """
        phase_name = phase.get("name", f"阶段 {index + 1}")
        phase_status = phase.get("status", "pending")
        agents = phase.get("agents", [])
        error = phase.get("error")

        status_class = f"phase-{phase_status}"
        status_icon = {
            "completed": "✓",
            "running": "⟳",
            "failed": "✕",
        }.get(phase_status, "○")

        # Create and mount the DAG node row to parent first
        node = Horizontal(classes="crew-dag-node")
        parent.mount(node)

        # Dot column
        dot_col = Vertical(classes="crew-dag-dot-column")
        node.mount(dot_col)
        dot_col.mount(Label("●", classes=f"crew-dag-dot {status_class}"))

        # Card column
        card_col = Vertical(classes="crew-dag-card-column")
        node.mount(card_col)
        card = Vertical(classes=f"crew-dag-card {status_class}")
        card_col.mount(card)
        card_header = Horizontal(classes="crew-dag-card-header")
        card.mount(card_header)
        card_header.mount(Label(phase_name, classes="crew-dag-phase-name"))
        card_header.mount(Label(
            f"{status_icon} {STATUS_LABELS.get(phase_status, phase_status)}",
            classes=f"crew-dag-phase-status {status_class}",
        ))

        if agents:
            agents_row = Horizontal(classes="crew-dag-agents")
            card.mount(agents_row)
            for agent in agents:
                agents_row.mount(Label(agent, classes="crew-dag-agent-tag"))

        if error:
            card.mount(Label(error, classes="crew-dag-error"))

        card.mount(Label(f"步骤 {index + 1} / {total}", classes="crew-dag-step-num"))

    def _get_duration(self, execution: Dict[str, Any]) -> str:
        """Get formatted duration string.

        Args:
            execution: Execution dict

        Returns:
            Duration string or empty
        """
        completed_at = execution.get("completed_at")
        created_at = execution.get("created_at")
        if completed_at and created_at:
            import datetime
            try:
                start = datetime.datetime.fromisoformat(created_at.replace("Z", "+00:00"))
                end = datetime.datetime.fromisoformat(completed_at.replace("Z", "+00:00"))
                delta = end - start
                total_seconds = int(delta.total_seconds())
                if total_seconds < 60:
                    return f"耗时: {total_seconds}s"
                return f"耗时: {total_seconds // 60}m {total_seconds % 60}s"
            except Exception:
                pass
        return ""

    # ── Event handlers ──

    def on_button_pressed(self, event: Button.Pressed) -> None:
        """Handle button presses.

        Args:
            event: Button pressed event
        """
        btn_id = event.button.id or ""

        # Navigation
        if btn_id == "btn-back":
            self.action_go_to_sessions()
        elif btn_id == "btn-back-to-list":
            self._exit_detail_view()
        elif btn_id == "btn-refresh":
            self.run_worker(self._load_executions())

        # Tab switching
        elif btn_id == "tab-executions":
            self._switch_tab("executions")
        elif btn_id == "tab-configs":
            self._switch_tab("configs")

        # Execution list actions
        elif btn_id.startswith("view-"):
            exec_id = btn_id.replace("view-", "")
            self._navigate_to_chat(exec_id)
        elif btn_id.startswith("abort-"):
            exec_id = btn_id.replace("abort-", "")
            self.run_worker(self._confirm_and_abort(exec_id))
        elif btn_id.startswith("del-"):
            exec_id = btn_id.replace("del-", "")
            self.run_worker(self._confirm_and_delete(exec_id))

        # Config file submit (match by sanitized ID)
        elif btn_id.startswith("submit-"):
            safe_submit_id = btn_id.replace("submit-", "")
            # Find the config file whose sanitized ID matches
            matched_filename = None
            for cfg in self._store.config_files:
                if self._sanitize_id(cfg.get("filename", "")) == safe_submit_id:
                    matched_filename = cfg.get("filename")
                    break
            if matched_filename:
                self.run_worker(self._submit_config(matched_filename))

        # Card name click → detail view
        elif btn_id.startswith("detail-"):
            exec_id = btn_id.replace("detail-", "")
            self._enter_detail_view(exec_id)

    def on_select_changed(self, event: Select.Changed) -> None:
        """Handle status filter changes.

        Args:
            event: Select changed event
        """
        if event.select.id == "status-filter":
            value = event.value
            status = value if value and value != "all" else None
            self.run_worker(self._load_executions(status=status))

    # ── Tab switching ──

    def _switch_tab(self, tab: str):
        """Switch between executions and configs tabs.

        Args:
            tab: 'executions' or 'configs'
        """
        self._store.set_active_tab(tab)

        # Toggle tab button active states
        tab_exec = self.query_one("#tab-executions", Button)
        tab_cfg = self.query_one("#tab-configs", Button)
        tab_exec.classes = "crew-tab active" if tab == "executions" else "crew-tab"
        tab_cfg.classes = "crew-tab active" if tab == "configs" else "crew-tab"

        # Show/hide tab content
        exec_tab = self.query_one("#executions-tab", Vertical)
        cfg_tab = self.query_one("#configs-tab", Vertical)
        exec_tab.display = tab == "executions"
        cfg_tab.display = tab == "configs"

        # Load data on first switch to configs
        if tab == "configs" and not self._store.config_files:
            self.run_worker(self._load_config_files())

    async def _load_config_files(self):
        """Load config files for the configs tab."""
        from broca_tui.api.session import SessionAPI
        api = SessionAPI()
        workspace = ""
        try:
            if self._session_id:
                session_info = await api.get_session(self._session_id)
                workspace = session_info.get("workspace", "")
        except Exception:
            pass
        finally:
            await api.close()

        if workspace:
            await self._store.load_config_files(workspace)

    # ── Detail view ──

    def _enter_detail_view(self, exec_id: str):
        """Enter detail view for an execution.

        Args:
            exec_id: Execution ID
        """
        self._selected_execution_id = exec_id

        # Use run_worker to properly await the async detail loading
        self.run_worker(self._store.load_execution_detail(exec_id))

        # Hide tab content, show detail view
        self.query_one("#executions-tab", Vertical).display = "none"
        self.query_one("#configs-tab", Vertical).display = "none"
        self.query_one(".crew-tab-bar", Horizontal).display = "none"
        self.query_one("#detail-view", Vertical).display = "block"

    def _exit_detail_view(self):
        """Exit detail view and return to list."""
        self._selected_execution_id = None
        self._store.selected_execution = None

        # Show tab content, hide detail view
        self.query_one("#detail-view", Vertical).display = "none"
        self.query_one(".crew-tab-bar", Horizontal).display = "block"

        # Show active tab
        active = self._store.active_tab
        self.query_one("#executions-tab", Vertical).display = active == "executions"
        self.query_one("#configs-tab", Vertical).display = active == "configs"

    # ── Actions ──

    async def _submit_config(self, filename: str):
        """Submit a config file for execution.

        Args:
            filename: Config filename
        """
        # Find the config
        cfg = None
        for c in self._store.config_files:
            if c.get("filename") == filename:
                cfg = c
                break

        if not cfg:
            self._show_error(f"未找到配置文件: {filename}")
            return

        result = await self._store.submit_execution(
            session_id=self._session_id,
            yaml_path=cfg.get("path"),
        )

        if result:
            self.notify(f"编排 {cfg.get('name', filename)} 提交成功", severity="information", timeout=3)
            # Switch to executions tab to show the new execution
            self._switch_tab("executions")

    async def _confirm_and_abort(self, exec_id: str):
        """Show confirmation then abort an execution.

        Args:
            exec_id: Execution ID
        """
        confirmed = await self._confirm_action("确认中止", "确定要中止此编排吗？")
        if confirmed:
            success = await self._store.abort_execution(exec_id)
            if success:
                self.notify("已中止执行", severity="warning", timeout=3)

    async def _confirm_and_delete(self, exec_id: str):
        """Show confirmation then delete an execution record.

        Args:
            exec_id: Execution ID
        """
        confirmed = await self._confirm_action("确认删除", "确定要删除此编排记录吗？")
        if confirmed:
            success = await self._store.delete_execution(exec_id)
            if success:
                self.notify("已删除执行记录", severity="information", timeout=3)

    def _navigate_to_chat(self, exec_id: str):
        """Navigate to ChatScreen with execution filter.

        Args:
            exec_id: Execution ID to filter by
        """
        from broca_tui.screens.chat import ChatScreen
        screen = ChatScreen(session_id=self._session_id, execution_id=exec_id)
        self.app.push_screen(screen)

    def action_go_to_sessions(self) -> None:
        """Navigate back to session list."""
        self.app.pop_screen()
