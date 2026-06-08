"""
Smoke-test for Lighthouse + Crawler workers.
Runs worker logic directly — no Celery or Redis needed.

Usage:
    python scripts/test_workers.py
    python scripts/test_workers.py https://your-client-site.com
"""
import json
import sys
import os
from unittest.mock import MagicMock

# Make `app` importable from the project root
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

# Stub Celery so workers can be imported without a running broker
_celery_stub = MagicMock()
sys.modules.setdefault("celery", _celery_stub)
sys.modules["app.workers.celery_app"] = MagicMock(celery_app=_celery_stub)

URL = sys.argv[1] if len(sys.argv) > 1 else "https://example.com"

CYAN  = "\033[96m"
GREEN = "\033[92m"
RED   = "\033[91m"
BOLD  = "\033[1m"
RESET = "\033[0m"


def banner(text: str) -> None:
    print(f"\n{CYAN}{'-' * 60}{RESET}")
    print(f"{BOLD}  {text}{RESET}")
    print(f"{CYAN}{'-' * 60}{RESET}")


def print_json(data: dict) -> None:
    print(json.dumps(data, indent=2, default=str))


def run_lighthouse(url: str) -> dict:
    banner(f"WORKER: Lighthouse  >  {url}")
    try:
        from app.workers.lighthouse import fetch_lighthouse
        result = fetch_lighthouse(url)
        data = result.model_dump()
        print_json(data)
        return data
    except Exception as exc:
        print(f"{RED}  FAILED: {exc}{RESET}")
        return {"error": str(exc)}


def run_google_places(business_name: str, location: str) -> dict:
    banner(f"WORKER: Google Places  >  {business_name}, {location}")
    try:
        from app.workers.google_places import fetch_google_places
        result = fetch_google_places(business_name, location)
        data = result.model_dump()
        print_json(data)
        return data
    except Exception as exc:
        print(f"{RED}  FAILED: {exc}{RESET}")
        return {"error": str(exc)}


def run_crawler(url: str) -> dict:
    banner(f"WORKER: Crawler     >  {url}")
    try:
        from app.workers.crawler import fetch_crawler
        result = fetch_crawler(url)
        data = result.model_dump()
        print_json(data)
        return data
    except Exception as exc:
        print(f"{RED}  FAILED: {exc}{RESET}")
        return {"error": str(exc)}


def summary(lh: dict, cr: dict) -> None:
    banner("SUMMARY")
    ok = lambda v: f"{GREEN}[Y] {v}{RESET}" if v else f"{RED}[N] {v}{RESET}"

    perf  = lh.get("performance_score")
    seo   = lh.get("seo_score")
    a11y  = lh.get("accessibility_score")
    bp    = lh.get("best_practices_score")
    fcp   = lh.get("first_contentful_paint_s")
    lcp   = lh.get("largest_contentful_paint_s")
    tbt   = lh.get("total_blocking_time_ms")
    cls_  = lh.get("cumulative_layout_shift")

    print(f"  Lighthouse scores")
    print(f"    Performance    : {perf}")
    print(f"    SEO            : {seo}")
    print(f"    Accessibility  : {a11y}")
    print(f"    Best Practices : {bp}")
    print(f"    FCP            : {fcp}s   LCP: {lcp}s   TBT: {tbt}ms   CLS: {cls_}")

    print(f"\n  Crawler signals")
    print(f"    Load time      : {cr.get('load_time_s')}s")
    print(f"    SSL            : {ok(cr.get('has_ssl'))}")
    print(f"    WhatsApp link  : {ok(cr.get('has_whatsapp_link'))}")
    print(f"    Structured data: {ok(cr.get('has_structured_data'))}")
    print(f"    Contact page   : {ok(cr.get('has_contact_page'))}")
    print(f"    Title          : {cr.get('meta_title')}")
    print(f"    Language       : {cr.get('language')}")
    print(f"    Phones found   : {cr.get('phone_numbers')}")
    print(f"    Emails found   : {cr.get('emails')}")

    lh_err = lh.get("error")
    cr_err = cr.get("error")
    if lh_err or cr_err:
        print(f"\n  {RED}Errors:{RESET}")
        if lh_err: print(f"    Lighthouse : {lh_err}")
        if cr_err:  print(f"    Crawler    : {cr_err}")
    else:
        print(f"\n  {GREEN}Both workers completed successfully.{RESET}")
    print()


if __name__ == "__main__":
    print(f"\n{BOLD}ZTGOS Worker Test{RESET}  |  target: {CYAN}{URL}{RESET}")

    lh_result = run_lighthouse(URL)
    cr_result = run_crawler(URL)
    summary(lh_result, cr_result)
