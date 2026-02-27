import json
import os

from broca.tools.tool import Tool, ToolCallContext


class TodoManager(Tool):
    def __init__(self, data_file="todos.json"):
        super().__init__()
        self.data_file = data_file
        self._load_todos()

    @property
    def name(self):
        return "todo_manager"

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

    def _load_todos(self):
        if os.path.exists(self.data_file):
            with open(self.data_file, "r") as f:
                self.todos = json.load(f)
        else:
            self.todos = []

    def _save_todos(self):
        with open(self.data_file, "w") as f:
            json.dump(self.todos, f, indent=2, ensure_ascii=False)

    def _get_next_id(self):
        if not self.todos:
            return "1"
        return str(max(int(todo["id"]) for todo in self.todos) + 1)

    def _find_todos(self, todo_id):
        for todo in self.todos:
            if todo["id"] == todo_id:
                return todo
        return None

    async def _execute(self, arguments: dict, context: ToolCallContext):
        action = arguments.get("action")

        if action == "create":
            return self._create_todos(arguments)
        elif action == "read":
            return self._read_todos(arguments)
        elif action == "update":
            return self._update_todos(arguments)
        else:
            return f"Unknown action: {action}"

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

    def _create_todos(self, arguments):
        name = arguments.get("name")
        todos = arguments.get("todos")

        if not name:
            return "Missing required field: name"
        if not todos:
            return "Missing required field: todos"

        error = self._validate_todos(todos)
        if error:
            return error

        todo = {
            "id": self._get_next_id(),
            "name": name,
            "todos": todos,
        }
        self.todos.append(todo)
        self._save_todos()
        return f"Todo group created successfully with ID: {todo['id']}"

    def _read_todos(self, arguments):
        todo_id = arguments.get("todo_id")
        if not todo_id:
            return "Missing required field: todo_id"

        todos = self._find_todos(todo_id)
        if not todos:
            return f"Todo group with ID {todo_id} not found"

        return json.dumps(todos, indent=2, default=str, ensure_ascii=False)

    def _update_todos(self, arguments):
        todo_id = arguments.get("todo_id")
        if not todo_id:
            return "Missing required field: todo_id"

        todo = self._find_todos(todo_id)
        if not todo:
            return f"Todo group with ID {todo_id} not found"

        if "name" in arguments:
            todo["name"] = arguments["name"]
        if "todos" in arguments:
            error = self._validate_todos(arguments["todos"])
            if error:
                return error
            todo["todos"] = arguments["todos"]

        self._save_todos()
        return f"Todo group {todo_id} updated successfully"
