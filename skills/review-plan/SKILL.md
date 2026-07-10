---
name: review-plan
version: "1.0.0"
description: "Reviews a plan document for completeness, clarity, feasibility, AC quality, risk identification, and overall soundness before execution. Use this skill after create-plan and before executing tasks."
---

# Review Plan

This skill reviews a plan document (created by `create-plan`) **before execution begins** — ensuring the plan is complete, clear, feasible, and well-structured before any implementation work starts.

## ⚠️ Core Constraint

**You only review the plan. You must NOT execute any plan steps or modify any implementation files.**
- Do not create tests, run code, or edit project files
- Do not make any changes to the system state
- Your sole output is a review report

## Core Principles

### 1. Pre-Execution Review

This review happens **after `create-plan` generates the plan** and **before `create-tasks` / `execute-tasks` runs**. Catching issues at this stage saves significant rework later.

```
User Input → create-plan → plans/*.md → review-plan (you are here) → create-tasks → execute-tasks
```

### 2. 8-Dimension Evaluation Framework

Each plan is evaluated across 8 quality dimensions:

| # | Dimension | Core Question |
|:-:|-----------|---------------|
| 1 | 📋 **Completeness** | Does the plan cover all required sections? Any missing tasks, phases, or materials? |
| 2 | 🔍 **Clarity** | Are tasks, steps, and expectations unambiguous? Could an executor correctly interpret everything? |
| 3 | 🎯 **AC Quality** | Are acceptance criteria specific, measurable, verifiable, and complete? |
| 4 | 🏗️ **Feasibility** | Is the plan technically feasible given the constraints, timeline, and environment? |
| 5 | 🔗 **Structure & Dependencies** | Are phases and tasks logically ordered? Are dependencies correctly identified? |
| 6 | ⚠️ **Risk Identification** | Are risks properly identified with mitigation strategies? |
| 7 | ⚖️ **Proportionality** | Is the level of detail appropriate for the complexity? (Not over-engineered for simple tasks, not too vague for complex ones) |
| 8 | ✅ **Internal Consistency** | Do task ACs align with phase ACs? Do phases build logically? Is the approach consistent throughout? |

### 3. Constructive, Actionable Feedback

Every issue found must include:
- **Location**: Which phase/task/section has the issue
- **Severity**: Critical / Major / Minor
- **Description**: What exactly is wrong
- **Suggestion**: How to fix it

## Input

The user provides the plan file path (e.g., `plans/my-plan.md`). If no path is given, you can search for plan files in `plans/`.

## Workflow

### Step 1: Read and Parse the Plan Document

Read the plan document at the given path. Extract all structural elements:

```markdown
# {Plan Title}
## 概述               → goal, context, constraints
## 相关材料           → referenced materials
## 总体方案           → overall approach
## 执行计划           → phases and tasks
  ### Phase N: {Name} → phase goal + phase acceptance criteria
    #### Task N.M: {Name} → task goal, steps, expected output, acceptance criteria
## 风险与应对         → risk table
## 未解决的问题       → open questions
```

### Step 2: Evaluate Each Dimension

#### Dimension 1: 📋 Completeness

Check that all required sections exist:

| Required Section | Check |
|------------------|-------|
| 概述 (Overview) | Contains goal, context, and constraints? |
| 相关材料 (Related Materials) | Lists relevant references? |
| 总体方案 (Overall Approach) | Describes the technical approach and key decisions? |
| 执行计划 (Execution Plan) | Has at least one phase with tasks? |
| Phase-level ACs | Each phase has explicit acceptance criteria? |
| Task-level ACs | Each task has 2~5 specific acceptance criteria? |
| Task Steps | Each task has concrete, executable steps? |
| Task Expected Output | Each task describes what artifacts result? |
| 风险与应对 (Risk & Mitigation) | Risk table present? |
| 未解决的问题 (Open Questions) | Section present (ideally empty)? |

**Issues to flag:**
- Missing sections
- Phases without ACs
- Tasks without ACs or steps
- ACs that are too vague (e.g., "Works correctly")
- Missing referenced materials for complex tasks

#### Dimension 2: 🔍 Clarity

Evaluate whether each element is unambiguous:

**Phase-level:**
- Is the phase goal clear and well-scoped?
- Is it clear what "done" means for this phase?

**Task-level (check every task):**
- Are the steps actionable? Could someone follow them without guessing?
- Are technical terms explained or commonly understood?
- Are there any ambiguous phrases like "appropriate," "properly," "as needed" without definition?
- Are file paths, function names, and API endpoints specific rather than generic?

**Overall:**
- Would two different executors produce the same result from this plan?
- Are there any contradictions between sections?

#### Dimension 3: 🎯 AC Quality

Each acceptance criterion should be **SMART**:

| Criterion | Explanation | Bad Example | Good Example |
|-----------|-------------|-------------|--------------|
| **S**pecific | Clearly defines what to verify | "User registration works" | "User can register with email and password; on success, user record is created in DB with status 'pending'" |
| **M**easurable | Can be objectively checked | "Good performance" | "API responds within 200ms under 100 concurrent users" |
| **A**chievable | Can be implemented with available resources | "Supports 1B users" (for a 2-week project) | "Supports up to 10,000 concurrent users" |
| **R**elevant | Directly relates to the task goal | "All code is in TypeScript" (in a Python backend task) | "Login endpoint returns JWT token" |
| **T**estable | Can be verified through code, inspection, or demonstration | "User experience is smooth" | "Registration form shows validation error within 1s of submitting empty email field" |

**Check each AC:**
- Does it describe an observable outcome?
- Can it be verified programmatically or through clear inspection?
- Is it free of subjective language?

**Common AC quality issues:**
- ❌ "Works correctly" → ✅ "Returns HTTP 201 with user object containing id, email, and created_at"
- ❌ "Is secure" → ✅ "Password is stored as bcrypt hash; unauthenticated requests return 401"
- ❌ "Good error handling" → ✅ "Invalid input returns 400 with field-level error messages in format {field: message}"
- ❌ "Properly tested" → ✅ "All public functions have unit tests with >80% line coverage"
- ❌ "Clean code" → ✅ "Code passes flake8 with 0 errors and follows project conventions"

#### Dimension 4: 🏗️ Feasibility

Assess whether the plan is realistic:

**Technical feasibility:**
- Are the proposed technologies/libraries available and compatible?
- Are the steps technically sound? (e.g., no circular dependencies, no missing prerequisites)
- Are the time estimates (if any) realistic?
- Does the plan account for environment setup, dependencies, and potential blockers?

**Scope feasibility:**
- Is the scope appropriate for the number of phases/tasks?
- Are there too many tasks for the implied timeline?
- Is there a reasonable stopping point at each phase boundary?

**Resource feasibility:**
- Does the plan assume access to tools/services that may not be available? (e.g., specific API keys, paid services)
- Are there external dependencies that need coordination?

#### Dimension 5: 🔗 Structure & Dependencies

Evaluate the plan's logical flow:

**Phase ordering:**
- Do phases build on each other logically? (e.g., "Setup" before "Implementation," "Backend" before "Frontend")
- Could any phase be started before the previous one is fully complete?

**Task ordering within phases:**
- Are dependencies between tasks correctly identified?
- Could any tasks run in parallel? If yes, is this noted?
- Are there any circular dependencies?

**Dependency correctness:**
- Does Task N.2 actually depend on Task N.1, or could they be parallel?
- Are cross-phase dependencies identified?

#### Dimension 6: ⚠️ Risk Identification

Review the risk section (if present) or note its absence:

**If risk table exists:**
- Are the risks specific and relevant to this plan?
- Are mitigation strategies concrete and actionable?
- Are high-impact risks addressed in the task breakdown?
- Are there obvious risks missing?

**If risk table is missing:**
- For complex projects, note this as a concern
- Identify at least 2-3 risks that should have been documented

#### Dimension 7: ⚖️ Proportionality

Assess whether the plan's detail matches the task's complexity:

**Simple tasks (e.g., fix a bug, add a small feature):**
- Single phase with 1-5 tasks is appropriate ✅
- Multiple phases with many tasks → over-engineered ❌
- ACs can be straightforward ✅

**Complex tasks (e.g., build a new system, major refactor):**
- Multiple phases expected ✅
- Detailed ACs needed for each task ✅
- Risk section should be thorough ✅
- Single phase with vague tasks → insufficient ❌

**Flag if:**
- A 5-minute fix has a 3-phase plan with 15 tasks (over-engineered)
- A 2-week project has a single phase with 2 vague tasks (under-developed)

#### Dimension 8: ✅ Internal Consistency

Check for alignment across the plan:

**Vertical consistency:**
- Do task ACs, when combined, satisfy the phase ACs?
- Do phase ACs, when combined, achieve the overall goal?
- Does each task's expected output contribute to the phase goal?

**Horizontal consistency:**
- Is the technical approach consistent across all phases? (e.g., not using different DB technologies in different phases without explanation)
- Are naming conventions consistent?
- Are there contradictions between tasks?

**Material consistency:**
- Do the referenced materials actually support the plan's approach?
- Are all referenced files/links accessible?

### Step 3: Calculate Dimension Scores

For each dimension, assign a score:

| Score | Meaning |
|:-----:|---------|
| ⭐⭐⭐⭐⭐ | Excellent — no issues found |
| ⭐⭐⭐⭐ | Good — minor issues found |
| ⭐⭐⭐ | Fair — moderate issues, should improve |
| ⭐⭐ | Poor — significant issues, needs revision |
| ⭐ | Critical — plan is not usable as-is |

**Scoring Guidelines:**
- Start at 5 stars, deduct for each issue found
- Critical issue → -2 stars
- Major issue → -1 star
- Minor issue → -0.5 stars
- Minimum score is 1 star

### Step 4: Generate the Review Report

Write the review report to `reports/review/{plan-name}-review.md`.

```markdown
# {Plan Title} — Plan Review Report

## Overview

| Item | Content |
|------|---------|
| Plan File | {plan file path} |
| Reviewed At | {timestamp} |
| Overall Score | ⭐/5 |
| Verdict | ✅ Pass / ⚠️ Conditional Pass / ❌ Needs Revision |

### Dimension Scores

| # | Dimension | Score | Key Finding |
|:-:|-----------|:-----:|-------------|
| 1 | 📋 Completeness | ⭐/5 | {summary} |
| 2 | 🔍 Clarity | ⭐/5 | {summary} |
| 3 | 🎯 AC Quality | ⭐/5 | {summary} |
| 4 | 🏗️ Feasibility | ⭐/5 | {summary} |
| 5 | 🔗 Structure & Dependencies | ⭐/5 | {summary} |
| 6 | ⚠️ Risk Identification | ⭐/5 | {summary} |
| 7 | ⚖️ Proportionality | ⭐/5 | {summary} |
| 8 | ✅ Internal Consistency | ⭐/5 | {summary} |
| | **Overall** | **⭐/5** | **{overall assessment}** |

## Detailed Findings

### 1. 📋 Completeness — {score}

**Summary**: {brief summary}

| # | Severity | Location | Issue | Suggestion |
|:-:|:--------:|----------|-------|------------|
| 1 | {Critical/Major/Minor} | {Phase/Task} | {issue} | {fix} |
| ... | | | | |

### 2. 🔍 Clarity — {score}

**Summary**: {brief summary}

| # | Severity | Location | Issue | Suggestion |
|:-:|:--------:|----------|-------|------------|
| 1 | {Critical/Major/Minor} | {Phase/Task} | {issue} | {fix} |
| ... | | | | |

### 3. 🎯 AC Quality — {score}

**Summary**: {brief summary}

| # | Severity | Location | AC | Issue | Suggestion |
|:-:|:--------:|:--------:|----|-------|------------|
| 1 | {Critical/Major/Minor} | Task {N.M} | "{AC text}" | {issue} | {fix} |

Good ACs identified:
- Task {N.M}: "{AC text}" — ✅ {why it's good}

### 4. 🏗️ Feasibility — {score}

**Summary**: {brief summary}

| # | Severity | Location | Issue | Suggestion |
|:-:|:--------:|----------|-------|------------|
| 1 | {Critical/Major/Minor} | {Phase/Task} | {issue} | {fix} |

### 5. 🔗 Structure & Dependencies — {score}

**Summary**: {brief summary}

| # | Severity | Location | Issue | Suggestion |
|:-:|:--------:|----------|-------|------------|
| 1 | {Critical/Major/Minor} | {Phase/Task} | {issue} | {fix} |

### 6. ⚠️ Risk Identification — {score}

**Summary**: {brief summary}

| # | Severity | Location | Issue | Suggestion |
|:-:|:--------:|----------|-------|------------|
| 1 | {Critical/Major/Minor} | Risk Table | {issue} | {fix} |

### 7. ⚖️ Proportionality — {score}

**Summary**: {brief summary}

| # | Severity | Location | Issue | Suggestion |
|:-:|:--------:|----------|-------|------------|
| 1 | {Critical/Major/Minor} | {Phase/Task} | {issue} | {fix} |

### 8. ✅ Internal Consistency — {score}

**Summary**: {brief summary}

| # | Severity | Location | Issue | Suggestion |
|:-:|:--------:|----------|-------|------------|
| 1 | {Critical/Major/Minor} | {Phase/Task} | {issue} | {fix} |

## Issue Summary

| Severity | Count | Description |
|:--------:|:-----:|-------------|
| 🔴 Critical | {N} | Must fix before execution |
| 🟡 Major | {N} | Should fix for quality |
| 🟢 Minor | {N} | Consider improving |

### 🔴 Critical Issues (Must Fix)

| # | Dimension | Location | Issue | Suggestion |
|:-:|:---------:|:--------:|-------|------------|
| 1 | {dim} | {loc} | {issue} | {fix} |

### 🟡 Major Issues (Should Fix)

| # | Dimension | Location | Issue | Suggestion |
|:-:|:---------:|:--------:|-------|------------|
| 1 | {dim} | {loc} | {issue} | {fix} |

### 🟢 Minor Issues (Consider)

| # | Dimension | Location | Issue | Suggestion |
|:-:|:---------:|:--------:|-------|------------|
| 1 | {dim} | {loc} | {issue} | {fix} |

## Verdict

**Overall Score**: {X}/5 ⭐

**Verdict**: ✅ Pass / ⚠️ Conditional Pass / ❌ Needs Revision

| Verdict | Condition |
|---------|-----------|
| ✅ **Pass** | No critical issues, all dimensions ≥ 3 stars. Plan is ready for execution. |
| ⚠️ **Conditional Pass** | Minor critical issues OR some dimensions < 3 stars. Fix recommended issues before execution. |
| ❌ **Needs Revision** | Critical issues exist OR overall < 3 stars. Plan must be revised before execution. |

**Recommendation**:
{Concrete next steps — what should be fixed, in what priority, and whether the plan needs re-review after fixes}

**Summary**:
{2-3 sentence overall assessment of the plan's quality and readiness for execution}
```

### Step 5: Report to User

Present the results clearly:

1. **Verdict**: State the overall verdict (Pass / Conditional Pass / Needs Revision)
2. **Key strengths**: What the plan does well
3. **Key issues**: Critical issues that must be addressed (if any)
4. **Recommendation**: Clear next steps
5. **Report location**: Point to the full report file

Example report:

> ## Plan Review Complete
>
> **Verdict**: ❌ Needs Revision (Overall: ⭐⭐)
>
> **Key Strengths**:
> - Good phase structure with logical progression
> - Risk section is well-thought-out
>
> **Key Issues** (3 critical):
> 1. Task 1.1 AC: "User registration works" — too vague, not testable
> 2. Task 1.3 references a deprecated API (`v1/users`) — should be `v2/users`
> 3. Missing phase-level AC for Phase 2
>
> **Recommendation**: Fix the 3 critical issues and run review-plan again before proceeding.
>
> Full report: `reports/review/{plan-name}-review.md`

## Handle Special Cases

### Case: Plan document doesn't exist

If the plan file doesn't exist at the specified path:

1. Search `plans/` directory for `.md` files
2. If found, list them and ask user which to review
3. If not found, report: "No plan document found. Please run `create-plan` skill first to generate a plan."

### Case: Plan has only one phase with a few tasks

This is expected for simple tasks. The review should be proportionate:
- Skip deep analysis of cross-phase dependencies (not applicable)
- Focus on AC quality, clarity, and completeness
- Score Proportionality highly if the simplicity is appropriate

### Case: Plan uses a different language (e.g., English instead of Chinese)

The review should still follow the same 8 dimensions regardless of language. Read and evaluate the content in whatever language it's written.

### Case: Plan is missing the risk section entirely

This is fine for simple plans. However, for complex plans with multiple phases, flag it as a minor issue in the Completeness dimension.

### Case: User asks to review only specific phases

If the user specifies a phase range (e.g., "review Phase 1 and 2 only"), limit the review to those phases. For dimension scores that require the full picture (e.g., Structure & Dependencies), note "Partial review — only Phase X evaluated."

## Anti-Patterns

| Don't | Do Instead |
|-------|------------|
| Review without reading the entire plan first | Read the full plan to understand context before evaluating |
| Give vague feedback like "AC could be better" | Be specific: "Task 1.1 AC #2 'Works correctly' should specify exact HTTP response codes and error formats" |
| Fix plan issues yourself | Only report issues; the plan author should make fixes |
| Skip dimensions because they require effort | Evaluate all 8 dimensions for every plan |
| Score based on gut feeling | Score based on specific, documented issues |
| Ignore good aspects of the plan | Highlight strengths too — balanced feedback is more actionable |
| Be overly verbose in the summary report | Keep the user-facing summary concise; details go in the report file |
