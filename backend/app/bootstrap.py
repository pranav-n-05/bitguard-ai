"""`python -m app.bootstrap` — seed RBAC/config and the bootstrap administrator (idempotent)."""

import asyncio

from app.core.config import get_settings
from app.database.session import get_sessionmaker
from app.services.bootstrap import ensure_user, seed_rbac


async def main() -> None:
    s = get_settings()
    async with get_sessionmaker()() as session, session.begin():
        await seed_rbac(session)
        if s.bootstrap_admin_email and s.bootstrap_admin_password:
            await ensure_user(
                session, s.bootstrap_admin_email, s.bootstrap_admin_password, "administrator", "Bootstrap Administrator"
            )
    print("bootstrap complete")


if __name__ == "__main__":
    asyncio.run(main())
