"""
BrocaConfig 单元测试

覆盖：
- 默认配置加载（项目默认 configs/configs.json）
- get_configs(config_path=...) 显式路径
- BrocaConfig.from_config() 方法
- 配置不存在时的默认值返回
"""

import json
import os
import tempfile
from pathlib import Path
from unittest.mock import patch

from broca.configs import BrocaConfig, get_configs, reset_configs_cache


class TestBrocaConfig:
    """测试 BrocaConfig 类"""

    def test_default_config(self):
        """测试默认配置加载（至少返回 BrocaConfig 实例）"""
        reset_configs_cache()
        config = get_configs()
        assert isinstance(config, BrocaConfig)

    def test_from_config_filters_unknown_keys(self):
        """测试 from_config 只保留已知属性"""
        config = BrocaConfig.from_config(
            {
                "log_level": "DEBUG",
                "unknown_key": "should_be_removed",
                "log_file": "/tmp/test.log",
            }
        )
        assert config.log_level == "DEBUG"
        assert config.log_file == "/tmp/test.log"
        assert not hasattr(config, "unknown_key")

    def test_from_config_invalid_key_not_added(self):
        """测试 from_config 不会添加未定义的属性"""
        config = BrocaConfig.from_config({"database_dir": "/tmp/db"})
        assert config.database_dir == "/tmp/db"
        # 确保其他属性有默认值
        assert config.log_level == "INFO"

    def test_from_config_empty_dict(self):
        """测试 from_config 空字典"""
        config = BrocaConfig.from_config({})
        assert config.log_level == "INFO"
        assert config.database_dir is None
        assert config.log_file is None

    def test_from_config_new_fields(self):
        """测试新增字段（log_dir, agents_config_dir, snapshot_home）"""
        config = BrocaConfig.from_config({
            "log_dir": "/custom/logs",
            "agents_config_dir": "/custom/agents",
            "snapshot_home": "/custom/snapshots",
        })
        assert config.log_dir == "/custom/logs"
        assert config.agents_config_dir == "/custom/agents"
        assert config.snapshot_home == "/custom/snapshots"

    def test_from_config_expanduser(self):
        """测试 ~ 路径展开"""
        config = BrocaConfig.from_config({"log_dir": "~/custom-logs"})
        assert config.log_dir == os.path.expanduser("~/custom-logs")
        assert not config.log_dir.startswith("~")

    def test_config_file_loading(self):
        """测试从项目默认配置加载（无论是否存在都不抛出异常）"""
        reset_configs_cache()
        config = get_configs()
        assert isinstance(config, BrocaConfig)

    def test_from_config_partial_update(self):
        """测试 from_config 部分更新"""
        config = BrocaConfig()
        config.log_level = "ERROR"
        updated = BrocaConfig.from_config({"log_level": "DEBUG"})
        assert updated.log_level == "DEBUG"
        assert updated.database_dir is None

    def test_default_log_dir(self):
        """测试默认 log_dir"""
        config = BrocaConfig()
        assert config.log_dir == os.path.expanduser("~/.broca/logs")

    def test_default_agents_config_dir(self):
        """测试默认 agents_config_dir"""
        config = BrocaConfig()
        assert config.agents_config_dir == os.path.expanduser("~/.broca/configs/agents")

    def test_default_snapshot_home(self):
        """测试默认 snapshot_home"""
        config = BrocaConfig()
        assert config.snapshot_home == os.path.expanduser("~/.broca/snapshots")


class TestGetConfigs:
    """测试 get_configs 函数"""

    def test_default_uses_project_config(self):
        """测试默认使用项目配置（或返回 BrocaConfig 实例）"""
        reset_configs_cache()
        config = get_configs()
        assert isinstance(config, BrocaConfig)

    def test_explicit_config_path(self):
        """测试显式 config_path 参数"""
        with tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False) as f:
            json.dump({"log_level": "ERROR", "database_dir": "/explicit/db"}, f)
            config_path = f.name

        try:
            config = get_configs(config_path=config_path)
            assert config.log_level == "ERROR"
            assert config.database_dir == "/explicit/db"
        finally:
            os.unlink(config_path)

    def test_non_existent_config_path(self):
        """测试显式路径不存在时回退到默认"""
        config = get_configs(config_path="/nonexistent/path.json")
        assert isinstance(config, BrocaConfig)

    def test_explicit_path_overrides_cache(self):
        """测试显式路径能覆盖缓存"""
        with tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False) as f:
            json.dump({"log_level": "WARNING", "log_file": "/tmp/explicit_test.log"}, f)
            config_path = f.name

        try:
            config = get_configs(config_path=config_path)
            assert config.log_level == "WARNING"
            assert config.log_file == "/tmp/explicit_test.log"
        finally:
            os.unlink(config_path)

    def test_enforce_production_downgrades_debug(self):
        """测试 enforce_production 将 DEBUG 降为 INFO"""
        with tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False) as f:
            json.dump({"log_level": "DEBUG"}, f)
            config_path = f.name

        try:
            config = get_configs(config_path=config_path, enforce_production=True)
            assert config.log_level == "INFO"
        finally:
            os.unlink(config_path)

    def test_reset_cache(self):
        """测试缓存重置"""
        reset_configs_cache()
        config1 = get_configs()
        assert isinstance(config1, BrocaConfig)
        reset_configs_cache()
        config2 = get_configs()
        assert isinstance(config2, BrocaConfig)
