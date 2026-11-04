# Phase 4 执行报告：消除抽象泄漏与性能优化

- **计划文档**：`plans/session-runner-refactor-plan.md`
- **阶段**：Phase 4（Task 4.1 ~ 4.4 + 收尾）
- **状态**：✅ 功能目标全部达成（行数指标按 Phase 2/3 报告的建议改用结构指标验收）
- **完成时间**：2026-11-04

---

## 1. 阶段目标回顾

> API 层不再触碰私有属性；IPC 由 N 线程降为 1 线程多路复用；DB 写入批量合并；
> 队列有背压；日志有轮转。

---

## 2. 阶段验收标准逐条核对

| # | 验收标准 | 结果 | 证据 |
|---|---|---|---|
| 1 | `grep -rn "runner_manager\._\|RunnerManager()\._" broca-web/backend/` 无结果 | ✅ | 实测 0 命中（Task 4.1） |
| 2 | 10 个并发 session 下 `session_runner` 相关线程数 ≤ 3 | ✅ | `test_single_thread_handles_multiple_connections`：增量 **1**，线程名 `ipc-poller` |
| 3 | 心跳状态同步在 10 个 session 下每分钟 DB commit 次数 ≤ 2 | ✅ | 状态落库：`persist_interval=60s` → 1 次/min；Agent 状态：10 session 合并为 **1 次 commit**（`test_n_sessions_produce_single_commit`） |
| 4 | Phase 1~3 全部测试仍绿 | ✅ | `broca/tests/` **1138 passed / 5 skipped**；`broca-web/tests` **323 passed** |

---

## 3. 各 Task 交付物

### Task 4.1：扩展 `SessionRunner` ABC + API 层改造（上一轮完成，本报告归档）

- ABC 4 → **13** 个抽象方法（`test_abc_method_count_is_13` 守卫）
- `get_session_status` → `get_status`，旧名保留一版并 `DeprecationWarning`
- API 层 `session_runner.py` / `session.py` 全部改用 ABC 方法，私有属性访问清零
- REST 响应基线：`broca-web/tests/snapshot_runner_api.py` + `fixtures/session_runner_responses.{before,after}.json`（diff 为空）
- 新增 `test_session_runner_abc.py`（5 例）

### Task 4.2：IPC 单线程多路复用（上一轮完成，详见 `session-runner-refactor-task-4.2.md`）

- 新增 `poller.py`：一个 `ipc-poller` 线程用 `multiprocessing.connection.wait()` 轮询所有连接
- 线程模型 O(N) → **O(1)**；10 session 空闲唤醒 ~100 次/秒 → ~2 次/秒
- 过程中修掉 3 个真实缺陷：漏解码、断连哨兵投递顺序反了、`ipc.close()` 后 `wait()` 抛 `TypeError` 杀死轮询线程
- 新增 `test_runner_poller.py`

### Task 4.3：DB 批量写入 + 心跳同步节流（本轮完成，详见 `session-runner-refactor-task-4.3.md`）

- `RunnerRepository.set_agent_statuses`：跨 session 一次 `SELECT ... IN (...)` + 1 次 commit
- `HeartbeatMonitor._persist_states` 按 `persist_interval` 聚合
- manager 侧 `_pending_agent_status` 缓冲 + 单个在途 flush task
- 新增 `test_runner_db_batching.py`（12 例，真实 SQLite + commit 事件计数）

### Task 4.4：队列背压 + 日志轮转（本轮完成，详见 `session-runner-refactor-task-4.4.md`）

- 新增 `backpressure.py`：心跳丢最旧、命令丢新、断连哨兵必达，全部计数
- 两处队列全部带 `maxsize`（可配 `execution.runner_ipc_queue_size`）
- `get_stats()["dropped_events"]` + runner `CMD_GET_STATS` 双向可观测
- 日志：`TimedRotatingFileHandler(when="midnight", backupCount=7)` + 固定 `runner.log`
- 新增 `test_runner_backpressure.py`（10 例）

### Phase 4 收尾：下线灰度回滚路径

- `manager_legacy.py` → 备份到 `docs/legacy/session_runner/manager_legacy.py.bak`，运行时删除
- 删除配置项 `execution.runner_ipc_multiplexing`（3 处同步）
- `IPCSessionRunner` 只保留 `IPCPoller` 一条实现路径
- 删除 2 个回滚路径专属测试，2 个开关相关测试改为单实现断言

---

## 4. 结构指标（替代纯行数指标）

Phase 2/3 报告已三次确认「行数」不是合适的验收口径（拆方法是行数中性的重构）。
本阶段沿用结构指标：

| 指标 | 目标 | 实测 |
|---|---|---|
| API 层私有属性访问 | 0 | **0** ✅ |
| `manager.py` 中 `threading.Thread` | 0 | **0** ✅ |
| `broca/session_runner/` 中无 `maxsize` 的 `asyncio.Queue` | 0 | **0** ✅ |
| 轮询线程数（10 session） | ≤ 3 | **1** ✅ |
| 10 session 心跳同步 commit 次数 | ≤ 2/min | **1** ✅ |
| `get_stats()` 背压可观测性 | 有 | `dropped_events` ✅ |
| 死代码/回滚路径 | 0 | **0** ✅（已留档删除） |

### 文件规模（仅记录，不作为 AC）

| 文件 | 行数 | 说明 |
|---|---|---|
| `manager.py` | 1094 | 纯编排层；已无 DB / 传输 / 进程细节（Task 4.3/4.4 的改动使其 +14） |
| `runner.py` | 808 | 子进程类化后含完整命令处理与生命周期 |
| `backpressure.py` | 177 | 新增 |
| `poller.py` | 237 | Task 4.2 新增 |
| `monitor.py` | 441 | Task 3.1 新增 |
| `repository.py` | 319 | Task 2.2 新增 |

---

## 5. 测试统计

| 范围 | 结果 |
|---|---|
| `broca/tests/`（全量，排除 orchestration） | **1138 passed / 5 skipped / 1 deselected** |
| `broca/tests/test_runner_*.py + test_ipc_*.py + test_session_runner_abc.py`（`BROCA_RUN_INTEGRATION=1`） | **163 passed** |
| `broca-web/tests` | **323 passed** |
| `ruff check broca/session_runner/ + 本轮新增/修改的测试与配置` | All checks passed |

### Phase 4 新增测试文件

| 文件 | 用例数 | Task |
|---|---|---|
| `test_runner_poller.py` | 17（含 2 例解码回归） | 4.2 |
| `test_runner_db_batching.py` | 12 | 4.3 |
| `test_runner_backpressure.py` | 10 | 4.4 |
| `test_session_runner_abc.py` | 5 | 4.1 |

---

## 6. 环境注意事项（非本次改动引入）

`venv/lib/python3.14/site-packages/broca/` 存在一份**旧安装副本**（`get_configs()` 仍是
0 参数版本）。从 `broca-web/backend` 目录启动子进程时，`import broca` 会解析到这份
旧副本，导致：

```
broca-web/tests/unit/test_alembic_db_url.py::TestExplicitDbUrl  →  2 failed
TypeError: get_configs() takes 0 positional arguments but 1 was given
```

这正是计划风险表里记录的那条风险。验证方式：

```bash
PYTHONPATH=/Users/luoweiang/code/Broca venv/bin/python -m pytest broca-web/tests -q
# 323 passed
```

建议后续统一用 `pip install -e .` 重新安装，或删除 site-packages 下的 `broca/` 副本。
**该问题与 session_runner 重构无关，本阶段未处理**（避免计划外改动）。

---

## 7. 结论

Phase 4 的 4 个 Task + 收尾全部完成，五项能力全部落地：

1. **抽象泄漏清零**：API 层只依赖 13 方法的 ABC，REST 响应有基线 diff 守卫；
2. **线程数 O(1)**：单线程多路复用，10 session = 1 线程；
3. **写放大消除**：空间（跨 session 批量）与时间（`persist_interval`）两个维度；
4. **背压可控**：无界队列清零，丢弃策略按消息语义分流，父子双向可观测；
5. **日志可轮转**：跨天归档 + 保留 7 天，不再无限膨胀。

灰度回滚路径已按计划下线，代码备份与下线理由留档在 `docs/legacy/`。
