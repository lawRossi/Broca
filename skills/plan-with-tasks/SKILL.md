---
name: plan-with-tasks
version: "1.0.0"
description: Implements task-based planning for complex tasks using the Task Management Tool. Creates hierarchical task structures with dependencies, priorities, and progress tracking. Use when starting complex multi-step tasks, research projects, or any task requiring organized task management.
---

# Planning with Tasks

Use the Task Management Tool as your persistent task memory system.

## Quick Start

Before ANY complex task:
1. **Create a master task** for the overall goal using the Task Management Tool
2. **Break down into subtasks** using parent_id to create hierarchical structure
3. **Set dependencies** between tasks that have ordering requirements
4. **Track progress** by updating task status as you complete each phase

## The Core Pattern

```
Context Window = RAM (volatile, limited)
Task Management Tool = Persistent Task Memory (structured, queryable)

→ All planning goes into the task system
→ Tasks can be queried, filtered, and organized
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

### 4. Track Progress

Update task status as you work:

| Status | Meaning | When to Set |
|--------|---------|-------------|
| pending | Not started | Task created but not begun |
| in_progress | Currently working | Actively working on task |
| blocked | Cannot proceed | Waiting on dependencies or issues |
| completed | Finished | All acceptance criteria met |

## Task Query Patterns

### Get Current Phase
```json
{
    "action": "get_by_status",
    "status": "in_progress"
}
```

### Get Remaining Tasks
```json
{
    "action": "get_by_status",
    "status": "pending"
}
```

### Get Completed Work
```json
{
    "action": "get_by_status",
    "status": "completed"
}
```

### Get Subtasks of Master
```json
{
    "action": "get_children",
    "task_id": "MASTER_TASK_ID"
}
```

### Search for Specific Tasks
```json
{
    "action": "search",
    "query": "authentication"
}
```

## The 3-Strike Error Protocol

```
ATTEMPT 1: Diagnose & Fix
  → Read task details carefully
  → Identify what's blocking progress
  → Apply targeted fix
  → Update task with resolution notes

ATTEMPT 2: Alternative Approach
  → Same error? Try different method
  → Update task acceptance criteria if needed
  → NEVER repeat exact same failing action

ATTEMPT 3: Broader Rethink
  → Question task assumptions
  → Consider breaking into smaller subtasks
  → May need to create new task for investigation

AFTER 3 FAILURES: Escalate to User
  → Explain what you tried
  → Share the specific error
  → Add comment to task with attempts made
  → Ask for guidance
```

## Task Naming Convention

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

## Progress Tracking Pattern

After completing each task:
1. Update task status to "completed"
2. Add completion comment with summary
3. Move to next pending task
4. Re-read next task details before starting

## When to Use This Pattern

**Use for:**
- Multi-step tasks (3+ steps)
- Projects with clear phases
- Tasks requiring dependency management
- Work that spans multiple sessions
- Anything requiring organized progress tracking

**Skip for:**
- Simple questions
- Single action tasks
- Quick lookups

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

### Update Task
```json
{
    "action": "update",
    "task_id": "task ID",
    "status": "pending|in_progress|blocked|completed",
    "name": "new name (optional)",
    "description": "new description (optional)",
    "priority": "new priority (optional)",
    "dependencies": ["new dependencies (optional)"]
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
| Forget to update task status | Update status after every significant action |
| Create monolithic tasks | Break into smaller, manageable subtasks |
| Ignore task dependencies | Set dependencies explicitly |
| Lose track of completed work | Mark tasks complete and add comments |
| Repeat failed approaches | Record failures to notes, try different method |
| Skip acceptance criteria | Define and verify acceptance criteria |