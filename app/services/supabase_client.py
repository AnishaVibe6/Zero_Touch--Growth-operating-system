from datetime import datetime
from typing import Any

import structlog
from supabase import create_client

from app.config import settings
from app.models.audit import AuditRequest
from app.models.report import AuditReport

logger = structlog.get_logger()


class SupabaseClient:
    def __init__(self) -> None:
        self._db = create_client(
            settings.supabase_url,
            settings.supabase_service_key,
        )

    # ── audits ────────────────────────────────────────────────────────────────

    def create_audit(self, audit_id: str, request: AuditRequest) -> None:
        row = {
            "id": audit_id,
            "business_name": request.business_name,
            "city": request.city,
            "category": request.business_description,          # legacy column name
            "business_description": request.business_description,
            "website_url": str(request.website_url) if request.website_url else None,
            "instagram_handle": request.instagram_handle,
            "monthly_ad_spend": float(request.monthly_ad_spend) if request.monthly_ad_spend else None,
            "status": "pending",
            "created_at": datetime.utcnow().isoformat(),
        }
        self._db.table("audits").insert(row).execute()

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
        self._db.table("audits").update(payload).eq("id", audit_id).execute()

    def get_audit(self, audit_id: str) -> dict | None:
        resp = self._db.table("audits").select("*").eq("id", audit_id).single().execute()
        return resp.data

    # ── reports ───────────────────────────────────────────────────────────────

    def save_report(self, audit_id: str, report: AuditReport) -> None:
        self._db.table("reports").upsert({
            "audit_id": audit_id,
            "overall_score": report.overall_score,
            "dimensions": report.dimensions.model_dump(mode="json"),
            "revenue_loss_low": report.revenue_loss_low,
            "revenue_loss_high": report.revenue_loss_high,
            "campaign_preview": report.campaign_preview.model_dump(mode="json"),
        }).execute()

    def get_report(self, audit_id: str) -> dict | None:
        resp = (
            self._db.table("reports")
            .select("*")
            .eq("audit_id", audit_id)
            .single()
            .execute()
        )
        return resp.data


supabase_client = SupabaseClient()
