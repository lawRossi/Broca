# Broca 系统组件化 / 插件化升级改造计划

## 概述

- **目标**：将 Broca Agent 框架的主要逻辑模块提取为可插拔组件（Plugin），现有实现作为默认实现，支持通过 Python entry points 或配置文件轻松替换为第三方插件
- **背景**：当前系统各模块间耦合严重——`Agent.create()` 是单一组合根，`LoopEngine` 硬编码了工具执行管道（权限/超时/广播/白名单混在一起），`SessionMemoryManager` 与 `ContextCompressor` 逻辑割裂，`Agent` 与 `LoopEngine` 存在**运行期双向引用**（`LoopEngine` 持有 `agent`、`agent` 持有 `execution_engine`；注意这**不是导入环**——`loop_engine.py` 并不 import `broca.agent`，只有 `agent.py:16` 单向 import），各组件均为具体类无抽象接口
- **约束条件**：
  - 所有现有功能必须保持不变（行为等价重构）
  - 现有测试必须全部通过
  - 插件机制不能增加正常启动时的性能开销（懒加载）
  - 第三方插件只需 `pip install` + entry point 声明即可生效
  - **每个组件必须声明作用域**（`singleton` / `per-agent` / `per-session` / `transient`），有状态组件禁止跨 Agent 复用
  - **行为等价重构前必须先写 characterization test 锁定现状**（尤其工具执行管道），不允许"先改再补测试"

## 相关材料

- 现有代码结构：`broca/` 包（核心框架）、`broca-web/backend/`（Web 服务）、`broca-tui/`（终端 UI）
- 现有抽象模式参考：`Tool` 基类（模板方法）、`Orchestrator` ABC（工厂模式）、`CommandManager`（注册表+调度器）
- 已有优化计划参考：`plans/session-memory-extraction-compression-optimization.md`（SessionMemory 合入 ContextCompressor 的详细设计）
  - ⚠️ **该文件在当前 worktree（`refactor`）中不存在，仅在主 worktree 有**；若执行时不可用，以本计划 Task 3.1 的方法清单为准，不要阻塞
- 参考插件架构：Python `importlib.metadata.entry_points()` 标准插件发现机制
- 评审报告：`plans/reports/review/component-plugin-architecture-plan-review.md`（本计划据此修订）
- 实测基线（2026-10-31，`refactor` worktree）：
  - `pytest broca/tests/ --collect-only -q` → **522 tests**
  - `pytest-cov 7.1.0` 已安装；`broca/tests/conftest.py` 当前不存在
  - `broca/components/` 当前不存在；`broca/tools/executor.py` 当前不存在
  - `broca` 已以 editable 方式安装在 `venv` 中（`pip show broca` → 0.1.0）

## 总体方案

### 架构设计

```
┌─────────────────────────────────────────────────────────────────┐
│                        Agent (组合根)                            │
│  Agent.create() 通过 ComponentRegistry 解析所有组件实现           │
└────┬──────────┬──────────┬──────────┬──────────┬────────────────┘
     │          │          │          │          │
     ▼          ▼          ▼          ▼          ▼
┌────────┐ ┌──────────┐ ┌────────┐ ┌──────────┐ ┌──────────┐
│LoopEngine│ │LLMClient │ │Context │ │ToolExecu-│ │Permission│
│(执行引擎)│ │(LLM调用) │ │Compres-│ │tor(工具) │ │Provider  │
│         │ │          │ │sor(压缩)│ │          │ │(权限)    │
└────────┘ └──────────┘ └────────┘ └──────────┘ └──────────┘
     │                              │
     ▼                              ▼
  各组件通过 ABC 接口解耦，ComponentRegistry 负责实例化
```

### 核心设计模式

1. **组件接口层** (`broca/components/`)：每个组件定义一个 ABC 接口
2. **ComponentRegistry**：统一的插件发现、解析、实例化机制
   - 自动发现：`importlib.metadata.entry_points(group="broca.components")`
   - 配置覆盖：`{workspace}/.broca/components.json` 或 `~/.broca/components.json`
   - 默认回退：未指定时使用 `broca/components/defaults.py` 中的映射
3. **依赖注入 + 显式生命周期**：
   - `ComponentRegistry.get()` **只负责构造**，不注入运行期依赖；
   - 需要 agent / 会话上下文的组件统一实现 `BaseComponent.initialize(**deps)`，由组合根（`Agent.create()`）按拓扑顺序 `await` 调用；
   - `initialize()` 必须幂等（重复调用不产生副作用），`shutdown()` 可选，仅 `Communicator` / `SessionRunner` / `ProcessManager` 需要
4. **窄接口协议**：组件间通过 Protocol 类型传递，而非传递整个 Agent 对象。
   - **唯一例外**：`ToolCallContext.agent` 继续传真实 `Agent` —— `task` / `blackboard` / `cron` / `bash` / `image` / `agent_interaction` 等工具依赖 `context.agent.name`、`context.agent.agent_id`、`context.agent.config`（已核实代码，见风险表）；强行窄化会让工具层失效
5. **组件作用域**：Registry 必须区分实例作用域，禁止"以接口类型为唯一 key 做单例缓存"——`Communicator`、`LoopEngine`、`ContextCompressor`、`MemoryManager`、`PermissionProvider`、`ToolExecutor` 都是 per-agent 实例，多 Agent / `assign_task` 子 Agent / 会话恢复场景下共用会直接串台
6. **组件分级**：23 个组件按插件价值分三级，避免"为抽象而抽象"——**核心 7 个**（必做）、**支撑 11 个**（按需，Phase 5 批量）、**基础设施 5 个**（可选，允许延后到下个迭代）

### 组件作用域与生命周期契约

> 本表是 Phase 1 的**交付物之一**（代码中的 `COMPONENT_SCOPES` 映射必须与本表一致，并有测试断言）。

**核心组件的构造 / initialize 契约**：

| 组件 | 构造参数 | `initialize()` 参数 | `shutdown()` | 备注 |
|------|---------|--------------------|:------------:|------|
| `LLMClient` | 无 | 无 | 否 | 无状态 |
| `ToolExecutor` | 无 | `tool_mapping`, `permission_provider`, `config`, `communicator` | 否 | 持 `tool_mapping` + 广播用 `communicator`，**必须 per-agent**；`allowed_tools` 不走 initialize（per-run 逐次传参） |
| `ContextCompressor` | 无 | `agent_ref`, `session_manager`, `config` | 否 | session memory 路径由 workspace 推导 |
| `PermissionProvider` | 无 | `communicator`, `session_manager`, `config` | 否 | 持待响应请求表，per-agent |
| `Communicator` | 无 | `agent_id`, `session_id`, `config` | 是 | 持 socket 连接，per-agent |
| `LoopEngine` | 无 | `agent_ref`, `llm_client`, `context`, `tool_executor`, `context_compressor`, `memory_manager`, `communicator`, `session_manager`, `config`, `tool_mapping`, `tool_permission_provider` | 否 | 持 `abort_event`/`turn_id`，**必须 per-agent** |
| `AgentFactory` | 无 | `registry` | 否 | 无状态，singleton |

**通用规则**：

1. `ComponentRegistry.get(interface, scope_key=None, **kwargs)`：
   - `singleton` → 缓存 key = `(interface, None)`
   - `per-agent` / `per-session` → 缓存 key = `(interface, scope_key)`；**`scope_key` 缺失时抛 `ComponentScopeError`**（不静默退化成 singleton）
   - `transient` → 每次新建，不缓存
   - `**kwargs` 只在**首次构造**时生效；缓存命中时传入 kwargs 记 `debug` 日志（避免"以为改了参数其实没生效"）
2. 组件的运行期依赖（agent、session、communicator）一律走 `initialize()`，不放进构造参数——这样 Registry 才能统一 `impl_cls()` 构造
3. 组合根内部允许传整个 `Agent`（`CommandSystem.initialize(agent)`）；**组件之间不允许**，只能传 Protocol
4. `ComponentRegistry.reset()` 清空所有缓存（含 per-agent 分表），供测试隔离
5. **`shutdown()` 调用约定**：由 `Agent.disconnect()` 按**逆拓扑序**调用（`loop_engine` → `tool_executor` → `context_compressor` → `memory_manager` → `permission_provider` → `communicator`），且只调用声明了 `shutdown()` 的组件（当前为 `Communicator` / `SessionRunner` / `ProcessManager`）
6. **per-agent 实例释放**：`ComponentRegistry.release(scope_key)` 释放该 agent 名下的全部 per-agent / per-session 实例（web 侧按会话反复创建 Agent，长期运行会累积实例）；`Agent.disconnect()` 负责调用；`reset()` 仅作测试兜底

### 23 个组件清单

**分级**：🔴 核心（Phase 1 定接口，必做）｜🟡 支撑（Phase 5 批量，按需）｜⚪ 基础设施（可选，允许延后）
**状态**：✅ 现有类可直接接口化｜🔧 现有类需改名/合并/去单例｜🆕 当前无对应类，需从零抽象

| # | 组件接口 | 默认实现 | 分级 | 作用域 | 现状 | 说明 |
|---|---------|---------|:----:|--------|:----:|------|
| 1 | `ToolExecutor` | `DefaultToolExecutor` | 🔴 | per-agent | 🆕 | 工具执行管道（新建 `broca/tools/executor.py`） |
| 2 | `ContextCompressor` | `SessionMemoryCompressor` | 🔴 | per-agent | 🔧 | 上下文压缩（含 SessionMemory；现为具体类，需拆 ABC + 实现） |
| 3 | `LLMClient` | `LiteLLMClient` | 🔴 | singleton | 🔧 | LLM 调用抽象（现类名 `LLMClient`，需改名并保留别名） |
| 4 | `PermissionProvider` | `DefaultPermissionProvider` | 🔴 | per-agent | 🆕 | 合并 `PermissionManager` + `ToolPermissionManager` |
| 5 | `Communicator` | `SocketIOCommunicator` | 🔴 | per-agent | 🔧 | 现 `AgentCommunicator(SocketIOClient)`，需改名 |
| 6 | `Orchestrator` | 已有 ABC | 🟡 | singleton | ✅ | 多智能体编排（已有 ABC，仅需纳入 `defaults.py` 映射） |
| 7 | `MemoryManager` | `SubAgentMemoryManager` | 🟡 | per-agent | 🔧 | 现 `PersistentMemoryManager(agent=..., workspace=...)`，需改名 + 去 agent 构造依赖 |
| 8 | `SnapshotManager` | `GitSnapshotManager` | 🟡 | per-agent | 🔧 | 合并 `SnapshotTracker` + `PatchCalculator`（+ `GitManager`） |
| 9 | `AgentFactory` | `DefaultAgentFactory` | 🔴 | singleton | 🔧 | 现 `AgentFactory`，需去单例 |
| 10 | `SessionManager` | `SQLSessionManager` | 🟡 | per-session | ✅ | 会话/消息持久化（现类名 `SessionManager`） |
| 11 | `SkillManager` | `FileSkillManager` | 🟡 | singleton | ✅ | Skill 加载 |
| 12 | `ProcessManager` | `LocalProcessManager` | 🟡 | singleton | ✅ | 后台进程管理 |
| 13 | `LoopEngine` | `DefaultLoopEngine` | 🔴 | per-agent | 🔧 | 执行引擎（现为具体类，需拆 ABC + 实现） |
| 14 | `ContentSecurityScanner` | `RegexContentScanner` | ⚪ | singleton | 🆕 | 现仅 `broca/utils/content_security.py:scan_content_security()` 函数，需包成类 |
| 15 | `SessionRunner` | `IPCSessionRunner` | 🟡 | singleton | 🔧 | 现 `session_runner/manager.py:RunnerManager`，需改名 |
| 16 | `ErrorStrategy` | `DefaultErrorStrategy` | ⚪ | singleton | 🆕 | 现只有 `errors/types.py:ErrorCode` 枚举，无策略类 |
| 17 | `ToolManager` | `AutoDiscoverToolManager` | 🟡 | per-agent | 🔧 | 现为**单例**（`__new__` 拦截），需去单例 |
| 18 | `MCPClient` | `StdMCPClient` | 🟡 | singleton | 🆕 | 现只有 `tools/mcp.py:_build_client()` 函数 + `MCPTool` |
| 19 | `Scheduler` | `APSchedulerAdapter` | ⚪ | singleton | ✅ | 定时任务（`broca/scheduler.py`） |
| 20 | `CommandSystem` | `FileCommandSystem` | 🟡 | per-agent | 🔧 | 现 `CommandManager(agent)`，构造需 agent |
| 21 | `TaskManager` | `DBTaskManager` | 🟡 | singleton | ✅ | 任务管理 |
| 22 | `ConfigManager` | `FileConfigManager` | ⚪ | singleton | 🆕 | 现仅模块级 `configs.py:get_configs()` 函数 |
| 23 | `Logger` | `LoguruLogger` | ⚪ | singleton | 🆕 | 现仅 `logging_config.py:LoggingConfig` + `get_logger()` 函数 |

**分级说明**：

- 🔴 **核心 7 个**（#1/2/3/4/5/9/13）：直接决定 Agent 的行为与可测试性，Phase 1 定接口、Phase 2~4 落地
- 🟡 **支撑 11 个**（#6/7/8/10/11/12/15/17/18/20/21）：有真实替换需求（沙箱、远程存储、自定义 MCP），Phase 5 批量接口化
- ⚪ **基础设施 5 个**（#14/16/19/22/23）：替换价值低（几乎不会有人替换 `Logger`），**允许本迭代不做**；如做，只要求"ABC + 默认实现 + 配对测试"，不要求改造调用方

---

## 测试策略

### 测试金字塔

```
                ┌─────────────────┐
                │  E2E 集成测试    │  ← Phase 7：完整 Agent 对话流程
               ┌┤  (5~10 个)      ├┐
              ┌│  插件加载验证     ││
             ┌┤  组件替换验证      │││
            ┌┤  核心循环集成测试   ││├┐  ← Phase 2~4：组件交互
           ┌─┤  组件单元测试       ││├┤  ← 每个 Task 附带
          ┌─┤  ABC 接口兼容性测试  ││├┤│  ← Phase 1：基础
         ┌─┤  Registry 单元测试    ││├┤││
         └─┤  Protocol 测试       ││├┤│└─┐
           └──┤  Fixture/Mock     ││├┤│ └─┐
              └──┤  conftest.py   ││├┤│  ─┤
                 └────────────────┘│├┤│   └──────────
                                  └┤│└─────────────────────────
                                   └──────────────────────────
```

### 测试基础设施（Phase 1 建立）

- **`broca/tests/conftest.py`**：共享 fixture
  - `mock_communicator`：`AsyncMock` 的 `Communicator` 接口
  - `mock_llm_client`：`AsyncMock` 的 `LLMClient` 接口（返回预定义流式响应）
  - `mock_permission_provider`：可配置 allow/ask/forbidden 的 `PermissionProvider` mock
  - `test_context`：最小化的 `Context` 实例（空消息列表）
  - `test_tool`：简单的测试用 `Tool` 子类
  - `fresh_registry`：`ComponentRegistry` 实例 + `reset()` 清理（防止测试间状态污染）
  - `test_workspace`：临时目录作为 workspace
- **`broca/tests/mock_components.py`**：**7 个核心组件**的 mock/stub 实现（用于隔离测试）；其余 16 个组件随 Phase 5 逐步补齐（基础设施类组件不强制提供 mock）
- **`ComponentRegistry.reset()`**：清除 `_instances` 缓存（含 per-agent / per-session 分表）与 `_overrides`，在 fixture 的 teardown 中调用

### 各 Phase 测试重点

| Phase | 测试重点 | 新增/修改测试文件 |
|-------|---------|-----------------|
| 1 | ABC 接口签名兼容性、Registry 发现/覆盖/回退/**作用域隔离**、Protocol 行为 | `test_components_registry.py`、`test_component_interfaces.py` |
| 2 | **工具执行管道 characterization test（改造前先绿）**、ToolExecutor 完整管道（权限×3、超时跳过、白名单、session override）、LoopEngine 委托 | `test_tool_execution_behavior.py`（新增，characterization）、`test_tool_executor.py`、更新 `test_loop_engine.py` |
| 3 | ContextCompressor 压缩流程（阈值触发、强制、pivot 计算、记忆提取）、SessionMemoryManager 兼容层、clear 命令门控 | `test_context_compressor.py`（更新）、`broca/tests/session_memory/test_memory_manager.py`（适配） |
| 4 | 核心循环集成：LLM→工具→结果→压缩；PermissionProvider 合并行为；AgentReference 适配器；并行/串行调度 | `test_execution_engine.py`（新增）、`test_permission_provider.py`（新增）、更新 `test_llm.py` |
| 5 | 各组件 ABC-默认实现配对验证、接口兼容性、调用方无直接实例化、SkillManager 新测试 | 更新现有测试文件 + `test_component_compatibility.py`、新增 `test_skill_manager.py` |
| 6 | Agent.create() 组合流程、AgentReferenceAdapter 行为（含 `__getattr__` 透传）、组件间连接正确性、多 Agent 隔离、disconnect 释放 | `test_agent_composition.py`（新增） |
| 7 | 全量回归、覆盖率对比、插件 E2E、配置覆盖验证、**懒加载与启动耗时** | 全量 + `test_plugin_loading.py`、`test_e2e_scenarios.py`、`test_startup_overhead.py`（新增） |

### 覆盖率要求

- 改造前基线：522 个测试（`pytest broca/tests/ --collect-only` 统计，**已实测确认**）
- 改造后要求：测试总数 ≥ 600
  - 口径说明：各 Task 显式枚举的新增测试约 75 条（2.1×11 + 2.5×12 + 3.4×7 + 4.5×14 + 5.2.1×3 + 6.3×11 + 7.2×16 + 7.3×4），**其余靠 Task 5.5 的参数化展开**（每个接口 × 5 项检查，18~23 个接口即 90+ 条）；若 Task 5.5 不做参数化（改为逐条手写），则目标下调为 **≥ 590**
- 核心模块行覆盖率（`broca/components/`、`broca/tools/executor.py`、`broca/loop_engine.py`、`broca/context_compressor.py`、`broca/agent.py`）≥ 80%（**与 Phase 7 阶段 AC 保持一致**）
- 每个 Phase 完成时运行 `pytest broca/tests/ --cov=broca --cov-report=term-missing` 并对比（**显式传 `--cov`，不写入 `addopts`**，避免拖慢 `broca-web`/`broca-tui` 测试）
- **启动开销**：`python -c "import broca; from broca.agent import Agent"` 与 `Agent.create()` 的耗时，**目标**劣化 ≤ 5%（优化参考），**CI 软断言**劣化 ≤ 15%（`@pytest.mark.perf`，容忍 CI 抖动；Phase 7 用 `time.perf_counter` 取 20 次中位数对比）

### 关键回归测试场景（Phase 7 E2E）

1. **基础对话**：发送消息 → LLM 返回纯文本 → 无工具调用 → 对话完成
2. **工具调用**：发送消息 → LLM 返回工具调用 → 权限 allow → 工具执行 → 结果返回
3. **权限 ask 流程**：LLM 返回工具调用 → 权限 ask → 用户拒绝 → 错误返回 LLM
4. **并行工具**：LLM 一次返回 3 个工具调用 → 并行执行 → 全部结果汇总
5. **上下文压缩**：构造 >150K token 的历史 → 触发自动压缩 → session memory 提取
6. **强制压缩**：`/compact` 命令 → 跳过阈值检查 → 立即压缩
7. **死循环检测**：相同工具+参数重复 N 次 → 触发死循环中断
8. **组件替换**：通过 `components.json` 替换 ToolExecutor → 工具执行走自定义实现
9. **插件发现**：模拟 entry point 注册 → `ComponentRegistry` 自动发现并使用
10. **错误恢复**：LLM 返回格式错误 → ErrorStrategy 分类 → 重试或用户提示

---

## 执行计划

> **⚠️ Pre-flight 检查**：执行 Phase 1 前，确认以下基线已记录（见"实测基线"节）：
> - [ ] `pytest broca/tests/ --collect-only -q` → 522 tests
> - [ ] `pytest broca-web/tests/ -q` 通过/失败清单已记录
> - [ ] `pytest broca-tui/tests/ -q` 通过/失败清单已记录

### 工作量估算与合并约定

| Phase | 内容 | 规模 | 预估 | 独立可合并 |
|:-----:|------|:----:|------|:----------:|
| 1 | 核心接口 + Registry（作用域）+ 配置 + 测试基建 | L | 2~3 天 | ✅ |
| 2 | characterization test + ToolExecutor 提取 | L | 3~4 天 | ✅ |
| 3 | ContextCompressor 收口 + 清理外部引用 | L | 2~3 天 | ✅ |
| 4 | 核心循环组件化（LLM/Permission/Communicator/LoopEngine） | XL | 4~5 天 | ✅ |
| 5 | 11 个支撑组件接口化（5.1~5.4 可并行） | XL | 4~6 天 | ✅（按 Task 分批） |
| 6 | 组合根重构 + 隔离验证 | L | 2~3 天 | ✅ |
| 7 | 集成验证 + 启动开销 + 文档 | M | 2~3 天 | ✅ |

**合并约定**：每个 Phase 结束时必须满足"`pytest broca/tests/` 全绿 + 该 Phase 的 grep 判据通过"，方可合并；不允许跨 Phase 混合提交。回滚策略：每个 Phase 一个独立 PR/commit 序列，出问题按 Phase 整体 revert（characterization test 保证回滚后行为可验证）。

### Phase 1: 基础架构

**目标**：建立组件化底座——核心接口定义、ComponentRegistry（含**作用域机制**）、插件加载机制、组件配置、测试基础设施

**范围说明（重要）**：本 Phase **只定义 7 个核心组件的 ABC**（`ToolExecutor`、`ContextCompressor`、`LLMClient`、`PermissionProvider`、`Communicator`、`LoopEngine`、`AgentFactory`），其余 16 个组件的接口随其实现阶段（Phase 5）**增量定义**。理由：在尚未重构任何组件时冻结 23 个接口，接口正确性只能靠人工读代码，且与"接口可能不准确"的风险自相矛盾（见风险表）。

**阶段验收标准**：
- [ ] `broca/components/` 包创建完成，包含 **7 个核心组件 ABC** + `protocols.py` + `base.py` + `registry.py` + `defaults.py` + `errors.py`
- [ ] `ComponentRegistry` 实现完成，支持 entry points 发现 + 配置覆盖 + 默认回退 + **作用域（singleton / per-agent / per-session / transient）**
- [ ] `COMPONENT_SCOPES` 中 7 个核心组件条目与"总体方案 · 组件作用域与生命周期契约"表**逐行一致**（有测试断言；Phase 5 结束时须覆盖全部 23 条）
- [ ] 组件配置文件格式定义完成（`.broca/components.json`），并支持 `BROCA_COMPONENTS_CONFIG` 环境变量
- [ ] `pyproject.toml` 中声明 `broca.components` entry point group（**声明存在性可机械校验**，见 Task 1.2 AC ①）；`poetry build` + 干净 venv 安装后 `importlib.metadata.distribution("broca").entry_points` 可枚举且不抛异常；若 group 非空则每条 `EntryPoint` 可 `load()` 成功
- [ ] 接口单元测试 + 签名兼容性测试通过

#### Task 1.1: 创建组件接口层（核心 7 个）

- **目标**：在 `broca/components/` 包中定义 7 个核心组件的 ABC 接口与跨组件 Protocol
- **步骤**：
  1. 创建 `broca/components/` 包目录结构
  2. 创建 `broca/components/base.py`——定义 `BaseComponent` 基类（`async def initialize(**deps)` 幂等钩子 + 可选 `async def shutdown()`）
  3. 为 7 个核心组件创建接口文件，定义 ABC：

  **关键接口设计（优先级最高的 3 个，其余 5 个同风格）**：

  ```python
  # broca/components/tool_executor.py
  @dataclass
  class ToolExecutionOutcome:
      """工具执行结果 + 会话级权限决策的**观测值**（override 已由 executor 内部写入，调用方勿重复应用）"""
      result: ToolResult
      session_action: Optional[str] = None   # "allow" | "forbid" | None，仅用于日志/上报

  class ToolExecutor(BaseComponent, ABC):
      """工具执行器接口——封装"广播→存在性→白名单→权限→超时→执行→session 决策"完整管道"""

      @abstractmethod
      async def execute_tool(
          self,
          tool_name: str,
          arguments: str,
          tool_call_id: str,                       # 必需：用于 send_tool_call 广播
          context: ToolCallContext,                # 需含 turn_id / agent_id（Task 2.2 扩展）
          tool: Tool,
          allowed_tools: Sequence[str] | None = None,  # per-run 白名单，由 LoopEngine 逐次传入
      ) -> ToolExecutionOutcome:
          """执行单个工具调用（含广播、白名单、权限检查、超时、session 决策应用）"""
          ...

      @abstractmethod
      def get_permission(self, tool_name: str) -> str:
          """返回 "allow" | "ask" | "forbidden"（LoopEngine 用它做并行/串行分区）"""
          ...

      @abstractmethod
      def is_readonly_tool(self, tool_name: str) -> bool:
          """判断工具是否为只读（用于快照决策）"""
          ...

      @abstractmethod
      async def initialize(
          self,
          tool_mapping: dict[str, Tool],
          permission_provider: "PermissionProvider",
          config: Any,
          communicator: "Communicator",            # 职责 #4 广播所需，必须在 ABC 中声明
      ) -> None:
          ...
  ```

  > **契约闭合要求**：`initialize()` 的参数集合 = Task 2.4 / Task 6.1 调用点的参数集合（第三方按 ABC 实现时不会因组合根多传参数而 `TypeError`）。`allowed_tools` 属 per-run 状态（`agent.py:465/481` 每次 `agent.run()` 设置并在 `finally` 复位），因此**不进 `initialize()`**，而是逐次传给 `execute_tool()`。

  ```python
  # broca/components/context_compressor.py
  class ContextCompressor(BaseComponent, ABC):
      """上下文压缩器接口——统一的 token 监控 + 记忆提取 + 截断压缩"""

      # === 路径管理（原 SessionMemoryManager）===
      @property
      @abstractmethod
      def snapshot_memory_path(self) -> str: ...

      @property
      @abstractmethod
      def memory_path(self) -> str: ...

      @abstractmethod
      async def check_and_compress(
          self,
          context: Context,
          compressor_context: "CompressorContext",
          force: bool = False,     # 唯一入口：force=True 即"强制压缩"
      ) -> CompressionStats:
          """检查 token 阈值并触发压缩（force=True 跳过阈值检查）"""
          ...

      @abstractmethod
      def reset_session_memory(self) -> None:
          """清空当前 agent 的 session memory 文件（供 clear_* 命令使用）"""
          ...
  ```

  > **注**：不再单独定义抽象方法 `force_compress()`——`force=True` 参数已是唯一入口；如需便捷方法，在实现类中以**非抽象**方法提供（`async def force_compress(...)` 内部调用 `check_and_compress(force=True)`），避免同一能力两套 API。

  **关键设计：`CompressorContext` 协议**——替代直接传递 `agent` 对象：

  ```python
  # broca/components/protocols.py
  class CompressorContext(Protocol):
      """ContextCompressor 所需的窄接口"""
      agent_id: str
      session_id: str
      communicator: "Communicator"
      session_manager: "SessionManager"

      @property
      def compact_config(self) -> ContextCompactConfig: ...
      @property
      def provider(self) -> str: ...
      @property
      def model(self) -> str: ...
      @property
      def workspace(self) -> str | None: ...
      last_context_length: Optional[int]      # context_compressor.py:181 的 token 估算依赖它

  class AgentReference(Protocol):
      """LoopEngine 所需的 Agent 窄接口（注意 turn_id 可写）"""
      agent_id: str
      session_id: str

      @property
      def turn_id(self) -> Optional[str]: ...
      @turn_id.setter
      def turn_id(self, value: Optional[str]) -> None: ...   # loop_engine.py:1389 会写它

      last_context_length: Optional[int]      # 压缩器的 token 估算依赖它（AgentReferenceAdapter 需代理）

      async def on_llm_call_completed(self, input_tokens: int, output_tokens: int) -> None: ...
      async def ask_for_permission(self, message: str) -> bool: ...
      async def ask_for_tool_permission(self, tool_name: str, arguments: str) -> tuple[bool, Optional[str]]: ...
  ```

  4. 创建其余 5 个核心接口：`llm_client.py`（`LLMClient`）、`permission_provider.py`（`PermissionProvider`）、`communicator.py`（`Communicator`）、`loop_engine.py`（`LoopEngine`：`execute` / `abort` / `reset` / `initialize`）、`agent_factory.py`（`AgentFactory`）
  5. 创建 `broca/components/protocols.py`——定义 `CompressorContext`、`AgentReference`、`PermissionContext`、`ExecutionContext`
  6. 创建 `broca/components/__init__.py`——导出所有核心接口
- **预期产出**：`broca/components/` 包（7 个 ABC 文件 + `protocols.py` + `base.py`）
- **验收标准**：
  - [ ] `broca/components/` 包含 7 个核心接口文件，每个 ABC 有完整 docstring 与类型注解
  - [ ] `ToolExecutor.execute_tool()` 签名包含 `tool_call_id`，返回 `ToolExecutionOutcome`（含 `session_action`）
  - [ ] `ToolExecutor` 暴露 `get_permission()`（LoopEngine 并行/串行分区依赖它）
  - [ ] `ToolExecutor.initialize()` 的 ABC 参数集合与 Task 2.4 / 6.1 调用点**完全一致**（含 `communicator`，不含 `allowed_tools`）
  - [ ] `ToolExecutor.execute_tool()` 接受 `allowed_tools` 逐次传参（per-run 白名单不经 initialize）
  - [ ] `AgentReference` 含 `last_context_length`（供 `_build_compressor_context()` 使用）
  - [ ] `AgentReference.turn_id` 为**可读写**属性（Protocol 中声明 setter）
  - [ ] `ContextCompressor` 无抽象方法 `force_compress`，强制压缩走 `check_and_compress(force=True)`
  - [ ] `from broca.components import ToolExecutor, ContextCompressor, LLMClient, PermissionProvider, Communicator, LoopEngine, AgentFactory` 可成功导入
  - [ ] `test_component_interfaces.py` 中的签名兼容性测试通过：**仅对 Phase 1 已有实现类的 5 个接口**（`LLMClient` / `PermissionProvider` / `Communicator` / `LoopEngine` / `AgentFactory`）用 `inspect.signature` 比对 ABC 抽象方法参数名与现有实现参数名（允许实现侧有额外带默认值的参数）
    - `ToolExecutor`（实现类到 Task 2.2 才有）与 `ContextCompressor`（`SessionMemoryCompressor` 到 Task 3.1 才有）在 Phase 1 **跳过**，由 Task 5.5 的参数化比对兜底
  
#### Task 1.2: 实现 ComponentRegistry（含作用域）

- **目标**：实现统一的组件插件发现、解析、**按作用域实例化**机制
- **步骤**：
  1. 创建 `broca/components/registry.py`
  2. 实现 `ComponentRegistry` 类（**注意 `_instances` 的 key 是 `(interface, scope_key)` 元组，不是 `interface`**）：

  ```python
  ComponentScope = Literal["singleton", "per-agent", "per-session", "transient"]

  class ComponentRegistry:
      """组件注册表——管理组件接口的实现解析与按作用域实例化"""

      _instance: Optional["ComponentRegistry"] = None

      def __init__(self):
          self._overrides: dict[type, type] = {}
          self._discovered: dict[type, type] = {}
          self._defaults: dict[type, type] = {}
          self._scopes: dict[type, ComponentScope] = {}          # 由 register_defaults() 填充
          self._name_to_interface: dict[str, type] = {}          # 由 defaults.ENTRY_POINT_NAMES 填充
          self._entry_points: dict[type, Any] = {}              # 接口 → EntryPoint（未 load）
          self._plugins_discovered: bool = False                 # 发现哨兵（只枚举一次）
          # 关键：key = (interface, scope_key)；singleton 用 None 作 scope_key
          self._instances: dict[tuple[type, str | None], Any] = {}

      @classmethod
      def get_instance(cls) -> "ComponentRegistry": ...

      def register_defaults(self):
          """注册内置默认实现 + 作用域映射 + entry point 名称映射"""
          from broca.components.defaults import (
              DEFAULT_IMPLEMENTATIONS, COMPONENT_SCOPES, ENTRY_POINT_NAMES,
          )
          self._defaults = DEFAULT_IMPLEMENTATIONS
          self._scopes = COMPONENT_SCOPES
          self._name_to_interface = ENTRY_POINT_NAMES   # {"tool_executor": ToolExecutor, ...}

      def discover_plugins(self):
          """发现第三方插件：只枚举并缓存 EntryPoint 对象，**绝不 ep.load()**（懒加载硬约束）"""
          if self._plugins_discovered:
              return
          for ep in importlib.metadata.entry_points(group="broca.components"):
              interface = self._name_to_interface.get(ep.name)
              if interface:
                  self._entry_points[interface] = ep      # 只存对象，不 import 模块
          self._plugins_discovered = True

      def load_config_overrides(self, workspace: str | None):
          """加载 components.json 配置覆盖（workspace 级 > 全局 > 环境变量指定路径）"""

      def resolve(self, interface: type) -> type:
          """解析实现类：override > discovered(惰性 load) > default，未找到抛 ComponentNotFoundError。

          关键：只有"该接口确实有插件"时才 ep.load()，实现**按接口惰性加载**——
          未使用的插件模块永不进入 sys.modules（懒加载硬约束）。
          """
          if interface in self._overrides:
              return self._overrides[interface]
          if interface in self._discovered:
              return self._discovered[interface]
          ep = self._entry_points.get(interface)          # 首次 resolve 该接口时才 load
          if ep is not None:
              self._discovered[interface] = ep.load()
              return self._discovered[interface]
          if interface in self._defaults:
              return self._defaults[interface]
          raise ComponentNotFoundError(f"No implementation for {interface.__name__}")

      def get(self, interface: type, scope_key: str | None = None, **kwargs) -> Any:
          """按作用域获取组件实例。

          - singleton            → cache key = (interface, None)
          - per-agent/per-session→ cache key = (interface, scope_key)；scope_key 缺失抛 ComponentScopeError
          - transient            → 不缓存，每次新建
          """
          scope = self._scopes.get(interface, "singleton")
          if scope in ("per-agent", "per-session") and scope_key is None:
              raise ComponentScopeError(
                  f"{interface.__name__} is scoped '{scope}', scope_key is required"
              )
          if scope == "transient":
              return self.resolve(interface)(**kwargs)
          cache_key = (interface, scope_key if scope != "singleton" else None)
          if cache_key in self._instances:
              if kwargs:
                  logger.debug(f"{interface.__name__} cache hit, kwargs ignored: {kwargs}")
              return self._instances[cache_key]
          instance = self.resolve(interface)(**kwargs)
          self._instances[cache_key] = instance
          return instance

      def release(self, scope_key: str) -> None:
          """释放某 agent/session 名下的全部 per-agent / per-session 实例（Agent.disconnect 调用）"""
          for k in [k for k in self._instances if k[1] == scope_key]:
              self._instances.pop(k, None)

      def reset(self):
          """清空所有缓存实例与发现状态（含 per-agent 分表），供测试隔离"""
          self._instances.clear()
          self._overrides.clear()
          self._discovered.clear()
          self._entry_points.clear()
          self._plugins_discovered = False
  ```

  3. 创建 `broca/components/defaults.py`——两张映射表：
     - `DEFAULT_IMPLEMENTATIONS`：接口 → 默认实现类（**Phase 1 先录入 7 个核心组件**，其余 16 条随 Phase 5/6 接口创建时补齐）
     - `COMPONENT_SCOPES`：接口 → 作用域（**已录入的 key 必须与"总体方案 · 组件作用域与生命周期契约"表逐行一致**；Phase 5 结束时 key 集合须为完整 23 条）
     - `ENTRY_POINT_NAMES`：entry point 名称 → 接口类型（如 `{"tool_executor": ToolExecutor}`），供 `discover_plugins()` 解析 `ep.name`
  4. 创建 `broca/components/errors.py`——`ComponentError` 基类，`ComponentNotFoundError(ComponentError)`、`ComponentScopeError(ComponentError)`
  5. 在 `pyproject.toml` 中添加 entry point 声明。**注意：内置默认实现只走 `defaults.py`，entry point 仅保留 1 个示例作为文档与可发现性验证**：
  
  ```toml
  [project.entry-points."broca.components"]
  # 示例：第三方插件通过此 group 注册实现
  # tool_executor = "my_package.executor:SandboxToolExecutor"
  ```
  
  6. 验证 entry point 机制可用：`poetry build` → 在临时 venv 安装 → 断言 `importlib.metadata.distribution("broca").entry_points` 可枚举（**`importlib.metadata` 只读已安装 dist 元数据，源码目录直接跑测试看不到自身 entry points**，因此必须有这一步，否则 AC 无法验证）
     - 内置默认实现只走 `defaults.py`，该 group **允许为空**；因此"声明是否还在"用 ① 判定，而不是"枚举结果非空"（空 group 枚举也返回空集，无鉴别力）

- **预期产出**：`ComponentRegistry`（含作用域）+ 默认映射表 + 作用域表 + entry point 验证脚本
- **验收标准**：
  - [ ] `discover_plugins()` 能正确发现 entry points 注册的插件（测试中 monkeypatch `entry_points()`）
  - [ ] 优先级正确：override > discovered > default
  - [ ] `get(LLMClient)`（singleton）多次调用返回同一实例
  - [ ] `get(Communicator, scope_key="agent-1")` 与 `get(Communicator, scope_key="agent-2")` 返回**不同**实例；同一 `scope_key` 返回同一实例
  - [ ] `get(Communicator)`（per-agent 但缺 `scope_key`）抛 `ComponentScopeError`，**不静默退化为 singleton**
  - [ ] `get(interface, ...)`（transient）每次返回新实例
  - [ ] 缓存命中时传入 kwargs 不改变已有实例（且有 debug 日志）
  - [ ] `reset()` 清空所有作用域缓存与 `_discovered` / `_plugins_discovered`（monkeypatch 后不跨测试泄漏）
  - [ ] `release(scope_key)` 只释放该 key 名下的实例，不影响其他 agent
  - [ ] `discover_plugins()` 幂等：重复调用只枚举一次（`_plugins_discovered` 哨兵）
  - [ ] **`discover_plugins()` 不触发任何 `EntryPoint.load()`**（mock `EntryPoint.load` 断言调用次数为 0）
  - [ ] `resolve(interface)` 才触发**该接口**的 `ep.load()`，且结果缓存进 `_discovered`（第二次 resolve 不再 load）
  - [ ] 未被 resolve 的接口对应的插件模块不出现在 `sys.modules`
  - [ ] `COMPONENT_SCOPES` 与设计表逐行一致的断言测试通过
  - [ ] ① `grep -c 'project.entry-points."broca.components"' pyproject.toml` **恰好为 1**（声明存在性）
  - [ ] ② `poetry build` + 干净 venv 安装后 `importlib.metadata.distribution("broca").entry_points` 可枚举且不抛异常
  - [ ] ③ 若 group 非空，每条 `EntryPoint.load()` 均成功（无 ImportError）

#### Task 1.3: 组件配置机制

- **目标**：定义组件覆盖配置的文件格式和加载逻辑
- **步骤**：
  1. 定义配置文件格式：`{workspace}/.broca/components.json`
  
  ```json
  {
    "tool_executor": "my_package.executor:SandboxToolExecutor",
    "llm_client": "my_package.llm:LocalLLMClient"
  }
  ```
  
  2. 支持全局配置：`~/.broca/components.json`（优先级低于 workspace 级）
  3. 在 `ComponentRegistry.load_config_overrides()` 中实现加载逻辑
  4. 支持环境变量 `BROCA_COMPONENTS_CONFIG` 指定自定义配置路径

- **预期产出**：配置文件格式文档 + 加载逻辑实现
- **验收标准**：
  - [ ] 配置文件中的 `"module:ClassName"` 格式能正确解析并导入（支持 `pkg.mod:Class` 与 `pkg.mod.Class` 两种写法）
  - [ ] 不存在的模块/类名给出清晰的错误信息（包含配置文件路径、key、原始值）
  - [ ] 优先级明确且有测试：`BROCA_COMPONENTS_CONFIG` 显式路径 > `{workspace}/.broca/components.json` > `~/.broca/components.json`
  - [ ] 配置文件不存在时不影响正常运行
  - [ ] 配置解析失败（JSON 语法错误 / 未知 key）时**只 warn 并回退默认**，不阻断 Agent 启动

#### Task 1.4: 测试基础设施搭建

- **目标**：建立组件化改造的测试基础设施，确保后续所有 Phase 的测试有一致的 mock/fixture 环境
- **步骤**：
  1. 创建 `broca/tests/conftest.py`，包含以下 fixture：
     - `mock_communicator`：`AsyncMock` 实现 `Communicator` 接口
     - `mock_llm_client`：`AsyncMock` 实现 `LLMClient` 接口（预定义流式响应 + `aggregate_message` 返回）
     - `mock_permission_provider`：可配置行为的 `PermissionProvider` mock（`allow_all`、`forbid_all`、`ask_all` 三种模式）
     - `test_context`：最小化 `Context` 实例
     - `test_tool`：简单测试用 `Tool` 子类（`execute` 返回固定结果）
     - `fresh_registry`：`ComponentRegistry` 实例 + teardown 时 `reset()`
     - `test_workspace`：`tmp_path` 作为 workspace 根目录
  2. 创建 `broca/tests/mock_components.py`：**7 个核心组件**的 `Mock*` 实现（`AsyncMock` 或简单 stub），用于隔离测试；其余 16 个随 Phase 5 补齐
  3. `ComponentRegistry.reset()` 在 Task 1.2 中已实现（含 per-agent 分表），本 Task 只负责在 fixture teardown 中调用
  4. 覆盖率配置：**不要**把 `--cov` 写进 `addopts`（会拖慢 `broca-web`/`broca-tui` 测试并污染口径），改为：
     ```toml
     [tool.coverage.run]
     source = ["broca"]
     omit = ["broca/alembic/*", "broca/tests/*"]
     ```
     覆盖率报告在各 Phase 收尾与 Phase 7 通过显式 `pytest ... --cov=broca --cov-report=term-missing` 生成

- **预期产出**：`broca/tests/conftest.py`、`broca/tests/mock_components.py`、覆盖率配置
- **验收标准**：
  - [ ] 所有 fixture 在 `pytest --fixtures` 中可见
  - [ ] `fresh_registry` fixture 保证每个测试的 Registry 状态干净（含 per-agent 缓存）
  - [ ] `mock_llm_client` 能正确模拟流式响应 + `aggregate_message`
  - [ ] `mock_components.py` 中 7 个核心组件 Mock 可导入
  - [ ] `pytest broca/tests/ -q` 的运行时间与改造前基线相比无显著增加（无全局 `--cov`）
  - [ ] `git diff pyproject.toml` 中**不包含** `addopts`
  - [ ] 显式 `--cov` 时覆盖率报告可正常生成

---

### Phase 2: ToolExecutor 组件提取（最高优先级）

**目标**：先用 characterization test 锁定现有工具执行行为，再把工具执行管道从 `LoopEngine` 中提取为独立的 `ToolExecutor` 组件

**阶段验收标准**：
- [ ] `ToolExecutor` ABC 就位（Phase 1 已创建，含 `get_permission()` 与 `ToolExecutionOutcome`）
- [ ] **11 条 characterization test 在改造前全绿**（`test_tool_execution_behavior.py`），改造后仍全绿，覆盖职责 #1~#8
- [ ] `DefaultToolExecutor` 实现完成，包含完整管道（**顺序与真实代码一致**）：**广播 → 存在性检查 → `allowed_tools` 白名单 → 权限（forbidden/ask/allow）→ 超时（含跳过规则）→ 执行 → session 决策**
  - 注：`_broadcast_tool_call_start()` 在 `loop_engine.py:791` 位于存在性（793）/白名单（801）/权限（808）**之前**，即"被拒绝的工具也会广播"，前端依赖该行为
- [ ] `LoopEngine` 中的 `_execute_single_tool_call()` / `_execute_tool_with_ask()` / `_execute_tool_with_allow()` 已删除，改为委托 `ToolExecutor`
- [ ] 现有工具执行行为完全不变（所有工具测试 + characterization test 通过）
- [ ] 支持通过组件配置替换为自定义 ToolExecutor（如沙箱执行器）

#### Task 2.1: 工具执行行为清点 + Characterization Tests（先做，不改产品代码）

- **目标**：用测试锁定 `LoopEngine` 现有工具执行管道的**全部 8 项职责**，为后续等价重构提供回归护栏
- **背景**：`_execute_single_tool_call()`（`loop_engine.py:784`）承担了远超"执行一个工具"的职责，逐一清点如下：

  | # | 现有行为 | 代码位置 | 重构后归属 |
  |:-:|---------|---------|-----------|
  | 1 | 工具存在性检查（不在 `tool_mapping` → ERROR） | `loop_engine.py:793-799` | ToolExecutor |
  | 2 | `allowed_tools` 白名单（不在列表 → "this tool is currently not allowed"） | `loop_engine.py:801-806` + `_is_tool_allowed()` | ToolExecutor |
  | 3 | 权限决策 forbidden / ask / allow | `loop_engine.py:808-828` | ToolExecutor（读 `PermissionProvider`） |
  | 4 | 工具调用广播 `send_tool_call(...)`（需 `tool_call.id` + `config.interactive`） | `loop_engine.py:677-689` | ToolExecutor（保留 communicator 依赖） |
  | 5 | 超时跳过规则：`bash` background、`ask_user` 不走外层 `wait_for` | `_should_skip_tool_timeout()` `loop_engine.py:946` | ToolExecutor |
  | 6 | 独立超时：`assign_task` 用 `assign_task_timeout`（1800s），其余用 `tool_call_timeout`（120s） | `_get_tool_execution_timeout()` `loop_engine.py:695` | ToolExecutor |
  | 7 | 异常映射：`ToolError`/`BrocaError` → `e.to_user_message()`；`TimeoutError` → 超时文案；`CancelledError` 必须**重新抛出** | `loop_engine.py:701-727` | ToolExecutor |
  | 8 | session 决策应用：`allow`/`forbid` → `set_session_override()` | `_apply_session_decision()` `loop_engine.py:773` | ToolExecutor 内部应用（经 `PermissionProvider`）；`session_action` 仅作观测返回值 |

  > **真实执行顺序**（务必按此实现，勿按表格编号顺序）：`#4 广播` → `#1 存在性` → `#2 白名单` → `#3 权限` → `#5/#6 超时` → 执行 → `#7 异常映射` → `#8 session 决策`。广播先于所有校验，因此**被拒绝的工具也会广播**（前端展示依赖）。

- **步骤**：
  1. 创建 `broca/tests/test_tool_execution_behavior.py`，**只使用现有 API**（`LoopEngine` + 真实/桩工具），不引入任何新接口
  2. 编写以下 **11 条** characterization test（断言当前行为，作为等价性基线）：

     | 测试 | 断言内容 | 覆盖职责 |
     |------|---------|:--------:|
     | `test_ask_user_not_interrupted_by_outer_timeout` | `ask_user` 内部 sleep > `tool_call_timeout` 仍正常返回 | #5 |
     | `test_bash_background_skips_outer_timeout` | `bash` + `{"background": true}` 不触发外层超时 | #5 |
     | `test_assign_task_uses_dedicated_timeout` | `assign_task` 用 `assign_task_timeout`（1800s）而非 120s | #6 |
     | `test_disallowed_tool_rejected` | `allowed_tools=["read_file"]` 时 `bash` 返回 `this tool is currently not allowed` | #2 |
     | `test_run_scoped_allowed_tools_reset` | 用 mock LLM 构造的 Agent 跑一次 `run(allowed_tools=["read_file"])`，结束后 `execution_engine.allowed_tools` 复位为 `None` | #2（per-run 状态） |
     | `test_session_override_persisted` | 权限 `ask` + 用户 `allow` → session override 写入，第二次调用不再询问 | #3 + #8 |
     | `test_tool_call_broadcast_emitted` | `interactive=True` 时 `send_tool_call` 被调用且带正确 `tool_call_id` | #4 |
     | `test_broadcast_emitted_for_forbidden_tool` | 权限 forbidden 的工具**仍然**广播了 `send_tool_call`（广播先于校验） | #4 |
     | `test_tool_not_found_returns_error` | 不在 `tool_mapping` 的工具 → `ToolResult(status=ERROR, content="Tool X not found")` | #1 |
     | `test_tool_error_mapped_to_user_message` | 工具抛 `ToolError` → 返回 `e.to_user_message()` 的 `ToolResult(ERROR)` | #7 |
     | `test_cancelled_error_propagates` | 工具执行中 `task.cancel()` → `CancelledError` 向上传播，**不被转成 ToolResult** | #7 |

  3. 运行 `pytest broca/tests/test_tool_execution_behavior.py -v`，**确认 11 条全绿后再进入 Task 2.2**
- **预期产出**：`broca/tests/test_tool_execution_behavior.py`（11 个测试函数）
- **验收标准**：
  - [ ] 11 条测试全部通过（改造前基线）
  - [ ] 职责 #1~#8 **每项至少 1 条测试**（本 Task 或 Task 2.5 覆盖，本 Task 至少覆盖 #1/#4/#5/#6/#7）
  - [ ] 每条测试注释标注职责编号
  - [ ] 测试不依赖真实 LLM / SocketIO / 数据库（使用 `tmp_path` + `mock_llm_client`；`test_run_scoped_allowed_tools_reset` 允许构造 Agent）
  - [ ] 若某条行为无法用现有 API 观测，需在报告中说明原因并给出替代断言

#### Task 2.2: 实现 DefaultToolExecutor

- **目标**：从 `LoopEngine` 提取工具执行逻辑到 `DefaultToolExecutor`，完整覆盖 Task 2.1 表中的 8 项职责
- **步骤**：
  1. **先扩展 `ToolCallContext`**（`broca/tools/tool.py:41`）：新增 `turn_id: Optional[str]` 与 `agent_id: Optional[str]` 两个字段，由 `LoopEngine._build_tool_context()` 填充。理由：职责 #4 广播需要 `turn_id` / `agent_id` / `subscription`（见 `communicator.send_tool_call` 签名，`loop_engine.py:681-689`），而现有 `ToolCallContext` 只有 `agent / workspace / session_id / execution_id / namespace`——不扩字段就无法在"禁止业务访问 `context.agent`"的前提下完成广播
  2. 创建 `broca/tools/executor.py`
  3. 按 Task 2.1 的**真实执行顺序**迁移（**8 项一项都不能少**）：`广播 → 存在性 → 白名单 → 权限 → 超时 → 执行 → 异常映射 → session 决策`，内部拆分为：
     - `execute_tool(tool_name, arguments, tool_call_id, context, tool, allowed_tools=None) -> ToolExecutionOutcome`（总入口）
     - `_check_exists()` / `_check_allowed()` / `_broadcast_start()` / `_execute_with_allow()` / `_execute_with_ask()` / `_apply_session_decision()`
     - `get_permission()` / `is_readonly_tool()` / `_get_timeout()` / `_should_skip_timeout()`
  4. `DefaultToolExecutor` 依赖通过 `initialize()` 注入（**参数集合必须与 ABC 完全一致**）：
  
  ```python
  class DefaultToolExecutor(ToolExecutor):
      def __init__(self):
          self._tool_mapping: dict[str, Tool] = {}
          self._permission_provider: PermissionProvider | None = None
          self._communicator: Communicator | None = None
          self._interactive: bool = False
          self._tool_call_timeout: int = 120
          self._assign_task_timeout: int = 1800

      async def initialize(
          self,
          tool_mapping: dict[str, Tool],
          permission_provider: PermissionProvider,
          config: Any,
          communicator: Communicator,
      ) -> None:
          """从 config 读取 interactive / tool_call_timeout / assign_task_timeout"""

      async def execute_tool(
          self, tool_name, arguments, tool_call_id, context, tool, allowed_tools=None
      ) -> ToolExecutionOutcome:
          # ④ 广播 → ① 存在性 → ② 白名单 → ③ 权限 → ⑤⑥ 超时 → 执行 → ⑦ 异常映射 → ⑧ session 决策
          ...
  ```
  
  5. 权限获取路径解耦：`DefaultToolExecutor` 通过 `PermissionProvider.request_tool_permission()` 请求权限、通过 `set_session_override()` 写会话决策，**不再通过 `context.agent.ask_for_tool_permission()`**
     - **`session_action` 的归属（唯一口径）**：会话级决策**由 executor 内部应用**（`_apply_session_decision()` 写 `PermissionProvider.set_session_override()`），`ToolExecutionOutcome.session_action` 仅作为**观测/日志返回值**暴露给调用方，**调用方不得再次应用**（避免重复写 override、语义混乱）
  6. 广播取 `context.turn_id` / `context.agent_id` / `context.session_id`，**不读 `context.agent`**
  7. **保留** `ToolCallContext.agent` 字段不动（工具层依赖它，见"总体方案 · 窄接口协议"的例外说明）
- **预期产出**：`broca/tools/executor.py`（`DefaultToolExecutor` + `ToolExecutionOutcome`）
- **验收标准**：
  - [ ] `DefaultToolExecutor` 实现 `ToolExecutor` ABC 的所有抽象方法
  - [ ] Task 2.1 表中 8 项职责**逐项有对应实现**（代码注释标注编号）
  - [ ] 权限三分支完整：forbidden / ask（含拒绝）/ allow
  - [ ] 超时：`ask_user` 与 `bash background` 跳过外层 `wait_for`；`assign_task` 用独立超时
  - [ ] `asyncio.CancelledError` 被重新抛出（不吞掉）
  - [ ] `execute_tool()` 返回 `ToolExecutionOutcome`；`session_action` 反映用户选择（`allow`/`forbid`/`None`），且 **override 已由 executor 内部写入**（断言 `provider.get_tool_permission(tool)` 已变更）
  - [ ] `LoopEngine` **不再**调用 `set_session_override`（`grep -n "set_session_override" broca/loop_engine.py` 为 0）
  - [ ] `is_readonly_tool()` 与 `ToolManager.READONLY_TOOLS` 判断一致
  - [ ] 广播顺序正确：被 forbidden 的工具**也有** `send_tool_call`（`test_broadcast_emitted_for_forbidden_tool` 通过）
  - [ ] `grep -nE "context\.agent\." broca/tools/executor.py` 结果为 0（禁止**业务属性访问**；类型注解与 `ctx.agent = ...` 透传允许）
  - [ ] `ToolCallContext` 新增 `turn_id` / `agent_id` 字段，`_build_tool_context()` 已填充

#### Task 2.3: 重构 LoopEngine 使用 ToolExecutor

- **目标**：修改 `LoopEngine` 将工具执行委托给 `ToolExecutor`，并保留调度/结果处理职责
- **步骤**：
  1. `LoopEngine.__init__()` 新增 `tool_executor: ToolExecutor` 参数（**中间态**：Phase 4.4 会统一改为 `initialize()` 注入；`tool_permission_manager` 保留为兼容回退，Phase 4.4 移除）
  2. `_process_tool_calls()` 改为调用 `self.tool_executor.execute_tool(tool_name, arguments, tool_call.id, context, tool, allowed_tools=self.allowed_tools)`
     - **`allowed_tools` 的归属**：继续留在 `LoopEngine`（`agent.run(allowed_tools=...)` 写 `execution_engine.allowed_tools`、`finally` 复位，见 `agent.py:465/481`），**逐次作为参数传给 `execute_tool()`**，不放进 `ToolExecutor.initialize()`。这样 `agent.run()` 的现有语义完全不变，白名单不会静默失效
  3. **保留在 LoopEngine**：并行/串行调度（`asyncio.Semaphore` + `max_parallel_tools`）、结果处理（`process_tool_call_result`：broadcast、DB save、context add）、abort 检查
  4. 并行/串行分区改为 `self.tool_executor.get_permission(tool_name) == "ask"`（**不再直接读 `tool_permission_manager`**）
  5. `check_step_has_write_operations()` 改为 `self.tool_executor.is_readonly_tool(tool_name)`
  6. 删除 `_execute_single_tool_call()`、`_execute_tool_with_ask()`、`_execute_tool_with_allow()`、`_apply_session_decision()`、`_should_skip_tool_timeout()`、`_get_tool_execution_timeout()`
     - 其中 `_apply_session_decision()` 的职责已迁入 executor 内部（见 Task 2.2 步骤 5），LoopEngine 侧**不得再写 `set_session_override`**（重复应用会让语义混乱）
  7. 保留 `_build_tool_context()`（`ToolCallContext.agent` 仍需赋值），并新增填充 `ctx.turn_id = self.turn_id`、`ctx.agent_id = self.agent_id`
- **预期产出**：重构后的 `broca/loop_engine.py`
- **验收标准**：
  - [ ] `grep -n "asyncio.wait_for" broca/loop_engine.py` 结果只出现在 LLM 调用处，**工具执行处为 0**
  - [ ] `grep -n "tool_permission_manager" broca/loop_engine.py` 结果只出现在 `__init__` 的兼容参数赋值处（或为 0）
  - [ ] `grep -n "_execute_single_tool_call\|_execute_tool_with_ask\|_execute_tool_with_allow\|_should_skip_tool_timeout" broca/loop_engine.py` 结果为 0
  - [ ] 并行/串行模式切换仍正确（Phase 4.5 的 `test_execute_parallel_tool_calls` 覆盖）
  - [ ] 结果处理（broadcast、DB save、context add）仍在 LoopEngine 中（`process_tool_call_result` 未被搬走）
  - [ ] `agent.run(allowed_tools=["read_file"])` 期间 `bash` 被拒、run 结束后白名单复位（`test_run_scoped_allowed_tools_reset` 仍绿）
  - [ ] `agent.py:465/466/481` 三处 per-run 赋值**未被修改**（`git diff broca/agent.py` 中不含这三行）
  - [ ] `test_loop_engine.py` + `test_tool_execution_behavior.py` 全部通过

#### Task 2.4: Agent.create() 适配 ToolExecutor

- **目标**：在 Agent 创建流程中通过 ComponentRegistry 初始化 ToolExecutor
- **步骤**：
  1. `Agent.create()` 中新增（**注意 per-agent 作用域必须传 `scope_key`**；参数与 ABC 完全一致，**不传 `allowed_tools`**）：
     ```python
     registry = ComponentRegistry.get_instance()
     tool_executor = registry.get(ToolExecutor, scope_key=agent.agent_id)
     await tool_executor.initialize(
         tool_mapping=agent.tool_mapping,
         permission_provider=agent.permission_manager,   # Phase 4.2 后改名为 permission_provider
         config=agent.config,
         communicator=agent.communicator,
     )
     ```
     - `allowed_tools` 是 **per-run 状态**（`agent.run()` 每次设置、`finally` 复位），创建阶段恒为 `None`，**不参与 initialize**；由 `LoopEngine` 在 `execute_tool(..., allowed_tools=self.allowed_tools)` 逐次传入（见 Task 2.3 步骤 2）
  2. `Agent._setup_execution_engine()` 传入 `tool_executor`
  3. `ToolCallContext` 的构造保持不变（`agent` 字段仍赋真实 Agent），并在 Task 2.3 中已补 `turn_id` / `agent_id`
- **预期产出**：修改后的 `broca/agent.py`
- **验收标准**：
  - [ ] `Agent.create()` 通过 `ComponentRegistry.get(ToolExecutor, scope_key=agent_id)` 获取执行器
  - [ ] 两个 Agent 实例拿到**不同**的 `ToolExecutor`（`test_two_agents_isolated`）
  - [ ] `initialize()` 调用参数与 `ToolExecutor` ABC 声明**逐参数一致**（无多余 kwargs，第三方实现不会 `TypeError`）
  - [ ] 不配置任何插件时行为与改造前完全一致
  - [ ] Agent 创建流程不会因组件缺失而失败（有默认回退）
  - [ ] `allowed_tools` 不在创建阶段传入（`grep -n "allowed_tools" broca/agent.py` 仅命中 `run()` 相关三行）

> **注意**：本 Task 对 `Agent.create()` 的修改是**中间步骤**——仅引入 `ToolExecutor` 的获取和初始化。Phase 6.1 将对 `Agent.create()` 进行彻底重构（所有组件均通过 Registry 获取）。本 Phase 中 `Agent.create()` 仍然直接 `new` 其他组件（Communicator、Context 等），只有 `ToolExecutor` 走了 Registry 路径。

#### Task 2.5: ToolExecutor 单元测试

- **目标**：为 ToolExecutor 编写独立的单元测试（**不含并行/串行调度**，调度留在 LoopEngine，由 Phase 4.5 覆盖）
- **步骤**：
  1. 创建 `broca/tests/test_tool_executor.py`
  2. 测试用例：
     - `test_execute_tool_allow` — 权限 allow 时直接执行
     - `test_execute_tool_forbidden` — forbidden 返回错误文案
     - `test_execute_tool_ask_granted` — ask + 用户允许 → 执行 + `session_action == "allow"`
     - `test_execute_tool_ask_denied` — ask + 用户拒绝 → 错误文案
     - `test_execute_tool_not_found` — 工具不存在 → ERROR
     - `test_execute_tool_not_allowed` — 不在 `allowed_tools` → `this tool is currently not allowed`
     - `test_execute_tool_timeout` — 执行超时
     - `test_skip_timeout_for_ask_user` / `test_skip_timeout_for_bash_background`
     - `test_assign_task_uses_dedicated_timeout`
     - `test_readonly_tool`
     - `test_broadcast_emitted_when_interactive`
     - `test_session_override_applied` — 断言 `session_action == "allow"` **且** `provider.get_tool_permission(tool)` 已变为 `"allow"`（override 由 executor 内部写入）
  3. 使用 mock 的 `Tool`、`PermissionProvider`、`Communicator`、`ToolCallContext`
- **预期产出**：`broca/tests/test_tool_executor.py`（≥ 12 个测试函数）
- **验收标准**：
  - [ ] 所有测试用例通过
  - [ ] 覆盖 Task 2.1 表中全部 8 项职责（每项至少 1 条测试）
  - [ ] 测试不依赖 Agent 实例，也不测试并行/串行调度

---


### Phase 3: ContextCompressor 合入 SessionMemory

**目标**：将 `SessionMemoryManager` 的提取/pivot/冻结逻辑合入 `ContextCompressor`，并把 `ContextCompressor` 从"接收 agent"改为"接收 `CompressorContext` 协议"

**现状说明（重要，避免重复劳动）**：`broca/context_compressor.py` 已存在具体类 `ContextCompressor`，其中 `check_and_compress(context, execution_engine, agent, force)` 已实现"阈值检查 → 委托 `_do_session_memory_compress()`"；`LoopEngine` 也已持有 `self.context_compressor` 并通过 `_check_context_compression()` 调用。本 Phase 的真实工作是**把逻辑从 `SessionMemoryManager` 搬进压缩器 + 换掉 `agent` 参数 + 清理外部引用**，不是从零实现。

**阶段验收标准**：
- [ ] `SessionMemoryCompressor(ContextCompressor)` 包含完整流程：token 监控 + pivot 计算 + 记忆提取 + 截断 + 冻结 + context 重建
- [ ] `ContextCompressor` 的全部对外方法只接收 `CompressorContext`，**不再接收 `agent`**
- [ ] `SessionMemoryManager` 收敛为**薄兼容层**：只保留路径属性 + `reset()`，内部持有 `ContextCompressor` 引用；**不再承载提取/pivot/冻结逻辑**
- [ ] 全仓 `agent.session_memory_manager` 引用点归零（**排除式口径**：`grep -rn "session_memory_manager" broca --include=*.py | grep -v "session_memory/" | grep -v tests` 结果为 0；兼容层自身与测试允许保留），`Agent._setup_session_memory()` 已移除
- [ ] `/compact` 与 `clear_history` / `clear_context` / `clear_all_context` 均通过 `ContextCompressor` 工作
- [ ] **门控载体明确**：`enable_context_compression=False` 时压缩与 session memory 文件操作全部跳过（`registry.get(ContextCompressor)` 永远返回实例，因此门控必须由 `agent.config.enable_context_compression` 判断，不能依赖"组件为 `None`"）
- [ ] 上下文压缩相关测试全部通过

#### Task 3.1: 重构 ContextCompressor 合入 SessionMemory

- **目标**：把 `SessionMemoryManager` 的核心逻辑迁入 `SessionMemoryCompressor`，接口改为 `CompressorContext`
- **步骤**：
  1. 参考 `plans/session-memory-extraction-compression-optimization.md`（**注意：该文件在当前 worktree 中不存在，仅主 worktree 有**；若不可用，以本 Task 步骤 2 的方法清单为准）
  2. 从 `broca/session_memory/memory_manager.py` 迁入以下方法到 `SessionMemoryCompressor`：
     - `compute_keep_pivot()`（`memory_manager.py:173`）
     - `extract()` / `_do_extract()` / `_run_extraction_subagent()`（保留子代理机制，`memory_manager.py:132/281/294`）
     - `frozen_session_memory()` / `_read_session_memory_content()`（`memory_manager.py:100/117`）
     - 路径管理：`_agent_memory_dir()` / `snapshot_memory_path` / `memory_path` / `_ensure_template_exists()`（`memory_manager.py:69-130`）
     - `is_session_memory_empty()` / `reset()`（`memory_manager.py:88/379`）
  3. 签名改造：
     ```python
     class SessionMemoryCompressor(ContextCompressor):
         async def initialize(self, agent_ref, session_manager, config) -> None: ...
         async def check_and_compress(self, context, compressor_context: CompressorContext, force: bool = False) -> CompressionStats: ...
         async def force_compress(self, context, compressor_context) -> CompressionStats:
             """非抽象便捷方法：等价于 check_and_compress(force=True)"""
             return await self.check_and_compress(context, compressor_context, force=True)
         def reset_session_memory(self) -> None: ...
     ```
  4. `_get_effective_threshold()` / `_get_total_tokens()` 中所有 `agent.config.provider`、`agent.config.model`、`agent.last_context_length` 改为读 `compressor_context.provider/model/last_context_length`
  5. `SessionMemoryManager` 改写为薄兼容层：
     ```python
     @deprecated("Use ContextCompressor (broca.components.ContextCompressor) instead")
     class SessionMemoryManager:
         """兼容层：仅保留路径属性与 reset()，逻辑委托给 ContextCompressor。
         注意：不再持有 extract/pivot/冻结逻辑（已迁入 SessionMemoryCompressor），
         避免"逻辑搬走后再委托回去"的循环。"""
         def __init__(self, compressor: ContextCompressor, workspace: str | None): ...
         @property
         def snapshot_memory_path(self) -> str: return self._compressor.snapshot_memory_path
         @property
         def memory_path(self) -> str: return self._compressor.memory_path
         def reset(self) -> None: self._compressor.reset_session_memory()
     ```
  6. 更新 `broca/components/defaults.py` 中 `ContextCompressor → SessionMemoryCompressor` 映射
- **预期产出**：重构后的 `broca/context_compressor.py`（含 `SessionMemoryCompressor`）+ 精简后的 `broca/session_memory/memory_manager.py`
- **验收标准**：
  - [ ] `issubclass(SessionMemoryCompressor, ContextCompressor)` 为真，`SessionMemoryCompressor.__abstractmethods__` 为空
  - [ ] `check_and_compress()` 完整流程可观测：token 检查 → pivot 计算 → 提取 → 截断 → 冻结 → 重建
  - [ ] `check_and_compress(force=True)` 与 `force_compress()` 行为一致（有测试断言两者 `CompressionStats` 相同）
  - [ ] `SessionMemoryManager` 只剩路径属性 + `reset()`，`grep -c "def " broca/session_memory/memory_manager.py` 显著减少（≤ 8 个方法）
  - [ ] `grep -rn "agent\." broca/context_compressor.py` 结果为 0（全部走 `CompressorContext`）
  - [ ] 子代理提取机制保持不变（仍通过 `AgentFactory` 创建子 agent）

#### Task 3.2: 重构 LoopEngine 的 post-step hooks

- **目标**：`LoopEngine._trigger_post_step_hooks()` 通过 `ContextCompressor` 触发压缩，**并保持持久化记忆的现有并发语义不变**
- **步骤**：
  1. `LoopEngine.__init__()` 新增 `context_compressor: ContextCompressor`、`memory_manager: MemoryManager | None` 参数
  2. `_trigger_post_step_hooks()` 改写（**保留 `enable_context_compression` 门控、`auto_extract` 门控、`increment_step()` 与后台 `create_task` 语义**，与当前 `loop_engine.py:507-526` 行为一致）：
     ```python
     async def _trigger_post_step_hooks(self) -> None:
         if self.config.enable_context_compression and self.context_compressor:
             await self.context_compressor.check_and_compress(
                 context=self.context,
                 compressor_context=self._build_compressor_context(),
             )
         # 持久化记忆：保持 fire-and-forget 语义，不改为同步 await
         if (
             self.memory_manager
             and getattr(self.config, "persistent_memory_config", None)
             and self.config.persistent_memory_config.auto_extract
         ):
             self.memory_manager.increment_step()
             task = asyncio.create_task(
                 self.memory_manager.check_and_extract(context=self.context)
             )
             task.add_done_callback(lambda t: t.exception() if not t.cancelled() else None)
     ```
  3. 实现 `_build_compressor_context() -> CompressorContext`（从 `self.agent_ref` 提取属性构造轻量适配对象；**必须包含 `last_context_length`**——`context_compressor.py:181` 的 token 估算优先读该值，因此 `AgentReference` Protocol 需声明该字段，见 Task 1.1）
  4. 删除 `LoopEngine` 中对 `agent.session_memory_manager` 的所有引用（当前仅经 `_check_context_compression()` 间接使用，直接删除 `_check_context_compression()`）
- **预期产出**：修改后的 `broca/loop_engine.py`
- **验收标准**：
  - [ ] `grep -n "session_memory_manager" broca/loop_engine.py` 结果为 0
  - [ ] `grep -n "_check_context_compression" broca/loop_engine.py` 结果为 0（合并进 `_trigger_post_step_hooks`）
  - [ ] 压缩通过 `self.context_compressor.check_and_compress(..., compressor_context=...)` 触发
  - [ ] 持久化记忆仍是后台 `create_task` + `auto_extract` 门控（`test_persistent_memory_not_awaited` 断言 `check_and_extract` 未阻塞 step）
  - [ ] `ContextCompressor` 不再接收 `agent` 参数（`grep -n "agent:" broca/context_compressor.py` 为 0）

#### Task 3.3: 适配 /compact 命令

- **目标**：`/compact` 通过共享的 `ContextCompressor` 实例强制压缩，而不是每次 `new` 一个
- **步骤**：
  1. 修改 `broca/commands/builtin/compact/__init__.py`（当前在 `:50` 直接 `ContextCompressor()`）
  2. 改为取 Agent 已装配的实例，并由执行引擎构造 `CompressorContext`（**不要自己拼字段**）：
     ```python
     engine = agent.execution_engine
     compressor = engine.context_compressor
     cc_ctx = engine._build_compressor_context()      # Task 3.2 已实现，复用同一构造逻辑
     stats = await compressor.check_and_compress(agent.context, cc_ctx, force=True)
     ```
  3. 若 `context_compressor` 尚未装配（非 interactive 场景），回退到 `registry.get(ContextCompressor, scope_key=agent.agent_id)`，并 `await compressor.initialize(agent_ref=AgentReferenceAdapter(agent), session_manager=..., config=agent.config)` 后再用
  4. 断言压缩后 `context` 正确重建、session memory 文件路径为 agent 级路径
- **预期产出**：修改后的 compact 命令
- **验收标准**：
  - [ ] `/compact` 走共享实例（`grep -c "ContextCompressor()" broca/commands/builtin/compact/__init__.py` 为 0）
  - [ ] 强制压缩跳过 token 阈值检查（构造小 context 也能压缩）
  - [ ] 压缩后 context 正确重建，session memory 文件被更新
  - [ ] `cc_ctx` 由 `execution_engine._build_compressor_context()` 构造（`grep -n "CompressorContext(" broca/commands/builtin/compact/__init__.py` 为 0）
  - [ ] 命令测试通过

#### Task 3.4: ContextCompressor 测试

- **目标**：更新和新增 ContextCompressor 测试
- **步骤**：
  1. 更新 `broca/tests/test_context_compressor.py`
  2. 新增测试：
     - `test_check_and_compress_below_threshold` — 不触发压缩
     - `test_check_and_compress_above_threshold` — 触发完整压缩流程
     - `test_force_compress_equals_force_flag` — `force_compress()` 与 `check_and_compress(force=True)` 结果一致
     - `test_keep_pivot_no_cross_turn` — 保留边界不跨 turn
     - `test_keep_pivot_within_keep_steps` — 保留最近 N 步
     - `test_compressor_context_only` — 只传 `CompressorContext`（不传 agent）即可工作
     - `test_reset_session_memory` — 清空 session memory 文件
  3. 适配 `broca/tests/session_memory/test_memory_manager.py`（**注意路径**：session memory 的测试在 `broca/tests/session_memory/`，不是 `broca/tests/persistent_memory/test_manager.py`；`SessionMemoryManager` 变为薄兼容层后，只保留路径属性与 `reset()` 的测试）
- **预期产出**：更新后的测试文件
- **验收标准**：
  - [ ] 所有 ContextCompressor 测试通过
  - [ ] 覆盖 token 阈值触发、强制压缩、pivot 边界、`reset_session_memory`
  - [ ] 不依赖 `Agent` 实例（使用 `CompressorContext` 桩对象）

#### Task 3.5: 清理 SessionMemoryManager 外部引用

- **目标**：让"`SessionMemoryManager` 不再被外部直接引用"这条 AC 真正落地
- **背景（已核实的引用点）**：
  - `broca/agent.py:227 _setup_session_memory()` 创建 `SessionMemoryManager(agent=self, ...)`
  - `broca/commands/builtin/clear_history/__init__.py:69-83`
  - `broca/commands/builtin/clear_context/__init__.py:57-71`
  - `broca/commands/builtin/clear_all_context/__init__.py:64-80`
- **步骤**：
  1. 删除 `Agent._setup_session_memory()` 与 `Agent.create()` 中的调用；`Agent` 不再持有 `session_memory_manager`
  2. 三个 clear 命令改为通过 `agent.execution_engine.context_compressor` 访问：`reset_session_memory()`、`snapshot_memory_path`、`memory_path`
  3. **门控改造**：`registry.get(ContextCompressor)` 永远返回实例（不会再是 `None`），因此三个命令必须显式判断 `agent.config.enable_context_compression`：
     ```python
     if not getattr(agent.config, "enable_context_compression", False):
         return   # 未启用压缩时不得触碰 session memory 文件
     compressor = agent.execution_engine.context_compressor
     compressor.reset_session_memory()
     ```
  4. 全仓搜索 `session_memory_manager`，确保除 `session_memory/` 包内部与兼容层本身外无引用
  5. 更新 `broca/tests/session_memory/test_memory_manager.py` / 命令测试
- **预期产出**：`broca/agent.py`、三个 clear 命令、相关测试的修改
- **验收标准**：
  - [ ] `grep -rn "session_memory_manager" broca --include=*.py | grep -v "session_memory/" | grep -v tests` 结果为 0
  - [ ] `clear_history` / `clear_context` / `clear_all_context` 三个命令的测试通过（含 session memory 文件清理断言）
  - [ ] `Agent` 实例上不再存在 `session_memory_manager` 属性
  - [ ] `enable_context_compression=False` 时三个 clear 命令**不创建也不删除** session memory 文件（`test_clear_without_compression_noop`）
  - [ ] `grep -rn "enable_context_compression" broca/commands/builtin/clear_*` 至少命中 3 处（门控显式存在）

---


### Phase 4: 核心循环组件化

**目标**：完成 `LoopEngine`、`LLMClient`、`PermissionProvider`、`Communicator` 的组件化，解除 `Agent ↔ LoopEngine` 的运行期双向引用

> **本 Phase 不创建 `AgentReferenceAdapter`**：`Agent` 自身结构化满足 `AgentReference` Protocol（有 `agent_id` / `session_id` / `turn_id` / 3 个回调），`Agent._setup_execution_engine()` 直接传 `agent=self` 即可。适配器文件在 **Task 6.1** 创建（届时组合根统一走 Registry，需要显式适配对象）。

**阶段验收标准**：
- [ ] `DefaultLoopEngine` 实现 `LoopEngine` ABC（`execute` / `abort` / `reset` / `initialize`）
- [ ] `LiteLLMClient` 实现 `LLMClient` ABC，且 `broca.llm.LLMClient` 别名保留（不破坏 `agent.py` / `agent_manager.py` / 测试的现有 import）
- [ ] `DefaultPermissionProvider` 合并了 `PermissionManager` + `ToolPermissionManager` 的职责，`set_state()` 模式被 `PermissionContext` 参数替代
- [ ] `SocketIOCommunicator` 实现 `Communicator` ABC
- [ ] `LoopEngine` 不出现 `Agent` 类型依赖（无 `agent` 属性、无 `self.agent.*`），改为 `agent_ref: AgentReference`
- [ ] 核心循环集成测试通过（LLM → 工具 → 结果 → 压缩，含并行/串行调度）

#### Task 4.1: LLMClient 接口化

- **目标**：为 LLM 调用定义抽象接口，保留向后兼容别名
- **步骤**：
  1. 在 `broca/components/llm_client.py` 中定义 ABC（Phase 1 已建，此处定稿）：
     ```python
     class LLMClient(BaseComponent, ABC):
         @abstractmethod
         def parse_message(self, provider: str, model: str, message: Message) -> dict: ...
         @abstractmethod
         async def get_stream_response(self, provider, model, messages, tools=None, **kwargs) -> AsyncGenerator[dict, None]: ...
         @abstractmethod
         def aggregate_message(self, content_chunks, tool_call_chunks) -> LLMMessage | None: ...
     ```
  2. `broca/llm.py` 的现有类改名为 `LiteLLMClient(LLMClient)`，**并在文件末尾保留别名**：
     ```python
     LLMClient = LiteLLMClient  # 向后兼容（broca.llm.LLMClient 仍可用）
     ```
  3. `LoopEngine` / `Agent` / `AgentFactory` 的类型注解改为引用 `broca.components.LLMClient`（ABC），实例仍可为 `LiteLLMClient`
- **预期产出**：`broca/components/llm_client.py`（ABC）+ 修改后的 `broca/llm.py`
- **验收标准**：
  - [ ] `issubclass(LiteLLMClient, LLMClient)` 为真
  - [ ] `from broca.llm import LLMClient` 仍可导入且 `LLMClient is LiteLLMClient`（兼容别名生效）
  - [ ] `broca/agent.py`、`broca/agent_manager.py`、`broca/tests/test_llm.py` 无需改动即可 import 通过
  - [ ] 现有 LLM 测试通过

#### Task 4.2: PermissionProvider 合并

- **目标**：将 `PermissionManager` + `ToolPermissionManager` 合并为统一的 `PermissionProvider` 接口
- **步骤**：
  1. 定义 `PermissionProvider` ABC（Phase 1 已建，此处定稿）：
     ```python
     class PermissionProvider(BaseComponent, ABC):
         # === 会话级权限请求（原 PermissionManager）===
         @abstractmethod
         async def request_permission(self, message: str, context: PermissionContext) -> bool: ...
         @abstractmethod
         async def request_tool_permission(self, tool_name: str, arguments: str, context: PermissionContext) -> tuple[bool, Optional[str]]: ...
         # === 工具权限配置（原 ToolPermissionManager）===
         @abstractmethod
         def get_tool_permission(self, tool_name: str) -> str: ...
         @abstractmethod
         def set_session_override(self, tool_name: str, permission: str) -> None: ...
         @abstractmethod
         def clear_session_overrides(self) -> None: ...
         @abstractmethod
         def get_all_permissions(self) -> dict[str, str]: ...
     ```
  2. `PermissionContext` Protocol：`turn_id` / `agent_id` / `session_id` / `communicator`（替代 `set_state()` 的隐式状态）
  3. 实现 `DefaultPermissionProvider(PermissionProvider)`——合并现有两个类的逻辑；`set_state()` 保留为 `@deprecated` 内部使用（读取 `PermissionContext` 优先）
  4. **逐个更新调用点**（已核实）：
     - `broca/agent.py:342` / `:370` 的 `permission_manager.set_state(...)` → 传 `PermissionContext`
     - `broca/loop_engine.py:733` 的 `self.agent.ask_for_tool_permission(...)` → 由 `ToolExecutor` 经 `PermissionProvider` 调用（Phase 2 已完成）
     - `broca/agent.py:281 _setup_permission_manager()` / `:255 _setup_tool_permission_manager()` → 合并为 `_setup_permission_provider()`
     - `broca-web/backend` 中权限相关 API（如存在）改为读 `PermissionProvider.get_all_permissions()`
  5. `ToolPermissionManager` **在本 Task 内直接删除**（Phase 4 结束时全部调用点已迁移，不留孤儿工作）：删除 `broca/tools/tool_permission_manager.py`，并同步删除 `broca/tests/test_tool_permission_manager.py`（其用例已并入 `test_permission_provider.py`）
- **预期产出**：`broca/components/permission_provider.py`（ABC）+ 合并后的实现
- **验收标准**：
  - [ ] `DefaultPermissionProvider` 实现所有抽象方法
  - [ ] `set_state()` 不再被 `Agent` 调用（`grep -n "set_state" broca/agent.py` 为 0）
  - [ ] `ToolExecutor` 通过 `PermissionProvider` 请求权限（`grep -n "tool_permission_manager" broca/tools/executor.py` 为 0）
  - [ ] 权限相关测试通过（`test_permission_manager.py` 适配 + 新增 `test_permission_provider.py` 全绿）
  - [ ] session override 行为与改造前一致（Phase 2.1 的 `test_session_override_persisted` 仍绿）
  - [ ] `grep -rn "ToolPermissionManager" broca --include=*.py | grep -v tests` 结果为 0
  - [ ] `broca/tools/tool_permission_manager.py` 已删除（`ls` 报不存在）

#### Task 4.3: Communicator 接口化

- **目标**：抽象通信层
- **步骤**：
  1. 定义 `Communicator` ABC（Phase 1 已建，此处定稿）：`send_message`、`send_error`、`send_turn_start/end`、`send_tool_call`、`send_permission_request`、`send_agent_system_message`、`connect`、`disconnect`、`register_event_handler`、`shutdown`
  2. `broca/communication/agent_communicator.py` 的 `AgentCommunicator` 改名为 `SocketIOCommunicator(Communicator)`，保留 `AgentCommunicator` 别名
  3. 所有 `agent.communicator` 的类型注解改为 `Communicator`
- **预期产出**：`broca/components/communicator.py`（ABC）+ 改名后的实现
- **验收标准**：
  - [ ] `issubclass(SocketIOCommunicator, Communicator)` 为真
  - [ ] `AgentCommunicator` 别名保留，现有 import 不破坏
  - [ ] 通信相关测试通过
  - [ ] `Communicator` 是 per-agent 作用域（`COMPONENT_SCOPES` 一致）

#### Task 4.4: LoopEngine 组件化

- **目标**：`LoopEngine` 定义 ABC 接口，`DefaultLoopEngine` 为默认实现，**并彻底移除对 `Agent` 类型的依赖**

- **步骤**：
  1. 定义 `LoopEngine` ABC（Phase 1 已建，此处定稿）：`async execute(message, max_steps=None, from_agent=False)`、`abort()`、`reset()`、`async initialize(**deps)`
  2. 现有 `LoopEngine` 拆分为 `LoopEngine`（ABC，放 `broca/components/loop_engine.py`）+ `DefaultLoopEngine`（实现，留在 `broca/loop_engine.py`）
  3. **完整依赖清单**（以真实 `__init__`（`loop_engine.py:92-205`）为准，**不是 5 个**）：

     | 参数 | 类型 | 来源 |
     |------|------|------|
     | `agent_ref` | `AgentReference` | 组合根传入（**Phase 4 直接传 `Agent`**，结构化满足 Protocol；Phase 6 起传 `AgentReferenceAdapter`） |
     | `llm_client` | `LLMClient` | Registry |
     | `context` | `Context` | 组合根创建（数据对象，非组件） |
     | `tool_mapping` | `dict[str, Tool]` | `ToolManager` |
     | `config` | `AgentConfig` | 组合根 |
     | `communicator` | `Communicator` | Registry（per-agent） |
     | `session_manager` | `SessionManager` | 组合根 |
     | `tool_executor` | `ToolExecutor` | Registry（per-agent） |
     | `context_compressor` | `ContextCompressor` | Registry（per-agent） |
     | `memory_manager` | `MemoryManager \| None` | Registry（per-agent） |
     | `tool_permission_provider` | `PermissionProvider` | Registry（per-agent），仅用于并行/串行分区回退 |
     | `step_max_errors` / `llm_retry_delay` / `tool_call_timeout` / `assign_task_timeout` | `int \| None` | 覆盖 config 中的 `execution_config` |
     | `snapshot_tracker` / `patch_calculator` | `SnapshotManager` 内部 | 组合根通过 `SnapshotManager` 提供（Phase 5） |

  4. **`AgentReference` Protocol 直接复用 Task 1.1 的定稿定义**（`broca/components/protocols.py`，含 `agent_id` / `session_id` / **可读写 `turn_id`** / `last_context_length` / 3 个回调）——**本 Task 不再重复声明第二份签名**，避免签名漂移；如需调整，回 Task 1.1 改并同步 AC
  5. **本 Phase 不创建适配器**：`Agent` 结构化满足 `AgentReference`，`Agent._setup_execution_engine()` 直接传 `agent=self`。适配器在 Task 6.1 创建，且**必须实现 `__getattr__` 透传**（见下）
  6. `_build_tool_context()` **保留** `ctx.agent = self.agent_ref`。语义要求：`ctx.agent` 最终必须是**能访问真实 Agent 属性的对象**——工具层真实用法包括 `context.agent.name`（`blackboard.py:267/530`、`task.py:117`）、`context.agent.config`（`image.py:104`、`agent_interaction.py:236`）、`context.agent.llm_client.config`（`image.py:240`）。Phase 6 传入 `AgentReferenceAdapter` 后，若适配器只代理 4 个成员，上述 6 个工具模块将 `AttributeError` → 因此适配器**必须**：
     ```python
     class AgentReferenceAdapter:
         def __init__(self, agent: "Agent"): self._agent = agent
         def __getattr__(self, name):            # 关键：未显式代理的属性透传到真实 Agent
             return getattr(self._agent, name)
         @property
         def agent_id(self) -> str: return self._agent.agent_id
         @property
         def session_id(self) -> str: return self._agent.session_id
         @property
         def turn_id(self) -> Optional[str]: return self._agent.turn_id
         @turn_id.setter
         def turn_id(self, value: Optional[str]) -> None: self._agent.turn_id = value
         @property
         def last_context_length(self) -> Optional[int]: return self._agent.last_context_length
         # on_llm_call_completed / ask_for_permission / ask_for_tool_permission 直接代理
     ```
  7. 删除 `LoopEngine.__init__` 中的 `self.agent = agent`、`self.persistent_memory_manager = getattr(agent, ...)` 等回溯式访问

- **预期产出**：重构后的 `broca/loop_engine.py` + `broca/components/loop_engine.py`（适配器文件由 Task 6.1 产出）
- **验收标准**：
  - [ ] `DefaultLoopEngine` 实现 `LoopEngine` ABC，`__abstractmethods__` 为空
  - [ ] `grep -n "self\.agent\." broca/loop_engine.py` 结果为 0（全部改走 `self.agent_ref.`）
  - [ ] `grep -n "agent: Any" broca/loop_engine.py` 结果为 0
  - [ ] `test_loop_engine_writes_turn_id_to_agent_ref`：`_start_new_turn()` 后 `engine.turn_id` 与 `agent_ref.turn_id` 同步（Phase 4 中 `agent_ref` 就是 `Agent`，验证写穿；适配器版本由 Task 6.3 覆盖）
  - [ ] `_build_tool_context()` 仍设置 `ctx.agent`，且 `ctx.turn_id` / `ctx.agent_id` 已填充（`test_tool_context_fields`）
  - [ ] `test_tools_receive_full_agent`：`ctx.agent.name`、`ctx.agent.config`、`ctx.agent.llm_client.config` 均可访问（Phase 4 传真实 Agent；Phase 6 传适配器后仍须通过）
  - [ ] 核心循环测试通过（LLM 调用 → 工具执行 → 步骤管理 → 死循环检测）

#### Task 4.5: 核心循环集成测试

- **目标**：编写覆盖完整 Agent 核心循环（LLM → 工具 → 结果 → 压缩）的集成测试，验证组件间协作与调度
- **步骤**：
  1. 创建 `broca/tests/test_execution_engine.py`
  2. 使用 Phase 1 建立的 `conftest.py` fixture（`mock_llm_client`、`mock_communicator`、`mock_permission_provider`、`fresh_registry`）
  3. 测试场景：
     - `test_execute_simple_response` — LLM 返回纯文本，无工具调用
     - `test_execute_single_tool_call` — 1 个工具调用 → ToolExecutor 执行 → 结果返回
     - `test_execute_parallel_tool_calls` — 3 个工具 → 并行执行 → 全部结果汇总
     - `test_execute_serial_mode` — `tool_execution_mode="serial"` 时按顺序执行
     - `test_ask_tools_executed_serially` — 含 `ask` 权限工具时被分区为串行执行（验证 `tool_executor.get_permission()` 分区逻辑）
     - `test_parallel_semaphore_limit` — `max_parallel_tools=2` 时并发不超过 2
     - `test_execute_with_permission_ask` — 权限 ask → 用户拒绝 → 错误返回 LLM
     - `test_execute_with_permission_forbidden` — forbidden → 直接返回错误
     - `test_context_compression_triggers` — 大 context → 压缩触发 → session memory 提取
     - `test_infinite_loop_detection` — 相同工具+参数重复 N 次 → 触发中断
     - `test_abort_mid_execution` — 执行中 abort → 当前步骤安全终止
     - `test_agent_reference_callbacks` — `agent_ref` 的 3 个回调（`on_llm_call_completed` / `ask_for_permission` / `ask_for_tool_permission`）被正确调用（**Phase 4 中 `agent_ref` 即 `Agent`；适配器代理由 Task 6.3 的 `test_agent_reference_adapter_full` 覆盖**）
     - `test_loop_engine_writes_turn_id_to_agent_ref` — 见 Task 4.4 AC（Phase 4 直传 Agent，不测适配器）
     - `test_tool_context_has_agent` — `ToolCallContext.agent` 为真实 Agent
  4. 每个测试使用 `ComponentRegistry` 组装完整组件栈（**per-agent 组件必须传 `scope_key`**），验证 Registry 路径正确
- **预期产出**：`broca/tests/test_execution_engine.py`（≥ 14 个测试函数）
- **验收标准**：
  - [ ] 14 个测试场景全部通过
  - [ ] 测试通过 `ComponentRegistry` 获取所有组件（不直接 `new`）
  - [ ] 验证了 `AgentReferenceAdapter` 的回调代理与 `turn_id` 写穿
  - [ ] 并行/串行两条路径都有断言，`asyncio.Semaphore` 限流有断言

---


### Phase 5: 支撑组件接口化（批量）

**目标**：完成 11 个 🟡 支撑组件的接口定义与默认实现适配（⚪ 基础设施组件见 Task 5.6，可选）

**并行性**：Task 5.1 / 5.2 / 5.3 / 5.4 **彼此独立，可并行执行**；Task 5.5 依赖 5.1~5.4 全部完成
> **合并冲突预防**：并行执行时，`defaults.py` / `COMPONENT_SCOPES` 的修改使用**追加模式**（各 sub-task 只 append 自己的条目）；PR 合并时取 union。若冲突频繁，退化为按 5.1→5.2→5.3→5.4 串行合并。

**统一约定（适用于本 Phase 所有组件）**：
- **ABC 命名**：一律用**裸名**（`SessionManager` / `ToolManager` / `AgentFactory`），实现类一律加前缀（`SQLSessionManager` / `AutoDiscoverToolManager` / `DefaultAgentFactory`）。禁止 `*ABC` 后缀（`SessionManagerABC` 之类），避免与实现类同名混淆
  - 旧 import 兼容：`from broca.session import SessionManager` 仍返回**实现类**（模块内保留 `SessionManager = SQLSessionManager` 别名）；类型注解一律用 `broca.components.*` 中的 ABC
- 接口文件放 `broca/components/<name>.py`，默认实现留在现有模块（或按"现状"列新建文件）
- 接口方法**只声明调用方真正使用的方法**（用 `grep -rn "<现有类名>(" broca --include=*.py` 清点调用点，不臆造方法）
- 需要运行期依赖（agent / workspace / session）的实现，一律走 `async initialize(**deps)`，不放构造参数
- 每个组件的 AC 统一包含三条：① `issubclass(默认实现, ABC)` ② `__abstractmethods__` 为空 ③ 调用方无直接实例化（`grep` 判据）

**阶段验收标准**：
- [ ] 11 个支撑组件的 ABC + 默认实现就位，且默认实现在 `defaults.py` / `COMPONENT_SCOPES` 中有映射
- [ ] 所有支撑组件的调用方通过接口类型引用（`grep` 判据逐条通过）
- [ ] 现有测试全部通过（各 Task 自行适配所属测试文件，不再集中到 5.5）
- [ ] 未破坏任何既有公共 API（保留旧类名别名）

#### Task 5.1: 持久化 / 快照组件

**5.1.1 `MemoryManager`**（现 `broca/persistent_memory/manager.py:PersistentMemoryManager`）

- ABC（`broca/components/memory_manager.py`）：`async check_and_extract(context, hint=None) -> bool`、`async trigger_extraction(context, hint) -> bool`、`increment_step()`、`reset()`
- 默认实现 `SubAgentMemoryManager`（`PersistentMemoryManager` 改名，保留 `PersistentMemoryManager` 别名）
- **关键改造**：现有构造为 `PersistentMemoryManager(agent=..., workspace=..., config=...)`（`agent.py:249`）→ 改为 `SubAgentMemoryManager()` + `async initialize(agent_ref, workspace, config)`，去掉构造期 agent 依赖
- 调用点：`broca/agent.py:243-253`、`broca/loop_engine.py:516-523`（Phase 3 已改为 `self.memory_manager`）
- **预期产出**：重构后的 `broca/persistent_memory/manager.py` + 新增 `broca/components/memory_manager.py`（ABC）
- AC：
  - [ ] `grep -n "PersistentMemoryManager(" broca --include=*.py` 只出现在 `defaults.py` 与测试
  - [ ] `grep -n "agent=self" broca/persistent_memory/manager.py` 为 0（改为 `initialize(agent_ref=...)`）
  - [ ] `test_memory_manager` 相关测试通过，`auto_extract` 保持 `increment_step()` 同步调用 + `asyncio.create_task(check_and_extract(...))` 后台执行 + `add_done_callback` 异常吞没的三要素不变

**5.1.2 `SnapshotManager`**（现 `broca/snapshot/track.py:SnapshotTracker` + `broca/snapshot/patch.py:PatchCalculator` + `broca/snapshot/git_manager.py`）

- ABC（`broca/components/snapshot_manager.py`）：`async track(workspace) -> str`、`async calculate_patch(from_hash, to_hash) -> dict`、`async acquire_lock()`、`async release_lock()`、`is_tracked() -> bool`
- 默认实现 `GitSnapshotManager`（新建 `broca/snapshot/manager.py`，内部组合 `SnapshotTracker` + `PatchCalculator` + `GitManager`，**不删除现有类**）
- 调用点：`broca/loop_engine.py:207-343`（`_initialize_snapshot_tracking` / `_capture_step_start_snapshot` / `_compute_step_end_patch` / `_capture_step_*`）
- **预期产出**：新增 `broca/snapshot/manager.py`（`GitSnapshotManager`）+ `broca/components/snapshot_manager.py`（ABC）
- AC：
  - [ ] `SnapshotManager` ABC 与 `GitSnapshotManager` 就位，`issubclass` 为真
  - [ ] `LoopEngine` 中快照相关逻辑改为调用 `self.snapshot_manager`（保留 `enable_snapshot_tracking` 门控）
  - [ ] Undo/Redo 命令测试（`test_undo` / `test_redo` 或等价）通过
  - [ ] 当 `git` 命令不存在或仓库未初始化时，`track()` 返回 `""`、`is_tracked()` 返回 `False`、不抛异常（与 `SnapshotTracker` 当前行为一致；测试 mock `shutil.which('git') → None`）

**5.1.3 `SessionManager`**（现 `broca/session/session_manager.py:SessionManager`）

- ABC（`broca/components/session_manager.py`）：仅声明调用方实际使用的方法（至少 `create_session`、`get_messages`、`save_message`、`start_turn`、`mark_messages_before_as_truncated`、`session_id` 属性）
- 默认实现 `SQLSessionManager`（现类改名；`broca/session/session_manager.py` 末尾保留 `SessionManager = SQLSessionManager` 别名以免破坏 import）
- 作用域：**per-session**
- **预期产出**：改名后的 `broca/session/session_manager.py`（`SQLSessionManager` + 别名）+ `broca/components/session_manager.py`（ABC）
- AC：
  - [ ] `issubclass(SQLSessionManager, broca.components.SessionManager)` 为真，且 `from broca.session import SessionManager` 仍返回实现类（`SessionManager is SQLSessionManager`）
  - [ ] `session_id` 可从接口访问
  - [ ] 以下测试文件全部通过：`broca/tests/session/test_database.py`、`broca/tests/session/test_turn_service.py`、`broca/tests/session/test_revert_service.py`、`broca/tests/test_session_delete_cleanup.py`

#### Task 5.2: 管理 / 工具组件

> 注：`AgentFactory`（🔴 核心）的接口化归属 **Phase 6.2**，不在本 Task；本 Task 只处理 🟡 支撑组件。

**5.2.1 `SkillManager`**（现 `broca/skill/skill_manager.py:SkillManager`）

- ABC：`get_skills(workspace, skill_names=None)`、`load_skill(name)`、`list_skills(workspace)`
- 默认实现 `FileSkillManager`（现类改名，`broca/skill/skill_manager.py` 末尾保留 `SkillManager = FileSkillManager` 别名）
- **注意**：仓库中当前**没有任何 skill 相关测试**（`find broca/tests -name "*skill*"` 为空），因此本 Task 必须自带测试
- **预期产出**：改名后的 `broca/skill/skill_manager.py`（`FileSkillManager` + 别名）+ `broca/components/skill_manager.py`（ABC）+ `broca/tests/test_skill_manager.py`
- AC：
  - [ ] `issubclass(FileSkillManager, broca.components.SkillManager)` 为真，别名保留
  - [ ] **新增** `broca/tests/test_skill_manager.py`（≥3 条）：`load_skill` 正常加载、`list_skills` 返回列表、未知 skill 返回空/`None` 且不抛异常
  - [ ] `pytest broca/tests/test_skill_manager.py -v` 通过

**5.2.2 `ProcessManager`**（现 `broca/process_manager.py:ProcessManager`）

- ABC：`start_process(...)`、`get_status(pid)`、`stop_process(pid)`、`list_processes()`、`cleanup()`
- 默认实现 `LocalProcessManager(ProcessManager)`（保留别名）
- **预期产出**：改名后的 `broca/process_manager.py`（`LocalProcessManager` + 别名）+ `broca/components/process_manager.py`（ABC）
- AC：
  - [ ] `issubclass` 为真，别名保留
  - [ ] `process_management` 工具测试通过
  - [ ] `shutdown()` 遍历 `list_processes()` 并逐一 `stop_process(pid)`，完成后 `list_processes()` 返回空列表；`stop_process()` 对已退出的 PID 不抛异常

**5.2.3 `Orchestrator`**（现 `broca/orchestration/orchestrator.py`，**已有 ABC**）

- 现状：已经是 ABC（`Orchestrator`），无需新建接口
- 工作内容：仅登记到 `DEFAULT_IMPLEMENTATIONS` 与 `COMPONENT_SCOPES`（`singleton`），并补充配对测试
- **预期产出**：`defaults.py` / `COMPONENT_SCOPES` 新增 `Orchestrator` 条目 + 配对测试
- AC：
  - [ ] `DEFAULT_IMPLEMENTATIONS` 中 `Orchestrator` 映射到现有实现
  - [ ] `COMPONENT_SCOPES[Orchestrator] == "singleton"`
  - [ ] 编排相关测试通过（`broca/tests/test_orchestration*.py` 或等价）

#### Task 5.3: 运行时 / 协议组件

**5.3.1 `SessionRunner`**（现 `broca/session_runner/manager.py:RunnerManager`）

- ABC：`async start_session(session_id, **kwargs)`、`async stop_session(session_id)`、`async send_command(session_id, command)`、`on(event, handler)`
- 默认实现 `IPCSessionRunner(SessionRunner)`（`RunnerManager` 改名 + 别名保留）
- **预期产出**：改名后的 `broca/session_runner/manager.py`（`IPCSessionRunner` + 别名）+ `broca/components/session_runner.py`（ABC）
- AC：
  - [ ] `issubclass` 为真，`RunnerManager` 别名保留
  - [ ] runner 启停与 IPC 测试通过
  - [ ] `shutdown()` 释放子进程（有测试断言无残留进程）

**5.3.2 `ToolManager`**（现 `broca/tools/tool_manager.py:ToolManager`，**单例**）

- ABC（`broca/components/tool_manager.py`，裸名 `ToolManager`）：`async init(workspace)`、`get_tools(tool_names)`、`async get_mcp_tools(server_names)`、`async load_custom_tools(workspace)`、`READONLY_TOOLS` 常量
- **`init()` 必须幂等**：`AgentFactory`（`agent_manager.py:176/261`）与 `Agent.create()`（Task 6.1）都会调用，重复调用不得重复建立 MCP 连接（有 `test_tool_manager_init_idempotent`）
- 默认实现 `AutoDiscoverToolManager`（现 `ToolManager` 改名，保留 `ToolManager = AutoDiscoverToolManager` 别名）：**去掉 `__new__` 单例拦截**（`tool_manager.py:49`），改为普通类；`READONLY_TOOLS` / `MODIFY_TOOLS` 保留为类常量
- **调用点必须同步改造**（否则多 Agent 共享工具表）：`broca/agent.py:183`、`broca/agent_manager.py:176/261`、`broca/tests/test_image_tool.py:162`
- 作用域：**per-agent**
- **预期产出**：改名后的 `broca/tools/tool_manager.py`（`AutoDiscoverToolManager` + 别名，去 `__new__` 单例）+ `broca/components/tool_manager.py`（ABC）+ 调用点改造
- AC：
  - [ ] `AutoDiscoverToolManager.__new__` 不再返回单例（`AutoDiscoverToolManager() is not AutoDiscoverToolManager()` 断言）
  - [ ] `grep -rn "ToolManager()" broca --include=*.py` 为 0（全部改 `registry.get(ToolManager, scope_key=agent_id)`）
  - [ ] 两个 Agent 的工具表互不影响（`test_two_agents_tool_isolation`）
  - [ ] **复核式判据**（`READONLY_TOOLS` 的迁移已在 Phase 2 Task 2.3 步骤 5 完成，本 Task 只验证）：`grep -rn "READONLY_TOOLS" broca --include=*.py` 仅命中 `tool_manager.py`（定义）、`tools/executor.py`（消费）与 `tests/`

**5.3.3 `MCPClient`**（现无类：`broca/tools/mcp.py:_build_client()` 函数 + `MCPTool`）

- ABC：`async connect(servers)`、`async get_tools(server_names) -> list[Tool]`、`async disconnect()`
- 默认实现 `StdMCPClient(MCPClient)`（新建 `broca/tools/mcp_client.py`，内部复用 `_build_client()` + `AsyncExitStack`）
- **说明**：这是"从零抽象"（当前无对应类），只为给 MCP 协议层一个可替换点；若评估后价值不足，可在本 Task 中标注"延后"，但需在报告中说明
- **预期产出**：新增 `broca/tools/mcp_client.py`（`StdMCPClient`）+ `broca/components/mcp_client.py`（ABC）
- AC：
  - [ ] `StdMCPClient` 可连接 mock server 并返回工具列表
  - [ ] `disconnect()` 正确释放连接（无 ResourceWarning）
  - [ ] 现有 MCP 工具测试通过

#### Task 5.4: 服务组件

**5.4.1 `CommandSystem`**（现 `broca/commands/manager.py:CommandManager`）

- ABC：`async initialize(agent)`、`parse(content) -> Optional[tuple[str, str]]`、`async dispatch(name, args, raw_input, **kwargs)`
- 默认实现 `FileCommandSystem(CommandSystem)`（`CommandManager` 改名 + 别名保留）
- **例外说明**：`initialize(agent)` 接收整个 Agent 是**允许的**（组合根内部），已写入"总体方案 · 通用规则 3"
- **预期产出**：改名后的 `broca/commands/manager.py`（`FileCommandSystem` + 别名）+ `broca/components/command_system.py`（ABC）
- AC：[ ] `issubclass` 为真；[ ] 命令解析/分发测试通过；[ ] `grep -n "CommandManager(" broca --include=*.py` 只出现在 `defaults.py` 与测试

**5.4.2 `TaskManager`**（现 `broca/task_manager.py:TaskManager`）

- ABC：仅声明 `task_management` 工具实际调用的方法（`create_task` / `get_task` / `update_task` / `search_tasks` / `add_comment` / `get_children` 等，按 `broca/tools/task.py` 调用点确定）
- 默认实现 `DBTaskManager(TaskManager)`（保留别名）
- **预期产出**：改名后的 `broca/task_manager.py`（`DBTaskManager` + 别名）+ `broca/components/task_manager.py`（ABC）
- AC：[ ] `issubclass` 为真；[ ] `task_management` 工具测试通过；[ ] 方法清单与 `broca/tools/task.py` 调用点一一对应（有 `inspect` 断言）

#### Task 5.5: 组件兼容性验证测试

- **目标**：为所有已接口化的组件编写 ABC-默认实现配对验证测试（**只做这一件事**；各 Phase 的测试适配已归属到产生变更的 Task）
- **步骤**：
  1. 创建 `broca/tests/test_component_compatibility.py`
  2. 参数化遍历 `DEFAULT_IMPLEMENTATIONS`，对每个 (接口, 默认实现) 对验证：
     - `issubclass(impl_cls, interface_cls)`
     - `impl_cls.__abstractmethods__` 为空集
     - `inspect.signature` 比对：ABC 抽象方法参数名 ⊆ 实现方法参数名（实现侧允许额外带默认值的参数）
     - `ComponentRegistry.resolve(interface)` 返回的类与 `defaults.py` 一致
     - `COMPONENT_SCOPES[interface]` 取值合法（`singleton`/`per-agent`/`per-session`/`transient`）
  3. 断言 `DEFAULT_IMPLEMENTATIONS` 的 key 集合与 `COMPONENT_SCOPES` 的 key 集合完全一致
- **预期产出**：`broca/tests/test_component_compatibility.py`
- **验收标准**：
  - [ ] 所有已接口化组件的配对测试通过
  - [ ] 所有 `@abstractmethod` 在默认实现中均已覆盖
  - [ ] 签名兼容性由机械断言保证（非人工比对）
  - [ ] `DEFAULT_IMPLEMENTATIONS` 与 `COMPONENT_SCOPES` key 集合一致
  - [ ] `pytest broca/tests/ -v` 全量通过

#### Task 5.6: 基础设施组件（⚪ 可选，允许延后）

- **目标**：为 5 个基础设施组件提供"最小可替换点"，**不改造调用方**
- **范围**：
  | 组件 | 现状 | 包法 |
  |------|------|------|
  | `ContentSecurityScanner` | `broca/utils/content_security.py:scan_content_security()` 函数 | `RegexContentScanner` 内部调用该函数，`scan(content) -> Optional[str]` |
  | `Scheduler` | `broca/scheduler.py:Scheduler`（已有类） | `APSchedulerAdapter`：`start()` / `shutdown()` / `add_job()` / `remove_job()` / `pause_job()` / `resume_job()` / `list_jobs()` / `get_job()` / `execute_job_now()`，内部委托现有类 |
  | `ErrorStrategy` | 只有 `errors/types.py:ErrorCode` 枚举 | `DefaultErrorStrategy`：`classify(error) -> ErrorCode`、`should_retry(error, attempt) -> bool`、`format_for_user(error) -> str`，逻辑从 `loop_engine._call_llm_with_retry` / `_send_execution_error` 提炼（**不改变现有控制流**） |
  | `ConfigManager` | `configs.py:get_configs()` 函数 | `FileConfigManager.get_configs()` / `get_agent_config(name)` / `get_llm_config()`，内部调用现有函数 |
  | `Logger` | `logging_config.py:LoggingConfig` + `get_logger()` | `LoguruLogger.get_logger(name)`，内部调用现有 `get_logger()` |
- **步骤**：定义 ABC + 默认实现 + `defaults.py` 映射 + 配对测试；**不改动任何调用方代码**
- **验收标准**：
  - [ ] 5 个组件 `issubclass` + `__abstractmethods__` 测试通过
  - [ ] 默认实现行为与直接调用现有函数/类**完全一致**（对比测试）
  - [ ] 无任何既有模块的 import 发生变化（`git diff --stat` 只涉及 `broca/components/` 与 `defaults.py`）
- **决策（二选一，必须明确写在执行报告中）**：
  - **方案 A（推荐，时间紧时）**：本 Task 整体延后 → `COMPONENT_SCOPES` 只覆盖 18 个组件，Phase 5 AC 注明"基础设施 5 个未接口化"，**不写薄实现**
  - **方案 B**：本期完成 → 5 个默认实现均为**薄包装（每个 ≤ 15 行、0 专属测试）**，仅满足 `issubclass` + 行为一致性对比测试
  - 禁止"延后但仍要求写薄实现"的混合态（那等于没延后）

---


### Phase 6: Agent 组合根重构

**目标**：重构 `Agent.create()` 为基于 ComponentRegistry 的组合根，按作用域取实例、按拓扑序 `initialize()`，彻底解除 `Agent ↔ LoopEngine` 的运行期双向引用

**阶段验收标准**：
- [ ] `Agent.create()` 通过 `ComponentRegistry` 获取所有组件实例，且 **per-agent 组件一律传 `scope_key=agent_id`**
- [ ] `Agent` 不再直接 `new` 任何组件（`grep` 判据）
- [ ] `Agent ↔ LoopEngine` 双向引用已解除（`LoopEngine` 侧无 `Agent` 类型依赖）
- [ ] 两个 Agent 实例的 per-agent 组件完全隔离（有测试）
- [ ] 所有 Agent 创建/恢复流程测试通过
- [ ] 完整 Agent 执行流程（消息→LLM→工具→结果）端到端测试通过

#### Task 6.1: 重构 Agent.create()

- **目标**：`Agent.create()` 使用 ComponentRegistry 按**作用域 + 拓扑序**组装所有组件
- **步骤**：
  1. 重构 `Agent.create()`：
     ```python
     @classmethod
     async def create(cls, config, llm_client, session_manager, **kwargs) -> "Agent":
         registry = ComponentRegistry.get_instance()
         registry.register_defaults()
         registry.load_config_overrides(getattr(config, "workspace", None))
         registry.discover_plugins()          # 只枚举 entry points（不 load）；按接口惰性加载

         agent = cls.__new__(cls)
         Agent.__init__(agent, config, llm_client, session_manager, **kwargs)
         key = agent.agent_id                 # per-agent 组件的 scope_key

         # ── 1. 无运行期依赖的组件：先构造 ────────────────────────────
         agent.context = Context(config, session_manager, **kwargs)
         agent.permission_provider = registry.get(PermissionProvider, scope_key=key)
         agent.communicator = registry.get(Communicator, scope_key=key)

         # ── 2. 按拓扑序 initialize（无依赖的在前）────────────────────
         await agent.communicator.initialize(
             agent_id=key, session_id=session_manager.session_id, config=config
         )
         await agent.permission_provider.initialize(
             communicator=agent.communicator,
             session_manager=session_manager,
             config=config,
         )

         # ── 3. 工具层 ───────────────────────────────────────────────
         agent.tool_manager = registry.get(ToolManager, scope_key=key)
         await agent.tool_manager.init(config.workspace)
         await agent._setup_tools()           # 填充 agent.tool_mapping

         # ── 4. 执行层组件（依赖 tool_mapping / permission_provider）──
         tool_executor = registry.get(ToolExecutor, scope_key=key)
         await tool_executor.initialize(
             tool_mapping=agent.tool_mapping,
             permission_provider=agent.permission_provider,
             config=config,
             communicator=agent.communicator,
         )
         context_compressor = registry.get(ContextCompressor, scope_key=key)
         await context_compressor.initialize(
             agent_ref=AgentReferenceAdapter(agent),
             session_manager=session_manager,
             config=config,
         )
         memory_manager = registry.get(MemoryManager, scope_key=key)
         await memory_manager.initialize(
             agent_ref=AgentReferenceAdapter(agent),
             workspace=config.workspace,
             config=config,
         )

         # ── 5. 执行引擎（依赖上面全部）──────────────────────────────
         agent.execution_engine = registry.get(LoopEngine, scope_key=key)
         await agent.execution_engine.initialize(
             agent_ref=AgentReferenceAdapter(agent),
             llm_client=llm_client,
             context=agent.context,
             tool_mapping=agent.tool_mapping,
             config=config,
             communicator=agent.communicator,
             session_manager=session_manager,
             tool_executor=tool_executor,
             context_compressor=context_compressor,
             memory_manager=memory_manager,
             tool_permission_provider=agent.permission_provider,
         )

         # ── 6. 命令系统（唯一允许拿到整个 Agent 的组件）──────────────
         agent.command_manager = registry.get(CommandSystem, scope_key=key)
         await agent.command_manager.initialize(agent)

         return agent
     ```
  2. 创建 `AgentReferenceAdapter`（放 `broca/agent_reference.py`，避免与 `agent.py` 形成新的导入环）：`agent_id` / `session_id` / **可读写 `turn_id`** / `last_context_length` / `on_llm_call_completed` / `ask_for_permission` / `ask_for_tool_permission`，**并且必须实现 `__getattr__` 透传**（`def __getattr__(self, name): return getattr(self._agent, name)`）
     - 原因：`ToolCallContext.agent` 会被赋为该适配器，而 6 个工具模块会访问 `agent.name` / `agent.config` / `agent.llm_client.config`；无透传则 Phase 6 后 `AttributeError`
  3. 删除 `_setup_context` / `_setup_communicator` / `_setup_session_memory` / `_setup_persistent_memory` / `_setup_permission_manager` / `_setup_tool_permission_manager` / `_setup_execution_engine` / `_setup_command_system` 这 8 个 `_setup_*` 方法（逻辑已内联到 `create()`）；若 `broca-web` / `broca-tui` 有调用，保留为 `@deprecated` 包装——**包装体内部为 `pass`（no-op）+ `logger.warning("...已废弃，请在 create() 前完成配置")`**；执行前先 `grep -rn "_setup_" broca-web/ broca-tui/` 确认调用点
  4. `Agent` 保留向后兼容属性：`permission_manager`（→ `permission_provider` 别名）、`communicator`、`command_manager`
  5. 新增 `Agent.disconnect()`（若已存在则改造）：**逆拓扑序**收尾 —— `execution_engine.abort()` → 各组件 `shutdown()`（逆序：`loop_engine` → `tool_executor` → `context_compressor` → `memory_manager` → `permission_provider` → `communicator`，仅调用声明了 `shutdown()` 的组件）→ `registry.release(agent_id)` 释放该 agent 的全部 per-agent 实例
     ```python
     async def disconnect(self):
         self.execution_engine.abort()                      # 先停掉在飞任务
         for comp in (self.execution_engine, self.execution_engine.tool_executor,
                      self.execution_engine.context_compressor,
                      self.execution_engine.memory_manager,
                      self.permission_provider, self.communicator):
             if comp is not None and hasattr(comp, "shutdown"):
                 await comp.shutdown()
         ComponentRegistry.get_instance().release(self.agent_id)
     ```
     - 说明：契约表中当前只有 `Communicator`（+ 支撑组件 `SessionRunner` / `ProcessManager`）有 `shutdown()`，`Agent` 直接持有的 6 个组件里仅 `communicator` 命中，因此**顺序断言只看 `shutdown` 会恒真**。为保证可验证，`disconnect()` 的语义定为"**`abort()` → `shutdown()` → `release()` 三段有序**"，用 spy 断言该序列
- **预期产出**：重构后的 `broca/agent.py` + 新增 `broca/agent_reference.py`
- **验收标准**：
  - [ ] `grep -nE "= (AgentCommunicator|SocketIOCommunicator|PermissionManager|ToolPermissionManager|ToolManager|LoopEngine|SessionMemoryManager|PersistentMemoryManager|CommandManager)\(" broca/agent.py` 结果为 0（**不含 `Context`**）
  - [ ] `grep -c "= Context(" broca/agent.py` **恰好为 1**（`Context` 是数据对象，允许在组合根创建一次）
  - [ ] 所有 per-agent 组件的 `registry.get(...)` 调用都带 `scope_key=key`
  - [ ] `AgentReferenceAdapter` 的 3 个回调 + `turn_id` 读写均正确代理（`test_agent_reference_adapter_full`）
  - [ ] `initialize()` 调用顺序符合拓扑序（`test_create_initialize_order`：communicator → permission → tool_manager → tool_executor → compressor → memory → loop_engine）
  - [ ] 创建后所有组件正确连接（`agent.execution_engine.tool_executor is tool_executor` 等断言）
  - [ ] 两个 Agent 的 `communicator` / `tool_executor` / `loop_engine` 互不相同（`test_two_agents_isolated`）
  - [ ] `test_tools_receive_full_agent`：经适配器后 `ctx.agent.name` / `.config` / `.llm_client.config` 均可访问
  - [ ] `test_disconnect_releases_scope`：用 spy 记录调用序列，断言 **`execution_engine.abort()` → `communicator.shutdown()` → `registry.release(agent_id)`** 三段有序；且 `release` 后该 agent 的 per-agent 实例已清空（`get(..., scope_key=agent_id)` 返回新实例）
  - [ ] `ToolExecutor.initialize()` 调用参数与 ABC 一致（`communicator` 有传，**`allowed_tools` 未传**）

#### Task 6.2: AgentFactory 组件化

- **目标**：`AgentFactory` 实现 `AgentFactory` ABC，并通过 Registry 创建 Agent
- **步骤**：
  1. `broca/agent_manager.py:AgentFactory` 改为 `DefaultAgentFactory(broca.components.AgentFactory)`，模块内保留 `AgentFactory = DefaultAgentFactory` 别名
  2. 去除 `AgentFactory` 的单例模式（若有），改为 `registry.get(AgentFactory)`（singleton 作用域）
  3. `DefaultAgentFactory` 内部调用 `Agent.create()`（不重复组装逻辑）
  4. `broca/session_runner/`、`broca/context_compressor.py`（子代理提取）中的 `AgentFactory()` 改为 `registry.get(AgentFactory)`
- **预期产出**：修改后的 `broca/agent_manager.py`
- **验收标准**：
  - [ ] `issubclass(DefaultAgentFactory, broca.components.AgentFactory)` 为真，`AgentFactory` 别名保留
  - [ ] `grep -rn "AgentFactory()" broca --include=*.py` 为 0
  - [ ] Agent 创建统一走 `Agent.create()`（`grep -c "Agent.create(" broca/agent_manager.py` ≥ 1）
  - [ ] Agent 恢复流程测试通过（`test_agent_restore_from_session`）
  - [ ] 子代理（session memory 提取、`assign_task`）仍能正常创建

#### Task 6.3: Agent 组合集成测试

- **目标**：验证组合根组装的完整组件栈工作正确，覆盖作用域隔离、生命周期顺序、循环引用解除
- **步骤**：
  1. 创建 `broca/tests/test_agent_composition.py`
  2. 测试场景：
     - `test_agent_create_with_defaults` — 不配置插件 → `Agent.create()` 成功 → 所有组件为默认实现
     - `test_agent_create_with_custom_tool_executor` — 通过 `components.json` 替换 `ToolExecutor` → 工具执行走自定义实现
     - `test_agent_create_with_custom_llm_client` — 替换 `LLMClient` → LLM 调用走自定义实现
     - `test_two_agents_isolated` — 两个 Agent 的 per-agent 组件互不相同、互不影响（**替代原 `test_no_circular_import`**）
     - `test_agent_reference_adapter_full` — 3 个回调 + `turn_id` 读写代理
     - `test_create_initialize_order` — `initialize()` 调用顺序符合拓扑序
     - `test_loop_engine_has_no_agent_dependency` — 断言 `LoopEngine` 实例无 `agent` 属性，且 `inspect.signature(DefaultLoopEngine.initialize)` 中不出现 `agent: Agent`（**原 `test_no_circular_import` 改造前就会通过，无鉴别力，已替换**）
     - `test_agent_full_lifecycle` — 创建 → 发消息 → LLM 响应 → 工具执行 → 结果保存 → 关闭
     - `test_agent_restore_from_session` — 从 session 恢复 → 组件栈重建 → 状态正确
     - `test_tools_receive_full_agent` — `ctx.agent.name` / `.config` / `.llm_client.config` 均可访问（适配器 `__getattr__` 透传生效）
     - `test_disconnect_releases_scope` — `Agent.disconnect()` 按逆拓扑序 `shutdown()`，且 `registry.release(agent_id)` 后 per-agent 实例清空
  3. 使用 `fresh_registry` fixture 隔离每个测试；使用 `mock_llm_client` 避免真实 API 调用
- **预期产出**：`broca/tests/test_agent_composition.py`（≥ 11 个测试函数）
- **验收标准**：
  - [ ] 11 个测试场景全部通过
  - [ ] per-agent 作用域隔离有断言（同接口不同 `scope_key` 不同实例）
  - [ ] 自定义组件通过 `components.json` 正确替换
  - [ ] `LoopEngine` 无 `Agent` 类型依赖有机械断言
  - [ ] `test_no_circular_import` 已删除或改为更严格的等价断言
  - [ ] 工具层拿到的是可访问完整 Agent 属性的对象（`test_tools_receive_full_agent`）

---


### Phase 7: 集成验证

**目标**：全量验证组件化改造后的系统正确性，并验证两条硬约束（懒加载 / 零启动开销）

**阶段验收标准**：
- [ ] `pytest broca/tests/` 全部通过，测试总数 ≥ 600（若 Task 5.5 不做参数化则 ≥ 590，与覆盖率要求节一致）
- [ ] `pytest broca-web/tests/` 全部通过（**基线要求**：改造前先记录该套件的通过/失败清单，改造后不得出现新增失败）
- [ ] `pytest broca-tui/tests/` 全部通过（同上）
- [ ] 核心模块行覆盖率 ≥ 80%（`broca/components/`、`executor.py`、`loop_engine.py`、`context_compressor.py`、`agent.py`）
- [ ] 插件加载机制端到端测试通过（`test_plugin_loading.py`）
- [ ] 10 个 E2E 回归场景全部通过（`test_e2e_scenarios.py`）
- [ ] **懒加载硬断言**通过（`test_startup_overhead.py`）：未使用的插件模块不进入 `sys.modules`，且 `discover_plugins()` 未调用 `ep.load()`
- [ ] 启动耗时回归 ≤ **+15%**（`@pytest.mark.perf`，默认跳过、CI 单独跑），并附基线测量报告
- [ ] 脚本化验证：运行 `scripts/verify_agent_e2e.py`（由 Task 7.2 创建），日志中出现 `tool_call_start → tool_result → turn_end` 且 `session-memory.md` 被更新
- [ ] 组件配置覆盖验证：通过 `components.json` 替换一个组件后系统正常工作

#### Task 7.1: 全量测试 + 覆盖率对比

- **步骤**：
  1. **改造前基线记录**（应在 Phase 1 之前完成一次）：
     - `pytest broca/tests/ --collect-only -q | tail -1` → 应为 **522**（已实测）
     - `pytest broca-web/tests/ -q` 与 `pytest broca-tui/tests/ -q` 的通过/失败清单（作为"不得新增失败"的基线）
  2. 运行 `pytest broca/tests/ -v --tb=short`，修复所有因接口变更导致的测试失败
  3. 运行 `pytest broca-web/tests/ -v --tb=short`、`pytest broca-tui/tests/ -v --tb=short`
  4. 运行覆盖率报告：`pytest broca/tests/ --cov=broca --cov-report=term-missing --cov-report=html`
  5. 对比改造前/后覆盖率（核心模块 ≥ 80%）
  6. 特别关注（**注意路径**）：
     - `broca/tests/test_loop_engine.py`
     - `broca/tests/test_context_compressor.py`
     - `broca/tests/session_memory/test_memory_manager.py`（session memory，**不是** `broca/tests/persistent_memory/test_manager.py`）
     - `broca/tests/persistent_memory/test_manager.py`（persistent memory，受 Task 5.1.1 影响）
     - `broca/tests/test_llm.py`、`broca/tests/test_permission_manager.py`、`broca/tests/test_tool_base.py`
     - `broca/tests/test_tool_permission_manager.py` 应在 Task 4.2 中已删除
  7. 检查是否有测试被 `pytest.mark.skip` 跳过——所有跳过必须附带理由和 TODO 注释
- **验收标准**：
  - [ ] `pytest broca/tests/` 全部通过，无跳过（或所有跳过有理由）
  - [ ] `broca-web` / `broca-tui` 无新增失败（与基线对比）
  - [ ] 总测试数 ≥ 600
  - [ ] 核心模块行覆盖率 ≥ 80%
  - [ ] 无新增的 `pytest.mark.skip`

#### Task 7.2: 插件加载验证 + E2E 回归测试

- **步骤**：
  1. **插件包测试**（`broca/tests/test_plugin_loading.py`）：
     - 最小化测试插件 `MockSandboxToolExecutor`（实现 `ToolExecutor` ABC）
     - entry point 发现：monkeypatch `entry_points()` 返回测试插件 → `ComponentRegistry` 正确发现
     - 配置覆盖：写入 `components.json` → `resolve()` 返回测试插件
     - 默认回退：不配置任何插件 → 使用 `DefaultToolExecutor`
     - 错误处理：配置了不存在的类名 → 抛 `ComponentError` 且消息包含配置路径/key/原始值；**且 Agent 仍能启动**（warn + 回退）
     - 多插件冲突：两个 entry point 注册同一接口 → 断言优先级行为（后注册覆盖或抛错，二选一并测试）
     - **作用域**：插件替换后，两个 Agent 仍拿到各自实例
  2. **E2E 回归测试**（`broca/tests/test_e2e_scenarios.py`）：执行"测试策略"章节的 10 个场景
  3. E2E 使用 `ComponentRegistry` + mock LLM/Communicator（不依赖真实 SocketIO）
  4. **创建 `scripts/verify_agent_e2e.py`**（供 Phase 7 阶段 AC 使用）：
     - 用 `tmp_path` workspace + mock LLM/Communicator 组装一个真实 `Agent`（走 `Agent.create()`）
     - 跑一轮含工具调用的对话，断言日志/事件序列含 `tool_call_start → tool_result → turn_end`
     - 断言 `session-memory.md` 的 mtime 被更新（先构造大 context 触发压缩）
     - 退出码 0/1，可直接在 CI 中运行：`python scripts/verify_agent_e2e.py`
- **预期产出**：`broca/tests/test_plugin_loading.py`、`broca/tests/test_e2e_scenarios.py`、`scripts/verify_agent_e2e.py`
- **验收标准**：
  - [ ] 插件发现、配置覆盖、默认回退、错误处理、多插件冲突、作用域 6 类场景全部通过
  - [ ] 10 个 E2E 回归场景全部通过
  - [ ] 模拟插件替换 `ToolExecutor` 后，工具执行走插件实现
  - [ ] 错误配置不会导致系统崩溃（有 fallback 且日志含配置路径）
  - [ ] `python scripts/verify_agent_e2e.py` 退出码 0，且输出包含 `tool_call_start` / `tool_result` / `turn_end` 三行

#### Task 7.3: 启动开销与懒加载验证（新增，对应概述中的硬约束）

- **步骤**：
  1. 创建 `broca/tests/test_startup_overhead.py`（**三重判据**，前两条为硬断言，第三条为软断言）
  2. **硬断言 1** `test_discover_plugins_does_not_load`：用 `unittest.mock.patch` 包装 `EntryPoint.load`，调用 `discover_plugins()` 后断言 **`load` 调用次数为 0**（发现阶段只枚举）
  3. **硬断言 2** `test_unresolved_interface_plugin_not_imported`：假插件 `tests/_fake_plugin.py` 注册在**本测试不 resolve 的接口**（如 `scheduler`）上；monkeypatch `entry_points()` 后 `discover_plugins()` + `resolve(ToolExecutor)`，断言 `"_fake_plugin" not in sys.modules`
     - **前提必须写进测试**：假插件注册的接口 ≠ 被测 resolve 的接口，否则"惰性加载"与"插件生效"两条要求互相矛盾
  4. **正向用例** `test_resolve_lazily_loads_registered_plugin`：`resolve(scheduler)` 时才 import 该插件模块（`"_fake_plugin" in sys.modules`），第二次 resolve 不重复 load
  5. `test_agent_create_no_plugin_load`：`Agent.create()` 全程断言 `sys.modules` 中不含第三方插件模块
  6. **软断言** `test_startup_time_regression`（标记 `@pytest.mark.perf`，**默认跳过**，CI 单独运行）：`time.perf_counter()` 取 20 次 `Agent.create()` 中位数，断言劣化 ≤ **15%**（CI 抖动容忍；±5% 会频繁假失败）
  7. 基线测量脚本 `scripts/bench_startup.py`（同时记录 `import broca` 与 `Agent.create()` 两项，输出 CSV 便于对比）
- **预期产出**：`broca/tests/test_startup_overhead.py`、`scripts/bench_startup.py`
- **验收标准**：
  - [ ] 硬断言 1（`discover_plugins()` 不 load）与硬断言 2（未 resolve 的插件不 import）通过，且正向用例（resolve 后确实 load）通过（不依赖耗时，CI 稳定）
  - [ ] 软断言（perf）在 CI 单独运行时劣化 ≤ 15%，且基线数值与测量方法写入测试注释
  - [ ] `pytest broca/tests/ -q` 默认不运行 perf 测试（`addopts` 或 marker 配置正确）

#### Task 7.4: 文档与示例

- **步骤**：
  1. 更新 `README.md` 添加组件化架构说明
  2. 创建 `docs/plugin-development-guide.md`——第三方插件开发指南（组件清单、作用域、`initialize` 契约、`components.json`、entry point）
  3. 创建**可运行示例** `examples/plugins/sandbox_tool_executor/`（含 `pyproject.toml` + 实现 + README），并提供 `examples/plugins/sandbox_tool_executor/test_example.py`
  4. 创建示例：如何替换 `LLMClient` 为本地模型（`examples/plugins/local_llm_client/`）
  5. 文档中明确声明**插件信任边界**：插件是进程内任意代码，可访问 `ToolCallContext.agent`（含 config / session manager / 文件系统）
- **预期产出**：`README.md` 更新 + `docs/plugin-development-guide.md` + 2 个可运行示例
- **验收标准**：
  - [ ] `examples/plugins/*/test_example.py` 全部通过（`pytest examples/plugins/ -q`）
  - [ ] 文档包含至少 2 个可运行代码示例（sandbox_tool_executor + local_llm_client），每个含 `pyproject.toml` 的 `[project.entry-points."broca.components"]` 配置片段
  - [ ] 文档包含组件作用域表与 `initialize` 契约说明
  - [ ] 文档包含插件信任边界声明

---


## 风险与应对

| # | 风险 | 影响 | 应对策略 |
|:-:|------|------|----------|
| 1 | **注册表作用域错误**：以接口类型为唯一 key 做单例缓存，导致 `Communicator` / `LoopEngine` / `ToolExecutor` / `ContextCompressor` / `MemoryManager` 等 per-agent 组件被多 Agent 共用 | 🔴 高——多 Agent、`assign_task` 子 Agent、会话恢复全部串台 | 组件作用域表（总体方案）+ `ComponentRegistry.get(interface, scope_key=...)` + `COMPONENT_SCOPES` 一致性测试 + `test_two_agents_isolated`（Task 6.3） |
| 2 | **工具执行管道行为漂移**：超时跳过规则（`ask_user` / `bash background`）、`assign_task` 独立超时、`allowed_tools` 白名单、session override、tool_call 广播在提取时被遗漏 | 🔴 高——静默改变行为，测试可能仍绿 | **先写 11 条 characterization test 再重构**（Task 2.1，覆盖职责 #1~#8）；Task 2.2 按真实执行顺序逐项迁移；Phase 2 AC 以 grep 判据兜底 |
| 3 | `AgentReference` 适配器能力不足：`turn_id` 需**可写**（`loop_engine.py:1389`）；`ToolCallContext.agent` 被 6 个工具模块依赖（`agent.name` / `agent.config` / `agent.llm_client.config`），无法窄化 | 🔴 高——赋值抛 `AttributeError` / 工具层失效 | Protocol 声明 setter 与 `last_context_length`；适配器提供 setter **+ `__getattr__` 透传到真实 Agent**（Task 4.4 步骤 6 / Task 6.1 步骤 2）；AC `test_tools_receive_full_agent` 断言 `ctx.agent.name` / `.config` / `.llm_client.config` 可访问 |
| 4 | 23 个组件接口定义不准确，后续需要修改 | 🟡 中——接口变更影响所有实现 | Phase 1 只定 7 个核心接口，其余随实现增量定义；`inspect.signature` 机械比对（Task 5.5）；不靠人工读代码 |
| 5 | 运行期双向引用（Agent ↔ LoopEngine）难以完全解除 | 🟡 中——可能残留部分引用 | `AgentReference` Protocol + `AgentReferenceAdapter`；AC 用 `grep -n "self\.agent\."` 判据；`test_loop_engine_has_no_agent_dependency` |
| 6 | `SessionMemoryManager` 合入 `ContextCompressor` 后职责边界模糊（兼容层反向委托形成循环） | 🟡 中——维护者困惑 | 定死终态：`SessionMemoryManager` 只保留路径属性 + `reset()`，不做逻辑委托；Task 3.5 清理全部外部引用 |
| 7 | 第三方插件信任/安全：插件是进程内任意代码，可经 `ToolCallContext.agent` 访问 config / session / 文件系统 | 🟡 中——供应链风险 | 文档明确信任边界（Task 7.4）；`components.json` 变更记 info 日志；预留 `BROCA_ALLOW_PLUGINS` 开关设计（本期不实现，仅在文档说明） |
| 8 | 启动开销回归：entry points 发现 / 组件装配增加启动耗时 | 🟡 中——违反"零开销"约束 | `discover_plugins()` 只解析不 `ep.load()`；`test_startup_overhead.py` 软断言 ≤ +15%（CI 容忍）、目标 ≤ +5%（优化参考），且插件模块不进入 `sys.modules`（Task 7.3） |
| 9 | 大规模重构导致回归 bug | 🟡 中——影响生产 | 每个 Phase 完成后跑全量测试；characterization test 兜底；Phase 7 含 10 个 E2E 场景 |
| 10 | 7 个 Phase / **32 个 Task**（31 必做 + 1 可选）长周期重构导致分支漂移、合并冲突（触碰 ~30 个文件，`loop_engine.py` 被 **4 个 Phase** 修改：2.3 工具委托 / 3.2 post-step hooks / 4.4 `agent_ref` / 5.1.2 snapshot） | 🟡 中——进度与质量风险 | 每个 Phase AC 要求"结束时全绿且可独立合并"；**建议把 Task 5.1.2 的 snapshot 改造提前到 Phase 4.4 一并做**（同为 `__init__` 依赖注入变更），把 4 次触碰压到 3 次；Phase 2 起就引入 `agent_ref` 形态以减少返工 |
| 11 | 测试 mock 与实际行为偏差（mock LLM 无法覆盖流式边界） | 🟡 中——测试通过但线上异常 | Phase 4.5/7.2 的 E2E 使用接近真实的流式响应模式；保留 1-2 个真实 API smoke test（`@pytest.mark.integration`） |
| 12 | 组件间接口参数过多，ABC 设计过度或不足 | 🟡 中——太宽难实现，太窄无法扩展 | 只声明调用方真正使用的方法（`grep` 清点）；Protocol 用结构化类型（非继承）降低耦合 |
| 12b | **per-run 可变状态迁移丢失**：`allowed_tools` 与 `namespace` 是 `agent.run()` 的逐次状态（`agent.py:465/466` 设置、`:481` 复位），组件化后容易被"下沉"到组件构造期而静默失效 | 🔴 高——白名单/命名空间静默失效 | `allowed_tools` 保留在 `LoopEngine` 并逐次传给 `execute_tool()`（Task 2.3 步骤 2）；Task 2.1 增加 `test_run_scoped_allowed_tools_reset`；Task 2.3 AC 断言 `agent.py:465/466/481` 未被修改 |
| 13 | litellm API 变化导致 `LLMClient` 接口不稳定 | 🟢 低 | `LiteLLMClient` 内部封装 litellm 细节，ABC 只暴露 `get_stream_response()` 等稳定方法 |
| 14 | Phase 2.4 的 `Agent.create()` 中间状态与 Phase 6.1 最终状态差异大 | 🟢 低——代码可读性 | Task 2.4 明确注释"中间步骤，Phase 6.1 彻底重构"；commit message 标注 |
| 15 | 现有用户配置不兼容 | 🟢 低 | 组件配置是新增文件（`components.json`），不影响现有 `configs.json` |
| 16 | Phase 5 并行执行时 `defaults.py` / `COMPONENT_SCOPES` 合并冲突（4 个 sub-task 同时修改共享映射文件） | 🟢 低——进度风险 | 各 sub-task 只 append 自己的条目（追加模式）；PR 合并时取 union；若冲突频繁退化为按 5.1→5.2→5.3→5.4 串行合并 |
| 17 | `Agent.disconnect()` 调用点遗漏导致 per-agent 实例泄漏（web 服务 shutdown、session cleanup、`assign_task` 子 Agent 完成） | 🟡 中——长期运行内存累积 | Task 6.3 的 `test_disconnect_releases_scope` + Phase 7 E2E 中每个 Agent 生命周期的 teardown 调用 `disconnect()`；在 `Agent.__del__` 中添加 warning 日志（非 blocking，仅提醒） |

## 关键设计决策（原"未解决的问题"，已定稿）

> 以下 6 项是第 1/2 轮评审中曾"未定"或"契约不闭合"的点，现已作出决策并写入正文；执行时**不再讨论，直接照做**。如需变更，须回到本表更新并重跑 review-plan。

| # | 决策点 | 结论 | 落点 |
|:-:|--------|------|------|
| 1 | 组件实例作用域 | 引入 `singleton` / `per-agent` / `per-session` / `transient` 四类；`COMPONENT_SCOPES` 为唯一事实来源；per-agent 组件缺 `scope_key` 时**抛错而非降级** | 总体方案 · 组件作用域与生命周期契约；Task 1.2 |
| 2 | 组件生命周期 | `get()` 只构造；运行期依赖一律 `await initialize(**deps)`；`initialize()` 幂等；`shutdown()` 仅 Communicator / SessionRunner / ProcessManager 需要 | 总体方案 · 通用规则；Task 6.1 |
| 3 | `SessionMemoryManager` 终态 | 保留为 `@deprecated` **薄兼容层**（只保留 `snapshot_memory_path` / `memory_path` / `reset()`），逻辑全部迁入 `SessionMemoryCompressor`，不反向委托 | Task 3.1 / Task 3.5 |
| 4 | `ToolCallContext.agent` 是否窄化 | **不窄化**，必须是能访问真实 Agent 属性的对象 —— `task` / `blackboard` / `cron` / `bash` / `image` / `agent_interaction` 依赖 `agent.name` / `agent_id` / `config` / `llm_client.config`。Phase 4 直接传 `Agent`（结构化满足 Protocol），Phase 6 传 `AgentReferenceAdapter` 且**必须 `__getattr__` 透传**。这是"窄接口"原则的唯一例外 | 总体方案 · 核心设计模式 4；Task 2.2 / 4.4 / 6.1；AC `test_tools_receive_full_agent` |
| 5 | `allowed_tools`（per-run 白名单）归属 | **留在 `LoopEngine`**（`agent.run()` 设置/复位语义不变），作为参数**逐次**传给 `ToolExecutor.execute_tool(..., allowed_tools=...)`，**不进 `initialize()`** | Task 1.1 ABC；Task 2.3 步骤 2；风险 #12b |
| 6 | `ToolExecutor.initialize()` 参数集 | `(tool_mapping, permission_provider, config, communicator)` —— 与 Task 2.4 / 6.1 调用点逐参数一致，第三方实现不会 `TypeError` | Task 1.1 / 2.2 / 2.4 / 6.1 |

## 待确认事项

- 无阻塞项。以下为**非阻塞**的开放问题，执行中按标注的默认方案处理：
  1. `MCPClient` 抽象价值评估（Task 5.3.3）：若 `StdMCPClient` 包一层只是转发 `_build_client()`，可在报告中标注"延后"，不影响其他组件
  2. 基础设施 5 个组件（Task 5.6）是否本期完成：默认**延后**，但需保证 `defaults.py` / `COMPONENT_SCOPES` 完整
  3. `broca-vscode` 是否纳入 Phase 7 回归：默认**不纳入**（当前无测试套件），仅人工冒烟

---

## 修订记录

| 版本 | 日期 | 依据 | 主要变更 |
|:----:|------|------|----------|
| v1 | 2026-10-31 | 初稿 | 7 Phase / 30 Task；23 个 ABC 全在 Phase 1；Registry 以接口类型为 key 做单例缓存 |
| v2 | 2026-10-31 | `plans/reports/review/component-plugin-architecture-plan-review.md`（2.7/5） | 引入组件作用域（singleton/per-agent/per-session/transient）与生命周期契约；Phase 1 减重为 7 个核心 ABC；新增 Task 2.1 characterization test、Task 3.5 清理外部引用、Task 7.3 启动开销验证；风险表 11 → 15 条；"未解决的问题"改为已定稿决策 |
| v3 | 2026-10-31 | `reports/review/component-plugin-architecture-plan-review.md`（第 2 轮，3.3/5，⚠️ Conditional Pass） | 修 1 项 Critical：`ctx.agent` 契约（适配器 `__getattr__` 透传 + `test_tools_receive_full_agent`）；修 3 项阻塞 Major：`allowed_tools` per-run 归属、`ToolExecutor.initialize` 参数集闭合、`ToolCallContext` 补 `turn_id`/`agent_id`；Phase 2 管道顺序改为"广播最先"并补 5 条 characterization test（共 11 条，覆盖职责 #1~#8）；`AgentReference` 补 `last_context_length`；修 3 条不可达 AC（entry_points、skill 测试、`scripts/verify_agent_e2e.py`）；新增 `Agent.disconnect()` + `ComponentRegistry.release()`；统一 ABC 命名、grep 口径、测试路径与 Task 计数（32） |
| v4 | 2026-10-31 | `reports/review/component-plugin-architecture-plan-review-round3-feasibility-ac.md`（第 3 轮部分评审：Feasibility 4⭐ / AC Quality 4⭐） | 修 3 项 Major：① 懒加载实现修正（`discover_plugins()` 只存 `EntryPoint` 不 load，`resolve()` 按接口惰性 load，补 3 条 AC）；② 删除 Phase 4 无鉴别力的适配器测试（`test_turn_id_write_through_adapter` → `test_loop_engine_writes_turn_id_to_agent_ref`，适配器行为统一由 Task 6.3 覆盖）；③ `session_action` 归属定案（executor 内部应用 override，`session_action` 仅观测返回值）。另修 5 项 Minor：`disconnect()` 顺序改为 `abort → shutdown → release` 可 spy 验证、Phase 1 entry point AC 补声明存在性判据、Task 7.3 硬断言前提与正向用例、Task 3.4 测试路径、Task 4.4 不再重复定义 `AgentReference` |
| v5 | 2026-10-31 | `reports/review/component-plugin-architecture-plan-review-round4.md`（第 4 轮全量评审：4.1/5，⚠️ Conditional Pass） | 修 1 项 Major：启动开销阈值统一（目标 ≤ 5% 优化参考，CI 软断言 ≤ 15%）；修 9 项 Minor：Phase 5 sub-task 补"预期产出"、Pre-flight 检查清单、auto_extract/git fallback/shutdown() 行为精化、Phase 5 合并冲突策略、`@deprecated` 包装体定义（no-op + warning）、新增 Risk #16/#17、修订记录排序、Phase 7 AC 测试数对齐（590 fallback）、Task 7.4 文档 AC 具体化 |
