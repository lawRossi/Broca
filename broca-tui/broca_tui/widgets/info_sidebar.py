"""
InfoSidebar Widget

Right info panel with:
- Session Info (ID, workspace)
- Runner Status (status, PID, uptime, start/stop toggle, auto-polling)
- Message Statistics (counts by type with colored indicators)

References broca-web ChatInfoSidebar pattern:
- Single toggle button instead of two separate start/stop buttons
- Button text/action changes based on runner status:
  - alive    → "⏹ 停止进程"  (stop)
  - error    → "🔄 重启进程"  (restart)
  - dead     → "▶ 启动进程"  (start/restart)
  - starting → disabled + "◐ 启动中"
"""

from __future__ import annotations

import asyncio
from typing import Optional

from textual.app import ComposeResult
from textual.containers import Horizontal, Vertical
from textual.reactive import reactive
from textual.widget import Widget
from textual.widgets import Button, Label

from broca_tui.api.session import SessionAPI
from broca_tui.stores.chat_store import ChatStore


class InfoSidebar(Widget):
    """Right info panel showing session details and runner status.

    References broca-web ChatInfoSidebar pattern:
    - Single toggle button instead of two separate start/stop buttons
    - Button text/action changes based on runner status:
      - alive    → "⏹ 停止进程"  (stop)
      - error    → "🔄 重启进程"  (restart)
      - dead     → "▶ 启动进程"  (start/restart)
      - starting → disabled + "◐ 启动中"
    """

    DEFAULT_CSS = """
    Tooltip {
        background: #e0e0e0;
    }
    """

    runner_status = reactive("unknown")
    runner_uptime = reactive("")
    runner_action_loading = reactive(False)

    def __init__(
        self,
        session_id: str = "",
        chat_store: Optional[ChatStore] = None,
        **kwargs,
    ):
        """Initialize info sidebar.

        Args:
            session_id: Current session ID
            chat_store: ChatStore instance for runner actions
        """
        super().__init__(**kwargs)
        self._session_id = session_id
        self._chat_store = chat_store
        self._api = SessionAPI()
        self._polling = False
        self._poll_timer = None

    def compose(self) -> ComposeResult:
        """Create the sidebar layout — 对齐 Web ChatInfoSidebar 结构。"""
        with Vertical(id="info-sidebar-content"):
            # ===== Session Info — 标签在上，值在下 =====
            with Vertical(classes="info-section"):
                yield Label("Session Info", classes="section-title")
                with Vertical(classes="info-block"):
                    yield Label("Session ID:", classes="info-label")
                    yield Label("未设置", classes="info-value", id="info-session-id")
                with Vertical(classes="info-block"):
                    yield Label("Workspace:", classes="info-label")
                    yield Label("未设置", classes="info-value", id="info-workspace")
                with Horizontal(classes="info-row"):
                    yield Label("Agent Task:", classes="info-label")
                    yield Label("0", classes="info-value", id="info-tasks")
                with Horizontal(classes="info-row"):
                    yield Label("定时Job:", classes="info-label")
                    yield Label("0", classes="info-value", id="info-jobs")

            # ===== Runner Status =====
            with Vertical(classes="info-section"):
                with Horizontal(classes="section-title-bar"):
                    yield Label("Runner Status", classes="section-title")
                    yield Button("🔄", id="btn-refresh-runner", classes="icon-button")
                yield Horizontal(
                    Label("Status:", classes="info-label"),
                    Label("-", classes="info-value", id="runner-status"),
                    classes="info-row",
                )
                yield Horizontal(
                    Label("PID:", classes="info-label"),
                    Label("-", classes="info-value", id="runner-pid"),
                    classes="info-row",
                )
                yield Horizontal(
                    Label("运行时长:", classes="info-label"),
                    Label("-", classes="info-value", id="runner-uptime"),
                    classes="info-row",
                )
                yield Horizontal(
                    Label("CPU:", classes="info-label"),
                    Label("-", classes="info-value", id="runner-cpu"),
                    classes="info-row",
                )
                yield Horizontal(
                    Label("Memory:", classes="info-label"),
                    Label("-", classes="info-value", id="runner-memory"),
                    classes="info-row",
                )
                # Action button — 对齐 Web：停止/重启/启动 不同按钮（非单 toggle）
                with Horizontal(classes="runner-btns"):
                    yield Button("启动", id="btn-start-runner", classes="runner-btn")
                    yield Button(
                        "停止", id="btn-stop-runner", classes="runner-btn stop-btn"
                    )
                    yield Button(
                        "重启",
                        id="btn-restart-runner",
                        classes="runner-btn restart-btn",
                    )

            # ===== Message Statistics =====
            with Vertical(classes="info-section"):
                yield Label("Message Statistics", classes="section-title")
                with Horizontal(classes="stat-row"):
                    yield Label("User Messages", classes="stat-label")
                    yield Label("0", classes="stat-value", id="stat-user")
                with Horizontal(classes="stat-row"):
                    yield Label("Assistant Responses", classes="stat-label")
                    yield Label("0", classes="stat-value", id="stat-agent")
                with Horizontal(classes="stat-row"):
                    yield Label("System Messages", classes="stat-label")
                    yield Label("0", classes="stat-value", id="stat-system")
                with Horizontal(classes="stat-row"):
                    yield Label("Tool Calls", classes="stat-label")
                    yield Label("0", classes="stat-value", id="stat-tool-calls")
                with Horizontal(classes="stat-row"):
                    yield Label("Tool Call Errors", classes="stat-label")
                    yield Label("0", classes="stat-value", id="stat-errors")

    def on_mount(self) -> None:
        """Start polling after mount."""
        if self._session_id:
            self._start_polling()

    def set_session(self, session_id: str, workspace: str = ""):
        """Set session information and start polling.

        Args:
            session_id: Session ID
            workspace: Workspace path
        """
        self._session_id = session_id
        session_label = self.query_one("#info-session-id", Label)
        session_label.update(
            session_id[:20] + "..."
            if session_id and len(session_id) > 20
            else (session_id or "未设置")
        )
        session_label.tooltip = session_id if session_id else "未设置"

        workspace_label = self.query_one("#info-workspace", Label)
        workspace_label.update(
            workspace[:20] + "..."
            if workspace and len(workspace) > 20
            else (workspace or "未设置")
        )
        workspace_label.tooltip = workspace if workspace else "未设置"
        self._start_polling()
        # 立即做一次初始状态获取，不等20s后的第一次轮询
        self.run_worker(self._poll_runner_status())

    def watch_runner_status(self, status: str):
        """Update runner status display and button visibility — 对齐 Web 多按钮模式。

        Args:
            status: 'alive', 'starting', 'error', 'dead', or 'unknown'
        """
        status_label = self.query_one("#runner-status", Label)
        color_map = {
            "alive": "● 运行中",
            "starting": "◐ 启动中",
            "error": "● 异常",
            "dead": "○ 已停止",
            "none": "○ 已停止",
            "unknown": "-",
        }
        display = color_map.get(status, f"● {status}")
        status_label.update(display)

        # 对齐 Web：不同状态显示不同按钮
        # starting 状态保持启动按钮可见（显示 loading 提示）
        self.query_one("#btn-start-runner").display = status in (
            "dead",
            "none",
            "unknown",
            "error",
            "starting",
        )
        self.query_one("#btn-stop-runner").display = status == "alive"
        self.query_one("#btn-restart-runner").display = status == "error"

        # 所有按钮在 starting/loading 时禁用
        for btn_id in ("#btn-start-runner", "#btn-stop-runner", "#btn-restart-runner"):
            self.query_one(btn_id).disabled = (
                status == "starting"
            ) or self.runner_action_loading

    def watch_runner_action_loading(self, loading: bool):
        """Sync loading state with button disabled states and show loading indicator."""
        labels = {
            "#btn-start-runner": "启动",
            "#btn-stop-runner": "停止",
            "#btn-restart-runner": "重启",
        }
        for btn_id, label in labels.items():
            try:
                btn = self.query_one(btn_id, Button)
                btn.disabled = loading
                btn.label = "⏳ 处理中" if loading else label
            except Exception:
                pass

    def update_runner_stats(
        self,
        pid: Optional[int],
        uptime: Optional[str],
        cpu: Optional[float] = None,
        memory_mb: Optional[float] = None,
    ):
        """Update runner PID, uptime, CPU, and memory.

        Args:
            pid: Process ID
            uptime: Uptime string
            cpu: CPU usage percentage
            memory_mb: Memory usage in MB
        """
        self.query_one("#runner-pid", Label).update(str(pid) if pid else "-")
        uptime_str = uptime or "-"
        self.query_one("#runner-uptime", Label).update(uptime_str)

        # CPU
        cpu_str = f"{int(cpu)}%" if cpu is not None else "-"
        self.query_one("#runner-cpu", Label).update(cpu_str)

        # Memory (>1024MB → GB)
        if memory_mb is not None:
            val = int(memory_mb)
            if val > 1024:
                memory_str = f"{val // 1024} GB"
            else:
                memory_str = f"{val} MB"
        else:
            memory_str = "-"
        self.query_one("#runner-memory", Label).update(memory_str)

    def update_message_stats(self, messages: list):
        """Update message statistics — 当前实现在 _poll_runner_status 中已改为 API 调用。

        此方法保留以兼容旧调用，但实际统计由 _poll_runner_status 中的 API 驱动。

        Args:
            messages: Deprecated, kept for compatibility
        """
        # 统计已改为通过 _poll_runner_status 中的 API 调用获取
        pass

    def _update_stats_from_api(self, stats_data: dict):
        """从 API 响应更新消息统计 — 对齐 Web 版兼容两种 key 格式。

        API 返回格式（GET /session/{id}/stats）：
        {
            "total_messages": int,
            "messages_by_type": {"MessageType.XXX": int} or {"XXX": int},
            "tool_call_errors": int
        }

        兼容两种 key 格式（Web 版 ChatInfoSidebar 相同做法）：
        - "MessageType.AGENT_RESPONSE" (SQLAlchemy str(enum) 输出)
        - "AGENT_RESPONSE" (数据库原始值)

        Args:
            stats_data: API 返回的统计数据
        """
        if not stats_data:
            return

        mt = stats_data.get("messages_by_type", {}) or {}
        error_count = stats_data.get("tool_call_errors", 0)

        # 兼容两种 key 格式：MessageType.XYZ 或 XYZ
        def _get(key: str) -> int:
            return mt.get(f"MessageType.{key}", 0) or mt.get(key, 0) or 0

        user_count = _get("USER_MESSAGE")
        agent_count = _get("AGENT_RESPONSE")
        tool_count = _get("TOOL_CALL")
        # 系统消息：包含 SYSTEM_MESSAGE + AGENT_SYSTEM_MESSAGE + COMMAND + 其他系统类（对齐 Web）
        system_count = (
            _get("SYSTEM_MESSAGE")
            + _get("AGENT_SYSTEM_MESSAGE")
            + _get("COMMAND")
            + _get("COMMAND_RESULT")
            + _get("PERMISSION_REQUEST")
            + _get("PERMISSION_RESPONSE")
            + _get("SUBSCRIBE")
            + _get("UNSUBSCRIBE")
            + _get("BROADCAST")
            + _get("TURN_START")
            + _get("TURN_END")
        )

        self.query_one("#stat-user", Label).update(str(user_count))
        self.query_one("#stat-agent", Label).update(str(agent_count))
        self.query_one("#stat-tool-calls", Label).update(str(tool_count))
        self.query_one("#stat-system", Label).update(str(system_count))
        # Tool Call Errors — 大于 0 时红色加粗（对齐 Web）
        err_label = self.query_one("#stat-errors", Label)
        err_label.update(str(error_count))
        err_label.styles.color = "$error" if error_count > 0 else ""

    def _start_polling(self):
        """Start periodic runner status polling (10s interval)."""
        if self._polling:
            return
        self._polling = True
        self._poll_timer = self.set_interval(10, self._poll_runner_status)

    def _stop_polling(self):
        """Stop runner status polling."""
        self._polling = False
        if self._poll_timer:
            try:
                self._poll_timer.stop()
            except Exception:
                pass
            self._poll_timer = None

    def _get_runner_uptime(self, uptime_seconds: Optional[float]) -> str:
        """格式化运行时长 — 中文格式。

        Args:
            uptime_seconds: 运行秒数（可能带小数）

        Returns:
            如 "3小时20分钟" 或 "45分钟"
        """
        if not uptime_seconds or uptime_seconds <= 0:
            return "-"
        total = int(uptime_seconds)
        h = total // 3600
        m = (total % 3600) // 60
        if h > 0:
            return f"{h}小时{m}分钟"
        return f"{m}分钟"

    async def _poll_runner_status(self):
        """Poll runner status from API — extended to include Session Info + Message Stats + Job/Task counts.

        All sections are independent: a failure in one does not block the others.
        """
        if not self._session_id:
            return

        # 1. Runner status (独立 try/except，不影响其他统计)
        try:
            info = await self._api.get_runner_status(self._session_id)
            status = info.get("status", "unknown")
            self.runner_status = status
            self.runner_uptime = str(info.get("uptime_seconds", ""))
            resource = info.get("resource_usage", {}) or {}
            uptime_seconds = info.get("uptime_seconds") or 0
            self.update_runner_stats(
                pid=info.get("pid"),
                uptime=self._get_runner_uptime(uptime_seconds),
                cpu=resource.get("cpu_percent"),
                memory_mb=resource.get("memory_rss_mb"),
            )
            # 同步 runner 状态到 ChatStore，确保 chat_input 禁用状态及时更新
            if self._chat_store:
                self._chat_store.runner_alive = status == "alive"
                self._chat_store._notify_change()
        except Exception:
            self.runner_status = "unknown"

        # 2. Message Statistics refresh (via API, not local messages)
        try:
            stats_data = await self._api.get_session_stats(self._session_id)
            self._update_stats_from_api(stats_data)
        except Exception:
            pass

        # 3. Job & Task counts (并行获取，对齐 Web 版)
        try:
            job_task = self._api.get_job_count(self._session_id)
            task_task = self._api.get_task_count(self._session_id)
            job_count, task_count = await asyncio.gather(job_task, task_task)
            self.query_one("#info-jobs", Label).update(str(job_count))
            self.query_one("#info-tasks", Label).update(str(task_count))
        except Exception:
            pass

    def on_button_pressed(self, event: Button.Pressed) -> None:
        """Handle button presses — 对齐 Web 多按钮模式。

        三个按钮分别对应：启动/停止/重启，不同状态显示不同按钮。
        """
        button_id = event.button.id or ""

        if button_id == "btn-refresh-runner":
            self.run_worker(self._poll_runner_status())
            return

        if button_id not in (
            "btn-start-runner",
            "btn-stop-runner",
            "btn-restart-runner",
        ):
            return

        session_id = self._session_id
        if not session_id:
            return

        self.runner_action_loading = True

        if button_id == "btn-stop-runner":
            self.run_worker(self._do_stop_runner(session_id))
        else:
            self.run_worker(self._do_start_runner(session_id))

    async def _do_start_runner(self, session_id: str):
        """Start (or restart) the runner."""
        try:
            self.runner_status = "starting"
            if self._chat_store:
                await self._chat_store.restart_runner()
            else:
                await self._api.restart_runner(session_id)
            # Poll until runner is alive (or timeout)
            for _ in range(12):  # 12 * 5 = 60 seconds max
                await self._sleep(5)
                try:
                    info = await self._api.get_runner_status(session_id)
                    s = info.get("status", "unknown")
                    self.runner_status = s
                    self.update_runner_stats(
                        pid=info.get("pid"),
                        uptime=self._get_runner_uptime(info.get("uptime_seconds")),
                    )
                    if s == "alive":
                        break
                    if s == "error":
                        break
                except Exception:
                    pass
        except Exception:
            self.runner_status = "error"
        finally:
            self.runner_action_loading = False

    async def _do_stop_runner(self, session_id: str):
        """Stop the runner."""
        try:
            if self._chat_store:
                await self._chat_store.stop_runner()
            else:
                await self._api.stop_runner(session_id)
            self.runner_status = "dead"
            self.update_runner_stats(pid=None, uptime=None)
        finally:
            self.runner_action_loading = False

    async def _sleep(self, seconds: float):
        """Async sleep helper."""
        import asyncio

        await asyncio.sleep(seconds)

    def on_unmount(self) -> None:
        """Clean up on unmount."""
        self._stop_polling()
        self.call_later(self._cleanup_api)

    async def _cleanup_api(self):
        """Close the API session."""
        try:
            await self._api.close()
        except Exception:
            pass
