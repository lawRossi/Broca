"""Debug: verify CSS is loaded correctly for MessageList."""
from pathlib import Path
import pytest
pytestmark = pytest.mark.asyncio

from textual.app import App, ComposeResult
from broca_tui.screens.chat import ChatScreen
from broca_tui.widgets.message_list import MessageList

CSS_PATH = str(Path(__file__).parent.parent / "broca_tui" / "theme" / "app.tcss")
print(f"\nCSS_PATH: {CSS_PATH}")
print(f"CSS file exists: {Path(CSS_PATH).exists()}")


class PushScreenApp(App):
    CSS_PATH = CSS_PATH

    def on_mount(self):
        self.push_screen(ChatScreen(session_id="test-session"))


async def test_message_list_css():
    """Verify MessageList CSS is applied."""
    app = PushScreenApp()
    async with app.run_test(size=(120, 40)) as pilot:
        await pilot.pause()
        await pilot.pause()

        screen = app.screen
        ml = screen.query_one("#message-list", MessageList)
        print(f"\nMessageList size: {ml.size}")
        print(f"MessageList styles.width: {ml.styles.width}")
        print(f"MessageList styles.height: {ml.styles.height}")
        
        # Check if CSS is loaded from file
        print(f"\nAll CSS rules loaded:")
        for rule in app.stylesheet.rules:
            selector = rule.selectors
            if 'message' in selector.lower():
                print(f"  {selector}")
