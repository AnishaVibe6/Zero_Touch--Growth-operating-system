"""
Campaign package builder.

Primary path  : POST full audit data to the n8n webhook (N8N_WEBHOOK_URL).
                n8n handles its own workflow and returns a campaign package dict.
Fallback path : direct Groq call when n8n is not configured, times out, or
                returns a non-2xx response.

Usage:
    from ai.campaign_package_builder import generate_campaign_package
    package = generate_campaign_package(merged, report)
"""
import json
import sys
from pathlib import Path

import httpx
import structlog

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.config import settings
from app.models.audit import MergedAuditData
from app.models.report import AuditReport

logger = structlog.get_logger()

_N8N_TIMEOUT = 30  # seconds — n8n workflows can be slow; keep generous


# ── Payload builder ───────────────────────────────────────────────────────────

def _build_payload(merged: MergedAuditData, report: AuditReport) -> dict:
    """Serialize the full audit context into a JSON-safe dict for n8n / Groq."""
    cp = report.campaign_preview
    return {
        "audit_id": str(report.audit_id),
        "business": {
            "name":         merged.request.business_name,
            "city":         merged.request.city,
            "description":  merged.request.business_description,
            "website_url":  str(merged.request.website_url) if merged.request.website_url else None,
            "instagram":    merged.request.instagram_handle,
            "ad_spend_inr": float(merged.request.monthly_ad_spend) if merged.request.monthly_ad_spend else 0,
        },
        "scores": {
            "overall":         report.overall_score,
            "local_seo":       report.dimensions.local_seo.score,
            "web_performance": report.dimensions.web_performance.score,
            "social_presence": report.dimensions.social_presence.score,
            "website_quality": report.dimensions.website_quality.score,
        },
        "revenue": {
            "loss_low":           report.revenue_loss_low,
            "loss_high":          report.revenue_loss_high,
            "current_monthly":    cp.current_monthly_revenue,
            "projected_monthly":  cp.projected_monthly_revenue,
            "additional":         cp.estimated_additional_revenue,
        },
        "campaign": cp.model_dump(mode="json"),
        "workers": {
            "google_places": merged.google_places.model_dump(mode="json"),
            "instagram":     merged.instagram.model_dump(mode="json"),
            "crawler":       merged.crawler.model_dump(mode="json"),
        },
    }


# ── n8n primary call ──────────────────────────────────────────────────────────

def _call_n8n(payload: dict, log) -> dict:
    """POST payload to n8n webhook. Raises on timeout or HTTP error."""
    resp = httpx.post(
        settings.n8n_webhook_url,
        json=payload,
        timeout=_N8N_TIMEOUT,
        headers={"Content-Type": "application/json"},
    )
    resp.raise_for_status()
    log.info("n8n.done", status=resp.status_code)
    return resp.json()


# ── Groq fallback ─────────────────────────────────────────────────────────────

def _groq_fallback(payload: dict, log) -> dict:
    """
    Generate a campaign package directly via Groq when n8n is unavailable.
    Returns a dict with the same top-level keys n8n is expected to return.
    """
    from groq import Groq

    client = Groq(api_key=settings.groq_api_key)
    biz      = payload["business"]
    scores   = payload["scores"]
    campaign = payload["campaign"]

    prompt = (
        f"Business: {biz['name']} in {biz['city']} — {biz['description']}\n"
        f"Overall audit score: {scores['overall']}/100\n"
        f"Worst dimension: {min(scores, key=lambda k: scores[k] if k != 'overall' else 999)}\n"
        f"Campaign channel: {campaign.get('channel')}\n"
        f"Monthly ad budget: Rs.{biz['ad_spend_inr']:,.0f}\n\n"
        "Generate a campaign package JSON with these exact keys:\n"
        "  summary         — one paragraph campaign strategy specific to this business\n"
        "  ad_variations   — 3 extra ad copy objects (headline, description, display_url) "
        "                    beyond the ones already generated\n"
        "  whatsapp_templates — 2 WhatsApp broadcast message strings for this business\n"
        "  week1_checklist — 5 day-by-day task strings for the first week\n"
        "All content must mention the business name and city. No generic phrases. "
        "Return valid JSON only."
    )

    log.info("groq_fallback.start", model=settings.groq_model)
    resp = client.chat.completions.create(
        model=settings.groq_model,
        max_tokens=1024,
        messages=[{"role": "user", "content": prompt}],
        response_format={"type": "json_object"},
    )
    result = json.loads(resp.choices[0].message.content)
    log.info("groq_fallback.done")
    return result


# ── Public entry point ────────────────────────────────────────────────────────

def generate_campaign_package(merged: MergedAuditData, report: AuditReport) -> dict:
    """
    Build a campaign package for a completed audit.

    Tries the n8n webhook first (N8N_WEBHOOK_URL in .env).
    Falls back to a direct Groq call on timeout, HTTP error, or if the
    webhook URL is not configured.

    Returns the campaign package dict on success, or
    {"error": "...", "source": "..."} if both paths fail.
    """
    log     = logger.bind(audit_id=str(report.audit_id))
    payload = _build_payload(merged, report)

    # ── Primary: n8n webhook ──────────────────────────────────────────────────
    if settings.n8n_webhook_url:
        try:
            log.info("n8n.start", url=settings.n8n_webhook_url)
            return _call_n8n(payload, log)
        except httpx.TimeoutException:
            log.warning("n8n.timeout", timeout_s=_N8N_TIMEOUT)
        except httpx.HTTPStatusError as exc:
            log.warning("n8n.http_error", status=exc.response.status_code)
        except Exception as exc:
            log.warning("n8n.failed", error=str(exc))
    else:
        log.info("n8n.skipped", reason="N8N_WEBHOOK_URL not set")

    # ── Fallback: direct Groq call ────────────────────────────────────────────
    log.info("groq_fallback.triggered")
    try:
        return _groq_fallback(payload, log)
    except Exception as exc:
        log.error("groq_fallback.failed", error=str(exc))
        return {"error": str(exc), "source": "groq_fallback"}
