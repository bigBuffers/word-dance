"""Vocabulary services (WP1): input normalisation, lemma resolution and the word DTO builders.

Contracts: DESIGN §5.1 (:func:`normalise_input`), DESIGN §5.2 (:func:`resolve` — exact → form → ambiguous → ecdict →
provisional; the signature is frozen in TASKS §I), API.md §9 (``WordBrief`` / ``WordDetail`` / ``UserWord`` dicts built
by :func:`word_brief`, :func:`word_detail`, :func:`user_word_dict`), API.md §9.1 (``confusables``,
``mastery_suggested``, the template-card ``ImageMeta``), API.md 24 (:func:`content_deferred_until`) and
CLAUDE_INTEGRATION §6.5 (:func:`validate_headword`, :func:`suffix_rule_maps`).

Every function takes an open ``sqlite3.Connection`` (``row_factory = sqlite3.Row``, see ``wd.db.connect``) and
composes with a caller's transaction through ``db.maybe_tx``. The ``ImageMeta`` of a word comes from WP6's
``images.image_meta`` (with the template card as the fallback for any image-layer failure), and the ECDICT step goes
through :mod:`wd.services.ecdict` (which answers None while ``WD_ECDICT_DB_PATH`` is unset).
"""

from __future__ import annotations

import json
import logging
import re
import sqlite3
import unicodedata
from dataclasses import dataclass, field
from datetime import timedelta
from typing import Any, ClassVar, Iterable, Literal, Mapping

from .. import db, images
from ..clock import now_iso, parse_iso, to_iso
from ..errors import ApiError
from ..jobs import queue
from ..schemas import STAGE_ORDER
from . import ecdict

log = logging.getLogger("wd.words")

# ------------------------------------------------------------------------------------------ constants
MAX_CHARS = 48
MAX_TOKENS = 4
MAX_DOTTED_TOKEN_LEN = 6  # 'a.m.', 'e.g.', 'etc.', 'U.S.A.' pass; 'example.com' fails (DESIGN §5.1)
KINDS: tuple[str, ...] = ("word", "phrase", "abbreviation", "proper_noun")
# The stage enum lives in schemas.py (DESIGN §0.3, PLAN R-1); the name STAGES stays for bank/screen/batches, which read it here.
STAGES: tuple[str, ...] = STAGE_ORDER
# word_forms.kind: ECDICT exchange codes, 'alt' (Claude/suffix rule) and 'alias' (an official list's spelling of a headword,
# written by the seed import from the record's aliases[] — migration 0013, PLAN §2.1)
FORM_KINDS: tuple[str, ...] = ("p", "d", "i", "3", "s", "r", "t", "alt", "alias")
FORM_KIND_ZH: dict[str, str] = {
    "p": "过去式",
    "d": "过去分词",
    "i": "现在分词",
    "3": "第三人称单数",
    "s": "复数",
    "r": "比较级",
    "t": "最高级",
    "alt": "变体",
    "alias": "另一种写法",
}
LOOKUP_DEBOUNCE_S = 20  # DESIGN §5.2 step 4: run_after = now + 20 s so pasted words share one lookup call
LOOKUP_PRIORITY = 10
DEFERRAL_THRESHOLD_S = 300  # API.md 24: a run_after more than 5 minutes ahead is a deferral
MAX_MERGE_HOPS = 8
MAX_CONFUSABLES = 6
TRANSLATION_SHORT_LEN = 60
HISTORY_LIMIT = 20

# zh reasons for Invalid (served as the invalid_word error message / LookupPreview.reason_zh)
REASON_EMPTY = "请输入单词"
REASON_NOT_ENGLISH = "请输入英文单词"
REASON_CHARSET = "只能包含英文字母、空格、连字符、撇号和缩写点"
REASON_TOO_LONG = f"太长了（最多 {MAX_CHARS} 个字符）"
REASON_TOO_MANY_TOKENS = f"最多 {MAX_TOKENS} 个单词组成的短语"
REASON_PUNCT_TOKEN = "请输入有效的单词"
REASON_DOT = "缩写点只能用于缩写（如 a.m.、e.g.）"
REASON_LEADING = "不能以连字符或撇号开头"

_CHAR_MAP = str.maketrans(
    {
        "’": "'",
        "‘": "'",
        "ʼ": "'",
        "‛": "'",
        "′": "'",
        "“": '"',
        "”": '"',
        "„": '"',
        "«": '"',
        "»": '"',
        "–": "-",
        "—": "-",
        "‐": "-",
        "‑": "-",
        "−": "-",
    }
)
_STRIP_PUNCT = ",;:!?\"()[]{}<>"
_WS_RE = re.compile(r"\s+")
_ALLOWED_RE = re.compile(r"^[A-Za-z' .\-]+$")
_ACRONYM_RE = re.compile(r"^[A-Z]{2,6}$")
_PUNCT_ONLY_RE = re.compile(r"^[' .\-]+$")
_CJK_RE = re.compile(r"[　-〿぀-ヿ㐀-䶿一-鿿가-힯豈-﫿＀-￯]")


def _form_kind_order(column: str = "kind") -> str:
    """SQL ``CASE`` ranking ``word_forms.kind`` p d i 3 s r t, then alt/alias (the note/forms order and the kind kept per pair)."""
    return f"CASE {column} WHEN 'p' THEN 0 WHEN 'd' THEN 1 WHEN 'i' THEN 2 WHEN '3' THEN 3 WHEN 's' THEN 4 WHEN 'r' THEN 5 WHEN 't' THEN 6 ELSE 7 END"


# -------------------------------------------------------------------------------------- normalisation
@dataclass(frozen=True)
class Normalised:
    """A valid custom-word input: ``lemma`` (lower-case key), ``display`` (casing kept where meaningful), ``kind``."""

    lemma: str
    display: str
    kind: str
    tokens: tuple[str, ...]
    ok: ClassVar[bool] = True


@dataclass(frozen=True)
class Invalid:
    """A rejected input with the zh reason (API.md ``invalid_word`` message / ``LookupPreview.reason_zh``)."""

    reason_zh: str
    ok: ClassVar[bool] = False


def _clean(text: str) -> str:
    """NFKC, curly quotes/dashes → ASCII, whitespace collapsed, surrounding punctuation (not ``.``) stripped."""
    s = unicodedata.normalize("NFKC", text or "").translate(_CHAR_MAP)
    s = _WS_RE.sub(" ", s)
    prev = None
    while prev != s:
        prev = s
        s = s.strip().strip(_STRIP_PUNCT)
    return s


def _display_token(tok: str) -> str:
    """Casing rule of DESIGN §5.1 step 3 per token: acronyms (≤ 6 upper-case letters, dots allowed) and
    Capitalised tokens keep their casing (proper-noun hint); everything else is lower-cased."""
    letters = [c for c in tok if c.isalpha()]
    if letters and 2 <= len(letters) <= MAX_DOTTED_TOKEN_LEN and all(c.isupper() for c in letters):
        return tok
    if tok[:1].isupper() and all(c.islower() for c in letters[1:]):
        return tok
    return tok.lower()


def derive_kind(display: str) -> str:
    """DESIGN §3.2 ``kind`` rule: space → phrase; ``^[A-Z]{2,6}$`` or a ``.`` → abbreviation; capital → proper_noun."""
    if " " in display:
        return "phrase"
    if _ACRONYM_RE.match(display) or "." in display:
        return "abbreviation"
    if display[:1].isupper():
        return "proper_noun"
    return "word"


def normalise_input(text: str) -> Normalised | Invalid:
    """DESIGN §5.1: clean, validate (charset, length, ≤ 4 tokens, punctuation-only tokens, dotted tokens, leading
    ``-``/``'``) and derive ``lemma`` / ``display`` / ``kind``. The same table drives the client-side preview."""
    if text is None:
        return Invalid(REASON_EMPTY)
    s = _clean(str(text))
    if not s:
        return Invalid(REASON_EMPTY)
    if _CJK_RE.search(s):
        return Invalid(REASON_NOT_ENGLISH)
    if not _ALLOWED_RE.match(s):
        return Invalid(REASON_CHARSET)
    if len(s) > MAX_CHARS:
        return Invalid(REASON_TOO_LONG)
    tokens = s.split(" ")
    if len(tokens) > MAX_TOKENS:
        return Invalid(REASON_TOO_MANY_TOKENS)
    for tok in tokens:
        if _PUNCT_ONLY_RE.match(tok):
            return Invalid(REASON_PUNCT_TOKEN)
        if "." in tok and len(tok) > MAX_DOTTED_TOKEN_LEN:
            return Invalid(REASON_DOT)
    if s[0] in "-'":
        return Invalid(REASON_LEADING)
    display = " ".join(_display_token(t) for t in tokens)
    lemma = s.lower()
    return Normalised(lemma=lemma, display=display, kind=derive_kind(display), tokens=tuple(lemma.split(" ")))


def normalise_lemma(text: str | None) -> str | None:
    """Lenient key normaliser for trusted dictionary strings (seed words, ``word_forms`` values): the cleaning step of
    :func:`normalise_input` plus lower-casing, without the validation. None when nothing is left."""
    if text is None:
        return None
    s = _clean(str(text)).lower()
    return s or None


def lemma_note_zh(display: str, form_kind: str) -> str:
    """«已归为原形 go（过去式）» (DESIGN §5.2 step 2)."""
    return f"已归为原形 {display}（{FORM_KIND_ZH.get(form_kind, FORM_KIND_ZH['alt'])}）"


# ------------------------------------------------------------------------------------------ row helpers
def _as_dict(row: sqlite3.Row | Mapping[str, Any]) -> dict[str, Any]:
    if isinstance(row, sqlite3.Row):
        return {k: row[k] for k in row.keys()}
    return dict(row)


def word_row(conn: sqlite3.Connection, word_id: int) -> dict[str, Any] | None:
    row = conn.execute("SELECT * FROM words WHERE id = ?", (int(word_id),)).fetchone()
    return None if row is None else _as_dict(row)


def word_by_lemma(conn: sqlite3.Connection, lemma: str) -> dict[str, Any] | None:
    row = conn.execute("SELECT * FROM words WHERE lemma = ?", (lemma,)).fetchone()
    return None if row is None else _as_dict(row)


def follow_merge(conn: sqlite3.Connection, row: sqlite3.Row | Mapping[str, Any]) -> tuple[dict[str, Any], str | None]:
    """Follow ``merged_into_word_id`` (bounded); returns the final row and the original lemma when a hop was taken."""
    r = _as_dict(row)
    origin = str(r["lemma"])
    hops = 0
    while r.get("merged_into_word_id") is not None and hops < MAX_MERGE_HOPS:
        nxt = word_row(conn, int(r["merged_into_word_id"]))
        if nxt is None or nxt["id"] == r["id"]:
            break
        r = nxt
        hops += 1
    return r, (origin if hops else None)


def stages_of(row: Mapping[str, Any]) -> list[str]:
    return [s for s in STAGES if int(row.get(f"stage_{s}") or 0)]


def translation_short(translation: str | None) -> str:
    """First translation line, ≤ 60 chars (API.md §9.1)."""
    for line in (translation or "").split("\n"):
        line = line.strip()
        if line:
            return line if len(line) <= TRANSLATION_SHORT_LEN else line[: TRANSLATION_SHORT_LEN - 1] + "…"
    return ""


def _bool_or_none(v: Any) -> bool | None:
    return None if v is None else bool(int(v))


def is_visible(conn: sqlite3.Connection, word: int | Mapping[str, Any] | sqlite3.Row, user_id: int) -> bool:
    """The API.md §1 visibility rule for one word (admins see everything). Mirrors ``deps.visible_word_sql``."""
    r = word_row(conn, int(word)) if isinstance(word, int) else _as_dict(word)
    if r is None:
        return False
    if int(r["is_public"] or 0) == 1 or r.get("created_by_user_id") == user_id:
        return True
    if conn.execute("SELECT 1 FROM user_words WHERE user_id = ? AND word_id = ?", (user_id, r["id"])).fetchone():
        return True
    role = conn.execute("SELECT role FROM users WHERE id = ?", (user_id,)).fetchone()
    return role is not None and role[0] == "admin"


# ------------------------------------------------------------------------------------------ DTO builders
def _my_state(conn: sqlite3.Connection, word_id: int, user_id: int) -> str | None:
    row = conn.execute("SELECT state FROM user_words WHERE user_id = ? AND word_id = ?", (user_id, word_id)).fetchone()
    return None if row is None else str(row[0])


def word_brief(conn: sqlite3.Connection, row: sqlite3.Row | Mapping[str, Any], user_id: int) -> dict[str, Any]:
    """API.md ``WordBrief`` from a ``words`` row. A row that already carries ``my_state`` (joined by the caller) is used
    as is; otherwise the user's ``user_words.state`` is looked up."""
    r = _as_dict(row)
    my_state = r["my_state"] if "my_state" in r else _my_state(conn, int(r["id"]), user_id)
    return {
        "id": int(r["id"]),
        "lemma": r["lemma"],
        "display": r["display"],
        "kind": r["kind"],
        "phonetic": r.get("phonetic") or None,
        "translation_short": translation_short(r.get("translation")),
        "stages": stages_of(r),
        "stage_min": r.get("stage_min"),
        "cet6_star": bool(r.get("cet6_star") or 0),
        "frq": r.get("frq"),
        "collins": r.get("collins"),
        "oxford": _bool_or_none(r.get("oxford")),
        "difficulty": r.get("difficulty"),
        "is_public": bool(int(r.get("is_public") or 0)),
        "is_valid_english": _bool_or_none(r.get("is_valid_english")),
        "my_state": my_state,
        "content_state": r.get("content_state") or "none",
        "image_state": r.get("image_state") or "none",
    }


def word_briefs(conn: sqlite3.Connection, rows: Iterable[sqlite3.Row | Mapping[str, Any]], user_id: int) -> list[dict[str, Any]]:
    """``word_brief`` for a list with one ``user_words`` query (lists of up to a page)."""
    dicts = [_as_dict(r) for r in rows]
    missing = [int(r["id"]) for r in dicts if "my_state" not in r]
    states: dict[int, str] = {}
    for chunk_start in range(0, len(missing), 500):
        chunk = missing[chunk_start : chunk_start + 500]
        marks = ",".join("?" * len(chunk))
        for wid, state in conn.execute(
            f"SELECT word_id, state FROM user_words WHERE user_id = ? AND word_id IN ({marks})", (user_id, *chunk)
        ):
            states[int(wid)] = str(state)
    out = []
    for r in dicts:
        if "my_state" not in r:
            r["my_state"] = states.get(int(r["id"]))
        out.append(word_brief(conn, r, user_id))
    return out


def mastery_suggested(srs: Mapping[str, Any]) -> bool:
    """API.md §9.1: ``step == 0 and interval_days >= 30 and consecutive_good >= 3`` (server computed)."""
    return int(srs.get("step") or 0) == 0 and int(srs.get("interval_days") or 0) >= 30 and int(srs.get("consecutive_good") or 0) >= 3


def user_word_dict(conn: sqlite3.Connection, row: sqlite3.Row | Mapping[str, Any], user_id: int | None = None) -> dict[str, Any]:
    """API.md ``UserWord`` from a ``user_words`` row (``suggested_word`` resolved to a ``WordBrief``)."""
    r = _as_dict(row)
    uid = int(user_id if user_id is not None else r["user_id"])
    suggested = None
    if r.get("suggested_word_id") is not None:
        srow = word_row(conn, int(r["suggested_word_id"]))
        if srow is not None:
            suggested = word_brief(conn, srow, uid)
    srs = {
        "ease": float(r["ease"]),
        "interval_days": int(r["interval_days"]),
        "step": int(r["step"]),
        "repetitions": int(r["repetitions"]),
        "lapses": int(r["lapses"]),
        "consecutive_good": int(r["consecutive_good"]),
        "due_at": r.get("due_at"),
        "last_graded_at": r.get("last_graded_at"),
    }
    srs["mastery_suggested"] = mastery_suggested(srs)
    return {
        "id": int(r["id"]),
        "word_id": int(r["word_id"]),
        "state": r["state"],
        "origin": r["origin"],
        "priority": int(r["priority"]),
        "note": r.get("note"),
        "input_text": r.get("input_text"),
        "needs_attention": bool(int(r.get("needs_attention") or 0)),
        "attention_msg": r.get("attention_msg"),
        "suggested_word": suggested,
        "srs": srs,
        "times_pushed": int(r.get("times_pushed") or 0),
        "times_added": int(r.get("times_added") or 1),
        "added_at": r["added_at"],
        "first_added_at": r["first_added_at"],
        "mastered_at": r.get("mastered_at"),
    }


def my_user_word(conn: sqlite3.Connection, word_id: int, user_id: int) -> dict[str, Any] | None:
    """The user's ``UserWord`` for a word, or None."""
    row = conn.execute("SELECT * FROM user_words WHERE user_id = ? AND word_id = ?", (user_id, word_id)).fetchone()
    return None if row is None else user_word_dict(conn, row, user_id)


def forms_with_kind(conn: sqlite3.Connection, word_id: int) -> list[dict[str, str]]:
    """``WordDetail.word.forms`` — ``[{form, kind}]`` ordered p d i 3 s r t alt, then alphabetically."""
    return [
        {"form": str(r[0]), "kind": str(r[1])}
        for r in conn.execute(f"SELECT form, kind FROM word_forms WHERE word_id = ? ORDER BY {_form_kind_order()}, form", (word_id,))
    ]


def forms_of(conn: sqlite3.Connection, word_id: int) -> list[str]:
    """Inflections of a word (TASKS §I) in the same order as :func:`forms_with_kind`."""
    return [f["form"] for f in forms_with_kind(conn, word_id)]


def word_forms_of_lemma(conn: sqlite3.Connection, lemma: str) -> set[str]:
    """The ``word_forms`` of the word whose lemma is ``lemma`` (CLAUDE_INTEGRATION §6.5 ``word_forms_of``)."""
    return {
        str(r[0])
        for r in conn.execute("SELECT wf.form FROM word_forms wf JOIN words w ON w.id = wf.word_id WHERE w.lemma = ?", (lemma,))
    }


def confusables_for(conn: sqlite3.Connection, user_id: int, lemma: str) -> list[str]:
    """API.md §9.1 ``confusables``: union of ``payload.group`` over this user's ``bank_suggestions`` rows with
    ``type='confusable_group' AND status='accepted'`` whose group contains ``lemma``, minus the lemma, de-duplicated,
    ≤ 6, in insertion order (``created_at, id``)."""
    rows = conn.execute(
        "SELECT payload_json FROM bank_suggestions "
        "WHERE user_id = ? AND type = 'confusable_group' AND status = 'accepted' AND json_valid(payload_json) "
        "AND EXISTS (SELECT 1 FROM json_each(bank_suggestions.payload_json, '$.group') WHERE json_each.value = ?) "
        "ORDER BY created_at, id",
        (user_id, lemma),
    ).fetchall()
    out: list[str] = []
    seen = {lemma}
    for (payload,) in rows:
        try:
            group = json.loads(payload).get("group")
        except (ValueError, AttributeError):
            continue
        if not isinstance(group, list):
            continue
        for member in group:
            if not isinstance(member, str):
                continue
            m = member.strip()
            if m and m not in seen:
                seen.add(m)
                out.append(m)
                if len(out) >= MAX_CONFUSABLES:
                    return out
    return out


def content_deferred_until(conn: sqlite3.Connection, word_id: int, *, now: str | None = None, cfg: Any = None) -> str | None:
    """API.md 24 ``deferred_until``: the live ``generate_content`` job's ``run_after`` when it lies more than 5 minutes
    ahead (budget deferral), else the instant AI may serve content again, else None.

    With ``cfg`` the pause question is CLAUDE_INTEGRATION §10's "any provider" rule for the content kind
    (``failover.availability``): a paused CLI with a fallback that may serve content is not a pause. Without ``cfg``
    the legacy answer applies — ``kv.claude.paused_until`` or the admin's global pause (``budget.paused_until``).
    """
    now = now or now_iso()
    job = queue.live_job(conn, f"content:{int(word_id)}")
    if job is not None and job.run_after > to_iso(parse_iso(now) + timedelta(seconds=DEFERRAL_THRESHOLD_S)):
        return str(job.run_after)
    from ..ai import budget  # local import: services → ai must not become a module cycle at import time

    if cfg is not None:
        from ..ai import failover

        avail = failover.availability(conn, cfg, kind="content", now=now, priority=job.priority if job is not None else 20)
        if avail.ok:
            return None
        return avail.resumes_at or budget.paused_until(conn, now)
    return budget.paused_until(conn, now)  # kv.claude.paused_until or the admin's global pause (CLAUDE_INTEGRATION §10)


def active_content(conn: sqlite3.Connection, row: Mapping[str, Any]) -> dict[str, Any] | None:
    """The validated ``Content`` object of ``words.active_content_id`` (None when absent or not active)."""
    cid = row.get("active_content_id")
    if cid is None:
        return None
    c = conn.execute("SELECT content_json FROM word_contents WHERE id = ? AND status = 'active'", (int(cid),)).fetchone()
    if c is None:
        return None
    try:
        data = json.loads(c[0])
    except ValueError:
        log.warning("word %s has unparsable content_json in word_contents %s", row.get("id"), cid)
        return None
    return data if isinstance(data, dict) else None


def card_image_meta(word_id: int) -> dict[str, Any]:
    """The template-card ``ImageMeta`` (API.md §9.1: never null)."""
    return {
        "id": None,
        "url": f"/media/card/{int(word_id)}.svg",
        "kind": "card",
        "provider": "card_svg",
        "mime": "image/svg+xml",
        "width": 800,
        "height": 500,
        "alt_zh": None,
        "attribution": None,
    }


def image_meta_for(conn: sqlite3.Connection, word_id: int) -> dict[str, Any]:
    """``ImageMeta`` of the word's active photo / Claude SVG through WP6's ``images.image_meta`` (itself falling back to
    the card when nothing is active); the card is also served when the image layer fails (API.md §9.1: never null)."""
    try:
        meta = images.image_meta(conn, int(word_id))
        if isinstance(meta, dict):
            return meta
    except Exception:  # noqa: BLE001 - the card is the documented fallback for any image-layer problem
        log.exception("images.image_meta failed for word %s; serving the card", word_id)
    return card_image_meta(word_id)


def history_for(conn: sqlite3.Connection, user_id: int, word_id: int, limit: int = HISTORY_LIMIT) -> list[dict[str, Any]]:
    """``WordDetail.history`` — the user's last ``limit`` ``review_logs`` rows on the word (``ReviewLogItem``)."""
    rows = conn.execute(
        "SELECT id, created_at, action, context, prev_state, new_state, prev_interval, new_interval FROM review_logs "
        "WHERE user_id = ? AND word_id = ? ORDER BY created_at DESC, id DESC LIMIT ?",
        (user_id, word_id, int(limit)),
    ).fetchall()
    return [_as_dict(r) for r in rows]


def word_detail(conn: sqlite3.Connection, word_id: int, user_id: int, *, now: str | None = None) -> dict[str, Any]:
    """API.md ``WordDetail`` for ``word_id`` as seen by ``user_id``.

    Follows ``merged_into_word_id`` (``redirected_from`` = the merged lemma), fills ``word.forms``, ``word.confusables``
    (:func:`confusables_for`), ``content`` / ``content_state`` / ``content_deferred_until`` (API.md 24), ``image``
    (card fallback), ``mine`` and ``history``. Raises ``ApiError('word_not_found')`` when the word does not exist or is
    outside the API.md §1 visibility rule for this user.
    """
    row = word_row(conn, word_id)
    if row is None:
        raise ApiError("word_not_found")
    final, redirected = follow_merge(conn, row)
    if not is_visible(conn, final, user_id):
        raise ApiError("word_not_found")
    wid = int(final["id"])
    word = word_brief(conn, final, user_id)
    word.update(
        {
            "definition": final.get("definition") or None,
            "translation": final.get("translation") or None,
            "pos": final.get("pos") or None,
            "exam_tags": (final.get("exam_tags") or "").split(),
            "bnc": final.get("bnc"),
            "forms": forms_with_kind(conn, wid),
            "source": final["source"],
            "confusables": confusables_for(conn, user_id, str(final["lemma"])),
        }
    )
    content_state = final.get("content_state") or "none"
    return {
        "word": word,
        "content": active_content(conn, final),
        "content_state": content_state,
        "content_deferred_until": content_deferred_until(conn, wid, now=now) if content_state == "queued" else None,
        "image": image_meta_for(conn, wid),
        "mine": my_user_word(conn, wid, user_id),
        "redirected_from": redirected,
        "history": history_for(conn, user_id, wid),
    }


# --------------------------------------------------------------------------------------------- resolution
Via = Literal["exact", "form", "ambiguous", "ecdict", "provisional"]


@dataclass
class Resolution:
    """Outcome of :func:`resolve` (DESIGN §5.2). ``word_id`` is None only for ``via='ambiguous'``, where
    ``candidates`` holds the ``WordBrief`` dicts of the possible headwords (alphabetical, never ranked by frequency).
    ``created`` says whether a ``words`` row was inserted (ecdict/provisional); ``job_id`` is the ``lookup_word`` job
    enqueued for a provisional (or ``[网络]``-only ECDICT) word; ``is_valid_english`` / ``is_public`` mirror the resolved
    row so the caller can apply the DESIGN §5.2 attention rule for ``is_valid_english = 0`` hits."""

    via: Via
    word_id: int | None
    candidates: list[dict[str, Any]] = field(default_factory=list)
    lemma_note_zh: str | None = None
    created: bool = False
    job_id: int | None = None
    redirected_from: str | None = None
    is_valid_english: int | None = None
    is_public: int | None = None

    @property
    def ambiguous(self) -> bool:
        return self.via == "ambiguous"

    @property
    def candidate_ids(self) -> list[int]:
        return [int(c["id"]) for c in self.candidates]


def _word_defaults() -> dict[str, Any]:
    return {
        "phonetic": None,
        "translation": None,
        "definition": None,
        "pos": None,
        "collins": None,
        "oxford": None,
        "exam_tags": None,
        "bnc": None,
        "frq": None,
        "exchange_json": None,
        **{f"stage_{s}": 0 for s in STAGE_ORDER},  # a user/ECDICT word is in no official list until the seed says so
        "stage_min": None,
        "cet6_star": 0,
        "sources": None,
        "ecdict_id": None,
        "difficulty": None,
        "created_by_user_id": None,
    }


# the columns of a words row the resolver writes, in DDL order; the five stage flags follow STAGE_ORDER (0011)
_INSERT_WORD_COLUMNS: tuple[str, ...] = (
    "lemma", "display", "kind", "phonetic", "translation", "definition", "pos", "collins", "oxford", "exam_tags", "bnc", "frq",
    "exchange_json", *(f"stage_{s}" for s in STAGE_ORDER), "stage_min", "cet6_star", "sources", "ecdict_id", "source",
    "is_public", "is_valid_english", "safe_for_sharing", "difficulty", "created_by_user_id",
)  # fmt: skip
_INSERT_WORD_SQL = (
    f"INSERT INTO words({', '.join(_INSERT_WORD_COLUMNS)}, created_at, updated_at) "
    f"VALUES ({', '.join(':' + c for c in _INSERT_WORD_COLUMNS)}, :now, :now) "
    "ON CONFLICT(lemma) DO NOTHING"
)


def _insert_word(conn: sqlite3.Connection, cols: Mapping[str, Any]) -> tuple[dict[str, Any], bool]:
    """Insert a ``words`` row unless its lemma exists (UNIQUE lemma race-safe); returns ``(row, created)``."""
    cur = conn.execute(_INSERT_WORD_SQL, dict(cols))
    created = cur.rowcount == 1
    row = word_by_lemma(conn, str(cols["lemma"]))
    if row is None:  # pragma: no cover - the lemma was just inserted or already existed
        raise RuntimeError(f"words row for lemma {cols['lemma']!r} vanished during insert")
    return row, created


def enqueue_lookup(conn: sqlite3.Connection, word_id: int, now: str | None = None, *, delay_s: int = LOOKUP_DEBOUNCE_S, priority: int = LOOKUP_PRIORITY) -> int:
    """Enqueue ``lookup_word {word_id}`` (dedupe ``lookup:<id>``, priority 10, ``run_after = now + 20 s`` — DESIGN §5.2 step 4).
    The UPSERT folds repeated calls into the live job; returns its id."""
    now = now or now_iso()
    run_after = to_iso(parse_iso(now) + timedelta(seconds=delay_s)) if delay_s else now
    return queue.enqueue(conn, "lookup_word", {"word_id": int(word_id)}, dedupe_key=f"lookup:{int(word_id)}", priority=priority, run_after=run_after, now=now)


def add_form(conn: sqlite3.Connection, form: str, word_id: int, kind: str = "alt") -> bool:
    """``INSERT OR IGNORE`` a ``word_forms`` row with the headword guard (a form that is a ``words.lemma`` is never inserted)."""
    key = normalise_lemma(form)
    if not key or kind not in FORM_KINDS:
        return False
    if conn.execute("SELECT 1 FROM words WHERE lemma = ?", (key,)).fetchone():
        return False
    cur = conn.execute("INSERT OR IGNORE INTO word_forms(form, word_id, kind) VALUES (?, ?, ?)", (key, int(word_id), kind))
    return cur.rowcount == 1


def _resolution_for(via: Via, row: Mapping[str, Any], *, lemma_note: str | None = None, redirected: str | None = None, created: bool = False, job_id: int | None = None) -> Resolution:
    return Resolution(
        via=via,
        word_id=int(row["id"]),
        lemma_note_zh=lemma_note,
        created=created,
        job_id=job_id,
        redirected_from=redirected,
        is_valid_english=row.get("is_valid_english"),
        is_public=row.get("is_public"),
    )


def _resolve_forms(conn: sqlite3.Connection, key: str, user_id: int) -> Resolution | None:
    rows = conn.execute(
        f"SELECT w.*, wf.kind AS form_kind FROM word_forms wf JOIN words w ON w.id = wf.word_id WHERE wf.form = ? "
        f"ORDER BY {_form_kind_order('wf.kind')}, w.lemma",
        (key,),
    ).fetchall()
    if not rows:
        return None
    targets: dict[int, tuple[dict[str, Any], str, str | None]] = {}
    for r in rows:
        d = _as_dict(r)
        form_kind = str(d.pop("form_kind"))
        final, redirected = follow_merge(conn, d)
        targets.setdefault(int(final["id"]), (final, form_kind, redirected))
    if len(targets) == 1:
        final, form_kind, redirected = next(iter(targets.values()))
        return _resolution_for("form", final, lemma_note=lemma_note_zh(str(final["display"]), form_kind), redirected=redirected)
    ordered = sorted(targets.values(), key=lambda t: str(t[0]["lemma"]))
    return Resolution(via="ambiguous", word_id=None, candidates=[word_brief(conn, t[0], user_id) for t in ordered])


def _resolve_ecdict(conn: sqlite3.Connection, key: str, user_id: int, now: str) -> Resolution | None:
    entry = ecdict.lookup(key)
    if entry is None:
        return None
    target, form_kind = entry, None
    pointer = entry.lemma_pointer
    if pointer and not entry.has_stage_tag and not entry.frq:
        base_key = normalise_lemma(pointer)
        if base_key and base_key != key:
            base = ecdict.lookup(base_key)
            if base is not None and (base.has_stage_tag or (base.frq or 0) > 0):
                target, form_kind = base, entry.form_code
    with db.maybe_tx(conn):
        lemma = normalise_lemma(target.word) or key
        row = word_by_lemma(conn, lemma)
        created, job_id = False, None
        if row is None:
            cols = {**_word_defaults(), **target.word_columns(), "lemma": lemma, "source": "ecdict", "now": now}
            cols["kind"] = derive_kind(str(cols["display"]))
            if target.is_network_only:
                cols.update(is_public=0, is_valid_english=None, safe_for_sharing=None, created_by_user_id=user_id)
            else:
                cols.update(is_public=1, is_valid_english=1, safe_for_sharing=1, created_by_user_id=None)
            row, created = _insert_word(conn, cols)
            if created and target.is_network_only:
                job_id = enqueue_lookup(conn, int(row["id"]), now)
        note = None
        if form_kind is not None:
            add_form(conn, key, int(row["id"]), form_kind)
            note = lemma_note_zh(str(row["display"]), form_kind)
        elif lemma != key:
            add_form(conn, key, int(row["id"]), "alt")
        final, redirected = follow_merge(conn, row)
    return _resolution_for("ecdict", final, lemma_note=note, redirected=redirected, created=created, job_id=job_id)


def _create_provisional(conn: sqlite3.Connection, key: str, display: str, kind: str, user_id: int, now: str) -> Resolution:
    shown = (display or "").strip() or key
    cols = {
        **_word_defaults(),
        "lemma": key,
        "display": shown,
        "kind": kind if kind in KINDS else derive_kind(shown),
        "source": "user",
        "is_public": 0,
        "is_valid_english": None,
        "safe_for_sharing": None,
        "created_by_user_id": user_id,
        "now": now,
    }
    with db.maybe_tx(conn):
        row, created = _insert_word(conn, cols)
        if not created:  # lost the UNIQUE(lemma) race against another holder: behave like the exact step
            final, redirected = follow_merge(conn, row)
            return _resolution_for("exact", final, redirected=redirected, job_id=_ensure_lookup(conn, final, now))
        job_id = enqueue_lookup(conn, int(row["id"]), now)
    return _resolution_for("provisional", row, created=True, job_id=job_id)


def _ensure_lookup(conn: sqlite3.Connection, row: Mapping[str, Any], now: str) -> int | None:
    """A hit on a word that is still ``is_valid_english IS NULL`` must have a live ``lookup_word`` job, or nothing is left
    to validate it (the first holder's job died, or the row was created without one): the new holder enqueues it. The
    pre-check only saves a write per add — the UPSERT folds repeats into the live job anyway. Returns the new job id."""
    if row.get("is_valid_english") is not None or row.get("merged_into_word_id") is not None:
        return None
    wid = int(row["id"])
    if queue.live_job(conn, f"lookup:{wid}") is not None:
        return None
    with db.maybe_tx(conn):
        return enqueue_lookup(conn, wid, now)


def resolve(conn: sqlite3.Connection, key: str, display: str, kind: str, user_id: int, *, now: str | None = None) -> Resolution:
    """DESIGN §5.2 lemma resolution, first hit wins: **exact** (``words.lemma``, following merges) → **form**
    (``word_forms``; one lemma → ``lemma_note_zh``, several → ``via='ambiguous'`` with candidates, nothing created) →
    **ecdict** (only while ``WD_ECDICT_DB_PATH`` is set) → **provisional** (private ``words`` row created by ``user_id``
    plus one debounced ``lookup_word`` job). ``key``/``display``/``kind`` come from :func:`normalise_input`.

    ``now`` (ISO, keyword-only; added at integration on top of the TASKS §I signature) is the app clock used for the
    created rows and the lookup debounce (``run_after = now + 20 s``); it defaults to the system clock.
    """
    key = normalise_lemma(key) or ""
    if not key:
        raise ValueError("resolve(): key must be a normalised, non-empty lemma")
    now = now or now_iso()
    row = word_by_lemma(conn, key)
    if row is not None:
        final, redirected = follow_merge(conn, row)
        return _resolution_for("exact", final, redirected=redirected, job_id=_ensure_lookup(conn, final, now))
    res = _resolve_forms(conn, key, user_id)
    if res is not None:
        return res
    res = _resolve_ecdict(conn, key, user_id, now)
    if res is not None:
        return res
    return _create_provisional(conn, key, display, kind, user_id, now)


# ------------------------------------------------------------------------------------- headword validation
_SUFFIXES: tuple[str, ...] = ("iest", "ies", "ied", "ier", "ing", "est", "es", "ed", "er", "s", "d")
_VOWELS = frozenset("aeiou")


def suffix_rule_maps(inflected: str, base: str) -> bool:
    """CLAUDE_INTEGRATION §6.5 suffix rules: ``inflected`` reduces to ``base`` through ``ies→y``, ``s``, ``es``, ``ed``,
    ``d``, ``ing``, ``er``, ``est`` (also ``ied/ier/iest→y``), an optional dropped ``e`` (making→make) or a doubled
    consonant (running→run, bigger→big)."""
    a = (inflected or "").strip().lower()
    b = (base or "").strip().lower()
    if not a or not b or a == b:
        return False
    for suf in _SUFFIXES:
        if not a.endswith(suf) or len(a) - len(suf) < 2:
            continue
        stem = a[: -len(suf)]
        cands = {stem}
        if suf[0] == "i" and suf != "ing":
            cands.add(stem + "y")
        if suf in ("ing", "ed", "er", "est", "d"):
            cands.add(stem + "e")
        if len(stem) >= 3 and stem[-1] == stem[-2] and stem[-1] not in _VOWELS:
            cands.add(stem[:-1])
        if b in cands:
            return True
    return False


def validate_headword(proposed: str, input_lemma: str, conn: sqlite3.Connection) -> Normalised | None:
    """CLAUDE_INTEGRATION §6.5: a Claude-proposed headword may touch shared data only if it normalises like user input
    (charset/length/tokens) **and** is related to the input: equal, the input is one of the target's ``word_forms``,
    a suffix rule maps the input onto it, or they share the first three letters. Returns the ``Normalised`` to use
    (``lemma``/``display``/``kind``) or None."""
    norm = normalise_input(proposed)
    if not norm.ok:
        return None
    assert isinstance(norm, Normalised)
    inp = normalise_lemma(input_lemma) or ""
    if not inp:
        return None
    lemma = norm.lemma
    if lemma == inp:
        return norm
    if inp in word_forms_of_lemma(conn, lemma):
        return norm
    if suffix_rule_maps(inp, lemma):
        return norm
    if inp[:3] == lemma[:3]:
        return norm
    return None


__all__ = [
    "Invalid",
    "Normalised",
    "Resolution",
    "active_content",
    "add_form",
    "card_image_meta",
    "confusables_for",
    "content_deferred_until",
    "derive_kind",
    "enqueue_lookup",
    "follow_merge",
    "forms_of",
    "forms_with_kind",
    "history_for",
    "image_meta_for",
    "is_visible",
    "lemma_note_zh",
    "mastery_suggested",
    "my_user_word",
    "normalise_input",
    "normalise_lemma",
    "resolve",
    "stages_of",
    "suffix_rule_maps",
    "translation_short",
    "user_word_dict",
    "validate_headword",
    "word_brief",
    "word_briefs",
    "word_by_lemma",
    "word_detail",
    "word_forms_of_lemma",
    "word_row",
]
