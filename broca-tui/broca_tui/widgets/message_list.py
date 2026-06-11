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
from textual.containers import ScrollableContainer, Vertical
from textual.reactive import reactive
from textual.widgets import Button, Label, Static
from textual.widget import Widget

from broca_tui.widgets.message_item import MessageItem


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
        self._user_scrolled_up = False
        self._session_id = ""
        self._last_scroll_top = 0.0
        self._scroll_cooldown_active = False
        self._poll_timer = None

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

    def append_messages_front(self, messages: List[Dict[str, Any]]):
        """Prepend messages (for history loading).

        Args:
            messages: Messages to prepend
        """
        self._messages = messages + self._messages
        self._render_messages()

    def _render_messages(self):
        """Render all messages."""
        try:
            area = self.query_one("#message-area", Static)
            scroll = self.query_one("#message-scroll", ScrollableContainer)
        except Exception:
            return  # Widgets not ready yet

        if not self._messages:
            area.update("等待消息...")
            # Remove previously mounted MessageItem widgets (keep structural children)
            for child in list(scroll.children):
                if isinstance(child, MessageItem):
                    child.remove()
            return

        # Remove previously mounted MessageItem widgets (keep structural children
        # like #message-area which are part of the compose template)
        for child in list(scroll.children):
            if isinstance(child, MessageItem):
                child.remove()

        # Mount messages
        for msg in self._messages:
            item = MessageItem(msg)
            scroll.mount(item)

        # Auto-scroll to bottom unless user scrolled up
        if self.auto_scroll and not self._user_scrolled_up:
            scroll.scroll_end(animate=False)

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

        # Check if user scrolled up
        if current_scroll_y > 0:
            self._user_scrolled_up = True
        else:
            self._user_scrolled_up = False

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
        """Handle redo button press.

        Args:
            event: Button pressed event
        """
        if event.button.id == "btn-redo" and self._on_redo:
            self._on_redo()
