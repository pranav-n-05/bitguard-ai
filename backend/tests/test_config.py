import pytest

from app.core.config import Settings


def test_cors_origins_accepts_comma_separated(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("BITGUARD_CORS_ORIGINS", "http://a.local, http://b.local")
    assert Settings().cors_origins == ["http://a.local", "http://b.local"]


def test_cors_origins_accepts_json_list(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("BITGUARD_CORS_ORIGINS", '["http://a.local"]')
    assert Settings().cors_origins == ["http://a.local"]


def test_production_rejects_default_secret(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("BITGUARD_JWT_SECRET", raising=False)
    s = Settings(env="production", jwt_secret="dev-only-insecure-secret-change-me-0123456789")
    with pytest.raises(RuntimeError):
        s.validate_for_runtime()


@pytest.mark.parametrize("scheme", ["postgres", "postgresql"])
def test_database_url_normalised_for_asyncpg(monkeypatch: pytest.MonkeyPatch, scheme: str) -> None:
    monkeypatch.setenv("BITGUARD_DATABASE_URL", f"{scheme}://u:p@dpg-abc:5432/db")
    assert Settings().database_url == "postgresql+asyncpg://u:p@dpg-abc:5432/db"
    monkeypatch.setenv("BITGUARD_DATABASE_URL", "postgresql+asyncpg://u:p@h/db")
    assert Settings().database_url == "postgresql+asyncpg://u:p@h/db"
