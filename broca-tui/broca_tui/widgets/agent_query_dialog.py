"""
AgentQueryDialog (ModalScreen)

Handles agent queries/questions to the user:
- Displays question text with ❓ icon
- Preset option cards (clickable)
- Custom input box (Ctrl+Enter to submit)
- Cancel / Submit buttons
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional

from textual.app import ComposeResult
from textual.containers import Horizontal, Vertical, ScrollableContainer
from textual.screen import ModalScreen
from textual.widgets import Button, Input, Label, Static


class AgentQueryDialog(ModalScreen):
    """Modal dialog for agent queries."""

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
        """Create the dialog layout."""
        with Vertical(classes="dialog query-dialog"):
            yield Label("❓ Agent 提问", classes="dialog-title")

            with ScrollableContainer(classes="dialog-content"):
                # Question text
                yield Label(self._question, classes="query-question")

                # Preset options as clickable cards
                if self._options:
                    yield Label("快捷回答:", classes="query-options-label")
                    for i, opt in enumerate(self._options):
                        name = opt.get("name", "")
                        desc = opt.get("description", "")
                        with Vertical(classes="option-card", id=f"option-{i}"):
                            yield Label(name, classes="option-name")
                            if desc:
                                yield Label(desc, classes="option-desc")

                # Custom input
                yield Label("自定义回答:", classes="query-input-label")
                yield Input(
                    placeholder="输入你的回答... (Ctrl+Enter 提交)",
                    id="query-input",
                    classes="query-input",
                )

            # Action buttons
            with Horizontal(classes="dialog-actions"):
                yield Button("✅ 提交", id="btn-submit", variant="primary")
                yield Button("❌ 取消", id="btn-cancel", variant="error")

    def on_mount(self) -> None:
        """Focus input on mount."""
        self.query_one("#query-input", Input).focus()

    def on_button_pressed(self, event: Button.Pressed) -> None:
        """Handle button presses.

        Args:
            event: Button pressed event
        """
        if event.button.id == "btn-submit":
            self._submit_answer()
        elif event.button.id == "btn-cancel":
            self.dismiss({"action": "cancel"})

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
            # Don't submit empty answers
            return

        self.dismiss({
            "action": "user_answer",
            "answer": answer,
            "request_id": self._request_id,
        })

    def on_static_click(self, event: Static.Click) -> None:
        """Handle clicking on option cards.

        Walks up the widget tree to find the option-card container,
        since the click may be captured by a child Label.

        Args:
            event: Click event
        """
        # Walk up the widget tree to find option-card
        widget = event.widget
        while widget is not None:
            if hasattr(widget, "id") and widget.id and widget.id.startswith("option-"):
                idx = int(widget.id.replace("option-", ""))
                if 0 <= idx < len(self._options):
                    selected_name = self._options[idx].get("name", "")
                    input_field = self.query_one("#query-input", Input)
                    input_field.value = selected_name
                    self._submit_answer()
                    return
            widget = widget.parent
