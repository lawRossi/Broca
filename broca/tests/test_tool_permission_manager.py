"""
ToolPermissionManager 单元测试

覆盖：
- 配置文件加载（workspace > global）
- 权限查询（get_permission）
- 会话级别覆盖（set_session_override）
- 权限查询接口
- 边界情况
"""

import json
import tempfile
from pathlib import Path

import pytest

from broca.tools.tool_permission_manager import ToolPermissionManager


class TestToolPermissionManager:
    """测试 ToolPermissionManager"""

    def test_init_with_no_config(self):
        """测试无配置文件时初始化为默认值"""
        # 使用临时目录作为 workspace，确保没有 .broca/tool_permission_config.json
        with tempfile.TemporaryDirectory() as tmpdir:
            manager = ToolPermissionManager(workspace=tmpdir)
            # 没有配置文件，所有工具默认 allow
            assert manager.get_permission("any_tool") == "allow"
            assert manager.get_permission("read_file") == "allow"
            assert manager.get_permission("edit_file") == "allow"

    def test_load_config_from_workspace(self):
        """测试从 workspace 加载配置文件"""
        with tempfile.TemporaryDirectory() as tmpdir:
            # 创建 .broca 目录和配置文件
            config_dir = Path(tmpdir) / ".broca"
            config_dir.mkdir()
            config_file = config_dir / "tool_permission_config.json"
            config_data = {
                "tools": {
                    "read_file": "allow",
                    "edit_file": "ask",
                    "bash": "forbidden",
                }
            }
            with open(config_file, "w") as f:
                json.dump(config_data, f)

            manager = ToolPermissionManager(workspace=tmpdir)
            assert manager.get_permission("read_file") == "allow"
            assert manager.get_permission("edit_file") == "ask"
            assert manager.get_permission("bash") == "forbidden"

    def test_load_config_ignores_global(self):
        """测试 workspace 配置优先于全局配置"""
        # 注意：此测试可能受用户实际 ~/.broca/configs/tool_permission_config.json 影响
        # 所以我们使用临时目录作为 workspace 并创建配置文件
        with tempfile.TemporaryDirectory() as tmpdir:
            config_dir = Path(tmpdir) / ".broca"
            config_dir.mkdir()
            config_file = config_dir / "tool_permission_config.json"
            with open(config_file, "w") as f:
                json.dump({"tools": {"bash": "forbidden"}}, f)

            manager = ToolPermissionManager(workspace=tmpdir)
            assert manager.get_permission("bash") == "forbidden"

    def test_session_override(self):
        """测试会话级别覆盖"""
        with tempfile.TemporaryDirectory() as tmpdir:
            manager = ToolPermissionManager(workspace=tmpdir)
            # 默认是 allow
            assert manager.get_permission("bash") == "allow"

            # 设置为 forbidden
            manager.set_session_override("bash", "forbidden")
            assert manager.get_permission("bash") == "forbidden"

            # 移除覆盖
            manager.remove_session_override("bash")
            assert manager.get_permission("bash") == "allow"

    def test_session_override_precedence(self):
        """测试会话覆盖优先级高于配置文件"""
        with tempfile.TemporaryDirectory() as tmpdir:
            config_dir = Path(tmpdir) / ".broca"
            config_dir.mkdir()
            config_file = config_dir / "tool_permission_config.json"
            with open(config_file, "w") as f:
                json.dump({"tools": {"bash": "forbidden"}}, f)

            manager = ToolPermissionManager(workspace=tmpdir)
            # 配置文件设置 bash 为 forbidden
            assert manager.get_permission("bash") == "forbidden"

            # 会话覆盖为 allow
            manager.set_session_override("bash", "allow")
            assert manager.get_permission("bash") == "allow"

    def test_clear_session_overrides(self):
        """测试清除所有会话覆盖"""
        with tempfile.TemporaryDirectory() as tmpdir:
            manager = ToolPermissionManager(workspace=tmpdir)
            manager.set_session_override("bash", "forbidden")
            manager.set_session_override("read_file", "forbidden")
            assert manager.get_permission("bash") == "forbidden"

            manager.clear_session_overrides()
            assert manager.get_permission("bash") == "allow"

    def test_get_all_permissions(self):
        """测试获取所有权限"""
        with tempfile.TemporaryDirectory() as tmpdir:
            config_dir = Path(tmpdir) / ".broca"
            config_dir.mkdir()
            config_file = config_dir / "tool_permission_config.json"
            with open(config_file, "w") as f:
                json.dump({"tools": {"bash": "forbidden"}}, f)

            manager = ToolPermissionManager(workspace=tmpdir)
            all_perms = manager.get_all_permissions()
            assert "bash" in all_perms
            assert all_perms["bash"] == "forbidden"

    def test_get_configured_permissions(self):
        """测试获取配置的权限（不含会话覆盖）"""
        with tempfile.TemporaryDirectory() as tmpdir:
            config_dir = Path(tmpdir) / ".broca"
            config_dir.mkdir()
            config_file = config_dir / "tool_permission_config.json"
            with open(config_file, "w") as f:
                json.dump({"tools": {"bash": "forbidden"}}, f)

            manager = ToolPermissionManager(workspace=tmpdir)
            configured = manager.get_configured_permissions()

            # 设置会话覆盖后，get_configured_permissions 不应包含覆盖
            manager.set_session_override("bash", "allow")
            configured_after = manager.get_configured_permissions()
            assert configured == configured_after
            assert configured["bash"] == "forbidden"

    def test_get_session_overrides(self):
        """测试获取会话覆盖"""
        with tempfile.TemporaryDirectory() as tmpdir:
            manager = ToolPermissionManager(workspace=tmpdir)
            assert manager.get_session_overrides() == {}

            manager.set_session_override("bash", "forbidden")
            overrides = manager.get_session_overrides()
            assert "bash" in overrides
            assert overrides["bash"] == "forbidden"

    def test_invalid_session_override(self):
        """测试无效的会话覆盖值"""
        with tempfile.TemporaryDirectory() as tmpdir:
            manager = ToolPermissionManager(workspace=tmpdir)
            with pytest.raises(Exception):
                manager.set_session_override("bash", "invalid_value")

    def test_config_load_failure_graceful(self):
        """测试配置文件损坏时优雅处理"""
        with tempfile.TemporaryDirectory() as tmpdir:
            config_dir = Path(tmpdir) / ".broca"
            config_dir.mkdir()
            config_file = config_dir / "tool_permission_config.json"
            # 写入无效 JSON
            with open(config_file, "w") as f:
                f.write("not valid json")

            # 不应抛出异常
            manager = ToolPermissionManager(workspace=tmpdir)
            # 应该回退到 allow
            assert manager.get_permission("any_tool") == "allow"

    def test_unknown_tool_defaults_to_allow(self):
        """测试未知工具默认 allow"""
        with tempfile.TemporaryDirectory() as tmpdir:
            config_dir = Path(tmpdir) / ".broca"
            config_dir.mkdir()
            config_file = config_dir / "tool_permission_config.json"
            with open(config_file, "w") as f:
                json.dump({"tools": {"bash": "forbidden"}}, f)

            manager = ToolPermissionManager(workspace=tmpdir)
            # 未配置的工具默认 allow
            assert manager.get_permission("unknown_tool") == "allow"
