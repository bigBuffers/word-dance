"""images/card_svg.py: deterministic template card, XML escaping, DB-backed rendering with the LRU cache."""

from __future__ import annotations

import json
from xml.etree import ElementTree as ET

from wd.images import card_svg

WORD = {"lemma": "abandon", "display": "abandon", "phonetic": "ə'bændən", "translation": "vt. 放弃, 抛弃, 遗弃\nn. 放纵", "definition": "to leave"}


def test_render_is_deterministic_and_lemma_dependent():
    a = card_svg.render(WORD, None)
    assert a == card_svg.render(dict(WORD), None)
    b = card_svg.render({**WORD, "lemma": "apple", "display": "apple"}, None)
    assert a != b
    assert card_svg.palette("abandon") == card_svg.palette("abandon") and card_svg.palette("abandon") != card_svg.palette("apple")
    for colour in card_svg.palette("abandon"):
        assert len(colour) == 7 and colour.startswith("#")


def test_render_structure_and_content():
    svg = card_svg.render(WORD, {"meaning_zh": "v. 放弃；抛弃", "examples": [{"en": "They had to abandon the car in the snow.", "zh": "他们不得不把车丢在雪里。"}]})
    root = ET.fromstring(svg)
    assert root.tag == "{http://www.w3.org/2000/svg}svg" and root.get("viewBox") == "0 0 800 500"
    assert root.get("width") == "800" and root.get("height") == "500"
    texts = [t.text for t in root.iter("{http://www.w3.org/2000/svg}text")]
    assert texts[0] == "abandon" and texts[1] == "ə'bændən"
    assert "v. 放弃；抛弃" in texts and "They had to abandon the car in the snow." in texts and texts[-1] == "word-Dance"
    assert svg.startswith("<svg xmlns=\"http://www.w3.org/2000/svg\"")
    assert "<script" not in svg and "href" not in svg
    # without content the first translation line stands in
    plain = card_svg.render(WORD, None)
    assert "vt. 放弃, 抛弃, 遗弃" in plain and "n. 放纵" not in plain


def test_everything_is_escaped():
    nasty = {"lemma": "x", "display": '<a&"b>', "phonetic": "<i>", "translation": 'x<y & "z"', "definition": None}
    svg = card_svg.render(nasty, {"meaning_zh": "<b>bold</b>", "examples": [{"en": "1 < 2 && \"q\"", "zh": ""}]})
    assert "<a&" not in svg and "<i>" not in svg and "<b>" not in svg and "&&" not in svg
    assert "&lt;a&amp;\"b&gt;" in svg or "&lt;a&amp;&quot;b&gt;" in svg
    root = ET.fromstring(svg)  # well-formed
    texts = [t.text for t in root.iter("{http://www.w3.org/2000/svg}text")]
    assert texts[0] == '<a&"b>' and "1 < 2 && \"q\"" in texts
    assert root.get("aria-label") == '<a&"b>'


def test_fit_and_headword_size():
    assert card_svg.fit("short", 10) == "short"
    assert card_svg.fit("a" * 20, 10) == "a" * 9 + "…"
    assert card_svg.fit("放弃抛弃遗弃", 6) == "放弃…"  # CJK counts double
    assert card_svg.fit("  spaced   out  ", 20) == "spaced out"
    assert card_svg.headword_size("abandon") == 72
    assert card_svg.headword_size("ice cream") == 72
    assert card_svg.headword_size("a" * 20) == 36
    assert card_svg.headword_size("a" * 40) == 28


def _word(conn, lemma: str, display: str | None = None) -> int:
    return conn.execute(
        "INSERT INTO words(lemma, display, phonetic, translation, definition, source) VALUES (?,?,?,?,?,'seed') RETURNING id",
        (lemma, display or lemma, "ə'bændən", "vt. 放弃", "to leave"),
    ).fetchone()[0]


def test_render_card_reads_db_and_caches(conn):
    card_svg.cache_clear()
    wid = _word(conn, "abandon")
    first = card_svg.render_card(conn, wid)
    assert "abandon" in first and "vt. 放弃" in first
    assert card_svg.render_card(conn, wid) == first and card_svg.cache_size() == 1
    # activate content → a different key → the card shows the example and meaning
    content = {"word": "abandon", "meaning_zh": "v. 放弃；抛弃", "examples": [{"en": "She abandoned the plan.", "zh": "她放弃了计划。"}]}
    cid = conn.execute(
        "INSERT INTO word_contents(word_id, version, prompt_version, model, content_json) VALUES (?,1,'content-v1','m',?) RETURNING id",
        (wid, json.dumps(content, ensure_ascii=False)),
    ).fetchone()[0]
    conn.execute("UPDATE words SET active_content_id=?, content_state='ready', updated_at='2026-10-14T01:00:00Z' WHERE id=?", (cid, wid))
    second = card_svg.render_card(conn, wid)
    assert second != first and "She abandoned the plan." in second and "v. 放弃；抛弃" in second
    assert card_svg.cache_size() == 2
    try:
        card_svg.render_card(conn, 999_999)
    except LookupError:
        pass
    else:  # pragma: no cover
        raise AssertionError("unknown word must raise LookupError")


def test_lru_evicts_oldest(conn, monkeypatch):
    card_svg.cache_clear()
    monkeypatch.setattr(card_svg, "LRU_SIZE", 3)
    ids = [_word(conn, f"w{i}") for i in range(5)]
    for wid in ids:
        card_svg.render_card(conn, wid)
    assert card_svg.cache_size() == 3
