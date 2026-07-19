"""
布局测试: 验证 ChatScreen 各组件的尺寸和可见性。
模拟 "除了顶栏其他一片空白" 的问题。
"""
from pathlib import Path

import pytest

from textual.app import App
from broca_tui.screens.chat import ChatScreen
from broca_tui.widgets.chat_header import ChatHeader
from broca_tui.widgets.message_list import MessageList
from broca_tui.widgets.chat_input import ChatInput

pytestmark = pytest.mark.asyncio
CSS_PATH = str(Path(__file__).parent.parent / "broca_tui" / "theme" / "app.tcss")


class PushScreenApp(App):
    CSS_PATH = CSS_PATH  # Load the actual CSS

    def __init__(self, **kwargs):
        super().__init__(**kwargs)

    def on_mount(self):
        self.push_screen(ChatScreen(session_id="test-session"))


async def test_chat_screen_layout_sizes():
    """Test that all panels have non-zero size after mount."""
    app = PushScreenApp()
    async with app.run_test(size=(120, 40)) as pilot:
        await pilot.pause()
        await pilot.pause()

        screen = app.screen
        print(f"\n===== Screen size: {screen.size} =====")

        # Check chat-screen container
        chat_screen = screen.query_one(".chat-screen")
        print(f"chat-screen: size={chat_screen.size}, region={chat_screen.region}")

        # Check chat-content horizontal
        chat_content = screen.query_one("#chat-content")
        print(f"chat-content: size={chat_content.size}, region={chat_content.region}")

        # Check header
        header = screen.query_one("#chat-header", ChatHeader)
        print(f"chat-header: size={header.size}, region={header.region}")
        # Check header's inner children
        for child in header.children:
            print(f"  header child: type={type(child).__name__}, size={child.size}, region={child.region}, classes={child.classes}")

        # Check agent sidebar
        from broca_tui.widgets.agent_sidebar import AgentSidebar
        agent_sidebar = screen.query_one("#agent-sidebar", AgentSidebar)
        print(f"agent-sidebar: size={agent_sidebar.size}, region={agent_sidebar.region}")
        for child in agent_sidebar.children:
            print(f"  agent-sidebar child: type={type(child).__name__}, size={child.size}, region={child.region}, classes={child.classes}")
            for gc in child.children[:3]:  # first 3
                print(f"    grandchild: type={type(gc).__name__}, size={gc.size}, region={gc.region}")

        # Check main content
        main_content = screen.query_one(".main-content")
        print(f"main-content: size={main_content.size}, region={main_content.region}")

        # Check message list
        ml = screen.query_one("#message-list", MessageList)
        print(f"message-list: size={ml.size}, region={ml.region}")
        print(f"  CSS: width={ml.styles.width}, height={ml.styles.height}")
        print(f"  DEFAULT_CSS: [{repr(MessageList.DEFAULT_CSS[:100])}]")
        for child in ml.children:
            print(f"  message-list child: type={type(child).__name__}, size={child.size}, region={child.region}, classes={child.classes}")

        # Check chat input
        ci = screen.query_one("#chat-input", ChatInput)
        print(f"chat-input: size={ci.size}, region={ci.region}")

        # Check info sidebar
        from broca_tui.widgets.info_sidebar import InfoSidebar
        info_sidebar = screen.query_one("#info-sidebar", InfoSidebar)
        print(f"info-sidebar: size={info_sidebar.size}, region={info_sidebar.region}")

        # Assertions
        assert chat_screen.size.height == 40, "chat-screen should fill screen height"
        assert chat_content.size.height > 2, f"chat-content should have >2 rows, got {chat_content.size.height}"
        assert header.size.height <= 3, f"chat-header should be <=3 rows, got {header.size.height}"
        assert agent_sidebar.size.height > 2, f"agent-sidebar has {agent_sidebar.size.height} height"
        assert ml.size.height > 2, f"message-list has {ml.size.height} height"
        assert info_sidebar.size.height > 2, f"info-sidebar has {info_sidebar.size.height} height"
