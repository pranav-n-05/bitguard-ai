"""Test harness. Requires the compose `test` profile: `docker compose --profile test up -d db-test redis`.

All fixtures are SYNTHETIC.
"""

import os
import tempfile
from collections.abc import AsyncIterator
from pathlib import Path

os.environ.setdefault("BITGUARD_DATABASE_URL", "postgresql+asyncpg://bitguard:bitguard@localhost:5433/bitguard_test")
os.environ["BITGUARD_CELERY_EAGER"] = "true"
os.environ["BITGUARD_RATE_LIMIT_STORAGE"] = "memory://"
os.environ["BITGUARD_LOGIN_RATE_LIMIT"] = "10000/minute"
os.environ["BITGUARD_DEFAULT_RATE_LIMIT"] = "100000/minute"
os.environ["BITGUARD_STORAGE_DIR"] = tempfile.mkdtemp(prefix="bitguard-test-")
os.environ["BITGUARD_MODEL_DIR"] = tempfile.mkdtemp(prefix="bitguard-models-")
os.environ["BITGUARD_JWT_SECRET"] = "test-secret-test-secret-test-secret-0123"

import pytest
from alembic import command
from alembic.config import Config
from httpx import ASGITransport, AsyncClient
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.database.session import get_engine, get_sessionmaker
from app.models import Base
from app.services.bootstrap import ensure_user, seed_rbac

BACKEND = Path(__file__).resolve().parents[1]
FIXTURES = Path(__file__).parent / "fixtures"
PASSWORD = "Correct-Horse-Battery-9"


@pytest.fixture(scope="session", autouse=True)
def _migrate() -> None:
    cfg = Config(str(BACKEND / "alembic.ini"))
    cfg.set_main_option("script_location", str(BACKEND / "migrations"))
    cfg.attributes["url"] = get_settings().database_url
    command.downgrade(cfg, "base")
    command.upgrade(cfg, "head")


@pytest.fixture(autouse=True)
async def _clean_db() -> AsyncIterator[None]:
    tables = ", ".join(f'"{t.name}"' for t in Base.metadata.sorted_tables)
    async with get_engine().begin() as conn:
        await conn.execute(text(f"TRUNCATE {tables} RESTART IDENTITY CASCADE"))
    async with get_sessionmaker()() as s, s.begin():
        await seed_rbac(s)
        for role in ("administrator", "senior_analyst", "analyst", "viewer"):
            await ensure_user(s, f"{role}@test.local", PASSWORD, role)
    yield


@pytest.fixture
async def session() -> AsyncIterator[AsyncSession]:
    async with get_sessionmaker()() as s:
        yield s


@pytest.fixture
async def client() -> AsyncIterator[AsyncClient]:
    from app.main import app

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        yield c


async def auth_headers(client: AsyncClient, role: str) -> dict[str, str]:
    r = await client.post("/api/v1/auth/login", json={"email": f"{role}@test.local", "password": PASSWORD})
    assert r.status_code == 200, r.text
    return {"Authorization": f"Bearer {r.json()['access_token']}"}


@pytest.fixture
async def admin(client: AsyncClient) -> dict[str, str]:
    return await auth_headers(client, "administrator")


@pytest.fixture
def small_dataset(tmp_path: Path) -> dict[str, Path]:
    """Small seeded SYNTHETIC dataset written in all four formats."""
    from app.ingestion.synthetic import Generator

    g = Generator(seed=7, n_actors=20, n_baseline_tx=120, error_rate=0.05).generate(patterns_per_type=1)
    return {fmt: g.write(tmp_path / fmt, fmt, name="synthetic_small") for fmt in ("csv", "json", "jsonl", "xml")}


def pytest_collection_modifyitems(items: list[pytest.Item]) -> None:
    """Run every async test on the single session event loop shared with the cached DB engine."""
    from pytest_asyncio import is_async_test

    marker = pytest.mark.asyncio(loop_scope="session")
    for item in items:
        if is_async_test(item):
            item.add_marker(marker, append=False)
