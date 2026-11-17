# 图片/文件按需物化改造计划 — Plan Review Report

## Overview

| Item | Content |
|------|---------|
| Plan File | `plans/media-ref-materialize-plan.md` |
| Reviewed At | 2026-11-10 |
| Overall Score | ⭐⭐⭐⭐ (4/5) |
| Verdict | ✅ Pass（附推荐改进项） |

### Dimension Scores

| # | Dimension | Score | Key Finding |
|:-:|-----------|:-----:|-------------|
| 1 | 📋 Completeness | ⭐⭐⭐⭐⭐ | 章节齐全，4 阶段 17 任务，均含目标/步骤/产出/AC；仅视频/音频路径覆盖偏薄 |
| 2 | 🔍 Clarity | ⭐⭐⭐⭐ | 文件路径/行号具体，但 `materialize_messages` 签名与调用不一致、`_via_files_api` 未单列实现步骤 |
| 3 | 🎯 AC Quality | ⭐⭐⭐⭐⭐ | AC 高度 SMART 化，多数可用单测/断言验证，质量优秀 |
| 4 | 🏗️ Feasibility | ⭐⭐⭐⭐ | 技术事实与代码库核对全部准确；litellm 透传不确定性已作开放项并有兜底 |
| 5 | 🔗 Structure & Dependencies | ⭐⭐⭐⭐ | 依赖图清晰、可并行点明确；2.1 决策树引用后置任务方法略超前 |
| 6 | ⚠️ Risk Identification | ⭐⭐⭐⭐⭐ | 14 条风险，覆盖安全/磁盘/缓存/透传/文件系统共享，应对具体可执行 |
| 7 | ⚖️ Proportionality | ⭐⭐⭐⭐⭐ | 复杂度高、任务粒度与阶段划分匹配，无过度/不足 |
| 8 | ✅ Internal Consistency | ⭐⭐⭐⭐ | 总体一致；存在函数签名不匹配、缓存与文件保留期张力、视频处理缺口 |
| | **Overall** | **⭐⭐⭐⭐** | **成熟可执行，建议先修 3 处一致性/覆盖问题再落地** |

## Detailed Findings

### 1. 📋 Completeness — ⭐⭐⭐⭐⭐

**Summary**：计划结构完整，涵盖概述、相关材料、总体方案、4 个阶段执行计划（每任务含目标/步骤/预期产出/验收标准）、依赖关系、风险与应对、未解决问题。关键路径与联动点（清理命令、session 删除、身份透传）均已列出。

| # | Severity | Location | Issue | Suggestion |
|:-:|:--------:|----------|-------|------------|
| 1 | Minor | 总体方案 / Phase 2 / Task 2.5 | 决策树以「part 模态」泛化，但压缩仅支持 `image/*`；视频在 base64 模式下超阈值必然压缩失败→报错，且未明确「无 files_api 时大视频」的产品预期 | 在总体方案或 Task 2.1/2.5 明确视频策略：无 files_api 时大视频直接报错（提示配置 files_api 或缩小文件），并补一条视频分支 AC |
| 2 | Minor | 总体方案 | `audio` 模态（现有 `parse_message` 为 `pass` 忽略）未被纳入 ref/物化讨论 | 在范围说明中显式声明「本期不含音频」，避免执行者误判为遗漏 |

### 2. 🔍 Clarity — ⭐⭐⭐⭐

**Summary**：绝大多数步骤可无歧义执行，文件名/行号/端点/字段都足够具体。少数引用与签名需要对齐。

| # | Severity | Location | Issue | Suggestion |
|:-:|:--------:|----------|-------|------------|
| 1 | Major | Task 2.1 vs Task 2.4 | Task 2.1 定义 `materialize_messages(self, messages, provider, model)`，但 Task 2.4 以 `materialize_messages(messages, provider, model, session_id=..., agent_id=...)` 调用，签名不匹配 | 在 Task 2.1 直接把签名定为 `materialize_messages(self, messages, provider, model, session_id=None, agent_id=None)` |
| 2 | Minor | Task 2.1 / 2.3 | `_via_files_api`、`_to_base64` 被多次引用，但未在任何任务的步骤里单独定义其签名与职责 | 在 Task 2.1 步骤中补一句明确 `_to_base64(ref)->str`、`_via_files_api(ref)->part` 的职责与返回形态 |
| 3 | Minor | Task 4.2 步骤 3 | `crypto.subtle` 在非 secure context 不可用的兜底「或提供纯 JS 兜底实现（如 js-sha256）」未定论，执行者需自行决定 | 明确结论（建议：新增 `js-sha256` 兜底并写进依赖/AC），或明确「仅支持 secure context」并在文档标注 |
| 4 | Minor | Task 4.1 vs `image.py` | 命名混用：Task 4.1 说「复用 `generateStoragePath` 命名规则」，而 Python 侧是 `_generate_storage_path`；前后端命名需澄清 | 注明后端复用 `_generate_storage_path`，前端仅为路径规则对齐，避免误解为调用同一函数 |

### 3. 🎯 AC Quality — ⭐⭐⭐⭐⭐

**Summary**：AC 质量优秀，绝大多数为可验证的 SMART 描述（如「`python -c "from PIL import Image; import httpx"` 通过」「第二次相同 sha256 命中缓存不重复 HTTP」「越界返回 403」）。

Good ACs identified:
- Task 2.3: 「`put` 后新建 `MediaCache` 实例（模拟进程重启）仍能 `get` 命中」— ✅ 可编程验证落盘复用。
- Task 1.4: 「路径穿越（如 `../../etc/passwd`）被拒绝，返回 403（基于 `is_relative_to`）」— ✅ 具体、安全相关、可测。
- Task 2.1: 「传入的 `messages` 原对象不被修改（引用不变）」— ✅ 直接对应「不污染历史」的核心约束。

| # | Severity | Location | AC | Issue | Suggestion |
|:-:|:--------:|:--------:|----|-------|------------|
| 1 | Minor | Phase 4 阶段 AC | 「聊天里图片可正常显示」 | 偏人工/主观，缺少可判定标准 | 补充「`<img>` 请求 `/files/raw` 返回 200 且 Content-Type 为 image/*」等可断言条件 |
| 2 | Minor | Task 3.4 | 「`pytest ... -k "media or image"` 全绿」 | 未覆盖新增 `media` 之外可能受影响的解析/持久化用例 | 追加「`pytest broca/tests/test_tool_injected_message_order.py` 亦全绿」以守住顺序不回归 |

### 4. 🏗️ Feasibility — ⭐⭐⭐⭐

**Summary**：已对照代码库核验，计划对现状的描述全部准确：`read_image` 确在 `broca/tools/image.py:185` 强制校验 `storage.backend` 否则返回错误；`parse_message` 确有 `image_part.update(modality["image"])` 会混入 wire；`pyproject.toml` 当前仅 `boto3` 缺 `pillow/httpx`；`/files/preview` 确仅 `resolve()` 无根约束。依赖与身份透传链路识别到位。

| # | Severity | Location | Issue | Suggestion |
|:-:|:--------:|----------|-------|------------|
| 1 | Major | Task 3.2 / 未解决问题 | litellm 是否原样透传 DeepSeek `{"type":"file","file_id":...}` 存在实质不确定性，直接影响 Phase 3 核心价值 | 已列为开放项且有兜底方向；建议在 Phase 3 起始即做一次「探针」验证（最小脚本直连 `acompletion`），先于 3.2 全量实现，降低返工 |
| 2 | Minor | Task 2.4 | 身份透传需改 `_llm_strategy.call` + `RetryLLMStrategy._stream_once` 多处；「缺省回退进程级临时目录或 agent_id=unknown」在多子 agent 场景可能造成缓存串味 | 明确缺省策略：无 session/agent 时用独立临时目录并按 TTL 清理，或直接禁用落盘缓存仅内存 |

### 5. 🔗 Structure & Dependencies — ⭐⭐⭐⭐

**Summary**：阶段顺序合理（持久化→物化→Files API→前端上传解耦），依赖关系章节明确给出 1.1→1.2/1.3、2.0→2.1→2.2/2.3/2.5→2.4、2.3→2.6、3.1→3.2→3.4 等链条，Phase 4 可并行标注清晰。

| # | Severity | Location | Issue | Suggestion |
|:-:|:--------:|----------|-------|------------|
| 1 | Minor | Task 2.1 | 2.1 的决策树调用 `_read_bytes`(2.2)、缓存(2.3)、`_compress_to_fit`(2.5)，但这些任务编号在 2.1 之后，2.1 阶段实际需先搭桩 | 在 2.1 步骤注明「本任务先以最小桩/接口占位，2.2/2.3/2.5 完成后替换」，或在依赖图中把 2.2/2.3/2.5 置于 2.1 之前 |
| 2 | Minor | 依赖关系 | Task 2.6 同时依赖 2.3 与 2.4，但 2.4 又依赖 2.2/2.3/2.5，链条较长，未标注关键路径/可并行边界 | 显式标注「2.4 是关键路径收敛点」，便于排期 |

### 6. ⚠️ Risk Identification — ⭐⭐⭐⭐⭐

**Summary**：风险表 14 条，覆盖面广且具体：图片超阈值、R2 回源慢、ref 兼容旧数据、Files API 差异、litellm 拦截、物化污染历史、缓存磁盘增长/串味、local 文件被删、后端与 agent 不共享 FS、本地落盘占满、前后端结构不一致、依赖未声明、`/files/raw` 任意文件读取。每条都有可执行应对。

| # | Severity | Location | Issue | Suggestion |
|:-:|:--------:|----------|-------|------------|
| 1 | Minor | 风险表 | 缺少「缓存 base64 与本地文件保留期不一致」风险：文件 ≤2 天删除，但 base64 缓存 ≤3 天，缓存命中可用、未命中则报错，行为不一致 | 补一行：明确「命中缓存优先，未命中且文件已过期→报错提示重新上传」，并确认 e2e 覆盖 |

### 7. ⚖️ Proportionality — ⭐⭐⭐⭐⭐

**Summary**：属于跨持久化/物化/供应商适配/前后端的复杂改造，4 阶段 17 任务、含依赖与风险，细节密度与复杂度匹配，无过度工程，也无关键处含糊。

| # | Severity | Location | Issue | Suggestion |
|:-:|:--------:|----------|-------|------------|
| 1 | — | — | 未发现问题 | — |

### 8. ✅ Internal Consistency — ⭐⭐⭐⭐

**Summary**：纵向（任务 AC→阶段 AC→目标）与横向（命名、ref kind、缓存 key、阈值命名空间）总体一致。存在函数签名不匹配与保留期/视频处理两处需对齐。

| # | Severity | Location | Issue | Suggestion |
|:-:|:--------:|----------|-------|------------|
| 1 | Major | Task 2.1 vs 2.4 | `materialize_messages` 签名缺 `session_id/agent_id`（同 Clarity #1），属跨任务不一致 | 统一签名，见 Clarity 建议 |
| 2 | Minor | Phase 2 AC vs Task 2.1 | Phase 2 阶段 AC「配置 files_api 的图片以 file_id 引用」在 Phase 2 实为 stub `file_id="stub"`，虽已加括号说明，但与阶段 AC 措辞仍有轻微张力 | 阶段 AC 直接写「以（桩）`file_id` 引用验证分支；真实 file_id 于 Phase 3」，与任务措辞完全对齐 |
| 3 | Minor | Task 2.5 vs 决策树 | 决策树对超阈值统一走 `_compress_to_fit`，但该方法仅图片有效；对视频返回 None→报错，未在决策树显式分支 | 在决策树补「非 image 且不可压缩→直接抛 `MediaFileTooLargeError`」分支 |

## Issue Summary

| Severity | Count | Description |
|:--------:|:-----:|-------------|
| 🔴 Critical | 0 | Must fix before execution |
| 🟡 Major | 2 | Should fix for quality |
| 🟢 Minor | 10 | Consider improving |

### 🔴 Critical Issues (Must Fix)

无。

### 🟡 Major Issues (Should Fix)

| # | Dimension | Location | Issue | Suggestion |
|:-:|:---------:|:--------:|-------|------------|
| 1 | Clarity / Consistency | Task 2.1 vs 2.4 | `materialize_messages` 签名与调用不一致（缺 `session_id/agent_id`） | Task 2.1 直接定为 `materialize_messages(self, messages, provider, model, session_id=None, agent_id=None)` |
| 2 | Feasibility | Task 3.2 / 未解决问题 | litellm 透传 `{"type":"file","file_id":...}` 的不确定性直接影响 Phase 3 | Phase 3 起始先做最小探针验证，再决定 3.2 全量实现或自定义请求方案 |

### 🟢 Minor Issues (Consider)

| # | Dimension | Location | Issue | Suggestion |
|:-:|:---------:|:--------:|-------|------------|
| 1 | Completeness | Task 2.1/2.5 | 视频在 base64 模式超阈值必报错，策略未显式化 | 明确视频策略并补视频分支 AC |
| 2 | Completeness | 总体方案 | 音频模态未纳入，未声明「本期不含」 | 显式声明范围 |
| 3 | Clarity | Task 2.1/2.3 | `_via_files_api`/`_to_base64` 未单列定义步骤 | 补职责与返回形态说明 |
| 4 | Clarity | Task 4.2 | `crypto.subtle` 兜底未定论 | 明确采用 js-sha256 或限定 secure context |
| 5 | Clarity | Task 4.1 | `generateStoragePath` vs `_generate_storage_path` 命名 | 注明前后端对应关系 |
| 6 | AC | Phase 4 AC | 「正常显示」偏主观 | 补 `<img>` 200 + Content-Type 断言 |
| 7 | AC | Task 3.4 | 未覆盖顺序/持久化回归 | 追加 test_tool_injected_message_order 全绿 |
| 8 | Structure | Task 2.1 | 决策树引用后置任务方法 | 注明先搭桩或调整顺序 |
| 9 | Risk | 风险表 | 缺「缓存 TTL 与文件保留期不一致」风险 | 补一行并加 e2e 覆盖 |
| 10 | Consistency | Task 2.5/决策树 | 视频压缩返回 None→报错未在决策树显式分支 | 决策树补不可压缩→报错分支 |

## Verdict

**Overall Score**: 4/5 ⭐

**Verdict**: ✅ Pass（附推荐改进）

| Verdict | Condition |
|---------|-----------|
| ✅ **Pass** | No critical issues, all dimensions ≥ 3 stars. Plan is ready for execution. |

**Recommendation**:
1. 执行前优先修 2 个 Major：①统一 `materialize_messages` 签名；②在 Phase 3 起始加 litellm 透传「探针」任务。
2. 顺带处理低成本 Minor：视频/音频范围声明、`_via_files_api`/`_to_base64` 定义说明、`crypto.subtle` 兜底结论、缓存 TTL 与文件保留期一致性风险。
3. 上述均为局部文本修订，无需重新走完整评审；建议修订后由执行者直接进入 `create-tasks`。

**Summary**:
这是一份成熟、可执行的高质量计划：技术事实与代码库核对全部准确，AC 高度可验证，风险与依赖覆盖充分，分层（ref 持久化 ↔ 请求时物化）设计清晰且收敛点唯一。仅存在函数签名不一致、litellm 透传不确定性与视频/音频边界等少量一致性与覆盖问题，均不阻塞执行，建议按上述优先级快速修订后落地。
