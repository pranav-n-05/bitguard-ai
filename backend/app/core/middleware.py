"""Security headers and request-size limits."""

from collections.abc import Awaitable, Callable

from fastapi import Request, Response
from fastapi.responses import JSONResponse

from app.core.config import get_settings

SECURITY_HEADERS = {
    "X-Content-Type-Options": "nosniff",
    "X-Frame-Options": "DENY",
    "Referrer-Policy": "no-referrer",
    "Permissions-Policy": "geolocation=(), camera=(), microphone=()",
    "Cross-Origin-Opener-Policy": "same-origin",
    "Cross-Origin-Resource-Policy": "same-origin",
}
API_CSP = "default-src 'none'; frame-ancestors 'none'"
DOCS_CSP = (
    "default-src 'self'; script-src 'self' 'unsafe-inline' https://cdn.jsdelivr.net; style-src 'self' 'unsafe-inline' "
    "https://cdn.jsdelivr.net; img-src 'self' data: https://fastapi.tiangolo.com; frame-ancestors 'none'"
)


async def security_headers(request: Request, call_next: Callable[[Request], Awaitable[Response]]) -> Response:
    s = get_settings()
    length = request.headers.get("content-length")
    ctype = request.headers.get("content-type", "")
    if length and length.isdigit():
        limit = s.max_upload_mb * 1024 * 1024 if ctype.startswith("multipart/") else s.max_json_body_kb * 1024
        if int(length) > limit:
            return JSONResponse(
                {
                    "type": "https://bitguard.local/errors/payload_too_large",
                    "title": "Payload Too Large",
                    "status": 413,
                    "detail": f"Request body exceeds {limit} bytes",
                },
                status_code=413,
                media_type="application/problem+json",
            )
    response = await call_next(request)
    for k, v in SECURITY_HEADERS.items():
        response.headers.setdefault(k, v)
    response.headers.setdefault("Content-Security-Policy", DOCS_CSP if request.url.path.startswith("/api/docs") else API_CSP)
    if request.url.path.startswith("/api/"):
        response.headers.setdefault("Cache-Control", "no-store")
    if s.is_production:
        response.headers.setdefault("Strict-Transport-Security", "max-age=63072000; includeSubDomains")
    return response
