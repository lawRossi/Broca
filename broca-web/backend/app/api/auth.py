import logging

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.deps import get_db
from app.schemas.schemas import ApiResponse
from app.services.auth_service import AuthError, AuthService

logger = logging.getLogger(__name__)
router = APIRouter()


class LoginRequest(BaseModel):
    username: str
    password: str


class LoginResponse(BaseModel):
    token: str
    user_id: str
    username: str


# 注册功能已移除：请在安装时通过 scripts/setup_admin.py 创建账户


@router.post("/login", response_model=ApiResponse)
async def login(data: LoginRequest, db: AsyncSession = Depends(get_db)) -> ApiResponse:
    """用户登录"""
    try:
        service = AuthService(db)
        user, token = await service.login(data.username, data.password)

        return ApiResponse.success(
            {
                "token": token,
                "user_id": user.id,
                "username": user.username,
            },
            msg="登录成功",
        )
    except AuthError as e:
        raise HTTPException(status_code=401, detail=str(e)) from e
    except Exception as e:
        logger.exception("Login error")
        raise HTTPException(status_code=500, detail="登录失败，请稍后重试") from e
