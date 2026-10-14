"""Media routes (API.md 52–53): path regex / traversal → 404, cookie required, immutable + SVG CSP headers,
template card with the visibility rule and its cache headers."""

from __future__ import annotations

import secrets
import sys

import pytest
from fastapi.testclient import TestClient


def _drop_editable_finder() -> None:
    """See test_images.py: keep this worktree's test run independent of the main checkout's modules."""
    sys.meta_path[:] = [f for f in sys.meta_path if "editable" not in (getattr(f, "__module__", "") + getattr(f, "__name__", type(f).__name__)).lower()]


_drop_editable_finder()

from wd import db  # noqa: E402
from wd.deps import hash_token
from wd.images import store

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
