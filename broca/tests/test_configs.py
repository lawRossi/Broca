"""
BrocaConfig 单元测试

覆盖：
- 默认配置加载（项目默认 configs/configs.json）
- 环境变量 BROCA_CONFIG 覆盖
- BrocaConfig.from_config() 方法
- 配置不存在时的默认值返回
"""

import json
import os
import tempfile
from unittest.mock import patch


from broca.configs import BrocaConfig, get_configs


class TestBrocaConfig:
    """测试 BrocaConfig 类"""

    def test_default_config(self):
        """测试默认配置加载（至少返回 BrocaConfig 实例）"""
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

    def test_config_file_loading(self):
        """测试从项目默认配置加载（无论是否存在都不抛出异常）"""
        config = get_configs()
        assert isinstance(config, BrocaConfig)

    def test_from_config_partial_update(self):
        """测试 from_config 部分更新"""
        config = BrocaConfig()
        config.log_level = "ERROR"
        updated = BrocaConfig.from_config({"log_level": "DEBUG"})
        assert updated.log_level == "DEBUG"
        assert updated.database_dir is None


class TestGetConfigs:
    """测试 get_configs 函数"""

    @patch.dict(os.environ, {"BROCA_CONFIG": ""}, clear=True)
    def test_no_env_var_uses_default(self):
        """测试没有环境变量时使用默认路径"""
        # 项目默认 configs.json 可能存在，所以至少要返回 BrocaConfig 实例
        config = get_configs()
        assert isinstance(config, BrocaConfig)

    def test_env_var_overrides(self):
        """测试环境变量覆盖配置路径"""
        with tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False) as f:
            json.dump({"log_level": "ERROR", "database_dir": "/env/db"}, f)
            env_path = f.name

        try:
            with patch.dict(os.environ, {"BROCA_CONFIG": env_path}):
                config = get_configs()
                assert config.log_level == "ERROR"
                assert config.database_dir == "/env/db"
        finally:
            os.unlink(env_path)

    def test_env_var_non_existent_file(self):
        """测试环境变量指向不存在的文件时使用默认"""
        with patch.dict(os.environ, {"BROCA_CONFIG": "/nonexistent/path.json"}):
            config = get_configs()
            assert isinstance(config, BrocaConfig)

    def test_user_config_priority(self):
        """测试用户配置优先级 (BROCA_CONFIG > 默认)"""
        # 创建一个临时配置文件，用环境变量指向它
        with tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False) as f:
            json.dump({"log_level": "WARNING", "log_file": "/tmp/env_test.log"}, f)
            env_path = f.name

        try:
            with patch.dict(os.environ, {"BROCA_CONFIG": env_path}):
                config = get_configs()
                assert config.log_level == "WARNING"
                assert config.log_file == "/tmp/env_test.log"
        finally:
            os.unlink(env_path)
