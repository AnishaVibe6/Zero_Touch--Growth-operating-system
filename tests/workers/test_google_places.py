from unittest.mock import MagicMock, patch

from app.workers.google_places import _gmb_completeness, run_google_places


def test_gmb_completeness_full():
    full = {
        "name": "Test", "rating": 4.5, "reviews": 100, "address": "Mumbai",
        "phone": "9876543210", "website": "https://test.com", "hours": {},
        "type": "Restaurant", "photos": ["p1"], "claimed": True,
    }
    assert _gmb_completeness(full) == 100


def test_gmb_completeness_partial():
    partial = {"name": "Test", "rating": 4.0}
    score = _gmb_completeness(partial)
    assert 0 < score < 100


def test_google_places_happy_path():
    mock_search = MagicMock()
    mock_search.get_dict.return_value = {
        "local_results": [{
            "place_id": "abc123",
            "title": "Sharma Electronics",
            "rating": 4.2,
            "reviews": 87,
            "address": "Lajpat Nagar, Delhi",
            "phone": "9810012345",
            "website": "https://sharmaelectronics.in",
            "type": "Electronics store",
        }]
    }

    with patch("app.workers.google_places.GoogleSearch", return_value=mock_search):
        result = run_google_places.run("audit-1", "Sharma Electronics", "Delhi")

    assert result["rating"] == 4.2
    assert result["review_count"] == 87
    assert result["error"] is None
