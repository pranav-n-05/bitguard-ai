from pathlib import Path

from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient

from app.spa import mount_spa


async def test_spa_fallback_and_api_404(tmp_path: Path) -> None:
    (tmp_path / "assets").mkdir()
    (tmp_path / "assets" / "app.js").write_text("console.log(1)")
    (tmp_path / "index.html").write_text("<html>spa</html>")
    (tmp_path / "favicon.svg").write_text("<svg/>")
    secret = tmp_path.parent / "secret.txt"
    secret.write_text("TOP")
    app = FastAPI()

    @app.get("/api/v1/ping")
    async def ping() -> dict[str, bool]:
        return {"ok": True}

    mount_spa(app, tmp_path)
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as c:
        assert (await c.get("/api/v1/ping")).json() == {"ok": True}
        assert "spa" in (await c.get("/alerts/123")).text  # client-side route on reload
        assert (await c.get("/assets/app.js")).text == "console.log(1)"
        assert (await c.get("/favicon.svg")).text == "<svg/>"
        assert (await c.get("/api/v1/missing")).status_code == 404  # API misses are not swallowed by the SPA
        assert "TOP" not in (await c.get("/..%2fsecret.txt")).text  # no path traversal
        assert "TOP" not in (await c.get("/../secret.txt")).text
