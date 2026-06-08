from unittest.mock import patch

from app.workers.crawler import run_crawler

_SAMPLE_HTML = """<!DOCTYPE html>
<html lang="en">
<head>
  <title>Sharma Electronics | Best Shop in Delhi</title>
  <meta name="description" content="Top electronics store in Lajpat Nagar.">
  <script type="application/ld+json">{"@type": "LocalBusiness"}</script>
</head>
<body>
  <h1>Welcome to Sharma Electronics</h1>
  <a href="/contact">Contact Us</a>
  <a href="/about">About</a>
  <a href="https://wa.me/919810012345">WhatsApp</a>
  <a href="https://instagram.com/sharmaelec">Instagram</a>
  <p>Call: 9810012345 | Email: info@sharma.com</p>
</body>
</html>"""


def test_crawler_happy_path():
    with patch("app.workers.crawler._crawl", return_value=(_SAMPLE_HTML, 1.4, True)):
        result = run_crawler.run("audit-1", "https://sharma.com")

    assert result["has_ssl"] is True
    assert result["has_contact_page"] is True
    assert result["has_whatsapp_link"] is True
    assert result["has_social_links"] is True
    assert result["has_structured_data"] is True
    assert "9810012345" in result["phone_numbers"]
    assert result["error"] is None


def test_crawler_no_ssl():
    with patch("app.workers.crawler._crawl", return_value=(_SAMPLE_HTML, 2.1, False)):
        result = run_crawler.run("audit-2", "http://sharma.com")

    assert result["has_ssl"] is False
