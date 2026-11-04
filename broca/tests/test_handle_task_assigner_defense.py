"""
Regression test: _handle_task defends against assigner=None.

Before the fix, when assigner was None and the task failed,
send_task_error(task_id, result, receiver_id=None) would be called,
potentially crashing or sending to an invalid target.
After the fix, assigner=None simply logs a warning without sending.
"""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from broca.agent import Agent
from broca.components.loop_engine import ExecutionResult, ExecutionStatus
from broca.session.models import Message, MessageRole, MessageType


def _make_agent():
    """Create a minimal Agent mock that uses the real _handle_task logic."""
    agent = MagicMock(spec=Agent)
    agent.agent_id = "test-agent"
    agent.name = "TestAgent"
    agent.communicator = MagicMock()
    agent.communicator.send_task_complete = AsyncMock()
    agent.communicator.send_task_error = AsyncMock()
    agent.context = MagicMock()
    agent.context.get_latest_assistant_message = MagicMock(return_value="done")
    agent.run = AsyncMock()
    # Bind the real _handle_task to the mock so it executes with our mocked deps
    agent._handle_task = Agent._handle_task.__get__(agent)
    return agent


def _make_task_message(task_id="task-1", assigner="agent-1"):
    return Message(
        message_type=MessageType.USER_MESSAGE,
        role=MessageRole.SYSTEM,
        sender_id=assigner or "system",
        data={"task_id": task_id, "assigner": assigner},
    )


class TestAssignerNoneDefense:
    """assigner=None should not cause crashes or invalid sends."""

    @pytest.mark.asyncio
    async def test_failure_no_assigner_no_send(self):
        """assigner=None + execution failure → no send_task_error call, only log."""
        agent = _make_agent()
        agent.run.return_value = ExecutionResult(
            status=ExecutionStatus.ERROR, message="something broke"
        )
        msg = _make_task_message(assigner=None)

        await agent._handle_task(msg)

        # send_task_error should NOT be called
        agent.communicator.send_task_error.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_success_no_assigner_no_send(self):
        """assigner=None + execution success → no send_task_complete call."""
        agent = _make_agent()
        agent.run.return_value = ExecutionResult(status=ExecutionStatus.COMPLETED)
        msg = _make_task_message(assigner=None)

        await agent._handle_task(msg)

        # send_task_complete should NOT be called
        agent.communicator.send_task_complete.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_failure_with_assigner_sends_error(self):
        """assigner='agent-1' + failure → send_task_error called."""
        agent = _make_agent()
        agent.run.return_value = ExecutionResult(
            status=ExecutionStatus.ERROR, message="broke"
        )
        msg = _make_task_message(task_id="task-42", assigner="agent-1")

        await agent._handle_task(msg)

        agent.communicator.send_task_error.assert_awaited_once()
        call_args = agent.communicator.send_task_error.call_args
        assert call_args[0][0] == "task-42"  # task_id
        assert call_args[1]["receiver_id"] == "agent-1"

    @pytest.mark.asyncio
    async def test_success_with_assigner_sends_complete(self):
        """assigner='agent-1' + success → send_task_complete called."""
        agent = _make_agent()
        agent.run.return_value = ExecutionResult(status=ExecutionStatus.COMPLETED)
        msg = _make_task_message(task_id="task-99", assigner="agent-1")

        await agent._handle_task(msg)

        agent.communicator.send_task_complete.assert_awaited_once()
        call_args = agent.communicator.send_task_complete.call_args
        assert call_args[0][0] == "task-99"
        assert call_args[0][2] == "agent-1"

    @pytest.mark.asyncio
    async def test_exception_no_assigner_no_crash(self):
        """Exception during run + assigner=None → no crash, just log."""
        agent = _make_agent()
        agent.run.side_effect = RuntimeError("boom")
        msg = _make_task_message(task_id="task-err", assigner=None)

        # Should not raise
        await agent._handle_task(msg)
        agent.communicator.send_task_error.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_exception_with_assigner_sends_error(self):
        """Exception during run + assigner='agent-1' → send_task_error."""
        agent = _make_agent()
        agent.run.side_effect = RuntimeError("boom")
        msg = _make_task_message(task_id="task-err", assigner="agent-1")

        await agent._handle_task(msg)

        agent.communicator.send_task_error.assert_awaited_once()
