"""
AgentQueryDialog (ModalScreen)

Handles agent queries/questions to the user:
- Displays question text with ❓ icon
- Preset option cards (clickable via Button)
- Custom input box (Ctrl+Enter to submit)
- Cancel / Submit buttons
"""

from __future__ import annotations

from typing import Dict, List, Optional

from rich.text import Text
from textual.app import ComposeResult
from textual.containers import Horizontal, ScrollableContainer, Vertical
from textual.screen import ModalScreen
from textual.widgets import Button, Input, Label, Static


class AgentQueryDialog(ModalScreen):
    """Modal dialog for agent queries."""

    DEFAULT_CSS = """
    AgentQueryDialog {
        align: center middle;
    }

    AgentQueryDialog > .dialog {
        width: 72;
        height: auto;
        max-height: 80%;
        background: $surface;
        border: thick $primary;
        padding: 1 2;
        overflow-y: auto;
    }

    AgentQueryDialog .dialog-title {
        text-style: bold;
        text-align: center;
        padding: 0 0 1 0;
    }

    AgentQueryDialog .dialog-content {
        height: 1fr;
    }

    AgentQueryDialog .query-question {
        padding: 0 0 1 0;
    }

    AgentQueryDialog .query-options-label {
        color: $text-muted;
        padding: 0 0 1 0;
    }

    AgentQueryDialog .option-btn {
        width: 1fr;
        height: auto;
        min-height: 3;
        padding: 0 1;
        background: transparent;
        border: solid $border;
        text-align: left;
        content-align: left middle;
        color: $text;
        margin: 0 0 1 0;
    }

    AgentQueryDialog .option-btn:hover {
        background: $accent 20%;
    }

    AgentQueryDialog .query-input-label {
        color: $text-muted;
        padding: 1 0 1 0;
    }

    AgentQueryDialog .query-input {
        margin: 0 0 1 0;
    }

    AgentQueryDialog .dialog-actions {
        align: center middle;
        height: auto;
        margin: 1 0 0 0;
    }
    """

    def __init__(
        self,
        question: str = "",
        options: Optional[List[Dict[str, str]]] = None,
        request_id: Optional[str] = None,
        sender_id: Optional[str] = None,
        **kwargs,
    ):
        """Initialize agent query dialog.

        Args:
            question: Question text to display
            options: List of option dicts with 'name' and 'description'
            request_id: Request identifier
            sender_id: Sender agent ID
        """
        super().__init__(**kwargs)
        self._question = question
        self._options = options or []
        self._request_id = request_id
        self._sender_id = sender_id

    def compose(self) -> ComposeResult:
        """Create the dialog layout (compact with scrollable content)."""
        with Vertical(classes="dialog"):
            yield Label("❓ Agent 提问", classes="dialog-title")

            with ScrollableContainer(classes="dialog-content"):
                # Question text (use Static for proper auto-wrapping)
                yield Static(self._question, classes="query-question")

                # Preset options as clickable buttons with styled text
                if self._options:
                    yield Label("快捷回答:", classes="query-options-label")
                    for i, opt in enumerate(self._options):
                        name = opt.get("name", "")
                        desc = opt.get("description", "")
                        label = Text()
                        label.append(f"● {name}\n", style="bold")
                        if desc:
                            label.append(desc, style="")
                        yield Button(label, id=f"opt-{i}", classes="option-btn")

                # Custom input
                yield Label("自定义回答:", classes="query-input-label")
                yield Input(
                    placeholder="输入你的回答... (Ctrl+Enter 提交)",
                    id="query-input",
                    classes="query-input",
                )

            # Action buttons
            with Horizontal(classes="dialog-actions"):
                yield Button("取消", id="btn-cancel")
                yield Button("提交", id="btn-submit", variant="primary")

    def on_mount(self) -> None:
        """Focus input on mount."""
        self.query_one("#query-input", Input).focus()

    def on_button_pressed(self, event: Button.Pressed) -> None:
        """Handle button presses: options + submit/cancel.

        Args:
            event: Button pressed event
        """
        btn_id = event.button.id or ""

        if btn_id == "btn-submit":
            self._submit_answer()
        elif btn_id == "btn-cancel":
            self.dismiss({"action": "cancel"})
        elif btn_id.startswith("opt-"):
            # Option button clicked → fill input and submit
            try:
                idx = int(btn_id.replace("opt-", ""))
                if 0 <= idx < len(self._options):
                    selected_name = self._options[idx].get("name", "")
                    input_field = self.query_one("#query-input", Input)
                    input_field.value = selected_name
                    self._submit_answer()
            except (ValueError, IndexError):
                pass

    def on_input_submitted(self, event: Input.Submitted) -> None:
        """Handle Ctrl+Enter (or Enter in input) to submit.

        Args:
            event: Input submitted event
        """
        if event.input.id == "query-input":
            self._submit_answer()

    def _submit_answer(self):
        """Submit the current answer."""
        input_field = self.query_one("#query-input", Input)
        answer = input_field.value.strip()
        if not answer:
            return
        self.dismiss(
            {
                "action": "user_answer",
                "answer": answer,
                "request_id": self._request_id,
            }
        )
