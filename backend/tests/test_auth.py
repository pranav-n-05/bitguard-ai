from httpx import AsyncClient

from tests.conftest import PASSWORD, auth_headers


async def test_login_and_me(client: AsyncClient) -> None:
    h = await auth_headers(client, "analyst")
    r = await client.get("/api/v1/auth/me", headers=h)
    assert r.status_code == 200
    body = r.json()
    assert body["role_names"] == ["analyst"]
    assert "case.create" in body["permission_codes"] and "user.admin" not in body["permission_codes"]


async def test_bad_password_and_unknown_user_same_error(client: AsyncClient) -> None:
    a = await client.post("/api/v1/auth/login", json={"email": "analyst@test.local", "password": "wrong"})
    b = await client.post("/api/v1/auth/login", json={"email": "nobody@test.local", "password": "wrong"})
    assert a.status_code == b.status_code == 401
    assert a.json()["detail"] == b.json()["detail"] == "Invalid credentials"


async def test_lockout_after_repeated_failures(client: AsyncClient) -> None:
    for _ in range(5):
        await client.post("/api/v1/auth/login", json={"email": "viewer@test.local", "password": "wrong"})
    r = await client.post("/api/v1/auth/login", json={"email": "viewer@test.local", "password": PASSWORD})
    assert r.status_code == 401 and "locked" in r.json()["detail"]


async def test_missing_and_invalid_token(client: AsyncClient) -> None:
    assert (await client.get("/api/v1/auth/me")).status_code == 401
    r = await client.get("/api/v1/auth/me", headers={"Authorization": "Bearer not.a.jwt"})
    assert r.status_code == 401


async def test_refresh_rotation_and_reuse_detection(client: AsyncClient) -> None:
    r = await client.post("/api/v1/auth/login", json={"email": "analyst@test.local", "password": PASSWORD})
    first = r.json()
    r2 = await client.post("/api/v1/auth/refresh", json={"refresh_token": first["refresh_token"]})
    assert r2.status_code == 200
    second = r2.json()
    # Reusing the rotated token revokes the family, including the new one
    assert (await client.post("/api/v1/auth/refresh", json={"refresh_token": first["refresh_token"]})).status_code == 401
    assert (await client.post("/api/v1/auth/refresh", json={"refresh_token": second["refresh_token"]})).status_code == 401


async def test_access_token_not_accepted_as_refresh(client: AsyncClient) -> None:
    r = await client.post("/api/v1/auth/login", json={"email": "analyst@test.local", "password": PASSWORD})
    assert (await client.post("/api/v1/auth/refresh", json={"refresh_token": r.json()["access_token"]})).status_code == 401


async def test_logout_revokes(client: AsyncClient) -> None:
    r = (await client.post("/api/v1/auth/login", json={"email": "analyst@test.local", "password": PASSWORD})).json()
    h = {"Authorization": f"Bearer {r['access_token']}"}
    assert (await client.post("/api/v1/auth/logout", headers=h, json={"refresh_token": r["refresh_token"]})).status_code == 204
    assert (await client.post("/api/v1/auth/refresh", json={"refresh_token": r["refresh_token"]})).status_code == 401


async def test_health_and_request_id(client: AsyncClient) -> None:
    r = await client.get("/api/v1/health", headers={"X-Request-ID": "abc123"})
    assert r.status_code == 200 and r.json()["database"] is True
    assert r.headers["X-Request-ID"] == "abc123"
