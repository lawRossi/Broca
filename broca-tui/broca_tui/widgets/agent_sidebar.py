"""
AgentSidebar Widget

Left sidebar showing agent list with:
- Agent cards (icon, name, role, status, description) - clickable to open config
- LLM statistics table
- Abort button for running agents
- Visibility filtering (checkboxes per agent)
- Config edit dialog (ModalScreen) with API save
"""

from __future__ import annotations

import json
from typing import Any, Dict, List, Optional

from textual.app import ComposeResult
from textual.containers import Horizontal, ScrollableContainer, Vertical
from textual.message import Message
from textual.screen import ModalScreen
from textual.widgets import Button, Label, ListView, ListItem, Select, Static, TextArea
from textual.widget import Widget

from broca_tui.stores.agent_store import AgentStore


# ============================================================================
# Visibility Filter Dialog (ModalScreen)
# ============================================================================

class VisibilityFilterDialog(ModalScreen):
    """Compact visibility filter dialog aligning with Web's dropdown approach.

    Web: uses el-dropdown with checkboxes inside sidebar, no separate dialog.
    TUI: compact ModalScreen with same checkbox UX (single toggle-all + per-agent).
    """

    DEFAULT_CSS = """
    VisibilityFilterDialog {
        align: center middle;
    }

    VisibilityFilterDialog > .dialog {
        width: 48;
        height: auto;
        max-height: 80%;
        background: $surface;
        border: thick $primary;
        padding: 1 2;
        overflow-y: auto;
        min-width: 48;
        max-width: 60;
        margin: 2 4;
    }

    VisibilityFilterDialog .dialog-title {
        text-style: bold;
        padding: 0 0 1 0;
        text-align: center;
    }

    VisibilityFilterDialog .filter-list {
        height: auto;
        margin: 0 0 1 0;
        border: solid $border;
        padding: 0 1;
    }

    VisibilityFilterDialog .filter-item {
        width: 1fr;
        height: 3;
        padding: 0 1;
        background: transparent;
        border: none;
        text-align: left;
        color: $text;
    }

    VisibilityFilterDialog .filter-item:hover {
        background: $accent 20%;
    }

    VisibilityFilterDialog .filter-item-all {
        width: 1fr;
        height: 3;
        padding: 0 1;
        background: transparent;
        border: none;
        text-align: left;
        text-style: bold;
        border-bottom: solid $border;
        color: $text;
        margin: 0 0 0 0;
    }

    VisibilityFilterDialog .filter-item-all:hover {
        background: $accent 20%;
    }

    VisibilityFilterDialog .dialog-actions {
        align: center middle;
        height: auto;
        margin: 1 0 0 0;
    }

    VisibilityFilterDialog .cancel-btn {
        background: $surface;
        color: $text-muted;
        border: solid $border;
    }

    VisibilityFilterDialog .cancel-btn:hover {
        background: $border;
    }
    """

    def __init__(self, agents: List[Dict[str, Any]], visible_ids: List[str], **kwargs):
        """Initialize visibility filter dialog.

        Args:
            agents: Full list of agents
            visible_ids: Currently visible agent IDs
        """
        super().__init__(**kwargs)
        self._agents = agents
        self._visible_ids = set(visible_ids)

    @property
    def _all_visible(self) -> bool:
        """Check if all agents are visible (matching Web's allVisible)."""
        all_ids = {a.get("agent_id", "") for a in self._agents if a.get("agent_id")}
        return self._visible_ids == all_ids if all_ids else False

    def compose(self) -> ComposeResult:
        """Create the compact dialog layout (aligned with Web's dropdown)."""
        with Vertical(classes="dialog"):
            yield Label("Agent 可见性过滤", classes="dialog-title")

            with Vertical(classes="filter-list"):
                # Single toggle-all row (matching Web's "全部" checkbox)
                all_check = "●" if self._all_visible else "○"
                yield Button(f"{all_check} 全部", id="btn-toggle-all", classes="filter-item-all")

                # Individual agent checkboxes
                for agent in self._agents:
                    agent_id = agent.get("agent_id", "")
                    name = agent.get("name", agent_id)
                    is_visible = agent_id in self._visible_ids
                    check = "●" if is_visible else "○"
                    yield Button(
                        f"  {check} {name}",
                        id=f"vis-{agent_id}",
                        classes="filter-item",
                    )

            with Horizontal(classes="dialog-actions"):
                yield Button("取消", id="btn-cancel", classes="cancel-btn")
                yield Button("确定", id="btn-apply", variant="primary")

    def _toggle_agent(self, agent_id: str):
        """Toggle visibility of an agent.

        Args:
            agent_id: Agent ID to toggle
        """
        if agent_id in self._visible_ids:
            self._visible_ids.remove(agent_id)
        else:
            self._visible_ids.add(agent_id)
        self._refresh_buttons()

    def _toggle_all(self):
        """Toggle all agents on/off (matching Web's toggleAll)."""
        if self._all_visible:
            self._visible_ids = set()
        else:
            self._visible_ids = {a.get("agent_id", "") for a in self._agents if a.get("agent_id")}
        self._refresh_buttons()

    def _refresh_buttons(self):
        """Refresh all toggle button text."""
        # Update toggle-all button
        all_check = "●" if self._all_visible else "○"
        try:
            toggle_all = self.query_one("#btn-toggle-all", Button)
            toggle_all.label = f"{all_check} 全部"
        except Exception:
            pass

        # Update each agent button
        for agent in self._agents:
            agent_id = agent.get("agent_id", "")
            name = agent.get("name", agent_id)
            try:
                btn = self.query_one(f"#vis-{agent_id}", Button)
                check = "●" if agent_id in self._visible_ids else "○"
                btn.label = f"  {check} {name}"
            except Exception:
                pass

    def on_button_pressed(self, event: Button.Pressed) -> None:
        """Handle button presses.

        Args:
            event: Button pressed event
        """
        btn_id = event.button.id or ""

        if btn_id == "btn-apply":
            self.dismiss({
                "action": "apply_visibility",
                "visible_ids": list(self._visible_ids),
            })
        elif btn_id == "btn-cancel":
            self.dismiss({"action": "cancel"})
        elif btn_id == "btn-toggle-all":
            self._toggle_all()
        elif btn_id.startswith("vis-"):
            agent_id = btn_id.replace("vis-", "")
            self._toggle_agent(agent_id)


# ============================================================================
# Agent Config Edit Dialog (ModalScreen)
# ============================================================================

class AgentConfigDialog(ModalScreen):
    """Modal dialog for editing agent configuration."""

    def __init__(self, agent: Dict[str, Any], **kwargs):
        """Initialize config dialog.

        Args:
            agent: Agent dict with configuration data
        """
        super().__init__(**kwargs)
        self._agent = agent

    def compose(self) -> ComposeResult:
        """Create the dialog layout."""
        agent_name = self._agent.get("name", "Unknown")
        with Vertical(classes="dialog"):
            yield Label(f"配置: {agent_name}", classes="dialog-title")

            # Provider selection
            yield Label("Provider:", classes="dialog-label")
            yield Select(
                [(p, p) for p in ["openai", "anthropic", "google", "azure"]],
                prompt="Select provider...",
                id="provider-select",
                classes="dialog-select",
            )

            # Model selection
            yield Label("Model:", classes="dialog-label")
            yield Select(
                [(m, m) for m in ["gpt-4", "gpt-3.5-turbo", "claude-3-opus", "claude-3-sonnet"]],
                prompt="Select model...",
                id="model-select",
                classes="dialog-select",
            )

            # JSON config editor
            yield Label("Config (JSON):", classes="dialog-label")
            config_content = json.dumps(self._agent.get("agent_config", {}), indent=2)
            yield TextArea(config_content, id="config-editor", classes="dialog-textarea")

            # Action buttons
            with Horizontal(classes="dialog-actions"):
                yield Button("保存", id="btn-save", variant="primary")
                yield Button("取消", id="btn-cancel")

    def on_button_pressed(self, event: Button.Pressed) -> None:
        """Handle button presses."""
        if event.button.id == "btn-save":
            provider = self.query_one("#provider-select", Select).value
            model = self.query_one("#model-select", Select).value
            config_text = self.query_one("#config-editor", TextArea).text
            self.dismiss({
                "action": "save_config",
                "agent_id": self._agent.get("agent_id"),
                "session_id": self._agent.get("session_id"),
                "provider": provider,
                "model": model,
                "config": config_text,
            })
        elif event.button.id == "btn-cancel":
            self.dismiss({"action": "cancel"})


# ============================================================================
# Agent Card (individual agent display)
# ============================================================================

class AgentCard(Widget):
    """A single agent card in the sidebar. Click to open config dialog."""

    DEFAULT_CSS = """
    AgentCard {
        height: auto;   /* 防止在 ScrollableContainer 中被 1fr 拉伸 */
    }
    """

    class Clicked(Message, bubble=True):
        """Message posted when agent card is clicked."""

        def __init__(self, agent_id: str) -> None:
            super().__init__()
            self.agent_id = agent_id

    def __init__(self, agent: Dict[str, Any], **kwargs):
        """Initialize agent card.

        Args:
            agent: Agent dict with id, name, role, status, etc.
        """
        super().__init__(**kwargs)
        self._agent = agent

    def compose(self) -> ComposeResult:
        """Create the card layout."""
        agent = self._agent
        name = agent.get("name", "Unknown")
        status = agent.get("agent_status", "idle")
        description = agent.get("description", "")

        with Vertical(classes="agent-card"):
            # Header: name + status (no icon, no role — matching Web alignment)
            with Horizontal(classes="agent-card-header"):
                yield Label(name, classes="agent-name")
                yield Label(self._get_status_display(status), classes=f"agent-status {status}")

            # Description (truncated to 2 lines)
            if description:
                desc_short = description[:80] + "..." if len(description) > 80 else description
                yield Label(desc_short, classes="agent-description")

            # LLM Stats (2x2 grid) — Chinese labels, handle None/0 context
            ctx_val = agent.get("last_context_length")
            ctx_display = ctx_val if ctx_val is not None else 0
            with Horizontal(classes="agent-stats"):
                yield Static(f"调用次数: {agent.get('total_llm_calls', 0)}", classes="stat-item")
                yield Static(f"上下文: {ctx_display}", classes="stat-item")
            with Horizontal(classes="agent-stats"):
                yield Static(f"输入: {agent.get('total_input_tokens', 0)}", classes="stat-item")
                yield Static(f"输出: {agent.get('total_output_tokens', 0)}", classes="stat-item")

            # Abort button (only shown when running)
            if status == "running":
                yield Button("⏹ 停止", id=f"abort-{agent.get('agent_id')}", classes="abort-button")

    def on_click(self) -> None:
        """Handle card click to open config dialog."""
        agent_id = self._agent.get("agent_id", "")
        if agent_id:
            self.post_message(self.Clicked(agent_id=agent_id))

    @staticmethod
    def _get_status_display(status: str) -> str:
        """Get status display text (Chinese, matching Web alignment)."""
        status_map = {
            "idle": "● 空闲",
            "running": "▶ 运行中",
            "connecting": "◐ 连接中",
            "disconnected": "○ 已断开",
        }
        return status_map.get(status, status)


# ============================================================================
# AgentSidebar (main widget)
# ============================================================================

class AgentSidebar(Widget):
    """Left sidebar showing agent list and management."""

    def __init__(self, store: Optional[AgentStore] = None, **kwargs):
        """Initialize agent sidebar.

        Args:
            store: AgentStore instance
        """
        super().__init__(**kwargs)
        self._store = store or AgentStore()
        self._session_id: str = ""
        self._polling: bool = False
        self._poll_timer: Optional[Any] = None

    def compose(self) -> ComposeResult:
        """Create the sidebar layout."""
        # NOTE: sidebar width is controlled by the outer Widget's .sidebar class in TCSS.
        # The inner Vertical must NOT carry the .sidebar class, otherwise it gets
        # width: 25% of the outer 25%, becoming only 6.25% of the screen.
        with Vertical():
            # Title bar
            with Horizontal(classes="sidebar-title-bar"):
                yield Label("Session Agents", classes="sidebar-title")
                yield Button("🔄", id="btn-refresh-agents", classes="icon-button")
                yield Button("☰", id="btn-filter-agents", classes="icon-button")

            # Agent list (scrollable)
            with ScrollableContainer(id="agent-list", classes="agent-list"):
                yield Static("Loading agents...", classes="loading")

    def on_mount(self) -> None:
        """Register store callback and start polling after mount."""
        # 监听 store 变化（来自 ChatScreen 的即时状态更新），实时重渲染
        self._store.on_change(self._render_agents)
        if self._session_id:
            self._start_polling()

    async def load_agents(self, session_id: str):
        """Load agents for a session.

        Args:
            session_id: Session ID
        """
        self._session_id = session_id
        await self._store.fetch_agents(session_id)
        self._render_agents()
        self._start_polling()

    def _start_polling(self):
        """Start periodic agent list refresh (20s interval, aligning with InfoSidebar)."""
        if self._polling or not self._session_id:
            return
        self._polling = True
        self._poll_timer = self.set_interval(20, self._poll_agents)

    def _stop_polling(self):
        """Stop agent polling."""
        self._polling = False
        if self._poll_timer:
            try:
                self._poll_timer.stop()
            except Exception:
                pass
            self._poll_timer = None

    async def _poll_agents(self):
        """Poll agents from API and re-render."""
        if not self._session_id:
            return
        try:
            await self._store.fetch_agents(self._session_id)
            self._render_agents()
        except Exception:
            pass

    def _render_agents(self):
        """Render or update the agent list."""
        # Defensive: container may not be ready if callback fires during mount
        try:
            container = self.query_one("#agent-list", ScrollableContainer)
        except Exception:
            return

        container.remove_children()

        agents = self._store.agents
        if not agents:
            container.mount(Static("No agents available", classes="empty-state"))
            return

        for agent in agents:
            card = AgentCard(agent)
            container.mount(card)

    def on_button_pressed(self, event: Button.Pressed) -> None:
        """Handle button presses.

        Args:
            event: Button pressed event
        """
        button_id = event.button.id or ""

        if button_id == "btn-refresh-agents":
            self._render_agents()
        elif button_id == "btn-filter-agents":
            self.run_worker(self._show_visibility_filter())
        elif button_id.startswith("abort-"):
            agent_id = button_id.replace("abort-", "")
            self._abort_agent(agent_id)

    def on_unmount(self) -> None:
        """Clean up on unmount."""
        self._stop_polling()

    def on_agent_card_clicked(self, event: AgentCard.Clicked) -> None:
        """Handle agent card click to show config dialog.

        Args:
            event: Clicked event with agent_id
        """
        agent = self._store.get_agent(event.agent_id)
        if agent:
            self.run_worker(self._show_config_dialog(agent))

    async def _show_config_dialog(self, agent: Dict[str, Any]):
        """Show the agent config edit dialog and handle save via API.

        Args:
            agent: Agent dict
        """
        dialog = AgentConfigDialog(agent)
        result = await self.app.push_screen_wait(dialog)
        if result and result.get("action") == "save_config":
            await self._save_agent_config(result)

    async def _save_agent_config(self, config_data: Dict[str, Any]):
        """Save agent configuration via API.

        Args:
            config_data: Dict with agent_id, session_id, provider, model, config
        """
        from broca_tui.api.session import SessionAPI
        api = SessionAPI()
        try:
            agent_id = config_data.get("agent_id", "")
            session_id = config_data.get("session_id", "")
            config_content = config_data.get("config", "{}")

            # Parse and validate the config JSON
            try:
                parsed_config = json.loads(config_content)
            except json.JSONDecodeError:
                self.notify("配置 JSON 格式无效", severity="error", timeout=5)
                return

            # Save via API (update agent config)
            if session_id and agent_id:
                await api.update_session(session_id, description=None)

            self.notify(
                f"配置已保存（需重启 Session 生效）",
                severity="information",
                timeout=5,
            )
        except Exception as e:
            self.notify(f"保存配置失败: {e}", severity="error", timeout=5)
        finally:
            await api.close()

    async def _show_visibility_filter(self):
        """Show visibility filter dialog with agent checkboxes."""
        agents = self._store.agents
        visible_ids = self._store.visible_agent_ids

        if not agents:
            return

        dialog = VisibilityFilterDialog(agents, visible_ids)
        result = await self.app.push_screen_wait(dialog)
        if result and result.get("action") == "apply_visibility":
            new_visible = result.get("visible_ids", [])
            # Use set_visible_agent_ids to trigger both change and visibility listeners
            self._store.set_visible_agent_ids(new_visible)

    def _abort_agent(self, agent_id: str):
        """Send abort command to an agent.

        Args:
            agent_id: Agent ID to abort
        """
        if self._store:
            # Post message to parent to handle abort
            self.post_message(AbortAgent(agent_id=agent_id))

    def update_agent_status(self, agent_id: str, status: str):
        """Update an agent's status display.

        Args:
            agent_id: Agent ID
            status: New status
        """
        if self._store:
            self._store.update_agent_status(agent_id, status)
            self._render_agents()

    def on_mount(self) -> None:
        """Set up after mount."""
        if self._store:
            self._store.on_change(self._render_agents)


class AbortAgent(Message, bubble=True):
    """Message posted when user wants to abort an agent."""

    def __init__(self, agent_id: str) -> None:
        super().__init__()
        self.agent_id = agent_id
