"""
Campaign brief builder — pure Python, no LLM call.

Runs BEFORE the Groq report prompt to pre-compute campaign strategy from
deterministic signals. The resulting CampaignBrief is injected into the
Groq prompt so the model writes hyper-specific, locally-grounded campaign copy.

Rules enforced (injected into Groq via as_prompt_block()):
  C1 — Primary channel locked to profile + worst dimension
  C2 — Campaign objective = fixing the worst dimension
  C3 — Budget-tier rules: zero/low/medium/high each get different tactics
  C4 — Roadmap specificity: Week 1 must be specific to business_description
  C5 — Ad copies: business name + city + local hook, never generic
  C6 — Tone: derived from business_description keywords
  C7 — Peak season urgency: inject if within 60 days
"""
import sys
from dataclasses import dataclass
from datetime import date
from pathlib import Path
from typing import Literal, Optional

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from pipeline.profile_detector import ProfileContext


# ── City context ─────────────────────────────────────────────────────────────

CITY_CONTEXT: dict[str, dict] = {
    "indore": {
        "markets":     ["Sarafa Bazaar", "Rajwada", "Chappan Dukan", "Khajuri Bazaar"],
        "landmarks":   ["Rajwada Palace", "Lal Bagh Palace", "Vijay Nagar Square"],
        "local_terms": ["poha-jalebi crowd", "Sarafa night crowd", "56 Dukan regulars"],
        "peak_times":  ["evening Chappan Dukan rush", "Sunday Sarafa market", "festival season at Rajwada"],
        "language_hint": "Mix Hindi with English naturally — Indore audiences respond well to 'bilkul sahi' energy.",
        "ad_hook": "Sarafa Bazaar favourite since",
    },
    "mumbai": {
        "markets":     ["Dadar Market", "Colaba Causeway", "Crawford Market", "Linking Road"],
        "landmarks":   ["Gateway of India", "Bandra Bandstand", "Marine Drive"],
        "local_terms": ["vada pav crowd", "local train commuters", "SoBo crowd", "suburbia families"],
        "peak_times":  ["post-office rush", "weekend Bandra crowd", "monsoon homebody season"],
        "language_hint": "Fast-paced, punchy language. 'ekdum mast deal' energy.",
        "ad_hook": "Mumbai's trusted",
    },
    "delhi": {
        "markets":     ["Connaught Place", "Lajpat Nagar", "Chandni Chowk", "Sarojini Nagar"],
        "landmarks":   ["India Gate", "Hauz Khas Village", "Dilli Haat"],
        "local_terms": ["CP crowd", "Dilli wale", "purani Dilli customers"],
        "peak_times":  ["winter wedding season", "Sunday market rush", "Dussehra-Diwali fortnight"],
        "language_hint": "Delhi audiences appreciate quality — lead with 'asli', 'guaranteed', 'premium'.",
        "ad_hook": "Delhi's preferred",
    },
    "bangalore": {
        "markets":     ["Commercial Street", "Indiranagar 100ft Road", "Koramangala", "Jayanagar"],
        "landmarks":   ["Cubbon Park", "MG Road", "UB City"],
        "local_terms": ["filter coffee crowd", "IT crowd", "weekend brunch seekers"],
        "peak_times":  ["Ugadi season", "IT bonus season Q4", "weekend Indiranagar rush"],
        "language_hint": "English-first — Bangalore is cosmopolitan, avoid heavy regional references.",
        "ad_hook": "Bangalore's go-to",
    },
    "bengaluru": {
        "markets":     ["Commercial Street", "Indiranagar 100ft Road", "Koramangala"],
        "landmarks":   ["Cubbon Park", "MG Road", "Lalbagh"],
        "local_terms": ["filter coffee crowd", "IT crowd", "weekend brunch seekers"],
        "peak_times":  ["Ugadi season", "weekend Indiranagar rush"],
        "language_hint": "English-first. Cosmopolitan crowd — keep it aspirational.",
        "ad_hook": "Bengaluru's trusted",
    },
    "hyderabad": {
        "markets":     ["Laad Bazaar", "Begum Bazaar", "Banjara Hills Road No.12"],
        "landmarks":   ["Charminar", "Golconda Fort", "HITEC City"],
        "local_terms": ["biryani crowd", "Charminar tourist rush", "HITEC City lunch crowd"],
        "peak_times":  ["Ramadan season", "Bonalu festival", "IT company lunch hours"],
        "language_hint": "Telugu + Urdu mix resonates. 'Ek dum mast' and 'badhiya' work well.",
        "ad_hook": "Hyderabad's neighbourhood",
    },
    "pune": {
        "markets":     ["FC Road", "MG Road", "Camp", "Koregaon Park"],
        "landmarks":   ["Shaniwar Wada", "Aga Khan Palace", "Sinhagad Fort"],
        "local_terms": ["chai tapri crowd", "college crowd FC Road", "IT park lunch rush"],
        "peak_times":  ["Ganesh Chaturthi season", "college semester start", "monsoon café season"],
        "language_hint": "Pune crowd is educated and discerning. Quality and authenticity win.",
        "ad_hook": "Pune's local favourite",
    },
    "jaipur": {
        "markets":     ["Johari Bazaar", "Bapu Bazaar", "Tripolia Bazaar", "C-Scheme"],
        "landmarks":   ["Hawa Mahal", "Amber Fort", "City Palace"],
        "local_terms": ["rajasthani clientele", "tourist traffic", "wedding shopping crowd"],
        "peak_times":  ["wedding season Nov-Feb", "Jaipur Literature Festival", "Diwali shopping rush"],
        "language_hint": "Heritage and tradition sell here. 'Padharo mhare des' warmth.",
        "ad_hook": "Jaipur's trusted",
    },
    "bhopal": {
        "markets":     ["New Market", "Chowk Bazaar", "MP Nagar", "Bittan Market"],
        "landmarks":   ["Upper Lake", "Van Vihar", "Bhojpur Temple"],
        "local_terms": ["poha crowd", "shaam ki chai regulars", "Sunday New Market crowd"],
        "peak_times":  ["Navratri season", "Bhopal Mahotsav", "winter morning market rush"],
        "language_hint": "Warm and local — community and family values resonate.",
        "ad_hook": "Bhopal's own",
    },
    "lucknow": {
        "markets":     ["Hazratganj", "Aminabad", "Chowk", "Gomti Nagar"],
        "landmarks":   ["Bara Imambara", "Rumi Darwaza", "Residency"],
        "local_terms": ["nawabi crowd", "Hazratganj evening strollers", "Lucknowi tehzeeb"],
        "peak_times":  ["Eid shopping at Aminabad", "wedding season Gomti Nagar", "winter biryani season"],
        "language_hint": "Courtesy and quality first. 'Aap ki khidmat mein' hospitality tone.",
        "ad_hook": "Lucknow's nawabi choice",
    },
    "surat": {
        "markets":     ["Textile Market", "Begampura", "Ring Road", "Adajan"],
        "landmarks":   ["Dumas Beach", "Surat Castle", "Diamond Nagar"],
        "local_terms": ["diamond merchant crowd", "textile trader audience", "Gujarati family shoppers"],
        "peak_times":  ["Diwali textile rush", "Uttarayan kite season", "wedding season Nov-Feb"],
        "language_hint": "Gujarati business mindset — value for money and quick ROI resonate.",
        "ad_hook": "Surat's trusted",
    },
    "ahmedabad": {
        "markets":     ["CG Road", "Navrangpura", "Law Garden", "Manek Chowk"],
        "landmarks":   ["Sabarmati Ashram", "Kankaria Lake", "Manek Chowk"],
        "local_terms": ["fafda-jalebi crowd", "garba season audience", "Manek Chowk night food lovers"],
        "peak_times":  ["Navratri garba season", "Uttarayan Jan 14", "Diwali shopping CG Road"],
        "language_hint": "Gujarati community pride — local success stories and community references.",
        "ad_hook": "Ahmedabad's neighbourhood favourite",
    },
    "chennai": {
        "markets":     ["T Nagar", "Pondy Bazaar", "Mylapore", "Nungambakkam"],
        "landmarks":   ["Marina Beach", "Kapaleeshwarar Temple", "Elliot's Beach"],
        "local_terms": ["filter coffee crowd", "T Nagar saree shoppers", "Marina evening crowd"],
        "peak_times":  ["Pongal season", "Tamil New Year", "wedding season May and Nov"],
        "language_hint": "Tamil cultural pride. 'Namma Chennai' references and local pride work well.",
        "ad_hook": "Chennai's trusted",
    },
    "kolkata": {
        "markets":     ["New Market", "Park Street", "Gariahat", "College Street"],
        "landmarks":   ["Victoria Memorial", "Howrah Bridge", "Dakshineswar Temple"],
        "local_terms": ["mishti doi lovers", "Durga Puja crowd", "adda culture regulars"],
        "peak_times":  ["Durga Puja 5 days", "Poila Boishakh", "winter Park Street season"],
        "language_hint": "Kolkata appreciates culture and emotion. Poetic tone with local warmth wins.",
        "ad_hook": "Kolkata's beloved",
    },
    "kochi": {
        "markets":     ["MG Road", "Broadway Market", "Lulu Mall area", "Mattancherry"],
        "landmarks":   ["Fort Kochi", "Cherai Beach", "Marine Drive"],
        "local_terms": ["backwater tourist crowd", "Syrian Christian families", "Fort Kochi art lovers"],
        "peak_times":  ["Onam season", "Christmas in Fort Kochi", "tourist peak Dec-Feb"],
        "language_hint": "Quality-conscious educated audience. Authenticity and eco signals work.",
        "ad_hook": "Kochi's trusted",
    },
    "chandigarh": {
        "markets":     ["Sector 17 Plaza", "Elante Mall", "Sector 22 Market"],
        "landmarks":   ["Rock Garden", "Sukhna Lake", "Rose Garden"],
        "local_terms": ["lassi crowd", "Sector 17 evening walkers", "university crowd"],
        "peak_times":  ["Lohri season", "Baisakhi", "summer rooftop season April-June"],
        "language_hint": "Punjab energy — vibrant, aspirational, community-driven. 'Zabardast' lands well.",
        "ad_hook": "Chandigarh's favourite",
    },
}

_CITY_ALIASES = {
    "bengaluru": "bangalore",
    "new delhi": "delhi",
    "bombay":    "mumbai",
    "calcutta":  "kolkata",
    "cochin":    "kochi",
    "madras":    "chennai",
}


def _get_city_context(city: Optional[str]) -> dict:
    if not city:
        return {}
    key = city.lower().strip()
    key = _CITY_ALIASES.get(key, key)
    return CITY_CONTEXT.get(key, {})


# ── Peak season detection ─────────────────────────────────────────────────────

_MONTH_ABBRS = {
    "jan": 1, "feb": 2, "mar": 3, "apr": 4, "may": 5, "jun": 6,
    "jul": 7, "aug": 8, "sep": 9, "oct": 10, "nov": 11, "dec": 12,
}


def _peak_within_60_days(peak_season_text: str) -> bool:
    """Return True if any month in the peak season string is within 60 days."""
    today = date.today()
    text = peak_season_text.lower()
    nearest: Optional[int] = None
    for abbr, month_num in _MONTH_ABBRS.items():
        if abbr in text:
            candidate = date(today.year, month_num, 1)
            if candidate <= today:
                candidate = date(today.year + 1, month_num, 1)
            days = (candidate - today).days
            if nearest is None or days < nearest:
                nearest = days
    return nearest is not None and nearest <= 60


# ── Tone derivation ───────────────────────────────────────────────────────────

_TONE_KEYWORDS: list[tuple[str, str]] = [
    ("b2b", "formal"), ("wholesale", "formal"), ("manufacturer", "formal"),
    ("supplier", "formal"), ("corporate", "formal"), ("industrial", "formal"),
    ("consultant", "formal"), ("chartered", "formal"), ("software", "formal"),
    ("fashion", "aspirational"), ("boutique", "aspirational"), ("jewellery", "aspirational"),
    ("jewelry", "aspirational"), ("designer", "aspirational"), ("luxury", "aspirational"),
    ("wedding", "aspirational"), ("bridal", "aspirational"), ("salon", "aspirational"),
    ("beauty", "aspirational"), ("interior", "aspirational"),
    ("gym", "motivational"), ("fitness", "motivational"), ("yoga", "motivational"),
    ("clinic", "trustworthy"), ("doctor", "trustworthy"), ("dental", "trustworthy"),
    ("pharmacy", "trustworthy"), ("hospital", "trustworthy"),
    ("food", "friendly"), ("restaurant", "friendly"), ("sweet", "friendly"),
    ("mithai", "friendly"), ("bakery", "friendly"), ("cafe", "friendly"),
    ("tiffin", "friendly"), ("dhaba", "friendly"), ("chai", "friendly"),
    ("namkeen", "friendly"), ("catering", "friendly"),
]

_TONE_GUIDANCE = {
    "formal":       "Professional, respectful language. No slang. Lead with credentials and trust.",
    "aspirational": "Evocative, image-driven copy. Paint a picture. Use 'exclusive', 'handcrafted', 'curated'.",
    "motivational": "Energy and transformation. 'Start today', 'See results in 30 days', 'Be your best'.",
    "trustworthy":  "Calm, evidence-based. Certifications, experience, safety signals. No hype.",
    "friendly":     "Warm, conversational, community-focused. Use 'we', 'your family', 'neighbours'.",
}


def _derive_tone(business_description: Optional[str]) -> str:
    if not business_description:
        return "friendly"
    desc = business_description.lower()
    for keyword, tone in _TONE_KEYWORDS:
        if keyword in desc:
            return tone
    return "friendly"


# ── Campaign objective map ────────────────────────────────────────────────────

_OBJECTIVE_MAP = {
    "local_seo":       "get discovered on Google Maps and rank for 'near me' searches",
    "web_performance": "convert website visitors into paying customers",
    "social_presence": "build brand awareness and grow a local social following",
    "website_quality": "improve website trust signals so visitors become customers",
}

_OBJECTIVE_FOCUS = {
    "local_seo":       "Every ad, keyword, and roadmap step must drive Google Maps visibility and local search ranking.",
    "web_performance": "Every recommendation must reduce bounce rate and increase enquiries from the website.",
    "social_presence": "Every piece of content and ad must grow followers, engagement, and brand recall.",
    "website_quality": "Every action must improve the website's ability to convert visitors into buyers.",
}


def _worst_dimension(scores: dict[str, int]) -> str:
    if not scores:
        return "local_seo"
    return min(scores, key=lambda k: scores[k])


# ── Channel derivation + exclusions ──────────────────────────────────────────

def _derive_primary_channel(profile: ProfileContext, worst_dim: str) -> str:
    pt = profile.profile_type
    bm = profile.extracted.business_model
    if pt == "instagram_first":
        return "Meta Ads (Instagram Reels + Stories)"
    if bm == "home_based":
        return "WhatsApp Business + Meta Ads" if worst_dim == "social_presence" else "Meta Ads"
    if worst_dim == "local_seo":
        return "Google Ads (local search + Maps)"
    if worst_dim == "social_presence":
        return "Meta Ads (Instagram/Facebook)"
    if bm == "shop_based":
        return "Google Ads (local search)"
    if pt == "hybrid":
        return "Google Ads + Meta Ads"
    return "Google Ads"


def _channel_exclusions(channel: str, profile: ProfileContext) -> str:
    pt = profile.profile_type
    bm = profile.extracted.business_model
    if pt == "instagram_first":
        return "NEVER suggest Google Search Ads or Maps campaigns as primary. This is a social-first business."
    if "google" in channel.lower() and "meta" not in channel.lower():
        return "NEVER suggest Instagram Reels strategy, Meta Ads, or influencer campaigns as the primary channel."
    if "meta" in channel.lower() and "google" not in channel.lower():
        return "NEVER suggest Google Ads as primary. Social and WhatsApp are the right channels here."
    if bm == "home_based":
        return "NEVER recommend opening a physical shop or outdoor advertising. All actions must work from a phone."
    return "Stick to the recommended channel. Do not diversify until Week 4."


# ── Budget tier rules ─────────────────────────────────────────────────────────

BudgetTier = Literal["zero", "low", "medium", "high"]


def _budget_tier(monthly_ad_spend: Optional[float]) -> BudgetTier:
    if not monthly_ad_spend or monthly_ad_spend == 0:
        return "zero"
    if monthly_ad_spend < 5000:
        return "low"
    if monthly_ad_spend < 20000:
        return "medium"
    return "high"


def _budget_tier_rules(tier: BudgetTier, channel: str, amount: float) -> str:
    if tier == "zero":
        return (
            "Zero paid budget — quick_wins and roadmap MUST contain ONLY free actions:\n"
            "  - GMB: add photos, update hours, respond to reviews\n"
            "  - Instagram: fix bio link, post 3x/week with product photos and prices\n"
            "  - WhatsApp: set status to product photos daily, create broadcast list\n"
            "  - Google: ask every customer to leave a review via WhatsApp message\n"
            "  Do NOT include a campaign_preview with paid ads. Set monthly_budget_inr=0."
        )
    if tier == "low":
        return (
            f"Low budget — ₹{int(amount):,}/month. ONE paid channel only: {channel}.\n"
            "  - Pick 3–5 hyper-local, high-intent keywords only\n"
            "  - No broad targeting, no audience expansion\n"
            "  - Bid on '[business type] near me [city]' exact phrases\n"
            "  - Week 1–2: test. Week 3–4: put 80% of budget on the single best-performing keyword."
        )
    if tier == "medium":
        return (
            f"Medium budget — ₹{int(amount):,}/month. Two channels max.\n"
            f"  - Primary (60%): {channel}\n"
            "  - Secondary (40%): retargeting or WhatsApp broadcast\n"
            "  - Week 1–2: test both channels with small budgets\n"
            "  - Week 3: double down on winner, pause underperformer\n"
            "  - Week 4: scale + add seasonal copy if peak season is near"
        )
    return (
        f"High budget — ₹{int(amount):,}/month. Full funnel:\n"
        f"  - Awareness (30%): Instagram Reels or Display Ads\n"
        f"  - Consideration (40%): {channel} with multiple ad groups\n"
        "  - Conversion (30%): retargeting warm audiences\n"
        "  - A/B test 2 versions of each ad copy\n"
        "  - Weekly performance review, reallocate budget to top performers"
    )


# ── Roadmap Week 1 specificity ────────────────────────────────────────────────

_ROADMAP_W1_KEYWORDS: list[tuple[str, str]] = [
    ("tiffin",     "Photograph your 5 most popular tiffin combos with prices and post on WhatsApp status and Instagram"),
    ("sweet",      "Upload 10 photos of fresh mithai varieties with prices to Google Maps and Instagram"),
    ("mithai",     "Upload 10 photos of fresh mithai varieties with prices to Google Maps and Instagram"),
    ("namkeen",    "Photograph your top 5 namkeen varieties with prices, post to Google Maps and WhatsApp"),
    ("salon",      "Post 3 before/after client transformation photos on Instagram with service name and price"),
    ("beauty",     "Post 3 before/after client transformation photos on Instagram with service name and price"),
    ("bakery",     "Photograph your 5 bestselling items with prices, upload to Google Maps and Instagram"),
    ("restaurant", "Upload 10 food photos with dish names and prices to Google Maps and Instagram"),
    ("clinic",     "Add doctor's credentials, working hours, and services list to Google Business Profile"),
    ("gym",        "Post 3 transformation videos of members (with permission) and today's class schedule"),
    ("fitness",    "Post 3 transformation videos of members (with permission) and today's class schedule"),
    ("pharmacy",   "Update Google Maps with full address, hours, all medicines available, WhatsApp number"),
    ("hardware",   "Photograph your 10 most-asked items with prices, create a WhatsApp product catalogue"),
    ("jewellery",  "Post 5 product photos with weight and price on Instagram and create a WhatsApp catalogue"),
    ("clothing",   "Post 5 outfit photos with prices on Instagram and add a WhatsApp click-to-chat link"),
    ("fashion",    "Post 5 outfit photos with prices on Instagram and add a WhatsApp click-to-chat link"),
    ("catering",   "Post photos of your 3 best event setups and a menu with starting prices on Instagram"),
    ("hotel",      "Upload 15 room and amenity photos to Google Maps and add correct check-in/check-out hours"),
    ("coaching",   "Post testimonials from 3 students who cleared exams, with their scores and subjects"),
    ("furniture",  "Photograph your 5 bestselling furniture pieces with prices and upload to Google Maps"),
]


def _roadmap_week1(business_description: Optional[str]) -> str:
    if not business_description:
        return "Claim and update Google Business Profile — add photos, correct hours, WhatsApp number"
    desc = business_description.lower()
    for keyword, action in _ROADMAP_W1_KEYWORDS:
        if keyword in desc:
            return action
    return "Photograph your top 5 products/services with prices and upload to Google Maps and Instagram"


# ── Target audience ───────────────────────────────────────────────────────────

_MODEL_AUDIENCE_PREFIX = {
    "home_based":   "Home delivery customers and WhatsApp order buyers",
    "shop_based":   "Walk-in customers and local neighbourhood shoppers",
    "online_only":  "Online buyers browsing on mobile",
    "hybrid":       "Both walk-in and online customers",
}


def _target_audience(profile: ProfileContext) -> str:
    prefix = _MODEL_AUDIENCE_PREFIX.get(profile.extracted.business_model, "Local customers")
    customer = profile.extracted.target_customer
    if customer and customer.lower() not in ("walk-in local customers", "local customers"):
        return f"{prefix} — specifically {customer}"
    return prefix


# ── Output dataclass ──────────────────────────────────────────────────────────

@dataclass
class CampaignBrief:
    primary_channel:      str
    campaign_objective:   str
    budget_tier:          BudgetTier
    tone:                 str
    urgency_trigger:      str
    local_hooks:          dict
    target_audience:      str
    quick_wins_only:      bool
    worst_dimension:      str
    monthly_ad_spend:     float
    business_description: Optional[str]
    business_name:        str
    city:                 str
    profile:              "ProfileContext"

    def as_prompt_block(self) -> str:
        """
        Return detailed campaign instructions for Groq.
        Encodes all 7 rules so the model produces hyper-specific,
        locally-grounded, budget-matched campaign content.
        """
        hooks     = self.local_hooks
        channel   = self.primary_channel
        tier      = self.budget_tier
        biz       = self.business_name
        city      = self.city
        desc      = self.business_description or ""
        peak_soon = _peak_within_60_days(self.urgency_trigger)

        lang    = hooks.get("language_hint", "")

        # Objective focus sentence
        obj_focus = _OBJECTIVE_FOCUS.get(self.worst_dimension, "Address the biggest gap identified above.")

        # Budget rules block
        budget_block = _budget_tier_rules(tier, channel, self.monthly_ad_spend)

        # Week 1 specific action
        w1 = _roadmap_week1(desc)

        # Tone guidance
        tone_guide = _TONE_GUIDANCE.get(self.tone, _TONE_GUIDANCE["friendly"])

        # Channel exclusion warning
        exclusion = _channel_exclusions(channel, self.profile)

        # Peak season block
        if peak_soon:
            peak_block = (
                f"⚠️  PEAK SEASON ALERT — {self.urgency_trigger}\n"
                f"  The campaign hook line, at least one ad copy headline, and Week 2 roadmap\n"
                f"  MUST reference the upcoming peak season explicitly."
            )
        else:
            peak_block = (
                f"Peak season ({self.urgency_trigger.replace('Peak season is coming: ', '').split('.')[0]}) "
                f"is not within 60 days. Mention it in Week 4 roadmap as preparation."
            )

        return f"""
CAMPAIGN BRIEF — FOLLOW ALL 7 RULES FOR CAMPAIGN CONTENT:

RULE C1 — PRIMARY CHANNEL: {channel}
  campaign_preview.channel MUST be exactly "{channel}".
  {exclusion}

RULE C2 — CAMPAIGN OBJECTIVE: {self.campaign_objective}
  {obj_focus}

RULE C3 — BUDGET ({tier.upper()} — ₹{int(self.monthly_ad_spend):,}/month):
  {budget_block}

RULE C4 — ROADMAP SPECIFICITY (this is a "{desc}" business):
  roadmap_weeks[0] (Week 1) MUST be: "{w1}"
  Each subsequent week must be specific to {biz} in {city}, not generic.
  NEVER write generic steps like "create content" or "run ads" — be specific.

RULE C5 — AD COPY REQUIREMENTS:
  Every ad headline MUST include "{biz}".
  Every ad description MUST mention "{city}".
  Use ONLY the business name and city — do NOT invent locality names, market names,
  or neighbourhood references (e.g. no "Sarafa Bazaar", "Laad Bazaar") unless the
  business owner explicitly mentioned them in their description.
  Good headline format: "{biz} — [specific product or service]"
  Good description format: "[specific product/service] in {city} · [price or benefit] · [CTA]"
  NEVER write: "Get 10% off", "Best quality guaranteed", "Call now for a free quote",
               "Limited time offer", "We are the best", or any other generic copy.
  {f'Language tip: {lang}' if lang else ''}

RULE C6 — TONE ({self.tone.upper()}):
  {tone_guide}
  Target audience: {self.target_audience}.

RULE C7 — PEAK SEASON:
  {peak_block}"""


# ── Public entry point ────────────────────────────────────────────────────────

def build_campaign_brief(
    profile: ProfileContext,
    dimension_scores: dict[str, int],
    business_description: Optional[str],
    city: Optional[str],
    monthly_ad_spend: Optional[float],
    business_name: str = "",
) -> CampaignBrief:
    """Build a CampaignBrief from deterministic signals before calling Groq."""
    worst    = _worst_dimension(dimension_scores)
    tier     = _budget_tier(monthly_ad_spend)
    channel  = _derive_primary_channel(profile, worst)
    obj      = _OBJECTIVE_MAP.get(worst, "grow your local digital presence")
    tone     = _derive_tone(business_description)
    urgency  = _urgency_trigger(profile.benchmark)
    hooks    = _get_city_context(city)
    audience = _target_audience(profile)

    return CampaignBrief(
        primary_channel      = channel,
        campaign_objective   = obj,
        budget_tier          = tier,
        tone                 = tone,
        urgency_trigger      = urgency,
        local_hooks          = hooks,
        target_audience      = audience,
        quick_wins_only      = (tier == "zero"),
        worst_dimension      = worst,
        monthly_ad_spend     = float(monthly_ad_spend or 0),
        business_description = business_description,
        business_name        = business_name,
        city                 = city or "India",
        profile              = profile,
    )


def _urgency_trigger(benchmark: dict) -> str:
    peak = benchmark.get("peak_season", "")
    if not peak:
        return "Launch now — every week without a campaign is customers choosing competitors."
    return f"Peak season is coming: {peak}. Campaigns started before the peak see 2–3× higher returns."
