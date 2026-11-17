"""Task 2.1: MediaMaterializer 决策树单测。

覆盖：模态不支持→文本链接；未配 files_api 小文件→base64；配 files_api→
注入 mock strategy 产出双 key 块；超阈值压缩达标→正常发送；压缩后仍超→抛错；
messages 原对象不被修改；非图片超阈值不压缩直接抛错；错误信息含文件名/大小/阈值/建议。
"""

import hashlib
import os

import pytest

from broca.media.errors import MediaFileTooLargeError
from broca.media.materializer import MediaMaterializer
from broca.media.ref import encode_media_ref

MB = 1024 * 1024


def make_config(*, modality=None, files_api=None, media_limits=None):
    meta = {"modality": modality if modality is not None else {"text": "", "image": {}}}
    if media_limits is not None:
        meta["media_limits"] = media_limits
    prov = {
        "base_url": "https://x",
        "api_key": "k",
        "models": {"m": {"model": "openai/x", "meta": meta}},
    }
    if files_api is not None:
        prov["files_api"] = files_api
    return {"prov": prov}


def local_ref(path: str, *, size: int | None = None, mime="image/png", sha="") -> str:
    if size is None:
        size = os.path.getsize(path)
    return encode_media_ref(
        {
            "kind": "local",
            "path": path,
            "url": f"/files/raw?path={path}",
            "sha256": sha or "deadbeef",
            "mime": mime,
            "size": size,
        }
    )


def image_msg(ref: str):
    return [
        {
            "role": "user",
            "content": [
                {"type": "image_url", "image_url": {"url": ref}},
                {"type": "text", "text": "hi"},
            ],
        }
    ]


class TestModalityUnsupported:
    @pytest.mark.asyncio
    async def test_downgrade_to_text_link(self):
        mat = MediaMaterializer(make_config(modality={"text": ""}))
        ref = encode_media_ref(
            {"kind": "local", "path": "/x.png", "url": "http://u/x.png",
             "sha256": "a", "mime": "image/png", "size": 10}
        )
        out = await mat.materialize_messages(image_msg(ref), "prov", "m")
        content = out[0]["content"]
        assert content[0] == {"type": "text", "text": "文件链接：http://u/x.png"}


class TestBase64Mode:
    @pytest.mark.asyncio
    async def test_small_image_becomes_base64(self, tmp_path):
        p = tmp_path / "a.png"
        data = b"\x89PNG\r\n\x1a\nhello-bytes"
        p.write_bytes(data)
        sha = hashlib.sha256(data).hexdigest()
        mat = MediaMaterializer(make_config())
        ref = local_ref(str(p), mime="image/png", sha=sha)
        out = await mat.materialize_messages(image_msg(ref), "prov", "m")
        url = out[0]["content"][0]["image_url"]["url"]
        assert url.startswith("data:image/png;base64,")
        import base64
        assert base64.b64decode(url.split(",", 1)[1]) == data

    @pytest.mark.asyncio
    async def test_over_threshold_compress_fits(self, tmp_path):
        # size 字段设为 >4MB，触发压缩分支；压缩返回小字节 → 正常发送
        mat = MediaMaterializer(make_config(media_limits={"max_inline_mb": 4}))
        ref = encode_media_ref(
            {"kind": "local", "path": "/nope.png", "url": "/x", "sha256": "s",
             "mime": "image/png", "size": 5 * MB}
        )

        async def fake_compress(_ref, _threshold, _cache=None):
            return b"small-bytes"

        mat._compress_to_fit = fake_compress
        out = await mat.materialize_messages(image_msg(ref), "prov", "m")
        url = out[0]["content"][0]["image_url"]["url"]
        assert url.startswith("data:image/png;base64,")

    @pytest.mark.asyncio
    async def test_over_threshold_compress_fails_raises(self):
        mat = MediaMaterializer(make_config(media_limits={"max_inline_mb": 4}))
        ref = encode_media_ref(
            {"kind": "local", "path": "/nope.png", "url": "/big.png", "sha256": "s",
             "mime": "image/png", "size": 5 * MB}
        )
        with pytest.raises(MediaFileTooLargeError) as ei:
            await mat.materialize_messages(image_msg(ref), "prov", "m")
        msg = str(ei.value)
        assert "/big.png" in msg
        assert "5.00MB" in msg
        assert "4.00MB" in msg
        assert ei.value.suggestion

    @pytest.mark.asyncio
    async def test_video_over_threshold_no_compress(self):
        """非图片超阈值：不尝试压缩，直接抛错。"""
        mat = MediaMaterializer(
            make_config(modality={"text": "", "video": {}}, media_limits={"max_inline_mb": 4})
        )
        called = {"n": 0}

        async def fake_compress(_ref, _threshold):
            called["n"] += 1
            return b"x"

        mat._compress_to_fit = fake_compress
        ref = encode_media_ref(
            {"kind": "local", "path": "/v.mp4", "url": "/v.mp4", "sha256": "s",
             "mime": "video/mp4", "size": 10 * MB}
        )
        msg = [{"role": "user", "content": [
            {"type": "video_url", "video_url": {"url": ref}},
            {"type": "text", "text": "hi"},
        ]}]
        with pytest.raises(MediaFileTooLargeError):
            await mat.materialize_messages(msg, "prov", "m")
        assert called["n"] == 0  # 未尝试压缩


class TestFilesApiMode:
    @pytest.mark.asyncio
    async def test_files_api_uses_injected_strategy(self):
        expected = {"type": "file", "file": {"file_id": "file-api-1"}, "file_id": "file-api-1"}

        class StubStrategy:
            async def upload(self, ref, cfg, data=None, cache=None, read_bytes=None):
                return dict(expected)

        def factory(provider, model, cfg):
            return StubStrategy()

        mat = MediaMaterializer(
            make_config(files_api={"type": "stub", "max_size_mb": 64}),
            files_api_factory=factory,
        )
        ref = encode_media_ref(
            {"kind": "local", "path": "/x.png", "url": "/x.png", "sha256": "s",
             "mime": "image/png", "size": 100}
        )
        out = await mat.materialize_messages(image_msg(ref), "prov", "m")
        assert out[0]["content"][0] == expected

    @pytest.mark.asyncio
    async def test_files_api_over_threshold_compress_fails_raises(self):
        class NoUploadStrategy:
            async def upload(self, ref, cfg, data=None, cache=None, read_bytes=None):
                raise AssertionError("should not upload when oversize")

        def factory(provider, model, cfg):
            return NoUploadStrategy()

        mat = MediaMaterializer(
            make_config(files_api={"type": "stub", "max_size_mb": 1}),
            files_api_factory=factory,
        )
        ref = encode_media_ref(
            {"kind": "local", "path": "/x.png", "url": "/x.png", "sha256": "s",
             "mime": "image/png", "size": 5 * MB}
        )
        with pytest.raises(MediaFileTooLargeError):
            await mat.materialize_messages(image_msg(ref), "prov", "m")


class TestNoMutation:
    @pytest.mark.asyncio
    async def test_original_messages_not_modified(self, tmp_path):
        p = tmp_path / "a.png"
        p.write_bytes(b"hello")
        mat = MediaMaterializer(make_config())
        ref = local_ref(str(p), mime="image/png", sha="s")
        original = image_msg(ref)
        import copy
        snapshot = copy.deepcopy(original)
        await mat.materialize_messages(original, "prov", "m")
        # 原对象引用未被就地改写
        assert original == snapshot
        assert original[0]["content"][0]["image_url"]["url"] == ref

    @pytest.mark.asyncio
    async def test_non_ref_message_passthrough(self):
        mat = MediaMaterializer(make_config())
        msgs = [{"role": "user", "content": "plain text"},
                {"role": "user", "content": [{"type": "image_url",
                                              "image_url": {"url": "https://x/a.png"}}]}]
        out = await mat.materialize_messages(msgs, "prov", "m")
        assert out[0]["content"] == "plain text"
        assert out[1]["content"][0]["image_url"]["url"] == "https://x/a.png"
