from unittest.mock import MagicMock, patch

from app.workers.instagram import run_instagram


def _make_mock_profile(followers=5000, posts=12):
    profile = MagicMock()
    profile.username = "testbusiness"
    profile.followers = followers
    profile.followees = 300
    profile.mediacount = 120
    profile.is_verified = False
    profile.biography = "Best shop in Mumbai"
    profile.external_url = "https://example.com"
    profile.business_email = ""

    mock_post = MagicMock()
    mock_post.likes = 150
    mock_post.comments = 10
    from datetime import datetime, timedelta
    mock_post.date_utc = datetime.utcnow()

    older_post = MagicMock()
    older_post.likes = 120
    older_post.comments = 8
    older_post.date_utc = datetime.utcnow() - timedelta(days=30)

    profile.get_posts.return_value = iter([mock_post] * posts)
    return profile


def test_instagram_happy_path():
    mock_profile = _make_mock_profile()

    with patch("app.workers.instagram._get_loader"), \
         patch("app.workers.instagram.instaloader.Profile.from_username", return_value=mock_profile):
        result = run_instagram.run("audit-1", "testbusiness")

    assert result["followers"] == 5000
    assert result["engagement_rate"] > 0
    assert result["error"] is None


def test_instagram_private_account_returns_error():
    with patch("app.workers.instagram._get_loader"), \
         patch("app.workers.instagram.instaloader.Profile.from_username",
               side_effect=Exception("private account")):
        result = run_instagram.run("audit-2", "privateacc")

    assert result["error"] is not None
