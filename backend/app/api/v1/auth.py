import pyotp
from fastapi import APIRouter, Request
from pydantic import BaseModel, Field

from app.api.deps import CurrentUser, SessionDep
from app.core.errors import AuthenticationError, InvalidStateError
from app.core.passwords import check_policy
from app.core.ratelimit import limiter, login_limit
from app.core.security import hash_password, verify_password
from app.schemas.auth import LoginRequest, RefreshRequest, TokenPair, UserOut
from app.services import audit
from app.services import auth as svc

router = APIRouter(prefix="/auth", tags=["auth"])


def _user_out(u: object) -> UserOut:
    out = UserOut.model_validate(u)
    out.permission_codes = sorted(out.permission_codes)
    return out


@router.post("/login", response_model=TokenPair, summary="Authenticate and obtain access/refresh tokens")
@limiter.limit(login_limit)
async def login(body: LoginRequest, request: Request, s: SessionDep) -> TokenPair:
    return await svc.login(s, body.email, body.password, body.otp, getattr(request.state, "request_id", None))


@router.post("/refresh", response_model=TokenPair, summary="Rotate refresh token")
async def refresh(body: RefreshRequest, s: SessionDep) -> TokenPair:
    return await svc.refresh(s, body.refresh_token)


@router.post("/logout", status_code=204, summary="Revoke a refresh token")
async def logout(body: RefreshRequest, user: CurrentUser, s: SessionDep) -> None:
    await svc.logout(s, body.refresh_token, user)


@router.get("/me", response_model=UserOut)
async def me(user: CurrentUser) -> UserOut:
    return _user_out(user)


class OtpIn(BaseModel):
    otp: str = Field(pattern=r"^\d{6}$")


class PasswordChange(BaseModel):
    current_password: str = Field(min_length=1, max_length=256)
    new_password: str = Field(min_length=1, max_length=256)


@router.post("/mfa/setup", summary="Generate a TOTP secret (MFA stays disabled until confirmed)")
async def mfa_setup(user: CurrentUser, s: SessionDep) -> dict[str, str]:
    if user.mfa_enabled:
        raise InvalidStateError("MFA already enabled; disable it first")
    secret = pyotp.random_base32()
    user.mfa_secret = secret
    await audit.record(s, "auth.mfa_setup", "user", str(user.id), actor_id=user.id, actor_email=user.email)
    await s.commit()
    return {"secret": secret, "otpauth_uri": pyotp.TOTP(secret).provisioning_uri(name=user.email, issuer_name="BITGUARD AI")}


@router.post("/mfa/enable")
async def mfa_enable(body: OtpIn, user: CurrentUser, s: SessionDep) -> dict[str, bool]:
    if not user.mfa_secret or not pyotp.TOTP(user.mfa_secret).verify(body.otp, valid_window=1):
        raise AuthenticationError("Invalid one-time code")
    user.mfa_enabled = True
    await audit.record(s, "auth.mfa_enabled", "user", str(user.id), actor_id=user.id, actor_email=user.email)
    await s.commit()
    return {"mfa_enabled": True}


@router.post("/mfa/disable")
async def mfa_disable(body: OtpIn, user: CurrentUser, s: SessionDep) -> dict[str, bool]:
    if not user.mfa_enabled or not user.mfa_secret or not pyotp.TOTP(user.mfa_secret).verify(body.otp, valid_window=1):
        raise AuthenticationError("Invalid one-time code")
    user.mfa_enabled, user.mfa_secret = False, None
    await audit.record(s, "auth.mfa_disabled", "user", str(user.id), actor_id=user.id, actor_email=user.email)
    await s.commit()
    return {"mfa_enabled": False}


@router.post("/password", status_code=204)
async def change_password(body: PasswordChange, user: CurrentUser, s: SessionDep) -> None:
    if not verify_password(body.current_password, user.password_hash):
        raise AuthenticationError("Current password is incorrect")
    check_policy(body.new_password, user.email)
    user.password_hash = hash_password(body.new_password)
    from sqlalchemy import func, update

    from app.models import RefreshToken

    await s.execute(
        update(RefreshToken)
        .where(RefreshToken.user_id == user.id, RefreshToken.revoked_at.is_(None))
        .values(revoked_at=func.now())
    )
    await audit.record(s, "auth.password_changed", "user", str(user.id), actor_id=user.id, actor_email=user.email)
    await s.commit()
