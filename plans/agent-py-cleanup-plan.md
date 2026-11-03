# agent.py 代码审查修复计划

## 概述
- **目标**：修复 `refactor` 分支 `broca/agent.py` 中代码审查发现的所有问题，包括拼写错误、反模式、职责混乱和封装性缺陷
- **背景**：对 `.worktrees/refactor/broca/agent.py` 进行代码审查后，发现 14 个问题（另 1 个跨文件适配问题随 Phase 3 Task 3.3 一并处理），按严重程度分为明确 bug、架构问题和代码卫生三类
- **约束条件**：
  - 所有修改必须在 `refactor` 分支（worktree: `.worktrees/refactor`）上执行
  - **路径约定**：本文档所有相对路径均以 `.worktrees/refactor/` 为根目录，所有命令的 cwd = `.worktrees/refactor`。⚠️ 仓库根目录 `/Users/luoweiang/code/Broca/broca/agent.py` 是一个**完全不同的旧版本文件**（685 行，无 `_init_history`/`create()` 组合根），**绝对不要修改该文件**
  - 不改变 `Agent.create()` 作为组合根的整体架构（组合根重构需单独出计划）
  - 保持 `AgentReference` 协议接口稳定，不破坏外部调用方
  - 所有修改后需通过现有测试（`pytest broca/tests/test_agent_composition.py` 等）
  - **基线测试**：Phase 1 开始前先执行 `pytest broca/tests/ -x -q` 记录基线结果，以便区分「本次改动引入的失败」与「既存失败」

## 相关材料
- 目标文件：`broca/agent.py`（refactor worktree）
- 协议定义：`broca/components/protocols.py`（`AgentReference` 协议）
- 适配器：`broca/agent_reference.py`（`AgentReferenceAdapter`）
- 工具执行器：`broca/tools/executor.py`（L57 使用 `agent.permission_manager` 别名）
- Context 类：`broca/context.py`（`_init_history` 私有方法，L42）
- 配置类：`broca/agent_configs.py`（`AgentConfig`，`execution_config` 在 `__init__` 中总是被赋值）
- 测试：`broca/tests/test_agent_composition.py`（14 个测试用例覆盖 create/adapter/lifecycle/disconnect）
- 测试：`broca/tests/test_component_interfaces.py`（接口一致性，含 `PermissionManager` import）
- 测试：`broca/tests/test_permission_manager.py`
- 新增测试：`broca/tests/test_agent_command_routing.py`（Task 2.6 新建）
- 脚本：`scripts/verify_agent_e2e.py`（L192-193 引用 `STATUS_IDEL`）
- Runner：`broca/session_runner/orchestrator_runner.py`（L129 调用 `agent.context._init_history()`）

## 总体方案

按风险从低到高分 3 个阶段执行：
1. **Phase 1 — Quick Fixes**：拼写、类型提示、冗余参数、`__init__` 副作用消除 — 纯机械修改，风险极低
2. **Phase 2 — Structural Fixes**：命令拦截上移到 `start()`、`_abort_task` 语义修正、`cls.__new__` 修复、`start()` 异常兜底、`permission_manager` 别名移除 — 涉及调用链调整
3. **Phase 3 — Encapsulation & Cleanup**：`_init_history` 私有访问、`disconnect()` 防御性 `getattr`、双重 `tool_manager.init()` — 跨文件封装性改善

## 执行计划

### Phase 1: Quick Fixes
**目标**：消除拼写错误、类型不一致、冗余代码和 `__init__` 中的异步副作用

**阶段验收标准**：
- [ ] 代码库中不再存在 `STATUS_IDEL` 字符串
- [ ] `broca/agent.py` 中无 `Dict`/`List`/`Tuple` 的 import 与使用（Task 1.2 typing 内置泛型）
- [ ] `Agent.__init__` 不再包含 `asyncio.create_task`
- [ ] `on_llm_call_completed` 不再透传冗余的 `session_manager` 参数
- [ ] `execution_config` 的链式 `getattr` 已简化
- [ ] `ask_for_tool_permission` 的授权消息包含 `arguments`（超过 500 字符时截断并追加 `…(truncated, N chars)`）（Task 1.6）
- [ ] `pytest broca/tests/test_agent_composition.py -x` 通过
- [ ] `pytest broca/tests/test_context.py broca/tests/test_compact_command.py -x` 通过

#### Task 1.1: 修复 `STATUS_IDEL` 拼写错误
- **目标**：将 `STATUS_IDEL` 重命名为 `STATUS_IDLE`，全代码库统一
- **步骤**：
  1. `broca/agent.py` L26：`STATUS_IDEL = "idle"` → `STATUS_IDLE = "idle"`
  2. `broca/agent.py` L363, L514, L584, L602：`STATUS_IDEL` → `STATUS_IDLE`（4 处使用点）
  3. `scripts/verify_agent_e2e.py` L192-193：`agent.STATUS_IDEL` → `agent.STATUS_IDLE`（2 处）
- **预期产出**：7 处重命名，常量名拼写正确
- **验收标准**：
  - [ ] `grep -rn "STATUS_IDEL" --include="*.py" --exclude-dir=.git --exclude-dir=__pycache__ .worktrees/refactor/` 返回空结果
  - [ ] `grep -rn "STATUS_IDLE" --include="*.py" --exclude-dir=.git --exclude-dir=__pycache__ .worktrees/refactor/` 返回 7 处（定义 1 + 使用 4 + 脚本 2）
  - [ ] `pytest broca/tests/test_agent_composition.py -x` 通过

#### Task 1.2: 修复 `typing.Tuple` → 内置 `tuple`
- **目标**：Python 3.12+ 风格统一，使用内置泛型
- **步骤**：
  1. `broca/agent.py` L10：`from typing import Any, Dict, List, Optional, Tuple` → `from typing import Any, Optional`
  2. 同文件中所有 `Dict[` → `dict[`，`List[` → `list[`，`Tuple[` → `tuple[`
  3. **规则**：本次仅替换 `Dict`/`List`/`Tuple` → `dict`/`list`/`tuple`；`Optional` 一律保留为 `typing.Optional`，最小 diff
- **预期产出**：类型提示风格统一为内置泛型
- **验收标准**：
  - [ ] `broca/agent.py` 中不再 import `Dict`、`List`、`Tuple`（`Optional` 保留）
  - [ ] 所有类型注解使用 `dict[str, Any]`、`list[str]`、`tuple[bool, Optional[str]]` 等内置泛型
  - [ ] `python -c "import broca.agent"` 导入成功（可捕获残留 `NameError`）

#### Task 1.3: 消除 `__init__` 中的 `asyncio.create_task` 副作用
- **目标**：构造函数不应有异步副作用，将 `load_stats` 移到 `create()` 中显式 `await`
- **步骤**：
  1. `broca/agent.py` L69：删除 `asyncio.create_task(self.load_stats(session_manager))`
  2. `broca/agent.py` `create()` 方法中，在 `Agent.__init__` 调用之后、组件装配之前，添加 `await agent.load_stats(session_manager)`
  3. 确认 `load_stats` 方法签名不变（`load_stats` 内部已 try/except 吞异常，改为 `await` 后 DB 异常不会阻断 `create()`；额外 DB 往返的耗时影响可接受）
- **预期产出**：`__init__` 变为纯同步构造，`load_stats` 在 `create()` 中确定性执行
- **验收标准**：
  - [ ] `Agent.__init__` 中无 `asyncio.create_task` 调用
  - [ ] `Agent.create()` 中有 `await agent.load_stats(session_manager)` 且位于组件装配之前
  - [ ] `pytest broca/tests/test_agent_composition.py -x` 通过

#### Task 1.4: 简化 `execution_config` 的链式 `getattr`
- **目标**：`AgentConfig.__init__` 保证 `execution_config` 总是被赋值（`self.execution_config = ExecutionConfig()`），无需防御性 `getattr`
- **步骤**：
  1. `broca/agent.py` L61-63：
     ```python
     # 旧
     self.message_queue: asyncio.Queue = asyncio.Queue(
         getattr(getattr(self.config, "execution_config", None), "message_queue_size", 3)
     )
     # 新
     self.message_queue: asyncio.Queue = asyncio.Queue(
         self.config.execution_config.message_queue_size
     )
     ```
- **预期产出**：消除无意义的防御性代码
- **验收标准**：
  - [ ] `broca/agent.py` 中无 `getattr(getattr(` 嵌套链
  - [ ] `pytest broca/tests/test_agent_composition.py -x` 通过

#### Task 1.5: 移除 `on_llm_call_completed` 的冗余 `session_manager` 参数
- **目标**：`update_stats` 内部直接访问 `self.session_manager`，无需外部传入
- **步骤**：
  1. `broca/agent.py` L257-258：`update_stats` 签名移除 `session_manager` 参数：
     ```python
     # 旧
     async def update_stats(self, input_tokens: int, output_tokens: int, session_manager: SessionManager) -> None:
     # 新
     async def update_stats(self, input_tokens: int, output_tokens: int) -> None:
     ```
  2. `broca/agent.py` L268：`session_manager.agent_service.update(...)` → `self.session_manager.agent_service.update(...)`
  3. `broca/agent.py` L617：`await self.update_stats(input_tokens, output_tokens, self.session_manager)` → `await self.update_stats(input_tokens, output_tokens)`
- **预期产出**：方法签名更简洁，依赖通过 `self` 自然获取
- **验收标准**：
  - [ ] `update_stats` 签名不再包含 `session_manager` 参数
  - [ ] `on_llm_call_completed` 中调用 `self.update_stats(input_tokens, output_tokens)` 无第三参数
  - [ ] `grep -rn "update_stats" broca/` 确认无其他调用方需要适配

#### Task 1.6: 让 `ask_for_tool_permission` 的 `arguments` 参数实际生效
- **目标**：不再接受后丢弃 `arguments`，将其纳入授权消息
- **步骤**：
  1. `broca/agent.py` 中 `ask_for_tool_permission` 方法：
     ```python
     # 旧
     return await self.permission_provider.request_tool_permission(
         f"工具 `{tool_name}` 需要你授权。"
     )
     # 新
     detail = f"工具 `{tool_name}` 需要你授权。"
     if arguments:
         arg_str = str(arguments)
         if len(arg_str) > 500:
             arg_str = arg_str[:500] + f"…(truncated, {len(arg_str)} chars)"
         detail += f"\n参数: {arg_str}"
     return await self.permission_provider.request_tool_permission(detail)
     ```
- **安全说明**：`PermissionProvider.request_tool_permission` 会将该消息 `save_message(...)` 持久化到会话 DB 并推送到前端。工具参数可能含密钥/文件全文，必须截断以防敏感信息落库与消息膨胀
- **预期产出**：`arguments` 参数被实际使用，授权消息更完整且安全
- **验收标准**：
  - [ ] `ask_for_tool_permission` 的 `arguments` 参数参与构造授权消息
  - [ ] `arguments` 为空时消息不包含 "参数:" 行
  - [ ] `arguments` 超过 500 字符时截断并追加 `…(truncated, N chars)`
  - [ ] `pytest broca/tests/test_agent_composition.py -x` 通过

---

### Phase 2: Structural Fixes
**目标**：解决职责混乱、语义偷换、异常处理缺失等架构层面问题

**前提**：Phase 2 全部任务以 Phase 1 完成为前提

**阶段验收标准**：
- [ ] `run()` 方法不再包含任何命令解析/分发逻辑
- [ ] `start()` 循环有兜底 `except Exception` 处理
- [ ] `_on_connected` 不再用 `_abort_task` 判定运行状态
- [ ] `cls.__new__` + `Agent.__init__` 模式已替换
- [ ] `permission_manager` 别名已移除，所有调用方改用 `permission_provider`
- [ ] `pytest broca/tests/test_agent_composition.py -x` 通过
- [ ] `pytest broca/tests/test_component_interfaces.py -x` 通过
- [ ] `pytest broca/tests/test_compact_command.py broca/tests/test_engine_dispatch.py broca/tests/test_engine_event_flow.py -x` 通过
- [ ] `pytest broca/tests/test_agent_command_routing.py -x` 通过

#### Task 2.1: 命令拦截从 `run()` 上移到 `start()`
- **目标**：`run()` 变为纯执行方法；命令解析/分发在消息循环层（`start()`）完成
- **步骤**：
  1. **新增 `_try_dispatch_inline_command` 方法**（放在 `run()` 之前；建议紧邻 `_handle_command` 放置，两者同属命令处理链路，便于阅读）：
     ```python
     async def _try_dispatch_inline_command(self, message: Message) -> bool:
         """尝试将用户消息作为 inline command 处理。
         返回 True 表示已作为命令处理（不再是普通对话）。
         """
         if not getattr(self, "command_manager", None):
             return False
         content = message.data.get("content", "")
         if not content:
             return False
         parsed = self.command_manager.parse(content)
         if not parsed:
             return False
         name, args = parsed
         await self._handle_command(name, args, message)
         return True
     ```
  2. **修改 `start()` 消息循环**（L437-448）：
     ```python
     # 旧
     message = await asyncio.wait_for(self.message_queue.get(), timeout=1)
     if message.message_type == MessageType.USER_MESSAGE:
         await self.run(message)
     # 新
     message = await asyncio.wait_for(self.message_queue.get(), timeout=1)
     if message.message_type == MessageType.USER_MESSAGE:
         if not await self._try_dispatch_inline_command(message):
             await self.run(message)
     ```
  3. **修改 `run()`**（L475-483）：删除整个命令拦截块（L475-483 的 `# ═══ Command interception` 注释块）
  4. **修改 `_handle_command`**（L533-536）：命令未命中时的 fallback 改为直接 `run()` 调用，移除递归风险说明注释；同步更新 `_handle_command` 的 docstring（现为「Handle a command intercepted in **run()**」，应改为引用 `start()` 消息循环）
  5. **修改 `run()` 的 `from_agent` 参数语义注释**：明确其含义是 "来自其他 agent 的消息"，不再兼做 "跳过命令拦截" 的开关；同步更新 `run()` 的 docstring
- **预期产出**：`run()` 职责单一（纯执行），命令处理在 `start()` 消息路由层
- **验收标准**：
  - [ ] `run()` 方法体中无 `command_manager.parse`、`_handle_command` 调用
  - [ ] `start()` 中 `USER_MESSAGE` 分支先调用 `_try_dispatch_inline_command`，返回 `False` 时才调用 `self.run(message)`
  - [ ] `_handle_command` 的 fallback（命令未找到）调用 `self.run(original_message)` 时不再传 `from_agent=True`（因为命令拦截已不在 `run()` 中）
  - [ ] **行为测试**：向 `message_queue` 放入一条 `/compact` 命令消息，调用 `start()` 一个周期，验证命令 handler 被调用且 `execution_engine.execute` 未被调用
  - [ ] **行为测试**：向 `message_queue` 放入一条普通文本消息（非命令），验证 `execution_engine.execute` 被调用且 `command_manager.dispatch` 未被调用
  - [ ] `pytest broca/tests/test_agent_composition.py -x` 通过

#### Task 2.2: 修复 `_abort_task` 的 truthiness 歧义
- **目标**：将 `_abort_task` 的判断从 truthiness 改为显式 `is not None`，消除 `Task` 对象 truthiness 的歧义
- **背景**：`_abort_task` 在此处是必要的——`status` 在断连时已被 `_on_disconnected` 覆盖为 `DISCONNECTED`，无法区分断连前是 running 还是 idle，而 `_abort_task` 是否非空能准确反映"断连前是否有执行中的 task"。本任务仅修正判断方式，不改变判定逻辑。
- **步骤**：
  1. `broca/agent.py` 中 `if self._abort_task`（在 `restore_status = self.STATUS_RUNNING if self._abort_task is not None else ...` 附近）→ `if self._abort_task is not None`
  2. 在该行添加注释：`# 用 _abort_task 而非 status 判断：断连时 status 已被覆盖为 DISCONNECTED，无法区分断连前的 running/idle`
- **预期产出**：语义更明确，消除 truthiness 歧义
- **验收标准**：
  - [ ] `restore_status = self.STATUS_RUNNING if self._abort_task is not None` 使用 `is not None` 而非 truthiness
  - [ ] 注释包含 "DISCONNECTED" 和 "status" 关键词，解释断连时 status 被覆盖的原因
  - [ ] `pytest broca/tests/test_agent_composition.py -x` 通过

#### Task 2.3: 修复 `create()` 中的 `cls.__new__` + `Agent.__init__` 模式
- **目标**：使用标准实例化路径，避免 MRO 绕过
- **步骤**：
  1. **前置检查**：确认当前代码库无 `Agent` 子类（`grep -rn "class.*\(Agent\)" --include="*.py" .worktrees/refactor/broca/ | grep -v "class Agent:" | grep -v "AgentReferenceAdapter"`）。如果存在子类，需评估 `cls(...)` 会调用子类 `__init__` 而非 `Agent.__init__` 的影响
  2. `broca/agent.py` L107-108：
     ```python
     # 旧
     agent = cls.__new__(cls)
     Agent.__init__(agent, config, llm_client, session_manager, **kwargs)
     # 新
     agent = cls(config, llm_client, session_manager, **kwargs)
     ```
  3. 确认 `Agent.__init__` 签名与调用兼容（它接受 `config`, `llm_client`, `session_manager`, `**kwargs`）
- **预期产出**：标准 `__init__` 调用路径，支持子类化
- **验收标准**：
  - [ ] 前置检查确认代码库中无 `Agent` 的直接子类（`AgentReferenceAdapter` 是代理非子类）
  - [ ] `create()` 中无 `cls.__new__(cls)` 调用
  - [ ] `create()` 中使用 `cls(config, llm_client, session_manager, **kwargs)` 实例化
  - [ ] `pytest broca/tests/test_agent_composition.py -x` 通过

#### Task 2.4: `start()` 循环添加兜底异常处理
- **目标**：非 `TimeoutError` 异常不再导致消息循环崩溃
- **步骤**：
  1. `broca/agent.py` L428-448：
     ```python
     # 旧
     while self.running:
         try:
             # ...
         except asyncio.TimeoutError:
             continue
     # 新
     while self.running:
         try:
             # ...
         except asyncio.TimeoutError:
             continue
         except Exception as e:
             logger.exception(f"Unexpected error in message loop: {e}")
     ```
- **预期产出**：意外异常被记录但不中断消息循环
- **验收标准**：
  - [ ] `start()` 的 `while` 循环有 `except asyncio.TimeoutError` 和 `except Exception` 两级处理
  - [ ] 兜底 handler 使用 `logger.exception`（含 traceback）
  - [ ] **行为测试**：注入一个自定义 `ValueError` 到消息处理路径（mock `self.run` 抛出 `ValueError`），验证 `logger.exception` 被调用且 `self.running` 仍为 True（循环未退出）
  - [ ] `pytest broca/tests/test_agent_composition.py -x` 通过

#### Task 2.5: 移除 `permission_manager` 别名，统一使用 `permission_provider`
- **目标**：消除 `permission_manager` / `permission_provider` 双命名
- **步骤**：
  1. `broca/agent.py` L71-74：删除 `permission_manager` property
  2. `broca/tools/executor.py` L57：`agent.permission_manager` → `agent.permission_provider`（注意：此处出现在 `initialize()` 的 docstring 示例中，是文档修改而非逻辑修改，不影响运行时行为）
  3. **仅修改 `agent.permission_manager`（属性访问）**；`broca.permission_manager`（模块导入）与 `broca.tools.tool_permission_manager` **不得修改**。`broca/tests/test_component_interfaces.py` 中的 `from broca.permission_manager import PermissionManager` 引用的是**遗留模块**（接口一致性测试的被测对象），与 Agent 的 `permission_manager` 别名属性无关，保持不动
  4. 全局搜索 `grep -rn "\.permission_manager\b" --include="*.py" .worktrees/refactor/broca/` 确认无遗漏引用（注意排除 `broca.permission_manager` 模块导入和 `test_permission_manager` 文件）
  5. 验证 `grep -rn "permission_manager" .worktrees/refactor/broca/components/` 确认 `components/` 目录无引用（已预检为空）
- **预期产出**：代码库中 `permission_manager` 不再作为 Agent 属性使用
- **验收标准**：
  - [ ] `broca/agent.py` 中无 `permission_manager` property 定义
  - [ ] `grep -rn "\.permission_manager\b" --include="*.py" .worktrees/refactor/broca/ | grep -v "broca\.permission_manager" | grep -v test_permission_manager` 无结果（排除模块导入引用）
  - [ ] `grep -rn "permission_manager" .worktrees/refactor/broca/components/` 无结果
  - [ ] `broca/agent.py` 中无 `def permission_manager`（property 已删除）
  - [ ] `pytest broca/tests/test_component_interfaces.py -x` 通过（该文件**不得被修改**）
  - [ ] `pytest broca/tests/test_agent_composition.py -x` 通过

#### Task 2.6: 新增命令路由行为测试
- **目标**：为 Task 2.1 的命令路由上移和 Task 2.4 的异常兜底补充可执行的行为测试
- **步骤**：
  1. 新建 `broca/tests/test_agent_command_routing.py`，包含以下 3 个测试用例：
     ```python
     class TestAgentCommandRouting:
         async def test_start_routes_command_to_handler(self, agent, mock_command_manager, mock_execution_engine):
             """向 message_queue 放入 /compact 命令消息 → 验证 handler 被调用且 execution_engine.execute 未被调用"""
             ...

         async def test_start_routes_plain_text_to_run(self, agent, mock_command_manager, mock_execution_engine):
             """向 message_queue 放入普通文本消息（非命令）→ 验证 execution_engine.execute 被调用且 command_manager.dispatch 未被调用"""
             ...

         async def test_start_survives_unexpected_exception(self, agent, mock_execution_engine):
             """mock self.run 抛 ValueError → 验证 logger.exception 被调用且 self.running 仍为 True"""
             ...
     ```
  2. 确保测试使用与 `test_agent_composition.py` 相同的 fixture 模式（`create_agent` 等）
  3. 运行 `pytest broca/tests/test_agent_command_routing.py -x -v` 验证全部通过
- **预期产出**：命令路由和异常兜底具备自动化行为验证
- **验收标准**：
  - [ ] `broca/tests/test_agent_command_routing.py` 存在且包含 3 个测试用例
  - [ ] `test_start_routes_command_to_handler`：命令消息走 `_try_dispatch_inline_command` → handler 被调用，`execution_engine.execute` 未被调用
  - [ ] `test_start_routes_plain_text_to_run`：普通消息走 `run()` → `execution_engine.execute` 被调用，`command_manager.dispatch` 未被调用
  - [ ] `test_start_survives_unexpected_exception`：`run()` 抛异常 → `logger.exception` 被调用，`self.running` 仍为 True
  - [ ] `pytest broca/tests/test_agent_command_routing.py -x -v` 全部通过

---

### Phase 3: Encapsulation & Cleanup
**目标**：修复跨对象私有访问、防御性编码过度和重复初始化

**前提**：Phase 3 三任务均修改 `agent.py`/`context.py`，建议串行执行避免合并冲突

**阶段验收标准**：
- [ ] `Context` 有公开的 `reset_history()` 方法
- [ ] 代码库中无 `context._init_history` 调用
- [ ] `Agent` 的 `disconnect()` 无 `getattr` 防御
- [ ] `tool_manager.init()` 不再被双重调用
- [ ] `pytest broca/tests/test_agent_composition.py -x` 通过
- [ ] `pytest broca/tests/test_context.py broca/tests/test_compact_command.py -x` 通过

#### Task 3.1: 为 `Context` 添加公开的 `reset_history()` 方法
- **目标**：消除跨对象 `_init_history` 私有方法调用
- **步骤**：
  1. `broca/context.py`：在 `_init_history` 方法附近添加公开方法：
     ```python
     def reset_history(self) -> None:
         """Public API to reset the conversation history to initial state."""
         self._init_history()
     ```
  2. `broca/agent.py` 中 `self.context._init_history()` 的 2 处调用（compact 相关逻辑 + disconnect 前清理）→ `self.context.reset_history()`
  3. `broca/session_runner/orchestrator_runner.py` 中 `agent.context._init_history()` → `agent.context.reset_history()`
  4. 检查 `broca/context.py` 内部对 `_init_history` 的调用保持不变（类内部调用私有方法是正常的）
- **预期产出**：外部调用方使用公开 API
- **验收标准**：
  - [ ] `Context` 类有 `reset_history()` 公开方法
  - [ ] `grep -rn "\._init_history" --include="*.py" .worktrees/refactor/broca/` 结果仅在 `context.py` 内部（共 3 处：`__init__`、`build_history_from_session`、新增的 `reset_history`）
  - [ ] `pytest broca/tests/test_agent_composition.py -x` 通过

#### Task 3.2: 简化 `disconnect()` 的组件 shutdown 列表
- **目标**：移除不必要的 `getattr` 防御，组件列表明确化
- **步骤**：
  1. **在 `Agent.__init__` 中声明半初始化属性**（防止 `create()` 中途失败后 `disconnect()` 抛 `AttributeError`）：
     ```python
     # 在 Agent.__init__ 中（现有属性赋值区域附近）添加：
     self.context_compressor = None
     self.persistent_memory_manager = None
     ```
  2. `broca/agent.py` 中 `disconnect()` 的 shutdown 列表（`for comp in (self.execution_engine, ...)` 循环）：
     ```python
     # 旧
     for comp in (
         self.execution_engine,
         getattr(self.execution_engine, "tool_executor", None),
         getattr(self, "context_compressor", None),
         getattr(self, "persistent_memory_manager", None),
         self.permission_provider,
         self.communicator,
     ):
         if comp is not None and hasattr(comp, "shutdown"):
             await comp.shutdown()
     # 新
     shutdown_order = [
         self.execution_engine,
         self.execution_engine.tool_executor,
         self.context_compressor,
         self.persistent_memory_manager,
         self.permission_provider,
         self.communicator,
     ]
     for comp in shutdown_order:
         if comp is not None and hasattr(comp, "shutdown"):
             await comp.shutdown()
     ```
  3. 已确认 `LoopEngine.tool_executor` 为直接属性（`broca/loop_engine/engine.py:183`，在 `__init__`/`initialize` 共用的 DI 辅助方法中 `self.tool_executor = tool_executor`，两条构造路径都会赋值）→ 可安全直接访问
- **预期产出**：组件 shutdown 列表更清晰，半初始化路径安全
- **验收标准**：
  - [ ] `Agent.__init__` 中显式声明 `self.context_compressor = None` 和 `self.persistent_memory_manager = None`
  - [ ] `disconnect()` 中无 `getattr(self,` 调用
  - [ ] shutdown 组件列表为显式属性访问
  - [ ] `pytest broca/tests/test_agent_composition.py -x -k "disconnect"` 通过

#### Task 3.3: 消除 `tool_manager.init()` 的双重调用
- **目标**：`tool_manager.init()` 只在一个地方被调用
- **背景**：`agent_manager.create_agent()` 使用 `scope_key=agent_id or "__global__"` 获取 ToolManager，而 `Agent.create()` 使用 `scope_key=agent.agent_id`（`agent_id=None` 时为自动生成的 UUID）。两者是不同的 ToolManager 实例。因此不能移除 `Agent.create()` 中的 `init` 调用（否则 `agent_id=None` 时 agent 自己的 ToolManager 永远不会被初始化，MCP 工具静默丢失）。必须移除 `agent_manager.py` 中的前置调用。
- **步骤**：
  1. 确认 `ToolManager.init()` 是幂等的（有 `self._initialized` guard，重复调用安全）
  2. `broca/agent_manager.py` `create_agent()` 方法（L267-269）：移除前置 ToolManager init：
     ```python
     # 旧
     from broca.components import ComponentRegistry, ToolManager as ToolManagerABC
     registry = ComponentRegistry.get_instance()
     await registry.get(ToolManagerABC, scope_key=agent_id or "__global__").init(config.workspace)
     # 删除以上 3 行（整个 import + registry.get + .init 调用）
     ```
  3. `broca/agent_manager.py` `restore_agent()` 方法（L358-360）：同样移除前置 ToolManager init：
     ```python
     # 旧
     from broca.components import ComponentRegistry, ToolManager as ToolManagerABC
     registry = ComponentRegistry.get_instance()
     await registry.get(ToolManagerABC, scope_key=agent_id or "__global__").init(agent_config.workspace)
     # 删除以上 3 行
     ```
  4. 确认 `Agent.create()` L149-150 中的 `agent.tool_manager.init(config.workspace)` 保持不变（它使用正确的 `scope_key=agent.agent_id`）
- **预期产出**：`tool_manager.init()` 仅在 `Agent.create()` 中调用一次，且使用正确的 scope_key
- **验收标准**：
  - [ ] `broca/agent_manager.py` 中无 `ToolManager` 的 `import` 和 `.init()` 调用
  - [ ] `Agent.create()` 中仍保留 `await agent.tool_manager.init(config.workspace)`
  - [ ] `pytest broca/tests/test_agent_composition.py -x` 通过

---

## 任务依赖关系

```
Phase 1 (无逻辑依赖，但全部修改同一文件 agent.py，建议顺序执行避免合并冲突):
  Task 1.1 (STATUS_IDEL)  ─┐
  Task 1.2 (typing)       ─┤
  Task 1.3 (init sidefx)  ─┼── 无逻辑依赖，但修改同一文件
  Task 1.4 (getattr)      ─┤    （不同行，但仍建议串行提交）
  Task 1.5 (update_stats) ─┤
  Task 1.6 (arguments)    ─┘

Phase 2 (全部以 Phase 1 完成为前提):
  Task 2.1 (command→start) ── 依赖 Phase 1 完成（run() 签名稳定后再改）
  Task 2.2 (_abort_task)   ── 依赖 Task 1.1（AC 锚点涉及 STATUS_RUNNING 重命名后的代码）
  Task 2.3 (cls.__new__)   ── 依赖 Task 1.3（create() 中 load_stats 已 await）
  Task 2.4 (exception)     ── 依赖 Task 2.1（同一个 start() 方法）
  Task 2.5 (perm alias)    ── 依赖 Phase 1 完成
  Task 2.6 (behavior tests)── 依赖 Task 2.1 + Task 2.4（测试它们的行为）

Phase 3 (全部串行执行，涉及 agent.py/context.py):
  Task 3.1 (reset_history) ── 串行（第 1 个）
  Task 3.2 (disconnect)    ── 串行（第 2 个，依赖 3.1 已稳定 agent.py）
  Task 3.3 (double init)   ── 串行（第 3 个；建议 Phase 2 之后执行，因为 Phase 2 会改动 Agent.create() 的实例化路径，先稳定后再验证 ToolManager 装配）
```

## 风险与应对

| 风险 | 影响 | 应对策略 |
|------|------|----------|
| Task 2.1 命令上移后，外部代码直接 `agent.run()` 不再触发命令拦截 | 如果存在未发现的调用方，`/compact` 等命令在直接调用 `run()` 时失效 | 已排查，`run()` 的全部调用方如下：① `start()` L439（`from_agent=False`，正常用户消息）→ 命令拦截已上移到 `start()`，安全；② `start()` L446（`from_agent=True`，TASK_COMPLETE/ERROR）；③ `_handle_task()` L551（`from_agent=True`，agent 间任务）；④ `agent_interaction.py` L102（`from_agent=True`）；⑤ `commands/dispatcher.py` L98/106/113（dispatcher 构造的是 `USER_MESSAGE`，但**不传 `from_agent`**，其 content 为 `build_prompt()` 产物（非原始用户输入），不含命令前缀，故不受影响。**若未来有 PromptCommand 的 prompt 以 `/` 开头，需重新评估**）；⑥ `skill/skill_evolution.py:78`（`from_agent=True`，不受影响）。后 5 者均传 `from_agent=True` 或 content 不含命令前缀，不需要命令拦截。风险可控 |
| Task 2.3 `cls(...)` 替代 `cls.__new__` + `Agent.__init__` 后行为差异 | 如果 `Agent` 有子类且子类重写了 `__init__`，`cls(...)` 会调用子类 `__init__` 而非 `Agent.__init__` | 已在 Task 步骤中添加前置检查：`grep` 确认代码库无 `Agent` 直接子类。`Agent` 无自定义 `__new__`，当前无子类时 `cls(...)` 等价于 `cls.__new__(cls)` + `cls.__init__(...)`。风险极低 |
| Task 2.4 `except Exception` 兜底在持续异常（如 DB 连接丢失）下产生日志风暴 | 循环每秒重试一次，`logger.exception` 持续输出大量日志 | 可接受的权衡：当前不添加连续错误计数器（避免过度设计）。**观测信号**：上线后观察 `Unexpected error in message loop` 的日志频率，若 >10 条/分钟则启动阈值方案（如连续 10 次异常后 `self.running = False`）|
| Task 2.5 移除 `permission_manager` 后 `executor.py` 需要适配 | `executor.py` L57 的 `agent.permission_manager` 会 AttributeError（实际是 docstring，不触发运行时错误） | 已在 Task 步骤中明确修改 `executor.py` docstring |
| Task 3.3 移除 `agent_manager` 前置 `init` 后，`agent_id=None` 场景下 ToolManager 实例不匹配 | `agent_manager` 用 `scope_key="__global__"`，`Agent.create()` 用 `scope_key=auto-UUID`，是不同实例 | 方案已修正：移除 `agent_manager` 的前置调用（它操作的是 `__global__` scope 的实例，agent 自己用的是 auto-UUID scope 的实例），保留 `Agent.create()` 中的调用（使用正确的 scope_key）|
| Task 1.6 `arguments` 含敏感数据（密钥/文件全文）落库与前端展示 | `PermissionProvider.request_tool_permission` 会将消息 `save_message(...)` 持久化到会话 DB 并推送到前端；`write_file` 类工具参数可能包含完整文件内容 | 应对：`arguments` 超过 500 字符时截断并追加 `…(truncated, N chars)`；仅在 `arguments` 非空且长度 > 0 时拼接参数行 |
| Task 3.2 半初始化路径 `AttributeError` | `context_compressor`/`persistent_memory_manager` 仅在 `create()` 第 5 步赋值，若 `create()` 中途失败后 `disconnect()` 被调用，移除 `getattr` 后会抛 `AttributeError` | 应对：在 `Agent.__init__` 中显式声明 `self.context_compressor = None` / `self.persistent_memory_manager = None`，保证属性始终存在 |

## 未解决的问题

- **`ToolManager` scope_key 统一策略**：当前 `agent_id=None` 时 `agent_manager` 使用 `"__global__"` scope，`Agent.create()` 使用 auto-UUID scope，导致两个不同实例。本计划通过移除 `agent_manager` 的前置调用来规避问题，但根本解决方案（统一 scope_key 策略）需要单独讨论
- **`Agent` 子类化约束**：Task 2.3 将 `Agent.__init__` 硬编码改为 `cls(...)` 后，如果未来添加 `Agent` 子类，子类必须正确实现 `__init__(self, config, llm_client, session_manager, **kwargs)` 签名。当前无子类，但需在架构文档中记录此约束
- **`start()` 异常兜底的日志风暴防护**：Task 2.4 的 `except Exception` 在持续异常（如 DB 断连）下会每秒产生一条 `logger.exception`。是否需要连续错误计数器 + 阈值退出，待实际运行后根据日志量决定

## 不在本次范围

- **`create()` 组合根重构**（将 ~160 行 DI 逻辑提取为独立的 `AgentBuilder`）：这是一个独立的架构重构，需要单独出计划，涉及 `ComponentRegistry` 的交互模式变更
- **中英文注释统一**：属于风格偏好，不影响功能，可在后续 cleanup PR 中统一
- **`AgentConfig.execution_config` 的 dataclass 化**：涉及配置系统的更大范围改动
