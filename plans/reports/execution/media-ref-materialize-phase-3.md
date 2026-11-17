# Media Ref Materialize — Phase 3: Files API 策略（DeepSeek 优先） — Execution Report

## Overview

| Item | Content |
|------|---------|
| Plan File | `plans/media-ref-materialize-plan.md` |
| Phase | Phase 3: Files API 策略（按 provider 差异，DeepSeek 优先） |
| Status | ✅ Pass |

## Plan Anchor Confirmation

- [x] Re-read the plan document Phase 3 section (lines 303–420) before starting
- [x] Acceptance criteria for each task confirmed

## Task Completion

| Task | Status | Plan ACs | Actual Result | Deviation |
|:----:|:------:|----------|---------------|-----------|
| Task 3.0: 双 key file 块 smoke | ✅ | smoke 给出「双 key 块是否被接受」结论；回填结论定 3.2 形态 | 真实 DeepSeek (`deepseek-flash`, `api.deepseek.com/v1`) 经 litellm `openai/` provider 发双 key 块 `{"type":"file","file":{"file_id":...},"file_id":...}`，模型正确识别红色测试图（返回 "Red"）→ **被接受**，无需回退。产出 `scripts/smoke_deepseek_file_block.py` | 实际模型 id 为 `deepseek-flash`；模板旧名 `deepseek-v4-flash` 为历史命名 |
| Task 3.1: FilesApiStrategy 接口与选择 | ✅ | 未配置/未知 type→None(materializer 走 base64)；type=deepseek→DeepSeekFilesStrategy；解析失败→None | `broca/media/files_api.py`：ABC + `register_strategy` + `build_files_api_strategy` + `make_files_api_factory`；materializer 改为**先解析策略再定模式**，strategy None→base64 兜底 | `upload()` 签名扩展为 `(ref, provider_cfg, data=None, cache=None, read_bytes=None)`（plan 写 2 参；materializer 需传 data/cache/read_bytes）。同步更新 1 个 Phase 2 测试（factory 早抛→upload 内抛） |
| Task 3.2: DeepSeekFilesStrategy | ✅ | mock 上传→双 key 块(非 base64)；同 sha 第二次命中缓存不重复 HTTP；非图/超大/上传抛错→明确报错；下发双 key 块用例通过 | `broca/media/deepseek_files.py`：内容嗅探(JPEG/PNG/GIF/WebP)、64MiB 上限、multipart POST `/files`（purpose + 可选 `expires_after`）、解析 `id`、返回双 key 块。`(provider, sha256(bytes))`→`{file_id,expires_at}` 缓存；缓存命中经 `read_bytes` 回调避免读源字节；过期重传。错误抛 `MediaMaterializeError`/`MediaFileTooLargeError`（不静默回退）。`llm.py` 注入 `make_files_api_factory(self.config)` | 缓存键用 `(provider, sha256(上传字节))`（含压缩后字节），比 plan 的 `(provider, sha256)` 更精确（同一原始图不同压缩阈值也正确区分） |
| Task 3.3: 配置模板与文档 | ✅ | 模板 JSON 合法；`max_inline_mb` 位于 `meta.media_limits` 且 `modality.image` 无业务字段；文档含字段/默认值/示例/provider 差异表/无 url 兜底策略 | 更新 `configs/llm_config_template.json`（deepseek-v4-flash 加 `meta.media_limits`（files_api 放 **provider 级**），Stepfun 加 `media_limits`）；`docs/configuration.md` 新增字段表、ref→wire 决策流程、files_api 字段表、示例、Provider 差异表（DeepSeek/Gemini/Anthropic/OpenAI） | 无 |
| Task 3.4: 端到端回归 | ✅ | 4 条 e2e 场景通过；`-k "media or image"` 全绿且不碰真实 `~/.broca/`；`test_tool_injected_message_order.py` 全绿 | `broca/tests/test_media_materialize_e2e.py`（6 测试）：cloud ref→base64；DeepSeek files_api→双 key 块 / 失败→LLMError；缓存复用不重复读；缓存命中源删仍可物化、缓存未命中+源删→报错 | 无 |

> ✅ = All ACs met, ⚠️ = Partial (reported), ❌ = Not completed

## Deviations

1. **`upload()` 签名扩展**（Task 3.1）：plan 写 `upload(ref, provider_cfg)`，实际 materializer 需传 `data`（压缩后字节）/`cache`（file_id 缓存）/`read_bytes`（命中缓存时避免读源字节）。这是满足「缓存命中不重复读取慢速存储」AC 的必要集成，已作为可选参数向后兼容。同步把 1 个 Phase 2 测试（`test_files_api_over_threshold_compress_fails_raises`）的「factory 早抛」改为「strategy.upload 内抛」——因 strategy 现在在阈值判断前解析。
2. **缓存键精度**（Task 3.2）：`(provider, sha256(上传字节))` 而非 plan 字面 `(provider, sha256)`，以正确区分「原图」与「压缩后字节」对应的不同 file_id。
3. **模板模型名**：smoke 确认真实模型 id 为 `deepseek-flash`；模板保留历史 `deepseek-v4-flash`（未改，避免影响其他引用），但把 `files_api`/`media_limits` 示例加在其上。

以上偏差均为实现必要性/正确性驱动，不降低任何 AC 标准。

## Task 3.0 Smoke 结论（回填「未解决的问题」）

- **双 key 块 `{"type":"file","file":{"file_id":...},"file_id":...}` 经 litellm `openai/` provider 发到 DeepSeek 被接受**（无 400，模型正确理解图片内容）。
- 因此 Task 3.2 采用双 key 块形态，**无需**回退到原生 HTTP / 猴补 / 内联 base64。

## Quality Checklist

- [x] All phase-level ACs satisfied
- [x] All task-level ACs satisfied
- [x] No missing tasks (3.0–3.4 全部完成)
- [x] No extra functionality (仅实现 plan 要求)
- [x] Manually verified key behaviors (真实 API smoke + e2e)
- [x] Code follows project conventions
- [x] Compatible with existing work (全量回归通过)

## Test Summary

| Suite | Result |
|-------|--------|
| `broca/tests/test_media_files_api.py` (Task 3.1) | 8 passed |
| `broca/tests/test_media_deepseek_files.py` (Task 3.2) | 9 passed |
| `broca/tests/test_llm_config_template_media.py` (Task 3.3) | 4 passed |
| `broca/tests/test_media_materialize_e2e.py` (Task 3.4) | 6 passed |
| `-k "media or image"` | 127 passed |
| `test_tool_injected_message_order.py` | 11 passed |
| **Full `broca/tests`** | **1717 passed, 2 skipped, 1 deselected** |

## Files Changed

**New**
- `broca/media/files_api.py` — FilesApiStrategy ABC + registry + factory
- `broca/media/deepseek_files.py` — DeepSeekFilesStrategy + sniff_image_mime
- `scripts/smoke_deepseek_file_block.py` — Task 3.0 smoke
- `broca/tests/test_media_files_api.py`
- `broca/tests/test_media_deepseek_files.py`
- `broca/tests/test_llm_config_template_media.py`
- `broca/tests/test_media_materialize_e2e.py`

**Modified**
- `broca/media/materializer.py` — 先解析策略再定模式；strategy None→base64；`_via_files_api` 传 read_bytes 回调
- `broca/media/__init__.py` — 导出 FilesApiStrategy/build/make_factory
- `broca/llm.py` — 注入 `make_files_api_factory(self.config)`
- `configs/llm_config_template.json` — media_limits + files_api 示例
- `docs/configuration.md` — 媒体字段 + 决策流程 + Provider 差异表
- `broca/tests/test_media_materializer.py` — 1 个测试适配（factory 早抛→upload 内抛）+ stub 加 read_bytes
- `broca/tests/test_media_get_stream_response.py` — stub 加 read_bytes

---

## 后续修正（Phase 4 前）：files_api 上提为 provider 级

**背景**：用户指出 files_api 配置在 model 的 `meta` 下不合理——上传端点/认证/配额是**供应商 API 级**能力，同一 provider 所有模型共享，放 model 级既冗余又易配漏。模型能否消费 file 块本就由 `meta.modality` 兜住。

**改动**（纯 provider 级，删除 model 级）：
- `broca/media/materializer.py`：`_resolve_part` 改读 `self._files_api_cfg(provider)`（provider 级 `config[provider]["files_api"]`）；新增 `_files_api_cfg` 辅助。
- `broca/media/files_api.py`：`make_files_api_factory` 的 cfg 参数可为 None，缺省时从 `provider_cfg["files_api"]` 自取。
- `configs/llm_config_template.json`：`files_api` 从 `models.deepseek-v4-flash.meta` 上提到 `deepseek.files_api`；`meta.media_limits` 保持 model 级。
- `docs/configuration.md` / `plans/media-ref-materialize-plan.md`：同步描述。
- 测试：`test_media_materializer/get_stream_response/materialize_e2e/files_api/llm_config_template_media` 的 make_config 与断言改为 provider 级；新增 `test_files_api_at_provider_level`。

**验证**：`broca/tests` 全量 **1718 passed, 2 skipped, 1 deselected**（较 Phase 3 基线 1717 +1 新测试）。真实 `configs/llm_config.json` 为 legacy 结构（无 files_api），无需迁移。
