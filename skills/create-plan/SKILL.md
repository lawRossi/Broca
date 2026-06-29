---
name: create-plan
version: "1.0.0"
description: "Generate a detailed, verifiable plan document based on user input. Always use this skill when you're asked to perform complex task, such as developing a system from scratch, creating significant features, system refactoring, etc."
---

# Create Plan

Take the user's input, conduct deep analysis and reasoning, and produce a **complete, verifiable plan document**.

## ⚠️ Core Constraint

**You may ONLY create the plan document. You must NOT execute any concrete steps of the plan.**
- Do not run any build, modification, deployment, or similar operations
- Do not call any tool that changes system state or files (except writing the plan document itself)
- Your sole output is a plan document (Markdown by default)

## Core Principles

**The quality of the plan determines the quality of execution.**

- **AC-first**: Every task must have clear, specific, measurable **Acceptance Criteria**. Anyone executing the plan should be able to verify each criterion against the result.
- **Executable**: Tasks must be broken down to directly actionable granularity. Steps must be unambiguous — the executor should never have to guess "how".
- **Well-referenced**: The plan must cite relevant materials (requirements docs, API docs, reference code, design mockups, etc.) so the executor can quickly establish context.
- ** Thorough and Comprehensive **: All important aspects and details must be addressed.
- ** Communicative**: Unclear requirements, important details, key risks, and key decisions must all be clearly communicated with the user using 'ask_user'. Ask only one question at a time to avoid information overload.
- ** Proportionate to Complexity**: Simple tasks MUST NOT be over-engineered. If a task is straightforward, use a **single phase** with a few tasks. Multiple phases are only needed for complex, multi-step projects. Resist the urge to artificially inflate the plan.

## Steps

### 1. Deep Understanding & Research

- **Explore context**: Understand the problem background and current state. If workspace exploration is needed, assign explorer to provide an overview; if external information is needed, use `web_search` and `web_fetch`.
- **Gather materials**: Proactively search and list relevant reference materials:
  - Requirements docs, technical proposals, API definitions
  - Existing code references (use `glob` / `grep` to find key files)
  - External documentation links (official docs, technical blogs, etc.)
  - Design mockups or prototype links
- **Analyze goals & constraints**: Understand the user's objectives, requirements, and constraints
- **Evaluate trade-offs & confirm**: Consider possible approaches, evaluate trade-offs, give constructive recommendations at key decision points.
- **Identify risks**: Identify potential risks and challenges, propose mitigation strategies

### 2. Structure the Plan Hierarchically

Organize the plan into a clear hierarchy. **Every element must be verifiable.**

#### Phase
Each phase is a major milestone, ordered logically. Each phase must have explicit **phase-level acceptance criteria** — what counts as "done" for this phase.

**⚠️ Simplicity Rule**: For simple tasks, use **exactly one phase**. Do not split into multiple phases just to follow the template. A single-phase plan with 2-5 focused tasks is perfect for straightforward work. Multiple phases only when the work truly spans multiple distinct milestones (e.g., "Setup" → "Core Feature" → "Testing & Polish").

#### Task
Each phase contains concrete tasks. Every task must include:
- **Goal**: What the task aims to achieve
- **Steps**: Specific, executable step descriptions
- **Expected output**: What concrete artifacts result (files, APIs, passing tests, etc.)
- **Acceptance Criteria (AC)**: **Must** list 2~5 specific, measurable criteria. Good ACs answer "How do I know this task is done and done right?"
  - ✅ Good: "After successful registration, the user receives an email with a verification link. Clicking the link sets the account status to 'verified'."
  - ❌ Bad: "User registration works correctly."

#### Dependencies
Clearly specify task dependencies and execution order (which tasks can run in parallel, which must be sequential).

### 3. Write the Plan Document

Write the complete plan to a Markdown file under `plans/`.

**File naming**: Generate the filename from the core topic of the user's input, using lowercase English with hyphens. Examples:
- User wants "build a blog platform" → `plans/blog-platform-plan.md`
- User wants "refactor payment module" → `plans/payment-module-refactor-plan.md`

**Document template**:

```markdown
# {计划标题}

## 概述
- **目标**：{用户的核心目标}
- **背景**：{用户提供的背景信息}
- **约束条件**：{任何约束条件，如时间、预算、技术栈限制等}

## 相关材料
{为执行此计划需要参考的材料清单，帮助执行者快速建立上下文}
- {材料1: 需求文档 / 链接 / 文件路径}
- {材料2: 参考实现 / API 定义 / 设计稿}
- {材料3: 外部参考链接}

## 总体方案
{对整体方案的简要描述，包括技术选型、架构决策、关键设计思路等}

## 执行计划

### Phase 1: {阶段名称}
**目标**：{本阶段目标}

**阶段验收标准**：
- [ ] {标准1}
- [ ] {标准2}
- [ ] ...

#### Task 1.1: {任务名称}
- **目标**：{任务目标}
- **步骤**：
  1. {步骤1}
  2. {步骤2}
  3. ...
- **预期产出**：{产出描述}
- **验收标准**：
  - [ ] {具体可衡量的验收标准1}
  - [ ] {具体可衡量的验收标准2}
  - [ ] ...

#### Task 1.2: {任务名称}
- **目标**：{任务目标}
- **步骤**：
  1. {步骤1}
  2. {步骤2}
  3. ...
- **预期产出**：{产出描述}
- **验收标准**：
  - [ ] {具体可衡量的验收标准1}
  - [ ] {具体可衡量的验收标准2}
  - [ ] ...

### Phase 2: {阶段名称（简单任务不需要）}
...

## 风险与应对
| 风险 | 影响 | 应对策略 |
|------|------|----------|
| ... | ... | ... |

## 未解决的问题
- {需要在执行前澄清的问题}
- {需要在执行中确认的决策点}
（原则上该章节应为空，因为所有问题在写计划前要和用户确认，除非用户不能及时回应）
```

### 4. Report to the User

After generating the plan document, summarize for the user:
1. **Plan overview**: Briefly state how many phases and tasks the plan contains
2. **Key decisions**: List the key decisions made in the plan
3. **AC highlight**: Emphasize that every phase and task has explicit acceptance criteria
4. **Materials check**: Ask the user to verify the referenced materials are accurate and complete
5. **Next step**: Ask if they want to execute the plan or make adjustments. Inform the user that **execute-plan** command can be used for execution

**Never start executing any plan steps without explicit user confirmation.**
