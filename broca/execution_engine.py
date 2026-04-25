"""
Execution Engine Module

This module handles the execution logic for agents, including:
- LLM calls and response processing
- Tool execution and management
- Execution flow control
- Error handling for execution steps
- Complete execution lifecycle management
- Execution status and result definitions
"""

import asyncio
import json
import uuid
from enum import Enum
from typing import Any, Dict, List, Optional

from litellm import Message as LLMMessage

from broca.context import Context
from broca.error_handler import AgentError, ErrorHandler, ErrorType
from broca.llm import LLMClient
from broca.logging_config import get_logger
from broca.session import (
    Message,
    MessageProtocol,
    MessageRole,
    MessageType,
    SessionManager,
    generate_message_id,
)
from broca.snapshot.patch import PatchCalculator
from broca.snapshot.track import SnapshotTracker
from broca.tools.tool import ToolCallContext, ToolResult, ToolStatus

logger = get_logger(__name__)


class ExecutionStatus(str, Enum):
    """Agent execution status enumeration"""

    RUNNING = "running"
    PENDING = "pending"
    COMPLETED = "completed"
    ERROR = "error"
    ABORTED = "aborted"
    SKIPPED = "skipped"
    LIMIT_EXCEEDED = "limit_exceeded"


class ExecutionResult:
    """Result of agent execution"""

    def __init__(
        self,
        status: ExecutionStatus,
        message: Optional[str] = None,
        data: Optional[Dict[str, Any]] = None,
        error: Optional[str] = None,
    ):
        self.status = status
        self.message = message
        self.data = data or {}
        self.error = error

    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary"""
        return {
            "status": self.status,
            "message": self.message,
            "data": self.data,
            "error": self.error,
        }

    def __str__(self) -> str:
        return f"ExecutionResult(status={self.status}, message={self.message})"


class ExecutionEngine:
    """
    Execution Engine for agent operations

    Handles the core execution logic including LLM calls, tool execution,
    and step management. Separated from agent.py to reduce complexity.
    """

    def __init__(
        self,
        agent: Any,
        llm_client: LLMClient,
        context: Context,
        tool_mapping: Dict[str, Any],
        config: Any,
        communicator: Any,
        session_manager: SessionManager,
        session_memory_manager: Any = None,
        step_max_errors=3,
        llm_retry_delay=10,
        tool_call_timeout=600,
        assign_task_timeout=1800,
    ):
        """
        Initialize the execution engine

        Args:
            agent: Reference to the parent agent
            llm_client: LLM client for making API calls
            context: Agent context for history management
            tool_mapping: Mapping of tool names to tool instances
            config: Agent configuration
            communicator: Communication interface for sending messages
            session_manager: Session manager for persistence
        """
        self.agent = agent
        self.llm_client = llm_client
        self.context = context
        self.tool_mapping = tool_mapping
        self.config = config
        self.communicator = communicator
        self.session_manager = session_manager
        self.session_memory_manager = session_memory_manager

        self.error_handler = ErrorHandler(
            session_manager=session_manager, turn_id=None, agent_id=None
        )

        self.abort_event = asyncio.Event()

        self.agent_id = agent.agent_id
        self.session_id = session_manager.session_id
        self.turn_id: str | None = None
        self.step_id: str | None = None

        self.step_max_errors = step_max_errors
        self.llm_retry_delay = llm_retry_delay
        self.tool_call_timeout = tool_call_timeout
        self.assign_task_timeout = assign_task_timeout

        # 快照跟踪
        self.snapshot_tracker: Optional[SnapshotTracker] = None
        self.patch_calculator: Optional[PatchCalculator] = None
        self.current_snapshot_hash: Optional[str] = None

        # Step跟踪
        self._step_has_write_operations: bool = False

        # 只读tool列表
        self._readonly_tools = {
            "read_file",
            "glob",
            "grep",
            "list_dir",
            "tree_dir",
            "web_fetch",
            "web_search",
            "ask_user",
            "task_management",
            "todo_management",
            "cron",
        }

    def _initialize_snapshot_tracking(self):
        """初始化快照跟踪"""
        if self.config and hasattr(self.config, "workspace") and self.config.workspace:
            self.snapshot_tracker = SnapshotTracker(self.config.workspace)
            self.patch_calculator = PatchCalculator(self.config.workspace)

    def _generate_step_id(self) -> str:
        """生成Step ID"""
        return f"step-{uuid.uuid4().hex[:8]}"

    async def _capture_step_init(self):
        # 检查是否需要快照（如果所有tool都是只读的，可以跳过）
        self._step_has_write_operations = False

    async def _capture_step_start(self) -> bool:
        """捕获Step开始快照"""
        if not self.snapshot_tracker or not self.step_id:
            return False

        try:
            if self._step_has_write_operations:
                snapshot_hash = await self.snapshot_tracker.track()
                self.current_snapshot_hash = snapshot_hash
            else:
                snapshot_hash = ""

            # 创建STEP_START消息
            step_start_msg = MessageProtocol.create_step_start(
                step_id=self.step_id, snapshot_hash=snapshot_hash
            )
            step_start_msg.session_id = self.session_id
            step_start_msg.turn_id = self.turn_id
            step_start_msg.agent_id = self.agent_id

            # 保存消息
            return await self.session_manager.save_message(
                role=step_start_msg.role,
                content=None,
                message_type=step_start_msg.message_type,
                turn_id=self.turn_id,
                agent_id=self.agent_id,
                data=step_start_msg.data,
            )
        except Exception as e:
            logger.error(f"Error capturing step start: {e}")
            return False

    async def _capture_step_end(self) -> bool:
        """捕获Step结束快照和patch"""
        if not self.snapshot_tracker or not self.patch_calculator or not self.step_id:
            return False

        if not self.current_snapshot_hash:
            # 如果没有起始快照，跳过
            return False

        # 检查是否需要快照（如果没有写操作，跳过）
        if not self._step_has_write_operations:
            logger.debug(
                f"Step {self.step_id} has no write operations, skipping snapshot"
            )
            return False

        try:
            # 捕获结束快照
            end_snapshot_hash = await self.snapshot_tracker.track()

            # 计算patch
            patch = await self.patch_calculator.calculate_patch(
                self.current_snapshot_hash, end_snapshot_hash
            )
            if not patch.get("files"):
                patch = {}

            # 创建STEP_END消息
            step_end_msg = MessageProtocol.create_step_end(
                step_id=self.step_id, snapshot_hash=end_snapshot_hash, patch=patch
            )
            step_end_msg.session_id = self.session_id
            step_end_msg.turn_id = self.turn_id
            step_end_msg.agent_id = self.agent_id

            # 保存消息
            return await self.session_manager.save_message(
                role=step_end_msg.role,
                content=None,
                message_type=step_end_msg.message_type,
                turn_id=self.turn_id,
                agent_id=self.agent_id,
                data=step_end_msg.data,
            )
        except Exception as e:
            logger.error(f"Error capturing step end: {e}")
            return False

    async def execute_step(self) -> ExecutionStatus:
        """
        Execute one step of agent execution

        Returns:
            True if more steps are needed, False otherwise
        """
        # 初始化快照跟踪
        if not self.snapshot_tracker:
            self._initialize_snapshot_tracking()

        # 生成Step ID
        self.step_id = self._generate_step_id()

        self._capture_step_init()

        errors = 0

        while errors < self.step_max_errors:
            if self.abort_event.is_set():
                logger.info("Agent execution aborted during LLM call")
                return ExecutionStatus.ABORTED

            try:
                async with self.error_handler.handle_llm_call(context="execute_step"):
                    response = await asyncio.wait_for(
                        self._call_llm_streaming(), timeout=300
                    )
                    if not response:
                        raise AgentError(ErrorType.LLM_ERROR, "LLM call failed")
                    break
            except AgentError as e:
                errors += 1
                logger.error(f"LLM call failed with error: {e}")
                if errors == self.step_max_errors:
                    logger.error(f"Too many errors ({e.error_type}), aborting...")
                    return ExecutionStatus.ERROR
                if e.error_type == ErrorType.LLM_RATE_LIMIT_ERROR:
                    await asyncio.sleep(self.llm_retry_delay)
                if self.config.interactive:
                    await self.communicator.send_error(
                        "calling LLM failed, retrying...", subscription=self.session_id
                    )
            except asyncio.CancelledError:
                logger.info("Agent execution cancelled by user during LLM call")
                return ExecutionStatus.ABORTED

        if self.abort_event.is_set():
            logger.info("Agent execution aborted after tool calls")
            return ExecutionStatus.ABORTED

        if not response:
            return ExecutionStatus.ERROR

        self.check_step_has_write_operations(response.tool_calls)

        await self._capture_step_start()

        if not await self.session_manager.save_agent_response(
            response,
            self.turn_id,
            self.agent_id,
            self.step_id,
            message_id=response.message_id,
        ):
            logger.error("Failed to save agent response")
            return ExecutionStatus.ERROR

        await self.context.add_message(response)

        if not response.tool_calls:
            await self._capture_step_end()
            status = ExecutionStatus.COMPLETED
        else:
            await self._process_tool_calls(response.tool_calls)
            await self._capture_step_end()
            status = ExecutionStatus.RUNNING

        if self.session_memory_manager:
            self.session_memory_manager.increment_step()
            task = asyncio.create_task(
                self.session_memory_manager.check_and_extract(
                    context=self.context,
                )
            )
            task.add_done_callback(lambda t: t.exception() if not t.cancelled() else None)

        return status

    async def _call_llm_streaming(self) -> LLMMessage | None:
        """
        Call LLM with current context

        Returns:
            LLM response message
        """
        content_chunks = []
        tool_call_chunks = []
        sent = set()
        message_id = generate_message_id()
        index = 0
        async for chunk in self.llm_client.get_stream_response(
            self.config.provider,
            self.config.model,
            self.context.history,
            self._get_tools_list(),
        ):
            if self.abort_event.is_set():
                logger.info("Agent execution aborted during LLM call")
                raise asyncio.CancelledError("Execution aborted by user")

            if chunk["type"] in ["content", "reasoning_content"]:
                content_chunks.append(chunk)
                content = chunk["data"] if chunk["type"] == "content" else ""
                reasoning_content = (
                    chunk["data"] if chunk["type"] == "reasoning_content" else ""
                )
                if self.config.interactive:
                    await self.communicator.send_agent_response(
                        content=content,
                        reasoning_content=reasoning_content,
                        index=index,
                        message_id=message_id,
                        subscription=self.session_id,
                    )
                index += 1

            elif chunk["type"] == "tool_call":
                tool_call = chunk["data"]
                tool_call_chunks.append(tool_call)
                if (
                    hasattr(tool_call, "id")
                    and tool_call.id
                    and tool_call.id not in sent
                ):
                    tool_call_id = tool_call.id
                    if hasattr(tool_call, "function") and tool_call.function:
                        tool_name = tool_call.function.name
                        if self.config.interactive:
                            await self.communicator.send_tool_call(
                                tool_name=tool_name,
                                arguments=None,
                                tool_call_id=tool_call_id,
                                subscription=self.session_id,
                            )
                        sent.add(tool_call_id)

        input_tokens = self.llm_client.input_tokens_used
        output_tokens = self.llm_client.output_tokens_used
        await self.agent.on_llm_call_completed(input_tokens, output_tokens)

        message = self.llm_client.aggregate_message(content_chunks, tool_call_chunks)
        if message is not None:
            message.message_id = message_id
        return message

    def _get_tools_list(self) -> List[Dict[str, Any]]:
        """
        Get formatted tools list for LLM

        Returns:
            List of formatted tools
        """
        return [tool.format() for tool in self.tool_mapping.values()]

    async def _process_tool_calls(self, tool_calls: List[Any]):
        """
        Process tool calls from LLM response

        Args:
            tool_calls: List of tool calls from LLM
        """
        context = ToolCallContext()
        context.agent = self.agent
        context.workspace = self.config.workspace
        context.session_id = self.session_id

        for tool_call in tool_calls:
            if self.abort_event.is_set():
                logger.info("Agent execution aborted during tool call processing")
                return

            tool_name = tool_call.function.name
            arguments = tool_call.function.arguments
            if self.config.interactive:
                await self.communicator.send_tool_call(
                    tool_name=tool_name,
                    arguments=arguments,
                    tool_call_id=tool_call.id,
                    subscription=self.session_id,
                )

            if tool_name not in self.tool_mapping:
                logger.error(f"Tool '{tool_name}' not found.")
                tool_result = ToolResult(
                    status=ToolStatus.ERROR, content=f"Tool {tool_name} not found"
                )
            else:
                try:
                    async with self.error_handler.handle_tool_execution(
                        tool_name=tool_name, context="tool_call_processing"
                    ):
                        timeout = (
                            self.assign_task_timeout
                            if tool_name == "assign_task"
                            else self.tool_call_timeout
                        )
                        tool_result = await asyncio.wait_for(
                            self.tool_mapping[tool_name].execute(arguments, context),
                            timeout=timeout,
                        )
                except AgentError as e:
                    logger.error(
                        f"Tool execution failed with {e.error_type}: {e.message}"
                    )
                    tool_result = ToolResult(
                        status=ToolStatus.ERROR,
                        content=f"Tool {tool_name} execution failed: {e.message}",
                    )
                except asyncio.CancelledError:
                    logger.info("Tool execution cancelled by user")
                    raise

            if not await self.process_tool_call_result(tool_call, tool_result):
                raise Exception("Tool call result processing failed")

            tool_call_result = {
                "role": "tool",
                "tool_call_id": tool_call.id,
                "content": tool_result.content,
            }
            await self.context.add_message(tool_call_result)

    def check_step_has_write_operations(self, tool_calls: List[Any]):
        """
        Check if a step has write operations.

        This function checks if any of the tool calls in the step have write operations.
        If any tool call has write operations, the function sets `_step_has_write_operations` to `True`.

        Args:
            tool_calls (List[Any]): List of tool calls in the step

        Returns:
            None
        """
        if not tool_calls:
            return
        for tool_call in tool_calls:
            tool_name = tool_call.function.name
            if tool_name not in self._readonly_tools:
                self._step_has_write_operations = True
                break

    async def process_tool_call_result(
        self, tool_call: Any, tool_result: ToolResult
    ) -> bool:
        """
        Save tool execution result to database

        Args:
            tool_name: Name of the tool
            arguments: Tool arguments
            tool_call_id: Tool call ID
            tool_result: Tool execution result
            tool_call_result: Formatted tool call result
        """
        message_id = generate_message_id()
        if self.config.interactive:
            await self.communicator.send_tool_call(
                tool_name=tool_call.function.name,
                arguments=tool_call.function.arguments,
                tool_call_id=tool_call.id,
                result=tool_result.content,
                status=tool_result.status,
                subscription=self.session_id,
                message_id=message_id,
            )

        return await self.session_manager.save_tool_call(
            turn_id=self.turn_id,
            agent_id=self.agent_id,
            tool_call=tool_call,
            tool_result=tool_result,
            step_id=self.step_id,
            message_id=message_id,
        )

    async def execute_round(self, max_steps: Optional[int] = None) -> ExecutionResult:
        """
        Execute a complete round of agent execution

        Args:
            max_steps: Maximum number of steps
        """
        steps = 0

        while True:
            if self.abort_event.is_set():
                logger.info("Round aborted by user")
                raise asyncio.CancelledError("Execution aborted by user")

            try:
                async with self.error_handler.handle_execution_step(step_number=steps):
                    status = await self.execute_step()
                    steps += 1

                    if status == ExecutionStatus.COMPLETED:
                        return ExecutionResult(
                            status=ExecutionStatus.COMPLETED,
                            message=f"Round completed after {steps} steps",
                        )
                    elif status == ExecutionStatus.ABORTED:
                        return ExecutionResult(
                            status=ExecutionStatus.ABORTED,
                            message=f"Round aborted by user after {steps} steps",
                        )
                    elif status == ExecutionStatus.ERROR:
                        return ExecutionResult(
                            status=ExecutionStatus.ERROR,
                            message=f"Round failed after {steps} steps",
                        )
                    if max_steps is not None and steps >= max_steps:
                        return ExecutionResult(
                            status=ExecutionStatus.LIMIT_EXCEEDED,
                            message=f"Max steps ({max_steps}) reached",
                        )
            except AgentError as e:
                return ExecutionResult(
                    status=ExecutionStatus.ERROR,
                    message=f"Round failed with {e.error_type}: {e.message}",
                )
            except asyncio.CancelledError:
                return ExecutionResult(
                    status=ExecutionStatus.ABORTED,
                    message="Round aborted by user",
                )

    async def execute(
        self,
        message: Optional[Message],
        max_steps: Optional[int] = None,
        from_agent: Optional[bool] = False,
    ) -> ExecutionResult:
        """
        Execute agent with the given user message

        This is the main entry point for agent execution, handling:
        - Execution context setup
        - Round execution
        - Result packaging
        - Error handling

        Args:
            message: the message to process
            max_steps: Maximum number of execution steps

        Returns:
            ExecutionResult: Result of the execution
        """
        if not message:
            return ExecutionResult(status=ExecutionStatus.SKIPPED)

        self.abort_event.clear()

        if not await self._setup_execution_context(message, from_agent):
            return ExecutionResult(
                status=ExecutionStatus.ERROR,
                message="Error setting up execution context",
            )

        try:
            result = await self.execute_round(max_steps)
        except asyncio.CancelledError:
            logger.info("Execution cancelled by user")
            result = ExecutionResult(
                status=ExecutionStatus.ABORTED, message="Execution cancelled by user"
            )
        except Exception as e:
            logger.error(f"Error in execute: {e}")
            result = ExecutionResult(
                status=ExecutionStatus.ERROR, message=f"Error in execute: {e}"
            )

        if not await self.process_turn_end(result):
            logger.warning("Turn end processing failed")

        return result

    async def process_turn_end(self, result: ExecutionResult) -> bool:
        try:
            logger.info("turn ended with result: " + str(result))
            if self.config.interactive:
                await self.communicator.send_turn_end(
                    turn_id=self.turn_id, subscription=self.session_id
                )
            if result.status == ExecutionStatus.COMPLETED:
                message = "Turn completed successfully"
            elif result.status == ExecutionStatus.ABORTED:
                await self._truncate_last_assistant_message_with_tool_calls()
                message = "Turn aborted by user"
            elif result.status == ExecutionStatus.LIMIT_EXCEEDED:
                message = "Turn step limit exceeded"
            elif result.status == ExecutionStatus.ERROR:
                message = "Turn failed"
            elif result.status == ExecutionStatus.SKIPPED:
                message = "Turn skipped"
            else:
                message = "Turn failed"

            if result.status != ExecutionStatus.COMPLETED:
                if self.config.interactive:
                    await self.communicator.send_error(
                        message, subscription=self.session_id
                    )

            return await self.session_manager.save_turn_end(
                turn_id=self.turn_id, agent_id=self.agent_id, message=message
            )
        except Exception as e:
            logger.error(f"Error in process_turn_end: {e}")
            return False

    async def _setup_execution_context(
        self, message: Message, from_agent: Optional[bool] = False
    ) -> bool:
        """
        Set up execution context for a new turn

        Args:
            message: The message to process
        """
        user_message = self.llm_client.parse_message(
            provider=self.config.provider, model=self.config.model, message=message
        )
        if not user_message:
            return False

        try:
            await self._ensure_session()

            turn_id = await self.session_manager.start_turn(self.agent_id)
            if not turn_id:
                return False

            self.turn_id = turn_id
            self.agent.turn_id = turn_id
            self.error_handler.set_context(
                turn_id=turn_id,
                agent_id=self.agent_id,
                session_manager=self.session_manager,
            )

            message_content = user_message.get("content")
            if self.config.interactive:
                await self.communicator.send_turn_start(
                    turn_id=turn_id,
                    turn_description=f"Processing user message: {message_content}",
                    subscription=self.session_id,
                )

            message.data["from_agent"] = from_agent
            message_id = message.message_id if not from_agent else None
            if not await self.session_manager.save_message(
                role=MessageRole.USER,
                content=json.dumps(user_message, ensure_ascii=False),
                message_type=MessageType.USER_MESSAGE,
                turn_id=turn_id,
                agent_id=self.agent_id,
                data=message.data,
                message_id=message_id,
            ):
                return False

            await self.context.add_message(user_message)
            return True
        except Exception as e:
            logger.error(f"Error in _setup_execution_context: {e}")
            return False

    async def _ensure_session(self, workspace: str | None = None):
        """Ensure session exists, create if not"""
        if not self.session_id:
            if not self.session_manager.session_id:
                await self.session_manager.create_session(workspace=workspace)
            self.session_id = self.session_manager.session_id

    def abort(self):
        """
        Abort the execution

        This method sets the abort flag to stop execution
        """
        logger.info("Aborting execution engine")
        self.abort_event.set()

    def reset(self):
        """
        Reset execution state

        Clears abort state and resets execution flags
        """
        self.abort_event.clear()
        self.turn_id = None
        self.agent_id = None
        self.session_id = None

    async def _truncate_last_assistant_message_with_tool_calls(self):
        """
        Truncate the last assistant message with tool_calls from context and database.
        """
        if self.context:
            await self.context.truncate_last_assistant_message_with_tool_calls(
                session_manager=self.session_manager,
                turn_id=self.turn_id,
                agent_id=self.agent_id,
            )
