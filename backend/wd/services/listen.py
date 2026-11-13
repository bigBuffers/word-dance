"""磨耳朵 — today's words as a listening playlist (API.md endpoint 123 ``ListenPlaylist``; docs/LISTEN_MODE_DESIGN.md §3.2 / §4.3,
DESIGN §6.6).

The study DTO is written for a card, not for a voice: ``meaning_zh`` carries part-of-speech labels, brackets and several senses
(``v. 分享；共用 n. 一份；股份``, ``adv./prep. 在船(飞机、车)上``), a headword may carry dictionary shorthand (``give sb. a hand``)
and a word has two to four example sentences. Read out as they are, a learner would hear 「v 点 分享 …」. This module derives,
per word, exactly what a voice should say — the headword spelled out (:func:`spoken_headword`), a short gloss
(:func:`speakable_gloss`) and ONE example sentence with its translation (:func:`pick_sentence`) — and every string it hands out
has passed the text rule of ``GET /media/audio`` (``wd.audio.normalize_text``), so the player never asks endpoint 76 for a clip it
would refuse; what cannot be spoken is ``null`` and the player skips that segment.

Everything is rule-derived from strings that are already stored: no prompt change (the whole library is pre-generated), no
regeneration, no schema change. :func:`playlist` is read-only — 磨耳朵 grades nothing, moves no review interval and leaves no
trace in ``daily_stats``.
"""

from __future__ import annotations

import re
import sqlite3
from datetime import datetime
from typing import Any, Mapping

from .. import audio
from ..clock import local_date as clock_local_date
from . import bank, batches, words

GLOSS_SENSES = 2  # senses read out per word: the main one and one more — a third is a list, not a gloss
GLOSS_MAX_CHARS = 40  # of the spoken gloss (≈ 6 s of Chinese at most)

# dictionary shorthand in a headword, spelled out for the voice (the seed has `give sb. a hand`, `talk to sb.`; custom words add
# `sth.` and the possessive): `sb's` / `sb.'s` → somebody's, `sb.` → somebody, `sth.` → something
_SHORTHAND: tuple[tuple[re.Pattern[str], str], ...] = (
    (re.compile(r"\bsb\.?(?=['’]s\b)"), "somebody"),
    (re.compile(r"\bsb\.(?!\w)"), "somebody"),
    (re.compile(r"\bsth\.(?!\w)"), "something"),
)
# the part-of-speech labels of a Chinese dictionary line, alone or in a run (`adv./prep. `, `vt.& vi. `, ECDICT's `vt.vi. `): the
# one-letter `n.` `v.` `a.` and ANY lower-case abbreviation of two to seven letters with its dot — the content prompt's (`adj.`,
# `prep.`), every one ECDICT uses in the seed (`ad.`, `vt.`, `na.`, `un.`, `pref.` …) and whatever else a model writes in that
# style (`phr.`, `excl.`, `quant.`: the generated library cannot be listed here, and a label read aloud is 「p h r 照顾」). Not the
# shorthand `sb.` / `sth.`, not a capitalised abbreviation (`Mr.`, `U.S.`), and the run must not lead into a letter, so `a.m.` is
# no label
_POS_RUN = r"(?:(?:[nva]|(?!sb\.|sth\.)[a-z]{2,7})\.\s*(?:[/&]\s*)?)+(?![A-Za-z])"
_POS_LABELS = re.compile("^" + _POS_RUN)
# a sense ends at `;` / `；` / a line break, at a comma (`，` `,` `、` — ECDICT separates synonyms with `, `), at a slash (`他/她`,
# `相连/联系`: the Chinese voice of `say` reads a slash out as 「斜杠」) or before the next part-of-speech group (`v. 放弃 n. 放纵`):
# ai/dance._SENSE_SPLIT widened by the commas, the slashes and the label runs
_SENSE_SPLIT = re.compile(rf"[；;\n，,、/／]|\s+(?={_POS_RUN})")
# bracketed asides are for the eye — `在船(飞机、车)上`, `（gross domestic product 的缩写）`, ECDICT's `[计]` / `<口>` — innermost first.
# A round pair may mix widths (`使（某人)高兴`, `(使）高兴` — a common slip in model-written Chinese): either closer ends either
# opener, or the pair would count as cut off below and take the rest of its sense with it
_BRACKETED = re.compile(r"[（(][^（）()]*[）)]|\[[^\[\]]*\]|【[^【】]*】|<[^<>]*>")
_UNCLOSED = re.compile(r"[（(\[【<][^；;\n]*")  # an aside cut off by the 120-char limit of meaning_zh: gone up to the end of its sense
_STRAY_CLOSERS = re.compile(r"[）)\]】>]")
_EDGES = re.compile(r"^\W+|\W+$")  # whatever is not a letter, a digit or a Han character at either end of a sense: punctuation, `+`, `=`, spaces


def spoken_headword(display: str) -> str | None:
    """``display`` as a voice should read it — ``sb.`` / ``sth.`` / ``sb's`` spelled out (``give sb. a hand`` → ``give somebody a
    hand``) — when the English rule of endpoint 76 accepts the result, else None (the player then has no word segment)."""
    text = str(display or "")
    for pattern, spoken in _SHORTHAND:
        text = pattern.sub(spoken, text)
    return audio.normalize_text(text)


def _without_brackets(text: str) -> str:
    previous = None
    while previous != text:  # innermost first, until nothing balanced is left
        previous, text = text, _BRACKETED.sub("", text)
    return _STRAY_CLOSERS.sub("", _UNCLOSED.sub("", text))


def speakable_gloss(meaning: str) -> str | None:
    """The Chinese a voice says for a word, from the card's ``meaning_zh`` (or a dictionary line): bracketed asides dropped, the
    text cut into senses (:data:`_SENSE_SPLIT`), each sense freed of its part-of-speech labels and of punctuation at its edges,
    senses the Chinese rule of endpoint 76 refuses (no Han character, a stray symbol) and repeats dropped, the first
    :data:`GLOSS_SENSES` joined by 「，」. Longer than :data:`GLOSS_MAX_CHARS` → the first sense alone, cut to that length if need
    be. None when nothing is left — the player then skips the gloss, it never reads a label or an aside.

    ``v. 分享；共用 n. 一份；股份`` → ``分享，共用`` · ``adv./prep. 在船(飞机、车)上;上船(车、飞机)`` → ``在船上，上船`` ·
    ``国内生产总值（gross domestic product 的缩写）`` → ``国内生产总值`` · ``n. 能力, 才干`` → ``能力，才干``."""
    senses: list[str] = []
    for raw in _SENSE_SPLIT.split(_without_brackets(str(meaning or ""))):
        sense = _EDGES.sub("", " ".join(_POS_LABELS.sub("", raw.strip()).split()))
        if sense not in senses and audio.normalize_text(sense, audio.ZH) is not None:  # a Han character, and nothing endpoint 76 refuses
            senses.append(sense)
    if not senses:
        return None
    gloss = "，".join(senses[:GLOSS_SENSES])
    if len(gloss) > GLOSS_MAX_CHARS:
        gloss = _EDGES.sub("", senses[0][:GLOSS_MAX_CHARS])
    return audio.normalize_text(gloss, audio.ZH)


def pick_sentence(content: Mapping[str, Any] | None) -> tuple[str | None, str | None]:
    """``(sentence_en, sentence_zh)``: the first example of ``content`` whose English endpoint 76 accepts (whitespace-collapsed,
    so it is the very text ``wd audio-prewarm`` made a clip for) and its translation when the Chinese rule accepts that too;
    ``(None, None)`` without content or without a speakable example."""
    examples = (content or {}).get("examples")
    for example in examples if isinstance(examples, list) else []:
        if not isinstance(example, Mapping):
            continue
        en = audio.normalize_text(str(example.get("en") or ""))
        if en is not None:
            return en, audio.normalize_text(str(example.get("zh") or ""), audio.ZH)
    return None, None


def listen_item(conn: sqlite3.Connection, item: Mapping[str, Any], word: Mapping[str, Any]) -> dict[str, Any]:
    """API.md ``ListenItem`` for a ``push_items`` row and its ``words`` row. ``meaning_zh`` is what the card shows — the content's,
    else the dictionary's main sense (``ai.dance.dictionary_sense``: the line of the dominant part of speech), else ``''`` — and
    ``gloss_zh`` its speakable form."""
    from ..ai import dance as annotate  # local import: services → ai must not become a module cycle at import time

    content = words.active_content(conn, word)
    meaning = str((content or {}).get("meaning_zh") or "").strip() or annotate.dictionary_sense(word)
    display = str(word.get("display") or word["lemma"])
    sentence_en, sentence_zh = pick_sentence(content)
    return {
        "item_id": int(item["id"]),
        "word_id": int(word["id"]),
        "kind": item["kind"],
        "done": item.get("result") is not None,
        "display": display,
        "phonetic": word.get("phonetic") or None,
        "spoken_en": spoken_headword(display),
        "meaning_zh": meaning,
        "gloss_zh": speakable_gloss(meaning),
        "sentence_en": sentence_en,
        "sentence_zh": sentence_zh,
    }


def playlist(conn: sqlite3.Connection, user_id: int, now: datetime | str | None, *, cfg: Any = None) -> dict[str, Any]:
    """API.md ``ListenPlaylist`` for the user's current local date. Side-effect free, like ``GET /api/today``.

    Today's batch whatever its status (``building`` / ``ready`` / ``published`` — listening never waits for content), its stale and
    superseded items hidden by the rule of the 今日 page (``batches.visible_items``); of those the ``review`` / ``new`` / ``extra``
    rows in ``position, id`` order — 推荐词 are not in the bank yet and are not listened to —, without the words that have left the
    bank since (``user_words.state`` now 已掌握 / 已认识 / removed, i.e. not in ``bank.BANK_STATES``) and with one row per word. The
    word's state decides, not the item's grade: the stale rule looks at ungraded rows only, so a word marked 已掌握 on its word
    page, or removed, after its final grade would keep playing on the strength of its ``good`` item; back in the bank it is listed
    again. Items that already have their final grade stay (``done``): the list is what today was about, not what is left of it.
    No batch today → ``batch_id`` null and no items; the endpoint never builds.
    ``cfg`` is accepted like ``batches.today_response``'s and unused so far — the text rules are the provider-independent ones.
    """
    now_dt, _now_s = bank.coerce_now(now)
    uid = int(user_id)
    today = clock_local_date(now_dt, bank.user_timezone(conn, uid)).isoformat()
    batch = bank.today_batch(conn, uid, today)
    if batch is None:
        return {"batch_id": None, "local_date": today, "items": []}
    items: list[dict[str, Any]] = []
    seen: set[int] = set()
    for it in batches.visible_items(conn, uid, int(batch["id"])):
        wid = int(it["word_id"])
        if it["kind"] not in batches.STUDY_KINDS or it.get("uw_state") not in bank.BANK_STATES or wid in seen:
            continue
        word = words.word_row(conn, wid)
        if word is None:
            continue
        seen.add(wid)
        items.append(listen_item(conn, it, word))
    return {"batch_id": int(batch["id"]), "local_date": str(batch["local_date"]), "items": items}


__all__ = ["GLOSS_MAX_CHARS", "GLOSS_SENSES", "listen_item", "pick_sentence", "playlist", "speakable_gloss", "spoken_headword"]
