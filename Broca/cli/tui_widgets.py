"""
TUI Widgets

Contains UI components for the TUI application:
- StatusWidget: Connection status display widget
- MessageListWidget: Chat message display widget
- PermissionDialog: Permission request dialog
"""

from typing import Callable, Optional

from textual import events
from textual.containers import Container, Horizontal
from textual.reactive import reactive
from textual.widgets import Button, Input, RichLog, Static

from .tui_models import ChatMessage, StatusIndicator


class StatusWidget(Static):
    """Widget displaying connection status"""

    status_text = reactive("Disconnected")
    status_color = reactive("red")
    agent_status_text = reactive("Agent Disconnected")
    agent_status_color = reactive("red")

    def __init__(self, status_indicator: StatusIndicator, **kwargs):
        super().__init__(**kwargs)
        self.status_indicator = status_indicator

    def watch_status_text(self, old_value: str, new_value: str):
        """Update status text"""
        self.update(self._render_status())

    def watch_status_color(self, old_value: str, new_value: str):
        """Update status color"""
        self.update(self._render_status())

    def watch_agent_status_text(self, old_value: str, new_value: str):
        """Update agent status text"""
        self.update(self._render_status())

    def watch_agent_status_color(self, old_value: str, new_value: str):
        """Update agent status color"""
        self.update(self._render_status())

    def _render_status(self) -> str:
        return (
            f"[bold]Broca CLI[/bold] │ "
            f"[{self.status_color}]{self.status_text}[/{self.status_color}] │ "
            f"[{self.agent_status_color}]{self.agent_status_text}[/{self.agent_status_color}]"
        )

    def update_status(self):
        """Update status from indicator"""
        self.status_text = self.status_indicator.get_status_text()
        self.status_color = self.status_indicator.get_status_color()
        self.agent_status_text = self.status_indicator.get_agent_status_text()
        self.agent_status_color = self.status_indicator.get_agent_status_color()


class MessageListWidget(RichLog):
    """Widget for displaying chat messages"""

    def __init__(self, **kwargs):
        super().__init__(markup=True, wrap=True, **kwargs)
        self._messages: list[str] = []
        self.auto_scroll = True

    def add_message(self, message: ChatMessage):
        """Add a new message to the log"""
        timestamp = message.timestamp.strftime("%H:%M:%S")

        # Style mapping
        styles = {
            ChatMessage.DisplayType.USER: ("You", "green"),
            ChatMessage.DisplayType.ASSISTANT: ("Assistant", "blue"),
            ChatMessage.DisplayType.SYSTEM: ("System", "grey"),
            ChatMessage.DisplayType.ERROR: ("Error", "red"),
            ChatMessage.DisplayType.TOOL: ("Tool", "orange"),
            ChatMessage.DisplayType.PERMISSION: ("Permission", "purple"),
        }

        sender_name, sender_color = styles.get(
            message.display_type, ("Unknown", "white")
        )

        # Format message with rich markup
        formatted_message = f"[dim]{timestamp}[/dim] [{sender_color} bold]{sender_name}:[/{sender_color} bold] {message.content}"

        self._messages.append(formatted_message)
        self.write(formatted_message)

    def clear_messages(self):
        """Clear all messages"""
        self._messages.clear()
        self.clear()


class PermissionDialog(Static):
    """Dialog for permission requests"""

    def __init__(self, message: str, **kwargs):
        super().__init__(**kwargs)
        self.message = message
        self.visible = False
        self._response_callback: Optional[Callable[[bool], None]] = None

    def set_response_callback(self, callback: Callable[[bool], None]):
        """Set the callback for user response"""
        self._response_callback = callback

    def compose(self):
        """Compose the permission dialog"""
        with Container(id="permission-container"):
            yield Static(self.message, id="permission-message")
            with Horizontal(id="permission-buttons"):
                yield Button("Yes (Y)", id="btn-yes", variant="success")
                yield Button("No (N)", id="btn-no", variant="error")

    def on_button_pressed(self, event: Button.Pressed) -> None:
        """Handle button press"""
        granted = event.button.id == "btn-yes"
        self.visible = False
        if self._response_callback:
            self._response_callback(granted)