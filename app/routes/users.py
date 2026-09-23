"""
Account and user management: change your own password; admins manage all users.
"""
from fastapi import APIRouter, Depends, HTTPException, Request, status

from app.config import DB_PATH, SESSION_COOKIE
from app.db import (
    create_user,
    delete_user,
    delete_user_sessions,
    get_user_by_id,
    list_users,
    set_user_admin,
    update_user_password,
)
from app.models import (
    APIResponse,
    PasswordChangeRequest,
    PasswordResetRequest,
    UserCreateRequest,
    UserUpdateRequest,
)
from app.routes.auth import public_user
from app.services.activity import log_activity
from app.services.auth import hash_password, require_admin, require_user, token_hash, verify_password

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
    full = get_user_by_id(DB_PATH, user["id"])
    if not verify_password(body.current_password, full["password_hash"]):
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Current password is incorrect")
    if body.new_password == body.current_password:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="New password must be different")
    update_user_password(DB_PATH, user["id"], hash_password(body.new_password))
    delete_user_sessions(DB_PATH, user["id"], keep_token_hash=token_hash(request.cookies[SESSION_COOKIE]))
    log_activity("user_password_changed", {"username": user["username"]})
    return APIResponse(success=True, message="Password changed. Your other sessions were signed out.")


@router.get("", response_model=APIResponse)
async def get_users(admin: dict = Depends(require_admin)):
    users = [public_user(u) for u in list_users(DB_PATH)]
    return APIResponse(success=True, message=f"Retrieved {len(users)} users", data={"users": users})


@router.post("", response_model=APIResponse)
async def add_user(body: UserCreateRequest, admin: dict = Depends(require_admin)):
    user = create_user(DB_PATH, body.username, hash_password(body.password), body.is_admin)
    if user is None:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=f"Username '{body.username}' is taken")
    log_activity("user_created", {"username": user["username"], "is_admin": body.is_admin, "by": admin["username"]})
    return APIResponse(success=True, message=f"User '{user['username']}' created", data={"user": public_user(user)})


@router.patch("/{user_id}", response_model=APIResponse)
async def update_user(user_id: int, body: UserUpdateRequest, admin: dict = Depends(require_admin)):
    target = _get_other_user(user_id, admin)
    if not set_user_admin(DB_PATH, target["id"], body.is_admin):
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="There must be at least one administrator")
    log_activity("user_updated", {"username": target["username"], "is_admin": body.is_admin, "by": admin["username"]})
    return APIResponse(
        success=True,
        message=f"'{target['username']}' is {'now an administrator' if body.is_admin else 'no longer an administrator'}",
        data={"user": public_user({**target, "is_admin": body.is_admin})},
    )


@router.post("/{user_id}/password", response_model=APIResponse)
async def reset_user_password(user_id: int, body: PasswordResetRequest, admin: dict = Depends(require_admin)):
    """Set a new password for another user and sign them out everywhere."""
    target = _get_other_user(user_id, admin)
    update_user_password(DB_PATH, target["id"], hash_password(body.new_password))
    delete_user_sessions(DB_PATH, target["id"])
    log_activity("user_password_reset", {"username": target["username"], "by": admin["username"]})
    return APIResponse(success=True, message=f"Password reset for '{target['username']}'")


@router.delete("/{user_id}", response_model=APIResponse)
async def remove_user(user_id: int, admin: dict = Depends(require_admin)):
    target = _get_other_user(user_id, admin)
    if not delete_user(DB_PATH, target["id"]):
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="There must be at least one administrator")
    log_activity("user_deleted", {"username": target["username"], "by": admin["username"]})
    return APIResponse(success=True, message=f"User '{target['username']}' deleted")
