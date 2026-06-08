"""
Lighthouse worker.

Runs Lighthouse CLI via subprocess (requires: npm i -g lighthouse).
If CLI is not available, returns an empty LighthouseResult so the
chord can still complete — Groq will score web_performance from
crawler data instead.
"""
import json
import shutil
import subprocess

import structlog

from app.models.audit import LighthouseResult
from app.workers.celery_app import celery_app

logger = structlog.get_logger()


def _score(raw: float | None) -> int | None:
    return round(raw * 100) if raw is not None else None


def _parse_lhr(cats: dict, audits: dict) -> LighthouseResult:
    """Parse a Lighthouse Result (LHR) dict into our model."""
    return LighthouseResult(
        performance_score=_score(cats.get("performance", {}).get("score")),
        accessibility_score=_score(cats.get("accessibility", {}).get("score")),
        seo_score=_score(cats.get("seo", {}).get("score")),
        best_practices_score=_score(cats.get("best-practices", {}).get("score")),
        first_contentful_paint_s=round(
            audits.get("first-contentful-paint", {}).get("numericValue", 0) / 1000, 2
        ),
        largest_contentful_paint_s=round(
            audits.get("largest-contentful-paint", {}).get("numericValue", 0) / 1000, 2
        ),
        total_blocking_time_ms=audits.get("total-blocking-time", {}).get("numericValue"),
        cumulative_layout_shift=audits.get("cumulative-layout-shift", {}).get("numericValue"),
        is_mobile_friendly=cats.get("performance", {}).get("score", 0) >= 0.5,
    )


def _fetch_via_cli(url: str) -> LighthouseResult:
    cli = shutil.which("lighthouse")
    if not cli:
        logger.warning("lighthouse.skipped", reason="lighthouse CLI not found")
        return LighthouseResult()

    logger.info("lighthouse.cli", path=cli, url=url)
    proc = subprocess.run(
        [
            cli, url,
            "--output=json",
            "--output-path=stdout",
            "--chrome-flags=--headless --no-sandbox --disable-gpu",
            "--only-categories=performance,accessibility,seo,best-practices",
            "--quiet",
        ],
        capture_output=True,
        text=True,
        timeout=120,
    )
    if proc.returncode != 0:
        raise RuntimeError(f"Lighthouse CLI failed (exit {proc.returncode}): {proc.stderr[:500]}")

    data = json.loads(proc.stdout)
    return _parse_lhr(data.get("categories", {}), data.get("audits", {}))


def fetch_lighthouse(url: str) -> LighthouseResult:
    return _fetch_via_cli(url)


# ── Celery task wrapper ───────────────────────────────────────────────────────

@celery_app.task(bind=True, max_retries=0, name="workers.lighthouse")
def run_lighthouse(self, audit_id: str, url: str, context: dict | None = None) -> dict:
    log = logger.bind(audit_id=audit_id, url=url, worker="lighthouse")
    log.info("start")
    try:
        result = fetch_lighthouse(url)
        log.info("done", performance=result.performance_score)
        return result.model_dump()
    except Exception as exc:
        log.error("failed", error=str(exc))
        return LighthouseResult().model_dump()
