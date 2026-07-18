# Phase 2: 提取 Agent + 工具改造 + 上下文集成 — Test Mapping
> Plan: plans/memory-system-upgrade-plan.md

## Task 2.1: 实现 PersistentMemoryManager

| AC | Test File | Test Function | Status |
|----|-----------|---------------|--------|
| check_and_extract() 在消息/步数未达阈值时直接返回 | `test_manager_extraction.py` ✨ (new) | `test_should_not_extract_below_threshold` | 🆕 |
| check_and_extract() 在已达阈值时触发子 Agent | `test_manager_extraction.py` ✨ (new) | `test_should_extract_when_met_threshold` | 🆕 |
| trigger_extraction() 跳过阈值检查直接触发 | `test_manager_extraction.py` ✨ (new) | `test_trigger_skips_threshold_check` | 🆕 |
| 提取执行中时新请求被跳过（不阻塞） | `test_manager_extraction.py` ✨ (new) | `test_skip_when_extraction_in_progress` | 🆕 |
| 子 Agent 只能调用白名单内的 7 个工具 | Static verification via grep | `ALLOWED_TOOLS` defined in manager.py | ✅ |
| edit_file/write_file 操作非记忆目录路径时被拒绝 | Static verification via code review | `MemoryStore._validate_path()` enforces | ✅ |
| 子 Agent 失败时 MEMORY.md 回滚到执行前内容 | Code review | `_do_extract()` has rollback logic | ✅ |
| 提取完成后发送系统通知消息 | Code review | `send_agent_system_message()` called | ✅ |

## Task 2.2: 实现提取 Prompt

| AC | Test File | Test Function | Status |
|----|-----------|---------------|--------|
| Prompt 中包含 4 种记忆类型的定义和保存规则 | `test_prompts.py` ✨ (new) | `test_prompt_contains_memory_types` | 🆕 |
| Prompt 中包含"不该存什么"的明确规则 | `test_prompts.py` ✨ (new) | `test_prompt_contains_exclusions` | 🆕 |
| Prompt 中包含现有记忆清单 | `test_prompts.py` ✨ (new) | `test_prompt_includes_existing_index` | 🆕 |
| 有 hint 时，prompt 中体现 hint 指示 | `test_prompts.py` ✨ (new) | `test_prompt_includes_hint` | 🆕 |
| Prompt 中包含 frontmatter 格式示例 | `test_prompts.py` ✨ (new) | `test_prompt_contains_frontmatter_example` | 🆕 |
| Prompt 要求相对日期转绝对日期 | `test_prompts.py` ✨ (new) | `test_prompt_requires_absolute_dates` | 🆕 |

## Task 2.3: 改造 MemoryTool + 注入到系统

| AC | Test File | Test Function | Status |
|----|-----------|---------------|--------|
| memory 工具只有 hint 一个可选参数（可为空） | `test_tool.py` | `TestMemoryTool::test_tool_parameters`, `test_hint_is_optional` | ✅ |
| 调用 memory 不阻塞主 Agent（异步） | Code review | `asyncio.create_task()` used ✅ | ✅ |
| 工具返回 "Memory extraction triggered" + hint | `test_tool_execution.py` ✨ (new) | `test_tool_returns_trigger_message` | 🆕 |
| 删除原 MemoryStore 类和 add/replace/remove 逻辑 | `test_tool.py` | `TestMemoryTool::test_tool_description_has_trigger_semantics` | ✅ |
| agent.py 中 _setup_persistent_memory() 正确初始化 | Static verification via grep | `agent.py` line 86, 223-236 | ✅ |
| loop_engine.py 中每步结束时检查自动提取 | Static verification via grep | `loop_engine.py` line 422-425 | ✅ |
| PersistentMemoryConfig 可在 AgentConfig 中配置 | `test_manager.py` | `TestPersistentMemoryConfig::test_default_config`, `test_custom_config` | ✅ |

## Task 2.4: 更新上下文注入 + Agent 模板

| AC | Test File | Test Function | Status |
|----|-----------|---------------|--------|
| 系统提示词中注入的是 MEMORY.md 的完整文本 | `test_context.py` | `test_index_format_has_header_entries_and_warning` | ✅ |
| 无记忆文件时，不显示任何记忆块 | `test_context.py` | `test_empty_index_returns_empty_string` | ✅ |
| 记忆格式化输出包含三部分 | `test_context.py` | `test_index_format_has_header_entries_and_warning` | ✅ |
| {{memory_content}} 和 {{user_content}} 从模板中移除 | Static verification via grep | `Broca.md` uses `memory_index` only | ✅ |
| Broca.md 的 tools 列表仍包含 memory | Static verification via grep | `memory` tool still listed | ✅ |

## Task 2.5: 端到端测试

| AC | Test File | Test Function | Status |
|----|-----------|---------------|--------|
| 单元测试覆盖 types.py 全部核心函数 | `test_types.py` | All test functions | ✅ |
| 单元测试覆盖 store.py 全部 CRUD 操作 | `test_store.py` | All test functions | ✅ |
| 集成测试验证自动提取阈值逻辑 | `test_manager_extraction.py` ✨ (new) | Threshold logic tests | 🆕 |
| 集成测试验证 memory 工具触发提取 | `test_tool_execution.py` ✨ (new) | Tool trigger tests | 🆕 |
| 所有测试通过 | All test files | All tests pass | ✅ |

## Phase Integration Tests

| Test File | What It Verifies |
|-----------|------------------|
| `test_context.py` | 上下文注入格式验证 |
| ✨ New tests | Manager threshold + tool trigger logic |
