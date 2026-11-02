-- 0009_strip_phonetic_delimiters.sql — one-off repair of words.phonetic values stored WITH IPA delimiters.
--
-- Until ai/common.clean_phonetic (commit 6ce260d) a Claude `lookup_word` / consolidation answer could be stored verbatim as
-- "/ˌdʒiː diː ˈpiː/" or "[əˈbændən]". The UI (StudyCard, WordRow, WordHeader) adds its own slashes around the value, so such
-- rows rendered as //…// on every card and list. ECDICT seed rows never carry delimiters ("ə'biliti"), so only the handful of
-- Claude-validated words written before that fix match the predicate below. Data-only and idempotent (a second run matches
-- nothing); safe under `deploy/install.sh --no-restart` (DEPLOY §10). The runner wraps the file in BEGIN IMMEDIATE and
-- records schema_migrations(9, 'strip_phonetic_delimiters') itself (SCHEMA.sql §1) — nothing else belongs here.
UPDATE words
   SET phonetic = NULLIF(TRIM(phonetic, '/[] '), '')
 WHERE phonetic IS NOT NULL
   AND (phonetic LIKE '/%' OR phonetic LIKE '%/' OR phonetic LIKE '[%' OR phonetic LIKE '%]');
