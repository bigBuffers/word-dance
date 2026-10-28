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

# make seed: the inputs (ECDICT stardict.db, mahavivo word lists) are NOT needed
# at deploy time — data/seed/vocab.jsonl.gz is tracked. Set them only to rebuild.
ECDICT_DB     ?=
WORDLISTS_DIR ?=

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

seed: ## Rebuild data/seed from ECDICT + syllabus lists: make seed ECDICT_DB=<stardict.db> WORDLISTS_DIR=<dir>
	@test -f "$(ECDICT_DB)" || { echo "make: set ECDICT_DB=<path to ECDICT stardict.db> (deploy/fetch_ecdict.sh downloads it)" >&2; exit 2; }
	@test -d "$(WORDLISTS_DIR)" || { echo "make: set WORDLISTS_DIR=<directory holding the mahavivo english-wordlists .txt files>" >&2; exit 2; }
	$(PYTHON) -I scripts/build_seed.py --db "$(ECDICT_DB)" --lists "$(WORDLISTS_DIR)" --out data/seed
	gzip -9 -n -k -f data/seed/vocab.jsonl
	@echo "data/seed/vocab.jsonl.gz: $$(zcat data/seed/vocab.jsonl.gz | wc -l) records"

install: ## Install or upgrade the systemd service on this box (deploy/install.sh; INSTALL_ARGS="--with-caddy DOMAIN" etc.)
	deploy/install.sh $(INSTALL_ARGS)

backup: ## Snapshot the live database with retention (wd backup --keep-daily 14 --keep-weekly 8)
	$(call need,$(WD),run 'make setup' first)
	$(WD) backup $(BACKUP_ARGS)

clean: ## Remove build outputs and caches inside the checkout (never the data directory)
	rm -rf frontend/dist .pytest_cache backend/.pytest_cache backend/build backend/*.egg-info .coverage htmlcov
	find backend -type d -name __pycache__ -prune -exec rm -rf {} +
