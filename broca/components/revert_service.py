"""RevertService ABC — interface for undo/redo operations."""

from abc import ABC, abstractmethod
from typing import Any, Dict, Optional


class RevertServiceABC(ABC):
    """Abstract base class for session undo/redo operations.

    Decouples the Session domain from the Snapshot domain — callers
    depend on this interface, not on the concrete SessionRevertService.
    """

    @abstractmethod
    async def undo(
        self,
        session_id: str,
        agent_id: str,
        target_message_id: Optional[str] = None,
        level: str = "step",
    ) -> Dict[str, Any]:
        """执行撤销操作。

        Returns:
            {"success": bool, "reverted_messages": int, ...}
        """
        ...

    @abstractmethod
    async def redo(
        self,
        session_id: str,
        agent_id: str,
    ) -> Dict[str, Any]:
        """执行重做操作。

        Returns:
            {"success": bool, "restored_messages": int, ...}
        """
        ...

    @abstractmethod
    def can_undo(self, session_id: str) -> bool:
        """是否可以撤销（undo_stack 非空）。"""
        ...

    @abstractmethod
    def can_redo(self, session_id: str) -> bool:
        """是否可以重做（有可恢复的 undo 记录）。"""
        ...
