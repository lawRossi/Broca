import asyncio
import datetime
import os
from pathlib import Path

from broca.tools.tool import Tool, ToolCallContext, ToolResult, ToolStatus


class GlobTool(Tool):
    """Tool to find files using glob patterns."""

    def __init__(self, limit=100):
        super().__init__()
        self.limit = limit

    @property
    def name(self) -> str:
        return "glob"

    @property
    def description(self) -> str:
        return """- Fast file pattern matching tool that works with any codebase size
- Supports glob patterns like "**/*.js" or "src/**/*.ts"
- Returns matching file paths sorted by modification time
- Use this tool when you need to find files by name patterns"""

    @property
    def parameters(self) -> dict:
        return {
            "type": "object",
            "properties": {
                "pattern": {
                    "type": "string",
                    "description": "The glob pattern to match files against",
                },
                "path": {
                    "type": "string",
                    "description": "The directory to search in. If not specified, the current working directory will be used.",
                },
                "show_mtime": {
                    "type": "boolean",
                    "description": "Whether to show last modification time of each file",
                    "default": False,
                },
            },
            "required": ["pattern"],
        }

    async def _execute(self, parameters: dict, context: ToolCallContext) -> ToolResult:
        try:
            pattern = parameters["pattern"]
            
            # Validate pattern is not empty
            if not pattern:
                return ToolResult(
                    status=ToolStatus.ERROR,
                    content="Error: Pattern cannot be empty",
                )
            
            search_path = parameters.get("path", ".")

            # Resolve the search path
            if context.workspace:
                base_path = Path(context.workspace)
            else:
                base_path = Path.cwd()

            # Handle relative paths
            if search_path == ".":
                search_dir = base_path
            else:
                if os.path.isabs(search_path):
                    search_dir = Path(search_path)
                else:
                    search_dir = base_path / search_path

            search_dir = search_dir.resolve()

            if not search_dir.exists():
                return ToolResult(
                    status=ToolStatus.ERROR,
                    content=f"Error: Directory not found: {search_dir}",
                )

            if not search_dir.is_dir():
                return ToolResult(
                    status=ToolStatus.ERROR,
                    content=f"Error: Not a directory: {search_dir}",
                )

            if pattern == "*":
                cmd = ["rg", "--files", str(search_dir)]
            else:
                cmd = ["rg", "--files", "--glob", pattern, str(search_dir)]

            try:
                process = await asyncio.create_subprocess_exec(
                    *cmd,
                    stdout=asyncio.subprocess.PIPE,
                    stderr=asyncio.subprocess.PIPE,
                )

                stdout, stderr = await process.communicate()

                if process.returncode == 0:
                    files = stdout.decode("utf-8").strip().split("\n")
                    files = [f for f in files if f]  # Remove empty strings

                    if not files:
                        return ToolResult(
                            status=ToolStatus.SUCCESS,
                            content="No files found",
                        )

                    # Sort by modification time (newest first)
                    sorted_files = []
                    for file_path in files:
                        try:
                            full_path = Path(file_path)
                            if full_path.exists():
                                mtime = full_path.stat().st_mtime
                                sorted_files.append((mtime, file_path))
                        except Exception:
                            sorted_files.append((0, file_path))

                    sorted_files.sort(reverse=True, key=lambda x: x[0])
                    files = [f[1] for f in sorted_files]
                    truncated = len(files) > self.limit
                    files = files[: self.limit]

                    show_mtime = parameters.get("show_mtime", False)
                    if show_mtime:
                        output_lines = []
                        for f in files:
                            try:
                                full_path = Path(f)
                                if full_path.exists():
                                    mtime = datetime.datetime.fromtimestamp(
                                        full_path.stat().st_mtime
                                    ).strftime("%Y-%m-%d %H:%M:%S")
                                    output_lines.append(f"{f}  ({mtime})")
                                else:
                                    output_lines.append(f)
                            except Exception:
                                output_lines.append(f)
                    else:
                        output_lines = list(files)

                    if truncated:
                        output_lines.append("")
                        output_lines.append(
                            "(Results are truncated. Consider using a more specific path or pattern.)"
                        )

                    return ToolResult(
                        status=ToolStatus.SUCCESS,
                        content="\n".join(output_lines),
                    )
                elif process.returncode == 1:
                    # No matches found
                    return ToolResult(
                        status=ToolStatus.SUCCESS,
                        content="No files found",
                    )
                else:
                    # Error from ripgrep
                    error_msg = stderr.decode("utf-8").strip()
                    return ToolResult(
                        status=ToolStatus.ERROR,
                        content=f"Error executing glob search: {error_msg}",
                    )

            except FileNotFoundError:
                return ToolResult(
                    status=ToolStatus.ERROR,
                    content="Error: ripgrep (rg) command not found. Please install ripgrep to use this tool.",
                )

        except Exception as e:
            return ToolResult(
                status=ToolStatus.ERROR,
                content=f"Error executing glob tool: {str(e)}",
            )
