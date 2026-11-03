# Loop Engine 策略+Hook 重构 — Phase 1: 基础设施（接口 + 数据类 + 包骨架） — Execution Report

## Overview

| Item | Content |
|------|---------|
| Plan File | `.worktrees/refactor/plans/loop-engine-hooks-refactor-plan.md` |
| Phase | Phase 1: 基础设施（接口 + 数据类 + 包骨架） |
| Status | ✅ Pass（1 项计划未覆盖偏离，已定稿处理，见「Deviations」） |
| Executed | 2026-11-01 |
| Test Baseline | 迁移前 `--collect-only` = **754 collected（1 deselected）**；迁移后 **751 passed / 3 skipped / 1 deselected = 754 collected，0 失败** |

## Plan Anchor Confirmation

- [x] 执行前重读计划 Phase 1 段（行 313–497）与「总体方案 / 接口契约速查」（行 50–311）
- [x] 逐任务确认 AC（Task 1.1 ~ 1.5），AC 原文已写入任务管理系统对应任务
- [x] 确认「并行约束」：Phase 1 只建骨架，`strategies/`、`hooks/` 内容留给 Phase 2/3

## Task Completion

| Task | Status | Plan ACs | Actual Result | Deviation |
|:----:|:------:|----------|---------------|-----------|
| **1.1** 定义 LoopHook ABC + 上下文数据类 | ✅ | ① `name` 非抽象类属性 + 6 个 async 方法 + `reset()`；② 空子类可实例化；③ `TurnContext` 字段齐全；④ `StepContext` 字段齐全；⑤ `from broca.components import LoopHook, TurnContext, StepContext` 成功 | 新建 `broca/components/loop_hook.py`（115 行，首行 `from __future__ import annotations`）；`name: str = "loop_hook"` 为普通类属性（`inspect.getattr_static` 非 property，且不在 `__abstractmethods__`）；6 个 async 方法全部默认 no-op；`TurnContext` 11 字段、`StepContext` 15 字段与计划逐字一致；`OnlyName(LoopHook)`（仅覆写 `name`）实例化成功 | 无 |
| **1.2** 定义 LLMStrategy ABC | ✅ | ① `call()` 含 `on_chunk`/`on_error`/`should_abort`；② `LLMCallResult` 含 message/message_id/tokens/success/aborted/error 字段；③ `reset()` 默认 no-op；④ 不依赖 communicator/session_manager/context | 新建 `broca/components/llm_strategy.py`（99 行）；`call(history, tools, *, on_chunk=None, on_error=None, should_abort=None)`；`initialize(*, llm_client, config)` 抽象（N5）；`LLMCallResult` 8 字段；模块导入表仅 `abc/dataclasses/typing/broca.components.base` | 无 |
| **1.3** 定义 ToolExecutionStrategy ABC | ✅ | ① `execute()` 返回 `list[ToolResult]` 且顺序一致；② 含 `should_abort`（不引用 `ToolCallContext.abort_event`）；③ `reset()` 默认 no-op | 新建 `broca/components/tool_strategy.py`（69 行）；`execute(tool_calls, context, tool_mapping, *, allowed_tools=None, should_abort=None) -> list[ToolResult]`；`initialize(*, tool_executor, config)`；docstring 显式声明「`ToolCallContext` 无 `abort_event`，abort 走 `should_abort`」 | 无 |
| **1.4** 更新 LoopEngine ABC initialize 签名 | ✅ | ① 新增 4 参数且全部有默认值；② `add_hook()` 非抽象；③ `Agent.create()` 无需改动，全量测试通过 | `broca/components/loop_engine.py`：`initialize` 末尾新增 `llm_strategy=None / tool_strategy=None / hooks=None / memory_manager=None`（`inspect.signature` 验证默认值均为 `None`）；新增非抽象 `add_hook()`（append 到 `_hooks`，可多次调用）；`__abstractmethods__` 仍为 `{execute, abort, reset, initialize}`；docstring 记录 `permission_provider` vs `tool_permission_manager` 历史差异 | 无 |
| **1.5** 包化骨架 | ✅ | ① `broca/loop_engine.py` 不存在；② `from broca.loop_engine import DefaultLoopEngine, LoopEngine, ExecutionStatus, ExecutionResult` 成功；③ `from broca.components.defaults import *` 成功；④ `m.__file__` 指向包 `__init__.py`；⑤ `pytest broca/tests/ -q` 0 失败、总数 ≥751 | `git mv broca/loop_engine.py broca/loop_engine/legacy.py`（1427 行，内容零改动）；新建包 `__init__.py`（re-export + `LoopEngine = DefaultLoopEngine` 别名 + docstring 声明「ABC 从 `broca.components` 导入」）；`strategies/__init__.py`、`hooks/__init__.py` 骨架；`broca/tests/fixtures/llm_streaming/.gitkeep`；registry 解析链验证：`ComponentRegistry.resolve(LoopEngine ABC)` → `broca.loop_engine.legacy:DefaultLoopEngine`（字符串路径 `broca.loop_engine:DefaultLoopEngine` 未变） | ⚠️ 见 Deviations D1（定稿方案 B：改写测试 patch 目标，包入口不含 shim） |

> ✅ = All ACs met, ⚠️ = Partial (reported), ❌ = Not completed

## Deviations

### D1（⚠️ 计划未覆盖，已按评审指示定稿为方案 B）：`broca.loop_engine.asyncio` patch 目标失效

- **现象**：`test_loop_engine.py` 中有 8 处 `patch("broca.loop_engine.asyncio.sleep")`。包化后 `broca.loop_engine` 是包，其 `__init__` 不再有 `asyncio` 属性 → `AttributeError: module 'broca.loop_engine' has no attribute 'asyncio'`，导致 7 个用例失败（`TestRateLimitRetry` 5 例 + `TestEmptyResponseRetry` 2 例），违反 Phase 1 AC「0 失败」。
- **计划未覆盖**：Phase 1 约定「除 `components/loop_engine.py`、`components/__init__.py`、`broca/loop_engine.py`(git mv) 外不修改已有文件」，因此原计划不允许改测试文件。
- **决策过程**：先询问用户（A：包 `__init__` 加 `asyncio` shim / B：改写 patch 目标），询问超时后临时按 A 落地；随后评审指示「偏离按更合理方式处理」，**最终定稿为 B**。
- **最终处理（B）**：
  1. 把 `broca/tests/test_loop_engine.py` 中 8 处 patch 目标机械改写为 `patch("broca.loop_engine.legacy.asyncio.sleep")` —— 语义准确（打桩的是真正调用 `asyncio.sleep` 的 legacy 模块），patch 的仍是全局 `asyncio.sleep`，行为与包化前完全等价；
  2. **移除**包 `__init__.py` 中临时的 `import asyncio as asyncio` shim —— 生产包入口保持干净，无 Phase 5 清理债务；
  3. 复测：`751 passed / 3 skipped`（0 失败）。
- **影响面**：仅测试文件 patch 路径 8 行；Task 4.3 迁移这些用例到策略层测试时会整体重写，无额外负担。
- **风险**：无（patch 目标更精确，不再依赖包命名空间副作用）。

### D2（记录）：`git mv` 未提交
- 仓库当前有大量未提交改动（`broca/components/` 整个目录仍是 untracked）。本次**未做任何 git 提交**，仅执行了 `git mv` 与文件新建；验证期间临时 `git add` 已 `git reset` 还原，工作区状态保持「既有未提交改动 + 本次新增」。
- 后果提示：`git status` 会显示 ` D broca/loop_engine.py` + `?? broca/loop_engine/`，这是预期的包化结果（非误删）。

## Quality Checklist

- [x] All phase-level ACs satisfied（逐条脚本化验证：`ALL PHASE-1 AC CHECKS PASSED`）
- [x] All task-level ACs satisfied（5/5 任务）
- [x] No missing tasks（对照计划 Phase 1：Task 1.1–1.5 共 5 个，全部建卡并完成）
- [x] No extra functionality（仅新增 3 个接口文件 + 包骨架 + fixtures 占位；未实现任何策略/Hook 实现类，未碰 `engine.py`）
- [x] Manually verified key behaviors（见下「验证证据」）
- [x] Code follows project conventions（`from __future__ import annotations`、TYPE_CHECKING 分组、中文 docstring 与现有一致；新文件 `ruff check --select I001,RUF100` 全绿）
- [x] Compatible with existing work（`ComponentRegistry` 字符串路径可解析；`Agent.create()` 零改动）

## 验证证据

### 1. 全量测试（基线 754 collected）
```
python -m pytest broca/tests/ -q
→ 751 passed, 3 skipped, 1 deselected, 20 warnings in 38.23s

python -m pytest broca/tests/ --collect-only -q
→ 754/755 tests collected (1 deselected)
```
（3 skipped 为既有 skip，与迁移前一致；0 失败）

### 2. 关键集成子集
```
python -m pytest broca/tests/test_agent_composition.py broca/tests/test_component_interfaces.py \
                 broca/tests/test_components_registry.py broca/tests/test_loop_engine.py \
                 broca/tests/test_image_tool.py -q
→ 131 passed
```

### 3. 接口契约
| 检查 | 结果 |
|------|------|
| `LoopHook.name` 非抽象类属性（非 property） | ✅ `"loop_hook"`，不在 `__abstractmethods__` |
| 6 个生命周期方法均为 `async def` 且默认 no-op | ✅ `inspect.iscoroutinefunction` 全 True |
| 只覆写 `name` 的空子类可实例化（防 C5 回归） | ✅ |
| `LLMStrategy.call` 关键字参数 | ✅ `on_chunk` / `on_error` / `should_abort` |
| `LLMStrategy.reset` / `ToolExecutionStrategy.reset` 非抽象 | ✅ |
| `ToolExecutionStrategy.execute` 签名 | ✅ `(tool_calls, context, tool_mapping, *, allowed_tools, should_abort)` |
| `LoopEngine.initialize` 4 个新参数默认值 | ✅ 全部 `None`（POSITIONAL_OR_KEYWORD） |
| `LoopEngine.add_hook` 非抽象、可多次追加 | ✅ `_hooks` 长度 2 |
| `LLMStrategy`/`ToolExecutionStrategy` 模块无 communicator/session/context 依赖 | ✅ |

### 4. 包化 / 注册表
```
python -c "import broca.loop_engine as m; print(m.__file__)"
→ .../broca/loop_engine/__init__.py

ComponentRegistry().register_defaults().resolve(broca.components.LoopEngine)
→ broca.loop_engine.legacy:DefaultLoopEngine  (issubclass → True)
```
- `broca/loop_engine.py` 已不存在 ✅
- `git mv` 保持内容不变：`legacy.py` 1427 行（与工作区原 `broca/loop_engine.py` 一致，`git mv` 语义保证）✅

## 变更文件清单

| 文件 | 类型 | 行数 | 说明 |
|------|------|:----:|------|
| `broca/components/loop_hook.py` | 新增 | 115 | `LoopHook` ABC + `TurnContext` + `StepContext` |
| `broca/components/llm_strategy.py` | 新增 | 99 | `LLMStrategy` ABC + `LLMCallResult` |
| `broca/components/tool_strategy.py` | 新增 | 69 | `ToolExecutionStrategy` ABC |
| `broca/components/loop_engine.py` | 修改 | 170（原 ~140） | `initialize` 新增 4 个可选参数 + `add_hook()` + docstring |
| `broca/components/__init__.py` | 修改 | +9 | re-export 5 个新类型 + 模块 docstring 补充 |
| `broca/tests/test_loop_engine.py` | 修改 | 8 行 | patch 目标 `broca.loop_engine.asyncio.sleep` → `broca.loop_engine.legacy.asyncio.sleep`（D1/B） |
| `broca/loop_engine/__init__.py` | 新增 | 17 | 包入口（re-export + `LoopEngine` 兼容别名） |
| `broca/loop_engine/legacy.py` | 重命名 | 1427 | `git mv broca/loop_engine.py` → 内容零改动 |
| `broca/loop_engine/strategies/__init__.py` | 新增 | 5 | Phase 2 骨架 |
| `broca/loop_engine/hooks/__init__.py` | 新增 | 5 | Phase 3 骨架 |
| `broca/tests/fixtures/llm_streaming/.gitkeep` | 新增 | 0 | golden fixture 目录占位 |

## 对后续 Phase 的影响 / 提示

1. **Phase 2** 可独占 `broca/loop_engine/strategies/`（`__init__.py` 已就绪），需实现 `retry_llm.py` / `parallel_tool.py` / `serial_tool.py` / `factory.py`。
2. **Phase 3** 可独占 `broca/loop_engine/hooks/` 与 `compressor_context.py`；`LoopHook` 的 6 个生命周期方法与 `name` 契约已固化。
3. **Phase 4** 切换时注意：`broca/loop_engine/__init__.py` 的 import 需从 `legacy` 改为 `engine`；Task 4.3 迁移 `test_loop_engine.py` 时，8 处 `broca.loop_engine.legacy.asyncio.sleep` patch 目标需随用例迁到策略层测试（改为 patch 策略模块）。
4. **Phase 5** 删除 `legacy.py` 后，仓库内不得再残留任何 `broca.loop_engine.legacy` 引用（含测试 patch 目标）。
