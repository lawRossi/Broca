---
name: plan
description: 使用create-plan skill生成详细的实施计划文档
short_description: 生成计划文档
type: prompt
use_sub_agent: false
argument_hint: "<目标或想法描述>"
---
# 制定计划

使用 **create-plan** skill 完成计划制定。

用户输入：`{{ args }}`

> create-plan 会探索上下文、收集材料、分析权衡、将目标拆解为带验收标准的 Phase 和 Task，并生成计划文档到 `plans/` 目录。
> 详细步骤和规范见对应 skill 文档。
