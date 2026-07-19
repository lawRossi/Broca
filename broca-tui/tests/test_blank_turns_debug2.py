"""
调试: turn 列表空白 — 模拟有数据时是否渲染
"""
from pathlib import Path

import pytest

from unittest.mock import patch

from textual.app import App
from broca_tui.screens.chat import ChatScreen
from broca_tui.widgets.message_list import MessageList
from broca_tui.stores.chat_store import TurnSummary

pytestmark = pytest.mark.asyncio
CSS_PATH = str(Path(__file__).parent.parent / "broca_tui" / "theme" / "app.tcss")


class TestApp(App):
    CSS_PATH = CSS_PATH
    def on_mount(self):
        self.push_screen(ChatScreen(session_id="test-session"))


async def test_chat_screen_with_turn_data():
    """模拟有 turn 数据时，检查是否渲染。"""
    fake_turns = [
        TurnSummary(
            turn_id="t1", sequence_number=1, agent_id="a1", agent_name="Agent A",
            user_message="Hello", status="completed", total_duration=1.0,
            final_response="Response 1"
        ),
        TurnSummary(
            turn_id="t2", sequence_number=2, agent_id="a1", agent_name="Agent A",
            user_message="World", status="completed", total_duration=2.0,
            final_response="Response 2"
        ),
    ]

    with patch.object(ChatScreen, '_connect', new_callable=lambda: lambda self: None):
        app = TestApp()
        async with app.run_test(size=(120, 40)) as pilot:
            await pilot.pause()

            screen = app.screen
            ml = screen.query_one("#message-list", MessageList)

            # 直接注入 turn 数据
            ml.set_turn_summaries(fake_turns, agent_name_map={"a1": "Agent A"})
            await pilot.pause()

            scroll = ml.query_one("#turn-scroll")
            area = ml.query_one("#turn-area")

            print("\n=== With turn data ===")
            print(f"scroll size={scroll.size}, region={scroll.region}")
            print(f"area size={area.size}, region={area.region}")
            print(f"area children count={len(area.children)}")
            for child in area.children:
                print(f"  child: type={type(child).__name__}, size={child.size}, region={child.region}")

            assert len(area.children) == 2, f"Expected 2 TurnCards, got {len(area.children)}"
            assert area.size.height > 2, f"Turn area should have height, got {area.size.height}"


async def test_chat_screen_lifecycle():
    """检查 ChatScreen mount 后的完整生命周期。"""
    with patch.object(ChatScreen, '_connect', new_callable=lambda: lambda self: None):
        app = TestApp()
        async with app.run_test(size=(120, 40)) as pilot:
            await pilot.pause()
            await pilot.pause()

            screen = app.screen
            print("\n=== ChatScreen lifecycle ===")
            print(f"screen type={type(screen).__name__}")
            print(f"screen size={screen.size}")

            # Check all widgets exist
            ml = screen.query_one("#message-list", MessageList)
            print(f"message-list exists: True, size={ml.size}")

            # Check if turn-scroll and turn-area exist
            try:
                scroll = screen.query_one("#turn-scroll")
                print(f"turn-scroll exists: True, size={scroll.size}")
            except Exception as e:
                print(f"turn-scroll exists: False, error={e}")

            try:
                area = screen.query_one("#turn-area")
                print(f"turn-area exists: True, size={area.size}, children={len(area.children)}")
            except Exception as e:
                print(f"turn-area exists: False, error={e}")

            # Check chat_store state
            store = screen._chat_store
            print(f"chat_store.turn_summaries count={len(store.turn_summaries)}")
            print(f"chat_store.loading={store.loading}")
            print(f"chat_store.session_id={store.session_id}")
