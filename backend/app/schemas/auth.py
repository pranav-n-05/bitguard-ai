import uuid
from datetime import datetime

from pydantic import BaseModel, Field

from app.schemas.common import ORM


class LoginRequest(BaseModel):
    # Offline deployments commonly use internal domains (e.g. .local), so validate shape only.
    email: str = Field(min_length=3, max_length=255, pattern=r"^[^@\s]+@[^@\s]+$")
    password: str = Field(min_length=1, max_length=256)
    otp: str | None = Field(default=None, pattern=r"^\d{6}$")


class TokenPair(BaseModel):
    access_token: str
    refresh_token: str
    token_type: str = "bearer"  # noqa: S105
    expires_at: datetime


class RefreshRequest(BaseModel):
    refresh_token: str


class UserOut(ORM):
    id: uuid.UUID
    email: str
    full_name: str
    is_active: bool
    mfa_enabled: bool
    role_names: list[str]
    permission_codes: list[str]
    last_login_at: datetime | None
