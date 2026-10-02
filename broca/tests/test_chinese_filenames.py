"""
Tests for Chinese (non-ASCII) filename handling in changed-files display.

Root cause being fixed:
Git defaults to core.quotepath=true, which escapes non-ASCII filenames as
octal sequences (e.g. "\344\270\255\346\226\207.txt") in command output.
The snapshot repo now disables quotepath, and diff summary parsing unquotes
git-escaped paths as defense in depth.

Verifies:
1. _unquote_git_path restores git-escaped paths (octal, quotes, backslashes)
2. calculate_patch returns raw UTF-8 Chinese filenames
3. get_diff_summary parses Chinese filenames from diff content (added/deleted/modified)
4. Filenames containing spaces are parsed correctly
"""

import tempfile
from pathlib import Path

import pytest

from broca.snapshot.git_manager import GitManager
from broca.snapshot.patch import (
    PatchCalculator,
    _strip_diff_prefix,
    _unquote_git_path,
)


# ============================================================
# Fixtures
# ============================================================

@pytest.fixture
def workspace():
    """Create a temporary workspace with initialized snapshot git repo."""
    with tempfile.TemporaryDirectory() as tmpdir:
        yield tmpdir


@pytest.fixture
def calculator(workspace):
    return PatchCalculator(workspace)


# ============================================================
# Unit tests: path unquoting
# ============================================================

class TestUnquoteGitPath:
    def test_plain_path_unchanged(self):
        assert _unquote_git_path("a/src/main.py") == "a/src/main.py"

    def test_octal_escaped_chinese(self):
        # git quotepath=true output for 中文文件.txt
        escaped = '"\\344\\270\\255\\346\\226\\207\\346\\226\\207\\344\\273\\266.txt"'
        assert _unquote_git_path(escaped) == "中文文件.txt"

    def test_mixed_ascii_and_chinese(self):
        escaped = '"a/docs/\\346\\226\\207\\346\\241\\243/README.md"'
        assert _unquote_git_path(escaped) == "a/docs/文档/README.md"

    def test_escaped_quote_and_backslash(self):
        assert _unquote_git_path('"a/foo\\"bar\\\\baz.txt"') == 'a/foo"bar\\baz.txt'

    def test_strip_diff_prefix(self):
        assert _strip_diff_prefix("a/中文.txt") == "中文.txt"
        assert _strip_diff_prefix("b/src/x.py") == "src/x.py"
        assert _strip_diff_prefix("/dev/null") == "/dev/null"
        # file literally named "a/..." at repo root: only one level stripped
        assert _strip_diff_prefix("a/a/x") == "a/x"


# ============================================================
# Integration tests: real git repo with Chinese filenames
# ============================================================

class TestChineseFilenamesEndToEnd:
    def test_repo_config_disables_quotepath(self, workspace):
        """GitManager must persist core.quotepath=false in repo config."""
        manager = GitManager(workspace)
        manager.ensure_initialized()
        repo = manager.get_repo()
        assert repo.config_reader().get_value("core", "quotepath") is False

    def test_calculate_patch_chinese_names(self, calculator, workspace):
        """calculate_patch returns raw Chinese filenames, not octal escapes."""
        import asyncio

        manager = calculator.git_manager
        manager.ensure_initialized()

        async def run():
            # initial commit
            await manager._run_git_command("add", "-A")
            await manager._run_git_command("commit -m init --allow-empty")
            base = (await manager._run_git_command("rev-parse", "HEAD")).strip()

            # create files with Chinese names and spaces
            Path(workspace, "中文文件.txt").write_text("hello\n", encoding="utf-8")
            Path(workspace, "docs/文档 说明.md").parent.mkdir(parents=True, exist_ok=True)
            Path(workspace, "docs/文档 说明.md").write_text(
                "content\n", encoding="utf-8"
            )

            await manager._run_git_command("add", "-A")
            tree2 = (await manager._run_git_command("write-tree")).strip()
            return base, tree2

        base, tree2 = asyncio.run(run())
        files = asyncio.run(calculator._get_changed_files(base, tree2))
        assert "中文文件.txt" in files
        assert "docs/文档 说明.md" in files
        for f in files:
            assert "\\3" not in f, f"escaped filename leaked: {f}"

    def test_get_diff_summary_chinese_names(self, calculator):
        """get_diff_summary parses Chinese filenames from a quotepath=true style diff.

        Defense in depth: even if a diff was produced with escaped paths,
        the summary must restore the original UTF-8 names.
        """
        diff_content = (
            'diff --git "a/\\344\\270\\255\\346\\226\\207.txt" "b/\\344\\270\\255\\346\\226\\207.txt"\n'
            "new file mode 100644\n"
            "index 0000000..ce01362\n"
            "--- /dev/null\n"
            '+++ "b/\\344\\270\\255\\346\\226\\207.txt"\n'
            "@@ -0,0 +1 @@\n"
            "+hello\n"
            'diff --git "a/\\344\\277\\256\\346\\224\\271.txt" "b/\\344\\277\\256\\346\\224\\271.txt"\n'
            "index ce01362..9daeafb 100644\n"
            '--- "a/\\344\\277\\256\\346\\224\\271.txt"\n'
            '+++ "b/\\344\\277\\256\\346\\224\\271.txt"\n'
            "@@ -1 +1,2 @@\n"
            "hello\n"
            "+world\n"
            "diff --git a/plain.txt b/plain.txt\n"
            "deleted file mode 100644\n"
            "index ce01362..0000000\n"
            "--- a/plain.txt\n"
            "+++ /dev/null\n"
        )
        summary = calculator.get_diff_summary(diff_content)
        assert summary["files_added"] == ["中文.txt"]
        assert summary["files_modified"] == ["修改.txt"]
        assert summary["files_deleted"] == ["plain.txt"]
        assert summary["total_files"] == 3

    def test_get_diff_summary_paths_with_spaces(self, calculator):
        """Quoted paths containing spaces must not be split incorrectly."""
        diff_content = (
            'diff --git "a/my doc/\\346\\226\\207\\344\\273\\266 one.md" "b/my doc/\\346\\226\\207\\344\\273\\266 one.md"\n'
            "new file mode 100644\n"
            "index 0000000..ce01362\n"
            "--- /dev/null\n"
            '+++ "b/my doc/\\346\\226\\207\\344\\273\\266 one.md"\n'
            "@@ -0,0 +1 @@\n"
            "+hi\n"
        )
        summary = calculator.get_diff_summary(diff_content)
        assert summary["files_added"] == ["my doc/文件 one.md"]
