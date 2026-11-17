"""DeepSeek Files API 上传策略（Phase 3 首个 provider）。

DeepSeek Files API 参考：
- 上传：``POST {base_url}/files`` multipart/form-data，字段 ``file`` + ``purpose=user_data``；
  可选 ``expires_after[anchor]=created_at`` + ``expires_after[seconds]``（3600–2592000）。
- 响应：``{"id":"file-api-...","object":"file","bytes":...,"created_at":...,"filename":...}``，
  取 ``id`` 作 file_id。
- 引用块（经 litellm openai provider 下发，Task 3.0 冒烟确认被接受）：
  ``{"type":"file","file":{"file_id":<id>},"file_id":<id>}``（file 包装喂 litellm，
  顶层 file_id 喂 DeepSeek；两者 litellm 都保留）。
- 单文件上限：64 MiB。

缓存：(provider, sha256(上传字节)) → {"file_id", "expires_at"}，落 per-agent 持久化缓存，
TTL 由缓存层 3 天上限 + 本策略 ``expires_at`` 双重约束（取 min）。缓存命中可完全不读源字节。
"""

from __future__ import annotations

import hashlib
import os
import time
from typing import Any

from broca.logging_config import get_logger
from broca.media.errors import MediaFileTooLargeError, MediaMaterializeError
from broca.media.files_api import FilesApiStrategy

logger = get_logger(__name__)

DEFAULT_MAX_SIZE_MB = 64
DEFAULT_PURPOSE = "user_data"
# DeepSeek expires_after[seconds] 合法区间
_MIN_EXPIRES = 3600
_MAX_EXPIRES = 2_592_000  # 30 天


def sniff_image_mime(data: bytes) -> str | None:
    """按内容魔数嗅探图片类型（JPEG/PNG/GIF/WebP），非图片返回 None。"""
    if len(data) >= 3 and data[:3] == b"\xff\xd8\xff":
        return "image/jpeg"
    if len(data) >= 8 and data[:8] == b"\x89PNG\r\n\x1a\n":
        return "image/png"
    if len(data) >= 6 and data[:6] in (b"GIF87a", b"GIF89a"):
        return "image/gif"
    if len(data) >= 12 and data[:4] == b"RIFF" and data[8:12] == b"WEBP":
        return "image/webp"
    return None


def _file_block(file_id: str) -> dict:
    """构造双 key file 块（file 喂 litellm，顶层 file_id 喂 DeepSeek）。"""
    return {"type": "file", "file": {"file_id": file_id}, "file_id": file_id}


class DeepSeekFilesStrategy(FilesApiStrategy):
    """DeepSeek 原生文件上传策略。"""

    def __init__(
        self,
        provider_cfg: dict,
        files_api_cfg: dict,
        provider: str = "deepseek",
    ):
        self.provider = provider or "deepseek"
        self.base_url = (provider_cfg or {}).get("base_url") or "https://api.deepseek.com/v1"
        self.api_key = (provider_cfg or {}).get("api_key") or ""
        cfg = files_api_cfg or {}
        self.purpose = cfg.get("purpose") or DEFAULT_PURPOSE
        expires = cfg.get("expires_seconds")
        self.expires_seconds = int(expires) if expires else None
        if self.expires_seconds is not None:
            # 夹到合法区间
            self.expires_seconds = max(_MIN_EXPIRES, min(_MAX_EXPIRES, self.expires_seconds))
        self.max_size_bytes = int(
            cfg.get("max_size_mb", DEFAULT_MAX_SIZE_MB)
        ) * 1024 * 1024

    async def upload(
        self,
        ref: dict,
        provider_cfg: dict,
        data: bytes | None = None,
        cache: Any = None,
        read_bytes: Any = None,
    ) -> dict:
        # 1. 缓存查询（需要 sha256；data 已给出时可直接算，否则先算 ref.sha256）
        #    为避免缓存命中仍读源字节：若 data 为空且有 ref.sha256，先用它探测缓存。
        cache_key = None
        if data is not None:
            cache_key = (self.provider, hashlib.sha256(data).hexdigest())
            hit = await self._cache_get(cache, cache_key)
            if hit is not None:
                return hit

        if data is None and cache is not None and ref.get("sha256"):
            # 用 ref 的原始 sha256 探测缓存（命中则无需读取/上传）
            probe_key = (self.provider, ref["sha256"])
            hit = await self._cache_get(cache, probe_key)
            if hit is not None:
                return hit

        # 2. 获取待上传字节
        if data is None:
            if read_bytes is None:
                raise MediaMaterializeError(
                    "无法获取待上传字节（无 data 且未提供 read_bytes）",
                    file_name=self._display_name(ref),
                )
            data = await read_bytes()

        # 3. 格式 + 大小校验
        mime = sniff_image_mime(data)
        if mime is None:
            raise MediaMaterializeError(
                "不支持的文件格式：files_api 仅支持 JPEG/PNG/GIF/WebP 图片（按内容嗅探）",
                file_name=self._display_name(ref),
            )
        if len(data) > self.max_size_bytes:
            raise MediaFileTooLargeError(
                file_name=self._display_name(ref),
                size_bytes=len(data),
                threshold_bytes=self.max_size_bytes,
                mime=mime,
                suggestion=(
                    f"文件超过 DeepSeek Files API 单文件上限 "
                    f"{self.max_size_bytes // (1024 * 1024)}MB，请压缩或缩小后重试。"
                ),
            )

        # 4. 重新计算最终缓存 key（若上面未计算：data 由 read_bytes 得到）
        if cache_key is None:
            cache_key = (self.provider, hashlib.sha256(data).hexdigest())

        # 5. 上传
        file_id, created_at = await self._post_file(data, mime, ref)

        # 6. 写缓存（含 expires_at，供读取时二次校验 min(3d, provider 过期)）
        if cache is not None:
            expires_at = (
                (created_at + self.expires_seconds)
                if self.expires_seconds
                else None
            )
            try:
                await cache.put(
                    cache_key,
                    {"file_id": file_id, "expires_at": expires_at},
                    kind="file_id",
                )
            except Exception as e:  # 缓存写失败不影响本次结果
                logger.warning(f"file_id cache put failed: {e}")

        return _file_block(file_id)

    # ------------------------------------------------------------------
    # 内部
    # ------------------------------------------------------------------

    async def _cache_get(self, cache: Any, cache_key: tuple) -> dict | None:
        """命中且未过期 → 返回 file 块；否则 None。"""
        if cache is None:
            return None
        try:
            entry = await cache.get(cache_key)
        except Exception as e:
            logger.warning(f"file_id cache get failed: {e}")
            return None
        if not entry:
            return None
        if isinstance(entry, str):
            # 兼容旧格式（裸 file_id）
            return _file_block(entry)
        file_id = entry.get("file_id")
        if not file_id:
            return None
        expires_at = entry.get("expires_at")
        if expires_at and time.time() >= expires_at:
            # provider 侧已过期 → 视为未命中（重新上传）
            return None
        return _file_block(file_id)

    async def _post_file(
        self, data: bytes, mime: str, ref: dict
    ) -> tuple[str, int]:
        """POST {base_url}/files 上传，返回 (file_id, created_at)。失败抛错（不兜底）。"""
        import httpx

        url = self.base_url.rstrip("/") + "/files"
        filename = self._filename(ref, mime)
        form = {"purpose": self.purpose}
        if self.expires_seconds:
            form["expires_after[anchor]"] = "created_at"
            form["expires_after[seconds]"] = str(self.expires_seconds)
        files = {"file": (filename, data, mime)}
        headers = {"Authorization": f"Bearer {self.api_key}"}
        try:
            async with httpx.AsyncClient(timeout=60.0) as client:
                resp = await client.post(
                    url, headers=headers, data=form, files=files
                )
        except Exception as e:  # 网络异常
            raise MediaMaterializeError(
                f"上传到 DeepSeek Files API 失败（网络错误）：{e}",
                file_name=self._display_name(ref),
                cause=e,
            ) from e

        if resp.status_code >= 400:
            body = resp.text[:500]
            raise MediaMaterializeError(
                f"上传到 DeepSeek Files API 失败（HTTP {resp.status_code}）：{body}",
                file_name=self._display_name(ref),
            )
        try:
            payload = resp.json()
        except Exception as e:
            raise MediaMaterializeError(
                f"DeepSeek Files API 响应解析失败：{resp.text[:200]}",
                file_name=self._display_name(ref),
                cause=e,
            ) from e
        file_id = payload.get("id")
        if not file_id:
            raise MediaMaterializeError(
                f"DeepSeek Files API 响应缺少 id：{payload}",
                file_name=self._display_name(ref),
            )
        created_at = int(payload.get("created_at") or time.time())
        return file_id, created_at

    @staticmethod
    def _filename(ref: dict, mime: str) -> str:
        ext = {
            "image/jpeg": ".jpg",
            "image/png": ".png",
            "image/gif": ".gif",
            "image/webp": ".webp",
        }.get(mime, "")
        for field in ("url", "path", "key"):
            val = ref.get(field)
            if isinstance(val, str) and val:
                base = os.path.basename(val.split("?")[0])
                if base and "." in base:
                    return base
        return "upload" + ext

    @staticmethod
    def _display_name(ref: dict) -> str:
        return ref.get("url") or ref.get("path") or ref.get("key") or "media"


__all__ = ["DeepSeekFilesStrategy", "sniff_image_mime"]
