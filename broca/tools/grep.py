import asyncio
from pathlib import Path
from typing import Any

from broca.tools.tool import Tool, ToolCallContext, ToolResult, ToolStatus


class GrepTool(Tool):
    """Tool to search file contents using regular expressions."""

    def __init__(self, limit=100, max_line_length=2000):
        super().__init__()
        self.limit = limit
        self.max_line_length = max_line_length

    @property
    def name(self) -> str:
        return "grep"

    @property
    def description(self) -> str:
        return """- Fast content search tool that searches file contents using regular expressions
- Supports full regex syntax (eg. "log.*Error", "function\\s+\\w+", etc.)
- Can search in directories or specific files
- Filter files by pattern with the include parameter (eg. "*.js", "*.{ts,tsx}")
- Returns file paths and line numbers with at least one match sorted by modification time
- Use this tool when you need to find files containing specific patterns"""

    @property
    def parameters(self) -> dict:
        return {
            "type": "object",
            "properties": {
                "pattern": {
                    "type": "string",
                    "description": "The regex pattern to search for in file contents",
                },
                "path": {
                    "type": "string",
                    "description": "The directory or file to search in. Defaults to the current working directory.",
                },
                "include": {
                    "type": "string",
                    "description": 'File pattern to include in the search (e.g. "*.js", "*.{ts,tsx}")',
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
            include_pattern = parameters.get("include")

            # Resolve the search path
            if context.workspace:
                base_path = Path(context.workspace)
            else:
                base_path = Path.cwd()

            # Handle relative paths
            if search_path == ".":
                search_dir = base_path
            else:
                search_dir = (base_path / search_path).resolve()

            search_path_resolved = search_dir.resolve()

            if not search_path_resolved.exists():
                return ToolResult(
                    status=ToolStatus.ERROR,
                    content=f"Error: Path not found: {search_path_resolved}",
                )

            # Build ripgrep command
            # rg -nH --field-match-separator=| --regexp "pattern" [--glob "include"] path
            cmd = ["rg", "-nH", "--field-match-separator=|", "--regexp", pattern]

            if include_pattern:
                cmd.extend(["--glob", include_pattern])

            cmd.append(str(search_path_resolved))

            try:
                process = await asyncio.create_subprocess_exec(
                    *cmd,
                    stdout=asyncio.subprocess.PIPE,
                    stderr=asyncio.subprocess.PIPE,
                )

                stdout, stderr = await process.communicate()

                if process.returncode == 0:
                    # Parse output
                    output = stdout.decode("utf-8").strip()
                    lines = output.split("\n") if output else []

                    matches: list[dict[str, Any]] = []
                    for line in lines:
                        if not line:
                            continue

                        # Format: file_path|line_number|line_text
                        parts = line.split("|", 2)
                        if len(parts) >= 3:
                            file_path = parts[0]
                            line_num = parts[1]
                            line_text = parts[2]

                            try:
                                full_path = Path(file_path)
                                if full_path.exists():
                                    mtime = full_path.stat().st_mtime
                                    matches.append(
                                        {
                                            "path": file_path,
                                            "line_num": int(line_num),
                                            "line_text": line_text,
                                            "mtime": mtime,
                                        }
                                    )
                            except Exception:
                                matches.append(
                                    {
                                        "path": file_path,
                                        "line_num": int(line_num),
                                        "line_text": line_text,
                                        "mtime": 0,
                                    }
                                )

                    if not matches:
                        return ToolResult(
                            status=ToolStatus.SUCCESS,
                            content="No matches found",
                        )

                    # Sort by modification time (newest first)
                    matches.sort(key=lambda x: int(x.get("mtime", 0) or 0), reverse=True)

                    truncated = len(matches) > self.limit
                    if truncated:
                        matches = matches[: self.limit]

                    # Format output
                    output_lines = [f"Found {len(matches)} matches"]

                    current_file = None
                    for match in matches:
                        if current_file != match["path"]:
                            if current_file is not None:
                                output_lines.append("")
                            current_file = match["path"]
                            output_lines.append(f"{match['path']}:")

                        # Truncate long lines
                        line_text = str(match.get("line_text", ""))
                        if len(line_text) > self.max_line_length:
                            line_text = line_text[: self.max_line_length] + "..."

                        output_lines.append(f"  Line {match['line_num']}: {line_text}")

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
                        content="No matches found",
                    )
                else:
                    # Error from ripgrep
                    error_msg = stderr.decode("utf-8").strip()
                    return ToolResult(
                        status=ToolStatus.ERROR,
                        content=f"Error executing grep search: {error_msg}",
                    )

            except FileNotFoundError:
                return ToolResult(
                    status=ToolStatus.ERROR,
                    content="Error: ripgrep (rg) command not found. Please install ripgrep to use this tool.",
                )

        except Exception as e:
            return ToolResult(
                status=ToolStatus.ERROR,
                content=f"Error executing grep tool: {str(e)}",
            )
