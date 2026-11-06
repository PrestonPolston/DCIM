from app.security.client_ip import client_ip
import hashlib
import secrets
from datetime import timedelta

from fastapi import Request, Response
from sqlmodel import Session, delete, select

from app.modules.audit.service import audit
from app.modules.auth.models import SessionRow, UserRow
from app.modules.auth.providers.base import AuthError, AuthResult, ExistingRoleMapper
from app.settings import Settings
from app.timestamps import as_utc, utcnow


def token_hash(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


# The only place sessions are created (AUTH_RBAC_PLAN §1.3). Returns (user, session row, raw token).
def finish_login(session: Session, result: AuthResult, provider_id: str, request: Request,
                 settings: Settings) -> tuple[UserRow, SessionRow, str]:
    user = session.exec(select(UserRow).where(UserRow.email == result.email.lower())).first()
    role = ExistingRoleMapper().role_for(result, user)
    if user is None or role is None or not user.is_active:
        raise AuthError()
    user.role = role
    user.last_login_at = utcnow()
    row, token = mint_session(session, user, provider_id, result.mfa_satisfied, request, settings)
    request.state.user = user
    audit(request, session, "auth.login", "user", user.id, after={"provider": provider_id})
    session.commit()
    return user, row, token


# New random session id + CSRF token (login, and rotation on credential change: R-4)
def mint_session(session: Session, user: UserRow, provider_id: str, mfa: bool, request: Request,
                 settings: Settings) -> tuple[SessionRow, str]:
    token = secrets.token_urlsafe(32)  # 256 bits
    now = utcnow()
    row = SessionRow(
        id=token_hash(token), user_id=user.id, auth_provider=provider_id,
        mfa_satisfied=mfa, csrf_token=secrets.token_urlsafe(32),
        created_at=now, last_seen_at=now,
        expires_at=now + timedelta(hours=settings.session_absolute_hours),
        ip=client_ip(request),
        user_agent=(request.headers.get("user-agent") or "")[:300],
    )
    session.add(row)
    return row, token


# Look up a session cookie; enforces idle and absolute expiry
def resolve_session(session: Session, token: str | None, settings: Settings) -> tuple[SessionRow, UserRow] | None:
    if not token:
        return None
    row = session.get(SessionRow, token_hash(token))
    if row is None:
        return None
    now = utcnow()
    idle_limit = as_utc(row.last_seen_at) + timedelta(minutes=settings.session_idle_minutes)
    if as_utc(row.expires_at) <= now or idle_limit <= now:
        session.delete(row)
        session.commit()
        return None
    user = session.get(UserRow, row.user_id)
    if user is None or not user.is_active:
        return None
    if (now - as_utc(row.last_seen_at)) > timedelta(minutes=1):  # avoid a write per request
        row.last_seen_at = now
        session.commit()
    return row, user


def revoke_user_sessions(session: Session, user_id: int, keep_session_id: str | None = None) -> None:
    statement = delete(SessionRow).where(SessionRow.user_id == user_id)
    if keep_session_id:
        statement = statement.where(SessionRow.id != keep_session_id)
    session.exec(statement)


def set_session_cookie(response: Response, token: str, settings: Settings) -> None:
    response.set_cookie(
        settings.session_cookie_name, token, httponly=True, secure=settings.cookie_secure,
        samesite="lax", path="/", max_age=settings.session_absolute_hours * 3600,
    )


def clear_session_cookie(response: Response, settings: Settings) -> None:
    response.delete_cookie(
        settings.session_cookie_name, path="/", secure=settings.cookie_secure, httponly=True, samesite="lax"
    )
