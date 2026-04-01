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
from enum import Enum
from typing import Any, Dict, List, Optional

from litellm import Message as LLMMessage
from loguru import logger

from broca.context import Context
from broca.error_handler import AgentError, ErrorHandler, ErrorType
from broca.llm import LLMClient
from broca.session import (
    Message,
    MessageRole,
    MessageType,
    SessionManager,
    generate_message_id,
)
from broca.tools.tool import ToolCallContext, ToolResult, ToolStatus


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

        # Initialize error handler
        self.error_handler = ErrorHandler(
            session_manager=session_manager,
            turn_id=None,  # Will be set during execution
            agent_id=None,  # Will be set during execution
        )

        # Execution state
        self.is_aborted = False
        self.abort_event = asyncio.Event()

        # For backward compatibility
        self.turn_id = None
        self.agent_id = None
        self.session_id = None

    def set_execution_state(
        self,
        turn_id: Optional[str] = None,
        agent_id: Optional[str] = None,
        session_id: Optional[str] = None,
        is_aborted: bool = False,
    ):
        """
        Set execution state variables

        Args:
            turn_id: Current turn ID
            agent_id: Agent ID
            session_id: Session ID
            is_aborted: Whether execution is aborted
        """
        self.turn_id = turn_id
        self.agent_id = agent_id
        self.session_id = session_id
        self.is_aborted = is_aborted

        # Update error handler context
        self.error_handler.set_context(
            turn_id=turn_id, agent_id=agent_id, session_manager=self.session_manager
        )

        if is_aborted:
            self.abort_event.set()
        else:
            self.abort_event.clear()

    async def execute_step(self) -> ExecutionStatus:
        """
        Execute one step of agent execution

        Returns:
            True if more steps are needed, False otherwise
        """
        errors = 0

        while errors < 3:
            # Check for abort during LLM call
            if self.is_aborted or self.abort_event.is_set():
                logger.info("Agent execution aborted during LLM call")
                return ExecutionStatus.ABORTED

            try:
                # Use error handler context manager for LLM call
                async with self.error_handler.handle_llm_call(context="execute_step"):
                    # Call LLM with timeout for cancellation support
                    response = await asyncio.wait_for(
                        self._call_llm_streaming(), timeout=300
                    )
                    break
            except AgentError as e:
                errors += 1
                if errors > 2:
                    logger.error(f"Too many errors ({e.error_type}), aborting...")
                    return ExecutionStatus.ERROR
                if e.error_type == ErrorType.LLM_RATE_LIMIT_ERROR:
                    await asyncio.sleep(3)
            except asyncio.CancelledError:
                logger.info("Agent execution cancelled by user during LLM call")
                return ExecutionStatus.ABORTED

        if self.is_aborted or self.abort_event.is_set():
            logger.info("Agent execution aborted after tool calls")
            return ExecutionStatus.ABORTED

        if not await self.session_manager.save_agent_response(
            response, self.turn_id, self.agent_id
        ):
            logger.error("Failed to save agent response")
            return ExecutionStatus.ERROR

        # Add response to history
        await self.context.add_message(response)

        # Process tool calls if any
        if not response.tool_calls:
            return ExecutionStatus.COMPLETED
        else:
            await self._process_tool_calls(response.tool_calls)
            return ExecutionStatus.RUNNING

    async def _call_llm_streaming(self) -> LLMMessage:
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
            if self.is_aborted or self.abort_event.is_set():
                logger.info("Agent execution aborted during LLM call")
                raise asyncio.CancelledError("Execution aborted by user")

            if chunk["type"] in ["content", "reasoning_content"]:
                content_chunks.append(chunk)
                content = chunk["data"] if chunk["type"] == "content" else ""
                reasoning_content = (
                    chunk["data"] if chunk["type"] == "reasoning_content" else ""
                )
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
                        await self.communicator.send_tool_call(
                            tool_name=tool_name,
                            arguments=None,
                            tool_call_id=tool_call_id,
                            subscription=self.session_id,
                        )
                        sent.add(tool_call_id)

        # Notify agent to update statistics
        input_tokens = self.llm_client.input_tokens_used
        output_tokens = self.llm_client.output_tokens_used
        await self.agent.on_llm_call_completed(input_tokens, output_tokens)

        return self.llm_client.aggregate_message(content_chunks, tool_call_chunks)

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
            # Check for abort before processing each tool call
            if self.is_aborted or self.abort_event.is_set():
                logger.info("Agent execution aborted during tool call processing")
                return

            tool_name = tool_call.function.name
            arguments = tool_call.function.arguments

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
                        timeout = 1800 if tool_name == "assign_task" else 600
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

    async def process_tool_call_result(
        self,
        tool_call: Any,
        tool_result: ToolResult
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
        await self.communicator.send_tool_call(
            tool_name=tool_call.function.name,
            arguments=tool_call.function.arguments,
            tool_call_id=tool_call.id,
            result=tool_result.content,
            status=tool_result.status,
            subscription=self.session_id
        )

        return await self.session_manager.save_tool_call(
            turn_id=self.turn_id,
            agent_id=self.agent_id,
            tool_call=tool_call,
            tool_result=tool_result
        )

    async def execute_round(self, max_steps: Optional[int] = None) -> ExecutionStatus:
        """
        Execute a complete round of agent execution

        Args:
            max_steps: Maximum number of steps
        """
        steps = 0

        while True:
            # Check for abort before running step
            if self.is_aborted or self.abort_event.is_set():
                logger.info("Round aborted by user")
                raise asyncio.CancelledError("Execution aborted by user")

            try:
                # Use error handler context manager for execution step
                async with self.error_handler.handle_execution_step(step_number=steps):
                    # Run one step
                    status = await self.execute_step()
                    steps += 1

                    # Check if more steps are needed
                    if status == ExecutionStatus.COMPLETED:
                        logger.info(f"Round completed after {steps} steps")
                        return status
                    elif status == ExecutionStatus.ABORTED:
                        logger.info(f"Round aborted after {steps} steps")
                        return status
                    elif status == ExecutionStatus.ERROR:
                        logger.error(f"Round failed after {steps} steps")
                        return status
                    # Check max steps limit
                    if max_steps is not None and steps >= max_steps:
                        logger.warning(f"Max steps ({max_steps}) reached")
                        return ExecutionStatus.LIMIT_EXCEEDED
            except AgentError as e:
                logger.error(f"Execution step failed with {e.error_type}: {e.message}")
                return ExecutionStatus.ERROR
            except asyncio.CancelledError:
                return ExecutionStatus.ABORTED

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
        # Reset abort state for new execution
        if not message:
            return ExecutionResult(status=ExecutionStatus.SKIPPED)

        self.is_aborted = False
        self.abort_event.clear()

        try:
            await self._setup_execution_context(message, from_agent)
            status = await self.execute_round(max_steps)
            result = ExecutionResult(status=status)

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

        await self.process_turn_end(result)
        return result

    async def process_turn_end(self, result: ExecutionResult) -> bool:
        await self.communicator.send_turn_end(
            turn_id=self.turn_id, subscription=self.session_id
        )
        if result.status == ExecutionStatus.COMPLETED:
            message = "Turn completed successfully"
        elif result.status == ExecutionStatus.ABORTED:
            message = "Turn aborted by user"
        elif result.status == ExecutionStatus.LIMIT_EXCEEDED:
            message = "Turn step limit exceeded"
            await self.communicator.send_error(
                message, subscription=self.session_id
            )
        elif result.status == ExecutionStatus.ERROR:
            message = "Turn failed"
            error_message = result.message
            await self.communicator.send_error(
                error_message, subscription=self.session_id
            )

        return await self.session_manager.save_turn_end(
            turn_id=self.turn_id,
            agent_id=self.agent_id,
            message=message
        )

    async def _setup_execution_context(
        self, message: Message, from_agent: Optional[bool] = False
    ):
        """
        Set up execution context for a new turn

        Args:
            message: The message to process
        """
        await self._ensure_session()

        # Start new turn
        turn_id = await self.session_manager.start_turn(self.agent_id)
        self.turn_id = turn_id

        user_message = self._parse_message(message)
        message_content = user_message.get("content")
        logger.info(f"Processing user message: {message_content[:50]}...")
        await self.communicator.send_turn_start(
            turn_id=turn_id,
            turn_description=f"Processing user message: {message_content[:50]}...",
            subscription=self.session_id,
        )

        message.data["from_agent"] = from_agent
        await self.session_manager.save_message(
            role=MessageRole.USER,
            content=json.dumps(user_message, ensure_ascii=False),
            message_type=MessageType.USER_MESSAGE,
            turn_id=turn_id,
            agent_id=self.agent_id,
            data=message.data,
        )

        # Add to context history
        await self.context.add_message(user_message)

    def _parse_message(self, message: Message) -> dict:
        """
        将内部 Message 对象解析为 LLM 需要的消息格式

        Args:
            message: 内部消息对象

        Returns:
            LLM 消息格式的字典，包含 role 和 content 字段
            对于 tool_call 消息，还包含 tool_calls 字段
        """
        if message.message_type == MessageType.USER_MESSAGE:
            content = message.data.get("content", "")
            files = message.data.get("files")
            if files:
                file_info_parts = []
                for file in files:
                    file_url = file.get("url", "")
                    file_type = file.get("type", "")
                    file_info = f"文件类型：{file_type}\n文件链接：{file_url}"
                    file_info_parts.append(file_info)

                if file_info_parts:
                    files_section = "\n\n[附件文件]:\n" + "\n".join(file_info_parts)
                    content = content + files_section
        elif message.message_type == MessageType.TASK_START:
            content = message.data.get("task_description")
        elif message.message_type == MessageType.TASK_COMPLETE:
            content = message.data.get("result")
        elif message.message_type == MessageType.TASK_ERROR:
            content = message.data.get("error_message")

        return {"role": "user", "content": content}

    async def _ensure_session(self, workspace: str | None = None):
        """Ensure session exists, create if not"""
        if not self.session_id:
            # Try to get session_id from session_manager
            if not self.session_manager.session_id:
                await self.session_manager.create_session(workspace=workspace)
            self.session_id = self.session_manager.session_id

    def abort(self):
        """
        Abort the execution

        This method sets the abort flag to stop execution
        """
        logger.info("Aborting execution engine")
        self.is_aborted = True
        self.abort_event.set()

    def reset(self):
        """
        Reset execution state

        Clears abort state and resets execution flags
        """
        self.is_aborted = False
        self.abort_event.clear()
        self.turn_id = None
        self.agent_id = None
        self.session_id = None
