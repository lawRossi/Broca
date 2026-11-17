"""按 agent 隔离的全量持久化媒体缓存。

设计要点（对应计划 Task 2.3）：
- **全量保存**：不做字节上限 / LRU 淘汰（数据量小）。
- **落盘持久化**：目录 ``<broca_home>/media_cache/<session_id>/<agent_id>/``，
  进程重启后可复用（启动时无需全量读盘，``get`` 时按需读）。
- **每个 agent 独立**：不同 ``(session_id, agent_id)`` 目录互相隔离。
- **TTL ≤ 3 天**：``created_at`` 超过 TTL 的条目在 ``get`` 时视为未命中并删除；
  ``gc_expired()`` 供启动/定时清理。
- **清理 API**：``clear()`` 删本 agent 目录；``clear_session()`` 删整 session 目录。

缓存内容（base64 data-url / file_id）只落盘，不进 DB、不进 ``context._history``。
key 为 ``sha256``（base64/压缩结果）或 ``(provider, sha256)``（file_id）。
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import os
import shutil
import time
from pathlib import Path
from typing import Any

from broca.logging_config import get_logger

logger = get_logger(__name__)

DEFAULT_TTL_SECONDS = 3 * 24 * 60 * 60  # 3 天


def default_cache_root() -> Path:
    """``<broca_home>/media_cache``（动态计算以支持测试 patch HOME）。"""
    return Path.home() / ".broca" / "media_cache"


def _key_to_id(key: Any) -> str:
    if isinstance(key, (list, tuple)):
        canonical = "\x1f".join(str(x) for x in key)
    else:
        canonical = str(key)
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def _jsonable_key(key: Any) -> Any:
    if isinstance(key, tuple):
        return list(key)
    return key


class MediaCache:
    """单个 agent 的持久化媒体缓存。"""

    def __init__(
        self,
        session_id: str | None = None,
        agent_id: str | None = None,
        *,
        root: Path | str | None = None,
        ttl_seconds: int = DEFAULT_TTL_SECONDS,
    ):
        self.session_id = session_id or "unknown"
        self.agent_id = agent_id or "unknown"
        self.root = Path(root) if root is not None else default_cache_root()
        self.dir = self.root / self.session_id / self.agent_id
        self.ttl_seconds = ttl_seconds
        self._lock = asyncio.Lock()

    # ------------------------------------------------------------------
    # 读写
    # ------------------------------------------------------------------

    def _entry_path(self, key: Any) -> Path:
        return self.dir / f"{_key_to_id(key)}.json"

    async def get(self, key: Any) -> Any | None:
        """命中返回值；未命中 / 过期返回 None（过期条目顺带删除）。"""
        path = self._entry_path(key)
        if not path.exists():
            return None
        try:
            raw = await asyncio.to_thread(path.read_text, "utf-8")
            entry = json.loads(raw)
        except (OSError, json.JSONDecodeError) as e:
            logger.warning(f"media cache read failed ({path}): {e}")
            return None

        created_at = entry.get("created_at", 0)
        if self.ttl_seconds and (time.time() - created_at) > self.ttl_seconds:
            # 过期：删除并视为未命中
            await self._safe_unlink(path)
            return None
        return entry.get("value")

    async def put(self, key: Any, value: Any, *, kind: str = "") -> None:
        """原子写入一条缓存（临时文件 + rename）。"""
        async with self._lock:
            await asyncio.to_thread(self.dir.mkdir, parents=True, exist_ok=True)
            entry = {
                "key": _jsonable_key(key),
                "created_at": time.time(),
                "kind": kind,
                "size": len(value) if isinstance(value, (str, bytes)) else 0,
                "value": value,
            }
            path = self._entry_path(key)
            tmp = path.with_name(f"{path.name}.tmp.{os.getpid()}.{id(entry)}")
            try:
                await asyncio.to_thread(
                    tmp.write_text,
                    json.dumps(entry, ensure_ascii=False),
                    "utf-8",
                )
                await asyncio.to_thread(os.replace, tmp, path)
            except OSError as e:
                logger.warning(f"media cache write failed ({path}): {e}")
                await self._safe_unlink(tmp)

    # ------------------------------------------------------------------
    # 清理
    # ------------------------------------------------------------------

    async def clear(self) -> None:
        """删除本 agent 的缓存目录。"""
        await asyncio.to_thread(self._rmtree, self.dir)

    async def clear_session(self, session_id: str | None = None) -> None:
        """删除整个 session 的缓存目录（所有 agent）。"""
        sid = session_id or self.session_id
        await asyncio.to_thread(self._rmtree, self.root / sid)

    async def gc_expired(self) -> int:
        """清理本 agent 目录下所有过期条目，返回删除数量。"""
        if not self.dir.exists():
            return 0
        now = time.time()
        removed = 0
        for path in await asyncio.to_thread(lambda: list(self.dir.glob("*.json"))):
            try:
                entry = json.loads(await asyncio.to_thread(path.read_text, "utf-8"))
            except (OSError, json.JSONDecodeError):
                await self._safe_unlink(path)
                removed += 1
                continue
            created_at = entry.get("created_at", 0)
            if self.ttl_seconds and (now - created_at) > self.ttl_seconds:
                await self._safe_unlink(path)
                removed += 1
        return removed

    # ------------------------------------------------------------------
    # 内部工具
    # ------------------------------------------------------------------

    @staticmethod
    async def _safe_unlink(path: Path) -> None:
        try:
            await asyncio.to_thread(path.unlink)
        except OSError:
            pass

    @staticmethod
    def _rmtree(path: Path) -> None:
        try:
            if path.exists():
                shutil.rmtree(path, ignore_errors=True)
        except OSError as e:  # pragma: no cover - 容错
            logger.warning(f"media cache rmtree failed ({path}): {e}")


def clear_session_cache(session_id: str, *, root: Path | str | None = None) -> None:
    """模块级：删除整个 session 的媒体缓存目录（供 session 删除联动）。容错不抛异常。"""
    base = Path(root) if root is not None else default_cache_root()
    target = base / (session_id or "unknown")
    try:
        if target.exists():
            shutil.rmtree(target, ignore_errors=True)
    except OSError as e:  # pragma: no cover - 容错
        logger.warning(f"clear_session_cache failed ({target}): {e}")


__all__ = ["MediaCache", "clear_session_cache", "default_cache_root", "DEFAULT_TTL_SECONDS"]
