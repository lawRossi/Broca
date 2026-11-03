"""Compression / memory hook — post-step context compression and memory extraction.

Migrated from ``DefaultLoopEngine._trigger_post_step_hooks()``.

Two independent concerns, each with its own gate:

* **Context compression** — awaited, gated by ``config.enable_context_compression``
  and a non-``None`` compressor.
* **Persistent memory extraction** — fire-and-forget (``asyncio.create_task``),
  gated by ``config.persistent_memory_config.auto_extract`` and a non-``None``
  memory manager.

Hook failures are logged and swallowed: a compression problem must never abort
the turn (plan decision "Hook 异常 catch + log，不中断").
"""

from __future__ import annotations

import asyncio
from typing import Any, Callable, Optional

from broca.components.loop_hook import LoopHook, StepContext
from broca.logging_config import get_logger

logger = get_logger(__name__)


class CompressionMemoryHook(LoopHook):
    """Run context compression and persistent-memory extraction after a step."""

    name = "compression"

    def __init__(
        self,
        context_compressor: Optional[Any] = None,
        memory_manager: Optional[Any] = None,
        config: Any = None,
        context: Optional[Any] = None,
        compressor_ctx_builder: Optional[Callable[[], Any]] = None,
    ):
        self._context_compressor = context_compressor
        self._memory_manager = memory_manager
        self._config = config
        self._context = context
        self._compressor_ctx_builder = compressor_ctx_builder

    # ------------------------------------------------------------------
    # Gating
    # ------------------------------------------------------------------

    @property
    def _compression_enabled(self) -> bool:
        return bool(getattr(self._config, "enable_context_compression", False)) and (
            self._context_compressor is not None
        )

    @property
    def _memory_enabled(self) -> bool:
        if self._memory_manager is None:
            return False
        memory_config = getattr(self._config, "persistent_memory_config", None)
        if memory_config is None:
            return False
        return bool(getattr(memory_config, "auto_extract", False))

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    async def on_post_step(self, ctx: StepContext) -> None:
        await self._compress()
        self._extract_memory()

    # ------------------------------------------------------------------
    # Compression
    # ------------------------------------------------------------------

    async def _compress(self) -> None:
        if not self._compression_enabled:
            return
        try:
            await self._context_compressor.check_and_compress(
                context=self._context,
                compressor_context=self._build_compressor_ctx(),
            )
        except Exception as e:
            logger.warning(f"Context compression failed: {e}")

    def _build_compressor_ctx(self) -> Optional[Any]:
        if self._compressor_ctx_builder is None:
            return None
        return self._compressor_ctx_builder()

    # ------------------------------------------------------------------
    # Persistent memory
    # ------------------------------------------------------------------

    def _extract_memory(self) -> None:
        """Fire-and-forget extraction; the step must not wait for it."""
        if not self._memory_enabled:
            return
        try:
            self._memory_manager.increment_step()
            task = asyncio.create_task(
                self._memory_manager.check_and_extract(context=self._context)
            )
            def _log_if_failed(t: asyncio.Task) -> None:
                if not t.cancelled():
                    exc = t.exception()
                    if exc is not None:
                        logger.warning(
                            f"Persistent memory extraction failed: {exc}"
                        )

            task.add_done_callback(_log_if_failed)
        except Exception as e:
            logger.warning(f"Persistent memory extraction failed to start: {e}")
