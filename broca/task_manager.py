import json
import os
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional
from uuid import uuid4

from .task import Task, TaskComment, TaskContext, TaskMetadata, TaskPriority, TaskStatus


class TaskManager:
    """Manages tasks with CRUD operations using JSON file storage."""

    def __init__(self, storage_file: str | Path):
        """
        Initialize the TaskManager.

        Args:
            storage_file: Path to the JSON file for task storage
        """
        self.storage_file = storage_file
        self._ensure_storage_file()

    def _ensure_storage_file(self) -> None:
        """Ensure the storage file exists and is properly initialized."""
        if not os.path.exists(self.storage_file):
            with open(self.storage_file, "w") as f:
                json.dump({"tasks": []}, f, indent=2, default=str)

    def _load_tasks(self) -> List[Dict[str, Any]]:
        """Load all tasks from the JSON file."""
        try:
            with open(self.storage_file, "r") as f:
                data = json.load(f)
                return data.get("tasks", [])
        except (json.JSONDecodeError, FileNotFoundError):
            return []

    def _save_tasks(self, tasks: List[Dict[str, Any]]) -> None:
        """Save tasks to the JSON file."""
        with open(self.storage_file, "w") as f:
            json.dump({"tasks": tasks}, f, indent=2, default=str)

    def _task_to_dict(self, task: Task) -> Dict[str, Any]:
        """Convert a Task object to a dictionary for JSON serialization."""
        return task.model_dump()

    def _dict_to_task(self, task_dict: Dict[str, Any]) -> Task:
        """Convert a dictionary to a Task object."""
        return Task.model_validate(task_dict)

    def create_task(
        self,
        name: str,
        description: str,
        priority: TaskPriority = TaskPriority.MEDIUM,
        parent_id: Optional[str] = None,
        assignee: Optional[str] = None,
        dependencies: Optional[List[str]] = None,
        details: Optional[str] = None,
        context: Optional[TaskContext] = None,
        acceptance_criteria: Optional[List[str]] = None,
    ) -> Task:
        """
        Create a new task.

        Args:
            name: Task name
            description: Task description
            priority: Task priority
            parent_id: Optional parent task ID
            assignee: Optional assignee
            dependencies: Optional list of dependency task IDs
            details: Optional detailed description
            context: Optional task context
            acceptance_criteria: Optional list of acceptance criteria

        Returns:
            Created Task object
        """
        task_id = str(uuid4())
        now = datetime.now()

        metadata = TaskMetadata(
            id=task_id,
            parent_id=parent_id,
            created=now,
            updated=now,
            status=TaskStatus.PENDING,
            priority=priority,
            dependencies=dependencies,
            assignee=assignee,
        )

        task = Task(
            metadata=metadata,
            name=name,
            description=description,
            details=details,
            context=context,
            acceptance_criteria=acceptance_criteria,
        )

        tasks = self._load_tasks()
        tasks.append(self._task_to_dict(task))
        self._save_tasks(tasks)

        return task

    def get_task(self, task_id: str) -> Optional[Task]:
        """
        Get a task by ID.

        Args:
            task_id: The ID of the task to retrieve

        Returns:
            Task object if found, None otherwise
        """
        tasks = self._load_tasks()
        for task_dict in tasks:
            if task_dict.get("metadata", {}).get("id") == task_id:
                return self._dict_to_task(task_dict)
        return None

    def get_all_tasks(self) -> List[Task]:
        """
        Get all tasks.

        Returns:
            List of all Task objects
        """
        tasks = self._load_tasks()
        return [self._dict_to_task(task_dict) for task_dict in tasks]

    def get_tasks_by_status(self, status: TaskStatus) -> List[Task]:
        """
        Get tasks by status.

        Args:
            status: The status to filter by

        Returns:
            List of Task objects with the specified status
        """
        tasks = self._load_tasks()
        filtered_tasks = []
        for task_dict in tasks:
            if task_dict.get("metadata", {}).get("status") == status:
                filtered_tasks.append(self._dict_to_task(task_dict))
        return filtered_tasks

    def get_tasks_by_assignee(self, assignee: str) -> List[Task]:
        """
        Get tasks by assignee.

        Args:
            assignee: The assignee to filter by

        Returns:
            List of Task objects assigned to the specified assignee
        """
        tasks = self._load_tasks()
        filtered_tasks = []
        for task_dict in tasks:
            if task_dict.get("metadata", {}).get("assignee") == assignee:
                filtered_tasks.append(self._dict_to_task(task_dict))
        return filtered_tasks

    def update_task(
        self,
        task_id: str,
        name: Optional[str] = None,
        description: Optional[str] = None,
        status: Optional[TaskStatus] = None,
        priority: Optional[TaskPriority] = None,
        assignee: Optional[str] = None,
        dependencies: Optional[List[str]] = None,
        details: Optional[str] = None,
        context: Optional[TaskContext] = None,
        acceptance_criteria: Optional[List[str]] = None,
    ) -> Optional[Task]:
        """
        Update an existing task.

        Args:
            task_id: The ID of the task to update
            name: Optional new name
            description: Optional new description
            status: Optional new status
            priority: Optional new priority
            assignee: Optional new assignee
            dependencies: Optional new dependencies
            details: Optional new details
            context: Optional new context
            acceptance_criteria: Optional new acceptance criteria

        Returns:
            Updated Task object if found, None otherwise
        """
        tasks = self._load_tasks()
        for i, task_dict in enumerate(tasks):
            if task_dict.get("metadata", {}).get("id") == task_id:
                task = self._dict_to_task(task_dict)

                # Update fields if provided
                if name is not None:
                    task.name = name
                if description is not None:
                    task.description = description
                if status is not None:
                    task.metadata.status = status
                if priority is not None:
                    task.metadata.priority = priority
                if assignee is not None:
                    task.metadata.assignee = assignee
                if dependencies is not None:
                    task.metadata.dependencies = dependencies
                if details is not None:
                    task.details = details
                if context is not None:
                    task.context = context
                if acceptance_criteria is not None:
                    task.acceptance_criteria = acceptance_criteria

                # Update the timestamp
                task.metadata.updated = datetime.now()

                # Save the updated task
                tasks[i] = self._task_to_dict(task)
                self._save_tasks(tasks)

                return task

        return None

    def delete_task(self, task_id: str) -> bool:
        """
        Delete a task by ID.

        Args:
            task_id: The ID of the task to delete

        Returns:
            True if task was deleted, False if task was not found
        """
        tasks = self._load_tasks()
        original_length = len(tasks)

        # Filter out the task to delete
        tasks = [
            task_dict
            for task_dict in tasks
            if task_dict.get("metadata", {}).get("id") != task_id
        ]

        if len(tasks) < original_length:
            self._save_tasks(tasks)
            return True

        return False

    def add_comment(self, task_id: str, author: str, content: str) -> Optional[Task]:
        """
        Add a comment to a task.

        Args:
            task_id: The ID of the task
            author: The comment author
            content: The comment content

        Returns:
            Updated Task object if found, None otherwise
        """
        tasks = self._load_tasks()
        for i, task_dict in enumerate(tasks):
            if task_dict.get("metadata", {}).get("id") == task_id:
                task = self._dict_to_task(task_dict)

                if task.discussion is None:
                    task.discussion = []

                comment = TaskComment(
                    author=author, content=content, created=datetime.now()
                )

                task.discussion.append(comment)
                task.metadata.updated = datetime.now()

                tasks[i] = self._task_to_dict(task)
                self._save_tasks(tasks)

                return task

        return None

    def get_child_tasks(self, parent_id: str) -> List[Task]:
        """
        Get all child tasks of a parent task.

        Args:
            parent_id: The ID of the parent task

        Returns:
            List of Task objects that are children of the specified parent
        """
        tasks = self._load_tasks()
        child_tasks = []
        for task_dict in tasks:
            if task_dict.get("metadata", {}).get("parent_id") == parent_id:
                child_tasks.append(self._dict_to_task(task_dict))
        return child_tasks

    def search_tasks(self, query: str) -> List[Task]:
        """
        Search tasks by name or description.

        Args:
            query: The search query

        Returns:
            List of Task objects matching the search query
        """
        tasks = self._load_tasks()
        matching_tasks = []
        query_lower = query.lower()

        for task_dict in tasks:
            task = self._dict_to_task(task_dict)
            if (
                query_lower in task.name.lower()
                or query_lower in task.description.lower()
                or (task.details and query_lower in task.details.lower())
            ):
                matching_tasks.append(task)

        return matching_tasks
