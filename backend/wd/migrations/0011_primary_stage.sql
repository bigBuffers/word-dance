-- 0011_primary_stage.sql — add the 小学 stage (code `xs`), renumber the stage index 1..5 and move the new-user default to K-12.
--
-- Why a rebuild: SQLite cannot ALTER a CHECK list or a column DEFAULT, so `words` (stage_min BETWEEN 1 AND 4) and
-- `user_settings` (current_stage BETWEEN 1 AND 4, DEFAULT 3, stages_json DEFAULT '["cet4","cet6"]') are re-created with
-- SQLite's 12-step recipe (CREATE new → INSERT … SELECT → DROP old → RENAME → indexes → views). The runner wraps this file
-- in BEGIN IMMEDIATE with foreign_keys=OFF and runs foreign_key_check before recording schema_migrations(11, 'primary_stage')
-- itself (SCHEMA.sql §1); nothing here toggles PRAGMAs or commits. Stop-first migration (DEPLOY §10: never under --no-restart).
--
-- Index renumbering (DESIGN §0.3 / API.md §9.1): old 1=zk 2=gk 3=cet4 4=cet6 → new 1=xs 2=zk 3=gk 4=cet4 5=cet6, so every stored
-- stage_min / current_stage moves +1 (NULL stays NULL). stages_json holds stage CODES and is copied as is; nobody is enrolled
-- in xs automatically (live rows: user 1 → current_stage 4 = cet4, user 2 → 2 = zk). The seed re-import that follows
-- (kv.seed_version is cleared below so the next `wd import-seed` / `wd serve` start imports unconditionally) recomputes
-- stage_xs/stage_zk/stage_gk/stage_min for every seed word from the official lists; the +1 here only keeps the database
-- self-consistent in between and for non-seed rows. push_batches.settings_json snapshots written before this migration keep
-- the OLD integer in "current_stage" (write-only column, batches.py; the "stages" codes next to it are unambiguous).
--
-- The view v_bank references words: it must be dropped before the DROP TABLE/RENAME and re-created afterwards (with
-- legacy_alter_table=OFF the RENAME otherwise fails with "error in view v_bank: no such table: main.words"). docs/SCHEMA.sql
-- stays the 0001 baseline byte for byte (test_db.py); the current DDL of words/user_settings is THIS file (DESIGN §3.1).

-- ---------------------------------------------------------------------------
-- 1. words: + stage_xs, stage_min 1..5 (renumbered)
-- ---------------------------------------------------------------------------
DROP VIEW v_bank;

CREATE TABLE words_new (
  id                  INTEGER PRIMARY KEY,
  lemma               TEXT NOT NULL,                    -- normalised key: NFKC, lower-case, single spaces, ASCII ' - .
  display             TEXT NOT NULL,                    -- display form, keeps casing ('China', 'NASA', 'a.m.', 'ice cream')
  kind                TEXT NOT NULL DEFAULT 'word' CHECK (kind IN ('word','phrase','abbreviation','proper_noun')),
  phonetic            TEXT,                             -- 'ə'bændən' (seed: ә→ə, :→ː normalised)
  translation         TEXT,                             -- zh lines joined by '\n' (seed translation[])
  definition          TEXT,                             -- en lines joined by '\n' (seed definition[])
  pos                 TEXT,                             -- ECDICT pos distribution 'n:4/v:96'
  collins             INTEGER,                          -- 0–5
  oxford              INTEGER,                          -- 0/1 (Oxford 3000)
  exam_tags           TEXT,                             -- 'ky toefl ielts gre' (space-joined seed exam_tags[])
  bnc                 INTEGER,                          -- BNC rank; 0/NULL = unknown
  frq                 INTEGER,                          -- COCA-ish rank; 0/NULL = unknown (sorted last)
  exchange_json       TEXT,                             -- seed exchange{} as JSON object ({"p":"went","d":"gone",…})
  stage_xs            INTEGER NOT NULL DEFAULT 0 CHECK (stage_xs   IN (0,1)),  -- 小学 (义务教育课标 2022 二级词汇表 + 附表数词/月份/星期)
  stage_zk            INTEGER NOT NULL DEFAULT 0 CHECK (stage_zk   IN (0,1)),  -- 初中 (课标 2022 三级 1600 ∪ 上海市教育考试院 2020 初中词汇表; ⊇ xs)
  stage_gk            INTEGER NOT NULL DEFAULT 0 CHECK (stage_gk   IN (0,1)),  -- 高中 (普通高中课标 2017 年版 2025 年修订 3100 ∪ 2020 年修订 3000)
  stage_cet4          INTEGER NOT NULL DEFAULT 0 CHECK (stage_cet4 IN (0,1)),  -- 四级
  stage_cet6          INTEGER NOT NULL DEFAULT 0 CHECK (stage_cet6 IN (0,1)),  -- 六级 (cumulative: includes most CET-4)
  stage_min           INTEGER CHECK (stage_min BETWEEN 1 AND 5),  -- lowest stage 1=xs 2=zk 3=gk 4=cet4 5=cet6; NULL = outside the 5 lists.
                                                                  -- 仅本阶段新增 filter == stage_min = <stage index>
  cet6_star           INTEGER NOT NULL DEFAULT 0 CHECK (cet6_star IN (0,1)),   -- starred CET-6 word
  sources             TEXT,                             -- provenance tokens (data/seed/ATTRIBUTION.md), e.g. 'cet4 cet46 ecdict moe22:l2 moe22:l3 shmeea20'
  ecdict_id           INTEGER,                          -- stardict.id
  source              TEXT NOT NULL CHECK (source IN ('seed','ecdict','claude','user')),  -- where dictionary fields came from
  is_public           INTEGER NOT NULL DEFAULT 1 CHECK (is_public IN (0,1)),   -- 0 = unvalidated/unsafe user word (visibility rule: API.md §1, DESIGN §5.2)
  is_valid_english    INTEGER CHECK (is_valid_english IN (0,1)),  -- NULL = not yet checked; set by lookup_word / seed import
  safe_for_sharing    INTEGER CHECK (safe_for_sharing IN (0,1)),  -- NULL = not yet checked; Claude verdict (no personal names etc.)
  difficulty          INTEGER CHECK (difficulty BETWEEN 1 AND 5), -- Claude scale, unchanged: 1 初中 … 4 六级, 5 beyond (= stage index − 1; vocab sort uses difficulty + 1)
  merged_into_word_id INTEGER REFERENCES words(id) ON DELETE SET NULL,  -- consolidation merged this row into another
  created_by_user_id  INTEGER REFERENCES users(id) ON DELETE SET NULL,
  active_content_id   INTEGER,                          -- logical FK → word_contents.id (no constraint: avoids a cycle)
  active_image_id     INTEGER,                          -- logical FK → word_images.id (NULL ⇒ template card is served)
  content_state       TEXT NOT NULL DEFAULT 'none' CHECK (content_state IN ('none','queued','ready','failed')),
  image_state         TEXT NOT NULL DEFAULT 'none' CHECK (image_state  IN ('none','queued','ready','failed')),
  created_at          TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ','now')),
  updated_at          TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ','now'))
);

INSERT INTO words_new (id, lemma, display, kind, phonetic, translation, definition, pos, collins, oxford, exam_tags, bnc, frq, exchange_json,
                       stage_xs, stage_zk, stage_gk, stage_cet4, stage_cet6, stage_min, cet6_star, sources, ecdict_id, source,
                       is_public, is_valid_english, safe_for_sharing, difficulty, merged_into_word_id, created_by_user_id,
                       active_content_id, active_image_id, content_state, image_state, created_at, updated_at)
SELECT id, lemma, display, kind, phonetic, translation, definition, pos, collins, oxford, exam_tags, bnc, frq, exchange_json,
       0, stage_zk, stage_gk, stage_cet4, stage_cet6, stage_min + 1, cet6_star, sources, ecdict_id, source,
       is_public, is_valid_english, safe_for_sharing, difficulty, merged_into_word_id, created_by_user_id,
       active_content_id, active_image_id, content_state, image_state, created_at, updated_at
FROM words;

DROP TABLE words;
ALTER TABLE words_new RENAME TO words;

CREATE UNIQUE INDEX ux_words_lemma      ON words(lemma);
CREATE INDEX        ix_words_frq        ON words(frq);
CREATE INDEX        ix_words_stage_min  ON words(stage_min, frq);
CREATE INDEX        ix_words_content    ON words(content_state);
CREATE INDEX        ix_words_created_by ON words(created_by_user_id) WHERE created_by_user_id IS NOT NULL;
CREATE INDEX        ix_words_public     ON words(is_public, is_valid_english);

CREATE VIEW v_bank AS
SELECT uw.*, w.lemma, w.display, w.kind, w.phonetic, w.translation, w.stage_min, w.content_state, w.image_state,
       w.is_public, w.is_valid_english
FROM user_words uw JOIN words w ON w.id = uw.word_id
WHERE uw.state IN ('new','learning');

-- ---------------------------------------------------------------------------
-- 2. user_settings: current_stage 1..5 (renumbered), K-12 defaults for new rows
-- ---------------------------------------------------------------------------
CREATE TABLE user_settings_new (
  user_id            INTEGER PRIMARY KEY REFERENCES users(id) ON DELETE CASCADE,
  timezone           TEXT    NOT NULL DEFAULT 'Asia/Shanghai',
  push_time          TEXT    NOT NULL DEFAULT '08:00' CHECK (push_time GLOB '[01][0-9]:[0-5][0-9]' OR push_time GLOB '2[0-3]:[0-5][0-9]'),
  push_enabled       INTEGER NOT NULL DEFAULT 1  CHECK (push_enabled IN (0,1)),
  daily_new_count    INTEGER NOT NULL DEFAULT 10 CHECK (daily_new_count BETWEEN 0 AND 50),
  daily_screen_count INTEGER NOT NULL DEFAULT 15 CHECK (daily_screen_count BETWEEN 0 AND 50),
  max_reviews        INTEGER NOT NULL DEFAULT 60 CHECK (max_reviews BETWEEN 0 AND 300),
  stages_json        TEXT    NOT NULL DEFAULT '["xs","zk"]',  -- 目标阶段: non-empty subset of xs/zk/gk/cet4/cet6 (set by onboarding); K-12 default, mirrored by services/bank.DEFAULT_STAGES (tested)
  current_stage      INTEGER NOT NULL DEFAULT 1  CHECK (current_stage BETWEEN 1 AND 5),  -- 主攻阶段 1=xs 2=zk 3=gk 4=cet4 5=cet6; Stage string on the wire (API.md §9.1); mirrored by bank.DEFAULT_CURRENT_STAGE
  show_images        INTEGER NOT NULL DEFAULT 1  CHECK (show_images IN (0,1)),
  zh_examples        TEXT    NOT NULL DEFAULT 'tap' CHECK (zh_examples IN ('tap','always')),
  auto_pronounce     INTEGER NOT NULL DEFAULT 1  CHECK (auto_pronounce IN (0,1)),
  accent             TEXT    NOT NULL DEFAULT 'en-US' CHECK (accent IN ('en-US','en-GB')),
  email_enabled      INTEGER NOT NULL DEFAULT 0  CHECK (email_enabled IN (0,1)),
  webhook_enabled    INTEGER NOT NULL DEFAULT 0  CHECK (webhook_enabled IN (0,1)),
  webhook_url        TEXT,
  webhook_format     TEXT    NOT NULL DEFAULT 'generic' CHECK (webhook_format IN ('generic','wecom','feishu','serverchan','bark')),
  next_push_at       TEXT,
  updated_at         TEXT    NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ','now'))
);

INSERT INTO user_settings_new (user_id, timezone, push_time, push_enabled, daily_new_count, daily_screen_count, max_reviews, stages_json,
                               current_stage, show_images, zh_examples, auto_pronounce, accent, email_enabled, webhook_enabled,
                               webhook_url, webhook_format, next_push_at, updated_at)
SELECT user_id, timezone, push_time, push_enabled, daily_new_count, daily_screen_count, max_reviews, stages_json,
       current_stage + 1, show_images, zh_examples, auto_pronounce, accent, email_enabled, webhook_enabled,
       webhook_url, webhook_format, next_push_at, updated_at
FROM user_settings;

DROP TABLE user_settings;
ALTER TABLE user_settings_new RENAME TO user_settings;
CREATE INDEX ix_user_settings_next_push ON user_settings(next_push_at);

-- ---------------------------------------------------------------------------
-- 3. Force the seed re-import on the next start and leave an operator-visible trace
-- ---------------------------------------------------------------------------
DELETE FROM kv WHERE key = 'seed_version';
INSERT INTO system_events(kind, detail_json, created_at)
VALUES ('migration', '{"version": 11, "name": "primary_stage", "stages": "xs/zk/gk/cet4/cet6", "index": "1..5", "note": "stage_min and current_stage renumbered +1; stage flags re-derived from the seed at the next import"}',
        strftime('%Y-%m-%dT%H:%M:%SZ','now'));
