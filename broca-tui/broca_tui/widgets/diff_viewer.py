"""
DiffViewer — 独立的文件 diff 展示 ModalScreen。

点击文件名时，从 API 获取 unified diff 并以彩色方式展示。
"""

from __future__ import annotations

import re
from typing import Any, Dict, List

from textual.app import ComposeResult
from textual.containers import Vertical, Horizontal, ScrollableContainer
from textual.screen import ModalScreen
from rich.text import Text
from textual.widgets import Static, Label, Button

# unified diff @@ 头部正则：@@ -old_start,old_count +new_start,new_count @@
_HUNK_HEADER_RE = re.compile(r"@@\s+-\d+(?:,\d+)?\s+\+(\d+)(?:,\d+)?\s+@@")


def _parse_diff_lines(diff_text: str) -> List[dict]:
    """解析 unified diff 文本，每行返回 {text, type, line_num}。

    自动跳过 git metadata 行（diff --git、index、---、+++ 等），
    仅保留 @@ 头部和实际的变更内容行。

    type: add / del / ctx / head
    line_num: 新文件中的真实行号（del/head 行为 None）
    """
    lines: List[dict] = []
    new_line_num = 0
    for raw in diff_text.split("\n"):
        # 跳过 git metadata 行
        if (
            raw.startswith("diff --git")
            or raw.startswith("index ")
            or raw.startswith("--- ")
            or raw.startswith("+++ ")
            or raw.startswith("new file mode")
            or raw.startswith("deleted file mode")
            or raw.startswith("old mode")
            or raw.startswith("new mode")
            or raw.startswith("rename from")
            or raw.startswith("rename to")
            or raw.startswith("copy from")
            or raw.startswith("copy to")
            or raw.startswith("similarity index")
            or raw.startswith("Binary files")
        ):
            continue

        if raw.startswith("@@"):
            # @@ 头部：仅解析行号，不展示
            m = _HUNK_HEADER_RE.search(raw)
            if m:
                new_line_num = int(m.group(1))
            continue
        if raw.startswith("+"):
            lines.append({"text": raw[1:], "type": "add", "line_num": new_line_num})
            new_line_num += 1
        elif raw.startswith("-"):
            lines.append({"text": raw[1:], "type": "del", "line_num": None})
        else:
            lines.append({"text": raw, "type": "ctx", "line_num": new_line_num})
            new_line_num += 1
    return lines


class DiffViewer(ModalScreen):
    """全屏 ModalScreen，展示文件的 unified diff，支持按 q/Esc/关闭按钮关闭。"""

    DEFAULT_CSS = """
    DiffViewer {
        align: center middle;
    }
    #diff-container {
        width: 90%;
        height: 80%;
        border: solid $border;
        background: #f0f0f0;
        padding: 0;
    }
    #diff-header-bar {
        height: auto;
        padding: 0 1;
        background: #e0e0e0;
        border-bottom: solid $border;
    }
    #diff-header-text {
        text-style: bold;
        width: 1fr;
        color: #333;
    }
    #diff-close-btn {
        width: auto;
        min-width: 0;
        height: auto;
        padding: 0 1;
        background: transparent;
        border: none;
        color: #999;
    }
    #diff-close-btn:hover {
        color: #333;
        background: #d0d0d0;
    }
    #diff-content {
        width: 1fr;
        height: 1fr;
        padding: 0 0;
    }
    #diff-content > .diff-line {
        width: 1fr;
        height: auto;
        padding: 0 1;
    }
    #diff-content > .diff-line.add {
        background: #d4edda;
        color: #1a1a1a;
        text-style: bold;
    }
    #diff-content > .diff-line.del {
        background: #f8d7da;
        color: #1a1a1a;
        text-style: bold;
    }
    #diff-content > .diff-line.head {
        background: #e8e8e8;
        color: #1a1a1a;
        text-style: bold;
    }
    #diff-content > .diff-line.ctx {
        color: #1a1a1a;
    }
    """

    def __init__(self, file_path: str, diff_text: str):
        super().__init__()
        self._file_path = file_path
        self._diff_text = diff_text

    def compose(self) -> ComposeResult:
        with Vertical(id="diff-container"):
            with Horizontal(id="diff-header-bar"):
                yield Static(f"Diff: {self._file_path}", id="diff-header-text")
                yield Button("✕", id="diff-close-btn")
            # 逐行渲染 diff，每行一个独立的 Label widget
            # 使用 Textual CSS class (width: 1fr) 确保背景色铺满整行宽度
            # 用 Text() 包裹避免 Rich 将 [ 和 ] 误解析为标记标签
            with ScrollableContainer(id="diff-content"):
                for line in _parse_diff_lines(self._diff_text or "(无变更)"):
                    ln = line["line_num"]
                    line_num_str = f"{ln:>4}" if ln is not None else "    "
                    text = line["text"]
                    typ = line["type"]
                    if typ == "add":
                        yield Label(Text(f"{line_num_str} + {text}"), classes="diff-line add")
                    elif typ == "del":
                        yield Label(Text(f"{line_num_str} - {text}"), classes="diff-line del")
                    elif typ == "head":
                        yield Label(Text(f"{line_num_str}   {text}"), classes="diff-line head")
                    else:
                        yield Label(Text(f"{line_num_str}   {text}"), classes="diff-line ctx")

    def on_key(self, event):
        if event.key in ("escape", "q"):
            self.dismiss()

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "diff-close-btn":
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
        self._file_paths: Dict[int, str] = {}  # idx -> file_path

    def compose(self) -> ComposeResult:
        with Vertical(id="fs-container"):
            yield Static("选择要查看 diff 的文件", id="fs-header")
            yield Static("点击文件名查看，按 q/Esc 关闭", id="fs-hint")
            with Vertical(id="fs-list"):
                cf = self._changed_files
                idx = 0
                if cf.get("files_added"):
                    yield Label("新增:", classes="fs-group-label")
                    for f in cf["files_added"]:
                        self._file_paths[idx] = f
                        yield Button(f"+ {f}", id=f"fs-file-{idx}")
                        idx += 1
                if cf.get("files_deleted"):
                    yield Label("删除:", classes="fs-group-label")
                    for f in cf["files_deleted"]:
                        self._file_paths[idx] = f
                        yield Button(f"- {f}", id=f"fs-file-{idx}")
                        idx += 1
                if cf.get("files_modified"):
                    yield Label("修改:", classes="fs-group-label")
                    for f in cf["files_modified"]:
                        self._file_paths[idx] = f
                        yield Button(f"~ {f}", id=f"fs-file-{idx}")
                        idx += 1

    def on_button_pressed(self, event: Button.Pressed) -> None:
        """处理文件选择，根据索引找到文件路径。"""
        if event.button.id and event.button.id.startswith("fs-file-"):
            try:
                idx = int(event.button.id.replace("fs-file-", ""))
                file_path = self._file_paths.get(idx)
                if file_path:
                    self.dismiss(file_path)
            except (ValueError, IndexError):
                pass

    def on_key(self, event):
        if event.key in ("escape", "q"):
            self.dismiss()
