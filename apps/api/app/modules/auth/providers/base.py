from dataclasses import dataclass, field
from typing import Literal, Protocol

from sqlmodel import Session


# What every provider hands to finish_login() (AUTH_RBAC_PLAN §1.3)
@dataclass
class AuthResult:
    issuer: str  # "local" or an OIDC issuer URL
    subject: str  # user id (local) or OIDC sub
    email: str
    display_name: str | None = None
    claims: dict = field(default_factory=dict)
    mfa_satisfied: bool = False


class AuthError(Exception):
    """Login failed; the API always answers with the same generic message."""


class AuthProvider(Protocol):
    id: str
    kind: Literal["password", "redirect"]

    def display(self) -> dict: ...

    # password providers
    def authenticate(self, session: Session, email: str, password: str) -> AuthResult: ...


class RoleMapper(Protocol):
    def role_for(self, result: AuthResult, existing_user) -> str | None: ...


# Local accounts keep the role an admin assigned
class ExistingRoleMapper:
    def role_for(self, result: AuthResult, existing_user) -> str | None:
        return existing_user.role if existing_user else None
