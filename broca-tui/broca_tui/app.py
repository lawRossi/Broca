"""
Broca TUI - Terminal User Interface for Broca Agent Framework

Main application entry point using the Textual framework.
"""

import asyncio
import logging
import warnings
from pathlib import Path
from typing import Optional

from textual.app import App
from textual.binding import Binding
from textual.reactive import reactive

from broca_tui.config import get_config
from broca_tui.screens.chat import ChatScreen
from broca_tui.screens.crew_executions import CrewExecutionsScreen
from broca_tui.screens.session_list import SessionListScreen

# Suppress aiohttp resource warnings on app exit.
# We close sessions cleanly in _quit(), but some short-lived or leftover sessions
# can trigger "Unclosed client session/connector" during GC.
# These are harmless since the process is terminating.
warnings.filterwarnings(
    "ignore", category=ResourceWarning, message=".*[Uu]nclosed.*", append=False
)


class BrocaTUIApp(App):
    """Main Broca TUI application."""

    TITLE = "Broca"
    SUB_TITLE = "Agent Framework Terminal UI"

    # CSS_PATH must be set as a CLASS variable.
    # Setting it in __init__ has no effect because Textual reads it
    # during super().__init__() which runs before instance attribute assignment.
    # Also, Textual 7.5.0 does not support cross-file CSS variables,
    # so theme variables are merged directly into app.tcss.
    CSS_PATH = str(Path(__file__).parent / "theme" / "app.tcss")

    # Global key bindings
    BINDINGS = [
        Binding("ctrl+c", "quit_app", "退出", priority=True),
        Binding("ctrl+s", "go_to_sessions", "会话列表", priority=False),
        Binding("question_mark", "show_help", "帮助", priority=False),
    ]

    # Connection state reactive
    connection_status = reactive("disconnected")

    def __init__(self, session_id: Optional[str] = None, **kwargs):
        """Initialize the TUI application.

        Args:
            session_id: Optional session ID to navigate to directly.
        """
        super().__init__(**kwargs)
        self._config = get_config()
        self._session_id = session_id
        self._runner_stopped = False

    def on_mount(self) -> None:
        """Called when the app is mounted."""
        self.title = self.TITLE
        self.sub_title = self.SUB_TITLE

        # Navigate to default screen or direct session
        if self._session_id:
            self._open_chat(self._session_id)
        else:
            self.push_screen(SessionListScreen())

    def on_session_list_screen_session_selected(self, event):
        """Handle session selection from SessionListScreen."""
        self._open_chat(event.session_id)

    def _make_chat_screen(
        self, session_id: str, execution_id: Optional[str] = None
    ) -> ChatScreen:
        """Create a ChatScreen instance.

        Args:
            session_id: Session ID
            execution_id: Optional execution ID for filtering

        Returns:
            ChatScreen instance
        """
        return ChatScreen(session_id=session_id, execution_id=execution_id)

    def _make_crew_screen(self, session_id: str) -> CrewExecutionsScreen:
        """Create a CrewExecutionsScreen instance.

        Args:
            session_id: Session ID

        Returns:
            CrewExecutionsScreen instance
        """
        return CrewExecutionsScreen(session_id=session_id)

    def _open_chat(self, session_id: str, execution_id: Optional[str] = None):
        """Open a chat screen for a session.

        Args:
            session_id: Session ID
            execution_id: Optional execution ID for filtering
        """
        screen = self._make_chat_screen(session_id, execution_id)
        self.push_screen(screen)

    def _open_crew_screen(self, session_id: str):
        """Open a crew execution screen for a session.

        Args:
            session_id: Session ID
        """
        screen = self._make_crew_screen(session_id)
        self.push_screen(screen)

    def _pop_to_sessions(self):
        """Pop back to session list screen."""
        # Find session_list screen in the stack
        for screen in self.screen_stack:
            if screen.name == "session_list" or isinstance(screen, SessionListScreen):
                return

        # Not found, push a new one
        self.push_screen(SessionListScreen())

    def action_go_to_sessions(self) -> None:
        """Navigate to session list."""
        # Only works if we're not already on session list
        current = self.screen
        if isinstance(current, SessionListScreen):
            return
        if hasattr(current, "disconnect_all"):

            async def _go():
                await current.disconnect_all()
                self.pop_screen()

            asyncio.create_task(_go())
        else:
            self.pop_screen()

    async def _quit(self):
        """Internal async quit routine with proper error handling."""
        logger = logging.getLogger(__name__)

        current_screen = self.screen

        # 1. Disconnect Socket.IO
        if hasattr(current_screen, "disconnect_all"):
            try:
                await current_screen.disconnect_all()
            except Exception as e:
                logger.warning(f"断开 Socket 连接失败: {e}")

        # 2. Close all API sessions — check all possible store/API attribute names
        # (avoids "Unclosed client session" warnings on exit)
        stores_to_close = []
        for attr_name in (
            "_chat_store",
            "_agent_store",
            "_store",
            "_session_store",
            "_crew_store",
            "_api",
        ):
            obj = getattr(current_screen, attr_name, None)
            if obj and hasattr(obj, "close"):
                stores_to_close.append(obj)

        for store in stores_to_close:
            try:
                await store.close()
            except Exception as e:
                logger.warning(f"关闭 {type(store).__name__} API 失败: {e}")

        self.exit()

    def action_quit_app(self) -> None:
        """Handle Ctrl+C / global quit."""
        asyncio.create_task(self._quit())

    def action_show_help(self) -> None:
        """Show help screen."""
        pass

    def get_config(self):
        """Get the application configuration."""
        return self._config


def main():
    """Entry point for running the TUI."""
    import argparse

    parser = argparse.ArgumentParser(description="Broca TUI")
    parser.add_argument("--session", "-s", help="Session ID to open directly")
    parser.add_argument("--server", help="Socket.IO server URL")
    args = parser.parse_args()

    app = BrocaTUIApp(session_id=args.session)
    app.run()


if __name__ == "__main__":
    main()
