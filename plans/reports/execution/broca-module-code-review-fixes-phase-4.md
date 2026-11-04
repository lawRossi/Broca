# Phase 4 执行报告：核心引擎健壮性加固

**计划**: `plans/broca-module-code-review-fixes.md`
**日期**: 2026-11-04
**状态**: ✅ 完成

## 任务完成摘要

| Task | 描述 | 状态 | 新增测试数 |
|------|------|------|-----------|
| 4.1 | 清理 LiteLLMClient 可变实例状态 | ✅ | 3 |
| 4.2 | CancelledError 后 _finalize_turn 防护 | ✅ | 4 |
| 4.3 | Tool.TOOL_RESULT_CACHE_DIR 改为绝对路径 | ✅ | 6 |
| 4.4 | _save_user_message 避免突变输入参数 | ✅ | 5 |
| 4.5 | Agent._handle_task 的 assigner=None 防御 | ✅ | 6 |

**总计**: 24 新增测试

## 关键变更

### `broca/llm.py`
- 删除 `self.input_tokens_used` / `self.output_tokens_used` 实例属性
- `_process_chunk` 不再赋值实例状态，仅 yield usage 事件
- `test_llm.py` 更新：验证 `vars(client)` 中无 token 属性

### `broca/loop_engine/engine.py`
- `_finalize_turn` 新增 `except asyncio.CancelledError` 分支（Python 3.9+ 中 CancelledError 是 BaseException）
- `execute()` 中 `_finalize_turn` 调用外包 `try/except Exception` 防御性保护
- `_save_user_message` 不再突变 `message.data`，改为构造新 dict

### `broca/tools/tool.py`
- 新增 `_get_cache_dir(workspace)` 方法，基于 workspace 返回绝对路径
- `_post_process_result` 新增 `workspace` 参数，使用 `_get_cache_dir` 替代类属性
- 调用方 `execute()` 传入 `context.workspace`

### `broca/agent.py`
- `_handle_task` 中 `task_id`/`assigner` 提前初始化防止 NameError
- 所有 `send_task_complete`/`send_task_error` 调用前检查 `assigner is not None`
- 异常分支中 assigner=None 时仅 log 不 send

## 测试套件结果

```
1332 passed, 5 skipped, 1 deselected in 55.24s
```

无新增失败。

## 新增测试文件
- `broca/tests/test_llm_concurrent_tokens.py` (3 tests)
- `broca/tests/test_finalized_turn_cancelled.py` (4 tests)
- `broca/tests/test_tool_cache_absolute_path.py` (6 tests)
- `broca/tests/test_save_user_message_no_mutation.py` (5 tests)
- `broca/tests/test_handle_task_assigner_defense.py` (6 tests)
