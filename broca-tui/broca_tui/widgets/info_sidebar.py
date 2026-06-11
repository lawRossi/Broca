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

import time
from typing import Any, Dict, Optional

from textual.app import ComposeResult
from textual.containers import Horizontal, Vertical, ScrollableContainer
from textual.reactive import reactive
from textual.widgets import Button, Label, Static
from textual.widget import Widget

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
        """Create the sidebar layout."""
        with Vertical():
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
                # Single toggle button (broca-web pattern)
                yield Button("▶ 启动进程", id="btn-toggle-runner", classes="runner-btn")

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
        """Update runner status display and toggle button.

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

        # Update toggle button (single button, broca-web pattern)
        toggle_btn = self.query_one("#btn-toggle-runner", Button)

        if status == "alive":
            toggle_btn.label = "⏹ 停止进程"
            toggle_btn.disabled = self.runner_action_loading
        elif status == "starting":
            toggle_btn.label = "◐ 启动中"
            toggle_btn.disabled = True
        elif status == "error":
            toggle_btn.label = "🔄 重启进程"
            toggle_btn.disabled = self.runner_action_loading
        else:  # dead, unknown
            toggle_btn.label = "▶ 启动进程"
            toggle_btn.disabled = self.runner_action_loading

    def watch_runner_action_loading(self, loading: bool):
        """Sync loading state with button disabled state."""
        try:
            btn = self.query_one("#btn-toggle-runner", Button)
            btn.disabled = loading
        except Exception:
            pass

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
        """Handle toggle button press — starts or stops the runner.

        broca-web pattern: single button that switches between start/stop.
        """
        if event.button.id != "btn-toggle-runner":
            return

        status = self.runner_status
        session_id = self._session_id
        if not session_id:
            return

        if status == "alive":
            self.runner_action_loading = True
            self.run_worker(self._do_stop_runner(session_id))
        else:
            self.runner_action_loading = True
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
                        uptime=str(info.get("uptime_seconds", "")),
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
        except Exception:
            pass  # Keep current status on failure
        finally:
            self.runner_action_loading = False

    async def _sleep(self, seconds: float):
        """Async sleep helper."""
        import asyncio
        await asyncio.sleep(seconds)

    def on_unmount(self) -> None:
        """Clean up on unmount."""
        self._stop_polling()
