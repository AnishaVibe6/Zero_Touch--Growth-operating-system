import re
from urllib.parse import urlparse


def normalise_url(url: str) -> str:
    """Ensure URL has a scheme; default to https."""
    if not url.startswith(("http://", "https://")):
        url = "https://" + url
    return url.rstrip("/")


def normalise_handle(handle: str) -> str:
    return handle.lstrip("@").strip()


def score_label(score: int) -> str:
    if score >= 81:
        return "Excellent"
    if score >= 61:
        return "Good"
    if score >= 41:
        return "Needs Work"
    return "Poor"


def extract_domain(url: str) -> str:
    return urlparse(normalise_url(url)).netloc
