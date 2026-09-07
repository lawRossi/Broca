"""TUI ChatInput # 路径补全自动化测试。

覆盖行为：
- 触发：#（前无空格）弹出 ListView
- 过滤：#ab 按前缀过滤
- 钻取：#dir/ 列出子目录；选中目录后继续钻取
- 选择：选中文件插入 "#path " 并关闭列表；# 后出现空格关闭列表

使用 mock 的 SessionAPI.complete_files 返回固定数据，避免真实网络依赖。
"""

from __future__ import annotations

import asyncio
from pathlib import Path
from unittest.mock import AsyncMock, patch

import pytest
from textual.app import App, ComposeResult
from textual.widgets import ListView

from broca_tui.widgets.chat_input import ChatInput

pytestmark = pytest.mark.asyncio
CSS_PATH = str(Path(__file__).parent.parent / "broca_tui" / "theme" / "app.tcss")


class ChatInputApp(App):
    """Test app hosting a single ChatInput."""

    CSS_PATH = CSS_PATH

    def compose(self) -> ComposeResult:
        yield ChatInput(id="test-chat-input")


ROOT_COMPLETIONS = [
    {"name": "src", "path": "src", "is_dir": True},
    {"name": "docs", "path": "docs", "is_dir": True},
    {"name": "README.md", "path": "README.md", "is_dir": False},
]

SRC_COMPLETIONS = [
    {"name": "utils", "path": "src/utils", "is_dir": True},
    {"name": "main.py", "path": "src/main.py", "is_dir": False},
]

SRC_UTILS_COMPLETIONS = [
    {"name": "helpers.py", "path": "src/utils/helpers.py", "is_dir": False},
]


def _mock_complete_files(base: str, prefix: str) -> list[dict]:
    """Mock backend /files/complete: base 与 prefix 语义与后端一致。"""
    if prefix == "src/":
        return SRC_COMPLETIONS
    if prefix == "src/utils/":
        return SRC_UTILS_COMPLETIONS
    if prefix == "a":
        return [{"name": "ab_test.txt", "path": "ab_test.txt", "is_dir": False}]
    return ROOT_COMPLETIONS


async def _type_and_wait(pilot, text_area, text: str) -> None:
    """Set input text and wait for the async completion worker to settle."""
    text_area.text = text
    await pilot.pause()
    await asyncio.sleep(0.2)
    await pilot.pause()


def _list_labels(ci: ChatInput) -> list[str]:
    """Render current ListView item labels (e.g. ['#src/', '#docs/'])."""
    lv = ci.query_one("#autocomplete-list", ListView)
    return [str(item.children[0].render()) for item in lv.children]


@pytest.fixture
def mock_complete_files():
    """Patch SessionAPI.complete_files with fixed data (no real network)."""
    with patch(
        "broca_tui.api.session.SessionAPI.complete_files",
        new=AsyncMock(side_effect=_mock_complete_files),
    ) as mock:
        yield mock


async def test_trigger_hash_shows_path_list(mock_complete_files):
    """输入 #（前无空格）弹出文件路径列表；set_workspace 生效。"""
    app = ChatInputApp()
    async with app.run_test(size=(120, 40)) as pilot:
        ci = app.query_one("#test-chat-input", ChatInput)
        ci.set_workspace("/tmp/ws")
        text_area = ci.query_one("#chat-input-field")

        await _type_and_wait(pilot, text_area, "#")

        lv = ci.query_one("#autocomplete-list", ListView)
        assert lv.display is True
        assert ci._autocomplete_type == "path"
        # 目录在前（src/、docs/），文件在后（README.md）
        assert _list_labels(ci) == ["#src/", "#docs/", "#README.md"]

        # workspace 已传给补全请求
        mock_complete_files.assert_awaited()
        call = mock_complete_files.await_args
        assert call.args[0] == "/tmp/ws"
        assert call.args[1] == ""


async def test_prefix_filter(mock_complete_files):
    """#a 按前缀过滤。"""
    app = ChatInputApp()
    async with app.run_test(size=(120, 40)) as pilot:
        ci = app.query_one("#test-chat-input", ChatInput)
        ci.set_workspace("/tmp/ws")
        text_area = ci.query_one("#chat-input-field")

        await _type_and_wait(pilot, text_area, "#a")

        lv = ci.query_one("#autocomplete-list", ListView)
        assert lv.display is True
        assert _list_labels(ci) == ["#ab_test.txt"]
        assert mock_complete_files.await_args.args[1] == "a"


async def test_dir_drill(mock_complete_files):
    """#src/ 钻取：列出子目录，path 形如 #src/<name>。"""
    app = ChatInputApp()
    async with app.run_test(size=(120, 40)) as pilot:
        ci = app.query_one("#test-chat-input", ChatInput)
        ci.set_workspace("/tmp/ws")
        text_area = ci.query_one("#chat-input-field")

        await _type_and_wait(pilot, text_area, "#src/")

        lv = ci.query_one("#autocomplete-list", ListView)
        assert lv.display is True
        assert _list_labels(ci) == ["#src/utils/", "#src/main.py"]
        assert mock_complete_files.await_args.args[1] == "src/"


async def test_select_dir_continues_drill(mock_complete_files):
    """选中目录 → 插入 #dir/ 并继续列出子目录（可多级钻取）。"""
    app = ChatInputApp()
    async with app.run_test(size=(120, 40)) as pilot:
        ci = app.query_one("#test-chat-input", ChatInput)
        ci.set_workspace("/tmp/ws")
        text_area = ci.query_one("#chat-input-field")

        await _type_and_wait(pilot, text_area, "#src")
        lv = ci.query_one("#autocomplete-list", ListView)
        assert lv.display is True

        # 选中 src 目录（index 0）→ 插入 #src/，继续显示子目录
        lv.index = 0
        lv.focus()
        await pilot.pause()
        await pilot.press("enter")
        await asyncio.sleep(0.3)
        await pilot.pause()

        assert text_area.text == "#src/"
        lv = ci.query_one("#autocomplete-list", ListView)
        assert lv.display is True
        assert _list_labels(ci) == ["#src/utils/", "#src/main.py"]

        # 继续钻取：选中 src/utils 目录 → #src/utils/，再列子项
        lv.index = 0
        lv.focus()
        await pilot.pause()
        await pilot.press("enter")
        await asyncio.sleep(0.3)
        await pilot.pause()

        assert text_area.text == "#src/utils/"
        lv = ci.query_one("#autocomplete-list", ListView)
        assert lv.display is True
        assert _list_labels(ci) == ["#src/utils/helpers.py"]


async def test_select_file_inserts_path_with_space(mock_complete_files):
    """选中文件 → 插入 #完整相对路径 + 尾随空格，并关闭列表。"""
    app = ChatInputApp()
    async with app.run_test(size=(120, 40)) as pilot:
        ci = app.query_one("#test-chat-input", ChatInput)
        ci.set_workspace("/tmp/ws")
        text_area = ci.query_one("#chat-input-field")

        await _type_and_wait(pilot, text_area, "#")
        lv = ci.query_one("#autocomplete-list", ListView)
        assert lv.display is True

        # 选中 README.md（index 2，文件）
        lv.index = 2
        lv.focus()
        await pilot.pause()
        await pilot.press("enter")
        await asyncio.sleep(0.2)
        await pilot.pause()

        assert text_area.text == "#README.md "
        lv = ci.query_one("#autocomplete-list", ListView)
        assert lv.display is False


async def test_space_after_hash_closes(mock_complete_files):
    """# 后出现空格 → 关闭列表；# 前有文字（无空格）仍可触发。"""
    app = ChatInputApp()
    async with app.run_test(size=(120, 40)) as pilot:
        ci = app.query_one("#test-chat-input", ChatInput)
        ci.set_workspace("/tmp/ws")
        text_area = ci.query_one("#chat-input-field")

        # 前面有文字、# 前无空格 → 仍触发（与 @ 规则一致）
        await _type_and_wait(pilot, text_area, "请读取 #")
        lv = ci.query_one("#autocomplete-list", ListView)
        assert lv.display is True

        # # 后有空格 → 关闭
        await _type_and_wait(pilot, text_area, "请读取 #src ")
        lv = ci.query_one("#autocomplete-list", ListView)
        assert lv.display is False


async def test_mutual_exclusion_with_mention(mock_complete_files):
    """@mention 显示时 # 不触发（互斥），mention 关闭后 # 正常触发。"""
    app = ChatInputApp()
    async with app.run_test(size=(120, 40)) as pilot:
        ci = app.query_one("#test-chat-input", ChatInput)
        ci.set_workspace("/tmp/ws")
        ci.set_agents([{"name": "agent1", "agent_id": "ag-1"}])
        text_area = ci.query_one("#chat-input-field")

        # @agent1 显示 mention 列表（无空格 → 未补全完成）
        await _type_and_wait(pilot, text_area, "@agent1 #x")
        lv = ci.query_one("#autocomplete-list", ListView)
        # mention 分支优先：after_at 含 "#x"（无空格），mention 列表显示中
        if lv.display:
            assert ci._autocomplete_type == "mention"

        # 清空后仅 # → path 列表正常显示
        await _type_and_wait(pilot, text_area, "#")
        lv = ci.query_one("#autocomplete-list", ListView)
        assert lv.display is True
        assert ci._autocomplete_type == "path"
