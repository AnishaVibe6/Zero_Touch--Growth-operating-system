"""
Report worker — chord callback, invoked after all 4 audit workers complete.
Celery passes the list of worker results as the first positional argument.
"""
import structlog

from app.models.audit import AuditRequest, MergedAuditData
from app.services.claude_report import generate_report
from app.services.supabase_client import supabase_client
from app.workers.celery_app import celery_app

logger = structlog.get_logger()


@celery_app.task(name="workers.noop")
def noop(audit_id: str, worker_name: str) -> dict:
    """Placeholder result for skipped workers (no URL / no handle provided)."""
    return {"error": f"{worker_name} skipped — no input provided"}


@celery_app.task(name="workers.report")
def build_report(results: list, audit_id: str, request_data: dict) -> dict:
    """
    results: [lighthouse_dict, google_places_dict, instagram_dict, crawler_dict]
    """
    log = logger.bind(audit_id=audit_id, worker="report")
    log.info("start")

    try:
        supabase_client.update_audit_status(audit_id, "running_report")

        lighthouse, google_places, instagram, crawler = results

        merged_data = MergedAuditData(
            audit_id=audit_id,
            request=AuditRequest(**request_data),
            lighthouse=lighthouse,
            google_places=google_places,
            instagram=instagram,
            crawler=crawler,
        )

        report = generate_report(merged_data)
        supabase_client.save_report(audit_id, report)
        supabase_client.update_audit_status(audit_id, "completed")
        log.info("done", overall_score=report.overall_score)
        return report.model_dump(mode="json")
    except Exception as exc:
        log.error("failed", error=str(exc))
        supabase_client.update_audit_status(audit_id, "failed", error=str(exc))
        raise
