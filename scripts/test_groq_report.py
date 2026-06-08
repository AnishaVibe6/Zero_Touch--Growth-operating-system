import sys, os, json
from unittest.mock import MagicMock
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
_s = MagicMock()
sys.modules.setdefault("celery", _s)
sys.modules["app.workers.celery_app"] = MagicMock(celery_app=_s)

from app.models.audit import (
    AuditRequest, MergedAuditData,
    LighthouseResult, GooglePlacesResult, InstagramResult, CrawlerResult,
)
from app.services.claude_report import generate_report

merged = MergedAuditData(
    audit_id="00000000-0000-0000-0000-000000000001",
    request=AuditRequest(
        business_name="Sharma Sarees",
        city="Bhopal",
        category="retail",
        website_url="https://sharmasarees.com",
        instagram_handle="sharmasarees_bhopal",
        monthly_ad_spend=8000,
    ),
    lighthouse=LighthouseResult(
        performance_score=42, accessibility_score=61, seo_score=55,
        best_practices_score=67, first_contentful_paint_s=4.2,
        largest_contentful_paint_s=7.1, total_blocking_time_ms=890,
        cumulative_layout_shift=0.28, is_mobile_friendly=False,
    ),
    google_places=GooglePlacesResult(
        place_id="ChIJtest123", name="Sharma Sarees",
        rating=3.8, review_count=12, address="New Market, Bhopal MP 462003",
        phone="9876543210", website=None,
        categories=["Clothing store", "Saree Shop"],
        photos_count=2, is_claimed=False, gmb_completeness_score=40,
    ),
    instagram=InstagramResult(
        username="sharmasarees_bhopal", followers=430, following=210,
        posts_count=38, is_verified=False, is_business_account=False,
        bio="Traditional sarees from Bhopal", has_bio_link=False,
        has_contact_button=False, posts_analysed=10,
        avg_likes=18.4, avg_comments=1.2, engagement_rate=4.56,
        post_frequency_per_week=0.8,
    ),
    crawler=CrawlerResult(
        has_ssl=False, has_contact_page=False, has_about_page=False,
        has_whatsapp_link=False, has_social_links=False,
        meta_title="Sharma Sarees", meta_description=None,
        h1_tags=["Welcome"], broken_links_count=4,
        load_time_s=6.8, has_structured_data=False,
        phone_numbers=["9876543210"], emails=[], language="en",
    ),
)

print("Calling Groq llama-3.3-70b-versatile ...\n")
report = generate_report(merged)
print(json.dumps(report.model_dump(mode="json"), indent=2, default=str))
