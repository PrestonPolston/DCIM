from datetime import timedelta

from sqlmodel import Session, select

from app.modules.audit.service import record_audit
from app.modules.auth.models import UserRow
from app.modules.auth.passwords import dummy_verify, hash_password, verify_password
from app.modules.auth.providers.base import AuthError, AuthResult
from app.settings import Settings
from app.timestamps import as_utc, utcnow


# Email + password accounts with argon2id and per-account lockout
class LocalProvider:
    id = "local"
    kind = "password"

    def __init__(self, settings: Settings):
        self.settings = settings

    def display(self) -> dict:
        return {"id": self.id, "kind": self.kind, "name": "Email and password"}

    def authenticate(self, session: Session, email: str, password: str, ip: str | None = None,
                     via: str | None = None) -> AuthResult:
        extra = {"via": via} if via else {}
        email = email.strip().lower()
        user = session.exec(select(UserRow).where(UserRow.email == email)).first()
        if user is None or user.password_hash is None or user.auth_source != "local":
            dummy_verify(password)
            record_audit(session, None, "auth.login_failed", "user", None, after={"email": email, **extra}, ip=ip, via=via)
            session.commit()
            raise AuthError()
        if self.settings.auth_local_enabled == "admin_only" and user.role != "admin":
            dummy_verify(password)
            # R-12: refusals under admin_only are audited too
            record_audit(session, None, "auth.login_failed", "user", user.id,
                         after={"reason": "local_disabled", **extra}, ip=ip, via=via)
            session.commit()
            raise AuthError()

        now = utcnow()
        if user.locked_until and as_utc(user.locked_until) > now:
            dummy_verify(password)
            record_audit(session, None, "auth.login_failed", "user", user.id, after={"reason": "locked", **extra}, ip=ip, via=via)
            session.commit()
            raise AuthError()

        ok, needs_rehash = verify_password(user.password_hash, password)
        if not ok:
            user.failed_logins += 1
            record_audit(session, None, "auth.login_failed", "user", user.id,
                         after={"failed_logins": user.failed_logins, **extra}, ip=ip, via=via)
            if user.failed_logins >= self.settings.login_max_failures:
                user.locked_until = now + timedelta(minutes=self.settings.login_lockout_minutes)
                user.failed_logins = 0
                record_audit(session, None, "auth.locked", "user", user.id,
                             after={"locked_until": user.locked_until.isoformat()}, ip=ip)
            session.commit()
            raise AuthError()

        user.failed_logins = 0
        user.locked_until = None
        if needs_rehash:
            user.password_hash = hash_password(password)
        return AuthResult(issuer="local", subject=str(user.id), email=user.email, display_name=user.display_name)


def build_providers(settings: Settings) -> dict:
    providers = {}
    if "local" in settings.auth_providers and settings.auth_local_enabled != "false":
        providers["local"] = LocalProvider(settings)
    return providers
