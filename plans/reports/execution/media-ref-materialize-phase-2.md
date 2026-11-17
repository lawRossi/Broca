# 图片/文件按需物化改造 — Phase 2: 请求时物化管线 — 执行报告

## Overview

| Item | Content |
|------|---------|
| Plan File | `plans/media-ref-materialize-plan.md` |
| Phase | Phase 2: 请求时物化管线（files_api / base64，无 url 兜底） |
| Status | ✅ Pass |
| Tests | 全量 `broca/tests`: **1690 passed, 2 skipped, 1 deselected**；Phase 2 新增 6 个测试文件共 **41 passed** |

## Plan Anchor Confirmation

- [x] 开工前重读 plan Phase 2 全部 Task（2.0–2.6）目标/步骤/AC
- [x] 逐任务确认 AC 后再实现，全部满足

## Task Completion

| Task | Status | Plan ACs | Actual Result | Deviation |
|:----:|:------:|----------|---------------|-----------|
| 2.0 依赖声明（Pillow/httpx） | ✅ | import 通过；pyproject 含 pillow+httpx；install 无报错且锁更新 | pillow(12.3.0)/httpx(0.28.1) 可导入；pyproject 声明；`poetry lock --regenerate` 成功、`poetry check`=All set、`poetry install` 无报错 | 见下方「偏差说明」 |
| 2.1 MediaMaterializer + 决策树 | ✅ | 5 分支单测；原 messages 不变；非图片超阈值不压缩抛错；错误含名/大小/阈值/建议 | `broca/media/materializer.py` + `errors.py`；`_resolve_part` 决策树；无 ref 消息不深拷贝 | — |
| 2.2 存储字节读取（local/cloud） | ✅ | local 不触网；cloud 走 S3/HTTP；缺失抛错；base64 集成 | `broca/media/storage.py`；`_read_bytes` 分派；image.py 委托复用 | — |
| 2.3 全量持久化缓存（per-agent, TTL≤3天） | ✅ | 二次不重读；重启命中；agent 隔离；TTL 过期；clear/clear_session；仅落盘 | `broca/media/cache.py`（MediaCache） | — |
| 2.4 接入 get_stream_response | ✅ | mock 断言 ref→base64/file_id；无 ref 透传；per-agent 目录；超限转 LLMError | llm.py 物化 + 身份透传（strategy.call→get_stream_response） | 见下方 |
| 2.5 图片压缩降采样 | ✅ | >4MB 压到阈值内可打开；非图片 None；二次命中压缩缓存；不改原文件 | `_compress_to_fit` + `_compress_bytes_sync`（Pillow 长边2048/JPEG循环降质降尺寸） | — |
| 2.6 缓存生命周期清理 | ✅ | 四路径清理；失败不抛异常 | clear_context/clear_all_context/clear_history/cleanup_session 联动 | — |

## Phase 验收标准逐条核对

- [x] 未配 files_api、`size<=max_inline_mb` → 请求体 base64：`test_ref_becomes_base64`
- [x] 配 files_api → 桩 file_id（不发 base64）：`test_ref_becomes_file_id`（双 key 块）
- [x] 超阈值先压缩、达标正常发送：`test_over_threshold_compress_fits`
- [x] 压缩后仍超 → 抛明确错误提醒：`test_too_large_becomes_llm_error` / `test_oversize_after_compress_raises_in_materialize`
- [x] 不支持图像模态 → 文本链接：`test_downgrade_to_text_link`
- [x] 相同 sha256 二次命中缓存不重读、重启仍命中：`test_second_request_hits_cache_no_reread` / `test_new_instance_hits_persisted`
- [x] 缓存 (session_id, agent_id) 隔离 + clear_context/clear_all_context/删 session 联动 + >3 天过期：`TestClear`/`TestTTL`/`test_media_cache_cleanup.py`
- [x] 物化前后 `context._history` 不变（仍为 ref）：`test_original_messages_not_modified` / `test_non_ref_passthrough`

## 新增/修改文件

**新增**
- `broca/media/materializer.py` — `MediaMaterializer`（决策树 + base64 + files_api 委托 + 压缩 + 缓存接入）
- `broca/media/errors.py` — `MediaFileTooLargeError` / `MediaMaterializeError`
- `broca/media/cache.py` — `MediaCache`（全量持久化、per-agent、TTL≤3天、clear/clear_session/gc_expired）+ `clear_session_cache`
- `broca/media/storage.py` — `build_s3_client` / `get_bucket` / `get_public_url_base` / `read_cloud_bytes`（S3 优先、httpx 兜底）
- 测试：`test_media_materializer.py`(9) `test_media_storage_read.py`(6) `test_media_cache.py`(12) `test_media_compress.py`(5) `test_media_get_stream_response.py`(5) `test_media_cache_cleanup.py`(5)

**修改**
- `broca/llm.py` — `LiteLLMClient.__init__` 构建 materializer；`get_stream_response` 增 `agent_id/session_id` 并物化；超限→LLMError
- `broca/components/llm_strategy.py` / `broca/loop_engine/strategies/retry_llm.py` / `broca/loop_engine/engine.py` — 透传 `agent_id/session_id`
- `broca/tools/image.py` — S3 client 逻辑委托到 `media/storage.py`
- `broca/commands/builtin/clear_context|clear_all_context|clear_history/__init__.py` — 联动清理缓存
- `broca/session/cleanup_service.py` — 删除 session 时清理 media_cache 目录
- `pyproject.toml` — 新增 pillow/httpx；`requires-python` 收窄 `>=3.12,<3.16`
- `poetry.lock` — 重新生成
- 测试替身签名修正：`test_llm_strategy.py` / `test_llm_strategy_golden.py` / `mock_components.py` / `test_engine_orchestration.py` / `test_turn_end_ordering.py`（`get_stream_response` / `call` 增 `agent_id/session_id`）

## 偏差说明

1. **Task 2.0 — poetry lock 阻塞的根因与修复（用户授权「升级 litellm、重新生成 lock」）**
   - 现象：`poetry lock` 失败，报「project python range >=3.15」。
   - 根因（-vvv 定位）：litellm 1.109.1 对 `tiktoken` 声明了三套条件依赖（`python_full_version < 3.14.0` / `== 3.14.*` / `>= 3.15.0`），在 `requires-python = ">=3.12,<4.0"`（含 3.16+）下触发 poetry 解析器缺陷，误推导出 `>=3.15` 范围；且 litellm 本身要求 `python < 3.16`，与 `<4.0` 冲突。
   - 修复：将 `requires-python` 由 `>=3.12,<4.0` 收窄为 **`>=3.12,<3.16`**（与 litellm 上限一致，语义正确）。`poetry lock --regenerate` 成功、`poetry check`=All set、`poetry install` 完成、锁含 pillow/httpx/litellm 1.109.1/tiktoken。uv 亦独立验证该依赖集在 3.14 可解析。
   - 说明：litellm 最新稳定版即 1.109.1（无更高版本），故实际未「升版本」，而是通过收窄 requires-python 使 lock 可生成。

2. **Task 2.4 — 测试替身签名**
   - 因 `LLMStrategy.call` / `get_stream_response` 新增可选 `agent_id/session_id`，5 个测试替身（fake strategy / fake client）需同步签名，已补为可选参数（向后兼容，默认 None）。

3. **跨任务桩替换**
   - 按 plan「桩先行」设计：2.1 以 `_read_bytes`(local) + `_compress_to_fit`(stub) + `cache_factory`(None) 起步，2.2/2.3/2.5 逐步替换为真实实现，2.4 收敛接入。最终代码无残留桩（cloud 读取、压缩、缓存均已落地）。

## Quality Checklist

- [x] 所有 phase 级 AC 满足
- [x] 所有 task 级 AC 满足
- [x] 无遗漏任务（对照 plan Phase 2 的 2.0–2.6 全覆盖）
- [x] 无越界功能（音频本期不纳入，与 plan 声明一致）
- [x] 关键行为手工/单测验证（决策树、缓存、压缩、清理、端到端接入）
- [x] 遵循项目约定（f-string 日志，通过 `test_no_percent_s_in_source_files`）
- [x] 与既有代码兼容（全量 1690 passed；旧 https 图片消息零改动透传）

## 备注

- 缓存默认目录 `<broca_home>/media_cache/<session_id>/<agent_id>/`；无身份调用回退 `unknown`。
- `files_api` 真实策略（DeepSeek）留待 Phase 3；Phase 2 以注入 strategy/mock 验证分支走向，`_via_files_api` 已定义委托契约（`upload(ref, cfg, data=None, cache=None)`）。
