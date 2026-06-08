"""
Narrative builder — pure Python, no Groq call.

Takes MergedAuditData + ProfileContext and assembles a rich plain-English
context paragraph that gets injected into the Groq report prompt.

The paragraph grounds Groq with:
  - Real business identity (name, city, description, model)
  - Live worker numbers (GMB reviews, load time, followers)
  - Category benchmark comparisons (you vs the typical sweet shop in Indore)
  - Competitor signals from SerpAPI fallback results
  - Business model language (home-based vs shop-based get different framing)
  - A closing line naming the single biggest gap

Design goal: Groq should be able to write a precise, non-generic report
from this paragraph alone, even if it never saw the raw JSON payload.
"""
import sys
from pathlib import Path
from typing import Optional

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.models.audit import MergedAuditData
from pipeline.profile_detector import ProfileContext


# ── Language tables keyed by business_model ──────────────────────────────────

_MODEL_IDENTITY: dict[str, str] = {
    "home_based":   "home-based",
    "shop_based":   "physical storefront",
    "online_only":  "online-only",
    "hybrid":       "hybrid (physical + online)",
}

_MODEL_CHANNEL_INSIGHT: dict[str, str] = {
    "home_based": (
        "For a home-based business, WhatsApp and Instagram are effectively the storefront — "
        "customers cannot walk in, so every digital touchpoint that makes contacting easy "
        "directly converts to revenue."
    ),
    "shop_based": (
        "For a physical shop, Google Maps is the single most critical digital channel — "
        "73% of Indian customers check Maps before deciding which shop to visit. "
        "Walk-in traffic lives and dies by local discoverability."
    ),
    "online_only": (
        "For an online-only business, the website IS the storefront — every second of load "
        "time and every missing trust signal (SSL, WhatsApp, structured data) directly "
        "costs conversions. Google Search and Instagram are the two primary acquisition channels."
    ),
    "hybrid": (
        "As a hybrid business serving both walk-in and online customers, performance must "
        "be strong on two fronts: Google Maps for local discovery and the website for "
        "online conversion. A gap in either channel splits the revenue potential."
    ),
}

_PROFILE_TYPE_FRAMING: dict[str, str] = {
    "instagram_first": (
        "This business has built its audience primarily through Instagram, "
        "which makes it strong on social discovery but exposed on local search — "
        "customers who find them on Maps or Google have nowhere to land."
    ),
    "traditional": (
        "This is a traditionally digital business — relying on Google Maps and word of mouth, "
        "with limited social media presence. The opportunity is to layer social proof "
        "and content on top of an existing local reputation."
    ),
    "hybrid": (
        "This business has presence on both social and local search channels, "
        "which is a strong foundation. The opportunity is to close the remaining gaps "
        "and convert the double presence into a compounding growth advantage."
    ),
}


# ── Section builders ──────────────────────────────────────────────────────────

def _opening(merged: MergedAuditData, profile: ProfileContext) -> str:
    """
    One sentence establishing who the business is.
    Uses name + city + description + business model + target customer.
    """
    req   = merged.request
    ext   = profile.extracted
    name  = req.business_name
    city  = req.city or "India"
    desc  = req.business_description or ext.category
    model = _MODEL_IDENTITY.get(ext.business_model, ext.business_model)

    spend_note = ""
    if req.monthly_ad_spend:
        spend_note = f", currently spending ₹{int(req.monthly_ad_spend):,}/month on advertising"

    return (
        f"{name} is a {model} {ext.subcategory} in {city} that {desc}, "
        f"targeting {ext.target_customer}{spend_note}."
    )


def _digital_footprint(merged: MergedAuditData, profile: ProfileContext) -> str:
    """
    2–3 sentences describing the current digital presence with real worker numbers.
    """
    gp  = merged.google_places
    ig  = merged.instagram
    cr  = merged.crawler
    req = merged.request
    parts: list[str] = []

    # GMB status
    if gp.gmb_exists:
        rating_str  = f"{gp.rating:.1f}★" if gp.rating else "unrated"
        reviews_str = f"{gp.review_count:,}" if gp.review_count else "no"
        claimed_str = "claimed and verified" if gp.is_claimed else "unclaimed"
        photos_str  = (
            f" with {gp.photos_count} photo{'s' if gp.photos_count != 1 else ''}"
            if gp.photos_count is not None else ""
        )
        parts.append(
            f"They have a {claimed_str} Google Maps listing rated {rating_str} "
            f"from {reviews_str} reviews{photos_str}."
        )
    else:
        parts.append("They have no Google Maps listing.")

    # Website
    if req.website_url:
        load = f"{cr.load_time_s:.1f}s" if cr.load_time_s else "unknown speed"
        ssl  = "HTTPS" if cr.has_ssl else "HTTP (no SSL)"
        wa   = " with a WhatsApp link" if cr.has_whatsapp_link else " but no WhatsApp link"
        parts.append(
            f"Their website ({req.website_url}) loads in {load} over mobile ({ssl}){wa}."
        )
    else:
        parts.append("They have no website.")

    # Instagram
    ig_ok = not bool(ig.error) and ig.followers is not None
    if ig_ok:
        freq  = f", posting {ig.post_frequency_per_week:.1f}× per week" if ig.post_frequency_per_week else ""
        eng   = f" ({ig.engagement_rate:.2f}% engagement)" if ig.engagement_rate else ""
        parts.append(
            f"Their Instagram has {ig.followers:,} followers{eng}{freq}."
        )
    else:
        parts.append("No Instagram data is available.")

    return " ".join(parts)


def _competitive_position(merged: MergedAuditData, profile: ProfileContext) -> str:
    """
    2–3 sentences comparing real worker numbers against:
      (a) top competitor from SerpAPI fallback results
      (b) category benchmark averages
    Only surfaces comparisons where the competitor or benchmark is BETTER than the user.
    """
    gp   = merged.google_places
    ig   = merged.instagram
    cr   = merged.crawler
    bm   = profile.benchmark
    city = merged.request.city or "India"
    cat  = profile.benchmark_key
    parts: list[str] = []

    # ── GMB reviews: user vs top competitor vs benchmark ─────────────────────
    user_reviews = gp.review_count or 0
    bm_reviews   = bm.get("avg_gmb_reviews", 0)

    # Top competitor from fallback list (sorted by review count descending)
    top_comp: Optional[dict] = None
    if gp.competitors:
        top_comp = max(gp.competitors, key=lambda c: c.get("reviews") or 0)

    comp_reviews = (top_comp.get("reviews") or 0) if top_comp else 0
    comp_name    = (top_comp.get("title") or "Top competitor") if top_comp else "Top competitor"

    if user_reviews > 0 and (comp_reviews > user_reviews or bm_reviews > user_reviews):
        if comp_reviews > user_reviews and top_comp:
            parts.append(
                f"On Google Maps, {comp_name} in {city} has {comp_reviews:,} reviews "
                f"while {merged.request.business_name} has {user_reviews:,} — "
                f"and the average {cat} in this city has around {bm_reviews:,}."
            )
        elif bm_reviews > user_reviews:
            parts.append(
                f"{cat.capitalize()}s in {city} average {bm_reviews:,} Google reviews; "
                f"{merged.request.business_name} currently has {user_reviews:,}."
            )
    elif user_reviews > 0 and user_reviews >= bm_reviews:
        parts.append(
            f"With {user_reviews:,} Google reviews, {merged.request.business_name} "
            f"leads the {cat} category in {city} (benchmark: ~{bm_reviews:,})."
        )

    # ── Website load time vs benchmark ───────────────────────────────────────
    bm_load = bm.get("avg_website_load_time", 0.0)
    if cr.load_time_s and bm_load and cr.load_time_s > bm_load:
        parts.append(
            f"Their website loads in {cr.load_time_s:.1f}s — "
            f"{cat.capitalize()}s in this city typically load in {bm_load:.1f}s, "
            f"making their site {cr.load_time_s - bm_load:.1f}s slower than expected."
        )

    # ── Instagram followers vs benchmark ─────────────────────────────────────
    ig_ok = not bool(ig.error) and ig.followers is not None
    bm_ig = bm.get("avg_instagram_followers", 0)
    if ig_ok and bm_ig:
        ig_followers = ig.followers or 0
        if ig_followers < bm_ig:
            parts.append(
                f"Active {cat}s in {city} average {bm_ig:,} Instagram followers; "
                f"{merged.request.business_name} has {ig_followers:,}."
            )
        else:
            parts.append(
                f"With {ig_followers:,} Instagram followers, {merged.request.business_name} "
                f"outpaces the {cat} benchmark of {bm_ig:,} in this city."
            )

    # ── GMB rating vs benchmark rating (rough: anything above 4.2 is good) ──
    if gp.rating is not None:
        if gp.rating < 4.2:
            parts.append(
                f"Their Google rating of {gp.rating:.1f}★ is below the 4.2★ threshold "
                f"that triggers customer trust in local search — improving this is high-priority."
            )

    if not parts:
        parts.append(
            f"No direct competitor data is available, but the typical {cat} in a Tier 2 "
            f"Indian city averages {bm_reviews:,} Google reviews and "
            f"{bm.get('avg_instagram_followers', 0):,} Instagram followers as a baseline."
        )

    return " ".join(parts)


def _business_model_insight(profile: ProfileContext) -> str:
    """One sentence grounding Groq in what the business model means for channel priority."""
    model   = profile.extracted.business_model
    insight = _MODEL_CHANNEL_INSIGHT.get(model, "")
    framing = _PROFILE_TYPE_FRAMING.get(profile.profile_type, "")
    return f"{insight} {framing}".strip()


def _instagram_sellability_note(profile: ProfileContext) -> str:
    """Optional sentence about Instagram ad potential based on product type."""
    if profile.extracted.is_instagram_sellable:
        return (
            f"The {profile.extracted.category} category is highly visual — "
            f"Instagram Reels and Meta Ads showing the product in action can "
            f"deliver strong ROI for {profile.extracted.target_customer}."
        )
    return (
        f"The {profile.extracted.category} category is intent-driven rather than impulse — "
        f"Google Ads targeting 'near me' and local keywords will outperform social ads "
        f"for reaching {profile.extracted.target_customer}."
    )


def _peak_season_note(profile: ProfileContext, city: Optional[str]) -> str:
    """One sentence about peak season timing for campaign context."""
    peak = profile.benchmark.get("peak_season", "")
    if not peak:
        return ""
    city_str = f" in {city}" if city else ""
    return (
        f"Peak season for this category{city_str} is {peak} — "
        f"campaigns launched before the peak see 2–3× higher conversion rates."
    )


def _biggest_gap_closing(profile: ProfileContext) -> str:
    """
    Final sentence — the single most critical problem, stated with urgency.
    This is the last thing Groq reads before scoring, so it should be concrete and direct.
    """
    return (
        f"The single most critical gap right now: {profile.biggest_gap_reason} "
        f"Fix this first — it is costing more revenue than any other issue on this audit."
    )


# ── Public entry point ────────────────────────────────────────────────────────

def build_narrative(merged: MergedAuditData, profile: ProfileContext) -> str:
    """
    Assemble the full context narrative for injection into the Groq report prompt.

    Returns a single multi-sentence paragraph (~180–280 words) that grounds Groq
    with specific, real-number context before it sees any raw JSON audit data.

    Section order:
      1. Business identity (name, city, description, model, target customer)
      2. Current digital footprint (GMB, website, Instagram — real numbers)
      3. Competitive position (user vs top competitor vs benchmark)
      4. Business model channel insight + profile type framing
      5. Instagram sellability and campaign channel recommendation
      6. Peak season timing
      7. Biggest gap — final urgent closing line
    """
    city = merged.request.city

    sections = [
        _opening(merged, profile),
        _digital_footprint(merged, profile),
        _competitive_position(merged, profile),
        _business_model_insight(profile),
        _instagram_sellability_note(profile),
    ]

    peak = _peak_season_note(profile, city)
    if peak:
        sections.append(peak)

    sections.append(_biggest_gap_closing(profile))

    return "\n\n".join(s for s in sections if s.strip())
