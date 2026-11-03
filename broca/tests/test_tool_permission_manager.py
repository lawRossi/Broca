"""
ToolPermissionManager 单元测试 (Phase 4.2: merged into DefaultPermissionProvider)

覆盖：
- 配置文件加载（workspace > global）
- 权限查询（get_permission）
- 会话级别覆盖（set_session_override）
- 权限查询接口
- 边界情况
"""

import asyncio
import json
import tempfile
from pathlib import Path
from typing import Any

import pytest

from broca.permission_provider import DefaultPermissionProvider


def _make_provider(workspace: str | None = None) -> DefaultPermissionProvider:
    """Create an initialized DefaultPermissionProvider for testing."""
    provider = DefaultPermissionProvider()

    class _Cfg:
        pass

    cfg = _Cfg()
    cfg.workspace = workspace
    cfg.execution_config = None

    asyncio.run(provider.initialize(
        communicator=None,
        session_manager=None,
        config=cfg,
    ))
    return provider


class TestToolPermissionManager:
    """测试 ToolPermissionManager (now DefaultPermissionProvider)"""

    def test_init_with_no_config(self):
        """测试无配置文件时初始化为默认值"""
        with tempfile.TemporaryDirectory() as tmpdir:
            manager = _make_provider(workspace=tmpdir)
            assert manager.get_permission("any_tool") == "allow"
            assert manager.get_permission("read_file") == "allow"
            assert manager.get_permission("edit_file") == "allow"

    def test_load_config_from_workspace(self):
        """测试从 workspace 加载配置文件"""
        with tempfile.TemporaryDirectory() as tmpdir:
            config = {"tools": {"bash": "ask", "read_file": "allow", "dangerous_tool": "forbidden"}}
            config_path = Path(tmpdir) / ".broca" / "tool_permission_config.json"
            config_path.parent.mkdir(parents=True)
            config_path.write_text(json.dumps(config))

            manager = _make_provider(workspace=tmpdir)
            assert manager.get_permission("bash") == "ask"
            assert manager.get_permission("read_file") == "allow"
            assert manager.get_permission("dangerous_tool") == "forbidden"
            assert manager.get_permission("unknown_tool") == "allow"

    def test_load_config_global_fallback(self):
        """测试全局配置文件回退"""
        with tempfile.TemporaryDirectory() as tmpdir:
            # No workspace config → should fallback to global (~/.broca/configs/)
            manager = _make_provider(workspace=tmpdir)
            # The behavior depends on whether ~/.broca/configs/tool_permission_config.json exists
            # Just verify it doesn't crash
            assert manager.get_permission("any_tool") in ("allow", "ask", "forbidden")

    def test_session_override(self):
        """测试会话级别权限覆盖"""
        with tempfile.TemporaryDirectory() as tmpdir:
            config = {"tools": {"bash": "allow"}}
            config_path = Path(tmpdir) / ".broca" / "tool_permission_config.json"
            config_path.parent.mkdir(parents=True)
            config_path.write_text(json.dumps(config))

            manager = _make_provider(workspace=tmpdir)
            assert manager.get_permission("bash") == "allow"

            manager.set_session_override("bash", "forbidden")
            assert manager.get_permission("bash") == "forbidden"

            manager.set_session_override("bash", "allow")
            assert manager.get_permission("bash") == "allow"

    def test_clear_session_overrides(self):
        """测试清除会话覆盖"""
        with tempfile.TemporaryDirectory() as tmpdir:
            config = {"tools": {"bash": "allow", "edit_file": "allow"}}
            config_path = Path(tmpdir) / ".broca" / "tool_permission_config.json"
            config_path.parent.mkdir(parents=True)
            config_path.write_text(json.dumps(config))

            manager = _make_provider(workspace=tmpdir)
            manager.set_session_override("bash", "forbidden")
            manager.set_session_override("edit_file", "forbidden")

            assert manager.get_permission("bash") == "forbidden"
            assert manager.get_permission("edit_file") == "forbidden"

            manager.clear_session_overrides()
            assert manager.get_permission("bash") == "allow"
            assert manager.get_permission("edit_file") == "allow"

    def test_get_all_permissions(self):
        """测试获取所有权限"""
        with tempfile.TemporaryDirectory() as tmpdir:
            config = {"tools": {"bash": "ask", "read_file": "allow"}}
            config_path = Path(tmpdir) / ".broca" / "tool_permission_config.json"
            config_path.parent.mkdir(parents=True)
            config_path.write_text(json.dumps(config))

            manager = _make_provider(workspace=tmpdir)
            perms = manager.get_all_permissions()
            assert perms["bash"] == "ask"
            assert perms["read_file"] == "allow"

            manager.set_session_override("bash", "forbidden")
            perms = manager.get_all_permissions()
            assert perms["bash"] == "forbidden"

    def test_invalid_session_override(self):
        """测试无效的会话覆盖值"""
        from broca.errors import ValidationError

        with tempfile.TemporaryDirectory() as tmpdir:
            manager = _make_provider(workspace=tmpdir)
            with pytest.raises(ValidationError):
                manager.set_session_override("bash", "invalid_value")

    def test_invalid_config_permission(self):
        """测试配置文件中的无效权限值"""
        with tempfile.TemporaryDirectory() as tmpdir:
            config = {"tools": {"bash": "invalid_perm"}}
            config_path = Path(tmpdir) / ".broca" / "tool_permission_config.json"
            config_path.parent.mkdir(parents=True)
            config_path.write_text(json.dumps(config))

            manager = _make_provider(workspace=tmpdir)
            # Invalid permission is ignored, defaults to "allow"
            assert manager.get_permission("bash") == "allow"

    def test_config_corrupted(self):
        """测试配置文件损坏时不崩溃"""
        with tempfile.TemporaryDirectory() as tmpdir:
            config_path = Path(tmpdir) / ".broca" / "tool_permission_config.json"
            config_path.parent.mkdir(parents=True)
            config_path.write_text("not valid json {{{")

            manager = _make_provider(workspace=tmpdir)
            assert manager.get_permission("any_tool") == "allow"

    def test_workspace_config_priority_over_global(self):
        """测试 workspace 配置优先级高于全局配置"""
        with tempfile.TemporaryDirectory() as tmpdir:
            config = {"tools": {"bash": "forbidden"}}
            config_path = Path(tmpdir) / ".broca" / "tool_permission_config.json"
            config_path.parent.mkdir(parents=True)
            config_path.write_text(json.dumps(config))

            manager = _make_provider(workspace=tmpdir)
            # Workspace config takes priority
            assert manager.get_permission("bash") == "forbidden"
