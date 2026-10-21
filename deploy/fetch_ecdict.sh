#!/usr/bin/env bash
# usage: deploy/fetch_ecdict.sh <DATA_DIR>
# Optional full ECDICT dictionary (docs/DEPLOY.md §2, `install.sh --with-ecdict`): downloads the 216 MB release zip,
# verifies its sha256 against the pinned value, extracts the single member `stardict.db` (851 MB) with the stdlib
# `python3 -m zipfile` (no unzip binary needed), installs it as <DATA_DIR>/stardict.db (0600) and writes
# WD_ECDICT_DB_PATH="<DATA_DIR>/stardict.db" into <DATA_DIR>/.env when that file exists.
# Idempotent: exits 0 at once when <DATA_DIR>/stardict.db already exists. Needs ≈ 1.1 GB free in <DATA_DIR> while extracting.
set -euo pipefail
DATA=${1:?usage: deploy/fetch_ecdict.sh <DATA_DIR>}
# The pinned release asset (verified on this box). ECDICT_URL / ECDICT_SHA256 may be overridden from the environment
# for a mirror whose checksum you computed yourself (the test suite uses this with a local file:// archive).
ECDICT_URL=${ECDICT_URL:-https://github.com/skywind3000/ECDICT/releases/download/1.0.28/ecdict-sqlite-28.zip}
ECDICT_SHA256=${ECDICT_SHA256:-ea01f76a3b3351021ce47077e89234465cc9441c8793054495320d06c0c3f3f6}
NEED_MB=1100
TARGET="$DATA/stardict.db"

if [ -s "$TARGET" ]; then
  echo "ECDICT already present: $TARGET ($(du -h "$TARGET" | cut -f1)) — nothing to do"
  exit 0
fi

install -d -m 0700 "$DATA" "$DATA/tmp"
AVAIL=$(df --output=avail -m "$DATA" | tail -1 | tr -d ' ')
[ "$AVAIL" -gt "$NEED_MB" ] || { echo "ERROR: need > ${NEED_MB} MB free in $DATA for the download + extraction (have ${AVAIL} MB)"; exit 1; }

ZIP="$DATA/tmp/ecdict-sqlite-28.zip"
EXTRACT="$DATA/tmp/ecdict"
rm -rf "$EXTRACT"

echo "downloading $ECDICT_URL"
curl -fL --retry 3 -o "$ZIP" "$ECDICT_URL"

ACTUAL=$(sha256sum "$ZIP" | awk '{print $1}')
if [ "$ACTUAL" != "$ECDICT_SHA256" ]; then
  rm -f "$ZIP"
  echo "ERROR: sha256 mismatch for $ZIP"
  echo "       expected $ECDICT_SHA256"
  echo "       got      $ACTUAL"
  echo "       the archive was deleted; re-run to download again (or check the release page)"
  exit 1
fi
echo "sha256 verified ($ECDICT_SHA256)"

echo "extracting with python3 -m zipfile"
python3 -m zipfile -e "$ZIP" "$EXTRACT"
[ -s "$EXTRACT/stardict.db" ] || { echo "ERROR: stardict.db not found inside the archive"; rm -rf "$EXTRACT" "$ZIP"; exit 1; }
# the extracted file must be the ECDICT SQLite database (table `stardict`), not an HTML error page or a truncated member
python3 -I -c 'import sqlite3, sys; c = sqlite3.connect("file:" + sys.argv[1] + "?mode=ro", uri=True); c.execute("SELECT word FROM stardict LIMIT 1").fetchone(); c.close()' "$EXTRACT/stardict.db" \
  || { echo "ERROR: $EXTRACT/stardict.db is not a readable ECDICT database"; rm -rf "$EXTRACT" "$ZIP"; exit 1; }

mv "$EXTRACT/stardict.db" "$TARGET"
chmod 0600 "$TARGET"
rm -rf "$EXTRACT" "$ZIP"
echo "installed $TARGET ($(du -h "$TARGET" | cut -f1))"

if [ -f "$DATA/.env" ]; then
  # keep the §4 quoting rule: KEY="value"
  if grep -q '^WD_ECDICT_DB_PATH=' "$DATA/.env"; then
    sed -i "s|^WD_ECDICT_DB_PATH=.*|WD_ECDICT_DB_PATH=\"$TARGET\"|" "$DATA/.env"
  else
    printf 'WD_ECDICT_DB_PATH="%s"\n' "$TARGET" >> "$DATA/.env"
  fi
  echo "WD_ECDICT_DB_PATH set in $DATA/.env — restart the service to use it: sudo systemctl restart word-dance"
else
  echo "NOTE: no $DATA/.env here — set WD_ECDICT_DB_PATH=\"$TARGET\" in your configuration to enable ECDICT lookups"
fi
