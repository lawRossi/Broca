"""
InfoSidebar Widget

Right info panel with:
- Session Info (ID, workspace)
- Runner Status (status, PID, uptime, start/stop buttons, auto-polling)
- Message Statistics (counts by type with colored indicators)
"""

from __future__ import annotations

import time
from typing import Any, Dict, Optional

from textual.app import ComposeResult
from textual.containers import Horizontal, Vertical, ScrollableContainer
from textual.message import Message
from textual.reactive import reactive
from textual.widgets import Button, Label, Static
from textual.widget import Widget

from broca_tui.api.session import SessionAPI
from broca_tui.stores.chat_store import ChatStore


class InfoSidebar(Widget):
    """Right info panel showing session details and runner status."""

    runner_status = reactive("unknown")
    runner_uptime = reactive("")

    class StartRunner(Message, bubble=True):
        """Message posted when user wants to start the runner."""

        def __init__(self, session_id: str = "") -> None:
            super().__init__()
            self.session_id = session_id

    class StopRunner(Message, bubble=True):
        """Message posted when user wants to stop the runner."""

        def __init__(self, session_id: str = "") -> None:
            super().__init__()
            self.session_id = session_id

    def __init__(
        self,
        session_id: str = "",
        chat_store: Optional[ChatStore] = None,
        **kwargs,
    ):
        """Initialize info sidebar.

        Args:
            session_id: Current session ID
            chat_store: ChatStore instance for runner polling
        """
        super().__init__(**kwargs)
        self._session_id = session_id
        self._chat_store = chat_store
        self._api = SessionAPI()
        self._polling = False
        self._poll_timer = None

    def compose(self) -> ComposeResult:
        """Create the sidebar layout."""
        with Vertical(classes="sidebar sidebar-right"):
            # Session Info Section
            with Vertical(classes="info-section"):
                yield Label("Session Info", classes="section-title")
                yield Label("ID: -", classes="info-row", id="info-session-id")
                yield Label("Workspace: -", classes="info-row", id="info-workspace")

            # Runner Status Section
            with Vertical(classes="info-section"):
                yield Label("Runner Status", classes="section-title")
                yield Label("Status: ● unknown", classes="info-row", id="runner-status")
                yield Label("PID: -", classes="info-row", id="runner-pid")
                yield Label("Uptime: -", classes="info-row", id="runner-uptime")
                with Horizontal(classes="runner-actions"):
                    yield Button("▶ 启动", id="btn-start-runner", classes="runner-btn")
                    yield Button("⏹ 停止", id="btn-stop-runner", classes="runner-btn")

            # Message Statistics Section
            with Vertical(classes="info-section"):
                yield Label("Message Statistics", classes="section-title")
                with Horizontal(classes="stat-row"):
                    yield Label("●", classes="stat-dot user-dot")
                    yield Label("User: 0", classes="stat-text", id="stat-user")
                with Horizontal(classes="stat-row"):
                    yield Label("●", classes="stat-dot agent-dot")
                    yield Label("Agent: 0", classes="stat-text", id="stat-agent")
                with Horizontal(classes="stat-row"):
                    yield Label("●", classes="stat-dot tool-dot")
                    yield Label("Tools: 0", classes="stat-text", id="stat-tools")
                with Horizontal(classes="stat-row"):
                    yield Label("●", classes="stat-dot system-dot")
                    yield Label("System: 0", classes="stat-text", id="stat-system")
                with Horizontal(classes="stat-row"):
                    yield Label("●", classes="stat-dot error-dot")
                    yield Label("Errors: 0", classes="stat-text", id="stat-errors")

    def on_mount(self) -> None:
        """Start polling after mount."""
        if self._session_id:
            self._start_polling()

    def set_session(self, session_id: str, workspace: str = ""):
        """Set session information.

        Args:
            session_id: Session ID
            workspace: Workspace path
        """
        self._session_id = session_id
        self.query_one("#info-session-id", Label).update(f"ID: {session_id[:16]}...")
        self.query_one("#info-workspace", Label).update(f"Workspace: {workspace or '-'}")

    def watch_runner_status(self, status: str):
        """Update runner status display.

        Args:
            status: 'alive', 'starting', 'error', 'dead', or 'unknown'
        """
        status_label = self.query_one("#runner-status", Label)
        color_map = {
            "alive": "● connected",
            "starting": "◐ starting",
            "error": "● error",
            "dead": "○ stopped",
            "unknown": "● unknown",
        }
        display = color_map.get(status, f"● {status}")
        status_label.update(f"Status: {display}")

        # Update button states
        start_btn = self.query_one("#btn-start-runner", Button)
        stop_btn = self.query_one("#btn-stop-runner", Button)

        if status == "alive":
            start_btn.disabled = True
            stop_btn.disabled = False
        elif status in ("dead", "error", "unknown"):
            start_btn.disabled = False
            stop_btn.disabled = True
        else:
            start_btn.disabled = True
            stop_btn.disabled = True

    def update_runner_stats(self, pid: Optional[int], uptime: Optional[str]):
        """Update runner PID and uptime.

        Args:
            pid: Process ID
            uptime: Uptime string
        """
        self.query_one("#runner-pid", Label).update(f"PID: {pid if pid else '-'}")
        uptime_str = uptime or "-"
        self.query_one("#runner-uptime", Label).update(f"Uptime: {uptime_str}")

    def update_message_stats(self, messages: list):
        """Update message statistics from messages list.

        Args:
            messages: List of message dicts
        """
        counts = {"user": 0, "agent": 0, "tool": 0, "system": 0, "error": 0}

        for msg in messages:
            msg_type = msg.get("message_type", "")
            if msg_type in ("user_message",):
                counts["user"] += 1
            elif msg_type in ("agent_response",):
                counts["agent"] += 1
            elif msg_type in ("tool_call",):
                counts["tool"] += 1
            elif msg_type in ("agent_system_message", "system_message"):
                counts["system"] += 1
            elif msg_type in ("error", "agent_error"):
                counts["error"] += 1

        self.query_one("#stat-user", Label).update(f"User: {counts['user']}")
        self.query_one("#stat-agent", Label).update(f"Agent: {counts['agent']}")
        self.query_one("#stat-tools", Label).update(f"Tools: {counts['tool']}")
        self.query_one("#stat-system", Label).update(f"System: {counts['system']}")
        self.query_one("#stat-errors", Label).update(f"Errors: {counts['error']}")

    def _start_polling(self):
        """Start periodic runner status polling."""
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

    async def _poll_runner_status(self):
        """Poll runner status from API."""
        if not self._session_id:
            return
        try:
            info = await self._api.get_runner_status(self._session_id)
            status = info.get("status", "unknown")
            self.runner_status = status
            self.runner_uptime = str(info.get("uptime_seconds", ""))
            self.update_runner_stats(
                pid=info.get("pid"),
                uptime=self.runner_uptime,
            )
        except Exception:
            self.runner_status = "unknown"

    def on_button_pressed(self, event: Button.Pressed) -> None:
        """Handle button presses.

        Args:
            event: Button pressed event
        """
        button_id = event.button.id
        if button_id == "btn-start-runner":
            self.post_message(self.StartRunner(session_id=self._session_id))
        elif button_id == "btn-stop-runner":
            self.post_message(self.StopRunner(session_id=self._session_id))

    def on_unmount(self) -> None:
        """Clean up on unmount."""
        self._stop_polling()
