> [← 返回 README](../README.md)

# Skill 系统与命令系统

## Skill 系统

**核心文件**: `broca/skill/skill_manager.py`, `broca/tools/skill.py`, `broca/skill/skill_store.py`, `broca/skill/skill_evolution.py`, `skills/`

Skill 是可复用的能力单元，以 Markdown 文件定义。系统提供一套完整的 Skill 创建、维护和进化能力。

### Skill 定义与加载

- **格式**: YAML frontmatter（名称、描述、版本、触发器）+ Markdown 正文（使用说明、步骤、注意事项）
- **加载路径**：用户级 `~/.agents/skills/`、`~/.broca/skills/`；工作区级 `{workspace}/skills/`、`.agents/skills/`（后者优先）
- **Workspace 覆盖**: 工作区技能可扩展全局技能
- **按需注入**: `load_skill` 工具可在运行时加载指定 Skill，内容注入到 Agent 上下文中（加载模式由 `skill_loading_mode` 控制）

### Skill 来源管理（SkillStore）

**核心文件**: `broca/skill/skill_store.py`

SkillStore 负责 Skill 的元数据管理和生命周期维护，**纯代码实现，不依赖 LLM**：

- **来源标记**: 区分 `builtin`（内置）和 `agent`（Agent 创建）两种来源
- **生命周期状态**: `active`（活跃）/ `archived`（已归档）
- **使用统计**: `use_count` / `view_count` 自动追踪
- **归档/恢复**: `archive_skill()` 将 Skill 目录移入 `.archive/`；`restore_skill()` 从 `.archive/` 恢复
- **来源隔离**: 归档/恢复操作只对 `agent` 来源的 Skill 生效，内置 Skill 受保护
- **并发安全**: 使用 `fcntl.flock` 文件锁保证 `.skill_store.json` 的并发读写安全

默认写入工作区 `{workspace}/.agents/skills/`（`~/.broca/skills/` 作为次级只读来源）：

```
{workspace}/.agents/skills/
├── my-skill/
│   └── SKILL.md              # 标准入口
├── .archive/                 # 归档目录（可恢复）
└── .skill_store.json         # 元数据：来源/状态/统计
```

### Skill 管理 Tool（SkillManage）

**核心文件**: `broca/tools/skill.py`

`skill_manage` 工具是 Agent 创建和维护 Skill 的接口，支持以下操作：

| 操作 | 说明 |
|------|------|
| `create` | 创建新 Skill：名称自动清洗为 slug，写入 SKILL.md，注册来源标记 |
| `patch` | 修改已有 Skill 的内容 |
| `delete` | 归档 Skill（移入 `.archive/`，而非真删除） |
| `write_file` | 在 Skill 的 `references/templates/scripts` 下写入辅助文件 |
| `remove_file` | 删除 Skill 下的辅助文件 |

**安全机制**：
- 名称清洗：只保留 `a-z0-9-` 字符
- 路径穿越防护：所有文件操作通过 `Path.resolve()` 校验，确保路径不逃逸 Skill 目录
- 来源检查：delete 操作只对 `agent` 来源的 Skill 生效

### 子 Agent Skill 进化模式

**核心文件**: `broca/skill/skill_evolution.py`

参考会话记忆压缩（`SessionMemoryCompressor`）与持久化记忆（`SubAgentMemoryManager`）的子 Agent 模式，Skill 的创建和改进建议通过独立子 Agent 执行：

```
run_skill_sub_agent(agent, prompt, allowed_tools)
  │
  ├─ AgentFactory → 创建/恢复子 Agent（ID: session_id + "#skill-evolution-agent"）
  ├─ Fork 主 Agent 的 context history
  ├─ 限制工具集（allowed_tools 参数）
  ├─ asyncio.wait_for 超时控制（默认 120s）
  └─ 错误处理与通知
```

**技能创建**（`/skill-create`）：子 Agent 分析当前会话，识别可复用的模式/流程，自动生成 SKILL.md
**改进建议**（`/skill-suggest`）：子 Agent 分析现有 Skill，输出改进文档到 `plans/` 目录，不直接修改 Skill

## 命令系统

**核心文件**: `broca/commands/`

命令系统提供了一种通过聊天的 `/` 触发快捷操作的方式，类似 Claude Code 的命令设计。

### 命令类型

| 类型 | 说明 | 示例 |
|------|------|------|
| **LocalCommand** | 在 Agent 进程内本地执行，不涉及 LLM 调用 | `/help`, `/abort`, `/undo`, `/redo` |
| **PromptCommand** | 构造提示词后调用 LLM 执行，可生成流式回复 | `/plan`, `/init`, `/debug`, `/review-code`, `/review-plan`, `/review-execution`, `/execute-plan` |

### 架构

```
命令输入 (/help)
     │
     ▼
parse_command_input() ── 解析 / 前缀
     │
     ▼
CommandRegistry ── 查找命令定义
     │
     ▼
dispatch_command()
     ├── LocalCommand  →  execute() 本地执行
     └── PromptCommand →  build_prompt() → agent.run() LLM 执行
```

- **CommandBase**: 所有命令的基类，定义 `name`、`description`、`type`、`is_hidden`、`is_enabled`、`show_result` 等元属性
- **CommandRegistry**: 命令注册中心，按名称注册/查找/列出命令
- **CommandLoader**: 自动扫描 `broca/commands/` 目录加载命令（每个命令一个子目录，含 `command.md` 和 `__init__.py`）
- **CommandManager**: 集成注册、加载、分发，挂载在 Agent 上

### 命令定义规范

每个命令定义在一个子目录中，包含两个文件：

**`command.md`** — YAML 头部 + Markdown 正文（PromptCommand 的提示词模板）：

```yaml
---
name: help
description: Show available commands
argument_hint: "[command_name]"
type: local
is_hidden: false
is_enabled: true
show_result: true
---
```

**`__init__.py`** — 命令实现类：

```python
from broca.commands.base import LocalCommand, CommandContext, CommandResult

class HelpCommand(LocalCommand):
    async def execute(self, args: str, ctx: CommandContext) -> CommandResult:
        ...
        return CommandResult(type="text", value="## Available Commands\n...")
```

### 可用命令

| 命令 | 类型 | 说明 |
|------|------|------|
| `/help` | local | 显示可用命令列表或某个命令的详细信息 |
| `/abort` | local | 中止当前 Agent 执行（隐藏，不显示在补全中） |
| `/undo` | local | 撤销上一步操作（隐藏） |
| `/redo` | local | 重做上一次撤销的操作（隐藏） |
| `/compact` | local | 手动触发上下文压缩（无需等待自动阈值） |
| `/clear-context` | local | 清除指定 Agent 的上下文并清理会话记忆 |
| `/clear-all-context` | local | 清除会话中所有 Agent 的上下文 |
| `/clear-history` | local | 清除会话中所有 Agent 的消息历史 |
| `/remember [hint]` | local | 手动触发持久化记忆提取，可带关注点提示 |
| `/plan` | prompt | 根据用户目标制定进化计划并形成文档，不执行 |
| `/init` | prompt | 初始化项目，扫描工作区并生成 `.agents/AGENTS.md` 概要 |
| `/debug` | prompt | 系统性 Bug 修复 — 复现、隔离、理解、修复、验证 |
| `/review-code` | prompt | 代码评审 — 检查 Bug、安全、代码异味、风格和最佳实践 |
| `/review-plan` | prompt | 执行前评审计划文档的完整性、可行性、AC 质量与稳健性 |
| `/review-execution` | prompt | 评审计划执行质量，对比计划文件与实际执行结果 |
| `/execute-plan` | prompt | 执行已制定的计划文件 |
| `/skill` | local | Skill 管理：`list` 列出所有 Skill / `view` 查看内容 / `archive` 归档 / `restore` 恢复 |
| `/skill-create` | local | 基于当前会话创建一个新的 Skill（通过子 Agent 分析会话并生成 SKILL.md） |
| `/skill-suggest` | local | 分析现有 Skill 并提出改进建议（输出到 `plans/`，不直接修改 Skill） |

### 前端集成

Web 前端和 VS Code 扩展均支持 `/` 命令补全：

- 输入 `/` 自动弹出命令建议列表
- 支持前缀匹配（`/pl` → `plan`）
- 通过 `↑↓` 导航、`Enter` 选择、`Esc` 关闭
- 每个命令项显示名称、描述和类型标签（local/prompt）
- 命令列表优先从后端 API `GET /api/commands` 获取，API 不可用时使用静态列表兜底

### 自定义命令

在工作区 `.broca/commands/` 目录下创建命令子目录即可自动加载：

```
your-project/
└── .broca/
    └── commands/
        └── deploy/
            ├── command.md
            └── __init__.py
```

自定义命令不会覆盖内置命令，且支持所有标准元属性配置。
