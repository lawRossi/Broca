# Agent Skill Evolution — Phase 1 & 2 Execution Report

## Overview

| Item | Content |
|------|---------|
| Plan File | `plans/agent-skill-evolution-plan.md` |
| Phases | Phase 1 (Skill Core) + Phase 2 (Agent Skill Operations) |
| Status | ✅ Pass |

## Plan Anchor Confirmation

- [x] Re-read the plan document section for both phases before starting
- [x] Acceptance criteria for each task confirmed
- [x] No deviation from plan — implementation strictly follows the simplified design

## Phase 1: Skill Core (纯代码)

### Task 1.1: SkillStore — `broca/tools/skill_store.py`

**Goal**: 实现 SkillStore 类，统一管理 Skill 元数据和归档/恢复。

**AC Verification**:

| # | Acceptance Criteria | Evidence |
|:-:|:--------------------|:---------|
| 1 | 可读写 `.skill_store.json`，并发锁生效 | `read()`/`save()` 通过 `fcntl.flock` 排他锁 + 原子写（tmp→rename）实现 |
| 2 | `archive_skill()` 移入 `.archive/` + 状态更新 | 测试验证：`shutil.move` 到 `.archive/`，`state` 变为 `archived` |
| 3 | `restore_skill()` 从 `.archive/` 恢复 + 状态更新 | 测试验证：`shutil.copytree` 恢复，`state` 回到 `active` |
| 4 | 对 builtin Skill 执行 archive/restore 时报错 | 测试验证：返回 `(False, "Skill 'X' is builtin, only agent-created...")` |
| 5 | `record_use()` / `record_view()` 正确递增 | 测试验证：`use_count` 从 5→6，时间戳同步更新 |

**Edge cases handled**:
- `.skill_store.json` 不存在时自动创建
- `.archive/` 目录不存在时自动创建
- 归档目标已存在 → 返回明确错误
- 并发锁文件异常时清理 (`lock_path.unlink(missing_ok=True)`)
- 名称清洗函数 `clean_skill_name()`：大小写转小写，特殊字符转 `-`，去重 `-`

### Task 1.2: `/skill` LocalCommand — `broca/commands/builtin/skill/`

**Goal**: 实现一个 `/skill` 命令，支持 list/view/archive/restore 子命令。

**AC Verification**:

| # | Acceptance Criteria | Evidence |
|:-:|:--------------------|:---------|
| 1 | `/skill list` 列出所有 Skill | 扫描 `~/.broca/skills/` +  `.archive/` 下含 SKILL.md 的目录，合并 store 元数据输出表格 |
| 2 | `/skill list archived` 只显示 archived | 传入 `filter_state` 参数，`[s for s in skills if s["state"] == state]` |
| 3 | `/skill view my-skill` 显示内容 + 元数据 | 读取 SKILL.md + store.get() 元数据，输出 metadata 块 + 全文 |
| 4 | `/skill archive my-skill` 归档 | 调 `SkillStore.archive_skill()` + `refresh_index()` |
| 5 | `/skill restore my-skill` 恢复 | 调 `SkillStore.restore_skill()` + `refresh_index()` |
| 6 | 对内置 Skill archive 时报错 | 复用 SkillStore 来源检查，返回错误信息 |

**命令注册验证**：通过 `load_commands_from_dir()` 扫描 `broca/commands/builtin/`，`/skill` 正确注册为 `type=local`，`/help` 中可见。

## Phase 2: Agent Skill 操作 (子 Agent 模式)

### Task 2.1: SkillManage Tool — `broca/tools/skill.py`

**Goal**: 新增 Agent 可调用的 Skill 管理工具。

**AC Verification**:

| # | Acceptance Criteria | Evidence |
|:-:|:--------------------|:---------|
| 1 | 子 Agent 可调用创建 Skill | `skill_manage(action="create", name=..., content=...)` 创建目录 + 写入 SKILL.md + store.ensure() + refresh_index() |
| 2 | 名称清洗、来源标记正确 | `clean_skill_name()` → slug；`ensure(slug, created_by="agent")` |
| 3 | 路径穿越防护有效 | `target.resolve().startswith(skill_dir.resolve())` 校验，测试验证 `../../escape.txt` 被拦截 |
| 4 | patch/delete/write_file 正常 | patch 更新文件内容；delete 归档；write_file 写入 references/ 下 |

**工具自动发现验证**：`ToolManager()` 启动时扫描 `broca/tools/`，`SkillManage` 类被自动注册为 `skill_manage` 工具（25 tools total）。

### Task 2.2: run_skill_sub_agent() + /skill-create

**Goal**: 实现子 Agent 工具函数和创建命令。

**AC Verification**:

| # | Acceptance Criteria | Evidence |
|:-:|:--------------------|:---------|
| 1 | `run_skill_sub_agent()` 正确创建子 Agent | 参考 `SessionMemoryManager._run_extraction_subagent()`：AgentFactory → create/restore → fork context → run(allowed_tools) |
| 2 | `/skill-create my-skill` 通过子 Agent 创建 | LocalCommand → build prompt → `run_skill_sub_agent()` → 子 Agent 调 `skill_manage` |
| 3 | 工具限制生效 | `allowed_tools` 参数传入 sub_agent.run()，只允许 `["skill_manage", "load_skill", "read_file", ...]` |
| 4 | 超时控制 (120s) | `asyncio.wait_for(task, timeout=task_timeout)` + TimeoutError 处理 |

**关键实现细节**：
- 子 Agent ID: `session_id + "#skill-evolution-agent"`
- 子 Agent 配置：`track_session_momory=False`, `save_history=False`, `interactive=False`
- 命令 `command.md` 通过 YAML frontmatter 声明 name/description/type，`__init__.py` 继承 LocalCommand

### Task 2.3: /skill-suggest

**Goal**: 实现改进建议命令，子 Agent 分析并输出文档。

**AC Verification**:

| # | Acceptance Criteria | Evidence |
|:-:|:--------------------|:---------|
| 1 | `/skill-suggest` 分析所有 Skill 输出文档到 `plans/` | 无参数时从 SkillStore 获取所有 active skill 列表，依次分析 |
| 2 | `/skill-suggest my-skill` 只分析指定 Skill | 传参时只查指定 skill（先查 store，再查目录） |
| 3 | 文档包含改进理由、方案、预期效果 | prompt 模板要求输出格式含 `当前问题` / `改进方案` / `预期效果` / `相关对话摘要` 四部分 |
| 4 | 子 Agent 不调用 skill_manage 修改 Skill | `allowed_tools` 只包含 read 类 + `write_file`（仅限 plans/ 路径），不含 `skill_manage`/`edit_file` |

**输出路径**：`plans/skill-suggest-{YYYY-MM-DD-HHMMSS}.md`

## Files Created / Modified

### New Files (6)

| File | Lines | Description |
|------|-------|-------------|
| `broca/tools/skill_store.py` | ~210 | SkillStore 核心类：元数据管理、归档/恢复、并发锁 |
| `broca/tools/skill_evolution.py` | ~100 | `run_skill_sub_agent()` 工具函数 |
| `broca/commands/builtin/skill/command.md` | 7 | `/skill` 命令元数据 |
| `broca/commands/builtin/skill/__init__.py` | ~180 | `/skill` 命令实现 (list/view/archive/restore) |
| `broca/commands/builtin/skill-create/command.md` | 7 | `/skill-create` 命令元数据 |
| `broca/commands/builtin/skill-create/__init__.py` | ~95 | `/skill-create` 命令实现 + CREATE_PROMPT_TEMPLATE |
| `broca/commands/builtin/skill-suggest/command.md` | 7 | `/skill-suggest` 命令元数据 |
| `broca/commands/builtin/skill-suggest/__init__.py` | ~100 | `/skill-suggest` 命令实现 + SUGGEST_PROMPT_TEMPLATE |

### Modified Files (2)

| File | Change |
|------|--------|
| `broca/tools/skill.py` | 新增 `SkillManage` 类（~200行），支持 create/patch/delete/write_file/remove_file |
| `broca/skill_manager.py` | 新增 `refresh_index()` 方法 + `_load_batch_skills()` 跳过 `.` 开头目录 |

## Deviations from Plan

- **无偏差**。实现严格遵循简化后的 2-Phase / 5-Task 方案。

## Quality Checklist

- [x] All phase-level ACs satisfied
- [x] All task-level ACs satisfied
- [x] No missing tasks (cross-referenced against plan)
- [x] No extra functionality (only what the plan asked for)
- [x] Manually verified key behaviors (archive/restore, source check, path traversal)
- [x] Code follows project conventions (Tool/ToolResult pattern, CommandBase pattern, Memory sub-agent pattern)
- [x] Compatible with existing work (SkillManager.refresh_index() backward-compatible)
- [x] All 7 files pass syntax check (`py_compile`)
- [x] All 3 commands register correctly in CommandRegistry
- [x] `skill_manage` + `load_skill` tools auto-discovered by ToolManager

## New Commands Summary

```
/skill list [state]        — 列出所有 Skill（可按 active/archived 过滤）
/skill view <name>         — 查看 Skill 内容 + 元数据
/skill archive <name>      — 归档 Skill（仅 agent-created）
/skill restore <name>      — 恢复已归档 Skill
/skill-create <name> [...] — 子 Agent 分析会话并自动创建 Skill
/skill-suggest [name]      — 子 Agent 分析并提出改进建议（输出到 plans/）
```
