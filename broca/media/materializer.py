"""请求时媒体物化（ref → wire 表示）。

分层原则：持久化层只存轻量 ``ref://``；真正发往 LLM 前，把 ref 物化为 wire
表示（base64 data-url 或 files_api file 块）。物化在
``LiteLLMClient.get_stream_response`` 调用 ``acompletion`` 之前对 messages 做一次
**深拷贝 + 物化**，绝不修改调用方传入的 ``messages``（即 ``context._history``）。

单 part 决策树（二选一 + 压缩兜底 + 报错，无 url 兜底）：

1. 读该 provider/model 的 ``meta.modality``，不支持该模态 → 降级为文本链接。
2. 支持时按「该 provider 是否配置 ``files_api``」二选一（files_api 是 **provider 级**
   能力——同一 provider 共享同一上传端点/认证/配额，故配置在 ``{provider}.files_api``，
   与 ``base_url``/``api_key``/``models`` 平级，不再放在 model 的 meta 里）：
   - 配置了 files_api → files_api 模式：阈值 ``files_api.max_size_mb``
     （默认 64）；``size <= 阈值`` 上传引用 file 块；否则先压缩，压缩后仍超 → 报错。
   - 未配置 → base64 模式：阈值 ``meta.media_limits.max_inline_mb``（默认 4，
     **不放在 ``meta.modality.image``** 以免被 ``parse_message`` 混入 wire）；
     ``size <= 阈值`` → base64；否则先压缩，压缩后仍超 → 报错。
3. 非图片（视频/音频）不可压缩：``_compress_to_fit`` 返回 None → 直接报错。

本模块随 Phase 2 各任务逐步补齐实现：字节读取（Task 2.2）、持久化缓存（Task 2.3）、
图片压缩（Task 2.5）、接入 get_stream_response（Task 2.4）。
"""

from __future__ import annotations

import base64
import copy
from typing import Any, Awaitable, Callable

from broca.logging_config import get_logger
from broca.media.errors import MediaFileTooLargeError, MediaMaterializeError
from broca.media.ref import decode_media_ref, is_media_ref

logger = get_logger(__name__)

# 默认阈值（MB）
DEFAULT_MAX_INLINE_MB = 4
DEFAULT_FILES_API_MAX_MB = 64

# part 类型 → modality key
_MODALITY_KEY = {"image_url": "image", "video_url": "video"}
# modality key → part 中承载 url 的字段名
_PART_URL_FIELD = {"image_url": "image_url", "video_url": "video_url"}

# files_api 策略工厂签名： (provider, model, files_api_cfg) -> strategy | None
FilesApiFactory = Callable[[str, str, dict], Any]
# 缓存工厂签名： (session_id, agent_id) -> MediaCache | None
CacheFactory = Callable[[str | None, str | None], Any]


class MediaMaterializer:
    """把 messages 中的 ``ref://`` 媒体引用物化为 wire 表示。"""

    def __init__(
        self,
        config: dict | None = None,
        storage: Any = None,
        files_api_factory: FilesApiFactory | None = None,
        cache_factory: CacheFactory | None = None,
        max_edge: int = 2048,
    ):
        """
        Args:
            config: LLM 配置 dict（含 provider/models/meta）。
            storage: ``StorageConfig``，用于 cloud ref 取字节（Task 2.2）。
            files_api_factory: 按 provider/model/files_api_cfg 返回 FilesApiStrategy
                的工厂；未提供时若配置了 files_api 将报错（Phase 3 提供真实实现）。
            cache_factory: 按 (session_id, agent_id) 返回 per-agent 持久化缓存；
                未提供时不做缓存（Task 2.3 提供实现）。
            max_edge: 压缩时图片长边上限（默认 2048）。
        """
        self.config = config or {}
        self.storage = storage
        self.files_api_factory = files_api_factory
        self.cache_factory = cache_factory
        self.max_edge = max_edge

    # ------------------------------------------------------------------
    # 批量物化入口
    # ------------------------------------------------------------------

    async def materialize_messages(
        self,
        messages: list[dict],
        provider: str,
        model: str,
        session_id: str | None = None,
        agent_id: str | None = None,
    ) -> list[dict]:
        """深拷贝 messages 并对含 ref 的 part 物化；原对象不被修改。"""
        if not isinstance(messages, list):
            return messages

        cache = self._get_cache(session_id, agent_id)
        out: list[dict] = []
        for msg in messages:
            if not self._message_has_ref(msg):
                # 无 ref → 原样保留（不深拷贝，避免大历史无谓复制）
                out.append(msg)
                continue
            out.append(await self._materialize_message(msg, provider, model, cache))
        return out

    @staticmethod
    def _message_has_ref(msg: Any) -> bool:
        if not isinstance(msg, dict):
            return False
        content = msg.get("content")
        if not isinstance(content, list):
            return False
        for part in content:
            if isinstance(part, dict):
                field = _PART_URL_FIELD.get(part.get("type", ""))
                if field:
                    container = part.get(field)
                    if isinstance(container, dict) and is_media_ref(container.get("url")):
                        return True
        return False

    async def _materialize_message(
        self, msg: Any, provider: str, model: str, cache: Any
    ) -> Any:
        if not isinstance(msg, dict):
            return msg
        content = msg.get("content")
        if not isinstance(content, list):
            # 纯文本 / 结构不符合预期 → 原样（深拷贝避免共享引用）
            return copy.deepcopy(msg)

        new_msg = copy.deepcopy(msg)
        new_content: list[Any] = []
        for part in new_msg["content"]:
            if isinstance(part, dict):
                new_content.append(
                    await self._resolve_part(part, provider, model, cache)
                )
            else:
                new_content.append(part)
        new_msg["content"] = new_content
        return new_msg

    # ------------------------------------------------------------------
    # 单 part 决策树
    # ------------------------------------------------------------------

    async def _resolve_part(
        self, part: dict, provider: str, model: str, cache: Any
    ) -> dict:
        url = self._get_part_url(part)
        if url is None or not is_media_ref(url):
            return part

        ref = decode_media_ref(url)
        if ref is None:
            # is_media_ref 已校验过，理论上不会到这里；保险起见原样返回
            logger.warning("media ref decode failed unexpectedly, leaving part as-is")
            return part

        part_type = part.get("type")
        mod_key = _MODALITY_KEY.get(part_type, "")
        meta = self._model_meta(provider, model)
        modality = (meta or {}).get("modality", {}) or {}

        # 1. 模态不支持 → 降级为文本链接
        if not mod_key or mod_key not in modality:
            link = ref.get("url") or ""
            return {"type": "text", "text": f"文件链接：{link}"}

        size = int(ref.get("size") or 0)
        file_name = self._ref_display_name(ref)
        mime = ref.get("mime") or ""
        # 仅图片可压缩；视频/音频等不可压缩，超阈值直接报错（不尝试压缩）
        can_compress = mime.startswith("image/")

        files_api_cfg = self._files_api_cfg(provider)
        # 先解析策略：未配置 / type 未知 / 构造失败 → strategy None → 走 base64 兜底。
        strategy = None
        if files_api_cfg:
            strategy = self._resolve_files_api_strategy(provider, model, files_api_cfg)

        if strategy is not None:
            # 2a. files_api 模式
            threshold = int(files_api_cfg.get("max_size_mb", DEFAULT_FILES_API_MAX_MB)) * 1024 * 1024
            if size <= threshold:
                return await self._via_files_api(strategy, ref, files_api_cfg, cache)
            compressed = (
                await self._compress_to_fit(ref, threshold, cache) if can_compress else None
            )
            if compressed is not None and len(compressed) <= threshold:
                return await self._via_files_api(
                    strategy, ref, files_api_cfg, cache, data=compressed
                )
            raise MediaFileTooLargeError(
                file_name=file_name,
                size_bytes=size,
                threshold_bytes=threshold,
                mime=ref.get("mime", ""),
                suggestion="已配置 files_api 但文件压缩后仍超限；请缩小文件或联系管理员调高 files_api.max_size_mb。",
            )

        # 2b. base64 模式（未配置 files_api，或 type 未知/构造失败 → 安全兜底）
        media_limits = (meta or {}).get("media_limits", {}) or {}
        threshold = int(media_limits.get("max_inline_mb", DEFAULT_MAX_INLINE_MB)) * 1024 * 1024
        if size <= threshold:
            data_url = await self._to_base64(ref, cache)
            self._set_part_url(part, data_url)
            return part

        compressed = (
            await self._compress_to_fit(ref, threshold, cache) if can_compress else None
        )
        if compressed is not None and len(compressed) <= threshold:
            data_url = self._bytes_to_data_url(compressed, ref.get("mime", ""))
            self._set_part_url(part, data_url)
            return part

        raise MediaFileTooLargeError(
            file_name=file_name,
            size_bytes=size,
            threshold_bytes=threshold,
            mime=ref.get("mime", ""),
            suggestion="请配置 files_api 以支持大文件，或缩小/压缩该文件后重试。",
        )

    # ------------------------------------------------------------------
    # 辅助：base64 / files_api / 字节读取 / 压缩（部分为桩，后续任务补齐）
    # ------------------------------------------------------------------

    async def _to_base64(self, ref: dict, cache: Any = None) -> str:
        """返回 ``data:<mime>;base64,<...>`` 字符串（命中缓存则复用）。"""
        mime = ref.get("mime") or "application/octet-stream"
        sha = ref.get("sha256") or ""
        if cache is not None and sha:
            hit = await cache.get(sha)
            if hit is not None:
                return hit
        data = await self._read_bytes(ref)
        data_url = self._bytes_to_data_url(data, mime)
        if cache is not None and sha:
            await cache.put(sha, data_url)
        return data_url

    async def _via_files_api(
        self,
        strategy: Any,
        ref: dict,
        files_api_cfg: dict,
        cache: Any = None,
        data: bytes | None = None,
    ) -> dict:
        """委托 FilesApiStrategy 上传并返回 wire content part（双 key 块）。

        ``strategy`` 已在 ``_resolve_part`` 中解析非 None；上传失败由 strategy 抛出
        ``MediaMaterializeError``（不静默回退 base64/url）。传入 ``read_bytes`` 回调，
        使 strategy 在 file_id 缓存命中时可避免读取慢速存储字节。
        """
        return await strategy.upload(
            ref,
            files_api_cfg,
            data=data,
            cache=cache,
            read_bytes=(None if data is not None else (lambda: self._read_bytes(ref))),
        )

    async def _read_bytes(self, ref: dict) -> bytes:
        """读取 ref 指向的原始字节。Task 2.1 仅实现 local；cloud 于 Task 2.2 补齐。"""
        kind = ref.get("kind")
        if kind == "local":
            return await self._read_local_bytes(ref)
        if kind == "cloud":
            return await self._read_cloud_bytes(ref)
        raise MediaMaterializeError(
            f"不支持的 media ref kind: {kind!r}",
            file_name=self._ref_display_name(ref),
        )

    async def _read_local_bytes(self, ref: dict) -> bytes:
        import asyncio
        from pathlib import Path

        path = ref.get("path")
        if not path:
            raise MediaMaterializeError(
                "local ref 缺少 path", file_name=self._ref_display_name(ref)
            )
        p = Path(path)
        if not p.exists() or not p.is_file():
            raise MediaMaterializeError(
                f"本地媒体文件不存在或已过期：{path}（请重新上传）",
                file_name=self._ref_display_name(ref),
            )
        try:
            return await asyncio.to_thread(p.read_bytes)
        except OSError as e:
            raise MediaMaterializeError(
                f"读取本地媒体文件失败：{path}: {e}",
                file_name=self._ref_display_name(ref),
                cause=e,
            ) from e

    async def _read_cloud_bytes(self, ref: dict) -> bytes:
        """cloud ref 取字节：优先 boto3，缺配置时按 url 用 httpx 兜底。"""
        from broca.media.storage import read_cloud_bytes

        try:
            return await read_cloud_bytes(self.storage, ref)
        except Exception as e:
            raise MediaMaterializeError(
                f"读取云端媒体失败：{self._ref_display_name(ref)}: {e}",
                file_name=self._ref_display_name(ref),
                cause=e,
            ) from e

    async def _compress_to_fit(
        self, ref: dict, threshold: int, cache: Any = None
    ) -> bytes | None:
        """把超阈值图片压缩到 ``threshold`` 字节内，压不下去返回 None。

        仅对 ``image/*`` 生效；视频/音频等直接返回 None。压缩结果（新内容）按
        ``("compressed", 源sha256, threshold)`` 写入 per-agent 缓存，避免重复压缩。
        """
        mime = ref.get("mime") or ""
        if not mime.startswith("image/"):
            return None

        src_sha = ref.get("sha256") or ""
        cache_key = ("compressed", src_sha, threshold)
        if cache is not None and src_sha:
            hit = await cache.get(cache_key)
            if hit is not None:
                try:
                    return base64.b64decode(hit)
                except (ValueError, TypeError):
                    pass

        try:
            data = await self._read_bytes(ref)
        except Exception as e:
            logger.warning(f"compress: read bytes failed for {self._ref_display_name(ref)}: {e}")
            return None

        import asyncio

        result = await asyncio.to_thread(self._compress_bytes_sync, data, threshold)
        if result is not None and cache is not None and src_sha:
            await cache.put(
                cache_key,
                base64.b64encode(result).decode("ascii"),
                kind="compressed",
            )
        return result

    def _compress_bytes_sync(self, data: bytes, threshold: int) -> bytes | None:
        """同步 Pillow 压缩：长边缩放到 max_edge，转 RGB，JPEG 循环降质/降尺寸。"""
        import io

        try:
            from PIL import Image
        except ImportError:  # pragma: no cover - 依赖已在 Task 2.0 声明
            logger.warning("Pillow not available, cannot compress media")
            return None

        try:
            img = Image.open(io.BytesIO(data))
            img.load()
        except Exception as e:
            logger.warning(f"compress: open image failed: {e}")
            return None

        # 合成到白底（处理 RGBA / P / LA 透明通道）
        if img.mode in ("RGBA", "LA", "P"):
            try:
                img = img.convert("RGBA")
                bg = Image.new("RGB", img.size, (255, 255, 255))
                bg.paste(img, mask=img.split()[-1])
                img = bg
            except Exception:
                img = img.convert("RGB")
        elif img.mode != "RGB":
            img = img.convert("RGB")

        # 先把长边缩到 max_edge
        w, h = img.size
        longest = max(w, h)
        if longest > self.max_edge:
            ratio = self.max_edge / float(longest)
            img = img.resize((max(1, int(w * ratio)), max(1, int(h * ratio))))

        qualities = [85, 75, 65, 55, 45, 35]
        scale_factors = [1.0, 0.75, 0.5, 0.35, 0.25]
        for scale in scale_factors:
            if scale == 1.0:
                cur = img
            else:
                cw, ch = img.size
                cur = img.resize((max(1, int(cw * scale)), max(1, int(ch * scale))))
            for q in qualities:
                buf = io.BytesIO()
                try:
                    cur.save(buf, format="JPEG", quality=q, optimize=True)
                except Exception as e:
                    logger.warning(f"compress: save failed: {e}")
                    return None
                out = buf.getvalue()
                if len(out) <= threshold:
                    return out
        return None

    # ------------------------------------------------------------------
    # 辅助：缓存 / strategy 解析 / part url 读写
    # ------------------------------------------------------------------

    def _get_cache(self, session_id: str | None, agent_id: str | None) -> Any:
        if self.cache_factory is None:
            return None
        try:
            return self.cache_factory(session_id, agent_id)
        except Exception as e:  # 缓存构建失败不应阻断请求
            logger.warning(f"media cache build failed, disable cache: {e}")
            return None

    def _resolve_files_api_strategy(
        self, provider: str, model: str, files_api_cfg: dict
    ) -> Any:
        if self.files_api_factory is None:
            return None
        try:
            return self.files_api_factory(provider, model, files_api_cfg)
        except Exception as e:
            logger.warning(f"files_api strategy resolve failed: {e}")
            return None

    def _files_api_cfg(self, provider: str) -> dict | None:
        """读取 **provider 级** ``files_api`` 配置（与 base_url/api_key 平级）。

        files_api 是供应商 API 级能力（端点/认证/配额全 provider 共享），故不放 model meta。
        """
        try:
            cfg = self.config.get(provider, {}).get("files_api")
        except (AttributeError, TypeError):
            return None
        return cfg or None

    def _model_meta(self, provider: str, model: str) -> dict:
        try:
            return (
                self.config.get(provider, {})
                .get("models", {})
                .get(model, {})
                .get("meta", {})
                or {}
            )
        except (AttributeError, TypeError):
            return {}

    @staticmethod
    def _get_part_url(part: dict) -> str | None:
        field = _PART_URL_FIELD.get(part.get("type", ""))
        if not field:
            return None
        container = part.get(field)
        if isinstance(container, dict):
            url = container.get("url")
            if isinstance(url, str):
                return url
        return None

    @staticmethod
    def _set_part_url(part: dict, url: str) -> None:
        field = _PART_URL_FIELD.get(part.get("type", ""))
        if not field:
            return
        container = part.setdefault(field, {})
        if isinstance(container, dict):
            container["url"] = url

    @staticmethod
    def _bytes_to_data_url(data: bytes, mime: str) -> str:
        mime = mime or "application/octet-stream"
        encoded = base64.b64encode(data).decode("ascii")
        return f"data:{mime};base64,{encoded}"

    @staticmethod
    def _ref_display_name(ref: dict) -> str:
        return (
            ref.get("url")
            or ref.get("path")
            or ref.get("key")
            or "media"
        )


__all__ = ["MediaMaterializer"]
