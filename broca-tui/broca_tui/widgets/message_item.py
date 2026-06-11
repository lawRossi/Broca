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
from typing import Any, Dict, Optional

from rich.markdown import Markdown

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

    def __init__(self, message: Dict[str, Any], **kwargs):
        """Initialize message item.

        Args:
            message: Message dict with message_type, role, data, etc.
        """
        super().__init__(**kwargs)
        self._message = message
        self._msg_id = message.get("message_id", f"msg-{id(self)}")
        self._show_params = False
        self._show_result = False
        self._show_reasoning = False

    def on_mount(self) -> None:
        """Collapse all collapsible sections by default on mount.

        Content containers (.params-content, .result-content, etc.) are
        mounted visible by default; this hides them so the initial "▶" icon
        correctly represents the collapsed state.
        """
        for selector in (
            ".params-content",
            ".result-content",
            ".reasoning-content",
            ".preview-content",
        ):
            try:
                for child in self.query(selector):
                    child.display = False
            except Exception:
                pass

    def compose(self) -> ComposeResult:
        """Create the message layout based on type."""
        msg = self._message
        msg_type = msg.get("message_type", "")
        role = msg.get("role", "")
        data = msg.get("data", {}) or {}

        border_class = self._get_border_class(msg_type, role)
        icon = self._get_icon(msg_type, data)
        sender = self._get_sender_name(msg_type, data)
        timestamp = msg.get("timestamp", "")[:19] if msg.get("timestamp") else ""

        with Vertical(classes=f"message-item {border_class}"):
            # Header: icon + sender + timestamp
            with Horizontal(classes="message-header-row"):
                yield Label(f"{icon} {sender}", classes="message-sender")
                if timestamp:
                    yield Label(timestamp, classes="message-timestamp")

            # Content area — MUST use yield from for generator methods
            with Vertical(classes="message-content-area"):
                yield from self._render_message_content(msg_type, data)

            # Hover actions (undo) — using dynamic ID
            hover_id = f"hover-actions-{self._msg_id}"
            with Horizontal(classes="hover-actions", id=hover_id):
                yield Button("↩ 撤销", id=f"undo-{self._msg_id}", classes="undo-button")

    # ===== Styling helpers =====

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
        """Get icon for message type."""
        if msg_type in ("user_message",):
            return "👤"
        elif msg_type in ("agent_response",):
            return "🤖"
        elif msg_type in ("error", "agent_error"):
            return "⚠️"
        elif msg_type == "tool_call":
            tool_name = data.get("tool_name", "")
            status = data.get("status")
            has_result = data.get("result") is not None
            if tool_name == "ask_user":
                return "❓"
            elif tool_name == "todo_management":
                return "📋"
            elif not has_result:
                return "🔧⏳"
            elif status in (True, "success"):
                return "🔧✅"
            elif status in (False, "error"):
                return "🔧❌"
            return "🔧"
        elif msg_type in ("agent_system_message", "system_message"):
            return "💬"
        return "💬"

    def _get_sender_name(self, msg_type: str, data: Dict[str, Any]) -> str:
        """Get sender display name."""
        if msg_type in ("user_message",):
            return "You"
        elif msg_type in ("agent_response",):
            return self._message.get("sender_id", "Agent")
        elif msg_type in ("error", "agent_error"):
            return "Error"
        elif msg_type == "tool_call":
            tool_name = data.get("tool_name", "unknown_tool")
            return f"Tool: {tool_name}"
        elif msg_type in ("agent_system_message",):
            return "System"
        return "Unknown"

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
        """Render user message content."""
        content = data.get("content", data.get("message", ""))
        yield Static(content, classes="msg-content plain-text", markup=False)

    def _render_agent_response(self, data: Dict[str, Any]):
        """Render agent response with Markdown."""
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
        if reasoning:
            reasoning_toggle_id = f"reasoning-toggle-{self._msg_id}"
            reasoning_content_id = f"reasoning-content-{self._msg_id}"
            yield Label("💭 Reasoning", classes="reasoning-toggle", id=reasoning_toggle_id)
            with Vertical(classes="reasoning-content", id=reasoning_content_id):
                yield Static(reasoning, classes="msg-content reasoning-text", markup=False)

        # Render main content with Markdown — FIX: use Static instead of RichLog
        if content:
            try:
                md = Markdown(content)
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
            params_toggle_id = f"params-toggle-{self._msg_id}"
            params_content_id = f"params-content-{self._msg_id}"
            if arguments:
                yield Label("▶ Parameters", classes="collapsible-toggle", id=params_toggle_id)
                with Vertical(classes="params-content", id=params_content_id):
                    formatted = _format_json(arguments)
                    yield Static(formatted, classes="json-display", markup=False)

            # Result (collapsible) — dynamic ID
            result_toggle_id = f"result-toggle-{self._msg_id}"
            result_content_id = f"result-content-{self._msg_id}"
            if result is not None:
                yield Label("▶ Result", classes="collapsible-toggle", id=result_toggle_id)
                with Vertical(classes="result-content", id=result_content_id):
                    yield Static(str(result), classes="result-display", markup=False)

    def _render_edit_file(self, arguments: Any):
        """Render edit_file tool with diff display."""
        args = _parse_arguments(arguments)
        path = args.get("path", "")
        old_text = args.get("old_text", "")
        new_text = args.get("new_text", "")

        yield Label(f"📝 Editing: {path}", classes="tool-header")

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
        """Render write_file tool with file content."""
        args = _parse_arguments(arguments)
        path = args.get("path", "")
        content = args.get("content", "")

        yield Label(f"📄 Writing: {path}", classes="tool-header")
        if content:
            yield Static(content.strip(), classes="file-content", markup=False)

    def _render_read_file(self, arguments: Any, result: Any):
        """Render read_file tool."""
        args = _parse_arguments(arguments)
        path = args.get("path", "")
        yield Label(f"📖 Reading: {path}", classes="tool-header")

        if result:
            preview_toggle_id = f"preview-toggle-{self._msg_id}"
            preview_content_id = f"preview-content-{self._msg_id}"
            yield Label("▶ Preview", classes="collapsible-toggle", id=preview_toggle_id)
            with Vertical(classes="preview-content", id=preview_content_id):
                yield Static(str(result)[:2000], classes="file-content", markup=False)

    def _render_todo_management(self, arguments: Any):
        """Render todo_management tool."""
        args = _parse_arguments(arguments)

        todos = None
        if isinstance(args, dict):
            todos = args.get("todos", args.get("parameters", {}).get("todos"))
        elif isinstance(args, list):
            todos = args

        if todos and isinstance(todos, list):
            yield Label("📋 Todo List", classes="tool-header")
            for todo in todos:
                name = todo.get("name", "Untitled")
                status = todo.get("status", "pending")
                icon = "✅" if status == "completed" else ("⏳" if status == "in_progress" else "⬜")
                yield Label(f"{icon}  {name}", classes="todo-item")
        else:
            yield Static(_format_json(todos or args), classes="json-display", markup=False)

    def _render_ask_user(self, arguments: Any, result: Any):
        """Render ask_user tool with question and options."""
        args = _parse_arguments(arguments)
        question = args.get("question", "")
        options = args.get("options", [])

        yield Label("❓ Question", classes="tool-header")
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

        if result is not None:
            yield Label("Answer:", classes="result-label")
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
