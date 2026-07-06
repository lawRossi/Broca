"""
ChatInput Widget

Input box with:
- Send target indicator ("Sending to: AgentName")
- /command autocomplete (dynamically loaded from API, with fallback)
- @mention autocomplete (filtered agent list above input)
- Enter to send, Shift+Enter for newline
- Disabled when Runner is not running
"""

from __future__ import annotations

from typing import Any, Callable, Dict, List, Optional, Tuple

from textual.app import ComposeResult
from textual.containers import Horizontal, Vertical
from textual.events import Key
from textual.reactive import reactive
from textual.widgets import Button, Label, ListItem, ListView, TextArea


class _ChatTextArea(TextArea):
    """TextArea subclass: Enter sends message, Shift+Enter inserts newline."""

    def __init__(self, on_send=None, nav_autocomplete=None, **kwargs):
        super().__init__(**kwargs)
        self._on_send = on_send
        self._nav_autocomplete = nav_autocomplete

    async def _on_key(self, event: Key) -> None:
        """Override TextArea._on_key to send on Enter instead of newline."""
        key = event.key
        if key in ("up", "down"):
            # 上下键优先导航补全列表
            if self._nav_autocomplete and self._nav_autocomplete(key):
                event.stop()
                event.prevent_default()
                return
            # 无补全列表时走默认行为
            await super()._on_key(event)
            return
        if key == "enter":
            event.stop()
            event.prevent_default()
            if self._on_send:
                self._on_send()
            return
        if key == "shift+enter":
            event.stop()
            event.prevent_default()
            self.insert("\n")
            return
        await super()._on_key(event)


from broca_tui.api.session import SessionAPI

# Fallback commands (used when API call fails)
FALLBACK_COMMANDS: List[Tuple[str, str]] = [
    ("/help", "显示命令帮助"),
    ("/abort", "中止当前执行"),
    ("/undo", "撤销上一步操作"),
    ("/redo", "重做上一步撤销"),
    ("/plan", "生成实施计划文档"),
    ("/init", "初始化项目并生成概要"),
    ("/clear_context", "清除当前 Agent 的上下文"),
    ("/clear_all_context", "清除所有 Agent 的上下文"),
    ("/clear_history", "清除所有 Agent 的消息历史"),
    ("/execute-plan", "按阶段执行计划文档"),
    ("/review-code", "系统化代码评审"),
    ("/debug", "系统化 Debug 修复 Bug"),
]


def _format_command_tuple(cmd: Dict[str, str]) -> Tuple[str, str]:
    """Convert API command dict to (name, short_description) tuple.

    Args:
        cmd: Command dict from API

    Returns:
        Tuple of (name, short_description)
    """
    name = cmd.get("name", "/unknown")
    if not name.startswith("/"):
        name = f"/{name}"
    short_desc = cmd.get("short_description", "") or cmd.get("description", "")
    return (name, short_desc)


class ChatInput(Vertical):
    """Input widget with autocomplete support."""

    DEFAULT_CSS = """
    ChatInput {
        width: 1fr;
        height: auto;
        layout: vertical;
        overflow: hidden hidden;
    }
    TextArea#chat-input-field {
        height: auto;
        max-height: 8;
        min-height: 1;
        border: none;
        background: transparent;
        padding: 0 1;
        margin: 0;
        color: #075985;
    }
    """

    disabled = reactive(False)
    target_agent = reactive("")

    def __init__(
        self,
        placeholder: str = "输入/执行命令，@指定agent",
        **kwargs,
    ):
        """Initialize chat input.

        Args:
            placeholder: Input placeholder text
        """
        super().__init__(**kwargs)
        self._placeholder = placeholder
        self._agents: List[Dict[str, Any]] = []
        self._main_agent_id: str = ""
        self._commands: List[Tuple[str, str]] = list(FALLBACK_COMMANDS)
        self._autocomplete_type: Optional[str] = None  # "command" or "mention"
        self._filtered_items: List[Any] = []
        self._selected_index: int = 0
        self._on_send: Optional[Callable] = None
        self._on_abort: Optional[Callable] = None
        self._suppress_next_change: bool = False  # 补全后抑制一次 Input.Changed

    def compose(self) -> ComposeResult:
        """Create the input layout."""
        with Vertical(classes="chat-input-container"):
            # Autocomplete dropdown (shown above input)
            yield ListView(id="autocomplete-list", classes="autocomplete")

            # Send target indicator
            yield Label("", id="target-indicator", classes="target-indicator")

            # Input row
            with Horizontal(classes="input-row"):
                yield _ChatTextArea(
                    on_send=self._send_message,
                    nav_autocomplete=self._navigate_autocomplete,
                    id="chat-input-field",
                    classes="chat-input-field",
                    soft_wrap=True,
                )
                yield Button(
                    "发送", id="btn-send", variant="primary", classes="send-button"
                )

    def set_agents(self, agents: List[Dict[str, Any]], main_agent_id: str = ""):
        """Set available agents for @mention, and optionally set the main agent ID.

        Args:
            agents: List of agent dicts
            main_agent_id: ID of the main agent (used as default target when no @mention)
        """
        self._agents = agents
        if main_agent_id:
            self._main_agent_id = main_agent_id

    def set_on_send(self, callback: Callable):
        """Set callback for message send.

        Args:
            callback: Called with (text, target_agent_id)
        """
        self._on_send = callback

    def set_on_abort(self, callback: Callable):
        """Set callback for abort.

        Args:
            callback: Called with ()
        """
        self._on_abort = callback

    def watch_disabled(self, is_disabled: bool):
        """Update input state when disabled changes.

        Args:
            is_disabled: Whether input is disabled
        """
        input_field = self.query_one("#chat-input-field", _ChatTextArea)
        input_field.disabled = is_disabled
        send_btn = self.query_one("#btn-send", Button)
        send_btn.disabled = is_disabled
        if is_disabled:
            input_field.placeholder = "Runner 未运行，无法发送消息..."
        else:
            input_field.placeholder = self._placeholder

    async def load_commands(self):
        """Load commands from API with fallback to hardcoded list.

        Called on mount to populate command autocomplete.
        Web: uses commandStore.fetchCommands() with get_commands API.
        """
        try:
            api = SessionAPI()
            api_commands = await api.get_commands()
            await api.close()
            if api_commands:
                self._commands = [_format_command_tuple(cmd) for cmd in api_commands]
        except Exception:
            self._commands = list(FALLBACK_COMMANDS)

    def watch_target_agent(self, agent_name: str):
        """Update target indicator.

        Args:
            agent_name: Target agent name
        """
        indicator = self.query_one("#target-indicator", Label)
        if agent_name:
            indicator.update(f"发送给: {agent_name}")
            indicator.styles.display = "block"
        else:
            indicator.update("")
            indicator.styles.display = "none"

    def _get_input_value(self) -> str:
        """Get current input value."""
        return self.query_one("#chat-input-field", _ChatTextArea).text

    def _set_input_value(self, value: str):
        """Set input value."""
        self.query_one("#chat-input-field", _ChatTextArea).text = value

    def _focus_input(self):
        """Focus the input field."""
        self.query_one("#chat-input-field", _ChatTextArea).focus()

    def _move_cursor_to_end(self):
        """Move cursor to end of text."""
        try:
            input_field = self.query_one("#chat-input-field", _ChatTextArea)
            input_field.action_cursor_line_end()
        except Exception:
            pass

    def _navigate_autocomplete(self, direction: str) -> bool:
        """Navigate autocomplete list with up/down keys.

        Args:
            direction: "up" or "down"

        Returns:
            True if autocomplete was navigated, False if no autocomplete visible
        """
        if not self._autocomplete_type or not self._filtered_items:
            return False
        list_view = self.query_one("#autocomplete-list", ListView)
        if not list_view.display:
            return False

        current = list_view.index or 0
        total = len(self._filtered_items)
        if direction == "up":
            list_view.index = max(0, current - 1)
        elif direction == "down":
            list_view.index = min(total - 1, current + 1)
        return True

    def _show_autocomplete(self, items: List[Any], type: str):
        """Show the autocomplete dropdown.

        Args:
            items: List of autocomplete items
            type: "command" or "mention"
        """
        if not items:
            self._hide_autocomplete()
            return

        self._autocomplete_type = type
        self._filtered_items = items
        self._selected_index = 0

        list_view = self.query_one("#autocomplete-list", ListView)
        list_view.clear()

        for item in items:
            if type == "command":
                cmd_name, cmd_desc = item
                label = f"{cmd_name}  — {cmd_desc}"
            else:
                agent_name = item.get("name", item.get("agent_id", "Unknown"))
                label = f"@{agent_name}"
            list_view.append(ListItem(Label(label)))

        list_view.display = True
        list_view.index = 0

    def _hide_autocomplete(self):
        """Hide the autocomplete dropdown."""
        self._autocomplete_type = None
        self._filtered_items = []
        self._selected_index = 0
        self.query_one("#autocomplete-list", ListView).display = False

    def _handle_input_change(self, value: str):
        """Handle input value changes for autocomplete.

        Args:
            value: Current input value
        """
        if self._suppress_next_change:
            self._suppress_next_change = False
            self._hide_autocomplete()
            return
        if not value:
            self._hide_autocomplete()
            return

        # Command autocomplete (/ at start) — uses dynamically loaded commands
        if value.startswith("/"):
            parts = value.split(" ")
            if len(parts) == 1:
                cmd_prefix = parts[0].lower()
                matches = [
                    cmd for cmd in self._commands if cmd[0].startswith(cmd_prefix)
                ]
                self._show_autocomplete(matches, "command")
                return

        # Mention autocomplete (@)
        if "@" in value:
            # Find the last @ in the text
            at_index = value.rfind("@")
            if at_index >= 0:
                after_at = value[at_index + 1 :]
                mention_text = after_at.split(" ")[0]

                # 如果 @ 后面有空格，说明 mention 已补全完成（名字后已有空格）
                if " " in after_at:
                    self._hide_autocomplete()
                    return

                # 如果 mention 文本已精确匹配某个 agent 名字，不再弹出
                if mention_text:
                    exact_match = any(
                        mention_text.lower() == agent.get("name", "").lower()
                        or mention_text.lower() == agent.get("agent_id", "").lower()
                        for agent in self._agents
                    )
                    if exact_match:
                        self._hide_autocomplete()
                        return

                matches = [
                    agent
                    for agent in self._agents
                    if not mention_text  # 无过滤文本时匹配全部
                    or mention_text.lower() in agent.get("name", "").lower()
                    or mention_text.lower() in agent.get("agent_id", "").lower()
                ]
                if matches:
                    self._show_autocomplete(matches, "mention")
                    return

        self._hide_autocomplete()

    def _select_autocomplete(self):
        """Select the currently highlighted autocomplete item."""
        if not self._autocomplete_type or not self._filtered_items:
            return

        list_view = self.query_one("#autocomplete-list", ListView)
        if list_view.index is None:
            return

        idx = list_view.index
        if idx >= len(self._filtered_items):
            return

        value = self._get_input_value()

        if self._autocomplete_type == "command":
            selected_cmd = self._filtered_items[idx][0]
            # Replace the partial command
            self._set_input_value(selected_cmd + " ")
        elif self._autocomplete_type == "mention":
            selected_agent = self._filtered_items[idx]
            agent_name = selected_agent.get("name", selected_agent.get("agent_id", ""))
            # Replace the @mention text
            at_index = value.rfind("@")
            if at_index >= 0:
                before = value[:at_index]
                after = value[at_index:].split(" ", 1)
                rest = after[1] if len(after) > 1 else ""
                self._set_input_value(f"{before}@{agent_name} {rest}")

        # 抑制本次补全触发的 Changed 事件重新弹出下拉
        self._suppress_next_change = True
        self._hide_autocomplete()
        self._focus_input()
        # 补全后将光标移到末尾（延迟执行，确保文本渲染完成）
        self.set_timer(0.01, self._move_cursor_to_end)

    def _send_message(self):
        """Send the current message.

        Parses @mention from text to determine target agent.
        """
        if self._autocomplete_type and self._filtered_items:
            self._select_autocomplete()
            return

        if self.disabled:
            return

        value = self._get_input_value().strip()
        if not value:
            return

        # Clear input
        self._set_input_value("")

        # Parse @mention to find target agent
        target_agent_id = None
        clean_text = value
        if "@" in value:
            import re

            mention_match = re.search(r"@(\S+)", value)
            if mention_match:
                mention = mention_match.group(1)
                # Remove the @mention from text
                clean_text = re.sub(r"@\S+\s*", "", value, count=1).strip()
                # Find agent by name or ID
                for agent in self._agents:
                    agent_name = agent.get("name", "")
                    agent_id = agent.get("agent_id", "")
                    if mention == agent_name or mention == agent_id:
                        target_agent_id = agent_id
                        break

        # Default to main agent when no @mention
        if target_agent_id is None and self._main_agent_id:
            target_agent_id = self._main_agent_id

        if self._on_send:
            self._on_send(clean_text, target_agent_id)

    def on_text_area_changed(self, event: TextArea.Changed) -> None:
        """Handle input text changes.

        Args:
            event: TextArea changed event
        """
        if event.text_area.id == "chat-input-field":
            self._handle_input_change(event.text_area.text)

    def on_button_pressed(self, event: Button.Pressed) -> None:
        """Handle send button press.

        Args:
            event: Button pressed event
        """
        if event.button.id == "btn-send":
            self._send_message()

    def on_list_view_selected(self, event: ListView.Selected) -> None:
        """Handle autocomplete selection.

        Args:
            event: ListView selected event
        """
        self._select_autocomplete()

    def on_mount(self) -> None:
        """Focus input on mount and load commands from API."""
        self._hide_autocomplete()
        self._focus_input()
        self.run_worker(self.load_commands())
