"""
Service类实现模块

为Session、Turn、Message、Agent、AgentConfig等数据模型提供Service类
实现CRUD操作和业务逻辑。
"""

import uuid
from datetime import datetime
from typing import Any, Dict, Generic, List, Optional, Type, TypeVar

from loguru import logger
from sqlalchemy import desc, func, select
from sqlmodel import SQLModel, and_

from .database import db_manager
from .models import (
    Agent,
    AgentConfig,
    JobExecution,
    JobStatus,
    JobType,
    Message,
    MessageRole,
    MessageType,
    ScheduledJob,
    Session,
    SessionStatus,
    Task,
    TaskComment,
    TaskPriority,
    TaskStatus,
    Turn,
)

logger.remove()
logger.add("db.log", level="DEBUG")

# 泛型类型变量
T = TypeVar("T", bound=SQLModel)


class BaseService(Generic[T]):
    """Service基类，提供通用的CRUD操作"""

    def __init__(self, model_class: Type[T]):
        self.model_class = model_class
        # 根据模型类名确定ID字段名
        self.id_field = self._get_id_field_name()

    def _get_id_field_name(self) -> str:
        """根据模型类名获取ID字段名"""
        class_name = self.model_class.__name__.lower()
        if class_name == "session":
            return "session_id"
        elif class_name == "turn":
            return "turn_id"
        elif class_name == "message":
            return "message_id"
        elif class_name == "agent":
            return "agent_id"
        elif class_name == "agentconfig":
            return "config_id"
        elif class_name == "scheduledjob":
            return "job_id"
        elif class_name == "jobexecution":
            return "execution_id"
        else:
            # 默认规则：类名 + "_id"
            return f"{class_name}_id"

    async def create(self, **kwargs) -> T:
        """创建新记录"""
        async with db_manager.get_session() as session:
            instance = self.model_class(**kwargs)
            session.add(instance)
            await session.commit()
            await session.refresh(instance)
            return instance

    async def get(self, id: str) -> Optional[T]:
        """根据ID获取记录"""
        async with db_manager.get_session() as session:
            statement = select(self.model_class).where(
                getattr(self.model_class, self.id_field) == id
            )
            result = await session.exec(statement)
            return result.scalars().first()

    async def get_batch(
        self,
        filters: Optional[Dict[str, Any]] = None,
        order_by: Optional[str] = None,
        skip=None,
        limit=None,
    ) -> List[T]:
        """获取批量记录"""

        async with db_manager.get_session() as session:
            statement = select(self.model_class)

            if filters:
                conditions = []
                for key, value in filters.items():
                    if hasattr(self.model_class, key):
                        conditions.append(getattr(self.model_class, key) == value)
                if conditions:
                    statement = statement.where(and_(*conditions))
            if order_by:
                parts = order_by.strip().split()
                if len(parts) >= 1:
                    column_name = parts[0]
                    if hasattr(self.model_class, column_name):
                        column = getattr(self.model_class, column_name)
                        if len(parts) >= 2 and parts[1].lower() == "desc":
                            statement = statement.order_by(desc(column))
                        else:
                            statement = statement.order_by(column)

            if skip is not None and limit is not None:
                statement = statement.offset(skip).limit(limit)

            result = await session.exec(statement)
            # 使用scalars()获取模型实例列表
            return result.scalars().all()

    async def update(self, id: str, **kwargs) -> Optional[T]:
        """更新记录"""
        async with db_manager.get_session() as session:
            # 直接查询而不是调用self.get，避免额外的会话
            statement = select(self.model_class).where(
                getattr(self.model_class, self.id_field) == id
            )
            result = await session.exec(statement)
            instance = result.scalars().first()

            if not instance:
                return None

            for key, value in kwargs.items():
                if hasattr(instance, key):
                    setattr(instance, key, value)

            session.add(instance)
            await session.commit()
            await session.refresh(instance)
            return instance

    async def delete(self, id: str) -> bool:
        """删除记录"""
        async with db_manager.get_session() as session:
            statement = select(self.model_class).where(
                getattr(self.model_class, self.id_field) == id
            )
            result = await session.exec(statement)
            instance = result.scalars().first()

            if not instance:
                return False

            await session.delete(instance)
            await session.commit()
            return True

    async def delete_batch(self, ids: List[str]) -> int:
        """批量删除记录，返回删除数量"""
        if not ids:
            return 0

        async with db_manager.get_session() as session:
            statement = select(self.model_class).where(
                getattr(self.model_class, self.id_field).in_(ids)
            )
            result = await session.exec(statement)
            instances = result.scalars().all()

            count = 0
            for instance in instances:
                await session.delete(instance)
                count += 1

            await session.commit()
            return count

    async def count(self, filters: Optional[Dict[str, Any]] = None) -> int:
        """统计记录数量"""
        async with db_manager.get_session() as session:
            statement = select(func.count(self.id_field))

            if filters:
                conditions = []
                for key, value in filters.items():
                    if hasattr(self.model_class, key):
                        conditions.append(getattr(self.model_class, key) == value)
                if conditions:
                    statement = statement.where(and_(*conditions))

            result = await session.exec(statement)
            return result.scalar()


class SessionService(BaseService[Session]):
    """Session Service类"""

    def __init__(self):
        super().__init__(Session)

    async def create_session(
        self,
        session_id: str,
        description: Optional[str] = None,
        workspace: Optional[str] = None,
    ) -> Session:
        """创建新会话"""
        return await self.create(
            session_id=session_id,
            status=SessionStatus.ACTIVE,
            description=description,
            workspace=workspace,
            created_at=datetime.utcnow(),
        )

    async def close_session(self, session_id: str) -> Optional[Session]:
        """关闭会话"""
        return await self.update(
            session_id,
            status=SessionStatus.INACTIVE,
            finished_at=datetime.utcnow(),
        )


class TurnService(BaseService[Turn]):
    """Turn Service类"""

    def __init__(self):
        super().__init__(Turn)

    async def create_turn(
        self,
        turn_id: str,
        session_id: str,
        agent_id: str,
        sequence_number: int,
        turn_description: Optional[str] = None,
    ) -> Turn:
        """创建新轮次"""
        return await self.create(
            turn_id=turn_id,
            session_id=session_id,
            agent_id=agent_id,
            sequence_number=sequence_number,
            turn_description=turn_description,
            created_at=datetime.utcnow(),
        )

    async def get_latest_turn(self, session_id: str) -> Optional[Turn]:
        """获取会话的最新轮次"""
        async with db_manager.get_session() as session:
            statement = (
                select(Turn)
                .where(Turn.session_id == session_id)
                .order_by(Turn.sequence_number.desc())
                .limit(1)
            )
            result = await session.exec(statement)
            return result.scalars().first()

    async def get_next_sequence_number(self, session_id: str) -> int:
        """获取下一个轮次序列号"""
        latest_turn = await self.get_latest_turn(session_id)
        if latest_turn:
            return latest_turn.sequence_number + 1
        return 1


class MessageService(BaseService[Message]):
    """Message Service类"""

    def __init__(self):
        super().__init__(Message)

    async def create_message(
        self,
        message_id: str,
        session_id: str,
        turn_id: str,
        agent_id: str,
        role: MessageRole,
        content: Optional[str] = None,
        message_type: MessageType = MessageType.USER_MESSAGE,
        sequence_number: int = 1,
        data: Optional[Dict[str, Any]] = None,
    ) -> Message:
        """创建新消息"""
        # 构建data字段
        message_data = data or {}
        if content:
            message_data["content"] = content

        return await self.create(
            message_id=message_id,
            session_id=session_id,
            turn_id=turn_id,
            agent_id=agent_id,
            role=role,
            message_type=message_type,
            sequence_number=sequence_number,
            timestamp=datetime.utcnow(),
            data=message_data,
        )

    async def get_messages_by_session(
        self, session_id: str, order_by="sequence_number", skip=None, limit=None
    ) -> List[Message]:
        """根据会话ID获取消息"""
        return await self.get_batch(
            filters={"session_id": session_id},
            order_by=order_by,
            skip=skip,
            limit=limit,
        )

    async def get_messages_by_agent(self, agent_id: str) -> List[Message]:
        """根据Agent ID获取消息"""
        return await self.get_batch(
            filters={"agent_id": agent_id}, order_by="sequence_number"
        )

    async def get_next_sequence_number(self, session_id: str) -> int:
        """获取下一个消息序列号"""
        async with db_manager.get_session() as session:
            statement = (
                select(Message)
                .where(Message.session_id == session_id)
                .order_by(Message.sequence_number.desc())
                .limit(1)
            )
            result = await session.exec(statement)
            latest_message = result.scalars().first()
            if latest_message:
                return latest_message.sequence_number + 1
            return 1

    async def get_message_stats_by_session(self, session_id: str) -> Dict[str, Any]:
        """获取会话的消息统计信息

        Returns:
            包含以下字段的字典:
            - total_messages: 消息总数
            - messages_by_type: 按消息类型分组的数量统计
            - tool_call_errors: 工具调用错误数量
        """
        async with db_manager.get_session() as session:
            total_messages = await self.count(filters={"session_id": session_id})

            type_stats_statement = (
                select(Message.message_type, func.count(Message.message_id))
                .where(Message.session_id == session_id)
                .group_by(Message.message_type)
            )
            type_stats_result = await session.exec(type_stats_statement)
            type_stats_rows = type_stats_result.all()

            messages_by_type = {}
            for msg_type, count in type_stats_rows:
                messages_by_type[str(msg_type)] = count

            tool_error_statement = select(Message).where(
                and_(
                    Message.session_id == session_id,
                    Message.message_type == MessageType.TOOL_CALL,
                )
            )
            tool_calls_result = await session.exec(tool_error_statement)
            tool_call_messages = tool_calls_result.scalars().all()

            tool_call_errors = 0
            for msg in tool_call_messages:
                # 检查data字段中是否包含错误信息
                data = msg.data or {}
                is_error = data.get("status") == "error"
                if is_error:
                    tool_call_errors += 1

            return {
                "total_messages": total_messages,
                "messages_by_type": messages_by_type,
                "tool_call_errors": tool_call_errors,
            }


class AgentConfigService(BaseService[AgentConfig]):
    """AgentConfig Service类"""

    def __init__(self):
        super().__init__(AgentConfig)

    async def create_config(
        self, session_id: str, name: str, config_content: str
    ) -> AgentConfig:
        """创建新配置"""
        config_id = uuid.uuid4().hex
        return await self.create(
            config_id=config_id,
            session_id=session_id,
            name=name,
            config_content=config_content,
            created_at=datetime.utcnow(),
        )

    async def get_configs_by_session(self, session_id: str) -> List[AgentConfig]:
        """根据会话ID获取配置"""
        return await self.get_batch(filters={"session_id": session_id})


class AgentService(BaseService[Agent]):
    """Agent Service类"""

    def __init__(self):
        super().__init__(Agent)

    async def create_agent(
        self,
        agent_id: str,
        config_id: str,
        session_id: str,
        name: str,
        role: str,
    ) -> Agent:
        """创建新Agent"""
        return await self.create(
            agent_id=agent_id,
            config_id=config_id,
            session_id=session_id,
            name=name,
            role=role,
            created_at=datetime.utcnow(),
        )

    async def get_agents_by_session(self, session_id: str) -> List[Agent]:
        """根据会话ID获取Agent"""
        return await self.get_batch(filters={"session_id": session_id})


# 全局Service实例
session_service = SessionService()
turn_service = TurnService()
message_service = MessageService()
agent_config_service = AgentConfigService()
agent_service = AgentService()


def get_session_service() -> SessionService:
    """获取SessionService实例"""
    return session_service


def get_turn_service() -> TurnService:
    """获取TurnService实例"""
    return turn_service


def get_message_service() -> MessageService:
    """获取MessageService实例"""
    return message_service


def get_agent_config_service() -> AgentConfigService:
    """获取AgentConfigService实例"""
    return agent_config_service


def get_agent_service() -> AgentService:
    """获取AgentService实例"""
    return agent_service


class JobService(BaseService[ScheduledJob]):
    """调度任务Service类"""

    def __init__(self):
        super().__init__(ScheduledJob)

    async def create_job(
        self,
        job_id: str,
        name: str,
        job_type: JobType,
        trigger_type: str,
        trigger_config: Dict[str, Any],
        content: str,
        session_id: Optional[str] = None,
        agent_id: Optional[str] = None,
    ) -> ScheduledJob:
        """创建新任务"""
        return await self.create(
            job_id=job_id,
            name=name,
            job_type=job_type,
            status=JobStatus.ACTIVE,
            trigger_type=trigger_type,
            trigger_config=trigger_config,
            content=content,
            session_id=session_id,
            agent_id=agent_id,
            created_at=datetime.utcnow(),
            updated_at=datetime.utcnow(),
        )

    async def get_active_jobs(
        self, session_id: Optional[str] = None
    ) -> List[ScheduledJob]:
        """获取活跃任务"""
        filters = {"status": JobStatus.ACTIVE}
        if session_id:
            filters["session_id"] = session_id
        return await self.get_batch(filters=filters, order_by="created_at")

    async def get_jobs_by_session(self, session_id: str) -> List[ScheduledJob]:
        """根据会话ID获取任务"""
        return await self.get_batch(
            filters={"session_id": session_id}, order_by="created_at"
        )

    async def update_job_status(self, job_id: str, status: JobStatus) -> bool:
        """更新任务状态"""
        job = await self.update(job_id, status=status, updated_at=datetime.utcnow())
        return job is not None

    async def update_next_run_time(
        self, job_id: str, next_run_time: Optional[datetime]
    ) -> bool:
        """更新下次执行时间"""
        job = await self.update(
            job_id, next_run_time=next_run_time, updated_at=datetime.utcnow()
        )
        return job is not None

    async def pause_job(self, job_id: str) -> bool:
        """暂停任务"""
        return await self.update_job_status(job_id, JobStatus.PAUSED)

    async def resume_job(self, job_id: str) -> bool:
        """恢复任务"""
        return await self.update_job_status(job_id, JobStatus.ACTIVE)

    async def cancel_job(self, job_id: str) -> bool:
        """取消任务"""
        return await self.update_job_status(job_id, JobStatus.CANCELLED)

    async def complete_job(self, job_id: str) -> bool:
        """标记任务完成（一次性任务）"""
        return await self.update_job_status(job_id, JobStatus.COMPLETED)


class JobExecutionService(BaseService[JobExecution]):
    """任务执行记录Service类"""

    def __init__(self):
        super().__init__(JobExecution)

    async def create_execution(
        self, job_id: str, success: bool, result: Optional[str] = None
    ) -> JobExecution:
        """创建执行记录"""
        execution_id = f"exec_{uuid.uuid4().hex}"
        return await self.create(
            execution_id=execution_id,
            job_id=job_id,
            success=success,
            result=result,
            executed_at=datetime.utcnow(),
        )

    async def get_executions_by_job(
        self, job_id: str, limit: int = 10
    ) -> List[JobExecution]:
        """根据任务ID获取执行记录"""
        async with db_manager.get_session() as session:
            statement = (
                select(JobExecution)
                .where(JobExecution.job_id == job_id)
                .order_by(JobExecution.executed_at.desc())
                .limit(limit)
            )
            result = await session.exec(statement)
            return result.scalars().all()

    async def get_recent_executions(self, limit: int = 50) -> List[JobExecution]:
        """获取最近的执行记录"""
        async with db_manager.get_session() as session:
            statement = (
                select(JobExecution)
                .order_by(JobExecution.executed_at.desc())
                .limit(limit)
            )
            result = await session.exec(statement)
            return result.scalars().all()


# 全局Service实例
job_service = JobService()
job_execution_service = JobExecutionService()


def get_job_service() -> JobService:
    """获取JobService实例"""
    return job_service


def get_job_execution_service() -> JobExecutionService:
    """获取JobExecutionService实例"""
    return job_execution_service


class TaskCommentService(BaseService[TaskComment]):
    """任务评论Service类"""

    def __init__(self):
        super().__init__(TaskComment)

    async def get_comments_by_task(self, task_id: str) -> List[TaskComment]:
        """根据任务ID获取评论"""
        return await self.get_batch(filters={"task_id": task_id}, order_by="created_at")

    async def get_comments_by_author(self, author: str) -> List[TaskComment]:
        """根据作者获取评论"""
        return await self.get_batch(filters={"author": author}, order_by="created_at")


class TaskService(BaseService[Task]):
    """任务Service类"""

    def __init__(self):
        super().__init__(Task)

    def _get_id_field_name(self) -> str:
        """重写ID字段名获取方法"""
        return "task_id"

    async def create_task(
        self,
        name: str,
        description: str,
        priority: TaskPriority = TaskPriority.MEDIUM,
        parent_id: Optional[str] = None,
        assignee: Optional[str] = None,
        dependencies: Optional[List[str]] = None,
        details: Optional[str] = None,
        context_files: Optional[List[str]] = None,
        context_links: Optional[List[str]] = None,
        context_notes: Optional[str] = None,
        acceptance_criteria: Optional[List[str]] = None,
        report: Optional[str] = None,
        session_id: Optional[str] = None,
    ) -> Task:
        """创建新任务"""
        now = datetime.now()
        return await self.create(
            name=name,
            description=description,
            session_id=session_id,
            parent_id=parent_id,
            status=TaskStatus.PENDING,
            priority=priority,
            assignee=assignee,
            dependencies=dependencies,
            details=details,
            acceptance_criteria=acceptance_criteria,
            context_files=context_files,
            context_links=context_links,
            context_notes=context_notes,
            report=report,
            created_at=now,
            updated_at=now,
        )

    async def get_tasks_by_session(
        self, session_id: str, status: Optional[TaskStatus] = None
    ) -> List[Task]:
        """根据会话ID获取任务"""
        filters = {"session_id": session_id}
        if status:
            filters["status"] = status
        return await self.get_batch(filters=filters, order_by="created_at desc")

    async def get_tasks_by_status(
        self, session_id: str, status: TaskStatus
    ) -> List[Task]:
        """根据状态获取任务"""
        return await self.get_batch(
            filters={"session_id": session_id, "status": status},
            order_by="created_at desc",
        )

    async def get_tasks_by_assignee(self, session_id: str, assignee: str) -> List[Task]:
        """根据分配对象获取任务"""
        return await self.get_batch(
            filters={"session_id": session_id, "assignee": assignee},
            order_by="created_at desc",
        )

    async def get_child_tasks(self, parent_id: str) -> List[Task]:
        """获取子任务"""
        return await self.get_batch(
            filters={"parent_id": parent_id}, order_by="created_at desc"
        )

    async def get_root_tasks(self, session_id: Optional[str] = None) -> List[Task]:
        """获取根任务（没有父任务的任务）"""
        async with db_manager.get_session() as session:
            statement = select(Task).where(Task.parent_id.is_(None))

            if session_id:
                statement = statement.where(Task.session_id == session_id)

            statement = statement.order_by(Task.created_at)
            result = await session.exec(statement)
            return result.scalars().all()

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
        context_files: Optional[List[str]] = None,
        context_links: Optional[List[str]] = None,
        context_notes: Optional[str] = None,
        acceptance_criteria: Optional[List[str]] = None,
        report: Optional[str] = None,
    ) -> Optional[Task]:
        """更新任务"""
        update_data = {}
        if name is not None:
            update_data["name"] = name
        if description is not None:
            update_data["description"] = description
        if status is not None:
            update_data["status"] = status
        if priority is not None:
            update_data["priority"] = priority
        if assignee is not None:
            update_data["assignee"] = assignee
        if dependencies is not None:
            update_data["dependencies"] = dependencies
        if details is not None:
            update_data["details"] = details
        if acceptance_criteria is not None:
            update_data["acceptance_criteria"] = acceptance_criteria
        if context_files is not None:
            update_data["context_files"] = context_files
        if context_links is not None:
            update_data["context_links"] = context_links
        if context_notes is not None:
            update_data["context_notes"] = context_notes
        if report is not None:
            update_data["report"] = report

        if update_data:
            update_data["updated_at"] = datetime.now()

        return await self.update(task_id, **update_data)

    async def search_tasks(
        self, query: str, session_id: Optional[str] = None
    ) -> List[Task]:
        """搜索任务（按名称和描述）"""
        async with db_manager.get_session() as session:
            statement = select(Task)

            conditions = []
            if session_id:
                conditions.append(Task.session_id == session_id)

            # 添加搜索条件
            query_lower = query.lower()
            # 由于SQLite的LIKE限制，我们会在Python中进行额外的过滤
            statement = statement.order_by(Task.created_at)

            if conditions:
                statement = statement.where(and_(*conditions))

            result = await session.exec(statement)
            tasks = result.scalars().all()

            # 在Python中进行模糊匹配
            filtered_tasks = []
            for task in tasks:
                if (
                    query_lower in task.name.lower()
                    or query_lower in task.description.lower()
                    or (task.details and query_lower in task.details.lower())
                ):
                    filtered_tasks.append(task)

            return filtered_tasks

    async def add_comment(
        self, task_id: str, author: str, content: str
    ) -> Optional[TaskComment]:
        """为任务添加评论"""
        # 验证任务存在
        task = await self.get(task_id)
        if not task:
            return None

        comment_service = TaskCommentService()
        comment = await comment_service.create(
            task_id=task_id,
            author=author,
            content=content,
            created_at=datetime.now(),
        )

        # 更新任务的updated_at
        await self.update(task_id, updated_at=datetime.now())

        return comment

    async def get_task_with_comments(self, task_id: str) -> Optional[Dict[str, Any]]:
        """获取任务及其所有评论"""
        task = await self.get(task_id)
        if not task:
            return None

        comment_service = TaskCommentService()
        comments = await comment_service.get_comments_by_task(task_id)
        return {"task": task, "comments": comments}


# 全局Service实例
task_service = TaskService()
task_comment_service = TaskCommentService()


def get_task_service() -> TaskService:
    """获取TaskService实例"""
    return task_service


def get_task_comment_service() -> TaskCommentService:
    """获取TaskCommentService实例"""
    return task_comment_service
