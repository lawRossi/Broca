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

from typing import Any, Dict, Optional

from rich.markdown import Markdown
from textual.app import ComposeResult
from textual.containers import Horizontal, Vertical
from textual.widgets import Button, Label, Static
from textual.widget import Widget

from broca_tui.stores.chat_store import TurnSummary


class TurnCard(Widget):
    """Turn 摘要卡片 — 渲染单个执行轮次的摘要信息。"""

    DEFAULT_CSS = """
    TurnCard {
        height: auto;
        margin: 0 2 2 2;
        padding: 1 2;
        border-left: solid #0ea5e9;
        background: white;
    }

    TurnCard.consecutive-agent {
        margin: 0 2 2 2;
    }

    TurnCard.status-completed {
        border-left: solid #10b981;
    }

    TurnCard.status-error {
        border-left: solid #ef4444;
    }

    TurnCard.status-active {
        border-left: solid #0ea5e9;
    }

    .turn-card-header {
        height: auto;
        margin-bottom: 0;
        padding: 0;
    }

    .turn-status-dot {
        text-style: bold;
        margin-right: 1;
    }

    .turn-status-dot.active {
        color: #0ea5e9;
    }

    .turn-status-dot.completed {
        color: #10b981;
    }

    .turn-status-dot.error {
        color: #ef4444;
    }

    .turn-agent-name {
        text-style: bold;
        color: #1e293b;
        width: 1fr;
    }

    .turn-sequence {
        color: #94a3b8;
    }

    .turn-duration {
        color: #64748b;
    }

    .turn-user-message {
        height: auto;
        border-bottom: solid #f1f5f9;
        padding: 0;
        margin: 0 0 0 0;
    }

    .turn-user-icon {
        color: #3b82f6;
    }

    .turn-user-text {
        color: #475569;
        width: 1fr;
    }

    .turn-summary-section {
        height: auto;
        padding: 0;
        margin: 0;
    }

    .turn-summary-title {
        color: #94a3b8;
        text-style: bold;
        margin-bottom: 0;
        margin-top: 0;
    }

    .turn-summary-row {
        height: auto;
        padding: 0 0 0 1;
    }

    .turn-summary-label {
        color: #94a3b8;
        width: 12;
    }

    .turn-summary-value {
        color: #334155;
        width: 1fr;
    }

    .turn-summary-status {
        text-style: bold;
    }

    .turn-summary-status.active {
        color: #0ea5e9;
    }

    .turn-summary-status.completed {
        color: #10b981;
    }

    .turn-summary-status.error {
        color: #ef4444;
    }

    .turn-response-section {
        height: auto;
        padding: 0;
        margin: 0;
    }

    .turn-response-icon {
        color: #22c55e;
    }

    .turn-response-content {
        height: auto;
        width: 1fr;
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
        background: #fffbeb;
        border: solid #e2e8f0;
        padding: 1;
        margin: 1 0;
    }

    .turn-reasoning-text {
        color: #475569;
        text-style: italic;
    }

    .turn-undo-button {
        dock: right;
        background: transparent;
        color: #94a3b8;
        border: none;
        min-width: 8;
        padding: 0 1;
        margin: 0;
        text-style: none;
    }

    .turn-undo-button:hover {
        background: transparent;
        color: #ef4444;
        text-style: bold;
    }

    .turn-todo-list {
        height: auto;
        padding: 0 0 0 2;
    }

    .turn-todo-item {
        height: auto;
        padding: 0 0 0 1;
    }

    .turn-tool-stats {
        color: #475569;
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
        """格式化耗时。"""
        seconds = round(self._turn.total_duration)
        if seconds < 60:
            return f"{seconds}s"
        mins = seconds // 60
        secs = seconds % 60
        return f"{mins}分{secs}秒"

    def _has_tool_execution(self) -> bool:
        """判断是否有工具执行。"""
        return (
            bool(self._turn.tool_call_stats)
            or bool(self._turn.current_tool)
            or self._show_file_path()
            or self._show_todo_list()
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
        return bool(self._turn.current_todo_list and len(self._turn.current_todo_list) > 0)

    def _get_tool_stats_text(self) -> str:
        """获取工具调用统计文本。"""
        return ", ".join(
            f'{s.get("toolName", "?")} ({s.get("count", 0)}次)'
            for s in self._turn.tool_call_stats
        )

    def _get_agent_display_name(self) -> str:
        """获取 Agent 显示名称。"""
        name = self._agent_name_map.get(self._turn.agent_id) or self._turn.agent_name
        return name or self._turn.agent_id

    def _can_undo(self) -> bool:
        """判断是否可撤销。"""
        return self._turn.status == "completed" and bool(self._turn.last_message_id)

    def compose(self) -> ComposeResult:
        """创建 TurnCard 布局。"""
        simplified_status = self._get_simplified_status()
        status_text = self._get_status_text()
        agent_name = self._get_agent_display_name()

        # 设置状态 class
        base_class = f"turn-card status-{simplified_status}"
        if self._consecutive_agent:
            base_class += " consecutive-agent"
        self.classes = base_class

        # ===== 标题栏 =====
        with Horizontal(classes="turn-card-header"):
            yield Label("●", classes=f"turn-status-dot {simplified_status}")
            yield Label(agent_name, classes="turn-agent-name")
            yield Label(f"第{self._turn.sequence_number}轮", classes="turn-sequence")
            yield Label(f"⏱️ {self._get_formatted_duration()}", classes="turn-duration")

        # ===== 用户消息 =====
        if self._turn.user_message:
            with Horizontal(classes="turn-user-message"):
                yield Label("👤", classes="turn-user-icon")
                yield Label(self._turn.user_message, classes="turn-user-text")

        # ===== 执行摘要 =====
        if self._has_tool_execution():
            with Vertical(classes="turn-summary-section"):
                yield Label("执行摘要", classes="turn-summary-title")

                # 步骤数
                with Horizontal(classes="turn-summary-row"):
                    yield Label("📋 步骤", classes="turn-summary-label")
                    yield Label(str(self._turn.total_steps), classes="turn-summary-value")

                # 状态
                with Horizontal(classes="turn-summary-row"):
                    yield Label("🔄 状态", classes="turn-summary-label")
                    yield Label(status_text, classes=f"turn-summary-status {simplified_status}")

                # 当前工具
                if self._turn.current_tool:
                    with Horizontal(classes="turn-summary-row"):
                        yield Label("🔧 工具", classes="turn-summary-label")
                        yield Label(self._turn.current_tool, classes="turn-summary-value")

                # 文件路径
                if self._show_file_path():
                    with Horizontal(classes="turn-summary-row"):
                        yield Label("📁 文件", classes="turn-summary-label")
                        yield Label(self._turn.current_file_path or "", classes="turn-summary-value")

                # TODO 列表
                if self._show_todo_list():
                    with Vertical(classes="turn-todo-list"):
                        yield Label("📝 任务", classes="turn-summary-label")
                        for todo in self._turn.current_todo_list:
                            todo_name = todo.get("name", "")
                            todo_status = todo.get("status", "pending")
                            icon = "✅" if todo_status == "completed" else ("⏳" if todo_status == "in_progress" else "⬜️")
                            with Horizontal(classes="turn-todo-item"):
                                yield Label(f"{icon} {todo_name}")

                # 工具调用统计
                if self._turn.tool_call_stats:
                    with Horizontal(classes="turn-summary-row"):
                        yield Label("🔧 工具调用", classes="turn-summary-label")
                        yield Label(self._get_tool_stats_text(), classes="turn-tool-stats")

        # ===== 回复区域 =====
        if self._turn.final_response:
            with Horizontal(classes="turn-response-section"):
                yield Label("🤖", classes="turn-response-icon")
                with Vertical(classes="turn-response-content"):
                    yield Static(Markdown(self._turn.final_response))

        # ===== 推理内容（可折叠） =====
        if self._turn.reasoning_content:
            toggle_icon = "▼" if self._show_reasoning else "▶"
            yield Label(f"{toggle_icon} 思考", classes="turn-reasoning-toggle", id="reasoning-toggle")
            # 始终包含 content，通过 display 控制显隐
            with Vertical(classes="turn-reasoning-content", id="reasoning-content"):
                yield Label(self._turn.reasoning_content, classes="turn-reasoning-text")

        # ===== 撤销按钮（hover 显示） =====
        if self._can_undo():
            yield Button("↩️ 撤销", id=f"undo-{self._turn.turn_id}", classes="turn-undo-button")

    def on_mount(self) -> None:
        """Set up after mount."""
        # 初始隐藏推理内容和撤销按钮
        self._update_reasoning_visibility()
        try:
            undo_btn = self.query_one(f"#undo-{self._turn.turn_id}", Button)
            if undo_btn:
                undo_btn.display = False
        except Exception:
            pass

    def _update_reasoning_visibility(self):
        """更新推理内容的显示状态。"""
        try:
            content = self.query_one("#reasoning-content", Vertical)
            toggle = self.query_one("#reasoning-toggle", Label)
            if content:
                content.display = self._show_reasoning
            if toggle:
                toggle_icon = "▼" if self._show_reasoning else "▶"
                toggle.update(f"{toggle_icon} 思考")
        except Exception:
            pass

    def on_click(self, event) -> None:
        """处理推理内容的点击切换。"""
        if hasattr(event, 'widget') and event.widget is not None:
            widget_id = getattr(event.widget, 'id', None)
            if widget_id == "reasoning-toggle":
                self._show_reasoning = not self._show_reasoning
                self._update_reasoning_visibility()

    def on_enter(self) -> None:
        """鼠标进入时显示撤销按钮。"""
        self._show_actions = True
        try:
            undo_btn = self.query_one(f"#undo-{self._turn.turn_id}", Button)
            if undo_btn:
                undo_btn.display = True
        except Exception:
            pass

    def on_leave(self) -> None:
        """鼠标离开时隐藏撤销按钮。"""
        self._show_actions = False
        try:
            undo_btn = self.query_one(f"#undo-{self._turn.turn_id}", Button)
            if undo_btn:
                undo_btn.display = False
        except Exception:
            pass
