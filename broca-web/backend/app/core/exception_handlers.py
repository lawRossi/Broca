"""Global exception handlers for consistent API error responses.

Registers handlers that catch HTTPException and generic Exception,
converting them all to the standard ApiResponse format.
"""

from __future__ import annotations

from fastapi import HTTPException, Request
from fastapi.responses import JSONResponse
from loguru import logger

from app.schemas.schemas import ApiResponse


async def http_exception_handler(request: Request, exc: HTTPException) -> JSONResponse:
    """Convert HTTPException to unified ApiResponse JSON format.

    Handles all ``raise HTTPException(status_code, detail=...)`` calls across API modules.
    Returns a JSON body matching ApiResponse schema so the frontend can parse it uniformly.
    """
    status_code = exc.status_code
    detail = exc.detail
    if isinstance(detail, dict):
        msg = detail.get("msg", str(detail))
    elif isinstance(detail, list):
        msg = "; ".join(str(e) for e in detail)
    else:
        msg = str(detail)

    response = ApiResponse.error(code=status_code, msg=msg)
    return JSONResponse(
        status_code=status_code,
        content=response.model_dump(),
    )


async def general_exception_handler(request: Request, exc: Exception) -> JSONResponse:
    """Catch-all handler for unhandled exceptions.

    Logs the full stack trace and returns a generic 500 error in ApiResponse format.
    This is the last resort — all known exception types should be handled before this.
    """
    logger.exception(f"Unhandled exception on {request.method} {request.url.path}")
    response = ApiResponse.error(code=500, msg="服务器内部错误，请稍后重试")
    return JSONResponse(
        status_code=500,
        content=response.model_dump(),
    )
