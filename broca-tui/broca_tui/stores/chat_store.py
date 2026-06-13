"""
Chat state management.

Manages messages, input state, connection state, and message display options.
Each chat page creates its own ChatStore instance.
"""

import json
from typing import Any, Callable, Dict, List, Optional

from broca.communication.socketio_client import SocketIOClient
from broca.session.models import Message, MessageProtocol

from broca_tui.api.session import SessionAPI
from broca_tui.config import get_config


class ChatStore:
    """Store for chat state."""

    def __init__(self, api: Optional[SessionAPI] = None):
        """Initialize chat store.

        Args:
            api: SessionAPI instance. Creates a new one if not provided.
        """
        self._api = api or SessionAPI()
        self._config = get_config()

        # Socket.IO client
        self._socket: Optional[SocketIOClient] = None

        # Connection state
        self.connected: bool = False
        self.connecting: bool = False
        self.session_id: Optional[str] = None
        self.execution_id: Optional[str] = None
        self.is_agent_orchestration: bool = False

        # Messages
        self.messages: List[Dict[str, Any]] = []
        self.message_states: Dict[str, Dict[str, bool]] = {}  # message_id -> {showParameters, showResult, showReasoning}
        self.pending_chunks: Dict[str, List[Dict[str, Any]]] = {}  # message_id -> [chunks]
        self.show_redo_button: bool = False
        self.redo_receiver_id: Optional[str] = None
        self._preserve_redo: bool = False  # Prevent redo from being cleared after undo

        # Streaming debounce: batch rapid _notify_change calls during streaming
        self._debounce_timer: Optional[asyncio.TimerHandle] = None
        self._debounce_delay: float = 0.2  # 200ms
        # Tracks which message was updated last (for in-place streaming updates)
        self.last_updated_message_id: Optional[str] = None

        # Loading state
        self.loading: bool = False
        self.loading_more: bool = False
        self.has_more_history: bool = True
        self.history_skip: int = 0
        self.history_total: int = 0

        # Input state
        self.input_text: str = ""

        # Runner state
        self.runner_info: Optional[Dict[str, Any]] = None
        self.runner_alive: bool = False

        # Permission dialog state
        self.permission_dialog: Dict[str, Any] = {
            "visible": False,
            "request_id": None,
            "sender_id": None,
            "message": "",
            "request_type": "general",
        }

        # Agent query dialog state
        self.agent_query_dialog: Dict[str, Any] = {
            "visible": False,
            "request_id": None,
            "sender_id": None,
            "question": "",
            "options": [],
        }

        # Callbacks
        self._on_change: Optional[Callable[[], None]] = None
        self._on_error: Optional[Callable[[str], None]] = None
        self._on_permission: Optional[Callable[[Dict[str, Any]], None]] = None
        self._on_agent_query: Optional[Callable[[Dict[str, Any]], None]] = None
        self._on_message: Optional[Callable[[Dict[str, Any]], None]] = None
        self._on_connection_change: Optional[Callable[[bool], None]] = None

    def on_change(self, callback: Callable[[], None]):
        """Register callback for general state changes."""
        self._on_change = callback

    def on_error(self, callback: Callable[[str], None]):
        """Register callback for errors."""
        self._on_error = callback

    def on_permission_request(self, callback: Callable[[Dict[str, Any]], None]):
        """Register callback for permission requests."""
        self._on_permission = callback

    def on_agent_query(self, callback: Callable[[Dict[str, Any]], None]):
        """Register callback for agent queries."""
        self._on_agent_query = callback

    def on_message_received(self, callback: Callable[[Dict[str, Any]], None]):
        """Register callback for new messages."""
        self._on_message = callback

    def on_connection_change(self, callback: Callable[[bool], None]):
        """Register callback for connection state changes."""
        self._on_connection_change = callback

    def _notify_change(self, force: bool = False):
        """Notify UI of state change, with debounce for streaming.

        During streaming (pending_chunks active), rapid _notify_change calls
        are debounced to avoid re-rendering on every chunk. Use force=True
        for critical updates (e.g., complete message, error).

        Args:
            force: If True, fire immediately regardless of debounce state
        """
        if force:
            self._cancel_debounce()
            if self._on_change:
                self._on_change()
            return

        # Debounce: batch rapid changes during streaming
        if self.pending_chunks:
            import asyncio
            loop = asyncio.get_event_loop()
            self._cancel_debounce()
            self._debounce_timer = loop.call_later(
                self._debounce_delay, self._fire_notify
            )
        else:
            if self._on_change:
                self._on_change()

    def _cancel_debounce(self):
        """Cancel pending debounce timer."""
        if self._debounce_timer is not None:
            try:
                self._debounce_timer.cancel()
            except Exception:
                pass
            self._debounce_timer = None

    def _fire_notify(self):
        """Fire pending notification (called by debounce timer)."""
        self._debounce_timer = None
        if self._on_change:
            self._on_change()

    def _notify_error(self, message: str):
        """Notify UI of error."""
        if self._on_error:
            self._on_error(message)

    # ==================== Socket.IO Connection ====================

    async def connect(self, session_id: str, execution_id: Optional[str] = None):
        """Connect to Socket.IO server and subscribe to session.

        Args:
            session_id: Session ID to subscribe to
            execution_id: Optional execution ID for filtering
        """
        if self.connecting:
            return

        self.connecting = True
        self.session_id = session_id
        self.execution_id = execution_id
        self._notify_change()

        try:
            # Create Socket.IO client
            self._socket = SocketIOClient(
                server_url=self._config.socket_server_url,
                client_type="tui",
                client_id=self._config.client_id,
                user_id=self._config.user_id,
                auto_reconnect=self._config.auto_reconnect,
                reconnect_delay=self._config.reconnect_delay,
                max_reconnect_attempts=self._config.max_reconnect_attempts,
            )

            # Register event handlers
            self._register_socket_handlers()

            # Connect
            await self._socket.connect()
            self.connected = True

            # Subscribe to session channel
            await self._socket.subscribe(session_id)

            # Start Runner polling
            await self._fetch_runner_status()

        except Exception as e:
            self._notify_error(f"连接失败: {e}")
        finally:
            self.connecting = False
            self._notify_change()

    def _register_socket_handlers(self):
        """Register Socket.IO event handlers."""
        if not self._socket:
            return

        @self._socket.on_message
        async def handle_message(message: Message):
            self._process_incoming_message(message)

        @self._socket.on("turn_start")
        async def handle_turn_start(message: Message):
            # Update agent state to running
            target_id = message.sender_id or message.agent_id
            if self._on_message:
                self._on_message({"type": "turn_start", "agent_id": target_id})

        @self._socket.on("turn_end")
        async def handle_turn_end(message: Message):
            # Update agent state to idle
            target_id = message.sender_id or message.agent_id
            if self._on_message:
                self._on_message({"type": "turn_end", "agent_id": target_id})

        @self._socket.on("permission_request")
        async def handle_permission(message: Message):
            self.permission_dialog["visible"] = True
            self.permission_dialog["request_id"] = message.data.get("request_id")
            self.permission_dialog["sender_id"] = message.sender_id
            self.permission_dialog["message"] = message.data.get("message", "")
            self.permission_dialog["request_type"] = message.data.get("request_type", "general")
            if self._on_permission:
                self._on_permission(self.permission_dialog)

        @self._socket.on("agent_query")
        async def handle_agent_query(message: Message):
            self.agent_query_dialog["visible"] = True
            self.agent_query_dialog["request_id"] = message.data.get("request_id")
            self.agent_query_dialog["sender_id"] = message.sender_id
            self.agent_query_dialog["question"] = message.data.get("question") or message.data.get("content", "")
            self.agent_query_dialog["options"] = message.data.get("options", [])
            if self._on_agent_query:
                self._on_agent_query(self.agent_query_dialog)

        @self._socket.on("connect")
        async def handle_connect():
            self.connected = True
            self._notify_change()
            if self._on_connection_change:
                self._on_connection_change(True)

        @self._socket.on("disconnect")
        async def handle_disconnect():
            self.connected = False
            self._notify_change()
            if self._on_connection_change:
                self._on_connection_change(False)

    # ==================== Message Handling ====================

    def _process_incoming_message(self, message: Message):
        """Process an incoming message from Socket.IO.

        Args:
            message: The received Message object
        """
        msg_dict = MessageProtocol.to_dict(message)

        # Skip filtered message types
        filtered_types = {
            "turn_start", "turn_end", "command",
            "permission_request", "permission_response",
            "agent_query", "user_answer",
            "subscribe", "unsubscribe", "connect", "disconnect",
            "ping", "pong", "task_start", "task_complete", "task_error",
            "step_start", "step_end",
        }
        if msg_dict.get("message_type") in filtered_types:
            return

        # Skip reverted messages
        if msg_dict.get("reverted"):
            return

        # Handle undo/redo
        if msg_dict.get("message_type") == "command_result":
            command = msg_dict.get("data", {}).get("command")
            if command in ("undo", "redo"):
                result = msg_dict.get("data", {}).get("result", {})
                if isinstance(result, dict) and result.get("code") == 0:
                    if command == "undo":
                        self.show_redo_button = True
                        self.redo_receiver_id = msg_dict.get("sender_id")
                        self._preserve_redo = True  # Don't clear redo during reload
                    else:
                        self.show_redo_button = False
                        self.redo_receiver_id = None
                        self._preserve_redo = False
                    # Reload history (we're in an async event loop context)
                    import asyncio
                    asyncio.ensure_future(self.load_history())
                return

        # Clear redo state on new messages (but not immediately after undo)
        if msg_dict.get("message_type") != "command_result" and not self._preserve_redo:
            self.show_redo_button = False
            self.redo_receiver_id = None

        # Add message
        self._add_message(msg_dict)

    def _add_message(self, message: Dict[str, Any]):
        """Add a message to the list, handling chunk merging for agent responses and tool calls.

        Args:
            message: Message dict
        """
        msg_type = message.get("message_type")

        # ===== Web-aligned filtering (processMessage) =====
        # 1. Filtered types — never displayed
        filtered_types = {
            "turn_start", "turn_end", "command",
            "permission_request", "permission_response",
            "agent_query", "user_answer",
            "subscribe", "unsubscribe", "connect", "disconnect",
            "ping", "pong", "task_start", "task_complete", "task_error",
            "step_start", "step_end",
        }
        if msg_type in filtered_types:
            return

        # 2. User messages from agents (e.g., permission granted echoes)
        data = message.get("data") or {}
        if msg_type == "user_message" and data.get("from_agent"):
            return

        # 3. Agent responses with empty content after JSON parsing
        if msg_type == "agent_response":
            content_str = data.get("content", "")
            if isinstance(content_str, str) and content_str.strip():
                try:
                    parsed = json.loads(content_str)
                    if isinstance(parsed, dict):
                        has_content = bool(parsed.get("content"))
                        has_reasoning = bool(parsed.get("reasoning_content"))
                        if not has_content and not has_reasoning:
                            return
                except (json.JSONDecodeError, TypeError):
                    pass

        # 4. Connection/subscription status messages
        content_str = str(data.get("content", ""))
        if any(keyword in content_str.lower() for keyword in ("connected to", "subscribed to")):
            return

        if msg_type == "tool_call":
            tool_call_id = message.get("data", {}).get("tool_call_id")
            if tool_call_id:
                # Check for existing tool call with same ID
                for i, existing in enumerate(self.messages):
                    if (existing.get("message_type") == "tool_call"
                            and existing.get("data", {}).get("tool_call_id") == tool_call_id):
                        # Merge data
                        existing["data"] = {**existing.get("data", {}), **message.get("data", {})}
                        self.last_updated_message_id = existing.get("message_id", "")
                        self._notify_change()
                        return

            # New tool call
            self.messages.append(message)
            self._init_message_state(message["message_id"])

        elif msg_type == "agent_response":
            msg_id = message.get("message_id")

            # Collect chunks
            if msg_id not in self.pending_chunks:
                self.pending_chunks[msg_id] = []
            self.pending_chunks[msg_id].append(message)

            # Merge chunks
            merged = self._merge_agent_chunks(self.pending_chunks[msg_id])

            # Check if message already exists
            for existing in self.messages:
                if existing.get("message_type") == "agent_response" and existing.get("message_id") == msg_id:
                    existing["data"] = {
                        **existing.get("data", {}),
                        "content": json.dumps(merged, ensure_ascii=False),
                    }
                    self.last_updated_message_id = msg_id
                    self._notify_change()
                    return

            # New message
            import copy
            self.messages.append(copy.deepcopy(message))
            self._init_message_state(msg_id)

        else:
            self.messages.append(message)
            self._init_message_state(message.get("message_id", ""))

        self._notify_change()

    def _merge_agent_chunks(self, chunks: List[Dict[str, Any]]) -> Dict[str, Any]:
        """Merge agent response chunks.

        Args:
            chunks: List of agent response message dicts

        Returns:
            Merged content dict with 'content', 'reasoning_content', 'index'
        """
        merged_content = ""
        merged_reasoning = ""

        for chunk in chunks:
            try:
                data_str = chunk.get("data", {}).get("content", "{}")
                if isinstance(data_str, str):
                    data = json.loads(data_str)
                else:
                    data = data_str
                merged_content += data.get("content", "")
                merged_reasoning += data.get("reasoning_content", "")
            except (json.JSONDecodeError, TypeError):
                pass

        return {
            "content": merged_content,
            "reasoning_content": merged_reasoning,
            "index": 0,
        }

    def _init_message_state(self, message_id: str):
        """Initialize display state for a message."""
        if message_id and message_id not in self.message_states:
            self.message_states[message_id] = {
                "showParameters": False,
                "showResult": False,
                "showReasoning": False,
            }

    # ==================== History Loading ====================

    async def load_history(self, is_load_more: bool = False):
        """Load message history.

        Args:
            is_load_more: If True, loads next page of history
        """
        if not self.session_id:
            return

        if is_load_more:
            if self.loading_more or not self.has_more_history:
                return
            self.loading_more = True
        else:
            self.loading = True
            self.history_skip = 0
            self.has_more_history = True

        self._notify_change()

        limit = 20

        try:
            result = await self._api.get_session_messages(
                self.session_id,
                skip=self.history_skip,
                limit=limit,
                execution_id=self.execution_id,
            )

            self.history_total = result.get("total", 0)
            raw_messages = result.get("messages", [])

            # Process messages
            processed = []
            for msg in raw_messages:
                msg_type = msg.get("message_type", "")
                if msg_type in ("turn_start", "turn_end", "command",
                                "subscribe", "unsubscribe", "connect", "disconnect",
                                "ping", "pong", "step_start", "step_end"):
                    continue
                if msg.get("reverted"):
                    continue
                processed.append(msg)
                self._init_message_state(msg.get("message_id", ""))

            if is_load_more:
                self.messages = processed + self.messages
            else:
                self.messages = processed

            self.history_skip += limit
            self.has_more_history = self.history_skip < self.history_total

        except Exception as e:
            self._notify_error(f"加载消息历史失败: {e}")
        finally:
            self.loading = False
            self.loading_more = False
            self._notify_change()

    # ==================== Sending Messages ====================

    async def send_user_message(
        self,
        content: str,
        target_agent_id: Optional[str] = None,
    ):
        """Send a user message.

        Args:
            content: Message content
            target_agent_id: Target agent ID
        """
        if not content.strip() or not self._socket or not self.session_id:
            return

        # Reset redo preservation when user sends a new message
        self._preserve_redo = False

        # Optimistic update
        msg_id = f"msg_{id(content)}_{hash(content)}"
        optimistic_msg = {
            "message_id": msg_id,
            "message_type": "user_message",
            "timestamp": "",
            "role": "user",
            "sender_id": "user",
            "receiver_id": target_agent_id,
            "data": {"content": content},
        }
        self.messages.append(optimistic_msg)
        self._notify_change()

        try:
            await self._socket.send_user_message(
                content=content,
                receiver_id=target_agent_id,
                subscription=self.session_id,
            )
        except Exception as e:
            self._notify_error(f"发送消息失败: {e}")

    async def send_abort(self, agent_id: Optional[str] = None):
        """Send abort command to an agent.

        Args:
            agent_id: Agent ID to abort. If None, aborts current agent.
        """
        if not self._socket:
            return
        try:
            await self._socket.send_command(
                command="/abort",
                arguments={"agent_id": agent_id} if agent_id else None,
                subscription=self.session_id,
            )
        except Exception as e:
            self._notify_error(f"中止失败: {e}")

    async def send_undo(self, target_message_id: str, target_agent_id: Optional[str] = None,
                         level: str = "step"):
        """Send undo command (matching Web's sendUndo command).

        Web reference:
        ```javascript
        client.sendCommand({
          command: 'undo',
          arguments: { target_message_id, level },
          subscription,
          receiverId,
        })
        ```

        Args:
            target_message_id: ID of the message to undo
            target_agent_id: Target agent (receiverId)
            level: Undo level ('turn' or 'step')
        """
        if not self._socket:
            self._notify_error("Socket 未连接，无法撤销")
            return
        try:
            await self._socket.send_command(
                command="undo",
                arguments={
                    "target_message_id": target_message_id,
                    "level": level,
                },
                subscription=self.session_id,
                receiver_id=target_agent_id,
            )
        except Exception as e:
            self._notify_error(f"撤销失败: {e}")

    async def send_redo(self, target_agent_id: Optional[str] = None):
        """Send redo command (matching Web's sendRedo command).

        Web reference:
        ```javascript
        client.sendCommand({
          command: 'redo',
          arguments: {},
          receiverId,
        })
        ```

        Args:
            target_agent_id: Target agent (receiverId)
        """
        if not self._socket:
            self._notify_error("Socket 未连接，无法重做")
            return
        try:
            await self._socket.send_command(
                command="redo",
                arguments={},
                subscription=self.session_id,
                receiver_id=target_agent_id,
            )
        except Exception as e:
            self._notify_error(f"重做失败: {e}")

    async def respond_permission(self, granted: bool, session_action: Optional[str] = None):
        """Respond to a permission request.

        Args:
            granted: Whether permission is granted
            session_action: Optional session-level action
        """
        if not self._socket:
            return

        dialog = self.permission_dialog
        try:
            await self._socket.send_permission_response(
                granted=granted,
                request_id=dialog["request_id"],
                receiver_id=dialog["sender_id"] or "",
                subscription=self.session_id,
            )
        except Exception as e:
            self._notify_error(f"权限响应失败: {e}")
        finally:
            dialog["visible"] = False
            self._notify_change()

    async def respond_user_answer(self, answer: str):
        """Respond to an agent query (Web alignment: sendUserAnswer).

        Web reference:
        ```javascript
        socketStore.sendUserAnswer({
          answer,        // string
          requestId,     // string
          receiverId,    // string
        })
        ```

        Args:
            answer: User's answer text
        """
        if not self._socket:
            return

        dialog = self.agent_query_dialog
        target_agent_id = dialog.get("sender_id") or ""
        try:
            # Send user_answer matching Web's format: {answer, request_id, receiver_id}
            from broca_tui.api.session import MessageProtocol
            msg = MessageProtocol.create_user_message(
                content=answer,
                sender_id="user",
                receiver_id=target_agent_id,
            )
            msg.message_type = "user_answer"
            # Backend handle_user_answer expects data.answer + data.request_id
            msg.data["answer"] = answer
            msg.data["request_id"] = dialog.get("request_id", "")
            msg.subscription = self.session_id
            await self._socket.send_message(msg)
        except Exception as e:
            self._notify_error(f"回答发送失败: {e}")
        finally:
            dialog["visible"] = False
            self._notify_change()

    # ==================== Runner Status ====================

    async def _fetch_runner_status(self):
        """Fetch current Runner status."""
        if not self.session_id:
            return
        try:
            info = await self._api.get_runner_status(self.session_id)
            self.runner_info = info
            self.runner_alive = info.get("status") == "alive"
            self._notify_change()
        except Exception:
            self.runner_alive = False

    async def stop_runner(self):
        """Stop the Runner process."""
        if not self.session_id:
            return
        try:
            await self._api.stop_runner(self.session_id)
            self.runner_alive = False
            self._notify_change()
        except Exception as e:
            self._notify_error(f"停止Runner失败: {e}")

    async def restart_runner(self):
        """Restart the Runner process."""
        if not self.session_id:
            return
        try:
            result = await self._api.restart_runner(self.session_id)
            await self._fetch_runner_status()
            return result
        except Exception as e:
            self._notify_error(f"重启Runner失败: {e}")
            return None

    # ==================== Message Display State ====================

    def toggle_tool_parameters(self, message_id: str):
        """Toggle display of tool parameters."""
        state = self.message_states.get(message_id)
        if state:
            state["showParameters"] = not state["showParameters"]
            self._notify_change()

    def toggle_tool_result(self, message_id: str):
        """Toggle display of tool result."""
        state = self.message_states.get(message_id)
        if state:
            state["showResult"] = not state["showResult"]
            self._notify_change()

    def toggle_reasoning(self, message_id: str):
        """Toggle display of reasoning content."""
        state = self.message_states.get(message_id)
        if state:
            state["showReasoning"] = not state["showReasoning"]
            self._notify_change()

    # ==================== Cleanup ====================

    def get_filtered_messages(self, visible_agent_ids: List[str], all_agent_ids: List[str]) -> List[Dict[str, Any]]:
        """Get messages filtered by agent visibility (matching Web's filteredMessages).

        Web reference logic:
        - user_message: filter by receiver_id → agent_id (no target → only show when all visible)
        - system_message: always visible
        - other: filter by sender_id → agent_id
        - If visible_agent_ids empty or equals all agents: no filtering

        Args:
            visible_agent_ids: Currently visible agent IDs
            all_agent_ids: All agent IDs in the session

        Returns:
            Filtered message list
        """
        if not visible_agent_ids or len(visible_agent_ids) >= len(all_agent_ids):
            return list(self.messages)

        result = []
        for msg in self.messages:
            msg_type = msg.get("message_type", "")
            role = msg.get("role", "")

            if msg_type in ("user_message",) or role == "user":
                target_id = msg.get("receiver_id") or msg.get("agent_id")
                if not target_id:
                    # No target → only show when ALL agents are visible
                    if len(visible_agent_ids) >= len(all_agent_ids):
                        result.append(msg)
                elif target_id in visible_agent_ids:
                    result.append(msg)
            elif msg_type in ("agent_system_message", "system_message") or role == "agent_system":
                # System messages always visible (Web alignment)
                result.append(msg)
            else:
                # agent_response, tool_call, error: filter by sender_id
                sender_id = msg.get("sender_id") or msg.get("agent_id")
                if not sender_id or sender_id in visible_agent_ids:
                    result.append(msg)

        return result

    def clear_messages(self):
        """Clear all messages and state."""
        self.messages = []
        self.message_states.clear()
        self.pending_chunks.clear()
        self.show_redo_button = False
        self._notify_change()

    async def disconnect(self):
        """Disconnect from Socket.IO server."""
        if self._socket:
            try:
                await self._socket.disconnect()
            except Exception:
                pass
            self._socket = None
        self.connected = False
        self.session_id = None
        self.runner_info = None
        self.runner_alive = False
        self._notify_change()

    async def close(self):
        """Close all connections and clean up."""
        await self.disconnect()
        await self._api.close()



