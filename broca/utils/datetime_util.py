"""
日期时间工具函数

提供统一的 datetime 序列化方法，解决 SQLite 丢失时区信息导致前端时间显示错误的问题。

所有模型统一使用 UTC 存储，但 SQLite 读出后变为 naive datetime。
此工具在序列化为 ISO 字符串时补回时区信息，使前端能正确转换到本地时间。
"""

from datetime import datetime, timezone


def serialize_dt(dt: datetime | None, *, is_utc: bool = True) -> str | None:
    """序列化 datetime 为带时区信息的 ISO 字符串。

    Args:
        dt: 待序列化的 datetime 对象（可能为 None）
        is_utc: True 表示该时间实际是 UTC（绝大多数模型字段，如 created_at），
                False 表示该时间实际是系统本地时间（如 ScheduledJob.next_run_time）

    Returns:
        带时区信息的 ISO 格式字符串，如 "2026-06-17T07:47:16+00:00"，
        或 None（入参为 None 时）
    """
    if dt is None:
        return None

    # 如果已经是 timezone-aware，直接序列化
    if dt.tzinfo is not None:
        return dt.isoformat()

    # 如果是 naive datetime，手动附加时区信息
    if is_utc:
        # 绝大多数模型字段：存储的是 UTC 时间，但 SQLite 丢了时区信息
        return dt.replace(tzinfo=timezone.utc).isoformat()
    else:
        # 少数字段（如 next_run_time）：存储的是系统本地时间
        local_tz = datetime.now(timezone.utc).astimezone().tzinfo
        return dt.replace(tzinfo=local_tz).isoformat()
