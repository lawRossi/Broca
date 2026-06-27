"""
TurnCard Widget — 简洁模式 turn 摘要卡片

对齐 Web ChatTurnCard.vue 的渲染模式：
- 标题栏（Agent 名称、轮次编号、耗时、状态色点）
- 用户问题
- 执行摘要（步骤数、状态、当前工具、文件路径、TODO 列表、工具调用统计）
- 最终回复（Markdown 渲染）
- 推理内容（可折叠）
- 撤销按钮（hover 显示）

状态颜色映射（简化）：
- active/thinking/calling_tool → 蓝色（"进行中"）
- completed → 绿色（"已完成"）
- error → 红色（"中断"）
"""

from __future__ import annotations

import copy
import time
from typing import Dict, Optional

from rich.markdown import Markdown
from textual.app import ComposeResult
from textual.containers import Horizontal, Vertical
from textual.message import Message
from textual.widget import Widget
from textual.widgets import Button, Label, Static

from broca_tui.stores.chat_store import TurnSummary


class TurnCard(Widget):
    """Turn 摘要卡片 — 渲染单个执行轮次的摘要信息。"""

    class FileDiffRequested(Message):
        """点击文件名时触发，沿父链冒泡到 ChatScreen 处理。"""

        def __init__(self, turn_id: str, file_path: str) -> None:
            super().__init__()
            self.turn_id = turn_id
            self.file_path = file_path

    DEFAULT_CSS = """
    TurnCard {
        height: auto;
        margin: 0 2 2 2;
        padding: 1 2;
        border-left: solid #5a8fc9;
        background: #f5f5f5;
    }

    TurnCard.consecutive-agent {
        margin: 0 2 2 2;
    }

    TurnCard.status-completed {
        border-left: solid #6b6b6b;
    }

    TurnCard.status-error {
        border-left: solid #c95a5a;
    }

    TurnCard.status-active {
        border-left: solid #5a8fc9;
    }

    .turn-card-header {
        height: auto;
        margin-bottom: 0;
        padding: 0;
    }

    .turn-header-spacer {
        width: 1fr;
        height: auto;
    }

    .turn-completion-time {
        color: #6b6b6b;
        margin: 0 1;
    }

    .turn-duration {
        margin: 0 0 0 1;
    }

    .turn-status-dot {
        text-style: bold;
        margin-right: 1;
    }

    .turn-status-dot.active {
        color: #5a8fc9;
    }

    .turn-status-dot.completed {
        color: #6b6b6b;
    }

    .turn-status-dot.error {
        color: #c95a5a;
    }

    .turn-agent-name {
        text-style: bold;
        color: $text;
        width: auto;
    }

    .turn-sequence {
        color: #6b6b6b;
        margin-left: 1;
    }

    .turn-sep {
        color: #3c3c3c;
    }

    .turn-status-text {
        text-style: bold;
        margin: 0 1 0 0;
    }

    .turn-status-text.active {
        color: #5a8fc9;
    }

    .turn-status-text.completed {
        color: #6b6b6b;
    }

    .turn-status-text.error {
        color: #c95a5a;
    }

    .turn-duration {
        color: #6b6b6b;
    }

    /* 区域左侧竖线 + 底部隔线 */
    .section-accent {
        height: auto;
        border-left: solid #3c3c3c;
        border-bottom: solid #3c3c3c;
        padding: 0 0 0 1;
        margin: 1 0 0 0;
    }

    .accent-user {
        border-left: solid #6b6b6b;
    }

    .accent-tool {
        border-left: solid #c9a84c;
    }

    .accent-agent {
        border-left: solid #5a8fc9;
    }

    .turn-user-message {
        height: auto;
        padding: 0;
        margin: 2 0 0 0;
    }

    .turn-user-icon {
        color: #6b6b6b;
    }

    .turn-user-text {
        color: $text;
        width: 1fr;
    }

    .turn-user-msg-content {
        height: auto;
        width: 1fr;
    }

    .turn-user-msg-content.collapsed {
        max-height: 6;
        overflow: hidden;
    }

    .turn-summary-section {
        height: auto;
        padding: 0;
        margin: 0;
    }

    .turn-summary-title {
        color: #6b6b6b;
        text-style: bold;
        margin-bottom: 0;
        margin-top: 0;
    }

    .turn-summary-row {
        height: auto;
        padding: 0 0 0 1;
    }

    .turn-summary-label {
        color: #6b6b6b;
        width: 20;
    }

    .turn-summary-value {
        color: $text;
        width: 1fr;
    }

    .turn-current-call {
        height: auto;
        width: 1fr;
        margin: 1 0 0 0;
        align: left middle;
        padding: 1 1;
        background: rgba(201, 168, 76, 0.1);
        border: none;
    }

    .turn-current-call-label {
        height: auto;
        width: auto;
        color: #6b6b6b;
        margin: 0 0 0 0;
    }

    .turn-current-call-tool {
        height: auto;
        width: auto;
        color: $text;
        margin: 0 1 0 0;
        text-style: bold;
    }

    .turn-reasoning-toggle {
        color: #f59e0b;
        text-style: bold;
    }

    .turn-reasoning-toggle:hover {
        text-style: bold underline;
    }

    .turn-reasoning-content {
        height: auto;
        background: transparent;
        border-left: solid #f59e0b;
        padding: 1;
        margin: 1 0;
    }

    .turn-reasoning-text {
        color: #f59e0b;
        text-style: italic;
    }

    .turn-undo-container {
        dock: bottom;
        height: auto;
        align-horizontal: right;
        margin: 0;
        padding: 0 1;
    }

    Button.turn-undo-button {
        width: auto;
        height: auto;
        min-width: 0;
        min-height: 0;
        padding: 0 1;
        margin: 0;
        background: transparent;
        color: #6b6b6b;
        border: none;
        text-style: none;
    }

    Button.turn-undo-button:focus {
        text-style: none;
        background: transparent;
        border: none;
    }

    Button.turn-undo-button:hover {
        color: #ef4444;
        text-style: bold;
        background: transparent;
    }

    .turn-todo-list {
        height: auto;
        padding: 0 0 0 0;
        border-left: solid #c9a84c;
    }

    #changed-files-summary {
        color: $text;
    }

    #changed-files-summary:hover {
        text-style: bold underline;
    }

    .changed-files-detail {
        height: auto;
        margin: 0 0 0 2;
        padding: 1 1;
        border-left: solid #c9a84c;
        background: rgba(201, 168, 76, 0.06);
    }

    #changed-files-detail-text {
        color: $text;
    }

    #changed-files-detail Label {
        height: auto;
    }

    #changed-files-detail Label:hover {
        text-style: bold underline;
    }

    .cf-file-btn {
        width: 1fr;
        height: auto;
        min-width: 0;
        min-height: 0;
        padding: 0 1;
        margin: 0;
        background: transparent;
        border: none;
        text-style: none;
        color: $text;
    }

    .cf-file-btn:hover {
        text-style: bold underline;
        background: transparent;
        border: none;
    }

    .cf-file-btn:focus {
        text-style: none;
        background: transparent;
        border: none;
    }

    .cf-group-label {
        text-style: bold;
        margin-top: 1;
    }

    .cf-added-label {
        color: #16a34a;
    }

    .cf-deleted-label {
        color: #dc2626;
    }

    .cf-modified-label {
        color: #ca8a04;
    }

    .turn-tool-stats {
        color: $text;
    }

    .turn-todo-item {
        height: auto;
        margin: 0 0 0 2;
    }

    .turn-response-section {
        height: auto;
        padding: 0;
        margin: 0;
    }

    .turn-response-icon {
        color: #5a8fc9;
    }

    .turn-response-content {
        height: auto;
        width: 1fr;
    }

    .turn-response-content.collapsed {
        max-height: 25;
        overflow: hidden;
    }

    .turn-fold-label {
        height: auto;
        color: #6b6b6b;
        text-style: none;
        padding: 0 1;
        margin: 0 0 0 3;
        opacity: 0.6;
    }

    .turn-fold-label:hover {
        text-style: none;
        opacity: 1;
    }
    """

    def __init__(
        self,
        turn: TurnSummary,
        agent_name_map: Optional[Dict[str, str]] = None,
        consecutive_agent: bool = False,
        **kwargs,
    ):
        """初始化 TurnCard。

        Args:
            turn: TurnSummary 数据
            agent_name_map: agent_id → display_name 映射
            consecutive_agent: 与上一个 turn 是否为同一 Agent（控制间距）
        """
        super().__init__(**kwargs)
        self._turn = turn
        self._agent_name_map = agent_name_map or {}
        self._consecutive_agent = consecutive_agent
        self._show_reasoning = False
        self._show_changed_files_detail = False  # 文件变更详情默认折叠
        self._file_diff_paths: Dict[
            int, str
        ] = {}  # idx → file_path, 用于点击文件查看 diff
        self._response_expanded = True  # 回复默认展开，过长时可折叠
        self._response_manually_toggled = False  # 用户是否手动切换过折叠状态（防止自动折叠覆盖）
        self._user_msg_expanded = True  # 用户消息默认展开，超长时可折叠
        self._user_msg_manually_toggled = False  # 用户是否手动切换过用户消息折叠状态
        self._last_reasoning_update = 0.0  # 推理内容节流时间戳
        self._last_response_update = 0.0  # 回复内容节流时间戳
        self._last_tool_update = 0.0  # 工具调用节流时间戳

    def update_turn(
        self, turn: TurnSummary, agent_name_map: Optional[Dict[str, str]] = None
    ):
        """更新卡片内容（仅 in-place 更新，永不重建 DOM），用于流式更新避免闪烁。

        Args:
            turn: 新的 TurnSummary 数据
            agent_name_map: 可选的 agent 名称映射更新
        """
        self._turn = copy.deepcopy(turn)
        if agent_name_map is not None:
            self._agent_name_map = agent_name_map

        # 更新标题栏（始终有）
        try:
            self.query_one(".turn-agent-name", Label).update(
                self._get_agent_display_name()
            )
        except Exception:
            pass
        try:
            self.query_one(".turn-duration", Label).update(
                f"⏱️ {self._get_formatted_duration()}"
            )
        except Exception:
            pass

        # 更新完成时刻
        try:
            ct_label = self.query_one("#turn-completion-time", Label)
            ct = self._get_formatted_completion_time()
            if ct:
                ct_label.update(f"🕐 {ct}")
                ct_label.display = True
            else:
                ct_label.display = False
        except Exception:
            pass

        # 更新状态点 + 状态文本（根据 simplified_status 切换 class 和文字）
        simplified = self._get_simplified_status()
        try:
            dot = self.query_one(".turn-status-dot", Label)
            dot.classes = f"turn-status-dot {simplified}"
        except Exception:
            pass
        try:
            status_text = self.query_one("#turn-status-text", Label)
            status_text.update(self._get_status_text())
            status_text.classes = f"turn-status-text {simplified}"
        except Exception:
            pass

        # 更新用户消息文本
        try:
            self.query_one("#user-msg-text", Label).update(
                self._turn.user_message or ""
            )
        except Exception:
            pass

        # 更新回复内容（节流，避免频繁 Markdown 重渲染）
        if self._turn.final_response:
            try:
                resp_text = self.query_one("#response-text", Static)
                now = time.time()
                if now - self._last_response_update >= 0.025:
                    resp_text.update(
                        Markdown(
                            self._format_response(self._turn.final_response),
                            code_theme="friendly",
                        )
                    )
                    self._last_response_update = now
            except Exception:
                pass

        # 更新推理内容（节流：折叠时 ≤0.5Hz，展开时 ≤2.5Hz）
        if self._turn.reasoning_content:
            try:
                reasoning_label = self.query_one("#reasoning-text", Label)
                now = time.time()
                throttle = 2.0 if not self._show_reasoning else 0.4
                if now - self._last_reasoning_update < throttle:
                    pass
                else:
                    reasoning_label.update(self._turn.reasoning_content)
                    self._last_reasoning_update = now
            except Exception:
                pass

        # 更新步骤数
        try:
            self.query_one("#turn-steps-value", Label).update(
                str(self._turn.total_steps)
            )
        except Exception:
            pass

        # 更新工具调用统计 + 当前工具名（节流 ≤5Hz）
        try:
            now = time.time()
            if now - self._last_tool_update >= 0.2:
                stats_label = self.query_one("#tool-stats-text", Label)
                stats_label.update(self._get_tool_stats_text())

                tool_label = self.query_one("#current-call-tool", Label)
                tool_label.update(self._turn.current_tool or "")

                self._last_tool_update = now
        except Exception:
            pass

        # 更新文件变更统计和详情（使用 plain text 避免 Rich markup span 拦截点击事件）
        try:
            cf = self._turn.changed_files
            if cf:
                cf_summary = self.query_one("#changed-files-summary", Label)
                if cf_summary:
                    added = cf.get("total_added", 0)
                    deleted = cf.get("total_deleted", 0)
                    modified = cf.get("total_modified", 0)
                    toggle_icon = "▼" if self._show_changed_files_detail else "▶"
                    cf_summary.update(f"+{added} -{deleted} ~{modified} {toggle_icon}")

                # 更新预创建的 Label：每组用各自的索引范围
                MAX = 50
                self._file_diff_paths.clear()
                # 新增 (idx 0-49)
                added = cf.get("files_added", [])
                self._toggle_display("#cf-head-added", bool(added))
                for i, f in enumerate(added):
                    if i < MAX:
                        self.query_one(f"#cf-file-{i}", Label).update(f)
                        self.query_one(f"#cf-file-{i}", Label).display = True
                        self._file_diff_paths[i] = f
                for i in range(len(added), MAX):
                    try:
                        self.query_one(f"#cf-file-{i}", Label).display = False
                    except Exception:
                        pass
                # 删除 (idx 50-99)
                deleted = cf.get("files_deleted", [])
                self._toggle_display("#cf-head-deleted", bool(deleted))
                for i, f in enumerate(deleted):
                    idx = MAX + i
                    if i < MAX:
                        self.query_one(f"#cf-file-{idx}", Label).update(f)
                        self.query_one(f"#cf-file-{idx}", Label).display = True
                        self._file_diff_paths[idx] = f
                for i in range(len(deleted), MAX):
                    try:
                        self.query_one(f"#cf-file-{MAX + i}", Label).display = False
                    except Exception:
                        pass
                # 修改 (idx 100-149)
                modified = cf.get("files_modified", [])
                self._toggle_display("#cf-head-modified", bool(modified))
                for i, f in enumerate(modified):
                    idx = MAX * 2 + i
                    if i < MAX:
                        self.query_one(f"#cf-file-{idx}", Label).update(f)
                        self.query_one(f"#cf-file-{idx}", Label).display = True
                        self._file_diff_paths[idx] = f
                for i in range(len(modified), MAX):
                    try:
                        self.query_one(f"#cf-file-{MAX * 2 + i}", Label).display = False
                    except Exception:
                        pass
        except Exception:
            pass

        # 更新 TODO 列表内容 — 预创建 Label，只 update + display 切换
        MAX_TODO_ITEMS = 50
        if self._show_todo_list():
            try:
                for i, todo in enumerate(self._turn.current_todo_list):
                    if i >= MAX_TODO_ITEMS:
                        break
                    todo_name = todo.get("name", "")
                    todo_status = todo.get("status", "pending")
                    icon = (
                        "✅"
                        if todo_status == "completed"
                        else ("⏳" if todo_status == "in_progress" else "⬜️")
                    )
                    label = self.query_one(f"#todo-item-{i}", Label)
                    label.update(f"{icon} {todo_name}")
                    label.display = True
                # 剩余预创建项隐藏
                remaining = len(self._turn.current_todo_list)
                for i in range(remaining, MAX_TODO_ITEMS):
                    try:
                        self.query_one(f"#todo-item-{i}", Label).display = False
                    except Exception:
                        pass
            except Exception:
                pass

        # 更新卡片基础 class（status / consecutive 变化时切换）
        base_class = f"turn-card status-{self._get_simplified_status()}"
        if self._consecutive_agent:
            base_class += " consecutive-agent"
        self.classes = base_class

        # 更新各区域显隐（所有区域已预创建，只切换 display）
        self._update_all_sections()

    def _get_simplified_status(self) -> str:
        """获取简化状态（对齐 Web：active/thinking/calling_tool → active）。"""
        if self._turn.status == "completed":
            return "completed"
        if self._turn.status == "error":
            return "error"
        return "active"

    def _get_status_text(self) -> str:
        """获取状态文本。"""
        status_map = {"active": "进行中", "completed": "已完成", "error": "中断"}
        return status_map.get(self._get_simplified_status(), "未知")

    def _get_formatted_duration(self) -> str:
        """格式化耗时。

        活跃 turn 动态计算（from started_at），已完成 turn 使用缓存的 total_duration。
        """
        import time

        if self._turn.is_active:
            seconds = round((time.time() * 1000 - self._turn.started_at) / 1000)
        else:
            seconds = round(self._turn.total_duration)
        if seconds < 60:
            return f"{seconds}s"
        mins = seconds // 60
        secs = seconds % 60
        return f"{mins}分{secs}秒"

    def _get_formatted_completion_time(self) -> str:
        """格式化完成时刻（已完成的 turn，用 started_at + total_duration 算出结束时间）。"""
        if self._turn.is_active:
            return ""
        import datetime as dt
        import time as tm

        # 优先用 started_at（活跃 turn 有 ms 时间戳），否则用 created_at（ISO 格式）
        if self._turn.started_at > 0:
            end_ms = self._turn.started_at + self._turn.total_duration * 1000
            d = tm.localtime(end_ms / 1000)
        elif self._turn.created_at:
            try:
                created = dt.datetime.fromisoformat(
                    self._turn.created_at.replace("Z", "+00:00")
                )
                if created.tzinfo is None:
                    created = created.replace(tzinfo=dt.timezone.utc)
                end_ts = created.timestamp() + self._turn.total_duration
                d = tm.localtime(end_ts)
            except Exception:
                return ""
        else:
            return ""

        now = tm.localtime()
        time_str = f"{d.tm_hour:02d}:{d.tm_min:02d}:{d.tm_sec:02d}"
        if d.tm_yday != now.tm_yday or d.tm_year != now.tm_year:
            return f"{d.tm_year}-{d.tm_mon:02d}-{d.tm_mday:02d} {time_str}"
        return time_str

    def _has_tool_execution(self) -> bool:
        """判断是否有工具执行。"""
        return (
            bool(self._turn.tool_call_stats)
            or bool(self._turn.current_tool)
            or self._show_file_path()
            or self._show_todo_list()
            or self._show_changed_files()
        )

    def _show_changed_files(self) -> bool:
        """判断是否有文件变更可展示。"""
        cf = self._turn.changed_files
        if not cf:
            return False
        return (
            cf.get("total_added", 0) > 0
            or cf.get("total_deleted", 0) > 0
            or cf.get("total_modified", 0) > 0
        )

    def _show_file_path(self) -> bool:
        """判断是否显示文件路径。"""
        return bool(
            self._turn.current_file_path
            and self._turn.current_tool
            and self._turn.current_tool in ("read_file", "edit_file", "write_file")
        )

    def _show_todo_list(self) -> bool:
        """判断是否显示 TODO 列表。"""
        return bool(
            self._turn.current_todo_list and len(self._turn.current_todo_list) > 0
        )

    def _get_tool_stats_text(self) -> str:
        return ", ".join(
            f"{s.get('tool_name', s.get('toolName', '?'))} ({s.get('count', 0)}次)"
            for s in self._turn.tool_call_stats
        )

    def _get_agent_display_name(self) -> str:
        """获取 Agent 显示名称。"""
        name = self._agent_name_map.get(self._turn.agent_id) or self._turn.agent_name
        return name or self._turn.agent_id

    @staticmethod
    def _format_response(text: str) -> str:
        """格式化回复内容，确保不同 chunk 之间的 \\n\\n 保留。

        现在不同 message 之间的空行已在 update_turn_on_agent_response 中
        通过追加 \\n\\n 处理，此方法仅做基本清理。
        """
        return text.replace("\r\n", "\n")

    def _can_undo(self) -> bool:
        """判断是否可撤销。"""
        return self._turn.status in ("completed", "error") and bool(
            self._turn.last_message_id
        )

    def _needs_fold(self) -> bool:
        """判断回复内容是否需要折叠（超过 25 行）。"""
        content = (self._turn.final_response or "").strip()
        if not content:
            return False
        return content.count("\n") > 25

    def _needs_user_fold(self) -> bool:
        """判断用户消息是否需要折叠（超过 300 字符）。"""
        content = (self._turn.user_message or "").strip()
        if not content:
            return False
        return len(content) > 300

    def compose(self) -> ComposeResult:
        """创建 TurnCard 布局 — 所有区域始终创建，通过 display 控制显隐，避免 DOM 重建闪烁。"""
        simplified_status = self._get_simplified_status()
        status_text = self._get_status_text()
        agent_name = self._get_agent_display_name()

        # 设置状态 class
        base_class = f"turn-card status-{simplified_status}"
        if self._consecutive_agent:
            base_class += " consecutive-agent"
        self.classes = base_class

        # ===== 标题栏（始终有） — 对齐 Web 版左右两组布局 =====
        completion_time = self._get_formatted_completion_time()
        with Horizontal(classes="turn-card-header"):
            yield Label("●", classes=f"turn-status-dot {simplified_status}")
            yield Label(agent_name, classes="turn-agent-name")
            yield Label(f"第{self._turn.sequence_number}轮", classes="turn-sequence")
            yield Label("", classes="turn-header-spacer")
            yield Label(
                status_text,
                classes=f"turn-status-text {simplified_status}",
                id="turn-status-text",
            )
            yield Label("|", classes="turn-sep")
            yield Label(
                f"🕐 {completion_time}" if completion_time else "",
                classes="turn-completion-time",
                id="turn-completion-time",
            )
            yield Label(f"⏱️ {self._get_formatted_duration()}", classes="turn-duration")

        # ===== 用户消息（始终创建，初始隐藏） =====
        with Horizontal(
            classes="turn-user-message section-accent accent-user",
            id="user-msg-section",
        ):
            yield Label("👤", classes="turn-user-icon")
            with Vertical(classes="turn-user-msg-content", id="user-msg-content"):
                yield Label(
                    self._turn.user_message or "",
                    classes="turn-user-text",
                    id="user-msg-text",
                )
        yield Label("展开全部", id="toggle-user-msg", classes="turn-fold-label")

        # ===== 执行摘要（始终创建，初始隐藏） =====
        with Vertical(
            classes="turn-summary-section section-accent accent-tool",
            id="tool-summary-section",
        ):
            yield Label("执行摘要", classes="turn-summary-title")
            # 步骤数
            with Horizontal(classes="turn-summary-row"):
                yield Label("📋 步骤", classes="turn-summary-label")
                yield Label(
                    str(self._turn.total_steps),
                    classes="turn-summary-value",
                    id="turn-steps-value",
                )
            # TODO 列表（容器始终存在，内部 Label 预先创建，通过 update + display 控制内容和显隐）
            MAX_TODO_ITEMS = 50
            with Vertical(classes="turn-todo-list", id="todo-list"):
                yield Label("📝 任务", classes="turn-summary-label")
                for i in range(MAX_TODO_ITEMS):
                    yield Label("", classes="turn-todo-item", id=f"todo-item-{i}")
            # 工具调用统计
            with Horizontal(classes="turn-summary-row", id="tool-stats-row"):
                yield Label("🔧 工具调用", classes="turn-summary-label")
                yield Label(
                    self._get_tool_stats_text(),
                    classes="turn-tool-stats",
                    id="tool-stats-text",
                )
            # 文件变更统计（可点击展开/折叠）
            with Horizontal(classes="turn-summary-row", id="changed-files-row"):
                yield Label(
                    "📁 变更文件",
                    classes="turn-summary-label",
                    id="changed-files-label",
                )
                yield Label(
                    "",
                    classes="turn-summary-value",
                    id="changed-files-summary",
                )
            # 文件变更详情（折叠区域，Label 预先创建，通过 display 控制显隐）
            with Vertical(classes="changed-files-detail", id="changed-files-detail"):
                MAX_FILES_PER_GROUP = 50
                yield Label(
                    "新增:", id="cf-head-added", classes="cf-group-label cf-added-label"
                )
                for i in range(MAX_FILES_PER_GROUP):
                    yield Label("", id=f"cf-file-{i}")
                yield Label(
                    "删除:",
                    id="cf-head-deleted",
                    classes="cf-group-label cf-deleted-label",
                )
                for i in range(MAX_FILES_PER_GROUP, MAX_FILES_PER_GROUP * 2):
                    yield Label("", id=f"cf-file-{i}")
                yield Label(
                    "修改:",
                    id="cf-head-modified",
                    classes="cf-group-label cf-modified-label",
                )
                for i in range(MAX_FILES_PER_GROUP * 2, MAX_FILES_PER_GROUP * 3):
                    yield Label("", id=f"cf-file-{i}")

        # ===== 回复区域（始终创建，初始隐藏） =====
        with Horizontal(
            classes="turn-response-section section-accent accent-agent",
            id="response-section",
        ):
            yield Label("🤖", classes="turn-response-icon")
            with Vertical(classes="turn-response-content", id="response-content"):
                yield Static(
                    Markdown(
                        self._format_response(self._turn.final_response or ""),
                        code_theme="friendly",
                    ),
                    id="response-text",
                )
        yield Label("展开全部", id="toggle-response", classes="turn-fold-label")

        # ===== 当前调用（始终创建，初始隐藏） =====
        with Horizontal(classes="turn-current-call", id="current-call-section"):
            yield Label("⏳ 当前调用:", classes="turn-current-call-label")
            yield Label(
                self._turn.current_tool or "",
                classes="turn-current-call-tool",
                id="current-call-tool",
            )

        # ===== 推理内容（始终创建，初始隐藏） =====
        toggle_icon = "▼" if self._show_reasoning else "▶"
        yield Label(
            f"{toggle_icon} 思考...",
            classes="turn-reasoning-toggle",
            id="reasoning-toggle",
        )
        with Vertical(classes="turn-reasoning-content", id="reasoning-content"):
            yield Label(
                self._turn.reasoning_content or "",
                classes="turn-reasoning-text",
                id="reasoning-text",
            )

        # ===== 撤销按钮（始终创建，初始隐藏） =====
        with Horizontal(classes="turn-undo-container", id="undo-container"):
            yield Button(
                "↩️ 撤销", id=f"undo-{self._turn.turn_id}", classes="turn-undo-button"
            )

    def on_mount(self) -> None:
        """Set up after mount — 初始化各区域显隐状态。"""
        self._update_all_sections()

    def _update_all_sections(self):
        """根据当前 _turn 数据，更新所有条件渲染区域的显隐 + 内容。

        所有区域已在 compose() 中预创建，这里只做：
        1. display 切换（永不重建 DOM）
        2. 文本内容更新（in-place）
        """
        # 用户消息
        has_user_msg = bool(self._turn.user_message)
        self._toggle_display("#user-msg-section", has_user_msg)
        needs_user_fold = has_user_msg and self._needs_user_fold()
        self._toggle_display("#toggle-user-msg", needs_user_fold)
        if has_user_msg:
            if not self._user_msg_manually_toggled:
                if needs_user_fold and self._user_msg_expanded:
                    self._user_msg_expanded = False
                elif not needs_user_fold and not self._user_msg_expanded:
                    self._user_msg_expanded = True
            self._update_user_msg_visibility()

        # 执行摘要整体
        has_tool = self._has_tool_execution()
        self._toggle_display("#tool-summary-section", has_tool)
        if has_tool:
            # TODO 列表
            self._toggle_display("#todo-list", self._show_todo_list())
            # 工具调用统计
            self._toggle_display("#tool-stats-row", bool(self._turn.tool_call_stats))
            # 文件变更
            show_cf = self._show_changed_files()
            self._toggle_display("#changed-files-row", show_cf)
            self._toggle_display(
                "#changed-files-detail", show_cf and self._show_changed_files_detail
            )

        # 回复区域
        has_response = bool(self._turn.final_response)
        self._toggle_display("#response-section", has_response)
        needs_fold = has_response and self._needs_fold()
        self._toggle_display("#toggle-response", needs_fold)
        # 内容首次超过阈值时自动折叠，且每次更新都维持折叠/展开状态
        # 注意：用户手动切换后（_response_manually_toggled=True），不再自动折叠/展开
        if has_response:
            if not self._response_manually_toggled:
                if needs_fold and self._response_expanded:
                    # 内容刚超过阈值，自动折叠
                    self._response_expanded = False
                elif not needs_fold and not self._response_expanded:
                    # 内容被缩短到阈值以下，自动展开
                    self._response_expanded = True
            self._update_response_visibility()

        # 当前调用 — 仅在 actively calling a tool 时显示
        # 不依赖 current_tool 的清空（已对齐 Web 版不清空行为），用 status 精确判断
        show_call = bool(
            self._turn.current_tool and self._turn.status == "calling_tool"
        )
        self._toggle_display("#current-call-section", show_call)

        # 推理内容（可折叠）— 与"当前调用"互斥，不在 calling_tool 状态时显示
        # 包括 thinking（agent 思考/回复时）、completed（回看记录时）
        show_reasoning = bool(self._turn.reasoning_content and not show_call)
        self._toggle_display("#reasoning-toggle", show_reasoning)
        self._toggle_display(
            "#reasoning-content", show_reasoning and self._show_reasoning
        )
        if show_reasoning:
            try:
                toggle = self.query_one("#reasoning-toggle", Label)
                toggle_icon = "▼" if self._show_reasoning else "▶"
                toggle.update(f"{toggle_icon} 思考")
            except Exception:
                pass

        # 撤销按钮
        self._toggle_display("#undo-container", self._can_undo())

    def _toggle_display(self, selector: str, show: bool) -> None:
        """Toggle widget display by selector.

        Args:
            selector: CSS selector for the widget
            show: True to show, False to hide
        """
        try:
            widget = self.query_one(selector)
            widget.display = show
        except Exception:
            pass

    def _update_response_visibility(self):
        """更新回复内容的折叠状态。"""
        try:
            content = self.query_one("#response-content", Vertical)
            toggle = self.query_one("#toggle-response", Label)
            if content:
                if self._response_expanded:
                    content.remove_class("collapsed")
                else:
                    content.add_class("collapsed")
            if toggle:
                toggle.update("折叠" if self._response_expanded else "展开全部")
        except Exception:
            pass

    def _update_user_msg_visibility(self):
        """更新用户消息的折叠状态。"""
        try:
            content = self.query_one("#user-msg-content", Vertical)
            toggle = self.query_one("#toggle-user-msg", Label)
            if content:
                if self._user_msg_expanded:
                    content.remove_class("collapsed")
                else:
                    content.add_class("collapsed")
            if toggle:
                toggle.update("折叠" if self._user_msg_expanded else "展开全部")
        except Exception:
            pass

    def on_click(self, event) -> None:
        """处理推理/回复/撤销的点击切换。"""
        if hasattr(event, "widget") and event.widget is not None:
            widget_id = getattr(event.widget, "id", None)
            if widget_id == "reasoning-toggle":
                self._show_reasoning = not self._show_reasoning
                # 展开时立即刷最新推理内容（节流期间可能跳过更新）
                if self._show_reasoning:
                    try:
                        label = self.query_one("#reasoning-text", Label)
                        if self._turn.reasoning_content:
                            label.update(self._turn.reasoning_content)
                            self._last_reasoning_update = time.time()
                    except Exception:
                        pass
                self._update_all_sections()
            elif widget_id in (
                "changed-files-row",
                "changed-files-summary",
                "changed-files-label",
            ):
                self._show_changed_files_detail = not self._show_changed_files_detail
                self._update_all_sections()
            elif widget_id and widget_id.startswith("cf-file-"):
                # 点击文件名 → 直接弹出 DiffViewer
                try:
                    idx = int(widget_id.replace("cf-file-", ""))
                    file_path = self._file_diff_paths.get(idx)
                    if file_path:
                        self.post_message(
                            self.FileDiffRequested(
                                turn_id=self._turn.turn_id,
                                file_path=file_path,
                            )
                        )
                except (ValueError, IndexError):
                    pass
            elif widget_id == "toggle-response":
                self._response_expanded = not self._response_expanded
                self._response_manually_toggled = True
                self._update_response_visibility()
            elif widget_id == "toggle-user-msg":
                self._user_msg_expanded = not self._user_msg_expanded
                self._user_msg_manually_toggled = True
                self._update_user_msg_visibility()
            elif widget_id and widget_id.startswith("undo-"):
                # 撤销按钮已改为 Button，由 on_button_pressed 处理
                pass

    def on_button_pressed(self, event: Button.Pressed) -> None:
        """Handle button press (undo)."""
        if event.button.id and event.button.id.startswith("undo-"):
            turn_id = event.button.id.replace("undo-", "", 1)
            parent = self.parent
            while parent is not None:
                if hasattr(parent, "_confirm_and_undo"):
                    parent._confirm_and_undo(turn_id)
                    break
                parent = parent.parent

    def _request_file_diff(self, file_path: str):
        """请求查看文件的 diff — 通过 post_message 沿父链冒泡。"""
        self.post_message(
            self.FileDiffRequested(turn_id=self._turn.turn_id, file_path=file_path)
        )

    def on_update_turn_undo_visibility(self) -> None:
        """撤销按钮始终显示（不需要 hover 触发）。"""
        pass
