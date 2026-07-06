---
name: review-execution
description: 对照计划文件评审执行质量——运行测试、七维评估、生成评审报告
short_description: 评审计划文档质量
type: prompt
use_sub_agent: true
sub_agent_name: assistant
argument_hint: "<计划文件路径> [阶段号]"
---
# 评审计划执行质量

使用 `create-and-run-tests` skill 来执行评审。用户输入：`{{ args }}`。

## 任务

你的任务是对一份计划的执行质量进行全面评审。用户输入中指定了要评审的计划文件（和可选的阶段号）。

## 执行方法

直接使用 **`create-and-run-tests` skill** 来完成评审工作：

1. **加载 skill**: `load_skill("create-and-run-tests")`
2. **读取计划文件**: 理解每个 Phase 的 AC 和 Task 的 AC
3. **按照 skill 步骤执行**:
   - 检查测试文件是否已存在；如果不存在，先从 AC 创建测试用例并运行
   - 运行测试，收集结果
   - 执行**七维质量评审**（计划锚定、AC达标率、完整性、正确性、测试质量、集成质量、报告真实性）
   - 生成评审报告到 `reports/review/{plan-name}-phase-{N}-review.md`
4. **向用户报告评审结果**

> ⚠️ 注意：如果用户没有指定阶段号，需要向用户确认评审范围。
> 详细的操作步骤和规范见 `create-and-run-tests` skill 文档。
