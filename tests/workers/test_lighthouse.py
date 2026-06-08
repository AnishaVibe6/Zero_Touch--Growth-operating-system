from unittest.mock import MagicMock, patch

from app.workers.lighthouse import run_lighthouse


def test_lighthouse_happy_path():
    mock_response = MagicMock()
    mock_response.json.return_value = {
        "lighthouseResult": {
            "categories": {
                "performance": {"score": 0.72},
                "accessibility": {"score": 0.91},
                "seo": {"score": 0.88},
                "best-practices": {"score": 0.83},
            },
            "audits": {
                "first-contentful-paint": {"numericValue": 1800},
                "largest-contentful-paint": {"numericValue": 3200},
                "total-blocking-time": {"numericValue": 120},
                "cumulative-layout-shift": {"numericValue": 0.05},
            },
        }
    }
    mock_response.raise_for_status = MagicMock()

    with patch("app.workers.lighthouse.httpx.get", return_value=mock_response):
        result = run_lighthouse.run("audit-1", "https://example.com")

    assert result["performance_score"] == 72
    assert result["seo_score"] == 88
    assert result["error"] is None


def test_lighthouse_api_error_returns_error_field():
    with patch("app.workers.lighthouse.httpx.get", side_effect=Exception("timeout")):
        result = run_lighthouse.run("audit-2", "https://example.com")

    assert result["error"] is not None
