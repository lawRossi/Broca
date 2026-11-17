"""Task 2.2: 存储字节读取单测（local 读盘 / cloud S3+httpx）。"""

import base64
from types import SimpleNamespace

import pytest

from broca.media import storage as storage_mod
from broca.media.errors import MediaMaterializeError
from broca.media.materializer import MediaMaterializer


def make_config():
    return {
        "prov": {
            "base_url": "https://x",
            "api_key": "k",
            "models": {"m": {"model": "openai/x", "meta": {"modality": {"text": "", "image": {}}}}},
        }
    }


def local_ref(path, data):
    import hashlib

    return {
        "kind": "local",
        "path": str(path),
        "url": "/files/raw?path=x",
        "sha256": hashlib.sha256(data).hexdigest(),
        "mime": "image/png",
        "size": len(data),
    }


def cloud_ref(key="uploads/a.png", url="https://r2/a.png"):
    return {
        "kind": "cloud",
        "key": key,
        "url": url,
        "sha256": "s",
        "mime": "image/png",
        "size": 10,
    }


class TestLocalRead:
    @pytest.mark.asyncio
    async def test_local_reads_bytes_without_network(self, tmp_path, monkeypatch):
        data = b"hello-local-bytes"
        p = tmp_path / "a.png"
        p.write_bytes(data)

        # 任何 S3 / httpx 调用都应报错 → 证明 local 不触网
        def boom(*a, **k):
            raise AssertionError("should not touch storage/network for local ref")

        monkeypatch.setattr(storage_mod, "build_s3_client", boom)

        class BoomClient:
            def __init__(self, *a, **k):
                raise AssertionError("should not create httpx client")

        import httpx
        monkeypatch.setattr(httpx, "AsyncClient", BoomClient)

        mat = MediaMaterializer(make_config(), storage=None)
        out = await mat._read_bytes(local_ref(p, data))
        assert out == data

    @pytest.mark.asyncio
    async def test_local_missing_raises(self, tmp_path):
        mat = MediaMaterializer(make_config(), storage=None)
        ref = local_ref(tmp_path / "nope.png", b"x")
        with pytest.raises(MediaMaterializeError):
            await mat._read_bytes(ref)

    @pytest.mark.asyncio
    async def test_to_base64_integration(self, tmp_path):
        data = b"\x89PNGdata"
        p = tmp_path / "a.png"
        p.write_bytes(data)
        mat = MediaMaterializer(make_config(), storage=None)
        url = await mat._to_base64(local_ref(p, data))
        assert url.startswith("data:image/png;base64,")
        assert base64.b64decode(url.split(",", 1)[1]) == data


class TestCloudRead:
    @pytest.mark.asyncio
    async def test_cloud_via_boto3(self, monkeypatch):
        data = b"cloud-object-bytes"
        fake_storage = SimpleNamespace(backend="cloudflare")

        class FakeBody:
            def read(self):
                return data

        class FakeClient:
            def get_object(self, Bucket, Key):
                assert Bucket == "upload"
                assert Key == "uploads/a.png"
                return {"Body": FakeBody()}

        monkeypatch.setattr(storage_mod, "build_s3_client", lambda s: FakeClient())
        monkeypatch.setattr(storage_mod, "get_bucket", lambda s: "upload")

        out = await storage_mod.read_cloud_bytes(fake_storage, cloud_ref())
        assert out == data

    @pytest.mark.asyncio
    async def test_cloud_via_httpx_fallback(self, monkeypatch):
        data = b"http-object-bytes"

        class FakeResp:
            content = data

            def raise_for_status(self):
                pass

        class FakeClient:
            def __init__(self, *a, **k):
                pass

            async def __aenter__(self):
                return self

            async def __aexit__(self, *a):
                return False

            async def get(self, url):
                assert url == "https://r2/a.png"
                return FakeResp()

        import httpx
        monkeypatch.setattr(httpx, "AsyncClient", FakeClient)

        # storage=None → 走 httpx 兜底
        out = await storage_mod.read_cloud_bytes(None, cloud_ref())
        assert out == data

    @pytest.mark.asyncio
    async def test_cloud_via_materializer(self, monkeypatch):
        data = b"cloud-bytes"
        fake_storage = SimpleNamespace(backend="supabase")

        class FakeBody:
            def read(self):
                return data

        class FakeClient:
            def get_object(self, Bucket, Key):
                return {"Body": FakeBody()}

        monkeypatch.setattr(storage_mod, "build_s3_client", lambda s: FakeClient())
        monkeypatch.setattr(storage_mod, "get_bucket", lambda s: "upload")

        mat = MediaMaterializer(make_config(), storage=fake_storage)
        out = await mat._read_bytes(cloud_ref())
        assert out == data
