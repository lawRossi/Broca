"""
统一的日志配置模块

提供全局的日志配置，避免在各个模块中重复配置。
支持不同模块的日志级别配置和日志文件分离。
"""

from pathlib import Path
from typing import Optional

from loguru import logger

from broca.configs import get_configs


class LoggingConfig:
    """日志配置管理器"""
    
    _initialized = False
    
    @classmethod
    def init_logging(cls, log_file: Optional[str] = None, log_level: Optional[str] = None):
        """
        初始化全局日志配置
        
        Args:
            log_file: 日志文件路径，如果为None则使用配置中的默认值
            log_level: 日志级别，如果为None则使用配置中的默认值
        """
        if cls._initialized:
            logger.warning("Logging already initialized, skipping re-initialization")
            return
            
        # 获取配置
        configs = get_configs()
        
        # 确定日志文件路径
        if log_file is None:
            log_file = configs.log_file
            
        if log_level is None:
            log_level = configs.log_level
            
        # 确保日志文件目录存在
        log_path = Path(log_file)
        log_path.parent.mkdir(parents=True, exist_ok=True)
        
        # 移除所有现有的处理器
        logger.remove()

        # 添加文件输出
        logger.add(
            log_file,
            format="{time:YYYY-MM-DD HH:mm:ss} | {level: <8} | {name}:{function}:{line} - {message}",
            level=log_level,
            rotation="10 MB",  # 日志文件大小达到10MB时轮转
            retention="30 days",  # 保留30天的日志
            compression="zip",  # 压缩旧的日志文件
            encoding="utf-8",
        )
        
        cls._initialized = True
        logger.info(f"Logging initialized. Main log: {log_file}, Level: {log_level}")

    @classmethod
    def get_logger(cls, name: str = __name__):
        """
        获取指定名称的logger
        
        Args:
            name: logger名称，通常是模块的__name__
            
        Returns:
            配置好的logger实例
        """
        if not cls._initialized:
            cls.init_logging()
        return logger.bind(name=name)


def init_logging(log_file: Optional[str] = None, log_level: Optional[str] = None):
    """初始化日志配置的便捷函数"""
    LoggingConfig.init_logging(log_file, log_level)


def get_logger(name: str = __name__):
    """获取logger的便捷函数"""
    return LoggingConfig.get_logger(name)


# 导出常用的日志级别常量
DEBUG = "DEBUG"
INFO = "INFO"
WARNING = "WARNING"
ERROR = "ERROR"
CRITICAL = "CRITICAL"