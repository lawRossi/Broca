"""Unit tests for app.core.exception_handlers module.

Tests HTTPException and generic Exception handling into ApiResponse format.
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

from fastapi import HTTPException
import pytest

from app.core.exception_handlers import general_exception_handler, http_exception_handler


class TestHttpExceptionHandler:
    """Test http_exception_handler."""

    @pytest.mark.asyncio
    async def test_str_detail(self):
        """String detail should be used directly."""
        request = MagicMock()
        exc = HTTPException(status_code=404, detail="Not found")
        response = await http_exception_handler(request, exc)
        assert response.status_code == 404
        body = response.body.decode()
        assert '"code":404' in body
        assert '"msg":"Not found"' in body

    @pytest.mark.asyncio
    async def test_dict_detail(self):
        """Dict detail should extract msg field."""
        request = MagicMock()
        exc = HTTPException(status_code=400, detail={"msg": "参数错误", "field": "username"})
        response = await http_exception_handler(request, exc)
        assert response.status_code == 400
        body = response.body.decode()
        assert '"msg":"参数错误"' in body

    @pytest.mark.asyncio
    async def test_list_detail(self):
        """List detail should join items with semicolons."""
        request = MagicMock()
        exc = HTTPException(status_code=422, detail=["Field required", "Invalid type"])
        response = await http_exception_handler(request, exc)
        assert response.status_code == 422
        body = response.body.decode()
        assert '"msg":"Field required; Invalid type"' in body

    @pytest.mark.asyncio
    async def test_empty_list_detail(self):
        """Empty list should produce empty msg."""
        request = MagicMock()
        exc = HTTPException(status_code=400, detail=[])
        response = await http_exception_handler(request, exc)
        assert response.status_code == 400
        body = response.body.decode()
        assert '"msg":""' in body

    @pytest.mark.asyncio
    async def test_empty_dict_detail(self):
        """Empty dict should produce str(dict) msg."""
        request = MagicMock()
        exc = HTTPException(status_code=500, detail={})
        response = await http_exception_handler(request, exc)
        assert response.status_code == 500
        body = response.body.decode()
        assert '"msg":"{}"' in body

    @pytest.mark.asyncio
    async def test_401_unauthorized(self):
        """401 should return proper format."""
        request = MagicMock()
        exc = HTTPException(status_code=401, detail="Unauthorized")
        response = await http_exception_handler(request, exc)
        assert response.status_code == 401
        body = response.body.decode()
        assert '"code":401' in body
        assert '"msg":"Unauthorized"' in body

    @pytest.mark.asyncio
    async def test_403_forbidden(self):
        """403 should return proper format."""
        request = MagicMock()
        exc = HTTPException(status_code=403, detail="Forbidden")
        response = await http_exception_handler(request, exc)
        assert response.status_code == 403
        body = response.body.decode()
        assert '"code":403' in body

    @pytest.mark.asyncio
    async def test_api_response_format(self):
        """Response should contain code, msg, data fields."""
        request = MagicMock()
        exc = HTTPException(status_code=400, detail="Bad request")
        response = await http_exception_handler(request, exc)
        body = response.body.decode()
        assert '"code"' in body
        assert '"msg"' in body
        assert '"data"' in body


class TestGeneralExceptionHandler:
    """Test general_exception_handler."""

    @pytest.mark.asyncio
    async def test_generic_exception(self):
        """Generic exception should return 500 with ApiResponse format."""
        request = MagicMock()
        request.method = "GET"
        request.url.path = "/api/test"
        exc = Exception("Something went wrong")
        response = await general_exception_handler(request, exc)
        assert response.status_code == 500
        body = response.body.decode()
        assert '"code":500' in body
        assert '"msg":"服务器内部错误，请稍后重试"' in body
        assert '"data":null' in body or '"data": None' in body

    @pytest.mark.asyncio
    async def test_value_error(self):
        """ValueError should also return 500."""
        request = MagicMock()
        request.method = "POST"
        request.url.path = "/api/data"
        exc = ValueError("Invalid value")
        response = await general_exception_handler(request, exc)
        assert response.status_code == 500

    @pytest.mark.asyncio
    async def test_runtime_error(self):
        """RuntimeError should also return 500."""
        request = MagicMock()
        request.method = "DELETE"
        request.url.path = "/api/item"
        exc = RuntimeError("Operation failed")
        response = await general_exception_handler(request, exc)
        assert response.status_code == 500
