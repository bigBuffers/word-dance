-- 0010_ai_provider.sql — which transport served an `ai_calls` row (docs/AI_FALLBACK_MODEL.md §4, CLAUDE_INTEGRATION §10).
--
-- Until now every row came from the `claude -p` CLI. The fallback provider (ai/providers/openai_http.py) writes the same
-- ledger — reservations, hourly caps, admin views and the eval tooling must be able to tell the two apart — so the row
-- records its provider: 'claude' (the CLI, also every row written before this migration) or 'fallback'. Additive and
-- idempotent in effect (ADD COLUMN with a default rewrites nothing); safe under `deploy/install.sh --no-restart`
-- (DEPLOY §10). The runner wraps the file in BEGIN IMMEDIATE and records schema_migrations(10, 'ai_provider') itself
-- (SCHEMA.sql §1) — nothing else belongs here.
ALTER TABLE ai_calls ADD COLUMN provider TEXT NOT NULL DEFAULT 'claude' CHECK (provider IN ('claude','fallback'));
CREATE INDEX ix_ai_calls_provider_started ON ai_calls(provider, started_at);
