import json
from app.workers.google_places import fetch_google_places, _name_matches

tests = [
    ("Apna Sweets",   "Apna Namkeen",             False),
    ("Apna Sweets",   "Apna Sweets Bhopal",        True),
    ("Sharma Sweets", "Sharma Mithai Bhandar",     True),
    ("Apna Sweets",   "Apna Fast Food",             False),
    ("Raj Bakery",    "Raj Bakery And Restaurant",  True),
    ("Apna Sweets",   "APNA RESTOURENT AND SWEETS", True),
]

print("=== NAME MATCHER TESTS ===")
for q, r, expected in tests:
    result = _name_matches(q, r)
    status = "PASS" if result == expected else "FAIL"
    print(f"  [{status}] '{q}' vs '{r}' -> {result} (expected {expected})")

print()
print("=== LIVE SEARCH: Apna Sweets, Indore ===")
result = fetch_google_places("Apna Sweets", "Indore", "sweets shop")
print(json.dumps(result.model_dump(), indent=2, default=str))
