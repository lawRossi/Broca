"""Files API 上传策略（按 provider 差异抽象）。

各供应商把本地/云端媒体"上传一次、后续用 id 引用"的能力差异很大：

==================  =========================================  =====================  ============
Provider            上传端点 / 认证                              引用块形态               单文件上限
==================  =========================================  =====================  ============
DeepSeek            ``POST {base_url}/files`` multipart         双 key file 块          64 MiB
                    ``purpose=user_data``                       ``{"type":"file","file":{"file_id":...},"file_id":...}``
Gemini              File API → 返回 ``uri``                       ``file_data``           ~2 GB
Anthropic           ``POST /v1/files`` + ``anthropic-beta`` 头   ``source.type=file``    500 MB
OpenAI              ``POST /v1/files`` 但 chat 图不支持 file_id  ——（不可用于 chat 图）  ——
==================  =========================================  =====================  ============

Phase 3 首批只落地 **DeepSeek**；其余 provider 预留扩展点（返回 None → 走 base64）。

设计要点：
- ``FilesApiStrategy.upload(ref, provider_cfg, data=None, cache=None) -> dict``：
  返回可直接放入 messages content 的 wire part（DeepSeek 为双 key file 块）。
  ``data`` 为已压缩后的字节（可选，None 表示由 strategy 自行读取/使用 ref 原字节）；
  ``cache`` 为 per-agent 持久化缓存（用于 (provider, sha256) → file_id 复用）。
- ``make_files_api_factory(llm_config)``：构造 ``(provider, model, files_api_cfg) -> strategy|None``
  工厂，供 ``MediaMaterializer`` 注入。未配置 / type 未知 / 解析失败 → None（materializer 走 base64）。
"""

from __future__ import annotations

import abc
from typing import Any

from broca.logging_config import get_logger

logger = get_logger(__name__)


class FilesApiStrategy(abc.ABC):
    """供应商原生文件上传策略抽象。"""

    #: 该策略支持的单文件大小上限（字节）；None 表示不限制/由实现决定。
    max_size_bytes: int | None = None

    @abc.abstractmethod
    async def upload(
        self,
        ref: dict,
        provider_cfg: dict,
        data: bytes | None = None,
        cache: Any = None,
        read_bytes: Any = None,
    ) -> dict:
        """上传媒体并返回可用于 wire 的 content part。

        Args:
            ref: 解码后的 media ref dict（含 kind/sha256/mime/size/url/path/key）。
            provider_cfg: provider 级 ``files_api`` 配置 dict（type/purpose/expires_seconds/max_size_mb...）。
            data: 可选，已压缩后的字节；None 时实现应在需要时调用 ``read_bytes`` 读取原始字节
                （缓存命中时可完全不读，避免慢速存储访问）。
            cache: 可选，per-agent 持久化缓存，用于 (provider, sha256) → file_id 复用。
            read_bytes: 可选，``async () -> bytes`` 回调，读取 ref 原始字节。

        Returns:
            可直接放入 messages content 的 wire part（如双 key file 块）。

        Raises:
            MediaMaterializeError: 上传失败 / 非法格式（不静默回退）。
            MediaFileTooLargeError: 超过 provider 单文件上限。
        """
        raise NotImplementedError


# type → builder(provider, provider_cfg, files_api_cfg) -> strategy
_BUILDERS: dict[str, Any] = {}


def register_strategy(type_name: str):
    """装饰器：把 builder 注册到 type 分发表。"""

    def deco(builder):
        _BUILDERS[type_name] = builder
        return builder

    return deco


@register_strategy("deepseek")
def _build_deepseek(provider: str, provider_cfg: dict, files_api_cfg: dict) -> FilesApiStrategy:
    from broca.media.deepseek_files import DeepSeekFilesStrategy

    return DeepSeekFilesStrategy(
        provider=provider, provider_cfg=provider_cfg, files_api_cfg=files_api_cfg
    )


def build_files_api_strategy(
    provider: str,
    model: str,
    files_api_cfg: dict,
    provider_cfg: dict | None,
) -> FilesApiStrategy | None:
    """按 ``files_api_cfg["type"]`` 构造对应策略；未配置/未知/解析失败 → None。

    None 会让 ``MediaMaterializer`` 走 base64 分支（安全兜底，不静默发 url）。
    """
    if not files_api_cfg:
        return None
    type_name = files_api_cfg.get("type")
    if not type_name:
        logger.warning(f"files_api 配置缺少 type（provider={provider}），回退 base64")
        return None
    builder = _BUILDERS.get(type_name)
    if builder is None:
        logger.warning(
            f"未知 files_api.type={type_name!r}（provider={provider}），回退 base64"
        )
        return None
    try:
        return builder(provider, provider_cfg or {}, files_api_cfg)
    except Exception as e:  # 配置解析失败不应阻断请求 → 回退 base64
        logger.warning(
            f"files_api strategy 构造失败（type={type_name}），回退 base64：{e}"
        )
        return None


def make_files_api_factory(llm_config: dict):
    """构造供 MediaMaterializer 注入的工厂 ``(provider, model, cfg) -> strategy|None``。

    ``llm_config`` 为完整的 LLM 配置（provider → {base_url, api_key, files_api, models...}）。
    ``cfg`` 为 provider 级 ``files_api`` 配置；为 None/空时自动从 ``provider_cfg`` 读取。
    """

    def factory(provider: str, model: str, files_api_cfg: dict | None = None):
        provider_cfg = (llm_config or {}).get(provider, {}) or {}
        if not files_api_cfg:
            files_api_cfg = provider_cfg.get("files_api")
        return build_files_api_strategy(provider, model, files_api_cfg, provider_cfg)

    return factory


__all__ = [
    "FilesApiStrategy",
    "build_files_api_strategy",
    "make_files_api_factory",
    "register_strategy",
]
