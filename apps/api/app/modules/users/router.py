import secrets

from fastapi import APIRouter, Depends, HTTPException, Request, Response
from sqlmodel import Session, func, select

from app.db import flush_or_409, commit_or_409, get_session
from app.modules.audit.service import audit
from app.modules.auth.deps import ADMIN
from app.modules.auth.models import UserRow
from app.modules.auth.passwords import hash_password, password_problems
from app.modules.auth.service import revoke_user_sessions
from app.modules.locations.service import get_or_404
from app.modules.users.schemas import User, UserCreate, UserUpdate, UserWithTemporaryPassword
from app.pagination import Pagination, paginate
from app.settings import Settings, get_settings
from app.timestamps import utcnow

# Admin-only user management; there is no self sign-up
router = APIRouter(prefix="/users", tags=["users"], dependencies=[Depends(ADMIN)])


def _temp_password() -> str:
    return secrets.token_urlsafe(15)  # 20 chars


def _ensure_another_admin(session: Session, user: UserRow) -> None:
    others = session.exec(
        select(func.count()).select_from(UserRow)
        .where(UserRow.role == "admin", UserRow.is_active, UserRow.id != user.id)
    ).one()
    if not others:
        raise HTTPException(status_code=409, detail="Cannot remove the last active admin")


@router.get("", response_model=list[User])
def list_users(response: Response, page: Pagination = Depends(), session: Session = Depends(get_session)):
    return paginate(session, select(UserRow), page, response, UserRow.id)


@router.post("", response_model=UserWithTemporaryPassword, status_code=201)
def create_user(payload: UserCreate, request: Request, session: Session = Depends(get_session),
                settings: Settings = Depends(get_settings)):
    email = payload.email.strip().lower()
    password = payload.temporary_password or _temp_password()
    problems = password_problems(password, email, settings.password_min_length)
    if problems:
        raise HTTPException(status_code=422, detail=problems)
    user = UserRow(email=email, role=payload.role, display_name=payload.display_name,
                   password_hash=hash_password(password), must_change_password=True,
                   created_by=request.state.user.id)
    session.add(user)
    flush_or_409(session, "A user with this email already exists")
    # R-6: the audit event commits in the same transaction as the user row
    audit(request, session, "user.create", "user", user.id, after={"email": email, "role": user.role})
    commit_or_409(session, "A user with this email already exists")
    session.refresh(user)
    return UserWithTemporaryPassword(**user.model_dump(), temporary_password=password)


@router.get("/{user_id}", response_model=User)
def get_user(user_id: int, session: Session = Depends(get_session)):
    return get_or_404(session, UserRow, user_id, "User")


# Role change or deactivation revokes the user's sessions
@router.patch("/{user_id}", response_model=User)
def update_user(user_id: int, payload: UserUpdate, request: Request, session: Session = Depends(get_session)):
    user = get_or_404(session, UserRow, user_id, "User")
    changes = payload.model_dump(exclude_unset=True)
    demoting = changes.get("role", user.role) != "admin" or changes.get("is_active") is False
    if user.role == "admin" and user.is_active and demoting:
        _ensure_another_admin(session, user)
    if "role" in changes and changes["role"] != user.role:
        audit(request, session, "user.role_change", "user", user.id,
              before={"role": user.role}, after={"role": changes["role"]})
        revoke_user_sessions(session, user.id)
    if changes.get("is_active") is False and user.is_active:
        audit(request, session, "user.deactivate", "user", user.id)
        revoke_user_sessions(session, user.id)
    if changes.get("is_active") is True and not user.is_active:
        audit(request, session, "user.activate", "user", user.id)
    for key, value in changes.items():
        setattr(user, key, value)
    session.commit()
    session.refresh(user)
    return user


@router.post("/{user_id}/reset-password", response_model=UserWithTemporaryPassword)
def reset_password(user_id: int, request: Request, session: Session = Depends(get_session)):
    user = get_or_404(session, UserRow, user_id, "User")
    password = _temp_password()
    user.password_hash = hash_password(password)
    user.must_change_password = True
    user.password_changed_at = utcnow()
    user.failed_logins, user.locked_until = 0, None
    revoke_user_sessions(session, user.id)
    audit(request, session, "user.reset_password", "user", user.id)
    session.commit()
    session.refresh(user)
    return UserWithTemporaryPassword(**user.model_dump(), temporary_password=password)


@router.post("/{user_id}/unlock", response_model=User)
def unlock(user_id: int, request: Request, session: Session = Depends(get_session)):
    user = get_or_404(session, UserRow, user_id, "User")
    user.failed_logins, user.locked_until = 0, None
    audit(request, session, "user.unlock", "user", user.id)
    session.commit()
    session.refresh(user)
    return user
