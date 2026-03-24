from fastapi import APIRouter

from .files import router as files_router
from .session import router as session_router
from .user import router as user_router

api_router = APIRouter()

api_router.include_router(user_router, prefix="/user", tags=["users"])
api_router.include_router(session_router, prefix="/session", tags=["sessions"])
api_router.include_router(files_router, tags=["files"])
