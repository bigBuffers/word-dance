"""The fetch_image chain end to end (mock_http providers, DNS pinned to a public IP, synchronous queue drain):
provider order, Openverse quota/priority rules, SVG fallback rules, exclude/refresh/report flows, sha reuse,
the admin refetch payload, the CLI commands and activate_svg."""

from __future__ import annotations

import io
import json
import os
import stat
import sys
import zlib
from dataclasses import replace

import httpx
import pytest
from PIL import Image


def _drop_editable_finder() -> None:
    """The shared venv's editable install maps ``wd`` to the main checkout; its finder would import immediate
    children missing from this worktree (``wd.seed``, ``wd.backup`` …) from there. Keep this run self-contained."""
    sys.meta_path[:] = [f for f in sys.meta_path if "editable" not in (getattr(f, "__module__", "") + getattr(f, "__name__", type(f).__name__)).lower()]


_drop_editable_finder()

from wd import cli, db  # noqa: E402
from wd.images import activate_svg, handler as image_handler, image_meta, photo_mix, quota, reject_active_image, request_refresh, service, store
from wd.images.sanitize_svg import SvgRejected
from wd.jobs import queue, registry
from wd.jobs.registry import JobContext
from wd.schemas import ImageMeta

PUBLIC_IP = "93.184.216.34"
RED_REF, TREE_REF = "7823406", "81528752"
EMPTY_WIKIMEDIA = {"batchcomplete": ""}
EMPTY_OPENVERSE = {"result_count": 0, "page_count": 0, "page_size": 20, "page": 1, "results": []}


@pytest.fixture
def pinned_dns(monkeypatch):
    monkeypatch.setattr("wd.images.fetch.resolve_host", lambda host: [PUBLIC_IP])


@pytest.fixture
def cfg(settings):
    return replace(settings, wikimedia_min_interval_ms=0)


@pytest.fixture
def ctx(cfg, conn, connect, frozen_clock):
    registry.load_handlers()
    registry.register("fetch_image")(image_handler.handle_fetch_image)  # other tests may reset the registry
    return JobContext(db=connect, cfg=cfg, clock=frozen_clock, enqueue=queue.enqueue, worker_id="io-1", boot_id="test")


def insert_word(conn, lemma: str, **cols) -> int:
    row = {"lemma": lemma, "display": lemma, "kind": "word", "source": "seed", "is_public": 1, "is_valid_english": 1, "translation": "n. 苹果", "phonetic": "'æpl"}
    row.update(cols)
    keys = ",".join(row)
    return conn.execute(f"INSERT INTO words({keys}) VALUES ({','.join('?' * len(row))}) RETURNING id", list(row.values())).fetchone()[0]


def set_content(conn, word_id: int, keywords: list[str], alt: str = "一个红苹果") -> int:
    content = {"word": "apple", "valid": True, "meaning_zh": "n. 苹果", "meaning_en": "a fruit", "examples": [], "collocations": [], "mnemonic_zh": "", "image_keywords": keywords, "image_alt_zh": alt, "difficulty": 1}
    cid = conn.execute(
        "INSERT INTO word_contents(word_id, version, prompt_version, model, content_json) VALUES (?,1,'content-v1','m',?) RETURNING id",
        (word_id, json.dumps(content, ensure_ascii=False)),
    ).fetchone()[0]
    conn.execute("UPDATE words SET active_content_id=?, content_state='ready' WHERE id=?", (cid, word_id))
    return cid


def enqueue(conn, word_id: int, priority: int = 20, now: str = "2026-10-14T00:00:00Z", **payload) -> int:
    return queue.enqueue(conn, "fetch_image", {"word_id": word_id, **payload}, dedupe_key=f"image:{word_id}", priority=priority, now=now)


def job(conn, job_id: int) -> dict:
    return db.row_to_dict(conn.execute("SELECT * FROM jobs WHERE id=?", (job_id,)).fetchone())


def active_image(conn, word_id: int) -> dict | None:
    return db.row_to_dict(conn.execute("SELECT wi.* FROM words w JOIN word_images wi ON wi.id = w.active_image_id WHERE w.id=?", (word_id,)).fetchone())


def add_to_bank(conn, word_id: int, username: str = "alice") -> int:
    uid = conn.execute("INSERT INTO users(username, password_hash) VALUES (?, 'x') RETURNING id", (username,)).fetchone()[0]
    conn.execute("INSERT INTO user_settings(user_id) VALUES (?)", (uid,))
    conn.execute("INSERT INTO user_words(user_id, word_id, state, origin) VALUES (?,?,'new','browse')", (uid, word_id))
    return uid


def svg_jobs(conn, word_id: int) -> list[dict]:
    return [db.row_to_dict(r) for r in conn.execute("SELECT * FROM jobs WHERE type='generate_svg' AND json_extract(payload_json,'$.word_id')=?", (word_id,))]


def distinct_photos(mock_http) -> None:
    """Serve a different JPEG per URL path (the default mock returns one fixed JPEG, so every photo would share a sha)."""

    def handler(request: httpx.Request) -> httpx.Response:
        seed = zlib.crc32(request.url.path.encode())
        img = Image.new("RGB", (640, 400), (seed % 256, (seed // 256) % 256, (seed // 65536) % 256))
        buf = io.BytesIO()
        img.save(buf, format="JPEG", quality=80)
        return httpx.Response(200, content=buf.getvalue(), headers={"Content-Type": "image/jpeg"})

    for host in ("thumb.wikimedia.org", "upload.wikimedia.org", "live.staticflickr.com"):
        mock_http.overrides[host] = handler


# ------------------------------------------------------------------------------------------------ chain
def test_wikimedia_first_download_via_thumb_host(ctx, conn, cfg, mock_http, pinned_dns):
    wid = insert_word(conn, "apple")
    set_content(conn, wid, ["red apple", "apple tree"])
    jid = enqueue(conn, wid)
    assert queue.run_once(ctx) == 1
    j = job(conn, jid)
    assert j["status"] == "done", j["last_error"]
    result = json.loads(j["result_json"])
    assert result["status"] == "ready" and result["provider"] == "wikimedia" and result["query"] == "red apple"
    img = active_image(conn, wid)
    assert img is not None and img["provider"] == "wikimedia" and img["status"] == "active"
    assert img["source_url"].startswith("https://thumb.wikimedia.org/wikipedia/commons/thumb/") and "utm_" not in img["source_url"]
    assert img["provider_ref"] in (RED_REF, TREE_REF) and img["license"] in ("CC0", "CC BY 2.0") and img["mime"] == "image/jpeg"
    assert img["alt_zh"] == "一个红苹果" and img["query"] == "red apple" and img["width"] <= 800 and img["height"] <= 800
    assert img["attribution_text"].endswith(img["license"]) and img["landing_url"].startswith("https://commons.wikimedia.org/wiki/File:")
    path = cfg.images_dir / img["file_path"]
    assert path.is_file() and stat.S_IMODE(os.stat(path).st_mode) == 0o600 and img["file_bytes"] == path.stat().st_size
    word = conn.execute("SELECT image_state, active_image_id FROM words WHERE id=?", (wid,)).fetchone()
    assert word["image_state"] == "ready" and word["active_image_id"] == img["id"]
    # requests: one Commons search, downloads only from thumb.wikimedia.org (DNS-pinned IP + Host + SNI), no Openverse
    assert len(mock_http.calls_to("commons.wikimedia.org")) == 1 and mock_http.calls_to("api.openverse.org") == []
    search = mock_http.calls_to("commons.wikimedia.org")[0]
    assert search.url.params["gsrsearch"] == "red apple filetype:bitmap" and "formatversion" not in search.url.params
    assert search.headers["user-agent"].startswith("word-Dance/")
    downloads = mock_http.calls_to("thumb.wikimedia.org")
    assert downloads and all(r.url.host == PUBLIC_IP and r.headers["host"] == "thumb.wikimedia.org" and r.extensions["sni_hostname"] == "thumb.wikimedia.org" for r in downloads)
    assert all("utm_" not in str(r.url) for r in downloads)
    meta = image_meta(conn, wid)
    ImageMeta.model_validate(meta)
    assert meta["kind"] == "photo" and meta["url"] == f"/media/images/{img['file_path']}" and meta["id"] == img["id"]
    assert meta["attribution"]["license"] == img["license"] and meta["attribution"]["text"] == img["attribution_text"]
    assert quota.counts(conn, "wikimedia", ctx.now()) == (1, 1) and quota.state(conn, "wikimedia")["last_ok_at"] == ctx.now()


def test_openverse_second_when_commons_is_empty_and_never_downloads_api_thumbnails(ctx, conn, mock_http, pinned_dns):
    mock_http.overrides["commons.wikimedia.org"] = lambda req: httpx.Response(200, json=EMPTY_WIKIMEDIA)
    wid = insert_word(conn, "apple")
    jid = enqueue(conn, wid)
    queue.run_once(ctx)
    assert json.loads(job(conn, jid)["result_json"])["provider"] == "openverse"
    img = active_image(conn, wid)
    assert img["provider"] == "openverse" and img["source_url"].startswith("https://live.staticflickr.com/") and img["query"] == "apple"
    assert img["attribution_text"].startswith('"Apples" by ') and "CC BY 2.0" in img["attribution_text"] and img["license"] == "CC BY 2.0"
    ov = mock_http.calls_to("api.openverse.org")
    assert len(ov) == 1 and ov[0].url.path == "/v1/images/"
    assert dict(ov[0].url.params) == {"q": "apple", "page_size": "20", "license_type": "commercial", "mature": "false"}
    assert not any("/thumb" in r.url.path for r in ov)
    assert mock_http.calls_to("live.staticflickr.com") and all(r.headers["host"] == "live.staticflickr.com" for r in mock_http.calls_to("live.staticflickr.com"))
    assert quota.counts(conn, "openverse", ctx.now()) == (1, 1) and quota.counts(conn, "wikimedia", ctx.now()) == (1, 1)


def test_openverse_skipped_when_counters_exhausted_or_in_cooldown(ctx, conn, cfg, mock_http, pinned_dns, frozen_clock):
    mock_http.overrides["commons.wikimedia.org"] = lambda req: httpx.Response(200, json=EMPTY_WIKIMEDIA)
    wid = insert_word(conn, "apple")
    for _ in range(cfg.openverse_minute_limit):
        quota.record(conn, "openverse", ctx.now())
    jid = enqueue(conn, wid)
    queue.run_once(ctx)
    assert mock_http.calls_to("api.openverse.org") == []
    assert json.loads(job(conn, jid)["result_json"])["status"] == "failed"
    assert conn.execute("SELECT image_state FROM words WHERE id=?", (wid,)).fetchone()[0] == "failed"
    # a later minute frees the counter, but a cooldown still blocks it
    frozen_clock.advance(minutes=2)
    quota.cooldown(conn, "openverse", ctx.now(), 600)
    wid2 = insert_word(conn, "pear")
    enqueue(conn, wid2, now=ctx.now())
    queue.run_once(ctx)
    assert mock_http.calls_to("api.openverse.org") == []
    # and once the cooldown is over it runs again
    frozen_clock.advance(minutes=11)
    wid3 = insert_word(conn, "plum")
    enqueue(conn, wid3, now=ctx.now())
    queue.run_once(ctx)
    assert len(mock_http.calls_to("api.openverse.org")) == 1 and active_image(conn, wid3)["provider"] == "openverse"


def test_priority_90_never_touches_openverse_and_gets_no_svg(ctx, conn, mock_http, pinned_dns):
    mock_http.overrides["commons.wikimedia.org"] = lambda req: httpx.Response(200, json=EMPTY_WIKIMEDIA)
    wid = insert_word(conn, "apple")
    add_to_bank(conn, wid)
    jid = enqueue(conn, wid, priority=90)
    queue.run_once(ctx)
    assert mock_http.calls_to("api.openverse.org") == [] and len(mock_http.calls_to("commons.wikimedia.org")) == 1
    assert json.loads(job(conn, jid)["result_json"])["status"] == "failed"
    assert svg_jobs(conn, wid) == []
    assert conn.execute("SELECT image_state FROM words WHERE id=?", (wid,)).fetchone()[0] == "failed"


def test_all_providers_fail_svg_rules(ctx, conn, cfg, mock_http, pinned_dns, connect, frozen_clock):
    mock_http.overrides["commons.wikimedia.org"] = lambda req: httpx.Response(200, json=EMPTY_WIKIMEDIA)
    mock_http.overrides["api.openverse.org"] = lambda req: httpx.Response(200, json=EMPTY_OPENVERSE)
    bank_word = insert_word(conn, "apple")
    uid = add_to_bank(conn, bank_word)
    lonely = insert_word(conn, "pear")
    batch_word = insert_word(conn, "plum")
    bid = conn.execute("INSERT INTO push_batches(user_id, local_date, timezone, trigger) VALUES (?, '2026-10-14', 'Asia/Shanghai', 'manual') RETURNING id", (uid,)).fetchone()[0]
    conn.execute("INSERT INTO push_items(batch_id, word_id, kind, position) VALUES (?, ?, 'screen', 0)", (bid, batch_word))
    jobs = {w: enqueue(conn, w) for w in (bank_word, lonely, batch_word)}
    queue.run_once(ctx)
    for w in (bank_word, lonely, batch_word):
        assert json.loads(job(conn, jobs[w])["result_json"])["status"] == "failed"
        assert conn.execute("SELECT image_state FROM words WHERE id=?", (w,)).fetchone()[0] == "failed"
        meta = image_meta(conn, w)
        ImageMeta.model_validate(meta)
        assert meta == {"id": None, "url": f"/media/card/{w}.svg", "kind": "card", "provider": "card_svg", "mime": "image/svg+xml", "width": 800, "height": 500, "alt_zh": None, "attribution": None}
    bank_svg = svg_jobs(conn, bank_word)
    assert len(bank_svg) == 1 and bank_svg[0]["priority"] == 20 and bank_svg[0]["dedupe_key"] == f"svg:{bank_word}" and bank_svg[0]["status"] == "queued"
    assert json.loads(job(conn, jobs[bank_word])["result_json"])["svg_job_id"] == bank_svg[0]["id"]
    assert svg_jobs(conn, lonely) == []  # in no bank and no batch
    assert len(svg_jobs(conn, batch_word)) == 1  # in an open batch counts as studied
    # a second failure for the same word folds into the live svg job (dedupe)
    enqueue(conn, bank_word, priority=10, now=ctx.now())
    queue.run_once(ctx)
    assert len(svg_jobs(conn, bank_word)) == 1 and svg_jobs(conn, bank_word)[0]["priority"] == 10
    # WD_SVG_VIA_CLAUDE=0 → no svg job
    off = JobContext(db=connect, cfg=replace(cfg, svg_via_claude=False), clock=frozen_clock, enqueue=queue.enqueue, worker_id="io-1", boot_id="test")
    w4 = insert_word(conn, "fig")
    add_to_bank(conn, w4, "bob")
    enqueue(conn, w4)
    queue.run_once(off)
    assert svg_jobs(conn, w4) == []
    # AI kill switch / SVG sub-cap 0 → no svg job either
    for variant in (replace(cfg, ai_enabled=False), replace(cfg, ai_svg_daily_budget_usd=0)):
        w = insert_word(conn, f"kiwi{variant.ai_enabled}{variant.ai_svg_daily_budget_usd}")
        conn.execute("INSERT INTO user_words(user_id, word_id, state, origin) VALUES (?,?,'learning','browse')", (uid, w))
        enqueue(conn, w)
        queue.run_once(JobContext(db=connect, cfg=variant, clock=frozen_clock, enqueue=queue.enqueue, worker_id="io-1", boot_id="test"))
        assert svg_jobs(conn, w) == []


def test_provider_429_sets_a_cooldown_from_retry_after(ctx, conn, cfg, mock_http, pinned_dns):
    mock_http.overrides["commons.wikimedia.org"] = lambda req: httpx.Response(429, text="slow down", headers={"Retry-After": "120"})
    wid = insert_word(conn, "apple")
    jid = enqueue(conn, wid)
    queue.run_once(ctx)
    st = quota.state(conn, "wikimedia")
    assert st["cooldown_until"] == "2026-10-14T00:02:00Z" and st["consecutive_errors"] == 1 and "429" in st["last_error"]
    assert quota.check(conn, "wikimedia", cfg, ctx.now()) == "cooldown"
    assert quota.counts(conn, "wikimedia", ctx.now()) == (1, 1)  # the failed request still counts
    assert json.loads(job(conn, jid)["result_json"])["provider"] == "openverse"  # the chain continued
    # a 503 uses the provider default (15 min) and a plain 400 only records the error
    mock_http.overrides["commons.wikimedia.org"] = lambda req: httpx.Response(503, text="maintenance")
    quota.mark_ok(conn, "wikimedia", ctx.now())
    conn.execute("UPDATE provider_state SET cooldown_until=NULL WHERE provider='wikimedia'")
    enqueue(conn, insert_word(conn, "pear"))
    queue.run_once(ctx)
    assert quota.state(conn, "wikimedia")["cooldown_until"] == "2026-10-14T00:15:00Z"
    mock_http.overrides["commons.wikimedia.org"] = lambda req: httpx.Response(400, json={"error": "bad"})
    quota.mark_ok(conn, "wikimedia", ctx.now())
    conn.execute("UPDATE provider_state SET cooldown_until=NULL WHERE provider='wikimedia'")
    enqueue(conn, insert_word(conn, "plum"))
    queue.run_once(ctx)
    st = quota.state(conn, "wikimedia")
    assert st["cooldown_until"] is None and st["consecutive_errors"] == 1 and "400" in st["last_error"]


# ------------------------------------------------------------------------------------ exclude / refresh
def test_report_rejects_active_image_and_refetch_excludes_it(ctx, conn, mock_http, pinned_dns):
    distinct_photos(mock_http)
    wid = insert_word(conn, "apple")
    enqueue(conn, wid)
    queue.run_once(ctx)
    first = active_image(conn, wid)
    assert first["provider_ref"] == TREE_REF  # CC0 + featured ranks above CC BY
    jid = reject_active_image(conn, wid, reason="irrelevant_image", now=ctx.now())
    assert jid is not None
    j = job(conn, jid)
    payload = json.loads(j["payload_json"])
    assert j["type"] == "fetch_image" and j["priority"] == 10 and j["dedupe_key"] == f"image:{wid}" and j["status"] == "queued"
    assert payload["word_id"] == wid and set(payload["exclude"]) == {TREE_REF, first["sha256"]}
    word = conn.execute("SELECT image_state, active_image_id FROM words WHERE id=?", (wid,)).fetchone()
    assert word["image_state"] == "queued" and word["active_image_id"] is None
    assert conn.execute("SELECT status FROM word_images WHERE id=?", (first["id"],)).fetchone()[0] == "rejected"
    assert image_meta(conn, wid)["kind"] == "card"
    event = conn.execute("SELECT detail_json FROM system_events WHERE kind='image_rejected'").fetchone()
    assert json.loads(event[0]) == {"word_id": wid, "image_id": first["id"], "provider": "wikimedia", "reason": "irrelevant_image"}
    queue.run_once(ctx)
    second = active_image(conn, wid)
    assert second["provider_ref"] == RED_REF and second["id"] != first["id"]
    assert second["source_url"] == "https://thumb.wikimedia.org/wikipedia/commons/thumb/1/15/Red_Apple.jpg/960px-Red_Apple.jpg"
    assert conn.execute("SELECT status FROM word_images WHERE id=?", (first["id"],)).fetchone()[0] == "rejected"
    assert json.loads(job(conn, jid)["result_json"])["ref"] == RED_REF
    # 换一张 excludes the rejected AND the current image: both Commons candidates are out, so the chain falls through to Openverse
    rid = request_refresh(conn, wid, now=ctx.now())
    payload = json.loads(job(conn, rid)["payload_json"])
    assert set(payload["exclude"]) == {TREE_REF, first["sha256"], RED_REF, second["sha256"]}
    assert conn.execute("SELECT image_state FROM words WHERE id=?", (wid,)).fetchone()[0] == "queued"
    assert active_image(conn, wid)["id"] == second["id"]  # the current image stays visible while the refresh runs
    queue.run_once(ctx)
    third = active_image(conn, wid)
    assert json.loads(job(conn, rid)["result_json"])["status"] == "ready" and third["provider"] == "openverse" and third["id"] != second["id"]
    assert conn.execute("SELECT status FROM word_images WHERE id=?", (second["id"],)).fetchone()[0] == "superseded"
    # a superseded photo may come back on a later 换一张 (only the current and the rejected ones are excluded)
    rid_again = request_refresh(conn, wid, now=ctx.now())
    assert set(json.loads(job(conn, rid_again)["payload_json"])["exclude"]) == {TREE_REF, first["sha256"], third["provider_ref"], third["sha256"]}
    queue.run_once(ctx)
    assert active_image(conn, wid)["provider_ref"] == RED_REF
    third = active_image(conn, wid)
    # with nothing acceptable left anywhere the current image is kept and image_state returns to ready
    mock_http.overrides["api.openverse.org"] = lambda req: httpx.Response(200, json=EMPTY_OPENVERSE)
    mock_http.overrides["commons.wikimedia.org"] = lambda req: httpx.Response(200, json=EMPTY_WIKIMEDIA)
    rid2 = request_refresh(conn, wid, now=ctx.now())
    assert third["provider_ref"] in json.loads(job(conn, rid2)["payload_json"])["exclude"]
    queue.run_once(ctx)
    assert json.loads(job(conn, rid2)["result_json"])["status"] == "failed"
    assert active_image(conn, wid)["id"] == third["id"]
    assert conn.execute("SELECT image_state FROM words WHERE id=?", (wid,)).fetchone()[0] == "ready"
    assert svg_jobs(conn, wid) == []  # not studied → no svg job
    assert reject_active_image(conn, 999_999, reason="x") is None and request_refresh(conn, 999_999) is None


def test_rejected_images_are_excluded_even_when_the_payload_lacks_them(ctx, conn, mock_http, pinned_dns):
    distinct_photos(mock_http)
    wid = insert_word(conn, "apple")
    enqueue(conn, wid)
    queue.run_once(ctx)
    first = active_image(conn, wid)
    conn.execute("UPDATE word_images SET status='rejected' WHERE id=?", (first["id"],))
    conn.execute("UPDATE words SET active_image_id=NULL WHERE id=?", (wid,))
    enqueue(conn, wid, now=ctx.now())  # plain payload, no exclude
    queue.run_once(ctx)
    assert active_image(conn, wid)["provider_ref"] != first["provider_ref"]


def test_same_sha_is_reused_across_words(ctx, conn, cfg, mock_http, pinned_dns):
    a, b = insert_word(conn, "apple"), insert_word(conn, "pear")
    enqueue(conn, a)
    enqueue(conn, b)
    queue.run_once(ctx)
    ia, ib = active_image(conn, a), active_image(conn, b)
    assert ia["sha256"] == ib["sha256"] and ia["file_path"] == ib["file_path"]
    assert store.list_files(cfg) == [ia["file_path"]]
    # the second word avoids the ref the first one used when another candidate is available (−2 for "already used")
    assert ia["provider_ref"] != ib["provider_ref"]


def test_admin_refetch_payload_provider_and_query(ctx, conn, mock_http, pinned_dns):
    wid = insert_word(conn, "apple")
    jid = service.admin_refetch(conn, wid, provider="openverse", query="green apple", now=ctx.now())
    payload = json.loads(job(conn, jid)["payload_json"])
    assert payload == {"word_id": wid, "provider": "openverse", "query": "green apple"}
    queue.run_once(ctx)
    assert mock_http.calls_to("commons.wikimedia.org") == []
    assert mock_http.calls_to("api.openverse.org")[0].url.params["q"] == "green apple"
    assert active_image(conn, wid)["provider"] == "openverse" and active_image(conn, wid)["query"] == "green apple"
    sid = service.admin_refetch(conn, wid, provider="claude_svg", now=ctx.now())
    queue.run_once(ctx)
    result = json.loads(job(conn, sid)["result_json"])
    assert result["status"] == "svg_queued" and svg_jobs(conn, wid)[0]["id"] == result["svg_job_id"] and svg_jobs(conn, wid)[0]["priority"] == 10


def test_keywords_come_from_content_with_blocklist_and_shape_filter(ctx, conn, mock_http, pinned_dns):
    wid = insert_word(conn, "chart")
    set_content(conn, wid, ["bar chart", "http://evil", "", "x" * 60, "Stock market"])  # blocklist, bad shape, too long
    enqueue(conn, wid)
    queue.run_once(ctx)
    assert mock_http.calls_to("commons.wikimedia.org")[0].url.params["gsrsearch"] == "stock market filetype:bitmap"
    wid2 = insert_word(conn, "pear")
    set_content(conn, wid2, ["bar chart"])  # nothing survives → the lemma
    enqueue(conn, wid2)
    queue.run_once(ctx)
    assert mock_http.calls_to("commons.wikimedia.org")[-1].url.params["gsrsearch"] == "pear filetype:bitmap"


def test_handler_edge_cases(ctx, conn, connect, cfg, frozen_clock, mock_http, pinned_dns):
    bad = queue.enqueue(conn, "fetch_image", {"nope": 1}, dedupe_key=None, now=ctx.now())
    missing = queue.enqueue(conn, "fetch_image", {"word_id": 999_999}, dedupe_key="image:999999", now=ctx.now())
    queue.run_once(ctx)
    assert job(conn, bad)["status"] == "queued" and "word_id" in job(conn, bad)["last_error"]  # failed → backoff
    assert job(conn, missing)["status"] == "done" and json.loads(job(conn, missing)["result_json"]) == {"status": "skipped", "detail": "word not found"}
    wid = insert_word(conn, "apple")
    jid = enqueue(conn, wid, now=ctx.now())
    off = JobContext(db=connect, cfg=replace(cfg, images_enabled=False), clock=frozen_clock, enqueue=queue.enqueue, worker_id="io-1", boot_id="test")
    queue.run_once(off)
    assert json.loads(job(conn, jid)["result_json"]) == {"status": "skipped", "detail": "images disabled"}
    assert mock_http.calls == []


def test_handler_crash_is_recorded_as_a_failed_attempt(ctx, conn, monkeypatch, mock_http, pinned_dns):
    wid = insert_word(conn, "apple")
    jid = enqueue(conn, wid)

    def boom(*a, **k):
        raise RuntimeError("provider exploded")

    monkeypatch.setattr(image_handler, "fetch_for_word", boom)
    queue.run_once(ctx)
    j = job(conn, jid)
    assert j["status"] == "queued" and "provider exploded" in j["last_error"] and j["attempts"] == 1


# ------------------------------------------------------------------------------------------ svg + mix
def test_activate_svg_sanitises_and_serves_a_svg_image(conn, cfg):
    wid = insert_word(conn, "abandon")
    svg = '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 800 500" onload="x()"><script>evil()</script><rect width="800" height="500" fill="#eee"/><text x="40" y="460" font-size="40">abandon</text></svg>'
    image_id = activate_svg(conn, cfg, wid, svg, "被遗弃在雪地里的汽车", now="2026-10-14T00:00:00Z")
    row = db.row_to_dict(conn.execute("SELECT * FROM word_images WHERE id=?", (image_id,)).fetchone())
    assert row["provider"] == "claude_svg" and row["mime"] == "image/svg+xml" and row["license"] == "generated" and row["status"] == "active"
    assert row["file_path"].endswith(".svg") and row["width"] == 800 and row["height"] == 500 and row["alt_zh"] == "被遗弃在雪地里的汽车"
    stored = (cfg.images_dir / row["file_path"]).read_text(encoding="utf-8")
    assert "<script" not in stored and "onload" not in stored and "<text" in stored and stored.startswith('<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 800 500">')
    assert tuple(conn.execute("SELECT image_state, active_image_id FROM words WHERE id=?", (wid,)).fetchone()) == ("ready", image_id)
    meta = image_meta(conn, wid)
    ImageMeta.model_validate(meta)
    assert meta["kind"] == "svg" and meta["provider"] == "claude_svg" and meta["attribution"] is None and meta["url"] == f"/media/images/{row['file_path']}"
    with pytest.raises(SvgRejected):
        activate_svg(conn, cfg, wid, "<html>no</html>", None)
    assert conn.execute("SELECT COUNT(*) FROM word_images WHERE word_id=?", (wid,)).fetchone()[0] == 1  # nothing stored on rejection


def test_photo_mix_counts(conn, cfg, ctx, mock_http, pinned_dns):
    photo = insert_word(conn, "apple")
    enqueue(conn, photo)
    queue.run_once(ctx)
    svg = insert_word(conn, "abandon")
    activate_svg(conn, cfg, svg, '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 800 500"><rect width="1" height="1"/></svg>', None)
    card_only = insert_word(conn, "pear")
    set_content(conn, card_only, ["pear"])
    insert_word(conn, "plum")  # no content, no image → not counted anywhere
    assert photo_mix(conn) == {"with_photo": 1, "with_claude_svg": 1, "card_only": 1}


# ------------------------------------------------------------------------------------------------- CLI
def test_cli_fetch_image_prints_attribution(conn, monkeypatch, mock_http, pinned_dns, capsys):
    monkeypatch.setenv("WD_WIKIMEDIA_MIN_INTERVAL_MS", "0")
    wid = insert_word(conn, "apple", display="Apple")
    assert cli.main(["fetch-image", "apple"]) == 0
    out = capsys.readouterr().out
    assert f"word: Apple (id {wid})" in out and "status: ready" in out and "provider: wikimedia" in out
    assert "attribution: " in out and "source: https://commons.wikimedia.org/wiki/File:" in out and "file: " in out and "/media/images/" in out
    img = active_image(conn, wid)
    assert img is not None and out.count(img["license"]) >= 1
    assert cli.main(["fetch-image", "nosuchword"]) == 1
    assert "not found" in capsys.readouterr().err
    assert cli.main(["fetch-image", str(wid), "--provider", "claude_svg"]) == 0
    assert "svg_queued" in capsys.readouterr().out and len(svg_jobs(conn, wid)) == 1
    mock_http.overrides["commons.wikimedia.org"] = lambda req: httpx.Response(200, json=EMPTY_WIKIMEDIA)
    mock_http.overrides["api.openverse.org"] = lambda req: httpx.Response(200, json=EMPTY_OPENVERSE)
    wid2 = insert_word(conn, "pear")
    assert cli.main(["fetch-image", "pear", "--no-svg"]) == 1
    assert "status: failed" in capsys.readouterr().out and svg_jobs(conn, wid2) == []


def test_cli_images_prune_removes_only_unused_words_and_orphan_files(conn, cfg, monkeypatch, capsys):
    data_a, data_b = b"\xff\xd8\xff" + b"a" * 100, b"\xff\xd8\xff" + b"b" * 100
    fa, fb = store.write_bytes(cfg, data_a, "jpg"), store.write_bytes(cfg, data_b, "jpg")
    used, unused, shared = insert_word(conn, "apple"), insert_word(conn, "pear"), insert_word(conn, "plum")
    add_to_bank(conn, used)
    old = "2026-01-01T00:00:00Z"
    for wid, f in ((used, fa), (unused, fb), (shared, fa)):
        store.activate(conn, wid, provider="wikimedia", ref=str(wid), file_path=f.file_path, file_bytes=f.file_bytes, sha256=f.sha256, mime="image/jpeg", now=old)
    orphan_rel = store.write_bytes(cfg, b"\xff\xd8\xff" + b"o" * 50, "jpg").file_path  # a file no row references
    result = image_handler.prune_unused(conn, cfg, 30, now="2026-10-14T00:00:00Z", dry_run=True)
    assert result["dry_run"] and result["words"] == 2 and result["rows"] == 2 and set(result["removed"]) == {fb.file_path, orphan_rel}
    assert (cfg.images_dir / fb.file_path).is_file()  # nothing deleted yet
    assert cli.main(["images-prune", "--unused-days", "30"]) == 0
    assert "2 word(s)" in capsys.readouterr().out
    assert not (cfg.images_dir / fb.file_path).exists() and not (cfg.images_dir / orphan_rel).exists()
    assert (cfg.images_dir / fa.file_path).is_file()  # still referenced by the bank word
    rows = {r[0]: r[1] for r in conn.execute("SELECT id, image_state FROM words")}
    assert rows[used] == "ready" and rows[unused] == "none" and rows[shared] == "none"
    assert conn.execute("SELECT COUNT(*) FROM word_images").fetchone()[0] == 1
    assert conn.execute("SELECT active_image_id FROM words WHERE id=?", (unused,)).fetchone()[0] is None
    # a recent image is never pruned even for an unused word
    fresh = insert_word(conn, "fig")
    store.activate(conn, fresh, provider="wikimedia", ref="f", file_path=fb.file_path, file_bytes=1, sha256=fb.sha256, mime="image/jpeg", now="2026-10-13T00:00:00Z")
    assert image_handler.prune_unused(conn, cfg, 30, now="2026-10-14T00:00:00Z")["words"] == 0
