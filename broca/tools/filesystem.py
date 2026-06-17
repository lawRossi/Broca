import datetime
import re
from pathlib import Path
from typing import Generator, Optional

from broca.tools.tool import Tool, ToolCallContext, ToolResult, ToolStatus


# ---------- Replacers ----------

Replacer = Generator[str, None, None]


def _simple_replacer(content: str, find: str) -> Replacer:
    """Exact match."""
    yield find


def _line_trimmed_replacer(content: str, find: str) -> Replacer:
    """Line-by-line trimmed comparison."""
    original_lines = content.split("\n")
    search_lines = find.split("\n")
    if search_lines and search_lines[-1] == "":
        search_lines.pop()

    for i in range(len(original_lines) - len(search_lines) + 1):
        match = True
        for j in range(len(search_lines)):
            if original_lines[i + j].strip() != search_lines[j].strip():
                match = False
                break
        if match:
            start = sum(len(original_lines[k]) + 1 for k in range(i))
            end = start + sum(
                len(original_lines[i + k]) + (1 if k < len(search_lines) - 1 else 0)
                for k in range(len(search_lines))
            )
            yield content[start:end]


def _whitespace_normalized_replacer(content: str, find: str) -> Replacer:
    """Normalize all whitespace (collapse to single space)."""

    def normalize_ws(t: str) -> str:
        return re.sub(r"\s+", " ", t).strip()

    normalized_find = normalize_ws(find)

    # Single line matches
    for line in content.split("\n"):
        if normalize_ws(line) == normalized_find:
            yield line
        else:
            normalized_line = normalize_ws(line)
            if normalized_find in normalized_line:
                words = find.strip().split()
                if words:
                    pattern_str = r"\s+".join(re.escape(w) for w in words)
                    m = re.search(pattern_str, line)
                    if m:
                        yield m.group(0)

    # Multi-line matches
    find_lines = find.split("\n")
    if len(find_lines) > 1:
        lines = content.split("\n")
        for i in range(len(lines) - len(find_lines) + 1):
            block = "\n".join(lines[i : i + len(find_lines)])
            if normalize_ws(block) == normalized_find:
                yield block


def _indentation_flexible_replacer(content: str, find: str) -> Replacer:
    """Remove common leading indentation before comparing."""

    def remove_indent(text: str) -> str:
        lines = text.split("\n")
        non_empty = [l for l in lines if l.strip()]
        if not non_empty:
            return text
        min_indent = min(
            len(m.group(1))
            for l in non_empty
            if (m := re.match(r"^(\s*)", l))
        )
        return "\n".join(
            l[min_indent:] if l.strip() else l for l in lines
        )

    normalized_find = remove_indent(find)
    content_lines = content.split("\n")
    find_lines = find.split("\n")

    for i in range(len(content_lines) - len(find_lines) + 1):
        block = "\n".join(content_lines[i : i + len(find_lines)])
        if remove_indent(block) == normalized_find:
            yield block


def _escape_normalized_replacer(content: str, find: str) -> Replacer:
    """Handle escape sequences in find string."""

    def unescape(s: str) -> str:
        return (
            s.replace("\\n", "\n")
            .replace("\\t", "\t")
            .replace("\\r", "\r")
            .replace("\\'", "'")
            .replace('\\"', '"')
            .replace("\\\\", "\\")
        )

    unescaped_find = unescape(find)

    if unescaped_find in content:
        yield unescaped_find

    lines = content.split("\n")
    find_lines = unescaped_find.split("\n")

    for i in range(len(lines) - len(find_lines) + 1):
        block = "\n".join(lines[i : i + len(find_lines)])
        if unescape(block) == unescaped_find:
            yield block


def _trimmed_boundary_replacer(content: str, find: str) -> Replacer:
    """Trim boundaries of search string."""
    trimmed_find = find.strip()
    if trimmed_find == find:
        return
    if trimmed_find in content:
        yield trimmed_find

    lines = content.split("\n")
    find_lines = find.split("\n")
    for i in range(len(lines) - len(find_lines) + 1):
        block = "\n".join(lines[i : i + len(find_lines)])
        if block.strip() == trimmed_find:
            yield block


def _multi_occurrence_replacer(content: str, find: str) -> Replacer:
    """Yield all exact matches of find in content."""
    start = 0
    while True:
        idx = content.find(find, start)
        if idx == -1:
            break
        yield find
        start = idx + len(find)


def _find_old_text(content: str, old_text: str, replace_all: bool) -> Optional[str]:
    """
    Try all replacer strategies to find old_text in content.
    Returns the actual matched string if found, None otherwise.
    """
    for replacer in [
        _simple_replacer,
        _line_trimmed_replacer,
        _whitespace_normalized_replacer,
        _indentation_flexible_replacer,
        _escape_normalized_replacer,
        _trimmed_boundary_replacer,
        _multi_occurrence_replacer,
    ]:
        for match in replacer(content, old_text):
            idx = content.find(match)
            if idx == -1:
                continue
            if replace_all:
                return match
            # For single replacement, ensure it's the last occurrence
            last_idx = content.rfind(match)
            if idx == last_idx:
                return match
            # Multiple occurrences of this match; try next replacer
            break
    return None


class ReadFile(Tool):
    """Tool to read file contents."""

    def __init__(self):
        super().__init__(max_content_length=30000)

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

            # Use multi-strategy search to find old_text
            actual_old = _find_old_text(content, old_text, replace_all)
            if actual_old is None:
                return ToolResult(
                    status=ToolStatus.ERROR,
                    content="Error: old_text not found in file. Make sure it matches exactly, including whitespace, indentation, and line endings.",
                )

            # Count occurrences of the actual match
            count = content.count(actual_old)
            if count > 1 and not replace_all:
                return ToolResult(
                    status=ToolStatus.ERROR,
                    content=f"Error: old_text appears {count} times. Please provide more context to make it unique or set replace_all to true.",
                )

            new_content = content.replace(actual_old, new_text)
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
                "path": {"type": "string", "description": "The directory path to list"},
                "show_mtime": {
                    "type": "boolean",
                    "description": "Whether to show last modification time of each item",
                    "default": False,
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

            show_mtime = parameters.get("show_mtime", False)
            items = []
            for item in sorted(dir_path.iterdir()):
                prefix = "📁 " if item.is_dir() else "📄 "
                if show_mtime:
                    try:
                        mtime = datetime.datetime.fromtimestamp(
                            item.stat().st_mtime
                        ).strftime("%Y-%m-%d %H:%M:%S")
                        items.append(f"{prefix}{item.name}  ({mtime})")
                    except Exception:
                        items.append(f"{prefix}{item.name}  (N/A)")
                else:
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
                "show_mtime": {
                    "type": "boolean",
                    "description": "Whether to show last modification time of each item",
                    "default": False,
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
            show_mtime = parameters.get("show_mtime", False)

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
                show_mtime=show_mtime,
            )

            if not tree_lines:
                return ToolResult(
                    status=ToolStatus.SUCCESS,
                    content=f"Directory {path} is empty or all items are ignored",
                )

            # Add header
            header = f"Directory tree for: {path}\n"
            if ignore_patterns:
                ignored_str = ", ".join(sorted(ignore_patterns)[:5])
                if len(ignore_patterns) > 5:
                    ignored_str += f" and {len(ignore_patterns) - 5} more"
                header += f"Ignored patterns: {ignored_str}\n"
            header += "max_depth: " + str(max_depth) + "\n"
            if show_mtime:
                header += "show_mtime: True\n"
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
        show_mtime: bool = False,
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
            if show_mtime:
                try:
                    mtime = datetime.datetime.fromtimestamp(
                        item.stat().st_mtime
                    ).strftime("%Y-%m-%d %H:%M:%S")
                    tree_lines.append(f"{prefix}{connector}{icon}{item.name}  ({mtime})")
                except Exception:
                    tree_lines.append(f"{prefix}{connector}{icon}{item.name}  (N/A)")
            else:
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
                    show_mtime=show_mtime,
                )


class FileMtime(Tool):
    """Tool to view last modification times of specified files."""

    @property
    def name(self) -> str:
        return "file_mtime"

    @property
    def description(self) -> str:
        return """View the last modification time of specified files.
Accepts a list of file paths and returns each file's last modified timestamp.
Useful for checking which files were recently changed."""

    @property
    def parameters(self) -> dict:
        return {
            "type": "object",
            "properties": {
                "paths": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "List of file paths to check modification times for",
                },
            },
            "required": ["paths"],
        }

    async def _execute(self, parameters: dict, context: ToolCallContext) -> ToolResult:
        try:
            paths = parameters["paths"]
            if not paths:
                return ToolResult(
                    status=ToolStatus.ERROR,
                    content="Error: No file paths provided",
                )

            results = []
            for path in paths:
                file_path = Path(path).expanduser()
                if not file_path.exists():
                    results.append(f"❌ {path}  —  Not found")
                    continue
                try:
                    stat = file_path.stat()
                    mtime = datetime.datetime.fromtimestamp(stat.st_mtime).strftime(
                        "%Y-%m-%d %H:%M:%S"
                    )
                    size = stat.st_size
                    if file_path.is_dir():
                        results.append(
                            f"📁 {path}  —  {mtime}  ({_format_size(size)})"
                        )
                    else:
                        results.append(
                            f"📄 {path}  —  {mtime}  ({_format_size(size)})"
                        )
                except PermissionError:
                    results.append(f"🔒 {path}  —  Permission denied")
                except Exception as e:
                    results.append(f"⚠️  {path}  —  Error: {e}")

            return ToolResult(
                status=ToolStatus.SUCCESS, content="\n".join(results)
            )
        except Exception as e:
            return ToolResult(
                status=ToolStatus.ERROR,
                content=f"Error checking file modification times: {str(e)}",
            )


def _format_size(size: int) -> str:
    """Format file size in human-readable format."""
    for unit in ["B", "KB", "MB", "GB", "TB"]:
        if size < 1024:
            return f"{size:.1f} {unit}" if unit != "B" else f"{size} B"
        size /= 1024
    return f"{size:.1f} PB"
