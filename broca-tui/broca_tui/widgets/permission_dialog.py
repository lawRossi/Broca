"""
PermissionDialog (ModalScreen)

Handles permission requests from agents:
- Tool permissions: 4-button grid (Single Allow/Deny, Session Allow/Deny)
- General permissions: 2-button grid (Allow/Deny)
"""

from __future__ import annotations

from typing import Any, Dict, Optional

from textual.app import ComposeResult
from textual.containers import Horizontal, Vertical, Grid
from textual.screen import ModalScreen
from textual.widgets import Button, Label, Static


class PermissionDialog(ModalScreen):
    """Modal dialog for permission requests."""

    def __init__(
        self,
        message: str = "",
        request_id: Optional[str] = None,
        sender_id: Optional[str] = None,
        request_type: str = "general",
        **kwargs,
    ):
        """Initialize permission dialog.

        Args:
            message: Permission request message
            request_id: Request identifier
            sender_id: Sender agent ID
            request_type: 'tool' or 'general'
        """
        super().__init__(**kwargs)
        self._message = message
        self._request_id = request_id
        self._sender_id = sender_id
        self._request_type = request_type

    def compose(self) -> ComposeResult:
        """Create the dialog layout."""
        with Vertical(classes="dialog permission-dialog"):
            yield Label("🔒 权限请求", classes="dialog-title")

            # Request message content
            with Vertical(classes="dialog-content"):
                yield Label(self._message, classes="permission-message")

            # Action buttons based on type
            if self._request_type == "tool":
                yield Grid(
                    Button("✅ 单次允许", id="btn-allow-once", classes="permission-btn allow"),
                    Button("❌ 单次拒绝", id="btn-deny-once", classes="permission-btn deny"),
                    Button("🔓 本Session允许", id="btn-allow-session", classes="permission-btn allow-session"),
                    Button("🔒 本Session拒绝", id="btn-deny-session", classes="permission-btn deny-session"),
                    classes="permission-grid",
                )
            else:
                with Horizontal(classes="dialog-actions"):
                    yield Button("✅ 允许", id="btn-allow", variant="primary")
                    yield Button("❌ 拒绝", id="btn-deny", variant="error")

    def on_button_pressed(self, event: Button.Pressed) -> None:
        """Handle permission response.

        Args:
            event: Button pressed event
        """
        btn_id = event.button.id

        if btn_id == "btn-allow-once":
            self.dismiss({
                "action": "permission_response",
                "granted": True,
                "request_id": self._request_id,
                "session_action": None,
            })
        elif btn_id == "btn-deny-once":
            self.dismiss({
                "action": "permission_response",
                "granted": False,
                "request_id": self._request_id,
                "session_action": None,
            })
        elif btn_id == "btn-allow-session":
            self.dismiss({
                "action": "permission_response",
                "granted": True,
                "request_id": self._request_id,
                "session_action": "allow",
            })
        elif btn_id == "btn-deny-session":
            self.dismiss({
                "action": "permission_response",
                "granted": False,
                "request_id": self._request_id,
                "session_action": "deny",
            })
        elif btn_id == "btn-allow":
            self.dismiss({
                "action": "permission_response",
                "granted": True,
                "request_id": self._request_id,
            })
        elif btn_id == "btn-deny":
            self.dismiss({
                "action": "permission_response",
                "granted": False,
                "request_id": self._request_id,
            })
