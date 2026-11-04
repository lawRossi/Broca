"""
辅助工具模块

提供 safe_call 等工具，用于简化最常见的 try/except/log 模式。
"""

from __future__ import annotations

import asyncio
import functools
from typing import Callable, TypeVar

from broca.errors.exceptions import BrocaError
from broca.errors.types import ErrorCode
from broca.logging_config import get_logger

logger = get_logger(__name__)

T = TypeVar("T")


def safe_call(
    func: Callable[..., T] | None = None,
    *,
    error_class: type[BrocaError] = BrocaError,
    error_code: ErrorCode | None = None,
    message: str = "",
    details: "dict | None | Callable[[Exception], dict]" = None,
    logger_name: str | None = None,
) -> Callable[..., T]:
    """装饰器工厂：将函数调用中的任意 Exception 转为指定的 BrocaError 子类。

    用于简化最重复的 try/except/log 模式。支持同步和异步函数。

    可同时作为装饰器工厂和直接装饰器使用：

        @safe_call  # 无参数
        @safe_call()  # 空参数
        @safe_call(error_class=ToolError, error_code=ErrorCode.TOOL_ERROR)

    动态 details 支持两种机制（可并存）：
      1. **装饰器参数** — ``details`` 接受 ``Callable[[Exception], dict]``，
         在异常发生时接收异常对象，返回动态 details。
      2. **调用时 kwarg** — 调用被装饰函数时传入 ``_details={"key": "val"}``，
         该值会覆盖装饰器级别的静态/可调用 details。
         ``_details`` 不会传递给被装饰函数本身。

    Args:
        func: 被装饰的函数（使用无参数装饰器时传入）
        error_class: 目标异常类，默认为 BrocaError
        error_code: 错误码，若不指定则使用 error_class 的默认值
        message: 用户友好错误消息
        details: 调试用上下文，可以是 ``dict``（静态）或
            ``Callable[[Exception], dict]``（动态，接收异常）
        logger_name: 日志记录器名称，默认使用函数所在模块

    Returns:
        包装后的函数，抛出 BrocaError 而非原始异常

    Example:
        @safe_call(error_class=ToolError, error_code=ErrorCode.TOOL_ERROR, message="工具执行失败")
        async def my_tool():
            ...

        # 动态 details（装饰器参数方式）
        @safe_call(details=lambda e: {"error": str(e)})
        def risky(): ...

        # 动态 details（调用时 kwarg 方式，覆盖装饰器级别的 details）
        risky(_details={"context": "extra-info"})
    """

    def decorator(f: Callable[..., T]) -> Callable[..., T]:
        log = get_logger(logger_name or f.__module__)
        actual_message = message or f"{f.__name__} 执行失败"

        if asyncio.iscoroutinefunction(f):

            @functools.wraps(f)
            async def async_wrapper(*args, **kwargs):
                # Pop _details from call-site kwargs (not passed to underlying func)
                call_details: "dict | None" = kwargs.pop("_details", None)
                try:
                    return await f(*args, **kwargs)
                except BrocaError:
                    raise
                except Exception as e:
                    if call_details is not None:
                        _details = call_details
                    else:
                        _details = details(e) if callable(details) else details
                    log.error(
                        "%s failed: %s | %s",
                        f.__name__,
                        e,
                        _details or "",
                        exc_info=True,
                    )
                    raise error_class(
                        message=actual_message,
                        error_code=error_code,
                        details=_details,
                        cause=e,
                    )

            return async_wrapper
        else:

            @functools.wraps(f)
            def sync_wrapper(*args, **kwargs):
                # Pop _details from call-site kwargs (not passed to underlying func)
                call_details: "dict | None" = kwargs.pop("_details", None)
                try:
                    return f(*args, **kwargs)
                except BrocaError:
                    raise
                except Exception as e:
                    if call_details is not None:
                        _details = call_details
                    else:
                        _details = details(e) if callable(details) else details
                    log.error(
                        "%s failed: %s | %s",
                        f.__name__,
                        e,
                        _details or "",
                        exc_info=True,
                    )
                    raise error_class(
                        message=actual_message,
                        error_code=error_code,
                        details=_details,
                        cause=e,
                    )

            return sync_wrapper

    # 如果 safe_call 直接被用作装饰器（无参数调用），func 就是被装饰的函数
    if func is not None:
        return decorator(func)

    return decorator  # type: ignore[return-value]
