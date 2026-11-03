# Broca 系统组件化 / 插件化升级改造计划 — Plan Review Report

## Overview

| Item | Content |
|------|---------|
| Plan File | `plans/component-plugin-architecture-plan.md`（1145 行，7 个 Phase，30 个 Task） |
| Reviewed At | 2026-10-31 |
| Review Basis | 对照 worktree `refactor` 真实代码逐项核验（`broca/loop_engine.py`、`agent.py`、`context_compressor.py`、`session_memory/`、`permission_manager.py`、`tools/tool_manager.py`、`pyproject.toml`、测试基线） |
| Overall Score | ⭐⭐⭐ (2.7/5) |
| Verdict | ❌ Needs Revision |

### Dimension Scores

| # | Dimension | Score | Key Finding |
|:-:|-----------|:-----:|-------------|
| 1 | 📋 Completeness | ⭐⭐⭐ | 缺 3 类关键任务：ToolExecutor 真实职责清单、`Agent._setup_session_memory()` 与 3 个内置命令的清理、约束（懒加载/性能）的验证 |
| 2 | 🔍 Clarity | ⭐⭐⭐ | 同一接口出现两套签名（`initialize`、`force_compress`）；Phase 5 的 13 个组件每个只有 1 行步骤 |
| 3 | 🎯 AC Quality | ⭐⭐⭐ | 核心 Task（1.2/2.2/6.3）AC 质量高；Phase 5 与 7.3 的 AC 不可度量 |
| 4 | 🏗️ Feasibility | ⭐⭐ | **Registry 单例缓存与"per-agent 组件"冲突（致命）**；`AgentReferenceAdapter` 缺 setter 会直接抛异常 |
| 5 | 🔗 Structure & Dependencies | ⭐⭐⭐⭐ | 阶段顺序合理；Phase 2/3/4 三次改 LoopEngine，测试适配责任在 Phase 5.5 与各 Task 间重复 |
| 6 | ⚠️ Risk Identification | ⭐⭐⭐ | 11 条风险质量不错，但漏掉最大的两个真实风险（注册表作用域、工具管道行为漂移） |
| 7 | ⚖️ Proportionality | ⭐⭐⭐ | 粒度极不均匀：Phase 1 过重，Task 5.1~5.4 过轻；23 个组件中约 5 个插件价值很低 |
| 8 | ✅ Internal Consistency | ⭐⭐ | Phase 1 建 23 个接口 vs Phase 5 "剩余 13 个"；"删除 ToolPermissionManager 引用" vs "保留并行分区逻辑"；SessionMemoryManager 去留三处说法不一 |
| | **Overall** | **⭐⭐⭐** | 骨架正确、方向可行，但**设计契约未定稿**，按当前文本执行会在 2 处静默改变行为、在 1 处直接破坏多 Agent |

---

## Detailed Findings

### 1. 📋 Completeness — ⭐⭐⭐

**Summary**：章节结构完整（概述/材料/总体方案/测试策略/执行计划/风险/未决问题齐全），Phase 与 Task 级 AC 基本都有；但对"被重构代码的真实职责"清点不足，导致最高优先级 Phase 2 的提取清单不完整。

| # | Severity | Location | Issue | Suggestion |
|:-:|:--------:|----------|-------|------------|
| 1 | 🔴 Critical | Task 2.1 步骤 2 | 提取清单只列了 `_execute_single_tool_call/_execute_tool_with_ask/_execute_tool_with_allow` + 权限 + `wait_for` + READONLY，**漏掉**：① 工具不存在检查 ② `_is_tool_allowed()`（`allowed_tools` 白名单）③ `_broadcast_tool_call_start()`（需要 `tool_call.id`、`communicator`、`config.interactive`）④ `_should_skip_tool_timeout()`（`bash` background、`ask_user` 跳过外层超时）⑤ `_get_tool_execution_timeout()`（`assign_task` 用 1800s 而非 120s）⑥ `_apply_session_decision()`（写 `set_session_override`）。按现文本实现会让 `ask_user` 在 120s 被 `wait_for` 掐断、`bash` 后台任务被误判超时、`allowed_tools` 失效 → 直接违反"行为等价重构"约束 | 在 Task 2.1 步骤 2 中把这 6 项显式列出并标注归属（迁入 executor 或保留 LoopEngine）；对应 AC 增加"ask_user/bash background 不触发外层超时""allowed_tools 拒绝路径""assign_task 使用独立超时"三条 |
| 2 | 🟡 Major | Phase 3 | 没有任务处理 `Agent._setup_session_memory()`（`agent.py:227`）与三个内置命令 `clear_history` / `clear_context` / `clear_all_context`（均直接访问 `agent.session_memory_manager.reset()/snapshot_memory_path/memory_path`）。Phase 3 AC 却要求"SessionMemoryManager 不再被外部直接引用" | 新增 Task 3.5「清理 SessionMemoryManager 外部引用」：改 `Agent.create()` 不再 `_setup_session_memory()`；三个 clear 命令改走 `ContextCompressor` 暴露的 `reset_session_memory()` / 路径属性 |
| 3 | 🟡 Major | Phase 1 Task 1.1 vs Phase 5 | Task 1.1 要求 Phase 1 就建齐 23 个 ABC（"其余 20 个组件接口按相同模式定义"），Phase 5 目标又写"完成剩余 13 个组件的接口定义" —— 同一批接口被规划了两次，执行时必然出现"已建但不可用"或"重复建" | 二选一并在两处统一：建议 Phase 1 只建 6 个核心接口（ToolExecutor/ContextCompressor/LLMClient/PermissionProvider/Communicator/LoopEngine）+ Registry + 配置 + 测试基建；其余 17 个随其实现 Phase 增量定义 |
| 4 | 🟡 Major | 概述「约束条件」 | 三条约束中"懒加载、不增加启动开销"与"`pip install` + entry point 即可生效"**没有任何 Task/AC 验证**：无启动耗时对比、无真实构建安装后 entry point 发现的验证 | Phase 7 增加：`test_registry_lazy_load`（未调用 `get()` 时不 import 插件模块，用 `sys.modules` 断言）+ 启动耗时基线对比（±5%）+ `poetry build` 后安装到干净 venv 验证 entry point 可发现 |
| 5 | 🟢 Minor | 相关材料 | 引用的 `plans/session-memory-extraction-compression-optimization.md` 在 `refactor` worktree 中不存在（仅主 worktree 有），Phase 3.1 步骤 1 直接依赖它 | 补一句"该文件不在本 worktree，若缺失则以本计划 Task 3.1 描述为准"，或把关键设计（pivot 计算、冻结流程）内联进本计划 |
| 6 | 🟢 Minor | Task 7.3 | 文档任务 AC "开发者能在 30 分钟内创建一个简单插件"不可客观验证 | 改为"提供 `examples/plugins/sandbox_tool_executor/` 可运行示例 + `pytest examples/plugins/` 通过" |
| 7 | 🟢 Minor | 全局 | 无工作量估算、无提交/回滚策略。30 个 Task 跨 7 个 Phase 的大重构，缺少"每 Phase 独立可合并"的约束（当前 Phase 2.3 的中间态会长期留在主干） | 每个 Phase AC 增加"该 Phase 结束时 `pytest` 全绿且可独立合并"，并给出粗估（建议 Task 级 S/M/L） |

---

### 2. 🔍 Clarity — ⭐⭐⭐

**Summary**：核心 3 个接口（ToolExecutor / ContextCompressor / AgentReference）有代码骨架，可读性好；但同一接口在不同 Task 里签名不一致，Phase 5 的 13 个组件只有一行描述，两个执行者会产出完全不同的代码。

| # | Severity | Location | Issue | Suggestion |
|:-:|:--------:|----------|-------|------------|
| 1 | 🟡 Major | Task 1.1 vs Task 2.1 | `ToolExecutor.initialize` 两套签名：Task 1.1 `initialize(self, tool_mapping: dict, config: Any)`，Task 2.1 `initialize(self, tool_mapping, permission_provider, config)` | 在 Phase 1 定稿一次，Task 2.1 只引用不重定义 |
| 2 | 🟡 Major | Task 4.4 vs Task 6.1 | Task 4.4 说 LoopEngine 依赖为 5 个（agent_ref/llm/tool_executor/compressor/communicator），Task 6.1 的 `initialize()` 又多出 `context/session_manager/config/memory_manager`；实际 `LoopEngine.__init__` 还需要 `tool_mapping`、`snapshot_tracker`/`patch_calculator`、`allowed_tools`、`persistent_memory_manager` 等 | 以真实 `__init__`（`loop_engine.py:92-205`）为准列出完整依赖表（参数名 / 类型 / 来源），两处引用同一张表 |
| 3 | 🟡 Major | Task 5.1~5.4 | 13 个组件每个只有 1 行"ABC：方法列表 + 默认实现（现有 X 重命名）"，没有文件路径、没有构造参数、没有"现有模块是函数/单例，如何包成类"的说明。其中 `ContentSecurityScanner`（现为 `broca/utils/content_security.py:scan_content_security()` 函数）、`ErrorStrategy`（现无，只有 `ErrorCode` 枚举）、`ConfigManager`（现只有模块级 `get_configs()`）、`Logger`（现只有 `LoggingConfig`）、`MCPClient`（现只有 `_build_client()` 函数 + `MCPTool`）**都不存在对应类**，属"从零造抽象"而非"接口化" | 每个组件补齐：目标文件路径、ABC 完整签名、默认实现如何包装现有模块、构造依赖；对这 5 个"无现成类"的组件单独说明设计动机（或直接剔除，见 Proportionality #2） |
| 4 | 🟡 Major | Task 3.2 代码示例 | 示例 `_trigger_post_step_hooks()` 把持久化记忆从"`increment_step()` + `asyncio.create_task()` 后台抽取 + `auto_extract` 门控"改成了 `await self.memory_manager.check_and_extract(...)`。这是**并发语义与门控逻辑的静默变更**（当前 `loop_engine.py:515-526`），且没在计划中标注 | 示例代码按现状保留门控与后台任务语义，或在风险表登记"持久化记忆改为同步等待"的行为变更并说明理由 |
| 5 | 🟢 Minor | Task 4.2 | ABC 用 `get_tool_permission()` / `request_tool_permission(tool_name, arguments, context)`，现实现是 `ToolPermissionManager.get_permission()` / `PermissionManager.request_tool_permission(message)`；谁做适配、`message` 如何拼装未说明 | 明确"新接口 + 适配器"或"沿用现名"，并列出调用点（`agent.py:342/370` 的 `set_state`、`loop_engine.py:733`） |
| 6 | 🟢 Minor | Task 2.2 | "保留并行/串行调度逻辑在 LoopEngine 中"与"删除 LoopEngine 对 `ToolPermissionManager` 的直接引用"并存，但分区逻辑 `_process_tool_calls_parallel` 正是用 `tool_permission_manager.get_permission()` 判断 ask（`loop_engine.py:891-896`） | 在 ToolExecutor ABC 上增加 `get_permission(tool_name) -> str`（或 `needs_user_confirmation()`），并明确 LoopEngine 通过它分区 |

---

### 3. 🎯 AC Quality — ⭐⭐⭐

**Summary**：Registry（Task 1.2）、LoopEngine 委托（Task 2.2）、Agent 组合（Task 6.3）的 AC 具体、可测；Phase 5 与部分 Phase 7 的 AC 停留在"就位/通过"层面，无法判定完成。

| # | Severity | Location | AC | Issue | Suggestion |
|:-:|:--------:|:--------:|----|-------|------------|
| 1 | 🟡 Major | Task 5.1~5.4 | "三个组件的 ABC 和默认实现就位"、"调用方通过接口类型引用" | 不可度量："就位"没有验收对象，"调用方"未枚举 | 改为"`issubclass(SQLSessionManager, SessionManager)` 为真；`grep -rn 'SessionManager(' broca --include=*.py` 除 `defaults.py` 外无直接实例化" |
| 2 | 🟡 Major | Task 2.2 | "LoopEngine 不再包含任何工具执行的具体逻辑" | 无判定方法 | 改为"`loop_engine.py` 中不再出现 `asyncio.wait_for`、`ToolPermissionManager`、`ToolStatus.ERROR` 的工具执行构造；`grep` 结果为 0" |
| 3 | 🟡 Major | Task 1.1 | "所有 ABC 的抽象方法签名与现有实现的方法签名兼容" | 人工比对不可靠，且 Task 5.5 的 `__abstractmethods__` 检查只验证"实现了"，不验证"签名一致" | 增加机械化检查：对每个 (ABC, impl) 用 `inspect.signature` 比对参数名/默认值，写成参数化测试 |
| 4 | 🟡 Major | Phase 7 | "手动验证：启动 Broca，执行一轮完整的 Agent 对话" | 主观、不可复现 | 改为"按 `examples/` 脚本运行，断言日志中出现 `tool_call_start→tool_result→turn_end` 且 `session-memory.md` 被更新" |
| 5 | 🟢 Minor | Task 6.3 | `test_no_circular_import` | 该测试在**改造前就会通过**（`loop_engine.py` 当前并不 import `broca.agent`，只有 `agent.py` 单向 import），无鉴别力 | 改为断言"`LoopEngine.__init__`/`initialize` 签名与属性中不出现 `Agent` 类型，且 `LoopEngine` 不读取 `agent.config`/`agent.session_memory_manager`"（可用 `inspect` + 运行时探针） |
| 6 | 🟢 Minor | Task 2.4 | "测试不依赖 Agent 实例" 但要求 "覆盖并行/串行模式" | 并行/串行调度按 Task 2.2 仍留在 LoopEngine，放在 executor 测试里位置不对 | 并行/串行测试归入 `test_execution_engine.py`（Phase 4.5），Task 2.4 只测单次执行管道 |
| 7 | 🟢 Minor | Phase 3 AC | "SessionMemoryManager 类不再被外部直接引用（作为内部实现或完全删除）" | "或"字导致两种截然不同的终态都算通过 | 定死一种（建议：保留为 `@deprecated` 薄封装，并在 Phase 7 用 `grep` 断言仅 `context_compressor.py` 引用） |

**Good ACs identified:**
- Task 1.2："配置优先级 override > discovered > default"、"同一接口多次 `get()` 返回同一实例"、"未找到抛 `ComponentError`" —— 可逐条写测试。
- Task 2.2："结果处理（broadcast、DB save、context add）仍在 LoopEngine 中" —— 明确了职责边界，避免把职责一起搬走。
- Task 6.3：7 个场景（默认装配、替换 ToolExecutor/LLMClient、适配器代理、生命周期、会话恢复）覆盖了组合根的关键路径。

---

### 4. 🏗️ Feasibility — ⭐⭐

**Summary**：整体技术路线（ABC + Registry + entry points + 组合根）是成熟做法，基线数据也准确（实测 `pytest broca/tests/ --collect-only` = **522 tests**，与计划一致；`pytest-cov 7.1.0` 已安装；`broca/tests/conftest.py` 当前不存在，与计划假设一致）。但注册表的作用域设计与适配器代码存在**会导致功能损坏**的问题。

| # | Severity | Location | Issue | Suggestion |
|:-:|:--------:|----------|-------|------------|
| 1 | 🔴 Critical | Task 1.2 `ComponentRegistry` / Task 6.1 | `_instances: dict[type, Any]` 以**接口类型为唯一 key 做单例缓存**，但计划自己要求通过它获取 `Communicator`、`LoopEngine`、`ContextCompressor`、`MemoryManager`、`SessionManager`、`PermissionProvider`、`ToolExecutor`（持 `tool_mapping`）——这些**全部是 per-agent / per-session 实例**。`registry.get(Communicator, agent_id=...)` 第二次调用会直接返回第一个 Agent 的 Communicator（kwargs 被忽略），多 Agent / `assign_task` 子 Agent / 会话恢复会全部串台 | 引入作用域概念：`ComponentRegistry.get(interface, scope="singleton"|"transient", key=None)`，per-agent 组件用 `key=agent_id` 或干脆 `transient` + 由组合根显式构造；并把"组件作用域表"（23 行：组件 / 作用域 / 是否持有 agent）作为 Phase 1 交付物与 AC |
| 2 | 🔴 Critical | Task 2.1 / Phase 2 AC | 见 Completeness #1：提取清单不完整，而 Phase 2 AC 断言"现有工具执行行为完全不变"。两者矛盾，按现文本执行会静默回归 | 见 Completeness #1；并补一条 AC："`ask_user` 连续等待 >120s 不被外层超时打断"（当前 `_should_skip_tool_timeout` 保证） |
| 3 | 🟡 Major | Task 6.1 `AgentReferenceAdapter` | 适配器用只读 `@property` 暴露 `turn_id`，但 `loop_engine.py:1389` 有 `self.agent.turn_id = turn_id`（写操作）→ 赋值会抛 `AttributeError: can't set attribute`。另外 `loop_engine.py:670` 的 `ctx.agent = self.agent` 被 `task/blackboard/cron/bash/image/agent_interaction` 等工具使用（`context.agent.name/agent_id`），因此 `ToolCallContext.agent` 必须继续是**真实 Agent**，与"窄接口、不传整个 Agent"的目标冲突 | 适配器为 `turn_id` 提供 setter；计划中明确声明"`ToolCallContext.agent` 例外，仍传真实 Agent（工具需要 `name/agent_id/config`）"，并把这条写进 Task 4.4 AC，避免执行者误删 |
| 4 | 🟡 Major | Task 1.2 `get(interface, **kwargs)` + Task 2.1/6.1 `initialize()` | 组件生命周期有两套机制：一部分构造注入（`impl_cls(**kwargs)`），一部分 `await initialize(...)`（ToolExecutor、LoopEngine）。Registry 只负责构造，`initialize` 由谁调用、调用顺序、重复调用是否幂等，均未定义；而 `SessionMemoryManager(agent=self)`、`PersistentMemoryManager(agent=self)`、`CommandManager(agent)`、`AgentCommunicator(agent)` 都需要 agent 才能构造，与"不传整个 Agent"原则直接冲突 | 定一个统一契约：建议 `ComponentRegistry.get()` 只做"构造"，所有需要 agent/运行期依赖的组件统一 `await component.initialize(**deps)`，并在 Phase 1 给出"组件生命周期表"（构造参数 / initialize 参数 / 是否需要 shutdown） |
| 5 | 🟡 Major | Task 2.1 `execute_tool` 返回值 | 现 `_execute_tool_with_ask()` 返回 `(ToolResult, session_action)`，`_apply_session_decision()` 需要把 `allow/forbid` 写回 `ToolPermissionManager`。新接口 `-> ToolResult` 无处返回 `session_action`，session 级"总是允许"功能会丢失 | `execute_tool` 返回 `ToolExecutionOutcome(result, session_action)`，或在 executor 内部完成 override 写入（需要 `PermissionProvider.set_session_override()`，当前 ABC 未定义） |
| 6 | 🟡 Major | Task 1.2 步骤 5 / Phase 1 AC | `[project.entry-points."broca.components"]` 写在 poetry-core 2.x + PEP 621 工程里，需确认 poetry-core 版本支持该表；更关键的是 `importlib.metadata.entry_points()` 只读**已安装 dist 元数据**，源码目录直接跑测试时 broca 自身的 entry points 可能不可见；且"内置默认实现用 entry point 自注册"与 `defaults.py` 冗余 | 加一步验证（`poetry build` + 干净 venv 安装后 `importlib.metadata.entry_points(group="broca.components")` 非空）；内置默认只走 `defaults.py`，pyproject 中仅保留 1 个示例 entry point 作为文档 |
| 7 | 🟡 Major | Phase 1 整体 | 在**尚未重构任何组件**时先冻结 23 个 ABC，与风险表第 1 条自相矛盾（"接口定义不准确后续需修改"）。接口正确性只能靠"读代码比对"，没有任何可执行验证直到 Phase 5.5 | 接口随实现 Phase 增量定义（核心 6 个先定），每个 Phase 结束时用 `inspect.signature` 兼容性测试兜底 |
| 8 | 🟢 Minor | Task 1.4 步骤 4 | 全局 `addopts = "--cov=broca --cov-report=term-missing"` 会作用于 `broca-web/tests`、`broca-tui/tests` 以及所有单测运行，显著拖慢并污染覆盖率口径 | 用 `[tool.coverage.run] source=["broca"]` + 仅在 Phase 7 显式传 `--cov`，不要写进 `addopts` |

---

### 5. 🔗 Structure & Dependencies — ⭐⭐⭐⭐

**Summary**：Phase 1（基础）→ 2/3（最高价值两处提取）→ 4（核心循环）→ 5（批量支撑）→ 6（组合根）→ 7（验证）的主干顺序正确，Phase 2.3 的"中间态 + 注释"处理得当。问题集中在**同一文件被三个 Phase 反复改**与**测试适配责任重叠**。

| # | Severity | Location | Issue | Suggestion |
|:-:|:--------:|----------|-------|------------|
| 1 | 🟡 Major | Task 2.2 / 3.2 / 4.4 | `loop_engine.py`（1537 行）在三个 Phase 被大改三次，且 Phase 4.4 才引入 `AgentReference`/`DefaultLoopEngine`，意味着 2.2 和 3.2 写的代码在 4.4 要再改一遍签名（`agent` → `agent_ref`） | 合并 2.2 + 3.2 的 LoopEngine 改动，或在 Phase 2 就把 `agent_ref` 参数形态引入（哪怕初期仍传 Agent），避免三次返工 |
| 2 | 🟡 Major | Task 5.5 vs Task 2.2/3.4/4.1/4.2 | 各 Phase 的 AC 都写"现有测试通过"，Phase 5.5 又列了一遍同样的测试文件适配清单（`test_llm.py`/`test_permission_manager.py`/`test_loop_engine.py`/`test_context_compressor.py`/`test_memory_manager.py`） | 把适配动作归属到产生变更的那个 Task（如 `test_llm.py` 归 4.1），Phase 5.5 只保留"23 组件 ABC↔默认实现配对"这一件事 |
| 3 | 🟢 Minor | Task 5.1~5.4 | 四组任务彼此独立，完全可以并行，但计划未标注 | 标注"5.1~5.4 可并行，无相互依赖" |
| 4 | 🟢 Minor | Phase 3 / Phase 4 | Phase 3 改 `ContextCompressor` 签名（`agent` → `CompressorContext`），Phase 4.4 才改 `LoopEngine` 依赖注入；中间态里 `LoopEngine._check_context_compression()` 需要同时适配两套 | 在 Phase 3 一次性把 `_build_compressor_context()` 落在 LoopEngine，Phase 4.4 只做类型替换 |
| 5 | 🟢 Minor | Task 5.3 / 6.2 | `ToolManager` 去单例（5.3）会影响 `agent.py:183`、`agent_manager.py:176/261`，但 6.2 才处理 AgentFactory；`Agent.create()` 在 6.1 就改完 | 把"去单例 + 调用点改造"合并为一个 Task，避免中途出现半单例状态 |

---

### 6. ⚠️ Risk Identification — ⭐⭐⭐

**Summary**：11 条风险覆盖面不错，且多数配了具体机制（`reset()` + `fresh_registry`、`test_no_circular_import`、Phase 7 E2E）。但**漏掉了本计划真正的两个高危点**，且"未解决的问题：无"过于自信。

| # | Severity | Location | Issue | Suggestion |
|:-:|:--------:|----------|-------|------------|
| 1 | 🔴 Critical | 风险表 | 未识别"注册表单例 vs per-agent 组件"风险 —— 这是会破坏多 Agent / 子 Agent / 会话恢复的头号风险（Feasibility #1） | 新增风险行 + 对应缓解（作用域表 + `test_two_agents_isolated` 测试） |
| 2 | 🟡 Major | 风险表 | 未识别"工具执行管道行为漂移"（超时跳过、`allowed_tools`、session override、`assign_task` 超时）—— 这类回归不会让测试变红，只会让线上行为悄悄变化 | 新增风险行 + 缓解："Task 2.1 前先为现有 6 项行为各写一条特征测试（characterization test），改造后必须全绿" |
| 3 | 🟡 Major | 风险表 | 未识别第三方插件的**信任/安全**风险：插件是任意 Python 代码，且按计划可拿到 `ToolCallContext.agent`（进而拿到 config、session manager、文件系统） | 新增风险行，缓解：文档明确"插件拥有进程内完全权限"；`components.json` 变更记日志；可选 `BROCA_ALLOW_PLUGINS=1` 开关 |
| 4 | 🟡 Minor | 风险表 | 未识别"启动开销"与"7 Phase 长周期重构的分支漂移/合并冲突"（30 个 Task 触碰 ~30 个文件） | 各补一行；缓解：每 Phase 独立可合并 + 单文件改动集中到一个 Phase（见 Structure #1） |
| 5 | 🟢 Minor | 未解决的问题 | 写"无（所有关键设计决策已与用户确认）"，但作用域、生命周期契约、SessionMemoryManager 去留、`ToolCallContext.agent` 例外四处均未定 | 把这 4 条列进"未解决的问题"，逐条给出推荐决策，确认后再进入 create-tasks |

---

### 7. ⚖️ Proportionality — ⭐⭐⭐

**Summary**：对"23 个组件 + 7 Phase"这个量级，计划长度（1145 行）与细节密度大体匹配，但**粒度分布严重不均**，且部分组件不值得抽象。

| # | Severity | Location | Issue | Suggestion |
|:-:|:--------:|----------|-------|------------|
| 1 | 🟡 Major | Phase 1 vs Task 5.1~5.4 | Phase 1 四个 Task 要交付 23 个 ABC + Registry + 配置 + 测试基建 + mock 组件，是全书最重的一块；而 Task 5.1~5.4 每个覆盖 3~5 个组件却只有 2~5 行步骤。同一份计划里"最重的 1/3 工作量"被压进 1 个 Phase | 拆分：Phase 1 = Registry + 配置 + 测试基建 + 6 个核心 ABC；其余 17 个接口按组件组拆成独立 Task（每个组件 ≥3 条步骤 + ≥2 条可测 AC） |
| 2 | 🟡 Major | 23 组件清单 #14/#16/#22/#23 | `ContentSecurityScanner`（现为 1 个函数）、`ErrorStrategy`（现为 1 个枚举）、`ConfigManager`（现为 1 个函数）、`Logger`（现为 1 个配置类）插件价值很低：包一层 ABC 只增加间接层，几乎不会有人替换 `Logger` | 分级：**核心 7 个**（ToolExecutor / ContextCompressor / LLMClient / PermissionProvider / Communicator / LoopEngine / AgentFactory）必做；**支撑 11 个**按需；**基础设施 5 个**（Logger / ConfigManager / ContentSecurityScanner / ErrorStrategy / Scheduler）标为可选、可延后 |
| 3 | 🟢 Minor | Phase 7 | 7 个 Phase 的验证集中压在最后，E2E 场景 10 条要一次写完 | 每个 Phase 收尾各带 1~2 条 E2E 场景（场景 1/2 在 Phase 2 末，场景 5/6 在 Phase 3 末），Phase 7 只做汇总回归 |

---

### 8. ✅ Internal Consistency — ⭐⭐

**Summary**：存在多处互相矛盾之处，执行者必须"猜"哪个是准的。

| # | Severity | Location | Issue | Suggestion |
|:-:|:--------:|----------|-------|------------|
| 1 | 🟡 Major | Phase 1 AC vs Phase 5 目标 | Phase 1 AC："`broca/components/` 包含所有 23 个组件的 ABC"；Phase 5 目标："完成剩余 13 个组件的接口定义" | 统一为"Phase 1 只建 6 个核心接口"或"Phase 5 只做默认实现适配"，二选一 |
| 2 | 🟡 Major | Task 2.2 步骤 5 vs Task 2.2 步骤 2 | "删除 LoopEngine 中直接引用 `ToolPermissionManager` 的代码"与"保留并行/串行调度逻辑（含 ask 判定）在 LoopEngine 中"冲突（ask 判定必须读权限） | 见 Clarity #6：ToolExecutor ABC 增补 `get_permission()` |
| 3 | 🟡 Major | Task 3.1 步骤 4 vs Phase 3 AC | Task 3.1："`SessionMemoryManager` 保留但 `@deprecated`，内部委托给 `ContextCompressor`"；Phase 3 AC："不再被外部直接引用（作为内部实现或完全删除）"。且"逻辑已搬进 ContextCompressor，SessionMemoryManager 再委托回去"方向不成立（会形成循环） | 定一种终态：建议 `SessionMemoryManager` 保留为**薄兼容层**（只保留路径属性 + `reset()`，内部持有 `ContextCompressor` 引用，不做逻辑委托），并写进 Phase 7 的 `grep` 断言 |
| 4 | 🟡 Major | Task 3.1 ABC vs Task 3.3 用法 | Task 3.1 定义 `force_compress()` 为独立抽象方法，Task 3.3 用 `force_compress()`；但现实现（`compact/__init__.py:50-55`）是 `check_and_compress(..., force=True)`。两套 API 并存 | 二选一：要么 ABC 只有 `check_and_compress(force=...)`，要么 `force_compress()` 作为非抽象便捷方法内部调用前者 |
| 5 | 🟡 Major | Task 3.2 示例 vs 现状 | 示例丢了 `enable_context_compression` 门控、`persistent_memory_config.auto_extract` 门控、`increment_step()` 与后台 `create_task` 语义（现状 `loop_engine.py:507-526`） | 示例按现状改写；若确要改语义，登记到风险表与 Phase 3 AC |
| 6 | 🟢 Minor | Phase 4 AC vs Task 4.4 | AC："`DefaultLoopEngine` 的所有依赖通过接口注入"；Task 4.4 只列 5 个依赖，与真实 `__init__` 不符 | 见 Clarity #2 |
| 7 | 🟢 Minor | Task 6.1 示例 vs 总体方案原则 | 原则 3/4 说"依赖注入、窄接口、不传整个 Agent"；但示例中 `command_system.initialize(agent)` 传整个 Agent，`registry.get(Communicator, agent_id=...)` 也暗示组件需要 agent 上下文 | 明确"组合根允许传 Agent，组件之间不允许"的边界，并写进 Task 1.1/6.1 的说明 |
| 8 | 🟢 Minor | 概述背景 | "`Agent` 与 `LoopEngine` 存在循环依赖"不准确：当前 `loop_engine.py` 并不 import `broca.agent`（只有 `agent.py:16` 单向 import），是**运行期双向引用**而非导入环 | 改为"运行期双向引用（LoopEngine 持有 agent，agent 持有 engine），导致无法独立测试与替换" |

---

## Issue Summary

| Severity | Count | Description |
|:--------:|:-----:|-------------|
| 🔴 Critical | 4 | 必须先修：注册表作用域、工具管道提取清单、AgentReference 写属性/工具依赖 agent、行为等价 AC 与实现冲突 |
| 🟡 Major | 19 | 影响执行质量：签名冲突、生命周期契约缺失、Phase 5 过粗、SessionMemoryManager 去留、测试责任重叠 |
| 🟢 Minor | 14 | 建议改进：文档、口径、并行标注、风险补充 |

### 🔴 Critical Issues (Must Fix)

| # | Dimension | Location | Issue | Suggestion |
|:-:|:---------:|:--------:|-------|------------|
| 1 | Feasibility / Consistency | Task 1.2 + Task 6.1 | Registry 以接口类型为唯一 key 做单例缓存，但 Communicator/LoopEngine/ContextCompressor/MemoryManager/PermissionProvider/ToolExecutor 全是 per-agent 实例 → 多 Agent、子 Agent、会话恢复全部串台 | 引入 `scope`（singleton/transient/per-agent）+ 组件作用域表，per-agent 组件按 `agent_id` 取实例 |
| 2 | Completeness | Task 2.1 | 工具管道提取清单漏 6 项真实职责（工具存在性、`allowed_tools`、tool_call 广播、`_should_skip_tool_timeout`、`assign_task` 独立超时、session override 写入）→ 与"行为完全不变"AC 冲突 | 补齐清单并明确归属；先写 6 条 characterization test 再动手 |
| 3 | Feasibility | Task 6.1 | `AgentReferenceAdapter` 的 `turn_id` 只读 property 与 `loop_engine.py:1389` 的写操作冲突；`ToolCallContext.agent` 仍被 6 个工具模块使用，窄接口目标不可完全达成 | 加 setter；明确声明 `ToolCallContext.agent` 保留真实 Agent 并写入 AC |
| 4 | Feasibility | Task 2.1 | `execute_tool() -> ToolResult` 无法返回 `session_action`，session 级"总是允许/禁止"会丢失 | 返回 `ToolExecutionOutcome(result, session_action)` 或把 override 写入下沉到 `PermissionProvider` |

### 🟡 Major Issues (Should Fix)

| # | Dimension | Location | Issue | Suggestion |
|:-:|:---------:|:--------:|-------|------------|
| 1 | Completeness | Phase 3 | 未覆盖 `Agent._setup_session_memory()` 与 `clear_history/clear_context/clear_all_context` 三个命令的 `agent.session_memory_manager` 引用 | 新增 Task 3.5 统一清理 |
| 2 | Completeness | Phase 1 / Phase 5 | 23 个 ABC 归属重复规划 | 统一拆分口径 |
| 3 | Completeness | 概述约束 | "懒加载/零启动开销"、"pip install 即生效"无 Task/AC 验证 | Phase 7 增加懒加载断言 + 启动耗时对比 + 真实安装验证 |
| 4 | Clarity | Task 1.1 / 2.1 | `initialize()` 两套签名 | Phase 1 定稿 |
| 5 | Clarity | Task 4.4 / 6.1 | LoopEngine 依赖清单与真实 `__init__` 不符 | 以代码为准列出完整依赖表 |
| 6 | Clarity | Task 5.1~5.4 | 13 个组件每个 1 行步骤，5 个组件当前并无对应类 | 补文件路径/签名/包装方式/动机 |
| 7 | Clarity | Task 3.2 | 示例静默改变持久化记忆的并发与门控语义 | 按现状改写或登记变更 |
| 8 | Clarity | Task 2.2 | "删除权限引用"与"保留并行分区"冲突 | ABC 增补 `get_permission()` |
| 9 | AC | Task 5.1~5.4 | "就位/通过"不可度量 | 改为 `issubclass` + `grep` 断言 |
| 10 | AC | Task 2.2 | "不含工具执行具体逻辑"无判定方法 | 给出 `grep` 判据 |
| 11 | AC | Task 1.1 | "签名兼容"只能人工判断 | 加 `inspect.signature` 参数化测试 |
| 12 | AC | Phase 7 | 手动验证不可复现 | 改为脚本 + 日志断言 |
| 13 | Feasibility | Task 1.2 / 6.1 | 构造注入与 `initialize()` 两套生命周期未定契约；多个组件构造需要 agent | 统一"构造 + initialize"契约，产出生命周期表 |
| 14 | Feasibility | Task 1.2 步骤 5 | poetry-core + PEP 621 entry points 支持性与可测试性未验证；内置默认自注册冗余 | 加 build+install 验证；内置默认只走 `defaults.py` |
| 15 | Feasibility | Phase 1 | 未重构任何组件前冻结 23 个 ABC，与风险表第 1 条矛盾 | 接口增量定义 + 机械兼容性测试 |
| 16 | Structure | Task 2.2 / 3.2 / 4.4 | `loop_engine.py` 三个 Phase 返工三次 | 合并或提前引入 `agent_ref` 形态 |
| 17 | Structure | Task 5.5 vs 2.2/3.4/4.1/4.2 | 测试适配责任重复 | 归属到产生变更的 Task |
| 18 | Risk | 风险表 | 缺"工具管道行为漂移"风险 | 新增 + characterization test 缓解 |
| 19 | Risk | 风险表 | 缺第三方插件信任/安全风险 | 新增 + 文档声明 + 开关 |

### 🟢 Minor Issues (Consider)

| # | Dimension | Location | Issue | Suggestion |
|:-:|:---------:|:--------:|-------|------------|
| 1 | Completeness | 相关材料 | 引用的 session-memory 计划在本 worktree 不存在 | 注明缺失时的处理 |
| 2 | Completeness | Task 7.3 | "30 分钟上手"不可验证 | 改为可运行示例 + 测试 |
| 3 | Completeness | 全局 | 无工作量估算 / 回滚策略 / 每 Phase 可合并约束 | 补粗估与合并约束 |
| 4 | Clarity | Task 4.2 | 权限接口命名与现实现不一致，调用点未列 | 明确适配策略与调用点 |
| 5 | AC | Task 6.3 | `test_no_circular_import` 改造前即通过，无鉴别力 | 改为断言无 Agent 类型依赖 |
| 6 | AC | Task 2.4 | 并行/串行测试位置与 Task 2.2 职责划分不一致 | 移到 4.5 |
| 7 | AC | Phase 3 AC | "作为内部实现或完全删除"二义 | 定死一种 |
| 8 | Feasibility | Task 1.4 | 全局 `addopts --cov` 拖慢所有测试 | 移到显式调用 |
| 9 | Structure | Task 5.1~5.4 | 未标注可并行 | 标注 |
| 10 | Structure | Phase 3 / Phase 4 | `CompressorContext` 与依赖注入分两阶段落地 | 合并到 Phase 3 |
| 11 | Structure | Task 5.3 / 6.2 | `ToolManager` 去单例与调用点改造跨 Phase | 合并 |
| 12 | Risk | 风险表 | 缺启动开销 / 长周期合并冲突 | 补充 |
| 13 | Consistency | 未解决的问题 | "无"过于自信，4 个关键决策未定 | 列 4 条并给推荐决策 |
| 14 | Consistency | 概述背景 | "循环依赖"表述不准确（实为运行期双向引用） | 修正措辞 |

---

## Verdict

**Overall Score**: 2.7/5 ⭐⭐⭐

**Verdict**: ❌ Needs Revision

**Recommendation**（按优先级）：

1. **P0 — 定稿两个设计契约（阻塞执行）**
   - 组件作用域表：23 行（组件 / singleton 或 per-agent / 构造参数 / `initialize` 参数 / 是否需要 shutdown），Registry 增加 `scope` 与 `key`。
   - 生命周期契约：`get()` 只构造，`initialize()` 注入运行期依赖；per-agent 组件如何拿到 `agent_ref`。
2. **P0 — 重写 Task 2.1 / 2.2 的提取清单与 AC**：补 6 项漏掉的行为 + 先写 characterization test（`ask_user` 长等待、`bash` background、`allowed_tools`、`assign_task` 1800s、session override、tool_call 广播）。
3. **P1 — 修 `AgentReferenceAdapter`**：`turn_id` 加 setter；明确 `ToolCallContext.agent` 保留真实 Agent；`execute_tool` 返回 `(result, session_action)`。
4. **P1 — Phase 1 减重、Phase 5 加细**：Phase 1 只留 Registry + 配置 + 测试基建 + 6 个核心 ABC；Phase 5 每个组件 ≥3 步 ≥2 条可测 AC；把 Logger/ConfigManager/ContentSecurityScanner/ErrorStrategy/Scheduler 标为可选。
5. **P1 — 统一 SessionMemoryManager 终态**，新增 Task 3.5 清理 `Agent._setup_session_memory()` 与 3 个 clear 命令。
6. **P2 — 补风险与验证**：工具管道漂移、插件信任、启动开销、长周期合并冲突；Phase 7 增加懒加载/启动耗时/真实安装 entry point 验证。
7. **P2 — 把"未解决的问题"写实**（4 条），确认后再跑 `create-tasks`。

修改后建议**再跑一次 review-plan**，重点复核 P0 两项（作用域表、Task 2.1 清单）与 Internal Consistency 的 4 处矛盾。

**Summary**：
计划的骨架与方向是对的——"ABC + Registry + entry points + 组合根"是成熟路线，基线数据（522 tests、pytest-cov 已装、无 conftest.py）也与仓库实况一致，核心 Task 的 AC 质量不低。但**关键设计契约（组件作用域、生命周期）尚未定稿**，而按当前文本执行会在三处造成实质损坏：多 Agent 共用同一个 Communicator/LoopEngine、`ask_user`/`bash background`/`assign_task` 的超时行为被静默改变、`AgentReferenceAdapter` 写入 `turn_id` 直接抛异常。这些都属于"改计划 1 天可解决"的问题，不是方向性错误；修完 P0/P1 后可放心进入 `create-tasks`。
