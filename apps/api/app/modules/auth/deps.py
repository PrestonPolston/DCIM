from app.security.client_ip import client_ip
import secrets
from urllib.parse import urlsplit

from fastapi import Depends, HTTPException, Request
from sqlmodel import Session

from app.db import get_session
from app.modules.auth.models import UserRow
from app.modules.auth.service import resolve_session
from app.settings import Settings, get_settings

SAFE_METHODS = {"GET", "HEAD", "OPTIONS"}
# reachable while must_change_password is set
PASSWORD_CHANGE_PATHS = {"/auth/me", "/auth/logout", "/auth/change-password"}


# Reject unsafe requests whose Origin (or Referer) isn't ours or allow-listed
def check_origin(request: Request, settings: Settings) -> None:
    if request.method in SAFE_METHODS:
        return
    origin = request.headers.get("origin")
    if origin is None and request.headers.get("referer"):
        parts = urlsplit(request.headers["referer"])
        origin = f"{parts.scheme}://{parts.netloc}"
    if origin is None:
        return  # non-browser client; the CSRF token is still required
    allowed = set(settings.trusted_origins) | set(settings.cors_origins)
    if origin in allowed or urlsplit(origin).netloc == request.headers.get("host"):
        return
    raise HTTPException(status_code=403, detail="Origin not allowed")


# Deny by default: every non-public router depends on this (401 without a valid session)
def get_current_user(
    request: Request,
    session: Session = Depends(get_session),
    settings: Settings = Depends(get_settings),
) -> UserRow:
    found = resolve_session(session, request.cookies.get(settings.session_cookie_name), settings)
    if found is None:
        raise HTTPException(status_code=401, detail="Not authenticated")
    session_row, user = found
    request.state.user = user
    request.state.session_row = session_row
    # services (change sets, audit) read the actor from the DB session
    session.info["user"] = user
    session.info["request_meta"] = {
        "ip": client_ip(request),
        "request_id": getattr(request.state, "request_id", None),
    }
    if request.method not in SAFE_METHODS:
        check_origin(request, settings)
        sent = request.headers.get("x-csrf-token", "")
        if not secrets.compare_digest(sent, session_row.csrf_token):
            raise HTTPException(status_code=403, detail="Missing or invalid CSRF token")
    if user.must_change_password and request.url.path not in PASSWORD_CHANGE_PATHS:
        raise HTTPException(
            status_code=403,
            detail={"code": "password_change_required", "message": "Change your password first"},
        )
    return user


# Per-route role check (403); the matrix lives in docs/API.md
def require_role(*roles: str):
    def dependency(user: UserRow = Depends(get_current_user)) -> UserRow:
        if user.role not in roles:
            raise HTTPException(status_code=403, detail=f"Requires role: {' or '.join(roles)}")
        return user

    dependency.roles = roles  # for the route-coverage test
    return dependency


ADMIN = require_role("admin")
TECH = require_role("admin", "technician")
ANY_ROLE = require_role("admin", "technician", "read-only")
