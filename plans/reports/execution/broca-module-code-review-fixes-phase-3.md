# Phase 3 执行报告：通讯模块修复

**计划**: `plans/broca-module-code-review-fixes.md`
**日期**: 2026-11-04
**状态**: ✅ 完成

## 任务完成摘要

| Task | 描述 | 状态 | 新增测试数 |
|------|------|------|-----------|
| 3.1 | `_MessageDispatcher._table` 补全 9 个缺失 MessageType | ✅ | 3 |
| 3.2 | `message_callbacks` 超时清理 | ✅ | 9 |
| 3.3 | 统一 `send_message()` 异常类型 + subscribe/unsubscribe 一致性 | ✅ | 13 |
| 3.4 | Server 端 client_id 唯一性 + 未知 receiver 回送错误 | ✅ | 6 |
| 3.5 | CONNECT 消息 role 修复 + TTL 注释修正 | ✅ | (含在 3.1 中) |
| 3.6 | Communicator ABC 补全方法 | ✅ | 10 |

**总计**: 41 新增测试

## 关键变更

### `broca/communication/socketio_client.py`
- **Task 3.1**: `_MessageDispatcher._table` 从 4 个条目扩展到 13 个（+9 缺失的 MessageType）
- **Task 3.2**: `message_callbacks` 类型改为 `Dict[str, Tuple[Callable, float]]`；新增 `MESSAGE_CALLBACK_TIMEOUT=120.0`、`_callback_cleanup_loop()` 后台任务（30s 扫描周期）；`disconnect()` 中取消清理任务并清空 callbacks
- **Task 3.3**: `send_message()` 重试耗尽后 raise `CommunicationError`（保留 `__cause__`），删除不可达的 `return ""`；`subscribe()`/`unsubscribe()` 中非 `CommunicationError` 的异常统一包装为 `CommunicationError`
- **Task 3.5**: CONNECT 消息 `role` 从 `USER` 改为 `SYSTEM`

### `broca/communication/socketio_server.py`
- **Task 3.4**: `connect` handler 检测 client_id 冲突时清理旧 SID 的 `ClientInfo` 和订阅映射；`_process_message()` 中 `_send_to_client()` 返回 False 时向 sender 回送 `ROUTING_FAILED` 错误
- **Task 3.5**: 修正 `_pending_messages` TTL 注释

### `broca/components/communicator.py`
- **Task 3.6**: 新增 9 个抽象方法（`send_turn_start`, `send_turn_end`, `send_command`, `send_command_result`, `send_permission_request`, `send_permission_response`, `send_error`, `send_task_start`, `send_task_complete`），签名完全对齐 `SocketIOClient` 实际方法

## 测试套件结果

```
1308 passed, 5 skipped, 1 deselected in 53.08s
```

无新增失败。

## 新增测试文件
- `broca/tests/test_message_dispatcher.py` (3 tests)
- `broca/tests/test_callback_timeout.py` (9 tests)
- `broca/tests/test_send_message_exceptions.py` (13 tests)
- `broca/tests/test_server_client_id_routing.py` (6 tests)
- `broca/tests/test_communicator_abc.py` (5 tests)
