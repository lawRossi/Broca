"""
Chat state management.

Manages messages, input state, connection state, and message display options.
Each chat page creates its own ChatStore instance.
"""

import json
import re
import time
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Callable, Dict, List, Optional

from broca.communication.socketio_client import SocketIOClient
from broca.session.models import Message, MessageProtocol
from broca_tui.api.session import SessionAPI
from broca_tui.config import get_config
from broca_tui.debug_log import log


def _clean_error_message(raw: str) -> str:
    """从 API 错误文本中提取用户可读的错误信息，避免 JSON 原文暴露到 toast。

    处理格式：
    - "Client error 400 for POST /path: {\"detail\":\"msg\"}"
    - "API error 400: some message"
    - Raw JSON: {"detail": "msg"}
    """
    if not raw:
        return raw
    # 尝试提取 JSON detail
    json_match = re.search(r'\{.*"detail"\s*:\s*"([^"]+)".*\}', raw, re.DOTALL)
    if json_match:
        return json_match.group(1)
    # 尝试提取 "API error N: msg"
    api_msg_match = re.search(r"API error \d+: (.+)", raw)
    if api_msg_match:
        return api_msg_match.group(1).strip()
    # 尝试提取 "Client error N for METHOD path: body"
    client_msg_match = re.search(r"Client error \d+ for [A-Z]+ [^:]+:\s*(.+)", raw)
    if client_msg_match:
        body = client_msg_match.group(1).strip()
        if body.startswith("{"):
            try:
                parsed = json.loads(body)
                if isinstance(parsed, dict):
                    if "detail" in parsed:
                        detail = parsed["detail"]
                        return (
                            "; ".join(str(e) for e in detail)
                            if isinstance(detail, list)
                            else str(detail)
                        )
                    for key in ("message", "error", "msg"):
                        if key in parsed:
                            return str(parsed[key])
            except (json.JSONDecodeError, ValueError):
                pass
        return body
    return raw


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
    changed_files: Optional[Dict[str, Any]] = None


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
        # 耗时改为消息驱动，不再使用定时器
        self._change_timer = None  # asyncio.TimerHandle: throttle _notify_change
        self._on_get_agent_name: Optional[Callable[[str], Optional[str]]] = None

        # Track last message_id that had content per turn (for agent_response separator logic)
        self._turn_content_msg_id: Dict[str, str] = {}

        # Track seen tool_call_ids per turn (dedup: backend sends preview→actual→result for same call)
        self._turn_seen_tool_call_ids: Dict[str, Set[str]] = {}

        # Track last response message_id per turn (for reasoning delimiting and undo targeting)
        self._turn_last_response_msg_id: Dict[str, str] = {}

        # 乐观更新：发送用户消息时预创建的 turn 信息（turn_start 到达后替换 turn_id）
        self._pending_turn_id: Optional[str] = None

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
        self._on_info: Optional[Callable[[str], None]] = None
        self._on_permission: Optional[Callable[[Dict[str, Any]], None]] = None
        self._on_agent_query: Optional[Callable[[Dict[str, Any]], None]] = None
        self._on_message: Optional[Callable[[Dict[str, Any]], None]] = None
        self._on_connection_change: Optional[Callable[[bool], None]] = None
        self._on_dismiss_dialogs: Optional[Callable[[], None]] = None

    def on_change(self, callback: Callable[[], None]):
        """Register callback for general state changes."""
        self._on_change = callback

    def on_error(self, callback: Callable[[str], None]):
        """Register callback for errors."""
        self._on_error = callback

    def on_info(self, callback: Callable[[str], None]):
        """Register callback for info/success notifications."""
        self._on_info = callback

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

    def on_dismiss_dialogs(self, callback: Callable[[], None]):
        """Register callback to dismiss active dialogs when new task messages arrive."""
        self._on_dismiss_dialogs = callback

    def on_get_agent_name(self, callback: Callable[[str], Optional[str]]):
        """Register callback to get agent display name by ID."""
        self._on_get_agent_name = callback

    def _notify_change(self, force: bool = False):
        """Notify UI of state change, throttled.

        流式 streaming 场景下每秒可能收到 10+ 个 agent_response 事件，
        每个都触发全量 _render_turn_cards 会导致页面卡死。
        使用 80ms throttle 合并短时间内的连续更新。

        Args:
            force: 如果为 True，立即触发更新（用于 turn_start/turn_end 等关键事件）
        """
        if force:
            # 立即触发并取消待处理的节流更新
            if self._change_timer is not None:
                self._change_timer.cancel()
                self._change_timer = None
            if self._on_change:
                self._on_change()
            return

        # 节流：80ms 内多次调用只触发一次
        if self._change_timer is not None:
            return  # 已有待处理的更新
        import asyncio

        self._change_timer = asyncio.get_event_loop().call_later(
            0.15, self._flush_change
        )

    def _flush_change(self):
        """Flush throttled change notification."""
        self._change_timer = None
        if self._on_change:
            self._on_change()

    def _notify_error(self, message: str):
        """Notify UI of error, with JSON cleaned from message."""
        if self._on_error:
            self._on_error(_clean_error_message(message))

    def _notify_info(self, message: str):
        """Notify UI with info/success message."""
        if self._on_info:
            self._on_info(message)

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

            # 订阅由 @self._socket.on("connect") 的 handle_connect 自动完成
            # （包含首次连接和断线重连两种场景，避免重复订阅）

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
            # 简洁模式：创建 TurnSummary
            turn_id = message.data.get("turn_id") if message.data else None
            if turn_id:
                target_id = message.sender_id or message.agent_id
                # 乐观更新：如果有预创建的 pending turn，替换 turn_id 而非新建
                if self._pending_turn_id:
                    pending = self._find_turn(self._pending_turn_id)
                    if pending:
                        pending.turn_id = turn_id
                        self._pending_turn_id = None
                        self._notify_change(force=True)
                        return
                    self._pending_turn_id = None

                agent_name = target_id or ""
                if self._on_get_agent_name:
                    agent_name = self._on_get_agent_name(target_id) or agent_name
                self.create_turn_summary(turn_id, target_id or "", agent_name)

        @self._socket.on("turn_end")
        async def handle_turn_end(message: Message):
            # 简洁模式：终结 TurnSummary
            turn_id = message.data.get("turn_id") if message.data else None
            if turn_id:
                status = message.data.get("status") if message.data else None
                changed_files = (
                    message.data.get("changed_files") if message.data else None
                )
                self.finalize_turn_summary(
                    turn_id,
                    status,
                    turn_end_msg_id=message.message_id,
                    changed_files=changed_files,
                )

        @self._socket.on("permission_request")
        async def handle_permission(message: Message):
            self.permission_dialog["visible"] = True
            self.permission_dialog["request_id"] = message.data.get("request_id")
            self.permission_dialog["sender_id"] = message.sender_id
            self.permission_dialog["message"] = message.data.get("message", "")
            self.permission_dialog["request_type"] = message.data.get(
                "request_type", "general"
            )
            if self._on_permission:
                self._on_permission(self.permission_dialog)

        @self._socket.on("agent_query")
        async def handle_agent_query(message: Message):
            self.agent_query_dialog["visible"] = True
            self.agent_query_dialog["request_id"] = message.data.get("request_id")
            self.agent_query_dialog["sender_id"] = message.sender_id
            self.agent_query_dialog["question"] = message.data.get(
                "question"
            ) or message.data.get("content", "")
            self.agent_query_dialog["options"] = message.data.get("options", [])
            if self._on_agent_query:
                self._on_agent_query(self.agent_query_dialog)

        @self._socket.on("connect")
        async def handle_connect():
            self.connected = True
            self._notify_change()
            if self._on_connection_change:
                self._on_connection_change(True)
            # 订阅 session 频道（首次连接和断线重连均走此路径）。
            # 服务端在 disconnect 时会清除客户端的订阅状态，
            # 因此 Socket.IO 连接后必须显式订阅，否则服务端无法将消息推送回来。
            # 注意：connect() 方法不再额外调用 subscribe，避免重复订阅。
            if self.session_id and self._socket:
                try:
                    await self._socket.subscribe(self.session_id)
                    log(f"已订阅 session {self.session_id}")
                except Exception as e:
                    log(f"订阅 session {self.session_id} 失败: {e}")

        @self._socket.on("disconnect")
        async def handle_disconnect():
            self.connected = False
            self._notify_change()
            if self._on_connection_change:
                self._on_connection_change(False)

        @self._socket.on("error")
        async def handle_error(data):
            """Handle error messages from server."""
            try:
                if isinstance(data, str):
                    msg = data
                elif hasattr(data, "data") and isinstance(data.data, dict):
                    # Message object: 取 content 或 message 字段
                    msg = (
                        data.data.get("content")
                        or data.data.get("message")
                        or str(data.data)
                    )
                elif isinstance(data, dict):
                    msg = data.get("content", data.get("message", str(data)))
                else:
                    msg = str(data)
                if msg:
                    self._notify_error(msg)
            except Exception:
                pass

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
            # 跳过空响应的 chunk（content + reasoning 皆空，对齐 Web 行为）
            raw_content = msg_dict.get("data", {}).get("content", "")
            if isinstance(raw_content, str) and raw_content.strip():
                try:
                    parsed = json.loads(raw_content)
                    if isinstance(parsed, dict):
                        has_content = bool(parsed.get("content")) or bool(
                            parsed.get("reasoning_content")
                        )
                        if not has_content:
                            return  # 跳过空响应
                except (json.JSONDecodeError, TypeError):
                    pass  # 非 JSON 内容，继续处理

            turn_id = msg_dict.get("turn_id", "")
            if turn_id:
                message_id = msg_dict.get("message_id", "")
                self.update_turn_on_agent_response(
                    turn_id, msg_dict.get("data", {}), message_id
                )

        # Notify agent status: tool_call / agent_response → agent is active (running)
        if msg_type in ("tool_call", "agent_response"):
            # 先从消息中取 sender_id 或 data.agent_id，若没有则从 turn 查
            agent_id = msg_dict.get("sender_id", "") or msg_dict.get("data", {}).get(
                "agent_id", ""
            )
            if not agent_id and turn_id:
                turn = self._find_turn(turn_id)
                if turn:
                    agent_id = turn.agent_id
            if agent_id and self._on_message:
                self._on_message({"type": "agent_active", "agent_id": agent_id})
            # 收到 agent 任务进展时自动关闭对话框（对齐 Web 行为）
            self.permission_dialog["visible"] = False
            self.agent_query_dialog["visible"] = False
            if self._on_dismiss_dialogs:
                self._on_dismiss_dialogs()

        # Agent status: turn_start / turn_end 也在 message 事件中处理（对齐 Web 版单一路径）
        # 避免与 @self._socket.on("turn_start") / @self._socket.on("turn_end") 双路径竞争
        if msg_type == "turn_start":
            agent_id = msg_dict.get("sender_id", "") or msg_dict.get("agent_id", "")
            if agent_id and self._on_message:
                self._on_message({"type": "turn_start", "agent_id": agent_id})
        elif msg_type == "turn_end":
            agent_id = msg_dict.get("sender_id", "") or msg_dict.get("agent_id", "")
            if agent_id and self._on_message:
                self._on_message({"type": "turn_end", "agent_id": agent_id})

        # ── 简洁模式：user_message 更新 turn 的用户消息 ──
        if msg_type == "user_message":
            # 跳过来自 agent 的用户消息（agent 转发/回显的消息，对齐 Web 行为）
            if msg_dict.get("data", {}).get("from_agent"):
                return
            turn_id = msg_dict.get("turn_id", "") or msg_dict.get("data", {}).get(
                "turn_id", ""
            )
            if turn_id:
                turn = self._find_turn(turn_id)
                if turn and not turn.user_message:
                    data = msg_dict.get("data", {})
                    # 优先使用 raw_input（对齐 Web ChatMessageItem 明细模式行为）
                    if data.get("raw_input") is not None:
                        turn.user_message = str(data.get("raw_input", ""))
                    else:
                        # data.content 是 json.dumps({"content": "用户消息", ...})
                        raw = data.get("content", "")
                        if raw:
                            try:
                                parsed = json.loads(raw)
                                if isinstance(parsed, dict):
                                    turn.user_message = parsed.get(
                                        "content", str(parsed)
                                    )
                                else:
                                    turn.user_message = str(parsed)
                            except (json.JSONDecodeError, TypeError):
                                turn.user_message = str(raw)
                    if turn.user_message:
                        self._notify_change()
                # 记录最后一条消息 ID（用于撤销定位）
                msg_id = msg_dict.get("message_id", "")
                if msg_id:
                    self._turn_last_response_msg_id[turn_id] = msg_id

        # Skip filtered message types
        filtered_types = {
            "turn_start",
            "turn_end",
            "command",
            "permission_request",
            "permission_response",
            "agent_query",
            "user_answer",
            "subscribe",
            "unsubscribe",
            "connect",
            "disconnect",
            "ping",
            "pong",
            "task_start",
            "task_complete",
            "task_error",
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

                    asyncio.ensure_future(
                        self.load_turn_history(filter_execution_id=self.execution_id)
                    )
                return
            elif command == "clear_context":
                self._notify_info("上下文已清空")
                return
            elif command == "clear_history":
                self._notify_info("历史记录已清空")
                import asyncio
                asyncio.ensure_future(
                    self.load_turn_history(filter_execution_id=self.execution_id)
                )
                return

        # Clear redo state on new messages (undo result is command_result, so it won't be cleared)
        if msg_dict.get("message_type") != "command_result":
            self.show_redo_button = False
            self.redo_receiver_id = None

        # 跳过连接相关的系统消息（对齐 Web 行为）
        content_str = msg_dict.get("data", {}).get("content", "")
        if isinstance(content_str, str):
            content_lower = content_str.lower()
            if "connected to" in content_lower or "subscribed to" in content_lower:
                return

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

    async def load_turn_history(
        self, is_load_more: bool = False, filter_execution_id: Optional[str] = None
    ):
        """加载 turn 历史（简洁模式）。

        Args:
            is_load_more: 是否加载更多（滚动到顶部触发）
            filter_execution_id: 可选，按编排执行 ID 过滤
        """
        if not self.session_id:
            log("load_turn_history: no session_id")
            return

        log(
            f" load_turn_history: is_load_more={is_load_more}, loading_more_turns={self.loading_more_turns}, has_more_turns={self.has_more_turns}, skip={self.turn_history_skip}"
        )

        if is_load_more:
            if self.loading_more_turns or not self.has_more_turns:
                log(
                    f" load_turn_history: early return (loading_more={self.loading_more_turns}, has_more={self.has_more_turns})"
                )
                return
            self.loading_more_turns = True
            self.loading = True  # 确保 loading 状态同步到 MessageList
        else:
            self.loading = True
            self.turn_history_skip = 0
            self.has_more_turns = True

        self._notify_change()

        limit = 3
        exec_id = filter_execution_id or self.execution_id

        try:
            result = await self._api.get_session_turns(
                self.session_id,
                skip=self.turn_history_skip,
                limit=limit,
                execution_id=exec_id,
            )

            total = result.get("total", 0)
            raw_turns = result.get("turns", [])

            log(
                f" load_turn_history: API returned total={total}, turns_count={len(raw_turns)}, skip={self.turn_history_skip}"
            )

            # 将后端数据映射为 TurnSummary
            new_turns = []
            for t in raw_turns:
                # 过滤已撤销的 turn
                if t.get("is_reverted", False):
                    continue

                # 解析 started_at（API 返回 ISO 格式字符串，转为 ms 时间戳）
                started_at_raw = t.get("started_at")
                started_at_ms = 0
                if started_at_raw:
                    try:
                        import datetime as _dt

                        # 统一按 UTC 解析，避免本地时区偏移
                        d = _dt.datetime.fromisoformat(
                            started_at_raw.replace("Z", "+00:00")
                        )
                        if d.tzinfo is None:
                            d = d.replace(tzinfo=_dt.timezone.utc)
                        started_at_ms = d.timestamp() * 1000
                    except Exception:
                        pass

                # 判断 turn 是否活跃：ended_at 为 null 表示 turn 仍在进行中
                # 后端 status 字段只有 turn_end 时才会被设为 'completed'/'error'，
                # 未结束的 turn 该字段为 None（被后端映射为 'completed'），
                # 故不能仅依赖后端 status 字段判断活跃状态。
                ended_at = t.get("ended_at")
                is_active_turn = not bool(ended_at)
                raw_status = t.get("status", "completed")
                if raw_status == "error":
                    status = "error"
                elif is_active_turn:
                    status = "active"
                else:
                    status = "completed"

                summary = TurnSummary(
                    turn_id=t.get("turn_id", ""),
                    sequence_number=t.get("sequence_number", 0),
                    agent_id=t.get("agent_id", ""),
                    agent_name=t.get("agent_name", ""),
                    user_message=t.get("user_message"),
                    status=status,
                    current_tool=t.get("current_tool"),
                    current_file_path=t.get("current_file_path"),
                    current_todo_list=t.get("current_todo_list", []),
                    total_duration=t.get("duration_seconds", 0) or 0.0,
                    total_steps=t.get("total_steps", 0),
                    tool_call_stats=t.get("tool_call_stats", []),
                    final_response=t.get("final_response", ""),
                    is_active=is_active_turn,
                    started_at=started_at_ms,
                    created_at=t.get("created_at", ""),
                    last_message_id=t.get("last_message_id"),
                    changed_files=t.get("changed_files"),
                )
                new_turns.append(summary)

            if is_load_more:
                self.turn_summaries = new_turns + self.turn_summaries
            else:
                self.turn_summaries = new_turns
                # undo 重载完成后，允许后续新消息清除 redo 按钮
                self._preserve_redo = False

            self.turn_history_skip += limit
            self.has_more_turns = self.turn_history_skip < total

            log(
                f" load_turn_history: done, turn_summaries count={len(self.turn_summaries)}, has_more_turns={self.has_more_turns}, loading={self.loading}"
            )

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

        # 轮次序号 = 已有最大序号 + 1（对齐 Web 版）
        max_seq = max((t.sequence_number for t in self.turn_summaries), default=0)
        summary = TurnSummary(
            turn_id=turn_id,
            sequence_number=max_seq + 1,
            agent_id=agent_id,
            agent_name=agent_name,
            is_active=True,
            status="active",
            started_at=time.time() * 1000,
            created_at=datetime.now().isoformat(),
        )
        self.turn_summaries.append(summary)
        self.active_turn_index = len(self.turn_summaries) - 1
        # 不再启动 1s 定时器更新耗时，改为消息驱动（tool_call/agent_response/step_start 时计算）
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

        # 更新当前工具（仅第一次更新：同 tool_call_id 会收到 preview→actual→result 三次）
        tool_call_id = data.get("tool_call_id", "")
        is_first_seen = True
        if tool_call_id:
            seen_ids = self._turn_seen_tool_call_ids.get(turn_id, set())
            if tool_call_id in seen_ids:
                is_first_seen = False
            else:
                seen_ids.add(tool_call_id)
                self._turn_seen_tool_call_ids[turn_id] = seen_ids

        if is_first_seen:
            turn.current_tool = tool_name
            # 更新工具调用统计
            found = False
            for stat in turn.tool_call_stats:
                if stat.get("tool_name") == tool_name:
                    stat["count"] = stat.get("count", 0) + 1
                    found = True
                    break
            if not found:
                turn.tool_call_stats.append({"tool_name": tool_name, "count": 1})

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

    def update_turn_on_agent_response(
        self, turn_id: str, data: Dict[str, Any], message_id: str = ""
    ):
        """Agent 回复消息到达时累加 finalResponse。

        同一 message_id 的 streaming chunks 连续拼接（同一 LLM 调用的输出流片段），
        不同 message_id（不同 LLM 调用）之间加空行分隔，对齐 Web ChatStore 行为。

        注意：对齐 Web 行为，不清除 current_tool / current_file_path / current_todo_list。
        TurnCard 的 compose 已通过 status 和字段值的组合条件控制显隐：
        - "当前调用"区域：由 current_tool and status != "completed" 控制
        - 推理区域：由 reasoning_content and (completed or not current_tool) 控制
        - TODO 列表：由 current_todo_list 有值控制

        Args:
            turn_id: Turn ID
            data: agent_response 消息的 data 字段
            message_id: 消息 ID，用于判断是否属于同一 LLM 调用
        """
        turn = self._find_turn(turn_id)
        if not turn:
            return

        # 对齐 Web 行为：不主动清除工具调用状态（current_tool/current_file_path/current_todo_list），
        # TurnCard 的 compose 通过 status + 字段值组合条件控制各区域显隐。

        content_str = data.get("content", "")
        if isinstance(content_str, str) and content_str.strip():
            try:
                parsed = json.loads(content_str)
                if isinstance(parsed, dict):
                    content = parsed.get("content", "")
                    reasoning = parsed.get("reasoning_content", "")

                    # Determine if this is a new LLM call (different message_id)
                    last_msg_id = self._turn_last_response_msg_id.get(turn_id, "")
                    is_new_response = last_msg_id != message_id

                    if content:
                        # 同一消息流拼接，新消息流替换（与 reasoning_content 逻辑一致）
                        prev_msg_id = self._turn_content_msg_id.get(turn_id, "")
                        is_new_message = prev_msg_id != message_id
                        if is_new_message:
                            turn.final_response = content  # 新消息流，替换
                        else:
                            turn.final_response += content  # 同一消息流，拼接
                        if message_id:
                            self._turn_content_msg_id[turn_id] = message_id

                    if reasoning:
                        if is_new_response:
                            turn.reasoning_content = reasoning  # 新 LLM 调用，重新开始
                        else:
                            turn.reasoning_content += (
                                reasoning  # 同调用流，连续拼接无分隔符
                            )

                    # 收到回复内容 → 思考阶段已结束，清空 reasoningContent
                    if content and turn.reasoning_content:
                        turn.reasoning_content = ""

                    if message_id:
                        self._turn_last_response_msg_id[turn_id] = message_id
                else:
                    prev_msg_id = self._turn_content_msg_id.get(turn_id, "")
                    is_new_message = prev_msg_id != message_id
                    if is_new_message:
                        turn.final_response = content_str  # 新消息流，替换
                    else:
                        turn.final_response += content_str  # 同一消息流，拼接
                    if message_id:
                        self._turn_content_msg_id[turn_id] = message_id
                        self._turn_last_response_msg_id[turn_id] = message_id
            except (json.JSONDecodeError, TypeError):
                prev_msg_id = self._turn_content_msg_id.get(turn_id, "")
                is_new_message = prev_msg_id != message_id
                if is_new_message:
                    turn.final_response = content_str  # 新消息流，替换
                else:
                    turn.final_response += content_str  # 同一消息流，拼接
                if message_id:
                    self._turn_content_msg_id[turn_id] = message_id
                    self._turn_last_response_msg_id[turn_id] = message_id

        turn.status = "thinking"
        self._notify_change()

    def finalize_turn_summary(
        self,
        turn_id: str,
        status: Optional[str] = None,
        turn_end_msg_id: Optional[str] = None,
        changed_files: Optional[Dict[str, Any]] = None,
    ):
        """终结 TurnSummary（turn_end 事件触发）。

        Args:
            turn_id: Turn ID
            status: turn_end 消息的 status 值（"completed"/"error"/"aborted"）
            turn_end_msg_id: turn_end 消息自身的 ID（中止时最后的响应消息已被删，用它做撤销定位）
            changed_files: 文件变更摘要字典
        """
        turn = self._find_turn(turn_id)
        if not turn:
            return

        turn.is_active = False
        is_error = status in ("error", "aborted") if status else False
        turn.status = "error" if is_error else "completed"
        turn.total_duration = (time.time() * 1000 - turn.started_at) / 1000

        # 保存文件变更信息
        if changed_files:
            turn.changed_files = changed_files

        # 保存 turn_end 消息 ID 用于撤销定位（始终安全，后端可能已删除最后响应消息）
        if turn_end_msg_id:
            turn.last_message_id = turn_end_msg_id
        if turn_id in self._turn_content_msg_id:
            del self._turn_content_msg_id[turn_id]
        if turn_id in self._turn_last_response_msg_id:
            del self._turn_last_response_msg_id[turn_id]
        if turn_id in self._turn_seen_tool_call_ids:
            del self._turn_seen_tool_call_ids[turn_id]

        # 终结活跃 turn
        if self.active_turn_index >= 0:
            turn_at_index = self.turn_summaries[self.active_turn_index]
            if turn_at_index.turn_id == turn_id:
                self.active_turn_index = -1

        # 触发 UI 更新（_process_incoming_message 跳过了 turn_end 类型，需手动通知）
        self._notify_change()

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

    def _stop_change_timer(self):
        """停止变更节流定时器。"""
        if self._change_timer is not None:
            try:
                self._change_timer.cancel()
            except Exception:
                pass
            self._change_timer = None

    # ==================== Filtered Turns (简洁模式) ====================

    def get_filtered_turns(
        self, visible_agent_ids: List[str], all_agent_ids: List[str]
    ) -> List[TurnSummary]:
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

        # 乐观更新：立即创建 TurnSummary（使用临时 turn_id），不等 turn_start
        agent_id = target_agent_id or ""
        agent_name = agent_id
        if agent_id and self._on_get_agent_name:
            agent_name = self._on_get_agent_name(agent_id) or agent_id
        temp_id = f"_pending_{int(time.time() * 1000)}"
        self._pending_turn_id = temp_id
        self.create_turn_summary(temp_id, agent_id, agent_name)
        # 预填用户消息
        turn = self._find_turn(temp_id)
        if turn:
            turn.user_message = content.strip()
        self._notify_change(force=True)

        try:
            await self._socket.send_user_message(
                content=content,
                receiver_id=target_agent_id,
                subscription=self.session_id,
            )
        except Exception as e:
            self._notify_error(f"发送消息失败: {e}")
            # 发送失败，移除预创建的 turn
            self.turn_summaries = [
                t for t in self.turn_summaries if t.turn_id != temp_id
            ]
            self._pending_turn_id = None
            self._notify_change(force=True)

    async def send_abort(self, agent_id: Optional[str] = None):
        """Send abort command to an agent.

        Args:
            agent_id: Agent ID to abort. If None, aborts current agent.
        """
        if not self._socket:
            return
        try:
            await self._socket.send_command(
                command="abort", arguments={}, receiver_id=agent_id
            )
        except Exception as e:
            self._notify_error(f"中止失败: {e}")

    async def send_undo(
        self,
        target_message_id: str,
        target_agent_id: Optional[str] = None,
        level: str = "step",
    ):
        """Send undo command (matching Web's sendUndo command).

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
                receiver_id=target_agent_id,
            )
        except Exception as e:
            self._notify_error(f"撤销失败: {e}")

    async def send_redo(self, target_agent_id: Optional[str] = None):
        """Send redo command (matching Web's sendRedo command).

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
                receiver_id=target_agent_id,
            )
        except Exception as e:
            self._notify_error(f"重做失败: {e}")

    async def respond_permission(
        self, granted: bool, session_action: Optional[str] = None
    ):
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
            )
        except Exception as e:
            self._notify_error(f"权限响应失败: {e}")
        finally:
            dialog["visible"] = False
            self._notify_change()

    async def respond_user_answer(self, answer: str):
        """Respond to an agent query (Web alignment: sendUserAnswer).

        Args:
            answer: User's answer text
        """
        if not self._socket:
            return

        dialog = self.agent_query_dialog
        target_agent_id = dialog.get("sender_id") or ""
        try:
            await self._socket.send_user_answer(
                answer=answer,
                request_id=dialog["request_id"],
                receiver_id=target_agent_id,
            )
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
        self._stop_change_timer()
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
