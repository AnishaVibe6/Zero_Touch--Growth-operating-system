from fastapi import APIRouter, HTTPException

from app.models.audit import AuditRequest, AuditStatusResponse
from app.models.report import AuditReport
from app.services.orchestrator import launch_audit
from app.services.supabase_client import supabase_client

router = APIRouter()


@router.post("", response_model=dict, status_code=202)
def start_audit(request: AuditRequest):
    """Submit a new audit. Returns audit_id immediately; poll /audit/{id} for status."""
    audit_id = launch_audit(request)
    return {"audit_id": audit_id, "status": "pending"}


@router.get("/{audit_id}", response_model=AuditStatusResponse)
def get_audit_status(audit_id: str):
    row = supabase_client.get_audit(audit_id)
    if not row:
        raise HTTPException(status_code=404, detail="Audit not found")
    return AuditStatusResponse(**row)


@router.get("/{audit_id}/report", response_model=AuditReport)
def get_report(audit_id: str):
    row = supabase_client.get_report(audit_id)
    if not row:
        raise HTTPException(status_code=404, detail="Report not ready yet")
    audit = supabase_client.get_audit(audit_id)
    has_website = bool(audit and audit.get("website_url"))
    return AuditReport(**row, has_website=has_website)
