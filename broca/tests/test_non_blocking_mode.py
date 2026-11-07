"""Non-blocking loop engine mode tests.

Covers:
- TC-1: Multi initial messages → _setup_turn processes all
- TC-2: Mid-step injection → LLM 2nd call sees new message
- TC-3: COMPLETED termination → even if mid-step has messages
- TC-4: Blocking compat → message_source=None
- TC-5: Abort → drain not executed
- TC-6: max_steps limit
- TC-7: _drain_user_messages selective drain
- TC-8: _drain_user_messages empty queue
"""

import asyncio
from unittest.mock import AsyncMock, MagicMock

import pytest

from broca.agent import Agent
from broca.components.loop_hook import StepContext, TurnContext
from broca.loop_engine import DefaultLoopEngine, ExecutionResult, ExecutionStatus
from broca.session import Message, MessageProtocol, MessageType


# ============================================================================
# Fixtures (same pattern as test_loop_engine.py)
# ============================================================================


@pytest.fixture
def mock_agent():
    agent = MagicMock()
    agent.agent_id = "test-agent"
    agent.turn_id = None
    agent.config.provider = "openai"
    agent.config.model = "gpt-4o"
    agent.config.interactive = False
    from broca.configs import ExecutionConfig

    agent.config.execution_config = ExecutionConfig()
    agent.config.workspace = ""
    agent.config.enable_snapshot_tracking = False
    return agent


@pytest.fixture
def mock_llm_client():
    client = MagicMock()
    client.parse_message = MagicMock(
        return_value={"role": "user", "content": "test", "raw_input": "test"}
    )
    return client


@pytest.fixture
def mock_context():
    ctx = MagicMock()
    ctx.history = [{"role": "system", "content": "sys"}]
    ctx._history = [{"role": "system", "content": "sys"}]
    ctx.add_message = AsyncMock()
    return ctx


@pytest.fixture
def mock_session_manager():
    sm = MagicMock()
    sm.session_id = "test-session"
    sm.create_session = AsyncMock()
    sm.start_turn = AsyncMock(return_value="turn-1")
    sm.save_message = AsyncMock(return_value="msg-id-1")
    sm.save_agent_response = AsyncMock(return_value=True)
    sm.save_turn_end = AsyncMock(return_value=True)
    return sm


@pytest.fixture
def mock_communicator():
    comm = AsyncMock()
    comm.send_message = AsyncMock()
    comm.send_error = AsyncMock()
    return comm


@pytest.fixture
def engine(mock_agent, mock_llm_client, mock_context, mock_session_manager, mock_communicator):
    """Create DefaultLoopEngine with all mocks."""
    eng = DefaultLoopEngine(
        agent_ref=mock_agent,
        llm_client=mock_llm_client,
        context=mock_context,
        tool_mapping={},
        config=mock_agent.config,
        communicator=mock_communicator,
        session_manager=mock_session_manager,
    )
    return eng


def _make_user_message(content: str, msg_id: str = None) -> Message:
    """Helper: create a USER_MESSAGE with given content."""
    m = MessageProtocol.create_user_message(content)
    if msg_id:
        m.message_id = msg_id
    return m


# ============================================================================
# TC-1: Multi initial messages — _setup_turn processes all
# ============================================================================


class TestMultiMessageSetup:
    """TC-1: 传入 list[Message]（3 条）时，save_message 被调用 3 次"""

    @pytest.mark.asyncio
    async def test_three_messages_setup(self, engine, mock_session_manager, mock_context):
        msgs = [
            _make_user_message("hello", "m1"),
            _make_user_message("world", "m2"),
            _make_user_message("again", "m3"),
        ]

        turn_ctx = await engine._setup_turn(msgs, False)

        # save_message called 3 times (once per message)
        assert mock_session_manager.save_message.call_count == 3
        # add_message called 3 times
        assert mock_context.add_message.call_count == 3
        # TurnContext fields from first message
        assert turn_ctx.turn_id == "turn-1"
        assert turn_ctx.user_message is not None


# ============================================================================
# TC-2: Mid-step injection — LLM 2nd call sees new message
# ============================================================================


class TestMidStepInjection:
    """TC-2: message_source.drain() returns new message → injected into context"""

    @pytest.mark.asyncio
    async def test_midstep_injection(self, engine, mock_session_manager, mock_context):
        # Mock: step 1 → tool_call (not terminal), step 2 → COMPLETED
        step1 = MagicMock(spec=StepContext)
        step1.status = ExecutionStatus.RUNNING
        step2 = MagicMock(spec=StepContext)
        step2.status = ExecutionStatus.COMPLETED
        engine._execute_step = AsyncMock(side_effect=[step1, step2])

        # Message source: first drain returns [new_msg], second returns []
        new_msg = _make_user_message("injected!", "injected_1")
        msg_source = MagicMock()
        msg_source.drain = AsyncMock(side_effect=[[new_msg], []])
        engine._message_source = msg_source

        turn_ctx = MagicMock(spec=TurnContext)
        turn_ctx.turn_id = "turn-1"
        turn_ctx.agent_id = "test-agent"
        turn_ctx.session_id = "test-session"

        result = await engine._execute_round(turn_ctx, max_steps=5)

        # drain called only after step 1 (non-terminal) — the injected message is
        # picked up for the next step. Step 2 is terminal, so no drain happens there
        # (see TC-3 / TC-10: pending messages are left for the next turn).
        assert msg_source.drain.call_count == 1
        # The injected message was persisted
        # (save_message called at least once for the injected message)
        assert mock_session_manager.save_message.call_count >= 1
        # Turn completed
        assert result.status == ExecutionStatus.COMPLETED


# ============================================================================
# TC-3: COMPLETED termination — even if mid-step has messages
# ============================================================================


class TestCompletedWithMidStep:
    """TC-3: COMPLETED → turn ends WITHOUT absorbing pending messages.

    A message that is still pending when a terminal step finishes must be LEFT
    in the queue so the next turn answers it. Draining it into the dying turn
    would persist it under the wrong turn, never answer it (the LLM already said
    "done"), and — having been drained from the queue — never reprocess it
    (silently swallowed). This is the regression this test guards.
    """

    @pytest.mark.asyncio
    async def test_completed_does_not_absorb_pending(self, engine, mock_session_manager, mock_context):
        # Step 1 → COMPLETED immediately
        step1 = MagicMock(spec=StepContext)
        step1.status = ExecutionStatus.COMPLETED
        engine._execute_step = AsyncMock(return_value=step1)

        # Message source has a pending message
        pending_msg = _make_user_message("late msg", "late_1")
        msg_source = MagicMock()
        msg_source.drain = AsyncMock(return_value=[pending_msg])
        engine._message_source = msg_source

        turn_ctx = MagicMock(spec=TurnContext)
        turn_ctx.turn_id = "turn-1"
        turn_ctx.agent_id = "test-agent"
        turn_ctx.session_id = "test-session"

        result = await engine._execute_round(turn_ctx, max_steps=5)

        # Turn completed (COMPLETED is terminal)
        assert result.status == ExecutionStatus.COMPLETED
        # Terminal step must NOT drain — pending message stays for the next turn
        assert msg_source.drain.call_count == 0
        # Nothing injected into the dying turn (no persist / no context add)
        assert mock_session_manager.save_message.call_count == 0
        assert mock_context.add_message.call_count == 0


# ============================================================================
# TC-4: Blocking compat — message_source=None
# ============================================================================


class TestBlockingCompat:
    """TC-4: message_source=None → drain never called"""

    @pytest.mark.asyncio
    async def test_no_source_no_drain(self, engine):
        step1 = MagicMock(spec=StepContext)
        step1.status = ExecutionStatus.COMPLETED
        engine._execute_step = AsyncMock(return_value=step1)

        # No message source (blocking mode)
        engine._message_source = None

        turn_ctx = MagicMock(spec=TurnContext)
        turn_ctx.turn_id = "turn-1"
        turn_ctx.agent_id = "test-agent"
        turn_ctx.session_id = "test-session"

        result = await engine._execute_round(turn_ctx, max_steps=5)

        assert result.status == ExecutionStatus.COMPLETED
        # No drain possible since _message_source is None
        assert engine._message_source is None


# ============================================================================
# TC-5: Abort → drain not executed
# ============================================================================


class TestAbortBlocksDrain:
    """TC-5: abort_event.set() → drain never called"""

    @pytest.mark.asyncio
    async def test_abort_before_round(self, engine):
        """Abort set BEFORE the round → while-loop exits immediately, no drain."""
        engine.abort_event.set()

        msg_source = MagicMock()
        msg_source.drain = AsyncMock(return_value=[])
        engine._message_source = msg_source

        turn_ctx = MagicMock(spec=TurnContext)
        turn_ctx.turn_id = "turn-1"
        turn_ctx.agent_id = "test-agent"
        turn_ctx.session_id = "test-session"

        result = await engine._execute_round(turn_ctx, max_steps=5)

        assert result.status == ExecutionStatus.ABORTED
        assert msg_source.drain.call_count == 0

    @pytest.mark.asyncio
    async def test_abort_during_step(self, engine):
        """Abort set DURING step execution (LLM call) → drain not called after step.

        Simulates: _execute_step completes, abort_event gets set (e.g., by a
        concurrent user action), then the drain guard `not abort_event.is_set()`
        prevents the mid-step injection.
        """

        def abort_on_step():
            engine.abort_event.set()
            step = MagicMock(spec=StepContext)
            step.status = ExecutionStatus.RUNNING
            return step

        engine._execute_step = AsyncMock(side_effect=[abort_on_step()])

        msg_source = MagicMock()
        msg_source.drain = AsyncMock(return_value=[_make_user_message("x", "x1")])
        engine._message_source = msg_source

        turn_ctx = MagicMock(spec=TurnContext)
        turn_ctx.turn_id = "turn-1"
        turn_ctx.agent_id = "test-agent"
        turn_ctx.session_id = "test-session"

        result = await engine._execute_round(turn_ctx, max_steps=5)

        # After step 1, abort is set → drain guard blocks
        assert msg_source.drain.call_count == 0
        # Next loop iteration detects abort → ABORTED
        assert result.status == ExecutionStatus.ABORTED


# ============================================================================
# TC-6: max_steps limit
# ============================================================================


class TestMaxSteps:
    """TC-6: max_steps=2, LLM always returns tool_call → LIMIT_EXCEEDED"""

    @pytest.mark.asyncio
    async def test_max_steps_exceeded(self, engine):
        # Always returns non-terminal status (RUNNING)
        step = MagicMock(spec=StepContext)
        step.status = ExecutionStatus.RUNNING
        engine._execute_step = AsyncMock(return_value=step)

        turn_ctx = MagicMock(spec=TurnContext)
        turn_ctx.turn_id = "turn-1"
        turn_ctx.agent_id = "test-agent"
        turn_ctx.session_id = "test-session"

        result = await engine._execute_round(turn_ctx, max_steps=2)

        assert result.status == ExecutionStatus.LIMIT_EXCEEDED
        # Exactly 2 steps executed
        assert engine._execute_step.call_count == 2


# ============================================================================
# TC-7: _drain_user_messages selective drain
# ============================================================================


class TestDrainUserMessages:
    """TC-7: Queue pre-filled with mixed types → only USER_MESSAGE returned"""

    @pytest.mark.asyncio
    async def test_selective_drain(self):
        agent = Agent.__new__(Agent)
        agent.message_queue = asyncio.Queue(maxsize=10)

        user_a = _make_user_message("A", "A")
        user_b = _make_user_message("B", "B")
        user_c = _make_user_message("C", "C")
        task_start = MessageProtocol.create_task_start("x", task_description="do it")
        task_start.message_id = "T"

        # Simulate: first_msg (user_a) was already dequeued by queue.get()
        # Queue now contains: user_b, task_start, user_c
        for m in [user_b, task_start, user_c]:
            agent.message_queue.put_nowait(m)

        results = agent._drain_user_messages(user_a)

        # All USER_MESSAGEs returned (including first_msg)
        result_ids = {m.message_id for m in results}
        assert result_ids == {"A", "B", "C"}
        # Non-USER message (task_start) re-queued
        assert agent.message_queue.qsize() == 1
        remaining = agent.message_queue.get_nowait()
        assert remaining.message_id == "T"


# ============================================================================
# TC-8: _drain_user_messages empty queue
# ============================================================================


class TestDrainEmptyQueue:
    """TC-8: Empty queue → returns [first_msg] only"""

    @pytest.mark.asyncio
    async def test_empty_queue(self):
        agent = Agent.__new__(Agent)
        agent.message_queue = asyncio.Queue(maxsize=10)

        first = _make_user_message("hello", "F")
        results = agent._drain_user_messages(first)

        assert len(results) == 1
        assert results[0].message_id == "F"


# ============================================================================
# TC-9: execute() end-to-end — message_source survives _setup_turn reset
# ============================================================================


class TestExecuteEndToEnd:
    """TC-9: Regression: _message_source must survive _reset_turn_scoped_state()
    which is called inside _setup_turn(). This test calls engine.execute()
    (the real production path) instead of bypassing it via _execute_round().
    """

    @pytest.mark.asyncio
    async def test_execute_preserves_message_source(
        self, engine, mock_session_manager, mock_context, mock_communicator
    ):
        """Verify message_source.drain() is actually called during execute()."""
        # Step 1 → RUNNING (tool call), Step 2 → COMPLETED
        step1 = MagicMock(spec=StepContext)
        step1.status = ExecutionStatus.RUNNING
        step2 = MagicMock(spec=StepContext)
        step2.status = ExecutionStatus.COMPLETED
        engine._execute_step = AsyncMock(side_effect=[step1, step2])

        # message_source that returns one message then empty
        injected_msg = _make_user_message("injected during execute", "exec_inj_1")
        msg_source = MagicMock()
        msg_source.drain = AsyncMock(side_effect=[[injected_msg], []])

        msg = _make_user_message("start turn", "start_1")
        result = await engine.execute(msg, message_source=msg_source)

        # The critical assertion: drain WAS called (meaning _message_source
        # survived _setup_turn → _reset_turn_scoped_state)
        # The critical assertion: drain WAS called for the non-terminal step
        # (meaning _message_source survived _setup_turn →
        # _reset_turn_scoped_state). Step 2 is terminal, so no drain there.
        assert msg_source.drain.call_count == 1, (
            f"Expected 1 drain call (after the non-terminal step), got "
            f"{msg_source.drain.call_count}. "
            "message_source was likely wiped by _reset_turn_scoped_state()."
        )
        # Turn completed successfully
        assert result.status == ExecutionStatus.COMPLETED

    @pytest.mark.asyncio
    async def test_execute_blocking_mode_no_drain(
        self, engine, mock_session_manager, mock_context
    ):
        """message_source=None → drain is never called (blocking compat)."""
        step1 = MagicMock(spec=StepContext)
        step1.status = ExecutionStatus.COMPLETED
        engine._execute_step = AsyncMock(return_value=step1)

        msg = _make_user_message("single", "blk_1")
        result = await engine.execute(msg)  # no message_source

        assert result.status == ExecutionStatus.COMPLETED
        assert engine._message_source is None


# ============================================================================
# TC-10: terminal step must NOT swallow a message sent mid-execution
#        (real queue + real drainer — models "user sends during long bash /
#         final answer, message arrives while the turn is completing")
# ============================================================================


class TestTerminalStepLeavesMessagesQueued:
    """TC-10: A user message that arrives while the turn is completing must be
    left in the queue so the next turn answers it — not silently swallowed.

    This models the reported bug: with a long bash step, a message sent mid-turn
    sometimes reached the queue during the FINAL (COMPLETED) step. The engine used
    to drain it into the dying turn (persisted + added to context) but never answer
    it, and because it was drained from the queue it was never reprocessed either.
    """

    @pytest.mark.asyncio
    async def test_message_during_terminal_step_stays_queued(
        self, engine, mock_session_manager, mock_context
    ):
        # Real message queue + the real _Drainer used in production.
        agent = Agent.__new__(Agent)
        agent.message_queue = asyncio.Queue(maxsize=10)

        # A message arrives while the (final) step is running.
        pending = _make_user_message("sent during final answer", "final_1")
        agent.message_queue.put_nowait(pending)

        # Wire the real drainer into the engine.
        engine._message_source = agent._make_message_source()

        # The single step is terminal (LLM said "done", no tool calls).
        step1 = MagicMock(spec=StepContext)
        step1.status = ExecutionStatus.COMPLETED
        engine._execute_step = AsyncMock(return_value=step1)

        turn_ctx = MagicMock(spec=TurnContext)
        turn_ctx.turn_id = "turn-1"
        turn_ctx.agent_id = "test-agent"
        turn_ctx.session_id = "test-session"

        result = await engine._execute_round(turn_ctx, max_steps=5)

        # Turn ended normally...
        assert result.status == ExecutionStatus.COMPLETED
        # ...and the message is STILL in the queue, ready for the next turn.
        assert agent.message_queue.qsize() == 1
        remaining = agent.message_queue.get_nowait()
        assert remaining.message_id == "final_1"
        # It was NOT persisted / injected into the dying turn.
        assert mock_session_manager.save_message.call_count == 0
        assert mock_context.add_message.call_count == 0

    @pytest.mark.asyncio
    async def test_message_during_nonterminal_step_is_injected(
        self, engine, mock_session_manager, mock_context
    ):
        """Control: a message arriving during a NON-terminal step (e.g. bash) IS
        drained and injected so the next step's LLM call sees it."""
        agent = Agent.__new__(Agent)
        agent.message_queue = asyncio.Queue(maxsize=10)

        during_bash = _make_user_message("sent during bash", "bash_1")
        agent.message_queue.put_nowait(during_bash)
        engine._message_source = agent._make_message_source()

        step1 = MagicMock(spec=StepContext)
        step1.status = ExecutionStatus.RUNNING  # bash step — more steps to come
        step2 = MagicMock(spec=StepContext)
        step2.status = ExecutionStatus.COMPLETED
        engine._execute_step = AsyncMock(side_effect=[step1, step2])

        turn_ctx = MagicMock(spec=TurnContext)
        turn_ctx.turn_id = "turn-1"
        turn_ctx.agent_id = "test-agent"
        turn_ctx.session_id = "test-session"

        result = await engine._execute_round(turn_ctx, max_steps=5)

        assert result.status == ExecutionStatus.COMPLETED
        # Drained from the queue after the non-terminal step...
        assert agent.message_queue.qsize() == 0
        # ...and injected so the next step's LLM sees it.
        assert mock_session_manager.save_message.call_count == 1
        assert mock_context.add_message.call_count == 1
