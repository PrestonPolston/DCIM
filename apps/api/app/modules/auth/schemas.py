from pydantic import BaseModel, ConfigDict, Field

from app.enums import RoleLiteral


class LoginRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    email: str = Field(min_length=3, max_length=254)
    password: str = Field(min_length=1, max_length=128)


class ChangePasswordRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    current_password: str = Field(max_length=128)
    new_password: str = Field(max_length=128)


class Me(BaseModel):
    id: int
    email: str
    display_name: str | None
    role: RoleLiteral
    must_change_password: bool
    csrf_token: str  # send back as X-CSRF-Token on POST/PATCH/DELETE


class Provider(BaseModel):
    id: str
    kind: str
    name: str
