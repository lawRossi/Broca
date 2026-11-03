"""Behavior tests for command routing in start() and exception resilience.

Covers:
- start() routes /compact command messages to the command handler
  (execution_engine.execute NOT called)
- start() routes plain text messages to run() (command_manager.dispatch
  NOT called)
- start() survives unexpected exceptions (logger.exception called,
  self.running remains True)
"""

from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

# Reuse helpers from test_agent_composition
from broca.tests.test_agent_composition import (
    _make_agent_config,
    _make_mock_llm,
    _make_session_manager,
    _register_mock_tool_manager,
)


# ---------------------------------------------------------------------------
# Fixture
# ---------------------------------------------------------------------------


@pytest.fixture
def agent_registry(fresh_registry):
    """Fresh registry with mock ToolManager, patched as the singleton."""
    _register_mock_tool_manager(fresh_registry)
    with patch(
        "broca.components.registry.ComponentRegistry.get_instance",
        return_value=fresh_registry,
    ):
        yield fresh_registry


async def _run_start_until(agent, stop_after: asyncio.Event, wait: float = 0.15):
    """Run agent.start() as a background task; stop when stop_after is set.

    The caller should set ``stop_after`` once the desired assertion
    window has passed.  This helper then forces ``agent.running = False``
    so the start() loop exits cleanly.
    """
    task = asyncio.create_task(agent.start())
    await asyncio.sleep(wait)
    agent.running = False
    stop_after.set()
    await task
    return task


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


class TestAgentCommandRouting:
    """Command routing behavior in start() message loop."""

    @pytest.mark.asyncio
    async def test_start_routes_command_to_handler(
        self, agent_registry, test_workspace
    ):
        """Command message → command dispatch called, execution_engine NOT called.

        Mocks only ``command_manager.dispatch`` so the real
        ``_try_dispatch_inline_command`` → ``_handle_command`` path is exercised.
        """
        from broca.agent import Agent
        from broca.session import Message, MessageType

        sm = _make_session_manager()
        cfg = _make_agent_config(workspace=test_workspace)
        llm = _make_mock_llm()

        agent = await Agent.create(cfg, llm, sm, agent_id="test-cmd-route")

        # Ensure start() skips the connection check
        agent.is_connected = lambda: True

        # Mock the execution engine's execute to detect if it's called
        agent.execution_engine.execute = AsyncMock()

        # Mock command_manager.dispatch to track calls while keeping
        # the real _handle_command → _try_dispatch_inline_command path.
        # Return a non-None sentinel so _handle_command doesn't fall back to run().
        fake_result = MagicMock()
        fake_result.value = "compacted"
        dispatch_mock = AsyncMock(return_value=fake_result)
        agent.command_manager.dispatch = dispatch_mock
        # Avoid real message sending
        agent.command_manager.send_result = AsyncMock()

        # Create a command message: "/compact"
        cmd_msg = Message(
            message_type=MessageType.USER_MESSAGE,
            data={"content": "/compact"},
        )
        await agent.message_queue.put(cmd_msg)

        stop_event = asyncio.Event()
        await _run_start_until(agent, stop_event)

        # command_manager.dispatch should have been called for /compact
        assert dispatch_mock.called, (
            "command_manager.dispatch should be called for /compact command"
        )
        # Execution engine should NOT be called
        assert not agent.execution_engine.execute.called, (
            "execution_engine.execute should NOT be called for command messages"
        )

    @pytest.mark.asyncio
    async def test_start_routes_plain_text_to_run(
        self, agent_registry, test_workspace
    ):
        """Plain text message → execution_engine.execute called,
        command_manager.dispatch NOT called."""
        from broca.agent import Agent
        from broca.session import Message, MessageType

        sm = _make_session_manager()

        # save_history=True to skip reset() in run()'s finally block
        cfg = _make_agent_config(workspace=test_workspace, save_history=True)
        llm = _make_mock_llm()
        agent = await Agent.create(cfg, llm, sm, agent_id="test-plain-route")

        # Ensure start() skips the connection check
        agent.is_connected = lambda: True

        # Mock execution engine so run() doesn't hit real LLM
        agent.execution_engine.execute = AsyncMock()

        # Track whether command_manager.dispatch is called
        dispatch_mock = AsyncMock()
        agent.command_manager.dispatch = dispatch_mock

        # Create a plain text message (no / prefix → not a command)
        text_msg = Message(
            message_type=MessageType.USER_MESSAGE,
            data={"content": "Hello, how are you?"},
        )
        await agent.message_queue.put(text_msg)

        stop_event = asyncio.Event()
        await _run_start_until(agent, stop_event)

        # Execution engine should be called (via run())
        assert agent.execution_engine.execute.called, (
            "execution_engine.execute should be called for plain text messages"
        )
        # Command dispatch should NOT be called
        assert not dispatch_mock.called, (
            "command_manager.dispatch should NOT be called for plain text"
        )

    @pytest.mark.asyncio
    async def test_start_survives_unexpected_exception(
        self, agent_registry, test_workspace
    ):
        """run() raises ValueError → logger.exception called, running stays True."""
        from broca.agent import Agent
        from broca.session import Message, MessageType

        sm = _make_session_manager()
        cfg = _make_agent_config(workspace=test_workspace)
        llm = _make_mock_llm()

        agent = await Agent.create(cfg, llm, sm, agent_id="test-exception")

        # Ensure start() skips the connection check
        agent.is_connected = lambda: True

        # Make run() raise ValueError
        async def _raising_run(*args, **kwargs):
            raise ValueError("simulated crash")

        agent.run = _raising_run

        # Create a plain text message (will trigger run())
        text_msg = Message(
            message_type=MessageType.USER_MESSAGE,
            data={"content": "trigger exception"},
        )
        await agent.message_queue.put(text_msg)

        # Patch logger.exception to track calls
        with patch(
            "broca.agent.logger.exception"
        ) as mock_exc:
            # Run start() and wait long enough for the exception to be caught
            task = asyncio.create_task(agent.start())
            await asyncio.sleep(0.15)

            # At this point the exception has been handled; loop should
            # still be running (self.running remains True)
            assert mock_exc.call_count >= 1, (
                "logger.exception should be called for unexpected ValueError"
            )
            assert agent.running is True, (
                "agent.running should still be True after an unexpected "
                "exception is caught by the start() loop"
            )

            # Clean up: force the loop to exit
            agent.running = False
            await task


class TestIPCCommandResultSending:
    """回归测试：IPC 命令（_on_command）必须始终将结果发送回前端。

    Bug: 重构后 _on_command 改为调用 command_manager.send_result()，
    该方法仅在 cmd.show_result==True 时才发送结果。UndoCommand.show_result=False
    导致 undo 成功结果被静默丢弃，前端收不到 command_result 事件。

    修复后 _on_command 应直接调用 communicator.send_command_result / send_error。
    """

    @pytest.mark.asyncio
    async def test_on_command_sends_result_directly_via_communicator(
        self, agent_registry, test_workspace
    ):
        """IPC undo 命令成功 → communicator.send_command_result 被调用"""
        from broca.agent import Agent
        from broca.session import Message, MessageType

        sm = _make_session_manager()
        cfg = _make_agent_config(workspace=test_workspace)
        llm = _make_mock_llm()
        agent = await Agent.create(cfg, llm, sm, agent_id="test-ipc-cmd")

        # Mock communicator
        agent.communicator = MagicMock()
        agent.communicator.send_command_result = AsyncMock()
        agent.communicator.send_error = AsyncMock()

        # Mock command_manager: dispatch returns success, send_result should NOT be used
        undo_result = MagicMock()
        undo_result.type = "text"
        undo_result.value = "Undo successful, 0 files changed"
        agent.command_manager.dispatch = AsyncMock(return_value=undo_result)
        agent.command_manager.send_result = AsyncMock()
        agent.command_manager.registry.has = MagicMock(return_value=True)

        # Construct a command message as if received via IPC
        cmd_message = Message(
            message_type=MessageType.COMMAND,
            data={"command": "undo", "arguments": {}},
            message_id="cmd-test-1",
        )

        await agent._on_command(cmd_message)

        # communicator.send_command_result 必须被调用（不再受 show_result 控制）
        agent.communicator.send_command_result.assert_called_once()
        call_kwargs = agent.communicator.send_command_result.call_args[1]
        assert call_kwargs["command"] == "undo"
        assert call_kwargs["result"]["code"] == 0

        # command_manager.send_result 不应被调用（IPC 路径直发 communicator）
        agent.command_manager.send_result.assert_not_called()

    @pytest.mark.asyncio
    async def test_on_command_sends_error_via_communicator(
        self, agent_registry, test_workspace
    ):
        """IPC 命令执行失败 → communicator.send_error 被调用"""
        from broca.agent import Agent
        from broca.session import Message, MessageType

        sm = _make_session_manager()
        cfg = _make_agent_config(workspace=test_workspace)
        llm = _make_mock_llm()
        agent = await Agent.create(cfg, llm, sm, agent_id="test-ipc-cmd-err")

        agent.communicator = MagicMock()
        agent.communicator.send_command_result = AsyncMock()
        agent.communicator.send_error = AsyncMock()

        error_result = MagicMock()
        error_result.type = "error"
        error_result.value = "No target message found"
        agent.command_manager.dispatch = AsyncMock(return_value=error_result)
        agent.command_manager.send_result = AsyncMock()
        agent.command_manager.registry.has = MagicMock(return_value=True)

        cmd_message = Message(
            message_type=MessageType.COMMAND,
            data={"command": "undo", "arguments": {}},
            message_id="cmd-test-2",
        )

        await agent._on_command(cmd_message)

        # send_error 应被调用
        agent.communicator.send_error.assert_called_once()
        # send_command_result 不应被调用
        agent.communicator.send_command_result.assert_not_called()
        # command_manager.send_result 不应被调用
        agent.command_manager.send_result.assert_not_called()

    @pytest.mark.asyncio
    async def test_on_unknown_command_sends_error(
        self, agent_registry, test_workspace
    ):
        """IPC 收到未注册命令 → communicator.send_error 被调用"""
        from broca.agent import Agent
        from broca.session import Message, MessageType

        sm = _make_session_manager()
        cfg = _make_agent_config(workspace=test_workspace)
        llm = _make_mock_llm()
        agent = await Agent.create(cfg, llm, sm, agent_id="test-ipc-cmd-unknown")

        agent.communicator = MagicMock()
        agent.communicator.send_error = AsyncMock()
        agent.command_manager.registry.has = MagicMock(return_value=False)

        cmd_message = Message(
            message_type=MessageType.COMMAND,
            data={"command": "nonexistent", "arguments": {}},
            message_id="cmd-test-3",
        )

        await agent._on_command(cmd_message)

        agent.communicator.send_error.assert_called_once()
