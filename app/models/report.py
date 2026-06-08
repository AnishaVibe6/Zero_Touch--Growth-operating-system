from datetime import datetime
from typing import Optional
from uuid import UUID

from pydantic import BaseModel, field_validator


class DimensionScore(BaseModel):
    score: int          # 0-100
    label: str          # Poor | Needs Work | Good | Excellent
    summary: str
    recommendations: list[str] = []
    competitor_hint: Optional[str] = None
    category_avg: Optional[int] = None      # typical benchmark for this category/city tier


class Dimensions(BaseModel):
    web_performance: DimensionScore
    local_seo: DimensionScore
    social_presence: DimensionScore
    website_quality: DimensionScore


class AdPreview(BaseModel):
    headline: str       # max ~30 chars
    description: str    # max ~90 chars
    display_url: str    # e.g. "apnasweets.com › order-sweets"


class GoogleAdsPreview(BaseModel):
    headline_1: str
    headline_2: str
    headline_3: Optional[str] = None
    description_1: str
    description_2: Optional[str] = None
    display_url: str


class FacebookAdsPreview(BaseModel):
    primary_text: str
    headline: str
    description: Optional[str] = None
    cta_button: str
    target_audience: Optional[str] = None


class InstagramPreview(BaseModel):
    content_type: str
    hook_line: str
    caption: str
    hashtags: list[str] = []


class CampaignPreview(BaseModel):
    channel: str
    monthly_budget_inr: int
    expected_leads: int
    cost_per_lead_inr: int
    estimated_reach: Optional[int] = None               # expected_leads × 20
    estimated_additional_revenue: Optional[int] = None  # expected_leads × avg_order_value
    current_monthly_revenue: Optional[int] = None       # benchmark monthly_customers × avg_order
    projected_monthly_revenue: Optional[int] = None     # current + estimated_additional_revenue
    ad_copies: list[AdPreview] = []
    keywords: list[str] = []
    quick_wins: list[str] = []
    we_will: list[str] = []                  # 3 specific "We will..." campaign actions
    roadmap_weeks: list[str] = []           # exactly 4 week milestones
    headline: Optional[str] = None          # brutal one-liner shown on score screen
    revenue_loss_reason: Optional[str] = None  # why the money is being lost
    google_ads: Optional[GoogleAdsPreview] = None
    facebook_ads: Optional[FacebookAdsPreview] = None
    instagram: Optional[InstagramPreview] = None

    @field_validator("ad_copies", mode="before")
    @classmethod
    def coerce_ad_copies(cls, v):
        """Accept both old plain-string format and new structured dict format."""
        result = []
        for item in v:
            if isinstance(item, str):
                result.append({"headline": item, "description": "", "display_url": ""})
            else:
                result.append(item)
        return result


class AuditReport(BaseModel):
    id: Optional[UUID] = None
    audit_id: UUID
    overall_score: int                      # 0-100 weighted average
    dimensions: Dimensions
    revenue_loss_low: Optional[float] = None    # monthly INR (lower bound)
    revenue_loss_high: Optional[float] = None   # monthly INR (upper bound)
    campaign_preview: CampaignPreview
    has_website: bool = True                # False when no website_url was provided
    created_at: datetime = datetime.utcnow()
