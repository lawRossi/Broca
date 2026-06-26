---
name: execute-plan
description: Orchestrate per-phase plan execution using create-tasks, execute-tasks, and create-tests in a loop, with review pauses between phases.
type: prompt
use_sub_agent: false
argument_hint: "<你的计划文件>"
---
# 执行计划

按阶段循环执行计划，每个阶段使用三个 skill 依次完成。**每个阶段结束后暂停等待评审，除非用户说明一次完成所有阶段。**

用户输入：`{{ args }}`

## 完整工作流

```
create-plan (skill)    → plans/*.md              (计划文档)
                          │
create-tasks (skill)   → 创建 Master Task        (仅一次)
                          │
             ┌────────────┴──────────────────┐
             ▼  (per phase, in a loop        │
create-tasks │  → 创建 Phase N 任务          │
execute-tasks│  → 实现 Phase N               │
create-tests │  → 创建+运行 Phase N 测试      │
             │  → ⏸️ 提交阶段报告，等待评审    │
             └────────────┬──────────────────┘
                          │
                          ▼ 下一阶段（用户批准后）...
```

## 使用方式

1. 先使用 `create-plan` skill 生成计划文档（如尚未生成）
2. 然后按阶段循环，每个阶段依次调用三个 skill：
   - **create-tasks** — 读取计划文档，创建 Master Task（仅第一次），然后创建当前 Phase 的任务体系
   - **execute-tasks** — 实现当前 Phase 的任务：阶段锚定 → 逐任务执行（手动验证 AC）→ 自查 → 集成检查
   - **create-tests** — 根据当前 Phase 每个 Task 的 AC 创建测试用例，运行测试，结果纳入阶段报告
3. **提交阶段报告后，必须等待用户评审**，不能自动进入下一阶段
4. 用户批准后，回到步骤 2 进入下一 Phase
5. 如果用户说明"一次完成所有阶段"，则跳过评审暂停，连续执行

> ⚠️ 每次只处理一个 Phase。不要跨 Phase 创建任务或测试。
> execute-tasks 只负责实现，不写测试；create-tests 负责创建和运行测试。
> 详细的操作步骤和规范见对应 skill 文档。
