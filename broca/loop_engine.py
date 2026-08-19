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
from broca.errors import BrocaError, ErrorCode, LLMError, ToolError, ValidationError
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
        llm_retry_delay=5,
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
        self.persistent_memory_manager = getattr(
            agent, "persistent_memory_manager", None
        )
        self.tool_permission_manager = tool_permission_manager or ToolPermissionManager(
            workspace=config.workspace if config else None
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

        # 限流连续失败计数（调用成功后清零）
        self._consecutive_rate_limit_errors: int = 0

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

    async def _broadcast_step_message(self, message) -> None:
        """广播 step 级别消息到前端"""
        if self.config.interactive:
            try:
                await self.communicator.send_message(message)
            except Exception as e:
                logger.warning(f"Failed to broadcast step message: {e}")

    async def _save_step_message(self, message) -> bool:
        """保存 step 消息到数据库"""
        return await self.session_manager.save_message(
            role=message.role,
            content=None,
            message_type=message.message_type,
            turn_id=self.turn_id,
            agent_id=self.agent_id,
            data=message.data,
        )

    def _acquire_step_lock(self) -> None:
        """持有文件锁直到 step end，防止其他进程插入导致 diff 串"""
        if self.snapshot_tracker is None:
            return
        self.snapshot_tracker.git_manager.acquire_lock(blocking=True)
        self._step_lock_held = True

    def _release_step_lock(self) -> None:
        """释放 step 期间持有的文件锁"""
        if self._step_lock_held and self.snapshot_tracker is not None:
            self.snapshot_tracker.git_manager.release_lock()
            self._step_lock_held = False

    async def _capture_step_start_snapshot(self) -> str:
        """捕获 step 开始时的快照，返回快照 hash"""
        if not self._step_has_write_operations or self.snapshot_tracker is None:
            return ""
        self._acquire_step_lock()
        snapshot_hash = await self.snapshot_tracker.track()
        self.current_snapshot_hash = snapshot_hash
        # 记录该 turn 的第一个快照（用于 turn_end 时计算全量 diff）
        if self._turn_first_snapshot_hash is None:
            self._turn_first_snapshot_hash = self.current_snapshot_hash
        return snapshot_hash

    async def _compute_step_end_patch(self) -> tuple[str, dict]:
        """计算 step 结束时的 patch，返回 (snapshot_hash, patch)"""
        if not (
            self.snapshot_tracker
            and self.patch_calculator
            and self.current_snapshot_hash
            and self._step_has_write_operations
        ):
            return ("", {})

        try:
            end_snapshot_hash = await self.snapshot_tracker.track()
            patch = await self.patch_calculator.calculate_patch(
                self.current_snapshot_hash, end_snapshot_hash
            )
            if not patch.get("files"):
                return (end_snapshot_hash, {})

            # 计算 diff summary
            try:
                diff_content = await self.patch_calculator.calculate_diff(
                    self.current_snapshot_hash, end_snapshot_hash
                )
                patch["summary"] = self.patch_calculator.get_diff_summary(diff_content)
            except Exception as e:
                logger.warning(f"Error calculating diff summary: {e}")
                patch["summary"] = {}
            # 更新 turn 级最晚快照
            self._turn_last_snapshot_hash = end_snapshot_hash
            return (end_snapshot_hash, patch)
        except Exception as e:
            logger.error(f"Error capturing snapshot/patch at step end: {e}")
            return ("", {})

    async def _capture_step_start(self) -> bool:
        """捕获Step开始快照"""
        if not self.snapshot_tracker or not self.step_id:
            return False

        try:
            snapshot_hash = await self._capture_step_start_snapshot()
            step_start_msg = MessageProtocol.create_step_start(
                step_id=self.step_id, snapshot_hash=snapshot_hash
            )
            step_start_msg.session_id = self.session_id
            step_start_msg.turn_id = self.turn_id
            step_start_msg.agent_id = self.agent_id
            step_start_msg.subscription = self.session_id

            saved = await self._save_step_message(step_start_msg)
            await self._broadcast_step_message(step_start_msg)
            return saved
        except Exception as e:
            logger.error(f"Error capturing step start: {e}")
            return False

    async def _capture_step_end(self) -> bool:
        """捕获Step结束快照和patch"""
        if not self.step_id:
            return False

        snapshot_hash, patch = await self._compute_step_end_patch()
        try:
            step_end_msg = MessageProtocol.create_step_end(
                step_id=self.step_id, snapshot_hash=snapshot_hash, patch=patch
            )
            step_end_msg.session_id = self.session_id
            step_end_msg.turn_id = self.turn_id
            step_end_msg.agent_id = self.agent_id
            step_end_msg.subscription = self.session_id

            saved = await self._save_step_message(step_end_msg)
            await self._broadcast_step_message(step_end_msg)
            return saved
        except Exception as e:
            logger.error(f"Error sending step end: {e}")
            return False

    async def _call_llm_with_retry(self) -> LLMMessage | None:
        """调用 LLM 并支持重试，返回 LLM 响应消息

        重试参数统一为 step_max_errors 次 / llm_retry_delay 秒：
        - 限流 (LLM_RATE_LIMIT)：等待后自动重试，最多连续重试 step_max_errors 次，
          某次调用成功后限流计数清零。
        - 其他 LLMError：立即向上抛出，结束 turn。
        - 超时/未知异常：按同一重试参数重试。
        """
        errors = 0
        while errors < self.step_max_errors:
            if self.abort_event.is_set():
                logger.info("Agent execution aborted during LLM call")
                return None

            try:
                response = await asyncio.wait_for(
                    self._call_llm_streaming(), timeout=300
                )
                if not response:
                    raise LLMError("LLM 调用返回空响应")
                # 调用成功：限流连续失败计数清零
                if self._consecutive_rate_limit_errors:
                    self._consecutive_rate_limit_errors = 0
                return response
            except LLMError as e:
                if e.error_code == ErrorCode.LLM_RATE_LIMIT:
                    self._consecutive_rate_limit_errors += 1
                    if self._consecutive_rate_limit_errors > self.step_max_errors:
                        logger.error(
                            "LLM rate limited %d consecutive times, aborting turn",
                            self._consecutive_rate_limit_errors,
                        )
                        raise
                    logger.warning(
                        "LLM rate limited (%d/%d), retrying in %ds",
                        self._consecutive_rate_limit_errors,
                        self.step_max_errors,
                        self.llm_retry_delay,
                    )
                    await self._send_llm_error(
                        f"请求频率过高，{self.llm_retry_delay} 秒后自动重试 "
                        f"({self._consecutive_rate_limit_errors}/{self.step_max_errors})...",
                        "LLM_RATE_LIMIT",
                        "warning",
                    )
                    await asyncio.sleep(self.llm_retry_delay)
                    continue
                raise
            except asyncio.TimeoutError:
                errors += 1
                logger.error("LLM call timed out")
                await self._send_llm_error(
                    "LLM 调用超时，自动重试中...", "LLM_TIMEOUT", "warning"
                )
                if errors < self.step_max_errors:
                    continue
                return None
            except asyncio.CancelledError:
                logger.info("Agent execution cancelled by user during LLM call")
                return None
            except Exception as e:
                errors += 1
                logger.error(f"LLM call failed: {e}")
                if errors == self.step_max_errors:
                    logger.error("Too many LLM errors, aborting...")
                    return None
                await self._send_llm_error(
                    "LLM 调用失败，正在重试...", "LLM_ERROR", "error"
                )
                await asyncio.sleep(self.llm_retry_delay)
        return None

    async def _send_llm_error(self, message: str, code: str, severity: str) -> None:
        """发送 LLM 错误通知到前端"""
        if self.config.interactive:
            await self.communicator.send_error(
                {"message": message, "code": code, "severity": severity},
                subscription=self.session_id,
            )

    def _detect_dead_loop(self, tool_calls: list) -> ExecutionStatus:
        """检测是否陷入死循环（最近 3 步工具调用完全相同）"""
        tool_call_signatures = self._extract_tool_call_signatures(tool_calls)
        self._recent_tool_call_signatures.extend(tool_call_signatures)
        if len(self._recent_tool_call_signatures) < 3:
            return ExecutionStatus.RUNNING
        last3 = self._recent_tool_call_signatures[-3:]
        if last3[0] == last3[1] == last3[2]:
            logger.warning(
                f"Dead loop detected: last 3 tool calls are identical "
                f"({self._recent_tool_call_signatures[-1]})"
            )
            return ExecutionStatus.DEAD_LOOP
        return ExecutionStatus.RUNNING

    async def _save_response_and_process_tool_calls(self, response) -> ExecutionStatus:
        """保存 LLM 响应，处理工具调用，返回步骤执行状态"""
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
            return ExecutionStatus.COMPLETED

        await self._process_tool_calls(response.tool_calls)
        await self._capture_step_end()
        return self._detect_dead_loop(response.tool_calls)

    async def _trigger_post_step_hooks(self) -> None:
        """触发 step 完成后的后置钩子：上下文压缩、session memory、持久化记忆"""
        if self.config.enable_context_compression:
            await self._check_context_compression()

        if self.session_memory_manager:
            self.session_memory_manager.increment_step()
            task = asyncio.create_task(
                self.session_memory_manager.check_and_extract(context=self.context)
            )
            task.add_done_callback(
                lambda t: t.exception() if not t.cancelled() else None
            )

        if (
            self.persistent_memory_manager
            and getattr(self.config, "persistent_memory_config", None)
            and self.config.persistent_memory_config.auto_extract
        ):
            self.persistent_memory_manager.increment_step()
            task = asyncio.create_task(
                self.persistent_memory_manager.check_and_extract(context=self.context)
            )
            task.add_done_callback(
                lambda t: t.exception() if not t.cancelled() else None
            )

    async def execute_step(self) -> ExecutionStatus:
        """
        Execute one step of agent execution

        Returns:
            ExecutionStatus indicating the result
        """
        # 初始化快照跟踪
        if not self.snapshot_tracker:
            self._initialize_snapshot_tracking()

        # 生成Step ID
        self.step_id = self._generate_step_id()
        await self._capture_step_init()

        # Step 1: LLM 调用（含重试）
        response = await self._call_llm_with_retry()
        if self.abort_event.is_set():
            logger.info("Agent execution aborted during LLM call")
            return ExecutionStatus.ABORTED
        if not response:
            return ExecutionStatus.ERROR

        # Step 2: 检查写操作，捕获 step start 快照
        self.check_step_has_write_operations(response.tool_calls or [])
        await self._capture_step_start()

        # Step 3: 保存响应、处理工具调用（含死循环检测）
        try:
            status = await self._save_response_and_process_tool_calls(response)
        finally:
            self._release_step_lock()

        # Step 4: 后置钩子
        await self._trigger_post_step_hooks()
        return status

    async def _process_content_chunk(
        self, chunk: dict, content_chunks: list, index: int, message_id: str
    ) -> int:
        """处理内容/推理内容块，广播到前端"""
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
        return index + 1

    async def _process_tool_call_chunk(
        self, chunk: dict, tool_call_chunks: list, sent: set
    ) -> None:
        """处理工具调用块，首次出现时广播到前端"""
        tool_call = chunk["data"]
        tool_call_chunks.append(tool_call)
        if not (hasattr(tool_call, "id") and tool_call.id and tool_call.id not in sent):
            return
        if (
            hasattr(tool_call, "function")
            and tool_call.function
            and tool_call.function.name
        ):
            if self.config.interactive:
                await self.communicator.send_tool_call(
                    tool_name=tool_call.function.name,
                    arguments=None,
                    tool_call_id=tool_call.id,
                    turn_id=self.turn_id,
                    agent_id=self.agent_id,
                    subscription=self.session_id,
                )
            sent.add(tool_call.id)

    async def _finalize_llm_response(
        self, content_chunks: list, tool_call_chunks: list, message_id: str
    ) -> LLMMessage | None:
        """完成 LLM 响应聚合，更新 token 计数"""
        input_tokens = self.llm_client.input_tokens_used
        output_tokens = self.llm_client.output_tokens_used
        await self.agent.on_llm_call_completed(input_tokens, output_tokens)

        message = self.llm_client.aggregate_message(content_chunks, tool_call_chunks)
        # 将 message_id 附加到消息对象供后续使用
        if message is not None:
            setattr(message, "message_id", message_id)
        return message

    async def _call_llm_streaming(self) -> LLMMessage | None:
        """
        Call LLM with current context (streaming)

        Returns:
            LLM response message
        """
        content_chunks: list[Any] = []
        tool_call_chunks: list[Any] = []
        sent: set[str] = set()
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

            if chunk["type"] in ("content", "reasoning_content"):
                index = await self._process_content_chunk(
                    chunk, content_chunks, index, message_id
                )
            elif chunk["type"] == "tool_call":
                await self._process_tool_call_chunk(chunk, tool_call_chunks, sent)

        return await self._finalize_llm_response(
            content_chunks, tool_call_chunks, message_id
        )

    def _get_tools_list(self) -> List[Dict[str, Any]]:
        """
        Get formatted tools list for LLM

        Returns:
            List of formatted tools
        """
        return [tool.format() for tool in self.tool_mapping.values()]

    def _build_tool_context(self) -> ToolCallContext:
        """构建工具执行上下文"""
        ctx = ToolCallContext()
        ctx.agent = self.agent
        ctx.workspace = self.config.workspace
        ctx.session_id = self.session_id
        ctx.execution_id = self.execution_id
        ctx.namespace = self.namespace
        return ctx

    async def _broadcast_tool_call_start(
        self, tool_name: str, arguments: str, tool_call_id: str
    ) -> None:
        """广播工具调用开始消息到前端"""
        if self.config.interactive:
            await self.communicator.send_tool_call(
                tool_name=tool_name,
                arguments=arguments,
                tool_call_id=tool_call_id,
                turn_id=self.turn_id,
                agent_id=self.agent_id,
                subscription=self.session_id,
            )

    def _is_tool_allowed(self, tool_name: str) -> bool:
        """检查工具是否在 allowed_tools 列表中"""
        return self.allowed_tools is None or tool_name in self.allowed_tools

    def _get_tool_execution_timeout(self, tool_name: str) -> int:
        """获取工具执行超时时间"""
        if tool_name == "assign_task":
            return self.assign_task_timeout
        return self.tool_call_timeout

    async def _execute_tool_with_allow(
        self, tool_name: str, arguments: str, context: ToolCallContext
    ) -> ToolResult:
        """以 allow 权限执行工具"""
        try:
            if self._should_skip_tool_timeout(tool_name, arguments):
                return await self.tool_mapping[tool_name].execute(arguments, context)
            timeout = self._get_tool_execution_timeout(tool_name)
            return await asyncio.wait_for(
                self.tool_mapping[tool_name].execute(arguments, context),
                timeout=timeout,
            )
        except (ToolError, BrocaError) as e:
            logger.error(f"Tool execution failed: {e}")
            return ToolResult(status=ToolStatus.ERROR, content=e.to_user_message())
        except asyncio.TimeoutError:
            timeout = self._get_tool_execution_timeout(tool_name)
            logger.error(
                f"Tool '{tool_name}' execution timed out after {timeout}s"
            )
            return ToolResult(
                status=ToolStatus.ERROR,
                content=f"Tool {tool_name} execution timed out after {timeout}s",
            )
        except asyncio.CancelledError:
            logger.info("Tool execution cancelled by user")
            raise

    async def _execute_tool_with_ask(
        self, tool_name: str, arguments: str, context: ToolCallContext
    ) -> tuple[ToolResult, str | None]:
        """以 ask 权限执行工具（需用户确认），返回 (result, session_action)"""
        granted, session_action = await self.agent.ask_for_tool_permission(
            tool_name, arguments
        )
        if not granted:
            logger.info(f"Tool '{tool_name}' execution denied by user")
            return ToolResult(
                status=ToolStatus.ERROR,
                content=f"Tool {tool_name} execution denied by user",
            ), session_action

        try:
            if self._should_skip_tool_timeout(tool_name, arguments):
                tool_result = await self.tool_mapping[tool_name].execute(
                    arguments, context
                )
            else:
                timeout = self._get_tool_execution_timeout(tool_name)
                tool_result = await asyncio.wait_for(
                    self.tool_mapping[tool_name].execute(arguments, context),
                    timeout=timeout,
                )
        except (ToolError, BrocaError) as e:
            logger.error(f"Tool execution failed: {e}")
            tool_result = ToolResult(
                status=ToolStatus.ERROR, content=e.to_user_message()
            )
        except asyncio.TimeoutError:
            timeout = self._get_tool_execution_timeout(tool_name)
            logger.error(
                f"Tool '{tool_name}' execution timed out after {timeout}s"
            )
            tool_result = ToolResult(
                status=ToolStatus.ERROR,
                content=f"Tool {tool_name} execution timed out after {timeout}s",
            )
        except asyncio.CancelledError:
            logger.info("Tool execution cancelled by user")
            raise
        return tool_result, session_action

    def _apply_session_decision(
        self, tool_name: str, session_action: str | None
    ) -> None:
        """应用会话级别的权限决策"""
        if session_action == "allow":
            self.tool_permission_manager.set_session_override(tool_name, "allow")
            logger.info(f"User chose to always allow '{tool_name}' for this session")
        elif session_action == "forbid":
            self.tool_permission_manager.set_session_override(tool_name, "forbidden")
            logger.info(f"User chose to always forbid '{tool_name}' for this session")

    async def _execute_single_tool_call(
        self, tool_call: Any, context: ToolCallContext
    ) -> ToolResult:
        """执行单个工具调用（含权限校验和 session 决策）"""
        tool_name = tool_call.function.name
        arguments = tool_call.function.arguments

        # 广播工具调用开始
        await self._broadcast_tool_call_start(tool_name, arguments, tool_call.id)

        # 检查工具是否存在
        if tool_name not in self.tool_mapping:
            logger.error(f"Tool '{tool_name}' not found.")
            return ToolResult(
                status=ToolStatus.ERROR, content=f"Tool {tool_name} not found"
            )

        # 检查 allowed_tools 限制
        if not self._is_tool_allowed(tool_name):
            logger.warning(
                f"Tool '{tool_name}' is not in allowed_tools list, skipping."
            )
            return ToolResult(
                status=ToolStatus.ERROR, content="this tool is currently not allowed"
            )

        # 权限决策：forbidden / ask / allow
        permission = self.tool_permission_manager.get_permission(tool_name)
        if permission == "forbidden":
            logger.warning(
                f"Tool '{tool_name}' is forbidden by permission settings, skipping."
            )
            return ToolResult(
                status=ToolStatus.ERROR,
                content=f"Tool {tool_name} is forbidden by permission settings",
            )
        if permission == "ask":
            tool_result, session_action = await self._execute_tool_with_ask(
                tool_name, arguments, context
            )
            self._apply_session_decision(tool_name, session_action)
            return tool_result

        # permission == "allow"
        return await self._execute_tool_with_allow(tool_name, arguments, context)

    async def _process_tool_calls(self, tool_calls: List[Any]):
        """
        Process tool calls from LLM response

        Args:
            tool_calls: List of tool calls from LLM
        """
        context = self._build_tool_context()

        for tool_call in tool_calls:
            if self.abort_event.is_set():
                logger.info("Agent execution aborted during tool call processing")
                return

            tool_result = await self._execute_single_tool_call(tool_call, context)

            if not await self.process_tool_call_result(tool_call, tool_result):
                raise Exception("Tool call result processing failed")

    def _should_skip_tool_timeout(self, tool_name: str, arguments: str) -> bool:
        """判断是否应跳过工具执行的外层超时

        以下工具由自身内部 timeout 控制，不需要 LoopEngine 的外层 wait_for 限制：
        - bash 的 background 模式：在工具内部快速通过 Scheduler 异步返回
        - ask_user：等待用户回答，由内部 timeout（当前 180s）控制
        """
        if tool_name == "bash":
            try:
                args_dict = json.loads(arguments)
                return bool(args_dict.get("background", False))
            except (json.JSONDecodeError, TypeError):
                return False
        if tool_name == "ask_user":
            return True
        return False

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

    async def _build_round_result(
        self, status: ExecutionStatus, steps: int
    ) -> ExecutionResult:
        """根据步骤状态构建回合执行结果"""
        messages = {
            ExecutionStatus.COMPLETED: f"Round completed after {steps} steps",
            ExecutionStatus.ABORTED: f"Round aborted by user after {steps} steps",
            ExecutionStatus.ERROR: f"Round failed after {steps} steps",
            ExecutionStatus.DEAD_LOOP: f"Dead loop detected after {steps} steps: last 3 tool calls are identical",
            ExecutionStatus.LIMIT_EXCEEDED: "Max steps reached",
        }
        return ExecutionResult(
            status=status,
            message=messages.get(status, f"Round ended with {status.value}"),
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
                status = await self.execute_step()
                steps += 1

                if status in (
                    ExecutionStatus.COMPLETED,
                    ExecutionStatus.ABORTED,
                    ExecutionStatus.ERROR,
                    ExecutionStatus.DEAD_LOOP,
                ):
                    return await self._build_round_result(status, steps)

                if max_steps is not None and steps >= max_steps:
                    return await self._build_round_result(
                        ExecutionStatus.LIMIT_EXCEEDED, steps
                    )
            except BrocaError as e:
                if self.config.interactive:
                    await self.communicator.send_error(
                        e.to_dict(), subscription=self.session_id
                    )
                return ExecutionResult(
                    status=ExecutionStatus.ERROR, message=e.to_user_message()
                )
            except asyncio.CancelledError:
                return ExecutionResult(
                    status=ExecutionStatus.ABORTED, message="Round aborted by user"
                )

    async def _send_execution_error(
        self, error: Exception, code: str, severity: str = "error"
    ) -> None:
        """发送执行错误通知到前端"""
        if self.config.interactive:
            error_info = {
                "message": f"执行异常: {error}"
                if code == "UNKNOWN_ERROR"
                else str(error),
                "code": code,
                "severity": severity,
            }
            await self.communicator.send_error(error_info, subscription=self.session_id)

    def _make_error_result(
        self, status: ExecutionStatus, error: Exception
    ) -> ExecutionResult:
        """从异常创建执行错误结果"""
        if isinstance(error, (BrocaError, ValidationError)):
            message = error.to_user_message()
        else:
            message = f"Unexpected error: {error}"
        return ExecutionResult(status=status, message=message)

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
        self._consecutive_rate_limit_errors = 0

        try:
            if not await self._setup_execution_context(message, from_agent):
                await self._send_execution_error(
                    Exception("执行上下文设置失败"), "SESSION_ERROR"
                )
                return ExecutionResult(
                    status=ExecutionStatus.ERROR,
                    message="Error setting up execution context",
                )
            result = await self.execute_round(max_steps)
        except ValidationError as e:
            logger.error(f"ValidationError in execute: {e}")
            await self._send_execution_error(e, "VALIDATION_ERROR")
            result = self._make_error_result(ExecutionStatus.ERROR, e)
        except asyncio.CancelledError:
            logger.info("Execution cancelled by user")
            result = ExecutionResult(
                status=ExecutionStatus.ABORTED, message="Execution cancelled by user"
            )
        except BrocaError as e:
            logger.error(f"BrocaError in execute: {e}")
            await self._send_execution_error(e, "BROCA_ERROR")
            result = self._make_error_result(ExecutionStatus.ERROR, e)
        except Exception as e:
            logger.error(f"Unexpected error in execute: {e}")
            await self._send_execution_error(e, "UNKNOWN_ERROR")
            result = self._make_error_result(ExecutionStatus.ERROR, e)

        if not await self.process_turn_end(result):
            logger.warning("Turn end processing failed")

        return result

    def _get_turn_end_message(self, result: ExecutionResult) -> str:
        """根据执行结果获取 turn_end 消息文本"""
        status_messages = {
            ExecutionStatus.COMPLETED: "Turn completed successfully",
            ExecutionStatus.ABORTED: "Turn aborted by user",
            ExecutionStatus.LIMIT_EXCEEDED: "Turn step limit exceeded",
            ExecutionStatus.DEAD_LOOP: "Turn dead loop detected",
            ExecutionStatus.ERROR: "Turn failed",
            ExecutionStatus.SKIPPED: "Turn skipped",
        }
        return status_messages.get(result.status, "Turn failed")

    async def _compute_turn_level_diff(self) -> dict | None:
        """计算 turn 级全量文件变更"""
        # 如果 turn 有开始快照但无结束快照（异常终止），捕获当前状态作为结束快照
        if (
            self.patch_calculator
            and self._turn_first_snapshot_hash
            and not self._turn_last_snapshot_hash
        ):
            try:
                if self.snapshot_tracker is None:
                    return None
                end_snapshot_hash = await self.snapshot_tracker.track()
                self._turn_last_snapshot_hash = end_snapshot_hash
            except Exception as e:
                logger.warning(
                    f"Error capturing final snapshot for abnormal turn end: {e}"
                )

        if not (
            self.patch_calculator
            and self._turn_first_snapshot_hash
            and self._turn_last_snapshot_hash
            and self._turn_first_snapshot_hash != self._turn_last_snapshot_hash
        ):
            return None
        try:
            diff_content = await self.patch_calculator.calculate_diff(
                self._turn_first_snapshot_hash, self._turn_last_snapshot_hash
            )
            diff_summary = self.patch_calculator.get_diff_summary(diff_content)
            if diff_summary.get("total_files", 0) == 0:
                return None
            return {
                "total_added": len(diff_summary.get("files_added", [])),
                "total_deleted": len(diff_summary.get("files_deleted", [])),
                "total_modified": len(diff_summary.get("files_modified", [])),
                "files_added": diff_summary.get("files_added", []),
                "files_deleted": diff_summary.get("files_deleted", []),
                "files_modified": diff_summary.get("files_modified", []),
                "first_snapshot_hash": self._turn_first_snapshot_hash,
                "last_snapshot_hash": self._turn_last_snapshot_hash,
            }
        except Exception as e:
            logger.warning(f"Error calculating turn-level diff: {e}")
            return None

    def _clear_turn_snapshots(self) -> None:
        """清理 turn 级快照跟踪"""
        self._turn_first_snapshot_hash = None
        self._turn_last_snapshot_hash = None

    async def _save_and_broadcast_turn_end(
        self,
        result: ExecutionResult,
        message: str,
        turn_end_msg_id: str,
        changed_files: dict | None,
    ) -> bool:
        """保存 turn_end 到数据库并广播到前端"""
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
        return saved

    async def _send_turn_error_notification(
        self, result: ExecutionResult, message: str
    ) -> None:
        """发送 turn 错误通知到前端"""
        if not self.config.interactive:
            return
        error_info = {
            "code": "EXECUTION_ERROR",
            "severity": "error",
            "message": message,
            "recovery_hint": None,
            "details": {"status": result.status.value},
            "cause": None,
            "traceback": None,
        }
        await self.communicator.send_error(
            error_info=error_info, subscription=self.session_id
        )

    async def process_turn_end(self, result: ExecutionResult) -> bool:
        try:
            logger.info("turn ended with result: " + str(result))

            turn_end_msg_id = f"msg_{uuid.uuid4().hex[:16]}"
            message = self._get_turn_end_message(result)

            if result.status == ExecutionStatus.ABORTED:
                await self._truncate_last_assistant_message_with_tool_calls()

            changed_files = await self._compute_turn_level_diff()
            self._clear_turn_snapshots()

            saved = await self._save_and_broadcast_turn_end(
                result, message, turn_end_msg_id, changed_files
            )

            if result.status != ExecutionStatus.COMPLETED:
                await self._send_turn_error_notification(result, message)

            return saved
        except Exception as e:
            logger.error(f"Error in process_turn_end: {e}")
            return False

    async def _start_new_turn(self, user_message: dict, from_agent: bool) -> str | None:
        """创建新 turn，设置 turn_id，广播 turn_start"""
        await self._ensure_session()
        turn_id = await self.session_manager.start_turn(self.agent_id)
        if not turn_id:
            return None
        self.turn_id = turn_id
        self.agent.turn_id = turn_id

        if self.config.interactive:
            await self.communicator.send_turn_start(
                turn_id=turn_id,
                turn_description=f"Processing user message: {user_message.get('content')}",
                subscription=self.session_id,
            )
        return turn_id

    async def _save_user_message(
        self, user_message: dict, message: Message, turn_id: str, from_agent: bool
    ) -> str | None:
        """保存用户消息到数据库，返回 message_id"""
        message.data["from_agent"] = from_agent
        if user_message.get("raw_input"):
            message.data["raw_input"] = user_message["raw_input"]
        # from_agent 消息预生成 message_id 并返回，避免 _setup_execution_context
        # 因 message_id 为 None 而误判执行上下文设置失败（回归修复，见 104c8c2）
        message_id = (
            message.message_id
            if not from_agent
            else f"msg_{uuid.uuid4().hex[:16]}"
        )
        saved = await self.session_manager.save_message(
            role=MessageRole.USER,
            content=json.dumps(user_message, ensure_ascii=False),
            message_type=MessageType.USER_MESSAGE,
            turn_id=turn_id,
            agent_id=self.agent_id,
            data=message.data,
            message_id=message_id,
        )
        return message_id if saved else None

    async def _broadcast_user_message(
        self, user_message: dict, message: Message, turn_id: str
    ) -> None:
        """广播用户消息到 session 订阅者"""
        if not (
            self.config.interactive
            and message.message_id
            and not getattr(message, "from_agent", False)
        ):
            return
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

    async def _setup_execution_context(
        self, message: Message, from_agent: Optional[bool] = False
    ) -> bool:
        """
        Set up execution context for a new turn

        Args:
            message: The message to process

        Raises:
            ValidationError: If provider or model configuration is invalid
        """
        try:
            user_message = self.llm_client.parse_message(
                provider=self.config.provider, model=self.config.model, message=message
            )
            if not user_message:
                return False

            turn_id = await self._start_new_turn(user_message, from_agent or False)
            if not turn_id:
                return False

            message_id = await self._save_user_message(
                user_message, message, turn_id, from_agent or False
            )
            if message_id is None:
                return False

            await self._broadcast_user_message(user_message, message, turn_id)
            await self.context.add_message(user_message, message_id)
            return True
        except ValidationError:
            raise
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
        self._consecutive_rate_limit_errors = 0

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
