"""
Debug ChatInput height: why does it take 34 rows instead of ~6?
"""
from pathlib import Path
import pytest
pytestmark = pytest.mark.asyncio

from textual.app import App, ComposeResult
from broca_tui.widgets.chat_input import ChatInput
from textual.containers import Vertical
from textual.geometry import Size


CSS_PATH = str(Path(__file__).parent.parent / "broca_tui" / "theme" / "app.tcss")


class ChatInputApp(App):
    CSS_PATH = CSS_PATH
    def compose(self) -> ComposeResult:
        yield ChatInput(id="test-chat-input")


async def test_chatinput_height():
    """Check ChatInput's natural height."""
    app = ChatInputApp()
    async with app.run_test(size=(120, 40)) as pilot:
        await pilot.pause()
        
        ci = app.query_one("#test-chat-input", ChatInput)
        print(f"\nChatInput: size={ci.size}, region={ci.region}")
        
        for child in ci.children:
            print(f"  child: type={type(child).__name__}, classes={child.classes}, size={child.size}, region={child.region}")
            for gc in child.children:
                print(f"    sub: type={type(gc).__name__}, classes={gc.classes}, size={gc.size}, region={gc.region}")
                for ggc in gc.children:
                    print(f"      sub-sub: type={type(ggc).__name__}, classes={ggc.classes}, size={ggc.size}, region={ggc.region}")
        
        inner_vertical = ci.children[0]
        print(f"\nInner Vertical CSS height: {inner_vertical.styles.height}")
        print(f"Inner Vertical CSS width: {inner_vertical.styles.width}")
        
        # Check list view
        from textual.widgets import ListView
        lv = ci.query_one("#autocomplete-list", ListView)
        print(f"\nListView: display={lv.display}, size={lv.size}")
        
        # Check input field
        from textual.widgets import Input
        inp = ci.query_one("#chat-input-field", Input)
        print(f"Input: size={inp.size}")
        
        # Check button
        btn = ci.query_one("#btn-send")
        print(f"Button: size={btn.size}, styles.height={btn.styles.height}")
