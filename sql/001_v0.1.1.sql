-- sql/001_v0.1.1.sql
-- ReputonBot schema freeze for v0.1.1
-- NOTE: This migration only FIXES the current schema (no structural changes beyond what's already in use).

BEGIN;

-- 0) Safe extensions (idempotent)
CREATE EXTENSION IF NOT EXISTS "uuid-ossp";
CREATE EXTENSION IF NOT EXISTS pgcrypto;

-- 1) Schema versioning
CREATE TABLE IF NOT EXISTS schema_version (
    version TEXT PRIMARY KEY,
    applied_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
COMMENT ON TABLE schema_version IS 'Migration history for ReputonBot DB schema.';
COMMENT ON COLUMN schema_version.version IS 'Semantic/ordered version label, e.g., 001_v0.1.1';

-- record current schema version
INSERT INTO schema_version(version) 
VALUES ('001_v0.1.1') 
ON CONFLICT (version) DO NOTHING;

-- 2) Platform rules
CREATE TABLE IF NOT EXISTS platform_rules (
    platform      TEXT PRIMARY KEY,                 -- 'ozon', 'wb', 'yandex_maps', ...
    name          TEXT,
    report_url    TEXT,
    rules_json    JSONB,                            -- normative rules of the platform
    system_prompt TEXT,                             -- system prompt for LLM
    updated_at    TIMESTAMPTZ NOT NULL DEFAULT now()
);
COMMENT ON TABLE platform_rules IS 'Rules/prompts/links per platform.';
COMMENT ON COLUMN platform_rules.rules_json IS 'JSON rules and constraints per platform.';

-- 3) Interactions (history of generations, idempotency by request_id)
CREATE TABLE IF NOT EXISTS interactions (
    id            BIGSERIAL PRIMARY KEY,
    request_id    TEXT UNIQUE,                      -- idempotency key (from X-Request-ID), may be NULL for legacy rows
    telegram_id   BIGINT,                           -- == chat_id
    platform      TEXT,
    input_text    TEXT,
    output_text   TEXT,                             -- generated complaint/answer/instructions
    intent        TEXT,                             -- optional intent label
    meta_json     JSONB NOT NULL DEFAULT '{}'::jsonb,
    created_at    TIMESTAMPTZ NOT NULL DEFAULT now()
);
COMMENT ON TABLE interactions IS 'Full journal of generations for analytics and debugging.';
COMMENT ON COLUMN interactions.request_id IS 'Ensures repeatable results for the same request.';
COMMENT ON COLUMN interactions.meta_json IS 'Aux telemetry: timings, model, version, etc.';

CREATE INDEX IF NOT EXISTS interactions_by_user_time
    ON interactions (telegram_id, created_at DESC);

-- 4) Chat state (last selected platform)
CREATE TABLE IF NOT EXISTS chat_state (
    chat_id     BIGINT PRIMARY KEY,
    platform    TEXT NOT NULL,
    updated_at  TIMESTAMPTZ NOT NULL DEFAULT now()
);
COMMENT ON TABLE chat_state IS 'Current platform selection per chat.';

-- 5) Rate limits (anti-spam per UTC day)
CREATE TABLE IF NOT EXISTS rate_limits (
    chat_id     BIGINT       NOT NULL,
    utc_day     DATE         NOT NULL DEFAULT (CURRENT_DATE),
    hits        INTEGER      NOT NULL DEFAULT 0,    -- total requests today
    threshold   INTEGER      NOT NULL DEFAULT 10,   -- daily threshold (may be tuned per tier)
    updated_at  TIMESTAMPTZ  NOT NULL DEFAULT now(),
    PRIMARY KEY (chat_id, utc_day)
);
COMMENT ON TABLE rate_limits IS 'Simple per-day request accounting.';
COMMENT ON COLUMN rate_limits.threshold IS 'Daily cap used by backend limiter.';

CREATE INDEX IF NOT EXISTS rate_limits_updated_at_idx
    ON rate_limits (updated_at DESC);

-- 6) Request cache (content-based)
CREATE TABLE IF NOT EXISTS request_cache (
    chat_id     BIGINT      NOT NULL,
    text_hash   TEXT        NOT NULL,               -- sha256(normalized_text + platform)
    platform    TEXT,
    result_json JSONB,                              -- cached LLM/pipeline result
    created_at  TIMESTAMPTZ NOT NULL DEFAULT now(),
    expires_at  TIMESTAMPTZ,
    PRIMARY KEY (chat_id, text_hash)
);
COMMENT ON TABLE request_cache IS 'Content-based cache for repeated requests.';

CREATE INDEX IF NOT EXISTS request_cache_expires_idx
    ON request_cache (expires_at);

COMMIT;
