---
name: plan-with-tasks
version: "1.0.0"
description: Implements task-based planning for complex tasks using the Task Management Tool. Creates hierarchical task structures with dependencies, priorities, and progress tracking. Use when starting complex multi-step tasks, research projects, or any task requiring organized task management.
---

# Planning with Tasks

Use the Task Management Tool as your persistent task memory system.

## Quick Start

For ANY complex task:
1. **Create a master task** for the overall goal using the Task Management Tool
2. **Break down into subtasks** using parent_id to create hierarchical structure
3. **Set dependencies** between tasks that have ordering requirements
4. **Define acceptance criteria** for each task
5. **Prioritize** tasks based on importance
6. **Set Context** for each task by recognizing relevant files, links, and writting notes
7. **Track progress** by updating task status as you complete each phase

## The Core Pattern

```
Context Window = RAM (volatile, limited)
Task Management Tool = Persistent Task Memory (structured, queryable)

→ All planning goes into the task system
→ Tasks can be queried, filtered, and organized
→ Task context is recorded as related files, links, and notes
→ Progress is tracked through status updates
```

## Task Structure

| Component | Purpose | When to Use |
|-----------|---------|-------------|
| Master Task | Overall goal and context | Start of any complex task |
| Subtasks | Logical breakdown of work | When master task has multiple phases |
| Dependencies | Task ordering | When tasks must happen in sequence |
| Priority | Work importance | When tasks have different urgency levels |
| Status | Progress tracking | Continuously update as work progresses |

## Critical Workflow

### 1. Initialize Planning Task

Create a master task that captures the entire project:

```json
{
    "action": "create",
    "name": "Project: [Project Name]",
    "description": "Overall project goal and scope",
    "priority": "high",
    "details": "Comprehensive project description including requirements and constraints",
    "acceptance_criteria": [
        "All requirements are met",
        "Tests are passing",
        "Documentation is complete"
    ]
}
```

### 2. Create Phase Tasks

Break the master task into logical phases:

```json
{
    "action": "create",
    "name": "Phase 1: Requirements & Discovery",
    "description": "Understand requirements and gather information",
    "priority": "high",
    "parent_id": "MASTER_TASK_ID",
    "dependencies": [],
    "acceptance_criteria": [
        "Requirements documented",
        "Constraints identified",
        "Findings recorded"
    ]
}
```

### 3. Set Dependencies

Link tasks that require completion before others can start:

```json
{
    "action": "update",
    "task_id": "PHASE_3_TASK_ID",
    "dependencies": ["PHASE_2_TASK_ID"]
}
```

### 4. Set Task Context

Record relevant files, links, and notes:

```json
{
    "action": "update",
    "task_id": "PHASE_3_TASK_ID",
    "context": {
        "files": [
            "requirements.txt",
            "constraints.txt"
        ],
        "links": [
            "https://example.com/requirements",
            "https://example.com/constraints"
        ],
        "notes": "Notes on requirements and constraints"
    }
}
```

### 5. Track Progress

Update task status as you work:

| Status | Meaning | When to Set |
|--------|---------|-------------|
| pending | Not started | Task created but not begun |
| in_progress | Currently working | Actively working on task |
| blocked | Cannot proceed | Waiting on dependencies or issues |
| completed | Finished | All acceptance criteria met |


## Task Management Actions Reference

You can refer to `references/task_reference.md` for more details.

### Create Task
```json
{
    "action": "create",
    "name": "Task name",
    "description": "Brief description",
    "priority": "low|medium|high",
    "assignee": "responsible party",
    "parent_id": "parent task ID",
    "dependencies": ["task IDs"],
    "details": "Detailed information",
    "acceptance_criteria": ["criteria list"]
}
```

#### Task Naming Convention

Use consistent naming for easy search and organization:

```
[PREFIX] [TYPE] [DESCRIPTION]

Examples:
- "Project: Blog Application"
- "Phase 1: Requirements Gathering"
- "Task: Implement User Authentication"
- "Bug: Fix Login Redirect Issue"
- "Research: Evaluate Database Options"
```

### Update Task
```json
{
    "action": "update",
    "task_id": "task ID",
    "status": "pending|in_progress|blocked|completed",
    "name": "new name (optional)",
    "description": "new description (optional)",
    "priority": "new priority (optional)",
    "dependencies": ["new dependencies (optional)"],
    "files": ["new related files (optional)"],
    "links": ["new related links (optional)"],
    "notes": "new notes (optional)"
}
```

### Add Comment
```json
{
    "action": "add_comment",
    "task_id": "task ID",
    "author": "your name",
    "content": "comment text"
}
```

## Anti-Patterns

| Don't | Do Instead |
|-------|------------|
| Skip task creation and start working | Create task structure first |
| Create monolithic tasks | Break into smaller, manageable subtasks |
| Skip acceptance criteria | Define and verify acceptance criteria |
| Skip task context | Record relevant files, links, and notes |
| Ignore task dependencies | Set dependencies explicitly |
| Forget to update task status | Update status after every significant action |
| Lose track of completed work | Mark tasks complete and add comments |
