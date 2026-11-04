# legacy/ — 已下线实现的留档备份

这里存放**已从运行时移除**的历史实现，仅供追溯与应急参考。

- 这些文件**不参与构建、不被任何模块 import**，后缀统一为 `.bak` 以避免被
  lint / test 收集器误扫。
- 需要复活某段逻辑时，请先评估它当初被删除的原因（见同名执行报告的
  「顺带清理 / 收尾」章节），不要直接 `cp` 回 `broca/`。

## 清单

| 文件 | 原路径 | 下线时间 | 原因 |
|---|---|---|---|
| `session_runner/manager_legacy.py.bak` | `broca/session_runner/manager_legacy.py` | 2026-11-04（Task 4.3/4.4 收尾） | IPC 单线程多路复用（`IPCPoller`）已在 Phase 4 Task 4.2 完成并稳定，`LegacyPollThreadMixin`（每 session 一个轮询线程）作为灰度回滚路径已无保留价值：① 线程数随 session 数线性增长（10 session = 10 线程）；② 回滚路径会绕过 Task 4.4 的队列背压策略，保留它等于把 OOM 风险一起留着。 |
