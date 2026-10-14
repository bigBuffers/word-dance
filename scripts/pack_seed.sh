#!/usr/bin/env bash
# scripts/pack_seed.sh — pack data/seed/vocab.jsonl into the tracked, reproducible data/seed/vocab.jsonl.gz (WP1).
#
#   scripts/pack_seed.sh [--check] [SEED_DIR]
#
# * gzip -9 -n: no file name / mtime in the archive, so identical input gives a byte-identical .gz and the sha256 that
#   the server stores as kv.seed_version (docs/P0_STATUS.md §3 item 24) is stable across rebuilds.
# * the record count is checked against stats.json (total_words) when that file exists, and the archive is verified by
#   a round trip (zcat | cmp) before the old .gz is replaced.
# * --check: verify only (counts + round trip of the existing archive), write nothing; exit 1 on any mismatch.
#
# Rebuilding vocab.jsonl itself needs the ECDICT database and the syllabus lists: `make seed ECDICT_DB=… WORDLISTS_DIR=…`
# (scripts/build_seed.py, kept verbatim). The intermediate vocab.jsonl is gitignored; only the .gz is tracked.
set -euo pipefail

usage() { sed -n '2,13p' "$0" | sed 's/^# \{0,1\}//'; }

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

if [ ! -s "$jsonl" ]; then
  if [ "$check_only" = 1 ] && [ -s "$gz" ]; then
    jsonl=""   # check mode may run from the archive alone
  else
    echo "pack_seed.sh: $jsonl is missing or empty (run 'make seed ECDICT_DB=… WORDLISTS_DIR=…' first)" >&2
    exit 1
  fi
fi

expected=""
if [ -s "$stats" ]; then
  expected="$(python3 -I -c 'import json,sys; print(json.load(open(sys.argv[1], encoding="utf-8")).get("total_words", ""))' "$stats")"
fi

count_lines() { grep -c . "$1" || true; }   # non-empty lines only

if [ -n "$jsonl" ]; then
  records="$(count_lines "$jsonl")"
  echo "vocab.jsonl: $records records"
  if [ -n "$expected" ] && [ "$records" != "$expected" ]; then
    echo "pack_seed.sh: record count $records != stats.json total_words $expected" >&2
    exit 1
  fi
fi

if [ "$check_only" = 1 ]; then
  [ -s "$gz" ] || { echo "pack_seed.sh: $gz is missing" >&2; exit 1; }
  gz_records="$(zcat "$gz" | grep -c . || true)"
  echo "vocab.jsonl.gz: $gz_records records, sha256 $(sha256sum "$gz" | cut -d' ' -f1)"
  if [ -n "$expected" ] && [ "$gz_records" != "$expected" ]; then
    echo "pack_seed.sh: archive record count $gz_records != stats.json total_words $expected" >&2
    exit 1
  fi
  if [ -n "$jsonl" ] && ! zcat "$gz" | cmp -s - "$jsonl"; then
    echo "pack_seed.sh: $gz does not match $jsonl (re-run without --check to repack)" >&2
    exit 1
  fi
  echo "seed archive OK"
  exit 0
fi

tmp="$(mktemp "$seed_dir/.vocab.jsonl.gz.XXXXXX")"
trap 'rm -f "$tmp"' EXIT
gzip -9 -n -c "$jsonl" > "$tmp"
if ! zcat "$tmp" | cmp -s - "$jsonl"; then
  echo "pack_seed.sh: round trip of the new archive failed" >&2
  exit 1
fi
if [ -s "$gz" ] && cmp -s "$tmp" "$gz"; then
  echo "vocab.jsonl.gz unchanged (sha256 $(sha256sum "$gz" | cut -d' ' -f1))"
  exit 0
fi
mv -f "$tmp" "$gz"
trap - EXIT
chmod 0644 "$gz"
echo "wrote $gz: $(zcat "$gz" | grep -c . || true) records, $(stat -c %s "$gz") bytes, sha256 $(sha256sum "$gz" | cut -d' ' -f1)"
