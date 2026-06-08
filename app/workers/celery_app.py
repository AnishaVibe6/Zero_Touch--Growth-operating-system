import ssl

from celery import Celery

from app.config import settings

celery_app = Celery("ztgos")

# Upstash (and any rediss://) requires SSL transport.
# Pass ssl_cert_reqs=CERT_NONE because Upstash free-tier uses SNI certs
# that Python's ssl module can't always verify without the full chain.
_is_tls = settings.redis_url.startswith("rediss://")
_ssl_opts = {"ssl_cert_reqs": ssl.CERT_NONE} if _is_tls else {}

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
    # solo pool avoids Python 3.14 + Windows spawn-pool incompatibility
    # where billiard child processes don't initialize Celery's _loc tuple
    worker_pool="solo",
    include=[
        "app.workers.lighthouse",
        "app.workers.google_places",
        "app.workers.instagram",
        "app.workers.crawler",
        "app.workers.report",
    ],
)
