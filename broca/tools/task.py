import json

from Broca.task import TaskContext, TaskPriority, TaskStatus
from Broca.task_manager import TaskManager

from broca.tools.tool import Tool, ToolCallContext


class TaskManagementTool(Tool):
    def __init__(self):
        super().__init__()

    @property
    def name(self):
        return "task_management"

    @property
    def description(self):
        return "Use this tool to manage tasks with CRUD operations."

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
                "acceptance_criteria": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "List of acceptance criteria (optional for create and update actions)",
                },
                "author": {
                    "type": "string",
                    "description": "Comment author (required for add_comment action)",
                },
                "content": {
                    "type": "string",
                    "description": "Comment content (required for add_comment action)",
                },
                "query": {
                    "type": "string",
                    "description": "Search query (required for search action)",
                },
            },
            "required": ["action"],
        }
        self.task_manager = TaskManager()

    def _execute(self, arguments: dict, context: ToolCallContext):
        action = arguments.get("action")

        if action == "create":
            return self._create_task(arguments)
        elif action == "get":
            return self._get_task(arguments)
        elif action == "get_all":
            return self._get_all_tasks()
        elif action == "get_by_status":
            return self._get_tasks_by_status(arguments)
        elif action == "get_by_assignee":
            return self._get_tasks_by_assignee(arguments)
        elif action == "update":
            return self._update_task(arguments)
        elif action == "delete":
            return self._delete_task(arguments)
        elif action == "add_comment":
            return self._add_comment(arguments)
        elif action == "get_children":
            return self._get_child_tasks(arguments)
        elif action == "search":
            return self._search_tasks(arguments)
        else:
            return f"Unknown action: {action}"

    def _create_task(self, arguments):
        required_fields = ["name", "description"]
        for field in required_fields:
            if field not in arguments:
                return f"Missing required field: {field}"

        try:
            # Convert string priority to enum if provided
            priority = TaskPriority.MEDIUM
            if "priority" in arguments:
                priority = TaskPriority(arguments["priority"].lower())

            # Convert context dict to TaskContext if provided
            task_context = TaskContext(
                arguments.get("files"), arguments.get("links"), arguments.get("notes")
            )

            task = self.task_manager.create_task(
                name=arguments["name"],
                description=arguments["description"],
                priority=priority,
                parent_id=arguments.get("parent_id"),
                assignee=arguments.get("assignee"),
                dependencies=arguments.get("dependencies"),
                details=arguments.get("details"),
                context=task_context,
                acceptance_criteria=arguments.get("acceptance_criteria"),
            )

            return f"Task created successfully with ID: {task.metadata.id}"
        except Exception as e:
            return f"Error creating task: {str(e)}"

    def _get_task(self, arguments):
        task_id = arguments.get("task_id")
        if not task_id:
            return "Missing required field: task_id"

        task = self.task_manager.get_task(task_id)
        if task:
            return json.dumps(task.model_dump(), indent=2, default=str)
        else:
            return f"Task with ID {task_id} not found"

    def _get_all_tasks(self):
        tasks = self.task_manager.get_all_tasks()
        return json.dumps([task.model_dump() for task in tasks], indent=2, default=str)

    def _get_tasks_by_status(self, arguments):
        status = arguments.get("status")
        if not status:
            return "Missing required field: status"

        try:
            status_enum = TaskStatus(status.lower())
            tasks = self.task_manager.get_tasks_by_status(status_enum)
            return json.dumps(
                [task.model_dump() for task in tasks], indent=2, default=str
            )
        except ValueError:
            return f"Invalid status: {status}. Valid values: pending, in_progress, blocked, completed"

    def _get_tasks_by_assignee(self, arguments):
        assignee = arguments.get("assignee")
        if not assignee:
            return "Missing required field: assignee"

        tasks = self.task_manager.get_tasks_by_assignee(assignee)
        return json.dumps([task.model_dump() for task in tasks], indent=2, default=str)

    def _update_task(self, arguments):
        task_id = arguments.get("task_id")
        if not task_id:
            return "Missing required field: task_id"

        try:
            # Convert string status to enum if provided
            status = None
            if "status" in arguments:
                status = TaskStatus(arguments["status"].lower())

            # Convert string priority to enum if provided
            priority = None
            if "priority" in arguments:
                priority = TaskPriority(arguments["priority"].lower())

            task_context = TaskContext(
                arguments.get("files"), arguments.get("links"), arguments.get("notes")
            )

            task = self.task_manager.update_task(
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
                return f"Task {task_id} updated successfully"
            else:
                return f"Task with ID {task_id} not found"
        except ValueError as e:
            return f"Invalid value: {str(e)}"
        except Exception as e:
            return f"Error updating task: {str(e)}"

    def _delete_task(self, arguments):
        task_id = arguments.get("task_id")
        if not task_id:
            return "Missing required field: task_id"

        success = self.task_manager.delete_task(task_id)
        if success:
            return f"Task {task_id} deleted successfully"
        else:
            return f"Task with ID {task_id} not found"

    def _add_comment(self, arguments):
        task_id = arguments.get("task_id")
        author = arguments.get("author")
        content = arguments.get("content")

        if not task_id:
            return "Missing required field: task_id"
        if not author:
            return "Missing required field: author"
        if not content:
            return "Missing required field: content"

        task = self.task_manager.add_comment(
            task_id=task_id, author=author, content=content
        )

        if task:
            return f"Comment added to task {task_id} successfully"
        else:
            return f"Task with ID {task_id} not found"

    def _get_child_tasks(self, arguments):
        parent_id = arguments.get("task_id")
        if not parent_id:
            return "Missing required field: task_id"

        tasks = self.task_manager.get_child_tasks(parent_id)
        return json.dumps([task.model_dump() for task in tasks], indent=2, default=str)

    def _search_tasks(self, arguments):
        query = arguments.get("query")
        if not query:
            return "Missing required field: query"

        tasks = self.task_manager.search_tasks(query)
        return json.dumps([task.model_dump() for task in tasks], indent=2, default=str)
