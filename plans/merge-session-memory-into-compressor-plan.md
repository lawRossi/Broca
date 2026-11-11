# 将 session_memory 模块并入 context_compressor

## 概述
- **目标**：删除 `broca/session_memory/` 目录，将其仅有的有效内容（prompt 模板 + 构建函数）内联到 `broca/context_compressor.py`，使 session memory 逻辑完全归属于上下文压缩模块
- **背景**：`SessionMemoryManager` 的实际逻辑早已迁入 `SessionMemoryCompressor`，`broca/session_memory/` 仅剩一个 `memory_prompts.py`（一个模板常量 + 一个 prompt 构建函数）被 `context_compressor.py` 引用，以及一个已无人使用的 deprecated shim（`memory_manager.py`）
- **约束条件**：不改变任何运行时行为；`persistent_memory/` 模块保持独立不动

## 相关材料
- `broca/session_memory/memory_prompts.py` — 要迁移的唯一有效代码（`DEFAULT_MEMORY_TEMPLATE` 常量 + `build_extraction_user_prompt()` 函数）
- `broca/session_memory/memory_manager.py` — deprecated shim，可删除
- `broca/session_memory/__init__.py` — 导出 deprecated 类，可删除
- `broca/context_compressor.py:31-33` — 唯一引用 `broca.session_memory` 的位置
- `broca/components/context_compressor.py` — ABC 定义，无需改动
- `broca/persistent_memory/` — 不改动，保持独立

## 总体方案

`broca/session_memory/` 的有效内容仅两个符号：`DEFAULT_MEMORY_TEMPLATE`（模板字符串）和 `build_extraction_user_prompt()`（prompt 构建函数）。直接内联到 `context_compressor.py` 文件顶部，然后删除整个目录。

## 执行计划

### Phase 1: 内联 + 删除 + 验证

**目标**：将 `session_memory` 的有效代码迁入 `context_compressor.py`，删除 `broca/session_memory/` 目录，全量测试通过

**阶段验收标准**：
- [ ] `broca/session_memory/` 目录已删除
- [ ] `context_compressor.py` 不再有任何对 `broca.session_memory` 的 import
- [ ] `DEFAULT_MEMORY_TEMPLATE` 和 `build_extraction_user_prompt` 在 `context_compressor.py` 中可直接使用
- [ ] `pytest broca/tests/` 全量通过
- [ ] `persistent_memory/` 模块不受影响，其测试全部通过

#### Task 1.1: 内联 prompt 模板到 context_compressor.py
- **目标**：将 `DEFAULT_MEMORY_TEMPLATE` 常量和 `build_extraction_user_prompt()` 函数从 `memory_prompts.py` 复制到 `context_compressor.py` 顶部，删除旧的 import
- **步骤**：
  1. 在 `context_compressor.py` 中，找到 `from broca.session_memory.memory_prompts import (DEFAULT_MEMORY_TEMPLATE, build_extraction_user_prompt)` 这行 import（约第 31 行）
  2. 删除该 import 语句
  3. 在 `context_compressor.py` 的 import 块之后、`logger` 定义之前，插入 `DEFAULT_MEMORY_TEMPLATE` 常量（从 `memory_prompts.py` 第 7-47 行复制）
  4. 在 `DEFAULT_MEMORY_TEMPLATE` 之后插入 `build_extraction_user_prompt()` 函数（从 `memory_prompts.py` 第 50-63 行复制）
  5. 更新 `context_compressor.py` 顶部 docstring，移除对 `session_memory` 模块的引用（第 4 行 "合并了原 ContextCompressor 和 SessionMemoryManager 的职责" 可以保留作为历史说明，但 import 注释需清理）
- **预期产出**：`context_compressor.py` 自包含所有 session memory prompt 逻辑，不再依赖 `broca.session_memory`
- **验收标准**：
  - [ ] `context_compressor.py` 中无任何 `broca.session_memory` 或 `session_memory` 字样的 import
  - [ ] `grep -r "from broca.session_memory\|from .session_memory" broca/` 返回空
  - [ ] `DEFAULT_MEMORY_TEMPLATE` 和 `build_extraction_user_prompt` 在 `context_compressor.py` 中定义，且函数签名和行为与原 `memory_prompts.py` 完全一致

#### Task 1.2: 删除 broca/session_memory/ 目录
- **目标**：移除 `broca/session_memory/` 整个目录（`__init__.py`、`memory_manager.py`、`memory_prompts.py`）
- **步骤**：
  1. 确认 Task 1.1 已完成（`context_compressor.py` 不再 import `broca.session_memory`）
  2. `grep -rn "session_memory" broca/ --include="*.py"` 确认除注释/docstring 外无代码引用
  3. 删除 `broca/session_memory/` 目录
  4. 运行 `python -c "import broca.context_compressor"` 确认 import 链正常
- **预期产出**：`broca/session_memory/` 目录不存在，代码可正常导入
- **验收标准**：
  - [ ] `ls broca/session_memory/` 报 No such file
  - [ ] `python -c "from broca.context_compressor import SessionMemoryCompressor"` 成功
  - [ ] `grep -rn "from broca.session_memory\|import broca.session_memory" broca/ --include="*.py"` 返回空

#### Task 1.3: 全量测试验证
- **目标**：确认所有测试通过，无回归
- **步骤**：
  1. 运行 `poetry run pytest broca/tests/ -x -v` 全量测试
  2. 如有失败，分析是否由本次改动引起并修复
  3. 特别关注 `broca/tests/test_context_compressor.py`、`broca/tests/persistent_memory/` 下的测试
- **预期产出**：全量测试通过
- **验收标准**：
  - [ ] `pytest broca/tests/` 全部通过，0 个失败
  - [ ] `broca/tests/persistent_memory/` 下的 4 个测试文件全部通过（确认未影响 persistent_memory 模块）

## 风险与应对
| 风险 | 影响 | 应对策略 |
|------|------|----------|
| `memory_prompts.py` 中有未发现的隐式依赖 | import 失败 | Task 1.2 中先用 `grep` 全面搜索，再删除 |
| deprecated `SessionMemoryManager` 被外部插件引用 | 插件报错 | 已确认代码库内无引用；`SessionMemoryManager` 已标记 deprecated 且发 DeprecationWarning，外部插件应已迁移 |

## 未解决的问题
（无 — 方案明确，无歧义）
