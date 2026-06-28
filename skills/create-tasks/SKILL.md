---
name: create-tasks
version: "2.1.0"
description: "Parses a plan document and creates the task hierarchy **one phase at a time** in the Task Management Tool. Use AFTER `create-plan`, in a loop with `execute-tasks`."
---

# Create Tasks from Plan Document

This skill reads the plan document and creates tasks in the Task Management Tool **one phase at a time** — not all at once. Each phase's tasks are created, executed, and reviewed before moving to the next.

## The Complete Workflow

```
create-plan (skill)          → plans/*.md              (plan document)
                               │
create-tasks (skill)         → create Master Task      (once)
                               │
             ┌──────────────────┴──────────────────┐
             ▼  per phase, in a loop              │
create-tasks │  → create Phase N tasks             │
execute-tasks│  → implement Phase N (impl. only)   │
             │    wait for user approval                    │
             └──────────────────┬──────────────────┘
                                │
                                ▼  next phase (after approval)...
```

## ⚠️ Core Rule: One Phase at a Time

**Never create tasks for all phases at once.** The workflow is incremental per phase:

```
Phase 1:  create-tasks → execute-tasks → ⏸️ review → (user approves) → 
Phase 2:  create-tasks → execute-tasks → ⏸️ review → (user approves) → 
Phase 3:  ...
```

Each phase ends with a **review pause** — after the review report is presented, you must wait for the user to review and approve before proceeding. Unless the user explicitly says "continue without pausing" or "complete all phases."

Each invocation of `create-tasks` only handles **one phase**. After creating that phase's tasks, hand off to `execute-tasks`. When that phase is complete and approved, come back to `create-tasks` for the next phase.

## Quick Start

1. **Read + evaluate the plan** (global, once)
2. **Create Master Task** (global, once)
3. **Loop over phases**, for each phase:
   - Create the Phase parent task
   - Create each Task under this Phase
   - Verify this phase's task completeness
   - → Hand off to `execute-tasks` for this phase
   - → Return for the next phase

## Core Principles

### 1. Plan ⇔ Task Bijection

**Every Task in the plan document must have exactly one corresponding task in the Task Management Tool.** No more, no less.

| Plan Document | Task Management |
|---------------|-----------------|
| Entire Plan | Master Task |
| Phase N | Parent Task (under Master) |
| Task N.M | Child Task (under Phase parent) |

### 2. Acceptance Criteria Must be Preserved

The plan document defines acceptance criteria (AC) for each task. These must be copied verbatim into the task's `acceptance_criteria` field. They are the contract for `execute-tasks` to verify against.

### 3. Context Must be Preserved

The plan document defines context for each task (steps, expected output, related materials). These must be recorded in the task's `details`, `files`, `links`, and `notes` fields.

## Task Naming Convention

Tasks must be named so it's clear which plan and which phase/task they correspond to:

```
{PlanName} / Phase {N}: {Phase Name}          (for Phase parent tasks)
{PlanName} / Task {N.M}: {Task Name}          (for individual task items)
```

**Examples:**
- `blog-platform / Phase 1: Requirements & Design`
- `blog-platform / Task 1.1: Database Schema Design`

This makes it trivial to search and filter tasks by plan name.

## Workflow

### Phase 0: Read and Critically Evaluate the Plan (Once)

This step happens only once, at the very beginning, before any phase tasks are created.

Locate and read the plan document. The plan is always at `plans/{plan-name}.md` unless the user specifies otherwise.

```json
{
    "action": "read_file",
    "path": "plans/{plan-name}.md"
}
```

Extract the following from the plan:
- **Plan title and goal** (for master task)
- **All phases** (name, goal, phase acceptance criteria for each)
- **All tasks** (name, target, steps, expected output, acceptance criteria for each)
- **Related materials** (files, links, references)
- **Dependencies** between tasks and phases

#### Critical Evaluation

Before creating any tasks, assess the plan's quality and flag issues:

- **Feasibility**: Is the plan technically feasible? If not, stop and explain why.
- **Completeness**: Are any important phases or tasks missing? If so, report to the user.
- **Clarity**: Are there ambiguities or unclear decisions that need user confirmation? **Must use `ask_user` to clarify before proceeding.**

> ⚠️ If any issue is found that could lead to incorrect task creation, resolve it with the user first. Do not create tasks from a flawed plan.

### Step 1: Create Master Task (Once)

Create a master task representing the entire plan. This is done once and holds all phases as children.

```json
{
    "action": "create",
    "name": "{PlanName}: {Plan Goal}",
    "description": "Master task for plan: plans/{plan-name}.md",
    "priority": "high",
    "details": "Full plan context: {brief summary of the plan}",
    "files": ["plans/{plan-name}.md"],
    "acceptance_criteria": [
        "All phases completed and verified",
        "All Phase acceptance criteria satisfied",
        "All Task acceptance criteria satisfied"
    ]
}
```

> **Save the returned `task_id`** — you'll need it as `parent_id` for all Phase tasks.

### Step 2: Determine Current Phase

Identify which phase to work on next. The user may tell you directly, or you can infer from existing tasks:

```json
// Check what phases already exist under the master task
{ "action": "get_children", "task_id": "MASTER_TASK_ID" }
```

- If no phases exist yet → start with **Phase 1**
- If Phase N exists and its status is `completed` → proceed to **Phase N+1**
- If the user specifies a phase → use that one

### Step 3: Create This Phase's Parent Task

Create **one** parent task for the current phase only. Do not create other phases' tasks.

```json
{
    "action": "create",
    "name": "{PlanName} / Phase {N}: {Phase Name}",
    "description": "Phase {N} of plan: plans/{plan-name}.md",
    "priority": "high",
    "parent_id": "MASTER_TASK_ID",
    "dependencies": ["PREVIOUS_PHASE_TASK_ID"],
    "details": "{Phase goal and any additional context from the plan}",
    "files": ["plans/{plan-name}.md"],
    "acceptance_criteria": [
        "{Phase AC #1 from plan}",
        "{Phase AC #2 from plan}",
        "..."
    ]
}
```

> **Dependencies**: Phase N depends on Phase N-1 being completed. Set this explicitly.
> **Save the returned `task_id`** — you'll use it as `parent_id` for this phase's child tasks.

### Step 4: Create This Phase's Individual Tasks

For each Task item inside the **current phase only**, create a child task:

```json
{
    "action": "create",
    "name": "{PlanName} / Task {N.M}: {Task Name}",
    "description": "Task {N.M} in Phase {N} of plan: plans/{plan-name}.md",
    "priority": "high",
    "parent_id": "PHASE_TASK_ID",
    "dependencies": ["TASK_DEPENDENCY_IDS"],
    "details": "## Steps\n{steps from plan}\n\n## Expected Output\n{expected output from plan}\n\n## Plan Reference\n- Plan: plans/{plan-name}.md\n- Phase: {Phase Name}\n- Related Materials: {related materials from plan}",
    "acceptance_criteria": [
        "{Task AC #1 from plan}",
        "{Task AC #2 from plan}",
        "..."
    ]
}
```

### Step 5: Verify This Phase's Completeness

Run a completeness check for the **current phase only**:

```json
{ "action": "get_children", "task_id": "PHASE_TASK_ID" }
```

Cross-reference the returned children against this phase's task list in the plan:
- Every Task for this phase → has a child task? ✅
- Acceptance criteria for each task → preserved? ✅
- Dependencies within this phase → set correctly? ✅

**Do not proceed to create the next phase's tasks.** The user (or `execute-plan` orchestration) will call this skill again when the current phase is finished.


## Handle Special Cases

### Case: No plan document exists yet

If there is no plan document, you cannot create tasks from it. Ask the user to run `create-plan` first:

> "No plan document found at `plans/`. Please use `create-plan` skill first to generate a plan, then I can create tasks from it."

### Case: Single-phase plan

If the plan has only one phase, Step 2 → 6 runs once and the plan is fully set up.

### Case: Parallel tasks within a phase (no dependency between them)

Set `"dependencies": []` for tasks that can run in parallel. This tells `execute-tasks` they can be worked on concurrently.

### Case: Re-creating tasks for a phase from an updated plan

If tasks already exist for this phase from a previous plan version:
1. Get existing tasks under this phase
2. Compare with the updated plan
3. Ask user how to handle: overwrite, merge, or skip?

## Anti-Patterns

| Don't                                       | Do Instead                                                               |
| ---------------------------------------------| --------------------------------------------------------------------------|
| Create all phases' tasks at once            | Create **one phase at a time** — let execution complete before next      |
| Skip reading the plan document              | Always read the plan first before creating tasks                         |
| Lose acceptance criteria in translation     | Copy ACs verbatim into the task's `acceptance_criteria` field            |
| Set vague descriptions                      | Use `details` to record the full task context (steps, output, materials) |
| Forget dependencies                         | Set explicit dependencies based on plan's dependency relationships       |
| Create orphaned tasks                       | Always set `parent_id` to maintain the hierarchy                         |
| Skip the verification step                  | Always get_children to double-check completeness for the current phase   |
