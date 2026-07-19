"""
Regression tests for ChatScreen, AgentSidebar, and MessageList defensive error handling.

Tests that:
1. _on_chat_change doesn't crash when widgets aren't ready
2. AgentSidebar._render_agents doesn't crash when #agent-list isn't ready
3. _on_connection_change properly wraps async calls with run_worker
4. Widget queries succeed after full mount (no regression)
5. MessageList._render_messages preserves #message-area across multiple calls
6. MessageList watch methods don't crash during compose phase
"""

from unittest.mock import AsyncMock, patch

import pytest

from textual.app import App, ComposeResult
from textual.containers import ScrollableContainer

from broca_tui.screens.chat import ChatScreen
from broca_tui.widgets.agent_sidebar import AgentSidebar
from broca_tui.widgets.message_list import MessageList
from broca_tui.widgets.chat_header import ChatHeader
from broca_tui.widgets.chat_input import ChatInput
from broca_tui.widgets.info_sidebar import InfoSidebar
from broca_tui.stores.agent_store import AgentStore

pytestmark = pytest.mark.asyncio


class PushScreenApp(App):
    """App that pushes ChatScreen as a screen (like real app does)."""

    def __init__(self, session_id="test-session", **kwargs):
        super().__init__(**kwargs)
        self._session_id = session_id

    def on_mount(self):
        self.push_screen(ChatScreen(session_id=self._session_id))


class TestDefensiveErrorHandling:
    """Test that defensive error handling prevents crashes."""

    async def test_on_chat_change_after_mount(self):
        """_on_chat_change should succeed when widgets are mounted."""
        screen = ChatScreen(session_id="test-session")

        with patch.object(screen._agent_store._api, 'get_session_agents',
                          new=AsyncMock(return_value=[])):
            with patch.object(screen._chat_store._api, 'get_session_messages',
                              new=AsyncMock(return_value={"total": 0, "messages": []})):
                app = PushScreenApp(session_id="test-session")
                async with app.run_test(size=(120, 40)) as pilot:
                    for _ in range(5):
                        await pilot.pause()

                    # _on_chat_change should work after screen is mounted
                    screen._on_chat_change()  # Should not raise

    async def test_on_chat_change_no_crash_on_early_call(self):
        """
        _on_chat_change should NOT crash even if widgets aren't mounted yet.
        This tests the defensive try/except in _on_chat_change.
        """
        screen = ChatScreen(session_id="test-session")

        # Simulate calling _on_chat_change before any widgets exist
        # by patching query_one to raise NoMatches
        with patch.object(screen, 'query_one',
                          side_effect=Exception("Widget not ready")):
            # Should not raise - the try/except should handle it gracefully
            screen._on_chat_change()

    async def test_render_agents_no_crash_on_early_call(self):
        """
        AgentSidebar._render_agents should NOT crash even if #agent-list
        isn't mounted yet. Tests the defensive try/except in _render_agents.
        """
        store = AgentStore()
        sidebar = AgentSidebar(store=store, id="test-sidebar")

        # Simulate calling _render_agents before mount by patching query_one
        with patch.object(sidebar, 'query_one',
                          side_effect=Exception("#agent-list not ready")):
            # Should not raise - the try/except should handle it gracefully
            sidebar._render_agents()

    async def test_render_agents_after_error_in_fetch(self):
        """
        Simulate the original bug: fetch_agents fails, triggers _render_agents.
        The defensive handling should prevent the crash.
        """
        screen = ChatScreen(session_id="test-session")

        # Get the agent sidebar from the screen itself
        with patch.multiple(screen._chat_store._api,
                            get_session_messages=AsyncMock(return_value={"total": 0, "messages": []})):
            # Register a callback on the agent_store that calls the sidebar's _render_agents
            # The sidebar will be mounted as part of the screen
            app = PushScreenApp(session_id="test-session")
            async with app.run_test(size=(120, 40)) as pilot:
                for _ in range(3):
                    await pilot.pause()

                # Get the actual mounted screen from the app
                actual_screen = app.screen
                from broca_tui.widgets.agent_sidebar import AgentSidebar
                sidebar = actual_screen.query_one("#agent-sidebar", AgentSidebar)

                # Force a failed fetch_agents on the screen's store
                # This simulates a network error triggering _render_agents
                store = screen._agent_store
                store.on_change(sidebar._render_agents)

                try:
                    await store.fetch_agents("test-no-server")
                except Exception:
                    pass

                # After the error, #agent-list should still exist on the mounted sidebar
                container = sidebar.query_one("#agent-list", ScrollableContainer)
                assert container is not None

    async def test_on_connection_change_wraps_async(self):
        """
        _on_connection_change should use run_worker for async calls.
        This test verifies the fix for the non-awaited coroutine bug.
        """
        screen = ChatScreen(session_id="test-session")

        with patch.object(screen, 'run_worker') as mock_run_worker:
            screen._on_connection_change(connected=True)
            # Should call run_worker with the coroutine
            mock_run_worker.assert_called_once()
            # The argument should be a coroutine
            arg = mock_run_worker.call_args[0][0]
            assert hasattr(arg, '__await__') or hasattr(arg, '__aiter__')

    async def test_on_connection_change_noop_when_disconnected(self):
        """_on_connection_change should do nothing when disconnected."""
        screen = ChatScreen(session_id="test-session")

        with patch.object(screen, 'run_worker') as mock_run_worker:
            screen._on_connection_change(connected=False)
            mock_run_worker.assert_not_called()


class TestWidgetQueryNoRegression:
    """Test that widget queries succeed in normal scenarios (no regression)."""

    async def test_all_widgets_found_on_chat_screen(self):
        """All expected widgets should be found on ChatScreen."""
        app = PushScreenApp(session_id="test-session")
        async with app.run_test(size=(120, 40)) as pilot:
            for _ in range(5):
                await pilot.pause()

            screen = app.screen

            assert screen.query_one("#chat-header", ChatHeader) is not None
            assert screen.query_one("#message-list", MessageList) is not None
            assert screen.query_one("#chat-input", ChatInput) is not None
            assert screen.query_one("#info-sidebar", InfoSidebar) is not None

            from broca_tui.widgets.agent_sidebar import AgentSidebar
            sidebar = screen.query_one("#agent-sidebar", AgentSidebar)
            assert sidebar is not None
            assert sidebar.query_one("#agent-list", ScrollableContainer) is not None

    async def test_worker_error_no_crash(self):
        """
        When the _connect worker fails (network error), the screen
        should remain usable and all widgets should be queryable.
        """
        app = PushScreenApp(session_id="test-session")
        async with app.run_test(size=(120, 40)) as pilot:
            for _ in range(10):
                await pilot.pause(0.1)

            screen = app.screen

            # Widgets should be queryable even after worker failure
            ml = screen.query_one("#message-list", MessageList)
            assert ml is not None


class TestMessageListNoRegression:
    """Test that MessageList doesn't crash on multiple render cycles."""

    @pytest.fixture
    def app(self):
        from textual.app import App
        from broca_tui.widgets.message_list import MessageList

        class TestApp(App):
            def compose(self) -> ComposeResult:
                yield MessageList(id="test-ml")

        return TestApp()

    async def test_set_turn_summaries_multiple_times(self, app):
        """Multiple set_turn_summaries calls should work (regression: turn-scroll destroyed by remove_children)."""
        from broca_tui.stores.chat_store import TurnSummary

        async with app.run_test() as pilot:
            await pilot.pause()

            ml = app.query_one("#test-ml", MessageList)

            t1 = TurnSummary(turn_id="t1", sequence_number=1, agent_id="a1", agent_name="A", user_message="Hello")
            t2 = TurnSummary(turn_id="t2", sequence_number=2, agent_id="a1", agent_name="A", user_message="World")

            # First call
            ml.set_turn_summaries([t1])
            await pilot.pause()

            # Second call (this was crashing because turn-scroll was removed)
            ml.set_turn_summaries([t2])
            await pilot.pause()

            # Cycle: empty → turns → empty
            ml.set_turn_summaries([])
            await pilot.pause()
            ml.set_turn_summaries([t1, t2])
            await pilot.pause()

    async def test_add_turn_after_set_turns(self, app):
        """add_turn_summary after set_turn_summaries should work."""
        from broca_tui.stores.chat_store import TurnSummary

        async with app.run_test() as pilot:
            await pilot.pause()
            ml = app.query_one("#test-ml", MessageList)

            t1 = TurnSummary(turn_id="t1", sequence_number=1, agent_id="a1", agent_name="A", user_message="Hello")
            t2 = TurnSummary(turn_id="t2", sequence_number=2, agent_id="a1", agent_name="A", user_message="World")

            ml.set_turn_summaries([t1])
            await pilot.pause()
            ml.add_turn_summary(t2)
            await pilot.pause()

    async def test_watch_methods_during_compose(self, app):
        """
        Watch methods (loading, show_redo) should not crash during compose phase
        when children aren't mounted yet.
        """
        async with app.run_test() as pilot:
            await pilot.pause()

            ml = app.query_one("#test-ml", MessageList)

            # These should not crash even though they trigger reactive watchers
            ml.loading = True
            await pilot.pause()
            ml.loading = False
            await pilot.pause()
            ml.show_redo = True
            await pilot.pause()
            ml.show_redo = False
            await pilot.pause()

    async def test_scroll_to_bottom_safe(self, app):
        """scroll_to_bottom should not crash when not mounted."""
        from broca_tui.widgets.message_list import MessageList
        ml = MessageList(id="unmounted")
        # Should not crash even though not mounted
        ml.scroll_to_bottom()
