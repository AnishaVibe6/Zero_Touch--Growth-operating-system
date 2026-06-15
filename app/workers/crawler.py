"""
HTML crawler — Playwright (JS rendering) + BeautifulSoup (parsing).
Extracts on-page SEO, contact signals, and structural quality indicators.
"""
import re
import time

import structlog
from bs4 import BeautifulSoup

try:
    from playwright.sync_api import sync_playwright as _sync_playwright
    _PLAYWRIGHT_OK = True
except Exception:
    _PLAYWRIGHT_OK = False

from app.models.audit import CrawlerResult
from app.workers.celery_app import celery_app

logger = structlog.get_logger()

# Non-capturing prefix so findall returns full phone strings, not the group
_PHONE_RE = re.compile(r"(?:\+91[-\s]?)?[6-9]\d{9}")
_EMAIL_RE = re.compile(r"[a-zA-Z0-9._%+\-]+@[a-zA-Z0-9.\-]+\.[a-zA-Z]{2,}")
_WA_RE    = re.compile(r"wa\.me|whatsapp\.com", re.I)
_SOCIAL_RE = re.compile(r"(facebook|instagram|twitter|linkedin|youtube)\.com", re.I)


def _render(url: str) -> tuple[str, float, bool]:
    """Returns (html, load_time_s, has_ssl). Uses Playwright Chromium."""
    if not _PLAYWRIGHT_OK:
        raise RuntimeError("Playwright is not available in this environment")
    sync_playwright = _sync_playwright
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        page = browser.new_page(
            user_agent=(
                "Mozilla/5.0 (Linux; Android 11; Pixel 5) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/120.0.0.0 Mobile Safari/537.36"
            )
        )
        t0 = time.perf_counter()
        page.goto(url, wait_until="domcontentloaded", timeout=30_000)
        # Give JS a moment to inject dynamic content, then stop waiting
        try:
            page.wait_for_load_state("networkidle", timeout=5_000)
        except Exception:
            pass  # Best-effort; proceed with whatever loaded
        load_time = round(time.perf_counter() - t0, 2)
        html = page.content()
        browser.close()
    return html, load_time, url.startswith("https://")


def _keyword_in(soup: BeautifulSoup, *keywords: str) -> bool:
    text = soup.get_text(" ", strip=True).lower()
    hrefs = [a.get("href", "").lower() for a in soup.find_all("a", href=True)]
    return any(k in text or any(k in h for h in hrefs) for k in keywords)


# ── Public entry point ────────────────────────────────────────────────────────

def fetch_crawler(url: str) -> CrawlerResult:
    html, load_time, has_ssl = _render(url)
    soup = BeautifulSoup(html, "html.parser")

    all_hrefs = [a.get("href", "") for a in soup.find_all("a", href=True)]
    full_text = soup.get_text(" ", strip=True)

    meta_desc_tag = soup.find("meta", {"name": "description"})
    meta_desc = meta_desc_tag.get("content", "")[:160] if meta_desc_tag else None

    title_tag = soup.find("title")
    meta_title = title_tag.get_text(strip=True)[:100] if title_tag else None

    return CrawlerResult(
        has_ssl=has_ssl,
        has_contact_page=_keyword_in(soup, "contact", "संपर्क"),
        has_about_page=_keyword_in(soup, "about", "about us", "हमारे बारे"),
        has_whatsapp_link=any(_WA_RE.search(h) for h in all_hrefs),
        has_social_links=any(_SOCIAL_RE.search(h) for h in all_hrefs),
        meta_title=meta_title,
        meta_description=meta_desc,
        h1_tags=[h.get_text(strip=True) for h in soup.find_all("h1")][:5],
        broken_links_count=0,
        load_time_s=load_time,
        has_structured_data=bool(soup.find("script", {"type": "application/ld+json"})),
        phone_numbers=list({m.group() for m in _PHONE_RE.finditer(full_text)})[:5],
        emails=list({m.group() for m in _EMAIL_RE.finditer(full_text)})[:5],
        language=soup.find("html").get("lang", "unknown") if soup.find("html") else "unknown",
    )


# ── Celery task wrapper ───────────────────────────────────────────────────────

@celery_app.task(bind=True, max_retries=1, default_retry_delay=15, name="workers.crawler")
def run_crawler(self, audit_id: str, url: str, context: dict | None = None) -> dict:
    log = logger.bind(audit_id=audit_id, url=url, worker="crawler")
    log.info("start")
    try:
        result = fetch_crawler(url)
        log.info("done", load_time=result.load_time_s, has_ssl=result.has_ssl)
        return result.model_dump()
    except Exception as exc:
        log.error("failed", error=str(exc))
        try:
            raise self.retry(exc=exc)
        except self.MaxRetriesExceededError:
            return CrawlerResult(error=str(exc)).model_dump()
