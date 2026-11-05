-- 0012_word_images_meta.sql — word_images gains prompt_version / model / text_free / eval_json
-- (docs/analysis/2026-11-05-stages-regions-images/design/PLAN.md §2.3).
--
-- Additive only: four ADD COLUMN statements, the 0010_ai_provider.sql precedent (ALTER TABLE … ADD COLUMN … NOT NULL DEFAULT …
-- CHECK). Existing rows keep their meaning: the 30 Claude SVGs drawn before this migration printed the headword (svg_system v1),
-- so text_free stays 0 for them; prompt_version / model stay NULL (photos never get a prompt_version). No view, trigger or real
-- foreign key references word_images (v_bank joins user_words/words only; words.active_image_id and content_reports.image_id are
-- logical), nothing is rebuilt, so the file is safe under `deploy/install.sh --no-restart` (DEPLOY §10). The runner wraps the
-- file in BEGIN IMMEDIATE and records schema_migrations(12, 'word_images_meta') itself (SCHEMA.sql §1) — nothing else belongs
-- here. Numbered 0012 because 0011 is the stage-model rebuild; db.list_migration_files does not require consecutive numbers and
-- pending_migrations applies every file not yet in schema_migrations, so the files may land in either order.
ALTER TABLE word_images ADD COLUMN prompt_version TEXT;                                             -- 'svg-v2' | 'ai-v1' | NULL (photos, pre-0012 SVGs)
ALTER TABLE word_images ADD COLUMN model TEXT;                                                      -- generator model id (ai_calls.model_used or the vendor model); NULL for photos
ALTER TABLE word_images ADD COLUMN text_free INTEGER NOT NULL DEFAULT 0 CHECK (text_free IN (0,1));  -- 1 = code-guaranteed text-free file (<text>/<tspan> stripped): the only gate for any picture-first mode
ALTER TABLE word_images ADD COLUMN eval_json TEXT;                                                  -- pilot / VLM rubric scores; never overwrites `score`
