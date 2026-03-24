from datetime import datetime
from enum import Enum
from typing import List, Optional

from pydantic import BaseModel


class TaskStatus(str, Enum):
    PENDING = "pending"
    IN_PROGRESS = "in_progress"
    BLOCKED = "blocked"
    COMPLETED = "completed"


class TaskPriority(str, Enum):
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"


class TaskMetadata(BaseModel):
    id: str
    parent_id: Optional[str] = None
    created: datetime
    updated: datetime
    status: TaskStatus
    priority: TaskPriority
    dependencies: Optional[List[str]] = None
    assignee: Optional[str] = None


class TaskComment(BaseModel):
    author: str
    content: str
    created: datetime


class TaskContext(BaseModel):
    files: Optional[List[str]] = None
    links: Optional[List[str]] = None
    notes: Optional[str] = None


class Task(BaseModel):
    metadata: TaskMetadata
    name: str
    description: str

    details: Optional[str] = None
    context: Optional[TaskContext] = None
    acceptance_criteria: Optional[List[str]] = None
    discussion: Optional[List[TaskComment]] = None
    report: Optional[str] = None
