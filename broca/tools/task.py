import json

from broca.session.models import TaskPriority, TaskStatus
from broca.task_manager import TaskContext, TaskManager
from broca.tools.tool import Tool, ToolCallContext, ToolResult, ToolStatus


class TaskManagement(Tool):
    def __init__(self):
        super().__init__()
        self.task_manager = TaskManager()

    @property
    def name(self):
        return "task_management"

    @property
    def description(self):
        return "Use this tool to manage tasks with CRUD operations. "

    @property
    def parameters(self):
        return {
            "type": "object",
            "properties": {
                "action": {
                    "type": "string",
                    "description": "The action to perform: create, get, get_all, get_by_status, get_by_assignee, update, delete, add_comment, get_children, search",
                },
                "task_id": {
                    "type": "string",
                    "description": "The ID of the task (required for get, update, delete, add_comment, get_children actions)",
                },
                "name": {
                    "type": "string",
                    "description": "Task name (required for create action)",
                },
                "description": {
                    "type": "string",
                    "description": "Task description (required for create action)",
                },
                "priority": {
                    "type": "string",
                    "description": "Task priority: low, medium, high (optional for create and update actions)",
                },
                "status": {
                    "type": "string",
                    "description": "Task status: pending, in_progress, blocked, completed (optional for update action)",
                },
                "assignee": {
                    "type": "string",
                    "description": "Task assignee (optional for create and update actions)",
                },
                "parent_id": {
                    "type": "string",
                    "description": "Parent task ID (optional for create action)",
                },
                "dependencies": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "List of dependency task IDs (optional for create and update actions)",
                },
                "details": {
                    "type": "string",
                    "description": "Detailed task description (optional for create and update actions)",
                },
                "files": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "List of task related files (optional for create and update actions)",
                },
                "links": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "List of task related links (optional for create and update actions)",
                },
                "notes": {
                    "type": "string",
                    "description": "Task notes (optional for create and update actions)",
                },
                "acceptance_criteria": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "List of acceptance criteria (optional for create and update actions)",
                },
                "content": {
                    "type": "string",
                    "description": "Comment content (required for add_comment action)",
                },
                "report": {
                    "type": "string",
                    "description": "Report content (optional for update action)",
                },
                "query": {
                    "type": "string",
                    "description": "Search query (required for search action)",
                },
            },
            "required": ["action"],
        }

    async def _execute(self, arguments: dict, context: ToolCallContext) -> ToolResult:
        action = arguments.get("action")
        arguments["session_id"] = context.session_id
        arguments["author"] = context.agent.name
        try:
            task_manager = self.task_manager
            if action == "create":
                return await self._create_task(arguments, task_manager)
            elif action == "get":
                return await self._get_task(arguments, task_manager)
            elif action == "get_all":
                return await self._get_all_tasks(task_manager, arguments)
            elif action == "get_by_status":
                return await self._get_tasks_by_status(arguments, task_manager)
            elif action == "get_by_assignee":
                return await self._get_tasks_by_assignee(arguments, task_manager)
            elif action == "update":
                return await self._update_task(arguments, task_manager)
            elif action == "delete":
                return await self._delete_task(arguments, task_manager)
            elif action == "add_comment":
                return await self._add_comment(arguments, task_manager)
            elif action == "get_children":
                return await self._get_child_tasks(arguments, task_manager)
            elif action == "search":
                return await self._search_tasks(arguments, task_manager)
            elif action == "write_report":
                return await self._write_report(arguments, task_manager)
            else:
                return ToolResult(
                    status=ToolStatus.ERROR, content=f"Unknown action: {action}"
                )
        except Exception as e:
            return ToolResult(
                status=ToolStatus.ERROR,
                content=f"Error executing action '{action}': {e}",
            )

    async def _create_task(self, arguments, task_manager) -> ToolResult:
        required_fields = ["name", "description"]
        for field in required_fields:
            if field not in arguments:
                return ToolResult(
                    status=ToolStatus.ERROR, content=f"Missing required field: {field}"
                )
        try:
            priority = TaskPriority.MEDIUM
            if "priority" in arguments:
                priority = TaskPriority(arguments["priority"].lower())

            task_context = TaskContext(
                files=arguments.get("files"),
                links=arguments.get("links"),
                notes=arguments.get("notes"),
            )

            task = await task_manager.create_task(
                name=arguments["name"],
                description=arguments["description"],
                priority=priority,
                parent_id=arguments.get("parent_id"),
                assignee=arguments.get("assignee"),
                dependencies=arguments.get("dependencies"),
                details=arguments.get("details"),
                context=task_context,
                acceptance_criteria=arguments.get("acceptance_criteria"),
                session_id=arguments.get("session_id"),
            )

            return ToolResult(
                status=ToolStatus.SUCCESS,
                content=f"Task created successfully with ID: {task.task_id}",
            )
        except ValueError as e:
            return ToolResult(status=ToolStatus.ERROR, content=f"Invalid value: {e}")
        except Exception as e:
            return ToolResult(
                status=ToolStatus.ERROR, content=f"Error creating task: {str(e)}"
            )

    async def _get_task(self, arguments, task_manager) -> ToolResult:
        task_id = arguments.get("task_id")
        if not task_id:
            return ToolResult(
                status=ToolStatus.ERROR, content="Missing required field: task_id"
            )

        task = await task_manager.get_task(task_id)
        if task:
            return ToolResult(
                status=ToolStatus.SUCCESS,
                content=json.dumps(task.model_dump(), indent=2, default=str),
            )
        else:
            return ToolResult(
                status=ToolStatus.ERROR, content=f"Task with ID {task_id} not found"
            )

    async def _get_all_tasks(self, task_manager, arguments) -> ToolResult:
        session_id = arguments.get("session_id")
        tasks = await task_manager.get_all_tasks(session_id=session_id)
        return ToolResult(
            status=ToolStatus.SUCCESS,
            content=json.dumps(
                [task.model_dump() for task in tasks], indent=2, default=str
            ),
        )

    async def _get_tasks_by_status(self, arguments, task_manager) -> ToolResult:
        session_id = arguments.get("session_id")
        status = arguments.get("status")
        if not status:
            return ToolResult(
                status=ToolStatus.ERROR, content="Missing required field: status"
            )

        try:
            status_enum = TaskStatus(status.lower())
            tasks = await task_manager.get_tasks_by_status(
                session_id=session_id, status=status_enum
            )
            return ToolResult(
                status=ToolStatus.SUCCESS,
                content=json.dumps(
                    [task.model_dump() for task in tasks], indent=2, default=str
                ),
            )
        except ValueError:
            return ToolResult(
                status=ToolStatus.ERROR,
                content=f"Invalid status: {status}. Valid values: pending, in_progress, blocked, completed",
            )

    async def _get_tasks_by_assignee(self, arguments, task_manager) -> ToolResult:
        session_id = arguments.get("session_id")
        assignee = arguments.get("assignee")
        if not assignee:
            return ToolResult(
                status=ToolStatus.ERROR, content="Missing required field: assignee"
            )

        tasks = await task_manager.get_tasks_by_assignee(session_id, assignee)
        return ToolResult(
            status=ToolStatus.SUCCESS,
            content=json.dumps(
                [task.model_dump() for task in tasks], indent=2, default=str
            ),
        )

    async def _update_task(self, arguments, task_manager) -> ToolResult:
        task_id = arguments.get("task_id")
        if not task_id:
            return ToolResult(
                status=ToolStatus.ERROR, content="Missing required field: task_id"
            )

        try:
            status = None
            if "status" in arguments:
                status = TaskStatus(arguments["status"].lower())

            priority = None
            if "priority" in arguments:
                priority = TaskPriority(arguments["priority"].lower())

            task_context = TaskContext(
                files=arguments.get("files"),
                links=arguments.get("links"),
                notes=arguments.get("notes"),
            )

            task = await task_manager.update_task(
                task_id=task_id,
                name=arguments.get("name"),
                description=arguments.get("description"),
                status=status,
                priority=priority,
                assignee=arguments.get("assignee"),
                dependencies=arguments.get("dependencies"),
                details=arguments.get("details"),
                context=task_context,
                acceptance_criteria=arguments.get("acceptance_criteria"),
            )

            if task:
                return ToolResult(
                    status=ToolStatus.SUCCESS,
                    content=f"Task {task_id} updated successfully",
                )
            else:
                return ToolResult(
                    status=ToolStatus.ERROR, content=f"Task with ID {task_id} not found"
                )
        except ValueError as e:
            return ToolResult(
                status=ToolStatus.ERROR, content=f"Invalid value: {str(e)}"
            )
        except Exception as e:
            return ToolResult(
                status=ToolStatus.ERROR, content=f"Error updating task: {str(e)}"
            )

    async def _delete_task(self, arguments, task_manager) -> ToolResult:
        task_id = arguments.get("task_id")
        if not task_id:
            return ToolResult(
                status=ToolStatus.ERROR, content="Missing required field: task_id"
            )

        success = await task_manager.delete_task(task_id)
        if success:
            return ToolResult(
                status=ToolStatus.SUCCESS,
                content=f"Task {task_id} deleted successfully",
            )
        else:
            return ToolResult(
                status=ToolStatus.ERROR, content=f"Task with ID {task_id} not found"
            )

    async def _add_comment(self, arguments, task_manager) -> ToolResult:
        task_id = arguments.get("task_id")
        author = arguments.get("author")
        content = arguments.get("content")

        if not task_id:
            return ToolResult(
                status=ToolStatus.ERROR, content="Missing required field: task_id"
            )
        if not content:
            return ToolResult(
                status=ToolStatus.ERROR, content="Missing required field: content"
            )

        task = await task_manager.add_comment(
            task_id=task_id, author=author, content=content
        )

        if task:
            return ToolResult(
                status=ToolStatus.SUCCESS,
                content=f"Comment added to task {task_id} successfully",
            )
        else:
            return ToolResult(
                status=ToolStatus.ERROR, content=f"Task with ID {task_id} not found"
            )

    async def _get_child_tasks(self, arguments, task_manager) -> ToolResult:
        parent_id = arguments.get("task_id")
        if not parent_id:
            return ToolResult(
                status=ToolStatus.ERROR, content="Missing required field: task_id"
            )

        tasks = await task_manager.get_child_tasks(parent_id)
        return ToolResult(
            status=ToolStatus.SUCCESS,
            content=json.dumps(
                [task.model_dump() for task in tasks], indent=2, default=str
            ),
        )

    async def _search_tasks(self, arguments, task_manager) -> ToolResult:
        session_id = arguments.get("session_id")
        query = arguments.get("query")
        if not query:
            return ToolResult(
                status=ToolStatus.ERROR, content="Missing required field: query"
            )

        tasks = await task_manager.search_tasks(query=query, session_id=session_id)
        return ToolResult(
            status=ToolStatus.SUCCESS,
            content=json.dumps(
                [task.model_dump() for task in tasks], indent=2, default=str
            ),
        )
