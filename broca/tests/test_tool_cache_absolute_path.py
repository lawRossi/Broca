"""
Regression test: Tool result cache uses absolute workspace path, not CWD.

Before the fix, `TOOL_RESULT_CACHE_DIR = Path(".broca/tool_result_cache")`
was relative to CWD, so `os.chdir()` would change where cache files are written.
After the fix, `_get_cache_dir(workspace)` returns an absolute path based on
the workspace directory.
"""

import os
from pathlib import Path
from unittest.mock import patch

import pytest

from broca.tools.tool import Tool, ToolResult, ToolStatus


class TestCacheDirResolution:
    """_get_cache_dir returns correct absolute paths."""

    def test_workspace_provided(self, tmp_path):
        """When workspace is given, cache dir is under workspace."""
        tool = Tool()
        workspace = str(tmp_path / "my_project")
        result = tool._get_cache_dir(workspace)
        assert result == Path(workspace) / ".broca" / "tool_result_cache"
        assert result.is_absolute()

    def test_no_workspace_falls_back_to_cwd(self, tmp_path):
        """When workspace is None, falls back to CWD-based path."""
        tool = Tool()
        os.chdir(str(tmp_path))
        result = tool._get_cache_dir(None)
        assert result.is_absolute()
        assert ".broca" in str(result)
        assert "tool_result_cache" in str(result)

    def test_chdir_does_not_affect_workspace_path(self, tmp_path):
        """Changing CWD does not affect workspace-based cache path."""
        tool = Tool()
        workspace = str(tmp_path / "stable_project")
        expected = tool._get_cache_dir(workspace)

        # Change CWD to somewhere else
        elsewhere = tmp_path / "elsewhere"
        elsewhere.mkdir()
        os.chdir(str(elsewhere))
        actual = tool._get_cache_dir(workspace)
        assert actual == expected

    def test_empty_string_workspace(self, tmp_path):
        """Empty string workspace is treated as falsy → CWD fallback."""
        tool = Tool()
        os.chdir(str(tmp_path))
        result = tool._get_cache_dir("")
        assert result.is_absolute()
        # Should use CWD, not Path("")
        assert str(tmp_path) in str(result)


class _TestTool(Tool):
    """Concrete tool with a fixed name for testing."""
    @property
    def name(self):
        return "test_tool"


class TestPostProcessResultWithWorkspace:
    """_post_process_result writes cache file to workspace directory."""

    def test_cache_file_written_to_workspace(self, tmp_path):
        """Long output is cached in {workspace}/.broca/tool_result_cache/."""
        tool = _TestTool(max_content_length=50)
        workspace = str(tmp_path / "ws")
        Path(workspace).mkdir(parents=True)

        result = ToolResult(
            status=ToolStatus.SUCCESS,
            content="x" * 200,  # exceeds max_content_length
        )
        processed = tool._post_process_result(result, workspace=workspace)

        # Content should be truncated (has the ellipsis marker)
        assert "..." in processed.content
        assert "truncated" in processed.content
        # Cache file should exist in workspace
        cache_dir = Path(workspace) / ".broca" / "tool_result_cache"
        assert cache_dir.exists()
        files = list(cache_dir.glob("*.txt"))
        assert len(files) == 1

    def test_short_output_no_cache(self, tmp_path):
        """Short output doesn't create a cache file."""
        tool = _TestTool(max_content_length=1000)
        workspace = str(tmp_path / "ws")
        Path(workspace).mkdir(parents=True)

        result = ToolResult(
            status=ToolStatus.SUCCESS,
            content="short",
        )
        processed = tool._post_process_result(result, workspace=workspace)
        assert processed.content == "short"
        cache_dir = Path(workspace) / ".broca" / "tool_result_cache"
        assert not cache_dir.exists()
