"""定时任务管理API

提供任务的查询、执行、状态管理等功能
"""

from typing import Any

from broca.session.service import get_job_execution_service, get_job_service
from fastapi import APIRouter, HTTPException
from loguru import logger

from app.schemas.schemas import ApiResponse

router = APIRouter()


@router.get("/jobs", response_model=ApiResponse)
async def get_jobs(
    skip: int = 0,
    limit: int = 20,
    status: str | None = None,
    job_type: str | None = None,
    session_id: str | None = None,
    keyword: str | None = None,
    order_by: str = "created_at desc",
) -> ApiResponse:
    """获取任务列表，支持分页、筛选、搜索和排序"""
    try:
        job_service = get_job_service()

        # 构建过滤条件
        filters = {}
        if status:
            filters["status"] = status
        if job_type:
            filters["job_type"] = job_type
        if session_id:
            filters["session_id"] = session_id

        # 获取所有任务（前端分页）
        jobs = await job_service.get_batch(filters=filters if filters else None, order_by=order_by)

        # 关键词过滤（在内存中过滤）
        if keyword and jobs:
            keyword_lower = keyword.lower()
            jobs = [
                j
                for j in jobs
                if (j.name and keyword_lower in j.name.lower())
                or keyword_lower in j.job_id.lower()
                or (j.content and keyword_lower in j.content.lower())
            ]

        # 分页
        total = len(jobs)
        jobs = jobs[skip : skip + limit]

        # 转换为字典格式返回
        job_list = []
        for job in jobs:
            job_dict = {
                "job_id": job.job_id,
                "name": job.name,
                "job_type": job.job_type.value if hasattr(job.job_type, "value") else str(job.job_type),
                "status": job.status.value if hasattr(job.status, "value") else str(job.status),
                "trigger_type": job.trigger_type,
                "trigger_config": job.trigger_config,
                "content": job.content,
                "session_id": job.session_id,
                "agent_id": job.agent_id,
                "created_at": job.created_at.isoformat() if job.created_at else None,
                "updated_at": job.updated_at.isoformat() if job.updated_at else None,
                "next_run_time": job.next_run_time.isoformat() if job.next_run_time else None,
            }
            job_list.append(job_dict)

        return ApiResponse.success({"jobs": job_list, "total": total, "skip": skip, "limit": limit})
    except Exception as e:
        logger.exception("Error getting jobs")
        raise HTTPException(500, f"Internal server error: {e!s}") from e


@router.get("/{job_id}", response_model=ApiResponse)
async def get_job_detail(job_id: str, execution_limit: int = 10) -> ApiResponse:
    """获取任务详情，包含最近的执行记录"""
    try:
        job_service = get_job_service()
        execution_service = get_job_execution_service()

        # 获取任务信息
        job = await job_service.get(job_id)
        if not job:
            raise HTTPException(status_code=404, detail="Job not found")

        # 获取最近的执行记录
        executions = await execution_service.get_executions_by_job(job_id, limit=execution_limit)

        # 构建返回数据
        job_dict = {
            "job_id": job.job_id,
            "name": job.name,
            "job_type": job.job_type.value if hasattr(job.job_type, "value") else str(job.job_type),
            "status": job.status.value if hasattr(job.status, "value") else str(job.status),
            "trigger_type": job.trigger_type,
            "trigger_config": job.trigger_config,
            "content": job.content,
            "session_id": job.session_id,
            "agent_id": job.agent_id,
            "created_at": job.created_at.isoformat() if job.created_at else None,
            "updated_at": job.updated_at.isoformat() if job.updated_at else None,
            "next_run_time": job.next_run_time.isoformat() if job.next_run_time else None,
        }

        execution_list = []
        for exec in executions:
            execution_list.append(
                {
                    "execution_id": exec.execution_id,
                    "executed_at": exec.executed_at.isoformat() if exec.executed_at else None,
                    "success": exec.success,
                    "result": exec.result,
                }
            )

        return ApiResponse.success(
            {
                "job": job_dict,
                "executions": execution_list,
            }
        )
    except HTTPException:
        raise
    except Exception as e:
        logger.exception("Error getting job detail")
        raise HTTPException(500, f"Internal server error: {e!s}") from e


@router.get("/{job_id}/executions", response_model=ApiResponse)
async def get_job_executions(
    job_id: str,
    skip: int = 0,
    limit: int = 50,
    success: bool | None = None,
) -> ApiResponse:
    """获取任务的执行记录，支持分页和按成功/失败筛选"""
    try:
        execution_service = get_job_execution_service()

        # 先验证任务是否存在
        job_service = get_job_service()
        job = await job_service.get(job_id)
        if not job:
            raise HTTPException(status_code=404, detail="Job not found")

        # 获取所有执行记录（需要手动筛选，因为服务层没有直接按job_id筛选+分页的方法）
        # 这里先获取该job的所有执行记录，再做分页和筛选
        from broca.session.models import JobExecution
        from broca.session.service import db_manager
        from sqlalchemy import select

        async with db_manager.get_session() as session:
            statement = (
                select(JobExecution).where(JobExecution.job_id == job_id).order_by(JobExecution.executed_at.desc())
            )

            if success is not None:
                statement = statement.where(JobExecution.success == success)

            result = await session.exec(statement)
            all_executions = result.scalars().all()

            # 分页
            total = len(all_executions)
            executions = all_executions[skip : skip + limit]

            execution_list = []
            for exec in executions:
                execution_list.append(
                    {
                        "execution_id": exec.execution_id,
                        "executed_at": exec.executed_at.isoformat() if exec.executed_at else None,
                        "success": exec.success,
                        "result": exec.result,
                    }
                )

            return ApiResponse.success(
                {
                    "executions": execution_list,
                    "total": total,
                    "skip": skip,
                    "limit": limit,
                }
            )
    except HTTPException:
        raise
    except Exception as e:
        logger.exception("Error getting job executions")
        raise HTTPException(500, f"Internal server error: {e!s}") from e


@router.post("/{job_id}/execute", response_model=ApiResponse)
async def execute_job_now(job_id: str) -> ApiResponse:
    """立即执行指定的任务"""
    try:
        from broca.scheduler import Scheduler

        scheduler = Scheduler()
        success = await scheduler.execute_job_now(job_id)

        if success:
            return ApiResponse.success(msg="Job executed successfully")
        else:
            return ApiResponse.error(400, "Failed to execute job")
    except Exception as e:
        logger.exception(f"Error executing job {job_id}")
        raise HTTPException(500, f"Internal server error: {e!s}") from e


@router.put("/{job_id}", response_model=ApiResponse)
async def update_job(job_id: str, update_data: dict[str, Any]) -> ApiResponse:
    """更新任务信息（目前仅支持更新名称和内容）"""
    try:
        job_service = get_job_service()
        job = await job_service.get(job_id)

        if not job:
            raise HTTPException(status_code=404, detail="Job not found")

        # 检查允许更新的字段
        allowed_fields = {"name", "content"}
        update_fields = {}
        for field in allowed_fields:
            if field in update_data:
                update_fields[field] = update_data[field]

        if not update_fields:
            raise HTTPException(400, "No valid fields to update")

        # 更新数据库
        updated_job = await job_service.update(job_id, **update_fields, updated_at=None)

        if not updated_job:
            raise HTTPException(500, "Failed to update job")

        # 注意：修改触发器配置或内容后，需要重新调度任务
        # 这里简化处理，仅更新数据库，实际可能需要重新调度
        # TODO: 如果需要修改trigger_config，需要调用scheduler重新调度

        logger.info(f"Job updated: {job_id}, fields: {list(update_fields.keys())}")
        return ApiResponse.success(msg="Job updated successfully")
    except HTTPException:
        raise
    except Exception as e:
        logger.exception("Error updating job")
        raise HTTPException(500, f"Internal server error: {e!s}") from e


@router.delete("/{job_id}", response_model=ApiResponse)
async def delete_job(job_id: str) -> ApiResponse:
    """删除任务"""
    try:
        from broca.scheduler import Scheduler

        scheduler = Scheduler()
        success = await scheduler.remove_job(job_id)

        if success:
            return ApiResponse.success(msg="Job deleted successfully")
        else:
            raise HTTPException(status_code=404, detail="Job not found")
    except Exception as e:
        logger.exception("Error deleting job")
        raise HTTPException(500, f"Internal server error: {e!s}") from e


@router.post("/{job_id}/pause", response_model=ApiResponse)
async def pause_job(job_id: str) -> ApiResponse:
    """暂停任务"""
    try:
        job_service = get_job_service()
        success = await job_service.pause_job(job_id)

        if success:
            # 同时暂停调度器中的任务
            from broca.scheduler import Scheduler

            scheduler = Scheduler()
            try:
                scheduler.apscheduler.pause_job(job_id)
            except Exception as e:
                logger.warning(f"Failed to pause job in scheduler: {e}")

            return ApiResponse.success(msg="Job paused successfully")
        else:
            raise HTTPException(status_code=404, detail="Job not found")
    except Exception as e:
        logger.exception("Error pausing job")
        raise HTTPException(500, f"Internal server error: {e!s}") from e


@router.post("/{job_id}/resume", response_model=ApiResponse)
async def resume_job(job_id: str) -> ApiResponse:
    """恢复任务"""
    try:
        job_service = get_job_service()
        success = await job_service.resume_job(job_id)

        if success:
            # 同时恢复调度器中的任务
            from broca.scheduler import Scheduler

            scheduler = Scheduler()
            try:
                scheduler.apscheduler.resume_job(job_id)
            except Exception as e:
                logger.warning(f"Failed to resume job in scheduler: {e}")

            return ApiResponse.success(msg="Job resumed successfully")
        else:
            raise HTTPException(status_code=404, detail="Job not found")
    except Exception as e:
        logger.exception("Error resuming job")
        raise HTTPException(500, f"Internal server error: {e!s}") from e
