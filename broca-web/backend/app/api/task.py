"""任务管理API

提供任务的查询、创建、更新、删除等功能
"""

from typing import Any, List, Optional

from broca.session.service import get_task_service, get_task_comment_service
from fastapi import APIRouter, HTTPException
from loguru import logger

from app.schemas.schemas import ApiResponse

router = APIRouter()


@router.get("/tasks", response_model=ApiResponse)
async def get_tasks(
    skip: int = 0,
    limit: int = 20,
    status: Optional[str] = None,
    priority: Optional[str] = None,
    assignee: Optional[str] = None,
    session_id: Optional[str] = None,
    parent_id: Optional[str] = None,
    keyword: Optional[str] = None,
    order_by: str = "created_at desc",
) -> ApiResponse:
    """获取任务列表，支持分页、筛选、搜索和排序"""
    try:
        task_service = get_task_service()

        # 构建过滤条件
        filters = {}
        if status:
            filters["status"] = status
        if priority:
            filters["priority"] = priority
        if assignee:
            filters["assignee"] = assignee
        if session_id:
            filters["session_id"] = session_id
        if parent_id:
            filters["parent_id"] = parent_id

        # 获取所有任务（前端分页）
        tasks = await task_service.get_batch(filters=filters if filters else None, order_by=order_by)

        # 关键词过滤（在内存中过滤）
        if keyword and tasks:
            keyword_lower = keyword.lower()
            tasks = [
                t
                for t in tasks
                if (t.name and keyword_lower in t.name.lower())
                or keyword_lower in t.task_id.lower()
                or (t.description and keyword_lower in t.description.lower())
                or (t.details and keyword_lower in t.details.lower())
            ]

        # 分页
        total = len(tasks)
        tasks = tasks[skip : skip + limit]

        # 转换为字典格式返回
        task_list = []
        for task in tasks:
            task_dict = {
                "task_id": task.task_id,
                "name": task.name,
                "description": task.description,
                "status": task.status.value if hasattr(task.status, "value") else str(task.status),
                "priority": task.priority.value if hasattr(task.priority, "value") else str(task.priority),
                "assignee": task.assignee,
                "parent_id": task.parent_id,
                "session_id": task.session_id,
                "details": task.details,
                "acceptance_criteria": task.acceptance_criteria,
                "context_files": task.context_files,
                "context_links": task.context_links,
                "context_notes": task.context_notes,
                "report": task.report,
                "dependencies": task.dependencies,
                "created_at": task.created_at.isoformat() if task.created_at else None,
                "updated_at": task.updated_at.isoformat() if task.updated_at else None,
            }
            task_list.append(task_dict)

        return ApiResponse.success({"tasks": task_list, "total": total, "skip": skip, "limit": limit})
    except Exception as e:
        logger.exception("Error getting tasks")
        raise HTTPException(500, f"Internal server error: {e!s}") from e


@router.get("/{task_id}", response_model=ApiResponse)
async def get_task_detail(task_id: str, include_comments: bool = True) -> ApiResponse:
    """获取任务详情，包含评论"""
    try:
        task_service = get_task_service()
        comment_service = get_task_comment_service()

        # 获取任务信息
        task = await task_service.get(task_id)
        if not task:
            raise HTTPException(status_code=404, detail="Task not found")

        # 获取评论
        comments = []
        if include_comments:
            comments_data = await comment_service.get_comments_by_task(task_id)
            for comment in comments_data:
                comments.append({
                    "comment_id": comment.comment_id,
                    "author": comment.author,
                    "content": comment.content,
                    "created_at": comment.created_at.isoformat() if comment.created_at else None,
                })

        # 获取子任务
        children = []
        child_tasks = await task_service.get_child_tasks(task_id)
        for child in child_tasks:
            children.append({
                "task_id": child.task_id,
                "name": child.name,
                "description": child.description,
                "status": child.status.value if hasattr(child.status, "value") else str(child.status),
                "priority": child.priority.value if hasattr(child.priority, "value") else str(child.priority),
            })

        # 构建返回数据
        task_dict = {
            "task_id": task.task_id,
            "name": task.name,
            "description": task.description,
            "status": task.status.value if hasattr(task.status, "value") else str(task.status),
            "priority": task.priority.value if hasattr(task.priority, "value") else str(task.priority),
            "assignee": task.assignee,
            "parent_id": task.parent_id,
            "session_id": task.session_id,
            "details": task.details,
            "acceptance_criteria": task.acceptance_criteria,
            "context_files": task.context_files,
            "context_links": task.context_links,
            "context_notes": task.context_notes,
            "report": task.report,
            "dependencies": task.dependencies,
            "created_at": task.created_at.isoformat() if task.created_at else None,
            "updated_at": task.updated_at.isoformat() if task.updated_at else None,
        }

        return ApiResponse.success(
            {
                "task": task_dict,
                "comments": comments,
                "children": children,
            }
        )
    except HTTPException:
        raise
    except Exception as e:
        logger.exception("Error getting task detail")
        raise HTTPException(500, f"Internal server error: {e!s}") from e


@router.post("/", response_model=ApiResponse)
async def create_task(task_data: dict[str, Any]) -> ApiResponse:
    """创建新任务"""
    try:
        task_service = get_task_service()

        # 提取必填字段
        name = task_data.get("name")
        description = task_data.get("description")
        
        if not name or not description:
            raise HTTPException(status_code=400, detail="Name and description are required")

        # 创建任务
        task = await task_service.create_task(
            name=name,
            description=description,
            priority=task_data.get("priority", "medium"),
            parent_id=task_data.get("parent_id"),
            assignee=task_data.get("assignee"),
            dependencies=task_data.get("dependencies"),
            details=task_data.get("details"),
            context_files=task_data.get("context_files"),
            context_links=task_data.get("context_links"),
            context_notes=task_data.get("context_notes"),
            acceptance_criteria=task_data.get("acceptance_criteria"),
            report=task_data.get("report"),
            session_id=task_data.get("session_id"),
        )

        if not task:
            raise HTTPException(status_code=500, detail="Failed to create task")

        # 返回创建的任务
        task_dict = {
            "task_id": task.task_id,
            "name": task.name,
            "description": task.description,
            "status": task.status.value if hasattr(task.status, "value") else str(task.status),
            "priority": task.priority.value if hasattr(task.priority, "value") else str(task.priority),
            "assignee": task.assignee,
            "parent_id": task.parent_id,
            "session_id": task.session_id,
            "created_at": task.created_at.isoformat() if task.created_at else None,
            "updated_at": task.updated_at.isoformat() if task.updated_at else None,
        }

        return ApiResponse.success({"task": task_dict}, msg="Task created successfully")
    except HTTPException:
        raise
    except Exception as e:
        logger.exception("Error creating task")
        raise HTTPException(500, f"Internal server error: {e!s}") from e


@router.put("/{task_id}", response_model=ApiResponse)
async def update_task(task_id: str, update_data: dict[str, Any]) -> ApiResponse:
    """更新任务信息"""
    try:
        task_service = get_task_service()
        task = await task_service.get(task_id)

        if not task:
            raise HTTPException(status_code=404, detail="Task not found")

        # 检查允许更新的字段
        allowed_fields = {
            "name", "description", "status", "priority", "assignee",
            "details", "acceptance_criteria", "context_files", "context_links",
            "context_notes", "report", "dependencies"
        }
        
        update_fields = {}
        for field in allowed_fields:
            if field in update_data:
                update_fields[field] = update_data[field]

        if not update_fields:
            raise HTTPException(400, "No valid fields to update")

        # 更新数据库
        updated_task = await task_service.update_task(task_id, **update_fields)

        if not updated_task:
            raise HTTPException(500, "Failed to update task")

        logger.info(f"Task updated: {task_id}, fields: {list(update_fields.keys())}")
        return ApiResponse.success(msg="Task updated successfully")
    except HTTPException:
        raise
    except Exception as e:
        logger.exception("Error updating task")
        raise HTTPException(500, f"Internal server error: {e!s}") from e


@router.delete("/{task_id}", response_model=ApiResponse)
async def delete_task(task_id: str) -> ApiResponse:
    """删除任务"""
    try:
        task_service = get_task_service()
        success = await task_service.delete(task_id)

        if success:
            return ApiResponse.success(msg="Task deleted successfully")
        else:
            raise HTTPException(status_code=404, detail="Task not found")
    except Exception as e:
        logger.exception("Error deleting task")
        raise HTTPException(500, f"Internal server error: {e!s}") from e


@router.get("/{task_id}/comments", response_model=ApiResponse)
async def get_task_comments(
    task_id: str,
    skip: int = 0,
    limit: int = 50,
) -> ApiResponse:
    """获取任务的评论"""
    try:
        comment_service = get_task_comment_service()

        # 先验证任务是否存在
        task_service = get_task_service()
        task = await task_service.get(task_id)
        if not task:
            raise HTTPException(status_code=404, detail="Task not found")

        # 获取所有评论（需要手动分页）
        comments = await comment_service.get_comments_by_task(task_id)

        # 分页
        total = len(comments)
        comments = comments[skip : skip + limit]

        comment_list = []
        for comment in comments:
            comment_list.append({
                "comment_id": comment.comment_id,
                "author": comment.author,
                "content": comment.content,
                "created_at": comment.created_at.isoformat() if comment.created_at else None,
            })

        return ApiResponse.success(
            {
                "comments": comment_list,
                "total": total,
                "skip": skip,
                "limit": limit,
            }
        )
    except HTTPException:
        raise
    except Exception as e:
        logger.exception("Error getting task comments")
        raise HTTPException(500, f"Internal server error: {e!s}") from e


@router.post("/{task_id}/comments", response_model=ApiResponse)
async def add_task_comment(task_id: str, comment_data: dict[str, Any]) -> ApiResponse:
    """为任务添加评论"""
    try:
        author = comment_data.get("author")
        content = comment_data.get("content")
        
        if not author or not content:
            raise HTTPException(status_code=400, detail="Author and content are required")

        task_service = get_task_service()
        comment = await task_service.add_comment(task_id, author, content)

        if not comment:
            raise HTTPException(status_code=404, detail="Task not found")

        comment_dict = {
            "comment_id": comment.comment_id,
            "author": comment.author,
            "content": comment.content,
            "created_at": comment.created_at.isoformat() if comment.created_at else None,
        }

        return ApiResponse.success({"comment": comment_dict}, msg="Comment added successfully")
    except HTTPException:
        raise
    except Exception as e:
        logger.exception("Error adding comment")
        raise HTTPException(500, f"Internal server error: {e!s}") from e


@router.get("/{task_id}/children", response_model=ApiResponse)
async def get_task_children(task_id: str) -> ApiResponse:
    """获取任务的子任务"""
    try:
        task_service = get_task_service()

        # 验证任务是否存在
        task = await task_service.get(task_id)
        if not task:
            raise HTTPException(status_code=404, detail="Task not found")

        # 获取子任务
        children = await task_service.get_child_tasks(task_id)

        child_list = []
        for child in children:
            child_list.append({
                "task_id": child.task_id,
                "name": child.name,
                "description": child.description,
                "status": child.status.value if hasattr(child.status, "value") else str(child.status),
                "priority": child.priority.value if hasattr(child.priority, "value") else str(child.priority),
                "assignee": child.assignee,
                "created_at": child.created_at.isoformat() if child.created_at else None,
                "updated_at": child.updated_at.isoformat() if child.updated_at else None,
            })

        return ApiResponse.success({"children": child_list})
    except HTTPException:
        raise
    except Exception as e:
        logger.exception("Error getting task children")
        raise HTTPException(500, f"Internal server error: {e!s}") from e


@router.get("/search", response_model=ApiResponse)
async def search_tasks(
    query: str,
    session_id: Optional[str] = None,
    skip: int = 0,
    limit: int = 20,
) -> ApiResponse:
    """搜索任务"""
    try:
        task_service = get_task_service()

        # 搜索任务
        tasks = await task_service.search_tasks(query, session_id)

        # 分页
        total = len(tasks)
        tasks = tasks[skip : skip + limit]

        # 转换为字典格式返回
        task_list = []
        for task in tasks:
            task_dict = {
                "task_id": task.task_id,
                "name": task.name,
                "description": task.description,
                "status": task.status.value if hasattr(task.status, "value") else str(task.status),
                "priority": task.priority.value if hasattr(task.priority, "value") else str(task.priority),
                "assignee": task.assignee,
                "parent_id": task.parent_id,
                "session_id": task.session_id,
                "created_at": task.created_at.isoformat() if task.created_at else None,
                "updated_at": task.updated_at.isoformat() if task.updated_at else None,
            }
            task_list.append(task_dict)

        return ApiResponse.success({"tasks": task_list, "total": total, "skip": skip, "limit": limit})
    except Exception as e:
        logger.exception("Error searching tasks")
        raise HTTPException(500, f"Internal server error: {e!s}") from e