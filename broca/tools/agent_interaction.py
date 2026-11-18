import asyncio
import uuid
from typing import Dict, Optional

from broca.logging_config import get_logger
from broca.agent_messenger.messenger import AgentCommunicationError
from broca.session import Message, MessageRole, MessageType
from broca.tools.tool import Tool, ToolCallContext, ToolResult, ToolStatus

logger = get_logger(__name__)


class AskUserToolManager:
    _pending_requests: Dict[str, Dict] = {}
    _lock = asyncio.Lock()

    @classmethod
    async def handle_user_answer(cls, message: Message):
        request_id = message.data.get("request_id")
        if request_id and request_id in cls._pending_requests:
            async with cls._lock:
                request_data = cls._pending_requests[request_id]
                request_data["answer"] = message.data.get("answer")
                request_data["event"].set()
                logger.info(f"User answered question {request_id}")

    @classmethod
    async def clear_request(cls, request_id: str):
        async with cls._lock:
            cls._pending_requests.pop(request_id, None)


class AskUser(Tool):
    is_readonly = True
    @property
    def name(self):
        return "ask_user"

    @property
    def description(self):
        return (
            "Use this tool to ask the user a question. Always use this tool to clearify user's intent, "
            "collect user's feedback, provide proposals or suggestions(put your most recommended option first and mark it as recommended)."
        )

    @property
    def parameters(self):
        return {
            "type": "object",
            "properties": {
                "question": {
                    "type": "string",
                    "description": "the question to ask the user",
                },
                "options": {
                    "type": "array",
                    "items": {
                        "type": "object",
                        "properties": {
                            "name": {
                                "type": "string",
                                "description": "the name of the option",
                            },
                            "description": {
                                "type": "string",
                                "description": "the description of the option",
                            },
                        },
                        "required": ["name"],
                    },
                },
            },
            "required": ["question"],
        }

    async def _execute(self, arguments: dict, context: ToolCallContext) -> ToolResult:
        agent = context.agent
        session_id = context.session_id

        question = arguments.get("question", "")
        options = arguments.get("options", [])

        request_id = str(uuid.uuid4())
        response_event = asyncio.Event()

        async with AskUserToolManager._lock:
            AskUserToolManager._pending_requests[request_id] = {
                "event": response_event,
                "answer": None,
            }

        query_timeout = getattr(
            getattr(agent.config, "execution_config", None),
            "agent_query_timeout",
            300,
        )

        try:
            await self._send_agent_question(
                agent=agent,
                question=question,
                options=options,
                request_id=request_id,
                subscription=session_id,
                turn_id=context.turn_id,
                timeout=query_timeout,
            )

            await self._log_question(
                question=question, request_id=request_id, agent=agent, options=options
            )

            try:
                await asyncio.wait_for(response_event.wait(), timeout=query_timeout)
            except asyncio.TimeoutError:
                logger.warning(f"User question {request_id} timed out")
                return ToolResult(
                    status=ToolStatus.ERROR,
                    content="Question timed out. No answer received from user.",
                )

            async with AskUserToolManager._lock:
                answer = AskUserToolManager._pending_requests.get(request_id, {}).get(
                    "answer"
                )

            if answer:
                await self._log_answer(
                    answer=answer,
                    request_id=request_id,
                    agent=agent,
                    session_id=session_id,
                )
                return ToolResult(status=ToolStatus.SUCCESS, content=answer)
            else:
                return ToolResult(
                    status=ToolStatus.ERROR,
                    content="No answer received from user.",
                )

        except Exception as e:
            logger.error(f"Failed to send user question: {e}")
            return ToolResult(
                status=ToolStatus.ERROR,
                content=f"Failed to send question: {e}",
            )
        finally:
            await AskUserToolManager.clear_request(request_id)

    async def _send_agent_question(
        self,
        agent,
        question: str,
        options: list,
        request_id: str,
        subscription: Optional[str],
        turn_id: Optional[str] = None,
        timeout: Optional[int] = None,
    ):
        message_data = {
            "question": question,
            "options": options,
            "request_id": request_id,
            # 前端据此设置本地兜底定时器：即使漏收 request_resolved / turn_end，
            # 弹窗也会在服务端超时后自动关闭，避免永久悬挂。
            "timeout": timeout,
        }
        message = Message(
            message_type=MessageType.AGENT_QUERY,
            role=MessageRole.AGENT,
            sender_id=agent.agent_id,
            subscription=subscription,
            content=question,
            turn_id=turn_id if turn_id is not None else getattr(agent, "turn_id", None),
            data=message_data,
        )
        await agent.communicator.send_message(message)

    async def _log_question(
        self,
        question: str,
        request_id: str,
        agent,
        options: Optional[list],
    ):
        session_manager = getattr(agent, "session_manager", None)
        if session_manager:
            try:
                await session_manager.save_message(
                    role=MessageRole.AGENT,
                    content=question,
                    message_type=MessageType.AGENT_QUERY,
                    turn_id=getattr(agent, "turn_id", None),
                    agent_id=agent.agent_id,
                    data={"request_id": request_id, "options": options},
                )
            except Exception as e:
                logger.error(f"Failed to save question: {e}")

    async def _log_answer(
        self,
        answer: str,
        request_id: str,
        agent,
        session_id: Optional[str],
    ):
        session_manager = getattr(agent, "session_manager", None)
        if session_manager:
            try:
                await session_manager.save_message(
                    role=MessageRole.USER,
                    content=answer,
                    message_type=MessageType.USER_ANSWER,
                    turn_id=getattr(agent, "turn_id", None),
                    agent_id=agent.agent_id,
                    data={"request_id": request_id},
                )
            except Exception as e:
                logger.error(f"Failed to save answer: {e}")


class Communicate(Tool):
    """Send a message to another agent (request / notify / delegate)."""

    is_readonly = True

    @property
    def name(self):
        return "communicate"

    @property
    def description(self):
        return (
            "Send a message to another agent. "
            "mode='request': ask target to do something and BLOCK until it replies "
            "so you can continue immediately with the answer. "
            "mode='notify': inform target, no reply, returns immediately once delivered. "
            "mode='delegate': assign a pre-existing task (task_id required) to target。"
        )

    @property
    def parameters(self):
        return {
            "type": "object",
            "properties": {
                "target": {"type": "string", "description": "name of the target agent"},
                "mode": {
                    "type": "string",
                    "enum": ["request", "notify", "delegate"],
                },
                "message": {
                    "type": "string",
                    "description": "the message/task/question content",
                },
                "task_id": {
                    "type": "string",
                    "description": (
                        "REQUIRED when mode='delegate'; must be a pre-created task. "
                        "Ignored otherwise."
                    ),
                },
            },
            "required": ["target", "mode", "message"],
        }

    async def _execute(self, arguments, context: ToolCallContext) -> ToolResult:
        agent = context.agent
        messenger = agent.messenger
        if messenger is None:
            return ToolResult(
                status=ToolStatus.ERROR, content="AgentMessenger not initialized"
            )

        target = arguments["target"]
        mode = arguments["mode"]
        message = arguments["message"]
        task_id = arguments.get("task_id")

        try:
            if mode == "request":
                # Blocks until reply; map reply status to ToolResult so error/aborted
                # replies are not mistaken for SUCCESS.
                reply, reply_status = await messenger.request(target, message)
                tool_status = (
                    ToolStatus.SUCCESS
                    if reply_status == "success"
                    else ToolStatus.ERROR
                )
                status_tag = (
                    "" if reply_status == "success" else f" [status={reply_status}]"
                )
                return ToolResult(
                    status=tool_status,
                    content=f"[Reply from '{target}' {status_tag}]: {reply}",
                )
            elif mode == "notify":
                # notify waits for ACK internally; routing_failed raises → ERROR below.
                await messenger.notify(target, message)
                return ToolResult(
                    status=ToolStatus.SUCCESS,
                    content=f"Notification delivered to '{target}'.",
                )
            elif mode == "delegate":
                # delegate waits for ACK; routing_failed raises → ERROR (never a
                # false SUCCESS that leaves the task silently dangling).
                await messenger.delegate(target, task_id, message)
                return ToolResult(
                    status=ToolStatus.SUCCESS,
                    content=(
                        f"Task '{task_id}' delegated to '{target}' . "
                        f"Target will send a receipt asynchronously; monitor via "
                        f"task_management (action='get', task_id='{task_id}')."
                    ),
                )
            else:
                return ToolResult(
                    status=ToolStatus.ERROR, content=f"Unknown mode: {mode}"
                )
        except AgentCommunicationError as e:
            return ToolResult(
                status=ToolStatus.ERROR,
                content=str(e) + (f" (reason: {e.reason})" if e.reason else ""),
            )
