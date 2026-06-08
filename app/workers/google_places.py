"""
Google Places worker — SerpAPI Google Maps local search.
Docs: https://serpapi.com/google-maps-api

Search strategy:
  1. Primary:  "{business_name} {city}"  → name-match check → gmb_exists=True
  2. Fallback: "{category} {city}"       → top 3 as competitors, gmb_exists=False
     Fallback triggered when: zero results OR top result name doesn't match query.
"""
import json
import re
from difflib import SequenceMatcher

import structlog
from serpapi import GoogleSearch

from app.config import settings
from app.models.audit import GooglePlacesResult
from app.workers.celery_app import celery_app

logger = structlog.get_logger()

# Common Indian business filler words that don't identify a specific business
_STOPWORDS = {
    "apna", "aapna", "mera", "hamara", "apni", "tera",
    "shri", "shree", "sree", "new", "old", "the", "and", "or",
    "co", "ltd", "pvt", "india", "kumar", "enterprises",
}


def _name_matches(query_name: str, result_title: str) -> bool:
    """
    True if result_title is plausibly the same business as query_name.
    Uses two independent checks — either one passing is enough:
      1. difflib ratio >= 0.6  (catches "Sharma Sweets" vs "Sharma Sweets Bhopal")
      2. At least one significant word (len>=4, not stopword) from query
         appears in result title  (catches same-family names like "Sharma Mithai")
    """
    q = re.sub(r"[^a-z0-9 ]", "", query_name.lower()).strip()
    r = re.sub(r"[^a-z0-9 ]", "", result_title.lower()).strip()

    if SequenceMatcher(None, q, r).ratio() >= 0.65:
        return True

    q_words = {w for w in q.split() if len(w) >= 4 and w not in _STOPWORDS}
    r_words = {w for w in r.split() if len(w) >= 4 and w not in _STOPWORDS}
    if q_words and q_words & r_words:
        return True

    return False


_GMB_FIELDS = [
    "name", "rating", "reviews", "address", "phone", "website",
    "hours", "type", "photos",
]


def _gmb_completeness(place: dict) -> int:
    filled = sum(1 for f in _GMB_FIELDS if place.get(f))
    # Count as claimed only when unclaimed_listing is absent/false
    if not place.get("unclaimed_listing", False):
        filled += 1
    return round(filled / (len(_GMB_FIELDS) + 1) * 100)


def _is_claimed(place: dict) -> bool:
    # SerpAPI marks unclaimed listings with unclaimed_listing:true
    # Absence of that key means the business HAS claimed/verified the listing
    return not place.get("unclaimed_listing", False)


def _photos_count(place: dict) -> int:
    photos = place.get("photos", [])
    if isinstance(photos, list):
        return len(photos)
    if isinstance(photos, dict):
        return len(photos)
    return 0


def _parse_categories(place: dict) -> list[str]:
    raw = place.get("type", [])
    if isinstance(raw, list):
        return raw
    if isinstance(raw, str):
        return [t.strip() for t in raw.split(",") if t.strip()]
    return []


def _competitor_summary(place: dict) -> dict:
    """Slim dict used for competitors list — just the fields Groq needs."""
    return {
        "name":         place.get("title"),
        "rating":       place.get("rating"),
        "review_count": place.get("reviews"),
        "address":      place.get("address"),
        "photos_count": _photos_count(place),
    }


def _run_search(query: str) -> dict:
    """Execute one Google Maps search and log the raw response summary."""
    raw = GoogleSearch({
        "engine": "google_maps",
        "q": query,
        "type": "search",
        "api_key": settings.serpapi_key,
        "hl": "en",
        "gl": "in",
    }).get_dict()

    local_list  = raw.get("local_results") or []
    place_card  = raw.get("place_results")
    search_info = raw.get("search_information", {})
    error_info  = raw.get("error")

    # Log a structured summary — full raw is too large, so log first result keys + counts
    first_result_keys = list(local_list[0].keys()) if local_list else []
    logger.info(
        "google_places.raw",
        query=query,
        top_level_keys=list(raw.keys()),
        local_results_count=len(local_list),
        has_place_results=bool(place_card),
        place_results_keys=list(place_card.keys()) if place_card else [],
        first_result_keys=first_result_keys,
        search_info=search_info,
        serpapi_error=error_info,
        # Dump first result in full so we can inspect field names in logs
        first_result=json.dumps(local_list[0], default=str) if local_list else None,
    )
    return raw


# ── Public entry point ────────────────────────────────────────────────────────

def fetch_google_places(
    business_name: str,
    city: str | None,
    business_description: str | None = None,
) -> GooglePlacesResult:
    if not settings.serpapi_key:
        raise RuntimeError("SERPAPI_KEY is not set in .env")

    location = city.strip() if city else "India"

    # ── Primary search: business name + city ──────────────────────────────────
    primary_query = f"{business_name.strip()} {location}"
    logger.info("google_places.search_primary", query=primary_query)

    raw = _run_search(primary_query)
    local_list = raw.get("local_results") or []
    place_card = raw.get("place_results")

    # Pick the best candidate from primary results
    candidate = None
    if place_card:
        candidate = place_card
    elif local_list:
        candidate = local_list[0]

    # Name-match check — reject results that are clearly a different business
    if candidate:
        result_name = candidate.get("title", "")
        matched = _name_matches(business_name, result_name)
        logger.info(
            "google_places.name_check",
            query_name=business_name,
            result_name=result_name,
            matched=matched,
        )
        if matched:
            logger.info(
                "google_places.found",
                name=result_name,
                rating=candidate.get("rating"),
                reviews=candidate.get("reviews"),
            )
            return GooglePlacesResult(
                gmb_exists=True,
                place_id=candidate.get("place_id"),
                name=result_name,
                rating=candidate.get("rating"),
                review_count=candidate.get("reviews"),
                address=candidate.get("address"),
                phone=candidate.get("phone"),
                website=candidate.get("website"),
                categories=_parse_categories(candidate),
                photos_count=_photos_count(candidate),
                is_claimed=_is_claimed(candidate),
                gmb_completeness_score=_gmb_completeness(candidate),
            )

    # ── Fallback: zero results OR name didn't match → competitors only ────────
    fallback_term  = (business_description or "business").split()[:3]
    fallback_term  = " ".join(fallback_term).strip() or "business"
    fallback_query = f"{fallback_term} shop {location}"
    logger.warning(
        "google_places.no_match",
        primary_query=primary_query,
        candidate_name=candidate.get("title") if candidate else None,
        fallback_query=fallback_query,
    )

    raw2 = _run_search(fallback_query)
    fallback_list = raw2.get("local_results") or []

    # Sort by review_count desc — chains and popular outlets rise to top
    fallback_list.sort(key=lambda p: p.get("reviews") or 0, reverse=True)
    competitors = [_competitor_summary(p) for p in fallback_list[:3]]

    logger.info(
        "google_places.fallback_competitors",
        count=len(competitors),
        names=[c["name"] for c in competitors],
    )

    return GooglePlacesResult(
        gmb_exists=False,
        competitors=competitors,
    )


# ── Celery task wrapper ───────────────────────────────────────────────────────

@celery_app.task(bind=True, max_retries=2, default_retry_delay=10, name="workers.google_places")
def run_google_places(
    self,
    audit_id: str,
    business_name: str,
    location: str | None,
    business_description: str | None = None,
    context: dict | None = None,
) -> dict:
    log = logger.bind(audit_id=audit_id, business=business_name, worker="google_places")
    log.info("start")
    try:
        result = fetch_google_places(business_name, location, business_description)
        log.info("done", gmb_exists=result.gmb_exists, rating=result.rating, reviews=result.review_count)
        return result.model_dump()
    except Exception as exc:
        log.error("failed", error=str(exc))
        try:
            raise self.retry(exc=exc)
        except self.MaxRetriesExceededError:
            return GooglePlacesResult(error=str(exc)).model_dump()
