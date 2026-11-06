from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field

from app.enums import RoleLiteral


class UserCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")
    email: str = Field(min_length=3, max_length=254, pattern=r"^[^@\s]+@[^@\s]+$")
    role: RoleLiteral
    display_name: str | None = Field(None, max_length=100)
    temporary_password: str | None = Field(None, max_length=128, description="Omit to generate one")


class UserUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")
    role: RoleLiteral | None = None
    is_active: bool | None = None
    display_name: str | None = Field(None, max_length=100)


class User(BaseModel):
    id: int
    email: str
    display_name: str | None
    role: RoleLiteral
    is_active: bool
    auth_source: str
    must_change_password: bool
    locked_until: datetime | None
    last_login_at: datetime | None
    created_at: datetime | None


# Returned once when an admin creates a user or resets a password
class UserWithTemporaryPassword(User):
    temporary_password: str
