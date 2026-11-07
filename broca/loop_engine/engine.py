"""Default loop engine — pure orchestrator over strategies + hooks.

The engine owns **orchestration and persistence only**:

* the turn/step lifecycle and the hook dispatch order (single source of truth);
* DB writes (``save_message`` / ``save_agent_response`` / ``save_tool_call`` /
  ``save_turn_end``);
* thin broadcasting callbacks handed to the LLM strategy.

Everything else is delegated: LLM calls (retry / rate-limit / timeout /
streaming) → ``LLMStrategy``; tool execution (serial / parallel / permission
partitioning) → ``ToolExecutionStrategy``; snapshots / step broadcasts /
dead-loop detection / compression / memory → ``LoopHook``.

Lifecycle (see ``broca.components.loop_hook``)::

    _setup_turn → [on_turn_start] → loop:
        llm_strategy.call → _check_write_ops → [on_step_start] → _save_response
        → tool_strategy.execute → _process_tool_results
        → [on_step_end] → [on_post_step]
    → _finalize_turn: [on_turn_end] → save_turn_end → [on_turn_finalized]
"""

from __future__ import annotations

import asyncio
import json
import uuid
from typing import Any, Dict, List, Optional

from broca.components.loop_engine import ExecutionResult, ExecutionStatus, LoopEngine
from broca.components.loop_hook import StepContext, TurnContext
from broca.components.tool_strategy import ABORTED_TOOL_RESULT_CONTENT
from broca.context import Context
from broca.errors import (
    BrocaError,
    SessionError,
    ToolResultProcessingError,
    ValidationError,
)
from broca.logging_config import get_logger
from broca.loop_engine.strategies.factory import (
    create_llm_strategy,
    create_tool_strategy,
)
from broca.session import (
    Message,
    MessageProtocol,
    MessageRole,
    MessageType,
    SessionManager,
    generate_message_id,
)
from broca.tools.tool import ToolCallContext, ToolResult, ToolStatus

logger = get_logger(__name__)

_TERMINAL_STATUSES = (
    ExecutionStatus.COMPLETED,
    ExecutionStatus.ABORTED,
    ExecutionStatus.ERROR,
    ExecutionStatus.DEAD_LOOP,
)

_MISSING_RESULT_CONTENT = "Tool execution failed (missing result)"

_TURN_END_MESSAGES = {
    ExecutionStatus.COMPLETED: "Turn completed successfully",
    ExecutionStatus.ABORTED: "Turn aborted by user",
    ExecutionStatus.LIMIT_EXCEEDED: "Turn step limit exceeded",
    ExecutionStatus.DEAD_LOOP: "Turn dead loop detected",
    ExecutionStatus.ERROR: "Turn failed",
    ExecutionStatus.SKIPPED: "Turn skipped",
}


class DefaultLoopEngine(LoopEngine):
    """Orchestrates one turn: LLM strategy → tool strategy → hooks.

    Dependencies arrive either through the constructor (legacy direct path,
    still used by unit-test fixtures) or through ``initialize()`` (the
    ``ComponentRegistry`` path used by ``Agent.create()``).
    """

    # ==================================================================
    # Dependency injection
    # ==================================================================

    def __init__(
        self,
        agent_ref: Optional[Any] = None,
        llm_client: Optional[Any] = None,
        context: Optional[Context] = None,
        tool_mapping: Optional[Dict[str, Any]] = None,
        config: Optional[Any] = None,
        communicator: Optional[Any] = None,
        session_manager: Optional[SessionManager] = None,
        permission_provider: Optional[Any] = None,
        tool_executor: Optional[Any] = None,
        llm_strategy: Optional[Any] = None,
        tool_strategy: Optional[Any] = None,
        hooks: Optional[List[Any]] = None,
    ):
        self._initialized = False

        # Mutable execution state
        self.abort_event = asyncio.Event()
        self.turn_id: Optional[str] = None
        self.step_id: Optional[str] = None
        self.namespace: Optional[str] = None
        self.execution_id: Optional[str] = None
        self.allowed_tools: Optional[List[str]] = None

        # Pluggable layers (populated by ``_do_initialize``)
        self._llm_strategy: Optional[Any] = None
        self._tool_strategy: Optional[Any] = None
        self._hooks: List[Any] = []
        self._strategies_ready = False

        # Chunk broadcast throttle (LLM 流式输出混合策略)
        self._chunk_buffer: list[dict] = []
        self._chunk_buffer_len: int = 0
        self._chunk_flush_task: Optional[asyncio.Task] = None
        self._CHUNK_FLUSH_CHARS: int = 128
        self._CHUNK_FLUSH_INTERVAL: float = 0.1
        self._CHUNK_BUFFER_MAX: int = 1000

        # Per-turn broadcast callbacks (created once in ``_execute_round``).
        self._on_chunk_handler: Optional[Any] = None
        self._on_error_handler: Optional[Any] = None

        # Non-blocking mode: message source for mid-step user message injection
        self._message_source: Optional[Any] = None

        # Legacy direct-construction path (unit-test fixtures rely on it)
        if agent_ref is not None:
            self._do_initialize(
                agent_ref=agent_ref,
                llm_client=llm_client,
                context=context,
                tool_mapping=tool_mapping,
                config=config,
                communicator=communicator,
                session_manager=session_manager,
                permission_provider=permission_provider,
                tool_executor=tool_executor,
                llm_strategy=llm_strategy,
                tool_strategy=tool_strategy,
                hooks=hooks,
            )

    def _do_initialize(
        self,
        agent_ref: Any,
        llm_client: Any,
        context: Context,
        tool_mapping: Dict[str, Any],
        config: Any,
        communicator: Any,
        session_manager: SessionManager,
        permission_provider: Optional[Any] = None,
        tool_executor: Optional[Any] = None,
        llm_strategy: Optional[Any] = None,
        tool_strategy: Optional[Any] = None,
        hooks: Optional[List[Any]] = None,
    ) -> None:
        """Shared dependency-injection logic for both construction paths.

        The context compressor and memory manager are **not** engine
        dependencies — they belong to ``CompressionMemoryHook`` and are wired
        by the hook factory (review 2.1).
        """
        self.agent_ref = agent_ref
        self.llm_client = llm_client
        self.context = context
        self.tool_mapping = tool_mapping if tool_mapping is not None else {}
        if not self.tool_mapping:
            logger.warning(
                "DefaultLoopEngine initialized with an empty tool_mapping — "
                "no tools will be available to the LLM."
            )
        self.config = config
        self.communicator = communicator
        self.session_manager = session_manager
        self.permission_provider = permission_provider
        self.tool_executor = tool_executor

        self.agent_id = agent_ref.agent_id
        self.session_id = session_manager.session_id

        self._llm_strategy = llm_strategy or create_llm_strategy(config)
        self._tool_strategy = tool_strategy or create_tool_strategy(config)
        self._hooks = list(hooks or [])
        self._strategies_ready = False
        self._initialized = True

    async def initialize(
        self,
        agent_ref: Any,
        llm_client: Any,
        context: Context,
        tool_executor: Any,
        communicator: Any,
        session_manager: SessionManager,
        config: Any,
        tool_mapping: Dict[str, Any],
        permission_provider: Optional[Any] = None,
        llm_strategy: Optional[Any] = None,
        tool_strategy: Optional[Any] = None,
        hooks: Optional[List[Any]] = None,
    ) -> None:
        """Inject all runtime dependencies (registry path).

        Raises on a second call: silently dropping a fresh dependency set on a
        registry-reused instance would be a very confusing failure mode
        (review 2.4).
        """
        if self._initialized:
            raise RuntimeError(
                "DefaultLoopEngine.initialize() called on an already-initialized "
                "instance; pass a fresh instance from the registry instead."
            )
        self._do_initialize(
            agent_ref=agent_ref,
            llm_client=llm_client,
            context=context,
            tool_mapping=tool_mapping,
            config=config,
            communicator=communicator,
            session_manager=session_manager,
            permission_provider=permission_provider,
            tool_executor=tool_executor,
            llm_strategy=llm_strategy,
            tool_strategy=tool_strategy,
            hooks=hooks,
        )
        await self._ensure_strategies()

    async def _ensure_strategies(self) -> None:
        """Await strategy ``initialize()`` once (the constructor path is sync)."""
        if self._strategies_ready:
            return
        if self._llm_strategy is not None:
            await self._llm_strategy.initialize(
                llm_client=self.llm_client, config=self.config
            )
        if self._tool_strategy is not None:
            await self._tool_strategy.initialize(
                tool_executor=self.tool_executor, config=self.config
            )
        self._strategies_ready = True

    def _reset_turn_scoped_state(self) -> None:
        """Drop per-turn state: hook state + strategy counters + chunk buffer (M12)."""
        for hook in self._hooks:
            try:
                hook.reset()
            except Exception as e:
                logger.warning(f"Hook {getattr(hook, 'name', '?')}.reset failed: {e}")
        for strategy in (self._llm_strategy, self._tool_strategy):
            if strategy is not None:
                strategy.reset()
        # Clear chunk buffer
        self._chunk_buffer.clear()
        self._chunk_buffer_len = 0
        if self._chunk_flush_task and not self._chunk_flush_task.done():
            self._chunk_flush_task.cancel()
            self._chunk_flush_task = None
        # Clear per-turn message source
        self._message_source = None

    # ==================================================================
    # Turn setup
    # ==================================================================

    async def _setup_turn(
        self, messages: List[Message], from_agent: Optional[bool] = False
    ) -> TurnContext:
        """Parse messages, open a turn, persist user messages.

        The first message drives turn creation and ``TurnContext``; subsequent
        messages are appended to context (parse failures are logged and skipped).

        Raises:
            SessionError: 带具体原因的会话初始化失败（session 未就绪、
                turn 创建失败、消息持久化失败等）。
        """
        self.abort_event.clear()
        self._reset_turn_scoped_state()
        try:
            # --- First message: original single-message path ---
            first_msg = messages[0]
            user_message = self.llm_client.parse_message(
                provider=self.config.provider,
                model=self.config.model,
                message=first_msg,
            )
            if not user_message:
                raise SessionError(
                    f"消息解析结果为空 (provider={self.config.provider}, "
                    f"model={self.config.model})"
                )

            turn_id = await self._start_turn(user_message, from_agent or False)
            if not turn_id:
                raise SessionError(
                    f"创建 Turn 失败 (session_id={self.session_id or 'None'}, "
                    f"agent_id={self.agent_id}, "
                    f"session_manager.session_id={self.session_manager.session_id or 'None'})"
                )

            message_id = await self._save_user_message(
                user_message, first_msg, turn_id, from_agent or False
            )
            if message_id is None:
                raise SessionError(
                    f"用户消息持久化失败 (turn_id={turn_id}, "
                    f"agent_id={self.agent_id})"
                )

            await self.context.add_message(user_message, message_id)

            # --- Subsequent messages: best-effort (parse failure skips) ---
            for msg in messages[1:]:
                try:
                    parsed = self.llm_client.parse_message(
                        provider=self.config.provider,
                        model=self.config.model,
                        message=msg,
                    )
                    if not parsed:
                        continue
                    mid = await self._save_user_message(
                        parsed, msg, turn_id, from_agent or False
                    )
                    if mid:
                        await self.context.add_message(parsed, mid)
                except Exception as e:
                    logger.warning(
                        f"Failed to process additional message "
                        f"{getattr(msg, 'message_id', '?')}: {e}"
                    )

            data = getattr(first_msg, "data", None) or {}
            return TurnContext(
                turn_id=turn_id,
                agent_id=self.agent_id,
                session_id=self.session_id,
                user_message=user_message,
                message_id=message_id,
                sender_id=getattr(first_msg, "sender_id", None) or "",
                files=list(data.get("files") or []),
                from_agent=bool(from_agent),
                raw_input=user_message.get("raw_input") or "",
            )
        except ValidationError:
            raise
        except BrocaError:
            # BrocaError carries a proper error code — let it propagate
            # so execute() can report it via the ``except BrocaError`` branch.
            raise
        except Exception as e:
            logger.error(f"Error in _setup_turn: {e}")
            raise SessionError(f"执行上下文初始化异常: {e}", cause=e) from e

    async def _start_turn(self, user_message: dict, from_agent: bool) -> Optional[str]:
        """Create the turn row and remember ``turn_id`` (broadcast is a hook)."""
        await self._ensure_session()
        turn_id = await self.session_manager.start_turn(self.agent_id, strict=True)
        if not turn_id:
            return None
        self.turn_id = turn_id
        self.agent_ref.turn_id = turn_id
        return turn_id

    async def _save_user_message(
        self, user_message: dict, message: Message, turn_id: str, from_agent: bool
    ) -> Optional[str]:
        """Persist the user message; returns its ``message_id``.

        Does NOT mutate ``message.data`` — constructs a new dict instead.
        """
        # Build a new data dict to avoid mutating the caller's message
        message_data = dict(message.data) if message.data else {}
        message_data["from_agent"] = from_agent
        if user_message.get("raw_input"):
            message_data["raw_input"] = user_message["raw_input"]
        # Agent-sourced messages get a pre-generated id so turn setup can never
        # mistake them for a failed setup (regression fix 104c8c2).
        message_id = f"msg_{uuid.uuid4().hex[:16]}" if from_agent else message.message_id
        saved = await self.session_manager.save_message(
            role=MessageRole.USER,
            content=json.dumps(user_message, ensure_ascii=False),
            message_type=MessageType.USER_MESSAGE,
            turn_id=turn_id,
            agent_id=self.agent_id,
            data=message_data,
            message_id=message_id,
            strict=True,
        )
        return message_id if saved else None

    async def _ensure_session(self, workspace: Optional[str] = None) -> None:
        """Ensure a session exists, creating one if needed."""
        if not self.session_id:
            if not self.session_manager.session_id:
                await self.session_manager.create_session(workspace=workspace)
            self.session_id = self.session_manager.session_id

    async def _inject_user_message(self, message: Message) -> None:
        """Parse and persist a mid-step injected user message.

        Called from ``_execute_round`` when a new user message arrives via
        the message source during non-blocking execution.
        """
        user_message = self.llm_client.parse_message(
            provider=self.config.provider,
            model=self.config.model,
            message=message,
        )
        if not user_message:
            logger.warning(
                f"parse_message returned empty for injected message "
                f"{getattr(message, 'message_id', '?')}, using fallback"
            )
            # Fallback: construct a simple text message from raw content
            raw = (message.data or {}).get("raw_input") or (message.data or {}).get("content") or ""
            if not raw:
                logger.warning(
                    f"Injected message {getattr(message, 'message_id', '?')} "
                    f"has no content; dropping"
                )
                return
            user_message = {
                "role": "user",
                "content": [{"type": "text", "text": str(raw)}],
                "raw_input": str(raw),
            }
        message_data = dict(message.data) if message.data else {}
        message_data["from_agent"] = False
        if user_message.get("raw_input"):
            message_data["raw_input"] = user_message["raw_input"]
        message_id = await self.session_manager.save_message(
            role=MessageRole.USER,
            content=json.dumps(user_message, ensure_ascii=False),
            message_type=MessageType.USER_MESSAGE,
            turn_id=self.turn_id,
            agent_id=self.agent_id,
            data=message_data,
            message_id=message.message_id,
        )
        if message_id:
            await self.context.add_message(user_message, message_id)

            # Broadcast mid-step injected message to frontend
            if getattr(self.config, "interactive", False):
                try:
                    broadcast_msg = Message(
                        message_id=message.message_id,
                        role=MessageRole.USER,
                        content=json.dumps(user_message, ensure_ascii=False),
                        message_type=MessageType.USER_MESSAGE,
                        turn_id=self.turn_id,
                        agent_id=self.agent_id,
                        # 设置 subscription 确保 server 走 _send_to_subscription 路由，
                        # 而非 _broadcast（发给所有客户端包括 agent 自身 → 自回显循环）
                        subscription=self.session_id,
                        data={
                            "content": message.data.get("content", ""),
                            "raw_input": user_message.get("raw_input", ""),
                        },
                    )
                    await self.communicator.send_message(broadcast_msg)
                except Exception as e:
                    logger.warning(f"Failed to broadcast injected message: {e}")

    # ==================================================================
    # Step / round execution
    # ==================================================================

    async def _execute_step(self, turn_ctx: TurnContext) -> StepContext:
        """One step: LLM call → hooks → tools → hooks."""
        step_ctx = StepContext(
            step_id=f"step-{uuid.uuid4().hex[:8]}",
            turn_id=self.turn_id or "",
            agent_id=self.agent_id,
            session_id=self.session_id or "",
        )
        self.step_id = step_ctx.step_id

        llm = await self._llm_strategy.call(
            history=self.context.history,
            tools=self._get_tools_list(),
            on_chunk=self._on_chunk_handler,
            on_error=self._on_error_handler,
            should_abort=lambda: self.abort_event.is_set(),
        )
        if llm.aborted or self.abort_event.is_set():
            logger.info("Agent execution aborted during LLM call")
            step_ctx.status = ExecutionStatus.ABORTED
            return step_ctx
        if not llm.success or llm.message is None:
            step_ctx.status = ExecutionStatus.ERROR
            return step_ctx

        # Token accounting stays in the engine (strategies stay side-effect free);
        # deliberately once per successful call (legacy reported per attempt).
        await self.agent_ref.on_llm_call_completed(llm.input_tokens, llm.output_tokens)

        step_ctx.response = llm.message
        step_ctx.tool_calls = list(getattr(llm.message, "tool_calls", None) or [])
        step_ctx.llm_input_tokens = llm.input_tokens
        step_ctx.llm_output_tokens = llm.output_tokens
        step_ctx.status = ExecutionStatus.RUNNING

        await self._dispatch("on_step_start", step_ctx)
        await self._persist_step_start(step_ctx)
        try:
            if not await self._save_response(step_ctx.response):
                logger.error("Failed to save agent response")
                step_ctx.status = ExecutionStatus.ERROR
            elif step_ctx.tool_calls:
                results = await self._tool_strategy.execute(
                    step_ctx.tool_calls,
                    self._build_tool_context(),
                    self.tool_mapping,
                    allowed_tools=self.allowed_tools,
                    should_abort=lambda: self.abort_event.is_set(),
                )
                step_ctx.tool_results = list(results)
                await self._process_tool_results(step_ctx.tool_calls, results)
            else:
                step_ctx.status = ExecutionStatus.COMPLETED
        finally:
            # ``on_step_end`` must always run — SnapshotHook releases its lock there.
            await self._dispatch("on_step_end", step_ctx)
            await self._persist_step_end(step_ctx)
        await self._dispatch("on_post_step", step_ctx)
        return step_ctx

    async def _execute_round(
        self, turn_ctx: TurnContext, max_steps: Optional[int] = None
    ) -> ExecutionResult:
        """Drive steps until a terminal status is reached."""
        # Create broadcast callbacks once per turn (review 3.2): the closures
        # only read ``self.turn_id`` / ``self.session_id`` at call time, so a
        # single instance serves every step without per-step allocation.
        self._on_chunk_handler = self._make_chunk_handler()
        self._on_error_handler = self._make_error_handler()

        steps = 0
        while True:
            if self.abort_event.is_set():
                logger.info("Round aborted by user")
                return self._build_round_result(ExecutionStatus.ABORTED, steps)
            try:
                step_ctx = await self._execute_step(turn_ctx)
                steps += 1

                # A terminal status ends the turn NOW — do NOT drain/inject pending
                # user messages into a dying turn. The LLM already signalled "done",
                # so anything injected here would be persisted under this turn but
                # never answered; worse, having been drained from the queue it would
                # also never be reprocessed as a new turn (silently swallowed).
                # Leaving them queued lets ``start()`` handle them as a fresh turn.
                # (design: "COMPLETED 时队列有消息 → turn 结束，消息留到下一 turn；
                #  LLM 'done' 信号保持权威性")
                if step_ctx.status in _TERMINAL_STATUSES:
                    return self._build_round_result(step_ctx.status, steps)
                if max_steps is not None and steps >= max_steps:
                    return self._build_round_result(ExecutionStatus.LIMIT_EXCEEDED, steps)

                # ── Non-blocking: mid-step message injection ──
                # Only reached when another step will actually run, so injected
                # messages are guaranteed to be seen by the next LLM call. Skipped
                # after abort (a dying turn must not absorb messages either).
                if self._message_source is not None and not self.abort_event.is_set():
                    try:
                        new_msgs = await self._message_source.drain()
                        if new_msgs:
                            logger.info(
                                f"Mid-step drain: got {len(new_msgs)} message(s) "
                                f"after step {steps}: "
                                f"{[m.message_type for m in new_msgs]}"
                            )
                        for msg in new_msgs:
                            if msg.message_type == MessageType.USER_MESSAGE:
                                await self._inject_user_message(msg)
                    except Exception as e:
                        logger.warning(f"Mid-step message drain failed: {e}")
            except BrocaError as e:
                # Report the concrete error dict so codes survive (LLM_RATE_LIMIT).
                if getattr(self.config, "interactive", False):
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

    def _build_round_result(self, status: ExecutionStatus, steps: int) -> ExecutionResult:
        """Build the round result (synchronous — no awaits inside)."""
        messages = {
            ExecutionStatus.COMPLETED: f"Round completed after {steps} steps",
            ExecutionStatus.ABORTED: f"Round aborted by user after {steps} steps",
            ExecutionStatus.ERROR: f"Round failed after {steps} steps",
            ExecutionStatus.DEAD_LOOP: (
                f"Dead loop detected after {steps} steps: last 3 tool calls are identical"
            ),
            ExecutionStatus.LIMIT_EXCEEDED: "Max steps reached",
        }
        return ExecutionResult(
            status=status,
            message=messages.get(status, f"Round ended with {status.value}"),
        )

    async def _dispatch(self, method: str, ctx: Any) -> None:
        """Call ``method`` on every hook in registration order; never raise.

        A failing hook must not break the loop (a broken snapshot must not stop
        the LLM call), so every exception is caught and logged.
        """
        for hook in self._hooks:
            try:
                await getattr(hook, method)(ctx)
            except Exception as e:
                logger.warning(f"Hook {getattr(hook, 'name', '?')}.{method} failed: {e}")

    # ==================================================================
    # Persistence (the engine is the only layer allowed to write to the DB)
    # ==================================================================

    async def _save_response(self, response: Any) -> bool:
        """Persist the assistant message and append it to the context."""
        message_id = getattr(response, "message_id", None)
        if not await self.session_manager.save_agent_response(
            response,
            self.turn_id,
            self.agent_id,
            self.step_id,
            message_id=message_id,
        ):
            return False
        await self.context.add_message(response, message_id)
        return True

    async def _process_tool_results(
        self, tool_calls: List[Any], results: List[ToolResult]
    ) -> None:
        """Persist/broadcast every tool result in the original call order (C2).

        Two guards keep the DB/front-end consistent with what actually ran:

        * a strategy returning fewer results than calls is padded (and logged)
          instead of being silently truncated by ``zip()``;
        * abort placeholders (tool calls that were **never executed**) are
          skipped — legacy's serial path wrote no rows for them either.
        """
        if len(results) < len(tool_calls):
            logger.error(
                f"Tool strategy returned {len(results)} results for "
                f"{len(tool_calls)} tool calls; padding missing results"
            )
            results = list(results) + [
                ToolResult(status=ToolStatus.ERROR, content=_MISSING_RESULT_CONTENT)
                for _ in range(len(tool_calls) - len(results))
            ]

        for tool_call, result in zip(tool_calls, results):
            if self._is_abort_placeholder(result):
                logger.info(
                    f"Skipping persistence for never-executed tool call {tool_call.id}"
                )
                continue
            if not await self.process_tool_call_result(tool_call, result):
                raise ToolResultProcessingError("Tool call result processing failed")

    def _is_abort_placeholder(self, result: ToolResult) -> bool:
        """True for the placeholder a strategy returns for a skipped call (M3)."""
        return (
            self.abort_event.is_set()
            and result.status == ToolStatus.ERROR
            and result.content == ABORTED_TOOL_RESULT_CONTENT
        )

    async def process_tool_call_result(
        self, tool_call: Any, tool_result: ToolResult
    ) -> bool:
        """Broadcast + persist one tool result and append it to the context.

        Kept as a public engine method: ``test_image_tool.py`` calls it directly.
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

        # Extra context messages (e.g. images injected by tools).
        for extra in tool_result.extra_context_messages or []:
            extra_id = f"msg_{uuid.uuid4().hex[:16]}"
            data = dict(extra.get("data", {}))
            data["tool_injected"] = True
            # Tool-injected messages are internal context, never user-visible.
            await self.session_manager.save_message(
                role=extra.get("role", "user"),
                content=json.dumps(extra["llm_message"], ensure_ascii=False),
                message_type=MessageType.USER_MESSAGE,
                turn_id=self.turn_id,
                agent_id=self.agent_id,
                data=data,
                message_id=extra_id,
            )
            await self.context.add_message(extra["llm_message"], extra_id)
        return True

    async def _persist_step_start(self, step_ctx: StepContext) -> bool:
        """Persist the STEP_START row (undo/redo depends on it).

        Legacy wrote it only when snapshot tracking was active; keep that gate.
        """
        if not getattr(self.config, "enable_snapshot_tracking", True):
            return False
        if not getattr(self.config, "workspace", None):
            return False
        return await self._save_step_message(
            MessageProtocol.create_step_start(
                step_id=step_ctx.step_id, snapshot_hash=step_ctx.step_start_snapshot
            )
        )

    async def _persist_step_end(self, step_ctx: StepContext) -> bool:
        """Persist the STEP_END row.

        Uses the same gates as ``_persist_step_start`` so that a STEP_END
        is never written without a matching STEP_START (review 1.1).
        """
        if not getattr(self.config, "enable_snapshot_tracking", True):
            return False
        if not getattr(self.config, "workspace", None):
            return False
        return await self._save_step_message(
            MessageProtocol.create_step_end(
                step_id=step_ctx.step_id,
                snapshot_hash=step_ctx.step_end_snapshot,
                patch=step_ctx.step_patch,
            )
        )

    async def _save_step_message(self, message: Message) -> bool:
        """Write a step lifecycle message; a failure never breaks the loop."""
        try:
            return await self.session_manager.save_message(
                role=message.role,
                content=None,
                message_type=message.message_type,
                turn_id=self.turn_id,
                agent_id=self.agent_id,
                data=message.data,
            )
        except Exception as e:
            logger.error(f"Error saving step message: {e}")
            return False

    async def _finalize_turn(
        self, turn_ctx: TurnContext, result: ExecutionResult
    ) -> bool:
        """Close the turn: hooks → ``save_turn_end`` → broadcast hooks (C3).

        ``save_turn_end`` must stay in the engine: hooks have no
        ``session_manager`` and the web backend reads the persisted turn status.
        """
        try:
            logger.info(f"turn ended with result: {result}")

            turn_ctx.result = result
            turn_ctx.data["turn_end_message"] = self._get_turn_end_message(result)
            turn_ctx.data["turn_end_message_id"] = f"msg_{uuid.uuid4().hex[:16]}"

            # State-computation phase (SnapshotHook fills ``changed_files``).
            await self._dispatch("on_turn_end", turn_ctx)

            saved = await self.session_manager.save_turn_end(
                turn_id=self.turn_id,
                agent_id=self.agent_id,
                message=turn_ctx.data["turn_end_message"],
                status=result.status.value,
                message_id=turn_ctx.data["turn_end_message_id"],
                changed_files=result.data.get("changed_files"),
            )

            # Outward-notification phase (always after the DB write).
            await self._dispatch("on_turn_finalized", turn_ctx)
            return saved
        except asyncio.CancelledError as e:
            logger.warning(f"_finalize_turn cancelled (loop may be shutting down): {e}")
            return False
        except (RuntimeError, Exception) as e:
            logger.error(f"Error in _finalize_turn: {e}")
            return False

    async def _truncate_last_assistant_message_with_tool_calls(self) -> None:
        """Drop the trailing assistant tool-call message (aborted turns)."""
        if self.context:
            await self.context.truncate_last_assistant_message_with_tool_calls(
                turn_id=self.turn_id, agent_id=self.agent_id
            )

    # ==================================================================
    # Main entry point
    # ==================================================================

    async def execute(
        self,
        message: Optional[Any],
        max_steps: Optional[int] = None,
        from_agent: Optional[bool] = False,
        *,
        allowed_tools: Optional[List[str]] = None,
        namespace: Optional[str] = None,
        message_source: Optional[Any] = None,
    ) -> ExecutionResult:
        """Execute one turn: setup → hooks → round → finalize.

        Args:
            message: Single ``Message``, a list of ``Message`` instances, or
                ``None``.
            message_source: Optional source for mid-step user message injection
                (non-blocking mode).
        """
        if message is None:
            return ExecutionResult(status=ExecutionStatus.SKIPPED)

        # Normalize to list
        if isinstance(message, list):
            messages = message
        else:
            messages = [message]

        # Per-turn execution params (review 2.5: no longer set externally).
        self.allowed_tools = allowed_tools
        self.namespace = namespace

        await self._ensure_strategies()

        turn_ctx: Optional[TurnContext] = None
        result: Optional[ExecutionResult] = None
        try:
            turn_ctx = await self._setup_turn(messages, from_agent)
            # Set AFTER _setup_turn because _reset_turn_scoped_state() wipes it.
            self._message_source = message_source
            await self._dispatch("on_turn_start", turn_ctx)
            result = await self._execute_round(turn_ctx, max_steps)
        except ValidationError as e:
            logger.error(f"ValidationError in execute: {e}")
            await self._send_execution_error(e, "VALIDATION_ERROR")
            result = self._make_error_result(ExecutionStatus.ERROR, e)
        except asyncio.CancelledError:
            logger.info("Execution cancelled by user")
            result = ExecutionResult(
                status=ExecutionStatus.ABORTED, message="Execution cancelled by user"
            )
        except SessionError as e:
            logger.error(f"SessionError in execute: {e}")
            await self._send_execution_error(e, "SESSION_ERROR")
            result = self._make_error_result(ExecutionStatus.ERROR, e)
        except BrocaError as e:
            logger.error(f"BrocaError in execute: {e}")
            await self._send_execution_error(e, "BROCA_ERROR")
            result = self._make_error_result(ExecutionStatus.ERROR, e)
        except Exception as e:
            logger.error(f"Unexpected error in execute: {e}")
            await self._send_execution_error(e, "UNKNOWN_ERROR")
            result = self._make_error_result(ExecutionStatus.ERROR, e)

        if turn_ctx is not None:
            try:
                if not await self._finalize_turn(turn_ctx, result):
                    logger.warning("Turn end processing failed")
            except Exception:
                # Defensive: never propagate from _finalize_turn after
                # a CancelledError or loop teardown.
                pass
        else:
            # Setup failed → no turn_id. Legacy wrote a turn_end row with a
            # ``None`` turn_id; we deliberately skip that dirty write.
            logger.warning("Turn setup failed; skip turn_end persistence")
        return result

    def _get_turn_end_message(self, result: ExecutionResult) -> str:
        """Human-readable turn-end summary (also used in error notifications)."""
        return _TURN_END_MESSAGES.get(result.status, "Turn failed")

    # ==================================================================
    # LLM callbacks (broadcast only — no retry policy here)
    # ==================================================================

    def _schedule_chunk_flush(self) -> None:
        """调度一个延迟 flush（时间兜底）"""
        if self._chunk_flush_task is None or self._chunk_flush_task.done():
            self._chunk_flush_task = asyncio.create_task(self._flush_chunks())

    def _flush_now(self) -> None:
        """立即 flush（长度达到阈值时调用）"""
        if self._chunk_flush_task and not self._chunk_flush_task.done():
            self._chunk_flush_task.cancel()
        self._chunk_flush_task = None
        asyncio.ensure_future(self._do_flush())

    async def _flush_chunks(self) -> None:
        """等待 FLUSH_INTERVAL 后合并发送 buffer 中的 chunks（时间兜底路径）"""
        from broca.loop_engine.chunk_flush import delayed_flush

        await delayed_flush(self._CHUNK_FLUSH_INTERVAL)
        await self._do_flush()

    async def _do_flush(self) -> None:
        """实际执行 flush：取出 buffer → merge → emit"""
        if not self._chunk_buffer:
            self._chunk_flush_task = None
            return
        chunks = self._chunk_buffer[:]
        self._chunk_buffer.clear()
        self._chunk_buffer_len = 0
        self._chunk_flush_task = None

        merged = self._merge_consecutive_chunks(chunks)
        for chunk in merged:
            try:
                kind = chunk.get("type")
                if kind in ("content", "reasoning_content"):
                    await self.communicator.send_agent_response(
                        content=chunk.get("data", "") if kind == "content" else "",
                        reasoning_content=(
                            chunk.get("data", "") if kind == "reasoning_content" else ""
                        ),
                        index=chunk.get("index", 0),
                        turn_id=self.turn_id,
                        agent_id=self.agent_id,
                        message_id=chunk.get("message_id", ""),
                        subscription=self.session_id,
                    )
            except Exception as e:
                logger.warning(f"Failed to broadcast merged LLM chunk: {e}")

    @staticmethod
    def _merge_consecutive_chunks(chunks: list) -> list:
        """合并连续同类型 (content/reasoning_content) chunks 的 data 字段"""
        if not chunks:
            return chunks
        merged = [chunks[0]]
        for chunk in chunks[1:]:
            prev = merged[-1]
            if (
                chunk.get("type") == prev.get("type")
                and chunk.get("type") in ("content", "reasoning_content")
                and chunk.get("index") == prev.get("index")
                and chunk.get("message_id") == prev.get("message_id")
            ):
                prev["data"] = prev.get("data", "") + chunk.get("data", "")
            else:
                merged.append(chunk)
        return merged

    def _make_chunk_handler(self):
        """Build the ``on_chunk`` callback handed to the LLM strategy."""

        async def _on_chunk(event: dict) -> None:
            if not getattr(self.config, "interactive", False):
                return
            try:
                kind = event.get("type")

                # tool_call 绕过 buffer，立即发送
                if kind == "tool_call":
                    tool_call = event.get("data")
                    name = getattr(getattr(tool_call, "function", None), "name", None)
                    if name:
                        await self.communicator.send_tool_call(
                            tool_name=name,
                            arguments=None,
                            tool_call_id=getattr(tool_call, "id", None),
                            turn_id=self.turn_id,
                            agent_id=self.agent_id,
                            subscription=self.session_id,
                        )
                    return

                # buffer 安全阀
                if len(self._chunk_buffer) > self._CHUNK_BUFFER_MAX:
                    self._flush_now()

                self._chunk_buffer.append(event)
                self._chunk_buffer_len += len(event.get("data", "") or "")
                if self._chunk_buffer_len >= self._CHUNK_FLUSH_CHARS:
                    self._flush_now()
                else:
                    self._schedule_chunk_flush()
            except Exception as e:
                logger.warning(f"Failed to broadcast LLM chunk: {e}")

        return _on_chunk

    def _make_error_handler(self):
        """Build the ``on_error`` callback handed to the LLM strategy."""

        async def _on_error(message: str, code: str, severity: str) -> None:
            if not getattr(self.config, "interactive", False):
                return
            try:
                await self.communicator.send_error(
                    {"message": message, "code": code, "severity": severity},
                    subscription=self.session_id,
                )
            except Exception as e:
                logger.warning(f"Failed to broadcast LLM error: {e}")

        return _on_error

    # ==================================================================
    # Tool helpers
    # ==================================================================

    def _get_tools_list(self) -> List[Dict[str, Any]]:
        return [tool.format() for tool in self.tool_mapping.values()]

    def _build_tool_context(self) -> ToolCallContext:
        ctx = ToolCallContext()
        ctx.agent = self.agent_ref
        ctx.workspace = self.config.workspace
        ctx.session_id = self.session_id
        ctx.execution_id = self.execution_id
        ctx.namespace = self.namespace
        ctx.turn_id = self.turn_id
        ctx.agent_id = self.agent_id
        return ctx

    # ==================================================================
    # Error reporting
    # ==================================================================

    async def _send_execution_error(
        self, error: Exception, code: str, severity: str = "error"
    ) -> None:
        """Send an execution error notification to the front end."""
        if getattr(self.config, "interactive", False):
            await self.communicator.send_error(
                {
                    "message": (
                        f"执行异常: {error}" if code == "UNKNOWN_ERROR" else str(error)
                    ),
                    "code": code,
                    "severity": severity,
                },
                subscription=self.session_id,
            )

    def _make_error_result(
        self, status: ExecutionStatus, error: Exception
    ) -> ExecutionResult:
        """Wrap an exception into an ``ExecutionResult``."""
        if isinstance(error, (BrocaError, ValidationError)):
            message = error.to_user_message()
        else:
            message = f"Unexpected error: {error}"
        return ExecutionResult(status=status, message=message)

    # ==================================================================
    # Lifecycle
    # ==================================================================

    def abort(self) -> None:
        """Abort the execution."""
        logger.info("Aborting execution engine")
        self.abort_event.set()
        # 立即 flush 残余 buffer
        if self._chunk_buffer:
            try:
                asyncio.ensure_future(self._do_flush())
            except RuntimeError:
                # 无 running event loop（跨线程调用场景），降级为同步清空
                self._chunk_buffer.clear()
                self._chunk_buffer_len = 0

    def reset(self) -> None:
        """Reset execution state (abort flag, turn id, per-turn state)."""
        self.abort_event.clear()
        self.turn_id = None
        if self.tool_executor is not None:
            self.tool_executor._permission_provider.clear_session_overrides()
        elif self.permission_provider is not None:
            self.permission_provider.clear_session_overrides()
        self._reset_turn_scoped_state()

