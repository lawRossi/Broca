---
name: review-plan
description: Review a plan document for completeness, clarity, feasibility, AC quality, and overall soundness before execution. Use after create-plan and before executing tasks.
type: prompt
use_sub_agent: true
sub_agent_name: assistant
argument_hint: "<计划文件路径> [--phases=1,2]"
---
# 评审计划质量

使用 **review-plan** skill 来评审计划文档。用户输入：`{{ args }}`。

## 任务

你的任务是对一份计划文档进行全面的**预执行质量评审**。用户输入指定了要评审的计划文件路径（和可选的阶段范围）。

## 执行方法

直接使用 **`review-plan` skill** 来完成评审工作：

1. **加载 skill**: `load_skill("review-plan")`
2. **读取计划文件**: 全面解析计划文档的结构和内容
3. **按照 skill 中的 8 维度评估框架执行评审**:
   - 📋 完整性（Completeness）
   - 🔍 清晰度（Clarity）
   - 🎯 AC质量（AC Quality）
   - 🏗️ 可行性（Feasibility）
   - 🔗 结构与依赖（Structure & Dependencies）
   - ⚠️ 风险识别（Risk Identification）
   - ⚖️ 比例适当性（Proportionality）
   - ✅ 内部一致性（Internal Consistency）
4. **生成评审报告**到 `reports/review/{plan-name}-review.md`
5. **向用户报告评审结果**

> ⚠️ 如果用户没有指定计划文件路径，需要先搜索 `plans/` 目录找到可用的计划文件，并询问用户要评审哪一个。
> 如果用户指定了 `--phases=1,2` 只评审特定阶段，则在报告中注明 "部分评审"。
> 详细的操作步骤和规范见 `review-plan` skill 文档。
