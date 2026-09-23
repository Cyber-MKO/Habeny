"""
Login, logout and first-run admin setup. These are the only API routes reachable without a session.
"""
import logging

from fastapi import APIRouter, HTTPException, Request, Response, status

from app.config import DB_PATH, SESSION_COOKIE, SESSION_TTL_HOURS
from app.db import count_users, create_first_user, get_user_by_username, update_user_last_login
from app.models import APIResponse, LoginRequest, SetupRequest
from app.services.activity import log_activity
from app.services.auth import (
    check_credentials,
    end_session,
    hash_password,
    login_limiter,
    session_user,
    start_session,
)
from app.services.password_policy import enforce_password_policy
from app.services.setup_token import check_setup_token, remove_setup_token

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/auth")


def public_user(user: dict) -> dict:
    return {
        "id": user["id"],
        "username": user["username"],
        "role": user.get("role") or ("admin" if user.get("is_admin") else "operator"),
        "is_admin": (user.get("role") == "admin") if user.get("role") else bool(user.get("is_admin")),
        "created_at": user.get("created_at"),
        "last_login_at": user.get("last_login_at"),
    }


def _set_session_cookie(request: Request, response: Response, token: str) -> None:
    response.set_cookie(
        SESSION_COOKIE,
        token,
        max_age=SESSION_TTL_HOURS * 3600,
        httponly=True,
        samesite="strict",
        secure=request.url.scheme == "https",
        path="/",
    )


@router.get("/status", response_model=APIResponse)
async def auth_status(request: Request):
    """Whether first-run setup is needed and who (if anyone) is signed in"""
    user = session_user(request)
    return APIResponse(
        success=True,
        message="Authenticated" if user else "Not authenticated",
        data={
            "setup_required": count_users(DB_PATH) == 0,
            "authenticated": user is not None,
            "user": public_user(user) if user else None,
        },
    )


@router.post("/setup", response_model=APIResponse)
async def setup_admin(body: SetupRequest, request: Request, response: Response):
    """Create the first (admin) account. Only allowed while no account exists, and only
    with the one-time setup token from the server's log / data directory."""
    if count_users(DB_PATH) > 0:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Setup has already been completed")
    client = request.client.host if request.client else "unknown"
    wait = login_limiter.retry_after(client)
    if wait:
        raise HTTPException(status_code=status.HTTP_429_TOO_MANY_REQUESTS,
                            detail="Too many failed attempts. Try again later.", headers={"Retry-After": str(wait)})
    if not check_setup_token(body.setup_token):
        login_limiter.record_failure(client)
        log_activity("auth_setup_token_rejected", {"client": client}, status="error")
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Invalid setup token")
    enforce_password_policy(body.password, body.username)
    user = create_first_user(DB_PATH, body.username, hash_password(body.password))
    if user is None:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Setup has already been completed")
    remove_setup_token()
    _set_session_cookie(request, response, start_session(user["id"], request))
    update_user_last_login(DB_PATH, user["id"])
    log_activity("auth_setup_completed", {"username": user["username"]})
    return APIResponse(success=True, message="Admin account created", data={"user": public_user(user)})


@router.post("/login", response_model=APIResponse)
async def login(body: LoginRequest, request: Request, response: Response):
    client = request.client.host if request.client else "unknown"
    wait = login_limiter.retry_after(client)
    if wait:
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail=f"Too many failed sign-in attempts. Try again in {max(1, wait // 60)} min.",
            headers={"Retry-After": str(wait)},
        )

    user = get_user_by_username(DB_PATH, body.username)
    if not check_credentials(user, body.password):
        login_limiter.record_failure(client)
        log_activity("auth_login_failed", {"username": body.username, "client": client}, status="error")
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid username or password")

    login_limiter.reset(client)
    _set_session_cookie(request, response, start_session(user["id"], request))
    update_user_last_login(DB_PATH, user["id"])
    log_activity("auth_login", {"username": user["username"], "client": client})
    return APIResponse(success=True, message="Signed in", data={"user": public_user(user)})


@router.post("/logout", response_model=APIResponse)
async def logout(request: Request, response: Response):
    token = request.cookies.get(SESSION_COOKIE)
    if token:
        end_session(token)
    response.delete_cookie(SESSION_COOKIE, path="/")
    return APIResponse(success=True, message="Signed out")
