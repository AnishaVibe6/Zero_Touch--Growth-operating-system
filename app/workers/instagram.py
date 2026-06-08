"""
Instagram worker — Instagram web_profile_info API (no login required).

Instaloader's GraphQL path now returns 403 for unauthenticated requests.
This worker uses the i.instagram.com mobile API endpoint, which returns
profile metadata + the 12 most recent posts in a single request.

If no handle is provided, the worker searches Google via SerpAPI using
'{business_name} {city} instagram' and extracts the first matching handle.
"""
import re
from datetime import datetime, timezone
from statistics import mean

import httpx
import structlog

from app.config import settings
from app.models.audit import InstagramResult
from app.workers.celery_app import celery_app

logger = structlog.get_logger()

RECENT_POSTS = 10

_PROFILE_URL = "https://i.instagram.com/api/v1/users/web_profile_info/"
_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (iPhone; CPU iPhone OS 17_0 like Mac OS X) "
        "AppleWebKit/605.1.15 (KHTML, like Gecko) "
        "Version/17.0 Mobile/15E148 Safari/604.1"
    ),
    "X-IG-App-ID": "936619743392459",
    "Accept": "*/*",
    "Accept-Language": "en-US,en;q=0.9",
    "Referer": "https://www.instagram.com/",
}


def _ts_to_dt(ts: int | None) -> datetime | None:
    if ts is None:
        return None
    return datetime.fromtimestamp(ts, tz=timezone.utc)


_IG_SKIP_PATHS = {"explore", "reels", "p", "tv", "stories", "accounts", "about", "blog", "legal"}


def _find_handle_via_search(business_name: str, city: str | None) -> str | None:
    """Use SerpAPI Google search to find an Instagram handle for a business."""
    if not settings.serpapi_key:
        return None
    try:
        from serpapi import GoogleSearch
        query = f"best {business_name} {city or ''} instagram".strip()
        results = GoogleSearch({
            "engine": "google",
            "q": query,
            "num": 5,
            "api_key": settings.serpapi_key,
        }).get_dict()
        for r in results.get("organic_results", []):
            link = r.get("link", "")
            m = re.match(r"https?://(?:www\.)?instagram\.com/([a-zA-Z0-9._]+)/?", link)
            if m and m.group(1) not in _IG_SKIP_PATHS:
                logger.info("instagram.handle_found_via_search", handle=m.group(1), query=query)
                return m.group(1)
    except Exception as exc:
        logger.warning("instagram.search_failed", error=str(exc))
    return None


# ── Public entry point ────────────────────────────────────────────────────────

def fetch_instagram(handle: str) -> InstagramResult:
    handle = handle.strip()
    # extract username from full Instagram URL (e.g. https://www.instagram.com/apna_sweets/?hl=en)
    if handle.startswith("http"):
        m = re.match(r"https?://(?:www\.)?instagram\.com/([a-zA-Z0-9._]+)", handle)
        handle = m.group(1) if m else handle
    handle = handle.lstrip("@").strip()
    log = logger.bind(handle=handle)
    log.info("instagram.start")

    try:
        resp = httpx.get(
            _PROFILE_URL,
            params={"username": handle},
            headers=_HEADERS,
            timeout=20,
            follow_redirects=True,
        )
    except Exception as exc:
        return InstagramResult(error=f"Request failed: {exc}")

    if resp.status_code == 404:
        return InstagramResult(error=f"Profile @{handle} not found")
    if resp.status_code != 200:
        return InstagramResult(error=f"Instagram API returned {resp.status_code}")

    try:
        user = resp.json()["data"]["user"]
    except Exception as exc:
        return InstagramResult(error=f"Unexpected API response shape: {exc}")

    if user is None:
        return InstagramResult(error=f"Profile @{handle} is private or does not exist")

    # ── Profile metadata ──────────────────────────────────────────────────────
    followers   = user.get("edge_followed_by", {}).get("count")
    following   = user.get("edge_follow",      {}).get("count")
    posts_count = user.get("edge_owner_to_timeline_media", {}).get("count")
    is_biz      = user.get("is_business_account", False)
    biz_cat     = user.get("business_category_name")
    external_url = user.get("external_url") or ""

    log.info("instagram.profile_ok", followers=followers)

    # ── Recent posts ──────────────────────────────────────────────────────────
    edges = (
        user.get("edge_owner_to_timeline_media", {})
            .get("edges", [])
    )[:RECENT_POSTS]

    last_post_date: datetime | None = None
    avg_likes = avg_comments = engagement_rate = post_freq = 0.0
    posts_analysed = len(edges)

    if edges:
        nodes = [e["node"] for e in edges]
        last_post_date = _ts_to_dt(nodes[0].get("taken_at_timestamp"))

        likes_list    = [n.get("edge_media_preview_like", {}).get("count", 0) for n in nodes]
        comments_list = [n.get("edge_media_to_comment",   {}).get("count", 0) for n in nodes]

        avg_likes    = round(mean(likes_list),    1)
        avg_comments = round(mean(comments_list), 1)

        if followers:
            engagement_rate = round((avg_likes + avg_comments) / followers * 100, 4)

        if len(nodes) >= 2:
            first_ts = nodes[0].get("taken_at_timestamp", 0)
            last_ts  = nodes[-1].get("taken_at_timestamp", 0)
            span_days = max((first_ts - last_ts) / 86400, 1)
            post_freq = round(len(nodes) / (span_days / 7), 2)

        log.info("instagram.posts_ok",
                 analysed=posts_analysed,
                 last=last_post_date.isoformat() if last_post_date else None,
                 avg_likes=avg_likes)

    return InstagramResult(
        username=user.get("username"),
        followers=followers,
        following=following,
        posts_count=posts_count,
        is_verified=user.get("is_verified"),
        is_business_account=is_biz,
        business_category=biz_cat,
        bio=user.get("biography"),
        has_bio_link=bool(external_url),
        has_contact_button=is_biz,
        last_post_date=last_post_date,
        posts_analysed=posts_analysed,
        avg_likes=avg_likes,
        avg_comments=avg_comments,
        engagement_rate=engagement_rate,
        post_frequency_per_week=post_freq,
    )


# ── Celery task wrapper ───────────────────────────────────────────────────────

@celery_app.task(bind=True, max_retries=2, default_retry_delay=30, name="workers.instagram")
def run_instagram(self, audit_id: str, handle: str | None, context: dict | None = None) -> dict:
    log = logger.bind(audit_id=audit_id, handle=handle, worker="instagram")
    log.info("start")
    try:
        resolved = handle
        if not resolved and context:
            resolved = _find_handle_via_search(
                context.get("business_name", ""),
                context.get("city"),
            )
        if not resolved:
            return InstagramResult(error="instagram skipped — no handle provided or found").model_dump()
        result = fetch_instagram(resolved)
        log.info("done", followers=result.followers, engagement=result.engagement_rate)
        return result.model_dump()
    except Exception as exc:
        log.error("failed", error=str(exc))
        try:
            raise self.retry(exc=exc)
        except self.MaxRetriesExceededError:
            return InstagramResult(error=str(exc)).model_dump()
