"""Idempotent seeding of roles, permissions, default alert rules, config and bootstrap admin."""

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.rbac import PERMISSIONS, ROLES
from app.core.security import hash_password
from app.models import Permission, Role, User


async def seed_rbac(s: AsyncSession) -> None:
    perms = {p.code: p for p in (await s.execute(select(Permission))).scalars()}
    for code, desc in PERMISSIONS.items():
        if code not in perms:
            perms[code] = Permission(code=code, description=desc)
            s.add(perms[code])
    await s.flush()
    roles = {r.name: r for r in (await s.execute(select(Role))).scalars()}
    for name, (desc, codes) in ROLES.items():
        role = roles.get(name) or Role(name=name, description=desc)
        role.permissions = [perms[c] for c in sorted(codes)]
        s.add(role)
    await s.flush()


async def ensure_user(s: AsyncSession, email: str, password: str, role: str, full_name: str | None = None) -> User:
    u = (await s.execute(select(User).where(User.email == email.lower()))).scalar_one_or_none()
    if u:
        return u
    r = (await s.execute(select(Role).where(Role.name == role))).scalar_one()
    u = User(email=email.lower(), full_name=full_name or email, password_hash=hash_password(password), roles=[r])
    s.add(u)
    await s.flush()
    return u
