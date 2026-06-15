"""
Profile detector — runs once per audit after all workers complete.

Given merged worker output + business_description free text:
  1. Calls Groq (one small extraction call) to parse structured context from the description.
  2. Detects profile_type from worker signals (instagram_first / traditional / hybrid).
  3. Looks up the closest benchmark from ai/category_benchmarks.py.
  4. Identifies the single biggest_gap via priority-ordered rules on worker data.
  5. Returns a ProfileContext object combining everything.
"""
import json
import sys
from pathlib import Path
from typing import Literal, Optional

import structlog
from groq import Groq
from pydantic import BaseModel

# Make project root importable when running this file directly
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from ai.category_benchmarks import CategoryBenchmark, get_closest_benchmark
from app.config import settings
from app.models.audit import MergedAuditData

logger = structlog.get_logger()

_client = Groq(api_key=settings.groq_api_key or "demo-mode-no-key")

# ── Output models ─────────────────────────────────────────────────────────────

class ExtractedContext(BaseModel):
    category: str
    subcategory: str
    business_model: Literal["home_based", "shop_based", "online_only", "hybrid"]
    product_or_service: Literal["product", "service", "both"]
    target_customer: str
    is_instagram_sellable: bool


class ProfileContext(BaseModel):
    # Groq-extracted fields
    extracted: ExtractedContext
    # Rule-based signals
    profile_type: Literal["instagram_first", "traditional", "hybrid"]
    biggest_gap: str          # machine-readable key, e.g. "no_gmb_listing"
    biggest_gap_reason: str   # one human sentence explaining the business impact
    # Benchmark data
    benchmark_key: str        # matched key from BENCHMARKS dict, or "generic"
    benchmark: dict           # full CategoryBenchmark dict


# ── Groq extraction tool ───────────────────────────────────────────────────────

_EXTRACT_TOOL = {
    "type": "function",
    "function": {
        "name": "submit_business_profile",
        "description": "Submit the structured business profile extracted from the description.",
        "parameters": {
            "type": "object",
            "properties": {
                "category": {
                    "type": "string",
                    "description": (
                        "Short canonical category name in English. "
                        "Use common Indian MSME labels: sweet shop, restaurant, salon, clinic, "
                        "gym, bakery, jewellery, pharmacy, coaching, hotel, travel agency, etc."
                    ),
                },
                "subcategory": {
                    "type": "string",
                    "description": (
                        "More specific label within the category. "
                        "E.g. category=restaurant → subcategory=South Indian vegetarian restaurant. "
                        "E.g. category=clinic → subcategory=general physician clinic."
                    ),
                },
                "business_model": {
                    "type": "string",
                    "enum": ["home_based", "shop_based", "online_only", "hybrid"],
                    "description": (
                        "home_based: operates from the owner's home. "
                        "shop_based: physical storefront or clinic. "
                        "online_only: sells entirely online, no physical counter. "
                        "hybrid: both physical and online."
                    ),
                },
                "product_or_service": {
                    "type": "string",
                    "enum": ["product", "service", "both"],
                    "description": "Whether the business sells physical products, provides services, or both.",
                },
                "target_customer": {
                    "type": "string",
                    "description": (
                        "One short phrase describing the primary customer. "
                        "E.g. 'walk-in families', 'working professionals', 'wedding clients', "
                        "'students preparing for competitive exams'."
                    ),
                },
                "is_instagram_sellable": {
                    "type": "boolean",
                    "description": (
                        "True if the product or service is highly visual and Instagram-worthy — "
                        "food, fashion, interiors, events, beauty. "
                        "False for utilities, hardware, repair services, logistics."
                    ),
                },
            },
            "required": [
                "category", "subcategory", "business_model",
                "product_or_service", "target_customer", "is_instagram_sellable",
            ],
        },
    },
}

_EXTRACT_SYSTEM = (
    "You are a business analyst specialising in Indian MSMEs. "
    "You receive a short free-text description of a business and extract a structured profile. "
    "Be concise and use common Indian business terminology. "
    "If the description is vague, make a reasonable inference — never refuse to answer."
)


def _coerce_args(args: dict) -> dict:
    """Coerce string booleans to real booleans.

    Groq occasionally returns boolean fields as JSON strings ("true"/"false")
    which causes a 400 tool validation error. Fixing post-parse is the
    cleanest recovery path since we can't control the server-side validator.
    """
    for k, v in args.items():
        if isinstance(v, str) and v.lower() in ("true", "false"):
            args[k] = v.lower() == "true"
    return args


def _extract_context_via_groq(
    business_name: str,
    business_description: str,
    city: Optional[str],
) -> ExtractedContext:
    """Call Groq once to parse the free-text description into a structured profile.

    On 400 validation errors (Groq rejects its own output), we parse the
    failed_generation field from the error body and coerce string booleans,
    then construct the model directly from the recovered JSON.
    """
    import re as _re

    city_hint = f" in {city}" if city else ""
    prompt = (
        f"Business: {business_name}{city_hint}\n"
        f"Description: {business_description}\n\n"
        "Extract the structured business profile. "
        "is_instagram_sellable MUST be a JSON boolean true or false, never a string."
    )
    try:
        response = _client.chat.completions.create(
            model=settings.groq_model,
            max_tokens=256,
            temperature=0,
            tools=[_EXTRACT_TOOL],
            tool_choice={"type": "function", "function": {"name": "submit_business_profile"}},
            messages=[
                {"role": "system", "content": _EXTRACT_SYSTEM},
                {"role": "user",   "content": prompt},
            ],
        )
        args = json.loads(response.choices[0].message.tool_calls[0].function.arguments)
        return ExtractedContext(**_coerce_args(args))
    except Exception as exc:
        # Groq 400: try to salvage the failed_generation JSON from the error body
        err_str = str(exc)
        m = _re.search(r"failed_generation['\"]:\s*['\"](<function.*?</function>|.*?)['\"]", err_str)
        if m:
            raw = m.group(1)
            # Strip <function=...> wrapper if present
            raw = _re.sub(r"<function=[^>]+>|</function>", "", raw).strip()
            try:
                args = json.loads(raw)
                return ExtractedContext(**_coerce_args(args))
            except Exception:
                pass
        raise


def _fallback_context(business_description: Optional[str]) -> ExtractedContext:
    """Return a generic context when no description is provided or Groq is unavailable."""
    return ExtractedContext(
        category="local business",
        subcategory="general retail or service",
        business_model="shop_based",
        product_or_service="both",
        target_customer="walk-in local customers",
        is_instagram_sellable=False,
    )


# ── Profile type detection ─────────────────────────────────────────────────────

def _detect_profile_type(
    merged: MergedAuditData,
) -> Literal["instagram_first", "traditional", "hybrid"]:
    """
    instagram_first : strong Instagram (>1 000 followers) but no website.
    hybrid          : meaningful Instagram presence AND a website.
    traditional     : website/GMB-driven with little or no social presence.
    """
    has_website  = bool(merged.request.website_url)
    ig_ok        = not bool(merged.instagram.error)
    ig_followers = (merged.instagram.followers or 0) if ig_ok else 0
    gmb_active   = merged.google_places.gmb_exists

    if ig_followers > 1000 and not has_website:
        return "instagram_first"
    if ig_followers > 500 and has_website:
        return "hybrid"
    return "traditional"


# ── Biggest gap detector ───────────────────────────────────────────────────────

_GAP_RULES: list[tuple[str, str]] = []  # built dynamically per audit


def _detect_biggest_gap(merged: MergedAuditData) -> tuple[str, str]:
    """
    Priority-ordered rule scan across all worker data.
    Returns (gap_key, gap_reason) — the single most critical problem.

    Priority rationale (Indian MSME context):
      Google Maps drives walk-in traffic more than any other channel, so GMB gaps
      rank highest. Website absence ranks second for trust/conversion. Then rating,
      reviews, speed, WhatsApp (critical for India), SSL, social.
    """
    gp  = merged.google_places
    ig  = merged.instagram
    cr  = merged.crawler
    req = merged.request
    has_website = bool(req.website_url)

    # 1 — No GMB listing at all
    if not gp.gmb_exists:
        return (
            "no_gmb_listing",
            "Business has no Google Maps listing — 73% of local buyers in India check Maps before visiting.",
        )

    # 2 — No website
    if not has_website:
        return (
            "no_website",
            "No website detected — businesses with even a simple site get 3× more online inquiries than those without.",
        )

    # 3 — GMB exists but unclaimed
    if gp.is_claimed is False:
        return (
            "unclaimed_gmb",
            "Google Maps listing exists but is unclaimed — you cannot respond to reviews, add photos, or post updates.",
        )

    # 4 — Very few reviews
    review_count = gp.review_count or 0
    if review_count < 20:
        return (
            "low_reviews",
            f"Only {review_count} Google review{'s' if review_count != 1 else ''} — customers need at least 50 to trust a local business.",
        )

    # 5 — Poor rating
    if gp.rating is not None and gp.rating < 3.5:
        return (
            "poor_rating",
            f"Google rating is {gp.rating:.1f}★ — below 3.8★ causes 70% of searchers to choose a competitor instead.",
        )

    # 6 — Slow website (mobile 4G)
    if cr.load_time_s is not None and cr.load_time_s > 4.0:
        return (
            "slow_website",
            f"Website loads in {cr.load_time_s:.1f}s — 53% of mobile users abandon pages that take over 3s to load.",
        )

    # 7 — No WhatsApp link (critical for Indian MSMEs)
    if has_website and cr.has_whatsapp_link is False:
        return (
            "no_whatsapp",
            "No WhatsApp click-to-chat link on website — 68% of Indian mobile customers prefer WhatsApp for first contact.",
        )

    # 8 — No SSL
    if has_website and cr.has_ssl is False:
        return (
            "no_ssl",
            "Website runs on HTTP, not HTTPS — browsers show a 'Not Secure' warning that drives visitors away immediately.",
        )

    # 9 — Low Instagram following (only flag when no error, meaning account genuinely small)
    ig_ok = not bool(ig.error)
    if ig_ok and (ig.followers is None or ig.followers < 100):
        return (
            "low_social",
            "Very few Instagram followers — social proof is missing, making it hard for new customers to discover and trust you.",
        )

    # 10 — Low engagement despite follower count
    if ig_ok and ig.engagement_rate is not None and ig.engagement_rate < 1.0:
        return (
            "low_engagement",
            f"Instagram engagement rate is {ig.engagement_rate:.1f}% — below 1% means posts are not reaching or connecting with the audience.",
        )

    # 11 — GMB has no photos
    if gp.photos_count is not None and gp.photos_count < 5:
        return (
            "few_gmb_photos",
            f"Google Maps listing has only {gp.photos_count} photo{'s' if gp.photos_count != 1 else ''} — businesses with 10+ photos get 42% more direction requests.",
        )

    # Fallback — meta description missing (minor but always fixable)
    return (
        "missing_meta_description",
        "Website has no meta description — this is the text Google shows in search results and directly affects click-through rate.",
    )


# ── Public entry point ─────────────────────────────────────────────────────────

def detect_profile(merged: MergedAuditData) -> ProfileContext:
    """
    Run the full profile detection pipeline and return a ProfileContext.

    Safe to call even when Groq is unavailable or business_description is empty —
    falls back to rule-based defaults so the audit pipeline never blocks.
    """
    log = logger.bind(audit_id=merged.audit_id)
    req = merged.request

    # Step 1 — Extract structured context from free-text description
    extracted: ExtractedContext
    if req.business_description and (settings.groq_api_key or settings.use_ollama) and not settings.use_ollama:
        try:
            log.info("profile_detector.extract_start")
            extracted = _extract_context_via_groq(
                business_name=req.business_name,
                business_description=req.business_description,
                city=req.city,
            )
            log.info(
                "profile_detector.extract_done",
                category=extracted.category,
                model=extracted.business_model,
            )
        except Exception as exc:
            log.warning("profile_detector.extract_failed", error=str(exc))
            extracted = _fallback_context(req.business_description)
    else:
        extracted = _fallback_context(req.business_description)

    # Step 2 — Detect profile type from worker signals
    profile_type = _detect_profile_type(merged)
    log.info("profile_detector.profile_type", type=profile_type)

    # Step 3 — Benchmark lookup using Groq-extracted category
    benchmark_key, benchmark = get_closest_benchmark(extracted.category)
    log.info("profile_detector.benchmark", key=benchmark_key)

    # Step 4 — Identify biggest gap
    biggest_gap, biggest_gap_reason = _detect_biggest_gap(merged)
    log.info("profile_detector.biggest_gap", gap=biggest_gap)

    return ProfileContext(
        extracted=extracted,
        profile_type=profile_type,
        biggest_gap=biggest_gap,
        biggest_gap_reason=biggest_gap_reason,
        benchmark_key=benchmark_key,
        benchmark=dict(benchmark),
    )
