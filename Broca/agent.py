import asyncio
import json
import logging
import traceback
import uuid
from typing import Optional

from litellm import Message as LLMMessage
from loguru import logger

from Broca.agent_configs import AgentConfig
from Broca.comm.agent_communicator import AgentCommunicator
from Broca.comm.message_types import Message
from Broca.context import Context
from Broca.llm import LLMClient
from Broca.session import MessageRole, MessageType, SessionManager
from Broca.tools.tool import ToolCallContext
from Broca.tools.tool_manager import ToolManager

# Standard logger for non-agent operations
std_logger = logging.getLogger(__name__)


class Agent:
    def __init__(self, config: AgentConfig, llm_client: LLMClient, **kwargs):
        self.config = config
        self.llm_client = llm_client
        self._setup_context(**kwargs)
        self._setup_tools()
        self._setup_logger()
        self.agent_id = kwargs.get("agent_id") or uuid.uuid4().hex
        self.name = kwargs.get("name")
        self.role = kwargs.get("role")

    def _setup_context(self, **kwargs) -> None:
        self.context = Context(self.config, **kwargs)

    def _setup_tools(self):
        tool_manager = ToolManager()
        tools = tool_manager.get_tools(tool_names=self.config.tools)
        self.tools = [tool.format() for tool in tools]
        self.tool_mapping = {tool.name: tool for tool in tools}

    def _setup_logger(self):
        logger.remove()
        logger.add(self.config.log_file, level="DEBUG")

    async def _call_llm(self, context: Context) -> LLMMessage:
        message = await self.llm_client.get_response(
            context.history, self.tools, self.config.llm_config_name
        )
        return message


class SocketIOAgent(Agent):
    """
    Socket.io-enabled Agent

    This agent uses Socket.io for communication instead of command-line interaction.
    It supports multi-endpoint communication including browser, command-line,
    VSCode plugin, and browser plugin clients.
    """

    def __init__(
        self,
        config: AgentConfig,
        llm_client: LLMClient,
        session_manager: SessionManager,
        **kwargs,
    ):
        super().__init__(config, llm_client, **kwargs)

        self.session_manager = session_manager
        self.session_id: str | None = None
        self.turn_id: str | None = None

        self._setup_communicator()

    def _setup_communicator(self):
        self.communicator = AgentCommunicator(
            agent_id=self.agent_id,
            server_url=self.config.server_url,
            client_type="agent",
        )

        # Set up callbacks
        self.communicator.register_event_handler("user_message", self._on_user_message)
        self.communicator.register_event_handler(
            "agent_response", self._on_agent_response
        )
        self.communicator.register_event_handler("error", self._on_error)
        self.communicator.register_event_handler("command", self._on_command)
        self.communicator.register_event_handler(
            "permission_response", self._on_permission_response
        )

        # Permission response tracking (thread-safe)
        self._permission_requests: dict[str, dict] = {}
        self._permission_lock = asyncio.Lock()

        # Abort control
        self.abort_event = asyncio.Event()
        self.is_aborted = False
        self._abort_task: Optional[asyncio.Task] = None

    async def _ensure_session(self):
        if not self.session_id:
            if not self.session_manager.session_id:
                await self.session_manager.create_session()
            self.session_id = self.session_manager.session_id

    async def _on_user_message(self, message: Message):
        """Handle user message from Socket.io"""
        try:
            content = message.data.get("content", "")
            if not content:
                logger.warning("Empty user message received")
                return

            # Check if there's an ongoing execution that's being aborted
            if self._abort_task and not self._abort_task.done():
                logger.warning(
                    "Previous execution is still running or being aborted, ignoring new message"
                )
                return

            await self.run_async(content, message.message_id)
        except Exception as e:
            logger.error(f"Error processing user message: {e}")
            # Save user message processing error to database
            if self.turn_id:
                try:
                    await self.session_manager.save_message(
                        role=MessageRole.SYSTEM,
                        content=f"Error processing user message: {e}",
                        message_type=MessageType.ERROR,
                        turn_id=self.turn_id,
                        agent_id=self.agent_id,
                    )
                except Exception as save_error:
                    logger.error(f"Failed to save user message error: {save_error}")

    async def _on_agent_response(self, message: Message):
        """Handle agent response from Socket.io"""
        pass

    async def _on_error(self, message: Message):
        """Handle error from Socket.io"""
        pass

    async def ask_for_permission(self, message: str) -> bool:
        """
        Ask for user permission via communication channel

        Args:
            message: Permission request message

        Returns:
            True if permission is granted, False otherwise
        """
        # Generate unique request ID
        request_id = str(uuid.uuid4())

        # Create event for waiting for response
        response_event = asyncio.Event()

        async with self._permission_lock:
            self._permission_requests[request_id] = {
                "event": response_event,
                "granted": None,
            }

        try:
            # Send permission request with request_id
            await self.communicator.send_permission_request(
                message=message,
                request_id=request_id,
                subscription=self.session_id,
            )

            if self.turn_id:
                await self.session_manager.save_message(
                    role=MessageRole.AGENT,
                    content=message,
                    message_type=MessageType.PERMISSION_REQUEST,
                    turn_id=self.turn_id,
                    agent_id=self.agent_id,
                )

            # Wait for response with timeout
            try:
                await asyncio.wait_for(response_event.wait(), timeout=60)
            except asyncio.TimeoutError:
                logger.warning(f"Permission request {request_id} timed out")
                if self.turn_id:
                    await self.session_manager.save_message(
                        role=MessageRole.SYSTEM,
                        content="Permission request timed out",
                        message_type=MessageType.ERROR,
                        turn_id=self.turn_id,
                        agent_id=self.agent_id,
                    )
                return False

            async with self._permission_lock:
                granted = self._permission_requests.get(request_id, {}).get(
                    "granted", False
                )
                if self.turn_id:
                    await self.session_manager.save_message(
                        role=MessageRole.AGENT,
                        content=f"Permission request {request_id}: {'granted' if granted else 'denied'}",
                        message_type=MessageType.PERMISSION_RESPONSE,
                        turn_id=self.turn_id,
                        agent_id=self.agent_id,
                    )
                return granted or False
        except Exception as e:
            logger.error(f"Failed to send permission request: {e}")
            if self.turn_id:
                await self.session_manager.save_message(
                    role=MessageRole.SYSTEM,
                    content=f"Failed to send permission request: {e}",
                    message_type=MessageType.ERROR,
                    turn_id=self.turn_id,
                    agent_id=self.agent_id,
                )
            return False
        finally:
            # Clean up the request
            async with self._permission_lock:
                self._permission_requests.pop(request_id, None)

    async def _on_permission_response(self, message: Message):
        """
        Handle permission response from Socket.io

        Args:
            message: Permission response message
        """
        granted = message.data.get("granted", False)
        request_id = message.data.get("request_id")

        # Find the matching permission request
        async with self._permission_lock:
            if request_id and request_id in self._permission_requests:
                request_data = self._permission_requests[request_id]
                request_data["granted"] = granted
                request_data["event"].set()

                logger.info(
                    f"Permission request {request_id}: {'granted' if granted else 'denied'}"
                )
            else:
                logger.warning(
                    f"Received permission response for unknown request_id: {request_id}"
                )

    async def run_step_async(self) -> bool:
        """
        Run one step of agent execution (async version)

        Returns:
            True if more steps are needed, False otherwise
        """
        # Check for abort before starting step
        if self.is_aborted or self.abort_event.is_set():
            logger.info("Agent execution aborted")
            return False

        need_more_steps = True
        errors = 0

        while errors < 3:
            # Check for abort during LLM call
            if self.is_aborted or self.abort_event.is_set():
                logger.info("Agent execution aborted during LLM call")
                return False
            try:
                # Call LLM with timeout for cancellation support
                response = await asyncio.wait_for(
                    self._call_llm(self.context), timeout=180
                )
                break
            except asyncio.TimeoutError:
                logger.error("LLM call timed out")
                errors += 1

                # Save timeout error to database
                if self.turn_id:
                    try:
                        await self.session_manager.save_message(
                            role=MessageRole.SYSTEM,
                            content="LLM call timed out",
                            message_type=MessageType.ERROR,
                            turn_id=self.turn_id,
                            agent_id=self.agent_id,
                        )
                    except Exception as save_error:
                        logger.error(f"Failed to save timeout error: {save_error}")

                if errors > 2:
                    logger.error("Too many timeouts, aborting...")
                    return False
            except asyncio.CancelledError:
                logger.info("Agent execution cancelled by user during LLM call")
                return False
            except Exception as e:
                logger.error(f"LLM call failed: {e}")
                errors += 1

                # Save LLM call error to database
                if self.turn_id:
                    try:
                        await self.session_manager.save_message(
                            role=MessageRole.SYSTEM,
                            content=f"LLM call failed: {e}",
                            message_type=MessageType.ERROR,
                            turn_id=self.turn_id,
                            agent_id=self.agent_id,
                        )
                    except Exception as save_error:
                        logger.error(f"Failed to save LLM error: {save_error}")

                if errors > 2:
                    logger.error("Too many errors, aborting...")
                    return False

        # Add response to history
        await self.context.add_message(response)

        # Send response via Socket.io (send_message will handle connection automatically)
        content = response.content
        if content:
            content = content.strip()
        reasoning_content = response.get("reasoning_content") or response.get(
            "reasoning_details"
        )
        if reasoning_content:
            reasoning_content = reasoning_content.strip()

        if content or reasoning_content:
            try:
                await self.communicator.send_agent_response(
                    content=content,
                    reasoning_content=reasoning_content,
                    subscription=self.session_id,
                )
            except Exception as e:
                logger.error(f"Failed to send agent response: {e}")

        if self.turn_id:
            try:
                msg_congent = json.dumps(response.json(), ensure_ascii=False)
                await self.session_manager.save_message(
                    role=MessageRole.ASSISTANT,
                    content=msg_congent,
                    message_type=MessageType.TEXT,
                    turn_id=self.turn_id,
                    agent_id=self.agent_id,
                )
            except Exception as save_error:
                logger.error(f"Failed to save agent response: {save_error}")

        if not response.tool_calls:
            need_more_steps = False
        else:
            await self._process_tool_calls_async(response.tool_calls)

        return need_more_steps

    async def _process_tool_calls_async(self, tool_calls: list):
        context = ToolCallContext()
        context.agent = self

        for tool_call in tool_calls:
            # Check for abort before processing each tool call
            if self.is_aborted or self.abort_event.is_set():
                logger.info("Agent execution aborted during tool call processing")
                return

            tool_name = tool_call.function.name
            arguments = tool_call.function.arguments
            if tool_name not in self.tool_mapping:
                logger.error(f"Tool '{tool_name}' not found.")
                result = f"Tool {tool_name} not found"
            else:
                logger.debug(
                    f"Executing tool '{tool_name}', arguments: {arguments[:50]}..."
                )
                try:
                    # Send tool call notification (send_message will handle connection automatically)
                    await self.communicator.send_tool_call(
                        tool_name=tool_name,
                        arguments=arguments,
                        subscription=self.session_id,
                    )

                    # Execute tool asynchronously with timeout for cancellation support
                    result = await asyncio.wait_for(
                        self.tool_mapping[tool_name].execute(arguments, context),
                        timeout=60,
                    )
                except asyncio.TimeoutError:
                    logger.error(f"Tool '{tool_name}' execution timed out")
                    result = f"Tool {tool_name} execution timed out"
                except asyncio.CancelledError:
                    logger.info("Tool execution cancelled by user")
                    return
                except Exception as e:
                    logger.error(f"Tool execution failed: {e}")
                    result = f"Tool execution failed: {e}"

            tool_call_result = {
                "role": "tool",
                "tool_call_id": tool_call.id,
                "content": result,
            }

            # Save tool result to database for persistence
            # This completes the tool execution record with the actual result
            if self.turn_id:
                try:
                    await self.session_manager.save_message(
                        role=MessageRole.TOOL,
                        content=json.dumps(tool_call_result, ensure_ascii=False),
                        message_type=MessageType.TOOL_RESULT,
                        turn_id=self.turn_id,
                        agent_id=self.agent_id,
                    )
                except Exception as save_error:
                    logger.error(f"Failed to save tool result: {save_error}")

            # Add to history
            await self.context.add_message(tool_call_result)

    async def run_async(
        self,
        user_message: Optional[str] = None,
        message_id: Optional[str] = None,
        max_steps: Optional[int] = None,
    ) -> None:
        """
        Run agent in async mode (replaces command-line interaction)

        This method executes complete rounds of agent execution, sending
        start and end messages for each round.

        Args:
            user_message: Optional user message
            max_steps: Maximum number of steps
        """
        # Reset abort state for new execution
        self.is_aborted = False
        self.abort_event.clear()

        # Store the current execution task for potential cancellation
        self._abort_task = asyncio.current_task()

        try:
            if user_message:
                try:
                    await self._ensure_session()

                    turn_id = await self.session_manager.start_turn(self.agent_id)
                    self.turn_id = turn_id

                    await self.communicator.send_turn_start(
                        turn_id=turn_id,
                        turn_description=f"Processing user message: {user_message[:50]}...",
                        subscription=self.session_id,
                    )

                    message = {"role": "user", "content": user_message}
                    msg_content = json.dumps(message, ensure_ascii=False)
                    await self.session_manager.save_message(
                        role=MessageRole.USER,
                        content=msg_content,
                        message_type=MessageType.TEXT,
                        turn_id=turn_id,
                        agent_id=self.agent_id,
                        message_id=message_id,
                    )

                    await self.context.add_message(message)
                except Exception as e:
                    logger.error(f"Failed to send turn start: {e}")
                    # Save turn start error to database
                    if self.turn_id:
                        try:
                            await self.session_manager.save_message(
                                role=MessageRole.SYSTEM,
                                content=f"Failed to send turn start: {e}",
                                message_type=MessageType.ERROR,
                                turn_id=self.turn_id,
                                agent_id=self.agent_id,
                            )
                        except Exception as save_error:
                            logger.error(
                                f"Failed to save turn start error: {save_error}"
                            )

                # Execute complete round
                await self._execute_round_async(max_steps)
        except asyncio.CancelledError:
            logger.info("Agent execution cancelled by user")
        except Exception as e:
            logger.error(f"Error in agent execution: {e}")
            # Save error to database
            if self.turn_id:
                try:
                    await self.session_manager.save_message(
                        role=MessageRole.SYSTEM,
                        content=f"Error in agent execution: {e}\n{traceback.format_exc()}",
                        message_type=MessageType.ERROR,
                        turn_id=self.turn_id,
                        agent_id=self.agent_id,
                    )
                except Exception as save_error:
                    logger.error(f"Failed to save execution error: {save_error}")

            # send error message (send_message will handle connection automatically)
            try:
                await self.communicator.send_agent_response(
                    content=f"Error in agent execution: {e}",
                    subscription=self.session_id,
                )
            except Exception as send_error:
                logger.error(f"Failed to send error response: {send_error}")
        finally:
            # Clear the abort task reference
            self._abort_task = None
            if self.turn_id:
                try:
                    turn_id = self.turn_id
                    self.turn_id = None
                    await self.communicator.send_turn_end(
                        turn_id=turn_id,
                        result="Turn completed",
                        subscription=self.session_id,
                    )
                    await self.session_manager.end_turn(turn_id, self.agent_id)

                except Exception as e:
                    logger.error(f"Failed to send turn end: {e}")
                    # Save turn end error to database
                    if turn_id:
                        try:
                            await self.session_manager.save_message(
                                role=MessageRole.SYSTEM,
                                content=f"Failed to send turn end: {e}",
                                message_type=MessageType.ERROR,
                                turn_id=turn_id,
                                agent_id=self.agent_id,
                            )
                        except Exception as save_error:
                            logger.error(f"Failed to save turn end error: {save_error}")

        logger.debug("Agent execution completed.")

        if not self.config.save_history:
            self.reset()

    async def _execute_round_async(self, max_steps: Optional[int] = None) -> None:
        """
        Execute a complete round of agent execution

        Args:
            max_steps: Maximum number of steps
        """
        steps = 0

        while True:
            try:
                # Check for abort before running step
                if self.is_aborted or self.abort_event.is_set():
                    logger.info("Round aborted by user")
                    break

                # Run one step
                need_more_steps = await self.run_step_async()
                steps += 1

                # Check if more steps are needed
                if not need_more_steps:
                    logger.info(f"Round completed after {steps} steps")
                    break

                # Check max steps limit
                if max_steps is not None and steps >= max_steps:
                    logger.warning(f"Max steps ({max_steps}) reached")
                    break

            except asyncio.CancelledError:
                logger.info("Round cancelled by user.")
                break
            except Exception as e:
                logger.error(f"Error in round execution: {e}")
                logger.error(traceback.format_exc())

                # Save round execution error to database
                if self.turn_id:
                    try:
                        await self.session_manager.save_message(
                            role=MessageRole.SYSTEM,
                            content=f"Error in round execution: {e}\n{traceback.format_exc()}",
                            message_type=MessageType.ERROR,
                            turn_id=self.turn_id,
                            agent_id=self.agent_id,
                        )
                    except Exception as save_error:
                        logger.error(f"Failed to save round error: {save_error}")
                break

    def reset(self):
        """Reset agent state"""
        super().reset()
        # Reset abort state
        self.is_aborted = False
        self.abort_event.clear()
        self._abort_task = None

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

    async def abort(self):
        """
        Abort the agent execution

        This method sets the abort flag and cancels the current execution task.
        """
        logger.info("Aborting agent execution")
        self.is_aborted = True
        self.abort_event.set()

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
        Handle abort command from Socket.io

        This method is called when an abort command is received via the command channel.
        """
        command = message.data.get("command")
        if command == "abort":
            logger.info("Received abort command from user")
            if self.turn_id:
                try:
                    await self.session_manager.save_message(
                        role=MessageRole.USER,
                        content="abort",
                        message_type=MessageType.COMMAND,
                        turn_id=self.turn_id,
                        agent_id=self.agent_id,
                    )
                except Exception as save_error:
                    logger.error(f"Failed to save abort command: {save_error}")
            await self.abort()

    async def disconnect(self):
        """Disconnect from server"""
        await self.communicator.disconnect()

    async def restore_from_session(self, agent_id):
        await self.context.build_history_from_session(self.session_manager, agent_id)
        for message in self.context.history:
            logger.info(message)
