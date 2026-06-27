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
from broca.context_compressor import ContextCompressor
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
from broca.tools.tool_manager import ToolManager
from broca.tools.tool_permission_manager import ToolPermissionManager

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
    DEAD_LOOP = "dead_loop"


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


class LoopEngine:
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
        tool_permission_manager: Optional[ToolPermissionManager] = None,
        step_max_errors=3,
        llm_retry_delay=10,
        tool_call_timeout=120,
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
        self.tool_permission_manager = tool_permission_manager or ToolPermissionManager(
            workspace=config.workspace if config else None
        )

        self.error_handler = ErrorHandler(
            session_manager=session_manager, turn_id=None, agent_id=None
        )

        self.abort_event = asyncio.Event()

        self.agent_id = agent.agent_id
        self.session_id = session_manager.session_id
        self.turn_id: str | None = None
        self.step_id: str | None = None
        self.namespace: Optional[str] = None
        self.execution_id: Optional[str] = None

        self.step_max_errors = step_max_errors
        self.llm_retry_delay = llm_retry_delay
        self.tool_call_timeout = tool_call_timeout
        self.assign_task_timeout = assign_task_timeout

        # 快照跟踪
        self.snapshot_tracker: Optional[SnapshotTracker] = None
        self.patch_calculator: Optional[PatchCalculator] = None
        self.current_snapshot_hash: Optional[str] = None

        # Turn 级快照跟踪（用于 turn_end 时计算全量文件变更）
        self._turn_first_snapshot_hash: Optional[str] = None
        self._turn_last_snapshot_hash: Optional[str] = None

        # Step跟踪
        self._step_has_write_operations: bool = False
        self._step_lock_held: bool = False  # step 期间是否持有文件锁

        # 上下文压缩器
        self.context_compressor: Optional[ContextCompressor] = None

        # 死循环检测
        self._recent_tool_call_signatures: List[str] = []

        # 允许调用的工具列表 (None 表示不限制)
        self.allowed_tools: Optional[List[str]] = None

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
                # 持有文件锁直到 step end，防止其他进程插入导致 diff 串
                self.snapshot_tracker.git_manager.acquire_lock(blocking=True)
                self._step_lock_held = True
                snapshot_hash = await self.snapshot_tracker.track()
                self.current_snapshot_hash = snapshot_hash
                # 记录该 turn 的第一个快照（用于 turn_end 时计算全量 diff）
                if self._turn_first_snapshot_hash is None:
                    self._turn_first_snapshot_hash = self.current_snapshot_hash
            else:
                snapshot_hash = ""
            step_start_msg = MessageProtocol.create_step_start(
                step_id=self.step_id, snapshot_hash=snapshot_hash
            )
            step_start_msg.session_id = self.session_id
            step_start_msg.turn_id = self.turn_id
            step_start_msg.agent_id = self.agent_id
            step_start_msg.subscription = self.session_id

            # 保存消息到数据库
            saved = await self.session_manager.save_message(
                role=step_start_msg.role,
                content=None,
                message_type=step_start_msg.message_type,
                turn_id=self.turn_id,
                agent_id=self.agent_id,
                data=step_start_msg.data,
            )

            # 广播 step_start 消息到前端（简洁模式依赖此消息更新步骤数）
            if self.config.interactive:
                try:
                    await self.communicator.send_message(step_start_msg)
                except Exception as e:
                    logger.warning(f"Failed to broadcast step_start: {e}")

            return saved
        except Exception as e:
            logger.error(f"Error capturing step start: {e}")
            return False

    async def _capture_step_end(self) -> bool:
        """捕获Step结束快照和patch"""
        if not self.step_id:
            return False

        # === 快照/patch 计算（仅在有写操作时执行）===
        snapshot_hash = ""
        patch: dict = {}

        if (
            self.snapshot_tracker
            and self.patch_calculator
            and self.current_snapshot_hash
            and self._step_has_write_operations
        ):
            try:
                end_snapshot_hash = await self.snapshot_tracker.track()
                snapshot_hash = end_snapshot_hash
                patch = await self.patch_calculator.calculate_patch(
                    self.current_snapshot_hash, end_snapshot_hash
                )
                if not patch.get("files"):
                    patch = {}
                else:
                    # 计算 diff summary (files_added/files_deleted/files_modified)
                    try:
                        diff_content = await self.patch_calculator.calculate_diff(
                            self.current_snapshot_hash, end_snapshot_hash
                        )
                        diff_summary = self.patch_calculator.get_diff_summary(
                            diff_content
                        )
                        patch["summary"] = diff_summary
                    except Exception as e:
                        logger.warning(f"Error calculating diff summary: {e}")
                        patch["summary"] = {}
                    # 更新 turn 级最晚快照
                    self._turn_last_snapshot_hash = snapshot_hash
            except Exception as e:
                logger.error(f"Error capturing snapshot/patch at step end: {e}")

        # === step_end 消息创建和广播（无论是否只读，始终发送）===
        try:
            step_end_msg = MessageProtocol.create_step_end(
                step_id=self.step_id, snapshot_hash=snapshot_hash, patch=patch
            )
            step_end_msg.session_id = self.session_id
            step_end_msg.turn_id = self.turn_id
            step_end_msg.agent_id = self.agent_id
            step_end_msg.subscription = self.session_id

            # 保存消息到数据库
            saved = await self.session_manager.save_message(
                role=step_end_msg.role,
                content=None,
                message_type=step_end_msg.message_type,
                turn_id=self.turn_id,
                agent_id=self.agent_id,
                data=step_end_msg.data,
            )

            # 广播 step_end 消息到前端
            if self.config.interactive:
                try:
                    await self.communicator.send_message(step_end_msg)
                except Exception as e:
                    logger.warning(f"Failed to broadcast step_end: {e}")

            return saved
        except Exception as e:
            logger.error(f"Error sending step end: {e}")
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

        await self._capture_step_init()

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
        try:
            message_id = response.message_id
            if not await self.session_manager.save_agent_response(
                response,
                self.turn_id,
                self.agent_id,
                self.step_id,
                message_id=response.message_id,
            ):
                logger.error("Failed to save agent response")
                return ExecutionStatus.ERROR

            await self.context.add_message(response, message_id)

            if not response.tool_calls:
                await self._capture_step_end()
                status = ExecutionStatus.COMPLETED
            else:
                await self._process_tool_calls(response.tool_calls)
                await self._capture_step_end()

                # 死循环检测：如果最近三个工具调用完全一样，判定为死循环
                tool_call_signatures = self._extract_tool_call_signatures(
                    response.tool_calls
                )
                self._recent_tool_call_signatures.extend(tool_call_signatures)
                if len(self._recent_tool_call_signatures) >= 3:
                    last3 = self._recent_tool_call_signatures[-3:]
                    if last3[0] == last3[1] == last3[2]:
                        logger.warning(
                            f"Dead loop detected: last 3 tool calls are identical "
                            f"({self._recent_tool_call_signatures[-1]})"
                        )
                        status = ExecutionStatus.DEAD_LOOP
                    else:
                        status = ExecutionStatus.RUNNING
                else:
                    status = ExecutionStatus.RUNNING
        finally:
            # 确保 step 期间持有的文件锁被释放
            if self._step_lock_held:
                self.snapshot_tracker.git_manager.release_lock()
                self._step_lock_held = False

        if self.config.enable_context_compression:
            await self._check_context_compression()

        if self.session_memory_manager:
            self.session_memory_manager.increment_step()
            task = asyncio.create_task(
                self.session_memory_manager.check_and_extract(
                    context=self.context,
                )
            )
            task.add_done_callback(
                lambda t: t.exception() if not t.cancelled() else None
            )

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
                        turn_id=self.turn_id,
                        agent_id=self.agent_id,
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
                                turn_id=self.turn_id,
                                agent_id=self.agent_id,
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
        context.execution_id = self.execution_id
        context.namespace = self.namespace

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
                    turn_id=self.turn_id,
                    agent_id=self.agent_id,
                    subscription=self.session_id,
                )

            if tool_name not in self.tool_mapping:
                logger.error(f"Tool '{tool_name}' not found.")
                tool_result = ToolResult(
                    status=ToolStatus.ERROR, content=f"Tool {tool_name} not found"
                )
            elif self.allowed_tools is not None and tool_name not in self.allowed_tools:
                logger.warning(
                    f"Tool '{tool_name}' is not in allowed_tools list, skipping."
                )
                tool_result = ToolResult(
                    status=ToolStatus.ERROR,
                    content="this tool is currently not allowed",
                )
            else:
                # ── Permission check from ToolPermissionManager ──
                permission = self.tool_permission_manager.get_permission(tool_name)
                if permission == "forbidden":
                    logger.warning(
                        f"Tool '{tool_name}' is forbidden by permission settings, skipping."
                    )
                    tool_result = ToolResult(
                        status=ToolStatus.ERROR,
                        content=f"Tool {tool_name} is forbidden by permission settings",
                    )
                elif permission == "ask":
                    # Ask user for permission with session-level options
                    granted, session_action = await self.agent.ask_for_tool_permission(
                        tool_name, arguments
                    )
                    if not granted:
                        logger.info(f"Tool '{tool_name}' execution denied by user")
                        tool_result = ToolResult(
                            status=ToolStatus.ERROR,
                            content=f"Tool {tool_name} execution denied by user",
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
                                    self.tool_mapping[tool_name].execute(
                                        arguments, context
                                    ),
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

                    # Handle session-level decisions
                    if session_action == "allow":
                        self.tool_permission_manager.set_session_override(
                            tool_name, "allow"
                        )
                        logger.info(
                            f"User chose to always allow '{tool_name}' for this session"
                        )
                    elif session_action == "forbid":
                        self.tool_permission_manager.set_session_override(
                            tool_name, "forbidden"
                        )
                        logger.info(
                            f"User chose to always forbid '{tool_name}' for this session"
                        )
                else:  # "allow"
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
                                self.tool_mapping[tool_name].execute(
                                    arguments, context
                                ),
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

    def check_step_has_write_operations(self, tool_calls: List[Any]):
        """
        Check if a step has write operations.

        Args:
            tool_calls (List[Any]): List of tool calls in the step

        Returns:
            None
        """
        if not tool_calls:
            return
        for tool_call in tool_calls:
            tool_name = tool_call.function.name
            if tool_name not in ToolManager.READONLY_TOOLS:
                self._step_has_write_operations = True
                return

    @staticmethod
    def _extract_tool_call_signatures(tool_calls: List[Any]) -> List[str]:
        """
        Extract tool call signatures for dead loop detection.

        Each signature is a string combining tool name and normalized arguments.
        Arguments are normalized by parsing JSON and sorting keys to eliminate
        order differences.

        Args:
            tool_calls: List of tool calls from LLM response

        Returns:
            List of signature strings, one per tool call
        """
        signatures = []
        for tc in tool_calls:
            name = tc.function.name
            args = tc.function.arguments
            normalized_args = LoopEngine._normalize_arguments(args)
            signatures.append(f"{name}({normalized_args})")
        return signatures

    @staticmethod
    def _normalize_arguments(args_str: Optional[str]) -> str:
        """
        Normalize tool call arguments by parsing JSON and sorting keys.

        This ensures that arguments with the same data but different key order
        (e.g. {"a":1,"b":2} vs {"b":2,"a":1}) are treated as identical.

        Args:
            args_str: Raw arguments string from tool call

        Returns:
            Normalized arguments string
        """
        if not args_str:
            return ""
        stripped = args_str.strip()
        if not stripped:
            return ""
        try:
            parsed = json.loads(stripped)
            if isinstance(parsed, dict):
                return json.dumps(parsed, sort_keys=True, ensure_ascii=False)
            elif isinstance(parsed, list):
                return json.dumps(parsed, ensure_ascii=False)
            return str(parsed)
        except (json.JSONDecodeError, ValueError):
            return stripped

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
                turn_id=self.turn_id,
                agent_id=self.agent_id,
                subscription=self.session_id,
                message_id=message_id,
            )

        if not await self.session_manager.save_tool_call(
            turn_id=self.turn_id,
            agent_id=self.agent_id,
            tool_call=tool_call,
            tool_result=tool_result,
            step_id=self.step_id,
            message_id=message_id,
        ):
            return False
        message = await self.session_manager.message_service.get(message_id)
        if not message:
            return False
        await self.context.add_message(
            self.context.format_tool_call_result(message), message_id
        )
        return True

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
                    elif status == ExecutionStatus.DEAD_LOOP:
                        return ExecutionResult(
                            status=ExecutionStatus.DEAD_LOOP,
                            message=f"Dead loop detected after {steps} steps: last 3 tool calls are identical",
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
        self._recent_tool_call_signatures.clear()

        if not await self._setup_execution_context(message, from_agent):
            if self.config.interactive:
                await self.communicator.send_error(
                    "Error setting up execution context",
                    subscription=self.session_id,
                )
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

            # 统一生成 turn_end 消息 ID，DB 和 Socket.IO 用同一个（前端撤销时用此 ID 查找）
            turn_end_msg_id = f"msg_{uuid.uuid4().hex[:16]}"

            if result.status == ExecutionStatus.COMPLETED:
                message = "Turn completed successfully"
            elif result.status == ExecutionStatus.ABORTED:
                await self._truncate_last_assistant_message_with_tool_calls()
                message = "Turn aborted by user"
            elif result.status == ExecutionStatus.LIMIT_EXCEEDED:
                message = "Turn step limit exceeded"
            elif result.status == ExecutionStatus.DEAD_LOOP:
                message = "Turn dead loop detected"
            elif result.status == ExecutionStatus.ERROR:
                message = "Turn failed"
            elif result.status == ExecutionStatus.SKIPPED:
                message = "Turn skipped"
            else:
                message = "Turn failed"

            # === 计算 turn 级全量文件变更（最早快照 vs 最晚快照）===
            changed_files = None
            if (
                self.patch_calculator
                and self._turn_first_snapshot_hash
                and self._turn_last_snapshot_hash
                and self._turn_first_snapshot_hash != self._turn_last_snapshot_hash
            ):
                try:
                    diff_content = await self.patch_calculator.calculate_diff(
                        self._turn_first_snapshot_hash, self._turn_last_snapshot_hash
                    )
                    diff_summary = self.patch_calculator.get_diff_summary(diff_content)
                    if diff_summary.get("total_files", 0) > 0:
                        changed_files = {
                            "total_added": len(diff_summary.get("files_added", [])),
                            "total_deleted": len(diff_summary.get("files_deleted", [])),
                            "total_modified": len(
                                diff_summary.get("files_modified", [])
                            ),
                            "files_added": diff_summary.get("files_added", []),
                            "files_deleted": diff_summary.get("files_deleted", []),
                            "files_modified": diff_summary.get("files_modified", []),
                            "first_snapshot_hash": self._turn_first_snapshot_hash,
                            "last_snapshot_hash": self._turn_last_snapshot_hash,
                        }
                except Exception as e:
                    logger.warning(f"Error calculating turn-level diff: {e}")

            # 清理 turn 级快照跟踪（为下一个 turn 做准备）
            self._turn_first_snapshot_hash = None
            self._turn_last_snapshot_hash = None

            # 先保存到 DB（使用统一 message_id），再发 Socket.IO
            turn_status = (
                "completed" if result.status == ExecutionStatus.COMPLETED else "error"
            )
            saved = await self.session_manager.save_turn_end(
                turn_id=self.turn_id,
                agent_id=self.agent_id,
                message=message,
                status=turn_status,
                message_id=turn_end_msg_id,
                changed_files=changed_files,
            )

            if self.config.interactive:
                await self.communicator.send_turn_end(
                    turn_id=self.turn_id,
                    result=result.status.value,
                    message_id=turn_end_msg_id,
                    subscription=self.session_id,
                    changed_files=changed_files,
                )

            if result.status != ExecutionStatus.COMPLETED:
                if self.config.interactive:
                    await self.communicator.send_error(
                        message,
                        subscription=self.session_id,
                    )

            return saved
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
        try:
            user_message = self.llm_client.parse_message(
                provider=self.config.provider, model=self.config.model, message=message
            )
            if not user_message:
                return False

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
            if user_message.get("raw_input"):
                message.data["raw_input"] = user_message["raw_input"]
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

            # 广播用户消息（带 turn_id/agent_id）到当前 session 的所有订阅者
            if self.config.interactive and not from_agent and message.message_id:
                broadcast_msg = MessageProtocol.create_user_message(
                    content=user_message.get("content", ""),
                    sender_id=message.sender_id,
                    subscription=self.session_id,
                    turn_id=turn_id,
                    agent_id=self.agent_id,
                    message_id=message.message_id,
                )
                if message.data and message.data.get("files"):
                    broadcast_msg.data["files"] = message.data["files"]
                if user_message.get("raw_input"):
                    broadcast_msg.data["raw_input"] = user_message["raw_input"]
                await self.communicator.send_message(broadcast_msg)

            await self.context.add_message(user_message, message_id)
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

        Clears abort state, resets execution flags, and clears
        session-level permission overrides.
        """
        self.abort_event.clear()
        self.turn_id = None
        self.tool_permission_manager.clear_session_overrides()

    async def _truncate_last_assistant_message_with_tool_calls(self):
        """
        Truncate the last assistant message with tool_calls from context and database.
        """
        if self.context:
            await self.context.truncate_last_assistant_message_with_tool_calls(
                turn_id=self.turn_id,
                agent_id=self.agent_id,
            )

    async def _check_context_compression(self):
        """
        检查 context 是否需要进行压缩。

        在 execute_step 完成后调用，触发策略A（过期工具结果清理）
        和策略B（Session Memory 截断）。
        """
        if not self.context_compressor:
            self.context_compressor = ContextCompressor()

        await self.context_compressor.check_and_compress(
            context=self.context,
            execution_engine=self,
            agent=self.agent,
        )
