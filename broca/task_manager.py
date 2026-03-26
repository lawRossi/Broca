"""
任务管理器模块（数据库版本）

使用数据库进行任务持久化存储，提供完整的任务管理功能。
全部接口为异步。
"""

from typing import Any, Dict, List, Optional

from pydantic import BaseModel

from .session.models import Task, TaskComment, TaskPriority, TaskStatus
from .session.service import get_task_comment_service, get_task_service


class TaskContext(BaseModel):
    files: Optional[List[str]] = None
    links: Optional[List[str]] = None
    notes: Optional[str] = None


class TaskManager:
    """
    任务管理器

    使用数据库进行任务持久化存储，提供CRUD操作和高级查询功能。
    所有方法都是异步的。
    """

    def __init__(self, session_id: Optional[str] = None):
        """
        初始化任务管理器。

        Args:
            session_id: 可选的会话ID，用于关联任务与会话
        """
        self._task_service = get_task_service()
        self._comment_service = get_task_comment_service()

    async def create_task(
        self,
        name: str,
        description: str,
        priority: TaskPriority = TaskPriority.MEDIUM,
        parent_id: Optional[str] = None,
        assignee: Optional[str] = None,
        dependencies: Optional[List[str]] = None,
        details: Optional[str] = None,
        context: Optional[TaskContext] = None,
        acceptance_criteria: Optional[List[str]] = None,
        session_id: Optional[str] = None,
    ) -> Task:
        """
        创建新任务。

        Args:
            name: 任务名称
            description: 任务描述
            priority: 任务优先级
            parent_id: 可选的父任务ID
            assignee: 可选的分配对象
            dependencies: 可选的依赖任务ID列表
            details: 可选的详细描述
            context: 可选的上下文信息
            acceptance_criteria: 可选的验收标准列表
            session_id: 可选的会话ID（如果不提供则使用初始化时的session_id）

        Returns:
            创建的Task对象
        """
        # 提取上下文字段
        context_files = None
        context_links = None
        context_notes = None
        if context:
            context_files = context.files
            context_links = context.links
            context_notes = context.notes

        return await self._task_service.create_task(
            name=name,
            description=description,
            priority=priority,
            parent_id=parent_id,
            assignee=assignee,
            dependencies=dependencies,
            details=details,
            context_files=context_files,
            context_links=context_links,
            context_notes=context_notes,
            acceptance_criteria=acceptance_criteria,
            session_id=session_id,
        )

    async def get_task(self, task_id: str) -> Optional[Task]:
        """
        根据ID获取任务。

        Args:
            task_id: 任务ID

        Returns:
            Task对象如果存在，否则返回None
        """
        return await self._task_service.get(task_id)

    async def get_all_tasks(
        self,
        session_id: str,
        status: Optional[TaskStatus] = None,
        assignee: Optional[str] = None,
    ) -> List[Task]:
        """
        获取所有任务，支持过滤。

        Args:
            session_id: 可选的会话ID过滤
            status: 可选的状态过滤
            assignee: 可选的分配对象过滤

        Returns:
            Task对象列表
        """
        tasks = await self._task_service.get_tasks_by_session(session_id, status)

        if assignee:
            tasks = [task for task in tasks if task.assignee == assignee]

        return tasks

    async def get_tasks_by_status(
        self, session_id: str, status: TaskStatus
    ) -> List[Task]:
        """
        根据状态获取任务。

        Args:
            status: 任务状态

        Returns:
            具有指定状态的Task对象列表
        """
        return await self._task_service.get_tasks_by_status(session_id, status)

    async def get_tasks_by_assignee(self, session_id: str, assignee: str) -> List[Task]:
        """
        根据分配对象获取任务。

        Args:
            assignee: 分配对象

        Returns:
            分配给指定对象的Task对象列表
        """
        return await self._task_service.get_tasks_by_assignee(session_id, assignee)

    async def update_task(
        self,
        task_id: str,
        name: Optional[str] = None,
        description: Optional[str] = None,
        status: Optional[TaskStatus] = None,
        priority: Optional[TaskPriority] = None,
        assignee: Optional[str] = None,
        dependencies: Optional[List[str]] = None,
        details: Optional[str] = None,
        context: Optional[TaskContext] = None,
        acceptance_criteria: Optional[List[str]] = None,
    ) -> Optional[Task]:
        """
        更新现有任务。

        Args:
            task_id: 要更新的任务ID
            name: 可选的新名称
            description: 可选的新描述
            status: 可选的新状态
            priority: 可选的新优先级
            assignee: 可选的新分配对象
            dependencies: 可选的新依赖列表
            details: 可选的新详细描述
            context: 可选的新上下文信息
            acceptance_criteria: 可选的新验收标准

        Returns:
            更新后的Task对象如果找到，否则返回None
        """
        # 处理上下文更新
        context_files = None
        context_links = None
        context_notes = None
        if context:
            context_files = context.files
            context_links = context.links
            context_notes = context.notes

        return await self._task_service.update_task(
            task_id=task_id,
            name=name,
            description=description,
            status=status,
            priority=priority,
            assignee=assignee,
            dependencies=dependencies,
            details=details,
            context_files=context_files,
            context_links=context_links,
            context_notes=context_notes,
            acceptance_criteria=acceptance_criteria,
        )

    async def delete_task(self, task_id: str) -> bool:
        """
        删除任务。

        Args:
            task_id: 要删除的任务ID

        Returns:
            如果任务被删除返回True，否则返回False
        """
        return await self._task_service.delete(task_id)

    async def add_comment(
        self, task_id: str, author: str, content: str
    ) -> Optional[TaskComment]:
        """
        为任务添加评论。

        Args:
            task_id: 任务ID
            author: 评论作者
            content: 评论内容

        Returns:
            创建的TaskComment对象如果任务存在，否则返回None
        """
        return await self._task_service.add_comment(
            task_id=task_id, author=author, content=content
        )

    async def get_comments(self, task_id: str) -> List[TaskComment]:
        """
        获取任务的所有评论。

        Args:
            task_id: 任务ID

        Returns:
            TaskComment对象列表
        """
        return await self._comment_service.get_comments_by_task(task_id)

    async def get_child_tasks(self, parent_id: str) -> List[Task]:
        """
        获取父任务的所有子任务。

        Args:
            parent_id: 父任务ID

        Returns:
            子Task对象列表
        """
        return await self._task_service.get_child_tasks(parent_id)

    async def search_tasks(
        self, query: str, session_id: Optional[str] = None
    ) -> List[Task]:
        """
        搜索任务（按名称和描述）。

        Args:
            query: 搜索关键词
            session_id: 可选的会话ID过滤

        Returns:
            匹配的Task对象列表
        """
        return await self._task_service.search_tasks(query=query, session_id=session_id)

    async def get_task_with_comments(self, task_id: str) -> Optional[Dict[str, Any]]:
        """
        获取任务及其所有评论。

        Args:
            task_id: 任务ID

        Returns:
            包含任务和评论的字典，或None
        """
        task = await self._task_service.get(task_id)
        if not task:
            return None

        comments = await self._comment_service.get_comments_by_task(task_id)
        return {"task": task, "comments": comments}

    async def get_tasks_by_parent(self, parent_id: str) -> List[Task]:
        """
        获取指定父任务的所有子任务。

        Args:
            parent_id: 父任务ID

        Returns:
            子Task对象列表
        """
        return await self._task_service.get_child_tasks(parent_id)

    async def get_root_tasks(self, session_id: Optional[str] = None) -> List[Task]:
        """
        获取根任务（没有父任务的任务）。

        Args:
            session_id: 可选的会话ID过滤

        Returns:
            根Task对象列表
        """
        return await self._task_service.get_root_tasks(session_id=session_id)
