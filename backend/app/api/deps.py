"""FastAPI dependencies: DB session, authenticated user, permission checks, pagination/sorting."""

import uuid
from collections.abc import AsyncIterator, Callable, Coroutine
from typing import Annotated, Any

from fastapi import Depends, Query, Request
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import AuthenticationError, PermissionDeniedError
from app.core.security import decode_token
from app.database.session import get_sessionmaker
from app.models import User

_bearer = HTTPBearer(auto_error=False)


async def db_session() -> AsyncIterator[AsyncSession]:
    async with get_sessionmaker()() as s:
        yield s


SessionDep = Annotated[AsyncSession, Depends(db_session)]


async def current_user(
    request: Request, session: SessionDep, creds: HTTPAuthorizationCredentials | None = Depends(_bearer)
) -> User:
    if creds is None or creds.scheme.lower() != "bearer":
        raise AuthenticationError("Missing bearer token")
    payload = decode_token(creds.credentials, "access")
    user = await session.get(User, uuid.UUID(payload["sub"]))
    if user is None or not user.is_active:
        raise AuthenticationError("User inactive or not found")
    request.state.user = user
    return user


CurrentUser = Annotated[User, Depends(current_user)]


def require(*codes: str) -> Callable[..., Coroutine[Any, Any, User]]:
    async def _check(user: CurrentUser) -> User:
        missing = [c for c in codes if c not in user.permission_codes]
        if missing:
            raise PermissionDeniedError(f"Missing permission: {', '.join(missing)}")
        return user

    return _check


class Page(BaseModel):
    limit: int
    offset: int
    sort: str | None


def page_params(
    limit: Annotated[int, Query(ge=1, le=500)] = 50,
    offset: Annotated[int, Query(ge=0)] = 0,
    sort: Annotated[str | None, Query(max_length=64, pattern=r"^-?[a-z_]+$")] = None,
) -> Page:
    return Page(limit=limit, offset=offset, sort=sort)


PageDep = Annotated[Page, Depends(page_params)]


def apply_sort(stmt: Any, model: Any, sort: str | None, allowed: set[str], default: Any) -> Any:
    if not sort:
        return stmt.order_by(default)
    desc = sort.startswith("-")
    name = sort.lstrip("-")
    if name not in allowed:
        from app.core.errors import AppError

        raise AppError(f"Cannot sort by {name!r}; allowed: {sorted(allowed)}")
    col = getattr(model, name)
    return stmt.order_by(col.desc() if desc else col.asc())
