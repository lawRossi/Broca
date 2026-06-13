"""
MessageItem Widget

Renders a single chat message with full type support:
- user_message: blue border, 👤 icon, plain text
- agent_response: green border, 🤖 icon, Markdown rendering
- tool_call: purple border, collapsible params/results, diff for edit_file
- error: red border
- system: gray centered
- Hover actions for undo
"""

from __future__ import annotations

import json
import difflib
import re
from datetime import datetime, timezone, timedelta
from typing import Any, Dict, Optional

from rich.markdown import Markdown
from rich.syntax import Syntax

from textual.app import ComposeResult
from textual.containers import Horizontal, Vertical
from textual.events import Click
from textual.widgets import Button, Label, Static
from textual.widget import Widget


def _format_json(data: Any) -> str:
    """Format data as pretty JSON string.

    Args:
        data: Data to format

    Returns:
        Pretty-printed JSON string
    """
    if data is None:
        return "null"
    try:
        if isinstance(data, str):
            try:
                parsed = json.loads(data)
                return json.dumps(parsed, indent=2, ensure_ascii=False)
            except (json.JSONDecodeError, TypeError):
                return data
        return json.dumps(data, indent=2, ensure_ascii=False)
    except (TypeError, ValueError):
        return str(data)


def _parse_arguments(arguments: Any) -> Dict[str, Any]:
    """Parse tool arguments from string or dict.

    Args:
        arguments: Raw arguments (string or dict)

    Returns:
        Parsed dict
    """
    if isinstance(arguments, str):
        try:
            return json.loads(arguments)
        except (json.JSONDecodeError, TypeError):
            return {}
    return arguments if isinstance(arguments, dict) else {}


class MessageItem(Widget):
    """A single message item in the chat."""

    DEFAULT_CSS = """
    MessageItem {
        height: auto;   /* 防止在 ScrollableContainer 中被 1fr 拉伸 */
    }
    """

    def __init__(self, message: Dict[str, Any], agent_name: str = "", agent_id: str = "",
                 agent_name_map: Optional[Dict[str, str]] = None, **kwargs):
        """Initialize message item.

        Args:
            message: Message dict with message_type, role, data, etc.
            agent_name: Current/primary agent display name (for same-agent display)
            agent_id: Current/primary agent ID (for cross-agent comparison, matching Web's currentAgentId)
            agent_name_map: Dict mapping agent_id → display_name (for showing @Name instead of @ID)
        """
        super().__init__(**kwargs)
        self._message = message
        self._msg_id = message.get("message_id", f"msg-{id(self)}")
        data = message.get("data", {}) or {}
        self._agent_name = agent_name or data.get("agent_name", "")
        self._agent_id = agent_id or data.get("agent_id", "")
        self._agent_name_map = agent_name_map or {}
        self._show_params = False
        self._show_result = False
        self._show_reasoning = False

        # Determine which sections should be expanded by default (Web alignment)
        msg_type = message.get("message_type", "")
        tool_name = (message.get("data", {}) or {}).get("tool_name", "")
        self._default_expand_params = (
            msg_type == "tool_call" and tool_name in ("todo_management", "ask_user")
        )
        self._default_expand_result = (
            msg_type == "tool_call" and tool_name == "ask_user"
        )
        self._default_expand_reasoning = False

    def on_mount(self) -> None:
        """Collapse/expand sections based on message type (Web alignment).

        Web behavior:
        - todo_management: parameters expanded by default
        - ask_user: parameters AND result expanded by default
        - Other tools: all sections collapsed by default
        """
        # Handle parameter sections
        for child in self.query(".params-content"):
            child.display = self._default_expand_params
            self._update_toggle_icon("params", self._default_expand_params)
        # Handle result sections
        for child in self.query(".result-content"):
            child.display = self._default_expand_result
            self._update_toggle_icon("result", self._default_expand_result)
        # Handle reasoning content
        for child in self.query(".reasoning-content"):
            child.display = self._default_expand_reasoning
            self._update_toggle_icon("reasoning", self._default_expand_reasoning)
        # Handle preview content (always collapsed)
        for child in self.query(".preview-content"):
            child.display = False
            self._update_toggle_icon("preview", False)

    def _update_toggle_icon(self, section: str, is_expanded: bool) -> None:
        """Update the toggle icon (▶/▼) for a given section.

        Args:
            section: Section name ('params', 'result', 'reasoning', 'preview')
            is_expanded: Whether the section is expanded
        """
        try:
            toggle = self.query_one(f"#{section}-toggle-{self._msg_id}", Label)
            current = toggle.content or ""
            icon = "▼" if is_expanded else "▶"
            for prefix in ("▶", "▼"):
                if current.startswith(prefix):
                    toggle.update(current.replace(prefix, icon, 1))
                    break
        except Exception:
            pass

    def compose(self) -> ComposeResult:
        """Create the message layout based on type."""
        msg = self._message
        msg_type = msg.get("message_type", "")
        role = msg.get("role", "")
        data = msg.get("data", {}) or {}

        border_class = self._get_border_class(msg_type, role)
        header_color_class = self._get_header_color_class(msg_type, role)
        icon = self._get_icon(msg_type, data)
        sender = self._get_sender_name(msg_type, data)
        timestamp = self._format_timestamp(msg.get("timestamp", ""))

        with Vertical(classes=f"message-item {border_class}"):
            # Header: icon + sender + timestamp — hidden for system messages (Web alignment)
            is_system = msg_type in ("agent_system_message", "system_message") or role == "agent_system"
            if not is_system:
                with Horizontal(classes="message-header-row"):
                    yield Label(f"{icon} {sender}", classes=f"message-sender {header_color_class}")
                    if timestamp:
                        yield Label(timestamp, classes="message-timestamp")

            # Content area — MUST use yield from for generator methods
            with Vertical(classes="message-content-area"):
                yield from self._render_message_content(msg_type, data)

            # Undo button — always clickable (Web: visibility toggle, but TUI needs consistent clickability)
            if not is_system:
                yield Button("↩️ 撤销", id=f"undo-{self._msg_id}", classes="undo-button")

    # ===== Styling helpers =====

    def _get_header_color_class(self, msg_type: str, role: str) -> str:
        """Get CSS class for header text color (aligns with Web getHeaderColor)."""
        if msg_type in ("user_message",) or role == "user":
            return "header-user"
        elif msg_type in ("agent_response",) or role == "assistant":
            return "header-agent"
        elif msg_type in ("error", "agent_error"):
            return "header-error"
        elif msg_type in ("tool_call",):
            return "header-tool"
        elif msg_type in ("agent_system_message", "system_message") or role == "agent_system":
            return "header-system"
        return "header-default"

    def _get_border_class(self, msg_type: str, role: str) -> str:
        """Get CSS class based on message type."""
        if msg_type in ("user_message",) or role == "user":
            return "msg-user"
        elif msg_type in ("agent_response",) or role == "assistant":
            return "msg-agent"
        elif msg_type in ("tool_call",):
            return "msg-tool"
        elif msg_type in ("error", "agent_error"):
            return "msg-error"
        elif msg_type in ("agent_system_message", "system_message"):
            return "msg-system"
        return "msg-default"

    @staticmethod
    def _get_icon(msg_type: str, data: Dict[str, Any]) -> str:
        """Get icon for message type (aligning with Web getIcon).

        Web priority order for tool_call:
        1. No result → 🔧⏳ (pending/streaming)
        2. Status true/success → 🔧✅
        3. Status false/error → 🔧❌
        4. Has result but no explicit status → 🔧 (fallback)
        """
        if msg_type == "tool_call":
            tool_name = data.get("tool_name", "")

            # Tool-specific icons
            if tool_name == "ask_user":
                return "❓"
            if tool_name == "todo_management":
                return "📋"

            has_result = data.get("result") is not None
            status = data.get("status")

            # Web priority: pending first → success → error → fallback
            if not has_result:
                return "🔧⏳"  # 1. No result = pending/streaming
            if status is True or status == "success":
                return "🔧✅"  # 2. Success with explicit status
            if status is False or status == "error":
                return "🔧❌"  # 3. Error with explicit status
            return "🔧"        # 4. Has result, unknown status

        elif msg_type in ("user_message",):
            return "👤"
        elif msg_type in ("agent_response",):
            return "🤖"
        elif msg_type in ("error", "agent_error"):
            return "⚠️"
        elif msg_type in ("agent_system_message", "system_message"):
            return "💬"
        return "💬"

    def _get_sender_name(self, msg_type: str, data: Dict[str, Any]) -> str:
        """Get sender display name (aligning with Web getSenderName).

        Cross-agent detection (aligning with Web):
        - Web compares sender_id/receiver_id with agentStore.currentAgentId
        - We use self._agent_id for comparison, self._agent_name for display
        - Falls back to msg.agent_id when sender_id is empty (sub-agent messages)
        - Cross-agent: shows @AgentName (resolved from agent_name_map), not @AgentID

        Cross-agent display:
        - user_message: "You" or "You → @AgentName" when receiver_id != current agent
        - agent_response: "@AgentName" or current agent_name (no @ prefix for self)
        - tool_call: "@AgentName - Tool" or "" for current agent (Web: empty = icon only)
        - error: "Error"
        - system: "System"
        """
        msg = self._message
        sender_id = msg.get("sender_id", "") or msg.get("agent_id", "")
        receiver_id = msg.get("receiver_id", "")
        msg_agent_id = msg.get("agent_id", "")

        # Determine the current agent ID for comparison (Web: agentStore.currentAgentId)
        current_agent_id = self._agent_id or self._agent_name or ""

        if msg_type in ("user_message",):
            # Web: targets other agent when receiver_id/agent_id != currentAgentId
            target_id = receiver_id or msg_agent_id
            if target_id and target_id != current_agent_id:
                target_name = self._resolve_agent_name(target_id)
                return f"You → @{target_name}"
            return "You"

        elif msg_type in ("agent_response",):
            # Fallback: use agent_id if sender_id is empty (sub-agent messages)
            sender = sender_id
            if not sender:
                sender = msg_agent_id

            if sender and sender != "user":
                if current_agent_id and sender != current_agent_id:
                    sender_name = self._resolve_agent_name(sender)
                    return f"@{sender_name}"
                return self._agent_name or sender
            return sender or self._agent_name or "Agent"

        elif msg_type in ("error", "agent_error"):
            return "Error"

        elif msg_type == "tool_call":
            tool_name = data.get("tool_name", "unknown_tool")
            # Fallback: use agent_id if sender_id is empty (sub-agent messages)
            sender = sender_id
            if not sender:
                sender = msg_agent_id

            # Web: returns '' for same-agent (header shows just icon)
            # Cross-agent: "@AgentName - Tool" when sender differs from current
            if sender and sender != current_agent_id and sender != "user":
                sender_name = self._resolve_agent_name(sender)
                return f"@{sender_name} - {tool_name}"
            return ""  # Same agent: empty sender name (Web alignment)

        elif msg_type in ("agent_system_message",):
            return "System"

        return "Unknown"

    def _resolve_agent_name(self, agent_id: str) -> str:
        """Resolve agent ID to display name (matching Web: agentStore.agents.find).

        Args:
            agent_id: Agent ID to resolve

        Returns:
            Agent display name, or the ID itself if not found in name map
        """
        if agent_id in self._agent_name_map:
            return self._agent_name_map[agent_id]
        return agent_id

    @staticmethod
    def _format_timestamp(timestamp_str: str) -> str:
        """Format timestamp aligning with Web's formatBeijingTimeShort.

        Web format:
        - Today: "HH:MM" (Beijing time)
        - Non-today: "MM/DD HH:MM"
        """
        if not timestamp_str:
            return ""

        try:
            # Parse ISO timestamp
            if timestamp_str.endswith("Z"):
                dt = datetime.fromisoformat(timestamp_str.replace("Z", "+00:00"))
            elif "+" in timestamp_str or "-" in timestamp_str[10:]:
                dt = datetime.fromisoformat(timestamp_str)
            else:
                dt = datetime.fromisoformat(timestamp_str)

            # Convert to Beijing time (UTC+8)
            beijing_tz = timezone(timedelta(hours=8))
            dt_beijing = dt.astimezone(beijing_tz)

            # Get current Beijing time
            now_beijing = datetime.now(beijing_tz)

            if dt_beijing.date() == now_beijing.date():
                # Today: HH:MM
                return dt_beijing.strftime("%H:%M")
            else:
                # Non-today: MM/DD HH:MM
                return dt_beijing.strftime("%m/%d %H:%M")
        except (ValueError, TypeError):
            # Fallback: return first 5 chars of timestamp
            return timestamp_str[:5] if len(timestamp_str) >= 5 else timestamp_str[:19]

    # ===== Content rendering =====

    def _render_message_content(self, msg_type: str, data: Dict[str, Any]):
        """Render message content based on type.

        NOTE: This method uses 'yield from' to delegate to sub-renderers.
        All sub-renderers are generator functions that yield Widget instances.
        """
        if msg_type in ("user_message",):
            yield from self._render_user_message(data)
        elif msg_type in ("agent_response",):
            yield from self._render_agent_response(data)
        elif msg_type == "tool_call":
            yield from self._render_tool_call(data)
        elif msg_type in ("error", "agent_error"):
            yield from self._render_error(data)
        elif msg_type in ("agent_system_message", "system_message"):
            yield from self._render_system_message(data)
        else:
            yield from self._render_fallback(data)

    def _render_user_message(self, data: Dict[str, Any]):
        """Render user message content (Web alignment: raw_input > content > message)."""
        # Web: raw_input has highest priority for user messages
        content = data.get("raw_input", "")
        if not content:
            content = data.get("content", data.get("message", ""))

        # Web: try to parse JSON content with nested content field
        if isinstance(content, str) and content.strip().startswith("{"):
            try:
                parsed = json.loads(content)
                if isinstance(parsed, dict) and "content" in parsed:
                    inner = parsed["content"]
                    if isinstance(inner, list):
                        # Web: filter for type === 'text' parts
                        text_parts = [
                            p.get("text", "") for p in inner
                            if isinstance(p, dict) and p.get("type") == "text"
                        ]
                        content = "".join(text_parts) if text_parts else content
                    else:
                        content = inner
            except (json.JSONDecodeError, TypeError):
                pass

        yield Static(str(content), classes="msg-content plain-text", markup=False)

    @staticmethod
    def _preprocess_markdown(content: str) -> str:
        """Preprocess Markdown content for TUI rendering.

        - Image fallback: ![alt](url) → [Image: alt](url)
        """
        if not content:
            return content
        # Replace image syntax: ![alt](url) → [Image: alt](url)
        content = re.sub(r'!\[([^\]]*)\]\([^)]+\)', r'[Image: \1]', content)
        return content

    def _render_agent_response(self, data: Dict[str, Any]):
        """Render agent response with Markdown (enhanced with syntax highlighting)."""
        content_str = data.get("content", "")

        # Try to extract content from JSON wrapper
        content = content_str
        reasoning = ""
        if isinstance(content_str, str):
            try:
                parsed = json.loads(content_str)
                if isinstance(parsed, dict):
                    content = parsed.get("content", content_str)
                    reasoning = parsed.get("reasoning_content", "")
            except (json.JSONDecodeError, TypeError):
                pass

        # Render reasoning content (collapsible) — dynamic ID
        # Web: "▶ 思考" / "▼ 思考" — use same class as Parameters toggle
        if reasoning:
            reasoning_toggle_id = f"reasoning-toggle-{self._msg_id}"
            reasoning_content_id = f"reasoning-content-{self._msg_id}"
            yield Label("▶ 思考", classes="collapsible-toggle", id=reasoning_toggle_id)
            with Vertical(classes="reasoning-content", id=reasoning_content_id):
                yield Static(reasoning, classes="msg-content reasoning-text", markup=False)

        # Render main content with Markdown
        if content:
            try:
                # Preprocess: image fallback, etc.
                processed = self._preprocess_markdown(content)

                # Configure Markdown with code theme, no hyperlinks
                md = Markdown(
                    processed,
                    code_theme="monokai",
                    hyperlinks=False,
                )
                yield Static(md, classes="msg-content markdown-content")
            except Exception:
                yield Static(content, classes="msg-content plain-text", markup=False)

    def _render_tool_call(self, data: Dict[str, Any]):
        """Render tool call with collapsible params and results."""
        tool_name = data.get("tool_name", "")
        arguments = data.get("arguments", {})
        result = data.get("result")

        # Special handling for specific tools — MUST use yield from
        if tool_name == "edit_file":
            yield from self._render_edit_file(arguments)
        elif tool_name == "write_file":
            yield from self._render_write_file(arguments)
        elif tool_name == "read_file":
            yield from self._render_read_file(arguments, result)
        elif tool_name == "todo_management":
            yield from self._render_todo_management(arguments)
        elif tool_name == "ask_user":
            yield from self._render_ask_user(arguments, result)
        else:
            # General tool: collapsible parameters — dynamic IDs
            # Web: toggle button shows getParametersTitle → "参数" (default)
            # Always show at least the tool name (even if empty) for consistency
            yield Label(f"🔧 {tool_name}", classes="tool-header")
            params_toggle_id = f"params-toggle-{self._msg_id}"
            params_content_id = f"params-content-{self._msg_id}"
            if arguments:
                yield Label("▶ 参数", classes="collapsible-toggle", id=params_toggle_id)
                with Vertical(classes="params-content", id=params_content_id):
                    formatted = _format_json(arguments)
                    yield Static(formatted, classes="json-display", markup=False)

            # Result (collapsible) — dynamic ID
            result_toggle_id = f"result-toggle-{self._msg_id}"
            result_content_id = f"result-content-{self._msg_id}"
            if result is not None:
                yield Label("▶ 结果", classes="collapsible-toggle", id=result_toggle_id)
                with Vertical(classes="result-content", id=result_content_id):
                    # Format result for better display
                    result_str = str(result)
                    if isinstance(result, str) and len(result) > 2000:
                        result_str = result[:2000] + "\n... [结果已截断]"
                    yield Static(result_str, classes="result-display", markup=False)

    def _render_edit_file(self, arguments: Any):
        """Render edit_file tool with diff display (Web: collapsible, default collapsed)."""
        args = _parse_arguments(arguments)
        path = args.get("path", "")
        old_text = args.get("old_text", "")
        new_text = args.get("new_text", "")

        # Show tool name + file path (Web: content area shows tool_name, diff-header shows path)
        yield Label(f"edit_file", classes="tool-header")
        yield Label(f"📃 {path}", classes="diff-path")

        # Web: edit_file parameters are collapsible, default collapsed (shouldExpand=false)
        params_toggle_id = f"params-toggle-{self._msg_id}"
        params_content_id = f"params-content-{self._msg_id}"
        yield Label("▶ 编辑内容", classes="collapsible-toggle", id=params_toggle_id)
        with Vertical(classes="params-content", id=params_content_id):
            if old_text or new_text:
                diff_lines = list(difflib.unified_diff(
                    old_text.splitlines(keepends=True),
                    new_text.splitlines(keepends=True),
                    fromfile="old",
                    tofile="new",
                ))

                with Vertical(classes="diff-container"):
                    for line in diff_lines[2:]:  # Skip header lines
                        line_content = line.rstrip("\n")
                        if line.startswith("+"):
                            yield Label(line_content, classes="diff-line diff-added")
                        elif line.startswith("-"):
                            yield Label(line_content, classes="diff-line diff-removed")
                        elif line.startswith("@"):
                            yield Label(line_content, classes="diff-line diff-header")
                        else:
                            yield Label(line_content, classes="diff-line diff-unchanged")
            else:
                yield Static(_format_json(args), classes="json-display", markup=False)

    def _render_write_file(self, arguments: Any):
        """Render write_file tool (Web: collapsible params, no result)."""
        args = _parse_arguments(arguments)
        path = args.get("path", "")
        content = args.get("content", "")

        # Web: content area shows tool_name → "write_file"
        # Web: diff-header shows 📃 {path}
        yield Label("write_file", classes="tool-header")
        yield Label(f"📃 {path}", classes="diff-path")

        # Web: parameters section with "文件内容" title, default collapsed
        # (shouldShowParameters=true, shouldExpandParameters=false for write_file)
        params_toggle_id = f"params-toggle-{self._msg_id}"
        params_content_id = f"params-content-{self._msg_id}"
        yield Label("▶ 文件内容", classes="collapsible-toggle", id=params_toggle_id)
        with Vertical(classes="params-content", id=params_content_id):
            if content:
                yield Static(content.strip(), classes="file-content", markup=False)

        # Web: no result section (shouldShowResult=false for write_file)

    def _render_read_file(self, arguments: Any, result: Any):
        """Render read_file tool (Web: params hidden, result collapsible)."""
        args = _parse_arguments(arguments)
        path = args.get("path", "")

        # Web: content area shows tool_name → "read_file"
        # Web: diff-header shows 📃 {path}
        yield Label("read_file", classes="tool-header")
        yield Label(f"📃 {path}", classes="diff-path")

        # Web: no parameters section (shouldShowParameters=false for read_file)
        # Web: result section with "文件内容" title, default collapsed (shouldExpandResult=false)
        if result:
            result_toggle_id = f"result-toggle-{self._msg_id}"
            result_content_id = f"result-content-{self._msg_id}"
            yield Label("▶ 文件内容", classes="collapsible-toggle", id=result_toggle_id)
            with Vertical(classes="result-content", id=result_content_id):
                yield Static(str(result)[:2000], classes="file-content", markup=False)

    def _render_todo_management(self, arguments: Any):
        """Render todo_management tool."""
        # Web: parameters expanded by default, no separate result section
        # (shouldShowResult=false for todo_management)
        args = _parse_arguments(arguments)

        todos = None
        if isinstance(args, dict):
            todos = args.get("todos", args.get("parameters", {}).get("todos"))
        elif isinstance(args, list):
            todos = args

        if todos and isinstance(todos, list):
            for todo in todos:
                name = todo.get("name", "Untitled")
                status = todo.get("status", "pending")
                icon = "✅" if status == "completed" else ("⏳" if status == "in_progress" else "⬜")
                yield Label(f"{icon}  {name}", classes="todo-item")
        else:
            yield Static(_format_json(todos or args), classes="json-display", markup=False)

    def _render_ask_user(self, arguments: Any, result: Any):
        """Render ask_user tool with question and options."""
        # Web: parameters expanded by default, result expanded by default
        args = _parse_arguments(arguments)
        question = args.get("question", "")
        options = args.get("options", [])

        # Web label: "问题:" (parameters section)
        yield Label("问题:", classes="params-label")
        if question:
            yield Static(question, classes="ask-question", markup=False)

        if options:
            for opt in options:
                name = opt.get("name", "")
                desc = opt.get("description", "")
                if desc:
                    yield Label(f"• {name}: {desc}", classes="ask-option")
                else:
                    yield Label(f"• {name}", classes="ask-option")

        # Web label: "回答:" (result section)
        if result is not None:
            yield Label("回答:", classes="result-label")
            yield Static(str(result), classes="result-text", markup=False)

    def _render_error(self, data: Dict[str, Any]):
        """Render error message."""
        error_msg = data.get("content", data.get("error_message", "Unknown error"))
        yield Label(f"⚠️ {error_msg}", classes="error-text")

    def _render_system_message(self, data: Dict[str, Any]):
        """Render system message (centered, gray)."""
        content = data.get("content", "")
        yield Label(content, classes="system-text")

    def _render_fallback(self, data: Dict[str, Any]):
        """Render fallback for unknown message types."""
        yield Static(str(data), classes="plain-text", markup=False)

    # ── Collapsible toggle click handler ──

    def on_click(self, event: Click) -> None:
        """Toggle collapsible sections when a toggle Label is clicked.

        Naming convention:
          - params-toggle-{msg_id}  <->  params-content-{msg_id}
          - result-toggle-{msg_id}  <->  result-content-{msg_id}
          - reasoning-toggle-{msg_id}  <->  reasoning-content-{msg_id}
          - preview-toggle-{msg_id}  <->  preview-content-{msg_id}
        """
        widget = event.widget
        if widget is None:
            return

        widget_id = widget.id or ""
        suffix = "-toggle-"
        idx = widget_id.find(suffix)
        if idx == -1:
            return

        # Derive content ID from toggle ID
        # e.g. "params-toggle-xxx" → "params-content-xxx"
        content_id = widget_id[:idx] + "-content-" + widget_id[idx + len(suffix):]

        try:
            content = self.query_one(f"#{content_id}")
        except Exception:
            return

        # Toggle display: visible ↔ hidden
        content.display = not content.display
        is_visible = content.display

        # Update toggle icon: ▶ collapsed / ▼ expanded
        icon = "▼" if is_visible else "▶"
        if isinstance(widget, Label):
            current = widget.content or ""
            for prefix in ("▶", "▼"):
                if current.startswith(prefix):
                    widget.update(current.replace(prefix, icon, 1))
                    break


