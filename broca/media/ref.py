"""媒体引用（ref）编解码工具。

设计目标：
- 消息入库 / 内存历史只保存轻量引用，而不是 base64 或易过期的公网 URL。
- 引用自包含（含真实展示 URL 及取数所需的 key/path），历史回放时无需额外查表。
- 单一字符串编码，放进 LLM ``image_url`` / ``video_url`` part 的 ``url`` 字段，
  以便复用现有消息结构，且 ``is_media_ref`` 可无歧义判别。

编码格式：``ref://`` + base64url(json.dumps(meta))（无 padding）。

两种 kind：
- ``cloud``: ``{kind, key, url, sha256, mime, size}`` —— 已上传云存储。
- ``local``: ``{kind, path, url, sha256, mime, size}`` —— 本地文件，物化直接读盘。

其中 ``url`` 用于前端展示（cloud 为公网 URL，local 为后端 /files/raw 预览地址），
``key`` / ``path`` 用于服务端物化取数。``url`` 允许为空（如 TUI 场景无展示需求）。
"""

from __future__ import annotations

import base64
import binascii
import json
from typing import Any

REF_SCHEME = "ref://"

# 所有 kind 共有的必填字段
_COMMON_REQUIRED = ("kind", "url", "sha256", "mime", "size")
# 各 kind 额外的必填字段
_KIND_REQUIRED = {
    "cloud": ("key",),
    "local": ("path",),
}
_VALID_KINDS = tuple(_KIND_REQUIRED.keys())


def _b64url_encode(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).decode("ascii").rstrip("=")


def _b64url_decode(data: str) -> bytes:
    # 还原 padding
    padding = "=" * (-len(data) % 4)
    return base64.urlsafe_b64decode(data + padding)


def encode_media_ref(meta: dict[str, Any]) -> str:
    """把 ref 元数据编码为 ``ref://...`` 字符串。

    Args:
        meta: 至少含 ``kind``（``cloud``|``local``）、``url``、``sha256``、``mime``、
            ``size``；``cloud`` 额外含 ``key``，``local`` 额外含 ``path``。

    Returns:
        ``ref://`` 前缀的自包含字符串。

    Raises:
        ValueError: meta 不是 dict、缺少必填字段或 kind 非法。
    """
    if not isinstance(meta, dict):
        raise ValueError("media ref meta must be a dict")

    kind = meta.get("kind")
    if kind not in _VALID_KINDS:
        raise ValueError(f"invalid media ref kind: {kind!r}")

    required = list(_COMMON_REQUIRED) + list(_KIND_REQUIRED[kind])
    missing = [f for f in required if f not in meta]
    if missing:
        raise ValueError(f"media ref meta missing required fields: {missing}")

    payload = json.dumps(meta, ensure_ascii=False, separators=(",", ":"))
    return REF_SCHEME + _b64url_encode(payload.encode("utf-8"))


def is_media_ref(url: Any) -> bool:
    """判断字符串是否为合法的 ``ref://`` 媒体引用。

    对非字符串、普通 https url、空串、非法 base64 / 非法结构一律返回 False。
    """
    if not isinstance(url, str):
        return False
    if not url.startswith(REF_SCHEME):
        return False
    return decode_media_ref(url) is not None


def decode_media_ref(ref: str) -> dict[str, Any] | None:
    """解码 ``ref://`` 字符串为 meta dict。

    解码失败（前缀不符、base64 非法、JSON 非法、结构非法、kind 非法、缺字段）
    一律返回 None，绝不抛异常。
    """
    if not isinstance(ref, str) or not ref.startswith(REF_SCHEME):
        return None

    encoded = ref[len(REF_SCHEME):]
    if not encoded:
        return None

    try:
        raw = _b64url_decode(encoded)
        meta = json.loads(raw.decode("utf-8"))
    except (binascii.Error, ValueError, UnicodeDecodeError):
        return None

    if not isinstance(meta, dict):
        return None

    kind = meta.get("kind")
    if kind not in _VALID_KINDS:
        return None

    required = list(_COMMON_REQUIRED) + list(_KIND_REQUIRED[kind])
    if any(f not in meta for f in required):
        return None

    return meta
