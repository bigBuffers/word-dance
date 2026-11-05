#!/usr/bin/env python3
"""Entry point of the seed diff — ``make seed`` runs it between the build and ``pack_seed.sh`` (PLAN §4.8).

    .venv/bin/python -I scripts/seed_diff.py OLD.jsonl[.gz] NEW.jsonl[.gz] [--md PATH] [--json PATH] [--stats PATH] \
        [--only stages|fields|added|removed] [--no-invariants] [--old-label TEXT] [--new-label TEXT]

Writes the Markdown report (``data/seed/DIFF.md``) and exits 1 when an invariant fails (new lemma set ⊇ old, xs ⊆ zk,
stage codes known and ordered, ``stats.json`` counts match); ``--no-invariants`` only reports. ``make seed`` passes OLD as
a temporary copy of ``git show $(SEED_BASE):data/seed/vocab.jsonl.gz`` and labels it ``HEAD:data/seed/vocab.jsonl.gz``
(``--old-label``) so the header never names the temporary file. Implementation: ``backend/wd/seedbuild/diff.py``.
"""
from wd.seedbuild.diff import main

raise SystemExit(main())
