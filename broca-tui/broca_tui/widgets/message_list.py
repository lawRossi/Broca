"""
MessageList Widget

Message list with:
- Virtual scrolling (via ScrollableContainer)
- Auto-scroll to bottom on new turns
- Infinite scroll up for turn history loading
- TurnCard rendering (简洁模式)
- Empty state and loading indicator
- Redo button display after undo
"""

from __future__ import annotations

import copy
from typing import Any, Callable, Dict, List, Optional

from textual.app import ComposeResult
from textual.containers import Horizontal, ScrollableContainer, Vertical
from textual.reactive import reactive
from textual.screen import ModalScreen
from textual.widgets import Button, Label, Static
from textual.widget import Widget

from broca_tui.stores.chat_store import TurnSummary
from broca_tui.widgets.turn_card import TurnCard

from broca_tui.debug_log import log, clear as debug_clear


class UndoConfirmDialog(ModalScreen):
    """Confirmation dialog for undo action (aligning with Web UX)."""

    def __init__(self, turn_id: str, sequence_number: int = 0, **kwargs):
        """Initialize undo confirmation dialog.

        Args:
            turn_id: ID of the turn to undo
            sequence_number: Turn sequence number (for display)
        """
        super().__init__(**kwargs)
        self._turn_id = turn_id
        self._sequence_number = sequence_number

    def compose(self) -> ComposeResult:
        """Create the dialog layout."""
        message_text = f"确定要撤销第{self._sequence_number}轮操作吗？此操作将同时撤销后续的相关操作。"

        with Vertical(classes="dialog"):
            yield Label("确认撤销", classes="dialog-title")
            yield Label(message_text, classes="dialog-label")
            with Horizontal(classes="dialog-actions"):
                yield Button("确定", id="btn-confirm-undo", variant="primary")
                yield Button("取消", id="btn-cancel-undo")

    def on_button_pressed(self, event: Button.Pressed) -> None:
        """Handle button presses."""
        if event.button.id == "btn-confirm-undo":
            self.dismiss({"action": "undo", "turn_id": self._turn_id})
        elif event.button.id == "btn-cancel-undo":
            self.dismiss({"action": "cancel"})


class MessageList(Vertical):
    """Scrollable message list showing TurnCards (简洁模式)."""

    DEFAULT_CSS = """
    MessageList {
        width: 1fr;
        height: 1fr;
        layout: vertical;
        overflow: hidden hidden;
    }
    MessageList #turn-area {
        height: auto;
    }
    """

    auto_scroll = reactive(True)
    loading = reactive(False)
    has_more = reactive(True)
    show_redo = reactive(False)

    # Scroll throttle: prevent multiple rapid history loads
    _SCROLL_COOLDOWN = 1.0  # seconds
    _SCROLL_POLL_INTERVAL = 0.3  # seconds

    def __init__(self, **kwargs):
        """Initialize message list."""
        super().__init__(**kwargs)
        self._turn_summaries: List[TurnSummary] = []
        self._agent_name_map: Dict[str, str] = {}
        self._on_load_more_turns: Optional[Callable] = None
        self._on_undo: Optional[Callable] = None
        self._on_redo: Optional[Callable] = None
        self._session_id: str = ""
        self._user_scrolled_up = False
        self.auto_scroll = True
        self._scroll_cooldown_active = False
        self._poll_timer = None
        self._initial_loaded = False  # 初始加载完成前阻止 scroll 触发加载
        self._prev_scroll_y = 0  # 上一次检查的 scroll_y，用于区分初始加载和用户主动滚动

    def compose(self) -> ComposeResult:
        """Create the message list layout."""
        with Vertical(classes="message-list-container"):
            # Loading indicator (shown when loading history)
            yield Label("Loading history...", classes="loading-indicator", id="loading-indicator")

            # Scrollable area — TurnCards inside Vertical (height: auto 切断 1fr 链路)
            with ScrollableContainer(id="turn-scroll", classes="message-scroll"):
                yield Vertical(id="turn-area")

            # Redo button (shown after undo)
            with Vertical(classes="redo-container", id="redo-container"):
                yield Button("↩ Redo", id="btn-redo", classes="redo-button")

    def on_mount(self) -> None:
        """Set up after mount."""
        # Hide loading and redo initially
        self.query_one("#loading-indicator", Label).display = False
        self.query_one("#redo-container", Vertical).display = False
        # Start scroll polling
        self._poll_timer = self.set_interval(self._SCROLL_POLL_INTERVAL, self._check_scroll_position)

    def set_session(self, session_id: str):
        """Set the current session ID.

        Args:
            session_id: Session ID
        """
        self._session_id = session_id

    def set_on_load_more_turns(self, callback: Callable):
        """Set callback for loading more turn history.

        Args:
            callback: Called when user scrolls to top
        """
        self._on_load_more_turns = callback

    def set_on_undo(self, callback: Callable):
        """Set callback for undo.

        Args:
            callback: Called with turn_id
        """
        self._on_undo = callback

    def set_on_redo(self, callback: Callable):
        """Set callback for redo.

        Args:
            callback: Called with ()
        """
        self._on_redo = callback

    # ==================== Turn Management ====================

    def set_turn_summaries(self, turns: List[TurnSummary], agent_name_map: Optional[Dict[str, str]] = None):
        """Replace all turns (e.g., after history load).

        Args:
            turns: List of TurnSummary
            agent_name_map: agent_id → display_name mapping
        """
        log(f" set_turn_summaries: turns={len(turns)}, initial_loaded={self._initial_loaded}")
        self._turn_summaries = turns
        if agent_name_map is not None:
            self._agent_name_map = agent_name_map
        # 只在有实际 turn 数据时才标记初始加载完成
        # 避免 set_turn_summaries([]) 提前解锁 scroll 触发
        if turns:
            self._initial_loaded = True
        # 初始加载后 auto-scroll 到底部，让用户看到最新内容
        self._render_turn_cards(auto_scroll=True)

    def add_turn_summary(self, turn: TurnSummary, agent_name_map: Optional[Dict[str, str]] = None):
        """Append a turn (real-time update).

        Args:
            turn: TurnSummary
            agent_name_map: agent_id → display_name mapping
        """
        self._turn_summaries.append(turn)
        if agent_name_map is not None:
            self._agent_name_map = agent_name_map
        # 重置用户滚动状态，确保追加新 turn 时能 auto-scroll 到底部
        # 初始加载 set_turn_summaries 不滚动，scroll_y=0导致 user_scrolled_up 被 poll 误标为 True
        self._user_scrolled_up = False
        self._render_turn_cards(auto_scroll=True)

    def _render_turn_cards(self, auto_scroll: bool = True):
        """Render all TurnCards.

        Args:
            auto_scroll: Whether to auto-scroll to bottom after render.
                         Should be True for real-time turn append, False for initial load.
        """
        try:
            area = self.query_one("#turn-area", Vertical)
            scroll = self.query_one("#turn-scroll", ScrollableContainer)
        except Exception as e:
            log(f" _render_turn_cards: query failed: {e}")
            return

        # 空 turn → 显示暂无数据
        if not self._turn_summaries:
            area.remove_children()
            log(f" _render_turn_cards: empty turns, showing '暂无 Turn 数据'")
            empty = Label("暂无 Turn 数据", classes="empty-message")
            area.mount(empty)
            return

        existing_cards = list(area.children)
        turn_count = len(self._turn_summaries)

        # 尝试增量更新：turn 数量一致且 turn_id 匹配时，只更新内容不重建 DOM
        # 但如果有条件渲染变化（final_response/reasoning/current_tool 从有到无或从无到有），
        # 必须重建，因为对应的子 widget 不存在或需要移除，update_turn 无法增减它们
        def _conditions_changed(old_turn, new_turn) -> bool:
            # 只检测需要 DOM 结构变化的场景（增删条件渲染区域），
            # 纯内容更新（如 final_response streaming 追加）走 update_turn 原地更新免闪烁。
            return (
                # final_response: 从无到有 → 创建响应区域；已有内容时只更新文本，无需重建
                (not old_turn.final_response and new_turn.final_response)
                # reasoning_content: 从无到有（创建推理区域），或从有到无（被 content 清空）
                or (not old_turn.reasoning_content and new_turn.reasoning_content)
                or (old_turn.reasoning_content and not new_turn.reasoning_content)
                # current_tool: 从无到有（创建当前调用区域），或从有到无（恢复推理/响应显示）
                or (not old_turn.current_tool and new_turn.current_tool)
                or (old_turn.current_tool and not new_turn.current_tool)
                # tool_call_stats: 从无到有（创建工具统计区域）
                or (not old_turn.tool_call_stats and new_turn.tool_call_stats)
                # user_message: 从无到有（创建用户消息区域）
                or (not old_turn.user_message and new_turn.user_message)
                # current_todo_list: 从无到有（创建 TODO 列表区域）
                or (not old_turn.current_todo_list and new_turn.current_todo_list)
                or (old_turn.current_todo_list and not new_turn.current_todo_list)
                # status: 完成/未完成切换影响条件渲染（如当前调用区域在 completed 时隐藏）
                or (old_turn.status != "completed" and new_turn.status == "completed")
                or (old_turn.status == "completed" and new_turn.status != "completed")
            )

        can_update_in_place = (
            len(existing_cards) == turn_count
            and all(
                isinstance(existing_cards[i], TurnCard)
                and existing_cards[i]._turn.turn_id == self._turn_summaries[i].turn_id
                and not _conditions_changed(existing_cards[i]._turn, self._turn_summaries[i])
                for i in range(turn_count)
            )
        )

        if can_update_in_place:
            log(f" _render_turn_cards: updating {turn_count} TurnCards in-place")
            prev_agent_id = None
            for i, turn in enumerate(self._turn_summaries):
                card = existing_cards[i]
                consecutive = (turn.agent_id == prev_agent_id)
                card._consecutive_agent = consecutive
                card.update_turn(turn, self._agent_name_map)
                prev_agent_id = turn.agent_id
                if i < 3 or i == turn_count - 1:
                    log(f" _render_turn_cards: updated card {i+1}/{turn_count}: turn_id={turn.turn_id}")
        else:
            # 精准重建：只替换条件变化的卡片，保留其他卡片 DOM 不动
            log(f" _render_turn_cards: targeted rebuild ({turn_count} cards, {len(existing_cards)} existing)")
            prev_agent_id = None

            # Step 1: 处理数量差异（末尾追加/移除）
            existing = list(area.children)
            if turn_count > len(existing):
                for i in range(len(existing), turn_count):
                    turn = self._turn_summaries[i]
                    consecutive = (turn.agent_id == prev_agent_id)
                    prev_agent_id = turn.agent_id
                    card = TurnCard(
                        turn=copy.deepcopy(turn),
                        agent_name_map=self._agent_name_map,
                        consecutive_agent=consecutive,
                    )
                    area.mount(card)
            elif turn_count < len(existing):
                for card in existing[turn_count:]:
                    card.remove()

            # Step 2: 逐个卡片检查，仅替换条件变化的（使用最新 DOM 快照）
            existing = list(area.children)
            prev_agent_id = None
            for i, turn in enumerate(self._turn_summaries):
                consecutive = (turn.agent_id == prev_agent_id)
                prev_agent_id = turn.agent_id
                if i < len(existing):
                    card = existing[i]
                    if (isinstance(card, TurnCard) and card._turn.turn_id == turn.turn_id
                            and not _conditions_changed(card._turn, turn)):
                        # 条件未变，原地更新（不触碰 DOM）
                        card._consecutive_agent = consecutive
                        card.update_turn(turn, self._agent_name_map)
                    else:
                        # 条件变化，在 DOM 中替换此卡片
                        new_card = TurnCard(
                            turn=copy.deepcopy(turn),
                            agent_name_map=self._agent_name_map,
                            consecutive_agent=consecutive,
                        )
                        siblings = list(area.children)
                        card_idx = siblings.index(card) if card in siblings else -1
                        card.remove()
                        before = siblings[card_idx + 1] if card_idx >= 0 and card_idx + 1 < len(siblings) else None
                        area.mount(new_card, before=before)
                        if i < 3 or i == turn_count - 1:
                            log(f" _render_turn_cards: replaced card {i+1}/{turn_count}: turn_id={turn.turn_id}, agent={turn.agent_name}")

        # Auto-scroll to bottom (仅追加新 turn 时触发，初始加载不滚动)
        if auto_scroll and self.auto_scroll and not self._user_scrolled_up:
            # 立即尝试滚动（使用当前 max_scroll_y，可能尚不准确）
            scroll.scroll_end(animate=False)
            # 延迟再滚动一次，确保新 mount 卡片布局完成后能滚到真正底部
            # 注意：set_timer(0) 会导致 Textual 除零错误，最小需 > 0
            def _do_scroll():
                try:
                    s = self.query_one("#turn-scroll", ScrollableContainer)
                    s.scroll_end(animate=False)
                except Exception:
                    pass
            self.set_timer(0.01, _do_scroll)
            log(f" _render_turn_cards: auto-scroll scheduled")

    # ==================== Watch Reactives ====================

    def watch_loading(self, is_loading: bool):
        """Update loading indicator.

        Args:
            is_loading: Whether loading is in progress
        """
        try:
            indicator = self.query_one("#loading-indicator", Label)
        except Exception:
            return
        indicator.display = is_loading

    def watch_show_redo(self, visible: bool):
        """Update redo button visibility.

        Args:
            visible: Whether to show redo button
        """
        try:
            container = self.query_one("#redo-container", Vertical)
        except Exception:
            return
        container.display = visible

    # ==================== Scroll Management ====================

    def _check_scroll_position(self):
        """Periodic scroll position check for history loading and auto-scroll control.

        Polls scroll_y at regular interval since Textual does not emit Scroll events.
        """
        try:
            scroll = self.query_one("#turn-scroll", ScrollableContainer)
        except Exception:
            return

        current_scroll_y = scroll.scroll_y
        max_scroll_y = scroll.max_scroll_y

        # Check if user scrolled up
        at_bottom = current_scroll_y >= max_scroll_y - 2 if max_scroll_y > 0 else True
        if at_bottom:
            self._user_scrolled_up = False
        else:
            self._user_scrolled_up = True

        # Load more history when user scrolls to top (with cooldown)
        # 使用 _prev_scroll_y 区分"初始加载 scroll_y=0"和"用户主动滚动到顶部"：
        # - 初始加载：prev=0, current=0 → is_at_top=False（prev 没有 > 0）
        # - 用户滚回顶部：prev=12, current=0 → is_at_top=True（prev 曾 > 0）
        # - 内容没占满一页（max_scroll_y=0）：初始加载完成后即可触发，否则永远无法加载更多
        has_content = max_scroll_y > 0
        if not has_content:
            # 内容没占满时，只要初始加载完成且有更多数据，即可触发
            is_at_top = current_scroll_y <= 0 and self._initial_loaded
        else:
            # 内容占满时，需要用户主动滚动到顶部才触发
            is_at_top = current_scroll_y <= 0 and self._prev_scroll_y > 2
        self._prev_scroll_y = current_scroll_y
        should_trigger = (is_at_top and self.has_more and self._on_load_more_turns
                and not self._scroll_cooldown_active and not self.loading
                and self._initial_loaded)
        if should_trigger:
            log(f" scroll_check: TRIGGER loading! scroll_y={current_scroll_y}, max_y={max_scroll_y}, has_more={self.has_more}, loading={self.loading}, initial_loaded={self._initial_loaded}, cooldown={self._scroll_cooldown_active}")
            self._scroll_cooldown_active = True
            self._on_load_more_turns()
            self.set_timer(self._SCROLL_COOLDOWN, self._reset_scroll_cooldown)

    def _reset_scroll_cooldown(self):
        """Reset the scroll cooldown flag."""
        self._scroll_cooldown_active = False

    def scroll_to_bottom(self):
        """Scroll to the bottom of the message list."""
        try:
            scroll = self.query_one("#turn-scroll", ScrollableContainer)
        except Exception:
            return
        scroll.scroll_end(animate=False)
        self._user_scrolled_up = False

    # ==================== Button Handling ====================

    def on_button_pressed(self, event: Button.Pressed) -> None:
        """Handle redo and undo button presses.

        Args:
            event: Button pressed event
        """
        btn_id = event.button.id or ""

        if btn_id == "btn-redo" and self._on_redo:
            self._on_redo()
        elif btn_id.startswith("undo-"):
            # Extract turn_id from "undo-{turn_id}"
            undo_turn_id = btn_id.replace("undo-", "", 1)
            self.run_worker(self._confirm_and_undo(undo_turn_id))

    async def _confirm_and_undo(self, turn_id: str):
        """Show undo confirmation dialog and execute undo.

        Args:
            turn_id: Turn ID to undo
        """
        # Find the sequence number for the dialog text
        seq_num = 0
        for turn in self._turn_summaries:
            if turn.turn_id == turn_id:
                seq_num = turn.sequence_number
                break

        dialog = UndoConfirmDialog(turn_id=turn_id, sequence_number=seq_num)
        result = await self.app.push_screen_wait(dialog)
        if result and result.get("action") == "undo" and self._on_undo:
            self._on_undo(turn_id)
