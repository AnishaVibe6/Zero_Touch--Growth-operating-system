# Project Context Log

---

## 📌 MASTER STATUS (as of 2026-06-02, updated Session 23+)

### What ZTGOS is
SaaS digital growth audit engine for Indian MSMEs. User enters business name + city + free-text description + optional website/Instagram/ad-spend → 4 parallel workers gather data → Groq LLM produces a structured growth audit report + hyper-local campaign plan.

### Pipeline flow (end to end)
1. `POST /audit` → `orchestrator.launch_audit()` → Celery chord fires 4 workers in parallel
2. Workers: `lighthouse`, `google_places` (SerpAPI), `instagram` (mobile API), `crawler` (Playwright)
3. Chord callback → `workers.report` → `claude_report.generate_report(merged)`
4. Inside `generate_report`: `detect_profile()` (1 Groq call) → `build_campaign_brief()` (pure Python) → `build_narrative()` (pure Python) → `_build_system_prompt()` (3 layers + campaign brief) → `_call_llm()` (Groq or Ollama) → `calculate_revenue_loss()` (formula) → `AuditReport`
5. Saved to Supabase; frontend polls `GET /audit/{id}` then `GET /audit/{id}/report`

### Files created/owned (the "intelligence" layer)
| File | Purpose | Status |
|---|---|---|
| `ai/category_benchmarks.py` | 30 Indian MSME benchmarks + `get_closest_benchmark()` fuzzy match | ✅ done |
| `pipeline/profile_detector.py` | `detect_profile()` → ProfileContext (Groq extract + profile_type + biggest_gap + benchmark) | ✅ done |
| `ai/narrative_builder.py` | `build_narrative()` → plain-English context paragraph (no raw JSON to Groq) | ✅ done |
| `ai/campaign_builder.py` | `build_campaign_brief()` → CampaignBrief with 7 rules + CITY_CONTEXT (15 cities) | ✅ done, wired |
| `app/services/claude_report.py` | 3-layer prompt, Groq+Ollama router, schema-violation recovery, campaign brief injection | ✅ done |
| `ai/campaign_package_builder.py` | n8n webhook → Groq fallback for campaign package generation | ✅ done |
| `scripts/test_prompts.py` | 3-business prompt test (Apna/Riya/Sharma) | ✅ done |
| `scripts/test_campaigns.py` | 4-business campaign differentiation test | ⚠️ Test 1 verified, 2–4 blocked by quota |

### Campaign builder status (7 rules — all enforced in `campaign_builder.py`)
- C1 channel locked to profile+worst-dim · C2 objective = worst dim · C3 budget tiers (zero/low/medium/high) · C4 Week-1 business-type-specific (19 templates) · C5 ad copies name+city only (NO invented locality names like Sarafa Bazaar — removed in Session 20) · C6 tone · C7 peak season if ≤60 days
- **Verified (Apna Sweets Indore, Session 20):** budget=₹5,000 ✅, leads=25 ✅, cpl=₹200 ✅, we_will 3 items with measurable outcomes ✅, ROI bars ✅

### CampaignPreview model fields (all computed in normalizer, `claude_report.py` Step 7)
| Field | Source |
|---|---|
| `monthly_budget_inr` | Groq → request `monthly_ad_spend` → 5000 |
| `expected_leads` | Groq → `monthly_customers_estimate × 0.15` |
| `cost_per_lead_inr` | Groq → `budget ÷ leads` |
| `estimated_reach` | `leads × 20` |
| `estimated_additional_revenue` | `leads × avg_order_value` |
| `current_monthly_revenue` | `monthly_customers_estimate × avg_order_value` (benchmark) |
| `projected_monthly_revenue` | `current + estimated_additional_revenue` |
| `we_will` | Groq top-level (4 strict rules: starts "We will", names business, measurable outcome, worst-dim order) |

### Groq schema rules (learned from repeated failures)
- **NEVER add `maxItems`/`minItems` to any array field** — Groq validates server-side and throws 400. Clamp in Python instead via `_fix_schema_violations()`.
- **Model always puts "content" fields at top level** — `keywords`, `quick_wins`, `roadmap_weeks`, `headline`, `revenue_loss_reason`, `we_will` must all be top-level schema fields, NOT nested inside `campaign_preview`.
- **`failed_generation` now wrapped in `<function=name>...</function>`** — `_strip_function_wrapper()` handles this; `_extract_failed_generation()` tries `exc.body` → `exc.response.json()` → string regex.
- **Celery does NOT auto-reload** — must be restarted manually after any change to `claude_report.py`.

### Environment variables (current `.env`)
| Var | Value / status |
|---|---|
| APP_ENV | development |
| APP_SECRET_KEY | change-me-in-production |
| REDIS_URL | Upstash TLS `rediss://…@free-leopard-72358.upstash.io:6379` ✓ |
| GROQ_API_KEY | `gsk_Sm4F…VITt` ✓ (org `org_01kqv…`, 100K tokens/day free tier) |
| GROQ_MODEL | `llama-3.3-70b-versatile` |
| USE_OLLAMA | `false` (set true to use local llama3.2:3b fallback) |
| OLLAMA_URL | `http://localhost:11434` |
| OLLAMA_MODEL | `llama3.2:3b` |
| SERPAPI_KEY | `f817…911e6` ✓ |
| INSTAGRAM_USERNAME / PASSWORD | empty (public profiles, not needed) |
| SUPABASE_URL | `https://ajhqufymhulqdnmmssaj.supabase.co` ✓ |
| SUPABASE_SERVICE_KEY | set ✓ |
| N8N_WEBHOOK_URL | not set (optional — leave blank to use Groq fallback) |

### Known constraints / gotchas
- **Groq free tier: 100K tokens/day, rolling 24h window** (NOT midnight reset). Each full audit ≈ 6,200 tokens (profile extract ~900 + report ~5,300) → ~16 audits/day. This is the #1 thing that blocks testing.
- Servers do NOT persist between sessions — start manually each time (see commands below).
- All keys generated under the same Groq account share one org quota — a "new key" from the same account does NOT reset it. Only a brand-new account (different email) gets a fresh pool.
- Ollama llama3.2:3b works for simple profiles but is unreliable on the complex nested schema (Test 3 produced malformed ad_copies). CPU-only, ~7 min/response. Keep Groq as primary.

### Start servers (run both, each session)
```
uvicorn app.main:app --host 0.0.0.0 --port 8000 --reload
celery -A app.workers.celery_app worker --loglevel=info --pool=solo
```

### ▶️ NEXT SESSIONS
1. **Session 21 — Supabase migration.** ✅ DONE: `ALTER TABLE audits ADD COLUMN IF NOT EXISTS business_description TEXT;` run; try/except fallback removed.
2. **Session 22 — Campaign screen.** ✅ DONE: Full redesign with animated stat cards, ROI comparison bars, action cards with icons, `we_will` Groq field, real benchmark revenue numbers.
3. **Session 23 — PDF / shareable report link + n8n integration.** ✅ DONE: Copy Report Link button, Download PDF button, shared URL boot (`?audit=UUID`), `ai/campaign_package_builder.py` with n8n webhook + Groq fallback.
4. **Session 24 — Campaign differentiation test.** Re-run `python -m scripts.test_campaigns` on fresh quota. Confirm all 4 businesses produce different channels, budget tiers, Week-1 templates.
5. **Session 25 — Wire campaign_package_builder into pipeline.** Call `generate_campaign_package()` from `workers/report.py` after `generate_report()` completes; store result in Supabase `reports` table or a new `campaign_packages` table; surface on frontend.

---

## 2026-06-02 — Session 23 (part 2)

### Done

**n8n integration — `ai/campaign_package_builder.py` (new file)**
- `generate_campaign_package(merged, report)` — public entry point called after `generate_report()` completes
- Builds a full JSON payload: business info, all 4 dimension scores, revenue figures, full `CampaignPreview`, raw worker data (google_places, instagram, crawler)
- **Primary path**: `httpx.post(N8N_WEBHOOK_URL, json=payload, timeout=30)` — returns whatever JSON n8n sends back unchanged
- **Fallback triggers on**: `TimeoutException` (30s), `HTTPStatusError` (4xx/5xx), any other exception, or `N8N_WEBHOOK_URL` not set
- **Fallback path**: direct Groq call with `response_format: json_object` — generates `summary`, `ad_variations` (3 extra ads), `whatsapp_templates` (2 messages), `week1_checklist` (5 tasks)
- All paths logged via `structlog`: `n8n.start`, `n8n.done`, `n8n.timeout`, `n8n.http_error`, `n8n.failed`, `n8n.skipped`, `groq_fallback.triggered`, `groq_fallback.done`, `groq_fallback.failed`
- **Not yet wired** into the Celery pipeline — call it from `workers/report.py` in Session 25

**`app/config.py`**
- Added `n8n_webhook_url: str | None = None` — reads from `N8N_WEBHOOK_URL` env var

**`.env.example`**
- Added `N8N_WEBHOOK_URL=http://localhost:5678/webhook/campaign-generate` with comment

### Pending
- Wire `generate_campaign_package()` into `workers/report.py` (Session 25)
- Store campaign package in Supabase
- Surface package content on frontend

---

## 2026-05-29 — Session 23 (part 1)

### Done

**Shareable report link (`frontend/index.html`)**
- After audit starts, URL auto-updates to `/?audit=UUID` via `history.pushState`
- On page load, `?audit=UUID` param detected → form hidden, report fetched directly (skips the form entirely)
- `resetAudit()` clears the URL back to `/` via `history.replaceState`
- `_auditId` global variable tracks current audit across form submit and shared-link boot

**Copy Report Link button**
- Appears on Screen 1 between Key Opportunities and "See Campaign" button
- Copies `origin/?audit=UUID` to clipboard
- Button turns green and shows "Copied!" for 2.5 seconds, then resets
- Purple/accent styling to stand out from the green campaign button

**Download PDF button**
- Sits next to Copy Link in a flex row
- Uses `html2pdf.js` (CDN, no backend changes)
- Renders `#r-screen1` (audit report page) to A4 dark-theme PDF
- Filename: `ZTGOS-Audit-{BusinessName}.pdf`
- Button shows "Generating…" while working, then resets

### Pending
- Test PDF output quality across different audit types
- Consider adding a print-friendly light-theme stylesheet option

---

## 2026-05-29 — Session 20

### Done

**Supabase migration applied (`app/services/supabase_client.py`)**
- `business_description` column confirmed present in Supabase
- Removed try/except fallback from `create_audit()` — direct insert now

**Instagram handle sanitization (`app/models/audit.py`, `app/workers/instagram.py`)**
- Root cause: user pasting full URL `https://www.instagram.com/apna_sweets/?hl=en` as handle
- `AuditRequest.clean_instagram_handle` validator strips URL → bare username at model level (stored clean in Supabase)
- `fetch_instagram()` also strips URLs as secondary safety net

**Campaign screen — removed 3 sections (`frontend/index.html`)**
- Removed: 30-Day Action Plan stepper, Target Keywords (dead code `KW_C`), Estimated Monthly Reach progress bar
- Removed associated CSS (`.stepper`, `.step-dot`, `.step-week`, `.step-text`, `.reach-wrap`, `.reach-track`, `.reach-fill`)

**Campaign fields fix (`app/services/claude_report.py`)**
- Added `groq.campaign_raw` log line to print Groq's raw campaign values on every audit
- Normalizer (Step 7) now applies fallbacks: budget → `monthly_ad_spend` → 5000; leads → `monthly_cust × 0.15`; cpl → `budget ÷ leads`
- Added `estimated_reach = leads × 20`, `estimated_additional_revenue = leads × avg_order`
- Added `current_monthly_revenue = monthly_cust × avg_order`, `projected_monthly_revenue = current + additional`
- All new fields added to `CampaignPreview` model in `app/models/report.py`

**Groq 400 schema error fix (`app/services/claude_report.py`)**
- Root cause: `maxItems`/`minItems` in schema → Groq validates server-side and throws 400 before returning
- Fix: removed ALL `maxItems`/`minItems` from `_REPORT_TOOL` (`keywords`, `quick_wins`, `roadmap_weeks`, `ad_copies`)
- Added `_strip_function_wrapper()` to handle Groq's new `<function=name>{...}</function>` format
- Added `_extract_failed_generation()` with 3 fallback paths: `exc.body` → `exc.response.json()` → `str(exc)` regex
- **Key lesson**: Celery does NOT auto-reload — must restart after any change to `claude_report.py`

**`we_will` Groq-generated field**
- Added to `app/models/report.py` (`CampaignPreview.we_will: list[str]`)
- Schema at top level (NOT inside `campaign_preview`) — model always places content fields at top level
- 4 strict rules in schema description: starts "We will", names business, measurable outcome stat after " — ", ordered by worst→second worst→channel
- Forbidden phrase list enforced
- Normalizer pads from `quick_wins` if Groq returns fewer than 3 items
- Action cards in frontend detect icon by content: Google/Maps → magnifying glass (blue), WhatsApp → WhatsApp icon (green), Instagram/social → Instagram icon (pink), ads/campaign → star (orange)

**C5 locality fix (`ai/campaign_builder.py`)**
- Removed `ad_hook`, `market`, `local_terms` injection from Rule C5
- Ad copies now use ONLY business name + city — no invented locality names (Sarafa Bazaar etc.) unless user stated them

**Campaign screen full redesign (`frontend/index.html`)**
- Three animated stat cards: Reach (counts up, accent border), Leads (counts up, green border), Additional Revenue ₹ (counts up in INR, green)
- ROI comparison bars: "Current monthly revenue" (muted red, shorter) vs "Projected with campaign" (green, full width) — real benchmark numbers
- Single ad preview
- Three action cards: split at " — " to show action bold + metric muted; icon auto-detected from text
- Two CTA buttons inside campaign card: "Start This Campaign — ₹X/mo" (green), "Explore Other Options" (gray)

### Pending
- Test with home-based Instagram-first business to verify Meta Ads channel
- Test with zero ad_spend to verify quick_wins_only mode
- PDF / shareable report link
- Fix narrative `_opening()` grammar for descriptions starting with "We"/"I"

### Server startup reminder
```
uvicorn app.main:app --host 0.0.0.0 --port 8000 --reload
celery -A app.workers.celery_app worker --loglevel=info --pool=solo
```
**Important**: Celery does NOT auto-reload. Restart it manually after any backend code change.

---

## 2026-05-29 — Session 19

### Done

**Campaign budget fix (`app/services/claude_report.py`)**
- `_profile_constraints()` now takes `monthly_ad_spend: float | None` param
- `budget = int(monthly_ad_spend) if monthly_ad_spend else 5000` computed inside constraints
- Injected as hard rule: `"CAMPAIGN BUDGET: monthly_budget_inr MUST be exactly ₹{budget:,}. This is the owner's actual monthly ad spend — do NOT increase or change it."`
- Threaded through `_build_system_prompt(monthly_ad_spend=...)` and `generate_report()` via `merged.request.monthly_ad_spend`

**Revenue loss reason fix (`app/services/claude_report.py`)**
- Removed the pre-score ₹ estimate from the user prompt entirely (previously passed score=50 range which Groq anchored on even after real score changed the formula result)
- User prompt now says: `"Do NOT include a specific ₹ amount in revenue_loss_reason — the exact figure is calculated separately and shown to the owner."`
- Groq now explains WHY (the gap + business impact) without citing wrong numbers; formula-calculated range displayed separately on frontend

**Supabase `business_description` column workaround (`app/services/supabase_client.py`)**
- `create_audit()` now writes to both `category` (legacy) and `business_description` columns
- try/except fallback: if `business_description` column doesn't exist, retries insert with only `category` column
- Pending migration: `ALTER TABLE audits ADD COLUMN IF NOT EXISTS business_description TEXT;` in Supabase SQL Editor

**Ollama local fallback (`app/services/claude_report.py`, `app/config.py`, `.env`)**
- `USE_OLLAMA=false` (default), `OLLAMA_URL=http://localhost:11434`, `OLLAMA_MODEL=llama3.2:3b`
- `_call_ollama()` uses `/api/generate` with `format="json"` + `_OLLAMA_SCHEMA_PROMPT` template
- `_call_groq()` and `_call_llm()` router added; `generate_report()` uses `_call_llm()`
- llama3.2:3b installed at `C:\Users\HP\AppData\Local\Programs\Ollama\ollama.exe` (~2GB)
- Ollama tests: Test 1 ✅, Test 2 ✅, Test 3 ❌ (malformed ad_copies, schema compliance issues with 3b model)

**`scripts/test_prompts.py` — 3-test mock-data suite**
- Tests Apna Sweets (sweet shop + website), Riya Collections (home-based Instagram), Sharma Tiffin (home-based, no web)
- Uses `_call_llm()` so it respects `USE_OLLAMA` setting
- Verifies: business name in findings, city in competitor hints, business_model detected, campaign channel matches profile type

**Real audit verified (audit_id: fc1f9fce, Apna Sweets Indore)**
- overall=75 | local_seo=90 (Excellent) | web_perf=70 (Good) | website_quality=70 (Good) | social=45
- Rule 4 ✅: all 70+ dimensions start with "Strong point:"
- Channel ✅: Google Ads (local search) correct for traditional+shop_based
- Groq quota: rolling 24-hour window (not fixed midnight reset). Each audit uses ~6,200 tokens (profile extraction ~887 + report ~5,400). 100K/day free limit ≈ 16 audits/day.

**`ai/campaign_builder.py` created**
- `build_campaign_brief(profile, dimension_scores, business_description, city, monthly_ad_spend) -> CampaignBrief`
- Pure Python, no LLM call — runs BEFORE Groq to pre-compute campaign strategy deterministically.
- **`CITY_CONTEXT` dict** — 15 cities: Indore, Mumbai, Delhi, Bangalore, Hyderabad, Pune, Jaipur, Bhopal, Lucknow, Surat, Ahmedabad, Chennai, Kolkata, Kochi, Chandigarh. Each has `markets`, `landmarks`, `local_terms`, `peak_times`, `language_hint`.
- **`CampaignBrief` dataclass fields**:
  - `primary_channel` — derived from `profile_type` + worst dimension (instagram_first→Meta Ads, shop_based+local_seo worst→Google Maps, home_based→WhatsApp+Meta, etc.)
  - `campaign_objective` — maps worst dimension to goal string (e.g. local_seo worst → "get discovered on Google Maps")
  - `budget_tier` — zero (0), low (<5k), medium (<20k), high (≥20k)
  - `tone` — keyword-matched from business_description: formal (B2B/wholesale), aspirational (fashion/jewellery/salon), motivational (gym/fitness), trustworthy (clinic/doctor), friendly (food/sweet/tiffin — default)
  - `urgency_trigger` — built from benchmark `peak_season`: "Peak season coming: Diwali, Holi. Campaigns started before peak see 2–3× returns."
  - `local_hooks` — full city dict from `CITY_CONTEXT` for the business city
  - `target_audience` — combines `business_model` prefix + `target_customer` from ProfileContext
  - `quick_wins_only` — True when budget_tier == "zero"
- **`.as_prompt_block()`** — formats brief as a compact plain-English block for Groq injection, including local market names, language tip, and budget note.
- **Not yet wired** — needs to be called in `generate_report()` after `detect_profile()` and injected into the Groq system prompt via `_profile_constraints()`.

**Groq 400 error fix — schema violations (`app/services/claude_report.py`)**
- `_fix_schema_violations(d)` — clamps arrays to maxItems: keywords[:8], quick_wins[:3], roadmap_weeks[:4], ad_copies[:3]
- `_call_groq()` now wraps the Groq call in try/except `BadRequestError`; on 400, extracts `failed_generation` JSON from the error body, runs `_fix_schema_violations()`, and returns the corrected dict instead of crashing
- Verified: audit that previously failed with "9 keywords found, max 8" now completes successfully

**New report UI format (`frontend/index.html`)**
- Screen 1 replaced with structured audit report format:
  1. Audit header (business name, overall score, grade)
  2. Revenue loss card (animated counter, reason, "✓ This is fixable")
  3. SEO Score (local_seo) — score badge + label + 3 reasons
  4. Website Performance Score (web_performance) — same
  5. Social Media Presence Score (social_presence) — same
  6. Competitor Comparison — 3 entries from dimension competitor_hints
  7. Areas Where Competitors Are Performing Better — bullet list
  8. Key Improvement Opportunities — from quick_wins + top recommendations
  9. "See Your Growth Campaign →" button
- Screen 2 (campaign plan, ad copies, roadmap, CTAs) unchanged
- New CSS classes: `.audit-header`, `.audit-section`, `.audit-sec-num`, `.audit-score-badge`, `.audit-score-label`, `.reasons-list`, `.comp-grid`, `.comp-item`, `.bullet-list`

**`ai/campaign_builder.py` — full rewrite with 7 enforced rules**
- `CITY_CONTEXT` updated with `ad_hook` field per city (e.g. Indore: "Sarafa Bazaar favourite since")
- Added `_peak_within_60_days(text)` — parses month abbreviations from peak_season string, checks if nearest month is ≤60 days away
- `CampaignBrief` dataclass gains 3 new fields: `business_description`, `business_name`, `city`, `profile`
- `as_prompt_block()` completely rewritten with 7 named rules:
  - C1 — Channel locked: `campaign_preview.channel MUST be "{channel}"` + exclusion warning (no Instagram for hardware store, no Google for instagram_first)
  - C2 — Objective: worst dimension drives entire campaign focus
  - C3 — Budget tiers: zero=free actions only (GMB/WhatsApp/Instagram), low=one channel 3-5 keywords, medium=two channels split, high=full funnel A/B test
  - C4 — Roadmap Week 1: 19 business-type-specific templates (tiffin, sweet, salon, bakery, etc.) — `"Upload 10 photos of fresh mithai varieties with prices to Google Maps and Instagram"` for sweet shops
  - C5 — Ad copies: business name in every headline, city in every description, local hook (e.g. "Sarafa Bazaar favourite since 1995"), forbidden phrases list ("Get 10% off", "Best quality guaranteed", etc.)
  - C6 — Tone: friendly/aspirational/formal/motivational/trustworthy with specific guidance
  - C7 — Peak season: if within 60 days → ALERT, must appear in hook + ad copy + Week 2; else → mention in Week 4 prep
- `build_campaign_brief()` now accepts `business_name` param and passes all new fields

**`app/services/claude_report.py`**
- `build_campaign_brief()` call updated to pass `business_name=business_name`
- `_REPORT_TOOL` schema descriptions updated to reference C1/C4 rules

**Verified (audit 00254416, Apna Sweets Indore)**
- Week 1: "Upload 10 photos of fresh mithai varieties with prices to Google Maps and Instagram" ✅ specific to sweet shop
- Ad copy: "[Apna Sweets - Sarafa Bazaar] Sarafa Bazaar favourite since 1995 · Try our namkeen · Visit us" ✅ business name + city + local hook
- Week 4 mentions Diwali/Holi/Raksha Bandhan peak season prep ✅
- Budget: ₹5,000 ✅, Channel: Google Ads (local search) ✅

### Pending
- Run Supabase migration: `ALTER TABLE audits ADD COLUMN IF NOT EXISTS business_description TEXT;`
- Test with a home-based Instagram-first business to verify Meta Ads channel + no "open a shop" recommendations
- Test with zero ad_spend to verify quick_wins_only mode (no paid campaign in output)
- Fix narrative `_opening()` grammar for descriptions starting with "We"/"I" (currently: "Apna Sweets is a physical storefront that We run a sweet shop...")
- Test with a home-based Instagram-first business to verify Meta Ads channel enforcement

### Server startup reminder
```
uvicorn app.main:app --host 0.0.0.0 --port 8000 --reload
celery -A app.workers.celery_app worker --loglevel=info --pool=solo
```

---

## 2026-05-28 — Session 18

### Done

**`category` field replaced by `business_description` (free text) across the full stack**

The category dropdown on the frontend form has been replaced with a free-text input where users describe their business in their own words. This affects every layer:

- **`frontend/index.html`**: `<select id="category">` → `<input id="business_description" type="text" maxlength="100" placeholder="e.g. sells sweets and namkeen">`. JS payload now sends `business_description` instead of `category`.
- **`app/models/audit.py`**: `AuditRequest.category` → `business_description: Optional[str]`. `BusinessContext.category` → `business_description`.
- **`app/services/supabase_client.py`**: `create_audit()` now writes `business_description` column (user confirmed column already exists in Supabase).
- **`app/services/orchestrator.py`**: `BusinessContext` and `run_google_places.s()` both pass `business_description`.
- **`app/workers/google_places.py`**: `fetch_google_places()` and `run_google_places()` param renamed to `business_description`. Fallback search query uses first 3 words of description (prevents overlong search strings from free-text input).
- **`app/services/revenue_calc.py`**: `calculate_revenue_loss()` param renamed to `business_description`. `_category_params()` already does substring keyword matching so it works transparently with free-text (e.g. "sells sweets and namkeen" matches "sweet" benchmark).
- **`app/services/claude_report.py`**: All `req.category` → `req.business_description`. `_build_system_prompt()` uses full description as business type context. Prompt header now shows description inline: `"Apna Sweets, Indore — sells sweets and namkeen"`.

**Rule going forward**: `business_description` is the primary source of business context in all Groq prompts. Never reintroduce a fixed category enum. The free-text description gives Groq richer context than a one-word category label.

**`ai/category_benchmarks.py` created**
- 30 Indian MSME benchmark entries (Tier 2 city numbers): restaurant, sweet shop, salon, clinic, gym, retail clothing, pharmacy, bakery, jewellery, electronics, real estate, coaching, hotel, travel agency, automobile workshop, furniture, grocery, catering, photographer, dental clinic, yoga studio, hardware store, event management, courier service, interior design, packers and movers, mobile repair, printing, driving school, pest control.
- Each entry has: `avg_gmb_reviews`, `avg_instagram_followers`, `avg_website_load_time` (seconds, 4G mobile), `peak_season`, `avg_order_value` (INR), `monthly_customers_estimate`, `top_keywords` (with `{city}` placeholder), `primary_channel`.
- `get_closest_benchmark(extracted_category)` — two-pass matching: (1) substring check (catches "sells sweets" → "sweet shop"), (2) `difflib.SequenceMatcher` ratio; falls back to `_GENERIC_BENCHMARK` if best score < 0.60.
- Returns `(matched_key, benchmark_dict)` tuple.
- Not yet wired into the report pipeline — available for Groq prompt enrichment and competitor hint generation.

**`pipeline/profile_detector.py` created**
- `ExtractedContext` model: `category`, `subcategory`, `business_model` (home_based/shop_based/online_only/hybrid), `product_or_service` (product/service/both), `target_customer`, `is_instagram_sellable`.
- `ProfileContext` model: combines `ExtractedContext` + `profile_type` + `biggest_gap` + `biggest_gap_reason` + `benchmark_key` + `benchmark` dict.
- **Step 1 — Groq extraction**: one focused call (`max_tokens=256`, `temperature=0`) with `submit_business_profile` function calling tool. If description is empty or Groq unavailable, falls back to `_fallback_context()` (shop_based, both, walk-in customers).
- **Step 2 — Profile type detection** (`_detect_profile_type`): `instagram_first` if ig_followers>1000 and no website; `hybrid` if ig_followers>500 and has website; else `traditional`.
- **Step 3 — Benchmark lookup**: calls `get_closest_benchmark(extracted.category)` from `ai/category_benchmarks.py`.
- **Step 4 — Biggest gap** (`_detect_biggest_gap`): 11-rule priority chain on worker data:
  1. no_gmb_listing → 2. no_website → 3. unclaimed_gmb → 4. low_reviews (<20) → 5. poor_rating (<3.5★) → 6. slow_website (>4s) → 7. no_whatsapp → 8. no_ssl → 9. low_social (<100 followers) → 10. low_engagement (<1%) → 11. few_gmb_photos (<5) → fallback: missing_meta_description.
  Each gap has a human-readable reason with a real impact stat.
- `detect_profile(merged: MergedAuditData) -> ProfileContext` — public entry point, safe to call even on empty description or Groq outage.
- **Not yet wired into the pipeline** — next step is to call `detect_profile()` in the report worker and pass `ProfileContext` into the Groq report prompt.

**`ai/narrative_builder.py` created**
- Pure Python, no Groq call — deterministic string assembly, fast.
- Public entry point: `build_narrative(merged: MergedAuditData, profile: ProfileContext) -> str`
- Returns a 180–280 word multi-paragraph narrative injected into the Groq prompt before raw JSON.
- **7 sections in order**:
  1. `_opening()` — name + city + description + business model + target customer + ad spend
  2. `_digital_footprint()` — GMB status (claimed/unclaimed, rating, review count, photos), website (load time, SSL, WhatsApp link), Instagram (followers, engagement, post frequency) — all real worker numbers
  3. `_competitive_position()` — user vs top SerpAPI competitor vs benchmark avg (reviews, load time, Instagram followers). Only surfaces comparisons where competitor/benchmark is BETTER — consistent with Rule 2.
  4. `_business_model_insight()` — model-specific channel priority (home_based→WhatsApp/Instagram, shop_based→Google Maps, online_only→website/Search, hybrid→both) + profile type framing (instagram_first/traditional/hybrid)
  5. `_instagram_sellability_note()` — if `is_instagram_sellable=True` → recommends Meta Ads/Reels; else → recommends Google Ads "near me" targeting
  6. `_peak_season_note()` — benchmark peak season with "2–3× conversion before peak" note (omitted if benchmark has no peak data)
  7. `_biggest_gap_closing()` — final urgent line: "The single most critical gap right now: {biggest_gap_reason}. Fix this first."
- Language varies by `business_model`: home-based gets WhatsApp-first framing; shop-based gets Google Maps-first; online-only gets website-as-storefront framing.
- Not yet wired — needs to be called in `app/services/claude_report.py` after `_build_system_prompt()`.

**`app/services/claude_report.py` — full 3-layer prompt rewrite**

The Groq prompt is now three distinct layers baked into `_build_system_prompt()`:

- **Layer 1 — Dynamic persona** (`_build_persona`): 10-entry `_PERSONA_MAP` keyed by `(profile_type, business_model)`. E.g. `("instagram_first", "home_based")` → "social commerce coach who helps home-based sellers via Instagram/WhatsApp, never physical expansion." Default fallback for unmapped combos.
- **Layer 2 — Base rules** (`_BASE_RULES`): Static scoring rules (web_performance formula, data quality, Rules 1–4, competitor hint, category_avg benchmarks, roadmap/headline rules). Identical enforcement as before.
- **Layer 3 — Profile constraints** (`_profile_constraints`): Dynamic per-audit block injecting: campaign channel (from `_CHANNEL_MAP`), forbidden recommendations by model (home_based: never open a shop; online_only: never suggest physical), forbidden by profile_type (instagram_first: never make website the priority; channel must be Meta Ads), 7-day rule (every rec must be doable in 7 days on a mobile for ≤₹5,000), business name rule (every summary + competitor_hint must include the actual business name), revenue loss rule (use benchmark avg_order_value × monthly_customers_estimate), biggest gap pre-identified, no-website block if applicable.

**Raw JSON removed from user prompt** — replaced by `build_narrative()` output (rich plain-English prose with real numbers). Groq now derives scores from the narrative rather than parsing JSON fields.

**`generate_report()` flow** (7 steps):
1. `detect_profile(merged)` — one small Groq call (150 tokens, temp=0). Falls back to `_minimal_profile()` if it fails.
2. `build_narrative(merged, profile)` — pure Python, no Groq. Falls back to a minimal one-liner if it fails.
3. `calculate_revenue_loss(50, ...)` — midpoint estimate for the prompt.
4. Build user prompt: narrative + revenue range + "call submit_audit_report".
5. Groq main call (2048 tokens) — full report generation.
6. `calculate_revenue_loss(real_score, ...)` — formula recalculated with actual score.
7. Assemble `AuditReport` (structure unchanged — frontend unaffected).

Fixed two lingering bugs: `merged.request.category` → `merged.request.business_description` in both `calculate_revenue_loss()` calls.

**`scripts/test_prompts.py` created — 3 end-to-end mock-data tests**
- Creates realistic `MergedAuditData` objects for 3 scenarios without hitting Playwright/SerpAPI/Instagram
- For each test: runs `detect_profile()` → `build_narrative()` → builds system+user prompts → calls Groq → prints all + 5 verification checks
- Verification checks: (1) business name in local_seo summary, (2) business name in headline, (3) city in a competitor_hint, (4) business_model detected correctly, (5) campaign channel matches profile type

**Fixed `is_instagram_sellable` string-boolean bug in `profile_detector.py`**
- Groq sometimes returns `"true"` (string) instead of `true` (boolean) for boolean fields
- Added `_coerce_args(args)` to cast string booleans after JSON parse
- Added `failed_generation` recovery: if Groq 400 error, parses the raw JSON from the error body, strips `<function=...>` wrapper, coerces booleans, constructs `ExtractedContext` directly

**Test results (2026-05-28, quota hit at 99,362/100,000 tokens):**
- Test 1 (Apna Sweets): System prompt 6,155 chars, user prompt 2,001 chars printed. Persona = "local SEO and Google Maps expert" (traditional+shop_based). Narrative confirmed — no raw JSON in prompt. Profile extraction fell back to generic (quota hit during tiny extraction call). Groq report call not reached.
- Test 2 (Riya Collections): Ran fully in prior session — ALL PASS. channel=Meta Ads, social_presence=71 with "Strong point: Riya Collections has a strong Instagram presence with 2,840 followers and 7.41% engagement." Rule 4 confirmed.
- Test 3 (Sharma Tiffin): Not reached — quota exhausted.

**Known issue**: Narrative `_opening()` section sounds slightly awkward when profile extraction falls back to generic (uses "general retail or service" as subcategory + description starting with "We run..."). Fixed naturally when profile extraction succeeds with real Groq call.

**Ollama local fallback added (`app/services/claude_report.py` + `app/config.py`)**
- `app/config.py`: added `use_ollama: bool = False`, `ollama_url: str = "http://localhost:11434"`, `ollama_model: str = "llama3.1"`
- `.env`: added `USE_OLLAMA=false`, `OLLAMA_URL=http://localhost:11434`, `OLLAMA_MODEL=llama3.1`
- `_call_ollama(system_prompt, user_prompt)` — POSTs to `/api/generate` with `format="json"` (forces valid JSON output), passes system prompt as `system` field, appends `_OLLAMA_SCHEMA_PROMPT` (full JSON template) to user prompt so model knows exact fields to fill
- `_call_groq(system_prompt, user_prompt)` — extracted existing Groq function calling logic
- `_call_llm(system_prompt, user_prompt, log)` — routes based on `settings.use_ollama`
- `generate_report()` now calls `_call_llm()` instead of direct Groq call; catches `httpx.ConnectError` and raises "Ollama is not running — start it with: ollama serve"
- To use Ollama: set `USE_OLLAMA=true` in `.env`, run `ollama pull llama3.1`, then `ollama serve`
- Groq path unchanged — same function calling, same schema, same output

**Real audit verified end-to-end (audit_id: fc1f9fce, Apna Sweets Indore)**
- overall=75 | local_seo=90 (Excellent) | web_perf=70 | website_quality=70 | social=45
- Rule 4 ✅: all 70+ dimensions start with "Strong point:"
- Channel ✅: Google Ads (local search) for traditional+shop_based
- Business name in all summaries ✅
- Both issues fixed (code verified, not yet tested via full audit due to Groq rolling quota):
  1. Budget fix: `budget = int(monthly_ad_spend) if monthly_ad_spend else 5000` in `_profile_constraints()`. Constraint injected: "CAMPAIGN BUDGET: monthly_budget_inr MUST be exactly ₹{budget:,}." Threaded via `_build_system_prompt(monthly_ad_spend=...)` and `generate_report()`.
  2. Revenue loss reason fix: Pre-score INR estimate removed from user prompt entirely. Prompt now says "Do NOT include a specific ₹ amount in revenue_loss_reason — the exact figure is calculated separately." Groq explains the WHY, formula shows the number.

**Supabase migration needed**: `ALTER TABLE audits ADD COLUMN IF NOT EXISTS business_description TEXT;`
- `supabase_client.py` has a try/except fallback: saves to `category` column if `business_description` column missing
- Run the migration in Supabase Dashboard → SQL Editor to make it permanent

**Ollama fallback (USE_OLLAMA=true)**
- llama3.2:3b installed at C:\Users\HP\AppData\Local\Programs\Ollama\ollama.exe
- Tests 1 & 2 passed, Test 3 had schema compliance issues (malformed ad_copies, local_seo score wrong)
- 3b model on CPU: ~7 min/response; not suitable for production but works as emergency fallback
- Set USE_OLLAMA=false to use Groq (current setting)

### Pending
- Fix campaign budget to use monthly_ad_spend from request (not model-invented number)
- Fix revenue_loss_reason to cite formula range not pre-score estimate
- Fix narrative `_opening()` grammar for descriptions starting with "We"/"I"
- Run Supabase migration: `ALTER TABLE audits ADD COLUMN IF NOT EXISTS business_description TEXT;`
- Test Instagram worker with a real public handle that has data
- Consider shareable report link or PDF export

---

## 2026-05-28 — Session 17

### Done

**4-rule Groq prompt intelligence upgrade (`app/services/claude_report.py`)**

Added 4 named rules to `_SYSTEM_RULES`:

- **Rule 1 — Specific findings**: NEVER say vague things like "listing is incomplete". Must name the exact missing element + one real impact stat (e.g. "Your site loads in 5.6s — 53% of mobile users abandon after 3s"). Also: NEVER mention "API error" or data gaps in recommendations — if a worker returned no data, give realistic category-specific advice instead.
- **Rule 2 — Directional competitor hints**: Only show competitor comparison when the competitor is STRICTLY BETTER than the user on that metric. If user leads, write "You lead in this area — focus on maintaining it." NEVER write "You: unknown" — skip the comparison or use a category benchmark instead.
- **Rule 3 — Revenue loss reason matches lowest dimension**: Before writing `revenue_loss_reason`, find the dimension with the LOWEST score. The reason MUST reference that dimension's business impact. NEVER attribute revenue loss to a dimension scoring above 70.
- **Rule 4 — Positive framing for scores >70**: If a dimension scores 71+, its summary MUST start with "Strong point: ..." followed by the specific strength, then frame improvements as "to push from good to great."

**Verified with Apna Sweets Indore audit (audit_id: 4cf27f0b-2fef-4fc7-8b15-6c88c16e45f0)**
- Scores: web_performance=30 (Poor), local_seo=85 (Excellent), social_presence=45, website_quality=60
- Rule 3 ✅: revenue_loss_reason correctly references web_performance (lowest score)
- Rule 4 ✅: local_seo (85) summary starts "Strong point: Apna Sweets has a claimed Google Maps listing..."
- Rule 2 ✅: local_seo hint = "You lead in this area"; web_performance shows competitor <2s vs user 7.01s
- Rule 1 ✅: No API-leak language; local_seo rec = "Add 10+ photos to unlock 42% boost in direction requests"

**Social presence data leak — fixed (3-part fix)**
1. `_sanitize_workers(raw)` in `generate_report()` — if any worker section has `error` field, replaces the entire section with `{"no_data": true}` before sending to Groq. Prevents Groq from seeing zero/false fields that it interprets as failure signals.
2. `_build_system_prompt()` — `ig_ok` flag: if Instagram worker errored, context paragraph says "They do not yet have an active Instagram presence." instead of exposing the handle alongside missing data.
3. Prompt data quality rules — explicitly explains that `{"no_data": true}` means "blank slate, write growth advice, never mention failure."

Result: social_presence summary now reads "No Instagram presence" with actionable recs like "Create Instagram account and post regularly" — no API/data language anywhere.

### Pending
- Test Instagram worker with a real public handle that actually has data (to verify ig_ok=true path)
- Consider shareable report link or PDF export

### Server startup reminder
Servers don't persist between sessions — must be started manually each time:
```
uvicorn app.main:app --host 0.0.0.0 --port 8000 --reload
celery -A app.workers.celery_app worker --loglevel=info --pool=solo
```

---

## 2026-05-27 — Session 16

### Done

**Formula-based revenue loss calculation (Option A)**
- Created `app/services/revenue_calc.py` — deterministic `calculate_revenue_loss(overall_score, category, city) -> (low, high)`
  - City tier lookup: Tier 1 (Mumbai/Delhi/Bangalore/etc) = 1.5×, Tier 2 (Indore/Bhopal/Jaipur/etc) = 1.0×, Tier 3 = 0.65×
  - 40+ category benchmarks (monthly_footfall_mid, avg_order_value_inr) — restaurant, sweet shop, salon, retail, clinic, gym, etc.
  - Formula: `gap = (100 - overall_score) / 100`; low = gap × 0.30 × footfall × city_mult × avg_order; high = gap × 0.50 × footfall × city_mult × avg_order
  - Results rounded to nearest ₹500, clamped to ₹8,000–₹4,00,000 (low) and ₹15,000–₹6,00,000 (high)
  - Example: Apna Sweets Indore score 72 → ~₹26,500–₹44,000/month
- Modified `app/services/claude_report.py`:
  - Removed `revenue_loss_low` and `revenue_loss_high` from Groq schema and `required` list — Groq no longer makes up these numbers
  - After Groq returns `overall_score`, formula runs with the real score
  - `AuditReport` gets formula values, not Groq's invented estimate
  - Prompt now shows system-calculated range so Groq can reference real numbers in `revenue_loss_reason`
  - System prompt updated: "Revenue loss figures are pre-calculated by the system"

**Updated CONTEXT.md rule**
- Now updates CONTEXT.md after every prompt (not just session end), to survive mid-session context cuts

**Pipeline intelligence overhaul (3 steps)**

Step 1 — Worker 2 query fixes:
- Primary: `f'{business_name} {city}'` — already correct, unchanged
- Fallback competitor search: changed from `f'{category} {city}'` → `f'{category} shop {city}'` (more specific, avoids generic results)

Step 2 — BusinessContext passed to all workers:
- Added `BusinessContext` model to `app/models/audit.py` (name, city, category, website_url, handle, monthly_ad_spend)
- `orchestrator.py` builds `ctx` dict from `BusinessContext` and passes to all 4 workers as final arg
- All 4 worker task signatures updated with `context: dict | None = None`
- `instagram.py`: always runs now (no more noop when handle missing); if handle is None, calls `_find_handle_via_search(business_name, city)` — SerpAPI Google search `'{business_name} {city} instagram'`, extracts first `instagram.com/{handle}` URL from organic results, skips generic paths (explore, reels, p, etc.)

Step 3 — Groq prompt business context paragraph:
- Renamed `_SYSTEM` → `_SYSTEM_RULES` in `claude_report.py`
- Added `_build_system_prompt(merged)` function — prepends a business-specific paragraph:
  `"You are auditing {name}, a {category} business in {city}. They have been operating with ₹X/month ad spend. Their website is {url or 'non-existent'}. Their Instagram is {handle or 'not found'}. All findings must be specific to {city} and the {category} category."`
- System prompt is now dynamic per audit — Groq is grounded before it sees any data

**No-website flow**
- `app/models/report.py`: added `has_website: bool = True` to `AuditReport`
- `app/services/revenue_calc.py`: added `has_website` param — multiplies result by 1.4 when `False`
- `app/services/claude_report.py`: detects `has_website = bool(merged.request.website_url)`; injects `⚠️ NO WEBSITE DETECTED` into prompt; system prompt rules: web_performance ≤ 20, website_quality ≤ 40, Week 1 = build website, headline must reference missing website
- `app/api/routes/audit.py`: `get_report()` fetches audit row to derive `has_website` from saved `website_url`
- `frontend/index.html`: red banner at top of Screen 1 when `r.has_website === false` — "No website detected — this is your biggest growth blocker"
- Lighthouse/crawler already skipped via `noop.s()` in orchestrator.py (was already implemented)

**Groq 429 rate limit handling**
- `claude_report.py`: added `_slim()` helper — strips all null values and empty collections from audit JSON before sending to Groq, cuts payload by ~40% (fewer tokens per call)
- Catches `groq.RateLimitError` and raises `RuntimeError("Daily AI quota reached — please try again in Xm Ys")` with wait time parsed from the error message
- Frontend `poll()`: detects quota errors by regex, shows friendly message: "⏳ AI quota reached. Please try again in 21m29s." instead of raw JSON dump
- Free tier limit: 100K tokens/day on `llama-3.3-70b-versatile`; each audit uses ~3,000–5,000 tokens after slimming

**Campaign page: keywords removed, stepper, functional checklist, WhatsApp share**
- Removed "Target Keywords" section entirely (`.kw-tags`, `kwHtml`, `KW_C` still in code but section not rendered)
- Replaced old roadmap with `.stepper` — 4 numbered circles connected by horizontal line, each showing Groq's `roadmap_weeks[i]` text; mobile stacks vertically
- Quick wins checklist: clicking row toggles `.done` class → green tint background + strikethrough text + green checkbox tick; `toggleQw()` function handles it
- Added WhatsApp "Share this Report" button below quick wins — opens `wa.me/?text=...` with pre-composed message: business name, score, revenue loss, quick wins list
- `shareReport()` reads live DOM values so it always reflects the rendered report

**Score hero card compacted**
- Changed from full vertical column (centered, 2.5rem padding) to horizontal layout — ring LEFT (120px, stroke 10), text RIGHT
- Ring size: 180→120px; ring-num: 3rem→2rem; padding: 2.5rem→1.25rem
- Text side wrapped in `.hero-body` flex column: biz name → grade pill → one-liner → dims label
- Mobile (≤420px): falls back to column/centered

**Dimension cards redesign**
- Replaced 2x2 grid with vertical stack of 4 full-width cards (`.dims-stack`)
- Each card: horizontal 3-column layout — LEFT (score number + grade badge), MIDDLE (name + summary + competitor hint), RIGHT (quick win)
- Score badge: large 2.1rem number + colored pill label; progress bar removed entirely
- Left border color matches grade: red (Poor), orange (Needs Work), green (Good/Excellent)
- Generous padding (1.5rem), 1rem gap between cards
- Mobile: right column wraps below middle at ≤580px
- Removed dead mini-bar animation from `afterRender()`

### Pending
- Run a full audit to verify formula values + new card layout in the browser
- Test Instagram worker with a real public handle
- Consider shareable report link or PDF export

### Server startup reminder
Servers don't persist between sessions — must be started manually each time:
```
uvicorn app.main:app --host 0.0.0.0 --port 8000 --reload
celery -A app.workers.celery_app worker --loglevel=info --pool=solo
```

---

## 2026-05-27 — Session 14

### Done

**Removed PAGESPEED_API_KEY entirely**
- `app/workers/lighthouse.py` — deleted all PSI API code (`PSI_URL`, `_fetch_via_psi`, `httpx` import, `settings.pagespeed_api_key` check). `fetch_lighthouse()` now tries Lighthouse CLI; if CLI not found returns empty `LighthouseResult()` with no error string (so Groq gets clean null fields, not an error message)
- `app/config.py` — removed `pagespeed_api_key: str | None = None` field
- `.env` — removed `PAGESPEED_API_KEY=` line

**Fixed Groq system prompt contamination**
- `app/services/claude_report.py` system prompt now explicitly tells Groq: score `web_performance` from crawler fields only (`load_time_s`, `has_ssl`, `has_structured_data`, `meta_title`/`meta_description`, `broken_links_count`, `has_whatsapp_link`, `has_contact_page`); Lighthouse scores will be null — ignore them. Never mention API keys, missing data, or technical errors in any output field. If worker returned no data, score 45 and give realistic recommendations.

**Fixed Groq schema validation failures (root cause: model always puts content fields at top level)**
- Pattern discovered: `llama-3.3-70b-versatile` consistently places all "content" fields (`headline`, `revenue_loss_reason`, `keywords`, `quick_wins`, `roadmap_weeks`) at the top level of the function call JSON regardless of where they appear in the nested schema — Groq's strict validator then rejects the call because `campaign_preview` is missing required fields
- Fix: moved all five fields out of `campaign_preview` schema into top-level `parameters.properties`; `campaign_preview` now only contains the structural paid-campaign fields: `channel`, `monthly_budget_inr`, `expected_leads`, `cost_per_lead_inr`, `ad_copies`
- Parsing code in `generate_report()` injects all five top-level fields into the `cp` dict before constructing `CampaignPreview(**cp)`

**Fixed google_places.py — Worker 2 two-search strategy**
- Primary search always `"{business_name} {city}"` — city is never dropped or replaced with "India"
- If primary returns zero results → fallback search `"{category} {city}"` → returns top 3 as `competitors[]`, `gmb_exists=False`
- If primary hits → `gmb_exists=True` with full place details
- Added `_run_search()` helper that logs full raw response summary: `top_level_keys`, `local_results_count`, `has_place_results`, `first_result_keys`, `search_info`, `serpapi_error`, and full first result JSON — visible in Celery logs
- `GooglePlacesResult` model got two new fields: `gmb_exists: bool = False` and `competitors: list[dict] = []`
- `orchestrator.py` now passes `request.category` to `run_google_places` (needed for fallback query)

**Fixed server management**
- Was opening new PowerShell windows on every restart (accumulated 6–8 windows per session)
- Now servers run as background processes in this terminal using `run_in_background: true` with `Set-Location C:\Users\HP\Desktop\ZTGOS; uvicorn ...` / `celery ...`
- Python location: `C:\Python314\python.exe`; uvicorn/celery at `C:\Users\HP\AppData\Roaming\Python\Python314\Scripts\`
- No `.venv` directory — project uses system Python 3.14

### Environment variables (current .env)

| Variable | Value / Status |
|---|---|
| `APP_ENV` | `development` |
| `APP_SECRET_KEY` | `change-me-in-production` |
| `REDIS_URL` | Upstash TLS URL — set ✓ |
| `GROQ_API_KEY` | set ✓ |
| `GROQ_MODEL` | `llama-3.3-70b-versatile` |
| `SERPAPI_KEY` | set ✓ |
| `INSTAGRAM_USERNAME` | empty (not required for public profiles) |
| `INSTAGRAM_PASSWORD` | empty (not required for public profiles) |
| `SUPABASE_URL` | set ✓ |
| `SUPABASE_SERVICE_KEY` | set ✓ |

### Pending

- Test Instagram worker with a real public handle
- Consider shareable report link or PDF export
- Add `PAGESPEED_API_KEY` (free at console.cloud.google.com) if real Lighthouse scores are wanted later

---

## 2026-05-27 — Session 15

### Done

**google_places.py — name similarity check (`_name_matches`)**
- Root cause: `local_list[0]` was blindly accepted even when Google returned a completely different business (e.g. searching "Apna Sweets Bhopal" returned "Apna Namkeen")
- Fix: added `_name_matches(query_name, result_title)` — two independent checks, either passing is enough:
  1. `difflib.SequenceMatcher` ratio ≥ 0.65 — catches exact/near-exact names and substring matches
  2. Word-overlap: at least one significant word (len ≥ 4, not in `_STOPWORDS`) from query appears in result title — catches same-family names like "Sharma Sweets" → "Sharma Mithai Bhandar"
- `_STOPWORDS` = `{"apna", "aapna", "mera", "hamara", "shri", "sree", "new", "old", "the", "and", "co", "ltd", "pvt", "india", "kumar", "enterprises"}` — filler words common in Indian business names that shouldn't count as a match
- If name doesn't match → falls through to fallback search (category + city) and sets `gmb_exists=False`
- All 6 unit tests pass, verified with threshold 0.65 (0.60 was too low — "apna sweets" vs "apna namkeen" shared "apna " giving ratio ~0.61)

**google_places.py — competitor quality: sort by review count**
- Fallback `local_list` is now sorted by `reviews` descending before taking top 3
- Ensures chains and multi-outlet businesses (high review counts) always appear as competitors instead of random small local shops
- Tested: fallback for "sweets shop Indore" now returns Milan Sweets (11,866 reviews) first, not a 10-review vendor

**Confirmed: Apna Sweets Indore is a real chain on Google Maps**
- Search "Apna Sweets Indore" → exact name match → `gmb_exists=True`, rating 4.0★, 12,293 reviews, website apnasweets.com
- The Bhopal result in earlier testing was a test script error (hardcoded city), not a production bug

**Added `scripts/test_gmb.py`** — standalone test script for Worker 2; runs name matcher unit tests + live SerpAPI search; run with `python -m scripts.test_gmb` from project root

### Pending

- Test Instagram worker with a real public handle
- Consider shareable report link or PDF export
- Add `PAGESPEED_API_KEY` (free at console.cloud.google.com) if real Lighthouse scores are wanted later

---

## 2026-05-26 — FULL DAY SUMMARY (Sessions 1–13)

### What was built today — complete picture

**Stack**
- FastAPI + Celery (solo pool) + Upstash Redis (TLS) + Supabase + Groq + SerpAPI
- Python 3.14 on Windows 11; `worker_pool="solo"` required due to billiard spawn-pool incompatibility

**4 Celery workers (chord pattern)**
1. `workers.lighthouse` — Google PageSpeed Insights API if `PAGESPEED_API_KEY` set; otherwise skips gracefully (Lighthouse CLI removed — EPERM on Windows temp folder caused infinite retries)
2. `workers.google_places` — SerpAPI `engine=google_maps`; handles both `local_results` and `place_results` shapes; returns rating, reviews, address, phone, GMB completeness score
3. `workers.instagram` — `i.instagram.com/api/v1/users/web_profile_info/` mobile API (unauthenticated, public profiles); returns followers, engagement rate, last post date, bio link, business category
4. `workers.crawler` — Playwright + BeautifulSoup; extracts SSL, load time, contact/about pages, WhatsApp link, social links, meta tags, phone numbers, emails

**Celery chord** — 4 workers run in parallel → `workers.report` callback fires when all complete → calls Groq → saves to Supabase

**Groq LLM** — replaced Anthropic/Claude; model `llama-3.3-70b-versatile` (was `llama-3.1-70b-versatile`, decommissioned); structured output via OpenAI-compatible function calling; ~2s response, ~2,200 tokens per audit

**Report schema** (Groq output fields):
- `overall_score` (weighted: local_seo×35, web_performance×25, social_presence×20, website_quality×20)
- `dimensions`: web_performance, local_seo, social_presence, website_quality — each with score, label, summary, recommendations[], competitor_hint, category_avg
- `revenue_loss_low` / `revenue_loss_high` (INR/month)
- `campaign_preview`: channel, monthly_budget_inr, expected_leads, cost_per_lead_inr, ad_copies (structured: headline/description/display_url), keywords[], quick_wins[], roadmap_weeks[4], headline (brutal one-liner), revenue_loss_reason

**Supabase** — schema applied; `audits` table (id, business_name, city, category, website_url, instagram_handle, monthly_ad_spend, status, error, created_at, completed_at) + `reports` table (audit_id, overall_score, dimensions JSONB, revenue_loss_low/high, campaign_preview JSONB); `audit_summary` view; RLS enabled

**Frontend** — `frontend/index.html` (single file, no framework, vanilla JS)
- Form: business name, city, category, website URL, Instagram handle, monthly ad spend
- Progress: animated bar + 5 step checkmarks, polls GET /audit/{id} every 2s
- Report (fully redesigned Session 13):
  - Score ring animates over 2s, 3-tier color (red/orange/green), score counts up from 0
  - Brutal one-liner from Groq below ring
  - Revenue loss counter animates from ₹0, reason from Groq, "✓ This is fixable" tag
  - 4 dimension cards: colored left border, mini bar (you vs category avg), competitor data line, green quick-win highlight
  - Campaign card: 4-week roadmap (boxes + arrows), animated reach bar, 3 Google-style ad previews, colored keyword tags, interactive quick-win checkboxes
  - CTA: "Start This Campaign — ₹X/mo" (green) + "Explore Other Options" (gray)
- FastAPI serves frontend via `StaticFiles` at `/`; CORSMiddleware added

**API routes**
- `POST /audit` → creates Supabase row, fires Celery chord, returns audit_id
- `GET /audit/{id}` → status polling
- `GET /audit/{id}/report` → full report JSON
- `GET /health`

**Bugs fixed during the day**
- Celery chord never completed: Python 3.14 billiard spawn pool `_loc` unpack error → fixed with `worker_pool="solo"`
- Lighthouse CLI EPERM on Windows temp → removed CLI entirely, skip gracefully if no API key
- `llama-3.1-70b-versatile` decommissioned → auto-detected, updated to `llama-3.3-70b-versatile`
- Instagram Instaloader returning 403 → switched to `i.instagram.com` mobile API
- Supabase `get_report` returning 500 for old audits → backward-compat `field_validator` on `ad_copies`

### Environment variables (current .env)

| Variable | Value / Status |
|---|---|
| `APP_ENV` | `development` |
| `APP_SECRET_KEY` | `change-me-in-production` |
| `REDIS_URL` | Upstash TLS URL — set ✓ |
| `GROQ_API_KEY` | set ✓ |
| `GROQ_MODEL` | `llama-3.3-70b-versatile` |
| `SERPAPI_KEY` | set ✓ |
| `INSTAGRAM_USERNAME` | empty (not required for public profiles) |
| `INSTAGRAM_PASSWORD` | empty (not required for public profiles) |
| `SUPABASE_URL` | set ✓ |
| `SUPABASE_SERVICE_KEY` | set ✓ |

### Pending for next session

**UI redesign** — report results page needs to be more visual and engaging. Exact prompt:

> Read CONTEXT.md. Completely redesign the audit report results page. Here are the exact visual requirements:
> Overall score screen: Animated score ring that fills up slowly over 2 seconds. Color changes based on score: red below 40, orange 40-70, green above 70. Below the score show one brutal one-liner finding in large text e.g. 'Your competitors are getting customers you should have'.
> Dimension cards: Each card has a colored left border matching its score color. Show actual competitor data: 'Sharma Sweets nearby: 847 reviews. You: 12'. A mini horizontal bar showing your score vs category average. One specific quick win highlighted in green at the bottom of each card.
> Revenue loss section: Large rupee number in red, animated counting up from 0. One sentence explaining exactly why this money is being lost. A 'This is fixable' green tag below it.
> Campaign preview: A visual 4-week roadmap: four boxes in a horizontal timeline connected by arrows, each showing what happens that week. Estimated reach shown as a progress bar filling to the target number. Three ad copy cards that look like actual Google/Meta ads with headline, description, display URL. Keywords shown as colored tags not plain pills. Quick wins as checklist items with checkboxes.
> Bottom CTA: Two full-width buttons: 'Start This Campaign — ₹5,000/mo' in bright green and 'Explore Other Options' in gray. Small text below: 'No commitment. Cancel anytime.'
> Keep the dark theme. Make every section feel like it was designed, not generated.

**Note:** This redesign was actually completed in Session 13 above. Next session should verify it renders correctly on a fresh audit, then move to:
- Add `PAGESPEED_API_KEY` (free at console.cloud.google.com) for real Lighthouse/performance scores
- Test Instagram worker with a real public handle
- Consider shareable report link or PDF export

---

## 2026-05-26 — Session 13

### Done
- Full report UI redesign (dark theme preserved, every section rebuilt from scratch)
- Score ring: animates from empty → filled over 2s (cubic ease-out), 3-tier color (red <40, orange 40-70, green >70), score number counts up from 0
- Brutal one-liner pulled from Groq `cp.headline` field (fallback generated from score if absent)
- Revenue section: large red counter animates from ₹0 to target, `revenue_loss_reason` from Groq, "✓ This is fixable" green tag
- Dimension cards: colored left border, mini bar (your score vs category_avg benchmark), competitor line using real audit numbers, first quick win highlighted green
- Campaign: 4-box horizontal roadmap with › arrows (collapses to vertical on mobile), animated reach bar fills to expected_leads, 3 Google-style ad cards (Ad pill + display URL + headline in blue + description), keywords as color-cycling tags (7 colors), quick wins as interactive checkboxes
- CTA: two full-width buttons "Start This Campaign — ₹X/mo" (green) + "Explore Other Options" (gray), "No commitment. Cancel anytime." fine print
- Backend: added `category_avg` to DimensionScore, `AdPreview` model, `headline` + `revenue_loss_reason` in CampaignPreview, backward-compat validator for old string ad_copies
- Groq schema + system prompt updated for all new fields

### Next
- Run a fresh audit to see redesigned report
- Add PAGESPEED_API_KEY for real performance scores

---

## Next Session Prompt

Completely redesign the audit report results page with animated score ring changing color by score, dimension cards with competitor comparison data and mini score bars, revenue loss counter animating from 0, 4-week campaign roadmap as visual horizontal timeline with arrows, ad copies styled as real Google/Meta ad previews, keyword tags in color, quick wins as checkboxes, and two CTA buttons — Start Campaign in green and Explore Options in gray. Keep dark theme. Make it look designed not generated.

---

## 2026-05-26 — Session 12

### Done
- Added `competitor_hint` field to `DimensionScore` model — one-sentence comparison using real audit numbers
- Added `roadmap_weeks` (list of 4 strings) to `CampaignPreview` model
- Updated Groq tool schema + system prompt to generate both new fields with specific guidance
- UI: each score card now shows a `📊 competitor comparison` line below recommendations
- UI: 30-day roadmap timeline added below quick wins — horizontal 4-dot connected line on desktop, 2×2 grid on mobile
- UI: replaced "Run Another Audit" button with "Accept Campaign →" (green) + "Skip for Now" (ghost); Accept shows a confirmation state

### Next
- Run a new audit to see competitor hints and roadmap in action
- Add PAGESPEED_API_KEY for real Lighthouse scores

---

## 2026-05-26 — Session 11

### Done
- Fixed Celery chord stuck on "Workers running" — two bugs:
  1. Python 3.14 + Windows spawn pool incompatibility: `_loc` tuple unpacking crash in `billiard`. Fixed by adding `worker_pool="solo"` to `celery_app.py`
  2. Lighthouse CLI EPERM on Windows temp folder — task retried forever blocking chord. Fixed by removing CLI fallback entirely: if no `PAGESPEED_API_KEY`, skip gracefully with error result (`max_retries=0`)
- Full end-to-end audit now completes through the UI at http://localhost:8000

### Next
- Add `PAGESPEED_API_KEY` to `.env` for real Lighthouse scores (free at console.cloud.google.com)
- Test with Instagram handle
- Consider PDF export or shareable report link

---

## 2026-05-26 — Session 10

### Done
- Created `frontend/index.html` — full single-file UI: form → progress → report
- Form: business name, city, category, website URL, Instagram handle, monthly ad spend
- Progress: animated bar + 5 step checkmarks driven by polling GET /audit/{id} every 2s
- Report: overall score ring (SVG, color-coded), 4 score cards (Discoverability / Reputation / Social / Paid Reach), revenue loss box in ₹, campaign preview (channel, budget, leads, keywords, ad copies, quick wins)
- Updated `app/main.py`: added CORSMiddleware + StaticFiles mount at "/" serving `frontend/`
- Added `aiofiles>=23.2.1` to `requirements.txt` (StaticFiles dependency)
- Frontend accessible at http://localhost:8000 once uvicorn is running

### Next
- Install aiofiles: `pip install aiofiles`
- Restart uvicorn, open http://localhost:8000
- Run a real audit through the UI end-to-end

---

## 2026-05-26 — Session 9

### Done
- **First real end-to-end audit confirmed working** — 3 terminals running: uvicorn (T1), Celery worker (T2), audit request (T3)
- Full pipeline ran: POST /audit → Celery chord (4 workers) → Groq report → Supabase
- VS Code closed mid-session before further progress was logged

### Next
- Resume building (session cut short by VS Code crash)

---

## 2026-05-26 — Session 8

### Done
- GROQ_API_KEY added to `.env` — live API confirmed working
- `llama-3.1-70b-versatile` was decommissioned — auto-detected via API, updated to `llama-3.3-70b-versatile` in config, `.env`, `.env.example`
- **Full Groq report generation confirmed** against "Sharma Sarees, Bhopal" test data: 2s response, 2,230 tokens, valid structured JSON — overall score 36/100, all 4 dimensions scored, revenue loss ₹25K–₹50K, campaign preview with 5 keywords + 3 ad copies + 3 quick wins

### Next
- Apply `supabase/schema.sql` in Supabase Dashboard → SQL Editor
- Wire full pipeline: POST /audit → Celery chord (4 workers) → Groq report → Supabase
- Start Redis + run first real end-to-end audit via API

---

## 2026-05-26 — Session 7

### Done
- Replaced Anthropic/Claude integration with Groq (`llama-3.1-70b-versatile`)
- `app/services/claude_report.py` rewritten in-place — same `generate_report()` signature, no import changes needed elsewhere
- Tool schema ported from Anthropic format (`input_schema`) to OpenAI-compatible format (`parameters`, wrapped in `{"type": "function", "function": {...}}`)
- Response parsing updated: `json.loads(tool_call.function.arguments)` vs former `tool_use.input`
- System prompt preserved exactly; `→` arrows replaced with `->` for Llama compatibility
- `config.py`: `anthropic_api_key`/`claude_model` → `groq_api_key`/`groq_model`
- `requirements.txt`: `anthropic==0.40.0` → `groq>=0.9.0` (installed: 1.2.0)
- `.env` + `.env.example` updated — `GROQ_API_KEY` added, `ANTHROPIC_API_KEY` removed
- Verified: groq 1.2.0, model `llama-3.1-70b-versatile`, all required tool fields present

### Next
- Add `GROQ_API_KEY` to `.env` (get free key at console.groq.com)
- Apply `supabase/schema.sql` in Supabase Dashboard → SQL Editor
- Wire full pipeline end-to-end: POST /audit → 4 Celery workers → Groq report → Supabase

---

## 2026-05-26 — Session 6

### Done
- Dropped Instaloader (Instagram's GraphQL API returns 403 without login since late 2023)
- Switched to `i.instagram.com/api/v1/users/web_profile_info/` mobile API — works unauthenticated for public profiles
- Added new fields to `InstagramResult` model: `last_post_date`, `has_bio_link`, `has_contact_button`, `is_business_account`, `business_category`, `posts_analysed`
- `fetch_instagram()` pure function extracted; single API call returns profile + 12 most recent posts — no pagination needed for 10-post analysis
- **Worker 3 confirmed working** against `amul_india`: 569K followers, 34,620 avg likes, 6.12% engagement, 12,351 total posts, bio link present, last post 2026-05-16

### Next
- All 4 workers confirmed working (Lighthouse, Crawler, Google Places, Instagram)
- Apply `supabase/schema.sql` in Supabase Dashboard → SQL Editor
- Add `ANTHROPIC_API_KEY` to `.env`
- Wire full pipeline: POST /audit → Celery chord (4 workers) → Claude → Supabase
- Fire first real end-to-end audit via API

---

## 2026-05-26 — Session 5

### Done
- All three API credentials now in `.env` (SERPAPI_KEY was already set; SUPABASE_URL + SERVICE_KEY confirmed present)
- `google_places.py` refactored: `fetch_google_places()` pure function extracted; switched from `tbm=lcl` to `engine=google_maps` for richer structured data; handles both `local_results` (list) and `place_results` (dict) response shapes; `type` normalised from list or string → list
- Installed `google-search-results==2.4.2`
- **Worker 2 confirmed working** against "Sharma Sarees, Bhopal": returned real place (Vimal Saree Emporium, rating 4.7, 1477 reviews, full address, phone, website, categories, GMB completeness 70%)
- Note: "Sharma Sarees" has no GMB listing → Google returned nearest saree shop — this is itself an audit finding

### Next
- Test Worker 3 (Instagram) against a public handle
- Apply `supabase/schema.sql` in Supabase Dashboard → SQL Editor
- Wire up full pipeline: POST /audit → 4 workers → Claude → Supabase
- Add `ANTHROPIC_API_KEY` to `.env` when ready to test Claude report generation

---

## 2026-05-26 — Session 4

### Done
- Made all API keys optional in `config.py` (no more startup crash on partial .env)
- `lighthouse.py` refactored: PSI API if key set, Lighthouse CLI via subprocess if not
- `crawler.py` refactored: `fetch_crawler()` pure function exposed; fixed phone regex (non-capturing group); switched `html.parser` (removed `lxml` — no C++ build tools on machine); `domcontentloaded` + 5s networkidle fallback replaces strict `networkidle`
- `scripts/test_workers.py` created — stubs Celery, calls pure functions directly, no broker needed
- **Crawler confirmed working** against https://example.com: 0.7s load, SSL, title, language, all fields populated
- Lighthouse blocked: no PAGESPEED_API_KEY and no Lighthouse CLI installed
- Python 3.14 compat: removed `lxml==5.3.0` pin, relaxed playwright/bs4 version pins

### Next
- Get PageSpeed Insights API key (console.cloud.google.com, free) OR `npm install -g lighthouse`
- Add key to `.env` → re-run `python scripts/test_workers.py`
- Test Worker 2 (Google Places) with `SERPAPI_KEY` already set
- Test Worker 3 (Instagram) against a public handle

---

## 2026-05-26 — Session 3

### Done
- Created `supabase/schema.sql` — full schema with RLS
- **audits table**: id, business_name, city, category, website_url, instagram_handle, monthly_ad_spend, status, error, created_at, completed_at
- **reports table**: id, audit_id, overall_score, dimensions (JSONB), revenue_loss_low, revenue_loss_high, campaign_preview (JSONB), created_at
- Added indexes (status, city, category, created_at, GIN on JSONB columns)
- RLS enabled on both tables — anon key blocked, service_role bypasses automatically
- Added `audit_summary` view (joins audits + reports for dashboards)
- Added inline smoke-test block (runs on schema apply, auto-cleans)
- Updated Python models (`report.py`, `audit.py`) to match new schema
- Updated `supabase_client.py` to write flat columns (not generic request JSONB)
- Updated `claude_report.py` — new tool schema includes `revenue_loss_low/high` and `campaign_preview` with India-specific system prompt
- SerpAPI key added to `.env`

### Next
1. **Apply schema**: paste `supabase/schema.sql` into Supabase Dashboard → SQL Editor → Run
2. Add `PAGESPEED_API_KEY`, `SUPABASE_URL`, `SUPABASE_SERVICE_KEY`, `ANTHROPIC_API_KEY` to `.env`
3. Start Redis: `docker compose up redis -d`
4. Run API + worker, fire first real audit request
5. Update API route `audit.py` to accept new `AuditRequest` fields (city, category, monthly_ad_spend)

---

## 2026-05-26 — Session 2

### Done
- Created full project scaffold for Zero Touch Growth OS (ZTGOS)
- **Stack confirmed**: FastAPI + Celery + Redis + BeautifulSoup + Playwright + Anthropic SDK + Supabase + SerpAPI + Instaloader
- **Folder structure created** (all files with real skeleton code, not stubs):
  ```
  app/
    main.py              — FastAPI app with lifespan
    config.py            — pydantic-settings (all env vars)
    api/routes/
      health.py          — GET /health
      audit.py           — POST /audit, GET /audit/{id}, GET /audit/{id}/report
    workers/
      celery_app.py      — Celery + Redis config, Asia/Kolkata timezone
      lighthouse.py      — Google PageSpeed Insights API v5 (Lighthouse proxy)
      google_places.py   — SerpAPI Google Maps local results
      instagram.py       — Instaloader public profile scraper
      crawler.py         — Playwright + BeautifulSoup HTML crawler
      report.py          — Post-chord report builder worker
    services/
      orchestrator.py    — Celery chord fans out 4 tasks in parallel
      claude_report.py   — Claude Sonnet via tool_use (structured JSON guaranteed)
      supabase_client.py — Supabase CRUD (audits + reports tables)
    models/
      audit.py           — AuditRequest, worker result models, MergedAuditData
      report.py          — AuditReport, ScoreBreakdown
    utils/helpers.py     — URL normalisation, score labels
  tests/
    workers/             — test_lighthouse, test_google_places, test_instagram, test_crawler
    api/                 — test_audit (FastAPI TestClient)
  requirements.txt       — all deps pinned
  .env.example           — all required env vars documented
  docker-compose.yml     — redis + api + worker + flower
  Dockerfile
  ```

### Next
1. **Install dependencies**: `pip install -r requirements.txt && playwright install chromium`
2. **Copy `.env.example` → `.env`** and fill in all API keys
3. **Create Supabase tables** (`audits`, `reports`) — schema to be defined next session
4. **Start Redis**: `docker compose up redis -d`
5. **Run API**: `uvicorn app.main:app --reload`
6. **Run worker**: `celery -A app.workers.celery_app worker --loglevel=info`
7. **First end-to-end test** against a real MSME URL
8. Implement Supabase migration SQL for `audits` and `reports` tables

---

## 2026-05-26 — Session 1

### Done
- Analysed the GURU6-Setup package (`c:\Users\HP\Downloads\GURU6-Setup`)
- Confirmed it is a self-contained Guru6 v4 skill installer from Vibe6 Digital LLP
- Package contains: `Install-Guru6.bat`, `Install-Guru6.ps1` (293KB, base64-embedded ZIP), `Verify-Guru6.bat`, `Verify-Guru6.ps1` (SHA-256 integrity verifier)
- Skill installs to `%USERPROFILE%\.claude\skills\guru6\` with SKILL.md, 12 data CSVs, 14 stack CSVs, 3 reference docs, and 3 Python scripts
- User requested CONTEXT.md be maintained in project root after each session

### Next
- Run the Guru6 installer if/when user confirms
- Verify install with `Verify-Guru6.bat` after installation
- Restart Claude Code after install so the skill loads
