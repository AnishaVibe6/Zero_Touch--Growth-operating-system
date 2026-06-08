"""
Indian MSME category benchmarks for Tier 2 cities (Indore, Jaipur, Bhopal, etc.).

Used to enrich audit reports with realistic comparisons when the business description
has been fuzzy-matched to a known category. All numbers reflect mid-market businesses
in Tier 2 Indian cities — not top performers, not bottom — so the gap feels real.
"""
import difflib
from typing import TypedDict


class CategoryBenchmark(TypedDict):
    avg_gmb_reviews: int           # typical Google Maps review count
    avg_instagram_followers: int   # typical follower count for active businesses
    avg_website_load_time: float   # seconds, mobile 4G
    peak_season: str               # months when footfall spikes
    avg_order_value: int           # INR per transaction
    monthly_customers_estimate: int
    top_keywords: list[str]        # high-intent local search terms
    primary_channel: str           # best paid channel for this type


BENCHMARKS: dict[str, CategoryBenchmark] = {
    "restaurant": {
        "avg_gmb_reviews": 320,
        "avg_instagram_followers": 1800,
        "avg_website_load_time": 4.2,
        "peak_season": "Oct–Feb, wedding season",
        "avg_order_value": 400,
        "monthly_customers_estimate": 900,
        "top_keywords": ["restaurant near me", "best restaurant in {city}", "family restaurant {city}", "lunch {city}"],
        "primary_channel": "Google Ads",
    },
    "sweet shop": {
        "avg_gmb_reviews": 850,
        "avg_instagram_followers": 2200,
        "avg_website_load_time": 4.8,
        "peak_season": "Diwali, Holi, Raksha Bandhan (Oct–Nov, Mar)",
        "avg_order_value": 450,
        "monthly_customers_estimate": 700,
        "top_keywords": ["mithai shop near me", "sweets {city}", "Diwali sweets {city}", "namkeen {city}"],
        "primary_channel": "Meta Ads",
    },
    "salon": {
        "avg_gmb_reviews": 210,
        "avg_instagram_followers": 3500,
        "avg_website_load_time": 3.9,
        "peak_season": "wedding season (Nov–Feb, May)",
        "avg_order_value": 650,
        "monthly_customers_estimate": 450,
        "top_keywords": ["salon near me", "best salon {city}", "hair cut {city}", "bridal makeup {city}"],
        "primary_channel": "Meta Ads",
    },
    "clinic": {
        "avg_gmb_reviews": 180,
        "avg_instagram_followers": 900,
        "avg_website_load_time": 4.5,
        "peak_season": "monsoon (Jul–Sep), winter (Dec–Feb)",
        "avg_order_value": 600,
        "monthly_customers_estimate": 500,
        "top_keywords": ["doctor near me", "clinic {city}", "general physician {city}", "consultation {city}"],
        "primary_channel": "Google Ads",
    },
    "gym": {
        "avg_gmb_reviews": 150,
        "avg_instagram_followers": 2800,
        "avg_website_load_time": 4.1,
        "peak_season": "Jan–Mar (New Year resolutions), Jun–Aug",
        "avg_order_value": 1500,
        "monthly_customers_estimate": 280,
        "top_keywords": ["gym near me", "fitness center {city}", "gym membership {city}", "personal trainer {city}"],
        "primary_channel": "Meta Ads",
    },
    "retail clothing": {
        "avg_gmb_reviews": 140,
        "avg_instagram_followers": 4200,
        "avg_website_load_time": 5.1,
        "peak_season": "Diwali, Eid, wedding season (Oct–Feb)",
        "avg_order_value": 1200,
        "monthly_customers_estimate": 600,
        "top_keywords": ["clothing store {city}", "dress shop near me", "ethnic wear {city}", "kurti {city}"],
        "primary_channel": "Meta Ads",
    },
    "pharmacy": {
        "avg_gmb_reviews": 95,
        "avg_instagram_followers": 400,
        "avg_website_load_time": 4.4,
        "peak_season": "year-round, spikes in monsoon",
        "avg_order_value": 320,
        "monthly_customers_estimate": 700,
        "top_keywords": ["medical store near me", "pharmacy {city}", "medicine delivery {city}", "chemist near me"],
        "primary_channel": "Google Ads",
    },
    "bakery": {
        "avg_gmb_reviews": 280,
        "avg_instagram_followers": 3100,
        "avg_website_load_time": 4.3,
        "peak_season": "Christmas, New Year, Valentine's Day",
        "avg_order_value": 320,
        "monthly_customers_estimate": 650,
        "top_keywords": ["bakery near me", "cake shop {city}", "birthday cake {city}", "fresh bread {city}"],
        "primary_channel": "Meta Ads",
    },
    "jewellery": {
        "avg_gmb_reviews": 190,
        "avg_instagram_followers": 5800,
        "avg_website_load_time": 5.4,
        "peak_season": "wedding season (Nov–Feb), Dhanteras, Akshaya Tritiya",
        "avg_order_value": 5000,
        "monthly_customers_estimate": 250,
        "top_keywords": ["jewellery shop {city}", "gold jewellery {city}", "bridal jewellery {city}", "imitation jewellery {city}"],
        "primary_channel": "Meta Ads",
    },
    "electronics": {
        "avg_gmb_reviews": 165,
        "avg_instagram_followers": 1200,
        "avg_website_load_time": 4.7,
        "peak_season": "Diwali, end of academic year (May–Jun)",
        "avg_order_value": 2800,
        "monthly_customers_estimate": 400,
        "top_keywords": ["mobile shop {city}", "electronics store near me", "laptop repair {city}", "mobile repair {city}"],
        "primary_channel": "Google Ads",
    },
    "real estate": {
        "avg_gmb_reviews": 75,
        "avg_instagram_followers": 3200,
        "avg_website_load_time": 5.8,
        "peak_season": "Jan–Mar, Oct–Dec",
        "avg_order_value": 50000,
        "monthly_customers_estimate": 120,
        "top_keywords": ["property dealer {city}", "flats for sale {city}", "plot {city}", "2BHK {city}"],
        "primary_channel": "Meta Ads",
    },
    "coaching": {
        "avg_gmb_reviews": 110,
        "avg_instagram_followers": 4500,
        "avg_website_load_time": 4.0,
        "peak_season": "Apr–Jun (admissions), Nov–Jan (board prep)",
        "avg_order_value": 3000,
        "monthly_customers_estimate": 200,
        "top_keywords": ["coaching center {city}", "tuition near me", "IIT coaching {city}", "UPSC coaching {city}"],
        "primary_channel": "Meta Ads",
    },
    "hotel": {
        "avg_gmb_reviews": 420,
        "avg_instagram_followers": 2100,
        "avg_website_load_time": 5.2,
        "peak_season": "Oct–Mar (tourist season), summer holidays",
        "avg_order_value": 3500,
        "monthly_customers_estimate": 200,
        "top_keywords": ["hotel near me", "hotel in {city}", "budget hotel {city}", "rooms {city}"],
        "primary_channel": "Google Ads",
    },
    "travel agency": {
        "avg_gmb_reviews": 130,
        "avg_instagram_followers": 5500,
        "avg_website_load_time": 4.6,
        "peak_season": "Apr–Jun (summer holidays), Oct–Nov (festive)",
        "avg_order_value": 8000,
        "monthly_customers_estimate": 250,
        "top_keywords": ["tour package {city}", "travel agent {city}", "holiday package", "Goa tour from {city}"],
        "primary_channel": "Meta Ads",
    },
    "automobile workshop": {
        "avg_gmb_reviews": 145,
        "avg_instagram_followers": 600,
        "avg_website_load_time": 4.3,
        "peak_season": "monsoon (Jul–Sep), winter (Nov–Jan)",
        "avg_order_value": 1500,
        "monthly_customers_estimate": 300,
        "top_keywords": ["car service center {city}", "bike repair near me", "auto workshop {city}", "puncture repair near me"],
        "primary_channel": "Google Ads",
    },
    "furniture": {
        "avg_gmb_reviews": 85,
        "avg_instagram_followers": 2400,
        "avg_website_load_time": 5.5,
        "peak_season": "Diwali, wedding season, summer (Apr–Jun)",
        "avg_order_value": 8000,
        "monthly_customers_estimate": 200,
        "top_keywords": ["furniture shop {city}", "wooden furniture {city}", "sofa set {city}", "modular kitchen {city}"],
        "primary_channel": "Meta Ads",
    },
    "grocery": {
        "avg_gmb_reviews": 210,
        "avg_instagram_followers": 800,
        "avg_website_load_time": 4.0,
        "peak_season": "Diwali, Holi (bulk buying), year-round",
        "avg_order_value": 550,
        "monthly_customers_estimate": 1200,
        "top_keywords": ["grocery store near me", "kirana store {city}", "online grocery {city}", "supermarket near me"],
        "primary_channel": "Google Ads",
    },
    "catering": {
        "avg_gmb_reviews": 170,
        "avg_instagram_followers": 3800,
        "avg_website_load_time": 4.9,
        "peak_season": "wedding season (Nov–Feb, May), festivals",
        "avg_order_value": 12000,
        "monthly_customers_estimate": 120,
        "top_keywords": ["caterer {city}", "wedding catering {city}", "catering service near me", "event catering {city}"],
        "primary_channel": "Meta Ads",
    },
    "photographer": {
        "avg_gmb_reviews": 95,
        "avg_instagram_followers": 7200,
        "avg_website_load_time": 5.8,
        "peak_season": "wedding season (Nov–Feb), year-round for events",
        "avg_order_value": 6000,
        "monthly_customers_estimate": 150,
        "top_keywords": ["wedding photographer {city}", "photographer near me", "maternity shoot {city}", "product photography {city}"],
        "primary_channel": "Meta Ads",
    },
    "dental clinic": {
        "avg_gmb_reviews": 155,
        "avg_instagram_followers": 1100,
        "avg_website_load_time": 4.2,
        "peak_season": "year-round, slight spike post-Diwali",
        "avg_order_value": 1200,
        "monthly_customers_estimate": 350,
        "top_keywords": ["dentist near me", "dental clinic {city}", "teeth whitening {city}", "root canal {city}"],
        "primary_channel": "Google Ads",
    },
    "yoga studio": {
        "avg_gmb_reviews": 90,
        "avg_instagram_followers": 3600,
        "avg_website_load_time": 3.8,
        "peak_season": "Jan–Mar (New Year), Jun (International Yoga Day)",
        "avg_order_value": 1200,
        "monthly_customers_estimate": 200,
        "top_keywords": ["yoga class {city}", "yoga center near me", "meditation {city}", "morning yoga {city}"],
        "primary_channel": "Meta Ads",
    },
    "hardware store": {
        "avg_gmb_reviews": 115,
        "avg_instagram_followers": 350,
        "avg_website_load_time": 4.5,
        "peak_season": "construction season (Nov–Mar), pre-monsoon (Apr–Jun)",
        "avg_order_value": 800,
        "monthly_customers_estimate": 600,
        "top_keywords": ["hardware shop near me", "building material {city}", "plumbing supplies {city}", "paint shop {city}"],
        "primary_channel": "Google Ads",
    },
    "event management": {
        "avg_gmb_reviews": 80,
        "avg_instagram_followers": 6500,
        "avg_website_load_time": 5.1,
        "peak_season": "wedding season (Nov–Feb), corporate events (Jan–Mar)",
        "avg_order_value": 15000,
        "monthly_customers_estimate": 100,
        "top_keywords": ["event planner {city}", "wedding decorator {city}", "birthday party organiser {city}", "corporate event {city}"],
        "primary_channel": "Meta Ads",
    },
    "courier service": {
        "avg_gmb_reviews": 130,
        "avg_instagram_followers": 500,
        "avg_website_load_time": 3.9,
        "peak_season": "Diwali, year-end (Dec), e-commerce sale seasons",
        "avg_order_value": 300,
        "monthly_customers_estimate": 800,
        "top_keywords": ["courier service {city}", "parcel delivery near me", "same day delivery {city}", "cargo {city}"],
        "primary_channel": "Google Ads",
    },
    "interior design": {
        "avg_gmb_reviews": 70,
        "avg_instagram_followers": 8500,
        "avg_website_load_time": 5.6,
        "peak_season": "Diwali (home renovation), post-monsoon (Sep–Nov)",
        "avg_order_value": 25000,
        "monthly_customers_estimate": 80,
        "top_keywords": ["interior designer {city}", "home interior {city}", "modular kitchen {city}", "false ceiling {city}"],
        "primary_channel": "Meta Ads",
    },
    "packers and movers": {
        "avg_gmb_reviews": 200,
        "avg_instagram_followers": 700,
        "avg_website_load_time": 4.4,
        "peak_season": "Apr–Jun (transfers season), Oct–Nov",
        "avg_order_value": 8000,
        "monthly_customers_estimate": 100,
        "top_keywords": ["packers and movers {city}", "house shifting {city}", "relocation service {city}", "movers near me"],
        "primary_channel": "Google Ads",
    },
    "mobile repair": {
        "avg_gmb_reviews": 175,
        "avg_instagram_followers": 900,
        "avg_website_load_time": 4.0,
        "peak_season": "year-round, slight spike post-Diwali (new devices)",
        "avg_order_value": 800,
        "monthly_customers_estimate": 500,
        "top_keywords": ["mobile repair near me", "phone repair {city}", "screen replacement {city}", "iphone repair {city}"],
        "primary_channel": "Google Ads",
    },
    "printing": {
        "avg_gmb_reviews": 100,
        "avg_instagram_followers": 600,
        "avg_website_load_time": 4.2,
        "peak_season": "election season, Diwali (packaging), year-end",
        "avg_order_value": 1200,
        "monthly_customers_estimate": 350,
        "top_keywords": ["printing shop {city}", "flex printing {city}", "visiting card {city}", "banner printing near me"],
        "primary_channel": "Google Ads",
    },
    "driving school": {
        "avg_gmb_reviews": 120,
        "avg_instagram_followers": 1100,
        "avg_website_load_time": 4.1,
        "peak_season": "Apr–Jun (school break), Jan–Mar",
        "avg_order_value": 3500,
        "monthly_customers_estimate": 180,
        "top_keywords": ["driving school {city}", "learn driving {city}", "motor driving class near me", "RTO test {city}"],
        "primary_channel": "Meta Ads",
    },
    "pest control": {
        "avg_gmb_reviews": 140,
        "avg_instagram_followers": 500,
        "avg_website_load_time": 4.3,
        "peak_season": "pre-monsoon (May–Jun), post-monsoon (Sep–Oct)",
        "avg_order_value": 2500,
        "monthly_customers_estimate": 200,
        "top_keywords": ["pest control near me", "termite treatment {city}", "cockroach control {city}", "bed bug treatment {city}"],
        "primary_channel": "Google Ads",
    },
}

_GENERIC_BENCHMARK: CategoryBenchmark = {
    "avg_gmb_reviews": 180,
    "avg_instagram_followers": 2000,
    "avg_website_load_time": 4.5,
    "peak_season": "festive season (Oct–Nov), year-round",
    "avg_order_value": 1200,
    "monthly_customers_estimate": 400,
    "top_keywords": ["{business} near me", "best {business} {city}", "{business} {city}"],
    "primary_channel": "Google Ads",
}


def get_closest_benchmark(extracted_category: str | None) -> tuple[str, CategoryBenchmark]:
    """
    Fuzzy-match a Groq-extracted category string to the nearest benchmark key.

    Returns (matched_key, benchmark_dict).
    Falls back to ("generic", _GENERIC_BENCHMARK) when:
      - extracted_category is None/empty
      - best similarity score is below 0.60

    Uses difflib.SequenceMatcher for primary ranking, then also checks whether
    any benchmark key word appears as a substring (catches "sells sweets" → "sweet shop").
    """
    if not extracted_category:
        return "generic", _GENERIC_BENCHMARK

    query = extracted_category.lower().strip()
    keys  = list(BENCHMARKS.keys())

    # Substring pass — if any benchmark key is contained in the query, prefer it
    for key in keys:
        if key in query or any(word in query for word in key.split()):
            return key, BENCHMARKS[key]

    # Fuzzy pass — SequenceMatcher ratio across all keys
    scores = [
        (key, difflib.SequenceMatcher(None, query, key).ratio())
        for key in keys
    ]
    best_key, best_score = max(scores, key=lambda x: x[1])

    if best_score >= 0.60:
        return best_key, BENCHMARKS[best_key]

    return "generic", _GENERIC_BENCHMARK
