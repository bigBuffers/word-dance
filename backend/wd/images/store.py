"""Image storage (DESIGN §9): ``images/<2hex>/<sha256>.<jpg|svg>`` files (0600, written atomically, de-duplicated
by content hash — the same sha may serve several words) and the ``word_images`` rows with exactly one ``active``
row per word (previous active → ``superseded``; ``words.active_image_id`` / ``image_state`` follow).
"""

from __future__ import annotations

import hashlib
import logging
import os
import re
import sqlite3
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable

from ..clock import now_iso
from ..config import Settings
from ..db import maybe_tx
from ..interfaces import Candidate
from . import sanitize_svg

log = logging.getLogger("wd.images.store")

FILE_RE = re.compile(r"^[0-9a-f]{2}/[0-9a-f]{64}\.(jpg|svg)$")


@dataclass
class StoredFile:
    sha256: str
    file_path: str  # relative to DATA_DIR/images, e.g. 'ab/ab12….jpg'
    file_bytes: int
    created: bool  # False when an identical file already existed (dedupe)


def rel_path(sha256: str, ext: str) -> str:
    return f"{sha256[:2]}/{sha256}.{ext}"


def write_bytes(cfg: Settings, data: bytes, ext: str) -> StoredFile:
    """Store ``data`` under its sha256 path with mode 0600 (atomic rename); an existing identical file is reused."""
    if ext not in ("jpg", "svg"):
        raise ValueError(f"unsupported extension {ext!r}")
    sha = hashlib.sha256(data).hexdigest()
    rel = rel_path(sha, ext)
    dest = cfg.images_dir / rel
    if dest.is_file() and dest.stat().st_size == len(data):
        return StoredFile(sha, rel, len(data), False)
    dest.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    fd, tmp_name = tempfile.mkstemp(prefix=".tmp-", dir=str(dest.parent))
    try:
        with os.fdopen(fd, "wb") as f:
            f.write(data)
            f.flush()
            os.fsync(f.fileno())
        os.chmod(tmp_name, 0o600)
        os.replace(tmp_name, dest)
    except BaseException:
        try:
            os.unlink(tmp_name)
        except OSError:
            pass
        raise
    return StoredFile(sha, rel, len(data), True)


def attribution_line(title: str | None, creator: str | None, license: str | None, *, sentence: str | None = None) -> str:
    """``"{title}" · {creator} · {license}`` (DESIGN §9), or the provider's own attribution sentence when it has one."""
    if sentence:
        return sentence
    parts = [f'"{title.strip()}"' if title and title.strip() else None, (creator or "").strip() or None, (license or "").strip() or None]
    return " · ".join(p for p in parts if p)


def activate(
    conn: sqlite3.Connection,
    word_id: int,
    *,
    provider: str,
    file_path: str,
    file_bytes: int,
    sha256: str,
    mime: str,
    ref: str | None = None,
    query: str | None = None,
    source_url: str | None = None,
    landing_url: str | None = None,
    title: str | None = None,
    creator: str | None = None,
    creator_url: str | None = None,
    license: str | None = None,
    license_url: str | None = None,
    attribution_text: str | None = None,
    alt_zh: str | None = None,
    width: int | None = None,
    height: int | None = None,
    score: float | None = None,
    now: str | None = None,
) -> int:
    """Insert the new ``active`` image row, supersede the previous one and point the word at it (one transaction)."""
    now = now or now_iso()
    with maybe_tx(conn):
        conn.execute("UPDATE word_images SET status = 'superseded' WHERE word_id = ? AND status = 'active'", (int(word_id),))
        cur = conn.execute(
            "INSERT INTO word_images(word_id, provider, provider_ref, query, source_url, landing_url, title, creator, creator_url, "
            "license, license_url, attribution_text, alt_zh, width, height, file_path, file_bytes, sha256, mime, score, status, created_at) "
            "VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,'active',?)",
            (
                int(word_id), provider, ref, query, source_url, landing_url, title, creator, creator_url,
                license, license_url, attribution_text, alt_zh, width, height, file_path, int(file_bytes), sha256, mime, score, now,
            ),
        )
        image_id = int(cur.lastrowid)
        conn.execute(
            "UPDATE words SET active_image_id = ?, image_state = 'ready', updated_at = ? WHERE id = ?",
            (image_id, now, int(word_id)),
        )
    log.info("image activated", extra={"provider": provider, "event": "image_ready"})
    return image_id


def activate_candidate(conn: sqlite3.Connection, word_id: int, cand: Candidate, stored: Any, *, query: str, alt_zh: str | None, score: float | None, now: str | None = None) -> int:
    """Activate a downloaded photo (``stored`` is :class:`wd.images.fetch.StoredImage`)."""
    sentence = cand.extra.get("attribution") if cand.provider == "openverse" else None
    return activate(
        conn,
        word_id,
        provider=cand.provider,
        ref=cand.ref,
        query=query,
        source_url=cand.image_url,
        landing_url=cand.landing_url or None,
        title=cand.title or None,
        creator=cand.creator,
        creator_url=cand.creator_url,
        license=cand.license or None,
        license_url=cand.license_url,
        attribution_text=attribution_line(cand.title, cand.creator, cand.license, sentence=sentence if isinstance(sentence, str) else None),
        alt_zh=alt_zh,
        width=stored.width,
        height=stored.height,
        file_path=stored.file_path,
        file_bytes=stored.file_bytes,
        sha256=stored.sha256,
        mime=stored.mime,
        score=score,
        now=now,
    )


def activate_svg(conn: sqlite3.Connection, cfg: Settings, word_id: int, svg: str, alt_zh: str | None, *, now: str | None = None) -> int:
    """Sanitise a Claude-drawn SVG (CLAUDE_INTEGRATION §6.7), store it as ``.svg`` and activate it.

    Raises :class:`wd.images.sanitize_svg.SvgRejected` when the SVG cannot be made safe; the caller
    (``ai/svg.py``) then sets ``image_state='failed'`` so the template card keeps being served.
    """
    cleaned = sanitize_svg.clean(svg)
    stored = write_bytes(cfg, cleaned.encode("utf-8"), "svg")
    width, height = sanitize_svg.viewbox_size(cleaned)
    return activate(
        conn,
        word_id,
        provider="claude_svg",
        license="generated",
        alt_zh=(alt_zh or "").strip()[:200] or None,
        width=width,
        height=height,
        file_path=stored.file_path,
        file_bytes=stored.file_bytes,
        sha256=stored.sha256,
        mime="image/svg+xml",
        now=now,
    )


def set_image_state(conn: sqlite3.Connection, word_id: int, state: str, *, now: str | None = None) -> None:
    if state not in ("none", "queued", "ready", "failed"):
        raise ValueError(f"invalid image_state {state!r}")
    now = now or now_iso()
    with maybe_tx(conn):
        conn.execute("UPDATE words SET image_state = ?, updated_at = ? WHERE id = ?", (state, now, int(word_id)))


# ------------------------------------------------------------------------------------------ pruning
def referenced_files(conn: sqlite3.Connection) -> set[str]:
    """Every ``file_path`` still referenced by a ``word_images`` row (any status)."""
    return {str(r[0]) for r in conn.execute("SELECT DISTINCT file_path FROM word_images")}


def list_files(cfg: Settings) -> list[str]:
    """Relative paths of the files under ``images/`` that look like stored images."""
    root = cfg.images_dir
    if not root.is_dir():
        return []
    out: list[str] = []
    for sub in sorted(p for p in root.iterdir() if p.is_dir() and len(p.name) == 2):
        for f in sorted(sub.iterdir()):
            rel = f"{sub.name}/{f.name}"
            if f.is_file() and FILE_RE.match(rel):
                out.append(rel)
    return out


def remove_files(cfg: Settings, paths: Iterable[str], *, dry_run: bool = False) -> list[str]:
    """Delete the given relative image paths (and empty shard directories); returns what was (or would be) removed."""
    removed: list[str] = []
    for rel in paths:
        if not FILE_RE.match(rel):
            continue
        p: Path = cfg.images_dir / rel
        if not p.is_file():
            continue
        removed.append(rel)
        if dry_run:
            continue
        try:
            p.unlink()
        except OSError as e:
            log.warning("could not delete %s: %s", p, e)
            continue
        try:
            p.parent.rmdir()  # only succeeds when the shard directory is empty
        except OSError:
            pass
    return removed
