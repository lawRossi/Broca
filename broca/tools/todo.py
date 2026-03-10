import json
import os
from pathlib import Path

from broca.tools.tool import Tool, ToolCallContext, ToolResult, ToolStatus


class TodoManagement(Tool):
    def __init__(self, data_file="todos.json"):
        super().__init__()
        self.data_file = data_file

    @property
    def name(self):
        return "todo_management"

    @property
    def description(self):
        return "Use this tool to manage todo list. Always use this tool to track progress when executing complex tasks that require multiple steps."

    @property
    def parameters(self):
        return {
            "type": "object",
            "properties": {
                "action": {
                    "type": "string",
                    "description": "The action to perform: create, read, update",
                },
                "todo_id": {
                    "type": "string",
                    "description": "The ID of the todo group (required for update and delete actions)",
                },
                "name": {
                    "type": "string",
                    "description": "Todo group name (required for create actions)",
                },
                "todos": {
                    "type": "array",
                    "items": {
                        "type": "object",
                        "properties": {
                            "name": {"type": "string"},
                            "status": {
                                "type": "string",
                                "enum": ["pending", "completed"],
                            },
                        },
                        "required": ["name", "status"],
                    },
                    "description": "List of todos with name and status (required for create and update actions)",
                },
            },
            "required": ["action"],
        }

    def _load_todos(self, data_file) -> list:
        if os.path.exists(data_file):
            with open(self.data_file, "r") as f:
                todos_data = json.load(f)
        else:
            todos_data = []
        return todos_data

    def _save_todos(self, data_file, todos_data):
        with open(data_file, "w") as f:
            json.dump(todos_data, f, indent=2, ensure_ascii=False)

    def _get_next_id(self, todos_data):
        if not todos_data:
            return "1"
        return str(max(int(todos["id"]) for todos in todos_data) + 1)

    def _find_todos(self, todo_id, todos_data):
        for todo in todos_data:
            if todo["id"] == todo_id:
                return todo
        return None

    async def _execute(self, arguments: dict, context: ToolCallContext) -> ToolResult:
        action = arguments.get("action")
        arguments["workspace"] = context.workspace
        if action == "create":
            return self._create_todos(arguments)
        elif action == "read":
            return self._read_todos(arguments)
        elif action == "update":
            return self._update_todos(arguments)
        else:
            return ToolResult(
                status=ToolStatus.ERROR, content=f"Unknown action: {action}"
            )

    def _validate_todos(self, todos):
        if not isinstance(todos, list):
            return "todos must be an array"
        for item in todos:
            if not isinstance(item, dict):
                return "each todo must be an object"
            if "name" not in item:
                return "each todo must have a name"
            if "status" not in item:
                return "each todo must have a status"
            if item["status"] not in ["pending", "completed"]:
                return "Invalid status. Valid values: pending, completed"
        return None

    def _create_todos(self, arguments) -> ToolResult:
        name = arguments.get("name")
        todos = arguments.get("todos")

        if not name:
            return ToolResult(
                status=ToolStatus.ERROR, content="Missing required field: name"
            )
        if not todos:
            return ToolResult(
                status=ToolStatus.ERROR, content="Missing required field: todos"
            )

        error = self._validate_todos(todos)
        if error:
            return ToolResult(status=ToolStatus.ERROR, content=error)

        data_file = Path(arguments["workspace"]) / self.data_file
        todos_data = self._load_todos(data_file)

        todos = {
            "id": self._get_next_id(todos_data),
            "name": name,
            "todos": todos,
        }
        todos_data.append(todos)
        self._save_todos(data_file, todos_data)

        return ToolResult(
            status=ToolStatus.SUCCESS,
            content=f"Todo group created successfully with ID: {todos['id']}",
        )

    def _read_todos(self, arguments) -> ToolResult:
        todo_id = arguments.get("todo_id")
        if not todo_id:
            return ToolResult(
                status=ToolStatus.ERROR, content="Missing required field: todo_id"
            )

        data_file = Path(arguments["workspace"]) / self.data_file
        todos_data = self._load_todos(data_file)
        todos = self._find_todos(todo_id, todos_data)
        if not todos:
            return ToolResult(
                status=ToolStatus.ERROR,
                content=f"Todo group with ID {todo_id} not found",
            )

        return ToolResult(
            status=ToolStatus.SUCCESS,
            content=json.dumps(todos, indent=2, default=str, ensure_ascii=False),
        )

    def _update_todos(self, arguments):
        todo_id = arguments.get("todo_id")
        if not todo_id:
            return ToolResult(
                status=ToolStatus.ERROR, content="Missing required field: todo_id"
            )

        data_file = Path(arguments["workspace"]) / self.data_file
        todos_data = self._load_todos(data_file)
        todos = self._find_todos(todo_id, todos_data)
        if not todos:
            return ToolResult(
                status=ToolStatus.ERROR,
                content=f"Todo group with ID {todo_id} not found",
            )

        if "name" in arguments:
            todos["name"] = arguments["name"]
        if "todos" in arguments:
            error = self._validate_todos(arguments["todos"])
            if error:
                return ToolResult(status=ToolStatus.ERROR, content=error)
            todos["todos"] = arguments["todos"]

        self._save_todos(data_file, todos_data)
        return ToolResult(
            status=ToolStatus.SUCCESS,
            content=f"Todo group {todo_id} updated successfully",
        )
