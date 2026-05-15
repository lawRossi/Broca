import logging
import time

from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.deps import get_db
from app.models.user import UserProfile
from app.schemas.schemas import ApiResponse
from app.services.user_service import UserService

logger = logging.getLogger(__name__)
router = APIRouter()


@router.get("/info", response_model=ApiResponse)
async def get_user_info(req: Request, db: AsyncSession = Depends(get_db)) -> ApiResponse:
    """获取用户信息"""
    try:
        svc = UserService(db)
        user_id = req.state.user_id
        if not user_id:
            raise HTTPException(401, "Unauthorized")

        user_profile = await svc.get_by_id(user_id)
        return ApiResponse.success(user_profile)
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error getting user info: {e}")
        raise HTTPException(500, f"Internal server error: {e!s}") from e


@router.post("/add_info", response_model=ApiResponse)
async def add_user_info(user_data: UserProfile, req: Request, db: AsyncSession = Depends(get_db)) -> ApiResponse:
    """添加用户信息，使用重试机制避免pgbouncer问题"""
    try:
        logger.info("Starting add user info process")
        user_id = req.state.user_id
        if not user_id:
            raise HTTPException(401, "Unauthorized")

        # 设置用户ID
        user_data.id = user_id

        start_time = time.time()

        svc = UserService(db)
        # 使用重试机制创建用户档案
        new_user = await svc.create_user_profile(user_data)

        end_time = time.time()
        duration = end_time - start_time

        logger.info(f"User profile created successfully in {duration:.2f} seconds")
        logger.info(f"Created user: {new_user.id} - {new_user.name}")

        return ApiResponse.success(new_user)

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error creating user profile: {e}")
        raise HTTPException(500, f"Failed to create user profile: {e!s}") from e
