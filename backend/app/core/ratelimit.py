from slowapi import Limiter
from slowapi.util import get_remote_address

from app.core.config import get_settings

_s = get_settings()
limiter = Limiter(
    key_func=get_remote_address,
    storage_uri=_s.rate_limit_storage or _s.redis_url,
    default_limits=[lambda: get_settings().default_rate_limit],
    headers_enabled=False,
    swallow_errors=True,
)


def login_limit() -> str:
    return get_settings().login_rate_limit
