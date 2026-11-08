"""Guards against dependency drift that only breaks the real (non-eager) Celery path."""

from app.workers.celery_app import celery_app


def test_celery_redis_transport_constructs() -> None:
    # Raises VersionMismatch when redis-py and kombu are incompatible.
    with celery_app.connection_for_write() as conn:
        conn.ensure_connection(max_retries=1, timeout=3)
        assert conn.connected
