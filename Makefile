# word-Dance — developer and operator entry points (docs/DEPLOY.md §8).
#
# Run from the repository root. The Python virtualenv lives at ./.venv (created
# by `make setup`); the frontend is a plain npm project under ./frontend.
# Runtime state (database, images, .env, backups) never lives in this checkout:
# it is WD_DATA_DIR (default /home/sqin/word-dance-data, docs/DEPLOY.md §1).
# The one exception is `make dev`, which uses the gitignored ./.dev-data.

SHELL := /bin/bash
.SHELLFLAGS := -eu -o pipefail -c
.DEFAULT_GOAL := help
.DELETE_ON_ERROR:
MAKEFLAGS += --no-builtin-rules --no-print-directory

PYTHON  ?= python3
NPM     ?= npm
VENV    ?= .venv
PY      := $(VENV)/bin/python
PIP     := $(VENV)/bin/pip
PT      := $(VENV)/bin/pytest
WD      := $(VENV)/bin/wd
UVICORN := $(VENV)/bin/uvicorn

# `wd` is importable through PYTHONPATH as well as through the editable install,
# so tests and the dev server work right after `make setup` on a fresh clone and
# even when the editable install was skipped. An existing PYTHONPATH is kept.
PYENV := PYTHONPATH=$(CURDIR)/backend$${PYTHONPATH:+:$$PYTHONPATH}

# make dev (docs/DEPLOY.md §8): throwaway data dir, open registration and the
# fake claude from the test suite. WD_DEV_REAL_CLAUDE=1 leaves WD_CLAUDE_BIN
# unset so the real, authenticated CLI is used instead (spends money).
DEV_DATA_DIR ?= $(CURDIR)/.dev-data
DEV_PORT     ?= 8000
FAKE_CLAUDE  := $(CURDIR)/backend/tests/fake_claude.py
DEV_CLAUDE   := $(if $(filter 1,$(WD_DEV_REAL_CLAUDE)),,WD_CLAUDE_BIN=$(FAKE_CLAUDE))

# make seed: the official lists (data/lists/) and the last committed seed are the
# only required inputs — data/seed/vocab.jsonl.gz is tracked, nothing is needed
# at deploy time. ECDICT_DB (stardict.db) is needed only when the lists bring
# headwords the committed seed lacks; WORDLISTS_DIR (the optional mahavivo CET
# lists) may be absent, existing rows then keep their CET flags (PLAN §4.5).
# SEED_BASE is the git revision whose data/seed/vocab.jsonl.gz is the baseline of
# BOTH the build (--previous) and DIFF.md (PLAN §4.5: the diff is against
# `git show HEAD:data/seed/vocab.jsonl.gz`). The working-tree archive is never the
# baseline: pack_seed.sh replaces it, so a second run would relabel its own output
# and stats.json (previous_sha256, new_words, rows_changed_vs_previous) would
# describe nothing (impl-review S3b F1). With the committed seed as the baseline
# `make seed` is idempotent: two runs give byte-identical vocab.jsonl.gz,
# stats.json and DIFF.md.
ECDICT_DB     ?=
WORDLISTS_DIR ?=
SEED_BASE     ?= HEAD

# Retention passed to `wd backup` (docs/DEPLOY.md §5).
BACKUP_ARGS  ?= --keep-daily 14 --keep-weekly 8
# Extra flags for deploy/install.sh, e.g. make install INSTALL_ARGS="--with-caddy words.example.com"
INSTALL_ARGS ?=
# Extra flags for scripts/smoke.py, e.g. make smoke SMOKE_ARGS="--keep --port 8011"
SMOKE_ARGS   ?=

# $(call need,<path>,<hint>) — fail early with a hint instead of bash's "No such file".
define need
@test -x "$(1)" || { echo "make: $(1) not found — $(2)" >&2; exit 2; }
endef

.PHONY: help setup dev build test check check-contract smoke seed install backup clean

help: ## List the available targets
	@awk 'BEGIN {FS = ":.*## "} /^[a-zA-Z_-]+:.*## / {printf "  %-9s %s\n", $$1, $$2}' $(MAKEFILE_LIST)

setup: ## Create .venv, install backend deps + editable `wd`, npm ci for the frontend
	test -x $(PY) || $(PYTHON) -m venv $(VENV)
	$(PIP) install -r backend/requirements.txt -r backend/requirements-dev.txt
	$(PIP) install -e backend
	cd frontend && $(NPM) ci

dev: ## Backend (uvicorn --reload :8000, fake claude, open registration) + Vite dev server (:5173)
	$(call need,$(UVICORN),run 'make setup' first)
	@if [ -x scripts/dev.sh ]; then exec scripts/dev.sh; fi; \
	mkdir -p "$(DEV_DATA_DIR)"; \
	WD_DEV=1 WD_DATA_DIR="$(DEV_DATA_DIR)" WD_REGISTRATION_MODE=open $(DEV_CLAUDE) $(PYENV) \
	  $(UVICORN) wd.main:create_app --factory --reload --port $(DEV_PORT) & UV=$$!; \
	trap 'kill $$UV 2>/dev/null || true' EXIT INT TERM; \
	cd frontend && $(NPM) run dev

build: ## Build the production SPA into frontend/dist (served by the backend)
	cd frontend && $(NPM) run build

test: ## pytest + contract audit + tsc + vitest + vite build
	$(call need,$(PT),run 'make setup' first)
	$(PYENV) $(PT) -q backend/tests
	$(PYENV) $(PY) scripts/check_contract.py -q
	cd frontend && $(NPM) run typecheck && $(NPM) test && $(NPM) run build

check: test ## Alias of `make test`

check-contract: ## schemas.py ↔ types.ts field-by-field audit (scripts/check_contract.py)
	$(call need,$(PY),run 'make setup' first)
	$(PYENV) $(PY) scripts/check_contract.py

smoke: ## End-to-end smoke run against a throwaway instance with the fake claude (scripts/smoke.py: temp data dir, port 8010, mocked providers)
	$(call need,$(PY),run 'make setup' first)
	$(PYENV) $(PY) scripts/smoke.py $(SMOKE_ARGS)

seed: ## Rebuild data/seed from data/lists + the committed seed: make seed [ECDICT_DB=<stardict.db>] [WORDLISTS_DIR=<mahavivo dir>] [SEED_BASE=<git rev>]
	$(call need,$(PY),run 'make setup' first)
	@if [ -n "$(ECDICT_DB)" ] && [ ! -f "$(ECDICT_DB)" ]; then echo "make: ECDICT_DB=$(ECDICT_DB) does not exist (deploy/fetch_ecdict.sh downloads stardict.db)" >&2; exit 2; fi
	@if [ -n "$(WORDLISTS_DIR)" ] && [ ! -d "$(WORDLISTS_DIR)" ]; then echo "make: WORDLISTS_DIR=$(WORDLISTS_DIR) is not a directory" >&2; exit 2; fi
	set -e; tmp="$$(mktemp -d)"; trap 'rm -rf "$$tmp"' EXIT; prev="$$tmp/vocab.jsonl.gz"; \
	git show "$(SEED_BASE):data/seed/vocab.jsonl.gz" > "$$prev" || { echo "make: cannot read $(SEED_BASE):data/seed/vocab.jsonl.gz from git (SEED_BASE must name a commit that tracks the seed)" >&2; exit 2; }; \
	$(PY) -I scripts/build_seed.py --manifest data/lists/manifest.json --previous "$$prev" \
	    $(if $(ECDICT_DB),--ecdict "$(ECDICT_DB)") $(if $(WORDLISTS_DIR),--wordlists "$(WORDLISTS_DIR)") --out data/seed; \
	$(PY) -I scripts/seed_diff.py "$$prev" data/seed/vocab.jsonl --md data/seed/DIFF.md \
	    --old-label "$(SEED_BASE):data/seed/vocab.jsonl.gz" --new-label data/seed/vocab.jsonl.gz
	scripts/pack_seed.sh

install: ## Install or upgrade the systemd service on this box (deploy/install.sh; INSTALL_ARGS="--with-caddy DOMAIN" etc.)
	deploy/install.sh $(INSTALL_ARGS)

backup: ## Snapshot the live database with retention (wd backup --keep-daily 14 --keep-weekly 8)
	$(call need,$(WD),run 'make setup' first)
	$(WD) backup $(BACKUP_ARGS)

clean: ## Remove build outputs and caches inside the checkout (never the data directory)
	rm -rf frontend/dist .pytest_cache backend/.pytest_cache backend/build backend/*.egg-info .coverage htmlcov
	find backend -type d -name __pycache__ -prune -exec rm -rf {} +

# The 记忆图卡 studio (studio/README.md) is not part of the app and not part of `make test`: its tools need fonttools and
# skia-pathops, which are no dependencies of the app, so they live in their own small virtualenv (gitignored;
# STUDIO_PYTHON picks the interpreter). Like `setup` above, the venv is created when missing and its packages are
# installed on EVERY run: a no-op that needs no network once they are there, and the thing that repairs a venv whose
# first install died half-way — an unreachable index leaves studio/.venv/bin/python behind, so a recipe that installs
# only when the interpreter is missing would skip the install for ever and die with `No module named pytest`.
# The tests validate the tools AND every approved card in studio/cards against the repository's own sanitiser and
# structure check (backend/wd/images/) — run this after touching either side.
STUDIO_PYTHON ?= python3.12
.PHONY: studio-check
studio-check: ## Memory-card studio: studio/.venv (created when missing, its packages installed on every run — a no-op without network once they are there), then studio/tests (tools + every card in studio/cards)
	test -x studio/.venv/bin/python || $(STUDIO_PYTHON) -m venv studio/.venv
	studio/.venv/bin/pip install -q --disable-pip-version-check -r studio/requirements.txt pytest
	studio/.venv/bin/python -m pytest -q -p no:cacheprovider studio/tests
