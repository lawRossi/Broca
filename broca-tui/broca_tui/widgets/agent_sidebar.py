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
from textual.widget import Widget
from textual.widgets import Button, Label, Select, Static, TextArea

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
        # Map sanitized IDs back to original agent IDs for button lookup
        self._safe_to_agent: Dict[str, str] = {}

    @staticmethod
    def _sanitize_id(raw: str) -> str:
        """Sanitize a string for use as a Textual widget ID.

        Textual IDs must contain only letters, numbers, underscores, or hyphens.

        Args:
            raw: Raw string to sanitize

        Returns:
            Sanitized ID string
        """
        import re

        return re.sub(r"[^a-zA-Z0-9_-]", "-", raw)

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
                yield Button(
                    f"{all_check} 全部", id="btn-toggle-all", classes="filter-item-all"
                )

                # Individual agent checkboxes — use sanitized IDs
                for agent in self._agents:
                    agent_id = agent.get("agent_id", "")
                    name = agent.get("name", agent_id)
                    safe_id = self._sanitize_id(agent_id)
                    self._safe_to_agent[safe_id] = agent_id
                    is_visible = agent_id in self._visible_ids
                    check = "●" if is_visible else "○"
                    yield Button(
                        f"  {check} {name}",
                        id=f"vis-{safe_id}",
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
            self._visible_ids = {
                a.get("agent_id", "") for a in self._agents if a.get("agent_id")
            }
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

        # Update each agent button — query by sanitized ID
        for agent in self._agents:
            agent_id = agent.get("agent_id", "")
            name = agent.get("name", agent_id)
            safe_id = self._sanitize_id(agent_id)
            try:
                btn = self.query_one(f"#vis-{safe_id}", Button)
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
            self.dismiss(
                {
                    "action": "apply_visibility",
                    "visible_ids": list(self._visible_ids),
                }
            )
        elif btn_id == "btn-cancel":
            self.dismiss({"action": "cancel"})
        elif btn_id == "btn-toggle-all":
            self._toggle_all()
        elif btn_id.startswith("vis-"):
            safe_id = btn_id.replace("vis-", "")
            agent_id = self._safe_to_agent.get(safe_id, safe_id)
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

            # Provider + Model 同一行（不要 label，下拉已有提示文字）
            with Horizontal(classes="dialog-select-row", id="provider-model-row"):
                yield Select(
                    [(p, p) for p in ["openai", "anthropic", "google", "azure"]],
                    prompt="Select provider...",
                    id="provider-select",
                    classes="dialog-select",
                )
                yield Select(
                    [
                        (m, m)
                        for m in [
                            "gpt-4",
                            "gpt-3.5-turbo",
                            "claude-3-opus",
                            "claude-3-sonnet",
                        ]
                    ],
                    prompt="Select model...",
                    id="model-select",
                    classes="dialog-select",
                )

            # JSON config editor（撑满剩余空间）
            yield Label("Config (JSON):", classes="dialog-label")
            config_content = json.dumps(self._agent.get("agent_config", {}), indent=2)
            yield TextArea(
                config_content, id="config-editor", classes="dialog-textarea"
            )

            # 底部按钮区（靠下，按钮紧凑）
            with Horizontal(classes="dialog-actions dialog-actions-config"):
                yield Button("保存", id="btn-save", variant="primary")
                yield Button("取消", id="btn-cancel", classes="cancel-btn")

    def on_button_pressed(self, event: Button.Pressed) -> None:
        """Handle button presses."""
        if event.button.id == "btn-save":
            provider = self.query_one("#provider-select", Select).value
            model = self.query_one("#model-select", Select).value
            config_text = self.query_one("#config-editor", TextArea).text
            self.dismiss(
                {
                    "action": "save_config",
                    "agent_id": self._agent.get("agent_id"),
                    "session_id": self._agent.get("session_id"),
                    "provider": provider,
                    "model": model,
                    "config": config_text,
                }
            )
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
    AgentCard .abort-button {
        display: none;  /* 默认隐藏，由 _update_status_display 切换 */
    }
    AgentCard .abort-button.visible {
        display: block;
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

    @staticmethod
    def _sanitize_id(raw: str) -> str:
        """Sanitize a string for use as a Textual widget ID.

        Textual IDs must contain only letters, numbers, underscores, or hyphens.

        Args:
            raw: Raw string to sanitize

        Returns:
            Sanitized ID string
        """
        import re

        return re.sub(r"[^a-zA-Z0-9_-]", "-", raw)

    def compose(self) -> ComposeResult:
        """Create the card layout."""
        agent = self._agent
        name = agent.get("name", "Unknown")
        status = agent.get("agent_status", "idle")
        description = agent.get("description", "")
        agent_id = agent.get("agent_id", "")
        safe_id = self._sanitize_id(agent_id)

        with Vertical(classes="agent-card"):
            # Header: name + status (no icon, no role — matching Web alignment)
            with Horizontal(classes="agent-card-header"):
                yield Label(name, classes="agent-name")
                yield Label(
                    self._get_status_display(status), classes=f"agent-status {status}"
                )

            # Description (truncated to 2 lines)
            if description:
                desc_short = (
                    description[:80] + "..." if len(description) > 80 else description
                )
                yield Label(desc_short, classes="agent-description")

            # LLM Stats (2x2 网格) — 标签在上，数字在下，对齐 Web 版
            ctx_val = agent.get("last_context_length")
            ctx_display = ctx_val if ctx_val is not None else 0
            with Horizontal(classes="agent-stats"):
                with Vertical(classes="stat-block"):
                    yield Static("调用次数", classes="stat-label")
                    yield Static(
                        str(agent.get("total_llm_calls", 0)),
                        classes="stat-value",
                        id=f"stat-calls-{safe_id}",
                    )
                with Vertical(classes="stat-block"):
                    yield Static("上下文", classes="stat-label")
                    yield Static(
                        str(ctx_display),
                        classes="stat-value",
                        id=f"stat-ctx-{safe_id}",
                    )
            with Horizontal(classes="agent-stats"):
                with Vertical(classes="stat-block"):
                    yield Static("输入", classes="stat-label")
                    yield Static(
                        str(agent.get("total_input_tokens", 0)),
                        classes="stat-value",
                        id=f"stat-input-{safe_id}",
                    )
                with Vertical(classes="stat-block"):
                    yield Static("输出", classes="stat-label")
                    yield Static(
                        str(agent.get("total_output_tokens", 0)),
                        classes="stat-value",
                        id=f"stat-output-{safe_id}",
                    )

            # Abort button (始终创建，通过 CSS 显隐)
            yield Button("停止", id=f"abort-{safe_id}", classes="abort-button")

    def on_button_pressed(self, event: Button.Pressed) -> None:
        """Handle abort button press — directly calls screen."""
        button_id = event.button.id or ""
        if button_id.startswith("abort-"):
            event.stop()
            agent_id = self._agent.get("agent_id", "")
            if (
                agent_id
                and hasattr(self, "screen")
                and hasattr(self.screen, "_abort_agent")
            ):
                self.screen._abort_agent(agent_id)

    def on_click(self) -> None:
        """Handle card click (not from button) to open config dialog."""
        agent_id = self._agent.get("agent_id", "")
        if agent_id:
            self.post_message(self.Clicked(agent_id=agent_id))

    def _update_status_display(self):
        """Update status dot color, label text, and statistics in-place (no DOM rebuild).

        Also mounts/removes the abort button based on current status.
        """
        status = self._agent.get("agent_status", "idle") or "idle"
        agent_id = self._agent.get("agent_id", "")

        try:
            label = self.query_one(".agent-status", Label)
            label.update(self._get_status_display(status))
            label.classes = f"agent-status {status}"
        except Exception:
            return

        # Toggle abort button visibility via CSS class (按钮始终在 compose 中)
        abort_id = f"abort-{agent_id}"
        try:
            btn = self.query_one(f"#{abort_id}", Button)
            btn.set_class(status == "running", "visible")
        except Exception:
            pass

        # ── 同步更新统计数字（轮询时 agent 数据已更新，但 Static 不会自动刷新）──
        # 使用 compose 中定义的 id 精确定位每个 stat-value
        stat_ids = {
            "total_llm_calls": f"stat-calls-{agent_id}",
            "last_context_length": f"stat-ctx-{agent_id}",
            "total_input_tokens": f"stat-input-{agent_id}",
            "total_output_tokens": f"stat-output-{agent_id}",
        }
        try:
            for key, widget_id in stat_ids.items():
                widget = self.query_one(f"#{widget_id}", Static)
                if key == "last_context_length":
                    ctx_val = self._agent.get("last_context_length")
                    widget.update(str(ctx_val if ctx_val is not None else 0))
                else:
                    widget.update(str(self._agent.get(key, 0)))
        except Exception:
            pass

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
            # Title bar（只保留筛选按钮）
            with Horizontal(classes="sidebar-title-bar"):
                yield Label("Session Agents", classes="sidebar-title")
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
        """Start periodic agent list refresh (10s interval)."""
        if self._polling or not self._session_id:
            return
        self._polling = True
        self._poll_timer = self.set_interval(10, self._poll_agents)

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
        """Render or update the agent list.

        Only rebuilds the DOM for structural changes (agent added/removed).
        For status-only changes, updates the existing AgentCards in-place.
        """
        try:
            container = self.query_one("#agent-list", ScrollableContainer)
        except Exception:
            return

        agents = self._store.agents
        # main_agent 排第一
        main_id = self._store.current_agent_id
        if main_id:
            agents = sorted(agents, key=lambda a: a.get("agent_id") != main_id)
        existing_cards = list(container.children)

        # If card count matches, update in-place (avoid flickering)
        if len(existing_cards) == len(agents) and all(
            isinstance(c, AgentCard) for c in existing_cards
        ):
            for card, agent in zip(existing_cards, agents):
                card._agent = agent  # Update the underlying data
                card._update_status_display()
            return

        # Structural change: full rebuild
        container.remove_children()

        if not agents:
            container.mount(Static("No agents available", classes="empty-state"))
            return

        for agent in agents:
            card = AgentCard(agent)
            container.mount(card)

    def on_button_pressed(self, event: Button.Pressed) -> None:
        """Handle button presses (non-abort buttons only; abort is handled by AgentCard)."""
        button_id = event.button.id or ""

        if button_id == "btn-filter-agents":
            self.run_worker(self._show_visibility_filter())

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
        # 优先用本地 store 中已保存的配置（_save_agent_config 更新后的数据），
        # 没有时才从 API 拉取（首次打开）。
        agent_config = agent.get("agent_config")
        if agent_config is None:
            from broca_tui.api.session import SessionAPI

            api = SessionAPI()
            try:
                config_data = await api.get_agent_config(
                    self._session_id, agent.get("agent_id", "")
                )
                agent_config = config_data.get("config_content", {})
            except Exception:
                agent_config = {}
            finally:
                await api.close()

        agent_with_config = {**agent, "agent_config": agent_config}
        dialog = AgentConfigDialog(agent_with_config)
        result = await self.app.push_screen_wait(dialog)
        if result and result.get("action") == "save_config":
            await self._save_agent_config(result)

    async def _save_agent_config(self, config_data: Dict[str, Any]):
        """保存 agent 配置到后端 API，同时更新本地 store。

        Args:
            config_data: Dict with agent_id, session_id, provider, model, config
        """
        from broca_tui.api.session import SessionAPI

        api = SessionAPI()
        try:
            agent_id = config_data.get("agent_id", "")
            session_id = config_data.get("session_id", "") or self._session_id
            provider = config_data.get("provider", "")
            model = config_data.get("model", "")
            config_content = config_data.get("config", "{}")

            # Parse and validate the config JSON
            try:
                parsed_config = json.loads(config_content)
            except json.JSONDecodeError:
                self.notify(
                    "配置JSON格式无效", severity="error", timeout=5, markup=False
                )
                return

            # 对齐 Web 版：后端只接收 { config_content: {完整配置对象} }
            # provider / model 等字段包含在 config_content 内部
            full_config = {
                "provider": provider,
                "model": model,
                **(parsed_config if isinstance(parsed_config, dict) else {}),
            }
            await api.update_agent_config(
                session_id,
                agent_id,
                {
                    "config_content": full_config,
                },
            )

            # 同步更新本地 store
            agent = self._store.get_agent(agent_id)
            if agent:
                agent["provider"] = provider
                agent["model"] = model
                agent["agent_config"] = parsed_config
                self._store._notify_change()

            self.notify(
                "配置已保存，重启Session后生效",
                severity="information",
                timeout=5,
                markup=False,
            )
        except Exception as e:
            self.notify(f"保存配置失败: {e}", severity="error", timeout=5, markup=False)
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
