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
from broca.error_handler import AgentError, ErrorHandler
from broca.llm import LLMClient
from broca.session import MessageRole, MessageType, SessionManager
from broca.tools.tool import ToolCallContext, ToolResult, ToolStatus


class ExecutionStatus(str, Enum):
    """Agent execution status enumeration"""

    RUNNING = "running"
    PENDING = "pending"
    COMPLETED = "completed"
    ERROR = "error"
    ABORTED = "aborted"


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
        # Check for abort before starting step
        if self.is_aborted or self.abort_event.is_set():
            logger.info("Agent execution aborted")
            return ExecutionStatus.ABORTED

        errors = 0

        # Try LLM call with retries
        while errors < 3:
            # Check for abort during LLM call
            if self.is_aborted or self.abort_event.is_set():
                logger.info("Agent execution aborted during LLM call")
                return ExecutionStatus.ABORTED

            try:
                # Use error handler context manager for LLM call
                async with self.error_handler.handle_llm_call(context="execute_step"):
                    # Call LLM with timeout for cancellation support
                    response = await asyncio.wait_for(self._call_llm(), timeout=180)
                    break
            except AgentError as e:
                errors += 1
                if errors > 2:
                    logger.error(f"Too many errors ({e.error_type}), aborting...")
                    return ExecutionStatus.ERROR
            except asyncio.CancelledError:
                logger.info("Agent execution cancelled by user during LLM call")
                return ExecutionStatus.ABORTED

        # Add response to history
        await self.context.add_message(response)

        # Send response via communication channel
        await self._send_agent_response(response)

        # Save response to database
        await self._save_agent_response(response)

        # Process tool calls if any
        if not response.tool_calls:
            return ExecutionStatus.COMPLETED
        else:
            await self._process_tool_calls(response.tool_calls)

        if self.is_aborted or self.abort_event.is_set():
            logger.info("Agent execution aborted after tool calls")
            return ExecutionStatus.ABORTED

        return ExecutionStatus.RUNNING

    async def _call_llm(self) -> LLMMessage:
        """
        Call LLM with current context

        Returns:
            LLM response message
        """
        return await self.llm_client.get_response(
            self.config.provider,
            self.config.model,
            self.context.history,
            self._get_tools_list(),
        )

    def _get_tools_list(self) -> List[Dict[str, Any]]:
        """
        Get formatted tools list for LLM

        Returns:
            List of formatted tools
        """
        return [tool.format() for tool in self.tool_mapping.values()]

    async def _send_agent_response(self, response: LLMMessage):
        """
        Send agent response via communication channel

        Args:
            response: LLM response message
        """
        content = response.content
        if content:
            content = content.strip()

        reasoning_content = response.get("reasoning_content")
        if reasoning_content:
            reasoning_content = reasoning_content.strip()

        if content or reasoning_content:
            try:
                # Use the same JSON format as database save for consistency
                response_data = response.json()
                await self.communicator.send_agent_response(
                    content=json.dumps(response_data, ensure_ascii=False),
                    reasoning_content=None,
                    subscription=self.session_id,
                )
            except Exception as e:
                logger.error(f"Failed to send agent response: {e}")

    async def _save_agent_response(self, response: LLMMessage):
        """
        Save agent response to database

        Args:
            response: LLM response message
        """
        if self.turn_id:
            try:
                msg_content = json.dumps(response.json(), ensure_ascii=False)
                await self.session_manager.save_message(
                    role=MessageRole.ASSISTANT,
                    content=msg_content,
                    message_type=MessageType.AGENT_RESPONSE,
                    turn_id=self.turn_id,
                    agent_id=self.agent_id,
                )
            except Exception as save_error:
                logger.error(f"Failed to save agent response: {save_error}")

    async def _process_tool_calls(self, tool_calls: List[Any]):
        """
        Process tool calls from LLM response

        Args:
            tool_calls: List of tool calls from LLM
        """
        context = ToolCallContext()
        context.agent = self.agent
        context.workspace = self.config.workspace

        for tool_call in tool_calls:
            # Check for abort before processing each tool call
            if self.is_aborted or self.abort_event.is_set():
                logger.info("Agent execution aborted during tool call processing")
                return

            tool_name = tool_call.function.name
            arguments = tool_call.function.arguments

            if tool_name not in self.tool_mapping:
                logger.error(f"Tool '{tool_name}' not found.")
                tool_result = ToolResult(
                    status=ToolStatus.ERROR, content=f"Tool {tool_name} not found"
                )
            else:
                logger.debug(
                    f"Executing tool '{tool_name}', arguments: {arguments[:50]}..."
                )
                try:
                    # Send tool call notification
                    await self.communicator.send_tool_call(
                        tool_name=tool_name,
                        arguments=arguments,
                        tool_call_id=tool_call.id,
                        subscription=self.session_id,
                    )

                    # Use error handler context manager for tool execution
                    async with self.error_handler.handle_tool_execution(
                        tool_name=tool_name, context="tool_call_processing"
                    ):
                        # Execute tool asynchronously with timeout
                        tool_result = await asyncio.wait_for(
                            self.tool_mapping[tool_name].execute(arguments, context),
                            timeout=60,
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
                    return

            # Create tool call result
            tool_call_result = {
                "role": "tool",
                "tool_call_id": tool_call.id,
                "content": tool_result.content,
            }

            # Save tool result to database
            await self._save_tool_result(
                tool_name, arguments, tool_call.id, tool_result, tool_call_result
            )

            # Add to history
            await self.context.add_message(tool_call_result)

    async def _save_tool_result(
        self,
        tool_name: str,
        arguments: str,
        tool_call_id: str,
        tool_result: ToolResult,
        tool_call_result: Dict[str, Any],
    ):
        """
        Save tool execution result to database

        Args:
            tool_name: Name of the tool
            arguments: Tool arguments
            tool_call_id: Tool call ID
            tool_result: Tool execution result
            tool_call_result: Formatted tool call result
        """
        if self.turn_id:
            try:
                # Send tool call result
                await self.communicator.send_tool_call(
                    tool_name=tool_name,
                    arguments=arguments,
                    tool_call_id=tool_call_id,
                    result=tool_result.content,
                    status=tool_result.status,
                    subscription=self.session_id,
                )

                # Save to database
                await self.session_manager.save_message(
                    role=MessageRole.TOOL,
                    content=None,  # content is in data field
                    message_type=MessageType.TOOL_CALL,
                    turn_id=self.turn_id,
                    agent_id=self.agent_id,
                    data={
                        "content": json.dumps(tool_call_result, ensure_ascii=False),
                        "action": "result",
                        "tool_name": tool_name,
                        "arguments": arguments,
                        "result": tool_result.content,
                        "status": tool_result.status,
                    },
                )
            except Exception as save_error:
                logger.error(f"Failed to save tool result: {save_error}")

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
                        return ExecutionStatus.COMPLETED

            except AgentError as e:
                logger.error(f"Execution step failed with {e.error_type}: {e.message}")
                # Error is already logged by error handler, just re-raise
                return ExecutionStatus.ERROR
            except asyncio.CancelledError as e:
                logger.info(f"Round cancelled: {e}")
                return ExecutionStatus.ABORTED

    async def execute(
        self,
        message: Optional[str] = None,
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
        self.is_aborted = False
        self.abort_event.clear()

        try:
            if message:
                # Set up execution context
                await self._setup_execution_context(message, from_agent)

                # Execute the round
                try:
                    status = await self.execute_round(max_steps)

                    # Send turn completion
                    await self._send_turn_completion()

                    return ExecutionResult(status=status)

                except asyncio.CancelledError:
                    logger.info("Execution cancelled by user")
                    await self._send_turn_cancellation()
                    return ExecutionResult(
                        status=ExecutionStatus.ABORTED,
                        message="Execution aborted by user",
                    )

                except Exception as e:
                    logger.error(f"Error during execution: {e}")
                    await self._send_turn_error(e)
                    return ExecutionResult(
                        status=ExecutionStatus.ERROR,
                        message=f"Execution failed: {e}",
                        error=str(e),
                    )

            logger.debug("No user message provided, execution skipped")

        except Exception as e:
            logger.error(f"Error in execute: {e}")
            return ExecutionResult(
                status=ExecutionStatus.ERROR,
                message=f"Failed to start execution: {e}",
                error=str(e),
            )

        # Return default result if no user message was provided
        return ExecutionResult(
            status=ExecutionStatus.COMPLETED,
            message="No user message provided, execution skipped",
        )

    async def _setup_execution_context(self, message: str, from_agent: bool = False):
        """
        Set up execution context for a new turn

        Args:
            message: The message to process
        """
        await self._ensure_session()

        # Start new turn
        turn_id = await self.session_manager.start_turn(self.agent_id)
        self.turn_id = turn_id

        # Send turn start notification
        await self.communicator.send_turn_start(
            turn_id=turn_id,
            turn_description=f"Processing user message: {message[:50]}...",
            subscription=self.session_id,
        )

        message_data = {"role": "user", "content": message}
        msg_content = json.dumps(message_data, ensure_ascii=False)

        # Save user message to database
        if not from_agent:
            await self.session_manager.save_message(
                role=MessageRole.USER,
                content=msg_content,
                message_type=MessageType.USER_MESSAGE,
                turn_id=turn_id,
                agent_id=self.agent_id,
            )

        # Add to context history
        await self.context.add_message(message_data)

    async def _ensure_session(self, workspace: str | None = None):
        """Ensure session exists, create if not"""
        if not self.session_id:
            # Try to get session_id from session_manager
            if not self.session_manager.session_id:
                await self.session_manager.create_session(workspace=workspace)
            self.session_id = self.session_manager.session_id

    async def _send_turn_completion(self):
        """Send turn completion notification"""
        try:
            await self.communicator.send_turn_end(
                turn_id=self.turn_id,
                turn_description="Turn completed successfully",
                subscription=self.session_id,
            )

            await self.session_manager.save_message(
                role=MessageRole.SYSTEM,
                content="Turn completed successfully",
                message_type=MessageType.TURN_END,
                turn_id=self.turn_id,
                agent_id=self.agent_id,
            )
        except Exception as e:
            logger.error(f"Failed to send turn completion: {e}")

    async def _send_turn_cancellation(self):
        """Send turn cancellation notification"""
        try:
            await self.communicator.send_turn_end(
                turn_id=self.turn_id,
                turn_description="Turn cancelled by user",
                subscription=self.session_id,
            )

            await self.session_manager.save_message(
                role=MessageRole.SYSTEM,
                content="Turn cancelled by user",
                message_type=MessageType.TURN_END,
                turn_id=self.turn_id,
                agent_id=self.agent_id,
            )
        except Exception as e:
            logger.error(f"Failed to send turn cancellation: {e}")

    async def _send_turn_error(self, error: Exception):
        """Send turn error notification"""
        try:
            error_message = f"Turn failed with error: {error}"
            await self.communicator.send_turn_end(
                turn_id=self.turn_id,
                turn_description=error_message,
                subscription=self.session_id,
            )

            await self.session_manager.save_message(
                role=MessageRole.SYSTEM,
                content=error_message,
                message_type=MessageType.ERROR,
                turn_id=self.turn_id,
                agent_id=self.agent_id,
            )
        except Exception as e:
            logger.error(f"Failed to send turn error: {e}")

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
