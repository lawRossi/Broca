"""
Regression tests: tool_result_cache cleanup removes stale files.

Fix: cleanup_tool_result_cache() removes files older than TOOL_CACHE_MAX_AGE,
triggered lazily on first cache write (guarded by module-level flag).
"""

import os
import time
from pathlib import Path
from unittest.mock import patch

import pytest

import broca.tools.tool as tool_module
from broca.tools.tool import Tool, ToolResult, ToolStatus, cleanup_tool_result_cache


@pytest.fixture(autouse=True)
def reset_cleanup_flag():
    """Reset the module-level flag before each test."""
    tool_module._tool_cache_cleanup_done = False
    yield
    tool_module._tool_cache_cleanup_done = False


@pytest.fixture
def cache_dir(tmp_path: Path):
    """Patch TOOL_RESULT_CACHE_DIR to a temp directory."""
    d = tmp_path / "tool_result_cache"
    d.mkdir()
    with patch.object(Tool, "TOOL_RESULT_CACHE_DIR", d):
        yield d


def _create_file(dir_path: Path, name: str, age_seconds: int) -> Path:
    """Create a file with mtime set to `age_seconds` in the past."""
    f = dir_path / name
    f.write_text("cached output")
    old_time = time.time() - age_seconds
    os.utime(f, (old_time, old_time))
    return f


class TestToolResultCacheCleanup:
    """Verify cleanup_tool_result_cache removes stale files correctly."""

    def test_removes_stale_keeps_fresh(self, cache_dir):
        """AC: files older than 1h removed, fresh files kept."""
        stale = _create_file(cache_dir, "stale_1.txt", age_seconds=7200)
        stale2 = _create_file(cache_dir, "stale_2.txt", age_seconds=3601)
        fresh = _create_file(cache_dir, "fresh.txt", age_seconds=60)

        cleanup_tool_result_cache()

        assert not stale.exists()
        assert not stale2.exists()
        assert fresh.exists()

    def test_nonexistent_dir_no_error(self, tmp_path):
        """AC: cache dir doesn't exist → no exception."""
        with patch.object(Tool, "TOOL_RESULT_CACHE_DIR", tmp_path / "nope"):
            cleanup_tool_result_cache()  # should not raise

    def test_runs_only_once(self, cache_dir):
        """AC: second call is a no-op (flag guard)."""
        stale = _create_file(cache_dir, "stale.txt", age_seconds=7200)

        cleanup_tool_result_cache()  # first call: cleans up
        # recreate a stale file after cleanup
        stale2 = _create_file(cache_dir, "stale2.txt", age_seconds=7200)

        cleanup_tool_result_cache()  # second call: no-op

        assert not stale.exists()
        assert stale2.exists(), "Second call should be a no-op"

    def test_non_files_ignored(self, cache_dir):
        """AC: subdirectories in cache dir are not removed."""
        subdir = cache_dir / "a_subdir"
        subdir.mkdir()
        old_time = time.time() - 7200
        os.utime(subdir, (old_time, old_time))

        cleanup_tool_result_cache()

        assert subdir.exists(), "Directories should not be removed"

    def test_post_process_triggers_cleanup(self, cache_dir):
        """AC: _post_process_result on long output triggers cleanup once."""
        stale = _create_file(cache_dir, "old.txt", age_seconds=7200)

        class FakeTool(Tool):
            @property
            def name(self) -> str:
                return "bash"

        tool = FakeTool(max_content_length=10)
        result = ToolResult(status=ToolStatus.SUCCESS, content="x" * 100)
        tool._post_process_result(result)

        assert not stale.exists(), "Stale file should be cleaned on first cache write"
        assert "full output is saved" in result.content
