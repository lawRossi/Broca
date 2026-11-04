# Task 4.3 执行报告：DB 批量写入 + 心跳同步节流（P1-5）

- **计划文档**：`plans/session-runner-refactor-plan.md`
- **阶段**：Phase 4 / Task 4.3（P1-5）
- **状态**：✅ 全部验收标准达成（实现部分在上一轮已落地，本轮补齐测试、修复回归、收尾）
- **完成时间**：2026-11-04

---

## 1. 问题回顾

心跳每 5s 一次，旧实现有两处写放大：

| 来源 | 旧行为 | 10 session 的代价 |
|---|---|---|
| Runner 状态落库 | 逐 runner `SELECT + UPDATE` | 20 次往返 / 轮 |
| Agent 状态同步 | **每个 session 各自** `SELECT + commit` | 每秒 2 次 commit（与 session 数线性相关） |

同时 `start_session` 之后状态只写一次，DB 里的 `status` / `last_heartbeat` 永远停在启动瞬间，`restore_active_sessions` 读到脏数据。

---

## 2. 方案与分工（严格遵守计划里的 P1-5 分工）

| 层次 | 归属 | 实现 |
|---|---|---|
| 单事务批量 | Task 2.2（已完成） | `RunnerRepository.upsert_many`：N 行 → 1 次 commit |
| 跨 session 批量 | **本 Task** | `RunnerRepository.set_agent_statuses({sid: {aid: status}})`：一次 `WHERE session_id IN (...)` + 1 次 commit |
| 时间维度聚合 | **本 Task** | `HeartbeatMonitor._persist_states` 按 `persist_interval` 过滤；manager 侧 `_pending_agent_status` 缓冲 + 单个在途 flush task |
| 配置 | **本 Task** | `execution.runner_status_persist_interval`（默认 60） |

### 2.1 manager 侧聚合链路

```
心跳到达 → _schedule_agent_status_sync(handle, statuses)
             ├─ 与 agent_status_cache 相同 → 直接返回（零成本）
             ├─ 乐观更新缓存 + 写入 _pending_agent_status[session_id]
             └─ _ensure_agent_flush_scheduled()（幂等：在途 task 未完成时不重复 spawn）
                                   ↓ 200ms 聚合窗口（AGENT_STATUS_FLUSH_DELAY）
                        _flush_agent_statuses()
                          └─ 一次 set_agent_statuses(所有待同步 session) → 1 次 commit
                          └─ 失败则回滚缓存，下一个心跳重新入缓冲
```

### 2.2 monitor 侧聚合

`_persist_states` 先按 `db_state_cache` 比对（状态相同且 `last_heartbeat` 在
`persist_interval` 内 → 跳过），再把剩余行合并成**一次** `upsert_many`。

---

## 3. 本轮实际改动

上一轮已经落地了 `set_agent_statuses` / `_persist_states` / `_flush_agent_statuses`，
但**留下了一个红着的测试**且没有 Task 4.3 的测试文件。本轮：

| 改动 | 说明 |
|---|---|
| 修复 `test_runner_taskset.py::test_agent_status_sync_is_coalesced` | 该用例仍在断言已被替换的旧 API（`handle.agent_status_sync_task` + `repo.set_agent_status`），Task 4.3 实现后一直失败。改为断言 manager 级单缓冲 + `repo.set_agent_statuses`，并额外校验「最后一次 flush 带的是最新状态」 |
| 清理 `process/registry.py` 的过期注释 | `pending_responses` 上残留「心跳同步任务去重（Task 2.5）」的注释，该字段已迁到 manager 的 `_agent_flush_task` |
| 新增 `broca/tests/test_runner_db_batching.py` | 12 例，见下 |

---

## 4. 测试（12 例，计划要求 3 例）

全部用**真实内存 SQLite**，commit 次数由 SQLAlchemy `commit` 事件精确计数
（用 mock 数 `commit()` 调用发现不了「一次 commit 前塞了 N 次 SELECT」这类写放大）。

| # | 用例 | 守住什么 |
|---|---|---|
| 1 | `test_n_sessions_produce_single_commit` | **10 session × 2 agent → 恰好 1 次 commit**（AC 原文） |
| 2 | `test_unchanged_statuses_produce_no_commit` | 状态没变 → 0 次 commit（否则节流形同虚设） |
| 3 | `test_status_change_within_interval_is_coalesced` | 60s 内重复上报 → 只 1 次 `upsert_many` |
| 4 | `test_real_status_change_bypasses_interval` | 状态真变了 → 立刻落库（不能被 interval 吞掉） |
| 5 | `test_interval_expiry_triggers_rewrite` | 超期后即使状态没变也要刷新 `last_heartbeat` |
| 6 | `test_manager_flushes_ten_sessions_in_one_call` | 10 个 session 的心跳 → 1 次 `set_agent_statuses`，payload 含 10 个 session |
| 7 | `test_persist_interval_from_config` | `HealthPolicy.persist_interval` 来自 configs.json |
| 8 | `test_execution_config_matches_configs_json` | **`ExecutionConfig` ↔ `configs.json` 字段一一对应**（AC 原文） |
| 9 | `test_runner_config_fields_are_all_in_json` | 所有 `runner_*` 字段必须显式写入 configs.json |
| 10 | `test_configs_json_has_no_stale_runner_fields` | configs.json 不得残留已删除的 `runner_*` 字段（本轮删 `runner_ipc_multiplexing` 后仍然通过） |
| 11 | `test_upsert_many_still_single_transaction` | 回归守卫：不得把 Task 2.2 的单事务批量改回逐条写 |
| 12 | `test_persist_states_uses_upsert_many_not_upsert` | 回归守卫：`_persist_states` 不得退回逐 runner `upsert` |

---

## 5. 验收标准逐条核对

| # | 验收标准 | 结果 | 证据 |
|---|---|---|---|
| 1 | 10 个 session 心跳同步一轮，commit 次数 == 1 | ✅ | `test_n_sessions_produce_single_commit`：`db.commits == 1`，`changed == 20` |
| 2 | 3 个新测试通过 | ✅ | 实收 **12** 例，全绿 |
| 3 | `configs.json` 与 `ExecutionConfig` 字段一一对应（有测试守卫） | ✅ | `test_execution_config_matches_configs_json` |
| 4 | Phase 1~3 与 Task 4.1/4.2 测试全绿 | ✅ | `broca/tests/` **1138 passed / 5 skipped**；`broca-web/tests` **323 passed** |

---

## 6. 与计划的偏离

### 偏离 1：配置一一对应的白名单

`ExecutionConfig` 有 3 个字段从未写入 `configs.json`：`max_concurrent_runners`、
`max_parallel_tools`、`tool_execution_mode`。它们都由 `getattr(..., default)`
兜底，且不属于 session_runner 改造范围。

因此守卫写成「**除白名单外必须一一对应**」，而不是无条件的全等 —— 否则本 Task
会被迫修改无关配置（把三个字段写进 `configs.json`），属于计划外改动。白名单在
测试里有注释说明，并额外用 `test_runner_config_fields_are_all_in_json` 保证
**本计划新增的 `runner_*` 字段一律不得进白名单**。

### 偏离 2：测试数 3 → 12

计划列的 3 个用例只覆盖「聚合生效」，没有覆盖「聚合不能过头」（状态真变必须立刻写）
与「不得退回逐条写」这两个反向风险。多出的 9 例都是这些反向守卫，未增加功能。

---

## 7. 结论

P1-5 的写放大已在**两个维度**上消除：

- 空间维度（session 数）：10 个 session 的 Agent 状态同步 → 1 次 commit；
- 时间维度（心跳轮次）：`persist_interval` 内的重复状态 → 0 次写。

并且用「真实 SQLite + commit 事件计数」把这两个维度都固化成了测试，
而不是靠 mock 调用次数自证。
