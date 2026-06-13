"""
调试: turn 列表空白 — 检查 TurnCard 是否被 mount, turn-scroll/turn-area 尺寸
"""
import pytest
pytestmark = pytest.mark.asyncio

from textual.app import App, ComposeResult
from textual.containers import ScrollableContainer, Vertical, Horizontal
from textual.widgets import Static, Label

from broca_tui.screens.chat import ChatScreen
from broca_tui.widgets.message_list import MessageList
from broca_tui.stores.chat_store import TurnSummary
from broca_tui.widgets.turn_card import TurnCard

from pathlib import Path
CSS_PATH = str(Path(__file__).parent.parent / "broca_tui" / "theme" / "app.tcss")


class DirectMessageListApp(App):
    CSS_PATH = CSS_PATH

    def compose(self) -> ComposeResult:
        yield MessageList(id="ml")


async def test_message_list_render_direct():
    """直接向 MessageList 注入 turn，检查渲染结果。"""
    app = DirectMessageListApp()
    async with app.run_test(size=(120, 40)) as pilot:
        await pilot.pause()
        ml = app.query_one("#ml", MessageList)

        t1 = TurnSummary(
            turn_id="t1", sequence_number=1, agent_id="a1", agent_name="A",
            user_message="Hello", status="completed", total_duration=1.0,
            final_response="Response 1"
        )
        t2 = TurnSummary(
            turn_id="t2", sequence_number=2, agent_id="a1", agent_name="A",
            user_message="World", status="completed", total_duration=2.0,
            final_response="Response 2"
        )

        ml.set_turn_summaries([t1, t2], agent_name_map={"a1": "Agent A"})
        await pilot.pause()

        # 检查结构
        scroll = ml.query_one("#turn-scroll", ScrollableContainer)
        area = ml.query_one("#turn-area", Vertical)
        print(f"\nscroll size={scroll.size}, region={scroll.region}")
        print(f"area size={area.size}, region={area.region}")
        print(f"area children count={len(area.children)}")
        for child in area.children:
            print(f"  child: type={type(child).__name__}, size={child.size}, region={child.region}")

        assert len(area.children) == 2, f"Expected 2 TurnCards, got {len(area.children)}"
        assert scroll.size.height > 0, "ScrollableContainer should have height"
        assert area.size.height > 0, "Turn area should have height"


async def test_chat_screen_turn_rendering():
    """进入 ChatScreen 后检查 turn 渲染。"""
    class TestApp(App):
        CSS_PATH = CSS_PATH
        def on_mount(self):
            self.push_screen(ChatScreen(session_id="test-session"))

    app = TestApp()
    async with app.run_test(size=(120, 40)) as pilot:
        for _ in range(10):
            await pilot.pause(0.2)

        screen = app.screen
        ml = screen.query_one("#message-list", MessageList)
        scroll = ml.query_one("#turn-scroll", ScrollableContainer)
        area = ml.query_one("#turn-area", Vertical)

        print(f"\n=== ChatScreen turn rendering ===")
        print(f"message-list size={ml.size}")
        print(f"scroll size={scroll.size}, region={scroll.region}")
        print(f"area size={area.size}, region={area.region}")
        print(f"area children count={len(area.children)}")
        for child in area.children:
            print(f"  child: type={type(child).__name__}, size={child.size}, region={child.region}")

        # 即使没有 turn 数据，也应该显示"暂无 Turn 数据"
        assert len(area.children) >= 1, f"Expected at least empty label, got {len(area.children)}"


async def test_turn_card_compose():
    """TurnCard compose 后尺寸是否正常。"""
    t = TurnSummary(
        turn_id="t1", sequence_number=1, agent_id="a1", agent_name="A",
        user_message="Hello", status="completed", total_duration=1.0,
        final_response="**bold** response"
    )
    card = TurnCard(turn=t, agent_name_map={"a1": "Agent A"})

    app = App(CSS_PATH=CSS_PATH)
    async with app.run_test(size=(120, 40)) as pilot:
        await pilot.pause()
        # 直接 mount
        await app.mount(card)
        await pilot.pause()

        print(f"\nTurnCard size={card.size}, region={card.region}")
        print(f"TurnCard children count={len(card.children)}")
        for child in card.children:
            print(f"  child: type={type(child).__name__}, size={child.size}, region={child.region}")

        assert card.size.height > 0, "TurnCard should have height"
        assert len(card.children) > 0, "TurnCard should have children"
