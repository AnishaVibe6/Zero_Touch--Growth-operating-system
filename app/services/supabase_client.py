from datetime import datetime
from typing import Any

import structlog
from supabase import create_client

from app.config import settings
from app.models.audit import AuditRequest
from app.models.report import AuditReport

logger = structlog.get_logger()

# In-memory fallback store — used when Supabase is not configured
_mem_audits: dict[str, dict] = {}
_mem_reports: dict[str, dict] = {}


def _is_real_supabase() -> bool:
    url = settings.supabase_url or ""
    key = settings.supabase_service_key or ""
    return (
        url.startswith("https://")
        and "supabase.co" in url
        and "placeholder" not in url
        and len(key) > 40
    )


class SupabaseClient:
    def __init__(self) -> None:
        self._db = None

    def _client(self):
        if self._db is None:
            self._db = create_client(settings.supabase_url, settings.supabase_service_key)
        return self._db

    # ── audits ────────────────────────────────────────────────────────────────

    def create_audit(self, audit_id: str, request: AuditRequest) -> None:
        row = {
            "id": audit_id,
            "business_name": request.business_name,
            "city": request.city,
            "category": request.business_description,
            "business_description": request.business_description,
            "website_url": str(request.website_url) if request.website_url else None,
            "instagram_handle": request.instagram_handle,
            "monthly_ad_spend": float(request.monthly_ad_spend) if request.monthly_ad_spend else None,
            "status": "pending",
            "created_at": datetime.utcnow().isoformat(),
        }
        if _is_real_supabase():
            self._client().table("audits").insert(row).execute()
        else:
            logger.info("supabase.fallback", action="create_audit", audit_id=audit_id)
            _mem_audits[audit_id] = row

    def update_audit_status(
        self,
        audit_id: str,
        status: str,
        error: str | None = None,
    ) -> None:
        payload: dict[str, Any] = {"status": status}
        if error:
            payload["error"] = error
        if status in ("completed", "failed"):
            payload["completed_at"] = datetime.utcnow().isoformat()
        if _is_real_supabase():
            self._client().table("audits").update(payload).eq("id", audit_id).execute()
        else:
            if audit_id in _mem_audits:
                _mem_audits[audit_id].update(payload)

    def get_audit(self, audit_id: str) -> dict | None:
        if _is_real_supabase():
            resp = self._client().table("audits").select("*").eq("id", audit_id).single().execute()
            return resp.data
        return _mem_audits.get(audit_id)

    # ── reports ───────────────────────────────────────────────────────────────

    def save_report(self, audit_id: str, report: AuditReport) -> None:
        row = {
            "audit_id": audit_id,
            "overall_score": report.overall_score,
            "dimensions": report.dimensions.model_dump(mode="json"),
            "revenue_loss_low": report.revenue_loss_low,
            "revenue_loss_high": report.revenue_loss_high,
            "campaign_preview": report.campaign_preview.model_dump(mode="json"),
        }
        if _is_real_supabase():
            self._client().table("reports").upsert(row).execute()
        else:
            _mem_reports[audit_id] = row

    def get_report(self, audit_id: str) -> dict | None:
        if _is_real_supabase():
            resp = (
                self._client().table("reports")
                .select("*")
                .eq("audit_id", audit_id)
                .single()
                .execute()
            )
            return resp.data
        return _mem_reports.get(audit_id)


supabase_client = SupabaseClient()
