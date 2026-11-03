# broca-web LLM 配置管理 — 增强: 模型多模态配置编辑 — Execution Report

## Overview

| Item | Content |
|------|---------|
| Base Plan | plans/llm-config-management-plan.md（Phase 1/2 已交付） |
| Enhancement | 模型配置补充多模态（meta.modality）编辑能力 |
| Status | ✅ Pass |

## 语义调研（实现依据）

`broca/llm.py` L110: `self.config[provider]["models"][model]["meta"]["modality"]` — **meta.modality 为运行时必需字段**（缺失直接 KeyError）。能力语义：
- `text`: 标记位（值为 `""`）
- `image` / `video` / `audio`: **key 存在即启用**；值为 dict，会合并进对应请求体（如 `{"fp": 2}`、`{"detail": "high"}`）
- 未启用能力的附件降级为文本链接
- 运行时真实配置（~/.broca/configs/llm_config.json）15 个模型全部含 meta.modality

## Changes

| 文件 | 改动 |
|------|------|
| `backend/app/api/config.py` | `_validate_llm_config` 增强：每个模型必须含 dict 类型的 `meta` 与 `meta.modality`（防止保存后 Runner 端 KeyError） |
| `tests/integration/test_api_config.py` | VALID_CONFIG 补 meta；新增 4 个用例（modality 合法通过 / 缺 meta 400 / 缺 modality 400 / modality 非 dict 400）→ **15/15 通过** |
| `frontend/src/views/Settings.vue` | ① 模型表格新增「多模态」列：文本/图片/视频/音频 四个勾选框（key 存在即启用，取消即删除 key，保留已有参数值）② 每行「参数」按钮打开高级对话框：已启用能力的额外参数（JSON 编辑、格式校验、未启用能力禁用输入）③ 新增模型默认创建 `meta: {modality: {text: ""}}` ④ 保存前校验补 meta.modality 缺失检查 |

**追加调整（用户反馈）**：「上下文窗口」从参数对话框提升为模型表格独立列（与 Max Tokens 同级，el-input-number 可编辑/可清空）；参数对话框仅保留 image/video/audio 额外参数。实测：编辑 1000000→2000000 持久化 ✓、清空后 key 移除 ✓、对话框编辑视频参数 `{"fp": 4, "max_duration": 30}` 持久化且不再触碰 context_window ✓。

## Verification（浏览器端到端实测）

| 场景 | 结果 |
|------|------|
| 渲染真实配置 | ✅ deepseek 仅文本勾选；nvidia qwen3.5/gemma4 图片+视频勾选，与文件一致 |
| 勾选图片 + 参数 `{"detail": "high"}` → 保存 | ✅ 文件 `meta.modality.image == {"detail": "high"}`，context_window 保留 |
| 取消勾选图片 → 保存 | ✅ image key 移除，context_window 保留，其余模型不受影响 |
| 新增模型 | ✅ 默认 `meta: {modality: {text: ""}}` 持久化 |
| 删除模型 | ✅ 文件复原（15 模型） |
| 参数 JSON 非法 | ✅ 对话框确认时拦截提示 |
| 质量 | ✅ pytest 15/15；ruff config.py 0 错误；mypy 无新错误；pnpm lint 0 error；vue-tsc 通过；build:dev 成功 |

截图：`plans/reports/execution/assets/llm-config-modality-column.png`

## Deviations / Notes

1. **测试操作教训（非代码缺陷）**：E2E 中 `agent-browser find text "保存" click` 未命中按钮导致 PUT 未发出，一度误判「保存丢数据」；改用 ref 点击后一次通过。已通过 XHR/fetch 钩子与 server 日志双重确认功能链路正常。
2. 联调仍用临时配置副本（/tmp/llm_cfg_test），用户真实配置未被触碰；测试后环境已清理（浏览器/后端/vite 均停止）。
3. el-input-number 浮点显示精度为 Element Plus 固有行为，存储值正确。
