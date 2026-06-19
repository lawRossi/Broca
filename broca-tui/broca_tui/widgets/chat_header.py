"""
ChatHeader Widget

Top navigation bar showing:
- Left: Broca brand + connection status indicator (dot + text)
- Right: Navigation buttons (← Sessions, Crew Management)
"""

from __future__ import annotations

from typing import Optional

from textual.app import ComposeResult
from textual.containers import Horizontal, Vertical
from textual.message import Message
from textual.reactive import reactive
from textual.widgets import Button, Label, Static
from textual.widget import Widget


class ChatHeader(Widget):
    """Top navigation bar for the chat screen."""

    # Reactive attributes for connection status
    connection_status = reactive("disconnected")
    is_agent_orchestration = reactive(False)
    session_category = reactive("normal")

    BINDINGS = [
        ("ctrl+s", "go_to_sessions", "会话列表"),
        ("ctrl+e", "go_to_crew", "编排管理"),
    ]

    class NavigateToSessions(Message, bubble=True):
        """Message posted when user wants to go to sessions list."""

    class NavigateToCrew(Message, bubble=True):
        """Message posted when user wants to go to crew management."""

        def __init__(self, session_id: str = "") -> None:
            super().__init__()
            self.session_id = session_id

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
                yield Button("← 会话列表", id="btn-sessions", classes="nav-button")
                yield Button("编排管理", id="btn-crew", classes="nav-button crew-button")

    def on_mount(self) -> None:
        """Initial setup after mount."""
        self.watch_connection_status(self.connection_status)
        self._update_crew_button_visibility()
        # Also set initial display based on is_agent_orchestration
        self.watch_is_agent_orchestration(self.is_agent_orchestration)

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

    def watch_is_agent_orchestration(self, is_orch: bool) -> None:
        """React to session category changes."""
        self._update_crew_button_visibility()

    def _update_crew_button_visibility(self) -> None:
        """Show/hide the crew management button based on session category."""
        try:
            crew_btn = self.query_one("#btn-crew", Button)
            crew_btn.display = self.is_agent_orchestration or self.session_category == "agent-orchestration"
        except Exception:
            pass  # Not yet mounted

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

    def action_go_to_crew(self) -> None:
        """Navigate to crew execution management."""
        self.post_message(self.NavigateToCrew(session_id=self._session_id))

    def on_button_pressed(self, event: Button.Pressed) -> None:
        """Handle button presses.

        Args:
            event: Button pressed event
        """
        button_id = event.button.id
        if button_id == "btn-sessions":
            self.action_go_to_sessions()
        elif button_id == "btn-crew":
            self.action_go_to_crew()
