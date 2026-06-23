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


def _is_local_request(req: Request) -> bool:
    """判断请求是否来自本机"""
    LOCAL_HOSTS = {"127.0.0.1", "::1", "localhost", "0.0.0.0"}
    client_host = req.headers.get("X-Real-IP") or (req.client.host if req.client else None)
    if not client_host:
        return False
    if client_host in LOCAL_HOSTS:
        return True
    # macOS 双栈模式下的 IPv4-mapped IPv6 回环地址
    try:
        from ipaddress import IPv6Address, ip_address
        addr = ip_address(client_host)
        if isinstance(addr, IPv6Address) and addr.ipv4_mapped:
            return addr.ipv4_mapped.is_loopback
        return addr.is_loopback
    except ValueError:
        return False


@router.post("/local-login", response_model=ApiResponse)
async def local_login(req: Request, db: AsyncSession = Depends(get_db)) -> ApiResponse:
    """本机自动登录 — 仅对本机请求生效，无需用户名密码。

    用于 broca-web / broca-vscode 在首次启动时自动获取 token，
    绕过前端的登录页 redirect。
    """
    if not _is_local_request(req):
        raise HTTPException(status_code=403, detail="仅允许本机请求自动登录")

    try:
        # 创建一个固定 ID 的"本地用户" token，不依赖数据库中的用户记录
        LOCAL_USER_ID = "local"
        LOCAL_USERNAME = "Local User"

        token = AuthService.create_access_token(LOCAL_USER_ID, LOCAL_USERNAME)

        return ApiResponse.success(
            {
                "token": token,
                "user_id": LOCAL_USER_ID,
                "username": LOCAL_USERNAME,
            },
            msg="本地自动登录成功",
        )
    except Exception as e:
        logger.exception("Local login error")
        raise HTTPException(status_code=500, detail="本地自动登录失败") from e
