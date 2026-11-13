"""Media routes (API.md 52–53): path regex / traversal → 404, cookie required, immutable + SVG CSP headers,
template card with the visibility rule and its cache headers; `?plain=1` (docs/MEMORY_CARDS_DESIGN.md §3.2): a 记忆图卡
without its word layer, and everything else — an older drawing, a photo, any other value of `plain` — exactly as without it."""

from __future__ import annotations

import re
import secrets

import pytest
from fastapi.testclient import TestClient

from wd import db
from wd.deps import hash_token
from wd.images import memo, sanitize_svg, store

SVG_CSP = "default-src 'none'; style-src 'unsafe-inline'"
JPEG = b"\xff\xd8\xff\xe0" + b"\x00" * 200


def make_user(conn, username: str, role: str = "user") -> tuple[int, str]:
    uid = conn.execute("INSERT INTO users(username, password_hash, role, onboarding_state) VALUES (?, 'x', ?, 'done') RETURNING id", (username, role)).fetchone()[0]
    conn.execute("INSERT INTO user_settings(user_id) VALUES (?)", (uid,))
    token = secrets.token_urlsafe(32)
    conn.execute("INSERT INTO sessions(token_hash, user_id, expires_at) VALUES (?, ?, '2027-01-01T00:00:00Z')", (hash_token(token), uid))
    return uid, token


def insert_word(conn, lemma: str, **cols) -> int:
    row = {"lemma": lemma, "display": lemma, "source": "seed", "is_public": 1, "is_valid_english": 1, "translation": "vt. 放弃", "phonetic": "ə'bændən"}
    row.update(cols)
    # the client fixture's lifespan imports the mini seed (WP1), which already holds `abandon`/`apple`; the tests
    # want a row with exactly these columns, so replace any seeded one (children cascade)
    conn.execute("DELETE FROM words WHERE lemma = ?", (lemma,))
    return conn.execute(f"INSERT INTO words({','.join(row)}) VALUES ({','.join('?' * len(row))}) RETURNING id", list(row.values())).fetchone()[0]


@pytest.fixture
def dbconn(client: TestClient, settings):
    c = db.connect(settings.db_path)
    try:
        yield c
    finally:
        c.close()


def test_image_path_shape_is_enforced_before_anything_else(client: TestClient, dbconn):
    for path in ("zz/notthere.jpg", "ab/short.jpg", "ab/" + "a" * 64 + ".png", "%2e%2e/%2e%2e/etc/passwd", "ab/%2e%2e/%2e%2e/" + "a" * 64 + ".jpg", "AB/" + "A" * 64 + ".jpg", "ab/" + "a" * 64 + ".jpg/extra"):
        r = client.get(f"/media/images/{path}")
        assert r.status_code == 404, path
        assert r.json()["error"]["code"] == "not_found"
    assert client.get("/media/other/thing").status_code == 404
    assert client.get("/media/other/thing").json()["error"]["code"] == "not_found"


def test_image_requires_a_session_and_serves_immutable_files(client: TestClient, dbconn, settings):
    stored = store.write_bytes(settings, JPEG, "jpg")
    url = f"/media/images/{stored.file_path}"
    r = client.get(url)
    assert r.status_code == 401 and r.json()["error"]["code"] == "unauthorized"
    _, token = make_user(dbconn, "alice")
    client.cookies.set("wd_session", token)
    r = client.get(url)
    assert r.status_code == 200 and r.content == JPEG
    assert r.headers["content-type"] == "image/jpeg"
    assert r.headers["cache-control"] == "private, max-age=31536000, immutable"
    assert r.headers["x-content-type-options"] == "nosniff"
    assert "X-Request-Id" in r.headers
    missing = f"/media/images/ab/{'a' * 64}.jpg"
    r = client.get(missing)
    assert r.status_code == 404 and r.json()["error"]["code"] == "not_found"


def test_svg_media_carries_the_sandboxing_csp(client: TestClient, dbconn, settings):
    svg = '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 800 500"><rect width="1" height="1"/></svg>'
    stored = store.write_bytes(settings, svg.encode("utf-8"), "svg")
    _, token = make_user(dbconn, "alice")
    client.cookies.set("wd_session", token)
    r = client.get(f"/media/images/{stored.file_path}")
    assert r.status_code == 200 and r.text == svg
    assert r.headers["content-type"].startswith("image/svg+xml")
    assert r.headers["content-security-policy"] == SVG_CSP
    assert r.headers["cache-control"] == "private, max-age=31536000, immutable"
    assert r.headers["x-content-type-options"] == "nosniff"


def test_plain_serves_a_memory_card_without_its_word_layer(client: TestClient, dbconn, settings, fixtures_dir):
    """`?plain=1` on a card: the stored file up to `<g id="word-art"` plus `</svg>` — the scene, its defs and the AIGC label byte
    for byte — under the same headers as the full picture (the immutable cache keys on the full URL). Session rule unchanged."""
    card = (fixtures_dir / "memo" / "moon.svg").read_text(encoding="utf-8")
    labelled = sanitize_svg.with_label(card, "AI-generated illustration · word-Dance · claude · 2026-11-13")  # what activate_memo stores
    stored = store.write_bytes(settings, labelled.encode("utf-8"), "svg")
    url = f"/media/images/{stored.file_path}"
    assert client.get(url + "?plain=1").status_code == 401 and client.get(url + "?plain=1").json()["error"]["code"] == "unauthorized"
    _, token = make_user(dbconn, "alice")
    client.cookies.set("wd_session", token)
    full = client.get(url)
    assert full.status_code == 200 and full.text == labelled and '<g id="word-art"' in full.text and "wa-0-m" in full.text
    plain = client.get(url, params={"plain": "1"})
    assert plain.status_code == 200 and plain.text == labelled[: labelled.index('<g id="word-art"')] + "</svg>" == memo.strip_word_layer(labelled)
    assert "word-art" not in plain.text and "wa-" not in plain.text and plain.text.startswith('<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 800 500"><desc id="aigc-label">')
    assert '<g id="scene"' in plain.text and "<filter " in plain.text and len(plain.content) == int(plain.headers["content-length"]) < len(full.content)
    for name in ("content-type", "cache-control", "x-content-type-options", "content-security-policy"):
        assert plain.headers[name] == full.headers[name], name
    assert plain.headers["content-type"].startswith("image/svg+xml") and plain.headers["cache-control"] == "private, max-age=31536000, immutable"
    assert plain.headers["content-security-policy"] == SVG_CSP and plain.headers["x-content-type-options"] == "nosniff" and "X-Request-Id" in plain.headers
    assert sanitize_svg.clean(plain.text, effects=True)  # well-formed: the cut closed the root
    # … and self-contained: every gradient / filter / clip path the cut picture uses is still in it (the import's structure check refuses a card whose scene leans on the word layer)
    used = {ref for value in re.findall(r'="([^"]*)"', plain.text) for ref in memo.URL_REF_RE.findall(value)}
    assert used and used <= set(re.findall(r' id="([^"]+)"', plain.text)) and memo.check_structure(labelled, "moon") == []
    # a path that is not stored stays 404 with the parameter, and the shape rule still comes first
    assert client.get(f"/media/images/ab/{'a' * 64}.svg?plain=1").status_code == 404
    assert client.get("/media/images/zz/notthere.svg?plain=1").status_code == 404


@pytest.mark.parametrize("query", ["plain=0", "plain=", "plain", "plain=true", "plain=yes", "plain=11", "plain=01", "plain=1&plain=1", "plain=1&plain=0", "PLAIN=1", "plain%20=1", "word=0"])
def test_plain_means_something_for_the_single_value_1_only(client: TestClient, dbconn, settings, fixtures_dir, query: str):
    """`plain` accepts `1`, given once; any other value (or a repeated parameter) is treated as no parameter: the full picture."""
    card = (fixtures_dir / "memo" / "moon.svg").read_text(encoding="utf-8")
    stored = store.write_bytes(settings, card.encode("utf-8"), "svg")
    _, token = make_user(dbconn, "alice")
    client.cookies.set("wd_session", token)
    r = client.get(f"/media/images/{stored.file_path}?{query}")
    assert r.status_code == 200 and r.text == card and '<g id="word-art"' in r.text
    assert r.headers["cache-control"] == "private, max-age=31536000, immutable" and r.headers["content-security-policy"] == SVG_CSP


def test_plain_leaves_older_drawings_photos_and_odd_files_as_they_are(client: TestClient, dbconn, settings, fixtures_dir):
    """Anything that is not a card with exactly one word layer as the root's last child is served exactly as without the
    parameter: an online drawing, a photo, a drawing with a group of that name in the wrong place, a file that is not UTF-8."""
    _, token = make_user(dbconn, "alice")
    client.cookies.set("wd_session", token)
    old = '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 800 500"><desc id="aigc-label">AI-generated illustration · word-Dance · claude · 2026-11-06</desc><rect width="800" height="500" fill="#eee"/></svg>'
    nested = '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 800 500"><g id="scene"><g id="word-art"><rect width="1" height="1"/></g></g></svg>'
    not_last = '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 800 500"><g id="word-art"><rect width="1" height="1"/></g><g id="scene"><rect width="2" height="2"/></g></svg>'
    twice = '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 800 500"><g id="word-art"/><g id="word-art"/></svg>'
    for body in (old.encode("utf-8"), nested.encode("utf-8"), not_last.encode("utf-8"), twice.encode("utf-8"), b'<svg xmlns="http://www.w3.org/2000/svg"><g id="word-art"/>\xff\xfe</svg>'):
        stored = store.write_bytes(settings, body, "svg")
        without, with_plain = client.get(f"/media/images/{stored.file_path}"), client.get(f"/media/images/{stored.file_path}?plain=1")
        assert without.status_code == with_plain.status_code == 200 and with_plain.content == without.content == body
        assert dict(with_plain.headers) == {**dict(without.headers), "x-request-id": with_plain.headers["x-request-id"]}  # the very same response (FileResponse: etag, last-modified …)
    photo = store.write_bytes(settings, JPEG, "jpg")
    r, without = client.get(f"/media/images/{photo.file_path}?plain=1"), client.get(f"/media/images/{photo.file_path}")
    assert r.status_code == 200 and r.content == JPEG and r.headers["content-type"] == "image/jpeg"
    assert r.headers["cache-control"] == "private, max-age=31536000, immutable" and r.headers.get("content-security-policy") != SVG_CSP
    assert dict(r.headers) == {**dict(without.headers), "x-request-id": r.headers["x-request-id"]}
    # a stored file far beyond a sanitised drawing's size is never read into memory for the cut
    card = (fixtures_dir / "memo" / "moon.svg").read_text(encoding="utf-8")
    huge = card.replace("<title>moon</title>", "<title>" + "m" * 130_000 + "</title>")
    stored = store.write_bytes(settings, huge.encode("utf-8"), "svg")
    r = client.get(f"/media/images/{stored.file_path}?plain=1")
    assert r.status_code == 200 and r.text == huge and memo.strip_word_layer(huge) is not None  # cuttable in principle, served whole by the size rule


def test_card_requires_a_session_and_obeys_the_visibility_rule(client: TestClient, dbconn):
    alice, alice_token = make_user(dbconn, "alice")
    bob, bob_token = make_user(dbconn, "bob")
    carol, carol_token = make_user(dbconn, "carol")
    _, admin_token = make_user(dbconn, "root", role="admin")
    public = insert_word(dbconn, "abandon")
    private = insert_word(dbconn, "zzqx", is_public=0, is_valid_english=None, source="user", created_by_user_id=alice)
    dbconn.execute("INSERT INTO user_words(user_id, word_id, state, origin) VALUES (?, ?, 'new', 'custom')", (bob, private))

    assert client.get(f"/media/card/{public}.svg").status_code == 401
    assert client.get(f"/media/card/{public}.svg").json()["error"]["code"] == "unauthorized"

    def as_user(token: str, word_id: int):
        client.cookies.set("wd_session", token)
        return client.get(f"/media/card/{word_id}.svg")

    assert as_user(carol_token, public).status_code == 200
    r = as_user(carol_token, private)
    assert r.status_code == 404 and r.json()["error"]["code"] == "word_not_found"
    assert as_user(alice_token, private).status_code == 200  # creator
    assert as_user(bob_token, private).status_code == 200  # holder of a user_words row
    assert as_user(admin_token, private).status_code == 200  # admins see everything
    assert as_user(alice_token, 999_999).status_code == 404
    assert client.get("/media/card/abc.svg").status_code == 404
    assert client.get(f"/media/card/{public}.png").status_code == 404


def test_card_body_and_headers(client: TestClient, dbconn):
    _, token = make_user(dbconn, "alice")
    wid = insert_word(dbconn, "abandon", display="abandon")
    client.cookies.set("wd_session", token)
    r = client.get(f"/media/card/{wid}.svg")
    assert r.status_code == 200
    assert r.headers["content-type"].startswith("image/svg+xml")
    assert r.headers["cache-control"] == "private, max-age=86400"
    assert r.headers["content-security-policy"] == SVG_CSP
    assert r.headers["x-content-type-options"] == "nosniff"
    assert r.text.startswith('<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 800 500"')
    assert ">abandon<" in r.text and "vt. 放弃" in r.text and "ə'bændən" in r.text
    assert client.get(f"/media/card/{wid}.svg").text == r.text  # deterministic (and cached)
