"""BITGUARD AI FastAPI application."""

import uuid
from collections.abc import Awaitable, Callable

import structlog
from fastapi import FastAPI, Request, Response
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from slowapi.errors import RateLimitExceeded
from slowapi.middleware import SlowAPIMiddleware

from app.api.v1 import (
    addresses,
    admin,
    ai,
    alerts,
    analytics,
    auth,
    graph,
    ingestion,
    investigations,
    network,
    reports,
    system,
    transactions,
)
from app.core.config import get_settings
from app.core.errors import register_error_handlers
from app.core.logging import configure_logging, get_logger
from app.core.middleware import security_headers
from app.core.ratelimit import limiter
from app.spa import mount_spa

configure_logging()
log = get_logger("bitguard.http")

app = FastAPI(
    title="BITGUARD AI",
    version="0.1.0",
    description="Offline Bitcoin transaction & network-metadata intelligence platform (SIH26146). "
    "All outputs are investigative leads, not legal conclusions.",
    openapi_url="/api/v1/openapi.json",
    docs_url="/api/docs",
    redoc_url=None,
)
settings = get_settings()
settings.validate_for_runtime()
app.state.limiter = limiter
app.add_middleware(SlowAPIMiddleware)
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins,
    allow_credentials=False,
    allow_methods=["GET", "POST", "PATCH", "DELETE"],
    allow_headers=["Authorization", "Content-Type", "X-Request-ID"],
)


@app.middleware("http")
async def request_context(request: Request, call_next: Callable[[Request], Awaitable[Response]]) -> Response:
    rid = request.headers.get("X-Request-ID") or uuid.uuid4().hex
    rid = rid[:64]
    request.state.request_id = rid
    structlog.contextvars.clear_contextvars()
    structlog.contextvars.bind_contextvars(request_id=rid, correlation_id=request.headers.get("X-Correlation-ID", rid)[:64])
    response = await call_next(request)
    response.headers["X-Request-ID"] = rid
    log.info("request", method=request.method, path=request.url.path, status=response.status_code)
    return response


register_error_handlers(app)
app.middleware("http")(security_headers)


@app.exception_handler(RateLimitExceeded)
async def _rate_limited(request: Request, exc: RateLimitExceeded) -> JSONResponse:
    return JSONResponse(
        {
            "type": "https://bitguard.local/errors/rate_limited",
            "title": "Too Many Requests",
            "status": 429,
            "detail": f"Rate limit exceeded: {exc.detail}",
        },
        status_code=429,
        media_type="application/problem+json",
    )


for r in (
    system.router,
    auth.router,
    ingestion.router,
    transactions.router,
    addresses.router,
    network.router,
    analytics.router,
    graph.router,
    ai.router,
    alerts.router,
    investigations.router,
    reports.router,
    admin.router,
):
    app.include_router(r, prefix="/api/v1")

if settings.static_dir and settings.static_dir.is_dir():
    mount_spa(app, settings.static_dir)  # must be last: its catch-all route would shadow later routes
