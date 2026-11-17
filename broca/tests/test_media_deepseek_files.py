"""Task 3.2: DeepSeekFilesStrategy 单测。

覆盖：上传成功返回双 key 块（非 base64）；第二次相同 sha256 命中缓存不重复 HTTP；
非图片/超大/HTTP 错误 → 明确报错（不静默回退）；缓存命中避免读取源字节；
expires_at 过期视为未命中重新上传；sniff 图片类型；read_bytes 兜底路径。
"""

import hashlib
import io

import httpx
import pytest
from PIL import Image

from broca.media.deepseek_files import DeepSeekFilesStrategy, sniff_image_mime
from broca.media.errors import MediaFileTooLargeError, MediaMaterializeError

PROVIDER_CFG = {"base_url": "https://api.deepseek.com/v1", "api_key": "sk-test"}


def make_png(color=(255, 0, 0), size=32) -> bytes:
    buf = io.BytesIO()
    Image.new("RGB", (size, size), color).save(buf, format="PNG")
    return buf.getvalue()


class FakeCache:
    def __init__(self):
        self.store = {}

    async def get(self, key):
        return self.store.get(key)

    async def put(self, key, value, *, kind=""):
        self.store[key] = value


def install_transport(monkeypatch, handler):
    """让 strategy 内部 httpx.AsyncClient 使用 MockTransport。"""
    orig = httpx.AsyncClient

    def fake_client(*a, **kw):
        kw.pop("timeout", None)
        return orig(transport=httpx.MockTransport(handler), **kw)

    monkeypatch.setattr(httpx, "AsyncClient", fake_client)


class TestSniff:
    def test_png(self):
        assert sniff_image_mime(make_png()) == "image/png"

    def test_non_image(self):
        assert sniff_image_mime(b"not an image at all") is None


class TestUpload:
    @pytest.mark.asyncio
    async def test_upload_success_returns_double_key_block(self, monkeypatch):
        calls = {"n": 0, "req": None}

        def handler(request: httpx.Request) -> httpx.Response:
            calls["n"] += 1
            calls["req"] = request
            assert request.method == "POST"
            assert str(request.url).endswith("/files")
            return httpx.Response(200, json={
                "id": "file-api-123", "object": "file", "bytes": 10,
                "created_at": 1790000000, "filename": "a.png",
            })

        install_transport(monkeypatch, handler)
        strat = DeepSeekFilesStrategy(provider_cfg=PROVIDER_CFG, files_api_cfg={"type": "deepseek"})
        ref = {"kind": "local", "path": "/a.png", "url": "/a.png", "sha256": "x",
               "mime": "image/png", "size": 10}
        out = await strat.upload(ref, {"type": "deepseek"}, data=make_png(), cache=FakeCache())
        assert out == {"type": "file", "file": {"file_id": "file-api-123"}, "file_id": "file-api-123"}
        assert calls["n"] == 1

    @pytest.mark.asyncio
    async def test_second_same_sha_hits_cache_no_http(self, monkeypatch):
        calls = {"n": 0}

        def handler(request: httpx.Request) -> httpx.Response:
            calls["n"] += 1
            return httpx.Response(200, json={
                "id": "file-api-1", "created_at": 1790000000,
            })

        install_transport(monkeypatch, handler)
        strat = DeepSeekFilesStrategy(provider_cfg=PROVIDER_CFG, files_api_cfg={"type": "deepseek"})
        cache = FakeCache()
        data = make_png()
        ref = {"kind": "local", "path": "/a.png", "url": "/a.png", "sha256": "x",
               "mime": "image/png", "size": len(data)}
        out1 = await strat.upload(ref, {"type": "deepseek"}, data=data, cache=cache)
        out2 = await strat.upload(ref, {"type": "deepseek"}, data=data, cache=cache)
        assert out1 == out2 == {"type": "file", "file": {"file_id": "file-api-1"}, "file_id": "file-api-1"}
        assert calls["n"] == 1  # 第二次命中缓存，无第二次 HTTP

    @pytest.mark.asyncio
    async def test_cache_hit_via_ref_sha_avoids_read_bytes(self, monkeypatch):
        def handler(request):
            return httpx.Response(200, json={"id": "file-api-9", "created_at": 1790000000})

        install_transport(monkeypatch, handler)
        strat = DeepSeekFilesStrategy(provider_cfg=PROVIDER_CFG, files_api_cfg={"type": "deepseek"})
        cache = FakeCache()
        # 预置缓存：用 ref.sha256 作 key
        await cache.put(("deepseek", "refsha"), {"file_id": "file-api-9", "expires_at": None})
        called = {"read": 0}

        async def read_bytes():
            called["read"] += 1
            return make_png()

        ref = {"kind": "local", "path": "/a.png", "url": "/a.png", "sha256": "refsha",
               "mime": "image/png", "size": 10}
        out = await strat.upload(ref, {"type": "deepseek"}, data=None, cache=cache, read_bytes=read_bytes)
        assert out["file_id"] == "file-api-9"
        assert called["read"] == 0  # 命中缓存，未读取源字节

    @pytest.mark.asyncio
    async def test_non_image_raises(self, monkeypatch):
        strat = DeepSeekFilesStrategy(provider_cfg=PROVIDER_CFG, files_api_cfg={"type": "deepseek"})
        ref = {"kind": "local", "path": "/a.txt", "url": "/a.txt", "sha256": "x",
               "mime": "text/plain", "size": 5}
        with pytest.raises(MediaMaterializeError):
            await strat.upload(ref, {"type": "deepseek"}, data=b"hello", cache=None)

    @pytest.mark.asyncio
    async def test_oversize_raises(self, monkeypatch):
        strat = DeepSeekFilesStrategy(
            provider_cfg=PROVIDER_CFG,
            files_api_cfg={"type": "deepseek", "max_size_mb": 0},
        )
        ref = {"kind": "local", "path": "/a.png", "url": "/a.png", "sha256": "x",
               "mime": "image/png", "size": 10}
        with pytest.raises(MediaFileTooLargeError):
            await strat.upload(ref, {"type": "deepseek"}, data=make_png(), cache=None)

    @pytest.mark.asyncio
    async def test_http_error_raises(self, monkeypatch):
        def handler(request):
            return httpx.Response(400, text="bad request")

        install_transport(monkeypatch, handler)
        strat = DeepSeekFilesStrategy(provider_cfg=PROVIDER_CFG, files_api_cfg={"type": "deepseek"})
        ref = {"kind": "local", "path": "/a.png", "url": "/a.png", "sha256": "x",
               "mime": "image/png", "size": 10}
        with pytest.raises(MediaMaterializeError):
            await strat.upload(ref, {"type": "deepseek"}, data=make_png(), cache=None)

    @pytest.mark.asyncio
    async def test_expired_cache_entry_reuploads(self, monkeypatch):
        calls = {"n": 0}

        def handler(request):
            calls["n"] += 1
            return httpx.Response(200, json={"id": "file-api-new", "created_at": 1790000000})

        install_transport(monkeypatch, handler)
        strat = DeepSeekFilesStrategy(provider_cfg=PROVIDER_CFG, files_api_cfg={"type": "deepseek"})
        cache = FakeCache()
        data = make_png()
        sha = hashlib.sha256(data).hexdigest()
        # 预置一个已过期条目
        await cache.put(("deepseek", sha), {"file_id": "file-api-old", "expires_at": 1})
        ref = {"kind": "local", "path": "/a.png", "url": "/a.png", "sha256": sha,
               "mime": "image/png", "size": len(data)}
        out = await strat.upload(ref, {"type": "deepseek"}, data=data, cache=cache)
        assert out["file_id"] == "file-api-new"
        assert calls["n"] == 1
