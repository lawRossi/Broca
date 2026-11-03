"""ContextCompressor component interface.

Unified token monitoring + memory extraction + truncation compression.
The default implementation (``SessionMemoryCompressor``) merges the current
``ContextCompressor`` and ``SessionMemoryManager`` responsibilities.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import TYPE_CHECKING, Optional

from broca.components.base import BaseComponent

if TYPE_CHECKING:
    from broca.components.protocols import CompressorContext
    from broca.context import Context
    from broca.context_compressor import CompressionStats


class ContextCompressor(BaseComponent, ABC):
    """Context compressor interface — unified token monitoring + compression.

    Note: There is **no** abstract method ``force_compress()``.
    Forced compression is achieved via ``check_and_compress(force=True)``.
    Convenience non-abstract wrappers may be added in concrete implementations.
    """

    # ------------------------------------------------------------------
    # Path management (originally SessionMemoryManager)
    # ------------------------------------------------------------------

    @property
    @abstractmethod
    def snapshot_memory_path(self) -> str:
        """Path to the latest snapshot memory file."""
        ...

    @property
    @abstractmethod
    def memory_path(self) -> str:
        """Path to the frozen session memory file."""
        ...

    # ------------------------------------------------------------------
    # Compression operations
    # ------------------------------------------------------------------

    @abstractmethod
    async def check_and_compress(
        self,
        context: "Context",
        compressor_context: "CompressorContext",
        force: bool = False,
    ) -> CompressionStats:
        """Check token threshold and trigger compression.

        When ``force=True`` (e.g. ``/compact`` command), the threshold check
        is skipped and compression runs immediately.

        Args:
            context: The ``Context`` instance to check/compress.
            compressor_context: Narrow interface providing agent_id,
                session_id, communicator, session_manager, compact_config,
                provider, model, workspace, last_context_length.
            force: If True, skip threshold check (forced compression).

        Returns:
            ``CompressionStats`` with truncation statistics.
        """
        ...

    @abstractmethod
    def reset_session_memory(self) -> None:
        """Clear the current agent's session memory files.

        Used by ``clear_*`` commands.
        """
        ...
