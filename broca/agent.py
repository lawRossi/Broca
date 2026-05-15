"""
Agent Module

This module defines the core Agent class, which encapsulates the agent's behavior and functionality.
"""

import asyncio
import uuid
from typing import Any, Dict, List, Optional

from broca.agent_configs import AgentConfig
from broca.comm.agent_communicator import AgentCommunicator
from broca.context import Context
from broca.error_handler import ErrorHandler
from broca.execution_engine import ExecutionEngine, ExecutionResult, ExecutionStatus
from broca.llm import LLMClient
from broca.logging_config import get_logger
from broca.permission_manager import PermissionManager
from broca.session import Message, MessageRole, MessageType, SessionManager
from broca.session.revert_service import SessionRevertService
from broca.tools.tool_manager import ToolManager

logger = get_logger(__name__)


class Agent:
    """Base Agent class with core functionality"""

    STATUS_IDEL = "idle"
    STATUS_RUNNING = "running"
    STATUS_DISCONNECTED = "disconnected"

    def __init__(
        self,
        config: AgentConfig,
        llm_client: LLMClient,
        session_manager: SessionManager,
        **kwargs,
    ):
        self.config = config
        self.llm_client = llm_client
        self.session_manager = session_manager
        self.agent_id = kwargs.get("agent_id") or uuid.uuid4().hex
        self.name = config.name
        self.role = config.role
        self.status = self.STATUS_DISCONNECTED
        self.revert_service = SessionRevertService(
            self.session_manager, self.config.workspace
        )

        self.session_id: Optional[str] = session_manager.session_id
        self.turn_id: Optional[str] = None

        # LLM usage statistics (loaded from database)
        self.total_input_tokens: int = 0
        self.total_output_tokens: int = 0
        self.total_llm_calls: int = 0
        self.last_context_length: Optional[int] = None

        # Initialize core components
        self._setup_context(**kwargs)
        self._setup_tools()
        self._setup_communicator()
        self._setup_session_memory()
        self._setup_execution_engine()
        self._setup_permission_manager()

        self.message_queue: asyncio.Queue = asyncio.Queue(3)
        self.error_handler = ErrorHandler()

        self._abort_task: Optional[asyncio.Task] = None
        self.running = False

        asyncio.create_task(self.load_stats(session_manager))

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

    async def _set_status(self, new_status: str) -> None:
        """更新 Agent 运行状态，同时持久化到数据库

        Args:
            new_status: 新状态 (idle / running / disconnected)
        """
        self.status = new_status
        try:
            await self.session_manager.agent_service.update_agent_status(
                self.agent_id, new_status
            )
        except Exception as e:
            logger.warning(f"Failed to persist agent status {new_status}: {e}")

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
        self.context = Context(self.config, self.session_manager, **kwargs)

    def _setup_tools(self):
        """Set up tools for the agent, including auto-discovered built-in tools
        and custom tools from {workspace}/.broca/tool.py."""
        tool_manager = ToolManager()
        tool_manager.load_custom_tools(self.config.workspace)
        tools = tool_manager.get_tools(tool_names=self.config.tools)
        self.tools = [tool.format() for tool in tools]
        self.tool_mapping = {tool.name: tool for tool in tools}

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

    def _setup_session_memory(self):
        """Set up session memory manager"""
        if not self.config.track_session_momory:
            self.session_memory_manager = None
            return

        logger.debug("Initializing session memory manager")

        from broca.session_memory import SessionMemoryManager

        self.session_memory_manager = SessionMemoryManager(
            workspace=self.config.workspace,
            agent=self,
            config=self.config.session_memory_config,
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
            session_memory_manager=self.session_memory_manager,
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

    async def _handle_undo_redo_command(self, message: Message):
        """
        Handle undo/redo command

        Args:
            message: Command message with undo/redo details
        """
        if self.status == self.STATUS_RUNNING:
            logger.error("Agent is already running")
            await self.communicator.send_command_result(
                command=message.data.get("command"),
                result={"code": 1, "message": "Agent is already running"},
                subscription=self.session_id,
            )
            return

        command = message.data.get("command")
        session_id = self.session_id

        if not session_id:
            logger.error("No session ID available for undo/redo")
            await self.communicator.send_error(
                "No active session for undo/redo operation", subscription=session_id
            )
            return

        try:
            if command == "undo":
                # 获取撤销参数
                arguments = message.data.get("arguments", {})
                target_message_id = arguments.get("target_message_id")
                level = arguments.get("level", "step")

                # 执行撤销
                result = await self.revert_service.undo(
                    session_id=session_id,
                    agent_id=self.agent_id,
                    target_message_id=target_message_id,
                    level=level,
                )

                if result.get("success"):
                    # 发送成功消息
                    diff_summary = result.get("diff_summary", {})
                    files_changed = diff_summary.get("total_files", 0)

                    # 重建context
                    await self.context.build_history_from_session(self.agent_id)

                    await self.communicator.send_command_result(
                        command="undo",
                        result={
                            "code": 0,
                            "message": f"Undo successful, {files_changed} files changed",
                        },
                        subscription=session_id,
                    )
                else:
                    await self.communicator.send_command_result(
                        command="undo",
                        result={
                            "code": 1,
                            "message": f"Undo failed: {result.get('message', 'Unknown error')}",
                        },
                        subscription=session_id,
                    )

            elif command == "redo":
                # 执行重做
                result = await self.revert_service.redo(
                    session_id=session_id, agent_id=self.agent_id
                )

                if result.get("success"):
                    # 重建context
                    await self.context.build_history_from_session(self.agent_id)
                    await self.communicator.send_command_result(
                        command="redo",
                        result={"code": 0, "message": "Redo successful"},
                        subscription=session_id,
                    )
                else:
                    await self.communicator.send_command_result(
                        command="redo",
                        result={
                            "code": 1,
                            "message": f"Redo failed: {result.get('message', 'Unknown error')}",
                        },
                        subscription=session_id,
                    )

        except Exception as e:
            logger.error(f"Error handling {command} command: {e}")
            await self.communicator.send_command_result(
                command=command,
                result={"code": 1, "message": f"Error handling {command} command: {e}"},
                subscription=session_id,
            )

    def stop(self):
        self.running = False

    async def start(self):
        self.running = True

        while self.running:
            try:
                if not self.is_connected():
                    if not await self.connect():
                        logger.error("Failed to connect to server")
                        self.running = False
                        break
                message = await asyncio.wait_for(self.message_queue.get(), timeout=1)
                if message.message_type == MessageType.USER_MESSAGE:
                    await self.run(message)
                elif message.message_type == MessageType.TASK_START:
                    await self._handle_task(message)
                elif message.message_type in [
                    MessageType.TASK_COMPLETE,
                    MessageType.TASK_ERROR,
                ]:
                    await self.run(message, from_agent=True)
            except asyncio.TimeoutError:
                continue

    async def run(
        self,
        message: Message,
        max_steps: Optional[int] = None,
        from_agent: Optional[bool] = False,
        allowed_tools: Optional[List[str]] = None,
    ) -> ExecutionResult:
        """
        Run agent in async mode (replaces command-line interaction)

        This method delegates execution to the execution engine,
        handling high-level execution control and cleanup.

        Args:
            message: The message to process
            max_steps: Maximum number of steps
            from_agent: Whether the message is from another agent
            allowed_tools: Optional list of tool names that are allowed to be called.
                           If provided, any tool not in this list will be skipped
                           with a "this tool is currently not allowed" result.

        Returns:
            ExecutionResult: Result of the execution with status and details
        """
        # Store the current execution task for potential cancellation
        self._abort_task = asyncio.current_task()
        await self._set_status(self.STATUS_RUNNING)

        # Clear undo meta info
        self.revert_service.undo_meta_info = {}

        # Set allowed_tools on execution engine before execution
        self.execution_engine.allowed_tools = allowed_tools

        try:
            return await self.execution_engine.execute(message, max_steps, from_agent)
        except Exception as e:
            logger.error(f"Error in run: {e}")
            return ExecutionResult(
                status=ExecutionStatus.ERROR,
                message=f"Failed to start execution: {e}",
                error=str(e),
            )
        finally:
            # Reset allowed_tools to avoid affecting subsequent runs
            self.execution_engine.allowed_tools = None
            # Clean up
            if not self.config.save_history:
                await self.reset()
            self._abort_task = None
            await self._set_status(self.STATUS_IDEL)

    async def _handle_task(self, message: Message) -> None:
        """Handle task assignment from another agent"""
        try:
            task_id = message.data.get("task_id")
            assigner = message.data.get("assigner")
            execution_result = await self.run(message, from_agent=True)

            # Check execution status
            if execution_result.status == ExecutionStatus.COMPLETED:
                msg = self.context.get_latest_assistant_message()
                result = f"Message from agent {self.name}: {msg}"
                logger.info(f"send result to {assigner}")
                await self.communicator.send_task_complete(task_id, result, assigner)
            elif execution_result.status == ExecutionStatus.ABORTED:
                result = f"The agent {self.agent_id} execution was aborted by user"
                logger.warning(result)
            elif execution_result.status in (
                ExecutionStatus.ERROR,
                ExecutionStatus.DEAD_LOOP,
            ):
                result = f"The agent {self.agent_id} failed to finish the task: {execution_result.message or execution_result.error}"
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
        self.execution_engine.reset()
        await self.permission_manager.reset()
        self.turn_id = None
        await self._set_status(self.STATUS_IDEL)

    async def subscribe(self, subscription: str):
        """Subscribe to channel"""
        await self.communicator.subscribe(subscription)

    async def unsubscribe(self, subscription: str):
        """Unsubscribe from channel"""
        await self.communicator.unsubscribe(subscription)

    def is_connected(self) -> bool:
        """Check if connected to server"""
        return self.communicator.is_connected()

    async def connect(self) -> bool:
        """Connect to server"""
        connected = await self.communicator.connect()
        if connected:
            await self._set_status(self.STATUS_IDEL)
            return True
        else:
            await self._set_status(self.STATUS_DISCONNECTED)
            return False

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

        self.execution_engine.abort()
        if self._abort_task and not self._abort_task.done():
            logger.info("Cancelling execution task...")
            try:
                self._abort_task.cancel()
            except Exception as e:
                logger.error(f"Failed to cancel execution task: {e}")
            finally:
                self._abort_task = None
        await self._set_status(self.STATUS_IDEL)

    async def _on_command(self, message: Message):
        """
        Handle command from Socket.io

        This method is called when a command is received via the command channel.
        """
        command = message.data.get("command")
        logger.info(f"Received command: {command}")

        await self.session_manager.save_message(
            role=MessageRole.SYSTEM,
            content=command,
            message_type=MessageType.COMMAND,
            turn_id=self.turn_id,
            agent_id=self.agent_id,
        )

        if command == "abort":
            logger.info("Received abort command from user")
            await self.abort()
        elif command in ["undo", "redo"]:
            await self._handle_undo_redo_command(message)

    async def disconnect(self):
        """Disconnect from server"""
        await self.communicator.disconnect()
        await self._set_status(self.STATUS_DISCONNECTED)

    async def restore_from_session(self, agent_id):
        """Restore agent state from session"""
        await self.context.build_history_from_session(agent_id)
