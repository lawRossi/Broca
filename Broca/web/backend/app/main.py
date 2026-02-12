import logging

from fastapi import Depends, FastAPI, HTTPException, Request
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from app.api import api_router
from app.utils.supabase_utils import get_supbase

logger = logging.getLogger(__name__)
WHITE_LIST = {"/api/user/login", "/docs", "/openapi.json", "/api/health"}
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
def setup() -> None:
    logger.info("Starting up")
    global supabase
    app.state.supabase = supabase


app.include_router(api_router, prefix="/api")
