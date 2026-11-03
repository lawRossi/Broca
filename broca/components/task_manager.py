"""TaskManager ABC — interface for task management.

Manages CRUD operations on tasks, comments, and hierarchical
task structures.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any, Dict, List, Optional


class TaskManager(ABC):
    """Abstract base class for task management.

    Implementations handle task CRUD, comments, hierarchy, and search.
    Methods match exactly what the ``task_management`` tool calls.
    """

    @abstractmethod
    async def create_task(
        self,
        name: str,
        description: str,
        **kwargs: Any,
    ) -> Any:
        """Create a new task. Returns the created task."""
        ...

    @abstractmethod
    async def get_task(self, task_id: str) -> Optional[Any]:
        """Get a task by ID. Returns None if not found."""
        ...

    @abstractmethod
    async def update_task(
        self, task_id: str, **kwargs: Any
    ) -> Optional[Any]:
        """Update a task's fields. Returns the updated task or None."""
        ...

    @abstractmethod
    async def delete_task(self, task_id: str) -> bool:
        """Delete a task. Returns True if deleted."""
        ...

    @abstractmethod
    async def add_comment(
        self, task_id: str, content: str, **kwargs: Any
    ) -> Optional[Any]:
        """Add a comment to a task. Returns the comment or None."""
        ...

    @abstractmethod
    async def get_child_tasks(self, parent_id: str) -> List[Any]:
        """Get child tasks of a parent task."""
        ...

    @abstractmethod
    async def search_tasks(
        self, query: str, **kwargs: Any
    ) -> List[Any]:
        """Search tasks by query string."""
        ...
