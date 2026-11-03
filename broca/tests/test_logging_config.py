"""
logging_config 模块单元测试
"""

import os
from pathlib import Path
from unittest.mock import patch

from broca.logging_config import get_log_dir, get_log_level, LoggingConfig


class TestGetLogDir:
    """测试 get_log_dir 函数"""

    def test_default_dir(self):
        """测试默认日志目录（configs.json 中 log_dir 为空时回退到默认）"""
        with patch("broca.configs.get_configs") as mock_gc:
            mock_gc.return_value.log_dir = ""
            log_dir = get_log_dir()
            expected = str(Path.home() / ".broca" / "logs")
            assert log_dir == expected

    def test_from_configs(self):
        """测试从 configs.json 读取日志目录"""
        with patch("broca.configs.get_configs") as mock_gc:
            mock_gc.return_value.log_dir = "/custom/log/dir"
            log_dir = get_log_dir()
            assert log_dir == "/custom/log/dir"


class TestGetLogLevel:
    """测试 get_log_level 函数"""

    def test_default_level(self):
        """测试默认日志级别"""
        with patch("broca.configs.get_configs") as mock_gc:
            mock_gc.return_value.log_level = ""
            level = get_log_level()
            assert level == "INFO"

    def test_from_configs(self):
        """测试从 configs.json 读取日志级别"""
        with patch("broca.configs.get_configs") as mock_gc:
            mock_gc.return_value.log_level = "DEBUG"
            level = get_log_level()
            assert level == "DEBUG"

    def test_error_level(self):
        """测试 ERROR 级别"""
        with patch("broca.configs.get_configs") as mock_gc:
            mock_gc.return_value.log_level = "ERROR"
            level = get_log_level()
            assert level == "ERROR"

    def test_warning_level(self):
        """测试 WARNING 级别"""
        with patch("broca.configs.get_configs") as mock_gc:
            mock_gc.return_value.log_level = "WARNING"
            level = get_log_level()
            assert level == "WARNING"


class TestLoggingConfig:
    """测试 LoggingConfig 类"""

    def test_init_logging_creates_dir(self, tmp_path):
        """测试初始化时创建日志目录"""
        LoggingConfig._initialized = False
        log_file = str(tmp_path / "test" / "agent.log")
        LoggingConfig.init_logging(log_file=log_file, log_level="INFO")
        assert (tmp_path / "test" / "agent.log").exists()
        LoggingConfig._initialized = False

    def test_get_logger_returns_bound_logger(self):
        """测试获取绑定的 logger"""
        logger = LoggingConfig.get_logger("test_module")
        assert logger is not None
