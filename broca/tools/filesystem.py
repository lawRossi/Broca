from pathlib import Path

from broca.tools.tool import Tool, ToolCallContext


class ReadFile(Tool):
    """Tool to read file contents."""

    @property
    def name(self) -> str:
        return "read_file"

    @property
    def description(self) -> str:
        return "Read the contents of a file at the given path."

    @property
    def parameters(self) -> dict:
        return {
            "type": "object",
            "properties": {
                "path": {
                    "type": "string",
                    "description": "The file path to read",
                },
                "encoding": {
                    "type": "string",
                    "description": "The encoding to use",
                    "default": "utf-8",
                },
            },
            "required": ["path"],
        }

    async def _execute(self, parameters: dict, context: ToolCallContext) -> str:
        try:
            path = parameters["path"]
            file_path = Path(path).expanduser()
            encoding = parameters.get("encoding", "utf-8")
            if not file_path.exists():
                return f"Error: File not found: {path}"
            if not file_path.is_file():
                return f"Error: Not a file: {path}"

            content = file_path.read_text(encoding=encoding)
            return content
        except PermissionError:
            return f"Error: Permission denied: {path}"
        except Exception as e:
            return f"Error reading file: {str(e)}"


class WriteFile(Tool):
    """Tool to write content to a file."""

    @property
    def name(self) -> str:
        return "write_file"

    @property
    def description(self) -> str:
        return "Write content to a file at the given path. Creates parent directories if needed."

    @property
    def parameters(self) -> dict:
        return {
            "type": "object",
            "properties": {
                "path": {"type": "string", "description": "The file path to write to"},
                "content": {"type": "string", "description": "The content to write"},
            },
            "required": ["path", "content"],
        }

    async def _execute(self, parameters: dict, context: ToolCallContext) -> str:
        try:
            path = parameters["path"]
            file_path = Path(path).expanduser()
            if file_path.exists() and not file_path.is_file():
                return f"Error: Not a file: {path}"
            content = parameters["content"]
            file_path.parent.mkdir(parents=True, exist_ok=True)
            file_path.write_text(content, encoding="utf-8")
            return f"Successfully wrote content to {path}"
        except PermissionError:
            return f"Error: Permission denied: {path}"
        except Exception as e:
            return f"Error writing file: {str(e)}"


class EditFile(Tool):
    """Tool to edit a file by replacing text."""

    @property
    def name(self) -> str:
        return "edit_file"

    @property
    def description(self) -> str:
        return "Edit a file by replacing old_text with new_text. The old_text must exist exactly in the file."

    @property
    def parameters(self) -> dict:
        return {
            "type": "object",
            "properties": {
                "path": {"type": "string", "description": "The file path to edit"},
                "old_text": {
                    "type": "string",
                    "description": "The exact text to find and replace",
                },
                "new_text": {
                    "type": "string",
                    "description": "The text to replace with",
                },
                "encoding": {
                    "type": "string",
                    "description": "The encoding to use",
                    "default": "utf-8",
                },
                "replace_all": {
                    "type": "boolean",
                    "description": "Whether to replace all occurrences of old_text",
                    "default": False,
                },
            },
            "required": ["path", "old_text", "new_text"],
        }

    async def _execute(self, parameters: dict, context: ToolCallContext) -> str:
        try:
            path = parameters["path"]
            file_path = Path(path).expanduser()
            if not file_path.exists():
                return f"Error: File not found: {path}"
            if not file_path.is_file():
                return f"Error: Not a file: {path}"
            old_text = parameters["old_text"]
            new_text = parameters["new_text"]
            encoding = parameters.get("encoding", "utf-8")
            replace_all = parameters.get("replace_all", False)

            content = file_path.read_text(encoding=encoding)

            if old_text not in content:
                return (
                    "Error: old_text not found in file. Make sure it matches exactly."
                )

            # Count occurrences
            count = content.count(old_text)
            if count > 1 and not replace_all:
                return f"Error: old_text appears {count} times. Please provide more context to make it unique or set replace_all to true."

            new_content = content.replace(old_text, new_text)
            file_path.write_text(new_content, encoding=encoding)

            return f"Successfully edited {path}"
        except PermissionError:
            return f"Error: Permission denied: {path}"
        except Exception as e:
            return f"Error editing file: {str(e)}"


class ListDir(Tool):
    """Tool to list directory contents."""

    @property
    def name(self) -> str:
        return "list_dir"

    @property
    def description(self) -> str:
        return "List the contents of a directory."

    @property
    def parameters(self) -> dict:
        return {
            "type": "object",
            "properties": {
                "path": {"type": "string", "description": "The directory path to list"}
            },
            "required": ["path"],
        }

    async def _execute(self, parameters: dict, context: ToolCallContext) -> str:
        try:
            path = parameters["path"]
            dir_path = Path(path).expanduser()
            if not dir_path.exists():
                return f"Error: Directory not found: {path}"
            if not dir_path.is_dir():
                return f"Error: Not a directory: {path}"

            items = []
            for item in sorted(dir_path.iterdir()):
                prefix = "📁 " if item.is_dir() else "📄 "
                items.append(f"{prefix}{item.name}")

            if not items:
                return f"Directory {path} is empty"

            return "\n".join(items)
        except PermissionError:
            return f"Error: Permission denied: {path}"
        except Exception as e:
            return f"Error listing directory: {str(e)}"
