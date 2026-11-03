"""Tests for the ``/compact`` command (Round-2 N1 — previously zero coverage).

The command used to call the engine's private ``_build_compressor_context()``,
which no longer exists (moved to ``loop_engine.compressor_context``).  These
tests pin the new wiring: the compressor comes from the agent, the context is
built by the standalone factory and ``check_and_compress(force=True)`` runs.
"""

from __future__ import annotations

import inspect
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import pytest

from broca.commands.base import CommandContext
from broca.commands.builtin.compact import CompactCommand
from broca.components.protocols import CompressorContext
from broca.context_compressor import CompressionStats


def _make_agent(compressor):
    agent = MagicMock()
    agent.status = "idle"
    agent.STATUS_RUNNING = "running"
    agent.agent_id = "agent-1"
    agent.session_id = "session-1"
    agent.last_context_length = 4242
    agent.config.name = "Tester"
    agent.config.provider = "openai"
    agent.config.model = "gpt-4o"
    agent.config.workspace = "/tmp/ws"
    agent.config.compact_config = MagicMock()
    agent.communicator = MagicMock(send_agent_system_message=AsyncMock())
    agent.context_compressor = compressor
    agent.execution_engine = MagicMock(
        session_manager=MagicMock(), session_id="session-1"
    )
    return agent


def _make_ctx(agent, context):
    return CommandContext(
        workspace="/tmp/ws",
        session_id="session-1",
        agent_id="agent-1",
        agent=agent,
        context=context,
    )


@pytest.mark.asyncio
async def test_compact_forces_compression_and_passes_compressor_context():
    compressor = MagicMock()
    compressor.check_and_compress = AsyncMock(
        return_value=CompressionStats(truncated_count=2)
    )
    agent = _make_agent(compressor)
    context = MagicMock()

    result = await CompactCommand().execute("", _make_ctx(agent, context))

    assert result.type == "text"
    compressor.check_and_compress.assert_awaited_once()
    kwargs = compressor.check_and_compress.await_args.kwargs
    assert kwargs["force"] is True
    assert kwargs["context"] is context
    assert kwargs["compressor_context"] is not None


@pytest.mark.asyncio
async def test_compact_context_satisfies_compressor_context_protocol():
    compressor = MagicMock()
    compressor.check_and_compress = AsyncMock(return_value=CompressionStats())
    agent = _make_agent(compressor)

    await CompactCommand().execute("", _make_ctx(agent, MagicMock()))

    cc_ctx = compressor.check_and_compress.await_args.kwargs["compressor_context"]
    assert isinstance(cc_ctx, CompressorContext)
    assert cc_ctx.agent_id == "agent-1"
    assert cc_ctx.session_id == "session-1"
    assert cc_ctx.provider == "openai"
    assert cc_ctx.model == "gpt-4o"
    assert cc_ctx.workspace == "/tmp/ws"
    assert cc_ctx.last_context_length == 4242


@pytest.mark.asyncio
async def test_compact_falls_back_to_registry_when_agent_has_no_compressor():
    """Non-interactive agents may not expose ``agent.context_compressor``."""
    from broca.components import ContextCompressor
    from broca.components.registry import ComponentRegistry

    registry = ComponentRegistry.get_instance()
    fallback = MagicMock()
    fallback.initialize = AsyncMock()
    fallback.check_and_compress = AsyncMock(return_value=CompressionStats())
    registry._instances[(ContextCompressor, "agent-1")] = fallback

    try:
        agent = _make_agent(None)
        result = await CompactCommand().execute("", _make_ctx(agent, MagicMock()))

        assert result.type == "text"
        fallback.initialize.assert_awaited_once()
        fallback.check_and_compress.assert_awaited_once()
    finally:
        registry._instances.pop((ContextCompressor, "agent-1"), None)


@pytest.mark.asyncio
async def test_compact_reports_error_when_compression_fails():
    compressor = MagicMock()
    compressor.check_and_compress = AsyncMock(side_effect=RuntimeError("boom"))
    agent = _make_agent(compressor)

    result = await CompactCommand().execute("", _make_ctx(agent, MagicMock()))

    assert result.type == "error"
    assert "boom" in result.value


def test_compact_no_longer_uses_the_engine_private_builder():
    """R14 guard: the removed ``_build_compressor_context`` must not come back.

    This path had zero coverage before Round-2 N1, so a silent regression
    (``AttributeError`` only at runtime, green CI) is a real risk.
    """
    source = Path(inspect.getfile(CompactCommand)).read_text()

    assert "_build_compressor_context" not in source
    assert "build_compressor_context" in source


def test_clear_commands_do_not_use_the_engine_private_builder():
    """Same guard for the three ``clear_*`` commands that compress context."""
    from broca.commands.builtin.clear_all_context import ClearAllContextCommand
    from broca.commands.builtin.clear_context import ClearContextCommand
    from broca.commands.builtin.clear_history import ClearHistoryCommand

    for command_cls in (ClearHistoryCommand, ClearContextCommand, ClearAllContextCommand):
        source = Path(inspect.getfile(command_cls)).read_text()
        assert "_build_compressor_context" not in source, command_cls.__name__
