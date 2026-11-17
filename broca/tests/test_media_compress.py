"""Task 2.5: 图片压缩降采样兜底单测。"""

import os

import pytest

from broca.media.cache import MediaCache
from broca.media.materializer import MediaMaterializer

MB = 1024 * 1024


def make_config():
    return {"prov": {"base_url": "x", "api_key": "k",
                     "models": {"m": {"model": "openai/x",
                                      "meta": {"modality": {"text": "", "image": {}}}}}}}


def _make_big_noise_png(path, size=1600):
    from PIL import Image
    raw = os.urandom(size * size * 3)
    img = Image.frombytes("RGB", (size, size), raw)
    img.save(path, format="PNG")
    return path


def _ref(path, mime="image/png"):
    import hashlib
    data = path.read_bytes()
    return {
        "kind": "local", "path": str(path), "url": "/x",
        "sha256": hashlib.sha256(data).hexdigest(),
        "mime": mime, "size": len(data),
    }


class TestCompress:
    @pytest.mark.asyncio
    async def test_big_image_compressed_below_threshold(self, tmp_path):
        p = _make_big_noise_png(tmp_path / "big.png", size=1600)
        assert p.stat().st_size > 4 * MB  # 源图 > 4MB
        threshold = 4 * MB
        mat = MediaMaterializer(make_config())
        out = await mat._compress_to_fit(_ref(p), threshold)
        assert out is not None
        assert len(out) < threshold
        # 能被 Pillow 正常打开
        import io
        from PIL import Image
        Image.open(io.BytesIO(out)).verify()

    @pytest.mark.asyncio
    async def test_non_image_returns_none(self, tmp_path):
        p = tmp_path / "v.mp4"
        p.write_bytes(b"not-an-image")
        mat = MediaMaterializer(make_config())
        out = await mat._compress_to_fit(_ref(p, mime="video/mp4"), 4 * MB)
        assert out is None

    @pytest.mark.asyncio
    async def test_second_time_hits_compress_cache(self, tmp_path):
        p = _make_big_noise_png(tmp_path / "big.png", size=1600)
        cache_root = tmp_path / "cache"
        mat = MediaMaterializer(make_config(),
                                cache_factory=lambda s, a: MediaCache(s, a, root=cache_root))
        ref = _ref(p)
        threshold = 4 * MB

        count = {"n": 0}
        orig = mat._compress_bytes_sync

        def counting(data, thr):
            count["n"] += 1
            return orig(data, thr)

        mat._compress_bytes_sync = counting

        await mat._compress_to_fit(ref, threshold, cache=MediaCache("s", "a", root=cache_root))
        await mat._compress_to_fit(ref, threshold, cache=MediaCache("s", "a", root=cache_root))
        assert count["n"] == 1  # 第二次命中压缩缓存，不重复压缩

    @pytest.mark.asyncio
    async def test_compress_does_not_modify_original(self, tmp_path):
        p = _make_big_noise_png(tmp_path / "big.png", size=1600)
        before = p.read_bytes()
        mat = MediaMaterializer(make_config())
        await mat._compress_to_fit(_ref(p), 4 * MB)
        assert p.read_bytes() == before  # 原文件未改动

    @pytest.mark.asyncio
    async def test_oversize_after_compress_raises_in_materialize(self, tmp_path):
        """压缩后仍超阈值 → 抛 MediaFileTooLargeError（集成决策树）。"""
        from broca.media.errors import MediaFileTooLargeError
        from broca.media.ref import encode_media_ref

        p = _make_big_noise_png(tmp_path / "big.png", size=1600)
        # 设一个极小的 media_limits，且 size 字段超大，强制走压缩且压不下去
        ref = encode_media_ref({
            "kind": "local", "path": str(p), "url": "/x",
            "sha256": "s", "mime": "image/png", "size": 100 * MB,
        })
        config = make_config()
        config["prov"]["models"]["m"]["meta"]["media_limits"] = {"max_inline_mb": 0}  # 阈值 0 → 必超
        mat = MediaMaterializer(config)
        msg = [{"role": "user", "content": [
            {"type": "image_url", "image_url": {"url": ref}},
            {"type": "text", "text": "hi"},
        ]}]
        with pytest.raises(MediaFileTooLargeError):
            await mat.materialize_messages(msg, "prov", "m")
