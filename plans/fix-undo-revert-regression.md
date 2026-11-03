# 修复 Undo/Revert 功能回归

## 概述
- **目标**：修复重构分支中 undo 功能的两个回归问题
- **背景**：refactor 分支（`.worktrees/refactor`）在重构后出现：
  1. undo 成功后前端无提示、页面不刷新
  2. turn 内部分步骤撤销（step-level undo）导致整个 turn 在前端不可见
- **约束条件**：main 分支行为正确，以 main 分支为基准修复

## 相关材料
- **Main 分支代码**：`/Users/luoweiang/code/Broca/`（行为正确，作为参考）
- **Refactor 分支代码**：`/Users/luoweiang/code/Broca/.worktrees/refactor/`（有 bug）
- **关键对比文件**：
  - `broca/agent.py` — IPC 命令处理（`_on_command` 方法）
  - `broca/commands/manager.py` — 新增的 `FileCommandSystem`（`send_result` 方法）
  - `broca/session/revert_service.py` — `_mark_messages_as_reverted_sql` vs `_mark_messages_as_reverted`
  - `broca/session/service.py` — `get_message_ids_from_pivot` 方法

## 总体方案

### Bug 1 根因分析

**问题**：IPC 命令（通过 Socket.IO 发送的 undo/redo）执行成功后，结果未发送回前端。

**根因**：
- **Main 分支** `agent.py._on_command` 直接调用 `self.communicator.send_command_result(...)` 发送结果，不检查 `show_result` 标志。
- **Refactor 分支** `agent.py._on_command` 改为调用 `self.command_manager.send_result(command, result, self.session_id)`，而 `send_result`（`commands/manager.py`）仅在 `cmd.show_result == True` 时才发送结果。`UndoCommand` 继承自 `LocalCommand`，其 `show_result` 默认为 `False`，因此结果永远不会被发送。

**修复**：在 `_on_command`（IPC 路径）中，不依赖 `show_result`，直接发送结果。保持 inline 命令路径（`_handle_command`）使用 `send_result` 以尊重 `show_result`。

### Bug 2 根因分析

**问题**：step-level undo（pivot 在 turn 中间的 STEP_START）标记了整个 turn 为 reverted，导致前端隐藏了仍有活跃消息的 turn。

**根因**：
- **Main 分支** `_mark_messages_as_reverted` 加载全量消息，按 turn 分组后，仅当 turn 的 **所有** 消息都在 revert 集合中才标记该 turn 为 reverted。
- **Refactor 分支** `_mark_messages_as_reverted_sql` 使用简化规则：将 `get_message_ids_from_pivot` 返回的 **所有** turn_ids 直接标记为 reverted。当 pivot 在 turn 中间时（step-level），该 turn 中 pivot 之前的消息未被 revert，但整个 turn 仍被标记为 reverted。

**修复**：在 `_mark_messages_as_reverted_sql` 中，对 pivot 所在的 turn（第一个 turn）进行额外检查：只有当该 turn 的所有消息都在 revert 集合中时才标记。后续 turn 可保持简化逻辑（因为从 TURN_START 开始的 revert 必然覆盖整个后续 turn）。

## 执行计划

### Phase 1: 修复 Undo/Revert 回归
**目标**：修复两个回归 bug，使 refactor 分支的 undo 行为与 main 一致

**阶段验收标准**：
- [ ] 通过 IPC 发送 undo 命令后，前端收到 command_result 事件，显示重做按钮并刷新消息列表
- [ ] step-level undo（turn 中间步骤撤销）后，该 turn 仍然可见（未被标记为 reverted）
- [ ] turn-level undo 行为不变（整个 turn 被正确标记为 reverted 并隐藏）
- [ ] redo 后 turn 正确恢复可见

#### Task 1.1: 修复 IPC 命令结果发送（Bug 1）
- **目标**：使 IPC 命令路径（`_on_command`）始终将结果发送回前端，不受 `show_result` 控制
- **步骤**：
  1. 打开 `broca/agent.py`，找到 `_on_command` 方法（约 line 649-685）
  2. 将 line 682 的 `await self.command_manager.send_result(command, result, self.session_id)` 替换为直接发送逻辑：
     ```python
     if result.type == "error":
         await self.communicator.send_error(
             {"message": result.value, "code": "COMMAND_ERROR", "severity": "error"},
             subscription=self.session_id,
         )
     else:
         await self.communicator.send_command_result(
             command=command,
             result={
                 "code": 0 if result.type != "error" else 1,
                 "message": result.value,
             },
             subscription=self.session_id,
         )
     ```
  3. 保持 `_handle_command`（inline 命令路径，约 line 528-551）中的 `self.command_manager.send_result(...)` 调用不变
- **预期产出**：`broca/agent.py` 中 `_on_command` 方法修改
- **验收标准**：
  - [ ] `_on_command` 中的 undo/redo 命令执行后，`communicator.send_command_result` 或 `communicator.send_error` 被调用
  - [ ] `_handle_command`（inline 路径）仍使用 `command_manager.send_result`，尊重 `show_result`
  - [ ] `commands/manager.py` 的 `send_result` 方法不需要修改

#### Task 1.2: 修复 turn 级别 revert 标记逻辑（Bug 2）
- **目标**：`_mark_messages_as_reverted_sql` 仅当 turn 的所有消息都被 revert 时才标记该 turn
- **步骤**：
  1. 打开 `broca/session/revert_service.py`，找到 `_mark_messages_as_reverted_sql` 方法（约 line 222-250）
  2. 在标记 turn 之前，添加 SQL 查询检查 pivot 所在 turn 是否有未 revert 的消息：
     ```python
     # 对 pivot 所在的 turn 进行精确检查
     # 仅当 turn 中所有消息都在 revert 集合中时才标记
     if turn_ids_from_pivot and message_ids_to_revert:
         async with db_manager.get_session() as session:
             # 查找这些 turn 中有未被 revert 的消息的 turn
             partial_rows = (
                 await session.execute(
                     select(Message.turn_id)
                     .where(Message.agent_id == agent_id)
                     .where(Message.turn_id.in_(list(turn_ids_from_pivot)))
                     .where(Message.message_id.not_in(list(message_ids_to_revert)))
                     .distinct()
                 )
             ).scalars().all()
             partial_turns = {tid for tid in partial_rows if tid}

         # 排除部分 revert 的 turn
         turn_ids_to_mark = turn_ids_from_pivot - partial_turns
         if turn_ids_to_mark:
             await self.session_manager.batch_update_turns(
                 list(turn_ids_to_mark), reverted=True
             )
     ```
  3. 需要在文件顶部添加 `from sqlalchemy import select` 和 `from broca.session.database import db_manager` 的 import（如果尚未存在）
- **预期产出**：`broca/session/revert_service.py` 中 `_mark_messages_as_reverted_sql` 方法修改
- **验收标准**：
  - [ ] step-level undo（pivot 在 turn 中间）后，pivot 所在的 turn 若还有未 revert 的消息，则不被标记为 reverted
  - [ ] turn-level undo（pivot 是 TURN_START）后，该 turn 的所有消息都被 revert，turn 被正确标记为 reverted
  - [ ] 后续完整 turn 的 revert 标记行为不变
  - [ ] redo 后 turn 的 reverted 标记正确恢复

#### Task 1.3: 验证修复
- **目标**：确认两个 bug 均已修复，且无副作用
- **步骤**：
  1. 运行现有测试：`cd /Users/luoweiang/code/Broca/.worktrees/refactor && python -m pytest broca/tests/ -x -v -k "revert or undo or redo"` 确认无回归
  2. 检查 `broca/agent.py` 的 `_on_command` 和 `_handle_command` 两个路径逻辑是否正确分离
  3. 检查 `broca/session/revert_service.py` 中 `_mark_messages_as_reverted_sql` 的边界情况：
     - `turn_ids_from_pivot` 为空时不执行查询
     - `message_ids_to_revert` 为空时不执行查询
- **预期产出**：测试通过，代码审查无问题
- **验收标准**：
  - [ ] 所有现有 revert/undo/redo 相关测试通过
  - [ ] `_on_command` 中不再调用 `command_manager.send_result`
  - [ ] `_mark_messages_as_reverted_sql` 包含 turn 完整性检查逻辑

## 风险与应对
| 风险 | 影响 | 应对策略 |
|------|------|----------|
| `not_in` 查询在大量 message_id 时性能问题 | 慢查询 | 通常 undo 涉及的 turn 数量很少（1-5 个），`in`/`not_in` 列表长度可控 |
| `_on_command` 直接操作 communicator 绕过 command_manager | 架构一致性 | 这是 IPC 路径的特殊需求（main 分支也是这样做的），inline 路径仍走 command_manager |

## 未解决的问题
（无）
