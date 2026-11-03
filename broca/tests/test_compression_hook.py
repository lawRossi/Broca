"""Unit tests for ``CompressionMemoryHook`` + ``build_compressor_context`` (Task 3.3).

Covers the migration of ``_trigger_post_step_hooks`` and
``_build_compressor_context``.
"""

from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, MagicMock

import pytest

from broca.components.loop_hook import StepContext
from broca.components.compressor_context_factory import build_compressor_context
from broca.loop_engine.hooks.compression_hook import CompressionMemoryHook


class FakeMemoryConfig:
    def __init__(self, auto_extract: bool = True):
        self.auto_extract = auto_extract


class FakeConfig:
    def __init__(
        self,
        enable_compression: bool = True,
        auto_extract: bool = True,
        workspace: str = "/tmp/ws",
        compact_config=None,
    ):
        self.enable_context_compression = enable_compression
        self.persistent_memory_config = FakeMemoryConfig(auto_extract)
        self.workspace = workspace
        self.compact_config = compact_config if compact_config is not None else object()


def make_step_ctx() -> StepContext:
    return StepContext(
        step_id="step-1",
        turn_id="turn-1",
        agent_id="agent-1",
        session_id="sess-1",
    )


class TestCompressorContextFactory:
    def test_exposes_protocol_attributes(self):
        agent_ref = MagicMock()
        agent_ref.last_context_length = 1234
        agent_ref.config.provider = "openai"
        agent_ref.config.model = "gpt-4o"
        config = FakeConfig()
        communicator = MagicMock()
        session_manager = MagicMock()

        ctx = build_compressor_context(
            agent_ref=agent_ref,
            config=config,
            communicator=communicator,
            session_manager=session_manager,
            agent_id="agent-1",
            session_id="sess-1",
        )

        assert ctx.last_context_length == 1234
        assert ctx.compact_config is config.compact_config
        assert ctx.provider == "openai"
        assert ctx.model == "gpt-4o"
        assert ctx.workspace == "/tmp/ws"
        # extras kept from the legacy adapter
        assert ctx.agent_id == "agent-1"
        assert ctx.session_id == "sess-1"
        assert ctx.communicator is communicator
        assert ctx.session_manager is session_manager

    def test_provider_and_model_are_lazy(self):
        agent_ref = MagicMock()
        agent_ref.last_context_length = None
        agent_ref.config.provider = "openai"
        agent_ref.config.model = "gpt-4o"
        ctx = build_compressor_context(
            agent_ref=agent_ref,
            config=FakeConfig(),
            communicator=None,
            session_manager=None,
            agent_id="a",
            session_id="s",
        )

        agent_ref.config.provider = "anthropic"
        agent_ref.config.model = "claude"
        assert ctx.provider == "anthropic"
        assert ctx.model == "claude"

    def test_missing_last_context_length_defaults_to_none(self):
        ctx = build_compressor_context(
            agent_ref=object(),
            config=FakeConfig(),
            communicator=None,
            session_manager=None,
            agent_id="a",
            session_id="s",
        )
        assert ctx.last_context_length is None


class TestCompressionGating:
    @pytest.mark.asyncio
    async def test_compression_called_with_context_and_compressor_context(self):
        compressor = MagicMock()
        compressor.check_and_compress = AsyncMock()
        builder = MagicMock(return_value="CC")
        hook = CompressionMemoryHook(
            context_compressor=compressor,
            memory_manager=None,
            config=FakeConfig(auto_extract=False),
            context="CTX",
            compressor_ctx_builder=builder,
        )

        await hook.on_post_step(make_step_ctx())

        compressor.check_and_compress.assert_awaited_once_with(
            context="CTX", compressor_context="CC"
        )
        builder.assert_called_once_with()

    @pytest.mark.asyncio
    async def test_disabled_by_config_skips_compression(self):
        compressor = MagicMock()
        compressor.check_and_compress = AsyncMock()
        hook = CompressionMemoryHook(
            context_compressor=compressor,
            config=FakeConfig(enable_compression=False, auto_extract=False),
            context="CTX",
            compressor_ctx_builder=lambda: "CC",
        )

        await hook.on_post_step(make_step_ctx())

        assert compressor.check_and_compress.await_count == 0

    @pytest.mark.asyncio
    async def test_missing_compressor_skips_compression(self):
        hook = CompressionMemoryHook(
            context_compressor=None,
            config=FakeConfig(auto_extract=False),
            context="CTX",
            compressor_ctx_builder=lambda: "CC",
        )

        await hook.on_post_step(make_step_ctx())  # must not raise

    @pytest.mark.asyncio
    async def test_compression_failure_is_swallowed(self):
        compressor = MagicMock()
        compressor.check_and_compress = AsyncMock(side_effect=RuntimeError("boom"))
        hook = CompressionMemoryHook(
            context_compressor=compressor,
            config=FakeConfig(auto_extract=False),
            context="CTX",
            compressor_ctx_builder=lambda: "CC",
        )

        await hook.on_post_step(make_step_ctx())  # must not raise


class TestMemoryGating:
    @pytest.mark.asyncio
    async def test_memory_extraction_is_fire_and_forget(self):
        memory_manager = MagicMock()
        memory_manager.increment_step = MagicMock()
        memory_manager.check_and_extract = AsyncMock()
        hook = CompressionMemoryHook(
            context_compressor=None,
            memory_manager=memory_manager,
            config=FakeConfig(enable_compression=False, auto_extract=True),
            context="CTX",
        )

        await hook.on_post_step(make_step_ctx())

        memory_manager.increment_step.assert_called_once_with()
        memory_manager.check_and_extract.assert_called_once_with(context="CTX")
        # the extraction coroutine runs as a separate task → not awaited inline
        assert isinstance(memory_manager.check_and_extract.return_value, object)
        await asyncio.sleep(0)  # let the background task finish

    @pytest.mark.asyncio
    async def test_auto_extract_false_skips_memory(self):
        memory_manager = MagicMock()
        memory_manager.check_and_extract = AsyncMock()
        hook = CompressionMemoryHook(
            context_compressor=None,
            memory_manager=memory_manager,
            config=FakeConfig(enable_compression=False, auto_extract=False),
            context="CTX",
        )

        await hook.on_post_step(make_step_ctx())

        assert memory_manager.increment_step.call_count == 0
        assert memory_manager.check_and_extract.await_count == 0

    @pytest.mark.asyncio
    async def test_missing_memory_manager_skips_memory(self):
        hook = CompressionMemoryHook(
            context_compressor=None,
            memory_manager=None,
            config=FakeConfig(enable_compression=False, auto_extract=True),
            context="CTX",
        )

        await hook.on_post_step(make_step_ctx())  # must not raise

    @pytest.mark.asyncio
    async def test_missing_persistent_memory_config_skips_memory(self):
        memory_manager = MagicMock()
        config = FakeConfig(enable_compression=False)
        config.persistent_memory_config = None
        hook = CompressionMemoryHook(
            context_compressor=None,
            memory_manager=memory_manager,
            config=config,
            context="CTX",
        )

        await hook.on_post_step(make_step_ctx())

        assert memory_manager.increment_step.call_count == 0


class TestHookContract:
    def test_name_is_unique(self):
        assert CompressionMemoryHook.name == "compression"

    def test_instantiable_without_dependencies(self):
        hook = CompressionMemoryHook()
        assert hook._compression_enabled is False
        assert hook._memory_enabled is False
