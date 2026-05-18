import logging
import uuid
from datetime import datetime, timedelta, timezone

import bcrypt
from jose import JWTError, jwt
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.models.auth import UserAuth

logger = logging.getLogger(__name__)


class AuthError(Exception):
    """认证相关错误"""
    pass


class AuthService:
    """认证服务：注册、登录、JWT 签发与验证"""

    def __init__(self, db: AsyncSession):
        self.db = db

    # ==================== 密码工具 ====================

    @staticmethod
    def hash_password(password: str) -> str:
        """对密码进行 bcrypt 哈希"""
        return bcrypt.hashpw(password.encode("utf-8"), bcrypt.gensalt()).decode("utf-8")

    @staticmethod
    def verify_password(plain_password: str, hashed_password: str) -> bool:
        """验证密码"""
        return bcrypt.checkpw(plain_password.encode("utf-8"), hashed_password.encode("utf-8"))

    # ==================== JWT 工具 ====================

    @staticmethod
    def create_access_token(user_id: str, username: str) -> str:
        """签发 JWT access token"""
        expire = datetime.now(timezone.utc) + timedelta(minutes=settings.jwt_expire_minutes)
        payload = {
            "sub": user_id,
            "username": username,
            "exp": expire,
            "iat": datetime.now(timezone.utc),
        }
        return jwt.encode(payload, settings.jwt_secret, algorithm=settings.jwt_algorithm)

    @staticmethod
    def decode_access_token(token: str) -> dict:
        """解码并验证 JWT token"""
        try:
            payload = jwt.decode(token, settings.jwt_secret, algorithms=[settings.jwt_algorithm])
            return payload
        except JWTError as e:
            logger.error(f"Failed to decode token: {e}")
            raise AuthError("Invalid or expired token") from e

    @staticmethod
    def is_token_expired(token: str) -> bool:
        """检查 token 是否过期"""
        try:
            payload = jwt.decode(token, settings.jwt_secret, algorithms=[settings.jwt_algorithm])
            exp = payload.get("exp")
            if exp:
                return datetime.fromtimestamp(exp, tz=timezone.utc) < datetime.now(timezone.utc)
            return True
        except JWTError:
            return True

    # ==================== 注册与登录 ====================

    async def register(self, username: str, password: str) -> UserAuth:
        """注册新用户

        Args:
            username: 用户名
            password: 密码

        Returns:
            UserAuth: 创建的用户记录

        Raises:
            AuthError: 用户名已存在或参数无效
        """
        # 参数校验
        if not username or len(username.strip()) < 2:
            raise AuthError("用户名至少需要2个字符")
        if not password or len(password) < 6:
            raise AuthError("密码至少需要6个字符")

        username = username.strip()

        # 检查用户名是否已存在
        existing = await self.db.scalar(select(UserAuth).where(UserAuth.username == username))
        if existing:
            raise AuthError("用户名已被注册")

        # 创建用户
        user_id = str(uuid.uuid4())
        hashed = self.hash_password(password)
        now = datetime.utcnow()

        user = UserAuth(
            id=user_id,
            username=username,
            hashed_password=hashed,
            created_at=now,
        )
        self.db.add(user)
        await self.db.commit()
        await self.db.refresh(user)

        logger.info(f"User registered: {username} ({user_id})")
        return user

    async def login(self, username: str, password: str) -> tuple[UserAuth, str]:
        """用户登录

        Args:
            username: 用户名
            password: 密码

        Returns:
            Tuple[UserAuth, str]: (用户记录, JWT token)

        Raises:
            AuthError: 用户名或密码错误
        """
        username = username.strip()

        user = await self.db.scalar(select(UserAuth).where(UserAuth.username == username))
        if not user:
            raise AuthError("用户名或密码错误")

        if not self.verify_password(password, user.hashed_password):
            raise AuthError("用户名或密码错误")

        # 更新最后登录时间
        user.last_login_at = datetime.utcnow()
        await self.db.commit()

        # 签发 token
        token = self.create_access_token(user.id, user.username)
        logger.info(f"User logged in: {username}")

        return user, token

    async def get_user_by_id(self, user_id: str) -> UserAuth | None:
        """根据 ID 获取用户"""
        return await self.db.scalar(select(UserAuth).where(UserAuth.id == user_id))
