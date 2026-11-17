"""Task 3.0 smoke: 验证「双 key file 块」经 litellm openai provider 发到 DeepSeek 被接受。

背景（已抓包核验 + 本脚本实测）：
- litellm 用 ``openai/`` 前缀把 content part 原样透传给上游 OpenAI 兼容 API。
- 若只发裸 ``{"type":"file","file_id":...}``，litellm 的 pydantic 校验可能因缺少
  ``file`` 字段而拒绝；用**双 key** ``{"type":"file","file":{"file_id":...},"file_id":...}``
  可同时满足 litellm 校验（读到 ``file.file_id``）与 DeepSeek（读到顶层 ``file_id``）。

本脚本流程：
1. 生成一张纯色 PNG，POST ``{base_url}/files`` 上传，拿到 ``file-api-...`` 的 file_id。
2. 用 litellm ``acompletion`` 以 ``openai/deepseek-flash`` 发一次带双 key 块的请求，
   要求模型描述图片主色。
3. 若被接受（无 400 且模型能正确描述图片），结论=「双 key 块被接受」。
   否则按计划回退：①原生 HTTP 直发裸 file_id；②猴补 litellm；③放弃 file_id 用 base64。

用法：
    ./venv/bin/python scripts/smoke_deepseek_file_block.py \
        --api-key sk-xxx [--model deepseek-flash] [--base-url https://api.deepseek.com/v1]

退出码：0 = 双 key 块被接受；2 = 需要回退（见输出结论）。
"""

from __future__ import annotations

import argparse
import asyncio
import io
import json
import urllib.error
import urllib.request
import uuid

# 结论（供 Task 3.2 参考）：
#   Task 3.0 实测（deepseek-flash, api.deepseek.com/v1, 2026-11）：
#   ✅ 双 key 块 {"type":"file","file":{"file_id":...},"file_id":...} 被 DeepSeek 接受，
#      模型正确识别图片主色为 Red；无需回退。
CONCLUSION = "double-key-accepted"


def _make_png() -> bytes:
    from PIL import Image

    buf = io.BytesIO()
    Image.new("RGB", (64, 64), (255, 0, 0)).save(buf, format="PNG")
    return buf.getvalue()


def _upload_file(base_url: str, api_key: str, data: bytes) -> str:
    boundary = "----broca" + uuid.uuid4().hex
    parts: list[bytes] = []

    def field(name: str, value: str) -> None:
        parts.append(("--" + boundary + "\r\n").encode())
        parts.append((f'Content-Disposition: form-data; name="{name}"\r\n\r\n').encode())
        parts.append(value.encode() + b"\r\n")

    field("purpose", "user_data")
    parts.append(("--" + boundary + "\r\n").encode())
    parts.append(
        ('Content-Disposition: form-data; name="file"; filename="smoke.png"\r\n').encode()
    )
    parts.append(b"Content-Type: image/png\r\n\r\n")
    parts.append(data + b"\r\n")
    parts.append(("--" + boundary + "--\r\n").encode())

    req = urllib.request.Request(
        base_url.rstrip("/") + "/files",
        data=b"".join(parts),
        method="POST",
        headers={
            "Authorization": "Bearer " + api_key,
            "Content-Type": "multipart/form-data; boundary=" + boundary,
        },
    )
    with urllib.request.urlopen(req, timeout=60) as r:
        payload = json.loads(r.read())
    return payload["id"]


async def _try_litellm_double_key(
    base_url: str, api_key: str, model: str, file_id: str
) -> bool:
    from litellm import acompletion

    block = {"type": "file", "file": {"file_id": file_id}, "file_id": file_id}
    messages = [
        {
            "role": "user",
            "content": [
                {
                    "type": "text",
                    "text": "What is the dominant color of this image? Answer with one word.",
                },
                block,
            ],
        }
    ]
    try:
        resp = await acompletion(
            model=f"openai/{model}",
            api_base=base_url,
            api_key=api_key,
            messages=messages,
            max_tokens=500,
            timeout=60,
        )
    except Exception as e:  # noqa: BLE001
        print(f"[litellm] double-key REJECTED: {type(e).__name__}: {str(e)[:400]}")
        return False

    content = (resp.choices[0].message.content or "").strip()
    print(f"[litellm] double-key ACCEPTED, model answer: {content!r}")
    # 若模型能描述出红色，说明它确实读到了图片（而非空跑）
    return "red" in content.lower()


def _raw_bare_file_id(base_url: str, api_key: str, model: str, file_id: str) -> bool:
    body = json.dumps(
        {
            "model": model,
            "max_tokens": 200,
            "messages": [
                {
                    "role": "user",
                    "content": [
                        {"type": "text", "text": "Dominant color? One word."},
                        {"type": "file", "file_id": file_id},
                    ],
                }
            ],
        }
    ).encode()
    req = urllib.request.Request(
        base_url.rstrip("/") + "/chat/completions",
        data=body,
        method="POST",
        headers={"Authorization": "Bearer " + api_key, "Content-Type": "application/json"},
    )
    try:
        with urllib.request.urlopen(req, timeout=60) as r:
            d = json.loads(r.read())
        content = d["choices"][0]["message"].get("content") or ""
        print(f"[raw bare file_id] ACCEPTED, answer: {content!r}")
        return "red" in content.lower()
    except urllib.error.HTTPError as e:
        print(f"[raw bare file_id] HTTP {e.code}: {e.read().decode()[:300]}")
        return False


async def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--api-key", required=True)
    ap.add_argument("--base-url", default="https://api.deepseek.com/v1")
    ap.add_argument("--model", default="deepseek-flash")
    args = ap.parse_args()

    print("== Task 3.0: double-key file block smoke ==")
    file_id = _upload_file(args.base_url, args.api_key, _make_png())
    print(f"uploaded file_id = {file_id}")

    ok = await _try_litellm_double_key(args.base_url, args.api_key, args.model, file_id)
    if ok:
        print(f"CONCLUSION: {CONCLUSION} (no fallback needed)")
        return 0

    print("double-key not accepted/understood, trying raw bare file_id fallback ...")
    if _raw_bare_file_id(args.base_url, args.api_key, args.model, file_id):
        print("CONCLUSION: fallback-raw-bare-file-id (litellm needs monkey-patch or raw HTTP)")
        return 2

    print("CONCLUSION: fallback-to-base64 (file_id path not usable)")
    return 2


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
