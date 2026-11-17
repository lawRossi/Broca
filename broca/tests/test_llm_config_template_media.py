"""Task 3.3: 配置模板媒体字段与文档一致性测试。

覆盖：模板 JSON 合法；media_limits/files_api 位于 meta（不在 meta.modality.image）；
modality.image 仅含 wire 允许键；parse_message 产出的 image_url part 不含业务配置字段。
"""

import json
import uuid
from pathlib import Path

from broca.llm import LiteLLMClient
from broca.session.models import Message, MessageType

TEMPLATE_PATH = Path(__file__).resolve().parents[2] / "configs" / "llm_config_template.json"

# modality.image 内允许的 wire 键（透传给供应商 image_url part 的合法键）
WIRE_IMAGE_KEYS = {"detail"}
# 绝不能出现在 modality.image 中的业务配置键
FORBIDDEN_IN_MODALITY = {"media_limits", "files_api", "max_inline_mb", "max_size_mb"}


def _load():
    return json.loads(TEMPLATE_PATH.read_text("utf-8"))


def _iter_models(cfg):
    for provider, pconf in cfg.items():
        for name, mconf in (pconf.get("models") or {}).items():
            yield provider, name, mconf


class TestTemplateStructure:
    def test_template_valid_json(self):
        cfg = _load()
        assert isinstance(cfg, dict) and cfg

    def test_media_config_at_meta_not_in_modality(self):
        cfg = _load()
        found_media = False
        for provider, name, mconf in _iter_models(cfg):
            meta = mconf.get("meta", {})
            modality = meta.get("modality", {})
            image = modality.get("image", {}) if isinstance(modality.get("image"), dict) else {}
            # modality.image 不得含业务配置键
            assert not (set(image.keys()) & FORBIDDEN_IN_MODALITY), (
                f"{provider}/{name}: media config leaked into modality.image: {image}"
            )
            # modality.image 仅 wire 允许键
            assert set(image.keys()) <= WIRE_IMAGE_KEYS, (
                f"{provider}/{name}: non-wire keys in modality.image: {image}"
            )
            # files_api 属 provider 级，绝不应出现在 model meta
            assert "files_api" not in meta, (
                f"{provider}/{name}: files_api 必须放 provider 级，不应在 model meta"
            )
            if "media_limits" in meta:
                found_media = True
                assert "max_inline_mb" in meta["media_limits"]
        assert found_media, "模板应至少含一个带 media_limits 的 model"

    def test_files_api_at_provider_level(self):
        cfg = _load()
        # 至少有一个 provider 在顶层配置 files_api，且其 model meta 内不含 files_api
        providers_with_fa = [
            p for p, pconf in cfg.items() if isinstance(pconf.get("files_api"), dict)
        ]
        assert providers_with_fa, "模板应在 provider 级配置 files_api"
        for p in providers_with_fa:
            assert "type" in cfg[p]["files_api"]
            for name, mconf in (cfg[p].get("models") or {}).items():
                assert "files_api" not in mconf.get("meta", {})

    def test_deepseek_files_api_example(self):
        cfg = _load()
        ds = cfg["deepseek"]
        fa = ds["files_api"]
        assert fa["type"] == "deepseek"
        assert fa["max_size_mb"] == 64
        meta = ds["models"]["deepseek-v4-flash"]["meta"]
        assert meta["media_limits"]["max_inline_mb"] == 4
        assert "image" in meta["modality"]
        assert "files_api" not in meta


class TestParseMessageCleanPart:
    def test_image_part_has_no_business_config(self):
        cfg = _load()
        client = LiteLLMClient(config=cfg)
        msg = Message(
            message_id=f"msg_{uuid.uuid4().hex[:16]}",
            session_id="s",
            role="user",
            message_type=MessageType.USER_MESSAGE,
            data={
                "content": "hi",
                "files": [
                    {
                        "name": "a.png",
                        "url": "https://cdn/a.png",
                        "type": "image/png",
                        "storage_key": "uploads/a.png",
                        "sha256": "abc",
                        "size": 10,
                    }
                ],
            },
        )
        result = client.parse_message("deepseek", "deepseek-v4-flash", msg)
        image_parts = [p for p in result["content"] if p.get("type") == "image_url"]
        assert image_parts, "应有 image_url part"
        part = image_parts[0]
        # part 顶层仅 type/image_url（及 wire 允许键）
        assert set(part.keys()) <= {"type", "image_url"} | WIRE_IMAGE_KEYS
        assert "media_limits" not in part and "files_api" not in part
        # image_url 仅 url（及 wire 允许键）
        assert set(part["image_url"].keys()) <= {"url"} | WIRE_IMAGE_KEYS
