# Refactor 分支工具实现 Bug 修复计划

## 概述
- **目标**：修复 `refactor` 分支中 `broca/tools/` 下所有已识别的逻辑错误和代码质量问题
- **背景**：代码审查发现 10 个问题（3 个严重、2 个中等、5 个轻微），涉及 `agent_interaction.py`、`skill.py`、`blackboard.py`、`tool.py`、`todo.py`、`web.py`、`filesystem.py` 共 7 个文件
- **约束条件**：所有修改在 `refactor` 分支上进行，不得引入新的 API 变更或破坏现有工具接口的 schema

## 相关材料
- `broca/tools/tool.py` — 工具基类，包含 `_check_type` 和 `validate_arguments`
- `broca/tools/agent_interaction.py` — AssignTask 和 AskUser 工具
- `broca/tools/skill.py` — SkillManage 工具的子文件管理
- `broca/tools/blackboard.py` — 黑板工具族（Read/Write/List/Changes/Delete）
- `broca/tools/todo.py` — Todo 管理工具
- `broca/tools/web.py` — WebFetch 和 WebSearch 工具
- `broca/tools/filesystem.py` — 文件操作工具族
- `broca/tests/test_tool_base.py` — 工具基类测试
- Python 3.12 `Path.is_relative_to()` API 文档

## 总体方案
按严重程度分为两个阶段：
1. **Phase 1 — 严重/中等 Bug 修复**：修复会导致运行时崩溃、安全漏洞或功能异常的问题（6 个任务，含测试编写）
2. **Phase 2 — 代码质量清理**：修复轻微问题、清理死代码、增强健壮性（5 个任务）

两个阶段顺序执行，Phase 1 完成后运行完整测试套件确认无回归，再进入 Phase 2。

> **注意**：`tool.py` 在两个 Phase 中均有修改（Phase 1 的 Task 1.4 修改 `_check_type`，Phase 2 的 Task 2.1 修改 `execute` 方法）。Phase 2 的测试基线包含 Phase 1 的所有变更。

## 执行计划

### Phase 1: 严重/中等 Bug 修复
**目标**：消除所有可能导致运行时崩溃、安全漏洞或功能异常的 bug，并为修复编写回归测试

**阶段验收标准**：
- [ ] `AssignTask` 在 `get_latest_assistant_message()` 返回 None 时不再抛出 UnboundLocalError
- [ ] `SkillManage._handle_subfile` 无法通过路径穿越写入 skill 目录外的文件
- [ ] `BlackboardChanges` 对 datetime 类型 timestamp 不再抛出 TypeError
- [ ] 布尔值 `True`/`False` 无法通过 "integer"/"number" 类型校验
- [ ] `todo.py` 错误提示包含全部合法状态值
- [ ] 完整测试套件通过（`pytest broca/tests/ -x -q`）

---

#### Task 1.1: 修复 AssignTask UnboundLocalError
- **文件**：`broca/tools/agent_interaction.py`
- **目标**：修复 blocking 模式下 `content` 变量可能未定义的崩溃
- **步骤**：
  1. 在 `AssignTask._execute` 的 blocking 分支中，`message = target_agent.context.get_latest_assistant_message()` 之后、`if message:` 之前，添加默认赋值 `content = "Task completed."`
  2. 保留原有 `if message: content = "Message from agent: " + message` 逻辑不变
- **预期产出**：修改后的 `agent_interaction.py`，blocking 模式在任何情况下都能安全返回 ToolResult
- **验收标准**：
  - [ ] 当 `get_latest_assistant_message()` 返回 `None` 时，blocking 执行 COMPLETED 状态返回 content="Task completed."（而非崩溃）
  - [ ] 当 `get_latest_assistant_message()` 返回非空字符串时，行为不变（content="Message from agent: ..."）
  - [ ] 当 `get_latest_assistant_message()` 返回空字符串 `""` 时，不崩溃，返回 "Task completed."

#### Task 1.2: 修复 SkillManage 路径穿越漏洞
- **文件**：`broca/tools/skill.py`
- **目标**：用 `Path.is_relative_to()` 替换不安全的 `str.startswith()` 路径包含检查
- **步骤**：
  1. 在 `_handle_subfile` 方法中，将 `if not str(target).startswith(str(skill_dir.resolve()))` 替换为 `if not target.is_relative_to(skill_dir.resolve())`
  2. 确认 Python 版本 ≥ 3.9（项目要求 ≥ 3.12，满足）
- **预期产出**：修复后的路径检查逻辑
- **验收标准**：
  - [ ] `file_path = "../other-skill/file.txt"` 被拒绝（路径逃逸）
  - [ ] `file_path = "../../etc/passwd"` 被拒绝
  - [ ] `file_path = "references/guide.md"` 被允许（正常子路径）
  - [ ] `file_path = "../my-skill-evil/file.txt"` 被拒绝（前缀相似但不同目录）
  - [ ] 对 `my-skill` 执行 `write_file(file_path='references/guide.md')` 成功写入且文件内容正确；执行 `remove_file(file_path='references/guide.md')` 后文件不存在

#### Task 1.3: 修复 BlackboardChanges timestamp 类型处理
- **文件**：`broca/tools/blackboard.py`
- **目标**：兼容 `datetime` 对象和 ISO 字符串两种 timestamp 格式
- **步骤**：
  1. 在 `BlackboardChanges._execute` 中，将 `c['timestamp'][11:19]` 替换为安全提取：
     ```python
     ts = c['timestamp']
     ts_str = ts.isoformat() if hasattr(ts, 'isoformat') else str(ts)
     # 然后使用 ts_str[11:19]
     ```
     > **注意**：如果 `timestamp` 既不是 `datetime` 也不是 ISO 字符串（例如 Unix epoch 数字），`str(ts)` 不会产生时间格式，`[11:19]` 切片会得到错误结果。执行前需确认 `blackboard.get_changes()` 返回的 `timestamp` 字段类型范围（预期为 `datetime` 对象或 ISO 格式字符串）。
  2. `ListBlackboard._execute` 中 `entry.updated_at.strftime("%H:%M:%S")` 已正确使用 datetime API（`strftime` 是 datetime 方法），经检查无需额外处理。
- **预期产出**：兼容两种 timestamp 表示的格式化代码
- **验收标准**：
  - [ ] 当 `c['timestamp']` 是 `datetime` 对象时，正确输出 HH:MM:SS 格式时间
  - [ ] 当 `c['timestamp']` 是 ISO 字符串 `"2024-01-15T14:30:00"` 时，正确输出 `"14:30:00"`
  - [ ] 不产生任何 TypeError

#### Task 1.4: 修复 _check_type 布尔值绕过
- **文件**：`broca/tools/tool.py`
- **目标**：使布尔值仅通过 "boolean" 类型校验，不被 "integer"/"number" 接受
- **步骤**：
  1. 在 `Tool._check_type` 方法开头（`type_map` 定义之前）添加布尔值短路判断：
     ```python
     if isinstance(value, bool):
         if isinstance(expected_type, str):
             return expected_type == "boolean"
         elif isinstance(expected_type, list):
             return "boolean" in expected_type
         return False
     ```
- **预期产出**：类型校验不再混淆 bool 和 int
- **验收标准**：
  - [ ] `_check_type(True, "integer")` 返回 `False`
  - [ ] `_check_type(False, "number")` 返回 `False`
  - [ ] `_check_type(True, "boolean")` 返回 `True`
  - [ ] `_check_type(1, "boolean")` 返回 `False`
  - [ ] `_check_type(42, "integer")` 返回 `True`（非布尔整数不受影响）
  - [ ] `_check_type(True, ["string", "boolean"])` 返回 `True`

#### Task 1.5: 修复 todo.py 错误提示信息
- **文件**：`broca/tools/todo.py`
- **目标**：修正 `_validate_todos` 中遗漏 `in_progress` 的错误提示
- **步骤**：
  1. 将 `return "Invalid status. Valid values: pending, completed"` 改为 `return "Invalid status. Valid values: pending, in_progress, completed"`
- **预期产出**：准确的状态枚举错误提示
- **验收标准**：
  - [ ] 传入 `status: "unknown"` 时，错误消息包含 "pending, in_progress, completed"
  - [ ] 传入 `status: "in_progress"` 时，验证通过不报错

#### Task 1.6: 为 Phase 1 所有修复编写回归测试
- **文件**：`broca/tests/test_tool_base.py`（或新建 `broca/tests/test_tool_bugfixes.py`）
- **目标**：为 Task 1.1–1.5 的修复编写自动化回归测试，防止未来回归
- **步骤**：
  1. **Test 1.1**（UnboundLocalError）：mock `target_agent.context.get_latest_assistant_message()` 分别返回 `None`、`""`、`"hello"`，调用 `AssignTask._execute`，断言不抛出 `UnboundLocalError` 且 content 正确
  2. **Test 1.2**（路径穿越）：构造 `SkillManage` 实例，对 `_handle_subfile("write", {...})` 分别传入：
     - `file_path="../other-skill/evil.txt"` → 断言返回 ToolStatus.ERROR
     - `file_path="../my-skill-evil/evil.txt"` → 断言返回 ToolStatus.ERROR
     - `file_path="references/guide.md"` → 断言返回 ToolStatus.SUCCESS
  3. **Test 1.3**（timestamp 类型）：mock `blackboard.get_changes()` 返回 `timestamp` 分别为 `datetime(2024,1,15,14,30,0)` 和 `"2024-01-15T14:30:00"`，调用 `BlackboardChanges._execute`，断言输出包含 `"14:30:00"`
  4. **Test 1.4**（布尔类型校验）：直接调用 `Tool._check_type` 验证 6 组输入输出对（与 Task 1.4 AC 一致）
  5. **Test 1.5**（错误提示）：调用 `TodoManagement._validate_todos` 传入 `status="unknown"`，断言返回的错误字符串包含 `"in_progress"`
- **预期产出**：至少 5 个测试函数，覆盖 Phase 1 所有修复的回归场景
- **验收标准**：
  - [ ] `pytest broca/tests/ -k "test_tool_bugfix or test_check_type or test_assign_task or test_path_traversal" -v` 全部通过
  - [ ] 每个测试独立可运行，不依赖其他测试的副作用
  - [ ] 测试中使用的 mock 对象正确模拟了被测方法的依赖

---

### Phase 2: 代码质量清理
**目标**：消除死代码、增强边界情况处理、修复设计缺陷

**阶段验收标准**：
- [ ] `validate_arguments` 对 `null` JSON 输入返回清晰的参数错误而非通用异常
- [ ] `WebFetch` 的 Playwright 初始化/关闭有并发保护
- [ ] `ReadBlackboard` 中的死代码已移除
- [ ] `TreeDir._build_tree` 签名中移除了未使用的 `is_last` 参数
- [ ] `WebSearch` schema 中 `query` 不再对 `queries` 批量模式强制必填
- [ ] 完整测试套件通过（`pytest broca/tests/ -x -q`）

---

#### Task 2.1: 增强 validate_arguments 对 null 输入的防护
- **文件**：`broca/tools/tool.py`
- **目标**：当 `json.loads` 返回 `None`（输入为 `"null"`）时，返回清晰的参数错误
- **步骤**：
  1. 在 `Tool.execute` 方法中，`args_dict = json.loads(arguments)` 之后、`validate_arguments` 调用之前添加检查：
     ```python
     if not isinstance(args_dict, dict):
         return ToolResult(
             status=ToolStatus.ERROR,
             content=f"Tool arguments must be a JSON object, got {type(args_dict).__name__}"
         )
     ```
- **预期产出**：对非 dict 的 JSON 输入（null、array、string 等）返回明确的错误信息
- **验收标准**：
  - [ ] `arguments = "null"` → 返回 "Tool arguments must be a JSON object, got NoneType"
  - [ ] `arguments = "[1,2,3]"` → 返回 "Tool arguments must be a JSON object, got list"
  - [ ] `arguments = '{"key": "value"}'` → 正常处理，不受影响

#### Task 2.2: 为 WebFetch Playwright 添加并发锁
- **文件**：`broca/tools/web.py`
- **目标**：防止并发调用时重复初始化 Playwright 浏览器
- **步骤**：
  1. 在 `WebFetch.__init__` 中添加 `self._pw_lock = asyncio.Lock()`
  2. 修改 `_init_playwright` 方法，在 `if self.playwright is None:` 的整个初始化逻辑外包裹 `async with self._pw_lock:`
  3. 修改 `_close` 方法，使用 `async with self._pw_lock:` 保护关闭逻辑
  4. 确认锁的非重入安全性：`_init_playwright` 在 `_execute_playwright` 的 try 块中调用并释放锁；`_close` 在同一 try 块的 `finally` 中调用（此时 `_init_playwright` 的 `async with` 已退出），不存在嵌套持锁
- **预期产出**：并发安全的 Playwright 生命周期管理
- **验收标准**：
  - [ ] 两个并发 `web_fetch`（provider=playwright）调用不会同时创建两个浏览器实例（通过 mock 验证 `_init_playwright` 只被有效调用一次）
  - [ ] 单次 `web_fetch(provider='playwright')` 调用成功返回页面内容，不引入超过 100ms 的额外延迟
  - [ ] Code review 确认 `_init_playwright` 和 `_close` 中的 `async with self._pw_lock` 配对正确，且不在持锁期间调用需要同一锁的方法

#### Task 2.3: 移除 ReadBlackboard 死代码
- **文件**：`broca/tools/blackboard.py`
- **目标**：删除未使用的 `read_single` 内部函数及其注释
- **步骤**：
  1. 定位 `ReadBlackboard._execute` 中的 `def read_single(k: str):` 函数定义
  2. 删除该函数定义（约 3-4 行）以及其上方的注释行 `# 上面这个 def 不能直接 await，用内联写法`
- **预期产出**：更干净的代码，无未使用的局部函数
- **验收标准**：
  - [ ] `blackboard.py` 中不存在 `def read_single` 定义
  - [ ] 对已有黑板数据，`read_blackboard(key='topic')` 返回正确值；`read_blackboard(key=['a','b'])` 批量返回正确结果

#### Task 2.4: 清理 TreeDir._build_tree 未使用参数
- **文件**：`broca/tools/filesystem.py`
- **目标**：移除 `_build_tree` 方法签名中从未使用的 `is_last` 参数
- **步骤**：
  1. 从 `_build_tree` 方法签名中移除 `is_last: bool` 参数
  2. 修改 `_execute` 中对 `_build_tree` 的调用，移除 `is_last=True` 传参
  3. 修改递归调用处，移除 `is_last=is_last_item` 传参
- **预期产出**：更简洁的方法签名
- **验收标准**：
  - [ ] `_build_tree` 签名不再包含 `is_last` 参数
  - [ ] 所有调用处同步更新
  - [ ] 对 `broca/tools/` 目录执行 `tree_dir`，输出与修复前 diff 为空

#### Task 2.5: 修复 WebSearch schema 必填字段设计
- **文件**：`broca/tools/web.py`
- **目标**：`queries` 批量搜索模式下不强制要求 `query` 字段
- **步骤**：
  1. 将 `parameters` 中的 `"required": ["query"]` 改为 `"required": []`
  2. 在 `WebSearch._execute` 方法开头（provider 分发之前）添加手动校验：
     ```python
     has_single = bool(arguments.get("query"))
     has_batch = bool(arguments.get("queries"))
     if not has_single and not has_batch:
         return ToolResult(
             status=ToolStatus.ERROR,
             content="Either 'query' or 'queries' must be provided",
         )
     ```
  3. 确认 `validate_arguments` 不会因 `required: []` 而跳过其他 enum/type 校验（`validate_arguments` 仍会检查 `properties` 中定义的类型和 enum 约束）
- **预期产出**：`query` 和 `queries` 至少提供一个即可通过校验
- **验收标准**：
  - [ ] 仅传 `query="test"` → 正常工作
  - [ ] 仅传 `queries=[{"query": "test"}]` → 正常工作
  - [ ] 两者都不传 → 返回 "Either 'query' or 'queries' must be provided"
  - [ ] 两者都传 → 正常工作（queries 优先）

---

## 任务依赖关系

```
Phase 1（任务 1.1–1.5 互不依赖可并行，1.6 依赖 1.1–1.5 完成）:
  Task 1.1, 1.2, 1.3, 1.4, 1.5  （可并行）
       ↓
  Task 1.6  （依赖 1.1–1.5 全部完成）

Phase 2（依赖 Phase 1 完成 + 测试通过；内部任务互不依赖可并行）:
  Task 2.1, 2.2, 2.3, 2.4, 2.5  （可并行）

Phase 1 完成 → pytest broca/tests/ -x -q → Phase 2 → pytest broca/tests/ -x -q

⚠️ tool.py 跨 Phase 修改说明：Task 1.4（Phase 1）修改 _check_type，
Task 2.1（Phase 2）修改 execute 方法。两者修改区域不重叠，但 Phase 2
的测试基线已包含 Phase 1 的变更。
```

## 风险与应对
| 风险 | 影响 | 应对策略 |
|------|------|----------|
| `is_relative_to` 在 Python 3.8 不可用 | Task 1.2 无法执行 | 项目要求 Python ≥ 3.12，无风险。如有疑虑可加 `fallback` 实现 |
| `_check_type` 修改影响 MCP 工具参数校验 | MCP 工具传入 boolean 到 integer 参数时可能报错 | MCP 工具的参数 schema 由远端定义，如果远端 schema 正确声明了类型，boolean 传 integer 本身就是调用错误。此修复是纠正行为 |
| Playwright 锁引入死锁 | WebFetch 挂起 | `_close` 在 `_execute_playwright` 的 finally 中调用，此时 `_init_playwright` 的 `async with` 已退出，不存在嵌套持锁。使用 `asyncio.Lock`（非重入）安全 |
| WebSearch `required: []` 导致 LLM 不知道必须传 query | LLM 可能两个都不传 | 通过 `_execute` 中的手动校验给出明确错误提示引导 LLM 重试 |
| `blackboard.get_changes()` 返回的 timestamp 类型超出预期 | Task 1.3 的 `str(ts)` fallback 对 Unix epoch 数字不产生有效时间格式 | 执行前确认 `get_changes()` 的 timestamp 类型范围；如存在 epoch 数字，需额外添加 `datetime.fromtimestamp(ts).strftime(...)` 分支 |
| `tool.py` 在两个 Phase 中均被修改 | Phase 2 测试基线包含 Phase 1 变更 | 通过 Phase 间的完整测试 gate 隔离风险；Task 2.1 修改 `execute` 方法，Task 1.4 修改 `_check_type`，区域不重叠 |

## 执行后验证

每个 Phase 完成后执行：
```bash
cd /Users/luoweiang/code/Broca
source venv/bin/activate
pytest broca/tests/ -x -q
```

最终全量验证：
```bash
pytest broca/tests/ -v
```

## 未解决的问题
（无 — 所有技术决策已在计划中明确）
