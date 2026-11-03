# Session Memory 提取 & 上下文压缩逻辑优化

## 一、现状问题

1. **多 agent 记忆文件冲突**：所有 agent 共用一个 session memory 文件
   `workspace/.broca/<session_id>/session-memory.md`，多 agent 并发写入互相覆盖。
2. **提取与压缩时机割裂**：
   - 提取由 `SessionMemoryConfig`（消息条数 `minimum_messages_to_init` /
     `minimum_messages_between_update` / `steps_between_updates`）触发；
   - 压缩由 `ContextCompactConfig.session_trunc_threshold`（token 阈值）触发；
   - 两者相互独立，且压缩依赖提取时设置的 `last_message_index` 作为 pivot，
     耦合且滞后，容易把 context 撑爆。
3. **无“保留最近 N 步”机制**：压缩按“最后提取点”一刀切截断，
   会截掉正在进行的 turn 的近几步信息。

## 二、目标方案（已确认的设计决策）

- 每个 agent 独立记忆文件：
  `workspace/.broca/<session_id>/<agent_id>/session-memory.md`
- 触发阈值**复用** `compact_config.session_trunc_threshold`（及比例
  `session_trunc_percentage`），**删除** `SessionMemoryConfig`
- `compact_config` 新增 `keep_steps`（默认 5），用于“保留最近 N 个 step 不垮 turn”
- **删除 `track_session_memory`（`track_session_momory`）字段**；
  保留 `enable_context_compression` 作为统一“提取+压缩”流程的**唯一门控**
- **删除** `session_memory_manager.increment_step()` 及 step 计数机制
  （不再依赖 step/消息条数触发）

## 三、改动清单（按文件）

### 1. `broca/agent_configs.py`
- 删除 `SessionMemoryConfig`、`DEFAULT_SESSION_MEMORY_CONFIG`。
- 删除 `track_session_momory` 字段。
- 保留 `enable_context_compression`（作为统一提取+压缩的唯一门控）。
- `ContextCompactConfig` 增加字段：
  ```python
  keep_steps: int = 5  # 截断时保留的最近 step 数（当前 turn 未结束时）
  ```
- `AgentConfig`：
  - 删除 `self.track_session_momory = False`；
  - 删除 `self.session_memory_config = DEFAULT_SESSION_MEMORY_CONFIG`；
  - `from_config` 中删除 `session_memory_config` 分支；
  - `to_json` 中删除 `session_memory_config` 的序列化。

### 2. `broca/context.py`
- `Context.__init__` 增加可选 `agent_id` 参数并保存到 `self.agent_id`。
- `_load_session_memory()` 改为按 agent 读取：
  ```python
  Path(workspace) / ".broca" / (session_id or "") / (agent_id or "") / "session-memory.md"
  ```
  （`agent_id` 为空时回退到旧的 session 级路径，保证测试兼容。）

### 3. `broca/agent.py`
- `_setup_context`：`Context(self.config, self.session_manager, agent_id=self.agent_id, **kwargs)`。
- `_setup_session_memory`：创建条件由 `track_session_momory` 改为 `enable_context_compression`；
  构造函数 `SessionMemoryManager(..., config=self.config.compact_config)`。

### 4. `broca/session/session_manager.py`
- 新增 `mark_messages_before_as_truncated(agent_id, keep_from_message_id)`：
  将序列号（sequence_number）**小于** keep_from 消息的所有消息标记为
  `is_truncated=True`。支持“同 turn 内保留最近 N 步”。

### 5. `broca/session_memory/memory_manager.py`（核心重写）
- **路径改为 agent 级**：
  - `snapshot_memory_path = workspace/.broca/<session_id>/<agent_id>/session-memory_latest.md`
  - `memory_path = workspace/.broca/<session_id>/<agent_id>/session-memory.md`
- 删除基于 `SessionMemoryConfig` 的旧逻辑：
  `_should_extract`、`reset_last_message_index`、`increment_step`、
  `last_message_id`/`last_message_index` 对齐校验等。
- 构造函数 `config` 参数改为接收 `ContextCompactConfig`。
- 新增统一触发方法 `check_and_extract(context, engine=None)`：
  1. 若 `extraction_in_progress` → 返回；
  2. 计算有效 token 阈值（复用 `ContextCompressor._estimate_context_tokens` +
     `_get_effective_threshold`）；
  3. 若 context token 数 ≤ 阈值 → 返回；
  4. 计算保留边界 `keep_pivot`：保留当前（进行中）turn 内最近 `keep_steps`
     个 step，得到 `keep_from_message_id` 与对应 context 索引 `keep_index`；
  5. 用 `context.history[:keep_index]`（被压缩的旧消息）作为子代理上下文，
     执行记忆提取（写 snapshot 文件）；
  6. 提取成功 → 截断压缩：
     - `session_manager.mark_messages_before_as_truncated(agent_id, keep_from_message_id)`
     - `frosen_session_memory()`（snapshot → frozen）
     - `reset()`
     - `context.build_history_from_session(agent_id, rebuild_system_prompt=True)`
- 新增 `_compute_keep_pivot(context, keep_steps)`：通过 agent 的 DB 消息序列计算
  一个assistant message为一个step
  遇到user message即停止，**确保不垮 turn**。


### 6. `broca/context_compressor.py`
- `check_and_compress` 改为：force 或 token 超阈值时，通过
  `agent.session_memory_manager` 计算 keep_pivot；若 session memory 为空或无法
  计算 pivot 则跳过；否则执行截断（保留最近 N 步）。供手动 `/compact` 命令与
  既有测试使用。复用 manager 的 pivot 计算与截断方法，避免逻辑重复。

### 7. `broca/loop_engine.py`
- `_trigger_post_step_hooks`：移除独立的 `_check_context_compression` 调用
  与 `increment_step()`，改为当存在 `session_memory_manager` 时：
  ```python
  await self.session_memory_manager.check_and_extract(
      context=self.context, engine=self)
  ```
  （提取+压缩在 token 超阈值时一起完成。`session_memory_manager` 仅在
  `enable_context_compression=True` 时创建，因此该分支即为其门控。）
  保留持久化记忆提取逻辑不变。

### 7b. 清理 `track_session_momory` 引用
- `broca/session_memory/memory_manager.py` 子代理配置中删除
  `agent_config["track_session_momory"] = False`。
- `broca/persistent_memory/manager.py` 中删除
  `agent_config["track_session_momory"] = False`。
- `broca/skill/skill_evolution.py` 中删除
  `agent_config["track_session_momory"] = False`。

### 8. 各 `clear_*` 命令
- `clear_context` / `clear_history` / `clear_all_context` 已通过
  `session_memory_manager.snapshot_memory_path` / `memory_path` 访问，
  路径自动跟随 agent 级，逻辑无需改动（确认清理范围即可）。

### 9. 测试
- 更新 `broca/tests/test_context_compressor.py`（适配新 pivot 逻辑）。
- 新增/适配“保留最近 N 步、不垮 turn”边界逻辑的单元测试。
- 运行 `pytest broca/tests/` 相关用例验证。

## 四、关键行为约定

- **保留边界**：以当前（进行中）的 turn 为界，保留最近 `keep_steps` 个 step；
  若当前 turn 总 step ≤ keep_steps，则整个当前 turn 保留，只截断更早的 turn；
  **绝不跨 turn 截到上一轮**。
- **提取子代理**只看到被压缩的旧消息（`history[:keep_index]`），
  最新几步不写入记忆，避免丢信息。
- **记忆文件迁移**：旧的 session 级文件**不自动迁移**（属历史数据，保持原样）。

## 五、影响与风险

- 删除 `SessionMemoryConfig` 与 `track_session_momory` 会影响现有配置文件中
  `session_memory_config` 字段（`from_config` 会忽略未知 key，兼容）。
- 统一触发以 `enable_context_compression` 为唯一门控（同时创建
  `SessionMemoryManager`）；压缩作为提取成功后的必然步骤。
- 子代理（session-memory-agent）自身 `enable_context_compression=False`，
  不会递归触发提取/压缩。
