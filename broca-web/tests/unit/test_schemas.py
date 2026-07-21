"""Unit tests for app.schemas.schemas module.

Tests ApiResponse model and request/response schemas.
"""

from __future__ import annotations

from pydantic import ValidationError
import pytest

# Import after conftest patches
from app.schemas.schemas import ApiResponse, CreateSessionRequest, UpdateSessionRequest


class TestApiResponse:
    """Test the ApiResponse Pydantic model."""

    def test_success_defaults(self):
        """success() should return code=200 with empty message."""
        resp = ApiResponse.success()
        assert resp.code == 200
        assert resp.msg == ""
        assert resp.data is None

    def test_success_with_data_and_msg(self):
        """success() should include data and message."""
        resp = ApiResponse.success(data={"key": "value"}, msg="操作成功")
        assert resp.code == 200
        assert resp.msg == "操作成功"
        assert resp.data == {"key": "value"}

    def test_success_with_list_data(self):
        """success() should handle list data."""
        resp = ApiResponse.success(data=[1, 2, 3], msg="列表获取成功")
        assert resp.code == 200
        assert resp.data == [1, 2, 3]

    def test_success_with_none_data(self):
        """success() with data=None should work."""
        resp = ApiResponse.success(data=None, msg="no data")
        assert resp.code == 200
        assert resp.data is None

    def test_error_defaults(self):
        """error() should return code=500 with default message."""
        resp = ApiResponse.error()
        assert resp.code == 500
        assert resp.msg == "服务器错误"
        assert resp.data is None

    def test_error_with_custom_code_and_msg(self):
        """error() should allow custom status code and message."""
        resp = ApiResponse.error(code=404, msg="资源未找到")
        assert resp.code == 404
        assert resp.msg == "资源未找到"
        assert resp.data is None

    def test_error_400(self):
        """error() with 400 should work."""
        resp = ApiResponse.error(code=400, msg="参数错误")
        assert resp.code == 400
        assert resp.msg == "参数错误"

    def test_error_401(self):
        """error() with 401 should work."""
        resp = ApiResponse.error(code=401, msg="未授权")
        assert resp.code == 401
        assert resp.msg == "未授权"

    def test_error_403(self):
        """error() with 403 should work."""
        resp = ApiResponse.error(code=403, msg="禁止访问")
        assert resp.code == 403

    def test_model_serialization(self):
        """ApiResponse should serialize to dict correctly."""
        resp = ApiResponse.success(data={"id": 1}, msg="ok")
        d = resp.model_dump()
        assert d["code"] == 200
        assert d["msg"] == "ok"
        assert d["data"] == {"id": 1}

    def test_model_deserialization(self):
        """ApiResponse should deserialize from dict correctly."""
        data = {"code": 200, "msg": "success", "data": {"name": "test"}}
        resp = ApiResponse(**data)
        assert resp.code == 200
        assert resp.msg == "success"
        assert resp.data == {"name": "test"}

    def test_invalid_code_type(self):
        """code field should be int."""
        with pytest.raises(ValidationError):
            ApiResponse(code="not-an-int")  # type: ignore[arg-type]


class TestCreateSessionRequest:
    """Test the CreateSessionRequest model."""

    def test_default_values(self):
        """All fields should have sensible defaults."""
        req = CreateSessionRequest()
        assert req.description is None
        assert req.workspace is None
        assert req.provider is None
        assert req.model is None
        assert req.category == "normal"

    def test_custom_values(self):
        """Custom values should be set correctly."""
        req = CreateSessionRequest(
            description="test session",
            workspace="/tmp/workspace",
            provider="openrouter",
            model="gpt-4",
            category="agent-orchestration",
        )
        assert req.description == "test session"
        assert req.workspace == "/tmp/workspace"
        assert req.provider == "openrouter"
        assert req.model == "gpt-4"
        assert req.category == "agent-orchestration"

    def test_partial_values(self):
        """Partial values should work."""
        req = CreateSessionRequest(description="only description")
        assert req.description == "only description"
        assert req.workspace is None
        assert req.category == "normal"


class TestUpdateSessionRequest:
    """Test the UpdateSessionRequest model."""

    def test_default_values(self):
        """All fields should be None by default."""
        req = UpdateSessionRequest()
        assert req.description is None

    def test_set_description(self):
        """Description should be settable."""
        req = UpdateSessionRequest(description="updated description")
        assert req.description == "updated description"
