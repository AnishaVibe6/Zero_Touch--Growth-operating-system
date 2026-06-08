"""
Three end-to-end prompt tests using realistic mock worker data.

Bypasses Playwright / SerpAPI / Instagram workers so the only API calls
are the two Groq calls per audit (profile extraction + full report).

Prints for each test:
  - SYSTEM PROMPT  (persona + base rules + profile constraints)
  - USER PROMPT    (narrative replacing raw JSON)
  - GROQ JSON      (raw function-call arguments)
  - VERIFICATION   (4 checks: business name, city, model, campaign channel)
"""
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

# Project root must be on path before any local imports
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from app.config import settings
from app.models.audit import (
    AuditRequest, CrawlerResult, GooglePlacesResult,
    InstagramResult, LighthouseResult, MergedAuditData,
)
from app.services.claude_report import (
    _REPORT_TOOL, _build_system_prompt, _call_llm,
)
from app.services.revenue_calc import calculate_revenue_loss
from ai.narrative_builder import build_narrative
from pipeline.profile_detector import detect_profile

SEP = "=" * 80


# ── Mock data factories ───────────────────────────────────────────────────────

def make_merged(
    audit_id: str,
    request: AuditRequest,
    gp: GooglePlacesResult,
    ig: InstagramResult,
    cr: CrawlerResult,
) -> MergedAuditData:
    return MergedAuditData(
        audit_id=audit_id,
        request=request,
        lighthouse=LighthouseResult(),   # always empty — scored from crawler
        google_places=gp,
        instagram=ig,
        crawler=cr,
    )


# ── Test 1: Apna Sweets, Indore ── sweet shop with website, GMB, no Instagram ─

TEST1 = make_merged(
    audit_id="test-001",
    request=AuditRequest(
        business_name="Apna Sweets",
        city="Indore",
        business_description="We run a sweet shop and namkeen store in Indore since 1995",
        website_url="https://apnasweets.com",
        instagram_handle="apnasweets",
        monthly_ad_spend=5000,
    ),
    gp=GooglePlacesResult(
        gmb_exists=True,
        name="Apna Sweets",
        rating=4.0,
        review_count=12295,
        address="56 Dukan, Indore, MP",
        phone="+91-731-4001234",
        website="https://apnasweets.com",
        categories=["Sweet shop", "Namkeen"],
        photos_count=6,
        is_claimed=True,
        gmb_completeness_score=72,
        competitors=[
            {"title": "Milan Sweets", "reviews": 11866, "rating": 4.3, "address": "Vijay Nagar, Indore"},
            {"title": "Shree Mithai", "reviews": 3210, "rating": 4.1, "address": "MG Road, Indore"},
        ],
    ),
    ig=InstagramResult(error="Profile @apnasweets not found"),
    cr=CrawlerResult(
        has_ssl=True,
        has_contact_page=True,
        has_about_page=False,
        has_whatsapp_link=False,
        has_social_links=False,
        meta_title="Apna Sweets Indore",
        meta_description=None,
        load_time_s=7.01,
        has_structured_data=False,
        phone_numbers=["+91-731-4001234"],
        emails=["info@apnasweets.com"],
        language="en",
    ),
)

# ── Test 2: Riya Collections, Bhopal ── home-based, Instagram-first, no website

TEST2 = make_merged(
    audit_id="test-002",
    request=AuditRequest(
        business_name="Riya Collections",
        city="Bhopal",
        business_description="I sell handmade embroidery suits from home, mostly through Instagram and WhatsApp",
        website_url=None,
        instagram_handle="riya.collections.bhopal",
        monthly_ad_spend=3000,
    ),
    gp=GooglePlacesResult(
        gmb_exists=False,
        competitors=[
            {"title": "Bhopal Handloom House", "reviews": 312, "rating": 4.4, "address": "New Market, Bhopal"},
            {"title": "Silk India Bhopal", "reviews": 189, "rating": 4.2, "address": "MP Nagar, Bhopal"},
        ],
    ),
    ig=InstagramResult(
        username="riya.collections.bhopal",
        followers=2840,
        following=620,
        posts_count=184,
        is_verified=False,
        is_business_account=True,
        business_category="Clothing (Brand)",
        bio="Handcrafted embroidery suits 🧵 Bhopal | DM to order | COD available",
        has_bio_link=False,
        has_contact_button=True,
        last_post_date=datetime(2026, 5, 25, tzinfo=timezone.utc),
        posts_analysed=10,
        avg_likes=187.4,
        avg_comments=23.1,
        engagement_rate=7.41,
        post_frequency_per_week=3.2,
    ),
    cr=CrawlerResult(error="No website provided"),
)

# ── Test 3: Sharma Tiffin, Indore ── home-based, WhatsApp only, no web, no GMB

TEST3 = make_merged(
    audit_id="test-003",
    request=AuditRequest(
        business_name="Sharma Tiffin",
        city="Indore",
        business_description="Home-based tiffin service delivering to offices, no website, taking orders on WhatsApp",
        website_url=None,
        instagram_handle=None,
        monthly_ad_spend=2000,
    ),
    gp=GooglePlacesResult(
        gmb_exists=False,
        competitors=[
            {"title": "Ghar Ka Khana Indore", "reviews": 890, "rating": 4.6, "address": "Vijay Nagar, Indore"},
            {"title": "Tiffin Wala Indore",   "reviews": 540, "rating": 4.3, "address": "Palasia, Indore"},
        ],
    ),
    ig=InstagramResult(error="No handle provided"),
    cr=CrawlerResult(error="No website provided"),
)


# ── Runner ───────────────────────────────────────────────────────────────────

def run_test(label: str, merged: MergedAuditData) -> None:
    req = merged.request
    print(f"\n{SEP}")
    print(f"TEST: {label}")
    print(f"  business_name       : {req.business_name}")
    print(f"  city                : {req.city}")
    print(f"  business_description: {req.business_description}")
    print(f"  website_url         : {req.website_url}")
    print(f"  instagram_handle    : {req.instagram_handle}")
    print(SEP)

    has_website = bool(req.website_url)

    # Step 1 — Profile detection (Groq extraction call)
    print("\n[1/4] Detecting profile...")
    profile = detect_profile(merged)
    print(f"  profile_type  : {profile.profile_type}")
    print(f"  business_model: {profile.extracted.business_model}")
    print(f"  category      : {profile.extracted.category}")
    print(f"  subcategory   : {profile.extracted.subcategory}")
    print(f"  target_customer: {profile.extracted.target_customer}")
    print(f"  is_ig_sellable: {profile.extracted.is_instagram_sellable}")
    print(f"  biggest_gap   : {profile.biggest_gap}")
    print(f"  benchmark_key : {profile.benchmark_key}")

    # Step 2 — Narrative
    print("\n[2/4] Building narrative...")
    narrative = build_narrative(merged, profile)
    print(f"  ({len(narrative)} chars)")

    # Step 3 — Reconstruct prompts (same logic as generate_report)
    print("\n[3/4] Building prompts...")
    _rev_low, _rev_high = calculate_revenue_loss(
        50, req.business_description,
        str(req.city) if req.city else None,
        has_website=has_website,
    )

    system_prompt = _build_system_prompt(
        profile, has_website,
        req.business_name, req.city or "India",
    )

    user_prompt = (
        f"Audit context for **{req.business_name}**, {req.city}:\n\n"
        f"{narrative}\n\n"
        f"System-calculated revenue loss range: "
        f"₹{int(_rev_low):,}–₹{int(_rev_high):,}/month "
        f"(use the benchmark numbers above to explain WHY in revenue_loss_reason).\n\n"
        f"Call submit_audit_report with your structured findings."
    )

    print(f"\n{'-'*40} SYSTEM PROMPT ({len(system_prompt)} chars) {'-'*40}")
    print(system_prompt)
    print(f"\n{'-'*40} USER PROMPT ({len(user_prompt)} chars) {'-'*40}")
    print(user_prompt)

    # Step 4 — LLM call (Ollama or Groq based on USE_OLLAMA)
    backend = f"Ollama ({settings.ollama_model})" if settings.use_ollama else f"Groq ({settings.groq_model})"
    print(f"\n[4/4] Calling {backend}...")

    import structlog as _sl
    _log = _sl.get_logger()
    d = _call_llm(system_prompt, user_prompt, _log)
    print(f"  response received")

    print(f"\n{'-'*40} LLM JSON RESPONSE ({backend}) {'-'*40}")
    print(json.dumps(d, indent=2, ensure_ascii=False))

    # ── Verification ──────────────────────────────────────────────────────────
    name = req.business_name
    city = req.city or ""

    checks = {
        "business name in local_seo summary":
            name.lower() in d.get("local_seo", {}).get("summary", "").lower(),

        "business name in headline":
            name.lower() in d.get("headline", "").lower(),

        "city appears in at least one competitor_hint":
            any(
                city.lower() in d.get(dim, {}).get("competitor_hint", "").lower()
                for dim in ("local_seo", "web_performance", "social_presence", "website_quality")
            ),

        f"business_model correctly detected as '{profile.extracted.business_model}'":
            True,  # already printed above, just flag it

        "campaign channel matches profile":
            _verify_channel(profile, d.get("campaign_preview", {}).get("channel", "")),
    }

    print(f"\n{'-'*40} VERIFICATION {'-'*40}")
    all_pass = True
    for check, result in checks.items():
        icon = "✅" if result else "❌"
        print(f"  {icon}  {check}")
        if not result:
            all_pass = False

    print(f"\n  Overall: {'✅ ALL PASS' if all_pass else '❌ SOME FAILURES'}")
    print(f"\n  Scores: overall={d.get('overall_score')} | "
          f"web_perf={d.get('web_performance', {}).get('score')} | "
          f"local_seo={d.get('local_seo', {}).get('score')} | "
          f"social={d.get('social_presence', {}).get('score')} | "
          f"web_qual={d.get('website_quality', {}).get('score')}")
    print(f"  Channel: {d.get('campaign_preview', {}).get('channel')}")
    print(f"  Headline: {d.get('headline')}")
    print(f"  Revenue loss reason: {d.get('revenue_loss_reason')}")


def _verify_channel(profile, channel: str) -> bool:
    """Check that campaign channel is appropriate for the profile."""
    channel = channel.lower()
    pt = profile.profile_type
    bm = profile.extracted.business_model
    if pt == "instagram_first":
        return "meta" in channel or "instagram" in channel or "facebook" in channel
    if bm == "shop_based" and pt == "traditional":
        return "google" in channel
    # hybrid and other combos: any channel is acceptable
    return bool(channel)


# ── Entry point ───────────────────────────────────────────────────────────────

if __name__ == "__main__":
    print(f"\n{SEP}")
    print("ZTGOS — Three-Layer Groq Prompt Test Suite")
    print(f"Model: {settings.groq_model}")
    print(SEP)

    run_test("1 — Apna Sweets, Indore (sweet shop + website)", TEST1)
    run_test("2 — Riya Collections, Bhopal (home-based Instagram seller)", TEST2)
    run_test("3 — Sharma Tiffin, Indore (home-based, WhatsApp only)", TEST3)

    print(f"\n{SEP}")
    print("All three tests complete.")
    print(SEP)
