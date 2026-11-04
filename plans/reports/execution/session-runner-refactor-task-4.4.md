# Task 4.4 执行报告：队列背压 + 日志轮转清理（P1-7）

- **计划文档**：`plans/session-runner-refactor-plan.md`
- **阶段**：Phase 4 / Task 4.4（P1-7）
- **状态**：✅ 全部验收标准达成
- **完成时间**：2026-11-04

---

## 1. 问题回顾

### 1.1 无界队列

两处 `asyncio.Queue` 都没有 `maxsize`：

| 位置 | 队列语义 | 无界后果 |
|---|---|---|
| manager 侧（现由 `poller.py` 创建） | runner → web 的心跳/事件/响应 | 事件循环被长工具调用卡住时，`ipc-poller` 线程持续投递 → 内存无界上涨 → OOM |
| runner 侧（`runner.py::_ipc_listener_loop`） | web → runner 的控制命令 | 同上，子进程 OOM 后表现为「runner 莫名消失」 |

注意：**「卡住轮询线程」不是解法**。那会让该 session 的心跳一起停摆，被心跳巡检
误判为崩溃（正是 Phase 1 修掉的 P0-5 语义）。

### 1.2 日志不轮转

`setup_logging` 用 `logging.FileHandler` + 文件名带 `%Y%m%d`。看似「每天一个文件」，
但**子进程是长驻的**：跨天后 handler 仍指向旧文件，实际效果是「跨天不轮转」，
且没有任何清理机制，日志无限膨胀。

---

## 2. 方案

### 2.1 背压策略（新增 `broca/session_runner/backpressure.py`，177 行）

按消息类型分流：

| 消息类型 | 队列满时 | 理由 |
|---|---|---|
| `EVT_HEARTBEAT` | 丢弃**最旧的**心跳，保留最新 | 心跳是幂等快照，最新一条即覆盖全部语义 |
| 其它（命令/响应/事件） | 丢弃**新**消息 + WARNING + 计数 | 命令/响应有状态，丢旧的会让 `send_command` 永远等不到响应（表现为 10s 超时） |
| 断连哨兵 `None` | `force=True`，丢弃最旧的直到有空间 | 哨兵丢了监听循环就永远退不出去 |

关键实现细节：**不能 `get_nowait()` 一丢了之**。队列里混着 `RESPONSE` 时，
丢队首会让调用方超时。因此 `_drop_oldest_heartbeat` 的语义是「队首是心跳才丢，
不是心跳就放回去，宁可丢新来的心跳」。

计数结构：

```python
@dataclass
class DroppedEvents:
    heartbeat: int = 0   # 心跳被合并（可接受）
    other: int = 0       # 真丢了命令/响应（要查）
    @property
    def total(self) -> int: ...
    def to_dict(self) -> dict[str, int]: ...  # {"total": n, "heartbeat": n, "other": n}
```

### 2.2 两处队列同时改造

| 位置 | 改动 |
|---|---|
| `poller.py` | `asyncio.Queue(maxsize=self._queue_size)`；`_put_nowait` → `put_with_backpressure`；`dropped_count` 改为 `dropped.total` 的 property；新增 `dropped_events` |
| `runner.py` | `asyncio.Queue(maxsize=get_queue_size())`；新增 `_enqueue`（`call_soon_threadsafe` 目标），哨兵走 `force=True` |
| `manager_legacy.py` | 回滚路径同样带 `maxsize`（灰度回切不能把 OOM 风险带回来）—— 该文件已在本轮收尾下线，见 §5 |

### 2.3 可观测性

`get_stats()` 新增顶层 `dropped_events`，并保留在 `ipc` 段：

```json
{
  "dropped_events": {"total": 3, "heartbeat": 2, "other": 1},
  "ipc": {
    "poller_running": true,
    "poller_connections": 10,
    "queue_size": 1000,
    "dropped_count": 3,
    "dropped_events": {"total": 3, "heartbeat": 2, "other": 1}
  }
}
```

runner 侧 `CMD_GET_STATS` 的响应 payload 也带上 `dropped_events`，父子两侧可用同一
指标排障。

### 2.4 日志轮转

| 侧 | 改动 |
|---|---|
| runner（`setup_logging`） | 新增 `build_file_handler()`：`TimedRotatingFileHandler(when="midnight", backupCount=7, encoding="utf-8")` |
| manager（`_get_runner_log_file`） | 文件名从 `{YYYYMMDD}.log` 改为固定 `runner.log`，轮转交给 handler |

---

## 3. 测试（10 例，计划要求 4 例）

| # | 用例 | 守住什么 |
|---|---|---|
| 1 | `test_is_heartbeat_accepts_message_and_dict` | 心跳识别兼容 `IPCMessage` / dict / 裸字符串 |
| 2 | `test_queue_full_drops_oldest_heartbeat` | **AC 用例**：队列满 + 新心跳 → 丢最旧，保留最新 |
| 3 | `test_queue_full_drops_non_heartbeat_and_counts` | **AC 用例**：非心跳丢新的，保旧消息，计入 `other` |
| 4 | `test_queue_full_heartbeat_does_not_evict_command` | 反向守卫：队首是命令时**不得**为塞心跳而丢命令 |
| 5 | `test_force_sentinel_is_never_dropped` | 断连哨兵必须入队 |
| 6 | `test_dropped_count_in_stats` | **AC 用例**：`get_stats()["dropped_events"]` 存在且明细正确 |
| 7 | `test_runner_stats_expose_dropped_events` | 子进程 `CMD_GET_STATS` 也回传丢弃计数 |
| 8 | `test_no_unbounded_asyncio_queue_in_source` | **长期守卫**：源码中不得再出现无 `maxsize` 的 `asyncio.Queue` |
| 9 | `test_log_rotation_creates_backup` | **AC 用例**：`doRollover()` 生成 `runner.log.YYYY-MM-DD` 备份，主文件只剩轮转后的内容 |
| 10 | `test_runner_log_file_is_fixed_name` | 父进程给的路径必须是 `runner.log`（带日期会导致跨天不轮转） |

---

## 4. 验收标准逐条核对

| # | 验收标准 | 结果 | 证据 |
|---|---|---|---|
| 1 | `grep -n "asyncio.Queue()" broca/session_runner/` 无结果 | ✅ | 实测 0 命中（连注释里的字面量也已改写，避免误判） |
| 2 | `get_stats()` 返回含 `dropped_events` 字段 | ✅ | `test_dropped_count_in_stats` |
| 3 | 4 个新测试通过 | ✅ | 实收 **10** 例，全绿 |
| 4 | Phase 1~3 与 Task 4.1~4.3 测试全绿 | ✅ | `broca/tests/` **1138 passed / 5 skipped**；`broca-web/tests` **323 passed** |

---

## 5. Phase 4 收尾：下线灰度回滚路径

按计划「`manager_legacy.py` 保留到 Phase 4 收尾，届时删除」，本轮完成收尾。
**采用「备份留档 + 运行时删除」**，而不是原地保留：

| 动作 | 说明 |
|---|---|
| 备份 | `broca/session_runner/manager_legacy.py` → `docs/legacy/session_runner/manager_legacy.py.bak`，并在 `docs/legacy/README.md` 记录原路径、下线时间与原因 |
| 删除 | `broca/session_runner/manager_legacy.py` |
| manager 清理 | 移除 `LegacyPollThreadMixin` 混入、`_read_multiplexing_flag`、`_ipc_multiplexing`、`_legacy_queues`、`_legacy_register` 分支；`_attach_listener` / `_ipc_listener_loop` 只保留 `IPCPoller` 路径 |
| 配置清理 | 删除 `execution.runner_ipc_multiplexing`（`configs.py` / `configs.json` / `docs/configuration.md` 三处同步） |
| 统计清理 | `get_stats()["ipc"]` 移除恒为 `true` 的 `multiplexing` 字段（web 前后端均无消费方，已 grep 确认） |
| 测试清理 | 删除 `test_multiplexing_flag_off_uses_legacy_thread`、`test_legacy_path_delivers_message_to_queue`；`test_multiplexing_flag_on_uses_poller` → `test_attach_listener_uses_poller`（并新增断言 `handle.poll_thread is None`）；`test_stats_reports_ipc_multiplexing` → `test_stats_reports_ipc_state` |

### 为什么现在删是安全的

1. `IPCPoller` 已覆盖 10 连接 / 断连 / 脏数据 / 关闭连接 / 真实 `IPCServer`+`IPCClient` 全链路；
2. 回滚路径**会绕过 Task 4.4 的背压策略**（`LegacyPollThreadMixin` 用的是自己的队列），保留它等于把 OOM 风险一起留着；
3. 回滚路径的线程数随 session 数线性增长，是 P1-6 要消除的根因本身。

### 对 Task 4.2 AC 的影响（需在计划层面知悉）

Task 4.2 的 AC #3 是「`grep -c "threading.Thread" manager_legacy.py >= 1`（回滚路径确实被保留）」。
收尾后该 AC **被有意废止**，对应的验证改为：

- `grep -c "threading.Thread" broca/session_runner/manager.py` == 0（仍然成立）
- 全仓 `grep -rn "manager_legacy" broca/ broca-web/ configs/ docs/` 仅命中 `docs/legacy/` 的留档说明

---

## 6. 与计划的偏离

| 偏离 | 说明 |
|---|---|
| 新增 `backpressure.py`（计划未列该模块） | 背压策略要被 `poller.py`（父进程）与 `runner.py`（子进程）共用。写在任一现有模块都会造成反向依赖（`runner` 不该依赖 `poller`，`poller` 也不该依赖 `runner`），抽成独立无依赖模块是最小代价 |
| 测试数 4 → 10 | 计划 4 例只覆盖「策略生效」，缺「策略不能过头」（不得丢命令）、「哨兵不可丢」、「不得回归无界队列」三类反向守卫 |
| 日志 handler 抽出 `build_file_handler()` | `setup_logging` 走 `logging.basicConfig` 是全局副作用，无法在测试里断言轮转行为；抽出纯函数后可直接 `doRollover()` 验证 |

---

## 7. 结论

P1-7 的两个问题都闭环：

| 指标 | 修复前 | 修复后 |
|---|---|---|
| 无界队列 | 2 处 | **0 处**（有长期 grep 守卫） |
| 队列满时行为 | 内存无限增长 | 心跳丢旧、命令丢新、哨兵必达，全部计数 |
| 可观测性 | 无 | `get_stats()["dropped_events"]`（父）+ `CMD_GET_STATS`（子） |
| 日志轮转 | 跨天不轮转 | `when=midnight` + `backupCount=7` |
| 日志文件名 | `{YYYYMMDD}.log` | `runner.log`（固定，由 handler 归档） |
