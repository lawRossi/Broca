"""
Refactored Agent Module

This is the refactored version of agent.py with modular architecture:
- Execution logic moved to execution_engine.py
- Permission management moved to permission_manager.py
- Error handling unified in error_handler.py
- Core agent responsibilities remain here
"""

import asyncio
import uuid
from typing import Any, Dict, Optional

from loguru import logger

from broca.agent_configs import AgentConfig
from broca.comm.agent_communicator import AgentCommunicator
from broca.context import Context
from broca.error_handler import ErrorHandler
from broca.execution_engine import ExecutionEngine, ExecutionResult, ExecutionStatus
from broca.llm import LLMClient
from broca.permission_manager import PermissionManager
from broca.session import Message, MessageRole, MessageType, SessionManager
from broca.tools.tool_manager import ToolManager


class Agent:
    """Base Agent class with core functionality"""

    def __init__(self, config: AgentConfig, llm_client: LLMClient, **kwargs):
        self.config = config
        self.llm_client = llm_client
        self.agent_id = kwargs.get("agent_id") or uuid.uuid4().hex
        self.name = config.name
        self.role = config.role

        # LLM usage statistics (loaded from database)
        self.total_input_tokens: int = 0
        self.total_output_tokens: int = 0
        self.total_llm_calls: int = 0
        self.last_context_length: Optional[int] = None

        # Initialize core components
        self._setup_context(**kwargs)
        self._setup_tools()
        self._setup_logger()

        # Initialize error handler
        self.error_handler = ErrorHandler()

    async def load_stats(self, session_manager: SessionManager) -> None:
        """Load statistics from database"""
        try:
            agent = await session_manager.agent_service.get(self.agent_id)
            if agent:
                self.total_input_tokens = agent.total_input_tokens or 0
                self.total_output_tokens = agent.total_output_tokens or 0
                self.total_llm_calls = agent.total_llm_calls or 0
                self.last_context_length = agent.last_context_length
                logger.info(
                    f"Loaded stats for agent {self.agent_id}: "
                    f"calls={self.total_llm_calls}, "
                    f"input={self.total_input_tokens}, "
                    f"output={self.total_output_tokens}"
                )
        except Exception as e:
            logger.warning(f"Failed to load agent stats: {e}")

    async def update_stats(
        self, input_tokens: int, output_tokens: int, session_manager: SessionManager
    ) -> None:
        """Update statistics and persist to database"""
        self.total_input_tokens += input_tokens
        self.total_output_tokens += output_tokens
        self.total_llm_calls += 1
        self.last_context_length = input_tokens + output_tokens

        # Persist to database
        try:
            await session_manager.agent_service.update(
                self.agent_id,
                total_input_tokens=self.total_input_tokens,
                total_output_tokens=self.total_output_tokens,
                total_llm_calls=self.total_llm_calls,
                last_context_length=self.last_context_length,
            )
            logger.debug(
                f"Saved stats for agent {self.agent_id}: "
                f"total_calls={self.total_llm_calls}"
            )
        except Exception as e:
            logger.error(f"Failed to save agent stats: {e}")

    def get_stats(self) -> Dict[str, Any]:
        """Get current statistics"""
        return {
            "agent_id": self.agent_id,
            "total_input_tokens": self.total_input_tokens,
            "total_output_tokens": self.total_output_tokens,
            "total_llm_calls": self.total_llm_calls,
            "last_context_length": self.last_context_length,
        }

    def _setup_context(self, **kwargs) -> None:
        """Set up agent context"""
        self.context = Context(self.config, **kwargs)

    def _setup_tools(self):
        """Set up tools for the agent"""
        tool_manager = ToolManager()
        tools = tool_manager.get_tools(tool_names=self.config.tools)
        self.tools = [tool.format() for tool in tools]
        self.tool_mapping = {tool.name: tool for tool in tools}

    def _setup_logger(self):
        """Set up logger for the agent"""
        logger.remove()
        logger.add(self.config.log_file, level="INFO")

    def reset(self):
        """Reset agent state"""
        # Base implementation - can be overridden by subclasses
        pass


class SocketIOAgent(Agent):
    """
    Socket.io-enabled Agent (Refactored)

    This agent uses Socket.io for communication with modular architecture:
    - Execution logic in ExecutionEngine
    - Permission management in PermissionManager
    - Error handling in ErrorHandler
    """

    def __init__(
        self,
        config: AgentConfig,
        llm_client: LLMClient,
        session_manager: SessionManager,
        **kwargs,
    ):
        # Save session_manager reference before calling super().__init__
        # because parent class may need it for stats loading
        self.session_manager = session_manager

        # Call parent initialization
        super().__init__(config, llm_client, **kwargs)

        self.session_id: Optional[str] = session_manager.session_id
        self.turn_id: Optional[str] = None

        # Initialize modular components
        self._setup_communicator()
        self._setup_execution_engine()
        self._setup_permission_manager()

        # Message queue for async communication
        self.message_queue: asyncio.Queue = asyncio.Queue(3)

        # Abort control
        self.abort_event = asyncio.Event()
        self.is_aborted = False
        self._abort_task: Optional[asyncio.Task] = None

        # Async load statistics from database (non-blocking)
        asyncio.create_task(self.load_stats(session_manager))

    def _setup_communicator(self):
        """Set up communication interface"""
        self.communicator = AgentCommunicator(
            agent_id=self.agent_id,
            server_url=self.config.server_url,
            client_type="agent",
        )

        # Set up callbacks
        self.communicator.register_event_handler("user_message", self._receive_message)
        self.communicator.register_event_handler("task_start", self._receive_message)
        self.communicator.register_event_handler("task_complete", self._receive_message)
        self.communicator.register_event_handler("task_error", self._receive_message)
        self.communicator.register_event_handler("error", self._on_error)
        self.communicator.register_event_handler("command", self._on_command)
        self.communicator.register_event_handler(
            "permission_response", self._on_permission_response
        )

        from broca.tools.agent_interaction import AskUserToolManager

        self.communicator.register_event_handler(
            "user_answer", AskUserToolManager.handle_user_answer
        )

    def _setup_execution_engine(self):
        """Set up execution engine"""
        self.execution_engine = ExecutionEngine(
            agent=self,
            llm_client=self.llm_client,
            context=self.context,
            tool_mapping=self.tool_mapping,
            config=self.config,
            communicator=self.communicator,
            session_manager=self.session_manager,
        )

    def _setup_permission_manager(self):
        """Set up permission manager"""
        self.permission_manager = PermissionManager(
            communicator=self.communicator,
            session_manager=self.session_manager,
        )

    async def _receive_message(self, message: Message):
        """Receive message from communication channel"""
        logger.info(f"Received message {message.message_type}")
        await self.message_queue.put(message)

    async def _on_error(self, message: Message):
        """Handle error from Socket.io"""
        # Error handling is now centralized in ErrorHandler
        pass

    async def ask_for_permission(self, message: str) -> bool:
        """
        Ask for user permission via communication channel

        Args:
            message: Permission request message

        Returns:
            True if permission is granted, False otherwise
        """
        # Update permission manager state
        self.permission_manager.set_state(
            turn_id=self.turn_id,
            agent_id=self.agent_id,
            session_id=self.session_id,
        )

        # Use permission manager to handle the request
        async with self.error_handler.handle_permission_request():
            return await self.permission_manager.request_permission(message)

    async def _on_permission_response(self, message: Message):
        """
        Handle permission response from Socket.io

        Args:
            message: Permission response message
        """
        await self.permission_manager.handle_permission_response(message)

    def stop(self):
        self.running = False

    async def run(self):
        self.running = True

        while self.running:
            try:
                message = await asyncio.wait_for(self.message_queue.get(), timeout=1)
                if message.message_type == MessageType.USER_MESSAGE:
                    await self.run_async(message)
                elif message.message_type == MessageType.TASK_START:
                    await self._handle_task(message)
                elif message.message_type in [
                    MessageType.TASK_COMPLETE,
                    MessageType.TASK_ERROR,
                ]:
                    await self.run_async(message, from_agent=True)
            except asyncio.TimeoutError:
                continue

    async def run_async(
        self,
        message: Message,
        max_steps: Optional[int] = None,
        from_agent: Optional[bool] = False,
    ) -> ExecutionResult:
        """
        Run agent in async mode (replaces command-line interaction)

        This method delegates execution to the execution engine,
        handling high-level execution control and cleanup.

        Args:
            user_message: Optional user message
            max_steps: Maximum number of steps

        Returns:
            ExecutionResult: Result of the execution with status and details
        """
        # Store the current execution task for potential cancellation
        self._abort_task = asyncio.current_task()

        try:
            # Update execution engine state
            self.execution_engine.set_execution_state(
                turn_id=self.turn_id,
                agent_id=self.agent_id,
                session_id=self.session_id,
                is_aborted=self.is_aborted,
            )

            # Update error handler context
            self.error_handler.set_context(
                turn_id=self.turn_id,
                agent_id=self.agent_id,
                session_manager=self.session_manager,
            )

            # Delegate execution to execution engine
            return await self.execution_engine.execute(message, max_steps, from_agent)

        except Exception as e:
            logger.error(f"Error in run_async: {e}")
            return ExecutionResult(
                status=ExecutionStatus.ERROR,
                message=f"Failed to start execution: {e}",
                error=str(e),
            )
        finally:
            # Clean up
            if not self.config.save_history:
                await self.reset()

            self._abort_task = None

    async def _handle_task(self, message: Message) -> None:
        """Handle task assignment from another agent"""
        try:
            task_id = message.data.get("task_id")
            assigner = message.data.get("assigner")
            execution_result = await self.run_async(message, from_agent=True)

            # Check execution status
            if execution_result.status == ExecutionStatus.COMPLETED:
                msg = self.context.get_latest_assistant_message()
                result = f"Message from agent {self.name}: {msg}"
                logger.info(f"send result to {assigner}")
                await self.communicator.send_task_complete(task_id, result, assigner)
            elif execution_result.status == ExecutionStatus.ABORTED:
                result = f"The agent {self.agent_id} execution was aborted by user"
                logger.warning(result)
            elif execution_result.status == ExecutionStatus.ERROR:
                result = f"The agent {self.agent_id} failed to finish the task: {execution_result.error}"
                logger.error(result)
                await self.communicator.send_task_error(
                    task_id, result, receiver_id=assigner
                )
        except Exception as e:
            logger.error(f"Error processing task: {e}")
            result = f"The agent {self.agent_id} failed to finish the task: {e}"
            await self.communicator.send_task_error(
                task_id, result, receiver_id=assigner
            )

    async def reset(self):
        """Reset agent state"""
        super().reset()

        # Reset abort state
        self.is_aborted = False
        self.abort_event.clear()
        self._abort_task = None

        # Reset modular components
        self.execution_engine.reset()
        await self.permission_manager.reset()

        # Reset state variables
        self.turn_id = None

    async def subscribe(self, subscription: str):
        """Subscribe to channel"""
        await self.communicator.subscribe(subscription)

    async def unsubscribe(self, subscription: str):
        """Unsubscribe from channel"""
        await self.communicator.unsubscribe(subscription)

    def is_connected(self) -> bool:
        """Check if connected to server"""
        return self.communicator.is_connected()

    async def connect(self):
        """Connect to server"""
        await self.communicator.connect()

    async def on_llm_call_completed(self, input_tokens: int, output_tokens: int):
        """
        Callback for ExecutionEngine when LLM call completes.
        Updates and persists statistics.

        Args:
            input_tokens: Number of input tokens used
            output_tokens: Number of output tokens generated
        """
        await self.update_stats(input_tokens, output_tokens, self.session_manager)

    async def abort(self):
        """
        Abort the agent execution

        This method sets the abort flag and cancels the current execution task.
        """
        logger.info("Aborting agent execution")
        self.is_aborted = True
        self.abort_event.set()

        # Abort execution engine
        self.execution_engine.abort()

        # Cancel the current execution task if it exists
        if self._abort_task and not self._abort_task.done():
            logger.info("Cancelling execution task...")
            self._abort_task.cancel()
            # Wait a bit for the task to be cancelled gracefully
            try:
                await asyncio.wait_for(asyncio.shield(self._abort_task), timeout=2)
            except asyncio.CancelledError:
                logger.info("Task cancelled successfully")
            except asyncio.TimeoutError:
                logger.warning("Task cancellation timed out, forcing abort")
            except Exception as e:
                logger.warning(f"Error during task cancellation: {e}")
            finally:
                self._abort_task = None

    async def _on_command(self, message: Message):
        """
        Handle command from Socket.io

        This method is called when a command is received via the command channel.
        """
        command = message.data.get("command")
        logger.info(f"Received command: {command}")

        if self.turn_id:
            try:
                await self.session_manager.save_message(
                    role=MessageRole.SYSTEM,
                    content=command,
                    message_type=MessageType.COMMAND,
                    turn_id=self.turn_id,
                    agent_id=self.agent_id,
                )
            except Exception as save_error:
                logger.error(f"Failed to save command: {save_error}")

        if command == "abort":
            logger.info("Received abort command from user")
            await self.abort()

    async def disconnect(self):
        """Disconnect from server"""
        await self.communicator.disconnect()

    async def restore_from_session(self, agent_id):
        """Restore agent state from session"""
        await self.context.build_history_from_session(self.session_manager, agent_id)
