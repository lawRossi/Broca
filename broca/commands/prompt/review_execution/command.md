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

用户输入：`{{ args }}`。

## 任务

Perform a thorough quality review against the plan. 

#### Evaluate 7 Quality Dimensions

Use workspace exploration (glob/grep/read_file) to gather evidence for each dimension, **not just what's in the report**:

| # | Dimension | Core Question |
|:-:|-----------|---------------|
| 1 | 📌 **Plan Anchoring** | Was execution always anchored to the plan? Any unapproved deviations? |
| 2 | 🎯 **AC Achievement Rate** | Are plan ACs met one by one? Any standard-lowering? |
| 3 | 📦 **Completeness** | All expected outputs produced? Any omissions or extras? |
| 4 | ✅ **Correctness** | Does implementation logic match the plan's technical approach? |
| 5 | 🧪 **Test Quality** | Test coverage, assertion quality, all passing? |
| 6 | 🔗 **Integration Quality** | Modules integrate correctly? Full regression passes? |
| 7 | 📋 **Report & Deviation Handling** | Phase report honest? Deviations properly recorded and approved? |

#### Generate the Review Report

Write a structured review report to `reports/review/{plan-name}-phase-{N}-review.md`:

```markdown
# {Plan Title} — Phase {N}: {Phase Name} — Review Report

## Overview

| Item | Content |
|------|---------|
| Plan File | {plan file path} |
| Phase | Phase {N}: {Phase Name} |
| Execution Report | {execution report path (if any)} |

### Dimension Scores

| # | Dimension | Score | Key Finding |
|:-:|-----------|:-----:|-------------|
| 1 | 📌 Plan Anchoring | ⭐/5 | {summary} |
| 2 | 🎯 AC Achievement Rate | ⭐/5 | {summary} |
| 3 | 📦 Completeness | ⭐/5 | {summary} |
| 4 | ✅ Correctness | ⭐/5 | {summary} |
| 5 | 🧪 Test Quality | ⭐/5 | {summary} |
| 6 | 🔗 Integration Quality | ⭐/5 | {summary} |
| 7 | 📋 Report & Deviation Handling | ⭐/5 | {summary} |
| | **Overall** | **⭐/5** | **{summary}** |

## AC Verification

### Phase {N}: {Phase Name}

**Phase-level ACs**:
| # | AC | Met? | Evidence |
|:-:|----|:----:|----------|
| 1 | {AC description} | ✅/⚠️/❌ | {evidence} |

#### Task {N.1}: {Task Name}

| # | AC | Met? | Evidence |
|:-:|----|:----:|----------|
| 1 | {AC description} | ✅/⚠️/❌ | {evidence} |
| — | **AC Rate**: {N}/{M} | | |

#### Task {N.2}: {Task Name}

## Issues Found

### 🔴 Critical (must fix)
| # | Task | Dimension | Issue | Suggestion |
|:-:|:----:|:---------:|-------|------------|
| 1 | {task} | {dim} | {issue} | {fix} |

### 🟡 Medium (should fix)
| # | Task | Dimension | Issue | Suggestion |
|:-:|:----:|:---------:|-------|------------|
| 1 | {task} | {dim} | {issue} | {fix} |

### 🟢 Minor (reference)
| # | Task | Dimension | Issue | Suggestion |
|:-:|:----:|:---------:|-------|------------|
| 1 | {task} | {dim} | {issue} | {fix} |

## Conclusion

**AC Achievement Rate**: {N}% ({passed}/{total})

**Overall**: ✅ Pass / ⚠️ Conditional Pass / ❌ Fail

**Next Step**: {recommendation}
```

### Report to User

Present the results to the user: Just provide the location of the review report.
Never be verbose. (Your report contains all details)

> ⚠️ 注意：如果用户没有指定阶段号，需要向用户确认评审范围。
