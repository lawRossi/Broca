"""
logging_config 模块单元测试
"""

import logging
import os
import threading
from pathlib import Path
from unittest.mock import patch

import pytest

from broca.logging_config import (
    LoggingConfig,
    _StdlibLoguruBridge,
    get_log_dir,
    get_log_level,
    get_logger,
    get_runner_log_backup_days,
    init_logging,
)


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
    """测试 LoggingConfig 类（主进程模式）"""

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


# ---------------------------------------------------------------------------
# 子进程模式测试
# ---------------------------------------------------------------------------


class TestChildProcessMode:
    """测试子进程模式（BROCA_RUNNER_CHILD=1）"""

    def test_get_logger_returns_stdlib(self, monkeypatch):
        """子进程中 get_logger 应返回 stdlib logging.Logger"""
        monkeypatch.setenv("BROCA_RUNNER_CHILD", "1")
        logger = get_logger("test.child.module")
        assert isinstance(logger, logging.Logger)
        # 不应该是 loguru logger
        from loguru import logger as loguru_logger

        assert type(logger) is not type(loguru_logger)

    def test_init_child_creates_timed_handler(self, monkeypatch, tmp_path):
        """子进程 init_logging 应创建 TimedRotatingFileHandler"""
        monkeypatch.setenv("BROCA_RUNNER_CHILD", "1")
        LoggingConfig._initialized = False
        log_file = str(tmp_path / "runner.log")
        init_logging(log_file=log_file, log_level="INFO")

        root = logging.getLogger()
        handler_types = [type(h).__name__ for h in root.handlers]
        assert "TimedRotatingFileHandler" in handler_types
        assert "StreamHandler" in handler_types
        LoggingConfig._initialized = False

    def test_init_child_no_bridge(self, monkeypatch, tmp_path):
        """子进程 init_logging 不应安装 _StdlibLoguruBridge"""
        monkeypatch.setenv("BROCA_RUNNER_CHILD", "1")
        LoggingConfig._initialized = False
        init_logging(log_file=str(tmp_path / "runner.log"), log_level="INFO")

        root = logging.getLogger()
        handler_types = [type(h).__name__ for h in root.handlers]
        assert "_StdlibLoguruBridge" not in handler_types
        LoggingConfig._initialized = False

    def test_get_logger_no_auto_init_in_child(self, monkeypatch):
        """子进程中 get_logger 不应触发自动初始化"""
        monkeypatch.setenv("BROCA_RUNNER_CHILD", "1")
        LoggingConfig._initialized = False
        logger = get_logger("test")
        # 不应触发 init_logging
        assert LoggingConfig._initialized is False

    def test_init_child_no_log_file(self, monkeypatch):
        """子进程无 log_file 时仅配置 stderr handler"""
        monkeypatch.setenv("BROCA_RUNNER_CHILD", "1")
        LoggingConfig._initialized = False
        init_logging(log_file=None, log_level="INFO")

        root = logging.getLogger()
        handler_types = [type(h).__name__ for h in root.handlers]
        assert "StreamHandler" in handler_types
        # 没有文件 handler
        LoggingConfig._initialized = False


class TestChildProcessLoggingIsolation:
    """回归测试：子进程中 crew 编排不应破坏 per-session 日志隔离。

    原 bug：orchestrator_runner.py 的 get_logger() 触发 init_logging()，
    将 root.handlers 替换为 [_StdlibLoguruBridge]，覆盖了 setup_logging()
    配置的 TimedRotatingFileHandler。
    """

    def test_init_in_child_does_not_install_bridge(self, monkeypatch, tmp_path):
        """子进程 init_logging 只配置 stdlib handler，不安装 loguru bridge"""
        monkeypatch.setenv("BROCA_RUNNER_CHILD", "1")
        LoggingConfig._initialized = False
        init_logging(log_file=str(tmp_path / "runner.log"))
        root = logging.getLogger()
        handler_types = [type(h).__name__ for h in root.handlers]
        assert "_StdlibLoguruBridge" not in handler_types
        assert "TimedRotatingFileHandler" in handler_types
        LoggingConfig._initialized = False

    def test_get_logger_in_child_does_not_clobber_handlers(self, monkeypatch, tmp_path):
        """子进程中 get_logger() 不改变 root logger handlers"""
        monkeypatch.setenv("BROCA_RUNNER_CHILD", "1")
        LoggingConfig._initialized = False
        init_logging(log_file=str(tmp_path / "runner.log"))
        handlers_before = list(logging.getLogger().handlers)
        # 模拟 orchestrator_runner 模块 import 时的 get_logger 调用
        get_logger("broca.session_runner.orchestrator_runner")
        handlers_after = list(logging.getLogger().handlers)
        assert handlers_before == handlers_after
        LoggingConfig._initialized = False


# ---------------------------------------------------------------------------
# 线程安全测试
# ---------------------------------------------------------------------------


class TestThreadSafety:
    """测试 init_logging 的线程安全性"""

    def test_concurrent_init(self, monkeypatch, tmp_path):
        """10 个线程并发调用 init_logging，验证无异常且仅初始化一次"""
        monkeypatch.delenv("BROCA_RUNNER_CHILD", raising=False)
        LoggingConfig._initialized = False
        log_file = str(tmp_path / "thread_test.log")

        results = []
        barrier = threading.Barrier(10)

        def _init():
            try:
                barrier.wait(timeout=5)
                init_logging(log_file=log_file, log_level="INFO")
                results.append("ok")
            except Exception as e:
                results.append(f"error: {e}")

        threads = [threading.Thread(target=_init) for _ in range(10)]
        for t in threads:
            t.start()
        for t in threads:
            t.join(timeout=10)

        assert len(results) == 10
        errors = [r for r in results if r.startswith("error")]
        assert not errors, f"Concurrent init errors: {errors}"
        assert LoggingConfig._initialized is True
        LoggingConfig._initialized = False


# ---------------------------------------------------------------------------
# Diagnose 标志测试
# ---------------------------------------------------------------------------


class TestDiagnoseFlag:
    """测试 diagnose 参数仅在 DEBUG 级别启用"""

    def test_diagnose_disabled_at_info(self, monkeypatch, tmp_path):
        """INFO 级别时所有 loguru handler 的 diagnose 为 False。

        通过 mock _loguru_logger.add() 捕获传入的 diagnose 参数值。
        """
        monkeypatch.delenv("BROCA_RUNNER_CHILD", raising=False)
        LoggingConfig._initialized = False

        from unittest.mock import MagicMock, patch as mock_patch

        with mock_patch("broca.logging_config._loguru_logger") as mock_logger:
            mock_logger.remove = MagicMock()
            mock_logger.bind = MagicMock(return_value=mock_logger)

            init_logging(log_file=str(tmp_path / "agent.log"), log_level="INFO")

            # 验证每次 add() 调用都传入了 diagnose=False
            assert mock_logger.add.call_count == 2  # stderr + file
            for call in mock_logger.add.call_args_list:
                kwargs = call[1] if call[1] else {}
                assert kwargs.get("diagnose") is False, (
                    f"INFO 级别时 diagnose 应为 False，"
                    f"实际为 {kwargs.get('diagnose')}"
                )
        LoggingConfig._initialized = False

    def test_diagnose_enabled_at_debug(self, monkeypatch, tmp_path):
        """DEBUG 级别时所有 loguru handler 的 diagnose 为 True。"""
        monkeypatch.delenv("BROCA_RUNNER_CHILD", raising=False)
        LoggingConfig._initialized = False

        from unittest.mock import MagicMock, patch as mock_patch

        with mock_patch("broca.logging_config._loguru_logger") as mock_logger:
            mock_logger.remove = MagicMock()
            mock_logger.bind = MagicMock(return_value=mock_logger)

            init_logging(log_file=str(tmp_path / "agent.log"), log_level="DEBUG")

            # 验证每次 add() 调用都传入了 diagnose=True
            assert mock_logger.add.call_count == 2  # stderr + file
            for call in mock_logger.add.call_args_list:
                kwargs = call[1] if call[1] else {}
                assert kwargs.get("diagnose") is True, (
                    f"DEBUG 级别时 diagnose 应为 True，"
                    f"实际为 {kwargs.get('diagnose')}"
                )
        LoggingConfig._initialized = False


# ---------------------------------------------------------------------------
# Runner launcher 环境变量测试
# ---------------------------------------------------------------------------


class TestRunnerLauncherEnv:
    """测试 build_runner_env 注入 BROCA_RUNNER_CHILD"""

    def test_build_runner_env_has_child_flag(self):
        """build_runner_env() 返回的 dict 包含 BROCA_RUNNER_CHILD=1"""
        from broca.session_runner.process.launcher import build_runner_env

        env = build_runner_env()
        assert env.get("BROCA_RUNNER_CHILD") == "1"


# ---------------------------------------------------------------------------
# get_runner_log_backup_days 测试
# ---------------------------------------------------------------------------


class TestGetRunnerLogBackupDays:
    """测试 get_runner_log_backup_days"""

    def test_default(self):
        """无配置时默认 7 天"""
        with patch("broca.configs.get_configs") as mock_gc:
            mock_gc.return_value.execution = type(
                "Cfg", (), {"runner_log_backup_days": 7}
            )
            days = get_runner_log_backup_days()
            assert days == 7

    def test_custom_value(self):
        """自定义天数"""
        with patch("broca.configs.get_configs") as mock_gc:
            mock_gc.return_value.execution = type(
                "Cfg", (), {"runner_log_backup_days": 14}
            )
            days = get_runner_log_backup_days()
            assert days == 14


# ---------------------------------------------------------------------------
# 死锁回归测试
# ---------------------------------------------------------------------------


class TestConfigsDeadlockRegression:
    """回归测试：configs.py 模块级代码不得触发 init_logging() 死锁。

    原 bug：configs.py 曾有模块级 ``logger = get_logger(__name__)``。
    当 ``logging_config.init_logging()`` 内部 lazy import ``broca.configs`` 时，
    configs.py 的模块级 ``get_logger()`` 再次调用 ``init_logging()``，
    在 ``threading.Lock``（非 reentrant）上死锁。

    修复：configs.py 使用 ``_get_logger()`` 惰性函数，不在模块级
    调用 ``get_logger()``。
    """

    def test_configs_has_no_module_level_logger(self):
        """configs.py 不得有模块级 'logger' 变量（会触发 init_logging 死锁）。"""
        import broca.configs

        assert not hasattr(broca.configs, "logger"), (
            "configs.py 不能有模块级 'logger' 变量。"
            "模块级 get_logger() 会触发 init_logging()，"
            "而 init_logging() 内部会 lazy import configs 形成死锁。"
            "请使用 _get_logger() 惰性函数。"
        )

    def test_configs_has_lazy_get_logger(self):
        """configs.py 必须有 _get_logger 惰性函数。"""
        import broca.configs

        assert hasattr(broca.configs, "_get_logger"), (
            "configs.py 应提供 _get_logger() 惰性函数用于日志记录。"
        )
        import inspect

        assert callable(broca.configs._get_logger)

    def test_import_session_runner_does_not_deadlock(self):
        """导入 broca.session_runner 必须在合理时间内完成（不触发死锁）。

        此测试在 pytest 正常超时保护下运行。如果死锁回归，
        此测试将超时失败。
        """
        # broca.session_runner 的导入已在 test collection 时完成，
        # 这里显式验证模块可访问（如果死锁则 collection 阶段就挂了）
        import broca.session_runner.models  # noqa: F401
        import broca.session_runner.manager  # noqa: F401

        assert True  # 走到这里说明没有死锁
