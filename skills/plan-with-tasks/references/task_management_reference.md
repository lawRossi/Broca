# Task Management Tool Reference

## Overview

The Task Management Tool provides a comprehensive interface for managing tasks with full CRUD (Create, Read, Update, Delete) operations.

## Features

- **Create Tasks**: Create new tasks with various attributes like priority, assignee, dependencies, etc.
- **Retrieve Tasks**: Get individual tasks, all tasks, or filter by status/assignee
- **Update Tasks**: Modify existing task attributes
- **Delete Tasks**: Remove tasks from the system
- **Task Comments**: Add comments to tasks for collaboration
- **Task Hierarchy**: Support for parent-child task relationships
- **Search**: Search tasks by name or description

## Actions

### 1. Create Task

Creates a new task with the specified attributes.

**Required Parameters:**
- `action`: "create"
- `name`: Task name (string)
- `description`: Task description (string)

**Optional Parameters:**
- `priority`: Task priority ("low", "medium", "high") - defaults to "medium"
- `assignee`: Task assignee (string)
- `parent_id`: Parent task ID (string) - for creating subtasks
- `dependencies`: List of dependency task IDs (array of strings)
- `details`: Detailed task description (string)
- `files`: Related files of the task (array of strings)
- `links`: Related urls of the task (array of strings)
- `notes`: Concise notes that is useful for task execution (string)
- `acceptance_criteria`: List of acceptance criteria (array of strings)

**Example:**
```json
{
    "action": "create",
    "name": "Implement User Authentication",
    "description": "Add login and registration functionality",
    "priority": "high",
    "assignee": "dev_team",
    "acceptance_criteria": [
        "Users can register with email and password",
        "Users can login with existing credentials",
        "Password validation is implemented"
    ]
}
```

### 2. Get Task

Retrieves a specific task by ID.

**Required Parameters:**
- `action`: "get"
- `task_id`: Task ID (string)

**Example:**
```json
{
    "action": "get",
    "task_id": "123e4567-e89b-12d3-a456-426614174000"
}
```

### 3. Get All Tasks

Retrieves all tasks in the system.

**Required Parameters:**
- `action`: "get_all"

**Example:**
```json
{
    "action": "get_all"
}
```

### 4. Get Tasks by Status

Retrieves tasks filtered by their status.

**Required Parameters:**
- `action`: "get_by_status"
- `status`: Task status ("pending", "in_progress", "blocked", "completed")

**Example:**
```json
{
    "action": "get_by_status",
    "status": "in_progress"
}
```

### 5. Get Tasks by Assignee

Retrieves tasks assigned to a specific person.

**Required Parameters:**
- `action`: "get_by_assignee"
- `assignee`: Assignee name (string)

**Example:**
```json
{
    "action": "get_by_assignee",
    "assignee": "john_doe"
}
```

### 6. Update Task

Updates an existing task with new values.

**Required Parameters:**
- `action`: "update"
- `task_id`: Task ID (string)

**Optional Parameters:**
- `name`: New task name (string)
- `description`: New task description (string)
- `status`: New task status ("pending", "in_progress", "blocked", "completed")
- `priority`: New task priority ("low", "medium", "high")
- `assignee`: New task assignee (string)
- `dependencies`: New dependency task IDs (array of strings)
- `details`: New detailed description (string)
- `files`: New related files of the task (array of strings)
- `links`: New related urls of the task (array of strings)
- `notes`: New concise notes that is useful for task execution (string)
- `acceptance_criteria`: New acceptance criteria (array of strings)
- `report`: New report (string)

**Example:**
```json
{
    "action": "update",
    "task_id": "123e4567-e89b-12d3-a456-426614174000",
    "status": "completed",
    "priority": "low"
}
```

### 7. Delete Task

Removes a task from the system.

**Required Parameters:**
- `action`: "delete"
- `task_id`: Task ID (string)

**Example:**
```json
{
    "action": "delete",
    "task_id": "123e4567-e89b-12d3-a456-426614174000"
}
```

### 8. Add Comment

Adds a comment to a task for collaboration.

**Required Parameters:**
- `action`: "add_comment"
- `task_id`: Task ID (string)
- `content`: Comment content (string)

**Example:**
```json
{
    "action": "add_comment",
    "task_id": "123e4567-e89b-12d3-a456-426614174000",
    "content": "This task is almost complete, just need to add tests."
}
```

### 9. Get Child Tasks

Retrieves all child tasks of a parent task.

**Required Parameters:**
- `action`: "get_children"
- `task_id`: Parent task ID (string)

**Example:**
```json
{
    "action": "get_children",
    "task_id": "123e4567-e89b-12d3-a456-426614174000"
}
```

### 10. Search Tasks

Searches for tasks by name or description.

**Required Parameters:**
- `action`: "search"
- `query`: Search query string

**Example:**
```json
{
    "action": "search",
    "query": "authentication"
}
```