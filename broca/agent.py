"""
Agent Module

This module defines the core Agent class, which encapsulates the agent's behavior and functionality.
"""

import asyncio
import json
import uuid
from typing import Any, Optional

from broca.agent_configs import AgentConfig
from broca.context import Context
from broca.llm import LLMClient
from broca.logging_config import get_logger
from broca.loop_engine import ExecutionResult, ExecutionStatus
from broca.session import Message, MessageRole, MessageType, SessionManager
from broca.session.revert_service import SessionRevertService
from broca.snapshot.manager import GitSnapshotManager

logger = get_logger(__name__)


class Agent:
    """Base Agent class with core functionality"""

    STATUS_IDLE = "idle"
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
        # revert_service is initialized in create() (not __init__) to avoid
        # Git operations during construction (Task 5.3).
        self.revert_service: Optional[SessionRevertService] = None

        self.session_id: Optional[str] = session_manager.session_id
        self.turn_id: Optional[str] = None

        # LLM usage statistics (loaded from database)
        self.total_input_tokens: int = 0
        self.total_output_tokens: int = 0
        self.total_llm_calls: int = 0
        self.last_context_length: Optional[int] = None

        self.message_queue: asyncio.Queue = asyncio.Queue(
            self.config.execution_config.message_queue_size
        )

        self._abort_task: Optional[asyncio.Task] = None
        self.running = False
        self._run_lock: asyncio.Lock = asyncio.Lock()

        # 半初始化安全：create() 中途失败后 disconnect() 不会抛 AttributeError
        self.context_compressor = None
        self.persistent_memory_manager = None

        # 消息去重：防止 SocketIO 重连/retry 导致同一 message_id 重复入队
        self._seen_message_ids: set[str] = set()
        self._DEDUP_MAX_SIZE = 2000

    @classmethod
    async def create(
        cls,
        config: AgentConfig,
        llm_client: LLMClient,
        session_manager: SessionManager,
        **kwargs,
    ) -> "Agent":
        """Async factory: creates an Agent via ComponentRegistry composition root.

        All components are resolved from the ``ComponentRegistry`` with
        per-agent scoping.  Dependencies are injected in topological order.
        """
        from broca.agent_reference import AgentReferenceAdapter
        from broca.components import (
            CommandSystem,
            Communicator,
            ComponentRegistry,
            ContextCompressor,
            LoopEngine,
            MemoryManager,
            PermissionProvider,
            ToolExecutor,
            ToolManager,
        )

        registry = ComponentRegistry.get_instance()
        registry.register_defaults()
        registry.load_config_overrides(getattr(config, "workspace", None))
        registry.discover_plugins()

        agent = cls(config, llm_client, session_manager, **kwargs)
        key = agent.agent_id

        # Initialize snapshot/revert (moved from __init__ to avoid Git ops during construction)
        _snap_mgr = GitSnapshotManager()
        _snap_mgr.initialize(config.workspace)
        agent.revert_service = SessionRevertService(
            session_manager,
            _snap_mgr,
            config.workspace,
            enable_snapshot_tracking=getattr(
                config, "enable_snapshot_tracking", True
            ),
        )

        await agent.load_stats(session_manager)

        # ── 1. No runtime deps: construct first ──────────────────────────
        agent.context = Context(config, session_manager, **kwargs)
        agent.permission_provider = registry.get(PermissionProvider, scope_key=key)
        agent.communicator = registry.get(Communicator, scope_key=key)

        # ── 2. Topological initialize (no deps first) ───────────────────
        await agent.communicator.initialize(
            agent_id=key,
            session_id=session_manager.session_id,
            config=config,
        )

        # Register Agent-level event handlers on the communicator
        agent.communicator.register_event_handler("user_message", agent._receive_message)
        agent.communicator.register_event_handler("task_start", agent._receive_message)
        agent.communicator.register_event_handler("task_complete", agent._receive_message)
        agent.communicator.register_event_handler("task_error", agent._receive_message)
        agent.communicator.register_event_handler("command", agent._on_command)
        agent.communicator.register_event_handler(
            "permission_response", agent._on_permission_response
        )
        agent.communicator.register_event_handler("disconnect", agent._on_disconnected)
        agent.communicator.register_event_handler("connect", agent._on_connected)
        from broca.tools.agent_interaction import AskUserToolManager

        agent.communicator.register_event_handler(
            "user_answer", AskUserToolManager.handle_user_answer
        )

        await agent.permission_provider.initialize(
            communicator=agent.communicator,
            session_manager=session_manager,
            config=config,
            agent_id=key,
            session_id=agent.session_id,
        )

        # ── 3. Tool layer ───────────────────────────────────────────────
        agent.tool_manager = registry.get(ToolManager, scope_key=key)
        await agent.tool_manager.init(config.workspace)
        await agent._setup_tools()

        # ── 4. Execution layer (depends on tool_mapping / permission) ──
        tool_executor = registry.get(ToolExecutor, scope_key=key)
        await tool_executor.initialize(
            tool_mapping=agent.tool_mapping,
            permission_provider=agent.permission_provider,
            config=config,
            communicator=agent.communicator,
        )

        context_compressor = registry.get(ContextCompressor, scope_key=key)
        await context_compressor.initialize(
            agent_ref=AgentReferenceAdapter(agent),
            session_manager=session_manager,
            config=config,
        )

        memory_manager = registry.get(MemoryManager, scope_key=key)
        await memory_manager.initialize(
            agent_ref=AgentReferenceAdapter(agent),
            workspace=config.workspace,
            config=config.persistent_memory_config,
        )

        # ── 5. Execution engine (depends on all above) ──────────────────
        import functools

        from broca.components.compressor_context_factory import build_compressor_context
        from broca.loop_engine.hooks.factory import build_hooks_for
        from broca.loop_engine.strategies.factory import (
            create_llm_strategy,
            create_tool_strategy,
        )

        # Components the engine no longer owns: the compressor / memory manager
        # belong to CompressionMemoryHook, but the /compact and /clear* commands
        # plus shutdown() need a handle on them → expose them on the agent.
        agent.context_compressor = context_compressor
        agent.persistent_memory_manager = memory_manager

        agent_ref = AgentReferenceAdapter(agent)
        llm_strategy = create_llm_strategy(config)
        tool_strategy = create_tool_strategy(config)
        # Main agents get snapshot + communicator hooks; internal sub agents
        # (memory extraction / skill evolution) get the reduced set (review M1).
        hooks = build_hooks_for(
            config,
            snapshot_manager=None,  # SnapshotHook lazily creates it
            communicator=agent.communicator,
            context_compressor=context_compressor,
            memory_manager=memory_manager,
            context=agent.context,
            session_id=session_manager.session_id,
            compressor_ctx_builder=functools.partial(
                build_compressor_context,
                agent_ref=agent_ref,
                config=config,
                communicator=agent.communicator,
                session_manager=session_manager,
                agent_id=agent.agent_id,
                session_id=session_manager.session_id,
            ),
            tool_executor=tool_executor,
        )

        agent.execution_engine = registry.get(LoopEngine, scope_key=key)
        await agent.execution_engine.initialize(
            agent_ref=agent_ref,
            llm_client=llm_client,
            context=agent.context,
            tool_executor=tool_executor,
            communicator=agent.communicator,
            session_manager=session_manager,
            config=config,
            tool_mapping=agent.tool_mapping,
            permission_provider=agent.permission_provider,
            llm_strategy=llm_strategy,
            tool_strategy=tool_strategy,
            hooks=hooks,
        )

        # ── 6. Command system (only component that gets full Agent) ─────
        agent.command_manager = registry.get(CommandSystem, scope_key=key)
        await agent.command_manager.initialize(agent=agent, communicator=agent.communicator)

        return agent

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

    async def update_stats(self, input_tokens: int, output_tokens: int) -> None:
        """Update statistics and persist to database"""
        self.total_input_tokens += input_tokens
        self.total_output_tokens += output_tokens
        self.total_llm_calls += 1
        self.last_context_length = input_tokens + output_tokens

        # Persist to database
        try:
            await self.session_manager.agent_service.update(
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

    def get_stats(self) -> dict[str, Any]:
        """Get current statistics"""
        return {
            "agent_id": self.agent_id,
            "total_input_tokens": self.total_input_tokens,
            "total_output_tokens": self.total_output_tokens,
            "total_llm_calls": self.total_llm_calls,
            "last_context_length": self.last_context_length,
        }

    async def _setup_tools(self):
        """Set up tools for the agent, including auto-discovered built-in tools,
        custom tools from {workspace}/.broca/tool.py, and MCP tools from
        configured MCP servers.

        MCP servers are loaded and connected by ToolManager.init() (called at
        a higher level, e.g., AgentFactory). This method only fetches the
        appropriate MCP tools for this agent based on its ``mcp_servers`` config.

        If MCP connection is still pending (deferred), a background task will
        refresh ``tool_mapping`` in-place once MCP tools become available.
        """
        from broca.components import ComponentRegistry, ToolManager

        registry = ComponentRegistry.get_instance()
        tool_manager = registry.get(ToolManager, scope_key=self.agent_id)
        if self.config.mcp_servers:
            mcp_tools = tool_manager.get_mcp_tools(self.config.mcp_servers)
            mcp_tool_names = [tool.name for tool in mcp_tools]
        else:
            mcp_tool_names = []

        tool_names = list(self.config.tools) + mcp_tool_names
        tools = tool_manager.get_tools(tool_names=tool_names)
        self.tools = [tool.format() for tool in tools]
        self.tool_mapping = {tool.name: tool for tool in tools}

        # If MCP connection is deferred, schedule a background refresh so
        # MCP tools are added to tool_mapping once the connection completes.
        if self.config.mcp_servers and tool_manager._mcp_connect_task is not None:
            asyncio.create_task(
                self._refresh_mcp_tools(tool_manager),
                name=f"mcp-refresh-{self.agent_id}",
            )

    async def _refresh_mcp_tools(self, tool_manager) -> None:
        """Wait for deferred MCP connection and merge MCP tools into tool_mapping.

        Updates ``self.tool_mapping`` in-place (``dict.update``) so that
        downstream consumers (ToolExecutor, LoopEngine) see the new tools
        without re-initialization.
        """
        try:
            await tool_manager.wait_mcp_ready()
        except Exception as e:  # noqa: BLE001
            logger.warning(
                "Agent %s: MCP refresh failed: %s", self.agent_id, e
            )
            return

        if not self.config.mcp_servers:
            return

        mcp_tools = tool_manager.get_mcp_tools(self.config.mcp_servers)
        if not mcp_tools:
            return

        for tool in mcp_tools:
            if tool.name not in self.tool_mapping:
                self.tool_mapping[tool.name] = tool

        # Refresh formatted tools list
        self.tools = [tool.format() for tool in self.tool_mapping.values()]
        logger.info(
            "Agent %s: %d MCP tools added after deferred connect",
            self.agent_id, len(mcp_tools),
        )

    async def _receive_message(self, message: Message):
        """Receive message from communication channel (with dedup)"""
        # 去重：防止 SocketIO 重连/retry 导致同一 message_id 重复处理
        if message.message_id in self._seen_message_ids:
            logger.debug(
                f"Agent {self.agent_id}: deduplicated message {message.message_id}"
            )
            return
        self._seen_message_ids.add(message.message_id)
        if len(self._seen_message_ids) > self._DEDUP_MAX_SIZE:
            # 淘汰最早的消息 ID（set 无序，清除一半即可）
            it = iter(self._seen_message_ids)
            to_remove = set(list(it)[: self._DEDUP_MAX_SIZE // 2])
            self._seen_message_ids -= to_remove

        logger.info(f"Received message {message.message_type}")
        await self.message_queue.put(message)

    async def _on_disconnected(self, *args):
        """Handle Socket.io disconnect event — mark as disconnected.

        SocketIOClient 在检测到底层连接断开时触发 "disconnect" 事件。
        仅在非 running 状态下标记为 disconnected，避免覆盖任务执行中的
        running 状态（长工具执行期间 Socket.IO 可能短暂断连）。
        """
        if self.status == self.STATUS_RUNNING:
            logger.info(
                "Agent %s socket disconnected during running, keeping running status",
                self.agent_id,
            )
            return
        logger.info(
            "Agent %s socket disconnected, marking as disconnected", self.agent_id
        )
        await self._set_status(self.STATUS_DISCONNECTED)

    async def _on_connected(self, *args):
        """Handle Socket.io connect/reconnect event — restore status after reconnection.

        SocketIOClient 连接（含自动重连）成功后触发 "connect" 事件。
        仅当当前状态为 disconnected 时才恢复：
        - 如果 run() 仍在执行中（_abort_task 不为 None），恢复为 running
        - 否则恢复为 idle
        - 初始连接时 start() -> connect() 已设置 idle，此处幂等
        """
        if self.status == self.STATUS_DISCONNECTED:
            # 用 _abort_task 而非 status 判断：断连时 status 已被覆盖为 DISCONNECTED，
            # 无法区分断连前的 running/idle。
            # 注意：当前 _on_disconnected 在 RUNNING 状态下提前 return，
            # 因此 DISCONNECTED + _abort_task 不为 None 的组合实际不可达，
            # 此处为防御性保留。
            restore_status = (
                self.STATUS_RUNNING
                if self._abort_task is not None
                else self.STATUS_IDLE
            )
            logger.info(
                "Agent %s socket (re)connected, restoring status to %s",
                self.agent_id,
                restore_status,
            )
            await self._set_status(restore_status)

    async def ask_for_permission(self, message: str) -> bool:
        """
        Ask for user permission via communication channel

        Args:
            message: Permission request message

        Returns:
            True if permission is granted, False otherwise
        """
        # Update turn_id on the permission provider
        self.permission_provider.set_turn_id(self.turn_id)

        # Use permission provider to handle the request
        return await self.permission_provider.request_permission(message)

    async def ask_for_tool_permission(
        self, tool_name: str, arguments: str
    ) -> tuple[bool, Optional[str]]:
        """
        Ask for user permission for a tool execution (tool permission system).

        Thin wrapper over ``permission_provider.request_tool_permission`` —
        message construction (including argument truncation) is handled by
        the permission provider itself.

        Args:
            tool_name: Name of the tool
            arguments: Tool arguments as JSON string

        Returns:
            Tuple of (granted: bool, session_action: Optional[str])
        """
        self.permission_provider.set_turn_id(self.turn_id)
        return await self.permission_provider.request_tool_permission(
            tool_name, arguments
        )

    async def _on_permission_response(self, message: Message):
        """
        Handle permission response from Socket.io

        Args:
            message: Permission response message
        """
        await self.permission_provider.handle_permission_response(message)

    def stop(self):
        self.running = False

    def _drain_user_messages(self, first_msg: Message) -> list[Message]:
        """初始批量取：first_msg + 队列中所有 USER_MESSAGE / TASK_COMPLETE / TASK_ERROR（其余放回）。"""
        _drain_types = {
            MessageType.USER_MESSAGE,
            MessageType.TASK_COMPLETE,
            MessageType.TASK_ERROR,
        }
        messages = [first_msg]
        pending = []
        while True:
            try:
                msg = self.message_queue.get_nowait()
                if msg.message_type in _drain_types:
                    messages.append(msg)
                else:
                    pending.append(msg)
            except asyncio.QueueEmpty:
                break
        for msg in pending:
            try:
                self.message_queue.put_nowait(msg)
            except asyncio.QueueFull:
                logger.warning(f"Queue full after re-queue: {msg.message_type}")
        return messages

    def _make_message_source(self) -> Any:
        """创建 message_source 对象，供 engine 在 step 间 drain 新用户消息。

        闭包捕获 self.message_queue 的引用。当前 Agent 生命周期内
        message_queue 不会被替换，因此闭包安全。
        """
        queue = self.message_queue

        _drain_types = {
            MessageType.USER_MESSAGE,
            MessageType.TASK_COMPLETE,
            MessageType.TASK_ERROR,
        }

        class _Drainer:
            async def drain(self) -> list[Message]:
                msgs, pending = [], []
                while True:
                    try:
                        msg = queue.get_nowait()
                        if msg.message_type in _drain_types:
                            msgs.append(msg)
                        else:
                            pending.append(msg)
                    except asyncio.QueueEmpty:
                        break
                for p in pending:
                    try:
                        queue.put_nowait(p)
                    except asyncio.QueueFull:
                        pass
                return msgs

        return _Drainer()

    async def start(self):
        self.running = True

        while self.running:
            try:
                if not self.is_connected():
                    if not await self.connect():
                        logger.error("Failed to connect to server")
                        # 重连失败，将状态持久化为 disconnected
                        await self._set_status(self.STATUS_DISCONNECTED)
                        self.running = False
                        break
                message = await asyncio.wait_for(self.message_queue.get(), timeout=1)
                if message.message_type == MessageType.USER_MESSAGE:
                    if not await self._try_dispatch_inline_command(message):
                        if self.config.execution_config.execution_mode == "non_blocking":
                            messages = self._drain_user_messages(message)
                            await self.run(messages, message_source=self._make_message_source())
                        else:
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
            except Exception:
                logger.exception("Unexpected error in message loop")

    async def _try_dispatch_inline_command(self, message: Message) -> bool:
        """尝试将用户消息作为 inline command 处理。
        返回 True 表示已作为命令处理（不再是普通对话）。
        """
        if not self.command_manager:
            return False
        content = message.data.get("content", "")
        if not content:
            return False
        parsed = self.command_manager.parse(content)
        if not parsed:
            return False
        name, args = parsed
        await self._handle_command(name, args, message)
        return True

    async def run(
        self,
        message: "Message | list[Message]",
        max_steps: Optional[int] = None,
        from_agent: Optional[bool] = False,
        allowed_tools: Optional[list[str]] = None,
        namespace: Optional[str] = None,
        message_source: Optional[Any] = None,
    ) -> ExecutionResult:
        """
        Run agent in async mode (replaces command-line interaction)

        This method delegates execution to the execution engine,
        handling high-level execution control and cleanup.

        Args:
            message: The message(s) to process (single Message or list of Messages)
            max_steps: Maximum number of steps
            from_agent: Whether the message is from another agent (inter-agent task,
                        not a direct user message). Command interception is handled
                        at the start() message-loop level, not here.
            allowed_tools: Optional list of tool names that are allowed to be called.
                           If provided, any tool not in this list will be skipped
                           with a "this tool is currently not allowed" result.
            message_source: Optional source for mid-step user message injection
                           (non-blocking mode).

        Returns:
            ExecutionResult: Result of the execution with status and details
        """
        # ═══ Serial execution lock ═══
        # Prevent concurrent execution of the run() method from multiple call paths
        # (e.g., start() message loop vs. direct run() calls)
        async with self._run_lock:
            # Store the current execution task for potential cancellation
            self._abort_task = asyncio.current_task()
            await self._set_status(self.STATUS_RUNNING)

            # Clear undo stack (new operation invalidates undo history)
            self.revert_service.undo_stack.clear()

            try:
                return await self.execution_engine.execute(
                    message, max_steps, from_agent,
                    allowed_tools=allowed_tools,
                    namespace=namespace,
                    message_source=message_source,
                )
            except Exception as e:
                logger.error(f"Error in run: {e}")
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
                await self._set_status(self.STATUS_IDLE)

    async def _handle_command(
        self, name: str, args: str, original_message: Message
    ) -> ExecutionResult:
        """
        Handle a command intercepted in the start() message loop.

        Dispatches the command via CommandManager and returns an ExecutionResult.
        If the command is not found, continues execution as a normal message.
        """
        raw_input = original_message.data.get("content", "")
        result = await self.command_manager.dispatch(
            name,
            args,
            raw_input,
            original_message_id=original_message.message_id,
        )

        if result is None:
            # Command not found, treat as normal message
            logger.warning(f"Command '{name}' not found, treating as normal message")
            return await self.run(original_message)

        # Send result via command manager (handles error vs success + show_result)
        await self.command_manager.send_result(name, result, self.session_id)

        return ExecutionResult(
            status=ExecutionStatus.COMPLETED,
            message=result.value,
        )

    async def _handle_task(self, message: Message) -> None:
        """Handle task assignment from another agent"""
        task_id: str = ""
        assigner = None
        try:
            task_id = message.data.get("task_id", "")
            assigner = message.data.get("assigner")
            execution_result = await self.run(message, from_agent=True)

            # Check execution status
            if execution_result.status == ExecutionStatus.COMPLETED:
                msg = self.context.get_latest_assistant_message()
                result = f"Message from agent {self.name}: {msg}"
                logger.info(f"send result to {assigner}")
                if assigner:
                    await self.communicator.send_task_complete(task_id, result, assigner)
                else:
                    logger.warning(f"Task {task_id} completed but no assigner to notify")
            elif execution_result.status == ExecutionStatus.ABORTED:
                result = f"The agent {self.agent_id} execution was aborted by user"
                logger.warning(result)
            elif execution_result.status in (
                ExecutionStatus.ERROR,
                ExecutionStatus.DEAD_LOOP,
            ):
                result = f"The agent {self.agent_id} failed to finish the task: {execution_result.message or execution_result.error}"
                logger.error(result)
                if assigner:
                    await self.communicator.send_task_error(
                        task_id, result, receiver_id=assigner
                    )
                else:
                    logger.warning(f"Task {task_id} failed but no assigner to notify")
        except Exception as e:
            logger.error(f"Error processing task: {e}")
            if assigner:
                result = f"The agent {self.agent_id} failed to finish the task: {e}"
                await self.communicator.send_task_error(
                    task_id, result, receiver_id=assigner
                )
            else:
                logger.error(
                    f"Task {task_id or 'unknown'} failed and no assigner to notify"
                )

    async def reset(self):
        """Reset agent state"""
        self.execution_engine.reset()
        await self.permission_provider.reset()
        self.context.reset_history()
        self.turn_id = None
        await self._set_status(self.STATUS_IDLE)

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
            await self._set_status(self.STATUS_IDLE)
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
        await self.update_stats(input_tokens, output_tokens)

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

    async def _on_command(self, message: Message):
        """
        Handle command from Socket.io

        This method is called when a command is received via the command channel.
        Routes to the command system via CommandManager for registered commands.
        """
        command = message.data.get("command")
        arguments = message.data.get("arguments", {})
        logger.info(f"Received command: {command}")

        # COMMAND 消息是系统级消息，不属于任何 turn。
        # 若使用 self.turn_id（可能还指向上一个已完成的 turn），
        # 会导致 undo/redo 的 redo 操作通过 _mark_messages_as_redone
        # 错误地将该 turn 的 reverted 标记恢复为 False，
        # 从而使前端展示一条只有标题栏的空卡片。
        await self.session_manager.save_message(
            role=MessageRole.SYSTEM,
            content=command,
            message_type=MessageType.COMMAND,
            turn_id=None,
            agent_id=self.agent_id,
        )

        if self.command_manager.registry.has(command):
            args_str = json.dumps(arguments)
            result = await self.command_manager.dispatch(
                command,
                args_str,
                None,
                original_message_id=message.message_id,
            )
            if result:
                if result.type == "error":
                    await self.communicator.send_error(
                        {"message": result.value, "code": "COMMAND_ERROR", "severity": "error"},
                        subscription=self.session_id,
                    )
                else:
                    await self.communicator.send_command_result(
                        command=command,
                        result={
                            "code": 0,
                            "message": result.value,
                        },
                        subscription=self.session_id,
                    )
                return
        else:
            await self.communicator.send_error(
                {"message": f"未知命令: {command}", "code": "COMMAND_ERROR", "severity": "error"},
                subscription=self.session_id,
            )

    async def disconnect(self):
        """Disconnect from server and release per-agent component scope.

        Performs reverse-topological shutdown:
        1. ``execution_engine.abort()`` — stop in-flight tasks
        2. ``shutdown()`` each component (only those that declare it)
        3. ``registry.release(agent_id)`` — release all per-agent instances
        """
        self.execution_engine.abort()
        await self.communicator.disconnect()
        await self._set_status(self.STATUS_DISCONNECTED)

        from broca.components import ComponentRegistry

        shutdown_order = [
            self.execution_engine,
            self.execution_engine.tool_executor,
            self.context_compressor,
            self.persistent_memory_manager,
            self.permission_provider,
            self.communicator,
        ]
        for comp in shutdown_order:
            if comp is not None and hasattr(comp, "shutdown"):
                await comp.shutdown()

        ComponentRegistry.get_instance().release(self.agent_id)

    async def restore_from_session(self, agent_id):
        """Restore agent state from session"""
        if self.config.save_history:
            await self.context.build_history_from_session(agent_id)
        else:
            self.context.reset_history()
