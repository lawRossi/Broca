"""Skills API

提供可用技能列表接口，用于前端 Agent 配置编辑时动态获取技能选项。
"""

from fastapi import APIRouter, Query
from loguru import logger

from broca.skill.skill_manager import SkillManager

from app.schemas.schemas import ApiResponse

router = APIRouter()


@router.get("", response_model=ApiResponse)
async def get_available_skills(
    workspace: str | None = Query(default=None, description="工作空间路径，提供后包含 workspace 级别 skills"),
) -> ApiResponse:
    """获取所有可用的技能列表（全局 + workspace）"""
    try:
        skill_manager = SkillManager()
        if workspace:
            skills = skill_manager.get_skills(workspace, "all")
        else:
            skills = skill_manager.skills
        skill_names = sorted(skills.keys())
        return ApiResponse.success(
            {"skills": skill_names},
            msg="Available skills retrieved successfully",
        )
    except Exception as e:
        logger.exception("Error getting available skills")
        return ApiResponse.error(500, f"Failed to get available skills: {e!s}")
