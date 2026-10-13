"""Skills API

提供可用技能列表接口，用于前端 Agent 配置编辑时动态获取技能选项。
"""

from broca.skill.skill_manager import SkillManager
from fastapi import APIRouter
from loguru import logger

from app.schemas.schemas import ApiResponse

router = APIRouter()


@router.get("", response_model=ApiResponse)
async def get_available_skills() -> ApiResponse:
    """获取所有可用的内置技能列表"""
    try:
        skill_manager = SkillManager()
        skill_names = sorted(skill_manager.skills.keys())
        return ApiResponse.success(
            {"skills": skill_names},
            msg="Available skills retrieved successfully",
        )
    except Exception as e:
        logger.exception("Error getting available skills")
        return ApiResponse.error(500, f"Failed to get available skills: {e!s}")
