# Broca — 轻量级 Agent 框架

<div align="center">

**一个可扩展的智能体框架，支持多UI实时交互**

</div>

### PC端web界面
![PC端Web界面](resource/web_snapshot.png)

### 移动端web界面

<div align="center">
  <img src="resource/phone_snapshot.jpeg" alt="移动端Web界面" width="50%"/>
<div>

### VS Code插件界面

![VS Code插件界面](resource/vscode_snapshot.png)

---

## 目录

- [概述](#概述)
- [核心架构](#核心架构)
- [技术栈](#技术栈)
- [模块详解](#模块详解)
  - [1. 核心 Agent 层](#1-核心-agent-层)
  - [2. 执行引擎](#2-执行引擎)
  - [3. 工具系统](#3-工具系统)
  - [4. 会话管理](#4-会话管理)
  - [5. 通信层](#5-通信层)
  - [6. Session Runner](#6-session-runner)
  - [7. 上下文与记忆](#7-上下文与记忆)
  - [8. 快照与撤销系统](#8-快照与撤销系统)
  - [9. 多智能体协作](#9-多智能体协作)
  - [10. Skill 系统](#10-skill-系统)
- [前端与客户端](#前端与客户端)
  - [Web 前端](#web-前端)
  - [Web 后端](#web-后端)
  - [VS Code 扩展](#vs-code-扩展)
- [配置](#配置)
- [快速开始](#快速开始)
- [项目结构](#项目结构)

---

## 概述

Broca 是一个用 Python 构建的轻量级 AI Agent 框架，核心设计理念是 **模块化** 和 **可扩展**。它支持：

- **多模型 LLM**：通过 litellm 统一接入多种 LLM 提供商（NVIDIA、DeepSeek、OpenRouter、智谱等）
- **实时通信**：基于 Socket.IO 实现浏览器/CLI/VS Code多端实时交互
- **子进程隔离**：每个会话在独立子进程中运行，支持心跳监控
- **快照与撤销**：基于Git的文件系统快照，实现操作级撤销/重做
- **上下文压缩**：智能管理长对话上下文，自动压缩过期内容
- **Skill插件系统**：通过 Markdown 文件定义可复用的技能
- **多客户端**：Web界面、CLI、VS Code 扩展

---

## 核心架构

```
┌─────────────────────────────────────────────────────────────┐
│                      Client Layer                            │
│  ┌──────────┐  ┌──────────┐  ┌────────────┐  ┌──────────┐  │
│  │  Web UI  │  │   CLI    │  │ VS Code    │  │  API     │  │
│  │ (Vue 3)  │  │(Textual) │  │ Extension  │  │ (REST)   │  │
│  └────┬─────┘  └────┬─────┘  └─────┬──────┘  └────┬─────┘  │
│       │              │              │              │         │
├───────┴──────────────┴──────────────┴──────────────┴────────┤
│                    Communication Layer                       │
│              ┌──────────────────────────┐                    │
│              │   Socket.IO Server        │                    │
│              │  (multi-endpoint, room)   │                    │
│              └────────────┬─────────────┘                    │
├───────────────────────────┴──────────────────────────────────┤
│                     Web Backend (FastAPI)                     │
│  ┌──────────────┐  ┌──────────────┐  ┌──────────────────┐   │
│  │ REST API     │  │ RunnerManager │  │ SocketIO Runtime │   │
│  │ (sessions,   │  │ (子进程管理)    │  │                  │   │
│  │  files, etc) │  │ 心跳监控/重启   │  │                  │   │
│  └──────────────┘  └──────┬───────┘  └──────────────────┘   │
├───────────────────────────┴──────────────────────────────────┤
│                     Session Runner (子进程)                    │
│  ┌──────────────────────────────────────────────────────┐    │
│  │ ┌─────────┐ ┌─────────┐ ┌─────────────────────────┐ │    │
│  │ │ Agent A │ │ Agent B │ │     IPC Client           │ │    │
│  │ │ (主Agent)│ │ (子Agent)│ │  (Unix Socket/Pipe)     │ │    │
│  │ └────┬────┘ └────┬────┘ └─────────────────────────┘ │    │
│  │      │            │                                   │    │
│  │ ┌────┴────────────┴────────────────────────────────┐  │    │
│  │ │              Execution Engine                      │  │    │
│  │ │  ┌────────┐  ┌──────────┐  ┌────────────────┐    │  │    │
│  │ │  │LLM Call│  │Tool Exec │  │Context Manager  │    │  │    │
│  │ │  └────────┘  └──────────┘  └────────────────┘    │  │    │
│  │ └───────────────────────────────────────────────────┘  │    │
│  └──────────────────────────────────────────────────────┘    │
├──────────────────────────────────────────────────────────────┤
│                       Data Layer                              │
│  ┌────────────────┐  ┌────────────────┐  ┌──────────────┐   │
│  │ SQLite/SQLModel │  │  Git Snapshots  │  │ Session      │   │
│  │ (sessions,      │  │  (workspace     │  │ Memory       │   │
│  │  messages,      │  │  版本追踪)      │  │ (long-term)  │   │
│  │  agents)        │  │                │  │              │   │
│  └────────────────┘  └────────────────┘  └──────────────┘   │
└──────────────────────────────────────────────────────────────┘
```

---

## 技术栈

### 后端核心

| 技术 | 用途 |
|------|------|
| Python | 主语言 |
| [litellm](https://github.com/BerriAI/litellm) | 统一 LLM API 接入 |
| [SQLModel](https://sqlmodel.tiangolo.com/) | ORM + 数据建模 |
| [aiosqlite](https://github.com/omnilib/aiosqlite) | 异步 SQLite |
| [python-socketio](https://python-socketio.readthedocs.io/) | 实时通信 |
| [aiohttp](https://docs.aiohttp.org/) | 异步 HTTP | ≥ 3.11.0 |
| [Jinja2](https://jinja.palletsprojects.com/) | 模板渲染 |
| [APScheduler](https://apscheduler.readthedocs.io/) | 任务调度 |
| [GitPython](https://gitpython.readthedocs.io/) | Git 操作 |
| [Playwright](https://playwright.dev/python/) | Web 抓取 |

### Web 后端

| 技术 | 用途 |
|------|------|
| [FastAPI](https://fastapi.tiangolo.com/) | REST API 框架 |
| [Uvicorn](https://www.uvicorn.org/) | ASGI 服务器 |
| [Supabase](https://supabase.com/) | 用户认证与文件上传 |
| [Alembic](https://alembic.sqlalchemy.org/) | 数据库迁移 |

### 前端

| 技术 | 用途 |
|------|------|
| [Vue 3](https://vuejs.org/) | 前端框架 (Composition API) |
| [TypeScript](https://www.typescriptlang.org/) | 类型安全 |
| [Vite](https://vitejs.dev/) | 构建工具 |
| [Pinia](https://pinia.vuejs.org/) | 状态管理 |
| [Tailwind CSS](https://tailwindcss.com/) | 样式 |
| [Socket.IO Client](https://socket.io/) | 实时通信 |

### VS Code 扩展

| 技术 | 用途 |
|------|------|
| TypeScript | 开发语言 |
| VS Code API | 扩展框架 |
| Socket.IO Client | 实时通信 |

---

## 模块详解

### 1. 核心 Agent 层

**核心文件**: `broca/agent.py`, `broca/agent_manager.py`, `broca/agent_configs.py`

Agent 是系统的核心执行单元，每个 Agent 包含：

- **LLM Client**: 统一封装对不同 LLM 提供商的调用（流式/非流式）
- **Tool 集合**: 可配置的工具列表，支持内置工具和自定义工具
- **Context**: 管理对话历史和 system prompt 的组装
- **Communicator**: 通过 Socket.IO 实现消息收发
- **Session Memory**: 长期记忆管理
- **Permission Manager**: 用户交互式权限管理
- **Revert Service**: 撤销/重做支持

Agent 有三种运行状态：`idle`、`running`、`disconnected`。每个 Agent 拥有独立的 LLM Client 实例和统计数据追踪（token 用量、调用次数等）。

**AgentFactory**（单例）负责：
- 从配置文件加载 Agent 配置（YAML + Markdown 格式）
- 创建/恢复/缓存 Agent 实例
- 管理会话内的 Agent 集合

### 2. 执行引擎

**核心文件**: `broca/execution_engine.py`

ExecutionEngine 是 Agent 的执行核心，管理完整的执行生命周期：

```
消息输入 → 设置执行上下文 → 循环执行步骤 → 返回执行结果
```

每个步骤（Step）包含：
1. **LLM 调用**（支持流式输出，含推理内容）
2. **结果保存**（持久化到数据库）
3. **工具调用**（可配置超时，支持并发工具执行）
4. **快照捕获**（step 开始/结束）
5. **死循环检测**（连续 3 步相同工具调用模式）
6. **上下文压缩**（过期工具结果清理 + Session Memory 截断）

执行状态枚举：`RUNNING`、`PENDING`、`COMPLETED`、`ERROR`、`ABORTED`、`SKIPPED`、`LIMIT_EXCEEDED`、`DEAD_LOOP`

### 3. 工具系统

**核心文件**: `broca/tools/tool_manager.py`, `broca/tools/tool.py`

**自动发现机制**：ToolManager（单例）启动时自动扫描 `broca/tools/` 目录下的所有 Tool 子类并注册。每类工具对应一个 Python 文件，继承自 `Tool` 基类。

**分类**：

| 类别 | 工具 |
|------|------|
| **只读工具** | `read_file`, `glob`, `grep`, `list_dir`, `tree_dir`, `web_fetch`, `web_search`, `ask_user`, `task_management`, `todo_management`, `cron` |
| **修改工具** | `edit_file`, `write_file` |

- 工具名必须唯一，内置工具与自定义工具不可重名
- 支持 MCP（Model Context Protocol）工具加载
- 支持工作区自定义工具（`{workspace}/.broca/tool.py`）
- 允许配置 Agent 可用的工具白名单

### 4. 会话管理

**核心文件**: `broca/session/`

会话（Session）是对话的基本单元，每个会话包含：

- **Session**: 会话元信息（描述、工作区、创建时间）
- **Turn**: 对话轮次（一次用户输入 + Agent 完整的回应过程）
- **Message**: 消息（USER / ASSISTANT / TOOL / SYSTEM / TURN_START / TURN_END）
- **Agent / AgentConfig**: Agent 实例及其配置持久化

**数据库**：基于 SQLModel + aiosqlite 的异步 SQLite 数据库，支持 Alembic 迁移。

**消息模型**支持：
- 序列号排序
- 截断标记（`is_truncated`，被 Session Memory 替代的历史消息）
- 过期标记（`is_expired`，上下文压缩清理的工具结果）
- Step 级快照关联

**RevertService** 提供 undo/redo 能力，基于 Git 快照比对实现文件级变更回滚。

### 5. 通信层

**核心文件**: `broca/comm/socketio_server.py`

SocketIOServer 是一个多端通信服务器，支持：

- **多种客户端类型**: browser、CLI、VSCode、browser_plugin
- **消息路由**: 支持直接发送、订阅广播、房间广播
- **事件系统**: 可注册自定义事件处理器（connect、disconnect、message 等）
- **线程安全**: 使用 asyncio.Lock 保护共享状态

通信消息包含完整的元信息：消息类型、角色、发送者/接收者、订阅频道、错误码等。

### 6. Session Runner

**核心文件**: `broca/session_runner/`

将每个会话隔离在独立子进程中运行，提供：

- **RunnerManager**（Web 进程中的单例）：管理子进程生命周期
  - 启动/停止/重启会话进程
  - 心跳监控（默认 15s 检查，45s 超时）
  - 数据库持久化与恢复（启东时恢复活跃会话）
  - 并发限制（默认最大 10 个并发）
  - 事件系统（session_started / session_stopped / session_crashed）

- **IPC 通信**: 基于 Unix Socket（Linux/macOS）或 Named Pipe（Windows）
  - 控制命令：execute、abort、shutdown、status、get_stats
  - 事件通知：ready、heartbeat、status_change、error、completed

- **Runner 子进程**: 加载会话 → 连接 Socket.IO → 启动 Agent 消息循环 → 定期心跳

### 7. 上下文与记忆

**核心文件**: `broca/context.py`, `broca/context_compressor.py`, `broca/session_memory/`

**Context** 负责：
- 组装 system prompt（角色定义、环境信息、Skills、配置文件、记忆、用户画像）
- 管理对话历史与数据库 message_id 的映射
- 支持从数据库重建历史（过滤被截断/过期的消息）
- 在 Abort 时自动截断最后一次含工具调用的 Assistant 消息

**会话上下文压缩** 包含两种策略：
- **策略A**: 清理过期的工具执行结果，替换为占位符
- **策略B**: 基于 Session Memory 截断早期对话，释放上下文窗口

**Session Memory** 实现长期记忆：
- 在上下文中注入历史摘要
- 每次 LLM 调用后自动检查并提取关键信息

### 8. 快照与撤销系统

**核心文件**: `broca/snapshot/`

基于 Git 实现文件系统快照：
- **SnapshotTracker**: 捕获工作区文件快照（Git 树哈希）
- **PatchCalculator**: 计算两个快照间的文件变更差异
- **GitManager**: 管理 Git 仓库（初始化、忽略规则同步）
- **Restore**: 基于快照恢复文件状态

每个 Agent Step 包含起始和结束两个快照，支持：
- 操作级撤销（回滚到指定消息前的状态）
- 操作级重做
- 变更摘要展示

### 9. 多智能体协作

**核心文件**: `broca/agent_crew.py`

AgentCrew 实现多 Agent 协作模式：
- **BlackBoard（黑板）**: 共享上下文
- **Crew Leader**: 负责协调和任务分发的 Agent
- **成员管理**: 动态添加/移除 Agent 成员
- **上下文注入**: 通过 Jinja2 模板为成员注入协作上下文

### 10. Skill 系统

**核心文件**: `broca/skill_manager.py`, `skills/`

Skill 是可复用的能力单元，以 Markdown 文件定义：
- **YAML 头部**: 技能名称、描述等元信息
- **Markdown 正文**: 技能详细规范（注入到 system prompt 中）
- **加载路径**: 全局 (`~/.agents/skills/`) 或项目内 (`skills/`, `.agents/skills/`)
- **Workspace 覆盖**: 工作区技能可扩展全局技能

---

## 前端与客户端

### Web 前端

`broca-web/frontend/` — Vue 3 + TypeScript 单页应用

- **页面**：Auth（登录）、Chat（对话）、Sessions（会话管理）、Files（文件浏览）、Jobs（任务）、Tasks（任务看板）
- **组件**：消息列表、输入框、Agent 侧边栏、权限对话框、文件预览等
- **状态管理**：Pinia stores（chat、session、agent、socket、task、user）
- **实时通信**：Socket.IO 客户端订阅 Agent 消息流
- **特性**：Markdown 渲染、代码高亮、文件拖拽上传、主题切换

### Web 后端

`broca-web/backend/` — FastAPI REST API 服务

- **API 路由**：sessions、agents、files、tasks、jobs、user
- **SocketIO Runtime**：集成 Broca SocketIO Server 运行时
- **认证**：Supabase JWT token 验证
- **Runner 集成**：管理 Session Runner 子进程

### VS Code 扩展

`broca-vscode/` — TypeScript 扩展

- 自定义 Chat Webview
- VS Code API 集成
- Socket.IO 实时通信
- 会话管理树视图

---

## 配置

### LLM 配置

`configs/llm_config.json` — 定义 LLM 提供商和模型：

```json
{
  "nvidia": {
    "base_url": "https://integrate.api.nvidia.com/v1",
    "api_key": "...",
    "qwen3.5": {
      "model": "openai/qwen/qwen3.5-397b-a17b",
      "temperature": 0.5,
      "modality": {"text": "", "image": {}, "video": {"fp": 2}}
    }
  }
}
```

### Agent 配置

`configs/agents/*.md` — YAML + Markdown 格式：

```yaml
---
name: Broca
role: main-agent
tools: ask_user,assign_task,edit_file,glob,grep,read_file,...
skills: all
---
## Role
...
```

### 运行配置

`configs/configs.json` — 数据库目录、日志等全局配置。

---

## 快速开始

### 安装

```bash
# 使用 poetry 安装
poetry install

# 或使用 pip
pip install -e .
```

### 启动

```bash
# 启动 Web 服务（前端 + 后端）
Broca web
```

### 环境要求

- Python ≥ 3.12
- pnpm（Web 前端）
- Node.js（VS Code 扩展）

---

## 项目结构

```
broca/
├── broca/                          # 核心 Python 包
│   ├── cli/                        # CLI 入口
│   │   └── main.py                 # 命令行解析与服务启动
│   ├── comm/                       # 通信层
│   │   ├── socketio_server.py      # Socket.IO 服务端
│   │   ├── socketio_client.py      # Socket.IO 客户端
│   │   └── agent_communicator.py   # Agent 通信接口
│   ├── session/                    # 会话管理
│   │   ├── database.py             # 数据库连接
│   │   ├── models.py               # 数据模型
│   │   ├── service.py              # CRUD 服务
│   │   ├── session_manager.py      # 会话管理器
│   │   ├── revert_service.py       # 撤销/重做服务
│   │   └── db_migration.py         # 数据库迁移
│   ├── session_memory/             # 长期记忆
│   │   ├── memory_manager.py       # 记忆管理器
│   │   └── memory_prompts.py       # 记忆提示词
│   ├── session_runner/             # 子进程 Runner
│   │   ├── manager.py              # 进程管理器
│   │   ├── runner.py               # 子进程入口
│   │   ├── ipc.py                  # 进程间通信
│   │   ├── models.py               # 数据结构
│   │   └── heartbeat.py            # 心跳监控
│   ├── snapshot/                   # 快照系统
│   │   ├── git_manager.py          # Git 操作
│   │   ├── track.py                # 快照捕获
│   │   ├── patch.py                # 变更计算
│   │   └── restore.py              # 文件恢复
│   ├── tools/                      # 工具系统
│   │   ├── tool.py                 # 工具基类
│   │   ├── tool_manager.py         # 工具管理器
│   │   ├── filesystem.py           # 文件操作工具
│   │   ├── web.py                  # 网络工具
│   │   ├── memory.py               # 记忆工具
│   │   ├── bash.py                 # 命令执行工具
│   │   ├── skill.py                # 技能加载工具
│   │   ├── task.py                 # 任务管理工具
│   │   ├── cron.py                 # 定时任务工具
│   │   └── ...                     # 其他工具
│   ├── agent.py                    # Agent 类
│   ├── agent_configs.py            # Agent 配置
│   ├── agent_crew.py               # 多 Agent 协作
│   ├── agent_manager.py            # Agent 工厂
│   ├── execution_engine.py         # 执行引擎
│   ├── context.py                  # 上下文管理
│   ├── context_compressor.py       # 上下文压缩
│   ├── llm.py                      # LLM 客户端
│   ├── skill_manager.py            # Skill 管理器
│   ├── scheduler.py                # 任务调度器
│   ├── permission_manager.py       # 权限管理
│   ├── error_handler.py            # 错误处理
│   └── configs.py                  # 全局配置
├── broca-web/                      # Web 应用
│   ├── backend/                    # FastAPI 后端
│   │   ├── app/
│   │   │   ├── api/                # REST API 路由
│   │   │   ├── core/               # 核心配置（SocketIO、DB）
│   │   │   ├── models/             # 数据模型
│   │   │   ├── schemas/            # Pydantic schema
│   │   │   ├── services/           # 业务服务
│   │   │   └── main.py             # 应用入口
│   │   ├── alembic/                # 数据库迁移
│   │   └── pyproject.toml
│   └── frontend/                   # Vue 3 前端
│       └── src/
│           ├── api/                # API 客户端
│           ├── components/         # UI 组件
│           ├── stores/             # Pinia 状态
│           ├── views/              # 页面视图
│           └── utils/              # 工具函数
├── broca-vscode/                   # VS Code 扩展
│   └── src/
│       ├── extension/              # 扩展主逻辑
│       └── webview/                # Chat Webview
├── configs/                        # 配置文件
│   ├── configs.json                # 全局配置
│   ├── llm_config.json             # LLM 配置
│   └── agents/                     # Agent 配置
├── skills/                         # 内置 Skills
├── alembic/                        # 数据库迁移
├── tests/                          # 测试
├── docs/                           # 文档
└── pyproject.toml                  # 项目元数据
```

---

## 设计模式

| 模式 | 使用场景 |
|------|---------|
| **单例 (Singleton)** | ToolManager、SkillManager、AgentFactory、RunnerManager、AsyncDatabaseManager |
| **观察者 (Observer)** | Socket.IO 事件系统、RunnerManager 事件 |
| **策略 (Strategy)** | 插件式工具系统、LLM 多提供商抽象 |
| **工厂 (Factory)** | AgentFactory 创建/恢复 Agent |
| **代理 (Proxy)** | IPC 子进程管理 |
| **黑板 (Blackboard)** | AgentCrew 多 Agent 协作 |
| **模板方法 (Template)** | 执行步骤生命周期 (capture → LLM → tool → compress) |

---
