"""
统一的日志配置模块

日志输出策略（由 supervisor 管理时）：
  - stderr → supervisor 捕获到 backend.err.log （关键日志实时可见）
  - 文件   → ~/.broca/logs/agent.log         （完整轮转归档）

配置来源：configs.json（通过 get_configs() 读取）
  - log_dir: 日志目录（默认 ~/.broca/logs）
  - log_level: 日志级别（默认 INFO）
  - log_file: 日志文件路径

使用规范：
  • 所有模块统一使用 ``from broca.logging_config import get_logger``
  • 禁止直接 ``logging.getLogger()`` 或 ``from loguru import logger``
  • 日志调用支持 f-string 和 %s 两种格式（均兼容）
  • 子进程（BROCA_RUNNER_CHILD=1）自动切换为 stdlib 后端
  • 手动启动 ``python -m broca.session_runner.runner`` 时，``main()`` 内通过
    ``os.environ.setdefault("BROCA_RUNNER_CHILD", "1")`` 兜底确保走 stdlib 模式
  • 例外：broca/alembic/env.py 使用 alembic 专用的 fileConfig
"""

import logging
import os
import sys
import threading
from logging.handlers import TimedRotatingFileHandler
from pathlib import Path
from typing import Optional

from loguru import logger as _loguru_logger


# ---------------------------------------------------------------------------
# 子进程检测
# ---------------------------------------------------------------------------

def _is_runner_child() -> bool:
    """判断当前是否运行在 runner 子进程中。

    由 ``RunnerLauncher.build_runner_env()`` 注入 ``BROCA_RUNNER_CHILD=1``。
    """
    return os.environ.get("BROCA_RUNNER_CHILD") == "1"


# ---------------------------------------------------------------------------
# 线程安全锁
# ---------------------------------------------------------------------------

_init_lock = threading.Lock()


# ---------------------------------------------------------------------------
# 辅助函数
# ---------------------------------------------------------------------------

def get_runner_log_backup_days() -> int:
    """获取 runner 日志备份天数，从 configs 读取，默认 7。"""
    try:
        from broca.configs import get_configs

        value = getattr(get_configs().execution, "runner_log_backup_days", 7)
        return int(value)
    except Exception:
        return 7


def get_gc_interval() -> int:
    """获取 runner 日志 GC 间隔（秒），从 configs 读取，默认 3600。"""
    try:
        from broca.configs import get_configs

        value = getattr(get_configs().execution, "runner_log_gc_interval", 3600)
        return int(value)
    except Exception:
        return 3600


# ---------------------------------------------------------------------------
# 配置读取
# ---------------------------------------------------------------------------

def get_log_dir() -> str:
    """获取日志目录，从 configs.json 读取"""
    try:
        from broca.configs import get_configs

        log_dir = get_configs().log_dir
        if log_dir:
            return log_dir
    except (ImportError, OSError, AttributeError):
        pass
    return str(Path.home() / ".broca" / "logs")


# 有效的日志级别白名单
VALID_LOG_LEVELS = {"DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"}


def get_log_level() -> str:
    """获取日志级别，从 configs.json 读取，默认 INFO。

    非法值会触发 WARNING 并回退到 "INFO"。
    """
    try:
        from broca.configs import get_configs

        level = get_configs().log_level
        if level:
            level = level.upper()
            if level in VALID_LOG_LEVELS:
                return level
            import logging as _logging

            _logging.getLogger(__name__).warning(
                "Invalid log_level '%s' in config, falling back to INFO", level
            )
    except (ImportError, OSError, AttributeError):
        pass
    return "INFO"


# ---------------------------------------------------------------------------
# 桥接器（仅主进程使用）
# ---------------------------------------------------------------------------

class _StdlibLoguruBridge(logging.Handler):
    """将标准库 logging 的 record 转发到 loguru。

    这样项目中任何使用 ``logging.getLogger()`` 的模块（如 ASR 服务）
    的日志都能通过 loguru 的统一管道输出。

    注意：CPython 的 ``Logger.makeRecord()`` 已正确填充了
    ``record.pathname``、``record.lineno``、``record.funcName``
    （指向真正的调用者），无需二次帧遍历。
    """

    def emit(self, record: logging.LogRecord):
        try:
            level = _loguru_logger.level(record.levelname).name
        except ValueError:
            level = record.levelno

        _loguru_logger.opt(depth=0, exception=record.exc_info).log(
            level, record.getMessage()
        )


# ---------------------------------------------------------------------------
# 子进程日志初始化（stdlib 后端）
# ---------------------------------------------------------------------------

def _init_child_logging(log_file: Optional[str], log_level: str) -> None:
    """子进程模式：使用 stdlib logging，配置 root logger。

    Args:
        log_file: 日志文件路径（可为 None，此时仅输出到 stderr）
        log_level: 日志级别字符串，如 "INFO"、"DEBUG"
    """
    handlers: list[logging.Handler] = [logging.StreamHandler(sys.stderr)]
    if log_file:
        log_dir = os.path.dirname(log_file)
        if log_dir:
            os.makedirs(log_dir, exist_ok=True)
        handlers.append(
            TimedRotatingFileHandler(
                log_file,
                when="midnight",
                backupCount=get_runner_log_backup_days(),
                encoding="utf-8",
            )
        )
    root = logging.getLogger()
    root.handlers = handlers
    root.setLevel(getattr(logging, log_level.upper(), logging.INFO))
    root.propagate = False


# ---------------------------------------------------------------------------
# 核心类
# ---------------------------------------------------------------------------

class LoggingConfig:
    """日志配置管理器，支持主进程（loguru）和子进程（stdlib）双模式。"""

    _initialized = False

    @classmethod
    def init_logging(
        cls,
        log_file: Optional[str] = None,
        log_level: Optional[str] = None,
    ):
        """
        初始化日志配置。

        主进程模式：输出到 stderr + 文件（loguru），并桥接 stdlib logging → loguru。
        子进程模式（BROCA_RUNNER_CHILD=1）：stdlib logging，root logger + 文件 handler。

        Args:
            log_file: 日志文件路径
            log_level: 日志级别
        """
        with _init_lock:
            if cls._initialized:
                return

            log_level = log_level or get_log_level()
            # 白名单校验：非法值回退 INFO
            if log_level.upper() not in VALID_LOG_LEVELS:
                logging.getLogger(__name__).warning(
                    "Invalid log_level '%s', falling back to INFO", log_level
                )
                log_level = "INFO"
            log_dir = get_log_dir()

            # 子进程模式
            if _is_runner_child():
                if log_file is None:
                    log_file = os.path.join(log_dir, "runner.log")
                _init_child_logging(log_file, log_level)
                cls._initialized = True
                return

            # 主进程模式
            if log_file is None:
                try:
                    from broca.configs import get_configs

                    cfg_log_file = get_configs().log_file
                    if cfg_log_file:
                        log_file = cfg_log_file
                except Exception:
                    pass

                if log_file is None:
                    log_file = os.path.join(log_dir, "agent.log")

            # 确保日志目录存在
            log_file_path = Path(log_file).expanduser()
            os.makedirs(log_file_path.parent, exist_ok=True)

            # diagnose 仅在 DEBUG 级别启用（避免生产环境信息泄露）
            diagnose = log_level.upper() == "DEBUG"

            # 移除默认的 stderr 处理器（loguru 自带的），替换为自定义配置
            _loguru_logger.remove()

            # 1. stderr 输出（supervisor 捕获此输出）
            _loguru_logger.add(
                sys.stderr,
                format=(
                    "<green>{time:HH:mm:ss}</green> | <level>{level: <8}</level> | "
                    "<cyan>{name}</cyan>:<cyan>{function}</cyan>:<cyan>{line}</cyan> - "
                    "<level>{message}</level>"
                ),
                level=log_level,
                colorize=True,
                backtrace=True,
                diagnose=diagnose,
            )

            # 2. 文件输出（完整轮转归档，记录更多细节）
            _loguru_logger.add(
                str(log_file_path),
                format=(
                    "{time:YYYY-MM-DD HH:mm:ss} | {level: <8} | "
                    "{name}:{function}:{line} - {message}"
                ),
                level=log_level,
                rotation="10 MB",
                retention="3 days",
                compression="zip",
                encoding="utf-8",
                backtrace=True,
                diagnose=diagnose,
            )

            # 3. 桥接标准库 logging → loguru
            bridge = _StdlibLoguruBridge()
            root = logging.getLogger()
            root.handlers = [bridge]  # 替换默认 handler，避免重复
            root.setLevel(getattr(logging, log_level.upper(), logging.INFO))

            cls._initialized = True

    @classmethod
    def get_logger(cls, name: str = __name__):
        """获取 logger。

        主进程模式：返回 loguru bound logger。
        子进程模式：返回 stdlib logger（不触发自动初始化，buffer 到 root）。
        """
        if _is_runner_child():
            return logging.getLogger(name)

        if not cls._initialized:
            cls.init_logging()
        return _loguru_logger.bind(name=name)


# ---------------------------------------------------------------------------
# 模块级便捷函数
# ---------------------------------------------------------------------------

def init_logging(log_file: Optional[str] = None, log_level: Optional[str] = None):
    """初始化日志配置"""
    LoggingConfig.init_logging(log_file, log_level)


def get_logger(name: str = __name__):
    """获取 logger"""
    return LoggingConfig.get_logger(name)
