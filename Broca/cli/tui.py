"""
Terminal User Interface for Broca CLI

Provides a rich TUI experience with:
- Persistent screen layout (header, messages, input)
- Real-time message updates
- Connection status indicator
- Message formatting with colors
- Input history navigation
- Command support
"""

import argparse
import asyncio
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Any, Callable, Dict, List, Optional

from loguru import logger
from textual import events
from textual.app import App, ComposeResult
from textual.binding import Binding
from textual.containers import Container, Horizontal, Vertical
from textual.reactive import reactive
from textual.widgets import (
    Button,
    Input,
    RichLog,
    Static,
)

from Broca.agent_manager import AgentFactory
from Broca.comm.socketio_client import SocketIOClient
from Broca.session.database import db_manager

logger.add("tui.log", level="DEBUG")


class MessageType(Enum):
    """Message types for styling"""

    USER = "user"
    ASSISTANT = "assistant"
    SYSTEM = "system"
    ERROR = "error"
    TOOL = "tool"
    PERMISSION = "permission"


@dataclass
class ChatMessage:
    """Chat message data structure"""

    content: str
    message_type: MessageType
    timestamp: datetime = field(default_factory=datetime.now)
    sender_id: Optional[str] = None
    message_id: Optional[str] = None
    metadata: Dict[str, Any] = field(default_factory=dict)


class MessageBuffer:
    """Thread-safe message buffer for storing chat messages"""

    def __init__(self, max_size: int = 1000):
        self._messages: List[ChatMessage] = []
        self._max_size = max_size
        self._lock = asyncio.Lock()

    async def add_message(self, message: ChatMessage):
        """Add a new message to the buffer"""
        async with self._lock:
            if len(self._messages) >= self._max_size:
                self._messages.pop(0)
            self._messages.append(message)

    async def get_messages(self) -> List[ChatMessage]:
        """Get all messages"""
        async with self._lock:
            return self._messages.copy()

    async def clear(self):
        """Clear all messages"""
        async with self._lock:
            self._messages.clear()

    def __len__(self):
        return len(self._messages)


class StatusIndicator:
    """Connection status indicator"""

    def __init__(self):
        # Server connection status
        self.connected = False
        self.connecting = False
        self.session_id: Optional[str] = None
        self.server_url: Optional[str] = None

        # Agent connection status
        self.agent_connected = False
        self.agent_connecting = False
        self.agent_running = False
        self.agent_id: Optional[str] = None

    def set_connecting(self):
        """Set server connection to connecting"""
        self.connecting = True
        self.connected = False

    def set_connected(self, session_id: str, server_url: str):
        """Set server connection to connected"""
        self.connecting = False
        self.connected = True
        self.session_id = session_id
        self.server_url = server_url

    def set_disconnected(self):
        """Set server connection to disconnected"""
        self.connecting = False
        self.connected = False
        self.session_id = None

    def set_agent_connecting(self):
        """Set agent connection to connecting"""
        self.agent_connecting = True
        self.agent_connected = False

    def set_agent_connected(self, agent_id: str):
        """Set agent connection to connected"""
        self.agent_connecting = False
        self.agent_connected = True
        self.agent_running = False
        self.agent_id = agent_id

    def set_agent_disconnected(self):
        """Set agent connection to disconnected"""
        self.agent_connecting = False
        self.agent_connected = False
        self.agent_running = False
        self.agent_id = None

    def set_agent_running(self):
        """Set agent to running state (thinking)"""
        self.agent_running = True

    def set_agent_idle(self):
        """Set agent to idle state (finished thinking)"""
        self.agent_running = False

    def get_status_text(self) -> str:
        """Get server connection status text"""
        if self.connecting:
            return "Connecting..."
        elif self.connected:
            return f"Connected [{self.session_id}]"
        else:
            return "Disconnected"

    def get_status_color(self) -> str:
        """Get server connection status color"""
        if self.connecting:
            return "yellow"
        elif self.connected:
            return "green"
        else:
            return "red"

    def get_agent_status_text(self) -> str:
        """Get agent connection status text"""
        if self.agent_connecting:
            return "Agent Connecting..."
        elif self.agent_connected and self.agent_running:
            return "Agent Running"
        elif self.agent_connected:
            return "Agent Connected"
        else:
            return "Agent Disconnected"

    def get_agent_status_color(self) -> str:
        """Get agent connection status color"""
        if self.agent_connecting:
            return "yellow"
        elif self.agent_connected and self.agent_running:
            return "cyan"
        elif self.agent_connected:
            return "green"
        else:
            return "red"


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
        self._messages: List[str] = []
        self.auto_scroll = True

    def add_message(self, message: ChatMessage):
        """Add a new message to the log"""
        timestamp = message.timestamp.strftime("%H:%M:%S")

        # Style mapping
        styles = {
            MessageType.USER: ("You", "green"),
            MessageType.ASSISTANT: ("Assistant", "blue"),
            MessageType.SYSTEM: ("System", "grey"),
            MessageType.ERROR: ("Error", "red"),
            MessageType.TOOL: ("Tool", "orange"),
            MessageType.PERMISSION: ("Permission", "purple"),
        }

        sender_name, sender_color = styles.get(
            message.message_type, ("Unknown", "white")
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

    def compose(self) -> ComposeResult:
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


class BrocaTUIApp(App):
    """Main TUI application"""

    CSS = """
    #main-container {
        height: 100%;
        background: #f0f0f0;
    }

    #status-bar {
        height: 2;
        dock: top;
        background: #f0f0f0;
        padding: 0 1;
        color: #000000;
    }

    #message-container {
        height: 1fr;
        border: solid $primary;
        background: #f5f5f5;
    }

    MessageListWidget {
        background: #f5f5f5;
        color: #000000;
        scrollbar-size: 1 1;
    }

    #input-container {
        height: 3;
        dock: bottom;
        padding: 0 1;
        background: #f0f0f0;
    }

    Input {
        width: 1fr;
        background: #ffffff;
        color: #000000;
    }

    #permission-dialog {
        dock: top;
        layer: overlay;
        height: 10;
        background: #f0f0f0;
        border: thick $primary;
        padding: 1;
        color: #000000;
    }

    #permission-container {
        height: 1fr;
        content-align: center middle;
    }

    #permission-message {
        margin-bottom: 1;
        text-align: center;
    }

    #permission-buttons {
        margin-top: 1;
    }

    Button {
        margin: 0 1;
        min-width: 10;
    }
    """

    BINDINGS = [
        Binding("ctrl+c", "quit", "Quit"),
        Binding("up", "history_up", "Previous in history"),
        Binding("down", "history_down", "Next in history"),
        Binding("ctrl+l", "clear", "Clear chat"),
        Binding("ctrl+s", "toggle_scroll", "Toggle auto-scroll"),
    ]

    def __init__(
        self,
        server_url: str = "http://localhost:8001",
        client_type: str = "cli",
        client_id: Optional[str] = None,
        user_id: Optional[str] = None,
        session_id: Optional[str] = None,
    ):
        super().__init__()
        self.server_url = server_url
        self.client_type = client_type
        self.client_id = client_id or f"{client_type}_{id(self)}"
        self.user_id = user_id

        self.session_id = session_id
        self.message_buffer = MessageBuffer()
        self.status = StatusIndicator()
        self.client = None
        self.agent = None

        # Input history
        self.input_history: List[str] = []
        self.history_index = -1
        self._current_input = ""

        # Permission callback
        self._permission_callback: Optional[Callable[[bool], Any]] = None

        # Event handlers
        self.event_handlers: Dict[str, List[Callable]] = {}

    def compose(self) -> ComposeResult:
        """Compose the UI"""
        yield StatusWidget(self.status, id="status-bar")
        with Vertical(id="main-container"):
            with Container(id="message-container"):
                yield MessageListWidget(id="message-list")
            with Container(id="input-container"):
                yield Input(placeholder="Type your message...", id="user-input")
        yield PermissionDialog("", id="permission-dialog")

    def on_mount(self) -> None:
        """Called when the app is mounted"""
        asyncio.create_task(self._on_mounted())

    async def _on_mounted(self) -> None:
        await self._show_welcome()
        await self._initialize_agent()
        await self._connect()

    async def _initialize_agent(self):
        """Initialize the agent"""
        try:
            # Set agent connecting status
            self.status.set_agent_connecting()
            self.query_one(StatusWidget).update_status()

            factory = AgentFactory()
            self.agent = await factory.get_agent(
                "main_agent", session_id=self.session_id
            )
            if self.session_id is None:
                self.session_id = self.agent.session_manager.session_id
            await self.agent.connect()
            await self.agent.subscribe(self.session_id)

            # Set agent connected status
            if hasattr(self.agent, "agent_id"):
                self.status.set_agent_connected(self.agent.agent_id)
            else:
                self.status.set_agent_connected("main_agent")
            self.query_one(StatusWidget).update_status()

            await self.add_message(
                ChatMessage(
                    content=f"Agent initialized with session_id: {self.session_id}\n\n",
                    message_type=MessageType.SYSTEM,
                )
            )
            logger.info(f"Agent initialized with session_id: {self.session_id}")

        except Exception as e:
            logger.error(f"Failed to initialize agent: {e}")
            import traceback

            logger.error(traceback.format_exc())

            # Set agent disconnected status
            self.status.set_agent_disconnected()
            self.query_one(StatusWidget).update_status()

            await self.add_message(
                ChatMessage(
                    content=f"Failed to initialize agent: {e}",
                    message_type=MessageType.ERROR,
                )
            )

    async def _show_welcome(self):
        """Show welcome message with ASCII art"""
        broca_ascii = """
╔══════════════════════════════════════════════════════════════════════════════════╗                                                                  ║
║  ██████╗ ██████╗  ██████╗  ██████╗ █████╗                                        ║
║  ██╔══██╗██╔══██╗██╔═══██╗██╔════╝██╔══██╗                                       ║
║  ██████╔╝██████╔╝██║   ██║██║     ███████║                                       ║
║  ██╔══██╗██╔══██╗██║   ██║██║     ██╔══██║                                       ║
║  ██████╔╝██║  ██║╚██████╔╝╚██████╗██║  ██║                                       ║
║  ╚═════╝ ╚═╝  ╚═╝ ╚═════╝  ╚═════╝╚═╝  ╚═╝                                       ║                                                                        ║
║  ──────────────────────────────────────────────────────────────────────────────  ║
║                                                                                  ║
║  Welcome to Broca CLI - Your Intelligent Assistant                               ║
║                                                                                  ║
║  Commands:                                                                       ║
║    • Type your message and press Enter to send                                   ║
║    • Use /help for available commands                                            ║
║    • Press Ctrl+C to exit                                                        ║
║                                                                                  ║
║  Keyboard Shortcuts:                                                             ║
║    • Up/Down: Navigate input history                                             ║
║    • Ctrl+L: Clear chat                                                          ║
║    • Ctrl+S: Toggle auto-scroll                                                  ║
║                                                                                  ║
╚══════════════════════════════════════════════════════════════════════════════════╝
"""
        welcome = ChatMessage(
            content=broca_ascii,
            message_type=MessageType.SYSTEM,
        )
        await self.add_message(welcome)

    async def _connect(self):
        """Connect to the server"""
        try:
            self.status.set_connecting()
            self.query_one(StatusWidget).update_status()

            self.client = SocketIOClient(
                server_url=self.server_url,
                client_type=self.client_type,
                client_id=self.client_id,
                user_id=self.user_id,
            )

            # Register event handlers
            self.client.register_event_handler("connect", self.on_connect)
            self.client.register_event_handler("disconnect", self.on_disconnect)
            self.client.register_event_handler("agent_response", self.on_agent_response)
            self.client.register_event_handler("turn_start", self.on_turn_start)
            self.client.register_event_handler("turn_end", self.on_turn_end)
            self.client.register_event_handler(
                "permission_request", self.on_permission_request
            )
            self.client.register_event_handler("error", self.on_error)

            # Connect to server
            await self.client.connect()

            # Subscribe to session
            session_id = self.session_id
            logger.info(f"Subscribing to session: {session_id}")
            await self.client.subscribe(session_id)

            self.status.set_connected(session_id, self.server_url)
            self.query_one(StatusWidget).update_status()

            logger.info("Connected to server")

        except Exception as e:
            logger.error(f"Connection failed: {e}")
            self.status.set_disconnected()
            self.query_one(StatusWidget).update_status()
            await self.add_message(
                ChatMessage(
                    content=f"Connection failed: {e}", message_type=MessageType.ERROR
                )
            )

    def on_input_submitted(self, event: Input.Submitted) -> None:
        """Handle input submission"""
        user_input = event.value.strip()

        if not user_input:
            return

        # Add to history
        self.input_history.append(user_input)
        self.history_index = len(self.input_history)
        self._current_input = ""

        # Clear input
        event.input.value = ""

        # Handle commands
        if user_input.startswith("/"):
            asyncio.create_task(self.handle_command(user_input))
        else:
            asyncio.create_task(self.send_message(user_input))

    def on_key(self, event: events.Key) -> None:
        """Handle key events for history navigation"""

        if event.key == "up":
            self.action_history_up()
        elif event.key == "down":
            self.action_history_down()

    def action_history_up(self) -> None:
        """Navigate up in history"""
        if self.history_index > 0:
            if self.history_index == len(self.input_history):
                # Save current input
                self._current_input = self.query_one("#user-input", Input).value
            self.history_index -= 1
            self.query_one("#user-input", Input).value = self.input_history[
                self.history_index
            ]

    def action_history_down(self) -> None:
        """Navigate down in history"""
        if self.history_index < len(self.input_history):
            self.history_index += 1
            if self.history_index == len(self.input_history):
                self.query_one("#user-input", Input).value = self._current_input
            else:
                self.query_one("#user-input", Input).value = self.input_history[
                    self.history_index
                ]

    def action_clear(self) -> None:
        """Clear chat history"""
        asyncio.create_task(self._clear_messages())

    def action_toggle_scroll(self) -> None:
        """Toggle auto-scroll"""
        message_list = self.query_one("#message-list", MessageListWidget)
        message_list.auto_scroll = not message_list.auto_scroll
        asyncio.create_task(
            self.add_message(
                ChatMessage(
                    content=f"Auto-scroll {'enabled' if message_list.auto_scroll else 'disabled'}",
                    message_type=MessageType.SYSTEM,
                )
            )
        )

    async def _clear_messages(self):
        """Clear all messages"""
        await self.message_buffer.clear()
        message_list = self.query_one("#message-list", MessageListWidget)
        await message_list.clear_messages()
        await self.add_message(
            ChatMessage(content="Chat history cleared", message_type=MessageType.SYSTEM)
        )

    async def add_message(self, message: ChatMessage):
        """Add a message to the display"""
        await self.message_buffer.add_message(message)
        message_list = self.query_one("#message-list", MessageListWidget)
        message_list.add_message(message)
        await self._trigger_event("message_added", message)

    async def handle_command(self, command: str):
        """Handle CLI commands"""
        parts = command.split()
        cmd = parts[0].lower()
        args = parts[1:]

        commands = {
            "/help": self.cmd_help,
            "/clear": self.cmd_clear,
            "/status": self.cmd_status,
            "/quit": self.cmd_quit,
            "/exit": self.cmd_quit,
            "/history": self.cmd_history,
            "/abort": self.cmd_abort,
        }

        if cmd in commands:
            await commands[cmd](args)
        else:
            await self.add_message(
                ChatMessage(
                    content=f"Unknown command: {cmd}", message_type=MessageType.ERROR
                )
            )
            await self.cmd_help([])

    async def cmd_help(self, args):
        """Show help message"""
        help_text = """Available commands:
  /help      - Show this help message
  /clear     - Clear chat history
  /status    - Show connection status
  /history   - Show command history
  /abort     - Send abort command to stop current operation
  /quit      - Quit the application
  /exit      - Quit the application

Keyboard shortcuts:
  Up/Down    - Navigate input history
  Ctrl+L     - Clear chat
  Ctrl+S     - Toggle auto-scroll
  Ctrl+C     - Quit"""
        await self.add_message(
            ChatMessage(content=help_text, message_type=MessageType.SYSTEM)
        )

    async def cmd_clear(self, args):
        """Clear chat history"""
        await self._clear_messages()

    async def cmd_status(self, args):
        """Show connection status"""
        status_info = f"""Connection Status:
  Server: {self.server_url}
  Client ID: {self.client_id}
  Status: {self.status.get_status_text()}
  Messages: {len(self.message_buffer)}"""
        await self.add_message(
            ChatMessage(content=status_info, message_type=MessageType.SYSTEM)
        )

    async def cmd_quit(self, args):
        """Quit the application"""
        await self.add_message(
            ChatMessage(content="Goodbye!", message_type=MessageType.SYSTEM)
        )
        await self._disconnect()
        await asyncio.sleep(0.1)  # Small delay to allow message to be displayed
        # Schedule exit on the main event loop
        self.call_later(0.1, self.exit)

    async def cmd_history(self, args):
        """Show command history"""
        if not self.input_history:
            await self.add_message(
                ChatMessage(
                    content="No command history", message_type=MessageType.SYSTEM
                )
            )
            return

        history_text = "Command History:\n" + "\n".join(
            f"{i + 1}. {cmd}" for i, cmd in enumerate(self.input_history)
        )
        await self.add_message(
            ChatMessage(content=history_text, message_type=MessageType.SYSTEM)
        )

    async def cmd_abort(self, args):
        """Send abort command to stop the current operation"""
        if not self.client or not self.client.is_connected():
            await self.add_message(
                ChatMessage(
                    content="Not connected to server", message_type=MessageType.ERROR
                )
            )
            return

        try:
            await self.client.send_command("abort", subscription=self.session_id)
            await self.add_message(
                ChatMessage(
                    content="Abort command sent", message_type=MessageType.SYSTEM
                )
            )
            logger.info(f"Abort command sent to {self.session_id}.")

        except Exception as e:
            logger.error(f"Failed to send abort command: {e}")
            await self.add_message(
                ChatMessage(
                    content=f"Failed to send abort command: {e}",
                    message_type=MessageType.ERROR,
                )
            )

    async def send_message(self, content: str):
        """Send a message to the server"""
        if not self.client or not self.client.is_connected():
            await self.add_message(
                ChatMessage(
                    content="Not connected to server", message_type=MessageType.ERROR
                )
            )
            return

        # Add user message to display
        await self.add_message(
            ChatMessage(content=content, message_type=MessageType.USER)
        )

        try:
            # Get agent ID
            agent_id = self.status.agent_id
            logger.info(agent_id)
            await self.client.send_user_message(content=content, receiver_id=agent_id)

        except Exception as e:
            logger.error(f"Failed to send message: {e}")
            await self.add_message(
                ChatMessage(
                    content=f"Failed to send message: {e}",
                    message_type=MessageType.ERROR,
                )
            )

    async def _disconnect(self):
        """Disconnect from server"""
        if self.client:
            try:
                await self.client.disconnect()
            except Exception as e:
                logger.error(f"Disconnect error: {e}")

        self.status.set_disconnected()
        self.query_one(StatusWidget).update_status()
        await self.add_message(
            ChatMessage(
                content="Disconnected from server", message_type=MessageType.SYSTEM
            )
        )

    def register_event_handler(self, event_name: str, func: Callable):
        """Register event handler"""
        if event_name not in self.event_handlers:
            self.event_handlers[event_name] = []
        self.event_handlers[event_name].append(func)

    async def _trigger_event(self, event_name: str, *args):
        """Trigger event handlers"""
        if event_name in self.event_handlers:
            for handler in self.event_handlers[event_name]:
                try:
                    await handler(*args)
                except Exception as e:
                    logger.error(f"Error in event handler {event_name}: {e}")

    # Event handlers for SocketIO client
    async def on_connect(self):
        """Handle connection event"""
        await self.add_message(
            ChatMessage(content="Connected to server", message_type=MessageType.SYSTEM)
        )

    async def on_disconnect(self):
        """Handle disconnection event"""
        self.status.set_disconnected()
        self.query_one(StatusWidget).update_status()
        await self.add_message(
            ChatMessage(
                content="Disconnected from server", message_type=MessageType.SYSTEM
            )
        )

    async def on_agent_response(self, message):
        """Handle agent response"""
        content = message.data.get("content", "")
        await self.add_message(
            ChatMessage(content=content, message_type=MessageType.ASSISTANT)
        )

    async def on_turn_start(self, message):
        """Handle turn start event"""
        self.status.set_agent_running()
        self.query_one(StatusWidget).update_status()
        await self.add_message(
            ChatMessage(
                content="Assistant is thinking...", message_type=MessageType.SYSTEM
            )
        )

    async def on_turn_end(self, message):
        """Handle turn end event"""
        self.status.set_agent_idle()
        self.query_one(StatusWidget).update_status()

    async def on_permission_request(self, message):
        """Handle permission request"""
        request_message = message.data.get("message", "Permission required")
        request_id = message.data.get("request_id")
        sender_id = message.sender_id

        # Show permission dialog
        dialog = self.query_one("#permission-dialog", PermissionDialog)
        dialog.message = request_message
        dialog.visible = True
        dialog.query_one("#permission-message", Static).update(request_message)

        # Wait for user response
        response_future = asyncio.Future()

        def on_response(granted: bool):
            response_future.set_result(granted)

        dialog.set_response_callback(on_response)

        try:
            granted = await asyncio.wait_for(response_future, timeout=60.0)
            logger.info(f"Permission {'granted' if granted else 'denied'}")
            # Send permission response back
            await self.client.send_permission_response(
                granted=granted, request_id=request_id, receiver_id=sender_id
            )
        except asyncio.TimeoutError:
            logger.warning("Permission request timed out")
            # Send denial on timeout
            await self.client.send_permission_response(
                granted=False, request_id=request_id, receiver_id=sender_id
            )
        finally:
            dialog.set_response_callback(None)

    async def on_error(self, data):
        """Handle error event"""
        error_msg = str(data)
        await self.add_message(
            ChatMessage(content=f"Error: {error_msg}", message_type=MessageType.ERROR)
        )


class TUI:
    """
    Terminal User Interface for Broca CLI

    This is a wrapper around the Textual app for backwards compatibility.
    """

    def __init__(
        self,
        server_url: str = "http://localhost:8001",
        client_type: str = "cli",
        client_id: Optional[str] = None,
        user_id: Optional[str] = None,
        session_id: Optional[str] = None,
    ):
        """
        Initialize TUI

        Args:
            server_url: Socket.io server URL
            client_type: Client type
            client_id: Client identifier
            user_id: User identifier
            session_id: Session identifier (if not provided, will generate one and initialize agent)
        """
        self.server_url = server_url
        self.client_type = client_type
        self.client_id = client_id or f"{client_type}_{id(self)}"
        self.user_id = user_id
        self.session_id = session_id

        self.app = BrocaTUIApp(
            server_url=server_url,
            client_type=client_type,
            client_id=client_id,
            user_id=user_id,
            session_id=session_id,
        )

    def register_event_handler(self, event_name: str, func: Callable):
        """Register event handler"""
        self.app.register_event_handler(event_name, func)

    async def run(self):
        """Run the TUI"""
        await self.app.run_async()


async def main():
    """Main entry point for TUI"""

    parser = argparse.ArgumentParser(description="Broca CLI - Terminal User Interface")
    parser.add_argument(
        "--server", "-s", default="http://localhost:8001", help="Socket.io server URL"
    )
    parser.add_argument("--client-type", "-t", default="cli", help="Client type")
    parser.add_argument("--client-id", "-c", default=None, help="Client identifier")
    parser.add_argument("--user-id", "-u", default=None, help="User identifier")
    parser.add_argument(
        "--session-id",
        "-i",
        default=None,
        help="Session identifier (if not provided, will generate one and initialize agent)",
    )

    args = parser.parse_args()

    # setup tables
    await db_manager.init_tables()

    # Create and run TUI
    tui = TUI(
        server_url=args.server,
        client_type=args.client_type,
        client_id=args.client_id,
        user_id=args.user_id,
        session_id=args.session_id,
    )

    try:
        await tui.run()
    except KeyboardInterrupt:
        logger.info("Interrupted by user")
    except Exception as e:
        logger.error(f"Fatal error: {e}")
        raise


if __name__ == "__main__":
    asyncio.run(main())
