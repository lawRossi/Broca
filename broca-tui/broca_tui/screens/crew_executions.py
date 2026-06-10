"""
CrewExecutionsScreen — Crew execution management page.

Features:
- Execution list with status colors, crew name, type tags
- Filter by status
- Submit execution from config files
- Single-run constraint (block if running)
- View messages → ChatScreen with execution_id filter
- Real-time progress updates
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional

from textual.app import ComposeResult
from textual.containers import Horizontal, ScrollableContainer, Vertical
from textual.screen import ModalScreen, Screen
from textual.widgets import Button, Input, Label, Select, Static

from broca_tui.stores.crew_store import CrewStore


# ============================================================================
# Submit Execution Dialog
# ============================================================================

class SubmitExecutionDialog(ModalScreen):
    """Dialog to pick a config file and submit execution."""

    def __init__(self, config_files: List[Dict[str, Any]], **kwargs):
        super().__init__(**kwargs)
        self._config_files = config_files

    def compose(self) -> ComposeResult:
        with Vertical(classes="dialog"):
            yield Label("提交编排执行", classes="dialog-title")

            if not self._config_files:
                yield Label("未找到配置文件", classes="dialog-content")
            else:
                yield Label("选择配置文件 (点击提交):", classes="dialog-label")
                for i, cfg in enumerate(self._config_files):
                    name = cfg.get("name", cfg.get("filename", "Unknown"))
                    desc = cfg.get("description", "")
                    orch_type = cfg.get("orchestrator_type", "?")
                    agents = cfg.get("agent_names", [])
                    agents_str = ", ".join(agents[:3])
                    if len(agents) > 3:
                        agents_str += "..."

                    info_lines = [f"[{orch_type}] {name}"]
                    if desc:
                        info_lines.append(f"  {desc}")
                    if agents_str:
                        info_lines.append(f"  Agents: {agents_str}")

                    yield Button(
                        f"🚀 提交: {name}",
                        id=f"cfg-{i}",
                        classes="config-file-btn",
                    )
                    yield Label("\n".join(info_lines), classes="config-file-info")

            if not self._config_files:
                yield Label("请先在 Workspace 中创建编排配置文件", classes="dialog-content")

            with Horizontal(classes="dialog-actions"):
                yield Button("关闭", id="btn-close", classes="cancel-btn")

    def on_button_pressed(self, event: Button.Pressed) -> None:
        btn_id = event.button.id or ""
        if btn_id == "btn-close":
            self.dismiss({"action": "cancel"})
        elif btn_id.startswith("cfg-"):
            idx = int(btn_id.replace("cfg-", ""))
            if 0 <= idx < len(self._config_files):
                cfg = self._config_files[idx]
                self.dismiss({
                    "action": "submit",
                    "yaml_path": cfg.get("path", ""),
                    "filename": cfg.get("filename", ""),
                })


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

    def compose(self) -> ComposeResult:
        with Vertical(classes="crew-screen"):
            # Header
            with Horizontal(classes="crew-header"):
                yield Button("← 会话列表", id="btn-back", classes="nav-button")
                yield Label("编排执行管理", classes="screen-title")
                yield Label("", id="exec-count", classes="session-count")

            # Filter bar
            with Horizontal(classes="filter-bar"):
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
                yield Button("提交执行", id="btn-submit", variant="primary", classes="submit-btn")

            # Execution list
            with ScrollableContainer(id="execution-list", classes="execution-list"):
                yield Static("加载中...", classes="loading")

    def on_mount(self) -> None:
        """Load executions on mount."""
        self.run_worker(self._load_executions())

    async def _load_executions(self, status: Optional[str] = None):
        """Load executions from store.

        Args:
            status: Optional status filter
        """
        await self._store.load_executions(
            session_id=self._session_id or None,
            status=status,
        )
        self._render_executions()

    def _render_executions(self):
        """Render execution list."""
        container = self.query_one("#execution-list", ScrollableContainer)
        count_label = self.query_one("#exec-count", Label)
        container.remove_children()

        executions = self._store.executions
        count_label.update(f"共 {self._store.total} 条记录")

        if not executions:
            container.mount(Static("暂无执行记录", classes="empty-state"))
            return

        for exec_item in executions:
            self._render_execution_card(container, exec_item)

    def _render_execution_card(self, container: ScrollableContainer, exec_item: Dict[str, Any]):
        """Render a single execution card in the container.

        Args:
            container: Container to mount into
            exec_item: Execution dict
        """
        exec_id = exec_item.get("execution_id", "")
        crew_name = exec_item.get("crew_name", "Unknown Crew")
        orch_type = exec_item.get("orchestrator_type", "?")
        status = exec_item.get("status", "pending")
        created_at = (exec_item.get("started_at", "") or "")[:19]
        agent_count = exec_item.get("agent_count", 0)

        status_icon = {
            "pending": "⏳",
            "running": "🔄",
            "completed": "✅",
            "failed": "❌",
            "aborted": "⏹",
        }.get(status, "❓")

        status_class = f"exec-{status}"

        with Vertical(classes="execution-card", id=f"exec-{exec_id}"):
            with Horizontal(classes="exec-card-header"):
                yield Label(f"{status_icon} {crew_name}", classes="exec-name")
                yield Label(status, classes=f"exec-status {status_class}")

            with Horizontal(classes="exec-card-meta"):
                yield Label(f"类型: {orch_type}", classes="exec-meta")
                yield Label(f"Agents: {agent_count}", classes="exec-meta")
                yield Label(f"{created_at}", classes="exec-meta")

            # Phase progress (if available)
            phases = exec_item.get("phases", [])
            if phases:
                yield Label(f"进度: {exec_item.get('progress', 0)*100:.0f}%", classes="exec-progress")

            # Action buttons
            with Horizontal(classes="exec-actions"):
                yield Button("查看消息", id=f"view-{exec_id}", classes="action-btn view-btn")
                if status == "running":
                    yield Button("中止", id=f"abort-{exec_id}", classes="action-btn abort-btn")
                if status in ("completed", "failed", "aborted"):
                    yield Button("删除", id=f"del-{exec_id}", classes="action-btn del-btn")

    def on_button_pressed(self, event: Button.Pressed) -> None:
        """Handle button presses.

        Args:
            event: Button pressed event
        """
        btn_id = event.button.id or ""

        if btn_id == "btn-back":
            self.action_go_to_sessions()
        elif btn_id == "btn-submit":
            self.run_worker(self._show_submit_dialog())
        elif btn_id.startswith("view-"):
            exec_id = btn_id.replace("view-", "")
            self._navigate_to_chat(exec_id)
        elif btn_id.startswith("abort-"):
            exec_id = btn_id.replace("abort-", "")
            self.run_worker(self._abort_execution(exec_id))
        elif btn_id.startswith("del-"):
            exec_id = btn_id.replace("del-", "")
            self.run_worker(self._delete_execution(exec_id))

    def on_select_changed(self, event: Select.Changed) -> None:
        """Handle status filter changes.

        Args:
            event: Select changed event
        """
        if event.select.id == "status-filter":
            value = event.value
            status = value if value and value != "all" else None
            self.run_worker(self._load_executions(status=status))

    async def _show_submit_dialog(self):
        """Show submit dialog with config files."""
        # Try to get workspace from the current session
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

        dialog = SubmitExecutionDialog(self._store.config_files)
        result = await self.app.push_screen_wait(dialog)
        if result and result.get("action") == "submit":
            await self._store.submit_execution(
                session_id=self._session_id,
                yaml_path=result.get("yaml_path"),
            )
            self._render_executions()

    async def _abort_execution(self, exec_id: str):
        """Abort an execution.

        Args:
            exec_id: Execution ID
        """
        success = await self._store.abort_execution(exec_id)
        if success:
            self._render_executions()

    async def _delete_execution(self, exec_id: str):
        """Delete an execution record.

        Args:
            exec_id: Execution ID
        """
        success = await self._store.delete_execution(exec_id)
        if success:
            self._render_executions()

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
