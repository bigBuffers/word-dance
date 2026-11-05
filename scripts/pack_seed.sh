#!/usr/bin/env bash
# scripts/pack_seed.sh — pack data/seed/vocab.jsonl into the tracked, reproducible data/seed/vocab.jsonl.gz (WP1, PLAN §4.5).
#
#   scripts/pack_seed.sh [--check] [SEED_DIR]
#
# * gzip -9 -n: no file name / mtime in the archive, so identical input gives a byte-identical .gz. The server stores the
#   sha256 of the DECOMPRESSED content as kv.seed_version (PLAN R-9), the same value the builder writes to
#   stats.json.content_sha256 — a re-pack by another gzip never looks like a new seed.
# * checks before the old .gz is replaced: record count == stats.json total_words, sha256 of vocab.jsonl ==
#   stats.json content_sha256 (when the key exists — format v2), and a round trip (gzip -dc | cmp).
# * --check: verify only — counts, content sha256 of the archive and the round trip when vocab.jsonl is present; writes
#   nothing; exit 1 on any mismatch.
# * portable to BSD/macOS: gzip -dc (not zcat, which appends .Z on macOS), shasum -a 256 when sha256sum is absent, wc -c
#   for the size (no stat -c).
#
# Rebuilding vocab.jsonl itself: `make seed [ECDICT_DB=<stardict.db>] [WORDLISTS_DIR=<mahavivo dir>] [SEED_BASE=<rev>]`
# runs scripts/build_seed.py (data/lists/manifest.json + the COMMITTED seed `git show $(SEED_BASE):data/seed/vocab.jsonl.gz`
# [+ ECDICT]) → scripts/seed_diff.py (DIFF.md, invariants; same baseline) → this script. The intermediate vocab.jsonl is
# gitignored; only the .gz is tracked.
set -euo pipefail

usage() { sed -n '2,19p' "$0" | sed 's/^# \{0,1\}//'; }

check_only=0
seed_dir=""
for arg in "$@"; do
  case "$arg" in
    --check) check_only=1 ;;
    -h|--help) usage; exit 0 ;;
    -*) echo "pack_seed.sh: unknown option $arg" >&2; usage >&2; exit 2 ;;
    *) seed_dir="$arg" ;;
  esac
done

repo_root="$(cd "$(dirname "$0")/.." && pwd)"
seed_dir="${seed_dir:-$repo_root/data/seed}"
jsonl="$seed_dir/vocab.jsonl"
gz="$seed_dir/vocab.jsonl.gz"
stats="$seed_dir/stats.json"
PY="$repo_root/.venv/bin/python"
[ -x "$PY" ] || PY=python3

sha256_file() {  # sha256 hex of a file
  if command -v sha256sum >/dev/null 2>&1; then sha256sum "$1" | cut -d' ' -f1; else shasum -a 256 "$1" | cut -d' ' -f1; fi
}
sha256_stdin() {  # sha256 hex of stdin
  if command -v sha256sum >/dev/null 2>&1; then sha256sum | cut -d' ' -f1; else shasum -a 256 | cut -d' ' -f1; fi
}
file_size() { wc -c < "$1" | tr -d ' '; }
count_lines() { grep -c . "$1" || true; }   # non-empty lines only

if [ ! -s "$jsonl" ]; then
  if [ "$check_only" = 1 ] && [ -s "$gz" ]; then
    jsonl=""   # check mode may run from the archive alone
  else
    echo "pack_seed.sh: $jsonl is missing or empty (run 'make seed [ECDICT_DB=…]' first)" >&2
    exit 1
  fi
fi

expected=""
expected_sha=""
if [ -s "$stats" ]; then
  expected="$("$PY" -I -c 'import json,sys; print(json.load(open(sys.argv[1], encoding="utf-8")).get("total_words", ""))' "$stats")"
  expected_sha="$("$PY" -I -c 'import json,sys; print(json.load(open(sys.argv[1], encoding="utf-8")).get("content_sha256", ""))' "$stats")"
fi

if [ -n "$jsonl" ]; then
  records="$(count_lines "$jsonl")"
  content_sha="$(sha256_file "$jsonl")"
  echo "vocab.jsonl: $records records, content sha256 $content_sha"
  if [ -n "$expected" ] && [ "$records" != "$expected" ]; then
    echo "pack_seed.sh: record count $records != stats.json total_words $expected" >&2
    exit 1
  fi
  if [ -n "$expected_sha" ] && [ "$content_sha" != "$expected_sha" ]; then
    echo "pack_seed.sh: vocab.jsonl sha256 $content_sha != stats.json content_sha256 $expected_sha (rebuild with make seed)" >&2
    exit 1
  fi
fi

if [ "$check_only" = 1 ]; then
  [ -s "$gz" ] || { echo "pack_seed.sh: $gz is missing" >&2; exit 1; }
  gz_records="$(gzip -dc "$gz" | grep -c . || true)"
  gz_content_sha="$(gzip -dc "$gz" | sha256_stdin)"
  echo "vocab.jsonl.gz: $gz_records records, content sha256 $gz_content_sha, archive sha256 $(sha256_file "$gz"), $(file_size "$gz") bytes"
  if [ -n "$expected" ] && [ "$gz_records" != "$expected" ]; then
    echo "pack_seed.sh: archive record count $gz_records != stats.json total_words $expected" >&2
    exit 1
  fi
  if [ -n "$expected_sha" ] && [ "$gz_content_sha" != "$expected_sha" ]; then
    echo "pack_seed.sh: archive content sha256 $gz_content_sha != stats.json content_sha256 $expected_sha" >&2
    exit 1
  fi
  if [ -n "$jsonl" ] && ! gzip -dc "$gz" | cmp -s - "$jsonl"; then
    echo "pack_seed.sh: $gz does not match $jsonl (re-run without --check to repack)" >&2
    exit 1
  fi
  echo "seed archive OK"
  exit 0
fi

tmp="$(mktemp "$seed_dir/.vocab.jsonl.gz.XXXXXX")"
trap 'rm -f "$tmp"' EXIT
gzip -9 -n -c "$jsonl" > "$tmp"
if ! gzip -dc "$tmp" | cmp -s - "$jsonl"; then
  echo "pack_seed.sh: round trip of the new archive failed" >&2
  exit 1
fi
if [ -s "$gz" ] && cmp -s "$tmp" "$gz"; then
  echo "vocab.jsonl.gz unchanged (archive sha256 $(sha256_file "$gz"))"
  exit 0
fi
mv -f "$tmp" "$gz"
trap - EXIT
chmod 0644 "$gz"
echo "wrote $gz: $(gzip -dc "$gz" | grep -c . || true) records, $(file_size "$gz") bytes, archive sha256 $(sha256_file "$gz")"
