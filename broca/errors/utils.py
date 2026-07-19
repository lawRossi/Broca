"""
辅助工具模块

提供 safe_call 等工具，用于简化最常见的 try/except/log 模式。
"""

from __future__ import annotations

import asyncio
import functools
import logging
from typing import Callable, TypeVar

from broca.errors.exceptions import BrocaError
from broca.errors.types import ErrorCode

logger = logging.getLogger(__name__)

T = TypeVar("T")


def safe_call(
    func: Callable[..., T] | None = None,
    *,
    error_class: type[BrocaError] = BrocaError,
    error_code: ErrorCode | None = None,
    message: str = "",
    details: dict | None = None,
    logger_name: str | None = None,
) -> Callable[..., T]:
    """装饰器工厂：将函数调用中的任意 Exception 转为指定的 BrocaError 子类。

    用于简化最重复的 try/except/log 模式。支持同步和异步函数。

    可同时作为装饰器工厂和直接装饰器使用：

        @safe_call  # 无参数
        @safe_call()  # 空参数
        @safe_call(error_class=ToolError, error_code=ErrorCode.TOOL_ERROR)

    Args:
        func: 被装饰的函数（使用无参数装饰器时传入）
        error_class: 目标异常类，默认为 BrocaError
        error_code: 错误码，若不指定则使用 error_class 的默认值
        message: 用户友好错误消息
        details: 调试用上下文
        logger_name: 日志记录器名称，默认使用函数所在模块

    Returns:
        包装后的函数，抛出 BrocaError 而非原始异常

    Example:
        @safe_call(error_class=ToolError, error_code=ErrorCode.TOOL_ERROR, message="工具执行失败")
        async def my_tool():
            ...
    """

    def decorator(f: Callable[..., T]) -> Callable[..., T]:
        log = logging.getLogger(logger_name or f.__module__)
        actual_message = message or f"{f.__name__} 执行失败"

        if asyncio.iscoroutinefunction(f):

            @functools.wraps(f)
            async def async_wrapper(*args, **kwargs):
                try:
                    return await f(*args, **kwargs)
                except BrocaError:
                    raise
                except Exception as e:
                    log.error(
                        "%s failed: %s | %s",
                        f.__name__,
                        e,
                        details or "",
                        exc_info=True,
                    )
                    raise error_class(
                        message=actual_message,
                        error_code=error_code,
                        details=details,
                        cause=e,
                    )

            return async_wrapper
        else:

            @functools.wraps(f)
            def sync_wrapper(*args, **kwargs):
                try:
                    return f(*args, **kwargs)
                except BrocaError:
                    raise
                except Exception as e:
                    log.error(
                        "%s failed: %s | %s",
                        f.__name__,
                        e,
                        details or "",
                        exc_info=True,
                    )
                    raise error_class(
                        message=actual_message,
                        error_code=error_code,
                        details=details,
                        cause=e,
                    )

            return sync_wrapper

    # 如果 safe_call 直接被用作装饰器（无参数调用），func 就是被装饰的函数
    if func is not None:
        return decorator(func)

    return decorator  # type: ignore[return-value]
