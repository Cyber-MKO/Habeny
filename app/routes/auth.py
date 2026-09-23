"""
Login, logout and first-run admin setup. These are the only API routes reachable without a session.
"""
import hmac
import logging
from urllib.parse import quote

from fastapi import APIRouter, HTTPException, Request, Response, status
from fastapi.responses import RedirectResponse

from app.config import DB_PATH, SESSION_COOKIE, SESSION_TTL_HOURS
from app.db import (
    count_users,
    create_first_user,
    create_sso_user,
    get_user_by_id,
    get_user_by_oidc_subject,
    get_user_by_username,
    set_user_role,
    update_user_last_login,
)
from app.models import APIResponse, LoginRequest, SetupRequest, TwoFactorLoginRequest
from app.services import oidc
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
from app.services.totp import challenges, check_second_factor, recovery_codes_left

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/auth")


def public_user(user: dict) -> dict:
    return {
        "id": user["id"],
        "username": user["username"],
        "role": user.get("role") or ("admin" if user.get("is_admin") else "operator"),
        "is_admin": (user.get("role") == "admin") if user.get("role") else bool(user.get("is_admin")),
        "totp_enabled": bool(user.get("totp_enabled")),
        "sso": bool(user.get("oidc_subject")),
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
            "sso": {"enabled": True, "label": sso.label} if (sso := oidc.settings()) else {"enabled": False},
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


def _check_rate_limit(client: str) -> None:
    wait = login_limiter.retry_after(client)
    if wait:
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail=f"Too many failed sign-in attempts. Try again in {max(1, wait // 60)} min.",
            headers={"Retry-After": str(wait)},
        )


def _complete_login(user: dict, request: Request, response: Response, client: str, **details) -> APIResponse:
    login_limiter.reset(client)
    _set_session_cookie(request, response, start_session(user["id"], request))
    update_user_last_login(DB_PATH, user["id"])
    log_activity("auth_login", {"username": user["username"], "client": client, **details})
    return APIResponse(success=True, message="Signed in", data={"user": public_user(user)})


@router.post("/login", response_model=APIResponse)
async def login(body: LoginRequest, request: Request, response: Response):
    client = request.client.host if request.client else "unknown"
    _check_rate_limit(client)

    user = get_user_by_username(DB_PATH, body.username)
    if not check_credentials(user, body.password):
        login_limiter.record_failure(client)
        log_activity("auth_login_failed", {"username": body.username, "client": client}, status="error")
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid username or password")

    if user.get("totp_enabled"):
        # Password is right; no session until the second factor is too
        return APIResponse(success=True, message="Enter your authentication code",
                           data={"mfa_required": True, "mfa_token": challenges.create(user["id"])})
    return _complete_login(user, request, response, client)


@router.post("/login/2fa", response_model=APIResponse)
async def login_second_factor(body: TwoFactorLoginRequest, request: Request, response: Response):
    client = request.client.host if request.client else "unknown"
    _check_rate_limit(client)
    user_id = challenges.user_for(body.mfa_token)
    user = get_user_by_id(DB_PATH, user_id) if user_id is not None else None
    if user is None:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED,
                            detail="Sign-in expired. Enter your username and password again.")

    method = check_second_factor(user, body.code)
    if method is None:
        login_limiter.record_failure(client)
        challenges.failed(body.mfa_token)
        log_activity("auth_2fa_failed", {"username": user["username"], "client": client}, status="error")
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid authentication code")

    challenges.finish(body.mfa_token)
    details = {"second_factor": method}
    if method == "recovery":
        details["recovery_codes_left"] = recovery_codes_left(get_user_by_id(DB_PATH, user["id"]))
    return _complete_login(user, request, response, client, **details)


@router.post("/logout", response_model=APIResponse)
async def logout(request: Request, response: Response):
    token = request.cookies.get(SESSION_COOKIE)
    if token:
        end_session(token)
    response.delete_cookie(SESSION_COOKIE, path="/")
    return APIResponse(success=True, message="Signed out")


# ── single sign-on (OpenID Connect) ─────────────────────────────────────

OIDC_STATE_COOKIE = "habeny_oidc_state"


def _sso_settings() -> oidc.Settings:
    cfg = oidc.settings()
    if cfg is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Single sign-on is not configured")
    return cfg


def _sso_failed(message: str, client: str) -> RedirectResponse:
    log_activity("auth_sso_failed", {"client": client, "error": message[:300]}, status="error")
    response = RedirectResponse(f"/?sso_error={quote(message[:300])}", status_code=status.HTTP_303_SEE_OTHER)
    response.delete_cookie(OIDC_STATE_COOKIE, path="/")
    return response


@router.get("/oidc/login")
def sso_login(request: Request):
    """Send the browser to the identity provider."""
    cfg = _sso_settings()
    client = request.client.host if request.client else "unknown"
    # The browser-facing URL includes /api (stripped by the API prefix middleware)
    redirect_uri = cfg.redirect_uri or f"{request.url.scheme}://{request.url.netloc}/api/auth/oidc/callback"
    flow = oidc.flows.create(redirect_uri)
    try:
        url = oidc.authorization_url(cfg, flow)
    except oidc.OIDCError as e:
        return _sso_failed(str(e), client)
    response = RedirectResponse(url, status_code=status.HTTP_303_SEE_OTHER)
    # Ties the callback to this browser (stops login CSRF). Lax: it must survive the
    # cross-site redirect back from the identity provider.
    response.set_cookie(OIDC_STATE_COOKIE, flow["state"], max_age=oidc.FLOW_TTL, httponly=True,
                        samesite="lax", secure=request.url.scheme == "https", path="/")
    return response


def _sso_account(cfg: oidc.Settings, claims: dict) -> dict:
    """Find or create the Habeny account for a verified identity; keeps the role in sync
    with IdP groups when group mapping is configured."""
    subject = oidc.subject_key(cfg, claims)
    group_role = oidc.role_from(cfg, claims)
    user = get_user_by_oidc_subject(DB_PATH, subject)
    if user is None:
        username = oidc.username_from(cfg, claims)
        user = create_sso_user(DB_PATH, username, subject, group_role or cfg.default_role)
        if user is None:
            # Never link to an existing account by name: an IdP user called "admin"
            # must not become the local admin.
            raise oidc.OIDCError(f"A Habeny account named '{username}' already exists. "
                                 "Ask an administrator to rename or remove it.")
        log_activity("user_created", {"username": username, "role": user["role"], "by": "sso"})
    elif group_role and group_role != user["role"] and set_user_role(DB_PATH, user["id"], group_role):
        log_activity("user_updated", {"username": user["username"], "role": group_role, "by": "sso groups"})
        user = get_user_by_id(DB_PATH, user["id"])
    return user


@router.get("/oidc/callback")
def sso_callback(request: Request, state: str = "", code: str = "", error: str = "",
                 error_description: str = ""):
    """The identity provider sends the browser back here with an authorization code."""
    cfg = _sso_settings()
    client = request.client.host if request.client else "unknown"
    cookie = request.cookies.get(OIDC_STATE_COOKIE, "")
    flow = oidc.flows.pop(state) if state else None
    if not flow or not cookie or not hmac.compare_digest(cookie, state):
        return _sso_failed("Sign-in expired or was started in another browser. Try again.", client)
    if error:  # only shown for a sign-in this browser started, so a crafted link can't inject text
        return _sso_failed(f"Sign-in was refused by the identity provider: {error_description or error}", client)
    if not code:
        return _sso_failed("The identity provider didn't return an authorization code.", client)
    try:
        claims = oidc.exchange_code(cfg, flow, code)
        user = _sso_account(cfg, claims)
    except oidc.OIDCError as e:
        return _sso_failed(str(e), client)

    response = RedirectResponse("/", status_code=status.HTTP_303_SEE_OTHER)
    response.delete_cookie(OIDC_STATE_COOKIE, path="/")
    _set_session_cookie(request, response, start_session(user["id"], request))
    update_user_last_login(DB_PATH, user["id"])
    log_activity("auth_login", {"username": user["username"], "client": client, "method": "sso"})
    return response
