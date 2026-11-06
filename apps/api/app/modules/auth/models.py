from datetime import datetime

from sqlalchemy import CheckConstraint, DateTime, false, true
from sqlmodel import Field, SQLModel, UniqueConstraint

from app.enums import Role, sql_in
from app.timestamps import TimestampMixin, ts_field


# Local or SSO user account (AUTH_RBAC_PLAN §1.1)
class UserRow(TimestampMixin, table=True):
    __tablename__ = "users"
    __table_args__ = (
        UniqueConstraint("external_issuer", "external_subject"),
        CheckConstraint(sql_in("role", Role), name="role"),
        CheckConstraint("auth_source IN ('local','oidc')", name="auth_source"),
        CheckConstraint("email = lower(email)", name="email_lower"),
    )

    id: int | None = Field(default=None, primary_key=True)
    email: str = Field(unique=True)  # stored lower-cased
    display_name: str | None = None
    password_hash: str | None = None  # argon2id; null for SSO-only users
    role: str
    is_active: bool = Field(default=True, sa_column_kwargs={"server_default": true()})
    auth_source: str = Field(default="local", sa_column_kwargs={"server_default": "local"})
    external_subject: str | None = None
    external_issuer: str | None = None
    must_change_password: bool = Field(default=False, sa_column_kwargs={"server_default": false()})
    mfa_secret_enc: str | None = None
    mfa_enabled: bool = Field(default=False, sa_column_kwargs={"server_default": false()})
    failed_logins: int = Field(default=0, sa_column_kwargs={"server_default": "0"})
    locked_until: datetime | None = ts_field()
    created_by: int | None = Field(default=None, foreign_key="users.id", ondelete="SET NULL")
    last_login_at: datetime | None = ts_field()
    password_changed_at: datetime | None = ts_field()


# Server-side session; id = SHA-256 of the cookie token (the token itself is never stored)
class SessionRow(SQLModel, table=True):
    __tablename__ = "sessions"

    id: str = Field(primary_key=True)
    user_id: int = Field(foreign_key="users.id", ondelete="CASCADE", index=True)
    auth_provider: str
    mfa_satisfied: bool = Field(default=False, sa_column_kwargs={"server_default": false()})
    csrf_token: str
    created_at: datetime = Field(sa_type=DateTime(timezone=True))
    expires_at: datetime = Field(sa_type=DateTime(timezone=True), index=True)
    last_seen_at: datetime = Field(sa_type=DateTime(timezone=True))
    ip: str | None = None
    user_agent: str | None = None
