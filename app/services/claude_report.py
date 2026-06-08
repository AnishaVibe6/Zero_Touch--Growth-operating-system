"""
Calls Groq (llama-3.3-70b-versatile) with a three-layer prompt and extracts
a structured report via function calling — guaranteed valid JSON output.

Three-layer prompt architecture:
  Layer 1 — Dynamic persona  : expert role matched to profile_type + business_model
  Layer 2 — Narrative context: rich plain-English business context (no raw JSON)
  Layer 3 — Strict output rules: business name in every finding, 7-day recs,
             profile-matched campaign, benchmark-grounded revenue loss
"""
import json
import re
import sys
from pathlib import Path

import httpx
import structlog
from groq import Groq, RateLimitError

# Project root on sys.path so pipeline/ and ai/ are importable
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from ai.campaign_builder import build_campaign_brief
from ai.narrative_builder import build_narrative
from app.config import settings
from app.models.audit import MergedAuditData
from app.models.report import (
    AuditReport, CampaignPreview, DimensionScore, Dimensions,
    GoogleAdsPreview, FacebookAdsPreview, InstagramPreview,
)
from app.services.revenue_calc import calculate_revenue_loss
from pipeline.profile_detector import ProfileContext, detect_profile

logger = structlog.get_logger()

_client = Groq(api_key=settings.groq_api_key)


# ── Platform-specific ad preview schemas ─────────────────────────────────────

_GOOGLE_ADS_SCHEMA = {
    "type": "object",
    "description": "Google Responsive Search Ad. All headlines max 30 chars. Descriptions max 90 chars.",
    "properties": {
        "headline_1": {"type": "string"},
        "headline_2": {"type": "string"},
        "headline_3": {"type": "string"},
        "description_1": {"type": "string"},
        "description_2": {"type": "string"},
        "display_url": {"type": "string", "description": "e.g. businessname.com › service-city"},
    },
    "required": ["headline_1", "headline_2", "description_1", "display_url"],
}

_FACEBOOK_ADS_SCHEMA = {
    "type": "object",
    "description": "Facebook Feed Ad. primary_text max 125 chars. headline max 40 chars.",
    "properties": {
        "primary_text": {"type": "string"},
        "headline": {"type": "string"},
        "description": {"type": "string"},
        "cta_button": {"type": "string", "description": "One of: Learn More, Shop Now, Get Quote, Contact Us, Book Now"},
        "target_audience": {"type": "string", "description": "One sentence: who sees this ad (age, city, interest)"},
    },
    "required": ["primary_text", "headline", "cta_button"],
}

_INSTAGRAM_SCHEMA = {
    "type": "object",
    "description": "Instagram Reel or Post. hook_line is first 3 seconds. caption max 150 chars.",
    "properties": {
        "content_type": {"type": "string", "description": "Reel, Carousel, Story, or Feed Post"},
        "hook_line": {"type": "string", "description": "Opening 3 seconds — what stops the scroll"},
        "caption": {"type": "string"},
        "hashtags": {"type": "array", "items": {"type": "string"}, "maxItems": 8, "description": "Without # prefix"},
    },
    "required": ["content_type", "hook_line", "caption", "hashtags"],
}


# ── Tool schema (unchanged — frontend depends on this exact shape) ─────────────

_DIMENSION_SCHEMA = {
    "type": "object",
    "properties": {
        "score":            {"type": "integer", "minimum": 0, "maximum": 100},
        "label":            {"type": "string", "enum": ["Poor", "Needs Work", "Good", "Excellent"]},
        "summary":          {"type": "string"},
        "recommendations":  {"type": "array", "items": {"type": "string"}, "maxItems": 5},
        "competitor_hint":  {
            "type": "string",
            "description": "One sentence using REAL numbers from the narrative. E.g. 'Sharma Sweets nearby: 847 reviews. Apna Sweets: 12.' Only show when competitor is strictly better.",
        },
        "category_avg": {
            "type": "integer",
            "minimum": 0,
            "maximum": 100,
            "description": "Typical score for this dimension in this category and city tier. Used as benchmark bar on the report.",
        },
    },
    "required": ["score", "label", "summary", "recommendations", "competitor_hint", "category_avg"],
}

_REPORT_TOOL = {
    "type": "function",
    "function": {
        "name": "submit_audit_report",
        "description": "Submit the structured growth audit report for an Indian MSME.",
        "parameters": {
            "type": "object",
            "properties": {
                "overall_score": {
                    "type": "integer",
                    "description": "Weighted average: web_performance×25 + local_seo×35 + social_presence×20 + website_quality×20.",
                },
                "web_performance": _DIMENSION_SCHEMA,
                "local_seo":       _DIMENSION_SCHEMA,
                "social_presence": _DIMENSION_SCHEMA,
                "website_quality": _DIMENSION_SCHEMA,
                "campaign_preview": {
                    "type": "object",
                    "description": "Paid campaign — channel must match profile type. See PROFILE CONSTRAINTS in your instructions.",
                    "properties": {
                        "channel":            {"type": "string"},
                        "monthly_budget_inr": {"type": "integer", "description": "Recommended monthly ad budget in INR. Use monthly_ad_spend from narrative or 5000 minimum."},
                        "expected_leads":     {"type": "integer"},
                        "cost_per_lead_inr":  {"type": "integer"},
                        "ad_copies": {
                            "type": "array",
                            "description": "3 structured ad previews styled like real Google/Meta ads.",
                            "items": {
                                "type": "object",
                                "properties": {
                                    "headline":    {"type": "string", "description": "Max 30 chars. Conversion-focused, lead with brand name or category benefit."},
                                    "description": {"type": "string", "description": "Max 90 chars. One specific benefit + strong CTA."},
                                    "display_url": {"type": "string", "description": "E.g. 'apnasweets.com › order-sweets'"},
                                },
                                "required": ["headline", "description", "display_url"],
                            },
                        },
                    },
                    "required": ["channel", "monthly_budget_inr", "expected_leads", "cost_per_lead_inr", "ad_copies"],
                },
                "keywords": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "Up to 8 high-intent keywords using city name and business-specific terms. Follow RULE C1 channel — Google keywords for Google Ads, Instagram hashtag-style for Meta.",
                },
                "quick_wins": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "3 zero-cost actions doable today on a mobile phone — WhatsApp link, GMB photos, reply to reviews.",
                },
                "we_will": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": (
                        "Exactly 3 campaign actions written as 'We will...' statements. "
                        "Every item MUST follow ALL 4 rules: "
                        "RULE 1 — Start with 'We will'. "
                        "RULE 2 — Name the business or its exact category — NEVER write 'your business'. "
                        "RULE 3 — End with a measurable outcome after ' — ' using a real impact stat. "
                        "E.g. '— businesses with 15+ photos get 42% more direction requests', "
                        "'— 68% of Indian buyers contact via WhatsApp before purchasing'. "
                        "RULE 4 — Item 1 fixes the WORST-scoring dimension, "
                        "Item 2 fixes the SECOND worst, "
                        "Item 3 describes the paid campaign action on the recommended channel. "
                        "FORBIDDEN: 'post high quality content', 'engage with customers', "
                        "'improve your online presence', 'optimize your profile', "
                        "'create compelling content', 'build brand awareness'. "
                        "Good example 1: 'We will upload 15 fresh mithai photos to "
                        "Apna Sweets Google Maps listing — businesses with 15+ photos get 42% more direction requests'. "
                        "Good example 2: 'We will add a WhatsApp click-to-chat button to "
                        "apnasweets.com — 68% of Indian buyers contact via WhatsApp before purchasing'. "
                        "Good example 3: 'We will run Google Ads targeting sweets near me Indore "
                        "for Apna Sweets at Rs.5000/month — targeting 25 new walk-in enquiries per month'."
                    ),
                },
                "roadmap_weeks": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "Exactly 4 strings. Week 1 MUST match RULE C4 (specific to business description). Each max 12 words, business-specific — never generic.",
                },
                "headline": {
                    "type": "string",
                    "description": "One brutal, motivating sentence the owner can't ignore. Must mention the business name. Max 12 words.",
                },
                "revenue_loss_reason": {
                    "type": "string",
                    "description": "One sentence referencing the benchmark avg_order_value and monthly customers to explain WHY money is lost. E.g. 'Sweet shops in Indore serve ~700 customers/month at ₹450 avg — your slow website is costing you 15% of that.'",
                },
                "google_ads_preview": _GOOGLE_ADS_SCHEMA,
                "facebook_ads_preview": _FACEBOOK_ADS_SCHEMA,
                "instagram_preview": _INSTAGRAM_SCHEMA,
            },
            "required": [
                "overall_score", "web_performance", "local_seo", "social_presence",
                "website_quality", "campaign_preview",
                "keywords", "quick_wins", "we_will", "roadmap_weeks", "headline", "revenue_loss_reason",
            ],
        },
    },
}


# ── Layer 1: Dynamic persona ───────────────────────────────────────────────────

_PERSONA_MAP: dict[tuple[str, str], str] = {
    ("instagram_first", "home_based"): (
        "You are a social commerce coach who helps home-based Indian sellers grow through "
        "Instagram, WhatsApp, and word-of-mouth. Your recommendations never involve opening "
        "a physical shop or investing in offline infrastructure. Everything you suggest can "
        "be done from a mobile phone."
    ),
    ("instagram_first", "shop_based"): (
        "You are a social-first retail consultant who builds Instagram-led acquisition "
        "funnels for Indian shop owners. You prioritise Meta Ads, Reels, and WhatsApp "
        "Business over traditional search marketing."
    ),
    ("instagram_first", "hybrid"): (
        "You are a social commerce strategist who connects Instagram engagement directly "
        "to in-store conversion for Indian MSMEs — Stories to foot traffic, DMs to sales."
    ),
    ("instagram_first", "online_only"): (
        "You are a D2C growth consultant for Indian online businesses. Instagram Ads, "
        "influencer collaborations, and WhatsApp broadcasts are your primary tools."
    ),
    ("traditional", "home_based"): (
        "You are a digital presence consultant who helps home-based Indian business owners "
        "build their first online footprint through Google, WhatsApp, and local directories. "
        "You understand they have no physical storefront and never suggest one."
    ),
    ("traditional", "shop_based"): (
        "You are a local SEO and Google Maps expert helping Indian brick-and-mortar shops "
        "dominate local search results and convert Google Maps visibility into walk-in traffic. "
        "Google Business Profile, reviews, and local keywords are your core tools."
    ),
    ("traditional", "online_only"): (
        "You are a performance marketing consultant for Indian online businesses — website "
        "speed, Google Ads, conversion rate optimisation, and trust signals are your "
        "primary levers."
    ),
    ("hybrid", "shop_based"): (
        "You are a full-funnel digital consultant for Indian businesses that serve both "
        "walk-in and online customers. You balance Google Maps visibility for local discovery "
        "with website conversion and Instagram for brand trust."
    ),
    ("hybrid", "home_based"): (
        "You are an omni-channel growth consultant for home-based Indian businesses — "
        "Instagram for discovery, WhatsApp for conversion, Google for search intent."
    ),
    ("hybrid", "online_only"): (
        "You are a multi-channel digital marketing strategist for Indian online businesses, "
        "balancing Google Ads search intent with Instagram's visual discovery."
    ),
}

_DEFAULT_PERSONA = (
    "You are a digital growth consultant specialising in Indian MSMEs. "
    "You produce specific, actionable audit reports grounded in real data."
)


def _build_persona(profile: ProfileContext) -> str:
    key = (profile.profile_type, profile.extracted.business_model)
    return _PERSONA_MAP.get(key, _DEFAULT_PERSONA)


# ── Layer 2: Base scoring and data quality rules (static) ─────────────────────

_BASE_RULES = """
Scoring guide (apply to each dimension):
  0-40  -> Poor        (critical gaps, immediate action needed)
  41-60 -> Needs Work  (visible gaps, high-impact fixes available)
  61-80 -> Good        (functional but room to improve)
  81-100-> Excellent   (best-in-class)

Overall score = weighted average: web_performance×25 + local_seo×35 + social_presence×20 + website_quality×20.
Local SEO is weighted highest because Google Maps drives walk-in traffic for Indian MSMEs.

web_performance scoring — derive from the narrative context provided:
  - load time < 2s = great (+0), 2–4s = ok (-10), > 4s = poor (-30)
  - no SSL (HTTP) = major penalty (-25)
  - has structured data = bonus (+10)
  - no meta description = -10
  - no WhatsApp link = -10 (critical for Indian MSMEs)
  - no contact page = -10
  Start from 70, apply adjustments, clamp to 0–100.

Data quality rules — CRITICAL:
  - Write every finding from the narrative context I provide. Do NOT invent data.
  - NEVER mention "API error", "data unavailable", "not configured", "missing data",
    "API key", "Lighthouse", "PageSpeed", or any technical infrastructure detail.
  - If a dimension has no data in the narrative, score it 45 (Needs Work) and write
    forward-looking growth advice specific to the business category and city.
  - Always provide real, actionable findings even when data is sparse.

google_places field meanings — READ CAREFULLY before scoring local_seo:
  - If the narrative says the GMB listing is "claimed and verified" → NEVER say "no listing".
  - If the narrative says "no Google Maps listing" → this IS a critical gap.
  - If the narrative says "unclaimed" → say "claim your listing", not "create a listing".
  - Use the exact review count and rating from the narrative in competitor_hint and summary.

India-specific signals that matter most:
  - WhatsApp click-to-chat link on website
  - Google Business Profile claimed + photos added
  - Hindi/vernacular content for Tier-2+ cities
  - Rating ≥ 4.2 and ≥ 50 reviews for trust
  - Mobile page speed (most Indian users are on 4G mobile)

RULE 1 — Specific findings (NEVER vague language):
  - NEVER say "your listing is incomplete", "your profile needs improvement", "your presence is weak".
  - Name the EXACT missing element + one real impact stat from the narrative.
  - E.g.: "Apna Sweets has no photos on Google Maps — listings with 10+ photos get 42% more direction requests."
  - Every recommendation must name the specific gap AND one real-world impact number.

RULE 2 — Directional competitor_hint (ONLY when competitor is BETTER):
  - Only surface a competitor comparison when the competitor's number is strictly higher (more reviews,
    higher rating, more followers, faster load time).
  - If the business leads on a metric, write: "Apna Sweets leads in this area — focus on maintaining it."
  - NEVER write "You: unknown" or "You: N/A". Skip or use a category benchmark instead.

RULE 3 — revenue_loss_reason must match the WORST dimension:
  - Identify the dimension with the LOWEST score. The revenue_loss_reason MUST reference that dimension.
  - NEVER attribute revenue loss to a dimension scoring above 70.

RULE 4 — Positive framing for scores above 70:
  - If a dimension scores 71+, its summary MUST start with "Strong point: ..." then name the specific strength.
  - Frame any improvements as "to push from good to great" — not as problems.

competitor_hint rules:
  - Use real numbers from the narrative (review count, rating, followers, load time).
  - Apply RULE 2 — only show when competitor is strictly better.
  - Format: "Top [category] in [city] has X. [Business name] has Y."

category_avg: estimate the typical dimension score for this category and city tier.
  Rough benchmarks: local_seo~52, web_performance~48, social_presence~38, website_quality~55.

roadmap_weeks: exactly 4 strings, one concrete sentence each (max 12 words):
  Week 1=setup & zero-cost wins, Week 2=campaign launch, Week 3=optimise, Week 4=review & scale.

headline: one brutal, motivating sentence the owner can't ignore — MUST include the business name. Max 12 words.
revenue_loss_reason: one sentence using benchmark avg_order_value and monthly_customers_estimate to
  explain WHY money is lost — MUST reference the lowest-scoring dimension (Rule 3).

MULTI-CHANNEL CAMPAIGN PREVIEWS — generate all three, platform-specific:

google_ads_preview (Google Responsive Search Ad):
  - headline_1, headline_2, headline_3: max 30 chars each — include business name or city in at least one
  - description_1, description_2: max 90 chars each — specific benefit + strong CTA
  - display_url: e.g. "businessname.com › order-online" (short, no https)
  - Use high-intent keywords: "[category] in [city]", "[service] near me"

facebook_ads_preview (Facebook Feed Ad):
  - primary_text: max 125 chars — conversational, problem-aware opening line that stops the scroll
  - headline: max 40 chars — bold value proposition
  - cta_button: match intent — "Get Quote" for services, "Shop Now" for products, "Book Now" for appointments
  - target_audience: one sentence — age range, city, interests that match the business category

instagram_preview (Instagram Reel or Post):
  - content_type: "Reel" if product/service can be shown in motion, "Carousel" for before/after or multi-item, "Feed Post" otherwise
  - hook_line: first 3 seconds — question, bold claim, or visual action that stops scrolling (max 10 words)
  - caption: max 150 chars — warm, local tone, ends with CTA or question
  - hashtags: 5–8 tags without # — mix of city + category + niche (e.g. "indorefood", "sweetshop", "mithai")
"""


# ── Layer 3: Profile-specific constraints (dynamic) ───────────────────────────

_CHANNEL_MAP: dict[tuple[str, str], str] = {
    ("instagram_first", "home_based"):  "Meta Ads (Instagram/Facebook)",
    ("instagram_first", "shop_based"):  "Meta Ads (Instagram/Facebook)",
    ("instagram_first", "hybrid"):      "Meta Ads (Instagram/Facebook)",
    ("instagram_first", "online_only"): "Meta Ads (Instagram/Facebook)",
    ("traditional",     "home_based"):  "Google Ads or Meta Ads",
    ("traditional",     "shop_based"):  "Google Ads (local search)",
    ("traditional",     "online_only"): "Google Ads (search)",
    ("hybrid",          "shop_based"):  "Google Ads (local search) or Meta Ads",
    ("hybrid",          "home_based"):  "Meta Ads (Instagram/Facebook)",
    ("hybrid",          "online_only"): "Google Ads or Meta Ads",
}

_FORBIDDEN_BY_MODEL: dict[str, list[str]] = {
    "home_based": [
        "NEVER recommend opening a physical shop, getting a commercial space, or renting premises.",
        "NEVER recommend offline advertising (billboards, newspaper, pamphlets) as a primary channel.",
        "All recommendations must be executable from a mobile phone by a solo operator.",
    ],
    "shop_based": [
        "NEVER recommend moving to online-only or closing the physical shop.",
    ],
    "online_only": [
        "NEVER recommend opening a physical shop or investing in physical infrastructure.",
        "Website speed, trust signals (SSL, reviews, structured data), and paid digital ads are the only levers.",
    ],
    "hybrid": [],
}

_FORBIDDEN_BY_PROFILE: dict[str, list[str]] = {
    "instagram_first": [
        "NEVER list 'build a website' as the first priority — this profile's primary growth lever is social, not search.",
        "campaign_preview channel MUST be Meta Ads or Instagram. Google Search Ads are wrong for this profile.",
    ],
    "traditional": [
        "campaign_preview channel MUST match the recommended channel in these constraints.",
    ],
    "hybrid": [],
}


def _profile_constraints(
    profile: ProfileContext,
    has_website: bool,
    business_name: str,
    city: str,
    monthly_ad_spend: float | None = None,
    campaign_brief_block: str = "",
) -> str:
    bm      = profile.benchmark
    ext     = profile.extracted
    channel = _CHANNEL_MAP.get(
        (profile.profile_type, ext.business_model),
        "Google Ads or Meta Ads",
    )

    avg_order    = bm.get("avg_order_value", 600)
    monthly_cust = bm.get("monthly_customers_estimate", 400)
    peak         = bm.get("peak_season", "festive season")
    budget       = int(monthly_ad_spend) if monthly_ad_spend else 5000

    forbidden_model   = "\n  - ".join(_FORBIDDEN_BY_MODEL.get(ext.business_model, []))
    forbidden_profile = "\n  - ".join(_FORBIDDEN_BY_PROFILE.get(profile.profile_type, []))

    no_website_block = ""
    if not has_website:
        no_website_block = (
            "\nNO WEBSITE DETECTED — apply these additional rules:\n"
            "  - web_performance score MUST be ≤ 20.\n"
            "  - website_quality score MUST be ≤ 40.\n"
            "  - roadmap_weeks[0] MUST be: 'Build a simple website with address, services, phone and WhatsApp link.'\n"
            "  - headline MUST reference the missing website as the biggest growth blocker.\n"
            "  - Do NOT say 'improve your website' — say 'build your website'.\n"
        )

    return f"""
PROFILE CONSTRAINTS FOR THIS AUDIT — follow these exactly:

Business: {business_name} in {city}
Profile type: {profile.profile_type}
Business model: {ext.business_model} ({ext.subcategory})
Target customer: {ext.target_customer}
Biggest gap: {profile.biggest_gap_reason}

CAMPAIGN CHANNEL: The campaign_preview channel MUST be "{channel}".
{f'  - {forbidden_profile}' if forbidden_profile else ''}

CAMPAIGN BUDGET: monthly_budget_inr MUST be exactly ₹{budget:,}.
  This is the owner's actual monthly ad spend — do NOT increase or change it.

BUSINESS MODEL RULES:
  - {forbidden_model if forbidden_model else 'No additional restrictions for this model.'}

7-DAY RULE: Every recommendation MUST be actionable by the business owner within 7 days
  using only a mobile phone and ₹5,000 or less. No recommendations that require contractors,
  agencies, or long timelines.

BUSINESS NAME RULE: Every dimension summary and every competitor_hint MUST include the
  business name "{business_name}" at least once. Never write "your business" without the actual name.

REVENUE LOSS RULE: Use these benchmark numbers to make revenue_loss_reason concrete:
  - avg_order_value = ₹{avg_order:,}
  - monthly_customers_estimate = {monthly_cust:,}
  - peak_season = {peak}
  Multiply the gap fraction by these numbers to arrive at a believable loss estimate.
  E.g. "~{monthly_cust} customers visit {profile.benchmark_key}s in {city} each month
  at ₹{avg_order} avg spend — the biggest gap is costing roughly 15–20% of that opportunity."

BIGGEST GAP (pre-identified): {profile.biggest_gap_reason}
  The revenue_loss_reason MUST explain this specific gap as the root cause.
{no_website_block}
{campaign_brief_block}"""


def _build_system_prompt(
    profile: ProfileContext,
    has_website: bool,
    business_name: str,
    city: str,
    monthly_ad_spend: float | None = None,
    campaign_brief_block: str = "",
) -> str:
    """Three-layer system prompt: persona → base rules → profile constraints + campaign brief."""
    persona     = _build_persona(profile)
    constraints = _profile_constraints(
        profile, has_website, business_name, city,
        monthly_ad_spend, campaign_brief_block,
    )
    return persona + "\n\n" + _BASE_RULES + "\n" + constraints


# ── Payload helpers (kept for logging; no longer sent to Groq) ────────────────

def _slim(obj):
    """Recursively drop null values and empty collections."""
    if isinstance(obj, dict):
        return {k: _slim(v) for k, v in obj.items()
                if v is not None and v != [] and v != {}}
    if isinstance(obj, list):
        return [_slim(i) for i in obj]
    return obj


def _sanitize_workers(raw: dict) -> dict:
    """Replace errored worker sections with a clean no_data marker."""
    for key in ("instagram", "google_places", "lighthouse", "crawler"):
        section = raw.get(key)
        if isinstance(section, dict) and section.get("error"):
            raw[key] = {"no_data": True}
    return raw


# ── Fallback profile when detector fails ─────────────────────────────────────

def _minimal_profile() -> ProfileContext:
    from pipeline.profile_detector import ExtractedContext
    return ProfileContext(
        extracted=ExtractedContext(
            category="local business",
            subcategory="general business",
            business_model="shop_based",
            product_or_service="both",
            target_customer="walk-in local customers",
            is_instagram_sellable=False,
        ),
        profile_type="traditional",
        biggest_gap="no_gmb_listing",
        biggest_gap_reason="Business has no Google Maps listing — 73% of local buyers check Maps before visiting.",
        benchmark_key="generic",
        benchmark={
            "avg_gmb_reviews": 180,
            "avg_instagram_followers": 2000,
            "avg_website_load_time": 4.5,
            "peak_season": "festive season",
            "avg_order_value": 600,
            "monthly_customers_estimate": 400,
            "top_keywords": [],
            "primary_channel": "Google Ads",
        },
    )


# ── LLM call helpers ─────────────────────────────────────────────────────────

# Injected at the end of the user prompt when using Ollama (no function calling).
# format="json" in the API call forces valid JSON, this schema tells the model
# exactly what fields to populate.
_OLLAMA_SCHEMA_PROMPT = """
Respond with ONLY a valid JSON object — no markdown fences, no explanation.
Required fields (fill every one, never omit):
{
  "overall_score": <integer 0-100>,
  "headline": "<one sentence with business name, max 12 words>",
  "revenue_loss_reason": "<one sentence using benchmark numbers, references lowest-scoring dimension>",
  "keywords": ["<kw1>","<kw2>","<kw3>","<kw4>","<kw5>","<kw6>","<kw7>","<kw8>"],
  "quick_wins": ["<zero-cost action 1>","<zero-cost action 2>","<zero-cost action 3>"],
  "roadmap_weeks": ["<week 1 sentence>","<week 2 sentence>","<week 3 sentence>","<week 4 sentence>"],
  "web_performance": {
    "score": <int>, "label": "<Poor|Needs Work|Good|Excellent>",
    "summary": "<sentence including business name>",
    "recommendations": ["<rec1>","<rec2>","<rec3>"],
    "competitor_hint": "<sentence with business name and real numbers>",
    "category_avg": <int>
  },
  "local_seo":       { <same six keys as web_performance> },
  "social_presence": { <same six keys as web_performance> },
  "website_quality": { <same six keys as web_performance> },
  "campaign_preview": {
    "channel": "<channel name>",
    "monthly_budget_inr": <integer>,
    "expected_leads": <integer>,
    "cost_per_lead_inr": <integer>,
    "ad_copies": [
      {"headline":"<max 30 chars>","description":"<max 90 chars>","display_url":"<domain/path>"},
      {"headline":"<max 30 chars>","description":"<max 90 chars>","display_url":"<domain/path>"},
      {"headline":"<max 30 chars>","description":"<max 90 chars>","display_url":"<domain/path>"}
    ]
  }
}"""


def _call_ollama(system_prompt: str, user_prompt: str) -> dict:
    """
    Call local Ollama instance at /api/generate.

    Combines system + user prompts and appends the JSON schema instruction.
    Uses format='json' so the Ollama runtime guarantees the response is
    parseable JSON even if the model doesn't follow the schema perfectly.
    """
    full_prompt = f"{user_prompt}\n\n{_OLLAMA_SCHEMA_PROMPT}"
    resp = httpx.post(
        f"{settings.ollama_url}/api/generate",
        json={
            "model":  settings.ollama_model,
            "system": system_prompt,
            "prompt": full_prompt,
            "stream": False,
            "format": "json",
        },
        timeout=600,
    )
    resp.raise_for_status()
    raw = resp.json().get("response", "{}")
    return json.loads(raw)


def _fix_schema_violations(d: dict) -> dict:
    """Clamp array fields to their schema-defined maxItems limits.

    Groq's validator rejects the entire call if any array is over-length.
    Fixing post-parse on the salvaged failed_generation is cheaper than a retry.
    """
    d["keywords"]      = (d.get("keywords") or [])[:8]
    d["quick_wins"]    = (d.get("quick_wins") or [])[:3]
    d["roadmap_weeks"] = (d.get("roadmap_weeks") or [])[:4]
    d["we_will"] = (d.get("we_will") or [])[:3]
    cp = d.get("campaign_preview", {})
    if isinstance(cp, dict):
        cp["ad_copies"] = (cp.get("ad_copies") or [])[:3]
    ig = d.get("instagram_preview", {})
    if isinstance(ig, dict):
        ig["hashtags"] = (ig.get("hashtags") or [])[:8]
    return d


def _strip_function_wrapper(raw: str) -> str:
    """Strip Groq's <function=name>{...}</function> wrapper if present."""
    raw = raw.strip()
    m = re.match(r"<function=\w+>(.*)</function>$", raw, re.DOTALL)
    if m:
        return m.group(1).strip()
    return raw


def _extract_failed_generation(exc) -> str:
    """Pull the failed_generation JSON string from a groq BadRequestError.

    Groq wraps the JSON in <function=submit_audit_report>{...}</function> —
    strip that wrapper before returning. Tries three paths in order:
    1. exc.body dict (groq SDK pre-parses here; most reliable)
    2. exc.response.json() (may fail if httpx body already consumed)
    3. str(exc) regex scan (guaranteed last resort)
    """
    raw = ""

    # Path 1 — exc.body
    if hasattr(exc, "body"):
        b = exc.body
        if isinstance(b, dict):
            raw = (b.get("error") or {}).get("failed_generation", "") or b.get("failed_generation", "")

    # Path 2 — exc.response
    if not raw and hasattr(exc, "response"):
        try:
            b = exc.response.json()
            raw = (b.get("error") or {}).get("failed_generation", "")
        except Exception:
            pass

    # Path 3 — parse from string representation
    if not raw:
        exc_str = str(exc)
        m = re.search(r"'failed_generation':\s*'(.*?)'(?:\}|,\s*')", exc_str, re.DOTALL)
        if m:
            raw = m.group(1).replace("\\'", "'")

    return _strip_function_wrapper(raw) if raw else ""


def _call_groq(system_prompt: str, user_prompt: str) -> dict:
    """Call Groq with function calling — returns parsed arguments dict.

    On 400 validation errors (e.g. array over maxItems), salvages the
    failed_generation JSON from the error body, fixes schema violations,
    and returns the corrected dict rather than raising.
    """
    from groq import BadRequestError as _BadReq
    try:
        response = _client.chat.completions.create(
            model=settings.groq_model,
            max_tokens=3072,
            tools=[_REPORT_TOOL],
            tool_choice={"type": "function", "function": {"name": "submit_audit_report"}},
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user",   "content": user_prompt},
            ],
        )
        return json.loads(response.choices[0].message.tool_calls[0].function.arguments)
    except _BadReq as exc:
        raw = _extract_failed_generation(exc)
        if raw:
            try:
                return _fix_schema_violations(json.loads(raw))
            except Exception:
                pass
        raise


def _call_llm(system_prompt: str, user_prompt: str, log) -> dict:
    """Route to Ollama or Groq based on USE_OLLAMA setting."""
    if settings.use_ollama:
        log.info("llm.ollama", model=settings.ollama_model, url=settings.ollama_url)
        return _call_ollama(system_prompt, user_prompt)
    log.info("llm.groq", model=settings.groq_model)
    return _call_groq(system_prompt, user_prompt)


# ── Main entry point ──────────────────────────────────────────────────────────

def generate_report(merged: MergedAuditData) -> AuditReport:
    log = logger.bind(audit_id=merged.audit_id)
    log.info("groq.start")

    has_website  = bool(merged.request.website_url)
    business_name = merged.request.business_name
    city          = merged.request.city or "India"

    # ── Step 1: Detect profile (one small Groq extraction call) ───────────────
    try:
        profile = detect_profile(merged)
        log.info(
            "profile.detected",
            type=profile.profile_type,
            model=profile.extracted.business_model,
            gap=profile.biggest_gap,
            benchmark=profile.benchmark_key,
        )
    except Exception as exc:
        log.warning("profile.detect_failed", error=str(exc))
        profile = _minimal_profile()

    # ── Step 2a: Build narrative (pure Python, no Groq call) ─────────────────
    try:
        narrative = build_narrative(merged, profile)
        log.info("narrative.built", chars=len(narrative))
    except Exception as exc:
        log.warning("narrative.build_failed", error=str(exc))
        narrative = (
            f"{business_name} is a {profile.extracted.subcategory} in {city}. "
            f"Profile type: {profile.profile_type}. "
            f"Biggest gap: {profile.biggest_gap_reason}"
        )

    # ── Step 2b: Build campaign brief (pure Python, no Groq call) ────────────
    dimension_scores = {}
    try:
        from app.models.audit import MergedAuditData as _MAD  # noqa: F401
        # Scores not yet computed — use heuristic defaults for channel/tone/brief
        # Real scores come from Groq; brief is based on worker signals only
        dimension_scores = {
            "local_seo":       50 if not merged.google_places.gmb_exists else 75,
            "web_performance": 20 if not has_website else (40 if (merged.crawler.load_time_s or 0) > 4 else 65),
            "social_presence": 20 if merged.instagram.error else (60 if (merged.instagram.followers or 0) > 500 else 35),
            "website_quality": 20 if not has_website else 55,
        }
        campaign_brief = build_campaign_brief(
            profile=profile,
            dimension_scores=dimension_scores,
            business_description=merged.request.business_description,
            city=merged.request.city,
            monthly_ad_spend=float(merged.request.monthly_ad_spend) if merged.request.monthly_ad_spend else None,
            business_name=business_name,
        )
        campaign_brief_block = campaign_brief.as_prompt_block()
        log.info("campaign_brief.built", channel=campaign_brief.primary_channel, tone=campaign_brief.tone, tier=campaign_brief.budget_tier)
    except Exception as exc:
        log.warning("campaign_brief.failed", error=str(exc))
        campaign_brief_block = ""

    # ── Step 3: Build prompt — narrative replaces raw JSON ───────────────────
    # Do NOT include a pre-calculated INR range here — Groq would anchor on the
    # score=50 estimate even after the real score changes the formula result.
    # revenue_loss_reason should explain WHY (the gap), not cite a number.
    prompt = (
        f"Audit context for **{business_name}**, {city}:\n\n"
        f"{narrative}\n\n"
        f"Write revenue_loss_reason by explaining exactly WHY money is lost "
        f"(the specific gap and its business impact) using the benchmark "
        f"avg_order_value and monthly_customers_estimate from your constraints. "
        f"Do NOT include a specific ₹ amount in revenue_loss_reason — "
        f"the exact figure is calculated separately and shown to the owner.\n\n"
        f"Call submit_audit_report with your structured findings."
    )

    system_prompt = _build_system_prompt(
        profile, has_website, business_name, city,
        monthly_ad_spend=float(merged.request.monthly_ad_spend) if merged.request.monthly_ad_spend else None,
        campaign_brief_block=campaign_brief_block,
    )
    log.info("llm.prompt_chars", system=len(system_prompt), user=len(prompt))

    # ── Step 5: LLM call (Ollama or Groq) ────────────────────────────────────
    try:
        d = _call_llm(system_prompt, prompt, log)
    except RateLimitError as exc:
        m = re.search(r"try again in ([\d]+m[\d.]+s|[\d.]+s)", str(exc), re.IGNORECASE)
        wait = m.group(1) if m else "a few minutes"
        log.warning("groq.rate_limit", wait=wait)
        raise RuntimeError(f"Daily AI quota reached — please try again in {wait}") from exc
    except httpx.ConnectError:
        raise RuntimeError(
            "Ollama is not running — start it with: ollama serve"
        )
    log.info("llm.done", backend="ollama" if settings.use_ollama else "groq")

    # ── Log raw campaign fields for debugging ────────────────────────────────
    _cp_raw = d.get("campaign_preview", {})
    log.info(
        "groq.campaign_raw",
        channel=_cp_raw.get("channel"),
        monthly_budget_inr=_cp_raw.get("monthly_budget_inr"),
        expected_leads=_cp_raw.get("expected_leads"),
        cost_per_lead_inr=_cp_raw.get("cost_per_lead_inr"),
        ad_copies_count=len(_cp_raw.get("ad_copies") or []),
    )

    # ── Step 6: Formula revenue loss using real score ─────────────────────────
    rev_low, rev_high = calculate_revenue_loss(
        d["overall_score"],
        merged.request.business_description,
        str(merged.request.city) if merged.request.city else None,
        has_website=has_website,
    )
    log.info("revenue_calc", score=d["overall_score"], low=rev_low, high=rev_high)

    # ── Step 7: Assemble AuditReport — normalise campaign fields ─────────────
    cp = d.get("campaign_preview", {})

    # Lift top-level fields into cp
    cp.setdefault("headline",            d.get("headline") or d.get("campaign_headline"))
    cp.setdefault("revenue_loss_reason", d.get("revenue_loss_reason"))
    cp.setdefault("keywords",            d.get("keywords", []))
    cp.setdefault("quick_wins",          d.get("quick_wins", []))
    cp.setdefault("we_will",             d.get("we_will", []))
    cp.setdefault("roadmap_weeks",       d.get("roadmap_weeks", []))

    # ── Fallback calculations when Groq returns 0 or null ────────────────────
    bm               = profile.benchmark
    monthly_cust     = bm.get("monthly_customers_estimate", 400)
    avg_order        = bm.get("avg_order_value", 600)
    req_spend        = float(merged.request.monthly_ad_spend) if merged.request.monthly_ad_spend else None

    # Budget: prefer Groq value → request ad_spend → 5000 minimum
    budget = int(cp.get("monthly_budget_inr") or 0)
    if budget <= 0:
        budget = int(req_spend) if req_spend else 5000
    cp["monthly_budget_inr"] = budget

    # Leads: prefer Groq value → benchmark × 0.15
    leads = int(cp.get("expected_leads") or 0)
    if leads <= 0:
        leads = max(1, round(monthly_cust * 0.15))
    cp["expected_leads"] = leads

    # Cost per lead: prefer Groq value → budget / leads
    cpl = int(cp.get("cost_per_lead_inr") or 0)
    if cpl <= 0:
        cpl = round(budget / leads) if leads > 0 else 0
    cp["cost_per_lead_inr"] = cpl

    # Reach and revenue figures (always computed from normalised leads + benchmark)
    cp["estimated_reach"]              = leads * 20
    cp["estimated_additional_revenue"] = round(leads * avg_order)
    cp["current_monthly_revenue"]      = round(monthly_cust * avg_order)
    cp["projected_monthly_revenue"]    = cp["current_monthly_revenue"] + cp["estimated_additional_revenue"]

    # we_will: top-level from Groq (model always puts content fields at top level)
    we_will = [w for w in (d.get("we_will") or cp.get("we_will") or []) if w.strip()][:3]
    if len(we_will) < 3:
        qw = [w for w in (cp.get("quick_wins") or d.get("quick_wins") or []) if w.strip()]
        for qw_item in qw:
            if len(we_will) >= 3:
                break
            stmt = qw_item if qw_item.lower().startswith("we will") else f"We will {qw_item[0].lower()}{qw_item[1:]}"
            we_will.append(stmt)
    cp["we_will"] = we_will[:3]

    log.info(
        "campaign.normalised",
        budget=budget, leads=leads, cpl=cpl,
        reach=cp["estimated_reach"],
        add_revenue=cp["estimated_additional_revenue"],
        we_will_count=len(cp["we_will"]),
        we_will_from_groq=len([w for w in (d.get("campaign_preview", {}).get("we_will") or []) if w.strip()]),
    )

    # ── Map multi-channel previews ─────────────────────────────────────────
    google_ads_data   = d.get("google_ads_preview")
    facebook_ads_data = d.get("facebook_ads_preview")
    instagram_data    = d.get("instagram_preview")

    if isinstance(google_ads_data, dict) and google_ads_data.get("headline_1"):
        cp["google_ads"] = google_ads_data
        log.info("campaign.google_ads", headline_1=google_ads_data.get("headline_1"))
    if isinstance(facebook_ads_data, dict) and facebook_ads_data.get("primary_text"):
        cp["facebook_ads"] = facebook_ads_data
        log.info("campaign.facebook_ads", headline=facebook_ads_data.get("headline"))
    if isinstance(instagram_data, dict) and instagram_data.get("caption"):
        cp["instagram"] = instagram_data
        log.info("campaign.instagram", content_type=instagram_data.get("content_type"))

    return AuditReport(
        audit_id=merged.audit_id,  # type: ignore[arg-type]
        overall_score=d["overall_score"],
        dimensions=Dimensions(
            web_performance=DimensionScore(**d["web_performance"]),
            local_seo=DimensionScore(**d["local_seo"]),
            social_presence=DimensionScore(**d["social_presence"]),
            website_quality=DimensionScore(**d["website_quality"]),
        ),
        revenue_loss_low=rev_low,
        revenue_loss_high=rev_high,
        campaign_preview=CampaignPreview(**cp),
        has_website=has_website,
    )
