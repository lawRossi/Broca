"""
ChatHeader Widget

Top navigation bar showing:
- Left: Broca brand + connection status indicator (dot + text)
- Right: Navigation buttons (← Sessions, Crew Management)
"""

from __future__ import annotations

from typing import Optional

from textual.app import ComposeResult
from textual.containers import Horizontal
from textual.message import Message
from textual.reactive import reactive
from textual.widgets import Button, Label
from textual.widget import Widget


class ChatHeader(Widget):
    """Top navigation bar for the chat screen."""

    # Reactive attributes for connection status
    connection_status = reactive("disconnected")
    is_agent_orchestration = reactive(False)
    session_category = reactive("normal")

    BINDINGS = [
        ("ctrl+s", "go_to_sessions", "会话列表"),
    ]

    class NavigateToSessions(Message, bubble=True):
        """Message posted when user wants to go to sessions list."""

    class RefreshRequested(Message, bubble=True):
        """Message posted when user clicks the refresh button."""

    def __init__(
        self,
        session_id: str = "",
        **kwargs,
    ):
        """Initialize ChatHeader.

        Args:
            session_id: Current session ID (for navigation)
        """
        super().__init__(**kwargs)
        self._session_id = session_id

    def compose(self) -> ComposeResult:
        """Create the header layout."""
        with Horizontal(classes="chat-header"):
            # Left section: Brand + Status
            with Horizontal(classes="header-left"):
                yield Label("Broca", classes="header-brand")
                yield Label("●", classes="status-dot", id="status-dot")
                yield Label("connecting...", classes="status-text", id="status-text")

            # Right section: Navigation buttons
            with Horizontal(classes="header-right"):
                yield Button("🔄 刷新", id="btn-refresh", classes="nav-button")
                yield Button("← 会话列表", id="btn-sessions", classes="nav-button")

    def on_mount(self) -> None:
        """Initial setup after mount."""
        self.watch_connection_status(self.connection_status)

    def watch_connection_status(self, status: str) -> None:
        """React to connection status changes.

        Args:
            status: 'connected', 'connecting', or 'disconnected'
        """
        status_dot = self.query_one("#status-dot", Label)
        status_text = self.query_one("#status-text", Label)

        if status == "connected":
            status_dot.classes = "status-dot connected"
            status_text.update("connected")
            status_text.classes = "status-text connected"
        elif status == "connecting":
            status_dot.classes = "status-dot connecting"
            status_text.update("connecting...")
            status_text.classes = "status-text connecting"
        else:  # disconnected
            status_dot.classes = "status-dot disconnected"
            status_text.update("disconnected")
            status_text.classes = "status-text disconnected"

    def set_session_id(self, session_id: str) -> None:
        """Set the current session ID.

        Args:
            session_id: Session ID
        """
        self._session_id = session_id

    def set_execution_filter(self, execution_id: Optional[str] = None) -> None:
        """Set execution filter (no-op, no longer displayed in header).

        Args:
            execution_id: Optional execution ID being filtered
        """
        pass

    def action_go_to_sessions(self) -> None:
        """Navigate back to session list."""
        self.post_message(self.NavigateToSessions())

    def action_refresh(self) -> None:
        """Trigger page refresh."""
        self.post_message(self.RefreshRequested())

    def on_button_pressed(self, event: Button.Pressed) -> None:
        """Handle button presses.

        Args:
            event: Button pressed event
        """
        if event.button.id == "btn-sessions":
            self.action_go_to_sessions()
        elif event.button.id == "btn-refresh":
            self.action_refresh()
