---
name: execute-tasks
version: "1.0.0"
description: Executes planned tasks using the Task Management Tool. Implements systematic task execution with error handling, progress tracking, and completion reporting. Use after planning phase to carry out tasks in an organized manner.
---

# Execute Tasks

Use the Task Management Tool to execute planned tasks systematically.

## Quick Start

1. **Get pending tasks**: Query tasks with task ids or status "pending"
2. **Pick next task**: Work on the highest priority pending task first
3. **Undertand the task**: Read task description, details, related context and check acceptance criteria
4. **Track progress**: Update task status during execution
5. **Refine task context**: Add files, links, and notes as needed
6. **Write completion report**: Record work done, results achieved, and acceptance criteria met

## Execution Workflow

### 1. Initialize Execution

Find the tasks to execute:

If task ids are provided: query tasks with given ids.
Else: get all tasks to understand task hierarchy or get all pending tasks:


### 2. Select Next Task

Choose the next task to execute based on:
- **Priority**: High priority tasks first
- **Dependencies**: All dependencies must be completed
- **Status**: Only "pending" tasks


### 3. Understand the Task

For the selected task:
1. Read task description and details carefully
2. Check acceptance criteria
3. Understand task context: related files, links, and notes

### 4. Make a plan

Write a plan for the task and add it to the task notes.
Break it down into steps and using `todo_management` to track progress if it involves multiple steps.

### 5. Execute the Task

1. Update task status to "in_progress"
2. Execute the work and refine task context as needed
3. Verify acceptance criteria are met
4. Update task status to "completed"
5. Add completion summary report

## The 3-Strike Error Protocol

When encountering errors or blockers:

### ATTEMPT 1: Diagnose & Fix

```
→ Read task details carefully
→ Identify what's blocking progress
→ Apply targeted fix
→ Update task with resolution notes
```

### ATTEMPT 2: Alternative Approach

```
→ Same error? Try different method
→ NEVER repeat exact same failing action
```

### ATTEMPT 3: Broader Rethink

```
→ Review the solution plan
→ May need further investigation
```

### AFTER 3 FAILURES: Escalate to User
```
→ Explain what you tried
→ Share the specific error
→ Add comment to task with attempts made
→ Mark the task as "blocked"
→ Ask for guidance
```


## Task Status Lifecycle

| Status | Meaning | When to Set |
|--------|---------|-------------|
| pending | Not started | Task created but not begun |
| in_progress | Currently working | Actively working on task |
| blocked | Cannot proceed | Waiting on dependencies or issues |
| completed | Finished | All acceptance criteria met |

## Query Patterns

### Get All Tasks
```json
{
    "action": "get_all"
}
```

### Get Tasks by Status
```json
{
    "action": "get_by_status",
    "status": "pending"
}
```

### Get Subtasks
```json
{
    "action": "get_children",
    "task_id": "PARENT_TASK_ID"
}
```

### Search Tasks
```json
{
    "action": "search",
    "query": "authentication"
}
```

## Task Report Pattern

When writing a completion report for a task, include:
- What was done
- Results achieved
- Acceptance criteria met
- Notes (optional)

```json
{
    "action": "update",
    "task_id": "TASK_ID",
    "report": "## Completion Report\n\n### What was done\n- [List of actions]\n\n### Results achieved\n- [Outcomes]\n\n### Acceptance criteria met\n- [x] Criteria 1\n- [x] Criteria 2\n\n### Notes\n- [Any additional information]"
}
```

## Anti-Patterns

| Don't | Do Instead |
|-------|------------|
| Repeat failed approaches | Record failures to notes, try different method |
| Skip acceptance criteria | Verify acceptance criteria before marking complete |
| Ignore dependencies | Check and wait for dependencies before starting |
| Work on tasks out of order | Follow priority and dependency order |
| Lose track of completed work | Mark tasks complete and write a detailed report |
