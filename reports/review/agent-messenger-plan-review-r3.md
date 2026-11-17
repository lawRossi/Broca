# AgentMessenger — 统一 Agent 间通信通道 — Plan Review Report (Round 3)

## Overview

| Item | Content |
|------|---------|
| Plan File | `plans/agent-messenger-plan.md` |
| Reviewed At | 2026-11-16 |
| Review Round | Round 3（前序 r1 / r2 的 Critical/Major 已在计划中标注消解） |
| Overall Score | ⭐⭐⭐⭐ (≈3.75) |
| Verdict | ⚠️ Conditional Pass |

### Dimension Scores

| # | Dimension | Score | Key Finding |
|:-:|-----------|:-----:|-------------|
| 1 | 📋 Completeness | ⭐⭐⭐⭐ | 全部章节齐备；Task 2.1 未展示 `set_call_chain` / `reset_budget` 两个抽象方法的具体实现 |
| 2 | 🔍 Clarity | ⭐⭐⭐⭐ | 语义清晰、契约统一；个别伪代码缩进错乱、`_resolve_agent_id` 重复解析 |
| 3 | 🎯 AC Quality | ⭐⭐⭐⭐ | AC 高度 SMART、可测；少数 AC 为复合断言（一条含多个子条件） |
| 4 | 🏗️ Feasibility | ⭐⭐⭐ | **CallChain 起点缺自身 agent_id，导致核心防死锁在"首跳"失效**；`asyncio.get_event_loop()` 在 3.14 已弃用；`TaskManager.get_task` 异步假设未核实 |
| 5 | 🔗 Structure & Dependencies | ⭐⭐⭐⭐⭐ | Phase 0→1→2→3 递进合理；ACK 前移、2.1↔2.4 依赖倒置已消除 |
| 6 | ⚠️ Risk Identification | ⭐⭐⭐⭐ | 风险表 15 项、覆盖充分；但"嵌套 run 不自死锁"的缓解措施受第 4 维 bug 削弱 |
| 7 | ⚖️ Proportionality | ⭐⭐⭐⭐ | 对子系统替换+并发场景，细节量合理；顶部三段修订记录属过程噪声可精简 |
| 8 | ✅ Internal Consistency | ⭐⭐⭐ | 存在"声称的环检测保护"与"实际链路实现"的不一致；`reply()` 与 `request/notify/delegate` 的 ACK 处理不一致 |
| | **Overall** | **⭐⭐⭐⭐** | 高成熟度计划，但有 1 个削弱核心机制的 Major 设计缺陷需在 Phase 2 前修复 |

## Detailed Findings

### 1. 📋 Completeness — ⭐⭐⭐⭐

**Summary**: 概述 / 相关材料 / 总体方案 / 执行计划 / 风险与应对 / 未解决的问题 全部齐备，Phase 0 前置验证、每个 Task 均有目标/步骤/预期产出/AC，材料引用详实。存在一处实现步骤缺口。

| # | Severity | Location | Issue | Suggestion |
|:-:|:--------:|----------|-------|------------|
| 1 | Minor | Task 2.1 步骤 1 | `AgentMessenger` ABC 要求 8 个抽象方法，但 Task 2.1 的 `DefaultAgentMessenger` 伪代码只实现了 `initialize / request / reply / handle_request_response / notify / delegate` 及私有辅助，**未展示 `set_call_chain` 与 `reset_budget` 的实现**。这两个是 `run()` 入口依赖的必实现方法，缺失会导致抽象类无法实例化。 | 在 Task 2.1 步骤中补 `def set_call_chain(self, chain): self._call_chain = chain` 与 `def reset_budget(self): self._budget.reset()`，并在 AC 增加"8 个抽象方法均已实现、可实例化"的断言。 |
| 2 | Minor | Task 1.3 / 2.1 | `AuditLogger(config.workspace if config is not None else "")`：当 `config is None` 时 workspace 为空串，审计落盘路径未定义。 | 明确 None 时的默认目录（如 `os.getcwd()` 或临时目录）或断言"生产路径恒传 config"。 |

### 2. 🔍 Clarity — ⭐⭐⭐⭐

**Summary**: 契约表述精确（`send() -> dict`、`get_agent` 同步、`request` 返回 `(text, status)`），"等 ACK vs 等回执"的核心区分在多处反复强调，歧义已被前两轮压缩到很低。剩余为编码层面小瑕疵。

| # | Severity | Location | Issue | Suggestion |
|:-:|:--------:|----------|-------|------------|
| 1 | Minor | Task 2.3 `Communicate._execute`、Task 2.1 `_check_permissions` | 伪代码块存在缩进错乱（如 `try:` 前多空格、`_check_permissions` 内 `# 可选：环检测` 段缩进与上下文不齐）。直接照抄会 `IndentationError`。 | 校对代码块缩进，保证可直接粘贴通过 `python -c "import ast; ast.parse(...)"`。 |
| 2 | Minor | Task 2.1 `notify()` / `_check_with_mode` | `_check_with_mode` 内已 `target_id = self._resolve_agent_id(...)`，`notify()` 返回后又 `target_id = self._resolve_agent_id(target_name)` 二次解析，逻辑重复且两次解析间无一致性保证。 | 让 `_check_with_mode` 返回 `(ok, reason, target_id)` 或先解析一次后复用。 |
| 3 | Minor | Task 2.1 `_check_with_mode` | 声明为 `async def` 却仅返回同步 `_check_permissions(...)` 结果，`request()` 则直接调同步版本，风格不统一。 | 统一为同步 `_check_with_mode`（或说明保留 async 的原因）。 |

### 3. 🎯 AC Quality — ⭐⭐⭐⭐

**Summary**: AC 质量整体很高——大量 AC 明确到方法名、返回结构、异常 `reason` 取值、grep 命令与测试文件名，可程序化验证。少数 AC 把多个断言塞进一条复选框。

Good ACs identified:
- Task 2.1: "`request()` 持有 pending + `asyncio.wait_for(event.wait(), timeout=request_timeout)`，返回 `(回复文本, 回复状态)`，`status ∈ success/error/aborted`" — ✅ 具体、可断言。
- Task 3.3: "`grep -rn "assign_task\|task_start\|...\|create_task_" broca/ --include=*.py --exclude-dir=alembic` 无结果" — ✅ 可机械验证。
- Task 2.4: "路由失败时 `send()` 返回 `{"status": "routing_failed", ...}`" — ✅ 明确的返回结构。

| # | Severity | Location | AC | Issue | Suggestion |
|:-:|:--------:|:--------:|----|-------|------------|
| 1 | Minor | Task 2.1 / 2.2 | 多条 AC 形如"X 且 Y 且 Z"（如"审计 result 取局部 final_result（routed/replied/timeout/routing_failed），routing_failed 不再误记为 timeout"） | 复合断言，部分失败时难定位 | 拆成独立复选框，便于逐条勾验 |

### 4. 🏗️ Feasibility — ⭐⭐⭐

**Summary**: 技术路线总体可行，ACK 通路的不确定性已用 Phase 0 门槛 + 备选方案兜住。但存在 1 个**削弱核心机制的设计缺陷**，以及 2 处运行时/接口假设需核实。

| # | Severity | Location | Issue | Suggestion |
|:-:|:--------:|----------|-------|------------|
| 1 | **Major** | Task 2.2 步骤 6（`run()`）+ Task 2.1 `request()`/`__init__` | **CallChain 在顶层 turn 缺失发起方自身 `agent_id`**。`run()` 中写作 `if call_chain: self.messenger.set_call_chain(call_chain.add(self.agent_id))`（plan L1149-1150）。当顶层用户 turn 触发时 `call_chain=None`，`self._call_chain` 保持 `__init__` 里的空 `CallChain()`，**发起方自身 id 从未入链**。于是 A 顶层发起 `request(B)` 时随消息发送的 `call_chain` 为 `{}`；B 收到后 `B.run` 得链 `[B]`；B 在 run 中回发 `request(A)` 时 `would_create_cycle(A)` 判 `A ∈ [B]` 为 **False**，环检测**不触发**。这恰好是计划反复声称"投递前就拦截、不会走到嵌套 run 拿锁"的 A↔B 互 request 死锁场景——实际只能靠 300s 超时兜底，风险表"request 循环死锁"与 Task 3.2"嵌套 run 不自死锁"测试的前提不成立。 | `run()` 入口无条件把自身 id 入链：`self.messenger.set_call_chain((call_chain or CallChain()).add(self.agent_id))`（去掉 `if call_chain:` 守卫）；并在 Task 3.2 增加断言"顶层 A 发起的 request，其 `call_chain` 已含 A"，确保首跳环检测生效。 |
| 2 | Minor | Task 1.4 `_send_message_with_ack` | `loop = asyncio.get_event_loop()` 在 Python 3.10+ 已弃用、3.14 在无运行 loop 时会告警/异常；当前处于 async 上下文应取运行中 loop。 | 改为 `asyncio.get_running_loop().create_future()`。 |
| 3 | Minor | Task 2.1 `_check_task_exists` / Task 2.2 `_handle_incoming_delegate` | 均 `await self._task_manager.get_task(task_id)`，但计划未核实 `TaskManager.get_task` 是否 `async`（相关材料仅列方法名）。若为同步方法，`await` 会报错。 | Phase 0 增加一项"确认 `TaskManager.get_task` 是否协程"；据此统一 `await` 或去掉 `await`。 |
| 4 | Minor | Task 2.1 `reply()` | `reply()` 直接 `await self.communicator.send(...)` 且忽略返回 dict，未走 `_send_and_check_ack`；若请求方已离线（`routing_failed`）静默丢弃且不写审计。 | 明确 `reply()` 的 ACK 语义（尽力而为）并至少记一条审计 `result=routing_failed`，避免与"三种模式都快速失败"的表述产生歧义。 |

### 5. 🔗 Structure & Dependencies — ⭐⭐⭐⭐⭐

**Summary**: Phase 递进合理（验证→骨架/删除→实现→测试），依赖声明清晰；ACK 能力前移 Task 1.4、消除 2.1↔2.4 依赖倒置；TASK_* 删除（Task 1.1）与 AGENT_NOTIFY 注入（Task 2.2）分两阶段集中处理，边界明确；测试更新时序统一收敛到 Task 3.3，消除了"全量 pytest 与测试更新"的时序冲突。未发现循环依赖或错序。

| # | Severity | Location | Issue | Suggestion |
|:-:|:--------:|----------|-------|------------|
| — | — | — | 无结构性问题 | — |

### 6. ⚠️ Risk Identification — ⭐⭐⭐⭐

**Summary**: 风险表 15 项，覆盖阻塞/死锁/滞留回复/级联刷屏/跨进程解析/删除断裂/ACK 改动/编排误用/delegate 静默悬空/回执丢失/terminal-step 边界等，缓解策略具体可执行，并映射到具体 Task 与 AC。唯一减分：核心死锁风险的缓解（环检测）受第 4 维 Major bug 削弱。

| # | Severity | Location | Issue | Suggestion |
|:-:|:--------:|----------|-------|------------|
| 1 | Minor | 风险表「request 循环死锁」 | 缓解措施断言"CallChain 随请求传递（含 agent_id）……投递前就拦截"，但顶层发起方 id 未入链（见 Feasibility #1），缓解对该场景不成立。 | 修复 CallChain 起点后同步校正该风险条目的表述与 Task 3.2 对应测试。 |

### 7. ⚖️ Proportionality — ⭐⭐⭐⭐

**Summary**: 作为替换 `assign_task` 子系统、且引入阻塞式 request 与并发死锁边界的改动，多 Phase + 细粒度 AC + 详实风险表是相称的，未过度也非不足。可改进点：顶部堆叠了三段冗长的"修订记录"，属评审过程产物，混入计划正文降低可读性。

| # | Severity | Location | Issue | Suggestion |
|:-:|:--------:|----------|-------|------------|
| 1 | Minor | 文档头部 | 三段（用户澄清 / r2 / r1）修订记录占据开头约 30 行，属元信息。 | 移至文档末尾"变更历史"附录，正文开头只留最新结论一句摘要。 |

### 8. ✅ Internal Consistency — ⭐⭐⭐

**Summary**: 绝大部分横/纵向一致性良好（消息类型 4 类无 `AGENT_DELEGATE_RESPONSE`、`send()->dict` 贯穿、`get_agent` 同步三处口径一致、`config` 二义已澄清）。但存在"声称行为 vs 实现"和"方法间 ACK 处理"两类不一致。

| # | Severity | Location | Issue | Suggestion |
|:-:|:--------:|----------|-------|------------|
| 1 | **Major** | 总体方案「request 环检测为核心机制」/ 风险表 / Task 3.2 测试 vs Task 2.2 `run()` | 计划声称"request 环检测在投递前拦截 A↔B 死锁、不会走到嵌套 run 拿锁"，但 `run()` 的 `if call_chain:` 守卫使顶层发起方不入链，首跳环检测实际失效——**文字承诺与实现矛盾**（同一根因见 Feasibility #1）。 | 修复入链逻辑后，该一致性缺口随之闭合；建议在 Task 2.1/Task 3.2 AC 中显式断言"顶层 request 的 call_chain 含自身 id"。 |
| 2 | Minor | Task 2.1 `reply()` vs `request()/notify()/delegate()` | 后三者统一经 `_send_and_check_ack` 消费 ACK 并在 `routing_failed` 时抛错；`reply()` 直接 `communicator.send` 且忽略返回。三种"投递"路径的失败处理不一致。 | 明确区分并文档化：`reply()` 为协议义务的 best-effort（记录审计即可），其余为强失败语义；在 AC 里写清。 |
| 3 | Minor | Task 2.2 `_handle_incoming_delegate` | AC 要求"try/finally 保证三路径都回执"，伪代码却用 `try/except`（正常路径 notify 在 try 内、异常路径再 notify 一次），并非 `finally`；正常路径 notify 抛错会落入 except 再发一次"Failed"回执，可能双重回执。 | 统一为 `try/.../finally` 单次回执，或校正 AC 措辞使之与实现一致。 |

## Issue Summary

| Severity | Count | Description |
|:--------:|:-----:|-------------|
| 🔴 Critical | 0 | 无需在动工前阻断的致命问题 |
| 🟡 Major | 2 | 应在 Phase 2（Task 2.1/2.2）前修复：CallChain 起点缺自身 id（同一根因，跨 Feasibility/Consistency） |
| 🟢 Minor | 8 | 建议改进：抽象方法实现缺口、缩进/重复解析、get_event_loop 弃用、TaskManager 异步假设、reply ACK 语义、复合 AC、修订记录位置、try/finally 措辞 |

### 🔴 Critical Issues (Must Fix)
_无。_

### 🟡 Major Issues (Should Fix)

| # | Dimension | Location | Issue | Suggestion |
|:-:|:---------:|:--------:|-------|------------|
| 1 | 🏗️ Feasibility | Task 2.2 `run()` (L1149-1150) | 顶层 turn `call_chain=None` 时发起方自身 id 不入链，A↔B 互 request 的首跳环检测失效，核心防死锁退化为 300s 超时兜底 | `set_call_chain((call_chain or CallChain()).add(self.agent_id))` 无条件入链 + 补断言/测试 |
| 2 | ✅ Consistency | 总体方案/风险表/Task 3.2 vs Task 2.2 | "投递前拦截死锁"的承诺与实现矛盾（同根因） | 随 #1 修复闭合；校正风险条目与测试前提 |

### 🟢 Minor Issues (Consider)

| # | Dimension | Location | Issue | Suggestion |
|:-:|:---------:|:--------:|-------|------------|
| 1 | 📋 Completeness | Task 2.1 | 未展示 `set_call_chain` / `reset_budget` 实现 | 补实现 + 实例化 AC |
| 2 | 🔍 Clarity | Task 2.1/2.3 | 伪代码缩进错乱 | 校对缩进 |
| 3 | 🔍 Clarity | Task 2.1 `notify` | `target_id` 重复解析 | 解析一次复用 |
| 4 | 🏗️ Feasibility | Task 1.4 | `asyncio.get_event_loop()` 已弃用 | 用 `get_running_loop()` |
| 5 | 🏗️ Feasibility | Task 2.1/2.2 | `TaskManager.get_task` 异步假设未核实 | Phase 0 核实 |
| 6 | 🏗️ Feasibility | Task 2.1 `reply()` | ACK 失败静默、无审计 | 明确 best-effort 语义 + 审计 |
| 7 | ⚖️ Proportionality | 文档头部 | 三段修订记录混入正文 | 移入附录 |
| 8 | ✅ Consistency | Task 2.2 `_handle_incoming_delegate` | AC 说 try/finally，伪代码用 try/except 可能双重回执 | 统一措辞/实现 |

## Verdict

**Overall Score**: ⭐⭐⭐⭐ (≈3.75)

**Verdict**: ⚠️ Conditional Pass

| Verdict | Condition |
|---------|-----------|
| ✅ **Pass** | No critical issues, all dimensions ≥ 3 stars. |
| ⚠️ **Conditional Pass** | Minor critical issues OR some dimensions < 3 stars. Fix recommended before execution. |
| ❌ **Needs Revision** | Critical issues exist OR overall < 3 stars. |

> 严格按"无 Critical 且各维 ≥3"的机械标准本可判 Pass，但 Feasibility #1 / Consistency #1 是**同一根因的核心机制缺陷**（削弱计划反复承诺的防死锁能力），属"应当在动工前修正"的实质问题，故判 **Conditional Pass**。

**Recommendation**（按优先级）:

1. **【必修，动工前】修复 CallChain 起点入链**：将 `run()` 的 `if call_chain:` 改为无条件 `set_call_chain((call_chain or CallChain()).add(self.agent_id))`；在 Task 2.1 / Task 3.2 增加"顶层 request 的 call_chain 含自身 agent_id""A↔B 互 request 首跳即被 `chain_cycle` 拒绝"的断言与测试。修复后同步校正风险表「request 循环死锁」表述。
2. **【应修】补齐 `set_call_chain` / `reset_budget` 实现**，并加"8 抽象方法可实现、可经 Registry 实例化"AC。
3. **【建议】** 校正伪代码缩进、`get_event_loop`→`get_running_loop`、`reply()` 的 ACK/审计语义、`_handle_incoming_delegate` 的 try/finally 措辞；Phase 0 增补"`TaskManager.get_task` 是否 async"核实项。
4. 修订记录移入附录。

修复 1、2 后建议做一次轻量复核（Round 4 可仅覆盖 Feasibility/Consistency 两维）即可进入 `create-tasks`。

**Summary**:
这是一份成熟度很高的计划——契约统一、AC 可测、依赖清晰、风险覆盖面广，前两轮 Critical/Major 已实质消解。唯一实质性阻塞点是 CallChain 起点未包含发起方自身 id，导致计划反复强调的"request 环检测在投递前拦截死锁"在首跳场景失效（退化为 300s 超时兜底）。该缺陷定位明确、修复成本低（一行逻辑 + 两条断言），修复并补齐两个抽象方法实现后，本计划即可放心进入执行阶段。
