import re
from datetime import datetime
from decimal import Decimal
from typing import Literal, Optional
from uuid import UUID

from pydantic import BaseModel, HttpUrl, field_validator


class AuditRequest(BaseModel):
    business_name: str
    city: Optional[str] = None
    business_description: Optional[str] = None  # free-text: "sells sweets and namkeen"
    website_url: Optional[HttpUrl] = None
    instagram_handle: Optional[str] = None
    monthly_ad_spend: Optional[Decimal] = None  # INR

    @field_validator("instagram_handle", mode="before")
    @classmethod
    def clean_instagram_handle(cls, v: Optional[str]) -> Optional[str]:
        if not v:
            return v
        v = v.strip()
        # extract username from full URL (e.g. https://www.instagram.com/handle/?hl=en)
        if v.startswith("http"):
            m = re.match(r"https?://(?:www\.)?instagram\.com/([a-zA-Z0-9._]+)", v)
            v = m.group(1) if m else v
        return v.lstrip("@").strip() or None


class BusinessContext(BaseModel):
    """Serialisable snapshot of AuditRequest passed to every worker."""
    business_name: str
    city: Optional[str] = None
    business_description: Optional[str] = None
    website_url: Optional[str] = None       # plain string for JSON serialisation
    instagram_handle: Optional[str] = None
    monthly_ad_spend: Optional[float] = None


class AuditStatusResponse(BaseModel):
    id: UUID
    business_name: str
    status: Literal["pending", "running", "running_report", "completed", "failed"]
    created_at: datetime
    completed_at: Optional[datetime] = None
    error: Optional[str] = None


# ── Per-worker result shapes ───────────────────────────────────────────────────

class LighthouseResult(BaseModel):
    performance_score: Optional[int] = None
    accessibility_score: Optional[int] = None
    seo_score: Optional[int] = None
    best_practices_score: Optional[int] = None
    first_contentful_paint_s: Optional[float] = None
    largest_contentful_paint_s: Optional[float] = None
    total_blocking_time_ms: Optional[float] = None
    cumulative_layout_shift: Optional[float] = None
    is_mobile_friendly: Optional[bool] = None
    error: Optional[str] = None


class GooglePlacesResult(BaseModel):
    gmb_exists: bool = False                 # True only when exact business+city search hit
    place_id: Optional[str] = None
    name: Optional[str] = None
    rating: Optional[float] = None
    review_count: Optional[int] = None
    address: Optional[str] = None
    phone: Optional[str] = None
    website: Optional[str] = None
    categories: list[str] = []
    photos_count: Optional[int] = None
    is_claimed: Optional[bool] = None
    gmb_completeness_score: Optional[int] = None
    competitors: list[dict] = []             # top 3 from fallback category+city search
    error: Optional[str] = None


class InstagramResult(BaseModel):
    username: Optional[str] = None
    followers: Optional[int] = None
    following: Optional[int] = None
    posts_count: Optional[int] = None
    is_verified: Optional[bool] = None
    is_business_account: Optional[bool] = None
    business_category: Optional[str] = None
    bio: Optional[str] = None
    has_bio_link: Optional[bool] = None       # external URL set in bio
    has_contact_button: Optional[bool] = None  # business account with contact method
    last_post_date: Optional[datetime] = None
    posts_analysed: Optional[int] = None       # how many posts were fetched
    avg_likes: Optional[float] = None
    avg_comments: Optional[float] = None
    engagement_rate: Optional[float] = None
    post_frequency_per_week: Optional[float] = None
    error: Optional[str] = None


class CrawlerResult(BaseModel):
    has_ssl: Optional[bool] = None
    has_contact_page: Optional[bool] = None
    has_about_page: Optional[bool] = None
    has_whatsapp_link: Optional[bool] = None
    has_social_links: Optional[bool] = None
    meta_title: Optional[str] = None
    meta_description: Optional[str] = None
    h1_tags: list[str] = []
    broken_links_count: Optional[int] = None
    load_time_s: Optional[float] = None
    has_structured_data: Optional[bool] = None
    phone_numbers: list[str] = []
    emails: list[str] = []
    language: Optional[str] = None
    error: Optional[str] = None


class MergedAuditData(BaseModel):
    audit_id: str
    request: AuditRequest
    lighthouse: LighthouseResult = LighthouseResult()
    google_places: GooglePlacesResult = GooglePlacesResult()
    instagram: InstagramResult = InstagramResult()
    crawler: CrawlerResult = CrawlerResult()
