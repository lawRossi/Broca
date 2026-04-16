import asyncio
import uuid
from typing import Dict, Optional

from broca.execution_engine import ExecutionStatus
from broca.logging_config import get_logger
from broca.session import Message, MessageProtocol, MessageRole, MessageType
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


class AssignTask(Tool):
    @property
    def name(self):
        return "assign_task"

    @property
    def description(self):
        return "Use this tool to assign a task to an agent."

    @property
    def parameters(self):
        return {
            "type": "object",
            "properties": {
                "agent": {
                    "type": "string",
                    "description": "the agent to assign the task to",
                },
                "task_id": {
                    "type": "string",
                    "description": "the id of the task",
                },
                "task": {
                    "type": "string",
                    "description": "a self-explanatory description of the task",
                },
                "execution_type": {
                    "type": "string",
                    "description": "the execution type of the task",
                    "default": "blocking",
                    "enum": ["blocking", "background"],
                },
            },
            "required": ["agent", "task_id", "task"],
        }

    async def _execute(self, arguments, context: ToolCallContext) -> ToolResult:
        from broca.agent_manager import AgentFactory

        agent = context.agent
        factory = AgentFactory()
        agent_name = arguments["agent"]
        target_agent = factory.get_agent(agent.session_id, agent_name)
        if target_agent is None:
            return ToolResult(
                status=ToolStatus.ERROR, content=f"Agent {agent_name} not found"
            )

        agent_id = target_agent.agent_id
        task_id = arguments["task_id"]
        task = arguments["task"]
        execution_type = arguments.get("execution_type", "blocking")
        if execution_type == "blocking":
            trigger_message = MessageProtocol.create_user_message(content=task)
            execution_result = await target_agent.run(trigger_message, from_agent=True)
            message = target_agent.context.get_latest_assistant_message()
            if message:
                content = "Message from agent: " + message
            if execution_result.status == ExecutionStatus.COMPLETED:
                return ToolResult(status=ToolStatus.SUCCESS, content=content)
            elif execution_result.status == ExecutionStatus.ABORTED:
                return ToolResult(
                    status=ToolStatus.ERROR,
                    content=f"The agent {target_agent.agent_id} execution was aborted by user",
                )
            else:
                return ToolResult(
                    status=ToolStatus.ERROR,
                    content=f"The agent {target_agent.agent_id} failed to finish the task: {execution_result.error}",
                )
        else:
            await agent.communicator.send_task_start(
                task_id, task, receiver_id=agent_id
            )
            return ToolResult(
                status=ToolStatus.SUCCESS,
                content="The task has been assigned to the agent and you will be notified when it is completed.",
            )


class AskUser(Tool):
    @property
    def name(self):
        return "ask_user"

    @property
    def description(self):
        return (
            "Use this tool to ask the user a question. Always use this tool to clearify user's intent, "
            "collect user's feedback, provide proposals or suggestions."
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

        try:
            await self._send_agent_question(
                agent=agent,
                question=question,
                options=options,
                request_id=request_id,
                subscription=session_id,
            )

            await self._log_question(
                question=question, request_id=request_id, agent=agent, options=options
            )

            try:
                await asyncio.wait_for(response_event.wait(), timeout=300)
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
    ):
        message_data = {
            "question": question,
            "options": options,
            "request_id": request_id,
        }
        message = Message(
            message_type=MessageType.AGENT_QUERY,
            role=MessageRole.AGENT,
            sender_id=agent.agent_id,
            subscription=subscription,
            content=question,
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
