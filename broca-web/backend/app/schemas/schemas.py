from typing import Any

from pydantic import BaseModel, ConfigDict


class BaseSchema(BaseModel):
    model_config = ConfigDict(from_attributes=True)


class CreateSessionRequest(BaseModel):
    """创建 Session 的请求模型"""

    description: str | None = None
    workspace: str | None = None
    provider: str | None = None  # LLM provider，如 openrouter、deepseek 等
    model: str | None = None  # LLM model，如 stepfun、nemotron 等
    category: str | None = "normal"  # 会话分类：normal / agent-orchestration


class UpdateSessionRequest(BaseModel):
    """更新 Session 的请求模型"""

    description: str | None = None


class ApiResponse(BaseModel):
    code: int = 200
    msg: str | None = ""
    data: Any | None = None

    @classmethod
    def success(cls, data: Any = None, msg: str = "") -> "ApiResponse":
        return cls(code=200, msg=msg, data=data)

    @classmethod
    def error(cls, code: int = 500, msg: str = "服务器错误") -> "ApiResponse":
        return cls(code=code, msg=msg, data=None)
