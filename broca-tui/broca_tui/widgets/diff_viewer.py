"""
DiffViewer — 独立的文件 diff 展示 ModalScreen。

点击文件名时，从 API 获取 unified diff 并以彩色方式展示。
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional

from textual.app import ComposeResult
from textual.containers import Vertical, Horizontal
from textual.screen import ModalScreen
from textual.widgets import Static, Label, Button


class DiffViewer(ModalScreen):
    """全屏 ModalScreen，展示文件的 unified diff，支持按 q/Esc 关闭。"""

    DEFAULT_CSS = """
    DiffViewer {
        align: center middle;
    }
    #diff-container {
        width: 90%;
        height: 80%;
        border: solid $primary;
        background: $surface;
        padding: 1;
    }
    #diff-header {
        text-style: bold;
        padding: 0 0 1 0;
        height: auto;
    }
    #diff-close-hint {
        color: $text-disabled;
        height: auto;
        padding: 0 0 1 0;
    }
    #diff-content {
        width: 1fr;
        height: 1fr;
        overflow: auto;
        padding: 0 1;
    }
    """

    def __init__(self, file_path: str, diff_text: str):
        super().__init__()
        self._file_path = file_path
        self._diff_text = diff_text

    def compose(self) -> ComposeResult:
        with Vertical(id="diff-container"):
            yield Static(f"Diff: {self._file_path}", id="diff-header")
            yield Static("按 q 或 Esc 关闭", id="diff-close-hint")
            # 解析 unified diff 为 Rich 标记
            rich_lines = []
            for line in (self._diff_text or "(无变更)").split("\n"):
                if line.startswith("+") and not line.startswith("+++"):
                    rich_lines.append(f"[bold #055d20 on #e6ffec]{line}[/]")
                elif line.startswith("-") and not line.startswith("---"):
                    rich_lines.append(f"[bold #82071e on #ffebe9]{line}[/]")
                elif line.startswith("@@"):
                    rich_lines.append(f"[#666 on #f0f0f0]{line}[/]")
                else:
                    rich_lines.append(line)
            yield Static("\n".join(rich_lines), id="diff-content")

    def on_key(self, event):
        if event.key in ("escape", "q"):
            self.dismiss()


class FileSelector(ModalScreen):
    """文件选择器 — 展示 turn 中变更的文件列表，点击后查看 diff。"""

    DEFAULT_CSS = """
    FileSelector {
        align: center middle;
    }
    #fs-container {
        width: 70%;
        height: 60%;
        border: solid $primary;
        background: $surface;
        padding: 1;
    }
    #fs-header {
        text-style: bold;
        padding: 0 0 1 0;
        height: auto;
    }
    #fs-hint {
        color: $text-disabled;
        height: auto;
        padding: 0 0 1 0;
    }
    #fs-list {
        width: 1fr;
        height: 1fr;
        overflow: auto;
        padding: 0 1;
    }
    .fs-file-btn {
        width: 1fr;
        height: auto;
        min-width: 0;
        min-height: 0;
        padding: 0 1;
        margin: 0;
        background: transparent;
        border: none;
        text-style: none;
        color: $text;
        content-align: left middle;
    }
    .fs-file-btn:hover {
        text-style: bold underline;
        background: $surface;
        border: none;
    }
    .fs-file-btn:focus {
        text-style: none;
        background: transparent;
        border: none;
    }
    .fs-group-label {
        text-style: bold;
        margin-top: 1;
        color: $text;
    }
    """

    def __init__(self, turn_id: str, changed_files: Dict[str, Any]):
        super().__init__()
        self._turn_id = turn_id
        self._changed_files = changed_files

    def compose(self) -> ComposeResult:
        with Vertical(id="fs-container"):
            yield Static("选择要查看 diff 的文件", id="fs-header")
            yield Static("点击文件名查看，按 q/Esc 关闭", id="fs-hint")
            with Vertical(id="fs-list"):
                cf = self._changed_files
                if cf.get("files_added"):
                    yield Label("新增:", classes="fs-group-label")
                    for f in cf["files_added"]:
                        yield Button(f"+ {f}", id=f"fs-file::{f}")
                if cf.get("files_deleted"):
                    yield Label("删除:", classes="fs-group-label")
                    for f in cf["files_deleted"]:
                        yield Button(f"- {f}", id=f"fs-file::{f}")
                if cf.get("files_modified"):
                    yield Label("修改:", classes="fs-group-label")
                    for f in cf["files_modified"]:
                        yield Button(f"~ {f}", id=f"fs-file::{f}")

    def on_button_pressed(self, event: Button.Pressed) -> None:
        """处理文件选择，将文件路径作为 dismiss 值返回。"""
        if event.button.id and event.button.id.startswith("fs-file::"):
            file_path = event.button.id[len("fs-file::"):]
            self.dismiss(file_path)

    def on_key(self, event):
        if event.key in ("escape", "q"):
            self.dismiss()
