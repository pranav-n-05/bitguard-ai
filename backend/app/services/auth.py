"""Login, refresh-token rotation with reuse detection, logout, lockout."""

import uuid
from datetime import UTC, datetime, timedelta

import pyotp
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import AuthenticationError
from app.core.security import create_token, decode_token, hash_password, needs_rehash, verify_password
from app.models import RefreshToken, User
from app.schemas.auth import TokenPair
from app.services import audit

MAX_FAILED = 5
LOCKOUT = timedelta(minutes=15)
_DUMMY_HASH = hash_password("timing-equaliser")


async def _issue(s: AsyncSession, user: User) -> TokenPair:
    access, _, exp = create_token(str(user.id), "access", extra={"roles": user.role_names})
    refresh, jti, rexp = create_token(str(user.id), "refresh")
    s.add(RefreshToken(jti=jti, user_id=user.id, expires_at=rexp))
    return TokenPair(access_token=access, refresh_token=refresh, expires_at=exp)


async def login(s: AsyncSession, email: str, password: str, otp: str | None, request_id: str | None) -> TokenPair:
    user = (await s.execute(select(User).where(User.email == email.lower()))).scalar_one_or_none()
    now = datetime.now(UTC)
    if user is None:
        verify_password(password, _DUMMY_HASH)
        await audit.record(s, "auth.login_failed", "user", None, details={"email": email.lower()}, request_id=request_id)
        await s.commit()
        raise AuthenticationError("Invalid credentials")
    if user.locked_until and user.locked_until > now:
        raise AuthenticationError("Account temporarily locked")
    ok = user.is_active and verify_password(password, user.password_hash)
    if ok and user.mfa_enabled:
        ok = bool(otp and user.mfa_secret and pyotp.TOTP(user.mfa_secret).verify(otp, valid_window=1))
    if not ok:
        user.failed_logins += 1
        if user.failed_logins >= MAX_FAILED:
            user.locked_until, user.failed_logins = now + LOCKOUT, 0
        await audit.record(s, "auth.login_failed", "user", str(user.id), actor_id=user.id, request_id=request_id)
        await s.commit()
        raise AuthenticationError("Invalid credentials")
    if needs_rehash(user.password_hash):
        user.password_hash = hash_password(password)
    user.failed_logins, user.locked_until, user.last_login_at = 0, None, now
    pair = await _issue(s, user)
    await audit.record(s, "auth.login", "user", str(user.id), actor_id=user.id, actor_email=user.email, request_id=request_id)
    await s.commit()
    return pair


async def refresh(s: AsyncSession, token: str) -> TokenPair:
    payload = decode_token(token, "refresh")
    rt = await s.get(RefreshToken, payload["jti"], with_for_update=True)
    if rt is None:
        raise AuthenticationError("Unknown refresh token")
    if rt.revoked_at is not None:
        # Reuse of a rotated token: assume theft, revoke the whole family.
        await s.execute(
            update(RefreshToken)
            .where(RefreshToken.user_id == rt.user_id, RefreshToken.revoked_at.is_(None))
            .values(revoked_at=datetime.now(UTC))
        )
        await audit.record(s, "auth.refresh_reuse_detected", "user", str(rt.user_id), actor_id=rt.user_id)
        await s.commit()
        raise AuthenticationError("Refresh token reuse detected; all sessions revoked")
    user = await s.get(User, uuid.UUID(payload["sub"]))
    if user is None or not user.is_active:
        raise AuthenticationError("User inactive")
    pair = await _issue(s, user)
    rt.revoked_at = datetime.now(UTC)
    rt.replaced_by = decode_token(pair.refresh_token, "refresh")["jti"]
    await s.commit()
    return pair


async def logout(s: AsyncSession, token: str, user: User) -> None:
    payload = decode_token(token, "refresh")
    rt = await s.get(RefreshToken, payload["jti"])
    if rt and rt.user_id == user.id and rt.revoked_at is None:
        rt.revoked_at = datetime.now(UTC)
    await audit.record(s, "auth.logout", "user", str(user.id), actor_id=user.id, actor_email=user.email)
    await s.commit()
