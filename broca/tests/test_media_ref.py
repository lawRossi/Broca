"""media ref 编解码工具单元测试。"""

import base64
import json

import pytest

from broca.media.ref import (
    REF_SCHEME,
    decode_media_ref,
    encode_media_ref,
    is_media_ref,
)


CLOUD_META = {
    "kind": "cloud",
    "key": "uploads/20260101/photo_ab12.png",
    "url": "https://cdn.example.com/uploads/20260101/photo_ab12.png",
    "sha256": "abc123",
    "mime": "image/png",
    "size": 1234,
}

LOCAL_META = {
    "kind": "local",
    "path": "/tmp/图片 test.png",
    "url": "/files/raw?path=%2Ftmp%2F%E5%9B%BE%E7%89%87",
    "sha256": "def456",
    "mime": "image/png",
    "size": 5678,
}


class TestRoundTrip:
    def test_cloud_roundtrip(self):
        ref = encode_media_ref(CLOUD_META)
        assert ref.startswith(REF_SCHEME)
        decoded = decode_media_ref(ref)
        assert decoded == CLOUD_META

    def test_local_roundtrip(self):
        ref = encode_media_ref(LOCAL_META)
        decoded = decode_media_ref(ref)
        assert decoded == LOCAL_META

    def test_chinese_and_special_chars(self):
        meta = {
            "kind": "local",
            "path": "/tmp/中文目录/图片 ①&?.png",
            "url": "https://例子.com/a b/图片.png?x=1&y=2",
            "sha256": "s",
            "mime": "image/png",
            "size": 1,
        }
        assert decode_media_ref(encode_media_ref(meta)) == meta

    def test_empty_url_allowed(self):
        meta = {
            "kind": "local",
            "path": "/tmp/x.png",
            "url": "",
            "sha256": "s",
            "mime": "image/png",
            "size": 1,
        }
        assert decode_media_ref(encode_media_ref(meta)) == meta


class TestIsMediaRef:
    def test_true_for_valid_ref(self):
        assert is_media_ref(encode_media_ref(CLOUD_META)) is True

    @pytest.mark.parametrize(
        "value",
        [
            "https://cdn.example.com/a.png",
            "",
            "ref://",
            "ref://!!!not-base64!!!",
            "not-a-ref",
            None,
            123,
            [],
        ],
    )
    def test_false_for_invalid(self, value):
        assert is_media_ref(value) is False


class TestDecodeInvalid:
    def test_missing_kind(self):
        payload = {k: v for k, v in CLOUD_META.items() if k != "kind"}
        ref = REF_SCHEME + base64.urlsafe_b64encode(
            json.dumps(payload).encode()
        ).decode().rstrip("=")
        assert decode_media_ref(ref) is None

    def test_invalid_kind(self):
        payload = dict(CLOUD_META, kind="ftp")
        ref = REF_SCHEME + base64.urlsafe_b64encode(
            json.dumps(payload).encode()
        ).decode().rstrip("=")
        assert decode_media_ref(ref) is None

    def test_missing_required_field(self):
        payload = {k: v for k, v in LOCAL_META.items() if k != "path"}
        ref = REF_SCHEME + base64.urlsafe_b64encode(
            json.dumps(payload).encode()
        ).decode().rstrip("=")
        assert decode_media_ref(ref) is None

    def test_cloud_missing_key(self):
        payload = {k: v for k, v in CLOUD_META.items() if k != "key"}
        ref = REF_SCHEME + base64.urlsafe_b64encode(
            json.dumps(payload).encode()
        ).decode().rstrip("=")
        assert decode_media_ref(ref) is None

    def test_invalid_base64(self):
        assert decode_media_ref(REF_SCHEME + "!!!@@@") is None

    def test_invalid_json(self):
        bad = base64.urlsafe_b64encode(b"not json").decode().rstrip("=")
        assert decode_media_ref(REF_SCHEME + bad) is None

    def test_not_dict(self):
        bad = base64.urlsafe_b64encode(b"[1,2,3]").decode().rstrip("=")
        assert decode_media_ref(REF_SCHEME + bad) is None


class TestEncodeValidation:
    def test_rejects_non_dict(self):
        with pytest.raises(ValueError):
            encode_media_ref("nope")  # type: ignore[arg-type]

    def test_rejects_invalid_kind(self):
        with pytest.raises(ValueError):
            encode_media_ref({"kind": "ftp"})

    def test_rejects_missing_fields(self):
        with pytest.raises(ValueError):
            encode_media_ref({"kind": "local"})
