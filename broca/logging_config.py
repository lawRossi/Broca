"""
统一的日志配置模块

日志输出策略（由 supervisor 管理时）：
  - stderr → supervisor 捕获到 backend.err.log （关键日志实时可见）
  - 文件   → ~/.broca/logs/agent.log         （完整轮转归档）

可通过环境变量覆盖：
  BROCA_LOG_DIR    日志目录（默认 ~/.broca/logs）
  BROCA_LOG_LEVEL  日志级别（默认 INFO）
"""

import os
import sys
from pathlib import Path
from typing import Optional

from loguru import logger


def get_log_dir() -> str:
    """获取日志目录，优先环境变量"""
    env_dir = os.getenv("BROCA_LOG_DIR")
    if env_dir:
        return env_dir
    return str(Path.home() / ".broca" / "logs")


def get_log_level() -> str:
    """获取日志级别，优先环境变量"""
    return os.getenv("BROCA_LOG_LEVEL", "INFO")


class LoggingConfig:
    """日志配置管理器"""

    _initialized = False

    @classmethod
    def init_logging(
        cls,
        log_file: Optional[str] = None,
        log_level: Optional[str] = None,
    ):
        """
        初始化日志配置，同时输出到 stderr 和文件。

        Args:
            log_file: 日志文件路径，默认 ~/.broca/logs/agent.log
            log_level: 日志级别，默认 INFO
        """
        if cls._initialized:
            return

        log_level = log_level or get_log_level()
        log_dir = get_log_dir()

        if log_file is None:
            log_file = os.path.join(log_dir, "agent.log")

        # 确保日志目录存在
        os.makedirs(os.path.dirname(log_file), exist_ok=True)

        # 移除默认的 stderr 处理器（loguru 自带的），替换为自定义配置
        logger.remove()

        # 1. stderr 输出（supervisor 捕获此输出）
        logger.add(
            sys.stderr,
            format="<green>{time:HH:mm:ss}</green> | <level>{level: <8}</level> | <cyan>{name}</cyan>:<cyan>{function}</cyan>:<cyan>{line}</cyan> - <level>{message}</level>",
            level=log_level,
            colorize=True,
            backtrace=True,
            diagnose=True,
        )

        # 2. 文件输出（完整轮转归档，记录更多细节）
        logger.add(
            log_file,
            format="{time:YYYY-MM-DD HH:mm:ss} | {level: <8} | {name}:{function}:{line} - {message}",
            level="DEBUG",
            rotation="10 MB",
            retention="30 days",
            compression="zip",
            encoding="utf-8",
            backtrace=True,
            diagnose=True,
        )

        cls._initialized = True
        logger.info(
            "Logging initialized: stderr=ON, file=%s, level=%s",
            log_file,
            log_level,
        )

    @classmethod
    def get_logger(cls, name: str = __name__):
        """获取 logger"""
        if not cls._initialized:
            cls.init_logging()
        return logger.bind(name=name)


def init_logging(log_file: Optional[str] = None, log_level: Optional[str] = None):
    """初始化日志配置"""
    LoggingConfig.init_logging(log_file, log_level)


def get_logger(name: str = __name__):
    """获取 logger"""
    return LoggingConfig.get_logger(name)


DEBUG = "DEBUG"
INFO = "INFO"
WARNING = "WARNING"
ERROR = "ERROR"
CRITICAL = "CRITICAL"
