-- 0013_word_forms_alias.sql — allow seed-provided spelling aliases in word_forms (kind 'alias').
--
-- The official word lists spell some headwords differently from the dictionary lemma (Mr → mr., PE → p.e.,
-- hot-dog → hot dog; data/lists/aliases.tsv). The seed import writes those spellings as word_forms rows with
-- kind 'alias' so that lookup/search resolve them to the headword before falling back to ECDICT, whose
-- undotted entries mean something else (Mr = a memory-reclaim program). 'alt' keeps its meaning (rows written
-- by lookup_word merges / the suffix rule, never touched by the import; DESIGN §3.1). SQLite cannot ALTER a
-- CHECK list, so the table is rebuilt (14k rows, WITHOUT ROWID, milliseconds). No view references word_forms;
-- the only index is re-created below. The runner wraps this file in BEGIN IMMEDIATE with foreign_keys=OFF and
-- records schema_migrations(13, 'word_forms_alias') itself (SCHEMA.sql §1) — nothing else belongs here.
-- docs/SCHEMA.sql stays the 0001 baseline byte-for-byte (test_db.py).
CREATE TABLE word_forms_new (
  form     TEXT NOT NULL,                               -- normalised like words.lemma
  word_id  INTEGER NOT NULL REFERENCES words(id) ON DELETE CASCADE,
  kind     TEXT NOT NULL CHECK (kind IN ('p','d','i','3','s','r','t','alt','alias')),  -- ECDICT codes; 'alt' = Claude/suffix rule; 'alias' = seed spelling alias (data/lists/aliases.tsv)
  PRIMARY KEY (form, word_id)
) WITHOUT ROWID;
INSERT INTO word_forms_new(form, word_id, kind) SELECT form, word_id, kind FROM word_forms;
DROP TABLE word_forms;
ALTER TABLE word_forms_new RENAME TO word_forms;
CREATE INDEX ix_word_forms_word ON word_forms(word_id);
