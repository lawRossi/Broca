"""
Crew API

提供编排（Crew）的 REST API：
- POST /api/crews - 提交编排执行
- POST /api/crews/validate - 校验编排配置
- GET /api/crews - 列出编排执行记录
- GET /api/crews/{execution_id} - 获取编排详情
- POST /api/crews/{execution_id}/abort - 中止编排
"""

from typing import Optional

from fastapi import APIRouter, HTTPException, Request
from loguru import logger
from pydantic import BaseModel

from app.schemas.schemas import ApiResponse
from app.services.crew_service import get_crew_service

router = APIRouter()


class CrewSubmitRequest(BaseModel):
    """提交编排的请求模型"""

    yaml_content: Optional[str] = None
    yaml_path: Optional[str] = None
    session_id: str

    model_config = {"from_attributes": True}


class CrewValidateRequest(BaseModel):
    """校验编排配置的请求模型"""

    yaml_content: Optional[str] = None
    yaml_path: Optional[str] = None

    model_config = {"from_attributes": True}


@router.post("", response_model=ApiResponse)
async def submit_crew(request: CrewSubmitRequest) -> ApiResponse:
    """
    提交编排执行

    支持两种方式提交编排配置：
    1. yaml_content: 直接传入 YAML 字符串
    2. yaml_path: 传入服务器上的 YAML 文件路径
    """
    try:
        crew_service = get_crew_service()

        if request.yaml_content:
            record = await crew_service.submit_crew_from_yaml(
                yaml_content=request.yaml_content,
                session_id=request.session_id,
            )
        elif request.yaml_path:
            record = await crew_service.submit_crew_from_file(
                yaml_path=request.yaml_path,
                session_id=request.session_id,
            )
        else:
            return ApiResponse.error(
                code=400,
                msg="Either yaml_content or yaml_path is required",
            )

        if record["status"] == "failed":
            return ApiResponse.error(
                code=500,
                msg=f"Crew submission failed: {record.get('error', 'Unknown error')}",
            )

        return ApiResponse.success(
            data=record,
            msg="Crew orchestration submitted successfully",
        )

    except ValueError as e:
        return ApiResponse.error(code=400, msg=str(e))
    except RuntimeError as e:
        return ApiResponse.error(code=400, msg=str(e))
    except Exception as e:
        logger.error(f"Error submitting crew: {e}")
        return ApiResponse.error(code=500, msg=f"Internal server error: {e!s}")


@router.post("/validate", response_model=ApiResponse)
async def validate_crew(request: CrewValidateRequest) -> ApiResponse:
    """
    校验编排配置

    支持 YAML 字符串和文件路径两种方式。
    返回校验错误列表，空列表表示配置有效。
    """
    try:
        crew_service = get_crew_service()

        if request.yaml_content:
            errors = crew_service.validate_crew_yaml(request.yaml_content)
        elif request.yaml_path:
            errors = crew_service.validate_crew_yaml_file(request.yaml_path)
        else:
            return ApiResponse.error(
                code=400,
                msg="Either yaml_content or yaml_path is required",
            )

        is_valid = len(errors) == 0
        return ApiResponse.success(
            data={
                "valid": is_valid,
                "errors": errors,
                "error_count": len(errors),
            },
            msg="Configuration is valid" if is_valid else f"Found {len(errors)} validation error(s)",
        )

    except Exception as e:
        logger.error(f"Error validating crew: {e}")
        return ApiResponse.error(code=500, msg=f"Validation error: {e!s}")


@router.get("", response_model=ApiResponse)
async def list_crews(
    session_id: Optional[str] = None,
    status: Optional[str] = None,
) -> ApiResponse:
    """列出编排执行记录"""
    try:
        crew_service = get_crew_service()
        executions = await crew_service.list_executions(
            session_id=session_id,
            status=status,
        )
        return ApiResponse.success(
            data={
                "executions": executions,
                "total": len(executions),
            },
            msg="Executions retrieved successfully",
        )
    except Exception as e:
        logger.error(f"Error listing crews: {e}")
        return ApiResponse.error(code=500, msg=f"Internal server error: {e!s}")


@router.get("/configs", response_model=ApiResponse)
async def list_crew_configs(workspace: str) -> ApiResponse:
    """
    列出 workspace 下 crew_configs 目录中已有的编排配置文件

    Args:
        workspace: 工作空间路径（需 URL 编码）
    """
    try:
        crew_service = get_crew_service()
        configs = crew_service.list_crew_configs(workspace)
        return ApiResponse.success(
            data={"configs": configs, "total": len(configs)},
            msg=f"Found {len(configs)} crew configs in workspace",
        )
    except Exception as e:
        logger.error(f"Error listing crew configs: {e}")
        return ApiResponse.error(code=500, msg=f"Internal server error: {e!s}")


@router.get("/configs/{filename}", response_model=ApiResponse)
async def get_crew_config_detail(filename: str, workspace: str) -> ApiResponse:
    """
    获取 workspace crew_configs 目录下指定配置文件的内容

    Args:
        filename: 配置文件名（不含路径）
        workspace: 工作空间路径
    """
    try:
        crew_service = get_crew_service()
        result = crew_service.get_crew_config_content(workspace, filename)
        return ApiResponse.success(data=result, msg="Config content retrieved")
    except FileNotFoundError as e:
        return ApiResponse.error(code=404, msg=str(e))
    except ValueError as e:
        return ApiResponse.error(code=400, msg=str(e))
    except Exception as e:
        logger.error(f"Error getting crew config {filename}: {e}")
        return ApiResponse.error(code=500, msg=f"Internal server error: {e!s}")


class CrewConfigSaveRequest(BaseModel):
    """保存编排配置文件的请求模型"""
    workspace: str
    filename: str
    content: str

    model_config = {"from_attributes": True}


@router.put("/configs/{filename}", response_model=ApiResponse)
async def save_crew_config(filename: str, request: CrewConfigSaveRequest) -> ApiResponse:
    """
    保存/更新 workspace crew_configs 目录下的配置文件

    Args:
        filename: 配置文件名
        request: 保存请求（含 workspace, content）
    """
    try:
        crew_service = get_crew_service()
        result = crew_service.save_crew_config(
            workspace=request.workspace,
            filename=filename,
            content=request.content,
        )
        return ApiResponse.success(data=result, msg="Config saved successfully")
    except ValueError as e:
        return ApiResponse.error(code=400, msg=str(e))
    except Exception as e:
        logger.error(f"Error saving crew config {filename}: {e}")
        return ApiResponse.error(code=500, msg=f"Internal server error: {e!s}")
    """
    获取 workspace crew_configs 目录下指定配置文件的内容

    Args:
        filename: 配置文件名（不含路径）
        workspace: 工作空间路径
    """
    try:
        crew_service = get_crew_service()
        result = crew_service.get_crew_config_content(workspace, filename)
        return ApiResponse.success(data=result, msg="Config content retrieved")
    except FileNotFoundError as e:
        return ApiResponse.error(code=404, msg=str(e))
    except ValueError as e:
        return ApiResponse.error(code=400, msg=str(e))
    except Exception as e:
        logger.error(f"Error getting crew config {filename}: {e}")
        return ApiResponse.error(code=500, msg=f"Internal server error: {e!s}")


@router.get("/{execution_id}", response_model=ApiResponse)
async def get_crew_execution(execution_id: str) -> ApiResponse:
    """获取编排执行详情"""
    try:
        crew_service = get_crew_service()
        record = await crew_service.get_execution(execution_id)

        if not record:
            return ApiResponse.error(
                code=404,
                msg=f"Execution '{execution_id}' not found",
            )

        return ApiResponse.success(
            data=record,
            msg="Execution retrieved successfully",
        )
    except Exception as e:
        logger.error(f"Error getting crew execution {execution_id}: {e}")
        return ApiResponse.error(code=500, msg=f"Internal server error: {e!s}")


@router.post("/{execution_id}/abort", response_model=ApiResponse)
async def abort_crew_execution(execution_id: str) -> ApiResponse:
    """中止编排执行"""
    try:
        crew_service = get_crew_service()
        success = await crew_service.abort_execution(execution_id)

        if not success:
            return ApiResponse.error(
                code=404,
                msg=f"Execution '{execution_id}' not found",
            )

        return ApiResponse.success(
            data={"execution_id": execution_id},
            msg="Execution aborted successfully",
        )
    except Exception as e:
        logger.error(f"Error aborting crew execution {execution_id}: {e}")
        return ApiResponse.error(code=500, msg=f"Internal server error: {e!s}")


@router.delete("/{execution_id}", response_model=ApiResponse)
async def delete_crew_execution(execution_id: str) -> ApiResponse:
    """删除编排执行记录"""
    try:
        crew_service = get_crew_service()
        success = await crew_service.delete_execution(execution_id)
        if not success:
            return ApiResponse.error(
                code=404,
                msg=f"Execution '{execution_id}' not found",
            )
        return ApiResponse.success(
            data={"execution_id": execution_id},
            msg="Execution deleted successfully",
        )
    except Exception as e:
        logger.error(f"Error deleting crew execution {execution_id}: {e}")
        return ApiResponse.error(code=500, msg=f"Internal server error: {e!s}")
