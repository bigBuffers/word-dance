"""Optional full-ECDICT lookup (WP1) — DESIGN §5.2 step 3.

:func:`lookup` queries the ``stardict`` table of the ECDICT ``stardict.db`` named by ``WD_ECDICT_DB_PATH``
(``SELECT … WHERE word = :key COLLATE NOCASE``). It returns ``None`` whenever the variable is unset, the file is
missing, the query fails or no row exists, so :func:`wd.services.words.resolve` can always call it and fall through
to the provisional step. The database is opened read-only per call — the file is an 851 MB read-only artefact and a
lookup is one indexed SELECT, so there is no shared connection to protect across request threads.

The record → ``words`` column mapping (:meth:`EcdictEntry.word_columns`) mirrors the seed builder (``norm_phonetic`` /
``parse_exchange`` / the field list) so an ECDICT-derived row looks like a seed row — except for the stage flags: since
the official word lists became the only source of 小学/初中/高中 membership (PLAN R-10 / SM D-14), ECDICT's ``zk``/``gk``
tags no longer grant a stage at runtime; only :data:`MEMBER_TAGS` (``cet4``/``cet6``) do. :data:`STAGE_TAGS` keeps all four
tag names for :attr:`EcdictEntry.has_stage_tag` ("carries any exam-stage tag"), which ``words.resolve`` uses to decide
whether an inflected ECDICT row points back to its lemma — that heuristic is unchanged.
Rows whose only translation lines start with ``[网络]`` (network slang of doubtful validity) are flagged by
:attr:`EcdictEntry.is_network_only`; the resolver creates those as private provisional words (DESIGN §5.2).
"""

from __future__ import annotations

import json
import logging
import os
import sqlite3
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping

from ..schemas import STAGE_ORDER, stage_to_index

log = logging.getLogger("wd.ecdict")

ENV_VAR = "WD_ECDICT_DB_PATH"
STAGE_TAGS: tuple[str, ...] = ("zk", "gk", "cet4", "cet6")  # ECDICT's exam-stage tag names (has_stage_tag); NOT the stage enum
MEMBER_TAGS: tuple[str, ...] = ("cet4", "cet6")  # the tags that still grant a words.stage_* flag at runtime (PLAN R-10)
EXAM_TAGS: tuple[str, ...] = ("ky", "toefl", "ielts", "gre")
FORM_CODES: tuple[str, ...] = ("p", "d", "i", "3", "s", "r", "t")  # word_forms.kind values derived from ECDICT exchange codes
NETWORK_PREFIX = "[网络]"
COLUMNS = "id, word, phonetic, definition, translation, pos, collins, oxford, tag, bnc, frq, exchange"

# the builder's phonetic normalisation (scripts/build_seed.py norm_phonetic), applied in this order
_PHONETIC_MAP: tuple[tuple[str, str], ...] = (
    ("ә", "ə"),
    ("ɒ:", "ɔː"),
    ("ɔ:", "ɔː"),
    ("i:", "iː"),
    ("u:", "uː"),
    ("ɑ:", "ɑː"),
    ("ә:", "əː"),
    ("ə:", "ɜː"),
)


def norm_phonetic(p: str | None) -> str:
    """``ә→ə``, ``:→ː`` normalisation exactly as the seed builder does it."""
    if not p:
        return ""
    for src, dst in _PHONETIC_MAP:
        p = p.replace(src, dst)
    return p.strip()


def parse_exchange(s: str | None) -> dict[str, str]:
    """``'p:went/d:gone/…'`` → ``{'p': 'went', 'd': 'gone', …}`` (builder semantics; malformed parts are skipped)."""
    out: dict[str, str] = {}
    if not s:
        return out
    for part in s.split("/"):
        if ":" in part:
            k, v = part.split(":", 1)
            out[k] = v
    return out


def _lines(text: str | None) -> list[str]:
    return [s.strip() for s in (text or "").replace("\r", "").split("\n") if s.strip()]


def _int(v: Any) -> int | None:
    if v is None or v == "":
        return None
    try:
        return int(v)
    except (TypeError, ValueError):
        return None


@dataclass(frozen=True)
class EcdictEntry:
    """One ``stardict`` row in the shape the seed builder produces."""

    ecdict_id: int
    word: str
    phonetic: str
    translation: str  # zh lines joined by '\n' ('' when absent)
    definition: str  # en lines joined by '\n'
    pos: str
    collins: int
    oxford: int
    tags: tuple[str, ...]
    bnc: int | None
    frq: int | None
    exchange: Mapping[str, str]

    @classmethod
    def from_row(cls, row: sqlite3.Row | tuple) -> "EcdictEntry":
        (id_, word, phonetic, definition, translation, pos, collins, oxford, tag, bnc, frq, exchange) = tuple(row)
        return cls(
            ecdict_id=int(id_),
            word=str(word or "").strip(),
            phonetic=norm_phonetic(phonetic),
            translation="\n".join(_lines(translation)),
            definition="\n".join(_lines(definition)),
            pos=str(pos or "").strip(),
            collins=_int(collins) or 0,
            oxford=_int(oxford) or 0,
            tags=tuple(str(tag or "").split()),
            bnc=_int(bnc),
            frq=_int(frq),
            exchange=parse_exchange(exchange),
        )

    # ------------------------------------------------------------------ derived
    @property
    def stages(self) -> list[str]:
        """Stage codes this row grants (``STAGE_ORDER`` order): only the CET tags; ``zk``/``gk`` come from the official lists."""
        return [s for s in STAGE_ORDER if s in MEMBER_TAGS and s in self.tags]

    @property
    def has_stage_tag(self) -> bool:
        """True when the row carries any of ECDICT's four exam-stage tags — the lemma-pointer heuristic of ``words.resolve``
        (an inflection whose row has no tag and no frequency points back to its lemma); deliberately wider than :attr:`stages`."""
        return any(t in self.tags for t in STAGE_TAGS)

    @property
    def exam_tags(self) -> list[str]:
        return [t for t in self.tags if t in EXAM_TAGS]

    @property
    def translation_lines(self) -> list[str]:
        return _lines(self.translation)

    @property
    def definition_lines(self) -> list[str]:
        return _lines(self.definition)

    @property
    def is_network_only(self) -> bool:
        """True when every translation line starts with ``[网络]`` (and there is at least one) — DESIGN §5.2 step 3."""
        lines = self.translation_lines
        return bool(lines) and all(line.startswith(NETWORK_PREFIX) for line in lines)

    @property
    def lemma_pointer(self) -> str | None:
        """The ``0:<lemma>`` exchange pointer (this row is an inflection of ``<lemma>``), or None."""
        v = (self.exchange.get("0") or "").strip()
        return v or None

    @property
    def form_code(self) -> str:
        """``word_forms.kind`` for this row as an inflection of :attr:`lemma_pointer` (from the ``1:`` code; ``alt`` otherwise)."""
        codes = (self.exchange.get("1") or "").strip()
        for c in codes:
            if c in FORM_CODES:
                return c
        return "alt"

    def word_columns(self) -> dict[str, Any]:
        """Dictionary columns of a ``words`` row (DESIGN §3.2 mapping); the caller adds lemma/kind/source/flags."""
        stages = self.stages
        return {
            "display": self.word,
            "phonetic": self.phonetic or None,
            "translation": self.translation or None,
            "definition": self.definition or None,
            "pos": self.pos or None,
            "collins": self.collins,
            "oxford": self.oxford,
            "exam_tags": " ".join(self.exam_tags) or None,
            "bnc": self.bnc,
            "frq": self.frq,
            "exchange_json": json.dumps(dict(self.exchange), ensure_ascii=False, sort_keys=True) if self.exchange else None,
            **{f"stage_{s}": int(s in stages) for s in STAGE_ORDER},
            "stage_min": min(stage_to_index(s) for s in stages) if stages else None,
            "cet6_star": 0,
            "sources": "ecdict",
            "ecdict_id": self.ecdict_id,
        }


# --------------------------------------------------------------------------------------------- lookup
def configured_path(env: Mapping[str, str] | None = None) -> Path | None:
    """``WD_ECDICT_DB_PATH`` as a Path, or None when unset/empty (the feature is optional, DEPLOY §4)."""
    raw = (os.environ if env is None else env).get(ENV_VAR, "").strip()
    return Path(raw).expanduser() if raw else None


def lookup(key: str, *, db_path: str | Path | None = None) -> EcdictEntry | None:
    """``SELECT … FROM stardict WHERE word = :key COLLATE NOCASE`` on the configured ECDICT database.

    Returns None when the feature is not configured, the file is missing, the query fails (logged) or no row
    matches. ``db_path`` overrides the environment (tests, ``wd check``).
    """
    key = (key or "").strip()
    path = Path(db_path).expanduser() if db_path else configured_path()
    if path is None or not key:
        return None
    if not path.is_file():
        log.warning("%s points at %s, which does not exist; ECDICT lookups are skipped", ENV_VAR, path)
        return None
    try:
        conn = sqlite3.connect(path.resolve().as_uri() + "?mode=ro", uri=True, timeout=2.0)
    except sqlite3.Error as e:
        log.warning("cannot open the ECDICT database %s: %s", path, e)
        return None
    try:
        row = conn.execute(
            f"SELECT {COLUMNS} FROM stardict WHERE word = ? COLLATE NOCASE ORDER BY id LIMIT 1",
            (key,),
        ).fetchone()
    except sqlite3.Error as e:
        log.warning("ECDICT lookup of %r failed: %s", key, e)
        return None
    finally:
        conn.close()
    return None if row is None else EcdictEntry.from_row(row)
