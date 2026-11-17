# media-ref-materialize — Phase 1: 持久化引用与展示 URL 分离 — Execution Report

## Overview

| Item | Content |
|------|---------|
| Plan File | plans/media-ref-materialize-plan.md |
| Phase | Phase 1: 持久化引用与展示 URL 分离 |
| Status | ✅ Pass |

## Plan Anchor Confirmation

- [x] Re-read the plan document section for this phase before starting
- [x] Acceptance criteria for each task confirmed

## Task Completion

| Task | Status | Plan ACs | Actual Result | Deviation |
|:----:|:------:|----------|---------------|-----------|
| Task 1.1: 新增 media ref 编解码工具 | ✅ | encode/decode/is_media_ref；两种 kind；非法返回 None；单测三类 | 新增 `broca/media/__init__.py` + `broca/media/ref.py`。`ref://` + base64url(json)。测试 23 passed | 无 |
| Task 1.2: 改造 read_image 产出 ref + 解耦云存储 | ✅ | 未配置 storage 不报错；local ref；cloud ref 含 storage_key/sha256/size；sha256 一致；测试更新 | `broca/tools/image.py`：新增 `_sha256_file`/`_local_preview_url`；移除强制 storage 校验；cloud→上传+cloud ref，否则→local ref + `/files/raw` 展示 url；data.files 带 sha256/size/local_path 或 storage_key | 无 |
| Task 1.3: 改造 parse_message 产出 ref | ✅ | storage_key→cloud / local_path→local / 旧数据原 url；无 base64；测试 | `broca/llm.py`：新增 `_resolve_file_ref_url`（5 级显式优先级判定）；image/video part 用 ref 占位 | 无 |
| Task 1.4: 后端 /files/raw 端点 | ✅ | 200+正确 Content-Type；目录/不存在 400/404；超大 413；穿越 403；类型白名单；同源说明 | `broca-web/backend/app/api/files.py`：新增 `GET /files/raw`，白名单根（`~/.broca/uploads`、`~/.broca` + DB session workspaces）+ `is_relative_to` 校验；image/video/audio 白名单；50MB 上限 | 无 |

> ✅ = All ACs met

## Acceptance Criteria Verification

### Phase-level
- ✅ 新产生的图片用户消息，DB content 中不含 `base64,`，含 `ref://` — `test_media_phase1::TestDbContent`
- ✅ 配置云存储时 `data.files[].url` 为真实 `https://` — `test_image_tool::TestS3Upload::test_upload_success_cloudflare`
- ✅ 未配置云存储时 `read_image` 成功、ref `kind=="local"`、`url` 为 `/files/raw?path=...` — `test_image_tool::TestLocalRef`
- ✅ 历史重建后 `_history` 中图片 part 仍为 ref — `test_media_phase1::TestHistoryRebuildPreservesRef`
- ✅ 旧数据（image_url 直接为 https）行为不变 — `test_parse_message_ref::test_plain_url_no_ref` + 既有 parse 测试

### Task-level
全部见上表「Actual Result」。

## Deviations

无。`parse_message` 对旧数据（无 storage_key/local_path/path）保持原 url，向后兼容；`read_image` 在无 agent 或模型不支持图片时返回文本链接（display_url），不产 ref，符合 plan 的「不支持模态→文本链接」要求。

## Quality Checklist

- [x] All phase-level ACs satisfied
- [x] All task-level ACs satisfied
- [x] No missing tasks (cross-referenced against plan: 1.1/1.2/1.3/1.4 全部覆盖)
- [x] No extra functionality (仅实现 ref 持久化 + /files/raw 展示；物化留待 Phase 2)
- [x] Manually verified key behaviors
- [x] Code follows project conventions
- [x] Compatible with existing work (280 相关测试通过)

## Test Summary

- `broca/tests/test_media_ref.py`: 23 passed
- `broca/tests/test_parse_message_ref.py`: 8 passed
- `broca/tests/test_image_tool.py`: 28 passed
- `broca/tests/test_media_phase1.py`: 2 passed
- `broca-web/backend/tests/test_files_raw.py`: 7 passed
- 回归 `pytest broca/tests -k "llm or parse_message or context or image or media or injected"`: 280 passed
