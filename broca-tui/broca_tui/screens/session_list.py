"""
SessionListScreen — Default home screen.

Features:
- Session cards with name, category tag, timestamps
- Create/delete sessions
- Search by keyword
- Navigation by category (normal → Chat, agent-orchestration → Crew)
- Ctrl+N create, Ctrl+F search
"""

from __future__ import annotations

import os
from datetime import datetime, timezone, timedelta
from typing import Any, Dict, Optional

from textual.app import ComposeResult
from textual.containers import Horizontal, ScrollableContainer, Vertical
from textual import events
from textual.screen import ModalScreen, Screen
from textual.widget import Widget
from textual.widgets import Button, Input, Label, Select, Static

from broca_tui.api.session import SessionAPI
from broca_tui.stores.session_store import SessionStore

# ============================================================================
# Create Session Dialog
# ============================================================================


class CreateSessionDialog(ModalScreen):
    """Modal dialog for creating a new session.

    Supports:
    - Optional session name
    - Workspace defaulting to current working directory
    - Session type selection (normal / agent-orchestration)
    - Optional LLM provider and model selection
    """

    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self._api = SessionAPI()
        self._selected_type = "normal"

    def compose(self) -> ComposeResult:
        """Create the dialog layout."""
        with Vertical(classes="dialog"):
            yield Label("创建新会话", classes="dialog-title")

            yield Label("名称:", classes="dialog-label")
            yield Input(
                placeholder="会话名称（可选）", id="input-name", classes="dialog-input"
            )

            yield Label("Workspace:", classes="dialog-label")
            yield Input(
                placeholder="工作空间路径",
                value=os.getcwd(),
                id="input-workspace",
                classes="dialog-input",
            )

            yield Label("类型:", classes="dialog-label")
            with Horizontal(classes="dialog-type-row"):
                yield Button(
                    "📝 普通会话", id="btn-type-normal", classes="dialog-input selected"
                )
                yield Button(
                    "🤖 Agent 编排", id="btn-type-orch", classes="dialog-input"
                )

            yield Label("LLM 配置（可选，不选则使用默认）", classes="dialog-label")
            with Horizontal(classes="dialog-select-row"):
                yield Select(
                    [("加载中...", "")],
                    id="input-provider",
                    prompt="选择提供商...",
                    classes="dialog-select",
                )
                yield Select(
                    [],
                    id="input-model",
                    prompt="选择模型...",
                    disabled=True,
                    classes="dialog-select",
                )

            with Horizontal(classes="dialog-actions"):
                yield Button("取消", id="btn-cancel", classes="cancel-btn")
                yield Button("创建", id="btn-create", variant="primary")

    async def on_mount(self) -> None:
        """Fetch available LLM providers on mount."""
        try:
            providers = await self._api.get_llm_providers()
            options: list[tuple[str, str | None]] = [("默认", "")]
            for p in providers:
                label = p.get("name", p["id"])
                options.append((label, p["id"]))
            provider_select = self.query_one("#input-provider", Select)
            provider_select.set_options(options)
        except Exception:
            # If can't fetch providers, keep the prompt placeholder
            self.notify("无法加载 LLM 提供商列表", severity="warning", timeout=3)

    async def on_select_changed(self, event: Select.Changed) -> None:
        """Handle Select changes — provider selection triggers model loading."""
        if event.select.id == "input-provider":
            provider = event.value
            await self._on_provider_selected(provider)

    async def _on_provider_selected(self, provider: str | None) -> None:
        """Fetch models when a provider is selected.

        Args:
            provider: The selected provider ID, or empty string for default.
        """
        model_select = self.query_one("#input-model", Select)

        if not provider:
            # "默认" selected — disable model select
            model_select.disabled = True
            model_select.set_options([])
            return

        # Fetch models for the selected provider
        try:
            model_select.disabled = True
            model_select.set_options([("加载中...", "")])
            models = await self._api.get_llm_models(provider)

            options: list[tuple[str, str | None]] = [("默认", "")]
            for m in models:
                label = m.get("name", m["id"])
                options.append((label, m["id"]))
            model_select.set_options(options)
            model_select.disabled = False
        except Exception:
            model_select.set_options([("无法加载模型", "")])
            model_select.disabled = True
            self.notify(
                f"无法加载 {provider} 的模型列表", severity="warning", timeout=3
            )

    def on_button_pressed(self, event: Button.Pressed) -> None:
        """Handle button presses."""
        btn_id = event.button.id or ""
        if btn_id == "btn-type-normal":
            self._selected_type = "normal"
            self.query_one("#btn-type-normal", Button).classes = "dialog-input selected"
            self.query_one("#btn-type-orch", Button).classes = "dialog-input"
        elif btn_id == "btn-type-orch":
            self._selected_type = "agent-orchestration"
            self.query_one("#btn-type-orch", Button).classes = "dialog-input selected"
            self.query_one("#btn-type-normal", Button).classes = "dialog-input"
        elif btn_id == "btn-create":
            self._do_create()
        elif btn_id == "btn-cancel":
            self.dismiss({"action": "cancel"})

    def _do_create(self) -> None:
        """Collect form values and dismiss with result."""
        name = self.query_one("#input-name", Input).value.strip()
        workspace = self.query_one("#input-workspace", Input).value.strip()
        provider_select = self.query_one("#input-provider", Select)
        model_select = self.query_one("#input-model", Select)

        # provider/model: 必须显式判断 Select.BLANK，因为 bool(Select.BLANK) 是 True
        # 空字符串 "" 表示 "使用默认"，Select.BLANK 表示用户未做选择 → 都视为 None
        provider = (
            None
            if provider_select.value is Select.BLANK or not provider_select.value
            else provider_select.value
        )
        model = (
            None
            if model_select.value is Select.BLANK or not model_select.value
            else model_select.value
        )

        self.dismiss(
            {
                "action": "create",
                "description": name or None,
                "workspace": workspace or None,
                "category": self._selected_type,
                "provider": provider,
                "model": model,
            }
        )


# ============================================================================
# Delete Confirm Dialog
# ============================================================================


class DeleteConfirmDialog(ModalScreen):
    """Confirm dialog for deleting a session."""

    def __init__(self, session_name: str, **kwargs):
        super().__init__(**kwargs)
        self._session_name = session_name

    def compose(self) -> ComposeResult:
        with Vertical(classes="dialog dialog-delete"):
            yield Label("⚠️ 确认删除", classes="dialog-title")
            yield Label(
                "确定要删除该会话吗？此操作不可撤销。", classes="dialog-content"
            )
            with Horizontal(classes="dialog-actions dialog-actions-delete"):
                yield Button("取消", id="btn-cancel", classes="cancel-btn")
                yield Button("删除", id="btn-confirm", classes="delete-btn")

    def on_button_pressed(self, event: Button.Pressed) -> None:
        """Handle button presses — dismiss with action result."""
        btn_id = event.button.id or ""
        if btn_id == "btn-confirm":
            self.dismiss({"action": "confirm"})
        elif btn_id == "btn-cancel":
            self.dismiss({"action": "cancel"})


# ============================================================================
# SessionListScreen
# ============================================================================


class SessionListScreen(Screen):
    """Default home screen for session management."""

    BINDINGS = [
        ("ctrl+n", "create_session", "新会话"),
        ("ctrl+f", "focus_search", "搜索"),
    ]

    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self._store = SessionStore()
        self._api = SessionAPI()

    async def _cleanup(self) -> None:
        """Clean up API client when screen is closed."""
        await self._api.close()

    def compose(self) -> ComposeResult:
        """Create the screen layout."""
        with Vertical(classes="session-list-screen"):
            # Top bar
            with Horizontal(classes="session-list-header"):
                yield Label("会话管理", classes="screen-title")
                yield Static("", classes="header-spacer")
                yield Label("", id="session-count", classes="session-count")
                yield Button(
                    "＋ 新会话",
                    id="btn-create-session",
                    variant="primary",
                    classes="create-btn",
                )

            # Search bar
            yield Input(
                placeholder="搜索会话... (Ctrl+F 聚焦)",
                id="search-input",
                classes="search-bar",
            )

            # Session cards list
            with ScrollableContainer(id="session-list", classes="session-list"):
                yield Static("加载中...", classes="loading")

    def on_mount(self) -> None:
        """Load sessions on mount and start scroll detection."""
        self.run_worker(self._load_sessions())
        self.set_interval(1 / 3, self._check_scroll_bottom)

    async def _load_sessions(self, keyword: Optional[str] = None):
        """Load sessions from store."""
        await self._store.load_sessions(keyword=keyword)

        if self._store.last_error:
            container = self.query_one("#session-list", ScrollableContainer)
            count_label = self.query_one("#session-count", Label)
            await container.remove_children()
            count_label.update("⚠️ 连接失败")
            # Strip operation prefix like "加载会话列表失败: " for cleaner display
            error_detail = self._store.last_error.split(": ", 1)[-1]
            container.mount(
                Static(
                    "无法连接到后端服务，请确保 API 服务器正在运行。\n"
                    f"错误: {error_detail}",
                    classes="empty-state error-state",
                )
            )
            self._store.last_error = None
            return

        await self._render_sessions()

    async def _render_sessions(self):
        """Render session cards. Must be async because remove_children() returns an AwaitRemove."""
        container = self.query_one("#session-list", ScrollableContainer)
        count_label = self.query_one("#session-count", Label)
        await container.remove_children()

        sessions = self._store.sessions
        count_label.update(f"共 {self._store.total} 个会话")

        if not sessions:
            container.mount(
                Static("暂无会话，点击「＋ 新会话」创建", classes="empty-state")
            )
            return

        for session in sessions:
            card = self._create_session_card(session)
            container.mount(card)

    def _check_scroll_bottom(self) -> None:
        """Check if user scrolled near bottom and load more if needed."""
        try:
            container = self.query_one("#session-list", ScrollableContainer)
            if not self._store.has_more or self._store.loading:
                return
            # Load more when within one viewport height of the bottom
            if container.max_scroll_y > 0:
                distance_from_bottom = container.max_scroll_y - container.scroll_y
                if distance_from_bottom <= container.container_size.height:
                    self.run_worker(
                        self._load_more_sessions(),
                        group="session-load-more",
                        exclusive=True,
                    )
        except Exception:
            pass  # Container not ready yet

    async def _load_more_sessions(self) -> None:
        """Load next page of sessions and append new cards to the list."""
        old_count = len(self._store.sessions)
        await self._store.load_more()
        if self._store.last_error:
            self._store.last_error = None
            return

        # Only mount new cards (don't re-render everything)
        new_sessions = self._store.sessions[old_count:]
        if not new_sessions:
            return

        container = self.query_one("#session-list", ScrollableContainer)
        for session in new_sessions:
            card = self._create_session_card(session)
            container.mount(card)

        # Update session count
        count_label = self.query_one("#session-count", Label)
        count_label.update(f"共 {self._store.total} 个会话")

    def _create_session_card(self, session: Dict[str, Any]) -> Vertical:
        """Create a session card with all child widgets.

        Uses widget constructor with positional children arguments instead of
        mount(), since mount() requires the parent to already be in the DOM.

        Args:
            session: Session dict

        Returns:
            Vertical container with card content
        """
        session_id = session.get("session_id", "")
        description = session.get("description") or session_id[:16]
        category = session.get("category", "normal")
        created_at_raw = session.get("created_at", "") or ""
        # 后端存储 UTC 时间，转为北京时间 (UTC+8) 并显示到分钟
        try:
            utc_dt = datetime.fromisoformat(created_at_raw.replace("Z", "+00:00"))
            if utc_dt.tzinfo is None:
                utc_dt = utc_dt.replace(tzinfo=timezone.utc)
            beijing_dt = utc_dt.astimezone(timezone(timedelta(hours=8)))
            created_at = beijing_dt.strftime("%Y-%m-%d %H:%M")
        except (ValueError, AttributeError):
            created_at = created_at_raw[:16]
        workspace = session.get("workspace", "")

        category_label = "" if category == "normal" else "📝 编排"
        category_class = "category-normal" if category == "normal" else "category-orch"

        # Runner status
        runner_status = session.get("runner_status", "none") or "none"
        status_map = {
            "alive": "● 运行中",
            "starting": "◐ 启动中",
            "error": "⚠ 进程异常",
            "dead": "● 已停止",
            "none": "○ 未运行",
        }
        status_text = status_map.get(runner_status, runner_status)

        # Build meta labels list
        meta_labels = [
            Label(f"ID: {session_id[:12]}...", classes="session-meta"),
        ]
        if workspace:
            meta_labels.append(Label(f"📁 {workspace[:20]}...", classes="session-meta"))
        meta_labels.append(Label(f"🕐 {created_at}", classes="session-meta"))

        # Runner toggle button
        is_alive = runner_status == "alive"
        toggle_btn = Button(
            "停止" if is_alive else "启动",
            id=f"runner-{session_id}",
            classes=f"runner-toggle-btn {'stop' if is_alive else 'start'}",
        )

        # Build card using constructor positional args (avoids mount() before DOM)
        card = Vertical(
            Horizontal(
                Label(description[:40], classes="session-name"),
                Label("✏️", classes="edit-hint"),
                Static("", classes="header-spacer"),
                Label(category_label, classes=f"session-category {category_class}"),
                Label(status_text, classes=f"runner-status {runner_status}"),
                classes="session-card-header",
            ),
            Horizontal(
                *meta_labels,
                toggle_btn,
                Button(
                    "删除", id=f"delete-{session_id}", classes="action-btn del-btn"
                ),
                classes="session-card-actions",
            ),
            classes="session-card",
            id=f"session-{session_id}",
        )
        return card

    def _find_session_id(self, widget: Widget) -> str | None:
        """Walk up the widget tree to find the session card ID.

        Args:
            widget: The clicked widget

        Returns:
            Session ID or None
        """
        parent = widget.parent
        while parent is not None:
            if hasattr(parent, "id") and parent.id and parent.id.startswith("session-"):
                return parent.id.replace("session-", "")
            parent = parent.parent
        return None

    def _start_inline_edit(self, session_id: str) -> None:
        """Replace session name label with an Input for inline editing.

        Finds the session-name label in the session card automatically.

        Args:
            session_id: Session ID
        """
        session = self._store.get_session(session_id)
        current_text = session.get("description", "") or session_id[:16]

        # Find the session-name label in the card
        card = self.query_one(f"#session-{session_id}", Vertical)
        name_label = card.query_one(".session-name", Label)
        edit_input = Input(
            value=str(current_text),
            id=f"edit-name-{session_id}",
            classes="edit-name-input",
        )
        parent = name_label.parent
        if parent:
            # 也移除编辑图标
            for child in list(parent.children):
                if child.has_class("edit-hint"):
                    child.remove()
            name_label.remove()
            parent.mount(edit_input, before=0)
            self.set_timer(0.05, lambda: edit_input.focus())

    def on_key(self, event: events.Key) -> None:
        """Handle Escape key to cancel inline editing.

        Args:
            event: Key event
        """
        if event.key == "escape":
            focused = self.focused
            if focused and isinstance(focused, Input) and focused.id and focused.id.startswith("edit-name-"):
                # Cancel: just re-render without saving
                event.stop()
                self.run_worker(self._render_sessions())

    def on_input_submitted(self, event: Input.Submitted) -> None:
        """Handle input submission — save inline-edited description on Enter.

        Args:
            event: Input submitted event
        """
        input_id = event.input.id or ""
        if input_id.startswith("edit-name-"):
            session_id = input_id.replace("edit-name-", "")
            new_desc = event.value.strip()
            self.run_worker(self._save_description(session_id, new_desc, event.input))

    def on_input_blurred(self, event: Input.Blurred) -> None:
        """Handle input blur — save and revert inline edit input on focus loss.

        Args:
            event: Input blurred event
        """
        input_id = event.input.id or ""
        if input_id.startswith("edit-name-"):
            session_id = input_id.replace("edit-name-", "")
            new_desc = event.value.strip()
            self.run_worker(self._save_description(session_id, new_desc, event.input))

    async def _save_description(self, session_id: str, description: str, edit_input: Input) -> None:
        """Save updated description via API and refresh the card.

        Args:
            session_id: Session ID
            description: New description text
            edit_input: The Input widget to replace back
        """
        session = self._store.get_session(session_id)
        old_desc = session.get("description", "") or session_id[:16]
        if description == old_desc:
            await self._render_sessions()
            return

        try:
            await self._api.update_session(session_id, description=description)
            await self._store.refresh()
            self.notify("描述已更新", severity="information", timeout=2)
        except Exception as e:
            self.notify(f"保存失败: {e}", severity="error", timeout=5)
        finally:
            await self._render_sessions()

    def on_click(self, event: events.Click) -> None:
        """Handle session card click — click card to enter, skip buttons.

        Args:
            event: Click event
        """
        # 如果点击的是按钮，不触发导航（按钮有自己的处理）
        if isinstance(event.widget, Button):
            return

        # 如果是输入框或编辑图标，不触发导航
        if isinstance(event.widget, Input):
            return

        # 点击 session-name 或 edit-hint 启动内联编辑
        if event.widget.has_class("session-name") or event.widget.has_class("edit-hint"):
            session_id = self._find_session_id(event.widget)
            if session_id:
                self._start_inline_edit(session_id)
            return

        # Walk up to find session card
        widget = event.widget
        while widget is not None:
            if hasattr(widget, "id") and widget.id and widget.id.startswith("session-"):
                session_id = widget.id.replace("session-", "")
                session = self._store.get_session(session_id)
                if session:
                    category = session.get("category", "normal")
                    self._navigate_to_session(session_id, category)
                return
            widget = widget.parent if hasattr(widget, "parent") else None

    def _navigate_to_session(self, session_id: str, category: str):
        """Navigate to the appropriate screen based on category.

        Args:
            session_id: Session ID
            category: 'normal' or 'agent-orchestration'
        """
        from broca_tui.screens.chat import ChatScreen
        from broca_tui.screens.crew_executions import CrewExecutionsScreen

        if category == "agent-orchestration":
            screen = CrewExecutionsScreen(session_id=session_id)
        else:
            screen = ChatScreen(session_id=session_id)
        self.app.push_screen(screen)

    def on_input_changed(self, event: Input.Changed) -> None:
        """Handle search input changes.

        Args:
            event: Input changed event
        """
        if event.input.id == "search-input":
            keyword = event.value.strip()
            # Exclusive group ensures previous search worker is cancelled
            # before starting a new one, preventing concurrent renders that
            # cause duplicate widget IDs.
            self.run_worker(
                self._load_sessions(keyword=keyword or None),
                group="session-search",
                exclusive=True,
            )

    def on_button_pressed(self, event: Button.Pressed) -> None:
        """Handle button presses.

        Args:
            event: Button pressed event
        """
        btn_id = event.button.id or ""

        if btn_id == "btn-create-session":
            self.run_worker(self.action_create_session())
        elif btn_id.startswith("delete-"):
            session_id = btn_id.replace("delete-", "")
            self.run_worker(self._confirm_delete(session_id))
        elif btn_id.startswith("runner-"):
            session_id = btn_id.replace("runner-", "")
            self.run_worker(self._toggle_runner(session_id))

    async def action_create_session(self) -> None:
        """Show create session dialog."""
        dialog = CreateSessionDialog()
        result = await self.app.push_screen_wait(dialog)
        if result and result.get("action") == "create":
            created = await self._store.create_session(
                description=result.get("description"),
                workspace=result.get("workspace"),
                category=result.get("category"),
                provider=result.get("provider"),
                model=result.get("model"),
            )
            if created:
                await self._render_sessions()
            else:
                error_msg = self._store.last_error or "创建会话失败"
                self._store.last_error = None
                self.notify(error_msg, severity="error", timeout=8)

    async def _confirm_delete(self, session_id: str) -> None:
        """Show delete confirmation dialog.

        Args:
            session_id: Session ID to delete
        """
        session = self._store.get_session(session_id)
        name = session.get("description", session_id[:16]) if session else session_id
        dialog = DeleteConfirmDialog(name)
        result = await self.app.push_screen_wait(dialog)
        if result and result.get("action") == "confirm":
            # Show loading state
            try:
                del_btn = self.query_one(f"#delete-{session_id}", Button)
                del_btn.disabled = True
                del_btn.label = "⏳ 删除中"
            except Exception:
                pass

            deleted = await self._store.delete_session(session_id)
            if deleted:
                await self._render_sessions()
            else:
                error_msg = self._store.last_error or "删除会话失败"
                self._store.last_error = None
                self.notify(error_msg, severity="error", timeout=5)

    async def _toggle_runner(self, session_id: str) -> None:
        """Start or stop the runner for a session.

        Args:
            session_id: Session ID
        """
        session = self._store.get_session(session_id)
        if not session:
            return
        runner_status = session.get("runner_status", "none") or "none"

        # Show loading state on the button
        try:
            toggle_btn = self.query_one(f"#runner-{session_id}", Button)
            toggle_btn.disabled = True
            toggle_btn.label = "⏳ 处理中"
        except Exception:
            pass

        api = SessionAPI()
        try:
            if runner_status == "alive":
                await api.stop_runner(session_id)
                self.notify("进程已停止", timeout=2)
            else:
                await api.restart_runner(session_id)
                self.notify("进程已启动", timeout=2)
            await api.close()
            # 刷新列表
            await self._store.refresh()
            await self._render_sessions()
        except Exception as e:
            await api.close()
            msg = getattr(e, "message", str(e))
            self.notify(f"操作失败: {msg}", severity="error", timeout=5)

    def action_focus_search(self) -> None:
        """Focus the search input."""
        self.query_one("#search-input", Input).focus()
