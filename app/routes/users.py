"""
Account and user management: change your own password; admins manage all users.
"""
from fastapi import APIRouter, Depends, HTTPException, Request, status

from app.config import DB_PATH, SESSION_COOKIE
from app.core.secrets import decrypt_secret, encrypt_secret
from app.db import (
    create_user,
    delete_session,
    delete_user,
    delete_user_sessions,
    disable_totp,
    enable_totp,
    get_user_by_id,
    list_user_sessions,
    list_users,
    set_pending_totp,
    set_recovery_codes,
    set_user_role,
    update_user_password,
)
from app.models import (
    APIResponse,
    PasswordChangeRequest,
    PasswordConfirmRequest,
    PasswordResetRequest,
    TwoFactorCodeRequest,
    TwoFactorDisableRequest,
    UserCreateRequest,
    UserUpdateRequest,
)
from app.routes.auth import public_user
from app.services import totp
from app.services.activity import log_activity
from app.services.auth import (
    hash_password,
    require_admin,
    require_user,
    session_public_id,
    token_hash,
    verify_password,
)
from app.services.password_policy import enforce_password_policy

router = APIRouter(prefix="/users")


def _get_other_user(user_id: int, current: dict) -> dict:
    """Look up the target of an admin action; admins manage themselves via /users/me."""
    target = get_user_by_id(DB_PATH, user_id)
    if not target:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="User not found")
    if target["id"] == current["id"]:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="You can't do that to your own account")
    return target


@router.post("/me/password", response_model=APIResponse)
async def change_own_password(body: PasswordChangeRequest, request: Request, user: dict = Depends(require_user)):
    """Change your own password. Signs out your other sessions."""
    _confirm_password(user, body.current_password)
    if body.new_password == body.current_password:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="New password must be different")
    enforce_password_policy(body.new_password, user["username"])
    update_user_password(DB_PATH, user["id"], hash_password(body.new_password))
    delete_user_sessions(DB_PATH, user["id"], keep_token_hash=token_hash(request.cookies[SESSION_COOKIE]))
    log_activity("user_password_changed", {"username": user["username"]})
    return APIResponse(success=True, message="Password changed. Your other sessions were signed out.")


SSO_MANAGED = "This account signs in with single sign-on; its password and two-factor are managed there"


def _confirm_password(user: dict, password: str) -> dict:
    """Re-check the password before sensitive account changes; returns the full user row."""
    full = get_user_by_id(DB_PATH, user["id"])
    if full.get("oidc_subject"):
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=SSO_MANAGED)
    if not verify_password(password, full["password_hash"]):
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Current password is incorrect")
    return full


# ── two-factor authentication ───────────────────────────────────────────

@router.get("/me/2fa", response_model=APIResponse)
async def my_two_factor(user: dict = Depends(require_user)):
    full = get_user_by_id(DB_PATH, user["id"])
    return APIResponse(success=True, message="Two-factor status", data={
        "enabled": bool(full.get("totp_enabled")),
        "recovery_codes_left": totp.recovery_codes_left(full),
    })


@router.post("/me/2fa/setup", response_model=APIResponse)
async def start_two_factor(body: PasswordConfirmRequest, user: dict = Depends(require_user)):
    """Start enrolling an authenticator app: returns a new secret (shown as a QR code).
    Nothing changes for sign-in until /me/2fa/enable confirms a code from the app."""
    full = _confirm_password(user, body.current_password)
    if full.get("totp_enabled"):
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Two-factor authentication is already on")
    secret = totp.new_secret()
    set_pending_totp(DB_PATH, user["id"], encrypt_secret(secret))
    return APIResponse(success=True, message="Scan the code with your authenticator app", data={
        "secret": secret,
        "otpauth_uri": totp.provisioning_uri(secret, user["username"]),
    })


@router.post("/me/2fa/enable", response_model=APIResponse)
async def enable_two_factor(body: TwoFactorCodeRequest, request: Request, user: dict = Depends(require_user)):
    """Confirm enrolment with a code from the app. Returns one-time recovery codes (shown once)."""
    full = get_user_by_id(DB_PATH, user["id"])
    if full.get("totp_enabled"):
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Two-factor authentication is already on")
    if not full.get("totp_secret"):
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Start the setup first")
    step = totp.matching_step(decrypt_secret(full["totp_secret"]), body.code)
    if step is None:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST,
                            detail="That code didn't match. Check the time on your phone and try the next code.")
    codes = totp.new_recovery_codes()
    enable_totp(DB_PATH, user["id"], step, [totp.hash_recovery_code(c) for c in codes])
    delete_user_sessions(DB_PATH, user["id"], keep_token_hash=token_hash(request.cookies[SESSION_COOKIE]))
    log_activity("user_2fa_enabled", {"username": user["username"]})
    return APIResponse(success=True, message="Two-factor authentication is on", data={"recovery_codes": codes})


@router.post("/me/2fa/recovery-codes", response_model=APIResponse)
async def regenerate_recovery_codes(body: PasswordConfirmRequest, user: dict = Depends(require_user)):
    """Replace your recovery codes (the old ones stop working)."""
    full = _confirm_password(user, body.current_password)
    if not full.get("totp_enabled"):
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Two-factor authentication is off")
    codes = totp.new_recovery_codes()
    set_recovery_codes(DB_PATH, user["id"], [totp.hash_recovery_code(c) for c in codes])
    log_activity("user_2fa_recovery_codes_regenerated", {"username": user["username"]})
    return APIResponse(success=True, message="New recovery codes", data={"recovery_codes": codes})


@router.post("/me/2fa/disable", response_model=APIResponse)
async def disable_two_factor(body: TwoFactorDisableRequest, user: dict = Depends(require_user)):
    full = _confirm_password(user, body.current_password)
    if not full.get("totp_enabled"):
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Two-factor authentication is off")
    if totp.check_second_factor(full, body.code) is None:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Invalid authentication code")
    disable_totp(DB_PATH, user["id"])
    log_activity("user_2fa_disabled", {"username": user["username"]})
    return APIResponse(success=True, message="Two-factor authentication is off")


def _public_session(row: dict, current_id: str) -> dict:
    sid = session_public_id(row["token_hash"])
    return {
        "id": sid,
        "current": sid == current_id,
        "created_at": row["created_at"],
        "last_seen_at": row.get("last_seen_at") or row["created_at"],
        "expires_at": row["expires_at"],
        "ip": row.get("ip"),
        "user_agent": row.get("user_agent") or "",
    }


@router.get("/me/sessions", response_model=APIResponse)
async def my_sessions(user: dict = Depends(require_user)):
    """Your active sessions (browsers/devices signed in to your account)."""
    rows = list_user_sessions(DB_PATH, user["id"])
    return APIResponse(success=True, message=f"{len(rows)} active sessions",
                       data={"sessions": [_public_session(r, user["session_id"]) for r in rows]})


@router.delete("/me/sessions/{session_id}", response_model=APIResponse)
async def end_my_session(session_id: str, user: dict = Depends(require_user)):
    """Sign out one of your sessions."""
    for row in list_user_sessions(DB_PATH, user["id"]):
        if session_public_id(row["token_hash"]) == session_id:
            delete_session(DB_PATH, row["token_hash"])
            log_activity("session_revoked", {"username": user["username"], "session": session_id})
            return APIResponse(success=True, message="Session signed out")
    raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Session not found")


@router.post("/me/sessions/revoke-others", response_model=APIResponse)
async def end_my_other_sessions(request: Request, user: dict = Depends(require_user)):
    """Sign out everywhere except this browser."""
    delete_user_sessions(DB_PATH, user["id"], keep_token_hash=token_hash(request.cookies[SESSION_COOKIE]))
    log_activity("sessions_revoked", {"username": user["username"], "scope": "others"})
    return APIResponse(success=True, message="Signed out of all other sessions")


@router.get("", response_model=APIResponse)
async def get_users(admin: dict = Depends(require_admin)):
    users = [public_user(u) for u in list_users(DB_PATH)]
    return APIResponse(success=True, message=f"Retrieved {len(users)} users", data={"users": users})


@router.post("", response_model=APIResponse)
async def add_user(body: UserCreateRequest, admin: dict = Depends(require_admin)):
    enforce_password_policy(body.password, body.username)
    user = create_user(DB_PATH, body.username, hash_password(body.password), body.role)
    if user is None:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=f"Username '{body.username}' is taken")
    log_activity("user_created", {"username": user["username"], "role": body.role, "by": admin["username"]})
    return APIResponse(success=True, message=f"User '{user['username']}' created", data={"user": public_user(user)})


@router.patch("/{user_id}", response_model=APIResponse)
async def update_user(user_id: int, body: UserUpdateRequest, admin: dict = Depends(require_admin)):
    target = _get_other_user(user_id, admin)
    if not set_user_role(DB_PATH, target["id"], body.role):
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="There must be at least one administrator")
    log_activity("user_updated", {"username": target["username"], "role": body.role, "by": admin["username"]})
    return APIResponse(
        success=True,
        message=f"'{target['username']}' is now {'an' if body.role in ('admin', 'operator') else 'a'} {body.role}",
        data={"user": public_user({**target, "role": body.role, "is_admin": body.role == "admin"})},
    )


@router.post("/{user_id}/password", response_model=APIResponse)
async def reset_user_password(user_id: int, body: PasswordResetRequest, admin: dict = Depends(require_admin)):
    """Set a new password for another user and sign them out everywhere."""
    target = _get_other_user(user_id, admin)
    if target.get("oidc_subject"):
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=SSO_MANAGED)
    enforce_password_policy(body.new_password, target["username"])
    update_user_password(DB_PATH, target["id"], hash_password(body.new_password))
    delete_user_sessions(DB_PATH, target["id"])
    log_activity("user_password_reset", {"username": target["username"], "by": admin["username"]})
    return APIResponse(success=True, message=f"Password reset for '{target['username']}'")


@router.get("/{user_id}/sessions", response_model=APIResponse)
async def user_sessions(user_id: int, admin: dict = Depends(require_admin)):
    target = get_user_by_id(DB_PATH, user_id)
    if not target:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="User not found")
    rows = list_user_sessions(DB_PATH, user_id)
    return APIResponse(success=True, message=f"{len(rows)} active sessions",
                       data={"sessions": [_public_session(r, admin["session_id"]) for r in rows]})


@router.post("/{user_id}/sessions/revoke", response_model=APIResponse)
async def end_user_sessions(user_id: int, admin: dict = Depends(require_admin)):
    """Sign a user out everywhere (e.g. a lost laptop)."""
    target = _get_other_user(user_id, admin)
    delete_user_sessions(DB_PATH, target["id"])
    log_activity("sessions_revoked", {"username": target["username"], "scope": "all", "by": admin["username"]})
    return APIResponse(success=True, message=f"'{target['username']}' was signed out everywhere")


@router.delete("/{user_id}/2fa", response_model=APIResponse)
async def reset_user_two_factor(user_id: int, admin: dict = Depends(require_admin)):
    """For a user who lost their authenticator and recovery codes: turn 2FA off so they
    can sign in with their password and enrol again. Also signs them out everywhere."""
    target = _get_other_user(user_id, admin)
    disable_totp(DB_PATH, target["id"])
    delete_user_sessions(DB_PATH, target["id"])
    log_activity("user_2fa_reset", {"username": target["username"], "by": admin["username"]})
    return APIResponse(success=True, message=f"Two-factor authentication reset for {target['username']}")


@router.delete("/{user_id}", response_model=APIResponse)
async def remove_user(user_id: int, admin: dict = Depends(require_admin)):
    target = _get_other_user(user_id, admin)
    if not delete_user(DB_PATH, target["id"]):
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="There must be at least one administrator")
    log_activity("user_deleted", {"username": target["username"], "by": admin["username"]})
    return APIResponse(success=True, message=f"User '{target['username']}' deleted")
