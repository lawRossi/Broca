from datetime import datetime

from pydantic import ConfigDict
from sqlmodel import Field, SQLModel


class UserAuth(SQLModel, table=True):
    """用户认证信息表（用户名+密码，取代 Supabase Auth）"""

    model_config = ConfigDict(from_attributes=True, title="User Auth")  # type: ignore[assignment]

    __tablename__ = "user_auth"

    id: str = Field(max_length=36, primary_key=True, index=True, description="Unique user identifier (UUID)")
    username: str = Field(max_length=50, unique=True, nullable=False, description="Username for login")
    hashed_password: str = Field(max_length=255, nullable=False, description="Bcrypt hashed password")
    created_at: datetime = Field(default_factory=datetime.utcnow, nullable=False, description="Account creation time")
    last_login_at: datetime | None = Field(default=None, nullable=True, description="Last login time")
