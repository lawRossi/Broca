"""
Chat state management.

Manages messages, input state, connection state, and message display options.
Each chat page creates its own ChatStore instance.
"""

import json
import time
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Callable, Dict, List, Optional

from broca.communication.socketio_client import SocketIOClient
from broca.session.models import Message, MessageProtocol

from broca_tui.debug_log import log, clear as debug_clear
from broca_tui.api.session import SessionAPI
from broca_tui.config import get_config


@dataclass
class TurnSummary:
    """Turn 摘要数据类（简洁模式使用，对齐 Web ChatTurnCard.vue 的 TurnSummary 接口）。

    表示一个 Agent 执行轮次的摘要信息，包含用户输入、工具执行统计、最终回复等。
    """
    turn_id: str
    sequence_number: int
    agent_id: str
    agent_name: str
    user_message: Optional[str] = None
    status: str = "active"  # active, thinking, calling_tool, completed, error
    current_tool: Optional[str] = None
    current_file_path: Optional[str] = None
    current_todo_list: List[Dict[str, Any]] = field(default_factory=list)
    total_duration: float = 0.0
    total_steps: int = 0
    tool_call_stats: List[Dict[str, Any]] = field(default_factory=list)
    final_response: str = ""
    reasoning_content: str = ""
    is_active: bool = True
    started_at: float = 0.0  # timestamp in ms
    created_at: str = ""
    last_message_id: Optional[str] = None


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

        # Messages (简洁模式: turn_summaries 替代 messages 用于渲染)
        self.show_redo_button: bool = False
        self.redo_receiver_id: Optional[str] = None
        self._preserve_redo: bool = False  # Prevent redo from being cleared after undo

        # Loading state
        self.loading: bool = False

        # Turn summaries (简洁模式)
        self.turn_summaries: List[TurnSummary] = []
        self.turn_history_skip: int = 0
        self.has_more_turns: bool = True
        self.loading_more_turns: bool = False
        self.active_turn_index: int = -1  # 当前活跃 turn 在列表中的索引
        self._duration_timer = None  # asyncio.TimerHandle
        self._on_get_agent_name: Optional[Callable[[str], Optional[str]]] = None

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

    def on_get_agent_name(self, callback: Callable[[str], Optional[str]]):
        """Register callback to get agent display name by ID."""
        self._on_get_agent_name = callback

    def _notify_change(self, force: bool = False):
        """Notify UI of state change.

        In 简洁模式, no debounce is needed since turn-based updates
        are less frequent than per-chunk message updates.

        Args:
            force: Kept for backward compatibility, always fires immediately
        """
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

            # 简洁模式：创建 TurnSummary
            turn_id = message.data.get("turn_id") if message.data else None
            if turn_id:
                agent_name = target_id or ""
                if self._on_get_agent_name:
                    agent_name = self._on_get_agent_name(target_id) or agent_name
                self.create_turn_summary(turn_id, target_id or "", agent_name)

            if self._on_message:
                self._on_message({"type": "turn_start", "agent_id": target_id})

        @self._socket.on("turn_end")
        async def handle_turn_end(message: Message):
            # Update agent state to idle
            target_id = message.sender_id or message.agent_id

            # 简洁模式：终结 TurnSummary
            turn_id = message.data.get("turn_id") if message.data else None
            if turn_id:
                result = message.data.get("result") if message.data else None
                self.finalize_turn_summary(turn_id, result)

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
        msg_type = msg_dict.get("message_type", "")

        # ── 简洁模式：step_start 更新 turn 步骤计数 ──
        if msg_type == "step_start":
            data = msg_dict.get("data", {}) or {}
            turn_id = data.get("turn_id") or msg_dict.get("turn_id", "")
            if turn_id:
                self.increment_turn_steps(turn_id)
            return

        # ── 简洁模式：tool_call 更新 turn 工具信息（仍需继续添加为消息） ──
        if msg_type == "tool_call":
            turn_id = msg_dict.get("turn_id", "")
            if turn_id:
                self.update_turn_on_tool_call(turn_id, msg_dict.get("data", {}))

        # ── 简洁模式：agent_response 更新 turn finalResponse（仍需继续添加为消息） ──
        if msg_type == "agent_response":
            turn_id = msg_dict.get("turn_id", "")
            if turn_id:
                self.update_turn_on_agent_response(turn_id, msg_dict.get("data", {}))

        # Skip filtered message types
        filtered_types = {
            "turn_start", "turn_end", "command",
            "permission_request", "permission_response",
            "agent_query", "user_answer",
            "subscribe", "unsubscribe", "connect", "disconnect",
            "ping", "pong", "task_start", "task_complete", "task_error",
            "step_end",
        }
        if msg_type in filtered_types:
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
                    # Reload turn data (简洁模式: turn_summaries 替代 messages)
                    import asyncio
                    asyncio.ensure_future(self.load_turn_history())
                return

        # Clear redo state on new messages (but not immediately after undo)
        if msg_dict.get("message_type") != "command_result" and not self._preserve_redo:
            self.show_redo_button = False
            self.redo_receiver_id = None

        # Add message
        # Turn update already handled above for step_start/tool_call/agent_response.
        # No need to add individual messages — rendering uses turn_summaries.
        return

    async def load_history(self, is_load_more: bool = False):
        """Load message history (简洁模式: 使用 load_turn_history 替代).

        保留此方法以防向后兼容，但内部不再执行消息级加载。
        渲染使用 load_turn_history() 加载的 turn_summaries。

        Args:
            is_load_more: Kept for API compatibility, unused
        """
        # 简洁模式下消息级历史不再需要，使用 load_turn_history() 替代
        pass

    # ==================== Turn Management (简洁模式) ====================

    def _find_turn(self, turn_id: str) -> Optional[TurnSummary]:
        """根据 turn_id 查找 TurnSummary。

        Args:
            turn_id: Turn ID to find

        Returns:
            TurnSummary if found, None otherwise
        """
        for t in self.turn_summaries:
            if t.turn_id == turn_id:
                return t
        return None

    async def load_turn_history(self, is_load_more: bool = False):
        """加载 turn 历史（简洁模式）。

        Args:
            is_load_more: 是否加载更多（滚动到顶部触发）
        """
        if not self.session_id:
            log("load_turn_history: no session_id")
            return

        log(f" load_turn_history: is_load_more={is_load_more}, loading_more_turns={self.loading_more_turns}, has_more_turns={self.has_more_turns}, skip={self.turn_history_skip}")

        if is_load_more:
            if self.loading_more_turns or not self.has_more_turns:
                log(f" load_turn_history: early return (loading_more={self.loading_more_turns}, has_more={self.has_more_turns})")
                return
            self.loading_more_turns = True
            self.loading = True  # 确保 loading 状态同步到 MessageList
        else:
            self.loading = True
            self.turn_history_skip = 0
            self.has_more_turns = True

        self._notify_change()

        limit = 3

        try:
            result = await self._api.get_session_turns(
                self.session_id,
                skip=self.turn_history_skip,
                limit=limit,
            )

            total = result.get("total", 0)
            raw_turns = result.get("turns", [])

            log(f" load_turn_history: API returned total={total}, turns_count={len(raw_turns)}, skip={self.turn_history_skip}")

            # 将后端数据映射为 TurnSummary
            new_turns = []
            for t in raw_turns:
                # 过滤已撤销的 turn
                if t.get("is_reverted", False):
                    continue

                summary = TurnSummary(
                    turn_id=t.get("turn_id", ""),
                    sequence_number=t.get("sequence_number", 0),
                    agent_id=t.get("agent_id", ""),
                    agent_name=t.get("agent_name", ""),
                    user_message=t.get("user_message"),
                    status="completed",  # 历史 turn 都是已完成的
                    current_tool=t.get("current_tool"),
                    current_file_path=t.get("current_file_path"),
                    current_todo_list=t.get("current_todo_list", []),
                    total_duration=t.get("duration_seconds", 0) or 0.0,
                    total_steps=t.get("total_steps", 0),
                    tool_call_stats=t.get("tool_call_stats", []),
                    final_response=t.get("final_response", ""),
                    is_active=False,
                    started_at=0,
                    created_at=t.get("created_at", ""),
                    last_message_id=t.get("last_message_id"),
                )
                new_turns.append(summary)

            if is_load_more:
                self.turn_summaries = new_turns + self.turn_summaries
            else:
                self.turn_summaries = new_turns

            self.turn_history_skip += limit
            self.has_more_turns = self.turn_history_skip < total

            log(f" load_turn_history: done, turn_summaries count={len(self.turn_summaries)}, has_more_turns={self.has_more_turns}, loading={self.loading}")

        except Exception as e:
            log(f" load_turn_history: ERROR {e}")
            self._notify_error(f"加载 Turn 历史失败: {e}")
        finally:
            self.loading = False
            self.loading_more_turns = False
            self._notify_change()

    def create_turn_summary(self, turn_id: str, agent_id: str, agent_name: str):
        """创建新的 TurnSummary（turn_start 事件触发）。

        Args:
            turn_id: Turn ID
            agent_id: Agent ID
            agent_name: Agent display name
        """
        # 检查是否已存在（避免重复）
        if any(t.turn_id == turn_id for t in self.turn_summaries):
            return

        summary = TurnSummary(
            turn_id=turn_id,
            sequence_number=len(self.turn_summaries) + 1,
            agent_id=agent_id,
            agent_name=agent_name,
            is_active=True,
            status="active",
            started_at=time.time() * 1000,
            created_at=datetime.now().isoformat(),
        )
        self.turn_summaries.append(summary)
        self.active_turn_index = len(self.turn_summaries) - 1
        self._start_duration_timer()
        self._notify_change(force=True)

    def update_turn_on_tool_call(self, turn_id: str, data: Dict[str, Any]):
        """工具调用消息到达时更新 turn 状态。

        Args:
            turn_id: Turn ID
            data: tool_call 消息的 data 字段
        """
        turn = self._find_turn(turn_id)
        if not turn:
            return

        tool_name = data.get("tool_name", "")
        if not tool_name:
            return

        # 更新当前工具
        turn.current_tool = tool_name

        # 更新工具调用统计
        found = False
        for stat in turn.tool_call_stats:
            if stat.get("toolName") == tool_name:
                stat["count"] = stat.get("count", 0) + 1
                found = True
                break
        if not found:
            turn.tool_call_stats.append({"toolName": tool_name, "count": 1})

        # 提取文件路径
        if tool_name in ("read_file", "edit_file", "write_file"):
            args = data.get("arguments", {})
            if isinstance(args, str):
                try:
                    args = json.loads(args)
                except (json.JSONDecodeError, TypeError):
                    args = {}
            if isinstance(args, dict):
                path = args.get("path")
                if path:
                    turn.current_file_path = path

        # 提取 TODO 列表
        if tool_name == "todo_management":
            args = data.get("arguments", {})
            if isinstance(args, str):
                try:
                    args = json.loads(args)
                except (json.JSONDecodeError, TypeError):
                    args = {}
            if isinstance(args, dict):
                todos = args.get("todos", [])
                if todos:
                    turn.current_todo_list = todos

        turn.status = "calling_tool"
        self._notify_change()

    def update_turn_on_agent_response(self, turn_id: str, data: Dict[str, Any]):
        """Agent 回复消息到达时累加 finalResponse。

        Args:
            turn_id: Turn ID
            data: agent_response 消息的 data 字段
        """
        turn = self._find_turn(turn_id)
        if not turn:
            return

        content_str = data.get("content", "")
        if isinstance(content_str, str) and content_str.strip():
            try:
                parsed = json.loads(content_str)
                if isinstance(parsed, dict):
                    content = parsed.get("content", "")
                    reasoning = parsed.get("reasoning_content", "")
                    if content:
                        turn.final_response += content
                    if reasoning:
                        turn.reasoning_content += reasoning
                else:
                    turn.final_response += content_str
            except (json.JSONDecodeError, TypeError):
                turn.final_response += content_str

        turn.status = "thinking"
        self._notify_change()

    def finalize_turn_summary(self, turn_id: str, result: Optional[Dict] = None):
        """终结 TurnSummary（turn_end 事件触发）。

        Args:
            turn_id: Turn ID
            result: turn_end 消息的 result 数据
        """
        turn = self._find_turn(turn_id)
        if not turn:
            return

        turn.is_active = False
        is_error = (result or {}).get("status") == "error" if result else False
        turn.status = "error" if is_error else "completed"
        turn.total_duration = (time.time() * 1000 - turn.started_at) / 1000

        # 如果当前活跃的 turn 被终结，停止定时器
        if self.active_turn_index >= 0:
            turn_at_index = self.turn_summaries[self.active_turn_index]
            if turn_at_index.turn_id == turn_id:
                self.active_turn_index = -1
                self._stop_duration_timer()

        self._notify_change(force=True)

    def increment_turn_steps(self, turn_id: str):
        """step_start 消息到达时增加对应 turn 的步骤计数。

        Args:
            turn_id: Turn ID
        """
        turn = self._find_turn(turn_id)
        if turn:
            turn.total_steps += 1
            self._notify_change()

    # ==================== Duration Timer ====================

    def _start_duration_timer(self):
        """启动活跃 turn 的耗时定时器。"""
        self._stop_duration_timer()
        import asyncio
        loop = asyncio.get_event_loop()
        self._duration_timer = loop.call_later(1.0, self._on_duration_tick)

    def _stop_duration_timer(self):
        """停止耗时定时器。"""
        if self._duration_timer is not None:
            try:
                self._duration_timer.cancel()
            except Exception:
                pass
            self._duration_timer = None

    def _on_duration_tick(self):
        """定时器回调：更新活跃 turn 的耗时。"""
        if self.active_turn_index >= 0 and self.active_turn_index < len(self.turn_summaries):
            turn = self.turn_summaries[self.active_turn_index]
            if turn.is_active:
                turn.total_duration = (time.time() * 1000 - turn.started_at) / 1000
                self._notify_change()
                # 继续计时
                import asyncio
                loop = asyncio.get_event_loop()
                self._duration_timer = loop.call_later(1.0, self._on_duration_tick)

    # ==================== Filtered Turns (简洁模式) ====================

    def get_filtered_turns(self, visible_agent_ids: List[str], all_agent_ids: List[str]) -> List[TurnSummary]:
        """根据 Agent 可见性过滤 turn。

        Args:
            visible_agent_ids: Currently visible agent IDs
            all_agent_ids: All agent IDs in the session

        Returns:
            Filtered list of TurnSummary
        """
        if not visible_agent_ids or len(visible_agent_ids) >= len(all_agent_ids):
            return list(self.turn_summaries)

        return [t for t in self.turn_summaries if t.agent_id in visible_agent_ids]

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

        # 简洁模式：无需乐观消息，turn_start 事件会创建 TurnSummary
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

    # ==================== Cleanup ====================

    def clear_messages(self):
        """Clear all turn data and state (简洁模式)."""
        self.show_redo_button = False
        self.turn_summaries.clear()
        self.turn_history_skip = 0
        self.has_more_turns = True
        self.loading_more_turns = False
        self.active_turn_index = -1
        self._stop_duration_timer()
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



