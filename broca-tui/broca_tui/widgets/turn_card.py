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
        width: 1fr;
    }

    .turn-sequence {
        color: #6b6b6b;
    }

    .turn-sep {
        color: #3c3c3c;
    }

    .turn-status-text {
        text-style: bold;
        margin-right: 0;
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
        margin: 0 0 0 0;
    }

    .turn-user-icon {
        color: #6b6b6b;
    }

    .turn-user-text {
        color: $text;
        width: 1fr;
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
        padding: 1 2;
        background: rgba(201, 168, 76, 0.1);
        border: solid #c9a84c;
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
        padding: 0 0 0 2;
        border-left: solid #c9a84c;
    }

    .turn-todo-item {
        height: auto;
        padding: 0 0 0 1;
    }

    .turn-tool-stats {
        color: $text;
    }

    .turn-summary-value {
        color: $text;
        width: 1fr;
    }

    .turn-todo-item {
        height: auto;
        padding: 0 0 0 1;
    }

    .turn-tool-stats {
        color: $text;
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
        max-height: 20;
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
        self._response_expanded = True  # 回复默认展开，过长时可折叠
        self._last_reasoning_update = 0.0  # 推理内容节流时间戳
        self._last_response_update = 0.0  # 回复内容节流时间戳
        self._last_tool_update = 0.0  # 工具调用节流时间戳

    def update_turn(self, turn: TurnSummary, agent_name_map: Optional[Dict[str, str]] = None):
        """更新卡片内容（不重建 DOM），用于流式更新避免闪烁。

        Args:
            turn: 新的 TurnSummary 数据
            agent_name_map: 可选的 agent 名称映射更新
        """
        # 深拷贝保持 self._turn 独立于 live TurnSummary（来自 chat_store.turn_summaries），
        # 使得 _render_turn_cards 中的 _conditions_changed 能正确检测数据变化，
        # 触发全量重建以创建条件渲染区域（回复、推理、工具调用等）。
        # 如果直接 self._turn = turn，则 _conditions_changed 比较同一对象的引用，
        # 永远返回 False，条件渲染元素永不创建 → Bug: 新 turn 只有 header 不更新内容。
        self._turn = copy.deepcopy(turn)
        if agent_name_map is not None:
            self._agent_name_map = agent_name_map

        # 更新标题栏（始终有）
        try:
            self.query_one(".turn-agent-name", Label).update(self._get_agent_display_name())
        except Exception:
            pass
        try:
            self.query_one(".turn-duration", Label).update(f"⏱️ {self._get_formatted_duration()}")
        except Exception:
            pass

        # 更新状态点（根据 simplified_status 切换 class）
        simplified = self._get_simplified_status()
        try:
            dot = self.query_one(".turn-status-dot", Label)
            dot.classes = f"turn-status-dot {simplified}"
        except Exception:
            pass

        # 更新回复内容（节流，避免频繁 Markdown 重渲染）
        try:
            resp_text = self.query_one("#response-text", Static)
            if turn.final_response:
                now = time.time()
                if now - self._last_response_update >= 0.4:
                    resp_text.update(Markdown(self._format_response(turn.final_response), code_theme="friendly"))
                    self._last_response_update = now
        except Exception:
            pass

        # 更新推理内容（节流：折叠时 ≤0.5Hz，展开时 ≤2.5Hz）
        try:
            reasoning_label = self.query_one("#reasoning-text", Label)
            if turn.reasoning_content:
                now = time.time()
                throttle = 2.0 if not self._show_reasoning else 0.4
                if now - self._last_reasoning_update < throttle:
                    # 距上次更新不足节流间隔，跳过本次更新
                    pass
                else:
                    reasoning_label.update(turn.reasoning_content)
                    self._last_reasoning_update = now
        except Exception:
            pass

        # 更新工具调用信息（节流 ≤5Hz）
        try:
            now = time.time()
            if now - self._last_tool_update >= 0.2:
                stats_label = self.query_one(".turn-tool-stats", Label)
                stats_label.update(self._get_tool_stats_text())

                tool_label = self.query_one(".turn-current-call-tool", Label)
                if turn.current_tool:
                    tool_label.update(turn.current_tool)

                self._last_tool_update = now
        except Exception:
            pass

        # 更新 TODO 列表内容（列表容器已由全量重建创建）
        try:
            todo_container = self.query_one(".turn-todo-list", Vertical)
            if self._show_todo_list():
                todo_container.remove_children()
                for todo in turn.current_todo_list:
                    todo_name = todo.get("name", "")
                    todo_status = todo.get("status", "pending")
                    icon = "✅" if todo_status == "completed" else ("⏳" if todo_status == "in_progress" else "⬜️")
                    h = Horizontal(classes="turn-todo-item")
                    h.mount(Label(f"{icon} {todo_name}"))
                    todo_container.mount(h)
        except Exception:
            pass

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
        return ", ".join(
            f'{s.get("tool_name", s.get("toolName", "?"))} ({s.get("count", 0)}次)'
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
        return self._turn.status in ("completed", "error") and bool(self._turn.last_message_id)

    def _needs_fold(self) -> bool:
        """判断回复内容是否需要折叠（超过 20 行）。"""
        content = (self._turn.final_response or "").strip()
        if not content:
            return False
        return content.count('\n') > 20

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
            yield Label("|", classes="turn-sep")
            yield Label(status_text, classes=f"turn-status-text {simplified_status}")
            yield Label(f"⏱️ {self._get_formatted_duration()}", classes="turn-duration")

        # ===== 用户消息 =====
        if self._turn.user_message:
            with Horizontal(classes="turn-user-message section-accent accent-user"):
                yield Label("👤", classes="turn-user-icon")
                yield Label(self._turn.user_message, classes="turn-user-text")

        # ===== 执行摘要 =====
        if self._has_tool_execution():
            with Vertical(classes="turn-summary-section section-accent accent-tool"):
                yield Label("执行摘要", classes="turn-summary-title")

                # 步骤数
                with Horizontal(classes="turn-summary-row"):
                    yield Label("📋 步骤", classes="turn-summary-label")
                    yield Label(str(self._turn.total_steps), classes="turn-summary-value")

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
            with Horizontal(classes="turn-response-section section-accent accent-agent"):
                yield Label("🤖", classes="turn-response-icon")
                with Vertical(classes="turn-response-content", id="response-content"):
                    yield Static(Markdown(self._format_response(self._turn.final_response), code_theme="friendly"), id="response-text")
            # 内容过长时显示折叠标签
            if self._needs_fold():
                yield Label("展开全部", id="toggle-response", classes="turn-fold-label")

        # ===== 当前调用（与工具名同一行，不显示文件路径） =====
        if self._turn.current_tool and self._turn.status != "completed":
            with Horizontal(classes="turn-current-call"):
                yield Label("⏳ 当前调用:", classes="turn-current-call-label")
                yield Label(self._turn.current_tool, classes="turn-current-call-tool")

        # ===== 推理内容（可折叠，仅在无当前工具或 turn 已完成时显示） =====
        if self._turn.reasoning_content and (self._turn.status == "completed" or not self._turn.current_tool):
            toggle_icon = "▼" if self._show_reasoning else "▶"
            yield Label(f"{toggle_icon} 思考", classes="turn-reasoning-toggle", id="reasoning-toggle")
            # 始终包含 content，通过 display 控制显隐
            with Vertical(classes="turn-reasoning-content", id="reasoning-content"):
                yield Label(self._turn.reasoning_content, classes="turn-reasoning-text", id="reasoning-text")

        # ===== 撤销按钮（始终显示，右下角） =====
        if self._can_undo():
            with Horizontal(classes="turn-undo-container"):
                yield Button("↩️ 撤销", id=f"undo-{self._turn.turn_id}", classes="turn-undo-button")

    def on_mount(self) -> None:
        """Set up after mount."""
        # 初始隐藏推理内容
        self._update_reasoning_visibility()

        # 回复内容默认展开，如果内容超长且有折叠按钮，默认折叠
        if self._needs_fold():
            self._response_expanded = False
            self._update_response_visibility()

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

    def on_click(self, event) -> None:
        """处理推理/回复/撤销的点击切换。"""
        if hasattr(event, 'widget') and event.widget is not None:
            widget_id = getattr(event.widget, 'id', None)
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
                self._update_reasoning_visibility()
            elif widget_id == "toggle-response":
                self._response_expanded = not self._response_expanded
                self._update_response_visibility()
            elif widget_id and widget_id.startswith("undo-"):
                # 撤销按钮已改为 Button，由 on_button_pressed 处理
                pass

    def on_button_pressed(self, event: Button.Pressed) -> None:
        """Handle undo button press."""
        if event.button.id and event.button.id.startswith("undo-"):
            turn_id = event.button.id.replace("undo-", "", 1)
            parent = self.parent
            while parent is not None:
                if hasattr(parent, '_confirm_and_undo'):
                    parent._confirm_and_undo(turn_id)
                    break
                parent = parent.parent

    def on_update_turn_undo_visibility(self) -> None:
        """撤销按钮始终显示（不需要 hover 触发）。"""
        pass
