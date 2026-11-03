"""
Session Memory 管理器 — 薄兼容层

Phase 3 起，所有压缩/提取/pivot/冻结逻辑已迁入
``SessionMemoryCompressor`` (``broca.context_compressor``).

本模块仅保留路径属性与 ``reset()`` 作为向后兼容入口。
新代码应直接使用 ``ContextCompressor`` (via ``ComponentRegistry``).
"""

import warnings
from typing import TYPE_CHECKING, Optional

from broca.logging_config import get_logger

if TYPE_CHECKING:
    from broca.components.context_compressor import ContextCompressor

logger = get_logger(__name__)


class SessionMemoryManager:
    """兼容层：仅保留路径属性与 reset()，逻辑委托给 ContextCompressor.

    .. deprecated::
        Use ``ContextCompressor`` (``broca.components.ContextCompressor``)
        instead. This class no longer holds extract/pivot/freeze logic.
    """

    def __init__(
        self,
        compressor: "ContextCompressor",
        workspace: Optional[str] = None,
    ):
        """
        Args:
            compressor: The ``ContextCompressor`` instance to delegate to.
            workspace: Retained for backward compat (unused).
        """
        warnings.warn(
            "SessionMemoryManager is deprecated. "
            "Use ContextCompressor (broca.components.ContextCompressor) instead.",
            DeprecationWarning,
            stacklevel=2,
        )
        self._compressor = compressor
        self._workspace = workspace or ""

    # ------------------------------------------------------------------
    # Path properties (delegate to compressor)
    # ------------------------------------------------------------------

    @property
    def snapshot_memory_path(self) -> str:
        return self._compressor.snapshot_memory_path

    @property
    def memory_path(self) -> str:
        return self._compressor.memory_path

    # ------------------------------------------------------------------
    # Operations (delegate to compressor)
    # ------------------------------------------------------------------

    def reset(self) -> None:
        """Delegate to ``ContextCompressor.reset_session_memory()``."""
        self._compressor.reset_session_memory()

    def is_session_memory_empty(self) -> bool:
        """Delegate to compressor (if available)."""
        if hasattr(self._compressor, "is_session_memory_empty"):
            return self._compressor.is_session_memory_empty()
        return True
