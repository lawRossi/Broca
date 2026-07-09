# Agent 自主创建与维护 Skill 方案

## 概述

- **目标**：基于 `skill_evo.md`，参考 Memory 管理的子 Agent 运行模式，实现 Agent 自主创建和维护 Skill。
- **背景**：Broca 已具备 SkillManager + load_skill + 命令系统 + Memory 子 Agent 模式。需在此基础上实现：
  1. Agent 自主创建 Skill（子 Agent 分析会话 → 生成 SKILL.md）
  2. Skill 维护（纯代码：来源标记、归档/恢复、使用统计）
  3. Agent 提出改进建议（子 Agent 分析 → 输出 md 文档，不修改 Skill）
- **约束条件**：
  - **命令触发**：所有操作通过命令，不自动
  - **维护纯代码**：来源标记、归档/恢复、统计不依赖 LLM
  - **含 LLM 操作通过子 Agent**：skill-create / skill-suggest 用子 Agent 执行
  - **建议文档化**：输出 `plans/` 下的 md，不直接改 Skill
  - **来源隔离**：归档/恢复只对 agent-created 生效

## 相关材料

- `skill_evo.md` — 顶层方案参考
- `broca/skill_manager.py` — Skill 加载/解析
- `broca/tools/skill.py` — LoadSkill 工具
- `broca/session_memory/memory_manager.py` — `_run_extraction_subagent()` 子 Agent 模式参考
- `broca/persistent_memory/manager.py` — 同上
- `broca/commands/` — 命令系统（base/loader/dispatcher）
- `broca/agent.py` / `broca/agent_manager.py` / `broca/agent_configs.py` — Agent 框架

## 总体方案

### 架构

```
命令层 ─────────────────────────────────────────────────
  /skill list|view|archive|restore  ← 纯代码, LocalCommand
  /skill-create <name>              ← LocalCommand → 子 Agent
  /skill-suggest [name]             ← LocalCommand → 子 Agent

服务层 ─────────────────────────────────────────────────
  SkillStore (纯代码)
    ├─ .skill_store.json: 来源标记 + 状态 + 使用计数
    ├─ archive_skill / restore_skill (shutil.move/copytree)
    └─ 来源检查: 只操作 agent-created

  SkillManage Tool
    └─ action: create/patch/delete/write_file/remove_file

  run_skill_sub_agent()  ← 工具函数, 非类
    └─ AgentFactory → fork context → run(allowed_tools) → 超时/错误
```

### Skill 目录结构

```
~/.broca/skills/
├── my-skill/
│   └── SKILL.md
├── .archive/
│   └── old-skill/
└── .skill_store.json    # 来源+状态+统计, 取代 .usage.json
```

### 关键设计

1. **SkillStore**：一个类管理所有 Skill 元数据
   - JSON 文件 `~/.broca/skills/.skill_store.json`
   - 结构：`{ "name": {"created_by": "agent", "state": "active", "use_count": 0, ...} }`
   - **无自动生命周期转换**，archive/restore 由命令手动触发
   - 并发文件锁（fcntl.flock）

2. **`/skill` 命令**：一个 LocalCommand + 子命令
   - `list` — 列出所有 Skill
   - `view <name>` — 查看 Skill + 元数据
   - `archive <name>` — 归档（仅 agent-created）
   - `restore <name>` — 恢复

3. **`run_skill_sub_agent()`**：工具函数，非类
   - 入参：agent, prompt, allowed_tools
   - 流程：AgentFactory → fork context → run → 超时 → 通知
   - `/skill-create` 和 `/skill-suggest` 命令直接调用

## 执行计划

### Phase 1: Skill Core（纯代码）

**目标**：SkillStore 数据管理 + `/skill` 命令。

**验收标准**：
- [ ] SkillStore 支持来源标记、状态、使用计数、归档/恢复
- [ ] 归档/恢复只对 agent-created 生效
- [ ] `/skill list/view/archive/restore` 全部可用

#### Task 1.1: SkillStore

- **目标**：实现 SkillStore 类，统一管理 Skill 元数据和归档/恢复。
- **步骤**：
  1. 创建 `broca/tools/skill_store.py`
  2. 数据模型（`.skill_store.json`）：
     ```json
     {
       "my-skill": {
         "created_by": "agent",     // builtin | agent
         "state": "active",         // active | archived
         "pinned": false,
         "use_count": 0,
         "view_count": 0,
         "created_at": "2026-01-15T10:00:00",
         "last_used_at": null
       }
     }
     ```
  3. 方法：
     - `read() / save()` — 读写 JSON，fcntl.flock 并发锁
     - `get(name)` / `update(name, **fields)` — 获取/更新单条
     - `ensure(name, created_by)` — 首次创建时写入
     - `record_use(name)` / `record_view(name)` — 便捷递增
     - `archive_skill(name)` — `shutil.move` 到 `.archive/`，state→archived
     - `restore_skill(name)` — `shutil.copytree` 恢复，state→active
     - `agent_created()` — 返回所有 agent-created 的 Skill 列表
  4. 来源检查：archive/restore 只对 `created_by == "agent"` 执行
  5. 错误处理：归档目标冲突、Skill 不存在等
- **预期产出**：`broca/tools/skill_store.py`
- **验收标准**：
  - [ ] 可读写 `.skill_store.json`，并发锁生效
  - [ ] `archive_skill()` 移入 `.archive/` + 状态更新
  - [ ] `restore_skill()` 从 `.archive/` 恢复 + 状态更新
  - [ ] 对 builtin Skill 执行 archive/restore 时报错
  - [ ] `record_use()` / `record_view()` 正确递增

#### Task 1.2: `/skill` LocalCommand

- **目标**：实现一个 `/skill` 命令，支持 list/view/archive/restore 子命令。
- **步骤**：
  1. 创建 `broca/commands/builtin/skill/` 目录（command.md + `__init__.py`）
  2. `command.md`：
     ```yaml
     name: skill
     description: Skill 管理：list/view/archive/restore
     short_description: 管理 Skill
     argument_hint: "list|view|archive|restore [...]"
     type: local
     show_result: true
     ```
  3. `__init__.py` 解析第一个参数为子命令：
     - `list` — 列出所有 Skill（名称/状态/来源/使用次数），支持 `list [state]` 过滤
     - `view <name>` — 显示 SKILL.md 内容 + 元数据（状态/来源/统计）
     - `archive <name>` — 调用 SkillStore.archive_skill()，仅 agent-created
     - `restore <name>` — 调用 SkillStore.restore_skill()
     - 未知子命令 → 显示用法
  4. 导入 SkillStore 获取数据
- **预期产出**：`broca/commands/builtin/skill/`
- **验收标准**：
  - [ ] `/skill list` 列出所有 Skill
  - [ ] `/skill list archived` 只显示 archived
  - [ ] `/skill view my-skill` 显示内容 + 元数据
  - [ ] `/skill archive my-skill` 归档
  - [ ] `/skill restore my-skill` 恢复
  - [ ] 对内置 Skill archive 时报错

### Phase 2: Agent Skill 操作（子 Agent 模式）

**目标**：SkillManage Tool + `run_skill_sub_agent()` 工具函数 + `/skill-create` / `/skill-suggest`。

**验收标准**：
- [ ] `skill_manage(action="create")` 可创建 Skill
- [ ] `run_skill_sub_agent()` 正确创建子 Agent 并执行
- [ ] `/skill-create` 通过子 Agent 创建 Skill
- [ ] `/skill-suggest` 输出改进文档到 `plans/`

#### Task 2.1: SkillManage Tool

- **目标**：新增 Agent 可调用的 Skill 管理工具。
- **步骤**：
  1. 在 `broca/tools/skill.py` 中新增 `SkillManage` 类
  2. 参数：`action` (create/patch/delete/write_file/remove_file) + `name` + 其他
  3. `create` — 名称清洗 slug → 创建目录 → 写入 SKILL.md → SkillStore.ensure()
  4. `patch` — 读取 → 替换/追加 → 写回 → record_patch()
  5. `delete` — 检查来源 → SkillStore.archive_skill()（不真删）
  6. `write_file` / `remove_file` — 操作 references/templates/scripts，防路径穿越
- **预期产出**：更新 `broca/tools/skill.py`
- **验收标准**：
  - [ ] 子 Agent 可调用创建 Skill
  - [ ] 名称清洗、来源标记正确
  - [ ] 路径穿越防护有效

#### Task 2.2: run_skill_sub_agent() + /skill-create

- **目标**：实现子 Agent 工具函数和创建命令。
- **步骤**：
  1. 在 `broca/tools/skill_evolution.py` 中实现 `run_skill_sub_agent(agent, prompt, allowed_tools)`：
     ```python
     async def run_skill_sub_agent(agent, prompt, allowed_tools, task_timeout=120):
         """参考 SessionMemoryManager._run_extraction_subagent()"""
         agent_factory = AgentFactory()
         agent_id = agent.session_id + "#skill-evolution-agent"
         session_manager = agent.session_manager

         # 创建或恢复子 Agent
         config = await session_manager.get_agent_config(agent_id)
         if config is None:
             config = agent.config.to_dict()
             config["name"] = "skill-evolution-agent"
             config["track_session_momory"] = False
             config["enable_context_compression"] = False
             config["save_history"] = False
             config["interactive"] = False
             sub_agent = await agent_factory.create_agent(config, session_manager, agent_id=agent_id)
         else:
             sub_agent = agent_factory.get_agent(session_manager.session_id, ...)
             if not sub_agent:
                 sub_agent = await agent_factory.restore_agent(agent_id, session_manager)

         # Fork 上下文
         sub_agent.context.history = copy.copy(agent.context.history)

         # 运行
         trigger_msg = MessageProtocol.create_user_message(content=prompt)
         result = await sub_agent.run(trigger_msg, from_agent=True, allowed_tools=allowed_tools)
         return result
     ```
  2. 创建 `broca/commands/builtin/skill-create/`（command.md + `__init__.py`）
     - 解析参数 `<name> [description]`
     - 构建 prompt：引导子 Agent 分析会话 → 使用 skill_manage create 创建
     - 调 `run_skill_sub_agent()` + 限定工具 `["skill_manage", "load_skill", "read_file", "glob", "grep", "list_dir", "tree_dir"]`
     - 返回结果
- **预期产出**：`broca/tools/skill_evolution.py` + `broca/commands/builtin/skill-create/`
- **验收标准**：
  - [ ] `run_skill_sub_agent()` 正确创建子 Agent 并 fork 上下文
  - [ ] `/skill-create my-skill` 通过子 Agent 创建 Skill
  - [ ] 工具限制生效（子 Agent 只能调用列出的工具）
  - [ ] 超时控制（120s）工作

#### Task 2.3: /skill-suggest

- **目标**：实现改进建议命令，子 Agent 分析并输出文档。
- **步骤**：
  1. 创建 `broca/commands/builtin/skill-suggest/`（command.md + `__init__.py`）
  2. 解析参数 `[skill-name]`
  3. 构建 prompt：分析目标 Skill（或所有）→ 发现改进点 → 用 write_file 写 `plans/skill-suggest-{timestamp}.md`
  4. 调 `run_skill_sub_agent()` + 限定工具 `["load_skill", "read_file", "glob", "grep", "list_dir", "tree_dir", "write_file"]`
  5. 约束：只写 plans/ 目录，不修改 Skill 文件
- **预期产出**：`broca/commands/builtin/skill-suggest/`
- **验收标准**：
  - [ ] `/skill-suggest` 分析所有 Skill 输出文档到 `plans/`
  - [ ] `/skill-suggest my-skill` 只分析指定 Skill
  - [ ] 文档包含改进理由、方案、预期效果
  - [ ] 子 Agent 不调用 skill_manage 修改 Skill

## 风险与应对

| 风险 | 应对 |
|------|------|
| `.skill_store.json` 并发写 | fcntl.flock 文件锁 |
| 归档误操作 | 永不删除只归档，可恢复 |
| 路径穿越 | 路径校验，限制在 Skill 目录内 |
| 子 Agent 超时 | 120s 超时 + 通知用户 |

## 未解决的问题

- (无)
