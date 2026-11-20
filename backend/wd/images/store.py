"""Image storage (DESIGN §9): ``images/<2hex>/<sha256>.<jpg|svg>`` files (0600, written atomically, de-duplicated
by content hash — the same sha may serve several words) and the ``word_images`` rows with exactly one ``active``
row per word (previous active → ``superseded``; ``words.active_image_id`` / ``image_state`` follow).

Since migration 0012 a row also records how a generated picture came to be (PLAN §2.3): ``prompt_version`` (``svg-v2``
for Claude drawings made with the current system prompt; NULL for photos and for the drawings made before 0012),
``model`` (the generator model, ``ai_calls.model_used``), ``text_free`` (1 only when the file went through
``sanitize_svg.clean(allow_text=False)`` — the single gate any future picture-first study mode may rely on) and
``eval_json`` (pilot rubric scores, never ``score``). Photos leave the four columns at their defaults.

Since migration 0021 a row may be a 记忆图卡 (docs/MEMORY_CARDS_DESIGN.md §3; ``images/memo.py``): still ``provider = 'claude_svg'``
and ``text_free = 1`` — the word on the card is made of paths — with ``prompt_version = 'memo-…'`` and its two captions in
``hook_zh`` / ``note_zh``. Such a card never comes from the online ``generate_svg`` job: it enters through ``wd images-import``
alone, in two steps — :func:`prepare_memo` cleans the file with ``effects=True`` (the only caller that lets blur filters and clip
paths through) and checks the card's structure and captions, :func:`store_memo` labels, stores and activates exactly that cleaned
text (:func:`activate_memo` is the two in one call). The file is cleaned ONCE: the import compares the prepared card with the
word's active picture, and ``clean()`` is not a fixed point for a file it emptied an element of. :func:`undo_memo` is the way
back: the card becomes ``superseded`` and the word returns to what it showed when the card arrived — its newest earlier picture
that is no card, unless a report had taken that one down (then, as before the import, the template card); nothing is ever deleted
by either.
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
from typing import Any, Iterable, Mapping

from ..clock import now_iso
from ..config import Settings
from ..db import maybe_tx
from ..interfaces import Candidate
from . import dancing, memo, sanitize_svg

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
    prompt_version: str | None = None,
    model: str | None = None,
    text_free: bool = False,
    eval_json: str | None = None,
) -> int:
    """Insert the new ``active`` image row, supersede the previous one and point the word at it (one transaction).

    ``prompt_version`` / ``model`` / ``text_free`` / ``eval_json`` are the 0012 provenance columns (module docstring);
    :func:`activate_candidate` leaves them at their defaults (a photo is never text-free by construction).
    """
    now = now or now_iso()
    with maybe_tx(conn):
        conn.execute("UPDATE word_images SET status = 'superseded' WHERE word_id = ? AND status = 'active'", (int(word_id),))
        cur = conn.execute(
            "INSERT INTO word_images(word_id, provider, provider_ref, query, source_url, landing_url, title, creator, creator_url, "
            "license, license_url, attribution_text, alt_zh, width, height, file_path, file_bytes, sha256, mime, score, status, created_at, "
            "prompt_version, model, text_free, eval_json) "
            "VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,'active',?,?,?,?,?)",
            (
                int(word_id), provider, ref, query, source_url, landing_url, title, creator, creator_url,
                license, license_url, attribution_text, alt_zh, width, height, file_path, int(file_bytes), sha256, mime, score, now,
                prompt_version, model, 1 if text_free else 0, eval_json,
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


def aigc_label(model: str | None, now: str) -> str:
    """The text of the implicit AIGC marker: ``AI-generated illustration · word-Dance · <model> · <date>``."""
    return f"AI-generated illustration · word-Dance · {model or 'claude'} · {now[:10]}"


def activate_svg(
    conn: sqlite3.Connection,
    cfg: Settings,
    word_id: int,
    svg: str,
    alt_zh: str | None,
    *,
    now: str | None = None,
    model: str | None = None,
    prompt_version: str | None = None,
    stage: Mapping[str, Any] | None = None,
) -> int:
    """Sanitise a Claude-drawn SVG (CLAUDE_INTEGRATION §6.7), store it as ``.svg`` and activate it.

    The drawing is cleaned with ``allow_text=False`` — ``<text>`` / ``<tspan>`` are dropped whatever the model wrote,
    which is what ``text_free = 1`` asserts — then labelled with the implicit AIGC marker (``sanitize_svg.with_label``)
    and stored; ``model`` (``ai_calls.model_used``) and ``prompt_version`` (``ai.svg.SVG_PROMPT_VERSION``) go to the
    0012 columns. Raises :class:`wd.images.sanitize_svg.SvgRejected` when the SVG cannot be made safe; the caller
    (``ai/svg.py``) then sets ``image_state='failed'`` so the template card keeps being served.

    ``stage`` (``{"display", "motion", "highlight", "hook_zh"}``, prompt ``svg-v3``) makes the drawing a 跳动图卡: the validated motion
    and highlight are recorded inside the file (``dancing.stage_svg``) and the memory line goes to ``hook_zh`` in the same transaction.
    """
    now = now or now_iso()
    cleaned = sanitize_svg.clean(svg, allow_text=False)
    if stage is not None:
        cleaned = dancing.stage_svg(cleaned, str(stage.get("display") or ""), motion=stage.get("motion"), highlight=stage.get("highlight"))
    cleaned = sanitize_svg.with_label(cleaned, aigc_label(model, now))
    stored = write_bytes(cfg, cleaned.encode("utf-8"), "svg")
    width, height = sanitize_svg.viewbox_size(cleaned)
    with maybe_tx(conn):
        image_id = activate(
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
            prompt_version=prompt_version,
            model=model,
            text_free=True,
        )
        if stage is not None:
            conn.execute("UPDATE word_images SET hook_zh = ? WHERE id = ?", (dancing.hook_of(stage.get("hook_zh")), image_id))
    return image_id


# ------------------------------------------------------------------------- 记忆图卡 (docs/MEMORY_CARDS_DESIGN.md §3)
HOOK_MAX_CHARS = 60  # word_images.hook_zh: the memory hook, one short sentence under the card
NOTE_MAX_CHARS = 60  # word_images.note_zh: the optional sound / meaning caveat
ALT_MAX_CHARS = 200  # word_images.alt_zh: the scene in words (the existing column and its existing limit)
MODEL_MAX_CHARS = 80  # goes into the AIGC label and word_images.model


class MemoRejected(sanitize_svg.SvgRejected):
    """A memory card that cannot be stored: the sanitiser refused the file, the structure of §3.1 is not met, a caption is
    too long, the version label is not a ``memo-…`` one. ``problems`` lists every reason found, not only the first."""

    def __init__(self, problems: Iterable[str]):
        self.problems = [str(p) for p in problems]
        super().__init__("; ".join(self.problems))


@dataclass
class MemoCard:
    """A validated memory card ready to be stored: the cleaned SVG (not yet labelled) and its normalised captions."""

    svg: str
    alt_zh: str | None
    hook_zh: str | None
    note_zh: str | None
    model: str
    prompt_version: str


def _caption(value: Any, name: str, limit: int, problems: list[str]) -> str | None:
    """A caption with its whitespace collapsed, ``None`` when absent or blank; too long or not a string → a problem (the
    limit is checked BEFORE anything could be cut: a hook that lost its last words would be a wrong hook)."""
    if value is None:
        return None
    if not isinstance(value, str):
        problems.append(f"{name} must be a string, not {type(value).__name__}")
        return None
    text = " ".join(value.split())
    if len(text) > limit:
        problems.append(f"{name} is {len(text)} characters, the limit is {limit}")
    return text or None


def prepare_memo(svg: str, headword: str, *, alt_zh: str | None, hook_zh: str | None, note_zh: str | None, model: str, prompt_version: str) -> MemoCard:
    """Everything :func:`activate_memo` checks, without touching the database or the disk (the dry run of ``wd images-import``).

    The file is cleaned with ``sanitize_svg.clean(allow_text=False, effects=True)`` and the result must satisfy
    :func:`wd.images.memo.check_structure` for ``headword`` (the word's display form); ``prompt_version`` must start with
    ``memo-``; ``model`` names who drew the card in 1–80 printable characters (it is written into the file's AIGC label after
    every check ran on the unlabelled text, and the label's escaping knows ``& < >`` only: a control character, U+FFFE or a lone
    surrogate there would store a file that is not XML, or not UTF-8 at all); ``hook_zh`` / ``note_zh`` hold at most 60 characters
    and ``alt_zh`` 200, after whitespace is collapsed. Raises :class:`MemoRejected` (a :class:`~wd.images.sanitize_svg.SvgRejected`)
    carrying every problem."""
    problems: list[str] = []
    if not isinstance(prompt_version, str) or not prompt_version.startswith(memo.PROMPT_PREFIX) or len(prompt_version) <= len(memo.PROMPT_PREFIX):
        problems.append(f"prompt_version must be {memo.PROMPT_PREFIX}<n> (e.g. memo-1), not {prompt_version!r}")
    model_name = " ".join(model.split()) if isinstance(model, str) else ""
    if not model_name or len(model_name) > MODEL_MAX_CHARS or not model_name.isprintable():  # whitespace is already single spaces: what is left unprintable is a control / format character, a noncharacter, a surrogate
        problems.append(f"model must name the model that drew the card (1–{MODEL_MAX_CHARS} printable characters), not {model!r}")
    alt = _caption(alt_zh, "alt_zh", ALT_MAX_CHARS, problems)
    hook = _caption(hook_zh, "hook_zh", HOOK_MAX_CHARS, problems)
    note = _caption(note_zh, "note_zh", NOTE_MAX_CHARS, problems)
    cleaned = ""
    try:
        cleaned = sanitize_svg.clean(svg, allow_text=False, effects=True)
    except sanitize_svg.SvgRejected as e:
        problems.append(f"the sanitiser rejected the file: {e}")
    else:
        problems.extend(memo.check_structure(cleaned, headword))
    if problems:
        raise MemoRejected(problems)
    return MemoCard(svg=cleaned, alt_zh=alt, hook_zh=hook, note_zh=note, model=model_name, prompt_version=prompt_version)


def stored_memo(row: Mapping[str, Any] | sqlite3.Row | None, card: MemoCard) -> bytes | None:
    """The file of ``row`` — a memory-card row of the word — when ``card`` is that very picture, else None. The stored file
    carries the AIGC label of the day (and model) it was first imported, so the candidate is labelled the same way before the
    two sha256 are compared — a card imported again next week is the same card, not a new row. What comes back is therefore
    byte for byte what is (or should be) on disk under ``row['file_path']``: :func:`restore_memo_file` writes it."""
    if not memo.is_memo(row):
        return None
    data = sanitize_svg.with_label(card.svg, aigc_label(row["model"], str(row["created_at"]))).encode("utf-8")
    return data if hashlib.sha256(data).hexdigest() == row["sha256"] else None


def memo_unchanged(active: Mapping[str, Any] | sqlite3.Row | None, card: MemoCard) -> bool:
    """Is ``card`` the very picture of ``active``, the word's active memory card? (:func:`stored_memo` has the comparison.)"""
    return stored_memo(active, card) is not None


def restore_memo_file(cfg: Settings, data: bytes, *, dry_run: bool = False) -> bool:
    """Put the file of an ``unchanged`` card back when ``images/`` has lost it — a partial copy to a new server, images restored
    from an older archive than the database, a shard deleted by hand. ``data`` is :func:`stored_memo`'s answer, so it lands on
    the row's own path; True when the file was not there (or cut short) — ``dry_run`` only says so. A card is the one picture
    no provider can fetch again, and "run the import again" is the documented repair (docs/ops.md §4): comparing sha256 alone
    would answer ``unchanged`` over a URL that is 404."""
    if dry_run:
        dest = cfg.images_dir / rel_path(hashlib.sha256(data).hexdigest(), "svg")
        return not (dest.is_file() and dest.stat().st_size == len(data))  # write_bytes' own test
    return write_bytes(cfg, data, "svg").created


def retired_memo(conn: sqlite3.Connection, word_id: int, card: MemoCard) -> sqlite3.Row | None:
    """The ``rejected`` memory-card row that says this very picture was taken down, or None. A learner's 不合适 on a card is only
    recorded (API.md 28), so a card row is ``rejected`` by one thing alone: an admin resolved a report with ``refetch_image``
    (API.md 71). The import must not take that decision back as a side effect of the next whole-manifest run — it asks here
    before it activates anything and leaves such a card down unless the lemma was named with ``--only``. The word's NEWEST
    earlier row of this picture decides: ``rejected`` → that row; ``superseded`` → None, because the picture was brought back
    after any rejection (``--only``) and what ended it since — ``--undo``, a redrawn card — is no retirement. A redrawn file is
    another picture and matches no row."""
    for row in conn.execute("SELECT * FROM word_images WHERE word_id = ? AND status != 'active' ORDER BY id DESC", (int(word_id),)).fetchall():
        if memo_unchanged(row, card):
            return row if row["status"] == "rejected" else None
    return None


def set_memo_captions(conn: sqlite3.Connection, image_id: int, card: MemoCard, *, dry_run: bool = False) -> bool:
    """Write ``card``'s three captions onto the memory-card row ``image_id`` (an unchanged picture whose manifest text was
    corrected); True when something differed — ``dry_run`` only says so. The picture, its label and its provenance columns
    (``prompt_version``, ``model``, ``created_at``) stay as first imported."""
    row = conn.execute("SELECT alt_zh, hook_zh, note_zh FROM word_images WHERE id = ?", (int(image_id),)).fetchone()
    if row is None or (row["alt_zh"], row["hook_zh"], row["note_zh"]) == (card.alt_zh, card.hook_zh, card.note_zh):
        return False
    if not dry_run:
        with maybe_tx(conn):
            conn.execute("UPDATE word_images SET alt_zh = ?, hook_zh = ?, note_zh = ? WHERE id = ?", (card.alt_zh, card.hook_zh, card.note_zh, int(image_id)))
    return True


def activate_memo(
    conn: sqlite3.Connection,
    cfg: Settings,
    word_id: int,
    svg: str,
    *,
    alt_zh: str | None,
    hook_zh: str | None,
    note_zh: str | None,
    model: str,
    prompt_version: str,
    now: str | None = None,
) -> int:
    """Validate, sanitise, label, store and activate a 记忆图卡 for ``word_id`` (docs/MEMORY_CARDS_DESIGN.md §3.1, §3.5).

    :func:`prepare_memo` does the checking against the word's display form — the one place a drawing is cleaned with
    ``effects=True`` — and :func:`store_memo` the rest. Raises :class:`MemoRejected` — nothing is written then."""
    word = conn.execute("SELECT display FROM words WHERE id = ?", (int(word_id),)).fetchone()
    if word is None:
        raise MemoRejected([f"word {int(word_id)} not found"])
    card = prepare_memo(svg, str(word["display"]), alt_zh=alt_zh, hook_zh=hook_zh, note_zh=note_zh, model=model, prompt_version=prompt_version)
    return store_memo(conn, cfg, word_id, card, now=now)


def store_memo(conn: sqlite3.Connection, cfg: Settings, word_id: int, card: MemoCard, *, now: str | None = None) -> int:
    """Label, store and activate ``card`` — a :func:`prepare_memo` result for this word — WITHOUT cleaning it again.

    The cleaned text gets the implicit AIGC marker like every Claude drawing and is stored under its sha256; the row is an
    ordinary ``claude_svg`` activation (the previous image becomes ``superseded`` and keeps its file, ``image_state = 'ready'``,
    ``text_free = 1``) with the card's ``prompt_version`` / ``model`` and, in the same transaction, ``hook_zh`` / ``note_zh``
    (migration 0021). ``wd images-import`` hands in the very card it compared with the active picture (:func:`memo_unchanged`):
    ``clean()`` writes an element whose children it dropped as ``<defs></defs>`` and that text, cleaned again, as ``<defs/>``,
    so a second pass here would store a file the next run could never recognise as ``unchanged``."""
    now = now or now_iso()
    labelled = sanitize_svg.with_label(card.svg, aigc_label(card.model, now))
    stored = write_bytes(cfg, labelled.encode("utf-8"), "svg")
    width, height = sanitize_svg.viewbox_size(labelled)
    with maybe_tx(conn):
        image_id = activate(
            conn,
            word_id,
            provider=memo.PROVIDER,
            license="generated",
            alt_zh=card.alt_zh,
            width=width,
            height=height,
            file_path=stored.file_path,
            file_bytes=stored.file_bytes,
            sha256=stored.sha256,
            mime="image/svg+xml",
            now=now,
            prompt_version=card.prompt_version,
            model=card.model,
            text_free=True,
        )
        # activate()'s INSERT is shared with every photo and keeps naming the columns it always named; the two captions only a
        # memory card has are set here, inside the same transaction
        conn.execute("UPDATE word_images SET hook_zh = ?, note_zh = ? WHERE id = ?", (card.hook_zh, card.note_zh, image_id))
    return image_id


def undo_memo(
    conn: sqlite3.Connection, cfg: Settings, word_id: int, *, now: str | None = None, dry_run: bool = False, tried: bool = False
) -> tuple[str, sqlite3.Row | None]:
    """Take the word's active memory card out of service (``wd images-import --undo``, the rollback of an import).

    ``('kept', active row or None)`` when the active image is not a memory card — nothing changes; that includes a word whose
    card an admin took down after a report (the card is ``rejected``, whatever replaced it stays). Otherwise the card becomes
    ``superseded`` (row and file stay; a later import of the same file simply activates a new row) and the word goes back to
    what it showed when the card arrived: its earlier rows are walked newest first, memory cards skipped whatever became of them
    (an earlier card that was undone, redrawn or taken down says nothing about the picture under it), and the first other row
    decides — ``superseded`` with its file still on disk is made ``active`` again, ``('restored', that row)``; ``superseded``
    without its file passes the question to the row before it; ``rejected`` ends the walk: a report took the word's last
    picture down and nothing replaced it, so the card arrived on the template card and the pictures older than the report
    stay retired. No row to restore: the template card, ``('card', None)``, with ``image_state = 'none'`` like after
    ``wd images-prune`` — or ``'failed'`` when ``tried`` (the caller knows the word's fetch chain has run before:
    ``service.chain_was_tried``), which is the state such a word had before its card and the one the retry rules look for.
    ``dry_run`` reports the same verdict without writing."""
    now = now or now_iso()
    with maybe_tx(conn):
        active = conn.execute(
            "SELECT wi.* FROM words w JOIN word_images wi ON wi.id = w.active_image_id WHERE w.id = ? AND wi.status = 'active'", (int(word_id),)
        ).fetchone()
        if not memo.is_memo(active):
            return "kept", active
        previous = None
        earlier = conn.execute(
            "SELECT * FROM word_images WHERE word_id = ? AND id < ? AND status IN ('superseded', 'rejected') ORDER BY id DESC", (int(word_id), int(active["id"]))
        ).fetchall()
        for row in earlier:
            if memo.is_memo(row):
                continue
            if row["status"] == "rejected":
                break  # reported and never replaced: the word was on the template card when the card arrived
            if FILE_RE.match(str(row["file_path"])) and (cfg.images_dir / str(row["file_path"])).is_file():
                previous = row
                break
        if not dry_run:
            conn.execute("UPDATE word_images SET status = 'superseded' WHERE id = ?", (int(active["id"]),))  # first: one active row per word
            if previous is not None:
                conn.execute("UPDATE word_images SET status = 'active' WHERE id = ?", (int(previous["id"]),))
                conn.execute("UPDATE words SET active_image_id = ?, image_state = 'ready', updated_at = ? WHERE id = ?", (int(previous["id"]), now, int(word_id)))
            else:
                conn.execute("UPDATE words SET active_image_id = NULL, image_state = ?, updated_at = ? WHERE id = ?", ("failed" if tried else "none", now, int(word_id)))
    if not dry_run:
        log.info("memory card undone", extra={"provider": memo.PROVIDER, "event": "image_memo_undone"})
    return ("restored", previous) if previous is not None else ("card", None)


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
