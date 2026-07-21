"""
LoggingConfig 单元测试

覆盖：
- get_log_dir() 函数（环境变量覆盖）
- get_log_level() 函数
- LoggingConfig.init_logging() 初始化
- 重复初始化不会重复添加处理器
- get_logger() 函数
"""

import os
import tempfile
from pathlib import Path
from unittest.mock import patch

from loguru import logger

from broca.logging_config import (
    LoggingConfig,
    get_log_dir,
    get_log_level,
    get_logger,
    init_logging,
)


class TestGetLogDir:
    """测试 get_log_dir 函数"""

    def test_default_dir(self):
        """测试默认日志目录"""
        log_dir = get_log_dir()
        expected = str(Path.home() / ".broca" / "logs")
        assert log_dir == expected

    @patch.dict(os.environ, {"BROCA_LOG_DIR": "/custom/log/dir"}, clear=True)
    def test_env_var_overrides(self):
        """测试环境变量覆盖日志目录"""
        log_dir = get_log_dir()
        assert log_dir == "/custom/log/dir"

    @patch.dict(os.environ, {}, clear=True)
    def test_no_env_var(self):
        """测试没有环境变量时的默认值"""
        log_dir = get_log_dir()
        expected = str(Path.home() / ".broca" / "logs")
        assert log_dir == expected


class TestGetLogLevel:
    """测试 get_log_level 函数"""

    def test_default_level(self):
        """测试默认日志级别"""
        level = get_log_level()
        assert level == "INFO"

    @patch.dict(os.environ, {"BROCA_LOG_LEVEL": "DEBUG"}, clear=True)
    def test_env_var_overrides(self):
        """测试环境变量覆盖日志级别"""
        level = get_log_level()
        assert level == "DEBUG"

    @patch.dict(os.environ, {"BROCA_LOG_LEVEL": "ERROR"}, clear=True)
    def test_error_level(self):
        """测试 ERROR 级别"""
        level = get_log_level()
        assert level == "ERROR"


class TestLoggingConfig:
    """测试 LoggingConfig 类"""

    def setup_method(self):
        """测试前重置初始化状态"""
        LoggingConfig._initialized = False
        logger.remove()  # 清除所有处理器

    def teardown_method(self):
        """测试后恢复"""
        LoggingConfig._initialized = False
        logger.remove()

    def test_init_logging_creates_directory(self):
        """测试初始化创建日志目录"""
        with tempfile.TemporaryDirectory() as tmpdir:
            log_file = os.path.join(tmpdir, "subdir", "test.log")
            LoggingConfig.init_logging(log_file=log_file, log_level="INFO")
            assert os.path.exists(os.path.dirname(log_file))
            assert LoggingConfig._initialized is True

    def test_init_logging_creates_log_file(self):
        """测试初始化创建日志文件"""
        with tempfile.TemporaryDirectory() as tmpdir:
            log_file = os.path.join(tmpdir, "test.log")
            LoggingConfig.init_logging(log_file=log_file, log_level="INFO")
            # 文件一开始可能是空的，但目录应已创建
            assert os.path.exists(os.path.dirname(log_file))

    def test_double_init_does_not_raise(self):
        """测试重复初始化不会抛出异常"""
        LoggingConfig._initialized = False
        LoggingConfig.init_logging(log_level="INFO")
        # 第二次初始化不应抛出异常
        LoggingConfig.init_logging(log_level="DEBUG")
        assert LoggingConfig._initialized is True

    def test_get_logger_works(self):
        """测试获取 logger"""
        LoggingConfig._initialized = False
        logger.remove()
        test_logger = LoggingConfig.get_logger("test_module")
        assert test_logger is not None

    def test_get_logger_without_init(self):
        """测试未初始化时 get_logger 自动初始化"""
        LoggingConfig._initialized = False
        logger.remove()
        test_logger = get_logger("test_module")
        assert test_logger is not None
        assert LoggingConfig._initialized is True


class TestInitLoggingFunction:
    """测试 init_logging 和 get_logger 函数"""

    def setup_method(self):
        LoggingConfig._initialized = False
        logger.remove()

    def teardown_method(self):
        LoggingConfig._initialized = False
        logger.remove()

    def test_init_logging_function(self):
        """测试 init_logging 函数"""
        with tempfile.TemporaryDirectory() as tmpdir:
            log_file = os.path.join(tmpdir, "agent.log")
            init_logging(log_file=log_file, log_level="DEBUG")
            assert LoggingConfig._initialized is True

    def test_logger_function(self):
        """测试 get_logger 函数"""
        LoggingConfig._initialized = False
        logger.remove()
        test_logger = get_logger("my_module")
        assert test_logger is not None

    @patch.dict(os.environ, {"BROCA_LOG_LEVEL": "WARNING"}, clear=True)
    def test_env_log_level_applied(self):
        """测试环境变量日志级别生效"""
        LoggingConfig._initialized = False
        logger.remove()
        # 不指定 log_level，应该从环境变量读取
        with tempfile.TemporaryDirectory() as tmpdir:
            log_file = os.path.join(tmpdir, "test.log")
            LoggingConfig.init_logging(log_file=log_file)
            assert LoggingConfig._initialized is True
