import socket
import ssl

from celery import Celery

from app.config import settings


def _redis_reachable(url: str) -> bool:
    """Quick TCP probe — returns False if Redis is not listening."""
    try:
        if url.startswith("rediss://") or url.startswith("redis://"):
            import re
            m = re.search(r"[@/]([^@/:]+):(\d+)", url)
            if not m:
                return False
            host, port = m.group(1), int(m.group(2))
            # Skip probe for localhost — it's never reachable in serverless envs
            if host in ("localhost", "127.0.0.1", "::1"):
                return False
            s = socket.create_connection((host, port), timeout=2)
            s.close()
            return True
    except Exception:
        return False
    return False


celery_app = Celery("ztgos")

_is_tls = settings.redis_url.startswith("rediss://")
_ssl_opts = {"ssl_cert_reqs": ssl.CERT_NONE} if _is_tls else {}
_eager = not _redis_reachable(settings.redis_url)

if _eager:
    import structlog
    structlog.get_logger().warning(
        "celery.eager_mode",
        reason="Redis not reachable — running tasks synchronously (no worker needed)",
    )

celery_app.conf.update(
    broker_url=settings.redis_url,
    result_backend=settings.redis_url,
    broker_use_ssl=_ssl_opts,
    redis_backend_use_ssl=_ssl_opts,
    task_serializer="json",
    result_serializer="json",
    accept_content=["json"],
    timezone="Asia/Kolkata",
    enable_utc=True,
    task_track_started=True,
    task_acks_late=True,
    worker_prefetch_multiplier=1,
    worker_pool="solo",
    # Eager mode: run tasks inline when Redis is unavailable (dev/demo)
    task_always_eager=_eager,
    task_eager_propagates=False,
    include=[
        "app.workers.lighthouse",
        "app.workers.google_places",
        "app.workers.instagram",
        "app.workers.crawler",
        "app.workers.report",
    ],
)
