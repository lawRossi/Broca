import logging
import os
from datetime import datetime

from fastapi import Depends, FastAPI, HTTPException, Request
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from app.api import api_router
from app.core.socketio_runtime import SocketIOServerConfig, SocketIOServerRuntime
from app.utils.supabase_utils import get_supbase

logger = logging.getLogger(__name__)
WHITE_LIST = {
    "/api/user/login",
    "/docs",
    "/openapi.json",
    "/api/health",
    "/api/files",
    "/api/files/info",
    "/api/files/preview",
}
security = HTTPBearer(auto_error=False)
supabase = get_supbase()


def verify_token(req: Request, cred: HTTPAuthorizationCredentials = Depends(security)) -> None:
    if req.url.path in WHITE_LIST:
        return
    if not cred:
        raise HTTPException(401, "Unauthorized")
    global supabase
    if supabase.auth.is_token_expired(cred.credentials):
        logger.error("Token expired")
        raise HTTPException(401, "Unauthorized")
    payload = supabase.auth.decode_supabase_token(cred.credentials)
    req.state.user = payload.get("user_metadata")
    req.state.user_id = payload.get("sub")


app = FastAPI(dependencies=[Depends(verify_token)], title="Simple Backend")


@app.on_event("startup")
async def setup() -> None:
    logger.info("Starting up")
    global supabase
    app.state.supabase = supabase

    # Start Broca SocketIO server alongside FastAPI (optional)
    enabled = os.getenv("BROCA_SOCKETIO_ENABLED", "true").lower() == "true"
    host = os.getenv("BROCA_SOCKETIO_HOST", "0.0.0.0")
    port = int(os.getenv("BROCA_SOCKETIO_PORT", "6868"))
    cors = os.getenv("BROCA_SOCKETIO_CORS", "*")

    app.state.socketio_runtime = SocketIOServerRuntime(
        SocketIOServerConfig(enabled=enabled, host=host, port=port, cors_allowed_origins=cors)
    )
    await app.state.socketio_runtime.start()


@app.on_event("shutdown")
async def shutdown() -> None:
    runtime = getattr(app.state, "socketio_runtime", None)
    if runtime:
        await runtime.stop()


@app.get("/api/health")
async def health_check():
    return {"status": "healthy", "timestamp": datetime.now().isoformat()}


app.include_router(api_router, prefix="/api")
