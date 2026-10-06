"""
统一的日志配置模块

日志输出策略（由 supervisor 管理时）：
  - stderr → supervisor 捕获到 backend.err.log （关键日志实时可见）
  - 文件   → ~/.broca/logs/agent.log         （完整轮转归档）

可通过环境变量覆盖：
  BROCA_LOG_DIR    日志目录（默认 ~/.broca/logs）
  BROCA_LOG_LEVEL  日志级别（默认 INFO）
"""

import logging
import os
import sys
from pathlib import Path
from typing import Optional

from loguru import logger


class _StdlibLoguruBridge(logging.Handler):
    """将标准库 logging 的 record 转发到 loguru。

    这样项目中任何使用 ``logging.getLogger()`` 的模块（如 ASR 服务）
    的日志都能通过 loguru 的统一管道输出。
    """

    def emit(self, record: logging.LogRecord):
        try:
            level = logger.level(record.levelname).name
        except ValueError:
            level = record.levelno

        # 找到真正的调用者（跳过 logging 内部帧）
        frame_info = sys._getframe(0)
        while frame_info and frame_info.f_code.co_filename.endswith("logging/__init__.py"):
            frame_info = frame_info.f_back
        if frame_info:
            record = logging.makeLogRecord(record.__dict__)
            record.pathname = frame_info.f_code.co_filename
            record.lineno = frame_info.f_lineno
            record.funcName = frame_info.f_code.co_name

        logger.opt(depth=0, exception=record.exc_info).log(level, record.getMessage())


def get_log_dir() -> str:
    """获取日志目录，优先环境变量"""
    env_dir = os.getenv("BROCA_LOG_DIR")
    if env_dir:
        return env_dir
    return str(Path.home() / ".broca" / "logs")


def get_log_level() -> str:
    """获取日志级别，优先级：环境变量 > configs.json > 默认 INFO"""
    env_level = os.getenv("BROCA_LOG_LEVEL")
    if env_level:
        return env_level
    # 尝试从配置文件读取
    try:
        config_path = _resolve_config_file()
        if config_path and config_path.exists():
            import json
            with open(config_path) as f:
                data = json.load(f)
            level = data.get("log_level")
            if level:
                return level.upper()
    except Exception:
        pass
    return "INFO"


def _resolve_config_file() -> Optional[Path]:
    """解析配置文件路径（与 app/api/config.py 逻辑一致）"""
    env_path = os.getenv("BROCA_CONFIG")
    if env_path:
        return Path(env_path).expanduser()
    new_path = Path.home() / ".broca" / "configs" / "configs.json"
    if new_path.exists():
        return new_path
    legacy_path = Path.home() / ".broca" / "configs.json"
    if legacy_path.exists():
        return legacy_path
    return None


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
            level=log_level,
            rotation="10 MB",
            retention="3 days",
            compression="zip",
            encoding="utf-8",
            backtrace=True,
            diagnose=True,
        )

        # 3. 桥接标准库 logging → loguru
        #    使 logging.getLogger("broca.asr") 等标准 logging 调用
        #    也能通过 loguru 管道输出
        bridge = _StdlibLoguruBridge()
        root = logging.getLogger()
        root.handlers = [bridge]  # 替换默认 handler，避免重复
        root.setLevel(getattr(logging, log_level.upper(), logging.INFO))

        cls._initialized = True

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
