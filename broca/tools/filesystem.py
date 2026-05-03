from pathlib import Path

from broca.tools.tool import Tool, ToolCallContext, ToolResult, ToolStatus


class ReadFile(Tool):
    """Tool to read file contents."""

    def __init__(self):
        super().__init__(30000)

    @property
    def name(self) -> str:
        return "read_file"

    @property
    def description(self) -> str:
        return (
            "Read the contents of a file at the given path. "
            "Supports reading specific line ranges with optional line numbers."
        )

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
                "start_line": {
                    "type": "integer",
                    "description": "The starting line number (1-indexed, inclusive) to read from. If not specified, reads from the beginning of the file.",
                },
                "end_line": {
                    "type": "integer",
                    "description": "The ending line number (1-indexed, inclusive) to read until. If not specified, reads to the end of the file.",
                },
                "show_line_number": {
                    "type": "boolean",
                    "description": "Whether to prefix each line with its line number (e.g., '1: '). Defaults to false.",
                    "default": False,
                },
            },
            "required": ["path"],
        }

    async def _execute(self, parameters: dict, context: ToolCallContext) -> ToolResult:
        try:
            path = parameters["path"]
            file_path = Path(path).expanduser()
            encoding = parameters.get("encoding", "utf-8")
            start_line = parameters.get("start_line")
            end_line = parameters.get("end_line")
            show_line_number = parameters.get("show_line_number", False)

            if not file_path.exists():
                return ToolResult(
                    status=ToolStatus.ERROR, content=f"Error: File not found: {path}"
                )
            if not file_path.is_file():
                return ToolResult(
                    status=ToolStatus.ERROR, content=f"Error: Not a file: {path}"
                )

            content = file_path.read_text(encoding=encoding)

            # If no line range specified, return full content (with optional line numbers)
            if start_line is None and end_line is None:
                if show_line_number:
                    lines = content.splitlines()
                    numbered_lines = [
                        f"{i + 1}: {line}" for i, line in enumerate(lines)
                    ]
                    return ToolResult(
                        status=ToolStatus.SUCCESS,
                        content="\n".join(numbered_lines),
                    )
                return ToolResult(status=ToolStatus.SUCCESS, content=content)

            lines = content.splitlines()
            total_lines = len(lines)

            # Validate and normalize line numbers
            if start_line is not None:
                if start_line < 1:
                    return ToolResult(
                        status=ToolStatus.ERROR,
                        content=f"Error: start_line must be >= 1, got {start_line}",
                    )
                if start_line > total_lines:
                    return ToolResult(
                        status=ToolStatus.ERROR,
                        content=f"Error: start_line ({start_line}) exceeds total lines ({total_lines}) in file",
                    )

            if end_line is not None:
                if end_line < 1:
                    return ToolResult(
                        status=ToolStatus.ERROR,
                        content=f"Error: end_line must be >= 1, got {end_line}",
                    )
                if end_line > total_lines:
                    end_line = total_lines

            # Default to full range if only one bound is set
            start_idx = (start_line - 1) if start_line is not None else 0
            end_idx = end_line if end_line is not None else total_lines

            # Ensure start <= end
            if start_idx >= end_idx:
                return ToolResult(
                    status=ToolStatus.ERROR,
                    content=f"Error: start_line ({start_line}) must be less than or equal to end_line ({end_line})",
                )

            selected_lines = lines[start_idx:end_idx]

            if show_line_number:
                # Offset by start_line so line numbers match the original file
                numbered_lines = [
                    f"{start_idx + i + 1}: {line}"
                    for i, line in enumerate(selected_lines)
                ]
                return ToolResult(
                    status=ToolStatus.SUCCESS,
                    content="\n".join(numbered_lines),
                )

            return ToolResult(
                status=ToolStatus.SUCCESS, content="\n".join(selected_lines)
            )
        except PermissionError:
            return ToolResult(
                status=ToolStatus.ERROR, content=f"Error: Permission denied: {path}"
            )
        except Exception as e:
            return ToolResult(
                status=ToolStatus.ERROR, content=f"Error reading file: {str(e)}"
            )


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

    async def _execute(self, parameters: dict, context: ToolCallContext) -> ToolResult:
        try:
            path = parameters["path"]
            file_path = Path(path).expanduser()
            if file_path.exists() and not file_path.is_file():
                return ToolResult(
                    status=ToolStatus.ERROR, content=f"Error: Not a file: {path}"
                )
            content = parameters["content"]
            file_path.parent.mkdir(parents=True, exist_ok=True)
            file_path.write_text(content, encoding="utf-8")
            return ToolResult(
                status=ToolStatus.SUCCESS,
                content=f"Successfully wrote content to {path}",
            )
        except PermissionError:
            return ToolResult(
                status=ToolStatus.ERROR, content=f"Error: Permission denied: {path}"
            )
        except Exception as e:
            return ToolResult(
                status=ToolStatus.ERROR, content=f"Error writing file: {str(e)}"
            )


class EditFile(Tool):
    """Tool to edit a file by replacing text."""

    @property
    def name(self) -> str:
        return "edit_file"

    @property
    def description(self) -> str:
        return (
            "Edit a file by replacing old_text with new_text. "
            "Use the smallest old_text that's clearly unique — usually 2-4 adjacent lines is sufficient. "
            "Avoid including 10+ lines of context when less identifies the target."
        )

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

    async def _execute(self, parameters: dict, context: ToolCallContext) -> ToolResult:
        try:
            path = parameters["path"]
            file_path = Path(path).expanduser()
            if not file_path.exists():
                return ToolResult(
                    status=ToolStatus.ERROR, content=f"Error: File not found: {path}"
                )
            if not file_path.is_file():
                return ToolResult(
                    status=ToolStatus.ERROR, content=f"Error: Not a file: {path}"
                )
            old_text = parameters["old_text"]
            new_text = parameters["new_text"]
            encoding = parameters.get("encoding", "utf-8")
            replace_all = parameters.get("replace_all", False)

            content = file_path.read_text(encoding=encoding)

            if old_text not in content:
                return ToolResult(
                    status=ToolStatus.ERROR,
                    content="Error: old_text not found in file. Make sure it matches exactly.",
                )

            # Count occurrences
            count = content.count(old_text)
            if count > 1 and not replace_all:
                return ToolResult(
                    status=ToolStatus.ERROR,
                    content=f"Error: old_text appears {count} times. Please provide more context to make it unique or set replace_all to true.",
                )

            new_content = content.replace(old_text, new_text)
            file_path.write_text(new_content, encoding=encoding)

            return ToolResult(
                status=ToolStatus.SUCCESS, content=f"Successfully edited {path}"
            )
        except PermissionError:
            return ToolResult(
                status=ToolStatus.ERROR, content=f"Error: Permission denied: {path}"
            )
        except Exception as e:
            return ToolResult(
                status=ToolStatus.ERROR, content=f"Error editing file: {str(e)}"
            )


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

    async def _execute(self, parameters: dict, context: ToolCallContext) -> ToolResult:
        try:
            path = parameters["path"]
            dir_path = Path(path).expanduser()
            if not dir_path.exists():
                return ToolResult(
                    status=ToolStatus.ERROR,
                    content=f"Error: Directory not found: {path}",
                )
            if not dir_path.is_dir():
                return ToolResult(
                    status=ToolStatus.ERROR, content=f"Error: Not a directory: {path}"
                )

            items = []
            for item in sorted(dir_path.iterdir()):
                prefix = "📁 " if item.is_dir() else "📄 "
                items.append(f"{prefix}{item.name}")

            if not items:
                return ToolResult(
                    status=ToolStatus.SUCCESS, content=f"Directory {path} is empty"
                )

            return ToolResult(status=ToolStatus.SUCCESS, content="\n".join(items))
        except PermissionError:
            return ToolResult(
                status=ToolStatus.ERROR, content=f"Error: Permission denied: {path}"
            )
        except Exception as e:
            return ToolResult(
                status=ToolStatus.ERROR, content=f"Error listing directory: {str(e)}"
            )


IGNORE_PATTERNS = [
    "node_modules",
    "__pycache__",
    ".git",
    "dist",
    "build",
    "target",
    "vendor",
    "bin",
    "obj",
    ".idea",
    ".vscode",
    ".zig-cache",
    "zig-out",
    ".coverage",
    "coverage",
    "vendor",
    "tmp",
    "temp",
    ".cache",
    "cache",
    "logs",
    ".venv",
    "venv",
    "env",
    ".pnpm",
    ".mypy_cache",
    ".pytest_cache",
    ".ruff_cache",
]


class TreeDir(Tool):
    """Tool to display directory tree structure."""

    @property
    def name(self) -> str:
        return "tree_dir"

    @property
    def description(self) -> str:
        return "Display directory tree structure with optional ignore patterns."

    @property
    def parameters(self) -> dict:
        return {
            "type": "object",
            "properties": {
                "path": {
                    "type": "string",
                    "description": "The directory path to display as tree",
                },
                "max_depth": {
                    "type": "integer",
                    "description": "Maximum depth to traverse (default: 5)",
                    "default": 3,
                },
                "ignore_special": {
                    "type": "boolean",
                    "description": "Whether to ignore special direcoties (e.g., ['node_modules', '.git'])",
                    "default": True,
                },
                "show_hidden": {
                    "type": "boolean",
                    "description": "Whether to show hidden files and directories",
                    "default": False,
                },
                "show_files": {
                    "type": "boolean",
                    "description": "Whether to show files or only directories",
                    "default": True,
                },
            },
            "required": ["path"],
        }

    async def _execute(self, parameters: dict, context: ToolCallContext) -> ToolResult:
        try:
            path = parameters["path"]
            dir_path = Path(path).expanduser()
            if not dir_path.exists():
                return ToolResult(
                    status=ToolStatus.ERROR,
                    content=f"Error: Directory not found: {path}",
                )
            if not dir_path.is_dir():
                return ToolResult(
                    status=ToolStatus.ERROR, content=f"Error: Not a directory: {path}"
                )

            max_depth = parameters.get("max_depth", 3)
            ignore_patterns = (
                IGNORE_PATTERNS if parameters.get("ignore_special", True) else []
            )
            show_hidden = parameters.get("show_hidden", False)
            show_files = parameters.get("show_files", True)

            # Build the tree structure
            tree_lines: list = []
            self._build_tree(
                dir_path,
                tree_lines,
                prefix="",
                is_last=True,
                depth=0,
                max_depth=max_depth,
                ignore_patterns=ignore_patterns,
                show_hidden=show_hidden,
                show_files=show_files,
            )

            if not tree_lines:
                return ToolResult(
                    status=ToolStatus.SUCCESS,
                    content=f"Directory {path} is empty or all items are ignored",
                )

            # Add header
            header = f"Directory tree for: {path}\n"
            if ignore_patterns:
                header += f"Ignored patterns: {', '.join(sorted(ignore_patterns)[:5])}"
                header += f"Ignored patterns: {', '.join(ignore_patterns[:5])}"
                if len(ignore_patterns) > 5:
                    header += f" and {len(ignore_patterns) - 5} more"
                header += "\n"
            header += "max_depth: " + str(max_depth) + "\n"
            header += "=" * 50 + "\n"

            return ToolResult(
                status=ToolStatus.SUCCESS, content=header + "\n".join(tree_lines)
            )
        except PermissionError:
            return ToolResult(
                status=ToolStatus.ERROR, content=f"Error: Permission denied: {path}"
            )
        except Exception as e:
            return ToolResult(
                status=ToolStatus.ERROR, content=f"Error displaying tree: {str(e)}"
            )

    def _build_tree(
        self,
        dir_path: Path,
        tree_lines: list,
        prefix: str,
        is_last: bool,
        depth: int,
        max_depth: int,
        ignore_patterns: list,
        show_hidden: bool,
        show_files: bool,
    ) -> None:
        """Recursively build tree structure."""
        if depth >= max_depth:
            return

        # Get all items in directory
        try:
            items = list(dir_path.iterdir())
        except PermissionError:
            tree_lines.append(f"{prefix}└── [Permission denied]")
            return

        # Filter items
        filtered_items = []
        for item in items:
            # Skip hidden files if not showing hidden
            if not show_hidden and item.name.startswith("."):
                continue

            # Skip ignored patterns
            if any(pattern in item.name for pattern in ignore_patterns):
                continue

            # Skip files if show_files is False
            if not show_files and not item.is_dir():
                continue

            filtered_items.append(item)

        # Sort items: directories first, then files
        filtered_items.sort(key=lambda x: (not x.is_dir(), x.name.lower()))

        for i, item in enumerate(filtered_items):
            is_last_item = i == len(filtered_items) - 1

            # Determine the connector
            connector = "└── " if is_last_item else "├── "

            # Determine the icon
            icon = "📁 " if item.is_dir() else "📄 "

            # Add the current item
            tree_lines.append(f"{prefix}{connector}{icon}{item.name}")

            # If it's a directory, recurse
            if item.is_dir():
                extension = "    " if is_last_item else "│   "
                self._build_tree(
                    item,
                    tree_lines,
                    prefix=prefix + extension,
                    is_last=is_last_item,
                    depth=depth + 1,
                    max_depth=max_depth,
                    ignore_patterns=ignore_patterns,
                    show_hidden=show_hidden,
                    show_files=show_files,
                )
