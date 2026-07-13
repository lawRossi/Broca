---
name: create-tool
version: "1.0.0"
description: "Helps users create custom tools for the Broca agent framework. Use this skill when the user asks about creating a custom tool, extending agent capabilities with new tools, or generating a tool file in .broca/tools.py."
---

# Create Tool

Create a custom tool for the Broca framework. Custom tools allow extending the agent's capabilities with new functionality.

## ⚠️ Core Constraint

You may ONLY create/modify the custom tool file. Do not execute any unrelated operations that you don't have the tool for.

## Background

Broca has a tool system where each tool is a Python class that extends the `Tool` base class. Tools are automatically discovered and registered by `broca.tools.tool_manager.ToolManager`.

### Tool Base Class (`broca.tools.tool.py`)

```python
class Tool:
    def __init__(self, max_content_length: int = 20000):
        self.max_content_length = max_content_length

    @property
    def name(self) -> str:
        return "tool"  # Must override: unique identifier for the tool

    @property
    def description(self) -> str:
        return "This is a tool"  # Must override: tells LLM when to use this tool

    @property
    def parameters(self) -> dict:
        return {}  # Must override: JSON Schema defining tool parameters

    async def _execute(self, arguments: dict, context: ToolCallContext) -> ToolResult:
        # Must override: actual tool logic
        ...

    def validate_arguments(self, args_dict: dict) -> Optional[str]:
        # Optional override: custom argument validation
        ...
```

### Key Types

```python
class ToolResult:
    def __init__(self, status: ToolStatus, content: str):
        self.status = status  # ToolStatus.SUCCESS or ToolStatus.ERROR
        self.content = content  # String output returned to the LLM

class ToolCallContext:
    def __init__(self):
        self.agent = None       # The agent instance executing this tool
        self.workspace = None   # Workspace directory path (string or None)
        self.session_id = None  # Current session ID
        self.execution_id = None
        self.namespace = None   # Blackboard namespace (if applicable)

class ToolStatus(str, Enum):
    SUCCESS = "success"
    ERROR = "error"
```


## Creating a Custom Tool

### Step 1: Understand the Problem

- Clarify what the user wants the tool to do.
- What input parameters are needed? What output should it produce?
- Does it read data (read-only) or modify state (modify)?
- What edge cases, errors, or security considerations exist?

### Step 2: Locate or Create the Custom Tool File

Custom tools go in a single file at:
```
{workspace}/.broca/tools.py
```

The file must contain at least one `Tool` subclass. Multiple tool classes can coexist in the same file.

### Step 3: Implement the Tool Class

#### Minimal Template

```python
import json
from pathlib import Path
from typing import Optional

from broca.tools.tool import Tool, ToolCallContext, ToolResult, ToolStatus


class MyCustomTool(Tool):
    """My custom tool description."""

    @property
    def name(self) -> str:
        # MUST be unique across ALL tools (built-in + custom)
        return "my_custom_tool"

    @property
    def description(self) -> str:
        # Tell the LLM clearly when and how to use this tool
        return "A custom tool that does X. Use it when Y."

    @property
    def parameters(self) -> dict:
        # JSON Schema format
        return {
            "type": "object",
            "properties": {
                "param1": {
                    "type": "string",
                    "description": "Description of param1",
                },
                "param2": {
                    "type": "integer",
                    "description": "Description of param2",
                    "default": 42,
                },
            },
            "required": ["param1"],
        }

    async def _execute(self, arguments: dict, context: ToolCallContext) -> ToolResult:
        try:
            # 1. Extract parameters
            param1 = arguments["param1"]
            param2 = arguments.get("param2", 42)

            # 2. Use context for workspace-aware operations
            workspace = context.workspace  # str or None

            # 3. Implement your core logic
            result = f"Processed {param1} with value {param2}"

            # 4. Return success with meaningful output
            return ToolResult(
                status=ToolStatus.SUCCESS,
                content=result,
            )

        except Exception as e:
            return ToolResult(
                status=ToolStatus.ERROR,
                content=f"Error in my_custom_tool: {str(e)}",
            )
```

#### Real-World Example: A Statistics Tool

```python
import json
from pathlib import Path
from typing import Optional

from broca.tools.tool import Tool, ToolCallContext, ToolResult, ToolStatus


class FileStats(Tool):
    """Tool to analyze file statistics in a workspace."""

    @property
    def name(self) -> str:
        return "file_stats"

    @property
    def description(self) -> str:
        return (
            "Analyze file statistics in a directory. "
            "Returns file count, total size, and breakdown by extension. "
            "Use this when you need to understand the composition of a codebase."
        )

    @property
    def parameters(self) -> dict:
        return {
            "type": "object",
            "properties": {
                "path": {
                    "type": "string",
                    "description": "The directory path to analyze (relative to workspace or absolute). Defaults to workspace root.",
                },
                "min_size": {
                    "type": "integer",
                    "description": "Minimum file size in bytes to include in stats",
                    "default": 0,
                },
            },
            "required": [],
        }

    async def _execute(self, arguments: dict, context: ToolCallContext) -> ToolResult:
        try:
            # Resolve the search path
            rel_path = arguments.get("path", ".")
            workspace = context.workspace
            if workspace:
                base = Path(workspace)
            else:
                base = Path.cwd()
            search_dir = (base / rel_path).resolve()

            if not search_dir.exists() or not search_dir.is_dir():
                return ToolResult(
                    status=ToolStatus.ERROR,
                    content=f"Error: Directory not found: {search_dir}",
                )

            min_size = arguments.get("min_size", 0)
            files = [f for f in search_dir.rglob("*") if f.is_file()]

            # Filter by size
            if min_size > 0:
                files = [f for f in files if f.stat().st_size >= min_size]

            # Compute stats
            total_size = sum(f.stat().st_size for f in files)
            ext_counts = {}
            for f in files:
                ext = f.suffix.lower() or "(no extension)"
                ext_counts[ext] = ext_counts.get(ext, 0) + 1

            # Sort by count descending
            sorted_exts = sorted(ext_counts.items(), key=lambda x: -x[1])

            # Build output
            lines = [
                f"📊 File Statistics for: {search_dir}",
                f"Total files: {len(files)}",
                f"Total size: {self._format_size(total_size)}",
                "",
                "Breakdown by extension:",
            ]
            for ext, count in sorted_exts:
                lines.append(f"  {ext}: {count} file(s)")

            return ToolResult(
                status=ToolStatus.SUCCESS,
                content="\n".join(lines),
            )

        except Exception as e:
            return ToolResult(
                status=ToolStatus.ERROR,
                content=f"Error analyzing file stats: {str(e)}",
            )

    def _format_size(self, size: int) -> str:
        for unit in ["B", "KB", "MB", "GB"]:
            if size < 1024:
                return f"{size:.1f} {unit}"
            size /= 1024
        return f"{size:.1f} TB"
```

### Step 4: Validate the Tool

Run a quick instantiation/execution test to verify the tool works:

```python
# Test script — run this in the workspace to validate
import asyncio
from pathlib import Path
from broca.tools.tool import ToolCallContext

# Change to the workspace directory first, then:
import sys
sys.path.insert(0, str(Path.cwd()))

# Import your custom tool
from your_tools_file import FileStats

async def test():
    tool = FileStats()
    print(f"Name: {tool.name}")
    print(f"Description: {tool.description}")
    print(f"Parameters: {tool.parameters}")
    
    context = ToolCallContext()
    context.workspace = str(Path.cwd())
    
    result = await tool._execute({"path": "."}, context)
    print(f"\nResult status: {result.status}")
    print(f"Result content:\n{result.content}")

asyncio.run(test())
```

## Best Practices

### 1. Naming
- `name` must be **unique** across all tools (built-in + custom). Check existing tools with `ToolManager().tools.keys()` or search `broca/tools/` for names.
- Use `snake_case` for tool names.
- Name should be descriptive and follow existing patterns (e.g., `read_file`, `web_search`, `file_stats`).

### 2. Descriptions
- Write descriptions that help the LLM **understand when to call this tool**.
- Include what the tool does AND what situations it's useful for.
- Keep them concise but informative.

### 3. Parameters (JSON Schema)
- Provide **clear, detailed descriptions** for each parameter — this is how the LLM knows what to pass.
- Set sensible `default` values for optional parameters.
- Use `"required"` list for mandatory parameters.
- Supported types: `string`, `integer`, `number`, `boolean`, `array`, `object`.
- Use `"enum"` for constrained string values.
- For array parameters, use `"items": {"type": "..."}`.

### 4. Error Handling
- Wrap `_execute` logic in try/except blocks.
- Return `ToolResult(status=ToolStatus.ERROR, content=...)` for expected errors.
- Return `ToolResult(status=ToolStatus.SUCCESS, content=...)` for success.
- The `Tool.execute()` method handles JSON parsing and basic validation — you only override `_execute`.

### 5. Output Formatting
- Return human-readable, well-structured text in `content`.
- Use clear formatting (line breaks, bullet points, tables when helpful).
- Consider output length — default `max_content_length` is 20,000 characters.
- If output can be very long, consider truncation strategies.

### 6. Path Resolution
- Always use `context.workspace` to resolve relative paths.
- Use `Path(path).resolve()` for absolute paths.
- Handle both relative (to workspace) and absolute paths.

### 7. Using Context
- `context.agent` — access the agent instance (for asking permissions, sending messages, etc.)
- `context.workspace` — the workspace root directory
- `context.session_id` — current session identifier
- `context.namespace` — blackboard namespace (when used in orchestration)

### 8. Importing Dependencies
- Custom tools can import any Python standard library modules.
- For external dependencies, use only what's available in the project's dependencies, or ask the user to install them.
- Import from `broca.*` as needed (e.g., `broca.tools.tool`, `broca.logging_config`).

## Common Pitfalls

| Pitfall | Solution |
|---------|----------|
| Tool name conflicts with built-in | Run `from broca.tools.tool_manager import ToolManager; list(ToolManager().tools.keys())` to check existing names |
| Forgetting `await` in async method | Always use `await` when calling async operations in `_execute` |
| Not handling file not found | Check `Path.exists()` before operations, return descriptive errors |
| Hardcoding paths | Always use `context.workspace` for relative path resolution |
| Returning non-string content | `ToolResult.content` must always be a string |
| Exceptions not caught | Wrap the entire `_execute` body in try/except |
