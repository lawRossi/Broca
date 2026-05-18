import logging

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.deps import get_db
from app.schemas.schemas import ApiResponse
from app.services.auth_service import AuthError, AuthService

logger = logging.getLogger(__name__)
router = APIRouter()


class RegisterRequest(BaseModel):
    username: str
    password: str


class LoginRequest(BaseModel):
    username: str
    password: str


class LoginResponse(BaseModel):
    token: str
    user_id: str
    username: str


@router.post("/register", response_model=ApiResponse)
async def register(data: RegisterRequest, db: AsyncSession = Depends(get_db)) -> ApiResponse:
    """用户注册（用户名+密码，无需邮箱）"""
    try:
        service = AuthService(db)
        user = await service.register(data.username, data.password)

        # 注册后直接签发 token
        token = service.create_access_token(user.id, user.username)

        return ApiResponse.success(
            {
                "token": token,
                "user_id": user.id,
                "username": user.username,
            },
            msg="注册成功",
        )
    except AuthError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e
    except Exception as e:
        logger.error(f"Registration error: {e}")
        raise HTTPException(status_code=500, detail="注册失败，请稍后重试") from e


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
        logger.error(f"Login error: {e}")
        raise HTTPException(status_code=500, detail="登录失败，请稍后重试") from e
