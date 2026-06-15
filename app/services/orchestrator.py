"""
Audit orchestrator — fans out 4 Celery tasks in parallel via a chord,
then fires the report worker once all complete.
"""
import uuid
from datetime import datetime

import structlog
from celery import chord

from app.models.audit import AuditRequest, BusinessContext, MergedAuditData
from app.services.supabase_client import supabase_client
from app.workers.crawler import run_crawler
from app.workers.google_places import run_google_places
from app.workers.instagram import run_instagram
from app.workers.lighthouse import run_lighthouse
from app.workers.report import build_report, noop

logger = structlog.get_logger()


def _merge_results(audit_id: str, request: AuditRequest, results: list[dict]) -> dict:
    lighthouse, google_places, instagram, crawler = results
    return MergedAuditData(
        audit_id=audit_id,
        request=request,
        lighthouse=lighthouse,
        google_places=google_places,
        instagram=instagram,
        crawler=crawler,
    ).model_dump()


def launch_audit(request: AuditRequest) -> str:
    audit_id = str(uuid.uuid4())
    log = logger.bind(audit_id=audit_id)

    supabase_client.create_audit(audit_id=audit_id, request=request)

    url = str(request.website_url) if request.website_url else None

    ctx = BusinessContext(
        business_name=request.business_name,
        city=request.city,
        business_description=request.business_description,
        website_url=url,
        instagram_handle=request.instagram_handle,
        monthly_ad_spend=float(request.monthly_ad_spend) if request.monthly_ad_spend else None,
    ).model_dump()

    parallel_tasks = [
        run_lighthouse.s(audit_id, url, ctx) if url else noop.s(audit_id, "lighthouse"),
        run_google_places.s(audit_id, request.business_name, request.city, request.business_description, ctx),
        run_instagram.s(audit_id, request.instagram_handle, ctx),   # always runs; handles None handle
        run_crawler.s(audit_id, url, ctx) if url else noop.s(audit_id, "crawler"),
    ]

    supabase_client.update_audit_status(audit_id, "running")

    pipeline = chord(parallel_tasks)(
        build_report.s(audit_id, request.model_dump(mode="json"))
    )

    log.info("audit.launched")
    return audit_id


