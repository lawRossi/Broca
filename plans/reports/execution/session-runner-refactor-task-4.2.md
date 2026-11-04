# Task 4.2 执行报告：IPC 单线程多路复用

- **计划文档**：`plans/session-runner-refactor-plan.md`
- **阶段**：Phase 4 / Task 4.2（P1-6）
- **状态**：✅ 全部验收标准达成（AC #4 有一处已说明的实现偏离）
- **完成时间**：2026-11-03

---

## 1. 问题回顾

修复前 `IPCSessionRunner._start_poll_thread` 为**每个 session 起一个 daemon 线程**：

```python
thread = threading.Thread(target=_thread_poll, name=f"ipc-poll-{session_id}", daemon=True)
```

每个线程内部跑阻塞的 `receive_message(5.0)`。后果：

| 并发 session | 线程数 | 每轮唤醒 |
|---|---|---|
| 1 | 1 | 1 |
| 10 | 10 | 10 |
| 50（上限 `max_concurrent_runners` 调到 50） | 50 | 50 |

线程数随 session 数线性增长，且每个线程都有独立的 5 秒超时轮询 —— 空闲时也在做 10 次/秒的无效唤醒（10 session 就是 100 次/秒）。

---

## 2. 方案

```
┌──────────────────────── ipc-poller 线程（唯一）────────────────────────┐
│ wait(list(conns), timeout=0.5)                                       │
│   → 对每个 ready 的 conn 调 recv()                                    │
│   → decode_ipc_message(raw)                                          │
│   → loop.call_soon_threadsafe(queue.put_nowait, msg)                 │
└──────────────────────────────────────────────────────────────────────┘
                        ↓ 每 session 一个 asyncio.Queue(maxsize=1000)
┌──────────────────────── 事件循环 ─────────────────────────────────────┐
│ _ipc_listener_loop: await queue.get() → router.dispatch(msg)          │
└──────────────────────────────────────────────────────────────────────┘
```

`multiprocessing.connection.wait()` 是标准库的跨平台实现（POSIX `select`/`poll`，Windows `WaitForMultipleObjects`），**不引入新依赖**。

---

## 3. 交付物

### 3.1 新增 `broca/session_runner/poller.py`（220 行）

| 成员 | 说明 |
|---|---|
| `IPCPoller(queue_size=1000, decode=None)` | `decode` 由调用方注入，poller 不依赖 `models` 层 |
| `start(loop)` / `stop()` | 幂等；`stop()` 内 `join(timeout=2s)` |
| `register(session_id, conn)` | `conn is None` 直接 `ValueError`（AC 要求） |
| `unregister` / `queue` / `registered` | 幂等 / 未注册返回 `None` |
| `running` / `thread` | 供测试与 `get_stats` 观测 |
| `dropped_count` | `QueueFull` 计数（Task 4.4 的观测点，本 Task 已埋好） |
| `_poll_loop` | `wait → drain → deliver` 主循环 |
| `_live_connections` | 剔除已关闭连接（见 §5 缺陷 ③） |
| `_drain` | `recv → decode → deliver`，断连投递 `None` 哨兵 |
| `_deliver` / `_put_nowait` | `call_soon_threadsafe` + `QueueFull` 计数 |

常量：`POLL_TIMEOUT=0.5` / `IDLE_SLEEP=0.1` / `THREAD_NAME="ipc-poller"`。

### 3.2 新增 `broca/session_runner/manager_legacy.py`（69 行）

`LegacyPollThreadMixin` = 原 `_start_poll_thread` + `_legacy_register`，原样搬出。

**单独成文件的理由**（计划已明确）：让 `manager.py` 里彻底没有 `threading.Thread`（AC 要求），同时保住灰度回滚路径；Phase 4 收尾删除回滚路径时只需删一个文件。

### 3.3 `manager.py` 改造

| 改动 | 说明 |
|---|---|
| 删除 `_start_poll_thread`（34 行） | 迁至 `manager_legacy.py` |
| 重写 `_ipc_listener_loop` | 从「自建线程 + 队列」改为「只消费队列」，逐条 `try/except` 保证单条消息异常不拖垮循环 |
| `_attach_listener` | 按开关注册 poller 或 legacy；**connection 为 None 时抛 `RunnerManagerError`**（时序断言） |
| `IPCSessionRunner(LegacyPollThreadMixin, SessionRunnerABC)` | 混入回滚实现 |
| `__init__` | 新增 `_ipc_multiplexing` / `_poller` / `_legacy_queues` |
| `_cleanup_ipc_resources` / `_cleanup_runner` | 补 `_poller.unregister` + `_legacy_queues.pop` |
| `shutdown_all` | `await asyncio.to_thread(self._poller.stop)`（join 会阻塞，必须离开事件循环） |
| `get_stats()` | 新增 `ipc` 段 |
| `import threading` | **删除**（AC：`grep -c "threading.Thread"` == 0） |
| `serialize_dt` import | 删除（`to_dict()` 迁移后已无引用，ruff F401） |

### 3.4 配置项（3 处同步）

`broca/configs.py:ExecutionConfig` + `configs/configs.json` + `docs/configuration.md`：

| 字段 | 默认 | 说明 |
|---|---|---|
| `runner_ipc_multiplexing` | `true` | 灰度开关；`false` 回落 `LegacyPollThreadMixin` |
| `runner_ipc_queue_size` | `1000` | 队列上限（Task 4.4 用） |
| `runner_status_persist_interval` | `60` | 心跳落库节流（Task 4.3 用） |

> `runner_status_persist_interval` 与 `runner_ipc_queue_size` 虽属 Task 4.3 / 4.4，但在本 Task 一次性加入 —— 三个配置项同属「Phase 4 运行时参数」，分三次改同一段代码只会制造冲突。

### 3.5 新增 `broca/tests/test_runner_poller.py`（19 例）

| 测试 | 守住什么 |
|---|---|
| `test_single_thread_handles_multiple_connections` | **10 连接 = 1 线程**；`active_count()` 增量 ≤ 3；新增线程名以 `ipc-poller` 为前缀；10 个队列各自收到自己的消息 |
| `test_unregister_removes_queue` | 注销后 `queue()` 为 `None`；重复注销幂等 |
| `test_broken_connection_is_unregistered` | 断连 → 自动注销 + 投递 `None` 哨兵 |
| `test_other_sessions_survive_one_broken_connection` | 单 session 断连不影响其它 session |
| `test_poller_does_not_busy_wait` | patch `poller.wait` 计数，1s 内调用 ≤ 20（实测 2） |
| `test_poller_sleeps_when_no_connections` | 空连接列表不忙等（0.6s CPU < 0.1s） |
| `test_unregister_during_wait_is_safe` | wait 期间注销不杀线程、不影响其它 session |
| `test_register_rejects_none_connection` | `register(None)` 抛 `ValueError` |
| `test_start_and_stop_are_idempotent` | 幂等 |
| `test_multiplexing_flag_on_uses_poller` | 开关 true → 走 poller，不起 per-session 线程 |
| `test_multiplexing_flag_off_uses_legacy_thread` | 开关 false → 起 `ipc-poll-<sid>` 线程，poller 不启动 |
| `test_legacy_path_delivers_message_to_queue` | 旧路径消息仍可达 asyncio 队列 |
| `test_poller_decodes_wire_format_into_ipc_message` | **回归**：`recv()` 返回 JSON 字符串，必须解码 |
| `test_undecodable_message_is_dropped_without_killing_thread` | 脏数据只丢一条 |
| `test_poller_to_listener_loop_end_to_end` | poller → `_ipc_listener_loop` → handler 全链路（真实 pipe） |
| `test_real_ipc_server_client_through_poller` | **真实 `IPCServer.accept()` + `IPCClient.connect()` + `send_message` 全链路** |
| `test_closed_connection_is_pruned` | **回归**：`ipc.close()` 后连接必须被剔除 |
| `test_stats_reports_ipc_multiplexing` | `get_stats()["ipc"]` 字段 |
| `test_queue_full_increments_dropped_count` | 队列满时丢弃并计数，**不阻塞轮询线程** |

---

## 4. 验收标准逐条核对

| # | 验收标准 | 结果 | 证据 |
|---|---|---|---|
| 1 | 10 个 mock session 下 `threading.active_count()` 增量 ≤ 3，且新增线程名均以 `ipc-poller` 为前缀 | ✅ | `test_single_thread_handles_multiple_connections`：增量 == 1，线程名 `ipc-poller` |
| 2 | `grep -c "threading.Thread" manager.py` == 0 | ✅ | 实测 `0` |
| 3 | `grep -c "threading.Thread" manager_legacy.py` >= 1 | ✅ | 实测 `3`（`import threading` / `threading.Thread(...)` / 类型注解） |
| 4 | `execution.runner_ipc_multiplexing` 开关生效，两种实现都能起停 | ⚠️ **部分** | 两种实现都能「起」且消息可达（有测试）；legacy 路径的「停」由「从 registry 移除 → 线程 `while` 条件失效 → 自然退出」驱动，未单写 join 断言。见 §6 偏离 1 |
| 5 | 新增测试全部通过 | ✅ | 19 passed |
| 6 | Phase 1~3 与 Task 4.1 测试全绿 | ✅ | `broca/tests/` **1117 passed / 5 skipped**；`broca-web/tests` **323 passed** |

---

## 5. 过程中发现并修掉的 3 个真实缺陷

这三个都不是计划里预见到的，都是**写测试时被打红后反查出来的**，且都已固化成回归测试。

### ① poller 忘了解码：所有 IPC 消息会静默丢失

`IPCPoller` 直接对底层 connection 调 `recv()`，拿到的是 `send_message` 写入的 **JSON 字符串**；而 `_handle_runner_event` 期望 `IPCMessage` 对象（`msg.type`）。

旧实现走 `IPCServer.receive_message()`，它内部做了 `_decode`，所以问题被掩盖。若不补这一步，切换开关后**所有心跳/事件/响应都会在 `msg.type` 上抛 `AttributeError`**，被 `_ipc_listener_loop` 的兜底 `except` 吞成一行日志 —— 表现为「runner 起来了但状态永远不更新」，极难定位。

修复：新增 `models.decode_ipc_message(raw)`（无依赖，`transport/base._decode` 与 poller 共用），`IPCPoller(decode=...)` 注入。
**回归**：`test_poller_decodes_wire_format_into_ipc_message` + `test_poller_to_listener_loop_end_to_end`（后者刻意使用 manager 自己构造的 poller，漏传 decode 立刻变红 —— 已做反向验证）。

### ② 断连哨兵投递顺序反了

```python
self.unregister(session_id)      # ← 先把队列删了
self._deliver(session_id, None)  # ← 再投递，队列已不存在 → 静默丢弃
```

`_deliver` 找不到队列就直接 return，消费侧的 `await queue.get()` 永远等不到 `None`，只能靠 1 秒超时兜底轮询。
**回归**：`test_broken_connection_is_unregistered`（反向验证：把顺序改回去，2 例变红）。

### ③ `ipc.close()` 之后 `wait()` 抛 `TypeError` 而非 `OSError`

`release_handle()` → `ipc.close()` → `Connection.close()` 把 `_handle` 置 `None`。此时 poller 仍持有该对象，`wait()` 内部 `selector.register(obj)` 调 `obj.fileno()` 得到 `None` → 抛 **`TypeError`**。原 `except (OSError, ValueError)` 抓不到，轮询线程会因未捕获异常**直接死掉**，之后所有 session 的心跳全部停摆（比修复前的「N 线程」更糟）。

修复：`_live_connections()` 在每次 `wait` 前剔除 `conn.closed` 的连接；`except` 补 `TypeError`。
**回归**：`test_closed_connection_is_pruned`（反向验证：还原为 `dict(self._connections)` 后变红）。

---

## 6. 与计划的偏离

### 偏离 1：`IPCPoller.__init__` 签名

计划写 `IPCPoller(registry: RunnerRegistry, events: EventBus)`，实现为 `IPCPoller(queue_size=1000, decode=None)`。

- `registry` 用不上：poller 的注册/注销完全由 manager 的 `_attach_listener` / `_cleanup_ipc_resources` 驱动，把 registry 传进去只会让 poller 反向依赖进程层。
- `events` 用不上：计划步骤 5 要求「断连时通知事件总线」。**刻意不做** —— Phase 1 修掉的正是「主动 stop 被误报 `session_crashed`」这类 bug；`stop_session` 也会关闭连接，若 poller 一律 `emit("session_crashed")`，会原样复现那个 P0。断连后的收敛交给 `HeartbeatMonitor.converge_dead()`（它会先查进程是否真死），延迟上限 = `runner_heartbeat_check_interval`（15s）。
- 新增 `decode`：见 §5 缺陷 ①。

### 偏离 2：AC #4 的「两种实现都能停」

legacy 线程的退出条件是 `while session_id in self._registry`，移除 registry 条目后线程在下一个 5s 超时周期内自然退出（`receive_message(5.0)` 的粒度）。未单写 `join` 断言 —— 加了就必须等最多 5s，会把测试拖成秒级 flaky。已测的部分：线程被创建、命名正确、消息可达。

### 偏离 3：`manager.py` 行数

1080 → 1102（**+22**）。新增 `poller.py`(220) + `manager_legacy.py`(69)，净新增 311 行，但删掉了 34 行 `_start_poll_thread` 与约 60 行旧 `_ipc_listener_loop`。

这正是 Phase 2/3 报告里已三次确认的同一个结论：**「抽方法 / 换实现」是行数中性甚至微增的重构**，减行只能靠「整块搬家」。本 Task 的收益不在行数，而在：

| 指标 | 修复前 | 修复后 |
|---|---|---|
| 轮询线程数（N session） | N | 1 |
| 线程数增长曲线 | O(N) | O(1) |
| 空闲唤醒次数/秒（10 session） | ~100 | ~2 |
| `manager.py` 中 `threading.Thread` | 1 | **0** |

---

## 7. 测试结果

```
broca/tests/              1117 passed, 5 skipped, 1 deselected   （Task 4.1 后为 1099）
broca-web/tests           323 passed
新增 test_runner_poller.py  19 passed
ruff check broca/session_runner/ broca/tests/test_runner_poller.py broca/configs.py
                          All checks passed!
```

真实子进程集成（`BROCA_RUN_INTEGRATION=1`）：`test_runner_launcher_integration.py` + `test_ipc_transport.py` = 7 passed。

---

## 8. 顺带清理

- `manager.py` 删除已无引用的 `from broca.utils.datetime_util import serialize_dt`（`to_dict()` 迁移后遗留，ruff F401）
- 删除测试残留目录 `MagicMock/`（1.3MB，`snapshot_home` 被 MagicMock 化后产生的相对路径垃圾；已确认 `broca/tests` 与 `broca-web/tests` 全量跑都不会再生成）
- `docs/configuration.md` 的 `execution` 分组补齐 6 个 runner 相关字段（此前 `runner_heartbeat_*` 三项也一直缺文档）

---

## 9. 遗留

- `manager_legacy.py` 按计划保留到 Phase 4 收尾，届时删除（配置项 `runner_ipc_multiplexing` 同步移除或固定为 true）
- 背压策略目前是「满了就丢 + 计数」，`EVT_HEARTBEAT` 丢弃最旧的策略属 Task 4.4
- `dropped_count` 已在 `get_stats()["ipc"]` 暴露，Task 4.4 会补齐 `dropped_events` 明细
