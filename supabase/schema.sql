-- =============================================================================
--  ZTGOS — Zero Touch Growth OS
--  Supabase Schema  |  Run this in: Supabase Dashboard → SQL Editor → Run
-- =============================================================================

-- ---------------------------------------------------------------------------
-- Extensions
-- ---------------------------------------------------------------------------
CREATE EXTENSION IF NOT EXISTS "pgcrypto";   -- gen_random_uuid()


-- ===========================================================================
--  TABLE: audits
--  One row per audit job. Status tracks the Celery pipeline.
-- ===========================================================================
CREATE TABLE IF NOT EXISTS audits (
    id                  UUID            PRIMARY KEY DEFAULT gen_random_uuid(),
    business_name       TEXT            NOT NULL,
    city                TEXT,
    category            TEXT,           -- e.g. 'restaurant', 'retail', 'salon'
    website_url         TEXT,
    instagram_handle    TEXT,
    monthly_ad_spend    NUMERIC(12, 2), -- INR; nullable if unknown
    status              TEXT            NOT NULL DEFAULT 'pending'
                            CHECK (status IN ('pending', 'running', 'running_report',
                                              'completed', 'failed')),
    error               TEXT,           -- populated on status = 'failed'
    created_at          TIMESTAMPTZ     NOT NULL DEFAULT NOW(),
    completed_at        TIMESTAMPTZ
);

-- Indexes
CREATE INDEX IF NOT EXISTS audits_status_idx      ON audits (status);
CREATE INDEX IF NOT EXISTS audits_created_at_idx  ON audits (created_at DESC);
CREATE INDEX IF NOT EXISTS audits_city_idx        ON audits (city);
CREATE INDEX IF NOT EXISTS audits_category_idx    ON audits (category);


-- ===========================================================================
--  TABLE: reports
--  One row per completed audit. Linked 1-to-1 with audits.
--
--  dimensions JSONB shape:
--  {
--    "web_performance": { "score": 72, "label": "Good",
--                         "summary": "...", "recommendations": ["..."] },
--    "local_seo":       { "score": 45, "label": "Needs Work",
--                         "summary": "...", "recommendations": ["..."] },
--    "social_presence": { "score": 30, "label": "Poor",
--                         "summary": "...", "recommendations": ["..."] },
--    "website_quality": { "score": 68, "label": "Good",
--                         "summary": "...", "recommendations": ["..."] }
--  }
--
--  campaign_preview JSONB shape:
--  {
--    "channel": "Google Ads",
--    "monthly_budget_inr": 5000,
--    "expected_leads": 15,
--    "cost_per_lead_inr": 333,
--    "ad_copies": ["Headline 1", "Headline 2"],
--    "keywords": ["keyword 1", "keyword 2"],
--    "quick_wins": ["Fix WhatsApp link", "Add photos to GMB"]
--  }
-- ===========================================================================
CREATE TABLE IF NOT EXISTS reports (
    id                  UUID            PRIMARY KEY DEFAULT gen_random_uuid(),
    audit_id            UUID            NOT NULL
                            REFERENCES audits (id) ON DELETE CASCADE,
    overall_score       INTEGER         NOT NULL CHECK (overall_score BETWEEN 0 AND 100),
    dimensions          JSONB           NOT NULL DEFAULT '{}',
    revenue_loss_low    NUMERIC(14, 2), -- estimated monthly INR loss (lower bound)
    revenue_loss_high   NUMERIC(14, 2), -- estimated monthly INR loss (upper bound)
    campaign_preview    JSONB           NOT NULL DEFAULT '{}',
    created_at          TIMESTAMPTZ     NOT NULL DEFAULT NOW()
);

-- Indexes
CREATE UNIQUE INDEX IF NOT EXISTS reports_audit_id_idx ON reports (audit_id);
CREATE INDEX IF NOT EXISTS reports_overall_score_idx   ON reports (overall_score);
CREATE INDEX IF NOT EXISTS reports_created_at_idx      ON reports (created_at DESC);

-- GIN index for JSONB queries (e.g. filter by dimension score)
CREATE INDEX IF NOT EXISTS reports_dimensions_gin      ON reports USING GIN (dimensions);
CREATE INDEX IF NOT EXISTS reports_campaign_gin        ON reports USING GIN (campaign_preview);


-- ===========================================================================
--  ROW LEVEL SECURITY
--  The FastAPI backend uses the service_role key, which bypasses RLS.
--  RLS is enabled so the anon/public key (used by any frontend client)
--  cannot read or write audit data directly — all access goes through the API.
-- ===========================================================================
ALTER TABLE audits  ENABLE ROW LEVEL SECURITY;
ALTER TABLE reports ENABLE ROW LEVEL SECURITY;

-- No anon policies → anon key gets zero access (RLS blocks by default).
-- service_role bypasses RLS automatically — no policy needed for the backend.

-- ---------------------------------------------------------------------------
--  Future user-auth policies (uncomment when you add Supabase Auth)
-- ---------------------------------------------------------------------------
-- Assumption: audits will get a `user_id UUID REFERENCES auth.users(id)` column.

-- CREATE POLICY "users_own_audits" ON audits
--     FOR ALL
--     TO authenticated
--     USING  (auth.uid() = user_id)
--     WITH CHECK (auth.uid() = user_id);

-- CREATE POLICY "users_own_reports" ON reports
--     FOR SELECT
--     TO authenticated
--     USING (
--         EXISTS (
--             SELECT 1 FROM audits
--             WHERE audits.id = reports.audit_id
--               AND audits.user_id = auth.uid()
--         )
--     );


-- ===========================================================================
--  HELPER VIEW  —  audits joined with their report (for dashboards)
-- ===========================================================================
CREATE OR REPLACE VIEW audit_summary AS
SELECT
    a.id                    AS audit_id,
    a.business_name,
    a.city,
    a.category,
    a.monthly_ad_spend,
    a.status,
    a.created_at,
    a.completed_at,
    r.overall_score,
    r.revenue_loss_low,
    r.revenue_loss_high,
    r.dimensions            -> 'web_performance'  ->> 'label'  AS web_label,
    r.dimensions            -> 'local_seo'        ->> 'label'  AS seo_label,
    r.dimensions            -> 'social_presence'  ->> 'label'  AS social_label,
    r.dimensions            -> 'website_quality'  ->> 'label'  AS website_label
FROM  audits  a
LEFT JOIN reports r ON r.audit_id = a.id;


-- ===========================================================================
--  QUICK SMOKE-TEST  —  run after applying schema to verify everything is set
-- ===========================================================================
DO $$
DECLARE
    v_audit_id  UUID;
    v_report_id UUID;
BEGIN
    -- insert test audit
    INSERT INTO audits (business_name, city, category, website_url,
                        instagram_handle, monthly_ad_spend, status)
    VALUES ('Test MSME', 'Mumbai', 'retail',
            'https://example.com', 'testhandle', 10000, 'completed')
    RETURNING id INTO v_audit_id;

    -- insert test report
    INSERT INTO reports (audit_id, overall_score, dimensions,
                         revenue_loss_low, revenue_loss_high, campaign_preview)
    VALUES (
        v_audit_id,
        58,
        '{
            "web_performance": {"score": 62, "label": "Good",     "summary": "OK", "recommendations": []},
            "local_seo":       {"score": 40, "label": "Needs Work","summary": "OK", "recommendations": []},
            "social_presence": {"score": 55, "label": "Needs Work","summary": "OK", "recommendations": []},
            "website_quality": {"score": 75, "label": "Good",     "summary": "OK", "recommendations": []}
        }'::JSONB,
        25000, 75000,
        '{"channel":"Google Ads","monthly_budget_inr":5000,"expected_leads":15}'::JSONB
    )
    RETURNING id INTO v_report_id;

    -- verify view
    ASSERT (SELECT overall_score FROM audit_summary WHERE audit_id = v_audit_id) = 58,
           'audit_summary view broken';

    -- clean up
    DELETE FROM audits WHERE id = v_audit_id;

    RAISE NOTICE 'Schema smoke-test PASSED.';
END $$;
