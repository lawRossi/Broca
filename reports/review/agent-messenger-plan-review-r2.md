# AgentMessenger — 统一 Agent 间通信通道 · Plan Review Report (Round 2)

## Overview

| Item | Content |
|------|---------|
| Plan File | `plans/agent-messenger-plan.md` |
| Reviewed At | 2026-11-16 18:28:57 |
| Review Round | Round 2（针对第一轮评审修订后的复审） |
| Overall Score | ⭐⭐⭐⭐ (3.75/5) |
| Verdict | ⚠️ Conditional Pass |

> 本计划是依据 `reports/review/agent-messenger-plan-review.md`（Round 1）修订后的第二版。Round 1 的 1 Critical + 5 Major 根因已基本消解（`send() -> dict` 契约统一、`get_agent` 同步化、engine.py 3 处 TASK 清理纳入清单、Task 2.4 伪代码修正、2.1↔2.4 依赖倒置修复）。本次复审在**验证这些修复的同时**，发现 4 个新的 Major 级一致性问题（详见下文），建议修复后再进入 `create-tasks`。

### Dimension Scores

| # | Dimension | Score | Key Finding |
|:-:|-----------|:-----:|-------------|
| 1 | 📋 Completeness | ⭐⭐⭐⭐ | 结构完整、章节齐全；`config` 语义与 AuditLogger workspace 来源未闭环 |
| 2 | 🔍 Clarity | ⭐⭐⭐ | `initialize(config=...)` 存在 AgentConfig / CommunicationPolicy 二义；`force_chain_check` 为死参数；审计 result 归类有误 |
| 3 | 🎯 AC Quality | ⭐⭐⭐⭐ | AC 极其具体可测；但 request 预算 AC 与伪代码矛盾，无法达成 |
| 4 | 🏗️ Feasibility | ⭐⭐⭐⭐ | 依赖 Phase 0 门控 + 备选方案，整体可行；跨进程解析与"统一 SocketIO"表述冲突 |
| 5 | 🔗 Structure & Dependencies | ⭐⭐⭐⭐ | 阶段/任务依赖清晰、ACK 前移合理；Phase 1 全量 pytest AC 与 Task 3.3 测试更新时序冲突 |
| 6 | ⚠️ Risk Identification | ⭐⭐⭐⭐ | 13 条风险覆盖充分；缺跨进程 name 解析风险 |
| 7 | ⚖️ Proportionality | ⭐⭐⭐⭐⭐ | 复杂系统，粒度恰当，无过度/不足 |
| 8 | ✅ Internal Consistency | ⭐⭐⭐ | 4 处 Major 一致性问题（Phase1 AC / budget / 跨进程 / config） |
| | **Overall** | **⭐⭐⭐⭐** | **高质量修订稿；无 Critical，但 4 处 Major 一致性缺陷需修复** |

---

## Detailed Findings

### 1. 📋 Completeness — ⭐⭐⭐⭐

**Summary**: 概述/相关材料/总体方案/执行计划/风险/未解决问题全部齐备；Phase 0 补了阶段验收标准；每个 Task 均有目标、步骤、预期产出、2~5 条 AC。主要缺口在 `config` 语义闭环与 AuditLogger 依赖。

| # | Severity | Location | Issue | Suggestion |
|:-:|:--------:|----------|-------|------------|
| 1 | Major | Task 1.2 / Task 2.1 / Task 2.2 | AuditLogger 需要 `workspace`，但 `CommunicationPolicy`（Task 1.2 定义）**无 `workspace` 字段**；`initialize` 伪代码 `self._audit = AuditLogger(config.workspace ...)` 的 `config` 究竟指向 AgentConfig 还是 CommunicationPolicy 未明确（见 Clarity #1）。 | 明确 `initialize(config: AgentConfig)`，内部 `self._config = config.communication_policy`、`self._audit = AuditLogger(config.workspace)`；或给 CommunicationPolicy 补 `workspace` 字段。 |
| 2 | Minor | Task 2.1 步骤1 | `AgentCommunicationError` 在 Task 2.1 Step 2 定义，但 `_resolve_agent_id` 在找不到目标时抛出的错误 message 未携带 `reason`（"not found" 不在 AC 列举的 reason 集合中）。 | 在 reason 集合补充 `target_not_found`（或 `agent_not_found`），并在 `_resolve_agent_id` 中带上该 reason。 |

### 2. 🔍 Clarity — ⭐⭐⭐

**Summary**: 整体叙述清晰、伪代码详尽、ask_user 类比到位。但 `config` 参数二义、`force_chain_check` 死参数、审计 result 归类三处影响执行者理解。

| # | Severity | Location | Issue | Suggestion |
|:-:|:--------:|----------|-------|------------|
| 1 | Major | Task 2.2 Step 2 ↔ Task 2.1 `initialize` | Task 2.2 传 `config=config`（AgentConfig 实例），但 messenger 字段类型声明为 `self._config: CommunicationPolicy`。`config` 一词同时指代 AgentConfig 与 CommunicationPolicy，且未说明 `self._config = config.communication_policy` 的转换。执行者可能误把 AgentConfig 当作 policy 用，导致 `self._config.request_timeout` 等访问失败。 | 在 `initialize` 内显式写出 `self._config = config.communication_policy`；签名改为 `config: "AgentConfig"`（去掉 `Any`）。 |
| 2 | Minor | Task 2.1 `_check_permissions` | 参数 `force_chain_check` 在**所有调用点**（`request` 直接调用默认 False、`_check_with_mode` 显式传 False）恒为 False；条件 `if ... and force_chain_check is False and mode != "request"` 中的 `force_chain_check is False` 恒真，参数实为死代码。 | 删除 `force_chain_check` 参数，notify/delegate 的可选环检测直接用 `enable_chain_detection and mode != "request"` 判断。 |
| 3 | Minor | Task 2.1 `request()` finally | 审计用 `result="replied" if event.is_set() else "timeout"` 判定；但 `_send_and_check_ack` 抛 `routing_failed` 时 event 未 set，finally 会把该请求误记为 `timeout` 而非 `routing_failed`。 | 用局部变量记录最终结果（routed/replied/timeout/routing_failed），在 finally 中据此写审计。 |

### 3. 🎯 AC Quality — ⭐⭐⭐⭐

**Summary**: AC 质量很高——大量可观测、可断言的具体条目（如 `send()` 返回 `{"status":"routed"}`、`request_timeout=0.05` 断言、`chain_cycle`/`budget_exhausted` 等 reason 值）。主要问题是 request 预算 AC 与伪代码不匹配，导致不可达成。

| # | Severity | Location | AC | Issue | Suggestion |
|:-:|:--------:|:--------:|----|-------|------------|
| 1 | Major | Task 3.2 | "预算 enable_budget=True：连续 4 次 request（默认 3）第 4 次被拒（budget_exhausted）" | Task 2.1 伪代码中 `request()` **从不调用** `self._budget.consume("request")`（只有 `notify`/`delegate` 调 consume）。因此 `_counters["request"]` 永远为 0，`can_communicate("request")` 永远 True，第 4 次不会被拒——该 AC 必然失败。 | 在 `request()` 成功投递后（或 `_check_permissions` 通过后）补 `self._budget.consume("request")`；或明确 request 不纳入预算并删除该 AC。二选一，保持伪代码与 AC 一致。 |
| 2 | Minor | Task 2.3 / Communicate | "communicate(mode=request) 把回复文本作为 ToolResult.content 返回" | `reply()` 可带 `status="error"/"aborted"`，但 `Communicate` 无论 reply status 一律返回 `ToolStatus.SUCCESS`（content 前缀 `[Reply from ...]`）。语义上 error/aborted 的回复被当作成功结果，LLM 可能误判。 | 明确：request 返回时若 reply.status != success，`Communicate` 应返回 `ToolStatus.ERROR`（或至少在 content 标注 status）。 |

**Good ACs identified:**
- Task 2.4: "路由成功时 `send()` 返回 `{"status": "routed"}`；路由失败返回 `{"status": "routing_failed", ...}`" — ✅ 精确、可断言、指明了数据来源（emit callback）。
- Task 3.2: "滞留回复被忽略（late reply）：request 超时后，再投递同 request_id 的 `AGENT_REQUEST_RESPONSE` → `handle_request_response` 查不到 pending 直接忽略，pending 表无残留" — ✅ 覆盖了易漏的竞态边界，可测。
- Task 3.2: "嵌套 run 不自死锁：… 断言拒绝 reason=`chain_cycle`" — ✅ 把抽象的 `_run_lock` 死锁风险转化为可断言的具体行为。
- Task 1.1: "`AgentCommunication(mode="delegate", task_id="...")` … `to_dict()` / `from_message_data()` 往返保留 `kind` / `task_id` / `request_id` / `status`" — ✅ 明确断言字段保真。

### 4. 🏗️ Feasibility — ⭐⭐⭐⭐

**Summary**: 技术路线可行——request 复刻 ask_user 同步链路、ACK 走 emit callback（Phase 0 门控 + 备选方案）、环检测防 `_run_lock` 自死锁 + 超时兜底，均有现实依据。主要可行性缺口是"统一 SocketIO / 跨进程"表述与实际本地解析能力不符。

| # | Severity | Location | Issue | Suggestion |
|:-:|:--------:|----------|-------|------------|
| 1 | Major | 概述"统一通信方式" / Task 2.1 `_resolve_agent_id` | 计划声明"所有 agent-to-agent 通信统一走 SocketIO，不区分同进程/跨进程"，但 `_resolve_agent_id` 依赖 `DefaultAgentFactory.get_agent(session_id, target_name)`——已核实其实现（`agent_manager.py:543`）**只查本地 `self._session_agents[session_id]`**。跨进程的目标 agent 不在本地 factory 中 → name→id 解析失败 → request/notify/delegate 全部在投递前抛错。delegate 的 `TaskManager()` 亦为本地实例。 | 二选一：(a) 修正表述为"仅支持同进程（同 session）内 agent 通信"，跨进程列为后续工作/风险；(b) 若必须跨进程，则设计 name→id 的远端解析（如经 SocketIO 查询 server 的 agent 注册表），并在 Phase 0 一并验证。 |

### 5. 🔗 Structure & Dependencies — ⭐⭐⭐⭐

**Summary**: Phase 0→1→2→3 递进合理；Task 依赖显式、ACK 前移到 Task 1.4 消除了 2.1↔2.4 的依赖倒置。主要问题是 Phase 1 阶段 AC 与测试更新时序矛盾。

| # | Severity | Location | Issue | Suggestion |
|:-:|:--------:|----------|-------|------------|
| 1 | Major | Phase 1 阶段 AC ↔ Task 1.1 / Task 3.3 | Phase 1 阶段 AC 要求 "`pytest broca/tests/` 全量通过（删除后无引用断裂）"，但 Task 1.1 删除了 `MessageType.TASK_START/COMPLETE/ERROR` 等枚举，而引用这些枚举的测试文件（`test_llm.py` / `test_save_user_message_no_mutation.py` / `test_non_blocking_mode.py` / `test_handle_task_assigner_defense.py` / `test_communicator_abc.py`）按 Task 1.1 AC 明确"同步更新在 Task 3.3 验收"。枚举删除后这些测试在 import/收集阶段即 `AttributeError`，Phase 1 全量 pytest 必然失败。 | 将上述测试文件的更新前移到 Phase 1（与 Task 1.1 删除同步），或把 Phase 1 阶段 AC 放宽为"生产代码无引用断裂 + 受影响测试标记 xfail/更新后通过"，把全量回归留给 Task 3.3。二者需择一并前后一致。 |

### 6. ⚠️ Risk Identification — ⭐⭐⭐⭐

**Summary**: 风险表 13 条，覆盖死锁、滞留回复、mid-turn 注入边界、routing_failed、删除断裂、ACK 影响面、编排误用等，质量高且与 Task 对应。

| # | Severity | Location | Issue | Suggestion |
|:-:|:--------:|----------|-------|------------|
| 1 | Minor | 风险与应对 | 缺"跨进程 name 解析失败"风险（与 Feasibility #1 同源）。既然计划声称统一 SocketIO，应显式记录该风险与缓解。 | 新增一行风险：跨进程 target 解析不可用 → 缓解：限定同进程或设计远端注册表查询。 |

### 7. ⚖️ Proportionality — ⭐⭐⭐⭐⭐

**Summary**: 这是一个涉及 ABC/组件注册/消息路由/同步唤醒/控制原语/删除迁移/多测试文件的复杂系统改造，多阶段 + 每任务详尽 AC + 风险表完全恰当，无过度工程，也无欠开发。

| # | Severity | Location | Issue | Suggestion |
|:-:|:--------:|----------|-------|------------|
| — | — | — | 无 | — |

### 8. ✅ Internal Consistency — ⭐⭐⭐

**Summary**: 纵向/横向一致性总体良好，但存在 4 处 Major 级不一致，均是"伪代码/表述 与 AC/实现 对不上"的具体矛盾。

| # | Severity | Location | Issue | Suggestion |
|:-:|:--------:|----------|-------|------------|
| 1 | Major | Task 3.2 AC ↔ Task 2.1 `request()` | request 预算 AC 与伪代码不符（request 从不 consume）——见 AC Quality #1。 | 补 `consume("request")` 或删除该 AC。 |
| 2 | Major | Phase 1 阶段 AC ↔ Task 1.1/Task 3.3 | Phase 1 "全量 pytest 通过" 与测试更新延后至 Task 3.3 矛盾——见 Structure #1。 | 前移测试更新或放宽 Phase 1 AC。 |
| 3 | Major | 概述"统一 SocketIO 跨进程" ↔ Task 2.1 `_resolve_agent_id` | 跨进程表述与本地 `get_agent` 解析能力矛盾——见 Feasibility #1。 | 修正表述或补远端解析。 |
| 4 | Major | Task 2.2 `config=config` ↔ Task 2.1 `self._config: CommunicationPolicy` | `config` 同时指 AgentConfig 与 CommunicationPolicy，且缺 `config.communication_policy` 转换——见 Clarity #1。 | 显式 `self._config = config.communication_policy`。 |

> **一致性亮点**：`send() -> dict` 契约在 ABC（Task 1.4）、`SocketIOClient.send`、`_send_and_check_ack`（Task 2.1）、Task 2.4 验证、AC 中五处完全统一；`get_agent` 三处口径（ABC 声明 / `agent_manager.py:543` 实现 / `_resolve_agent_id` 调用）已核实一致；engine.py 3 处 + agent.py 2 处共 5 处跨 agent 识别逻辑在 Task 1.1（删旧）/Task 2.2（加新）中成对列出，未再遗漏。

---

## Issue Summary

| Severity | Count | Description |
|:--------:|:-----:|-------------|
| 🔴 Critical | 0 | 无阻断性缺陷 |
| 🟡 Major | 4 | 执行前应修复（会导致 AC 失败或时序矛盾） |
| 🟢 Minor | 5 | 建议改进 |

### 🔴 Critical Issues (Must Fix)

_无。_

### 🟡 Major Issues (Should Fix)

| # | Dimension | Location | Issue | Suggestion |
|:-:|:---------:|:--------:|-------|------------|
| 1 | AC/Consistency | Task 2.1 `request()` ↔ Task 3.2 AC | request 预算从不 consume，`budget_exhausted` 的 request AC 不可达成 | `request()` 投递后补 `self._budget.consume("request")` |
| 2 | Structure/Consistency | Phase 1 阶段 AC ↔ Task 1.1/3.3 | Phase 1 要求全量 pytest 通过，但引用已删枚举的测试延后到 Task 3.3 才更新 | 前移测试更新，或放宽 Phase 1 AC |
| 3 | Feasibility/Consistency | 概述 ↔ Task 2.1 `_resolve_agent_id` | "跨进程统一 SocketIO" 与本地 `get_agent` 仅查本地 session 矛盾 | 修正表述为同进程，或设计远端 name→id 解析 |
| 4 | Clarity/Consistency | Task 2.2 `config=config` ↔ Task 2.1 `self._config` | `config` 二义（AgentConfig vs CommunicationPolicy），缺转换 | 显式 `self._config = config.communication_policy`，签名标注 `AgentConfig` |

### 🟢 Minor Issues (Consider)

| # | Dimension | Location | Issue | Suggestion |
|:-:|:---------:|:--------:|-------|------------|
| 1 | Clarity | Task 2.1 `_check_permissions` | `force_chain_check` 恒为 False，死参数 | 删除该参数 |
| 2 | Clarity | Task 2.1 `request()` finally | routing_failed 被误记为 timeout | 用局部变量记录最终 result |
| 3 | Completeness | Task 2.1 `_resolve_agent_id` | "not found" 未纳入 reason 集合 | 补 `target_not_found` reason |
| 4 | AC Quality | Task 2.3 Communicate | error/aborted 回复仍返回 SUCCESS | 按 reply.status 映射 ToolResult 状态 |
| 5 | Risk | 风险表 | 缺跨进程解析风险 | 新增对应风险行 |

---

## Verdict

**Overall Score**: ⭐⭐⭐⭐ (3.75/5)

**Verdict**: ⚠️ **Conditional Pass**

| Verdict | Condition | 本例 |
|---------|-----------|------|
| ✅ Pass | 无 Critical 且所有维度 ≥3 | 满足（无 Critical，最低维度 3） |
| ⚠️ Conditional Pass | 存在少量 Critical 或部分维度 <3 / 存在需修复的 Major | **采用**：存在 4 处 Major 一致性问题，虽无 Critical 但会导致 AC 失败/时序矛盾，建议修复后再执行 |
| ❌ Needs Revision | 存在 Critical 或整体 <3 | 不适用 |

**Recommendation**:

1. **优先修复 4 处 Major（建议全部在 `create-tasks` 前完成）**：
   - 补 `request()` 的 `self._budget.consume("request")`（或删除该 request 预算 AC）——成本最低、影响 Task 3.2 可达性。
   - 统一 Phase 1 全量 pytest AC 与测试更新时序（前移 5 个测试文件的更新，或放宽 Phase 1 AC）。
   - 澄清跨进程能力：将"统一 SocketIO 不分同进程/跨进程"改为"同进程（同 session）内"，或将远端 name→id 解析列为 Phase 0 验证项。
   - 显式 `self._config = config.communication_policy` 并将 `initialize` 的 `config` 标注为 `AgentConfig`。
2. **次要修复 5 处 Minor**（可与 Major 一并处理，非阻塞）。
3. 修复后**无需完整重审**，针对上述 4 处 Major 做一次轻量复核即可进入 `create-tasks` → `execute-tasks`。

**Summary**:
本轮修订稿质量很高——Round 1 的 Critical/Major 根因已切实消解，AC 具体可测、风险覆盖充分、结构清晰、比例恰当，已非常接近可执行状态。剩余问题集中在 4 处"伪代码/表述 与 AC/实现 对不上"的一致性细节（budget consume 缺失、Phase 1 测试时序、跨进程表述、config 二义），均为**局部可修**、不涉及方案重设计。建议按上述优先级修复后即可放行。
