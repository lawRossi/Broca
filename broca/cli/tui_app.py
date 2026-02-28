"""
Main TUI Application

Contains the main BrocaTUIApp class and related functionality.
"""

import asyncio
from typing import Any, Callable, Dict, Optional

from loguru import logger
from textual.app import App, ComposeResult
from textual.binding import Binding
from textual.containers import Container, Vertical
from textual.widgets import Input, Static

from .tui_models import ChatMessage, MessageBuffer, StatusIndicator
from .tui_widgets import MessageListWidget, PermissionDialog, StatusWidget


class BrocaTUIApp(App):
    """Main TUI application"""

    CSS_PATH = "tui_app.tcss"

    BINDINGS = [
        Binding("ctrl+c", "quit", "Quit"),
        Binding("up", "history_up", "Previous in history"),
        Binding("down", "history_down", "Next in history"),
        Binding("ctrl+l", "clear", "Clear chat"),
        Binding("ctrl+s", "toggle_scroll", "Toggle auto-scroll"),
    ]

    def __init__(
        self,
        server_url: str = "http://localhost:6868",
        client_type: str = "cli",
        client_id: Optional[str] = None,
        user_id: Optional[str] = None,
        session_id: Optional[str] = None,
        workspace: Optional[str] = None
    ):
        super().__init__()
        self.server_url = server_url
        self.client_type = client_type
        self.client_id = client_id or f"{client_type}_{id(self)}"
        self.user_id = user_id
        self.session_id = session_id
        self.workspace = workspace
        self._history_loaded: bool = False
        self._session_id_provided: bool = session_id is not None
        self.message_buffer = MessageBuffer()
        self.status = StatusIndicator()
        self.client = None
        self.agent = None

        # Input history
        self.input_history: list[str] = []
        self.history_index = -1
        self._current_input = ""

        # Permission callback
        self._permission_callback: Optional[Callable[[bool], Any]] = None

        # Event handlers
        self.event_handlers: Dict[str, list[Callable]] = {}

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
        # If session_id is provided (or resolved during agent init), load and show history
        await self._load_and_show_history_if_needed()
        await self._connect()

    async def _load_and_show_history_if_needed(self) -> None:
        """Load historical messages for the current session (if any) and render them."""
        if not self.session_id:
            return

        # Only load if user explicitly specified a session_id when launching
        # (avoid duplicating messages for brand-new sessions).
        if not self._session_id_provided or self._history_loaded:
            return

        try:
            if not self.agent or not hasattr(self.agent, "session_manager"):
                return

            messages = await self.agent.session_manager.get_messages()
            if not messages:
                self._history_loaded = True
                return

            await self.add_message(
                ChatMessage(
                    content=f"--- Loaded {len(messages)} historical messages for session {self.session_id} ---\n",
                    display_type=ChatMessage.DisplayType.SYSTEM,
                )
            )
            for m in messages:
                await self.add_session_message(m)

            self._history_loaded = True
        except Exception as e:
            logger.error(f"Failed to load history for session {self.session_id}: {e}")
            await self.add_message(
                ChatMessage(
                    content=f"Failed to load history for session {self.session_id}: {e}",
                    display_type=ChatMessage.DisplayType.ERROR,
                )
            )

    async def _initialize_agent(self):
        """Initialize the agent"""
        try:
            # Set agent connecting status
            self.status.set_agent_connecting()
            self.query_one(StatusWidget).update_status()

            from broca.agent_manager import AgentFactory

            factory = AgentFactory()
            self.agent = await factory.get_agent(
                "main_agent", session_id=self.session_id, workspace=self.workspace
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
                    display_type=ChatMessage.DisplayType.SYSTEM,
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
                    display_type=ChatMessage.DisplayType.ERROR,
                )
            )

    async def _show_welcome(self):
        """Show welcome message with ASCII art"""
        broca_ascii = """
╔══════════════════════════════════════════════════════════════════════════════════╗                                                                  ║
║                   ██████╗ ██████╗  ██████╗  ██████╗ █████╗                       ║
║                   ██╔══██╗██╔══██╗██╔═══██╗██╔════╝██╔══██╗                      ║
║                   ██████╔╝██████╔╝██║   ██║██║     ███████║                      ║
║                   ██╔══██╗██╔══██╗██║   ██║██║     ██╔══██║                      ║
║                   ██████╔╝██║  ██║╚██████╔╝╚██████╗██║  ██║                      ║
║                   ╚═════╝ ╚═╝  ╚═╝ ╚═════╝  ╚═════╝╚═╝  ╚═╝                      ║                                                                        ║
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
            display_type=ChatMessage.DisplayType.SYSTEM,
        )
        await self.add_message(welcome)

    async def _connect(self):
        """Connect to the server"""
        try:
            self.status.set_connecting()
            self.query_one(StatusWidget).update_status()

            from broca.comm.socketio_client import SocketIOClient

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
            self.client.register_event_handler("tool_call", self.on_tool_call)
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
                    content=f"Connection failed: {e}",
                    display_type=ChatMessage.DisplayType.ERROR,
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

    def on_key(self, event) -> None:
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
                    display_type=ChatMessage.DisplayType.SYSTEM,
                )
            )
        )

    async def _clear_messages(self):
        """Clear all messages"""
        await self.message_buffer.clear()
        message_list = self.query_one("#message-list", MessageListWidget)
        await message_list.clear_messages()
        await self.add_message(
            ChatMessage(
                content="Chat history cleared",
                display_type=ChatMessage.DisplayType.SYSTEM,
            )
        )

    async def add_message(self, message: ChatMessage):
        """Add a ChatMessage to the display"""
        await self.message_buffer.add_message(message)
        message_list = self.query_one("#message-list", MessageListWidget)
        message_list.add_message(message)
        await self._trigger_event("message_added", message)

    async def add_session_message(
        self, message: Any, display_type: Optional[ChatMessage.DisplayType] = None
    ):
        """
        Add a session message to the display

        Args:
            message: A session message object (e.g., Broca.session.models.Message)
            display_type: Optional display type override
        """
        await self.message_buffer.add_session_message(message, display_type)
        chat_message = ChatMessage.from_session_message(message, display_type)
        if chat_message:
            message_list = self.query_one("#message-list", MessageListWidget)
            message_list.add_message(chat_message)
            await self._trigger_event("message_added", chat_message)

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
                    content=f"Unknown command: {cmd}",
                    display_type=ChatMessage.DisplayType.ERROR,
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
            ChatMessage(content=help_text, display_type=ChatMessage.DisplayType.SYSTEM)
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
            ChatMessage(
                content=status_info, display_type=ChatMessage.DisplayType.SYSTEM
            )
        )

    async def cmd_quit(self, args):
        """Quit the application"""
        await self.add_message(
            ChatMessage(content="Goodbye!", display_type=ChatMessage.DisplayType.SYSTEM)
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
                    content="No command history",
                    display_type=ChatMessage.DisplayType.SYSTEM,
                )
            )
            return

        history_text = "Command History:\n" + "\n".join(
            f"{i + 1}. {cmd}" for i, cmd in enumerate(self.input_history)
        )
        await self.add_message(
            ChatMessage(
                content=history_text, display_type=ChatMessage.DisplayType.SYSTEM
            )
        )

    async def cmd_abort(self, args):
        """Send abort command to stop the current operation"""
        if not self.client or not self.client.is_connected():
            await self.add_message(
                ChatMessage(
                    content="Not connected to server",
                    display_type=ChatMessage.DisplayType.ERROR,
                )
            )
            return

        try:
            await self.client.send_command("abort", subscription=self.session_id)
            await self.add_message(
                ChatMessage(
                    content="Abort command sent",
                    display_type=ChatMessage.DisplayType.SYSTEM,
                )
            )
            logger.info(f"Abort command sent to {self.session_id}.")

        except Exception as e:
            logger.error(f"Failed to send abort command: {e}")
            await self.add_message(
                ChatMessage(
                    content=f"Failed to send abort command: {e}",
                    display_type=ChatMessage.DisplayType.ERROR,
                )
            )

    async def send_message(self, content: str):
        """Send a message to the server"""
        if not self.client or not self.client.is_connected():
            await self.add_message(
                ChatMessage(
                    content="Not connected to server",
                    display_type=ChatMessage.DisplayType.ERROR,
                )
            )
            return

        # Add user message to display
        await self.add_message(
            ChatMessage(content=content, display_type=ChatMessage.DisplayType.USER)
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
                    display_type=ChatMessage.DisplayType.ERROR,
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
                content="Disconnected from server",
                display_type=ChatMessage.DisplayType.SYSTEM,
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
            ChatMessage(
                content="Connected to server",
                display_type=ChatMessage.DisplayType.SYSTEM,
            )
        )

    async def on_disconnect(self):
        """Handle disconnection event"""
        self.status.set_disconnected()
        self.query_one(StatusWidget).update_status()
        await self.add_message(
            ChatMessage(
                content="Disconnected from server",
                display_type=ChatMessage.DisplayType.SYSTEM,
            )
        )

    async def on_agent_response(self, message):
        """Handle agent response"""
        content = message.data.get("content", "")
        await self.add_message(
            ChatMessage(content=content, display_type=ChatMessage.DisplayType.ASSISTANT)
        )

    async def on_tool_call(self, message):
        """Handle tool call"""
        tool_name = message.data.get("tool_name", "unknown")
        await self.add_message(
            ChatMessage(content=f"Calling tool: {tool_name}", display_type=ChatMessage.DisplayType.TOOL_CALL)
        )

    async def on_turn_start(self, message):
        """Handle turn start event"""
        self.status.set_agent_running()
        self.query_one(StatusWidget).update_status()
        await self.add_message(
            ChatMessage(
                content="Assistant is thinking...",
                display_type=ChatMessage.DisplayType.SYSTEM,
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
            ChatMessage(
                content=f"Error: {error_msg}",
                display_type=ChatMessage.DisplayType.ERROR,
            )
        )
