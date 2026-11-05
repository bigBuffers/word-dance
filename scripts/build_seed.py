#!/usr/bin/env python3
"""Entry point of the seed builder — ``make seed`` (PLAN §4.5).

    .venv/bin/python -I scripts/build_seed.py --manifest data/lists/manifest.json --previous data/seed/vocab.jsonl.gz \
        [--ecdict PATH] [--wordlists DIR] --out data/seed [--no-strict] [--built-at ISO]

The implementation lives in ``backend/wd/seedbuild/build.py`` (importable under ``-I`` because ``wd`` is the venv's
editable install); this file only forwards ``argv`` so the package can be unit-tested while the script stays a one-liner.
Exit codes: 0 built, 2 manifest / build failure (nothing written). ``make seed`` passes the COMMITTED seed
(``git show $(SEED_BASE):data/seed/vocab.jsonl.gz``, default HEAD) as ``--previous`` — never the working-tree archive,
which ``pack_seed.sh`` replaces on the first run (Makefile comment; impl-review S3b F1).
"""
from wd.seedbuild.build import main

raise SystemExit(main())
