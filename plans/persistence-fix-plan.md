# 数据持久化性能与组件化修复计划

## 概述
- **目标**：修复 refactor 分支中数据持久化层的 9 项性能瓶颈和组件化不足
- **背景**：refactor 分支引入了 ABC 组件层（`broca/components/`），但底层实现仍存在高频写路径的低效查询、全量加载、无 ABC 等问题
- **约束条件**：
  - 不改变 hook 生命周期（`on_turn_start → on_step_start → on_step_end → on_post_step → on_turn_end → on_turn_finalized`）
  - 不改变任何 ABC 接口签名
  - 所有修改向后兼容（已有数据不需迁移，或仅需一个简单 Alembic migration）
  - 在 `.worktrees/refactor` 分支上执行
  - Message 模型不新增任何列。序列号管理完全转移到辅助表

## 相关材料
- 持久化核心代码：`broca/session/database.py`、`broca/session/models.py`、`broca/session/service.py`、`broca/session/session_manager.py`
- 撤销逻辑：`broca/session/revert_service.py`
- 快照：`broca/snapshot/`（git_manager、track、patch、restore、manager）
- 持久化记忆：`broca/persistent_memory/store.py`、`broca/persistent_memory/manager.py`
- Skill 存储：`broca/skill/skill_store.py`
- 调度器：`broca/scheduler.py`
- ABC 层：`broca/components/session_manager.py`、`broca/components/snapshot_manager.py`、`broca/components/task_manager.py`、`broca/components/memory_manager.py`
- 组件注册：`broca/components/defaults.py`（`_DEFAULT_IMPLS`、`COMPONENT_SCOPES`、`ENTRY_POINT_NAMES`）、`broca/components/__init__.py`
- 循环引擎（调用方）：`broca/loop_engine/engine.py`
- Hook 实现：`broca/loop_engine/hooks/`
- 测试：`broca/tests/session/`、`broca/tests/test_snapshot_undo_redo.py`、`broca/tests/persistent_memory/`
- 数据库迁移：`broca/alembic/versions/`

## 总体方案

按 **性能优化** → **组件化** 两个阶段执行：

1. **Phase 1（性能）**：优化高频写路径（sequence_number、start_turn 事务合并）、undo/redo SQL 化、查询优化（search/stats）、存储层调优（pool size、MemoryStore 缓存）
2. **Phase 2（组件化）**：补充 Scheduler ABC、RevertService ABC、GitManager 线程安全

**依赖关系**：
- Task 1.2 依赖 Task 1.1（`start_turn` 合并事务时调用 Task 1.1 新增的 `next_sequence_in_session` 方法）
- Task 1.3-1.8 互相独立，可并行执行
- Phase 2 各 Task 互相独立，且依赖 Phase 1 完成（因为 Phase 2 会修改 Phase 1 已优化的类）

所有改动遵循原则：
- ABC 接口不变，仅改实现
- 每个修复独立可验证，不引入跨文件依赖
- 新增 Alembic migration 仅在 schema 变更时

---

## 执行计划

### Phase 1: 性能优化

**目标**：消除高频路径上的 O(n) 查询、多余事务、全量加载

**阶段验收标准**：
- [ ] 单次 `save_message` 不再执行 `SELECT MAX(sequence_number)` 查询
- [ ] `start_turn` 的 DB 操作合并在 1 个事务中
- [ ] `undo()`/`redo()` 不再调用 `get_messages(agent_id)` 全量加载
- [ ] `TaskService.search_tasks` 使用 SQL `LIKE` 而非 Python 过滤
- [ ] `TurnService.get_turn_stats` 使用 SQL 聚合
- [ ] SQLite 连接池调整为 `pool_size=3, max_overflow=5`
- [ ] `MemoryStore` 支持内存缓存，避免每次操作全文件读写
- [ ] `SkillStore` 支持内存缓存
- [ ] 全部通过：`pytest broca/tests/session/ broca/tests/test_snapshot_undo_redo.py broca/tests/persistent_memory/ broca/tests/test_loop_engine.py -v`

---

#### Task 1.1: sequence_number 优化 — 使用辅助计数器表

**依赖**：无（Phase 1 首个 Task）

- **目标**：消除每次 `save_message` 的 `SELECT MAX(sequence_number)+1` 查询
- **设计说明**：
  - Message 模型 **不变**（`sequence_number` 字段保留为普通 INTEGER，由外部写入）
  - 新增 `message_seq_counter` 辅助表存储每个 session 的下一个序列号
  - 使用 SQLite UPSERT 原子操作（`ON CONFLICT DO UPDATE SET last_seq = last_seq + 1 RETURNING last_seq`）
  - Turn 序号复用同一张表，key = `turn_{session_id}`
- **步骤**：
  1. 在 `broca/session/models.py` 中新增 `MessageSeqCounter` 模型：
     ```python
     class MessageSeqCounter(BaseModel, table=True):
         """辅助计数器表：为每个 session 维护 message 和 turn 的序列号"""
         __tablename__ = "message_seq_counter"
         counter_key: str = Field(primary_key=True, description="格式: {session_id} 或 turn_{session_id}")
         last_seq: int = Field(default=0, description="最后分配的序列号")
     ```
  2. 新增 Alembic migration（`broca/alembic/versions/xxxx_add_message_seq_counter.py`）：
     ```python
     def upgrade():
         op.create_table(
             "message_seq_counter",
             sa.Column("counter_key", sa.String, primary_key=True),
             sa.Column("last_seq", sa.Integer, nullable=False, server_default="0"),
         )
         # 数据兼容：为已有 session 初始化 counter
         op.execute("""
             INSERT INTO message_seq_counter (counter_key, last_seq)
             SELECT DISTINCT session_id, COALESCE(MAX(sequence_number), 0)
             FROM message WHERE session_id IS NOT NULL
             GROUP BY session_id;
         """)
         op.execute("""
             INSERT INTO message_seq_counter (counter_key, last_seq)
             SELECT 'turn_' || session_id, COALESCE(MAX(sequence_number), 0)
             FROM turn WHERE session_id IS NOT NULL
             GROUP BY session_id
             ON CONFLICT(counter_key) DO NOTHING;
         """)
     ```
  3. 在 `broca/session/service.py` 的 `MessageService` 中新增方法：
     ```python
     from sqlalchemy.dialects.sqlite import insert as sqlite_insert
     from broca.session.models import MessageSeqCounter

     async def next_sequence_for_session(self, session_id: str) -> int:
         """原子递增并返回该 session 的下一个 message 序列号"""
         async with db_manager.get_session() as session:
             stmt = (
                 sqlite_insert(MessageSeqCounter)
                 .values(counter_key=session_id, last_seq=0)
                 .on_conflict_do_update(
                     index_elements=["counter_key"],
                     set_={"last_seq": MessageSeqCounter.last_seq + 1},
                 )
                 .returning(MessageSeqCounter.last_seq)
             )
             # 首次插入时 last_seq=0，需要 +1 作为第一个有效序列号
             # UPSERT 时 last_seq = old + 1
             result = await session.execute(stmt)
             value = result.scalar_one()
             await session.commit()
             return value
     ```
  4. 在 `TurnService` 中新增 `next_turn_sequence_for_session(self, session_id: str) -> int`（实现类似，`counter_key = f"turn_{session_id}"`）
  5. 修改 `broca/session/session_manager.py` 的 `save_message`：将 `seq_num = await self.message_service.get_next_sequence_number(self.session_id)` 替换为 `seq_num = await self.message_service.next_sequence_for_session(self.session_id)`
  6. 将 `MessageService.get_next_sequence_number` 标记为 deprecated，内部委托 `next_sequence_for_session`（向后兼容过渡）
  7. 更新测试：在 `broca/tests/session/test_database.py` 或新建 `test_sequence_counter.py` 中添加：
     - 同一 session 连续 10 次 `next_sequence_for_session` 返回 1-10
     - 并发 5 协程调用无重复值
     - 已有数据的 session 初始化后从正确值继续

- **预期产出**：
  - 修改的 `broca/session/models.py`（新增 `MessageSeqCounter`）
  - 修改的 `broca/session/service.py`（新增方法 + deprecate 旧方法）
  - 修改的 `broca/session/session_manager.py`（`save_message` 调用新方法）
  - 新增 Alembic migration 文件
  - 新增/更新测试

- **验收标准**：
  - [ ] `save_message` 调用链中无 `SELECT MAX(sequence_number)` 查询（通过 SQL echo 或 `aiosqlite` 事件监听验证）
  - [ ] 同一 session 内连续 `save_message` 10 次，`sequence_number` 严格递增无重复（1,2,3...10）
  - [ ] 并发 5 个协程同时 `save_message` 同一 session，无主键冲突、无重复序列号
  - [ ] 已有数据库（含历史消息）启动后，UPSERT 从 `MAX(sequence_number)+1` 继续递增
  - [ ] `pytest broca/tests/session/ -v` 全部通过

---

#### Task 1.2: start_turn 事务合并

**依赖**：Task 1.1（需要 `next_sequence_in_session` 方法）

- **目标**：将 `start_turn` 从 4-5 个独立事务减少到 1 个
- **步骤**：
  1. 在 `broca/session/database.py` 的 `AsyncDatabaseManager` 中新增方法：
     ```python
     @asynccontextmanager
     async def get_multi_session(self) -> AsyncGenerator[AsyncSession, None]:
         """长事务上下文管理器。
         
         ⚠️ 与 get_session() 的区别：
         - get_session(): 调用者手动 commit/rollback
         - get_multi_session(): 正常退出时自动 commit，异常时自动 rollback
         
         用于将多个 DB 操作合并在一个事务中原子执行。
         """
         self._ensure_initialized()
         async with self._session_factory() as session:
             try:
                 yield session
                 await session.commit()
             except BaseException:
                 await session.rollback()
                 raise
     ```
  2. 在 `MessageService` 中新增 `create_message_in_session(self, db_session: AsyncSession, **kwargs) -> Message`：
     ```python
     async def create_message_in_session(self, db_session: AsyncSession, **kwargs) -> Message:
         """在外部事务中创建消息。
         
         ⚠️ 此方法不做 commit/rollback——事务生命周期由外层 get_multi_session() 管理。
         调用者必须确保 db_session 处于活跃事务中。
         """
         assert db_session.in_transaction(), "create_message_in_session requires an active transaction (use get_multi_session)"
         instance = Message(**kwargs)
         db_session.add(instance)
         await db_session.flush()  # flush 而非 commit，让外层统一提交
         return instance
     ```
  3. 在 `TurnService` 中新增 `create_turn_in_session(self, db_session: AsyncSession, **kwargs) -> Turn`（模式同上）
  4. 新增 `MessageService.next_sequence_in_session(self, db_session: AsyncSession, session_id: str) -> int`：
     ```python
     async def next_sequence_in_session(self, db_session: AsyncSession, session_id: str) -> int:
         """在外部事务中递增序列号。不 commit。"""
         assert db_session.in_transaction()
         stmt = (
             sqlite_insert(MessageSeqCounter)
             .values(counter_key=session_id, last_seq=0)
             .on_conflict_do_update(
                 index_elements=["counter_key"],
                 set_={"last_seq": MessageSeqCounter.last_seq + 1},
             )
             .returning(MessageSeqCounter.last_seq)
         )
         result = await db_session.execute(stmt)
         return result.scalar_one()
     ```
  5. 新增 `TurnService.next_turn_seq_in_session(self, db_session: AsyncSession, session_id: str) -> int`（同上，`counter_key = f"turn_{session_id}"`）
  6. 重写 `SQLSessionManager.start_turn`：
     ```python
     async def start_turn(self, agent_id, description=None):
         if not self.session_id:
             return None
         await self._ensure_initialized()
         turn_id = f"turn_{uuid.uuid4().hex[:16]}"
         
         async with db_manager.get_multi_session() as db_session:
             # 1. 获取 turn 序列号
             seq_num = await self.turn_service.next_turn_seq_in_session(db_session, self.session_id)
             # 2. 创建 turn 记录
             await self.turn_service.create_turn_in_session(db_session,
                 turn_id=turn_id, session_id=self.session_id, agent_id=agent_id,
                 sequence_number=seq_num, turn_description=description,
                 execution_id=self.current_execution_id,
             )
             # 3. 创建 TURN_START 消息
             msg_seq = await self.message_service.next_sequence_in_session(db_session, self.session_id)
             await self.message_service.create_message_in_session(db_session,
                 message_id=f"msg_{uuid.uuid4().hex[:16]}",
                 session_id=self.session_id, turn_id=turn_id, agent_id=agent_id,
                 role=MessageRole.AGENT, message_type=MessageType.TURN_START,
                 sequence_number=msg_seq, data={},
             )
         # 自动 commit 在 context exit 时发生
         logger.info(f"Started new turn: {turn_id}")
         return turn_id
     ```
  7. `end_turn` 和 `save_turn_end` 各自仅涉及 1-2 个 DB 操作，无需合并事务，保持现有 `get_session()` 模式即可。
  8. 更新测试：验证 turn 和 TURN_START message 的原子性（注入 fault 使 message 写入失败，验证 turn 也被回滚）

- **预期产出**：
  - 修改的 `broca/session/database.py`（新增 `get_multi_session`）
  - 修改的 `broca/session/service.py`（新增 `*_in_session` 方法族）
  - 修改的 `broca/session/session_manager.py`（重写 `start_turn`）
  - 更新的测试

- **验收标准**：
  - [ ] `start_turn` 只产生 1 个数据库事务（通过 `engine.sync_engine` 的 `begin`/`commit` 事件计数验证）
  - [ ] 原子性：模拟 `create_message_in_session` 抛异常，验证 turn 记录也被回滚（DB 中无残留 turn）
  - [ ] 正常流程下 turn 的 `sequence_number` 和 message 的 `sequence_number` 均正确递增
  - [ ] `pytest broca/tests/session/test_turn_service.py -v` 通过
  - [ ] `pytest broca/tests/test_loop_engine.py -v` 通过

---

#### Task 1.3: undo/redo 全量加载 → SQL 化

**依赖**：无（与 Task 1.1/1.2 独立）

- **目标**：`undo()` 和 `redo()` 不再调用 `get_messages(agent_id)` 全量加载
- **步骤**：
  1. 在 `MessageService` 中新增方法：
     ```python
     async def get_message_ids_from_pivot(self, agent_id: str, pivot_message_id: str) -> set[str]:
         """获取从 pivot 开始（含）的所有 message_id（仅查 ID，不加载完整 data）"""
         async with db_manager.get_session() as session:
             pivot_seq = (await session.exec(
                 select(Message.sequence_number).where(Message.message_id == pivot_message_id)
             )).scalars().first()
             if pivot_seq is None:
                 return set()
             ids = (await session.exec(
                 select(Message.message_id)
                 .where(Message.agent_id == agent_id)
                 .where(Message.sequence_number >= pivot_seq)
             )).scalars().all()
             return set(ids)
     ```
  2. 新增 `get_messages_from_pivot(self, agent_id: str, pivot_message_id: str) -> List[Message]`：
     ```python
     async def get_messages_from_pivot(self, agent_id: str, pivot_message_id: str) -> List[Message]:
         """获取从 pivot 开始（含）到 agent 最后一条消息的完整消息（用于收集 patches）"""
         async with db_manager.get_session() as session:
             pivot_seq = (await session.exec(
                 select(Message.sequence_number).where(Message.message_id == pivot_message_id)
             )).scalars().first()
             if pivot_seq is None:
                 return []
             return (await session.exec(
                 select(Message)
                 .where(Message.agent_id == agent_id)
                 .where(Message.sequence_number >= pivot_seq)
                 .order_by(Message.sequence_number)
             )).scalars().all()
     ```
  3. 新增 `find_pivot_message_id(self, agent_id: str, target_message_id: str, level: str) -> Optional[str]`：
     ```python
     async def find_pivot_message_id(self, agent_id: str, target_message_id: str, level: str) -> Optional[str]:
         """通过 SQL 查找 pivot message_id"""
         async with db_manager.get_session() as session:
             # 获取目标消息的 turn_id 和 step_id
             target = (await session.exec(
                 select(Message.turn_id, Message.data)
                 .where(Message.message_id == target_message_id)
             )).first()
             if not target:
                 return None
             target_turn_id, target_data = target
             
             if level == "turn":
                 # 找该 turn 的 TURN_START 消息
                 pivot = (await session.exec(
                     select(Message.message_id)
                     .where(Message.turn_id == target_turn_id)
                     .where(Message.agent_id == agent_id)
                     .where(Message.message_type == MessageType.TURN_START)
                     .limit(1)
                 )).scalars().first()
                 if not pivot:
                     pivot = target_message_id  # fallback
             else:  # level == "step"
                 step_id = (target_data or {}).get("step_id")
                 if step_id:
                     pivot = (await session.exec(
                         select(Message.message_id)
                         .where(Message.turn_id == target_turn_id)
                         .where(Message.agent_id == agent_id)
                         .where(Message.message_type == MessageType.STEP_START)
                         .where(func.json_extract(Message.data, "$.step_id") == step_id)
                         .limit(1)
                     )).scalars().first()
                 else:
                     pivot = target_message_id  # fallback
             return pivot
     ```
  4. 新增 `get_turn_ids_for_message_ids(self, agent_id: str, message_ids: set[str]) -> list[str]`：
     ```python
     async def get_turn_ids_for_message_ids(self, agent_id: str, message_ids: set[str]) -> list[str]:
         """批量查找 message_ids 对应的 turn_id 集合（用于 redo 恢复 turn 标记）"""
         if not message_ids:
             return []
         async with db_manager.get_session() as session:
             turn_ids = (await session.exec(
                 select(Message.turn_id)
                 .where(Message.agent_id == agent_id)
                 .where(Message.message_id.in_(message_ids))
                 .where(Message.turn_id.isnot(None))
                 .distinct()
             )).scalars().all()
             return list(turn_ids)
     ```
  5. 新增 `find_last_target_message_id(self, agent_id: str) -> Optional[str]`：
     ```python
     async def find_last_target_message_id(self, agent_id: str) -> Optional[str]:
         """找最后一条 AGENT_RESPONSE 的 message_id（LIMIT 1，不全量加载）"""
         async with db_manager.get_session() as session:
             msg_id = (await session.exec(
                 select(Message.message_id)
                 .where(Message.agent_id == agent_id)
                 .where(Message.message_type == MessageType.AGENT_RESPONSE)
                 .order_by(Message.sequence_number.desc())
                 .limit(1)
             )).scalars().first()
             if not msg_id:
                 # fallback: 最后一条消息
                 msg_id = (await session.exec(
                     select(Message.message_id)
                     .where(Message.agent_id == agent_id)
                     .order_by(Message.sequence_number.desc())
                     .limit(1)
                 )).scalars().first()
             return msg_id
     ```
  6. 新增 `find_fully_reverted_turn_ids(self, agent_id: str) -> list[str]`：
     ```python
     async def find_fully_reverted_turn_ids(self, agent_id: str) -> list[str]:
         """找出该 agent 所有消息都已撤销的 turn"""
         async with db_manager.get_session() as session:
             stmt = (
                 select(Turn.turn_id)
                 .join(Message, Message.turn_id == Turn.turn_id)
                 .where(Message.agent_id == agent_id)
                 .group_by(Turn.turn_id)
                 .having(func.sum(case((Message.reverted == False, 1), else_=0)) == 0)
             )
             result = await session.exec(stmt)
             return list(result.scalars().all())
     ```
  7. 重写 `SessionRevertService.undo()`：
     ```python
     async def undo(self, session_id, agent_id, target_message_id=None, level="step"):
         # 1. 验证 session
         session = await self.session_manager.get_session(session_id)
         if not session:
             raise SessionError(f"会话不存在: {session_id}")
         
         # 2. 自动定位 target（SQL LIMIT 1）
         if not target_message_id:
             target_message_id = await msg_service.find_last_target_message_id(agent_id)
         
         # 3. 找 pivot（SQL 查询）
         pivot_message_id = await msg_service.find_pivot_message_id(agent_id, target_message_id, level)
         if not pivot_message_id:
             return {"success": False, "error": "No pivot message found", "patches_reverted": 0}
         
         # 4. 收集 patches（仅加载 pivot 之后的消息）
         messages_after = await msg_service.get_messages_from_pivot(agent_id, pivot_message_id)
         patches = [
             m.data.get("patch") for m in messages_after
             if m.message_type == MessageType.STEP_END and m.data and m.data.get("patch")
         ]
         
         # 5. 快照 + 文件恢复（逻辑不变）
         patches_to_revert = [p for p in patches if p]
         current_snapshot_hash = ""
         if patches_to_revert and self.enable_snapshot_tracking:
             current_snapshot_hash = await self.snapshot_tracker.track()
             await self.snapshot_restorer.revert_patches(patches_to_revert)
             ...
         
         # 6. 标记撤销（SQL 批量）
         message_ids = await msg_service.get_message_ids_from_pivot(agent_id, pivot_message_id)
         if message_ids:
             await self.session_manager.batch_update_messages(list(message_ids), reverted=True)
         
         # 7. 标记完全撤销的 turn
         turn_ids = await msg_service.find_fully_reverted_turn_ids(agent_id)
         if turn_ids:
             await self.session_manager.batch_update_turns(turn_ids, reverted=True)
         
         # 8. 保存 undo 记录
         self.undo_stack.append(self._create_undo_meta_info(...))
         
         return {"success": True, ...}
     ```
  8. 重写 `SessionRevertService.redo()`：
     ```python
     async def redo(self, session_id, agent_id):
         session = await self.session_manager.get_session(session_id)
         if not session:
             raise SessionError(...)
         if not self.undo_stack:
             return {"success": False, "message": "没有可重做的操作"}
         
         undo_meta_info = self.undo_stack[-1]
         
         # 文件恢复（不变）
         ...
         
         # 标记消息恢复
         message_ids_to_restore = set(undo_meta_info.get("message_ids_to_revert", []))
         if message_ids_to_restore:
             await self.session_manager.batch_update_messages(list(message_ids_to_restore), reverted=False)
         
         # 查找对应的 turn_ids（SQL，不全量加载）
         turn_ids = await msg_service.get_turn_ids_for_message_ids(agent_id, message_ids_to_restore)
         if turn_ids:
             await self.session_manager.batch_update_turns(turn_ids, reverted=False)
         
         self.undo_stack.pop()
         return {"success": True}
     ```
  9. 更新 `broca/tests/session/test_revert_service.py`：
     - 验证 undo 后 `get_messages` 的 call_count == 0（通过 mock）
     - 1000 条消息场景性能验证
     - redo 后正确恢复 turn 标记

- **预期产出**：
  - 修改的 `broca/session/service.py`（新增 6 个 SQL 查询方法）
  - 重写的 `broca/session/revert_service.py`（undo/redo 逻辑）
  - 更新的测试

- **验收标准**：
  - [ ] `undo()` 执行过程中 `get_messages(agent_id)` 的调用次数 == 0（通过 mock 的 `call_count` 验证）
  - [ ] 1000 条消息的 session 执行 undo，SQL 查询只返回 pivot 之后的行（通过 SQL echo log 验证行数）
  - [ ] undo 后 `reverted` 标记正确：pivot 及之后的消息/turn 全部标记为 `reverted=True`
  - [ ] redo 后正确恢复：仅恢复本次 undo 标记的消息，turn 标记也正确恢复
  - [ ] `pytest broca/tests/session/test_revert_service.py -v` 通过
  - [ ] `pytest broca/tests/test_snapshot_undo_redo.py -v` 通过

---

#### Task 1.4: TaskService.search_tasks SQL 优化

**依赖**：无（与 Task 1.1/1.2/1.3 独立，可并行）

- **目标**：将 Python 全表过滤改为 SQL `LIKE` 查询
- **步骤**：
  1. 重写 `broca/session/service.py` 中 `TaskService.search_tasks`：
     ```python
     async def search_tasks(self, query: str, session_id: Optional[str] = None) -> List[Task]:
         """搜索任务（按名称和描述，SQL LIKE）"""
         async with db_manager.get_session() as session:
             stmt = select(Task)
             # SQLite 的 LIKE 默认对 ASCII 已 case-insensitive，对中文无大小写概念
             like_pattern = f"%{query}%"
             stmt = stmt.where(
                 or_(
                     Task.name.like(like_pattern),
                     Task.description.like(like_pattern),
                 )
             )
             if session_id:
                 stmt = stmt.where(Task.session_id == session_id)
             stmt = stmt.order_by(Task.created_at.desc()).limit(100)
             result = await session.exec(stmt)
             return result.scalars().all()
     ```
  2. 注意：SQLite 的 `LIKE` 对 ASCII 字符天然 case-insensitive（无需额外 PRAGMA），对中文则直接按 Unicode 码点匹配。`details` 字段为可选搜索目标（大文本），如需要可追加 `or_(Task.details.like(like_pattern))`，但默认不搜索以控制性能。
  3. 添加 `limit=100` 防止超大结果集
  4. 更新测试：验证中英文搜索均工作

- **预期产出**：修改的 `broca/session/service.py`（`search_tasks` 方法）

- **验收标准**：
  - [ ] `search_tasks("broca")` 返回包含 "broca" 的任务（不区分大小写："Broca"、"BROCA" 均匹配）
  - [ ] 中文搜索正常工作：`search_tasks("文件")` 能匹配 `description` 中含 "文件" 的任务
  - [ ] 结果限制在 100 条以内
  - [ ] 1000 条任务的表中搜索，响应时间 < 50ms
  - [ ] 现有 task 相关测试通过（`pytest broca/tests/ -k task -v`）

---

#### Task 1.5: TurnService.get_turn_stats SQL 聚合

**依赖**：无（可并行）

- **目标**：将 Python 遍历统计改为 SQL 聚合查询
- **步骤**：
  1. 重写 `TurnService.get_turn_stats`，拆分为多个轻量 SQL 查询：
     ```python
     async def get_turn_stats(self, turn_id: str) -> Dict[str, Any]:
         async with db_manager.get_session() as session:
             stats: Dict[str, Any] = {
                 "is_reverted": True, "user_message": None, "total_steps": 0,
                 "tool_call_stats": [], "current_file_path": None,
                 "current_todo_list": [], "final_response": "",
                 "last_message_id": None, "changed_files": {},
             }
             
             # Q1: 是否有活跃（未撤销）消息
             active_count = (await session.exec(
                 select(func.count()).select_from(Message)
                 .where(Message.turn_id == turn_id)
                 .where(Message.reverted == False)
             )).scalar_one()
             stats["is_reverted"] = (active_count == 0)
             if active_count == 0:
                 return stats  # 全部撤销，无需继续查
             
             # Q2: 用户消息（LIMIT 1）
             user_msg_data = (await session.exec(
                 select(Message.data)
                 .where(Message.turn_id == turn_id)
                 .where(Message.message_type == MessageType.USER_MESSAGE)
                 .where(Message.reverted == False)
                 .limit(1)
             )).scalars().first()
             if user_msg_data:
                 raw_input = user_msg_data.get("raw_input")
                 if raw_input:
                     stats["user_message"] = str(raw_input)
                 else:
                     raw = user_msg_data.get("content")
                     if raw:
                         try:
                             parsed = json.loads(raw) if isinstance(raw, str) else raw
                             stats["user_message"] = parsed.get("content", str(parsed)) if isinstance(parsed, dict) else str(parsed)
                         except (json.JSONDecodeError, TypeError):
                             stats["user_message"] = str(raw)
             
             # Q3: 步骤计数
             stats["total_steps"] = (await session.exec(
                 select(func.count()).select_from(Message)
                 .where(Message.turn_id == turn_id)
                 .where(Message.message_type == MessageType.STEP_START)
                 .where(Message.reverted == False)
             )).scalar_one()
             
             # Q4: 工具调用统计（GROUP BY）
             tool_rows = (await session.exec(
                 select(
                     func.json_extract(Message.data, "$.tool_name").label("tool_name"),
                     func.count().label("cnt")
                 )
                 .where(Message.turn_id == turn_id)
                 .where(Message.message_type == MessageType.TOOL_CALL)
                 .where(Message.reverted == False)
                 .where(func.json_extract(Message.data, "$.tool_name").isnot(None))
                 .group_by("tool_name")
             )).all()
             stats["tool_call_stats"] = [{"tool_name": r[0], "count": r[1]} for r in tool_rows if r[0]]
             
             # Q5: 最后一条非撤销消息 ID
             stats["last_message_id"] = (await session.exec(
                 select(Message.message_id)
                 .where(Message.turn_id == turn_id)
                 .where(Message.reverted == False)
                 .order_by(Message.sequence_number.desc())
                 .limit(1)
             )).scalars().first()
             
             # Q6: 最终响应（拼接 AGENT_RESPONSE 内容）
             responses = (await session.exec(
                 select(Message.data)
                 .where(Message.turn_id == turn_id)
                 .where(Message.message_type == MessageType.AGENT_RESPONSE)
                 .where(Message.reverted == False)
                 .order_by(Message.sequence_number)
             )).scalars().all()
             parts = []
             for data in responses:
                 try:
                     content = json.loads(data.get("content", "{}")) if isinstance(data.get("content"), str) else data.get("content", {})
                     parts.append(content.get("content", ""))
                 except (json.JSONDecodeError, TypeError):
                     parts.append(data.get("content", ""))
             stats["final_response"] = "\n".join(p for p in parts if p)
             
             # Q7: 最后修改的文件路径
             file_msg = (await session.exec(
                 select(Message.data)
                 .where(Message.turn_id == turn_id)
                 .where(Message.message_type == MessageType.TOOL_CALL)
                 .where(Message.reverted == False)
                 .where(or_(
                     func.json_extract(Message.data, "$.tool_name") == "read_file",
                     func.json_extract(Message.data, "$.tool_name") == "edit_file",
                     func.json_extract(Message.data, "$.tool_name") == "write_file",
                 ))
                 .order_by(Message.sequence_number.desc())
                 .limit(1)
             )).scalars().first()
             if file_msg:
                 args = file_msg.get("arguments")
                 if args:
                     try:
                         parsed = json.loads(args) if isinstance(args, str) else args
                         stats["current_file_path"] = parsed.get("path")
                     except (json.JSONDecodeError, TypeError):
                         pass
             
             # Q8 (可选): TODO 列表
             todo_msg = (await session.exec(
                 select(Message.data)
                 .where(Message.turn_id == turn_id)
                 .where(Message.message_type == MessageType.TOOL_CALL)
                 .where(Message.reverted == False)
                 .where(func.json_extract(Message.data, "$.tool_name") == "todo_management")
                 .where(func.json_extract(Message.data, "$.status") != "error")
                 .order_by(Message.sequence_number.desc())
                 .limit(1)
             )).scalars().first()
             if todo_msg:
                 args = todo_msg.get("arguments")
                 if args:
                     try:
                         parsed = json.loads(args) if isinstance(args, str) else args
                         stats["current_todo_list"] = parsed.get("todos", [])
                     except (json.JSONDecodeError, TypeError):
                         pass
             
             # Q9: changed_files（从最后一条 TURN_END 获取）
             turn_end_data = (await session.exec(
                 select(Message.data)
                 .where(Message.turn_id == turn_id)
                 .where(Message.message_type == MessageType.TURN_END)
                 .where(Message.reverted == False)
                 .order_by(Message.sequence_number.desc())
                 .limit(1)
             )).scalars().first()
             if turn_end_data and turn_end_data.get("changed_files"):
                 stats["changed_files"] = turn_end_data["changed_files"]
             
             return stats
     ```
  2. 对比优化前后的返回值结构，确保字段名和类型一致（golden test）
  3. 更新测试：
     - 构造含 200 条消息的 turn，验证 `get_turn_stats` 结果正确
     - golden test：优化前后对同一数据集输出一致
  4. 确保现有 turn 相关测试通过

- **预期产出**：修改的 `broca/session/service.py`（`get_turn_stats` 方法）+ 更新的测试

- **验收标准**：
  - [ ] 含 200 条消息的 turn 调用 `get_turn_stats`，执行 ≤ 9 次 SQL 查询（Q1-Q9），而非加载 200 行 Python 遍历
  - [ ] 返回值结构和内容与优化前完全一致（golden test 对比：对同一 mock 数据，优化前后 `assert result_old == result_new`）
  - [ ] `tool_call_stats` 正确按 tool_name 聚合（如 `{"tool_name": "bash", "count": 5}`）
  - [ ] 全部消息已撤销的 turn 提前返回 `{"is_reverted": True}`（仅执行 Q1）
  - [ ] 现有 turn 相关测试通过（`pytest broca/tests/session/ -v`）

---

#### Task 1.6: SQLite 连接池调优

**依赖**：无（可并行）

- **目标**：减少不必要的连接数，适配 SQLite 单写者模型
- **步骤**：
  1. 修改 `broca/session/database.py` 的 `_initialize_database`：
     ```python
     self._engine = create_async_engine(
         f"sqlite+aiosqlite:///{database_path}",
         connect_args={"check_same_thread": False, "timeout": 10},
         pool_size=3,        # 从 5 → 3（SQLite 单写者，3 个常驻连接足够）
         max_overflow=5,     # 从 10 → 5（突发时最多再开 5 个，总计 ≤ 8）
         pool_recycle=3600,
         pool_timeout=30,
         pool_pre_ping=True,
         echo=False,
     )
     ```
  2. 添加集成验证测试 `broca/tests/test_pool_sizing.py`：
     - 启动 5 个 `asyncio.create_task` 各执行 10 次 `save_message`
     - 验证总耗时内无 `PoolTimeout` 异常
     - 验证 `engine.pool.size()` 峰值 ≤ 8
  3. 如果 CI 环境中 `pool_timeout=30` 导致 flaky（CI 机器慢），可通过 conftest 在测试中覆盖为 60s

- **预期产出**：修改的 `database.py` + 新增 `broca/tests/test_pool_sizing.py`

- **验收标准**：
  - [ ] 5 个并发协程各执行 10 次 `save_message`（共 50 次写入），无 `PoolTimeout` 异常
  - [ ] 进程运行期间 `engine.pool.size()` 峰值 ≤ 8
  - [ ] 正常单 session 使用（1 个 Runner 进程）不出现连接池问题
  - [ ] `pytest broca/tests/test_pool_sizing.py -v` 通过

---

#### Task 1.7: MemoryStore 内存缓存

**依赖**：无（可并行）

- **目标**：避免每次 `write_memory` / `read_index` 都全文件读写
- **步骤**：
  1. 在 `broca/persistent_memory/store.py` 的 `MemoryStore` 中添加：
     ```python
     class MemoryStore:
         def __init__(self, memory_dir=None, freshness_warning_days=7):
             ...
             self._cache: list[MemoryIndexEntry] | None = None
             self._cache_mtime: float = 0.0

         def _cache_valid(self) -> bool:
             """检查缓存是否有效（mtime 未变）"""
             if self._cache is None:
                 return False
             if not self.index_path.exists():
                 return True  # 文件不存在，空缓存有效
             try:
                 current_mtime = self.index_path.stat().st_mtime
                 return current_mtime == self._cache_mtime
             except OSError:
                 return False

         def invalidate_cache(self) -> None:
             """显式使缓存失效（外部修改文件后调用）"""
             self._cache = None
             self._cache_mtime = 0.0

         def read_index(self) -> list[MemoryIndexEntry]:
             if self._cache_valid():
                 return self._cache
             # 缓存失效，重新加载
             ...  # 原有读文件 + 解析逻辑
             self._cache = entries
             self._cache_mtime = self.index_path.stat().st_mtime
             return entries

         def _write_index_file(self, entries: list[MemoryIndexEntry]) -> None:
             ...  # 原有写文件逻辑
             # 写入后更新缓存
             self._cache = entries
             self._cache_mtime = self.index_path.stat().st_mtime
     ```
  2. 在 `SubAgentMemoryManager._do_extract` 完成（成功/失败）后调用 `self._store.invalidate_cache()`
  3. 在 `write_memory` / `update_index` / `remove_index` 方法中，写入文件后更新 `self._cache` 和 `self._cache_mtime`
  4. 更新测试 `broca/tests/persistent_memory/test_store.py`：
     - 连续 10 次 `read_index()` 只触发 1 次文件读取（mock `Path.read_text`）
     - `write_memory` 后 `read_index` 立即反映
     - 外部 `write_text` 修改 MEMORY.md 后 `sleep(2)` 再 `read_index`，返回更新后内容（验证 mtime 失效）

- **预期产出**：修改的 `broca/persistent_memory/store.py` + 更新的测试

- **验收标准**：
  - [ ] 连续 10 次 `read_index()` 只产生 1 次文件读取（通过 mock `Path.read_text` 的 `call_count == 1` 验证）
  - [ ] `write_memory` 后 `read_index` 立即反映变更（缓存一致性）
  - [ ] 外部修改 MEMORY.md 并 `sleep(2)` 后，`read_index` 返回更新后的内容（验证 mtime 失效逻辑）
  - [ ] `SubAgentMemoryManager._do_extract` 完成后调用 `invalidate_cache()`，下次 `read_index` 重新加载
  - [ ] `pytest broca/tests/persistent_memory/ -v` 通过

---

#### Task 1.8: SkillStore 读写合并

**依赖**：无（可并行）

- **目标**：`record_use` / `record_view` 不重复全文件读取
- **步骤**：
  1. 在 `broca/skill/skill_store.py` 的 `SkillStore` 中添加：
     ```python
     class SkillStore:
         def __init__(self, skills_dir=None):
             ...
             self._cache: dict[str, dict] | None = None

         def _ensure_cache(self) -> dict[str, dict]:
             if self._cache is None:
                 self._cache = self._read_file_locked()
             return self._cache

         def _read_file_locked(self) -> dict[str, dict]:
             """加锁读文件，更新缓存"""
             self._ensure_store()
             with self._file_lock():
                 raw = self.store_path.read_text(encoding="utf-8")
                 data = json.loads(raw) if raw.strip() else {}
                 self._cache = data
                 return data

         def save(self, data: dict[str, dict]):
             """原子写 + 更新缓存"""
             self._ensure_store()
             with self._file_lock():
                 tmp = self.store_path.with_suffix(".json.tmp")
                 tmp.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")
                 tmp.replace(self.store_path)
             self._cache = data  # 更新缓存

         def invalidate_cache(self) -> None:
             """使缓存失效（跨进程更新后调用）"""
             self._cache = None
     ```
  2. 修改 `read()` 方法：优先从缓存返回（`return self._ensure_cache()`），仅在缓存为 None 时加锁读文件
  3. 修改 `record_use` / `record_view`：直接修改 `self._ensure_cache()` + 调用 `self.save(self._cache)`（1 次写，0 次额外读）
  4. 注意：跨进程场景下（2 个进程同时 `record_use`），文件锁仍保证原子性。但缓存可能过期——如果检测到 mtime 变化（类似 MemoryStore），应 `invalidate_cache()`
  5. 更新测试：
     - 连续 10 次 `record_use` 只产生 10 次文件写入 + 0 次额外文件读取
     - 跨进程：2 个进程各 `record_use` 5 次，最终 `use_count` 正确（文件锁保护）

- **预期产出**：修改的 `broca/skill/skill_store.py` + 更新的测试

- **验收标准**：
  - [ ] 连续 10 次 `record_use("skill_x")` 不产生额外的文件读取操作（通过 mock 验证 `read_text` 调用次数 ≤ 1）
  - [ ] 缓存命中时 `record_use` 不产生文件 I/O 读取操作（通过 mock `fcntl.flock` 验证读操作无调用）
  - [ ] 跨进程场景：2 个进程各 `record_use` 5 次，最终文件中 `use_count == 10`
  - [ ] `invalidate_cache()` 后下次 `read()` 重新从文件加载
  - [ ] 现有 skill 相关测试通过

---

### Phase 2: 组件化改进

**目标**：补齐缺失的 ABC，消除跨域紧耦合

**阶段验收标准**：
- [ ] 存在 `SchedulerABC`（`broca/components/scheduler.py`）且 `Scheduler` 实现它
- [ ] 存在 `RevertServiceABC`（`broca/components/revert_service.py`）且 `SessionRevertService` 实现它
- [ ] `GitManager` 的 `_instances` 字典访问是线程安全的
- [ ] 新 ABC 在 `broca/components/defaults.py` 中正确注册（`_DEFAULT_IMPLS`、`COMPONENT_SCOPES`、`ENTRY_POINT_NAMES`）
- [ ] 调用方通过 `ComponentRegistry` 获取依赖
- [ ] 全部通过：`pytest broca/tests/ -v`

---

#### Task 2.1: 新增 SchedulerABC

**依赖**：Phase 1 完成

- **目标**：为调度器定义 ABC，支持替换实现和测试 mock
- **步骤**：
  1. 新建 `broca/components/scheduler.py`：
     ```python
     """Scheduler ABC — interface for job scheduling and execution."""
     from abc import ABC, abstractmethod
     from typing import Any, Dict, List, Optional

     class SchedulerABC(ABC):
         @abstractmethod
         async def start(self) -> None: ...
         @abstractmethod
         async def shutdown(self) -> None: ...
         @abstractmethod
         async def add_job(self, session_id: str, name: str,
                          job_type: Any, trigger_type: str,
                          trigger_config: Dict[str, Any], content: str,
                          agent_id: Optional[str] = None,
                          notify: bool = False) -> str: ...
         @abstractmethod
         async def remove_job(self, job_id: str) -> bool: ...
         @abstractmethod
         async def pause_job(self, job_id: str) -> bool: ...
         @abstractmethod
         async def resume_job(self, job_id: str) -> bool: ...
         @abstractmethod
         async def list_jobs(self, session_id: str) -> List[Dict[str, Any]]: ...
         @abstractmethod
         async def get_job(self, job_id: str) -> Optional[Dict[str, Any]]: ...
         @abstractmethod
         async def execute_job_now(self, job_id: str) -> bool: ...
         @abstractmethod
         async def cancel_job_execution(self, job_id: str) -> bool: ...
         @abstractmethod
         async def cleanup(self) -> None: ...
     ```
  2. 修改 `broca/scheduler.py`：`class Scheduler(SchedulerABC):`
  3. 在 `broca/components/defaults.py` 中注册：
     ```python
     # 在 import 区添加
     from broca.components.scheduler import SchedulerABC
     
     # _DEFAULT_IMPLS 中添加
     SchedulerABC: "broca.scheduler:Scheduler",
     
     # COMPONENT_SCOPES 中添加
     SchedulerABC: "singleton",
     
     # ENTRY_POINT_NAMES 中添加
     "scheduler": SchedulerABC,
     ```
  4. 在 `broca/components/__init__.py` 中添加 `from broca.components.scheduler import SchedulerABC`
  5. 找到所有直接 `from broca.scheduler import Scheduler` 的调用方（如 `broca/tools/cron.py`、`broca/service_manager.py`），改为通过 `ComponentRegistry.get_instance().get(SchedulerABC)` 获取
  6. 确保 `Scheduler` 的单例模式与 registry 的 `singleton` scope 兼容（registry 缓存实例，不再每次 `Scheduler()` 创建新的）

- **预期产出**：
  - 新增 `broca/components/scheduler.py`
  - 修改 `broca/scheduler.py`（添加继承）
  - 修改 `broca/components/defaults.py`（3 处注册）
  - 修改 `broca/components/__init__.py`（导出）
  - 修改调用方

- **验收标准**：
  - [ ] `isinstance(Scheduler(), SchedulerABC)` 为 True
  - [ ] `ComponentRegistry.get_instance().get(SchedulerABC)` 返回 Scheduler 单例
  - [ ] 测试中可以用 `MockScheduler(SchedulerABC)` 替换（验证 `cron` tool 正常工作）
  - [ ] `pytest broca/tests/ -k "cron or scheduler or job" -v` 通过

---

#### Task 2.2: 新增 RevertServiceABC

**依赖**：Phase 1 完成（Task 1.3 重写了 undo/redo 逻辑）

- **目标**：为撤销/重做定义 ABC，解耦 Session 域和 Snapshot 域
- **步骤**：
  1. 新建 `broca/components/revert_service.py`：
     ```python
     """RevertService ABC — interface for undo/redo operations."""
     from abc import ABC, abstractmethod
     from typing import Any, Dict, Optional

     class RevertServiceABC(ABC):
         @abstractmethod
         async def undo(self, session_id: str, agent_id: str,
                        target_message_id: Optional[str] = None,
                        level: str = "step") -> Dict[str, Any]:
             """执行撤销操作。返回 {"success": bool, ...}"""
             ...

         @abstractmethod
         async def redo(self, session_id: str, agent_id: str) -> Dict[str, Any]:
             """执行重做操作。返回 {"success": bool, ...}"""
             ...

         @abstractmethod
         def can_undo(self, session_id: str) -> bool:
             """是否可以撤销（undo_stack 非空）"""
             ...

         @abstractmethod
         def can_redo(self, session_id: str) -> bool:
             """是否可以重做（有可恢复的 undo 记录）"""
             ...
     ```
  2. 修改 `broca/session/revert_service.py`：
     ```python
     from broca.components.revert_service import RevertServiceABC
     
     class SessionRevertService(RevertServiceABC):
         def can_undo(self, session_id: str) -> bool:
             """同步方法：检查 undo_stack 是否非空"""
             return len(self.undo_stack) > 0

         def can_redo(self, session_id: str) -> bool:
             """同步方法：当前实现中 redo 依赖 undo_stack 栈顶，
             因此 can_redo 等同于 can_undo（栈非空时可 redo 栈顶记录）"""
             return len(self.undo_stack) > 0
     ```
  3. 在 `broca/components/defaults.py` 中注册：
     ```python
     from broca.components.revert_service import RevertServiceABC
     
     # _DEFAULT_IMPLS
     RevertServiceABC: "broca.session.revert_service:SessionRevertService",
     
     # COMPONENT_SCOPES（per-agent：每个 agent 有独立的 undo 栈）
     RevertServiceABC: "per-agent",
     
     # ENTRY_POINT_NAMES
     "revert_service": RevertServiceABC,
     ```
  4. 在 `broca/components/__init__.py` 中导出
  5. 修改调用方（`/undo` 命令、`/redo` 命令）改为通过 registry 获取 `RevertServiceABC`
  6. `SessionRevertService` 内部的 Snapshot 依赖（`SnapshotTracker`/`PatchCalculator`/`SnapshotRestorer`）保持构造参数注入，测试时可传入 mock

- **预期产出**：
  - 新增 `broca/components/revert_service.py`
  - 修改 `broca/session/revert_service.py`（添加继承 + `can_undo`/`can_redo`）
  - 修改 `broca/components/defaults.py`（3 处注册）
  - 修改 `broca/components/__init__.py`（导出）
  - 修改命令调用方

- **验收标准**：
  - [ ] `isinstance(SessionRevertService(...), RevertServiceABC)` 为 True
  - [ ] `can_undo()` 在 `undo_stack` 非空时返回 True，空时返回 False
  - [ ] 测试中可 mock `RevertServiceABC` 而无需 mock 内部的 Snapshot 组件
  - [ ] `/undo` 和 `/redo` 命令通过 registry 获取 service 后正常工作
  - [ ] `pytest broca/tests/ -k "undo or redo or revert" -v` 通过

---

#### Task 2.3: GitManager 线程安全

**依赖**：Phase 1 完成

- **目标**：消除 `GitManager._instances` 类级字典的竞态风险
- **步骤**：
  1. 在 `broca/snapshot/git_manager.py` 的 `GitManager` 类中添加：
     ```python
     import threading
     
     class GitManager:
         _instances: dict[str, "GitManager"] = {}
         _class_lock = threading.Lock()  # 保护 _instances 字典的并发访问
     ```
  2. 修改 `__new__`：
     ```python
     def __new__(cls, workspace_path: str):
         normalized = str(Path(workspace_path).resolve())
         with cls._class_lock:
             if normalized not in cls._instances:
                 instance = super().__new__(cls)
                 instance._initialized = False
                 instance._instance_lock = threading.Lock()
                 cls._instances[normalized] = instance
         return cls._instances[normalized]
     ```
  3. 修改 `__init__` 使用实例锁防止并发初始化：
     ```python
     def __init__(self, workspace_path: str):
         if self._initialized:
             return
         with self._instance_lock:
             if self._initialized:  # double-check
                 return
             self._do_init(workspace_path)

     def _do_init(self, workspace_path: str):
         self._initialized = True
         self.workspace_path = Path(workspace_path).resolve()
         self.repo_path = self._get_repo_path()
         self.repo = None
         self._file_lock = None
     ```
  4. 更新测试：
     - 10 个协程 + 2 个线程混合并发 `GitManager("/same/path")`，全部返回同一对象
     - 不同路径返回不同实例
     - 初始化幂等：多次调用 `ensure_initialized()` 不重复创建 repo

- **预期产出**：修改的 `broca/snapshot/git_manager.py` + 新增测试

- **验收标准**：
  - [ ] 并发（10 协程 + 2 线程混合）创建 `GitManager("/same/path")`，全部返回同一对象（`all(x is first for x in results)`）
  - [ ] 不同 workspace 路径的 `GitManager` 实例独立（`git_a is not git_b`）
  - [ ] 初始化是幂等的：多次调用 `ensure_initialized()` 后 `repo` 只初始化一次
  - [ ] 现有 snapshot 相关测试通过（`pytest broca/tests/test_snapshot_hook.py broca/tests/test_snapshot_undo_redo.py -v`）

---

## 风险与应对

| 风险 | 影响 | 应对策略 |
|------|------|----------|
| `message_seq_counter` UPSERT 在旧 SQLite 版本不支持 | 数据库操作失败 | Python 3.12 自带 sqlite3 模块通常 ≥ 3.37，支持 `ON CONFLICT DO UPDATE ... RETURNING`。在 migration 中加 `PRAGMA user_version` 检查，不满足时 fallback 到 `SELECT FOR UPDATE` 模式 |
| 事务合并后 rollback 范围增大 | 如果 TURN_START 消息写入失败，turn 记录也回滚 | 这是**正确的行为**（turn 和 TURN_START 应该原子）。`get_multi_session` 已实现 `except BaseException: rollback` |
| `get_multi_session` 误用：`*_in_session` 方法在外部无 `get_multi_session` 上下文时调用 | 数据不会持久化（无 commit） | `*_in_session` 方法开头 `assert db_session.in_transaction()`，非事务上下文直接 `AssertionError` |
| 跨进程 sequence 冲突：Web 后端 + Runner 子进程同时 UPSERT 同一 counter 行 | 两个进程可能得到相同 sequence 值 | SQLite WAL 模式下 UPSERT 语句是原子的（单语句级别）。两个进程并发 UPSERT 同一行时，SQLite 内部串行化写操作，后到者看到前者的更新值。aiosqlite 的连接 `timeout=10s` 确保等待锁释放。验证：5 进程 × 10 次并发 UPSERT 无重复 |
| undo SQL 化后 pivot 查找逻辑与原版有细微差异 | 撤销结果不一致 | `find_pivot_message_id` 保留 fallback（找不到 TURN_START/STEP_START 时用 target 自身）；golden test 覆盖各种 edge case |
| MemoryStore 缓存与子 Agent 文件操作冲突 | 读到过期索引 | `SubAgentMemoryManager._do_extract` **完成后**（finally 块中）调用 `store.invalidate_cache()`，而非启动时 |
| SQLite pool 调小后多 Runner 并发写入时 PoolTimeout | Runner 启动失败 | `timeout=30s` 足够（WAL 模式写操作通常 < 10ms）；`test_pool_sizing.py` 验证 5 并发 × 10 次写入无超时 |
| Phase 2 的 ABC 注册影响现有集成测试 | 测试 break | 在 `ComponentRegistry` 中保持默认注册不变，仅当显式注入 mock 时才替换；现有通过 `Scheduler()` 直接获取的代码路径仍工作（registry 返回同一个单例） |

## 未解决的问题
- 无（所有决策已在 plan 中明确）
