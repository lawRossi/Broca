from fastapi import APIRouter

from .files import router as files_router
from .job import router as job_router
from .session import router as session_router
from .session_runner import router as session_runner_router
from .task import router as task_router
from .user import router as user_router
from .config import router as config_router

api_router = APIRouter()

api_router.include_router(user_router, prefix="/user", tags=["users"])
api_router.include_router(session_router, prefix="/session", tags=["sessions"])
api_router.include_router(session_runner_router, prefix="/session", tags=["session-runners"])
api_router.include_router(job_router, prefix="/job", tags=["jobs"])
api_router.include_router(task_router, prefix="/task", tags=["tasks"])
api_router.include_router(files_router, tags=["files"])
api_router.include_router(config_router, prefix="/config", tags=["config"])
