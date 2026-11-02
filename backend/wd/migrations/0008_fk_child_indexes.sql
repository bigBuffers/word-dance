-- 0008_fk_child_indexes.sql — indexes on the foreign-key child columns that receive ON DELETE actions when a user
-- (DELETE /api/account, DESIGN §10) or an orphaned private word (routers/account.py) is deleted.
--
-- Without them SQLite scans push_items / bank_suggestions in full once per deleted user_words row inside the
-- account-deletion BEGIN IMMEDIATE: measured 5.2 s on a five-user, one-year database (73,000 push_items), during which
-- every other writer waits on busy_timeout; with the indexes the same delete takes 0.07 s.
--
-- Purely additive (safe under `deploy/install.sh --no-restart`, DEPLOY §10). Numbers 0002–0007 were pre-allocated to
-- the work packages and left unused (TASKS.md). The runner wraps this file in BEGIN IMMEDIATE and records
-- schema_migrations(8, 'fk_child_indexes') itself (SCHEMA.sql §1) — nothing else belongs here.
CREATE INDEX IF NOT EXISTS ix_push_items_user_word       ON push_items(user_word_id);        -- ON DELETE SET NULL from user_words
CREATE INDEX IF NOT EXISTS ix_push_items_word            ON push_items(word_id);             -- ON DELETE CASCADE from words
CREATE INDEX IF NOT EXISTS ix_bank_suggestions_user_word ON bank_suggestions(user_word_id);  -- ON DELETE CASCADE from user_words
