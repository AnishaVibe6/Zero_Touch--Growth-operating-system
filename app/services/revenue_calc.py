"""
Deterministic revenue loss estimator for Indian MSMEs.

Formula:
  gap            = (100 - overall_score) / 100
  revenue_loss   = gap × lost_fraction × monthly_footfall × city_multiplier × avg_order_value

Low estimate uses lost_fraction=0.30, high uses 0.50.
"""

# ── City tier lookup ────────────────────────────────────────────────────────────

_TIER1 = {
    "mumbai", "delhi", "new delhi", "bangalore", "bengaluru",
    "hyderabad", "chennai", "kolkata", "calcutta", "pune", "ahmedabad",
}
_TIER2 = {
    "indore", "bhopal", "jaipur", "lucknow", "kanpur", "nagpur", "surat",
    "vadodara", "baroda", "patna", "agra", "coimbatore", "visakhapatnam",
    "vizag", "kochi", "cochin", "chandigarh", "mysore", "mysuru",
    "bhubaneswar", "ranchi", "amritsar", "guwahati", "nashik", "faridabad",
    "meerut", "rajkot", "varanasi", "jodhpur", "jabalpur", "srinagar",
    "aurangabad", "dhanbad", "allahabad", "prayagraj", "raipur", "gwalior",
    "vijayawada", "madurai", "hubli", "tiruchirappalli", "trichy",
    "thiruvananthapuram", "trivandrum", "kozhikode", "calicut", "thrissur",
    "mangalore", "mangaluru", "shimla", "dehradun", "udaipur", "ajmer",
    "bikaner", "kota", "solapur", "latur", "kolhapur", "sangli",
    "jalandhar", "ludhiana", "firozabad", "mathura", "aligarh", "bareilly",
    "moradabad", "gorakhpur", "saharanpur",
}

_CITY_MULTIPLIER = {1: 1.5, 2: 1.0, 3: 0.65}


def _city_tier(city: str | None) -> int:
    if not city:
        return 2
    c = city.lower().strip()
    if any(t in c for t in _TIER1):
        return 1
    if any(t in c for t in _TIER2):
        return 2
    return 3


# ── Category params: (monthly_footfall_mid, avg_order_value_inr) ───────────────

_CATEGORY_PARAMS: dict[str, tuple[int, int]] = {
    "restaurant":  (900,  400),
    "dhaba":       (700,  300),
    "cafe":        (700,  280),
    "coffee":      (600,  250),
    "sweet":       (700,  450),
    "sweets":      (700,  450),
    "mithai":      (700,  450),
    "namkeen":     (600,  300),
    "bakery":      (650,  320),
    "salon":       (450,  650),
    "beauty":      (450,  650),
    "parlour":     (450,  650),
    "parlor":      (450,  650),
    "spa":         (300,  900),
    "barber":      (500,  300),
    "retail":      (1000, 750),
    "shop":        (800,  550),
    "store":       (800,  600),
    "cloth":       (600,  1200),
    "garment":     (600,  1200),
    "saree":       (400,  2000),
    "jewel":       (250,  5000),
    "jewelry":     (250,  5000),
    "hotel":       (200,  3500),
    "guest house": (150,  2000),
    "clinic":      (500,  600),
    "doctor":      (500,  600),
    "hospital":    (600,  900),
    "dental":      (350,  1200),
    "pharmacy":    (700,  320),
    "gym":         (280,  1500),
    "fitness":     (280,  1500),
    "yoga":        (200,  1200),
    "electronics": (400,  2800),
    "mobile":      (500,  2000),
    "coaching":    (200,  3000),
    "tuition":     (200,  2500),
    "school":      (150,  5000),
    "travel":      (250,  8000),
    "tour":        (250,  8000),
    "car":         (120,  18000),
    "auto":        (180,  5000),
    "mechanic":    (300,  1500),
    "hardware":    (600,  800),
    "paint":       (350,  1500),
    "furniture":   (200,  8000),
    "photographer":(150,  6000),
    "event":       (100,  15000),
    "catering":    (120,  12000),
    "packers":     (100,  8000),
    "mover":       (100,  8000),
}
_DEFAULT_PARAMS = (600, 600)


def _category_params(category: str | None) -> tuple[int, int]:
    if not category:
        return _DEFAULT_PARAMS
    cat = category.lower()
    for key, params in _CATEGORY_PARAMS.items():
        if key in cat:
            return params
    return _DEFAULT_PARAMS


# ── Public API ──────────────────────────────────────────────────────────────────

def calculate_revenue_loss(
    overall_score: int,
    business_description: str | None,
    city: str | None,
    has_website: bool = True,
) -> tuple[float, float]:
    """
    Returns (revenue_loss_low, revenue_loss_high) in INR per month.

    Conservative: 30% of theoretical gap converts to lost revenue.
    Optimistic:   50% of theoretical gap converts to lost revenue.
    No website: 40% uplift applied — a missing website is a compounding gap.
    """
    tier = _city_tier(city)
    footfall, avg_order = _category_params(business_description)
    city_mult = _CITY_MULTIPLIER[tier]

    gap = (100 - max(0, min(100, overall_score))) / 100

    base = gap * footfall * city_mult * avg_order

    low  = round(base * 0.30 / 500) * 500
    high = round(base * 0.50 / 500) * 500

    if not has_website:
        low  = round(low  * 1.4 / 500) * 500
        high = round(high * 1.4 / 500) * 500

    low  = max(8_000,   min(4_00_000, low))
    high = max(15_000,  min(6_00_000, high))
    high = max(high, low + 5_000)

    return float(low), float(high)
