---
name: execute-plan
description: 按阶段循环执行计划——使用create-tasks和execute-tasks，阶段间暂停等待评审
short_description: 执行计划文档
type: prompt
use_sub_agent: false
argument_hint: "<计划文件路径>"
---
# 执行计划

按阶段循环执行计划，每个阶段使用两个skill依次完成。**每个阶段结束后暂停等待评审，除非用户说明一次完成所有阶段。**

用户输入：`{{ args }}`

## 完整工作流

```
create-plan (skill)          → plans/*.md              (计划文档)
                               │
create-tasks (skill)         → 创建 Master Task        (仅一次)
                               │
             ┌─────────────────┴──────────────────┐
             ▼  (per phase, in a loop             │
create-tasks │  → 创建 Phase N 任务                │
execute-tasks│  → 实现 Phase N (只做实现)           │
             │    等待用户评审和审批                 │
             └─────────────────┬──────────────────┘
                               │
                               ▼ 下一阶段（用户批准后）...
```

## 使用方式

1. 先使用 `create-plan` skill 生成计划文档（如尚未生成）
2. 然后按阶段循环，每个阶段依次调用三个 skill：
   - **create-tasks** — 读取计划文档，创建 Master Task（仅第一次），然后创建当前 Phase 的任务体系
   - **execute-tasks** — **只做实现**：阶段锚定 → 逐任务执行（手动验证 AC）→ 自查 → 集成检查 → 阶段报告
3. **提交阶段报告后，必须等待用户审批**，不能自动进入下一阶段
4. 用户批准后，回到步骤 2 进入下一 Phase
5. 如果用户说明"一次完成所有阶段"，则跳过评审暂停，连续执行

> ⚠️ 每次只处理一个 Phase。不要跨 Phase 创建任务或测试。
> 详细的操作步骤和规范见对应 skill 文档。
