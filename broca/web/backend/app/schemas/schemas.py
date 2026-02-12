from typing import Any

from pydantic import BaseModel, ConfigDict


class BaseSchema(BaseModel):
    model_config = ConfigDict(from_attributes=True)


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
