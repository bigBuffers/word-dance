-- 0021_memory_cards.sql — 记忆图卡 (docs/MEMORY_CARDS_DESIGN.md §3.4): user_settings.image_word, the learner's 「图片上显示单词」 switch
-- (API.md 15 and §9 `Settings.image_word`), and word_images.hook_zh / note_zh, the two captions a memory card brings with it (API.md §9
-- `ImageMeta.hook_zh` / `note_zh`; written only by wd.images.store.activate_memo, i.e. `wd images-import`).
--
-- Additive only, the 0012_word_images_meta.sql / 0015_dance_mode.sql precedent: THREE ADD COLUMNs — one NOT NULL flag with its default
-- and CHECK, two nullable TEXTs — no table rebuild, no index (user_settings is read by primary key once per request, word_images by
-- words.active_image_id), no data step. v_bank names its columns explicitly (0011) and no view, trigger or real foreign key reads
-- either table's other columns, so the file is safe under `deploy/install.sh --no-restart` and a plain `launchctl kickstart -k` on the
-- Mac; existing settings rows get image_word = 1 (the word stays on the picture — nothing changes for anyone until they switch it off)
-- and every existing image keeps hook_zh / note_zh NULL. A memory card is recognised by provider = 'claude_svg' AND prompt_version LIKE
-- 'memo-%' (wd.images.memo.is_memo) — no column of its own here. The limits (hook_zh ≤ 60 characters, note_zh ≤ 60) are the
-- importer's: checked before anything is stored, never truncated. The runner wraps this file in BEGIN IMMEDIATE and records
-- schema_migrations(21, 'memory_cards') itself (SCHEMA.sql §1) — nothing else belongs here. docs/SCHEMA.sql stays the 0001 baseline
-- byte for byte (test_db.py). Rollback = `git checkout` alone: the old code never reads the columns (its INSERTs name their columns)
-- and the DDL default keeps image_word valid; the pictures themselves are rolled back with `wd images-import --undo`.
ALTER TABLE user_settings ADD COLUMN image_word INTEGER NOT NULL DEFAULT 1 CHECK (image_word IN (0,1));
ALTER TABLE word_images ADD COLUMN hook_zh TEXT;
ALTER TABLE word_images ADD COLUMN note_zh TEXT;
