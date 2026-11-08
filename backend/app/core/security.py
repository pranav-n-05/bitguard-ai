"""Password hashing (Argon2id) and JWT access/refresh tokens."""

import uuid
from datetime import UTC, datetime, timedelta
from typing import Any, Literal

import jwt
from argon2 import PasswordHasher
from argon2.exceptions import InvalidHashError, VerificationError

from app.core.config import get_settings
from app.core.errors import AuthenticationError

_hasher = PasswordHasher()  # argon2id defaults (RFC 9106 low-memory profile)

TokenType = Literal["access", "refresh"]


def hash_password(password: str) -> str:
    return _hasher.hash(password)


def verify_password(password: str, password_hash: str) -> bool:
    try:
        return _hasher.verify(password_hash, password)
    except (VerificationError, InvalidHashError):
        return False


def needs_rehash(password_hash: str) -> bool:
    return _hasher.check_needs_rehash(password_hash)


def create_token(subject: str, token_type: TokenType, *, extra: dict[str, Any] | None = None) -> tuple[str, str, datetime]:
    s = get_settings()
    now = datetime.now(UTC)
    ttl = timedelta(minutes=s.access_token_minutes) if token_type == "access" else timedelta(days=s.refresh_token_days)  # noqa: S105
    jti = uuid.uuid4().hex
    exp = now + ttl
    payload = {"sub": subject, "type": token_type, "jti": jti, "iat": now, "exp": exp, **(extra or {})}
    return jwt.encode(payload, s.jwt_secret, algorithm=s.jwt_algorithm), jti, exp


def decode_token(token: str, expected_type: TokenType) -> dict[str, Any]:
    s = get_settings()
    try:
        payload: dict[str, Any] = jwt.decode(token, s.jwt_secret, algorithms=[s.jwt_algorithm])
    except jwt.ExpiredSignatureError as e:
        raise AuthenticationError("Token expired") from e
    except jwt.PyJWTError as e:
        raise AuthenticationError("Invalid token") from e
    if payload.get("type") != expected_type:
        raise AuthenticationError("Wrong token type")
    return payload
