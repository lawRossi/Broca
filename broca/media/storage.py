"""云存储（Cloudflare R2 / Supabase S3）工具：S3 client 构建与对象字节读取。

从 ``broca/tools/image.py`` 抽出的公共逻辑，供图片上传与请求时物化（cloud ref
取字节）复用，避免重复实现。
"""

from __future__ import annotations

import asyncio
from typing import Any


def build_s3_client(storage: Any):
    """根据 ``StorageConfig`` 构建 boto3 S3 client。"""
    import boto3
    from botocore.client import Config as BotocoreConfig

    if storage.backend == "cloudflare":
        endpoint = f"https://{storage.cloudflare_account_id}.r2.cloudflarestorage.com"
        access_key_id = storage.cloudflare_access_key_id
        secret_key = storage.cloudflare_secret_access_key
    elif storage.backend == "supabase":
        endpoint = f"{storage.supabase_url}/storage/v1/s3"
        access_key_id = storage.supabase_s3_access_key_id
        secret_key = storage.supabase_s3_secret_access_key
    else:
        raise ValueError(f"Unsupported storage backend: {storage.backend}")

    return boto3.client(
        "s3",
        endpoint_url=endpoint,
        region_name="auto",
        aws_access_key_id=access_key_id,
        aws_secret_access_key=secret_key,
        config=BotocoreConfig(s3={"addressing_style": "path"}),
    )


def get_bucket(storage: Any) -> str:
    """返回当前存储后端的 bucket 名。"""
    if storage.backend == "cloudflare":
        return storage.cloudflare_bucket or "upload"
    elif storage.backend == "supabase":
        return storage.supabase_bucket or "upload"
    raise ValueError(f"Unsupported storage backend: {storage.backend}")


def get_public_url_base(storage: Any) -> str:
    """返回上传文件的公网 URL 前缀。"""
    if storage.backend == "cloudflare":
        return storage.cloudflare_public_url or (
            f"https://{storage.cloudflare_bucket}.{storage.cloudflare_account_id}.r2.dev"
        )
    elif storage.backend == "supabase":
        return f"{storage.supabase_url}/storage/v1/object/public/{storage.supabase_bucket}"
    raise ValueError(f"Unsupported storage backend: {storage.backend}")


def _get_object_sync(storage: Any, key: str) -> bytes:
    client = build_s3_client(storage)
    bucket = get_bucket(storage)
    resp = client.get_object(Bucket=bucket, Key=key)
    return resp["Body"].read()


async def read_cloud_bytes(storage: Any, ref: dict) -> bytes:
    """读取 cloud ref 指向的字节。

    优先用 boto3（项目已有依赖）按 ``key``/bucket 读取；当未配置可用存储后端或
    缺 ``key`` 时，按 ``ref["url"]`` 用 httpx HTTP GET 兜底。
    """
    key = ref.get("key")
    backend = getattr(storage, "backend", "") if storage is not None else ""
    if storage is not None and backend in ("cloudflare", "supabase") and key:
        return await asyncio.to_thread(_get_object_sync, storage, key)

    url = ref.get("url")
    if url:
        import httpx

        async with httpx.AsyncClient(timeout=30.0, follow_redirects=True) as client:
            resp = await client.get(url)
            resp.raise_for_status()
            return resp.content

    raise ValueError("cloud ref 缺少可用取数信息（既无 storage key 也无 url）")


__all__ = [
    "build_s3_client",
    "get_bucket",
    "get_public_url_base",
    "read_cloud_bytes",
]
