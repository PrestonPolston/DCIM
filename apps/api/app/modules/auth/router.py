from app.security.client_ip import client_ip
from fastapi import APIRouter, Depends, HTTPException, Request, Response
from sqlmodel import Session

from app.db import get_session
from app.modules.audit.service import audit
from app.modules.auth.deps import check_origin, get_current_user
from app.modules.auth.models import UserRow
from app.modules.auth.passwords import hash_password, password_problems, verify_password
from app.modules.auth.providers.base import AuthError
from app.modules.auth.providers.local import build_providers
from app.modules.auth.schemas import ChangePasswordRequest, LoginRequest, Me, Provider
from app.modules.auth.service import (
    clear_session_cookie,
    finish_login,
    mint_session,
    revoke_user_sessions,
    set_session_cookie,
)
from app.security.ratelimit import login_limiter
from app.settings import Settings, get_settings
from app.timestamps import utcnow

router = APIRouter(prefix="/auth", tags=["auth"])
INVALID = "Invalid email or password"


def me_payload(user: UserRow, csrf_token: str) -> Me:
    return Me(id=user.id, email=user.email, display_name=user.display_name, role=user.role,
              must_change_password=user.must_change_password, csrf_token=csrf_token)


# Public: which login methods the login page should show
@router.get("/providers", response_model=list[Provider])
def providers(settings: Settings = Depends(get_settings)):
    return [p.display() for p in build_providers(settings).values()]


# Public: email + password login; sets the session cookie and returns /auth/me
@router.post("/login", response_model=Me)
def login(payload: LoginRequest, request: Request, response: Response,
          session: Session = Depends(get_session), settings: Settings = Depends(get_settings)):
    check_origin(request, settings)  # login CSRF
    provider = build_providers(settings).get("local")
    if provider is None:
        raise HTTPException(status_code=404, detail="Password login is disabled")
    ip = client_ip(request) or "unknown"
    window = settings.login_rate_window_seconds
    pair = f"fail:{ip}:{payload.email.strip().lower()}"
    wait = (login_limiter.retry_after("global", settings.login_rate_global, window)
            or login_limiter.retry_after(f"ip:{ip}", settings.login_rate_per_ip, window)
            or login_limiter.blocked(pair, settings.login_failures_per_ip_email, window))
    if wait:
        # N-2: one audit row per IP per window (the global limit stays a high circuit breaker)
        if login_limiter.first_in_window(f"audit:{ip}", window):
            audit(request, session, "auth.rate_limited", "user", None, after={"ip": ip, "first_in_window": True})
            session.commit()
        raise HTTPException(status_code=429, detail="Too many login attempts; try again later",
                            headers={"Retry-After": str(wait)})
    try:
        result = provider.authenticate(session, payload.email, payload.password, ip=ip)
        user, session_row, token = finish_login(session, result, provider.id, request, settings)
    except AuthError:
        login_limiter.hit(pair)
        raise HTTPException(status_code=401, detail=INVALID)
    set_session_cookie(response, token, settings)  # new random id on every login
    return me_payload(user, session_row.csrf_token)


@router.post("/logout", status_code=204)
def logout(request: Request, user: UserRow = Depends(get_current_user),
           session: Session = Depends(get_session), settings: Settings = Depends(get_settings)):
    session.delete(request.state.session_row)
    audit(request, session, "auth.logout", "user", user.id)
    session.commit()
    response = Response(status_code=204)
    clear_session_cookie(response, settings)
    return response


@router.get("/me", response_model=Me)
def me(request: Request, user: UserRow = Depends(get_current_user)):
    return me_payload(user, request.state.session_row.csrf_token)


# Self-service password change (forced when must_change_password); other sessions are revoked
@router.post("/change-password", response_model=Me)
def change_password(payload: ChangePasswordRequest, request: Request, response: Response,
                    user: UserRow = Depends(get_current_user), session: Session = Depends(get_session),
                    settings: Settings = Depends(get_settings)):
    ok, _ = verify_password(user.password_hash or "", payload.current_password)
    if not ok:
        raise HTTPException(status_code=400, detail="Current password is incorrect")
    problems = password_problems(payload.new_password, user.email, settings.password_min_length)
    if payload.new_password == payload.current_password:
        problems.append("New password must differ from the current one")
    if problems:
        raise HTTPException(status_code=422, detail=problems)
    user.password_hash = hash_password(payload.new_password)
    user.must_change_password = False
    user.password_changed_at = utcnow()
    old = request.state.session_row
    revoke_user_sessions(session, user.id)  # every session, including this one (R-4 rotation)
    new_row, token = mint_session(session, user, old.auth_provider, old.mfa_satisfied, request, settings)
    audit(request, session, "auth.password_changed", "user", user.id)
    session.commit()
    set_session_cookie(response, token, settings)
    return me_payload(user, new_row.csrf_token)
