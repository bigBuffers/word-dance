-- 0022_assignments.sql — 布置词汇 (docs/releases/2026-11-assignments.md): a guardian (for their children) or the admin picks words a
-- learner must study; the day's batch takes them first (services/batches.select_words) and 磨耳朵 plays them first.
--
-- assignments       one list handed to one learner. mode 'today' = every word goes into the learner's next batch (today's when it
--                   already exists) whatever the daily quota; 'spread' = the words take the daily new-word quota, a few per day.
-- assignment_words  one word of a list. status 'pending' (waiting for a batch) → 'scheduled' (it has its push_items row:
--                   push_item_id / scheduled_date; the grade is read from that row) or 'withdrawn' (taken back before it was
--                   scheduled). A word is in a list once.
--
-- Additive only (the 0015 / 0021 precedent): two CREATE TABLEs and their indexes, no existing table touched, no data step — safe
-- under a plain restart. push_items is NOT changed: an assigned item is a normal 'new' / 'extra' / 'review' row that an
-- assignment_words row points at. ON DELETE: a deleted user takes their lists (both roles) with them, a deleted push item leaves
-- the word 'scheduled' without a grade. Rollback = `git checkout` alone: the old code never reads the tables.
CREATE TABLE assignments (
  id           INTEGER PRIMARY KEY,
  assigner_id  INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
  learner_id   INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
  title        TEXT NOT NULL DEFAULT '',
  mode         TEXT NOT NULL CHECK (mode IN ('today','spread')),
  created_at   TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ','now'))
);
CREATE INDEX ix_assignments_learner  ON assignments(learner_id, id);
CREATE INDEX ix_assignments_assigner ON assignments(assigner_id, id);

CREATE TABLE assignment_words (
  id             INTEGER PRIMARY KEY,
  assignment_id  INTEGER NOT NULL REFERENCES assignments(id) ON DELETE CASCADE,
  word_id        INTEGER NOT NULL REFERENCES words(id) ON DELETE CASCADE,
  position       INTEGER NOT NULL,
  status         TEXT NOT NULL DEFAULT 'pending' CHECK (status IN ('pending','scheduled','withdrawn')),
  push_item_id   INTEGER REFERENCES push_items(id) ON DELETE SET NULL,
  scheduled_date TEXT
);
CREATE UNIQUE INDEX ux_assignment_words_word ON assignment_words(assignment_id, word_id);
CREATE INDEX        ix_assignment_words_item ON assignment_words(push_item_id);
CREATE INDEX        ix_assignment_words_open ON assignment_words(status, assignment_id, position);
