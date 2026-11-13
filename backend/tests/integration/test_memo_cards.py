"""记忆图卡 end to end (docs/MEMORY_CARDS_DESIGN.md §3): store.activate_memo (validate, clean with effects, label, store, activate,
hook_zh / note_zh), the ImageMeta shapes of a card / an older drawing / a photo / the template card, `wd images-import` and `--undo`
(happy path, dry run, unknown lemma, structure rejected, the gate's newer rules and a card stored without CSS, unchanged, captions brought up to date, a card cleaned once, two manifest keys
for one word, a model name that would break the label, a card that cannot be stored, a lost file written back, a card an admin took
down left down; undo back to the previous drawing, to the template card, never past a report), and the guards of §3.6: no fetch_image
but an admin's explicit one and no fallback generate_svg replaces a card, and a learner's 不合适 on a card is only recorded — the
admin's resolution of the report is what takes the card down."""

from __future__ import annotations

import hashlib
import json
import secrets
import shutil
import sqlite3
from dataclasses import replace
from pathlib import Path

import httpx
import pytest
from fastapi.testclient import TestClient

from wd import cli, db
from wd.deps import hash_token
from wd.images import activate_memo, activate_svg, handler as image_handler, image_meta, memo, photo_mix, reject_active_image, request_refresh, sanitize_svg, service, store
from wd.images.sanitize_svg import SvgRejected
from wd.jobs import queue, registry, worker
from wd.jobs.registry import JobContext
from wd.schemas import ImageMeta

PUBLIC_IP = "93.184.216.34"
NOW = "2026-10-14T00:00:00Z"
MODEL = "claude-fable-5-2"
ALT = "中秋夜的湖边，朵朵指着天上又大又圆的月亮，团子伸出爪子去捞水里的月亮，兔子灯在一旁亮着。"
HOOK = "两个 o 像两轮圆月：天上一个，水里一个，oo 读长音 /uː/。"
NOTE = "注意：book、look 里的 oo 读短音 /ʊ/。"
OLD_DRAWING = '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 800 500"><rect width="800" height="500" fill="#123"/><circle cx="400" cy="250" r="90" fill="#FFE08A"/></svg>'
EMPTY_WIKIMEDIA = {"batchcomplete": ""}
EMPTY_OPENVERSE = {"result_count": 0, "page_count": 0, "page_size": 20, "page": 1, "results": []}


@pytest.fixture
def moon_svg(fixtures_dir) -> str:
    """One of the ten approved sample cards, as the studio's validator cleaned it (tests/fixtures/memo/moon.svg)."""
    return (fixtures_dir / "memo" / "moon.svg").read_text(encoding="utf-8")


@pytest.fixture
def cfg(settings):
    return replace(settings, wikimedia_min_interval_ms=0)


@pytest.fixture
def pinned_dns(monkeypatch):
    monkeypatch.setattr("wd.images.fetch.resolve_host", lambda host: [PUBLIC_IP])


@pytest.fixture
def ctx(cfg, conn, connect, frozen_clock):
    registry.load_handlers()
    registry.register("fetch_image")(image_handler.handle_fetch_image)  # other tests may reset the registry
    return JobContext(db=connect, cfg=cfg, clock=frozen_clock, enqueue=queue.enqueue, worker_id="io-1", boot_id="test")


def insert_word(conn, lemma: str, **cols) -> int:
    row = {"lemma": lemma, "display": lemma, "kind": "word", "source": "seed", "is_public": 1, "is_valid_english": 1, "translation": "n. 月亮", "phonetic": "muːn"}
    row.update(cols)
    conn.execute("DELETE FROM words WHERE lemma = ?", (lemma,))  # a client-fixture database carries the mini seed
    return conn.execute(f"INSERT INTO words({','.join(row)}) VALUES ({','.join('?' * len(row))}) RETURNING id", list(row.values())).fetchone()[0]


def small_card(word: str) -> str:
    """A minimal well-formed memory card for ``word`` (one path per letter or digit, indexed by position)."""
    paths = "".join(f'<path id="wa-{i}-{ch}" d="M{20 * i} 300H{20 * i + 12}V320Z" fill="#fff"/>' for i, ch in enumerate(word) if ch.isalnum())
    return (
        '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 800 500"><defs><filter id="soft"><feGaussianBlur stdDeviation="4"/></filter></defs>'
        f'<g id="scene"><rect width="800" height="500" fill="#2F3F96"/><circle cx="168" cy="126" r="60" fill="#FFF5C4" filter="url(#soft)"/></g><g id="word-art">{paths}</g></svg>'
    )


def images(conn, word_id: int) -> list[dict]:
    return [db.row_to_dict(r) for r in conn.execute("SELECT * FROM word_images WHERE word_id = ? ORDER BY id", (word_id,))]


def word_state(conn, word_id: int) -> tuple:
    return tuple(conn.execute("SELECT image_state, active_image_id FROM words WHERE id = ?", (word_id,)).fetchone())


def job(conn, job_id: int) -> dict:
    return db.row_to_dict(conn.execute("SELECT * FROM jobs WHERE id = ?", (job_id,)).fetchone())


def svg_jobs(conn, word_id: int) -> list[dict]:
    return [db.row_to_dict(r) for r in conn.execute("SELECT * FROM jobs WHERE type = 'generate_svg' AND json_extract(payload_json, '$.word_id') = ?", (word_id,))]


def give_card(conn, cfg, word_id: int, svg: str, now: str = NOW) -> int:
    return activate_memo(conn, cfg, word_id, svg, alt_zh=ALT, hook_zh=HOOK, note_zh=NOTE, model=MODEL, prompt_version="memo-1", now=now)


def write_manifest(directory: Path, cards: dict[str, dict], **top) -> Path:
    path = directory / "manifest.json"
    path.write_text(json.dumps({"prompt_version": "memo-1", "model": MODEL, **top, "cards": cards}, ensure_ascii=False), encoding="utf-8")
    return path


@pytest.fixture
def studio(tmp_path: Path, moon_svg: str) -> Path:
    """A studio output directory: moon.svg (the approved card) and its manifest."""
    d = tmp_path / "cards"
    d.mkdir()
    (d / "moon.svg").write_text(moon_svg, encoding="utf-8")
    write_manifest(d, {"moon": {"alt_zh": ALT, "hook_zh": HOOK, "note_zh": NOTE}})
    return d


# ------------------------------------------------------------------------------------------------ store
def test_activate_memo_cleans_with_effects_labels_stores_and_activates(conn, cfg, moon_svg):
    wid = insert_word(conn, "moon")
    old_id = activate_svg(conn, cfg, wid, OLD_DRAWING, "夜空里的月亮", now="2026-10-01T00:00:00Z", model="claude-sonnet-4-5", prompt_version="svg-v2")
    old_file = cfg.images_dir / images(conn, wid)[0]["file_path"]
    image_id = give_card(conn, cfg, wid, moon_svg)
    old, new = images(conn, wid)
    assert (old["id"], old["status"]) == (old_id, "superseded") and old_file.is_file()  # the previous drawing keeps its row and its file: --undo needs both
    assert (new["id"], new["status"], new["provider"], new["mime"], new["license"]) == (image_id, "active", "claude_svg", "image/svg+xml", "generated")
    assert (new["prompt_version"], new["model"], new["text_free"], new["eval_json"]) == ("memo-1", MODEL, 1, None)  # the letters are paths: still text-free
    assert (new["alt_zh"], new["hook_zh"], new["note_zh"]) == (ALT, HOOK, NOTE) and (new["width"], new["height"]) == (800, 500) and new["created_at"] == NOW
    assert word_state(conn, wid) == ("ready", image_id)
    stored = (cfg.images_dir / new["file_path"]).read_text(encoding="utf-8")
    label = f"AI-generated illustration · word-Dance · {MODEL} · 2026-10-14"
    assert stored == sanitize_svg.with_label(moon_svg, label)  # the studio's cleaned file + the implicit AIGC marker, nothing else changed
    assert stored.count('id="aigc-label"') == 1 and "<filter " in stored and "<feGaussianBlur " in stored and "<feDropShadow " in stored and ' filter="url(#' in stored
    assert new["sha256"] == hashlib.sha256(stored.encode("utf-8")).hexdigest() and new["file_bytes"] == len(stored.encode("utf-8"))
    assert memo.is_memo(new) and not memo.is_memo(old) and memo.check_structure(stored, "moon") == []
    meta = image_meta(conn, wid)
    ImageMeta.model_validate(meta)
    assert meta == {
        "id": image_id, "url": f"/media/images/{new['file_path']}", "kind": "svg", "provider": "claude_svg", "mime": "image/svg+xml", "width": 800, "height": 500,
        "alt_zh": ALT, "attribution": None, "word_layer": True, "hook_zh": HOOK, "note_zh": NOTE,
    }
    assert photo_mix(conn) == {"with_photo": 0, "with_claude_svg": 1, "card_only": 0}  # a card counts as a Claude drawing everywhere else


def test_image_meta_shapes_for_an_older_drawing_a_photo_and_the_template_card(conn, cfg, moon_svg):
    """ImageMeta.word_layer / hook_zh / note_zh (API.md §9): false / null / null on everything that is not a memory card — the
    online drawing made from the very same file included, which loses its filters and is no card."""
    drawing = insert_word(conn, "moon")
    drawing_id = activate_svg(conn, cfg, drawing, moon_svg, "月亮", now=NOW, model="claude-sonnet-4-5", prompt_version="svg-v2")
    row = images(conn, drawing)[0]
    stored = (cfg.images_dir / row["file_path"]).read_text(encoding="utf-8")
    assert "<filter" not in stored and "feGaussianBlur" not in stored and " filter=" not in stored  # activate_svg never passes effects
    assert image_meta(conn, drawing) == {
        "id": drawing_id, "url": f"/media/images/{row['file_path']}", "kind": "svg", "provider": "claude_svg", "mime": "image/svg+xml", "width": 800, "height": 500,
        "alt_zh": "月亮", "attribution": None, "word_layer": False, "hook_zh": None, "note_zh": None,
    }
    conn.execute("UPDATE word_images SET hook_zh = '不该出现', note_zh = '不该出现' WHERE id = ?", (drawing_id,))  # captions on a row that is no card are never served
    assert (image_meta(conn, drawing)["hook_zh"], image_meta(conn, drawing)["note_zh"]) == (None, None)
    photo = insert_word(conn, "apple")
    jpg = store.write_bytes(cfg, b"\xff\xd8\xff" + b"p" * 100, "jpg")
    photo_id = store.activate(conn, photo, provider="wikimedia", ref="1", file_path=jpg.file_path, file_bytes=jpg.file_bytes, sha256=jpg.sha256, mime="image/jpeg", title="Red Apple", creator="A", license="CC0", width=640, height=400, now=NOW)
    meta = image_meta(conn, photo)
    ImageMeta.model_validate(meta)
    assert meta == {
        "id": photo_id, "url": f"/media/images/{jpg.file_path}", "kind": "photo", "provider": "wikimedia", "mime": "image/jpeg", "width": 640, "height": 400, "alt_zh": None,
        "attribution": {"title": "Red Apple", "creator": "A", "creator_url": None, "license": "CC0", "license_url": None, "landing_url": None, "text": '"Red Apple" · A · CC0'},
        "word_layer": False, "hook_zh": None, "note_zh": None,
    }
    bare = insert_word(conn, "pear")
    card = {"id": None, "url": f"/media/card/{bare}.svg", "kind": "card", "provider": "card_svg", "mime": "image/svg+xml", "width": 800, "height": 500, "alt_zh": None, "attribution": None, "word_layer": False, "hook_zh": None, "note_zh": None}
    assert image_meta(conn, bare) == card == service.card_meta(bare)
    from wd.services import words

    assert words.card_image_meta(bare) == card and words.image_meta_for(conn, bare) == card
    # a card whose manifest had no hook: word_layer true, both captions null (the 记忆 section then keeps content.mnemonic_zh)
    hookless = insert_word(conn, "noon")
    activate_memo(conn, cfg, hookless, small_card("noon"), alt_zh=None, hook_zh="  ", note_zh=None, model=MODEL, prompt_version="memo-1", now=NOW)
    meta = image_meta(conn, hookless)
    assert (meta["word_layer"], meta["hook_zh"], meta["note_zh"], meta["alt_zh"]) == (True, None, None, None)


@pytest.mark.parametrize(
    "overrides,needle",
    [
        pytest.param({"headword": "noon"}, "word-art spells 'moon'", id="another-word"),
        pytest.param({"hook_zh": "月" * 61}, "hook_zh is 61 characters, the limit is 60", id="hook-too-long"),
        pytest.param({"note_zh": "月" * 61}, "note_zh is 61 characters, the limit is 60", id="note-too-long"),
        pytest.param({"alt_zh": "月" * 201}, "alt_zh is 201 characters, the limit is 200", id="alt-too-long"),
        pytest.param({"hook_zh": 7}, "hook_zh must be a string, not int", id="hook-not-a-string"),
        pytest.param({"prompt_version": "svg-v2"}, "prompt_version must be memo-<n>", id="not-a-memo-version"),
        pytest.param({"prompt_version": "memo-"}, "prompt_version must be memo-<n>", id="bare-prefix"),
        pytest.param({"model": "  "}, "model must name the model that drew the card", id="no-model"),
        # the name goes into the file's AIGC label after every check: these would store a file that is not XML (or not UTF-8)
        pytest.param({"model": "claude\u0001opus"}, "model must name the model that drew the card (1–80 printable characters)", id="model-control-character"),
        pytest.param({"model": "claude\ufffe"}, "model must name the model that drew the card (1–80 printable characters)", id="model-noncharacter"),
        pytest.param({"model": "claude\ud800"}, "model must name the model that drew the card (1–80 printable characters)", id="model-lone-surrogate"),
        pytest.param({"model": "claude\u001b[0m"}, "model must name the model that drew the card (1–80 printable characters)", id="model-escape-sequence"),
        pytest.param({"svg": "<html>no</html>"}, "the sanitiser rejected the file: root element is not", id="not-svg"),
        pytest.param({"svg": OLD_DRAWING}, 'no <g id="scene"> as a direct child', id="an-ordinary-drawing"),
    ],
)
def test_activate_memo_rejects_and_writes_nothing(conn, cfg, moon_svg, overrides, needle):
    wid = insert_word(conn, overrides.get("headword", "moon"))
    kwargs = {"alt_zh": ALT, "hook_zh": HOOK, "note_zh": NOTE, "model": MODEL, "prompt_version": "memo-1", **{k: v for k, v in overrides.items() if k not in ("svg", "headword")}}
    with pytest.raises(store.MemoRejected) as e:
        activate_memo(conn, cfg, wid, overrides.get("svg", moon_svg), now=NOW, **kwargs)
    assert any(needle in p for p in e.value.problems), e.value.problems
    assert isinstance(e.value, SvgRejected) and isinstance(e.value, ValueError)  # callers that catch the sanitiser's error catch this one
    assert images(conn, wid) == [] and word_state(conn, wid) == ("none", None) and store.list_files(cfg) == []


def test_activate_memo_reports_every_problem_and_limits_are_on_collapsed_text(conn, cfg, moon_svg):
    wid = insert_word(conn, "noon")
    with pytest.raises(store.MemoRejected) as e:
        activate_memo(conn, cfg, wid, moon_svg, alt_zh=ALT, hook_zh="月" * 61, note_zh="月" * 61, model=MODEL, prompt_version="memo-1")
    assert len(e.value.problems) == 3 and str(e.value) == "; ".join(e.value.problems)
    with pytest.raises(store.MemoRejected, match="word 999999 not found"):
        activate_memo(conn, cfg, 999_999, moon_svg, alt_zh=None, hook_zh=None, note_zh=None, model=MODEL, prompt_version="memo-1")
    # exactly 60 characters pass; whitespace is collapsed before counting and before storing
    moon = insert_word(conn, "moon")
    image_id = activate_memo(conn, cfg, moon, moon_svg, alt_zh=" 月亮 \n 很圆 ", hook_zh="月" * 60, note_zh="  " + "亮" * 30 + "   " + "圆" * 29 + "\n", model=f"  {MODEL} ", prompt_version="memo-2", now=NOW)
    row = images(conn, moon)[0]
    assert row["id"] == image_id and (row["alt_zh"], row["hook_zh"], row["note_zh"]) == ("月亮 很圆", "月" * 60, "亮" * 30 + " " + "圆" * 29)
    assert (row["model"], row["prompt_version"]) == (MODEL, "memo-2") and (store.HOOK_MAX_CHARS, store.NOTE_MAX_CHARS, store.ALT_MAX_CHARS) == (60, 60, 200)


def test_activate_memo_sanitises_a_raw_card(conn, cfg):
    """The importer takes raw studio files too: scripts, handlers, text, foreign elements and outside references are gone from
    what is stored, exactly like for an online drawing — only the card's own effects stay."""
    raw = small_card("moon").replace(
        '<g id="scene">',
        '<script>alert(1)</script><g id="scene" onclick="x()"><text x="10" y="40">moon</text><image href="https://evil.example/x.png"/><rect width="5" height="5" filter="url(https://evil.example/f.svg#f)"/>',
    )
    wid = insert_word(conn, "moon")
    give_card(conn, cfg, wid, raw)
    stored = (cfg.images_dir / images(conn, wid)[0]["file_path"]).read_text(encoding="utf-8")
    for gone in ("script", "onclick", "<text", "<image", "evil"):
        assert gone not in stored, gone
    assert '<circle cx="168" cy="126" r="60" fill="#FFF5C4" filter="url(#soft)"/>' in stored and '<rect width="5" height="5"/>' in stored


# ------------------------------------------------------------------------------------------------- API
def make_user(conn, username: str, role: str = "user") -> str:
    uid = conn.execute("INSERT INTO users(username, password_hash, role, onboarding_state) VALUES (?, 'x', ?, 'done') RETURNING id", (username, role)).fetchone()[0]
    conn.execute("INSERT INTO user_settings(user_id) VALUES (?)", (uid,))
    token = secrets.token_urlsafe(32)
    conn.execute("INSERT INTO sessions(token_hash, user_id, expires_at) VALUES (?, ?, '2027-01-01T00:00:00Z')", (hash_token(token), uid))
    return token


def test_api_serves_the_card_meta_and_both_pictures(client: TestClient, settings, moon_svg):
    """Endpoints 23 / 25 carry the card's ImageMeta, endpoint 52 the picture with the word and — `?plain=1` — without it."""
    c = db.connect(settings.db_path)
    try:
        wid = insert_word(c, "moon")
        image_id = give_card(c, settings, wid, moon_svg)
        file_path = images(c, wid)[0]["file_path"]
        client.cookies.set("wd_session", make_user(c, "alice"))
    finally:
        c.close()
    expected = {
        "id": image_id, "url": f"/media/images/{file_path}", "kind": "svg", "provider": "claude_svg", "mime": "image/svg+xml", "width": 800, "height": 500,
        "alt_zh": ALT, "attribution": None, "word_layer": True, "hook_zh": HOOK, "note_zh": NOTE,
    }
    r = client.get(f"/api/words/{wid}/image")
    assert r.status_code == 200 and r.json() == expected
    assert client.get("/api/words/moon").json()["image"] == expected
    full = client.get(expected["url"])
    plain = client.get(expected["url"] + "?plain=1")
    assert full.status_code == plain.status_code == 200
    assert '<g id="word-art"' in full.text and "wa-0-m" in full.text
    assert "word-art" not in plain.text and "wa-" not in plain.text and plain.text == full.text[: full.text.index('<g id="word-art"')] + "</svg>"
    assert plain.headers["content-type"] == full.headers["content-type"] and plain.headers["cache-control"] == "private, max-age=31536000, immutable"


# ------------------------------------------------------------------------------------- wd images-import
def test_import_happy_path_supersedes_the_previous_drawing(conn, cfg, studio, moon_svg, capsys):
    wid = insert_word(conn, "moon")
    old_id = activate_svg(conn, cfg, wid, OLD_DRAWING, "夜空里的月亮", now="2026-10-01T00:00:00Z", model="claude-sonnet-4-5", prompt_version="svg-v2")
    assert cli.main(["images-import", str(studio), "--manifest", str(studio / "manifest.json")]) == 0
    out = capsys.readouterr().out
    assert "  imported   moon\n" in out and f"images-import: 1 imported, 0 unchanged, 0 rejected (memo-1, {MODEL})" in out and "dry run" not in out
    old, new = images(conn, wid)
    assert (old["id"], old["status"]) == (old_id, "superseded") and (cfg.images_dir / old["file_path"]).is_file()
    assert (new["status"], new["prompt_version"], new["model"], new["alt_zh"], new["hook_zh"], new["note_zh"]) == ("active", "memo-1", MODEL, ALT, HOOK, NOTE)
    assert word_state(conn, wid) == ("ready", new["id"]) and image_meta(conn, wid)["word_layer"] is True
    stored = (cfg.images_dir / new["file_path"]).read_text(encoding="utf-8")
    assert stored == sanitize_svg.with_label(moon_svg, f"AI-generated illustration · word-Dance · {MODEL} · {new['created_at'][:10]}")
    assert conn.execute("SELECT COUNT(*) FROM jobs").fetchone()[0] == 0  # no job, no provider, no Claude call


def test_import_dry_run_checks_everything_and_writes_nothing(conn, cfg, studio, capsys):
    wid = insert_word(conn, "moon")
    (studio / "noon.svg").write_text((studio / "moon.svg").read_text(encoding="utf-8"), encoding="utf-8")  # the moon card under another word's name
    insert_word(conn, "noon")
    write_manifest(studio, {"moon": {"alt_zh": ALT, "hook_zh": HOOK, "note_zh": NOTE}, "noon": {"hook_zh": "正午"}})
    assert cli.main(["images-import", str(studio), "--manifest", str(studio / "manifest.json"), "--dry-run"]) == 1  # the verdicts (and the exit code) are the real run's
    out = capsys.readouterr().out
    assert "  ok         moon (would be imported)" in out and "  rejected   noon: word-art spells 'moon'" in out
    assert "images-import: 1 would be imported, 0 unchanged, 1 rejected" in out and out.rstrip().endswith("— dry run, nothing written")
    assert images(conn, wid) == [] and word_state(conn, wid) == ("none", None) and store.list_files(cfg) == []
    assert conn.execute("SELECT COUNT(*) FROM word_images").fetchone()[0] == 0


def test_import_rejects_unknown_lemmas_bad_structure_and_missing_files_but_imports_the_rest(conn, cfg, studio, moon_svg, capsys):
    moon = insert_word(conn, "moon")
    noon = insert_word(conn, "noon")
    private = insert_word(conn, "zzqx", is_public=0, is_valid_english=None, source="user")
    merged = insert_word(conn, "mooon", merged_into_word_id=moon)
    pear = insert_word(conn, "pear")
    for name in ("noon", "zzqx", "mooon", "nosuchword"):
        (studio / f"{name}.svg").write_text(moon_svg, encoding="utf-8")
    (studio / "big.svg").write_text("<svg xmlns='http://www.w3.org/2000/svg'>" + " " * 61_000 + "</svg>", encoding="utf-8")
    insert_word(conn, "big")
    cards = {lemma: {"hook_zh": HOOK} for lemma in ("nosuchword", "zzqx", "mooon", "noon", "pear", "big", "moon")}
    cards["moon"]["note_zh"] = "读" * 61
    manifest = write_manifest(studio, cards)
    assert cli.main(["images-import", str(studio), "--manifest", str(manifest)]) == 1
    out = capsys.readouterr().out
    for lemma in ("nosuchword", "zzqx", "mooon"):  # not found → reported and skipped: no such word, a private custom word, a merged duplicate
        assert f"  rejected   {lemma}: unknown lemma (no public, unmerged word)" in out
    assert "  rejected   noon: word-art spells 'moon' (wa-0-m, wa-1-o, wa-2-o, wa-3-n), expected 'noon'" in out
    assert f"  rejected   pear: no file {studio / 'pear.svg'}" in out
    assert "  rejected   big: the file is " in out and "the sanitiser takes at most 60000" in out
    assert "  rejected   moon: note_zh is 61 characters, the limit is 60" in out
    assert "images-import: 0 imported, 0 unchanged, 7 rejected" in out
    assert conn.execute("SELECT COUNT(*) FROM word_images").fetchone()[0] == 0 and store.list_files(cfg) == []
    # with the one bad caption fixed, the good card goes in although its neighbours are still rejected (exit 1 says so)
    cards["moon"]["note_zh"] = NOTE
    assert cli.main(["images-import", str(studio), "--manifest", str(write_manifest(studio, cards))]) == 1
    out = capsys.readouterr().out
    assert "  imported   moon\n" in out and "images-import: 1 imported, 0 unchanged, 6 rejected" in out
    assert image_meta(conn, moon)["word_layer"] is True and all(images(conn, w) == [] for w in (noon, private, merged, pear))


def test_import_turns_away_what_the_gate_refuses_and_stores_no_css(conn, cfg, tmp_path, capsys):
    """One sanitiser and one gate for the studio and the import (studio/tools/check runs the same two functions): a scene that
    paints with a gradient defined inside the word layer — `?plain=1` would serve it unpainted — and a card outside the blur
    budget are `rejected` in the gate's own words, in the dry run already; a `style` attribute and a CSS-escaped paint are not
    refused but are not in the stored file either (the import takes raw files: only the studio reports what was dropped)."""
    noon, pear, kiwi = insert_word(conn, "noon"), insert_word(conn, "pear"), insert_word(conn, "kiwi")
    sky = '<defs><linearGradient id="sky"><stop offset="0" stop-color="#123"/></linearGradient></defs>'
    (tmp_path / "noon.svg").write_text(small_card("noon").replace('fill="#2F3F96"', 'fill="url(#sky)"').replace('<g id="word-art">', f'<g id="word-art">{sky}'), encoding="utf-8")
    (tmp_path / "pear.svg").write_text(small_card("pear").replace('<feGaussianBlur stdDeviation="4"/>', '<feDropShadow stdDeviation="4"/>' * 4), encoding="utf-8")
    css = small_card("kiwi").replace('fill="#2F3F96"', 'fill="u\\72l(#sky)" style="filter:blur(20px)"').replace('r="60"', 'r="60" style="clip-path:circle(20%)"')
    (tmp_path / "kiwi.svg").write_text(css.replace("<defs>", "<defs>" + sky[len("<defs>") : -len("</defs>")]), encoding="utf-8")
    manifest = str(write_manifest(tmp_path, {"noon": {"hook_zh": "正午"}, "pear": {"hook_zh": "梨"}, "kiwi": {"hook_zh": "猕猴桃"}}))
    for flags, verdict in ((["--dry-run"], "  ok         kiwi (would be imported)\n"), ([], "  imported   kiwi\n")):
        assert cli.main(["images-import", str(tmp_path), "--manifest", manifest, *flags]) == 1
        out = capsys.readouterr().out
        assert '  rejected   noon: the picture without the word layer (?plain=1) uses #sky, defined inside <g id="word-art"> and cut away with it: move the definition to the root <defs>\n' in out
        assert '  rejected   pear: <filter id="soft"> chains 4 feGaussianBlur / feDropShadow primitives, at most 3 may: use one per filter' in out
        assert verdict in out and "2 rejected" in out
    assert images(conn, noon) == [] and images(conn, pear) == [] and len(store.list_files(cfg)) == 1
    stored = (cfg.images_dir / images(conn, kiwi)[0]["file_path"]).read_text(encoding="utf-8")
    assert "style" not in stored and "\\" not in stored and "blur(" not in stored and "circle(" not in stored and 'id="sky"' in stored
    assert stored.count("<rect") == 1 and stored.count("<circle") == 1 and memo.check_structure(stored, "kiwi") == []  # the shapes stay, without the CSS


def test_import_again_is_unchanged_even_on_a_later_day_and_brings_captions_up_to_date(conn, cfg, studio, capsys):
    """The stored file carries the AIGC label of the day it was first imported: a later run compares against that label, so
    the same card is `unchanged` — no new row, no new file — and only its captions follow the manifest."""
    wid = insert_word(conn, "moon")
    manifest = json.loads((studio / "manifest.json").read_text(encoding="utf-8"))
    first = image_handler.import_cards(conn, cfg, studio, manifest, now="2026-10-14T00:00:00Z")
    assert (first.imported, first.unchanged, first.rejected) == (["moon"], [], [])
    again = image_handler.import_cards(conn, cfg, studio, manifest, now="2026-10-21T09:00:00Z")
    assert (again.imported, again.unchanged, again.rejected, again.recaptioned) == ([], ["moon"], [], [])
    assert len(images(conn, wid)) == 1 and len(store.list_files(cfg)) == 1 and images(conn, wid)[0]["created_at"] == "2026-10-14T00:00:00Z"
    assert cli.main(["images-import", str(studio), "--manifest", str(studio / "manifest.json")]) == 0  # today's date, through the command
    out = capsys.readouterr().out
    assert "  unchanged  moon\n" in out and "images-import: 0 imported, 1 unchanged, 0 rejected" in out and len(images(conn, wid)) == 1
    # a corrected hook in the manifest: the picture is unchanged, the row's captions are updated in place (dry run: reported only)
    fixed = write_manifest(studio, {"moon": {"alt_zh": ALT, "hook_zh": "两个 o 是两轮圆月。", "note_zh": None}})
    assert cli.main(["images-import", str(studio), "--manifest", str(fixed), "--dry-run"]) == 0
    assert "  unchanged  moon (captions would be updated)" in capsys.readouterr().out and images(conn, wid)[0]["hook_zh"] == HOOK
    assert cli.main(["images-import", str(studio), "--manifest", str(fixed)]) == 0
    out = capsys.readouterr().out
    assert "  unchanged  moon (captions updated)" in out and "1 unchanged (1 with new captions)" in out
    row = images(conn, wid)[0]
    assert len(images(conn, wid)) == 1 and (row["alt_zh"], row["hook_zh"], row["note_zh"]) == (ALT, "两个 o 是两轮圆月。", None) and row["status"] == "active"
    # a redrawn card (different bytes) is a new picture: the earlier card becomes superseded
    (studio / "moon.svg").write_text(small_card("moon"), encoding="utf-8")
    assert cli.main(["images-import", str(studio), "--manifest", str(fixed)]) == 0
    assert "  imported   moon\n" in capsys.readouterr().out
    assert [r["status"] for r in images(conn, wid)] == ["superseded", "active"] and all(memo.is_memo(r) for r in images(conn, wid))


def test_import_again_is_unchanged_for_a_card_the_sanitiser_emptied_an_element_of(conn, cfg, tmp_path):
    """The import cleans a card ONCE: what it compares with the active picture is what it stores. clean() writes an element whose
    children it dropped as `<defs></defs>` and that text, cleaned again, as `<defs/>` — stored after a second pass, such a card was
    `imported` on every run, a new row each time (studio/tools/check reports dropped elements, but the import takes raw files)."""
    wid = insert_word(conn, "moon")
    raw = small_card("moon").replace('<g id="scene">', '<defs><style>.sky{fill:#123}</style></defs><g id="scene"><g><text x="10" y="20">moon</text></g>')
    (tmp_path / "moon.svg").write_text(raw, encoding="utf-8")
    manifest = {"prompt_version": "memo-1", "model": MODEL, "cards": {"moon": {"hook_zh": HOOK}}}
    first = image_handler.import_cards(conn, cfg, tmp_path, manifest, now="2026-10-14T00:00:00Z")
    dry = image_handler.import_cards(conn, cfg, tmp_path, manifest, dry_run=True, now="2026-10-15T09:00:00Z")
    again = image_handler.import_cards(conn, cfg, tmp_path, manifest, now="2026-10-15T09:00:00Z")
    assert (first.imported, first.unchanged, first.rejected) == (["moon"], [], [])
    assert (dry.imported, dry.unchanged, dry.rejected) == ([], ["moon"], []) and (again.imported, again.unchanged, again.rejected) == ([], ["moon"], [])
    rows = images(conn, wid)
    assert [(r["status"], r["created_at"]) for r in rows] == [("active", "2026-10-14T00:00:00Z")] and len(store.list_files(cfg)) == 1
    stored = (cfg.images_dir / rows[0]["file_path"]).read_text(encoding="utf-8")
    assert stored == sanitize_svg.with_label(sanitize_svg.clean(raw, allow_text=False, effects=True), f"AI-generated illustration · word-Dance · {MODEL} · 2026-10-14")
    assert "<style" not in stored and "<text" not in stored and memo.check_structure(stored, "moon") == []
    # activate_memo — prepare + store in one call — stores the same bytes for the same raw file
    noon = insert_word(conn, "noon")
    activate_memo(conn, cfg, noon, raw.replace("wa-0-m", "wa-0-n"), alt_zh=None, hook_zh=None, note_zh=None, model=MODEL, prompt_version="memo-1", now="2026-10-14T00:00:00Z")
    assert (cfg.images_dir / images(conn, noon)[0]["file_path"]).read_text(encoding="utf-8") == stored.replace("wa-0-m", "wa-0-n")


def test_import_again_writes_back_the_file_of_an_unchanged_card(conn, cfg, studio, capsys, monkeypatch):
    """`run the import again` is the documented repair for a card whose file images/ lost (a partial copy to the new server,
    images restored from an older archive than the database): comparing sha256 alone answered `unchanged` over a URL that is 404."""
    wid = insert_word(conn, "moon")
    manifest = str(studio / "manifest.json")
    assert cli.main(["images-import", str(studio), "--manifest", manifest]) == 0
    row = images(conn, wid)[0]
    stored = cfg.images_dir / row["file_path"]
    data = stored.read_bytes()
    stored.unlink()
    capsys.readouterr()
    assert cli.main(["images-import", str(studio), "--manifest", manifest, "--dry-run"]) == 0
    out = capsys.readouterr().out
    assert "  unchanged  moon (file missing from images/ — a real run restores it)" in out and "0 would be imported, 1 unchanged (1 with a missing file), 0 rejected" in out
    assert not stored.exists()  # a dry run writes nothing
    assert cli.main(["images-import", str(studio), "--manifest", manifest]) == 0
    out = capsys.readouterr().out
    assert "  unchanged  moon (file restored)" in out and "images-import: 0 imported, 1 unchanged (1 with the file restored), 0 rejected" in out
    assert stored.read_bytes() == data and images(conn, wid) == [row] and store.list_files(cfg) == [row["file_path"]]  # the same bytes on the same path, the row untouched
    assert cli.main(["images-import", str(studio), "--manifest", manifest]) == 0
    assert "  unchanged  moon\n" in capsys.readouterr().out  # nothing left to restore
    # a file cut short is restored too, together with a corrected caption
    stored.write_bytes(data[:100])
    fixed = write_manifest(studio, {"moon": {"alt_zh": ALT, "hook_zh": "两个 o 是两轮圆月。", "note_zh": NOTE}})
    assert cli.main(["images-import", str(studio), "--manifest", str(fixed)]) == 0
    out = capsys.readouterr().out
    assert "  unchanged  moon (captions updated; file restored)" in out and "1 unchanged (1 with new captions, 1 with the file restored)" in out
    assert stored.read_bytes() == data and images(conn, wid)[0]["hook_zh"] == "两个 o 是两轮圆月。" and len(images(conn, wid)) == 1
    # the file cannot be written back: the card is `rejected: could not store`, not `unchanged`, and its captions are left alone
    stored.unlink()

    def read_only(*args, **kwargs):
        raise OSError(30, "Read-only file system")

    monkeypatch.setattr(store, "write_bytes", read_only)
    report = image_handler.import_cards(conn, cfg, studio, image_handler.load_manifest(studio / "manifest.json") | {"cards": {"moon": {"hook_zh": HOOK}}})
    assert (report.unchanged, report.recaptioned, report.restored) == ([], [], []) and report.rejected == [("moon", "could not store: [Errno 30] Read-only file system")]
    assert images(conn, wid)[0]["hook_zh"] == "两个 o 是两轮圆月。" and not stored.exists() and not conn.in_transaction


def test_import_only_and_lemmas_with_spaces(conn, cfg, studio, capsys):
    """`--only LEMMA …` narrows the run to those manifest lemmas; a lemma's spaces are `_` in the file name; the card spells the
    word's display form."""
    moon = insert_word(conn, "moon")
    ice = insert_word(conn, "ice cream", kind="phrase")
    china = insert_word(conn, "china", display="China")
    (studio / "ice_cream.svg").write_text(small_card("ice cream"), encoding="utf-8")
    (studio / "china.svg").write_text(small_card("China"), encoding="utf-8")
    manifest = write_manifest(studio, {"moon": {"hook_zh": HOOK}, "ice cream": {"hook_zh": "ice 是冰，cream 是奶油。"}, "china": {}})
    assert cli.main(["images-import", str(studio), "--manifest", str(manifest), "--only", "Ice  Cream", "china", "pear"]) == 1
    out = capsys.readouterr().out
    assert "  imported   ice cream\n" in out and "  imported   china\n" in out and "  rejected   pear: not in the manifest" in out and "moon" not in out
    assert image_meta(conn, ice)["hook_zh"] == "ice 是冰，cream 是奶油。" and image_meta(conn, china)["word_layer"] is True and images(conn, moon) == []
    (studio / "china.svg").write_text(small_card("china"), encoding="utf-8")  # lower-case letters for a word displayed as China
    assert cli.main(["images-import", str(studio), "--manifest", str(manifest), "--only", "china"]) == 1
    assert "rejected   china: word-art spells 'china'" in capsys.readouterr().out
    assert image_handler.card_file(studio, "ice cream") == studio / "ice_cream.svg"
    for key in ("../moon", "a/b", ".hidden", "", "a\\b"):
        assert image_handler.card_file(studio, key) is None, key


def test_manifest_keys_naming_one_word_are_refused_and_the_file_name_is_the_lemma(conn, cfg, studio, capsys):
    """A key is matched to words.lemma in normalised form, so `moon` / `MOON` / ` moon ` are ONE word: worked in turn they imported
    it once and re-captioned it twice, the last hook winning, exit 0. And the file was named after the raw key — `Ice  Cream` read
    Ice__Cream.svg, `Monday` Monday.svg: found on the Mac's case-insensitive volume, `no file` on the Linux server."""
    for cards in ({"moon": {}, "MOON": {}}, {"moon": {}, " moon ": {}}, {"ice cream": {}, "Ice  Cream": {}}):
        with pytest.raises(image_handler.ManifestError, match="name the same word"):
            image_handler.load_manifest(write_manifest(studio, cards))
    insert_word(conn, "moon")
    twice = str(write_manifest(studio, {"moon": {"hook_zh": "第一句"}, "Moon": {"hook_zh": "第二句"}}))
    assert cli.main(["images-import", str(studio), "--manifest", twice]) == 2  # unusable manifest: nothing is done
    assert "cards['moon'] and cards['Moon'] name the same word" in capsys.readouterr().err
    assert cli.main(["images-import", "--undo", twice]) == 2 and "name the same word" in capsys.readouterr().err  # --undo reads it through the same loader
    assert conn.execute("SELECT COUNT(*) FROM word_images").fetchone()[0] == 0
    two = image_handler.load_manifest(write_manifest(studio, {"ice cream": {}, "ice_cream": {}, "moon": {}, "moons": {}}))  # different lemmas stay different
    assert list(two["cards"]) == ["ice cream", "ice_cream", "moon", "moons"]
    assert image_handler.card_file(studio, "Ice  Cream") == studio / "ice_cream.svg" and image_handler.card_file(studio, "Monday") == studio / "monday.svg"
    assert image_handler.card_file(studio, " moon ") == studio / "moon.svg"
    for key in ("../moon", "a/b", "..", ".hidden", "", "  ", "a\\b", "x/../../etc/passwd", "nul\0x"):
        assert image_handler.card_file(studio, key) is None, key
    # a manifest keyed by a display form reads the lemma's file …
    ice = insert_word(conn, "ice cream", kind="phrase")
    (studio / "ice_cream.svg").write_text(small_card("ice cream"), encoding="utf-8")
    report = image_handler.import_cards(conn, cfg, studio, image_handler.load_manifest(write_manifest(studio, {"Ice  Cream": {"hook_zh": "ice 是冰，cream 是奶油。"}})), now=NOW)
    assert (report.imported, report.rejected) == (["Ice  Cream"], []) and image_meta(conn, ice)["word_layer"] is True
    # … and `no file` names the path that was looked for
    insert_word(conn, "monday", display="Monday")
    report = image_handler.import_cards(conn, cfg, studio, image_handler.load_manifest(write_manifest(studio, {"Monday": {}})), now=NOW)
    assert report.rejected == [("Monday", f"no file {studio / 'monday.svg'}")]


def test_import_usage_errors_and_a_database_behind_schema_21(conn, cfg, studio, tmp_path, capsys, monkeypatch):
    manifest = studio / "manifest.json"
    bad = tmp_path / "bad.json"
    for text in ("not json", "[]", '{"prompt_version": "memo-1", "model": "m"}', '{"prompt_version": "memo-1", "model": "m", "cards": {}}', '{"prompt_version": "", "model": "m", "cards": {"moon": {}}}', '{"prompt_version": "memo-1", "model": "m", "cards": {"moon": "x"}}'):
        bad.write_text(text, encoding="utf-8")
        assert cli.main(["images-import", str(studio), "--manifest", str(bad)]) == 2, text
        assert "wd images-import: " in capsys.readouterr().err
    assert cli.main(["images-import", str(studio), "--manifest", str(tmp_path / "missing.json")]) == 2 and "cannot read" in capsys.readouterr().err
    assert cli.main(["images-import", str(tmp_path / "nodir"), "--manifest", str(manifest)]) == 2 and "is not a directory" in capsys.readouterr().err
    assert conn.execute("SELECT COUNT(*) FROM word_images").fetchone()[0] == 0
    # the import-seed / learn-order precedent: one line, exit 1, no traceback when 0021 has not been applied yet
    old = tmp_path / "migrations"
    old.mkdir()
    for f in db.list_migration_files():
        if f.version <= 20:
            shutil.copy(f.path, old / f.path.name)
    behind = tmp_path / "behind.db"
    c = db.connect(behind)
    try:
        db.run_migrations(c, migrations_dir=old)
        assert db.current_version(c) == 20
    finally:
        c.close()
    monkeypatch.setenv("WD_DB_PATH", str(behind))
    assert cli.main(["images-import", str(studio), "--manifest", str(manifest)]) == 1
    assert "schema version 20 has no word_images.hook_zh (migration 0021) — run `wd migrate` first" in capsys.readouterr().err
    assert cli.main(["images-import", "--undo", str(manifest)]) == 1 and "run `wd migrate` first" in capsys.readouterr().err


@pytest.mark.parametrize("model", ["claude\u0001opus", "claude\ufffe", "claude\ud800", "claude\u001b[0m"], ids=["control-character", "noncharacter", "lone-surrogate", "escape-sequence"])
def test_import_refuses_a_model_name_that_would_break_the_aigc_label(conn, cfg, studio, model):
    """All four are legal JSON strings. The first three passed every check — the structure is checked on the unlabelled text — and
    were written into `<desc id="aigc-label">` of every card of the batch: `imported`, and a file no browser can parse; the lone
    surrogate ended the real run with UnicodeEncodeError after the dry run had said `would be imported`."""
    wid = insert_word(conn, "moon")
    manifest = {"prompt_version": "memo-1", "model": model, "cards": {"moon": {"hook_zh": HOOK}}}
    for dry_run in (True, False):
        report = image_handler.import_cards(conn, cfg, studio, manifest, dry_run=dry_run, now=NOW)
        assert report.imported == [] and [k for k, _ in report.rejected] == ["moon"], report
        assert "model must name the model that drew the card (1–80 printable characters)" in report.rejected[0][1]
    assert images(conn, wid) == [] and word_state(conn, wid) == ("none", None) and store.list_files(cfg) == []
    # the names people write pass, their whitespace collapsed — a tab or a line break between two words included
    ok = store.prepare_memo(small_card("moon"), "moon", alt_zh=None, hook_zh=None, note_zh=None, model="  Claude\tOpus 4.5\n（画师）", prompt_version="memo-1")
    assert ok.model == "Claude Opus 4.5 （画师）" and store.MODEL_MAX_CHARS == 80


@pytest.mark.parametrize("where", ["key", "hook_zh", "alt_zh", "prompt_version", "model"])
def test_a_manifest_with_half_a_surrogate_pair_is_refused_whole(conn, cfg, studio, capsys, where):
    """`"\\ud83c"` without its second half is legal JSON and not text: it can be written neither into the card's file nor into the
    database. In a caption or the version label it passed the dry run and ended the real run with UnicodeEncodeError — in the
    middle of the batch; in `model` it broke the summary line. The loader refuses such a manifest: exit 2, nothing done."""
    wid = insert_word(conn, "moon")
    data = {"prompt_version": "memo-1", "model": MODEL, "cards": {"moon": {"alt_zh": ALT, "hook_zh": HOOK}}}
    if where == "key":
        data["cards"]["noon\ud83c"] = {}
    elif where in ("hook_zh", "alt_zh"):
        data["cards"]["moon"][where] = "月亮\ud83c"
    else:
        data[where] += "\ud83c"
    path = studio / "manifest.json"
    path.write_text(json.dumps(data), encoding="utf-8")  # ensure_ascii: the escape is written as six ASCII characters, as a tool would
    for flags in (["--dry-run"], []):
        assert cli.main(["images-import", str(studio), "--manifest", str(path), *flags]) == 2
        err = capsys.readouterr().err
        assert "holds a lone surrogate escape" in err and "\\ud83c" in err and err.isprintable() is False and err.strip().isprintable()  # named by its escape: one printable line
    assert cli.main(["images-import", "--undo", str(path)]) == 2
    assert images(conn, wid) == [] and store.list_files(cfg) == []
    # a whole pair is a character like any other
    data = {"prompt_version": "memo-1", "model": MODEL, "cards": {"moon": {"hook_zh": "月亮 \ud83c\udf19"}}}
    path.write_text(json.dumps(data), encoding="utf-8")
    assert cli.main(["images-import", str(studio), "--manifest", str(path)]) == 0 and images(conn, wid)[0]["hook_zh"] == "月亮 🌙"


@pytest.mark.parametrize(
    "target,error",
    [("write_bytes", OSError(28, "No space left on device")), ("activate", sqlite3.OperationalError("database is locked"))],
    ids=["disk-full", "database-locked"],
)
def test_a_card_that_cannot_be_stored_is_its_own_verdict_and_the_run_goes_on(conn, cfg, studio, monkeypatch, capsys, target, error):
    """A full disk or a write lock that outlives the retries used to end the run with a traceback: the cards before it committed
    and live, and not one line of output to say which. Now it is that card's `rejected`, the summary is printed, exit 1."""
    lemmas = ("moon", "rain", "swim")
    for lemma in lemmas:
        insert_word(conn, lemma)
        (studio / f"{lemma}.svg").write_text(small_card(lemma), encoding="utf-8")
    path = str(write_manifest(studio, {lemma: {"hook_zh": lemma} for lemma in lemmas}))
    manifest = image_handler.load_manifest(path)
    real = getattr(store, target)
    calls: list[int] = []

    def second_call_fails(*args, **kwargs):
        calls.append(1)
        if len(calls) == 2:
            raise error
        return real(*args, **kwargs)

    monkeypatch.setattr(store, target, second_call_fails)
    report = image_handler.import_cards(conn, cfg, studio, manifest, now=NOW)
    assert (report.imported, report.unchanged, report.rejected) == (["moon", "swim"], [], [("rain", f"could not store: {error}")])
    assert not conn.in_transaction  # the card's transaction was rolled back; the connection went on to the next card
    assert [r[0] for r in conn.execute("SELECT w.lemma FROM words w JOIN word_images wi ON wi.id = w.active_image_id WHERE wi.prompt_version = 'memo-1' ORDER BY w.lemma")] == ["moon", "swim"]

    def always_fails(*args, **kwargs):
        raise error

    monkeypatch.setattr(store, target, always_fails)  # through the command: every verdict and the summary are printed, exit 1
    assert cli.main(["images-import", str(studio), "--manifest", path]) == 1
    out = capsys.readouterr().out
    assert f"  rejected   rain: could not store: {error}" in out and out.rstrip().splitlines()[-1].startswith("images-import: 0 imported, ")
    monkeypatch.setattr(store, target, real)  # the fault gone, a second run finishes the batch
    assert cli.main(["images-import", str(studio), "--manifest", path]) == 0
    out = capsys.readouterr().out
    assert "  imported   rain\n" in out and "  unchanged  moon\n" in out and "  unchanged  swim\n" in out and "images-import: 1 imported, 2 unchanged, 0 rejected" in out


def test_a_card_an_admin_took_down_is_not_reinstated_by_a_whole_manifest_import(conn, cfg, studio, capsys):
    """A learner's 不合适 on a card is only recorded, so a `rejected` card row means one thing: an admin resolved the report with
    refetch_image (API.md 71). The next whole-manifest run — the 100-card batch — must not bring that very picture back as one
    more `imported` line; naming the word with --only does, and a redrawn file is another picture."""
    moon, noon = insert_word(conn, "moon"), insert_word(conn, "noon")
    drawing = activate_svg(conn, cfg, moon, OLD_DRAWING, "夜空里的月亮", now="2026-10-01T00:00:00Z", model="claude-sonnet-4-5", prompt_version="svg-v2")
    (studio / "noon.svg").write_text(small_card("noon"), encoding="utf-8")
    manifest = str(write_manifest(studio, {"moon": {"alt_zh": ALT, "hook_zh": HOOK, "note_zh": NOTE}, "noon": {"hook_zh": "正午"}}))
    assert cli.main(["images-import", str(studio), "--manifest", manifest]) == 0
    card_id = word_state(conn, moon)[1]
    reject_active_image(conn, moon, reason="report:irrelevant_image", now="2026-10-15T00:00:00Z")  # what endpoint 71 does with refetch_image
    conn.execute("UPDATE jobs SET status = 'done', finished_at = '2026-10-15T00:01:00Z', result_json = '{\"status\": \"failed\"}' WHERE type = 'fetch_image'")
    conn.execute("UPDATE words SET image_state = 'failed' WHERE id = ?", (moon,))  # the fetch that followed found nothing: the template card
    capsys.readouterr()
    for flags, would in ((["--dry-run"], "would be "), ([], "")):
        assert cli.main(["images-import", str(studio), "--manifest", manifest, *flags]) == 0  # left down is not an error
        out = capsys.readouterr().out
        assert f"  retired    moon: an admin took this very card down after a report (image {card_id}) — left as it is; pass --only moon to bring it back" in out
        assert f"images-import: 0 {would}imported, 1 unchanged, 0 rejected, 1 retired (memo-1, {MODEL})" in out and "  unchanged  noon\n" in out
        assert [r["status"] for r in images(conn, moon)] == ["superseded", "rejected"] and word_state(conn, moon) == ("failed", None)
    card = store.prepare_memo((studio / "moon.svg").read_text(encoding="utf-8"), "moon", alt_zh=None, hook_zh=None, note_zh=None, model=MODEL, prompt_version="memo-1")
    assert store.retired_memo(conn, moon, card)["id"] == card_id and store.retired_memo(conn, noon, card) is None
    # --undo has nothing to do for it: the active picture (here: none) is not a card, the admin's decision stands
    assert cli.main(["images-import", "--undo", manifest, "--only", "moon"]) == 0
    assert "  kept       moon: the active picture is not a memory card" in capsys.readouterr().out and word_state(conn, moon) == ("failed", None)
    # naming the word is the deliberate act that brings the card back
    assert cli.main(["images-import", str(studio), "--manifest", manifest, "--only", "moon"]) == 0
    out = capsys.readouterr().out
    assert "  imported   moon\n" in out and "images-import: 1 imported, 0 unchanged, 0 rejected (memo-1" in out
    assert [r["status"] for r in images(conn, moon)] == ["superseded", "rejected", "active"] and image_meta(conn, moon)["word_layer"] is True
    # the rollback of that import walks past the card that was taken down, to the drawing under both cards
    assert store.undo_memo(conn, cfg, moon, now=NOW)[0] == "restored" and word_state(conn, moon) == ("ready", drawing)
    # … and is no retirement: the newest row of this picture is the one the operator brought back, so a whole-manifest run imports it
    assert store.retired_memo(conn, moon, card) is None
    assert cli.main(["images-import", str(studio), "--manifest", manifest]) == 0
    out = capsys.readouterr().out
    assert "  imported   moon\n" in out and "retired" not in out
    assert [r["status"] for r in images(conn, moon)] == ["superseded", "rejected", "superseded", "active"]
    # taken down again (a second report, resolved the same way): the rule holds for the newest row
    reject_active_image(conn, moon, reason="report:inappropriate_image", now="2026-10-20T00:00:00Z")
    assert store.retired_memo(conn, moon, card)["id"] == images(conn, moon)[3]["id"]
    # a redrawn card is not the picture that was taken down: a whole-manifest run imports it
    (studio / "moon.svg").write_text(small_card("moon"), encoding="utf-8")
    assert cli.main(["images-import", str(studio), "--manifest", manifest]) == 0
    out = capsys.readouterr().out
    assert "  imported   moon\n" in out and "retired" not in out and image_meta(conn, moon)["word_layer"] is True


# -------------------------------------------------------------------------------------------------- undo
def test_undo_puts_the_previous_drawing_back(conn, cfg, studio, capsys):
    wid = insert_word(conn, "moon")
    old_id = activate_svg(conn, cfg, wid, OLD_DRAWING, "夜空里的月亮", now="2026-10-01T00:00:00Z", model="claude-sonnet-4-5", prompt_version="svg-v2")
    manifest = str(studio / "manifest.json")
    assert cli.main(["images-import", str(studio), "--manifest", manifest]) == 0
    card_id = word_state(conn, wid)[1]
    capsys.readouterr()
    assert cli.main(["images-import", "--undo", manifest, "--dry-run"]) == 0
    out = capsys.readouterr().out
    assert f"  undone     moon → claude_svg image {old_id} would be active again" in out and out.rstrip().endswith("— dry run, nothing written")
    assert word_state(conn, wid) == ("ready", card_id)  # nothing written
    assert cli.main(["images-import", "--undo", manifest]) == 0
    out = capsys.readouterr().out
    assert f"  undone     moon → claude_svg image {old_id} active again" in out
    assert "images-import --undo: 1 memory card(s) superseded (1 word(s) back on the previous picture, 0 on the template card), 0 kept, 0 unknown" in out
    old, card = images(conn, wid)
    assert (old["id"], old["status"], card["id"], card["status"]) == (old_id, "active", card_id, "superseded") and (cfg.images_dir / card["file_path"]).is_file()
    assert word_state(conn, wid) == ("ready", old_id)
    meta = image_meta(conn, wid)
    assert (meta["id"], meta["kind"], meta["word_layer"], meta["hook_zh"], meta["alt_zh"]) == (old_id, "svg", False, None, "夜空里的月亮")
    # a second undo has nothing to undo; importing again brings the card back as a new row, and undo still finds the old drawing
    assert cli.main(["images-import", "--undo", manifest]) == 0
    assert "  kept       moon: the active picture is not a memory card" in capsys.readouterr().out and word_state(conn, wid) == ("ready", old_id)
    assert cli.main(["images-import", str(studio), "--manifest", manifest]) == 0
    assert [r["status"] for r in images(conn, wid)] == ["superseded", "superseded", "active"] and image_meta(conn, wid)["word_layer"] is True
    assert cli.main(["images-import", "--undo", manifest]) == 0
    assert [r["status"] for r in images(conn, wid)] == ["active", "superseded", "superseded"] and word_state(conn, wid) == ("ready", old_id)


def test_undo_goes_back_to_the_template_card_when_there_is_no_earlier_picture(conn, cfg, studio, capsys):
    wid = insert_word(conn, "moon")  # never had a picture: the template card
    manifest = str(studio / "manifest.json")
    assert cli.main(["images-import", str(studio), "--manifest", manifest]) == 0
    card_id = word_state(conn, wid)[1]
    capsys.readouterr()
    assert cli.main(["images-import", "--undo", manifest]) == 0
    out = capsys.readouterr().out
    assert "  undone     moon → back on the template card (no earlier picture to restore)" in out and "(0 word(s) back on the previous picture, 1 on the template card)" in out
    assert word_state(conn, wid) == ("none", None) and [(r["id"], r["status"]) for r in images(conn, wid)] == [(card_id, "superseded")]
    meta = image_meta(conn, wid)
    assert meta == {"id": None, "url": f"/media/card/{wid}.svg", "kind": "card", "provider": "card_svg", "mime": "image/svg+xml", "width": 800, "height": 500, "alt_zh": None, "attribution": None, "word_layer": False, "hook_zh": None, "note_zh": None}
    # a rejected photo is never brought back, and an earlier picture whose file was pruned is skipped for the one before it
    pear = insert_word(conn, "pear")
    jpg_a, jpg_b = store.write_bytes(cfg, b"\xff\xd8\xff" + b"a" * 100, "jpg"), store.write_bytes(cfg, b"\xff\xd8\xff" + b"b" * 100, "jpg")
    first = store.activate(conn, pear, provider="wikimedia", ref="a", file_path=jpg_a.file_path, file_bytes=jpg_a.file_bytes, sha256=jpg_a.sha256, mime="image/jpeg", now="2026-10-01T00:00:00Z")
    second = store.activate(conn, pear, provider="wikimedia", ref="b", file_path=jpg_b.file_path, file_bytes=jpg_b.file_bytes, sha256=jpg_b.sha256, mime="image/jpeg", now="2026-10-02T00:00:00Z")
    give_card(conn, cfg, pear, small_card("pear"))
    (cfg.images_dir / jpg_b.file_path).unlink()
    assert store.undo_memo(conn, cfg, pear, now=NOW)[0] == "restored" and word_state(conn, pear) == ("ready", first)
    give_card(conn, cfg, pear, small_card("pear"), now="2026-10-15T00:00:00Z")
    conn.execute("UPDATE word_images SET status = 'rejected' WHERE id IN (?, ?)", (first, second))
    assert store.undo_memo(conn, cfg, pear, now=NOW) == ("card", None) and word_state(conn, pear) == ("none", None)
    assert store.undo_memo(conn, cfg, pear, now=NOW) == ("kept", None) and store.undo_memo(conn, cfg, 999_999, now=NOW) == ("kept", None)


def photo(conn, cfg, word_id: int, ref: str, now: str) -> int:
    jpg = store.write_bytes(cfg, b"\xff\xd8\xff" + ref.encode() * 100, "jpg")
    return store.activate(conn, word_id, provider="wikimedia", ref=ref, file_path=jpg.file_path, file_bytes=jpg.file_bytes, sha256=jpg.sha256, mime="image/jpeg", now=now)


def report_found_nothing(conn, word_id: int, now: str) -> None:
    """不合适 on the word's active picture (not a card) and a fetch that found nothing: the template card, image_state failed."""
    job_id = reject_active_image(conn, word_id, reason="irrelevant_image", now=now)
    queue.finish(conn, job_id, {"status": "failed", "detail": "no acceptable photo from any provider"}, now=now)
    conn.execute("UPDATE words SET image_state = 'failed' WHERE id = ?", (word_id,))


def test_undo_never_revives_a_picture_older_than_a_report(conn, cfg):
    """photo → drawing (the photo superseded) → the drawing is reported and nothing replaces it → card → undo. The word was on the
    template card when its card arrived and goes back there: the photo was replaced long before and is not what the card took
    the place of (undo used to restore the newest `superseded` row and never saw the newer `rejected` one)."""
    wid = insert_word(conn, "pear")
    old = photo(conn, cfg, wid, "a", "2026-10-01T00:00:00Z")
    drawing = activate_svg(conn, cfg, wid, OLD_DRAWING, None, now="2026-10-02T00:00:00Z", model="claude-sonnet-4-5", prompt_version="svg-v2")
    report_found_nothing(conn, wid, "2026-10-03T00:00:00Z")
    assert image_meta(conn, wid)["kind"] == "card" and word_state(conn, wid)[1] is None
    card_id = give_card(conn, cfg, wid, small_card("pear"))
    assert store.undo_memo(conn, cfg, wid, now=NOW, dry_run=True) == ("card", None) and word_state(conn, wid) == ("ready", card_id)
    assert store.undo_memo(conn, cfg, wid, now=NOW) == ("card", None)
    assert word_state(conn, wid)[1] is None and image_meta(conn, wid)["kind"] == "card"
    assert [(r["id"], r["status"]) for r in images(conn, wid)] == [(old, "superseded"), (drawing, "rejected"), (card_id, "superseded")]


def test_undo_goes_back_to_what_the_word_showed_when_its_card_arrived(conn, cfg):
    """The histories around the rule above keep their answers."""
    # a report whose fetch DID find a replacement: that picture is newer than the report and comes back
    plum = insert_word(conn, "plum")
    photo(conn, cfg, plum, "a", "2026-10-01T00:00:00Z")
    reject_active_image(conn, plum, reason="irrelevant_image", now="2026-10-02T00:00:00Z")
    found = photo(conn, cfg, plum, "b", "2026-10-03T00:00:00Z")
    give_card(conn, cfg, plum, small_card("plum"))
    assert store.undo_memo(conn, cfg, plum, now=NOW)[0] == "restored" and word_state(conn, plum) == ("ready", found)
    # a redrawn card over a card: the earlier card is skipped, the drawing under both is restored
    noon = insert_word(conn, "noon")
    drawing = activate_svg(conn, cfg, noon, OLD_DRAWING, None, now="2026-10-01T00:00:00Z", model="claude-sonnet-4-5", prompt_version="svg-v2")
    give_card(conn, cfg, noon, small_card("noon"), now="2026-10-02T00:00:00Z")
    give_card(conn, cfg, noon, small_card("noon").replace("#2F3F96", "#2F3F97"), now="2026-10-03T00:00:00Z")
    assert store.undo_memo(conn, cfg, noon, now=NOW)[0] == "restored" and word_state(conn, noon) == ("ready", drawing)
    # that drawing is reported afterwards, nothing replaces it, the card is imported again: undo → the template card, although the
    # drawing's row is `rejected` only since AFTER the first card — the newest earlier picture that is no card decides
    report_found_nothing(conn, noon, "2026-10-05T00:00:00Z")
    give_card(conn, cfg, noon, small_card("noon"), now="2026-10-06T00:00:00Z")
    assert store.undo_memo(conn, cfg, noon, now=NOW) == ("card", None) and image_meta(conn, noon)["kind"] == "card"
    # a card an admin took down (rejected) and the operator imported again with --only: a card row of ANY status is skipped —
    # the report was about the card, not about the drawing under it
    kiwi = insert_word(conn, "kiwi")
    under = activate_svg(conn, cfg, kiwi, OLD_DRAWING, None, now="2026-10-01T00:00:00Z", model="claude-sonnet-4-5", prompt_version="svg-v2")
    give_card(conn, cfg, kiwi, small_card("kiwi"), now="2026-10-02T00:00:00Z")
    reject_active_image(conn, kiwi, reason="report:inappropriate_image", now="2026-10-03T00:00:00Z")
    give_card(conn, cfg, kiwi, small_card("kiwi"), now="2026-10-04T00:00:00Z")
    assert [r["status"] for r in images(conn, kiwi)] == ["superseded", "rejected", "active"]
    assert store.undo_memo(conn, cfg, kiwi, now=NOW)[0] == "restored" and word_state(conn, kiwi) == ("ready", under)


def test_undo_to_the_template_card_keeps_failed_for_a_word_whose_fetch_had_been_tried(conn, cfg, studio, capsys):
    """A word that was on the template card with image_state `failed` (the chain ran and found nothing) came back `none` after
    import + undo — and the retry rules only ever select `failed`, so a studied word with ready content was never fetched again.
    `none` stays the answer for a word no fetch was ever tried for; a fetch the card itself held back (换一张 → skipped) is no try."""
    moon, noon = insert_word(conn, "moon"), insert_word(conn, "noon")
    tried = service.enqueue_fetch(conn, moon, priority=20, now="2026-10-01T00:00:00Z")
    queue.finish(conn, tried, {"status": "failed", "detail": "no acceptable photo from any provider"}, now="2026-10-01T00:00:05Z")
    conn.execute("UPDATE words SET image_state = 'failed' WHERE id = ?", (moon,))
    (studio / "noon.svg").write_text(small_card("noon"), encoding="utf-8")
    manifest = str(write_manifest(studio, {"moon": {"hook_zh": HOOK}, "noon": {"hook_zh": "正午"}}))
    assert (word_state(conn, moon), word_state(conn, noon)) == (("failed", None), ("none", None))
    assert cli.main(["images-import", str(studio), "--manifest", manifest]) == 0
    held = request_refresh(conn, noon, now="2026-10-14T00:00:00Z")  # 换一张 from an old page: the guard ends it unrun
    queue.finish(conn, held, {"skipped": image_handler.SKIPPED_MEMORY_CARD}, now="2026-10-14T00:00:05Z")
    conn.execute("UPDATE words SET image_state = 'ready' WHERE id = ?", (noon,))
    cards = (word_state(conn, moon), word_state(conn, noon))
    capsys.readouterr()
    assert cli.main(["images-import", "--undo", manifest, "--dry-run"]) == 0
    assert capsys.readouterr().out.count("would be back on the template card") == 2 and (word_state(conn, moon), word_state(conn, noon)) == cards
    assert cli.main(["images-import", "--undo", manifest]) == 0
    assert "(0 word(s) back on the previous picture, 2 on the template card)" in capsys.readouterr().out
    assert (word_state(conn, moon), word_state(conn, noon)) == (("failed", None), ("none", None))  # each as before its card
    row = dict(conn.execute("SELECT id, pos, image_state FROM words WHERE id = ?", (moon,)).fetchone())
    assert service.retry_due(conn, row, "2026-10-20T00:00:00Z") is True  # the retry rules see the word again
    assert (service.chain_was_tried(conn, moon), service.chain_was_tried(conn, noon), service.chain_was_tried(conn, 999_999)) == (True, False, False)


def test_undo_only_touches_the_manifest_words_that_wear_a_card(conn, cfg, studio, capsys):
    moon, noon, pear = insert_word(conn, "moon"), insert_word(conn, "noon"), insert_word(conn, "pear")
    give_card(conn, cfg, moon, (studio / "moon.svg").read_text(encoding="utf-8"))
    give_card(conn, cfg, noon, small_card("noon"))
    drawing = activate_svg(conn, cfg, pear, OLD_DRAWING, None, now=NOW)
    manifest = str(write_manifest(studio, {"moon": {}, "pear": {}, "nosuchword": {}}))
    assert cli.main(["images-import", "--undo", manifest, "--only", "pear", "nosuchword", "kiwi"]) == 1  # an unknown lemma is reported: exit 1
    out = capsys.readouterr().out
    assert "  kept       pear: the active picture is not a memory card" in out and "  unknown    nosuchword" in out and "  unknown    kiwi" in out
    assert "0 memory card(s) superseded" in out and image_meta(conn, moon)["word_layer"] is True
    assert cli.main(["images-import", "--undo", manifest]) == 1
    assert image_meta(conn, moon)["kind"] == "card" and image_meta(conn, noon)["word_layer"] is True  # noon is not in this manifest
    assert word_state(conn, pear) == ("ready", drawing)


# ------------------------------------------------------------------------- guards (docs/MEMORY_CARDS_DESIGN.md §3.6)
def test_fetch_image_never_replaces_a_memory_card_unless_an_admin_asked(ctx, conn, cfg, moon_svg, mock_http, pinned_dns):
    """换一张 from a client that still shows the button, a content job's plain fetch and an automatic retry all end
    {"skipped": "memory_card"} without a single provider request; the card stays active and image_state returns to ready."""
    wid = insert_word(conn, "moon")
    conn.execute("INSERT INTO users(id, username, password_hash) VALUES (1, 'alice', 'x')")
    conn.execute("INSERT INTO user_words(user_id, word_id, state, origin) VALUES (1, ?, 'new', 'browse')", (wid,))  # studied: an SVG fallback would be allowed
    card_id = give_card(conn, cfg, wid, moon_svg, now=ctx.now())
    refresh = request_refresh(conn, wid, now=ctx.now())
    assert word_state(conn, wid) == ("queued", card_id)
    assert worker.drain(ctx, ("fetch_image",)) == 1
    done = job(conn, refresh)
    assert done["status"] == "done" and json.loads(done["result_json"]) == {"skipped": "memory_card"}
    assert word_state(conn, wid) == ("ready", card_id) and image_meta(conn, wid)["word_layer"] is True
    assert mock_http.calls == [] and svg_jobs(conn, wid) == []
    plain = queue.enqueue(conn, "fetch_image", {"word_id": wid}, dedupe_key=f"image:{wid}", priority=20, now=ctx.now())  # what a content job enqueues
    retry = service.enqueue_fetch(conn, wid, priority=30, now=ctx.now(), retry=True)
    assert retry == plain  # folded into the live job; the retry flag is not an admin's request
    worker.drain(ctx, ("fetch_image",))
    assert json.loads(job(conn, plain)["result_json"]) == {"skipped": "memory_card"} and word_state(conn, wid) == ("ready", card_id) and mock_http.calls == []
    assert image_handler.explicit_request({"word_id": wid}) is False and image_handler.explicit_request({"word_id": wid, "exclude": ["x"], "retry": True, "query": "  "}) is False
    assert all(image_handler.explicit_request(p) for p in ({"requested": True}, {"provider": "wikimedia"}, {"query": "full moon"}))
    assert image_handler.explicit_request({"requested": "yes"}) is False and image_handler.SKIPPED_MEMORY_CARD == "memory_card"
    # the admin's refetch (API.md 69) is an explicit decision: the chain runs and the photo supersedes the card
    admin = service.admin_refetch(conn, wid, now=ctx.now())
    assert json.loads(job(conn, admin)["payload_json"])["requested"] is True
    worker.drain(ctx, ("fetch_image",))
    assert json.loads(job(conn, admin)["result_json"])["status"] == "ready" and mock_http.calls_to("commons.wikimedia.org")
    meta = image_meta(conn, wid)
    assert (meta["kind"], meta["word_layer"], meta["hook_zh"]) == ("photo", False, None)
    assert conn.execute("SELECT status FROM word_images WHERE id = ?", (card_id,)).fetchone()[0] == "superseded"


def test_fetch_image_guard_edges_merge_override_report_and_cli(ctx, conn, cfg, moon_svg, mock_http, pinned_dns, capsys):
    # an admin's refetch folded into a learner's still-queued 换一张 makes that job an admin's job
    wid = insert_word(conn, "moon")
    card_id = give_card(conn, cfg, wid, moon_svg, now=ctx.now())
    learner = request_refresh(conn, wid, now=ctx.now())
    assert service.admin_refetch(conn, wid, now=ctx.now()) == learner and json.loads(job(conn, learner)["payload_json"])["requested"] is True
    worker.drain(ctx, ("fetch_image",))
    assert json.loads(job(conn, learner)["result_json"])["status"] == "ready" and image_meta(conn, wid)["kind"] == "photo"
    # a provider / query override without the flag (a job queued by an older build) is explicit as well
    noon = insert_word(conn, "noon")
    give_card(conn, cfg, noon, small_card("noon"), now=ctx.now())
    override = queue.enqueue(conn, "fetch_image", {"word_id": noon, "query": "midday sun"}, dedupe_key=f"image:{noon}", priority=10, now=ctx.now())
    worker.drain(ctx, ("fetch_image",))
    assert json.loads(job(conn, override)["result_json"])["status"] == "ready" and image_meta(conn, noon)["kind"] == "photo"
    # the report flow as an admin runs it (API.md 71, refetch_image → reject_active_image): the card is rejected first, so the fetch
    # that follows is not held back (a learner's own 不合适 never gets here for a card — test_a_learners_report_on_a_memory_card_…)
    pear = insert_word(conn, "pear")
    pear_card = give_card(conn, cfg, pear, small_card("pear"), now=ctx.now())
    report = reject_active_image(conn, pear, reason="irrelevant_image", now=ctx.now())
    assert conn.execute("SELECT status FROM word_images WHERE id = ?", (pear_card,)).fetchone()[0] == "rejected" and word_state(conn, pear) == ("queued", None)
    worker.drain(ctx, ("fetch_image",))
    assert json.loads(job(conn, report)["result_json"])["status"] == "ready" and image_meta(conn, pear)["kind"] == "photo"
    # `wd fetch-image` is the operator's own decision and runs the chain
    plum = insert_word(conn, "plum")
    give_card(conn, cfg, plum, small_card("plum"), now=ctx.now())
    assert cli.main(["fetch-image", "plum"]) == 0
    assert "status: ready" in capsys.readouterr().out and image_meta(conn, plum)["kind"] == "photo"
    # a 换一张 that finds nothing new on a word whose card was already replaced by an admin keeps working as before (no guard involved)
    mock_http.overrides["commons.wikimedia.org"] = lambda req: httpx.Response(200, json=EMPTY_WIKIMEDIA)
    mock_http.overrides["api.openverse.org"] = lambda req: httpx.Response(200, json=EMPTY_OPENVERSE)
    again = request_refresh(conn, wid, now=ctx.now())
    worker.drain(ctx, ("fetch_image",))
    assert json.loads(job(conn, again)["result_json"])["status"] == "failed" and image_meta(conn, wid)["kind"] == "photo"
    assert conn.execute("SELECT status FROM word_images WHERE id = ?", (card_id,)).fetchone()[0] == "superseded"


def test_generate_svg_fallback_never_draws_over_a_memory_card(ctx, conn, cfg, moon_svg):
    """generate_svg: a fallback job (not `requested`) whose word wears a card finishes {"skipped": "photo_active"} without a
    call — the rule that already protects photos; only the admin's explicit `claude_svg` request (API.md 69) draws over it."""
    wid = insert_word(conn, "moon")
    card_id = give_card(conn, cfg, wid, moon_svg, now=ctx.now())
    fallback = queue.enqueue(conn, "generate_svg", {"word_id": wid}, dedupe_key=f"svg:{wid}", priority=20, now=ctx.now())
    assert worker.drain(ctx, ("generate_svg",)) == 1
    assert json.loads(job(conn, fallback)["result_json"]) == {"skipped": "photo_active"}
    assert conn.execute("SELECT COUNT(*) FROM ai_calls").fetchone()[0] == 0 and word_state(conn, wid) == ("ready", card_id) and image_meta(conn, wid)["word_layer"] is True
    requested = queue.enqueue(conn, "generate_svg", {"word_id": wid, "requested": True}, dedupe_key=f"svg:{wid}:req", priority=10, now=ctx.now())
    assert worker.drain(ctx, ("generate_svg",)) == 1
    result = json.loads(job(conn, requested)["result_json"])
    assert "image_id" in result and word_state(conn, wid) == ("ready", result["image_id"])
    drawn = [r for r in images(conn, wid) if r["id"] == result["image_id"]][0]
    assert drawn["prompt_version"] == "svg-v2" and not memo.is_memo(drawn) and image_meta(conn, wid)["word_layer"] is False
    assert conn.execute("SELECT status FROM word_images WHERE id = ?", (card_id,)).fetchone()[0] == "superseded"
    # the admin's `provider: "claude_svg"` refetch reaches generate_svg through fetch_image although the word wore a card
    noon = insert_word(conn, "noon")
    give_card(conn, cfg, noon, small_card("noon"), now=ctx.now())
    sid = service.admin_refetch(conn, noon, provider="claude_svg", now=ctx.now())
    worker.drain(ctx, ("fetch_image",))
    assert json.loads(job(conn, sid)["result_json"])["status"] == "svg_queued" and json.loads(svg_jobs(conn, noon)[0]["payload_json"]) == {"word_id": noon, "requested": True}


# ------------------------------------------------------------ 不合适 on a card (API.md 28 / 71; release note §6 item 3)
def test_a_learners_report_on_a_memory_card_is_only_recorded_and_the_admin_decides(client: TestClient, ctx, conn, cfg, moon_svg, mock_http, pinned_dns):
    """POST /api/words/{id}/report {target: "image"} on a word whose active image is a 记忆图卡 records the report and leaves the
    card alone — nothing rejected, active_image_id / image_state as they were, no fetch_image — so one learner's tap cannot trade a
    reviewed card for a stock picture. The admin's resolution with refetch_image (endpoint 71) is the decision that takes it down:
    the card is rejected first, and the fetch queued then is not held back by the guard. Every other picture: as before."""
    moon = insert_word(conn, "moon")
    drawing_id = activate_svg(conn, cfg, moon, OLD_DRAWING, "夜空里的月亮", now="2026-10-01T00:00:00Z", model="claude-sonnet-4-5", prompt_version="svg-v2")
    card_id = give_card(conn, cfg, moon, moon_svg, now=ctx.now())
    card_sha = images(conn, moon)[1]["sha256"]
    before = image_meta(conn, moon)
    learner, root = make_user(conn, "alice"), make_user(conn, "root", role="admin")
    client.cookies.set("wd_session", learner)

    # the learner: 不合适 under the picture, then the 反馈问题 sheet with a picture reason — the endpoint's contract is unchanged
    r = client.post(f"/api/words/{moon}/report", json={"target": "image", "reason": "irrelevant_image", "note": "看不懂这张图"})
    assert r.status_code == 201 and set(r.json()) == {"id"}, r.text
    first = r.json()["id"]
    r = client.post(f"/api/words/{moon}/report", json={"target": "image", "reason": "inappropriate_image"})
    assert r.status_code == 201
    rows = [db.row_to_dict(x) for x in conn.execute("SELECT * FROM content_reports WHERE word_id = ? ORDER BY id", (moon,))]
    assert [(x["id"], x["target"], x["reason"], x["note"], x["status"], x["image_id"]) for x in rows] == [
        (first, "image", "irrelevant_image", "看不懂这张图", "open", card_id),  # the report names the card it is about
        (r.json()["id"], "image", "inappropriate_image", None, "open", card_id),
    ]
    assert word_state(conn, moon) == ("ready", card_id) and [(x["id"], x["status"]) for x in images(conn, moon)] == [(drawing_id, "superseded"), (card_id, "active")]
    assert conn.execute("SELECT COUNT(*) FROM jobs").fetchone()[0] == 0 and conn.execute("SELECT COUNT(*) FROM system_events WHERE kind = 'image_rejected'").fetchone()[0] == 0
    assert client.get(f"/api/words/{moon}/image").json() == before and client.get(f"/api/words/{moon}").json()["word"]["image_state"] == "ready"
    assert mock_http.calls == [] and service.wears_memory_card(conn, moon) is True and before["word_layer"] is True  # one predicate: the server's rule is what the client is told

    # every other picture behaves as before: an online drawing is rejected at once and a fetch excluding it is queued …
    noon = insert_word(conn, "noon")
    noon_drawing = activate_svg(conn, cfg, noon, OLD_DRAWING, None, now=ctx.now(), model="claude-sonnet-4-5", prompt_version="svg-v2")
    assert client.post(f"/api/words/{noon}/report", json={"target": "image", "reason": "irrelevant_image"}).status_code == 201
    assert conn.execute("SELECT status FROM word_images WHERE id = ?", (noon_drawing,)).fetchone()[0] == "rejected" and word_state(conn, noon) == ("queued", None)
    noon_job = db.row_to_dict(conn.execute("SELECT * FROM jobs WHERE dedupe_key = ?", (f"image:{noon}",)).fetchone())
    assert (noon_job["type"], noon_job["priority"]) == ("fetch_image", 10) and json.loads(noon_job["payload_json"]) == {"word_id": noon, "exclude": [images(conn, noon)[0]["sha256"]]}
    assert conn.execute("SELECT COUNT(*) FROM system_events WHERE kind = 'image_rejected'").fetchone()[0] == 1
    # … and a report on the template card, or about the content of a word that wears a card, records and touches no picture
    pear = insert_word(conn, "pear")
    assert client.post(f"/api/words/{pear}/report", json={"target": "image", "reason": "irrelevant_image"}).status_code == 201
    assert client.post(f"/api/words/{moon}/report", json={"target": "content", "reason": "wrong_meaning"}).status_code == 201
    assert word_state(conn, pear) == ("none", None) and word_state(conn, moon) == ("ready", card_id) and conn.execute("SELECT COUNT(*) FROM jobs").fetchone()[0] == 1
    assert (service.wears_memory_card(conn, noon), service.wears_memory_card(conn, pear), service.wears_memory_card(conn, 999_999)) == (False, False, False)
    conn.execute("DELETE FROM jobs WHERE id = ?", (noon_job["id"],))  # noon's fetch is not this test's business

    # the admin: the report waits as `open`; dismissing it changes nothing; resolving it with refetch_image takes the card down
    client.cookies.set("wd_session", root)
    listed = client.get("/api/admin/reports").json()["items"]
    assert first in [x["id"] for x in listed] and all(x["status"] == "open" for x in listed)
    dismissed = client.post(f"/api/admin/reports/{rows[1]['id']}", json={"status": "dismissed", "refetch_image": True}).json()
    assert dismissed["resolution"] == "dismissed" and word_state(conn, moon) == ("ready", card_id)
    resolved = client.post(f"/api/admin/reports/{first}", json={"status": "resolved", "refetch_image": True})
    assert resolved.status_code == 200 and resolved.json()["resolution"] == "image_replaced" and resolved.json()["word"]["image_state"] == "queued", resolved.text
    assert conn.execute("SELECT status FROM word_images WHERE id = ?", (card_id,)).fetchone()[0] == "rejected" and word_state(conn, moon) == ("queued", None)
    event = json.loads(conn.execute("SELECT detail_json FROM system_events WHERE kind = 'image_rejected' ORDER BY id DESC LIMIT 1").fetchone()[0])
    assert event == {"word_id": moon, "image_id": card_id, "provider": "claude_svg", "reason": "report:irrelevant_image"}
    fetch = db.row_to_dict(conn.execute("SELECT * FROM jobs WHERE dedupe_key = ?", (f"image:{moon}",)).fetchone())
    assert json.loads(fetch["payload_json"]) == {"word_id": moon, "exclude": [card_sha]}  # an ordinary report fetch: the card is no longer active, nothing to guard
    assert worker.drain(ctx, ("fetch_image",)) == 1
    result = json.loads(job(conn, fetch["id"])["result_json"])
    assert result["status"] == "ready" and "skipped" not in result and mock_http.calls_to("commons.wikimedia.org")  # the chain ran
    meta = image_meta(conn, moon)
    assert (meta["kind"], meta["word_layer"], meta["hook_zh"]) == ("photo", False, None)
    assert [x["status"] for x in images(conn, moon)] == ["superseded", "rejected", "active"]
