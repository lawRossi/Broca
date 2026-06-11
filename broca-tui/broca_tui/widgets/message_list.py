"""
MessageList Widget

Message list with:
- Virtual scrolling (via ScrollableContainer)
- Auto-scroll to bottom on new messages
- Infinite scroll up for history loading
- Streaming message append
- Empty state and loading indicator
- Redo button display after undo
"""

from __future__ import annotations

from typing import Any, Callable, Dict, List, Optional

from textual.app import ComposeResult
from textual.containers import Horizontal, ScrollableContainer, Vertical
from textual.reactive import reactive
from textual.screen import ModalScreen
from textual.widgets import Button, Label, Static
from textual.widget import Widget

from broca_tui.widgets.message_item import MessageItem


class UndoConfirmDialog(ModalScreen):
    """Confirmation dialog for undo action (aligning with Web UX)."""

    def __init__(self, message_id: str, message_type: str = "", **kwargs):
        """Initialize undo confirmation dialog.

        Args:
            message_id: ID of the message to undo
            message_type: Type of message being undone (for contextual text)
        """
        super().__init__(**kwargs)
        self._message_id = message_id
        self._message_type = message_type

    def compose(self) -> ComposeResult:
        """Create the dialog layout (matching Web's ElMessageBox)."""
        # Web: different text for user_message vs other types
        if self._message_type == "user_message":
            message_text = "确定要撤销此操作吗？此操作将同时撤销后续的相关操作。"
        else:
            message_text = "确定要撤销此操作吗？"

        with Vertical(classes="dialog"):
            yield Label("确认撤销", classes="dialog-title")
            yield Label(message_text, classes="dialog-label")
            with Horizontal(classes="dialog-actions"):
                yield Button("确定", id="btn-confirm-undo", variant="primary")
                yield Button("取消", id="btn-cancel-undo")

    def on_button_pressed(self, event: Button.Pressed) -> None:
        """Handle button presses."""
        if event.button.id == "btn-confirm-undo":
            self.dismiss({"action": "undo", "message_id": self._message_id})
        elif event.button.id == "btn-cancel-undo":
            self.dismiss({"action": "cancel"})


class MessageList(Vertical):
    """Scrollable message list with auto-scroll and history loading."""

    DEFAULT_CSS = """
    MessageList {
        width: 1fr;
        height: 1fr;
        layout: vertical;
        overflow: hidden hidden;
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
        self._messages: List[Dict[str, Any]] = []
        self._on_load_more: Optional[Callable] = None
        self._on_undo: Optional[Callable] = None
        self._on_redo: Optional[Callable] = None
        self._session_id: str = ""
        self._user_scrolled_up = False
        self.auto_scroll = True
        self._scroll_cooldown_active = False
        self._poll_timer = None
        # Current agent info (for cross-agent sender name display)
        self._current_agent_name: str = ""
        self._current_agent_id: str = ""
        self._agent_name_map: Dict[str, str] = {}  # agent_id → display_name

    def compose(self) -> ComposeResult:
        """Create the message list layout."""
        with Vertical(classes="message-list-container"):
            # Loading indicator (shown when loading history)
            yield Label("Loading history...", classes="loading-indicator", id="loading-indicator")

            # Scrollable message area
            with ScrollableContainer(id="message-scroll", classes="message-scroll"):
                yield Static("", id="message-area")

            # Redo button (shown after undo)
            with Vertical(classes="redo-container", id="redo-container"):
                yield Button("↩ Redo", id="btn-redo", classes="redo-button")

    def on_mount(self) -> None:
        """Set up after mount."""
        # Hide loading and redo initially
        self.query_one("#loading-indicator", Label).display = False
        self.query_one("#redo-container", Vertical).display = False
        # Start scroll polling (Textual 7.5.0 doesn't have a Scroll event)
        self._poll_timer = self.set_interval(self._SCROLL_POLL_INTERVAL, self._check_scroll_position)

    def set_session(self, session_id: str):
        """Set the current session ID.

        Args:
            session_id: Session ID
        """
        self._session_id = session_id

    def set_on_load_more(self, callback: Callable):
        """Set callback for loading more history.

        Args:
            callback: Called when user scrolls to top
        """
        self._on_load_more = callback

    def set_on_undo(self, callback: Callable):
        """Set callback for undo.

        Args:
            callback: Called with message_id
        """
        self._on_undo = callback

    def set_on_redo(self, callback: Callable):
        """Set callback for redo.

        Args:
            callback: Called with ()
        """
        self._on_redo = callback

    def set_current_agent(self, agent_id: str = "", agent_name: str = "",
                           agent_name_map: Optional[Dict[str, str]] = None,
                           force_rerender: bool = False):
        """Set the current agent info for cross-agent sender name display.

        Args:
            agent_id: Current agent's ID (for cross-agent comparison)
            agent_name: Current agent's display name
            agent_name_map: Dict mapping agent_id → display_name (for showing @Name not @ID)
            force_rerender: If True, re-render messages with updated agent info
        """
        self._current_agent_id = agent_id
        self._current_agent_name = agent_name
        if agent_name_map is not None:
            self._agent_name_map = agent_name_map
        if force_rerender and self._messages:
            self._render_messages()

    def _update_mounted_agent_info(self):
        """Update agent_name_map on already-mounted MessageItems directly.

        Called when agent info arrives after messages are already rendered,
        to fix sender names that still show IDs instead of display names.
        """
        if not self._agent_name_map:
            return
        for child in self.query(MessageItem):
            child._agent_name_map = self._agent_name_map
        # No need to re-mount — sender names use _agent_name_map at render time,
        # but the label text was already set during compose. Force refresh.
        self._render_messages()

    def add_message(self, message: Dict[str, Any]):
        """Add a message to the list.

        Args:
            message: Message dict to add
        """
        self._messages.append(message)
        self._render_messages()

    def set_messages(self, messages: List[Dict[str, Any]]):
        """Replace all messages (e.g., after history load).

        Args:
            messages: Full list of messages
        """
        self._messages = messages
        self._render_messages()

    def update_streaming_message(self, msg: Dict[str, Any]):
        """Update a streaming message's content in-place (no full re-render).

        Called during streaming to update content without flicker.
        Falls back to incremental render if the message isn't found.

        Args:
            msg: Updated message dict
        """
        msg_id = msg.get("message_id", "")
        if not msg_id:
            return

        # Try in-place update of existing MessageItem
        for child in self.query(MessageItem):
            if getattr(child, "_msg_id", None) == msg_id:
                # Update the message data and trigger a refresh
                child._message = msg
                # Remove and re-mount just this one message
                try:
                    scroll = self.query_one("#message-scroll", ScrollableContainer)
                    new_item = MessageItem(
                        msg,
                        agent_name=self._current_agent_name,
                        agent_id=self._current_agent_id,
                        agent_name_map=self._agent_name_map,
                    )
                    child.remove()
                    # Mount at same position
                    scroll.mount(new_item, before=scroll.children[-1] if scroll.children else None)
                except Exception:
                    pass
                return

        # Message not found — do incremental render
        self._render_messages(incremental=True)

    def append_messages_front(self, messages: List[Dict[str, Any]]):
        """Prepend messages (for history loading).

        Args:
            messages: Messages to prepend
        """
        self._messages = messages + self._messages
        self._render_messages()

    def _render_messages(self, incremental: bool = False):
        """Render all messages, optionally with incremental updates.

        When incremental=True (streaming), only add NEW messages and update
        existing ones in-place, avoiding full re-render flicker.

        Args:
            incremental: If True, only add/update messages without removing all
        """
        try:
            area = self.query_one("#message-area", Static)
            scroll = self.query_one("#message-scroll", ScrollableContainer)
        except Exception:
            return  # Widgets not ready yet

        if not self._messages:
            area.update("等待消息...")
            area.classes = "empty-message"
            for child in list(scroll.children):
                if isinstance(child, MessageItem):
                    child.remove()
            return

        # Clear empty-state text when messages exist
        area.update("")

        if incremental:
            # Incremental update: add new messages, skip existing
            existing_ids = {
                getattr(child, "_msg_id", "")
                for child in scroll.children
                if isinstance(child, MessageItem)
            }

            for msg in self._messages:
                msg_id = msg.get("message_id", "")
                if msg_id not in existing_ids:
                    item = MessageItem(
                        msg,
                        agent_name=self._current_agent_name,
                        agent_id=self._current_agent_id,
                        agent_name_map=self._agent_name_map,
                    )
                    scroll.mount(item)
                    existing_ids.add(msg_id)
                # Existing messages keep their current render (streaming
                # content updates are handled via _update_message_content)
        else:
            # Full re-render: remove all and recreate
            for child in list(scroll.children):
                if isinstance(child, MessageItem):
                    child.remove()

            for msg in self._messages:
                item = MessageItem(
                    msg,
                    agent_name=self._current_agent_name,
                    agent_id=self._current_agent_id,
                    agent_name_map=self._agent_name_map,
                )
                scroll.mount(item)

        # Auto-scroll to bottom unless user scrolled up
        if self.auto_scroll and not self._user_scrolled_up:
            scroll.scroll_end(animate=False)
            self._user_scrolled_up = False

    def watch_loading(self, is_loading: bool):
        """Update loading indicator.

        Args:
            is_loading: Whether loading is in progress
        """
        try:
            indicator = self.query_one("#loading-indicator", Label)
        except Exception:
            return  # Widget not ready yet (may fire during compose)
        indicator.display = is_loading

    def watch_has_more(self, more: bool):
        """Update has-more state.

        Args:
            more: Whether more history is available
        """
        if not more:
            # Can show "end of history" indicator
            pass

    def watch_show_redo(self, visible: bool):
        """Update redo button visibility.

        Args:
            visible: Whether to show redo button
        """
        try:
            container = self.query_one("#redo-container", Vertical)
        except Exception:
            return  # Widget not ready yet (may fire during compose)
        container.display = visible

    def _check_scroll_position(self):
        """Periodic scroll position check for history loading and auto-scroll control.

        Textual 7.5.0 does not emit a Scroll event on ScrollableContainer,
        so we poll scroll_y at a regular interval instead.
        """
        try:
            scroll = self.query_one("#message-scroll", ScrollableContainer)
        except Exception:
            return  # Widget not ready yet
        current_scroll_y = scroll.scroll_y
        max_scroll_y = scroll.max_scroll_y

        # Check if user scrolled up: not at bottom → user scrolled up
        # Use a 2-line threshold to account for minor height changes
        at_bottom = current_scroll_y >= max_scroll_y - 2 if max_scroll_y > 0 else True
        if at_bottom:
            self._user_scrolled_up = False
        else:
            self._user_scrolled_up = True

        # Load more history when scrolling to top (with cooldown)
        is_at_top = current_scroll_y <= 0
        if (is_at_top and self.has_more and self._on_load_more
                and not self._scroll_cooldown_active and not self.loading):
            self._scroll_cooldown_active = True
            self.loading = True
            self._on_load_more()
            self.set_timer(self._SCROLL_COOLDOWN, self._reset_scroll_cooldown)

        self._last_scroll_top = current_scroll_y

    def _reset_scroll_cooldown(self):
        """Reset the scroll cooldown flag."""
        self._scroll_cooldown_active = False

    def scroll_to_bottom(self):
        """Scroll to the bottom of the message list."""
        try:
            scroll = self.query_one("#message-scroll", ScrollableContainer)
        except Exception:
            return
        scroll.scroll_end(animate=False)
        self._user_scrolled_up = False

    def on_button_pressed(self, event: Button.Pressed) -> None:
        """Handle redo and undo button presses.

        Args:
            event: Button pressed event
        """
        btn_id = event.button.id or ""

        if btn_id == "btn-redo" and self._on_redo:
            self._on_redo()
        elif btn_id.startswith("undo-"):
            # Extract message_id from "undo-{msg_id}"
            undo_msg_id = btn_id.replace("undo-", "", 1)
            self.run_worker(self._confirm_and_undo(undo_msg_id))

    async def _confirm_and_undo(self, msg_id: str):
        """Show undo confirmation dialog and execute undo.

        Args:
            msg_id: Message ID to undo
        """
        # Find the message to determine its type (for contextual dialog text)
        msg_type = ""
        for child in self.query(MessageItem):
            if getattr(child, "_msg_id", None) == msg_id:
                msg_type = child._message.get("message_type", "")
                break

        dialog = UndoConfirmDialog(message_id=msg_id, message_type=msg_type)
        result = await self.app.push_screen_wait(dialog)
        if result and result.get("action") == "undo" and self._on_undo:
            self._on_undo(msg_id)
