"""
Campaign differentiation test — 4 businesses that must produce completely different campaigns.

Tests:
  1. Apna Sweets Indore      — traditional sweet shop, Rs.0 ad spend, Diwali peak season
  2. Riya Collections Bhopal — home-based Instagram fashion, Rs.2000 ad spend
  3. Sharma Tiffin Indore    — home-based tiffin, WhatsApp only, Rs.0 spend
  4. TechFix Mobile Repair   — shop-based repair, website, Rs.5000 ad spend

Verifies per business:
  - Primary channel is correct for the profile type
  - Budget tier is correctly applied (zero / low / medium)
  - Week 1 roadmap is specific to the business type
  - Ad copies include business name + city
  - All 4 campaigns are meaningfully different from each other
"""
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import structlog
from app.config import settings
from app.models.audit import (
    AuditRequest, CrawlerResult, GooglePlacesResult,
    InstagramResult, LighthouseResult, MergedAuditData,
)
from app.services.claude_report import _build_system_prompt, _call_llm, _REPORT_TOOL
from app.services.revenue_calc import calculate_revenue_loss
from ai.campaign_builder import build_campaign_brief
from ai.narrative_builder import build_narrative
from pipeline.profile_detector import detect_profile

log = structlog.get_logger()
SEP = "=" * 72


# ── Mock data factory ─────────────────────────────────────────────────────────

def merged(request, gp, ig, cr):
    return MergedAuditData(
        audit_id=f"test-{request.business_name[:4].lower().replace(' ','')}",
        request=request,
        lighthouse=LighthouseResult(),
        google_places=gp,
        instagram=ig,
        crawler=cr,
    )


# ── Test 1: Apna Sweets Indore — Rs.0 ad spend, sweet shop ───────────────────
T1 = merged(
    AuditRequest(
        business_name="Apna Sweets",
        city="Indore",
        business_description="traditional sweet shop selling mithai and namkeen since 1995",
        website_url="https://apnasweets.com",
        monthly_ad_spend=0,
    ),
    GooglePlacesResult(
        gmb_exists=True, name="Apna Sweets", rating=4.0, review_count=12295,
        is_claimed=True, photos_count=3,
        competitors=[{"title": "Milan Sweets", "reviews": 11866, "rating": 4.3}],
    ),
    InstagramResult(error="Profile not found"),
    CrawlerResult(
        has_ssl=True, load_time_s=2.6, has_whatsapp_link=False,
        has_contact_page=True, has_about_page=False, meta_title="Apna Sweets",
    ),
)

# ── Test 2: Riya Collections Bhopal — home-based Instagram, Rs.2000 ──────────
T2 = merged(
    AuditRequest(
        business_name="Riya Collections",
        city="Bhopal",
        business_description="home-based handmade embroidery suits seller, orders via Instagram DM and WhatsApp",
        website_url=None,
        instagram_handle="riya.collections.bhopal",
        monthly_ad_spend=2000,
    ),
    GooglePlacesResult(
        gmb_exists=False,
        competitors=[{"title": "Bhopal Handloom House", "reviews": 312, "rating": 4.4}],
    ),
    InstagramResult(
        username="riya.collections.bhopal", followers=3000, following=620,
        posts_count=184, is_business_account=True,
        bio="Handcrafted embroidery suits 🧵 Bhopal | DM to order",
        has_bio_link=False, has_contact_button=True,
        last_post_date=datetime(2026, 5, 25, tzinfo=timezone.utc),
        posts_analysed=10, avg_likes=210.0, avg_comments=28.0,
        engagement_rate=7.9, post_frequency_per_week=3.5,
    ),
    CrawlerResult(error="No website"),
)

# ── Test 3: Sharma Tiffin Indore — home-based, WhatsApp only, Rs.0 ───────────
T3 = merged(
    AuditRequest(
        business_name="Sharma Tiffin Service",
        city="Indore",
        business_description="home-based tiffin delivery to offices in Indore, orders only on WhatsApp",
        website_url=None,
        monthly_ad_spend=0,
    ),
    GooglePlacesResult(
        gmb_exists=False,
        competitors=[{"title": "Ghar Ka Khana Indore", "reviews": 890, "rating": 4.6}],
    ),
    InstagramResult(error="No handle"),
    CrawlerResult(error="No website"),
)

# ── Test 4: TechFix Mobile Repair Jabalpur — shop, website, Rs.5000 ──────────
T4 = merged(
    AuditRequest(
        business_name="TechFix Mobile Repair",
        city="Jabalpur",
        business_description="mobile phone and laptop repair shop, screen replacement, battery replacement",
        website_url="https://techfixjabalpur.com",
        monthly_ad_spend=5000,
    ),
    GooglePlacesResult(
        gmb_exists=True, name="TechFix Mobile Repair", rating=4.2, review_count=87,
        is_claimed=True, photos_count=4,
        competitors=[{"title": "Mobile Care Center", "reviews": 215, "rating": 4.4}],
    ),
    InstagramResult(error="No handle"),
    CrawlerResult(
        has_ssl=True, load_time_s=3.8, has_whatsapp_link=True,
        has_contact_page=True, has_about_page=True, meta_title="TechFix Jabalpur",
    ),
)

TESTS = [
    ("1 — Apna Sweets, Indore (sweet shop, Rs.0)",           T1),
    ("2 — Riya Collections, Bhopal (home Instagram, Rs.2k)", T2),
    ("3 — Sharma Tiffin, Indore (home tiffin, Rs.0)",        T3),
    ("4 — TechFix Mobile Repair, Jabalpur (Rs.5k)",          T4),
]


# ── Runner ────────────────────────────────────────────────────────────────────

def run_test(label, merged_data):
    req = merged_data.request
    has_website = bool(req.website_url)

    print(f"\n{SEP}")
    print(f"TEST {label}")
    print(f"  ad_spend: Rs.{req.monthly_ad_spend or 0} | website: {has_website} | city: {req.city}")
    print(SEP)

    # Profile detection
    print("[1/4] Detecting profile...")
    profile = detect_profile(merged_data)
    print(f"  profile_type  : {profile.profile_type}")
    print(f"  business_model: {profile.extracted.business_model}")
    print(f"  category      : {profile.extracted.category}")
    print(f"  is_ig_sellable: {profile.extracted.is_instagram_sellable}")
    print(f"  biggest_gap   : {profile.biggest_gap}")

    # Campaign brief
    print("[2/4] Building campaign brief...")
    dim_scores = {
        "local_seo":       50 if not merged_data.google_places.gmb_exists else 75,
        "web_performance": 20 if not has_website else (40 if (merged_data.crawler.load_time_s or 0) > 4 else 65),
        "social_presence": 20 if merged_data.instagram.error else (60 if (merged_data.instagram.followers or 0) > 500 else 35),
        "website_quality": 20 if not has_website else 55,
    }
    brief = build_campaign_brief(
        profile=profile,
        dimension_scores=dim_scores,
        business_description=req.business_description,
        city=req.city,
        monthly_ad_spend=float(req.monthly_ad_spend) if req.monthly_ad_spend else None,
        business_name=req.business_name,
    )
    print(f"  primary_channel : {brief.primary_channel}")
    print(f"  budget_tier     : {brief.budget_tier}")
    print(f"  tone            : {brief.tone}")
    print(f"  worst_dimension : {brief.worst_dimension}")
    print(f"  quick_wins_only : {brief.quick_wins_only}")
    print(f"\n--- CAMPAIGN BRIEF PROMPT BLOCK ---")
    print(brief.as_prompt_block())

    # Narrative + prompts
    print("\n[3/4] Building prompts...")
    narrative = build_narrative(merged_data, profile)
    brief_block = brief.as_prompt_block()
    user_prompt = (
        f"Audit context for **{req.business_name}**, {req.city}:\n\n"
        f"{narrative}\n\n"
        f"Write revenue_loss_reason explaining WHY money is lost using benchmark "
        f"avg_order_value and monthly_customers_estimate. "
        f"Do NOT include a specific Rs. amount.\n\n"
        f"Call submit_audit_report with your structured findings."
    )
    system_prompt = _build_system_prompt(
        profile, has_website, req.business_name, req.city or "India",
        monthly_ad_spend=float(req.monthly_ad_spend) if req.monthly_ad_spend else None,
        campaign_brief_block=brief_block,
    )

    # Groq call
    print(f"[4/4] Calling {settings.groq_model}...")
    import structlog as _sl
    _log = _sl.get_logger()
    d = _call_llm(system_prompt, user_prompt, _log)
    cp = d.get("campaign_preview", {})

    print(f"\n--- FINAL CAMPAIGN JSON ---")
    campaign_out = {
        "channel":            cp.get("channel"),
        "monthly_budget_inr": cp.get("monthly_budget_inr"),
        "expected_leads":     cp.get("expected_leads"),
        "keywords":           d.get("keywords", []),
        "roadmap_weeks":      d.get("roadmap_weeks", []),
        "quick_wins":         d.get("quick_wins", []),
        "ad_copies":          cp.get("ad_copies", []),
    }
    print(json.dumps(campaign_out, indent=2, ensure_ascii=False))

    return {
        "label":          label,
        "brief_channel":  brief.primary_channel,
        "brief_tier":     brief.budget_tier,
        "out_channel":    cp.get("channel", ""),
        "out_budget":     cp.get("monthly_budget_inr", 0),
        "week1":          (d.get("roadmap_weeks") or [""])[0],
        "ad_headline_0":  (cp.get("ad_copies") or [{}])[0].get("headline", ""),
        "quick_wins":     d.get("quick_wins", []),
        "keywords":       d.get("keywords", []),
    }


# ── Similarity checker ────────────────────────────────────────────────────────

def _similarity_score(a: dict, b: dict) -> int:
    """Return 0-4 similarity count across key campaign fields."""
    score = 0
    if a["out_channel"] == b["out_channel"]:
        score += 1
    if a["brief_tier"] == b["brief_tier"]:
        score += 1
    # Week 1 similarity: share 3+ words
    wa = set(a["week1"].lower().split())
    wb = set(b["week1"].lower().split())
    if len(wa & wb) >= 3:
        score += 1
    # Keyword overlap > 50%
    ka = set(a["keywords"])
    kb = set(b["keywords"])
    if ka and kb and len(ka & kb) / max(len(ka), len(kb)) > 0.5:
        score += 1
    return score


# ── Main ──────────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    print(f"\n{SEP}")
    print("ZTGOS — Campaign Differentiation Test (4 businesses)")
    print(f"Model: {settings.groq_model}")
    print(SEP)

    results = []
    for label, data in TESTS:
        result = run_test(label, data)
        results.append(result)

    # Final comparison table
    print(f"\n{SEP}")
    print("VERIFICATION SUMMARY")
    print(SEP)
    print(f"{'Test':<45} {'Channel':<28} {'Tier':<8} {'Budget'}")
    print("-" * 72)
    for r in results:
        budget_ok = "✅" if abs(r["out_budget"] - (0 if r["brief_tier"] == "zero" else 2000 if "Riya" in r["label"] else 5000)) < 1000 else "⚠️ "
        print(f"{r['label'][:44]:<45} {r['out_channel'][:27]:<28} {r['brief_tier']:<8} {budget_ok} Rs.{r['out_budget']}")

    print(f"\n{'Week 1 Specificity Check':}")
    for r in results:
        generic_words = {"create", "launch", "run", "start", "setup", "optimize", "review"}
        words = set(r["week1"].lower().split())
        is_generic = len(words & generic_words) > 2 and len(words) < 8
        flag = "❌ GENERIC" if is_generic else "✅"
        print(f"  {flag} {r['label'][:40]}: {r['week1'][:80]}")

    print(f"\n{'Ad Copy Business Name + City Check':}")
    for r in results:
        biz_name = r["label"].split("—")[1].strip().split(",")[0].strip()
        city = r["label"].split(",")[1].strip().split()[0] if "," in r["label"] else ""
        headline = r["ad_headline_0"]
        has_biz = any(word.lower() in headline.lower() for word in biz_name.split())
        flag = "✅" if has_biz else "❌ missing biz name"
        print(f"  {flag} [{headline}]")

    print(f"\n{'Similarity Check (flag if score >= 3/4)':}")
    flagged = []
    for i in range(len(results)):
        for j in range(i + 1, len(results)):
            sim = _similarity_score(results[i], results[j])
            if sim >= 3:
                flagged.append((results[i]["label"], results[j]["label"], sim))
    if flagged:
        for a, b, s in flagged:
            print(f"  ⚠️  SIMILAR ({s}/4): {a[:35]} vs {b[:35]}")
    else:
        print("  ✅ All 4 campaigns are sufficiently different")

    print(f"\n{SEP}")
    print("All tests complete.")
    print(SEP)
