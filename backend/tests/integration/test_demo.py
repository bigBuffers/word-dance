"""Endpoints 77–78 (API.md §3.1, design D9): the public read-only demo — allow-listed lemmas only, the guest WordBrief, content and
dance, the card-shaped ImageMeta pointing at the public demo route, the active Claude SVG when there is one, public cache headers,
and 404 for every other id."""

from __future__ import annotations

import json

import pytest
from fastapi.testclient import TestClient

from wd import db
from wd.images import store
from wd.routers.demo import DEMO_LEMMAS

SVG_CSP = "default-src 'none'; style-src 'unsafe-inline'"
PHONETICS = {"up": "ʌp", "jump": "dʒʌmp", "cold": "kəuld"}
TRANSLATIONS = {"up": "adv. 向上", "jump": "v. 跳", "cold": "adj. 冷的"}


def insert_word(conn, lemma: str, **cols) -> int:
    row = {"lemma": lemma, "display": lemma, "source": "seed", "is_public": 1, "is_valid_english": 1, "translation": TRANSLATIONS.get(lemma, "n. 词"), "phonetic": PHONETICS.get(lemma, "wɜːd"), "stage_xs": 1, "stage_zk": 1, "stage_min": 1}
    row.update(cols)
    conn.execute("DELETE FROM words WHERE lemma = ?", (lemma,))  # the mini seed lacks the demo words; a test may still re-insert one
    return int(conn.execute(f"INSERT INTO words({','.join(row)}) VALUES ({','.join('?' * len(row))}) RETURNING id", list(row.values())).fetchone()[0])


@pytest.fixture
def dbconn(client: TestClient, settings):
    c = db.connect(settings.db_path)
    try:
        yield c
    finally:
        c.close()


def test_demo_is_public_and_lists_the_allow_listed_words_in_order(client: TestClient, dbconn):
    assert DEMO_LEMMAS == ("up", "jump", "cold")
    ids = {lemma: insert_word(dbconn, lemma) for lemma in ("cold", "up", "jump")}  # inserted out of order on purpose
    abandon = int(dbconn.execute("SELECT id FROM words WHERE lemma = 'abandon'").fetchone()[0])
    r = client.get("/api/demo")  # no cookie
    assert r.status_code == 200, r.text
    assert r.headers["Cache-Control"] == "no-store"
    items = r.json()["items"]
    assert [i["word"]["lemma"] for i in items] == ["up", "jump", "cold"]
    for item in items:
        word = item["word"]
        assert set(item) == {"word", "content", "image", "dance"}
        assert word["id"] == ids[word["lemma"]] and word["my_state"] is None and word["is_public"] is True and word["stages"] == ["xs", "zk"]
        assert word["translation_short"] == TRANSLATIONS[word["lemma"]] and word["phonetic"] == PHONETICS[word["lemma"]]
        assert item["content"] is None
        assert item["image"] == {"id": None, "url": f"/media/demo/{word['id']}.svg", "kind": "card", "provider": "card_svg", "mime": "image/svg+xml", "width": 800, "height": 500, "alt_zh": None, "attribution": None, "word_layer": False, "dancing": False, "hook_zh": None, "note_zh": None}
        dance = item["dance"]
        assert dance is not None and "".join(dance["letters"]) == word["display"] and dance["source"] == "rule" and dance["semantic"] is None
    # the card route: public, cached, the SVG headers of the media routes
    r = client.get(f"/media/demo/{ids['up']}.svg")
    assert r.status_code == 200, r.text
    assert r.headers["content-type"].startswith("image/svg+xml")
    assert r.headers["cache-control"] == "public, max-age=86400"
    assert r.headers["content-security-policy"] == SVG_CSP and r.headers["x-content-type-options"] == "nosniff"
    assert r.text.startswith('<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 800 500"') and ">up<" in r.text and "向上" in r.text
    # anything outside the demo set is 404 — never a session-less card renderer for the vocabulary
    r = client.get(f"/media/demo/{abandon}.svg")
    assert r.status_code == 404 and r.json()["error"]["code"] == "not_found"
    assert client.get("/media/demo/999999.svg").status_code == 404
    assert client.get("/media/demo/abc.svg").status_code == 404
    assert client.get(f"/media/demo/{ids['up']}.png").status_code == 404
    assert client.get(f"/media/card/{ids['up']}.svg").status_code == 401  # the regular card route still needs a session
    # no writes: nothing queued, no throttle rows
    assert int(dbconn.execute("SELECT COUNT(*) FROM jobs").fetchone()[0]) == 0
    assert int(dbconn.execute("SELECT COUNT(*) FROM auth_throttle").fetchone()[0]) == 0


def test_demo_skips_missing_private_invalid_or_merged_words(client: TestClient, dbconn):
    assert client.get("/api/demo").json() == {"items": []}  # the mini seed has none of the three: never a 500
    up = insert_word(dbconn, "up", is_public=0)
    jump = insert_word(dbconn, "jump", is_valid_english=None)
    cold = insert_word(dbconn, "cold")
    assert [i["word"]["lemma"] for i in client.get("/api/demo").json()["items"]] == ["cold"]
    assert client.get(f"/media/demo/{up}.svg").status_code == 404 and client.get(f"/media/demo/{jump}.svg").status_code == 404
    assert client.get(f"/media/demo/{cold}.svg").status_code == 200
    dbconn.execute("UPDATE words SET merged_into_word_id = ? WHERE id = ?", (up, cold))
    assert client.get("/api/demo").json() == {"items": []}
    assert client.get(f"/media/demo/{cold}.svg").status_code == 404


def test_demo_serves_the_active_claude_svg_and_the_active_content(client: TestClient, dbconn, settings):
    up = insert_word(dbconn, "up")
    svg = '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 800 500"><rect width="1" height="1"/></svg>'
    stored = store.write_bytes(settings, svg.encode("utf-8"), "svg")
    image_id = int(
        dbconn.execute(
            "INSERT INTO word_images(word_id, provider, license, file_path, file_bytes, sha256, mime, width, height, alt_zh, status) VALUES (?, 'claude_svg', 'CC0', ?, ?, ?, 'image/svg+xml', 800, 500, '一个向上的箭头', 'active') RETURNING id",
            (up, stored.file_path, len(svg), stored.sha256),
        ).fetchone()[0]
    )
    content = {
        "word": "up", "valid": True, "meaning_zh": "向上", "meaning_en": "toward a higher place", "examples": [{"en": "Look up at the sky.", "zh": "抬头看天空。"}],
        "collocations": ["get up"], "mnemonic_zh": "u 像杯子，p 把它举起来", "image_keywords": ["arrow"], "image_alt_zh": "向上的箭头", "difficulty": 1,
        "version": 1, "prompt_version": "content-v1", "model": "claude-sonnet-5-5", "created_at": "2026-10-14T00:00:00Z",
    }
    content_id = int(dbconn.execute("INSERT INTO word_contents(word_id, version, prompt_version, model, content_json, status) VALUES (?, 1, 'content-v1', 'claude-sonnet-5-5', ?, 'active') RETURNING id", (up, json.dumps(content, ensure_ascii=False))).fetchone()[0])
    dbconn.execute("UPDATE words SET active_image_id = ?, image_state = 'ready', active_content_id = ?, content_state = 'ready' WHERE id = ?", (image_id, content_id, up))
    item = client.get("/api/demo").json()["items"][0]
    assert item["image"] == {"id": image_id, "url": f"/media/demo/{up}.svg", "kind": "svg", "provider": "claude_svg", "mime": "image/svg+xml", "width": 800, "height": 500, "alt_zh": "一个向上的箭头", "attribution": None, "word_layer": False, "dancing": False, "hook_zh": None, "note_zh": None}
    assert item["content"]["meaning_zh"] == "向上" and item["content"]["examples"][0]["en"] == "Look up at the sky." and item["word"]["content_state"] == "ready"
    r = client.get(f"/media/demo/{up}.svg")
    assert r.status_code == 200 and r.text == svg and r.headers["cache-control"] == "public, max-age=86400" and r.headers["content-security-policy"] == SVG_CSP
    # a photo (or a missing file) falls back to the template card so the route stays single-type
    (settings.images_dir / stored.file_path).unlink()
    item = client.get("/api/demo").json()["items"][0]
    assert item["image"]["kind"] == "card" and item["image"]["provider"] == "card_svg" and item["image"]["url"] == f"/media/demo/{up}.svg"
    r = client.get(f"/media/demo/{up}.svg")
    assert r.status_code == 200 and r.text.startswith("<svg") and "向上" in r.text  # the template card carries the active meaning


def test_demo_shows_a_memory_card_with_its_word_and_no_plain_variant(client: TestClient, dbconn, settings):
    """记忆图卡 on a demo word (docs/MEMORY_CARDS_DESIGN.md §3.3): the public route serves the whole card — a guest has no
    `image_word` setting to switch off — so the demo's ImageMeta keeps `word_layer: false` (the URL has no `?plain=1`) and carries
    no hook; the route ignores the parameter."""
    from wd.images import activate_memo

    up = insert_word(dbconn, "up")
    card = (
        '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 800 500"><g id="scene"><rect width="800" height="500" fill="#9CD3F5"/></g>'
        '<g id="word-art"><path id="wa-0-u" d="M300 200H340V260Z" fill="#fff"/><path id="wa-1-p" d="M360 200H400V280Z" fill="#fff"/></g></svg>'
    )
    image_id = activate_memo(dbconn, settings, up, card, alt_zh="朵朵把风筝举上天", hook_zh="u 像杯子，p 把它举起来。", note_zh=None, model="claude-fable-5-2", prompt_version="memo-1", now="2026-10-14T00:00:00Z")
    item = client.get("/api/demo").json()["items"][0]
    assert item["image"] == {"id": image_id, "url": f"/media/demo/{up}.svg", "kind": "svg", "provider": "claude_svg", "mime": "image/svg+xml", "width": 800, "height": 500, "alt_zh": "朵朵把风筝举上天", "attribution": None, "word_layer": False, "dancing": False, "hook_zh": None, "note_zh": None}
    full = client.get(f"/media/demo/{up}.svg")
    assert full.status_code == 200 and '<g id="word-art"' in full.text and "wa-0-u" in full.text
    assert client.get(f"/media/demo/{up}.svg?plain=1").text == full.text
