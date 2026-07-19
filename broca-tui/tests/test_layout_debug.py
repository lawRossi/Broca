"""
Minimal layout debug test: figure out why main-content children distribute height incorrectly.
"""
from pathlib import Path

import pytest

from textual.app import App, ComposeResult
from textual.containers import Vertical, Horizontal, ScrollableContainer
from textual.widgets import Static

pytestmark = pytest.mark.asyncio
CSS_PATH = str(Path(__file__).parent.parent / "broca_tui" / "theme" / "app.tcss")


class MinimalTestApp(App):
    CSS_PATH = CSS_PATH

    def compose(self) -> ComposeResult:
        with Vertical(classes="chat-screen"):
            # Simulate header (3 rows)
            yield Static("Header", id="test-header")
            with Horizontal(id="chat-content", classes="chat-content"):
                with Vertical(classes="main-content"):
                    # Message area with 1fr
                    yield ScrollableContainer(id="test-messages", classes="message-scroll")
                    # Input area (auto height)
                    yield Static("Input", id="test-input")


async def test_minimal_layout():
    """Minimal layout test to understand Vertical height distribution."""
    app = MinimalTestApp()
    async with app.run_test(size=(120, 40)) as pilot:
        await pilot.pause()
        
        screen = app.screen
        
        chat_screen = screen.query_one(".chat-screen")
        chat_content = screen.query_one("#chat-content")
        main_content = screen.query_one(".main-content")
        test_messages = screen.query_one("#test-messages")
        test_input = screen.query_one("#test-input")
        
        print(f"\nchat-screen: {chat_screen.size}, region={chat_screen.region}")
        print(f"chat-content: {chat_content.size}, region={chat_content.region}")
        print(f"main-content: {main_content.size}, region={main_content.region}")
        print(f"test-messages: {test_messages.size}, region={test_messages.region} (classes={test_messages.classes})")
        print(f"test-input: {test_input.size}, region={test_input.region}")
        
        assert chat_screen.size.height == 40
        assert chat_content.size.height > 2
        # Messages area should get most of the height
        assert test_messages.size.height > test_input.size.height, \
            f"Messages ({test_messages.size.height}) should be larger than input ({test_input.size.height})"


class SpecificCSSApp(App):
    """Test with specific CSS to debug the issue."""
    
    CSS = """
    #specific-main-content {
        height: 1fr;
    }
    
    #specific-messages {
        height: 1fr;
    }
    
    #specific-input {
        height: auto;
    }
    """
    
    def compose(self) -> ComposeResult:
        with Vertical(classes="chat-screen"):
            yield Static("Header", id="test-header")
            with Horizontal(id="chat-content", classes="chat-content"):
                with Vertical(id="specific-main-content", classes="main-content"):
                    yield ScrollableContainer(id="specific-messages", classes="message-scroll")
                    yield Static("Input", id="specific-input")


async def test_specific_css_layout():
    """Test with specific CSS to understand height distribution."""
    app = SpecificCSSApp()
    async with app.run_test(size=(120, 40)) as pilot:
        await pilot.pause()
        
        screen = app.screen
        
        main_content = screen.query_one("#specific-main-content")
        messages = screen.query_one("#specific-messages")
        input_widget = screen.query_one("#specific-input")
        
        print(f"\nmain-content: {main_content.size}, region={main_content.region}")
        print(f"messages: {messages.size}, region={messages.region} (classes={messages.classes})")
        print(f"input: {input_widget.size}, region={input_widget.region}")
        
        # Check if input is taking too much space
        print(f"input CSS: height={input_widget.styles.height}")
        print(f"messages CSS: height={messages.styles.height}")
        
        assert messages.size.height > 5, f"Messages area should be >5 rows, got {messages.size.height}"
