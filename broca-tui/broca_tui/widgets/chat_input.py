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
from textual.reactive import reactive
from textual.widgets import Button, Input, Label, ListView, ListItem
from textual.widget import Widget

from broca_tui.api.session import SessionAPI


# Fallback commands (used when API call fails)
FALLBACK_COMMANDS: List[Tuple[str, str, str]] = [
    ("/help", "显示帮助信息", "local"),
    ("/abort", "中止当前操作", "local"),
    ("/undo", "撤销上一步操作", "local"),
    ("/redo", "重做已撤销的操作", "local"),
    ("/plan", "制定执行计划", "prompt"),
    ("/ask", "询问问题", "prompt"),
    ("/init", "初始化项目", "prompt"),
]


def _format_command_tuple(cmd: Dict[str, str]) -> Tuple[str, str, str]:
    """Convert API command dict to (name, description, type) tuple.

    Args:
        cmd: Command dict from API

    Returns:
        Tuple of (name, description, type)
    """
    name = cmd.get("name", "/unknown")
    if not name.startswith("/"):
        name = f"/{name}"
    return (
        name,
        cmd.get("description", ""),
        cmd.get("type", "local"),
    )


class ChatInput(Vertical):
    """Input widget with autocomplete support."""

    DEFAULT_CSS = """
    ChatInput {
        width: 1fr;
        height: auto;
        layout: vertical;
        overflow: hidden hidden;
    }
    """

    disabled = reactive(False)
    target_agent = reactive("")

    def __init__(
        self,
        placeholder: str = "输入消息... (Enter 发送, @ 提及 Agent)",
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
        self._commands: List[Tuple[str, str, str]] = list(FALLBACK_COMMANDS)
        self._autocomplete_type: Optional[str] = None  # "command" or "mention"
        self._filtered_items: List[Any] = []
        self._selected_index: int = 0
        self._on_send: Optional[Callable] = None
        self._on_abort: Optional[Callable] = None

    def compose(self) -> ComposeResult:
        """Create the input layout."""
        with Vertical(classes="chat-input-container"):
            # Autocomplete dropdown (shown above input)
            yield ListView(id="autocomplete-list", classes="autocomplete")

            # Send target indicator
            yield Label("", id="target-indicator", classes="target-indicator")

            # Input row
            with Horizontal(classes="input-row"):
                yield Input(
                    placeholder=self._placeholder,
                    id="chat-input-field",
                    classes="chat-input-field",
                )
                yield Button("发送", id="btn-send", variant="primary", classes="send-button")

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
        input_field = self.query_one("#chat-input-field", Input)
        input_field.disabled = is_disabled
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
        return self.query_one("#chat-input-field", Input).value

    def _set_input_value(self, value: str):
        """Set input value."""
        self.query_one("#chat-input-field", Input).value = value

    def _focus_input(self):
        """Focus the input field."""
        self.query_one("#chat-input-field", Input).focus()

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
                cmd_name, cmd_desc, cmd_type = item
                label = f"{cmd_name}  — {cmd_desc}  [{cmd_type}]"
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
        if not value:
            self._hide_autocomplete()
            return

        # Command autocomplete (/ at start) — uses dynamically loaded commands
        if value.startswith("/"):
            parts = value.split(" ")
            if len(parts) == 1:
                cmd_prefix = parts[0].lower()
                matches = [
                    cmd for cmd in self._commands
                    if cmd[0].startswith(cmd_prefix)
                ]
                self._show_autocomplete(matches, "command")
                return

        # Mention autocomplete (@)
        if "@" in value:
            # Find the last @ in the text
            at_index = value.rfind("@")
            if at_index >= 0:
                mention_text = value[at_index + 1:].split(" ")[0]
                matches = [
                    agent for agent in self._agents
                    if mention_text.lower() in agent.get("name", "").lower()
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

        self._hide_autocomplete()
        self._focus_input()

    def _send_message(self):
        """Send the current message.

        Parses @mention from text to determine target agent.
        """
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

    def on_input_changed(self, event: Input.Changed) -> None:
        """Handle input text changes.

        Args:
            event: Input changed event
        """
        if event.input.id == "chat-input-field":
            self._handle_input_change(event.value)

    def on_input_submitted(self, event: Input.Submitted) -> None:
        """Handle Enter key (send message).

        Args:
            event: Input submitted event
        """
        if event.input.id == "chat-input-field":
            # Don't send if autocomplete is visible
            list_view = self.query_one("#autocomplete-list", ListView)
            if list_view.display:
                self._select_autocomplete()
            else:
                self._send_message()

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
