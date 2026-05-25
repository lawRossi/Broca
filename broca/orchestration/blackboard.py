"""
Blackboard 模块

实现共享黑板（Blackboard）组件，用于 Agent 间共享状态。
- 支持 key-value 存储，支持嵌套 dict/list
- 版本化管理，每次写入生成新版本号
- 事件通知（created/updated/deleted）
- 序列化/反序列化，可持久化到数据库
- 线程安全（asyncio.Lock）
"""

from __future__ import annotations

import asyncio
import copy
import json
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Any, Callable, Dict, List, Optional


class BlackboardEventType(str, Enum):
    """黑板事件类型"""

    CREATED = "created"
    UPDATED = "updated"
    DELETED = "deleted"


@dataclass
class BlackboardEvent:
    """黑板变更事件"""

    key: str
    old_value: Any
    new_value: Any
    producer: str
    timestamp: datetime
    event_type: BlackboardEventType

    def to_dict(self) -> Dict[str, Any]:
        return {
            "key": self.key,
            "old_value": self._serialize_value(self.old_value),
            "new_value": self._serialize_value(self.new_value),
            "producer": self.producer,
            "timestamp": self.timestamp.isoformat(),
            "event_type": self.event_type.value,
        }

    @staticmethod
    def _serialize_value(value: Any) -> Any:
        if isinstance(value, (dict, list)):
            return copy.deepcopy(value)
        return value


@dataclass
class BlackboardEntry:
    """黑板条目（带版本号）"""

    key: str
    value: Any
    version: int
    producer: str
    created_at: datetime
    updated_at: datetime

    def to_dict(self) -> Dict[str, Any]:
        return {
            "key": self.key,
            "value": copy.deepcopy(self.value),
            "version": self.version,
            "producer": self.producer,
            "created_at": self.created_at.isoformat(),
            "updated_at": self.updated_at.isoformat(),
        }


class Blackboard:
    """
    共享黑板

    是所有 Agent 共享状态的核心组件。Agent 通过工具读写黑板，
    编排器负责协调。黑板支持版本化管理、事件通知。

    用法:
        bb = Blackboard()
        bb.set("topic", "AI safety", producer="moderator")
        value = bb.get("topic")
        bb.subscribe(lambda event: print(f"Changed: {event.key}"))
    """

    def __init__(self, initial_entries: Optional[Dict[str, Any]] = None):
        self._lock = asyncio.Lock()
        self._entries: Dict[str, BlackboardEntry] = {}
        self._callbacks: List[Callable[[BlackboardEvent], None]] = []
        self._version_counter: int = 0

        if initial_entries:
            for key, value in initial_entries.items():
                self._set_initial(key, value)

    def _set_initial(self, key: str, value: Any) -> None:
        """设置初始条目（不触发事件）"""
        now = datetime.now(timezone.utc)
        self._version_counter += 1
        self._entries[key] = BlackboardEntry(
            key=key,
            value=copy.deepcopy(value),
            version=self._version_counter,
            producer="init",
            created_at=now,
            updated_at=now,
        )

    def _notify(
        self,
        key: str,
        old_value: Any,
        new_value: Any,
        producer: str,
        event_type: BlackboardEventType,
    ) -> None:
        """通知所有订阅者"""
        event = BlackboardEvent(
            key=key,
            old_value=old_value,
            new_value=new_value,
            producer=producer,
            timestamp=datetime.now(timezone.utc),
            event_type=event_type,
        )
        for callback in self._callbacks:
            try:
                callback(event)
            except Exception:
                pass  # 回调异常不影响主流程

    async def get(self, key: str, default: Any = None) -> Any:
        """
        获取黑板中指定 key 的值

        Args:
            key: 键名，支持点号分隔的嵌套路径（如 "user.name"）
            default: 当 key 不存在时返回的默认值

        Returns:
            存储的值，或 default
        """
        async with self._lock:
            if "." in key:
                return self._get_nested(key, default)
            entry = self._entries.get(key)
            if entry is None:
                return default
            return copy.deepcopy(entry.value)

    def _get_nested(self, key: str, default: Any = None) -> Any:
        """获取嵌套路径的值"""
        parts = key.split(".")
        root_key = parts[0]
        entry = self._entries.get(root_key)
        if entry is None:
            return default

        value = entry.value
        try:
            for part in parts[1:]:
                if isinstance(value, dict):
                    value = value[part]
                elif isinstance(value, list):
                    value = value[int(part)]
                else:
                    return default
            return copy.deepcopy(value)
        except (KeyError, IndexError, TypeError, ValueError):
            return default

    async def get_entry(self, key: str) -> Optional[BlackboardEntry]:
        """
        获取完整的黑板条目（含版本号、时间戳等元数据）

        Args:
            key: 键名

        Returns:
            BlackboardEntry 或 None
        """
        async with self._lock:
            entry = self._entries.get(key)
            if entry is None:
                return None
            return copy.deepcopy(entry)

    async def set(
        self,
        key: str,
        value: Any,
        producer: str = "system",
    ) -> BlackboardEvent:
        """
        设置黑板中指定 key 的值

        Args:
            key: 键名
            value: 要存储的值
            producer: 写入者标识

        Returns:
            生成的变更事件
        """
        async with self._lock:
            now = datetime.now(timezone.utc)
            old_value = None
            event_type = BlackboardEventType.CREATED

            if key in self._entries:
                old_value = copy.deepcopy(self._entries[key].value)
                event_type = BlackboardEventType.UPDATED

            self._version_counter += 1
            self._entries[key] = BlackboardEntry(
                key=key,
                value=copy.deepcopy(value),
                version=self._version_counter,
                producer=producer,
                created_at=self._entries[key].created_at if key in self._entries else now,
                updated_at=now,
            )

        # 锁外通知
        self._notify(key, old_value, value, producer, event_type)
        return BlackboardEvent(
            key=key,
            old_value=old_value,
            new_value=value,
            producer=producer,
            timestamp=now,
            event_type=event_type,
        )

    async def delete(self, key: str, producer: str = "system") -> Optional[BlackboardEvent]:
        """
        删除黑板中指定 key

        Args:
            key: 键名
            producer: 删除者标识

        Returns:
            如果存在则返回删除事件，否则返回 None
        """
        async with self._lock:
            if key not in self._entries:
                return None

            old_value = copy.deepcopy(self._entries[key].value)
            del self._entries[key]

        self._notify(key, old_value, None, producer, BlackboardEventType.DELETED)
        return BlackboardEvent(
            key=key,
            old_value=old_value,
            new_value=None,
            producer=producer,
            timestamp=datetime.now(timezone.utc),
            event_type=BlackboardEventType.DELETED,
        )

    async def exists(self, key: str) -> bool:
        """检查 key 是否存在"""
        async with self._lock:
            return key in self._entries

    async def keys(self) -> List[str]:
        """获取所有 key 列表"""
        async with self._lock:
            return list(self._entries.keys())

    async def all_entries(self) -> Dict[str, BlackboardEntry]:
        """获取所有条目（深拷贝）"""
        async with self._lock:
            return {k: copy.deepcopy(v) for k, v in self._entries.items()}

    async def to_dict(self) -> Dict[str, Any]:
        """导出为纯字典（不含元数据）"""
        async with self._lock:
            return {k: copy.deepcopy(v.value) for k, v in self._entries.items()}

    async def clear(self) -> None:
        """清空所有条目"""
        async with self._lock:
            self._entries.clear()
            self._version_counter = 0

    def subscribe(self, callback: Callable[[BlackboardEvent], None]) -> Callable:
        """
        订阅黑板变更事件

        Args:
            callback: 事件回调函数，接收 BlackboardEvent

        Returns:
            取消订阅的函数
        """
        self._callbacks.append(callback)

        def unsubscribe():
            if callback in self._callbacks:
                self._callbacks.remove(callback)

        return unsubscribe

    async def get_version(self) -> int:
        """获取当前全局版本号"""
        async with self._lock:
            return self._version_counter

    def to_serializable(self) -> Dict[str, Any]:
        """序列化为可持久化的字典"""
        return {
            "entries": {
                k: v.to_dict() for k, v in self._entries.items()
            },
            "version": self._version_counter,
        }

    @classmethod
    def from_serializable(cls, data: Dict[str, Any]) -> "Blackboard":
        """从序列化数据恢复"""
        bb = cls()
        bb._version_counter = data.get("version", 0)
        for key, entry_data in data.get("entries", {}).items():
            bb._entries[key] = BlackboardEntry(
                key=entry_data["key"],
                value=entry_data["value"],
                version=entry_data["version"],
                producer=entry_data["producer"],
                created_at=datetime.fromisoformat(entry_data["created_at"]),
                updated_at=datetime.fromisoformat(entry_data["updated_at"]),
            )
        return bb
