"""
OrchestrationBanner Widget

Read-only banner displayed in ChatScreen for agent-orchestration sessions.
Aligned with VS Code's orchestration-readonly-bar in App.vue.

Shows:
- ⚡ icon
- "Agent 编排会话" title
- "此会话为只读模式，聊天仅用于查看执行日志" description
- "查看编排" button → NavigateToCrew message
"""

from __future__ import annotations

from typing import Optional

from textual.app import ComposeResult
from textual.containers import Horizontal, Vertical
from textual.message import Message
from textual.widgets import Button, Label, Static
from textual.widget import Widget


class OrchestrationBanner(Widget):
    """Read-only banner for agent-orchestration sessions."""

    DEFAULT_CSS = """
    OrchestrationBanner {
        height: auto;
        border-top: solid #bae6fd;
        background: #f0f9ff;
        padding: 0 1;
    }

    .orchestration-banner-content {
        height: auto;
        align: center middle;
    }

    .orchestration-banner-icon {
        color: #0284c7;
        text-style: bold;
        width: 3;
    }

    .orchestration-banner-text {
        width: 1fr;
        height: auto;
    }

    .orchestration-banner-title {
        text-style: bold;
        color: #075985;
    }

    .orchestration-banner-desc {
        color: #0284c7;
    }

    .orchestration-banner-btn {
        background: #0ea5e9;
        color: white;
        border: none;
        min-width: 16;
        margin-left: 1;
    }

    .orchestration-banner-btn:hover {
        background: #0284c7;
        text-style: bold;
    }
    """

    class NavigateToCrew(Message, bubble=True):
        """Message posted when user clicks '查看编排' button."""

        def __init__(self, session_id: str = "") -> None:
            super().__init__()
            self.session_id = session_id

    def __init__(
        self,
        session_id: str = "",
        **kwargs,
    ):
        """Initialize OrchestrationBanner.

        Args:
            session_id: Current session ID (for navigation)
        """
        super().__init__(**kwargs)
        self._session_id = session_id

    def compose(self) -> ComposeResult:
        """Create the banner layout."""
        with Horizontal(classes="orchestration-banner-content"):
            yield Label("⚡", classes="orchestration-banner-icon")
            with Vertical(classes="orchestration-banner-text"):
                yield Label("Agent 编排会话", classes="orchestration-banner-title")
                yield Label(
                    "此会话为只读模式，聊天仅用于查看执行日志",
                    classes="orchestration-banner-desc",
                )
            yield Button("查看编排", id="btn-view-crew", classes="orchestration-banner-btn")

    def on_button_pressed(self, event: Button.Pressed) -> None:
        """Handle button press.

        Args:
            event: Button pressed event
        """
        if event.button.id == "btn-view-crew":
            self.post_message(self.NavigateToCrew(session_id=self._session_id))
