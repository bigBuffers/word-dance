"""The fetch_image chain end to end (mock_http providers, DNS pinned to a public IP, synchronous queue drain):
provider order, Openverse quota/priority rules, SVG fallback rules, exclude/refresh/report flows, sha reuse,
the admin refetch payload, the CLI commands and activate_svg; PLAN §5.1 C5–C8: the function-word gate, the lemma-token
blocklist exemption, the adverb bare-lemma rule, the kid illustration round (default off), the unchanged default request
shape, the Commons maxlag cooldown, the ignored admin query, the failed-image retry rules and `wd images-retry`."""

from __future__ import annotations

import io
import json
import logging
import os
import stat
import zlib
from dataclasses import replace

import httpx
import pytest
from PIL import Image

from wd import cli, db, logging_setup
from wd.images import activate_svg, handler as image_handler, image_meta, photo_mix, quota, reject_active_image, request_refresh, service, store
from wd.images.sanitize_svg import SvgRejected
from wd.jobs import queue, registry, worker
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


def ai_calls(conn) -> list[dict]:
    return [db.row_to_dict(r) for r in conn.execute("SELECT kind, status, cost_usd FROM ai_calls ORDER BY id")]


def image_state(conn, word_id: int) -> str:
    return conn.execute("SELECT image_state FROM words WHERE id=?", (word_id,)).fetchone()[0]


def drain_images(ctx: JobContext) -> int:
    """Drain only ``fetch_image`` jobs: the ``generate_svg`` jobs this chain enqueues must stay queued for the
    assertions below (their handler is WP5's and would otherwise activate the fake's SVG; it has its own tests)."""
    return worker.drain(ctx, ("fetch_image",))


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
    assert (img["prompt_version"], img["model"], img["text_free"], img["eval_json"]) == (None, None, 0, None)  # 0012 columns: a photo is never text-free by construction
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
    assert dict(ov[0].url.params) == {"q": "apple", "page_size": "10", "license_type": "commercial", "mature": "false"}
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
    drain_images(ctx)
    for w in (bank_word, lonely, batch_word):
        assert json.loads(job(conn, jobs[w])["result_json"])["status"] == "failed"
        assert conn.execute("SELECT image_state FROM words WHERE id=?", (w,)).fetchone()[0] == "failed"
        meta = image_meta(conn, w)
        ImageMeta.model_validate(meta)
        assert meta == {"id": None, "url": f"/media/card/{w}.svg", "kind": "card", "provider": "card_svg", "mime": "image/svg+xml", "width": 800, "height": 500, "alt_zh": None, "attribution": None, "word_layer": False, "hook_zh": None, "note_zh": None}
    bank_svg = svg_jobs(conn, bank_word)
    assert len(bank_svg) == 1 and bank_svg[0]["priority"] == 20 and bank_svg[0]["dedupe_key"] == f"svg:{bank_word}" and bank_svg[0]["status"] == "queued"
    assert json.loads(job(conn, jobs[bank_word])["result_json"])["svg_job_id"] == bank_svg[0]["id"]
    assert svg_jobs(conn, lonely) == []  # in no bank and no batch
    assert len(svg_jobs(conn, batch_word)) == 1  # in an open batch counts as studied
    # a second failure for the same word folds into the live svg job (dedupe)
    enqueue(conn, bank_word, priority=10, now=ctx.now())
    drain_images(ctx)
    assert len(svg_jobs(conn, bank_word)) == 1 and svg_jobs(conn, bank_word)[0]["priority"] == 10
    # WD_SVG_VIA_CLAUDE=0 → no svg job
    off = JobContext(db=connect, cfg=replace(cfg, svg_via_claude=False), clock=frozen_clock, enqueue=queue.enqueue, worker_id="io-1", boot_id="test")
    w4 = insert_word(conn, "fig")
    add_to_bank(conn, w4, "bob")
    enqueue(conn, w4)
    drain_images(off)
    assert svg_jobs(conn, w4) == []
    # AI kill switch / SVG sub-cap 0 → no svg job either
    for variant in (replace(cfg, ai_enabled=False), replace(cfg, ai_svg_daily_budget_usd=0)):
        w = insert_word(conn, f"kiwi{variant.ai_enabled}{variant.ai_svg_daily_budget_usd}")
        conn.execute("INSERT INTO user_words(user_id, word_id, state, origin) VALUES (?,?,'learning','browse')", (uid, w))
        enqueue(conn, w)
        drain_images(JobContext(db=connect, cfg=variant, clock=frozen_clock, enqueue=queue.enqueue, worker_id="io-1", boot_id="test"))
        assert svg_jobs(conn, w) == []


def test_refresh_with_an_active_photo_never_falls_back_to_svg(ctx, conn, mock_http, pinned_dns):
    """DESIGN §9 / §0.1 row 7: the Claude SVG stands in only when NO acceptable photo exists. A 换一张 on a studied word
    that finds nothing new keeps the photo — it must not queue (and later activate) a drawing nor spend the SVG sub-cap."""
    wid = insert_word(conn, "apple")
    set_content(conn, wid, ["red apple"])
    add_to_bank(conn, wid)
    assert service.word_is_studied(conn, wid, ctx.now())
    enqueue(conn, wid)
    drain_images(ctx)
    photo = active_image(conn, wid)
    assert photo["provider"] == "wikimedia"
    mock_http.overrides["commons.wikimedia.org"] = lambda req: httpx.Response(200, json=EMPTY_WIKIMEDIA)
    mock_http.overrides["api.openverse.org"] = lambda req: httpx.Response(200, json=EMPTY_OPENVERSE)
    rid = request_refresh(conn, wid, now=ctx.now())
    drain_images(ctx)
    result = json.loads(job(conn, rid)["result_json"])
    assert result["status"] == "failed" and result["detail"].endswith("(current image kept)") and "svg_job_id" not in result
    assert svg_jobs(conn, wid) == []
    assert active_image(conn, wid)["id"] == photo["id"] and image_state(conn, wid) == "ready"
    assert worker.drain(ctx, ("generate_svg",)) == 0 and ai_calls(conn) == []  # the Claude worker has nothing to do
    assert image_meta(conn, wid)["kind"] == "photo"
    # the report flow (不合适) still falls through to the SVG: the photo is rejected first, so no image is active any more
    jid = reject_active_image(conn, wid, reason="irrelevant_image", now=ctx.now())
    drain_images(ctx)
    result = json.loads(job(conn, jid)["result_json"])
    assert result["status"] == "failed" and len(svg_jobs(conn, wid)) == 1 and result["svg_job_id"] == svg_jobs(conn, wid)[0]["id"]
    assert image_state(conn, wid) == "failed" and image_meta(conn, wid)["kind"] == "card"


def test_queued_svg_job_is_skipped_once_a_photo_landed(ctx, conn, mock_http, pinned_dns):
    """The race behind the same rule: a generate_svg job queued legitimately (no image at the time) runs only after a
    later fetch landed a photo (it sat deferred under the SVG sub-cap, say) — it must finish skipped, spending nothing."""
    mock_http.overrides["commons.wikimedia.org"] = lambda req: httpx.Response(200, json=EMPTY_WIKIMEDIA)
    mock_http.overrides["api.openverse.org"] = lambda req: httpx.Response(200, json=EMPTY_OPENVERSE)
    wid = insert_word(conn, "pear")
    add_to_bank(conn, wid)
    enqueue(conn, wid)
    drain_images(ctx)
    assert active_image(conn, wid) is None and image_state(conn, wid) == "failed"
    assert len(svg_jobs(conn, wid)) == 1 and svg_jobs(conn, wid)[0]["status"] == "queued"
    mock_http.overrides.clear()  # the providers recover and an admin refetch lands a photo while the svg job is still queued
    service.admin_refetch(conn, wid, now=ctx.now())
    drain_images(ctx)
    photo = active_image(conn, wid)
    assert photo["provider"] == "wikimedia" and svg_jobs(conn, wid)[0]["status"] == "queued"
    assert worker.drain(ctx, ("generate_svg",)) == 1
    svg = svg_jobs(conn, wid)[0]
    assert svg["status"] == "done" and json.loads(svg["result_json"]) == {"skipped": "photo_active"}
    assert active_image(conn, wid)["id"] == photo["id"] and conn.execute("SELECT status FROM word_images WHERE id=?", (photo["id"],)).fetchone()[0] == "active"
    assert ai_calls(conn) == [] and image_state(conn, wid) == "ready" and image_meta(conn, wid)["kind"] == "photo"


def test_svg_drawn_while_a_photo_lands_is_discarded(ctx, conn, cfg, mock_http, pinned_dns, monkeypatch):
    """The call takes up to 120 s; a photo that lands meanwhile wins — the handler re-checks before activating."""
    from wd.ai import svg as svg_handler

    mock_http.overrides["commons.wikimedia.org"] = lambda req: httpx.Response(200, json=EMPTY_WIKIMEDIA)
    mock_http.overrides["api.openverse.org"] = lambda req: httpx.Response(200, json=EMPTY_OPENVERSE)
    wid = insert_word(conn, "plum")
    add_to_bank(conn, wid)
    enqueue(conn, wid)
    drain_images(ctx)
    assert active_image(conn, wid) is None and len(svg_jobs(conn, wid)) == 1
    late = store.write_bytes(cfg, b"\xff\xd8\xff" + b"p" * 100, "jpg")
    real_call = svg_handler.common.claude_call

    def call_during_which_a_photo_lands(ctx_, conn_, **kw):
        result = real_call(ctx_, conn_, **kw)
        store.activate(conn_, wid, provider="wikimedia", ref="late", file_path=late.file_path, file_bytes=late.file_bytes, sha256=late.sha256, mime="image/jpeg", now=ctx.now())
        return result

    monkeypatch.setattr(svg_handler.common, "claude_call", call_during_which_a_photo_lands)
    assert worker.drain(ctx, ("generate_svg",)) == 1
    svg = svg_jobs(conn, wid)[0]
    result = json.loads(svg["result_json"])
    assert svg["status"] == "done" and result["skipped"] == "photo_active" and result["cost_usd"] > 0
    assert active_image(conn, wid)["provider_ref"] == "late" and image_state(conn, wid) == "ready"
    assert [c["kind"] for c in ai_calls(conn)] == ["svg"]  # the call happened (ledger) but the drawing was never activated
    assert conn.execute("SELECT COUNT(*) FROM word_images WHERE word_id=? AND provider='claude_svg'", (wid,)).fetchone()[0] == 0


def test_admin_claude_svg_request_draws_over_an_active_photo(ctx, conn, mock_http, pinned_dns):
    """API.md 69 `provider: "claude_svg"` is an explicit decision: the job carries `requested` on its own live key and
    the handler draws although a photo is active, while a fallback job for the same word is skipped."""
    wid = insert_word(conn, "apple")
    enqueue(conn, wid)
    queue.run_once(ctx)
    photo = active_image(conn, wid)
    sid = service.admin_refetch(conn, wid, provider="claude_svg", now=ctx.now())
    drain_images(ctx)
    result = json.loads(job(conn, sid)["result_json"])
    svg = svg_jobs(conn, wid)
    assert result["status"] == "svg_queued" and len(svg) == 1 and svg[0]["id"] == result["svg_job_id"] and svg[0]["priority"] == 10
    assert svg[0]["dedupe_key"] == f"svg:{wid}:req" and json.loads(svg[0]["payload_json"]) == {"word_id": wid, "requested": True}
    fallback = queue.enqueue(conn, "generate_svg", {"word_id": wid}, dedupe_key=f"svg:{wid}", priority=20, now=ctx.now())
    assert fallback != svg[0]["id"]  # an explicit request never folds into (or is swallowed by) a fallback job
    assert worker.drain(ctx, ("generate_svg",)) == 2
    assert active_image(conn, wid)["provider"] == "claude_svg" and image_meta(conn, wid)["kind"] == "svg"
    assert conn.execute("SELECT status FROM word_images WHERE id=?", (photo["id"],)).fetchone()[0] == "superseded"
    assert json.loads(job(conn, fallback)["result_json"]) == {"skipped": "photo_active"}  # the requested SVG is active now
    assert [c["kind"] for c in ai_calls(conn)] == ["svg"]


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
    assert payload == {"word_id": wid, "provider": "openverse", "query": "green apple", "requested": True}  # requested: an admin's explicit refetch (API.md 69)
    queue.run_once(ctx)
    assert mock_http.calls_to("commons.wikimedia.org") == []
    assert mock_http.calls_to("api.openverse.org")[0].url.params["q"] == "green apple"
    assert active_image(conn, wid)["provider"] == "openverse" and active_image(conn, wid)["query"] == "green apple"
    sid = service.admin_refetch(conn, wid, provider="claude_svg", now=ctx.now())
    queue.run_once(ctx)
    result = json.loads(job(conn, sid)["result_json"])
    assert result["status"] == "svg_queued" and svg_jobs(conn, wid)[0]["id"] == result["svg_job_id"] and svg_jobs(conn, wid)[0]["priority"] == 10


def test_merge_fetch_payloads():
    merge = service.merge_fetch_payloads
    assert merge({"word_id": 1}, {"word_id": 1}) == {"word_id": 1}
    assert merge({"word_id": 1, "exclude": ["a"]}, {"word_id": 1, "exclude": ["b", "a"]}) == {"word_id": 1, "exclude": ["a", "b"]}
    assert merge({"word_id": 1, "provider": "openverse", "query": "x"}, {"word_id": 1, "exclude": ["a"]}) == {"word_id": 1, "provider": "openverse", "query": "x", "exclude": ["a"]}
    assert merge({"word_id": 1, "query": "x"}, {"word_id": 1, "provider": "wikimedia", "query": "y"}) == {"word_id": 1, "query": "y", "provider": "wikimedia"}
    # requested (an admin's refetch, API.md 69) is sticky in both directions: folded into a learner's job, or met by a learner's later 换一张
    assert merge({"word_id": 1, "exclude": ["a"]}, {"word_id": 1, "requested": True}) == {"word_id": 1, "exclude": ["a"], "requested": True}
    assert merge({"word_id": 1, "requested": True}, {"word_id": 1, "exclude": ["a"]}) == {"word_id": 1, "requested": True, "exclude": ["a"]}
    assert merge({"word_id": 1}, {"word_id": 1, "requested": "yes"}) == {"word_id": 1}  # only a JSON true counts


def test_enqueue_fetch_merges_a_later_request_into_the_queued_job(ctx, conn, mock_http, pinned_dns):
    """queue.enqueue's UPSERT keeps the live job's payload: an API.md 69 override or a 换一张 exclude that meets a
    queued plain job must be folded into that job rather than silently dropped while the caller gets its id."""
    distinct_photos(mock_http)
    wid = insert_word(conn, "apple")
    set_content(conn, wid, ["red apple"])
    plain = enqueue(conn, wid)  # what the content handler enqueues: {"word_id"} only
    jid = service.admin_refetch(conn, wid, provider="openverse", query="green apple", now=ctx.now())
    assert jid == plain
    j = job(conn, jid)
    assert json.loads(j["payload_json"]) == {"word_id": wid, "provider": "openverse", "query": "green apple", "requested": True} and j["priority"] == 10
    queue.run_once(ctx)
    assert mock_http.calls_to("commons.wikimedia.org") == [] and mock_http.calls_to("api.openverse.org")[0].url.params["q"] == "green apple"
    first = active_image(conn, wid)
    assert first["provider"] == "openverse" and first["query"] == "green apple"
    # a 换一张 meeting a queued plain job (one requeued after a worker crash, say) adds its exclude list to it
    stale = enqueue(conn, wid, now=ctx.now())
    rid = request_refresh(conn, wid, now=ctx.now())
    assert rid == stale and set(json.loads(job(conn, rid)["payload_json"])["exclude"]) == {first["provider_ref"], first["sha256"]}
    assert conn.execute("SELECT COUNT(*) FROM jobs WHERE type='fetch_image'").fetchone()[0] == 2
    queue.run_once(ctx)
    assert json.loads(job(conn, rid)["result_json"])["status"] == "ready" and active_image(conn, wid)["provider_ref"] != first["provider_ref"]


def test_enqueue_fetch_queues_a_follow_up_behind_a_running_job(ctx, conn, mock_http, pinned_dns):
    """A running job has already read its payload: a request it does not cover gets a follow-up on `image:<id>:r<n>`
    (the IoWorker runs it next), a request it does cover keeps returning the running job's id (no duplicate fetch)."""
    distinct_photos(mock_http)
    wid = insert_word(conn, "apple")
    enqueue(conn, wid)
    queue.run_once(ctx)
    first = active_image(conn, wid)
    j1 = request_refresh(conn, wid, now=ctx.now())
    claimed = queue.claim_batch(conn, "fetch_image", 1, ctx.locked_by, now=ctx.now())
    assert [c.id for c in claimed] == [j1] and job(conn, j1)["status"] == "running"
    assert request_refresh(conn, wid, now=ctx.now()) == j1  # the same exclude list is already covered
    j2 = service.admin_refetch(conn, wid, provider="openverse", query="green apple", now=ctx.now())
    follow = job(conn, j2)
    assert j2 != j1 and follow["dedupe_key"] == f"image:{wid}:r1" and follow["status"] == "queued" and follow["priority"] == 10
    assert json.loads(follow["payload_json"]) == {"word_id": wid, "exclude": [first["provider_ref"], first["sha256"]], "provider": "openverse", "query": "green apple", "requested": True}
    assert json.loads(job(conn, j1)["payload_json"]) == {"word_id": wid, "exclude": [first["provider_ref"], first["sha256"]]}  # the running job is left alone
    # a third request while the first still runs folds into the queued follow-up (no r2)
    assert service.admin_refetch(conn, wid, query="apple pie", now=ctx.now()) == j2
    assert json.loads(job(conn, j2)["payload_json"])["query"] == "apple pie" and json.loads(job(conn, j2)["payload_json"])["provider"] == "openverse"
    assert conn.execute("SELECT COUNT(*) FROM jobs WHERE type='fetch_image'").fetchone()[0] == 3
    # the running job finishes through its handler, then the follow-up runs with the override
    registry.get_handler("fetch_image")(ctx, claimed)
    assert job(conn, j1)["status"] == "done" and active_image(conn, wid)["provider_ref"] != first["provider_ref"]
    seen = len(mock_http.calls_to("api.openverse.org"))
    queue.run_once(ctx)
    assert job(conn, j2)["status"] == "done" and [r.url.params["q"] for r in mock_http.calls_to("api.openverse.org")[seen:]] == ["apple pie"]
    assert active_image(conn, wid)["provider"] == "openverse" and active_image(conn, wid)["query"] == "apple pie"
    assert conn.execute("SELECT COUNT(*) FROM jobs WHERE type='fetch_image' AND status IN ('queued','running')").fetchone()[0] == 0
    assert job(conn, request_refresh(conn, wid, now=ctx.now()))["dedupe_key"] == f"image:{wid}"  # the primary key is free again


def test_keywords_come_from_content_with_blocklist_and_shape_filter(ctx, conn, mock_http, pinned_dns):
    wid = insert_word(conn, "apple")
    set_content(conn, wid, ["bar chart", "http://evil", "", "x" * 60, "Stock market"])  # blocklist (chart is not an apple token), bad shape, too long
    enqueue(conn, wid)
    queue.run_once(ctx)
    assert mock_http.calls_to("commons.wikimedia.org")[0].url.params["gsrsearch"] == "stock market filetype:bitmap"
    wid2 = insert_word(conn, "pear")
    set_content(conn, wid2, ["bar chart"])  # nothing survives → the lemma
    enqueue(conn, wid2)
    queue.run_once(ctx)
    assert mock_http.calls_to("commons.wikimedia.org")[-1].url.params["gsrsearch"] == "pear filetype:bitmap"
    # clean_keywords reports what it dropped (the admin-query path logs it) and honours allow_lemma
    assert image_handler.clean_keywords(["bar chart", "http://evil", "", "x" * 60, "Stock market", "stock  market"], "apple") == (["stock market"], ["bar chart", "http://evil", "", "x" * 60])
    assert image_handler.clean_keywords(["bar chart"], "pear") == (["pear"], ["bar chart"])
    assert image_handler.clean_keywords(["bar chart"], "pear", allow_lemma=False) == ([], ["bar chart"])
    assert image_handler.clean_keywords(["bar chart"], "chart") == (["bar chart"], [])
    assert image_handler.clean_keywords(["a", "b c", "d e", "f g", 7, None], "x") == (["b c", "d e", "f g"], ["a"])  # ≤ 3 kept, non-strings ignored


def test_lemma_token_is_exempt_from_the_non_photo_blocklist(ctx, conn, mock_http, pinned_dns):
    """PLAN §5.1 C5 / D-images-10: `map`, `chart`, `flag`, `cover`, `text` are 小学 words — their own tokens pass the
    non-photo list, so the card for `chart` may search "bar chart" (and select.rank lets a "Bar chart" title through)."""
    wid = insert_word(conn, "chart")
    set_content(conn, wid, ["bar chart", "stock market"])
    enqueue(conn, wid)
    queue.run_once(ctx)
    assert mock_http.calls_to("commons.wikimedia.org")[0].url.params["gsrsearch"] == "bar chart filetype:bitmap"
    assert active_image(conn, wid)["query"] == "bar chart"
    # the unsafe list is never exempted: `gun`'s own keyword "toy gun" is dropped and the bare lemma is not searched either
    gun = insert_word(conn, "gun")
    set_content(conn, gun, ["toy gun", "water pistol"])
    enqueue(conn, gun, now=ctx.now())
    queue.run_once(ctx)
    assert mock_http.calls_to("commons.wikimedia.org")[-1].url.params["gsrsearch"] == "water pistol filetype:bitmap"


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
    wid = insert_word(conn, "apple", image_state="queued")
    jid = enqueue(conn, wid)

    def boom(*a, **k):
        raise RuntimeError("provider exploded")

    monkeypatch.setattr(image_handler, "fetch_for_word", boom)
    queue.run_once(ctx)
    j = job(conn, jid)
    assert j["status"] == "queued" and "provider exploded" in j["last_error"] and j["attempts"] == 1
    assert image_state(conn, wid) == "queued"  # a retry is pending; the state is reset only once the job goes dead (below)


def test_dead_fetch_job_leaves_the_word_failed_or_ready_never_queued(ctx, conn, cfg, monkeypatch, mock_http, pinned_dns):
    """A fetch_image job that crashes on its last attempt goes `dead` (queue.fail); the word must not stay `queued` for ever —
    the nightly retry selects `failed` and requeue_dead_once revives only content/lookup jobs, so nothing else would ever
    heal it (PLAN §5.1 C7; impl-review final M-3). Like ai.svg.mark_failed: `failed`, or `ready` when an image is active."""

    def boom(*a, **k):
        raise RuntimeError("provider exploded")

    monkeypatch.setattr(image_handler, "fetch_for_word", boom)
    wid = insert_word(conn, "apple", image_state="queued")
    jid = queue.enqueue(conn, "fetch_image", {"word_id": wid}, dedupe_key=f"image:{wid}", priority=20, max_attempts=1, now=ctx.now())
    queue.run_once(ctx)
    assert job(conn, jid)["status"] == "dead" and image_state(conn, wid) == "failed" and active_image(conn, wid) is None
    # an active image is kept and the word goes back to ready (a 换一张 that died must not demote the picture to a template card)
    pear = insert_word(conn, "pear")
    activate_svg(conn, cfg, pear, '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 800 500"><rect width="1" height="1"/></svg>', None, now=ctx.now())
    store.set_image_state(conn, pear, "queued", now=ctx.now())
    jid2 = queue.enqueue(conn, "fetch_image", {"word_id": pear}, dedupe_key=f"image:{pear}", priority=10, max_attempts=1, now=ctx.now())
    queue.run_once(ctx)
    assert job(conn, jid2)["status"] == "dead" and image_state(conn, pear) == "ready" and active_image(conn, pear)["provider"] == "claude_svg"


def test_malformed_candidate_urls_and_provider_crashes_never_kill_the_job(ctx, conn, mock_http, pinned_dns, monkeypatch):
    """httpx.InvalidURL is not an HTTPError: a candidate URL carrying a C0/DEL byte used to escape download_and_store
    and openverse.parse_search and crash the whole job (provider request uncounted, backoff, finally dead)."""
    for page in mock_http.wikimedia["query"]["pages"].values():
        page["imageinfo"][0]["thumburl"] = page["imageinfo"][0]["thumburl"].replace("/960px-", "/960px-\x7f")
    mock_http.openverse["results"][0]["url"] = "https://live.staticflickr.com/8035/807\x7f4168006.jpg"
    wid = insert_word(conn, "apple")
    jid = enqueue(conn, wid)
    queue.run_once(ctx)
    j = job(conn, jid)
    assert j["status"] == "done", j["last_error"]
    result = json.loads(j["result_json"])
    assert result["status"] == "ready" and result["provider"] == "openverse" and result["ref"] == "c4939b4c-aa73-4256-bb52-9b25962562d9"
    assert mock_http.calls_to("thumb.wikimedia.org") == []  # both Commons thumbs refused before any request went out
    assert quota.counts(conn, "wikimedia", ctx.now()) == (1, 1) and quota.counts(conn, "openverse", ctx.now()) == (1, 1)
    assert image_state(conn, wid) == "ready"
    # any other exception out of a provider is counted, recorded on the provider and the chain moves on
    from wd.images.providers import WikimediaProvider

    def boom(self, query, limit, *, style="neutral"):
        raise TypeError("unexpected response shape")

    monkeypatch.setattr(WikimediaProvider, "search", boom)
    wid2 = insert_word(conn, "pear")
    jid2 = enqueue(conn, wid2, now=ctx.now())
    queue.run_once(ctx)
    assert json.loads(job(conn, jid2)["result_json"])["provider"] == "openverse"
    assert quota.counts(conn, "wikimedia", ctx.now()) == (2, 2)
    st = quota.state(conn, "wikimedia")
    assert st["consecutive_errors"] == 1 and st["last_error"] == "TypeError: unexpected response shape" and st["cooldown_until"] is None


# ------------------------------------------------------- function-word gate · bare lemma · rounds (PLAN §5.1 C5 / C8)
def test_function_word_without_admin_override_gets_the_card_and_no_provider_call(ctx, conn, mock_http, pinned_dns, capsys):
    """D-images-9: a word whose dominant pos is a function word (prep / conj / det / pron / art / int / inf) gets
    image_state='failed' and the template card without a single provider request or an SVG job, even while studied."""
    uid = None
    for lemma, pos in (("of", "i:100"), ("despite", "i:100"), ("some", "p:1/d:99"), ("and", "c:100"), ("oh", "u:100")):
        wid = insert_word(conn, lemma, pos=pos)
        if uid is None:
            uid = add_to_bank(conn, wid)
        else:
            conn.execute("INSERT INTO user_words(user_id, word_id, state, origin) VALUES (?,?,'new','browse')", (uid, wid))
        set_content(conn, wid, [f"{lemma} something"])
        jid = enqueue(conn, wid)
        queue.run_once(ctx)
        assert json.loads(job(conn, jid)["result_json"]) == {"status": "skipped", "detail": "function word: card only"}, lemma
        assert image_state(conn, wid) == "failed" and svg_jobs(conn, wid) == [] and active_image(conn, wid) is None
        assert image_meta(conn, wid)["kind"] == "card"
    assert mock_http.calls == []
    # content words with the same shape of pos string are fetched as before
    noun = insert_word(conn, "apple", pos="n:96/v:4")
    enqueue(conn, noun)
    queue.run_once(ctx)
    assert active_image(conn, noun)["provider"] == "wikimedia"
    # the CLI reports the gate and exits 0 (a skip is the design's answer, not a failed chain)
    assert cli.main(["fetch-image", "of", "--no-svg"]) == 0
    out = capsys.readouterr().out
    assert "status: skipped" in out and "detail: function word: card only" in out
    assert all("apple" in c.url.params["gsrsearch"] for c in mock_http.calls_to("commons.wikimedia.org"))  # only the noun ever reached Commons


def test_function_word_with_an_active_image_keeps_it_and_stays_ready(ctx, conn, cfg, mock_http, pinned_dns, capsys):
    """The gate never contradicts a live image (impl-review S5b F-1): `despite` (i:100) on the live DB carries an
    admin-requested SVG with image_state='ready'. A 换一张 (request_refresh: no provider / query), a content re-generation's
    fetch or `wd fetch-image despite --no-svg` still makes no provider request and queues no SVG, but the image stays
    active and the state returns to `ready` from the `queued` enqueue_fetch wrote — `failed` beside an active_image_id
    would under-count in diag and never heal, because the nightly retry skips function words."""
    wid = insert_word(conn, "despite", pos="i:100")
    add_to_bank(conn, wid)
    set_content(conn, wid, ["despite the rain"])
    svg = '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 800 500"><rect width="800" height="500" fill="#eee"/></svg>'
    image_id = activate_svg(conn, cfg, wid, svg, "雨中打伞的人", now=ctx.now())
    assert image_state(conn, wid) == "ready" and image_meta(conn, wid)["kind"] == "svg"
    rid = request_refresh(conn, wid, now=ctx.now())
    assert image_state(conn, wid) == "queued"
    drain_images(ctx)
    assert json.loads(job(conn, rid)["result_json"]) == {"status": "skipped", "detail": "function word: current image kept"}
    assert image_state(conn, wid) == "ready" and active_image(conn, wid)["id"] == image_id and image_meta(conn, wid)["kind"] == "svg"
    assert svg_jobs(conn, wid) == [] and mock_http.calls == []
    # the CLI runs the same gate and exits 0
    assert cli.main(["fetch-image", "despite", "--no-svg"]) == 0
    out = capsys.readouterr().out
    assert "status: skipped" in out and "detail: function word: current image kept" in out
    assert image_state(conn, wid) == "ready" and active_image(conn, wid)["id"] == image_id and mock_http.calls == []
    # the report flow (不合适) clears the image first, so the same gate then puts the word on the card
    jid = reject_active_image(conn, wid, reason="irrelevant_image", now=ctx.now())
    drain_images(ctx)
    assert json.loads(job(conn, jid)["result_json"]) == {"status": "skipped", "detail": "function word: card only"}
    assert image_state(conn, wid) == "failed" and active_image(conn, wid) is None and image_meta(conn, wid)["kind"] == "card"
    assert svg_jobs(conn, wid) == [] and mock_http.calls == []


def test_function_word_with_admin_query_is_fetched(ctx, conn, mock_http, pinned_dns):
    """An admin override (query / provider) is an explicit decision and bypasses the gate; without a query the function
    word still gets no bare-lemma search (NO_BARE_LEMMA_POS), so an explicit provider alone ends on the card."""
    wid = insert_word(conn, "of", pos="i:100")
    jid = service.admin_refetch(conn, wid, query="box of apples", now=ctx.now())
    queue.run_once(ctx)
    result = json.loads(job(conn, jid)["result_json"])
    assert result["status"] == "ready" and result["query"] == "box of apples" and "query ignored" not in result.get("detail", "")
    assert mock_http.calls_to("commons.wikimedia.org")[0].url.params["gsrsearch"] == "box of apples filetype:bitmap"
    assert image_state(conn, wid) == "ready" and image_meta(conn, wid)["kind"] == "photo"
    sid = service.admin_refetch(conn, wid, provider="claude_svg", now=ctx.now())
    drain_images(ctx)
    assert json.loads(job(conn, sid)["result_json"])["status"] == "svg_queued" and len(svg_jobs(conn, wid)) == 1 and svg_jobs(conn, wid)[0]["status"] == "queued"
    other = insert_word(conn, "despite", pos="i:100")
    seen = len(mock_http.calls)
    pid = service.admin_refetch(conn, other, provider="wikimedia", now=ctx.now())
    drain_images(ctx)
    result = json.loads(job(conn, pid)["result_json"])
    assert result["status"] == "failed" and result["detail"] == "no acceptable photo from any provider" and len(mock_http.calls) == seen
    assert image_state(conn, other) == "failed"


def test_adverb_without_content_keywords_skips_the_bare_lemma_search(ctx, conn, mock_http, pinned_dns):
    """D-images-9: adverbs are not gated (fast / today are drawable) but never searched by their bare lemma — without a
    usable content keyword no provider is asked; the SVG fallback still applies to a studied word."""
    very = insert_word(conn, "very", pos="r:100")
    add_to_bank(conn, very)
    jid = enqueue(conn, very)
    drain_images(ctx)
    assert json.loads(job(conn, jid)["result_json"])["status"] == "failed" and mock_http.calls == []
    assert image_state(conn, very) == "failed" and len(svg_jobs(conn, very)) == 1 and svg_jobs(conn, very)[0]["status"] == "queued"  # the drawing is still worth a try
    # content keywords that all fail the shape rule / blocklist → still no bare lemma
    why = insert_word(conn, "why", pos="r:100")
    set_content(conn, why, ["http://x", "world map"])
    enqueue(conn, why)
    drain_images(ctx)
    assert mock_http.calls == [] and image_state(conn, why) == "failed"
    # a usable content keyword is searched like for any other word
    fast = insert_word(conn, "fast", pos="r:70/j:30")
    set_content(conn, fast, ["fast runner"])
    enqueue(conn, fast)
    queue.run_once(ctx)
    assert mock_http.calls_to("commons.wikimedia.org")[0].url.params["gsrsearch"] == "fast runner filetype:bitmap"
    assert active_image(conn, fast)["query"] == "fast runner"
    # an unknown pos (a phrase, a Claude word) keeps the bare-lemma search
    phrase = insert_word(conn, "ice cream", kind="phrase", pos=None)
    enqueue(conn, phrase)
    queue.run_once(ctx)
    assert mock_http.calls_to("commons.wikimedia.org")[-1].url.params["gsrsearch"] == "ice cream filetype:bitmap"


def test_default_chain_shape_is_unchanged_except_thumbmime_maxlag_page_size(ctx, conn, cfg, mock_http, pinned_dns):
    """PLAN §5.3: with WD_IMAGE_KID_STAGES empty the live request shapes differ from before only by `thumbmime` (iiprop),
    `maxlag=5` and `page_size=10` — no kid round, no `category`, no `orientation`, `filetype:bitmap` as ever."""
    assert cfg.image_kid_stages == ()
    mock_http.overrides["commons.wikimedia.org"] = lambda req: httpx.Response(200, json=EMPTY_WIKIMEDIA)
    wid = insert_word(conn, "cat", stage_xs=1, stage_zk=1, stage_min=1)  # a 小学 word: neutral until the pilot clears `xs`
    enqueue(conn, wid)
    queue.run_once(ctx)
    commons = mock_http.calls_to("commons.wikimedia.org")
    openverse = mock_http.calls_to("api.openverse.org")
    assert len(commons) == 1 and len(openverse) == 1
    assert dict(commons[0].url.params) == {
        "action": "query",
        "generator": "search",
        "gsrsearch": "cat filetype:bitmap",
        "gsrnamespace": "6",
        "gsrlimit": "10",
        "prop": "imageinfo",
        "iiprop": "url|extmetadata|size|mime|thumbmime",
        "iiurlwidth": "800",
        "format": "json",
        "maxlag": "5",
    }
    assert dict(openverse[0].url.params) == {"q": "cat", "page_size": "10", "license_type": "commercial", "mature": "false"}
    assert image_handler.search_rounds(cfg, "neutral", None) == (("neutral", ("wikimedia", "openverse")),)
    assert image_handler.search_rounds(cfg, "neutral", "openverse") == (("neutral", ("openverse",)),)


def test_kid_stage_word_tries_drawing_then_bitmap(cfg, conn, connect, frozen_clock, mock_http, pinned_dns):
    """PLAN §5.1 C8: a word whose stage is listed in WD_IMAGE_KID_STAGES runs an illustration round first (Commons
    `filetype:drawing`, Openverse `category=illustration`, Pexels left out) and falls back to the ordinary photo round."""
    registry.load_handlers()
    kid_cfg = replace(cfg, image_kid_stages=("zk",), pexels_key="pk", image_providers=("wikimedia", "openverse", "pexels"))
    kid_ctx = JobContext(db=connect, cfg=kid_cfg, clock=frozen_clock, enqueue=queue.enqueue, worker_id="io-1", boot_id="test")
    assert image_handler.search_rounds(kid_cfg, "kid", None) == (("kid", ("wikimedia", "openverse")), ("neutral", ("wikimedia", "openverse", "pexels")))
    assert image_handler.search_rounds(kid_cfg, "kid", "openverse") == (("kid", ("openverse",)),)  # an explicit provider: one round in the word's style
    assert image_handler.search_rounds(replace(kid_cfg, image_providers=("pexels",)), "kid", None) == (("kid", ()), ("neutral", ("pexels",)))  # the empty kid round is skipped by the handler
    mock_http.overrides["commons.wikimedia.org"] = lambda req: httpx.Response(200, json=EMPTY_WIKIMEDIA if "filetype:drawing" in req.url.params["gsrsearch"] else mock_http.wikimedia)
    mock_http.overrides["api.openverse.org"] = lambda req: httpx.Response(200, json=EMPTY_OPENVERSE if "category" in req.url.params else mock_http.openverse)
    cat = insert_word(conn, "cat", stage_zk=1, stage_min=2)
    jid = enqueue(conn, cat)
    queue.run_once(kid_ctx)
    result = json.loads(job(conn, jid)["result_json"])
    assert result["status"] == "ready" and result["provider"] == "wikimedia" and result["query"] == "cat"
    assert [c.url.params["gsrsearch"] for c in mock_http.calls_to("commons.wikimedia.org")] == ["cat filetype:drawing", "cat filetype:bitmap"]
    assert [dict(c.url.params) for c in mock_http.calls_to("api.openverse.org")] == [{"q": "cat", "page_size": "10", "license_type": "commercial", "mature": "false", "category": "illustration"}]
    assert mock_http.calls_to("api.pexels.com") == []  # never in the kid round; the neutral round found the photo on Commons first
    assert quota.counts(conn, "wikimedia", kid_ctx.now()) == (2, 2)
    # a word of another stage under the same configuration: the single neutral round
    mock_http.calls.clear()
    dog = insert_word(conn, "dog", stage_gk=1, stage_min=3)
    enqueue(conn, dog, now=kid_ctx.now())
    queue.run_once(kid_ctx)
    assert [c.url.params["gsrsearch"] for c in mock_http.calls_to("commons.wikimedia.org")] == ["dog filetype:bitmap"]
    assert active_image(conn, dog)["provider"] == "wikimedia"
    # an explicit admin provider on a kid word: one round, kid style, no neutral fallback
    mock_http.calls.clear()
    aid = service.admin_refetch(conn, cat, provider="openverse", now=kid_ctx.now())
    queue.run_once(kid_ctx)
    assert json.loads(job(conn, aid)["result_json"])["status"] == "failed"
    assert [c.url.params.get("category") for c in mock_http.calls_to("api.openverse.org")] == ["illustration"] and mock_http.calls_to("commons.wikimedia.org") == []
    # the default configuration never runs the kid round for the same word
    mock_http.calls.clear()
    plain = JobContext(db=connect, cfg=cfg, clock=frozen_clock, enqueue=queue.enqueue, worker_id="io-1", boot_id="test")
    conn.execute("UPDATE words SET active_image_id = NULL, image_state = 'none' WHERE id = ?", (cat,))
    conn.execute("UPDATE word_images SET status = 'superseded' WHERE word_id = ?", (cat,))
    enqueue(conn, cat, now=plain.now())
    queue.run_once(plain)
    assert [c.url.params["gsrsearch"] for c in mock_http.calls_to("commons.wikimedia.org")] == ["cat filetype:bitmap"]


def test_prewarm_priority_skips_openverse_pixabay_and_pexels(cfg, conn, connect, frozen_clock, mock_http, pinned_dns):
    """PREWARM_SKIP_PROVIDERS: at priority ≥ 90 only Commons is asked — the quota-bound and keyed providers are for words
    somebody is about to study (Pixabay forbids systematic mass downloads)."""
    registry.load_handlers()
    keyed = replace(cfg, pixabay_key="k", pexels_key="p", image_providers=("wikimedia", "openverse", "pixabay", "pexels"))
    kctx = JobContext(db=connect, cfg=keyed, clock=frozen_clock, enqueue=queue.enqueue, worker_id="io-1", boot_id="test")
    mock_http.overrides["commons.wikimedia.org"] = lambda req: httpx.Response(200, json=EMPTY_WIKIMEDIA)
    mock_http.overrides["api.openverse.org"] = lambda req: httpx.Response(200, json=EMPTY_OPENVERSE)
    wid = insert_word(conn, "apple")
    enqueue(conn, wid, priority=90)
    queue.run_once(kctx)
    assert {h for h in (mock_http.host_of(c) for c in mock_http.calls)} == {"commons.wikimedia.org"}
    assert image_handler.PREWARM_SKIP_PROVIDERS == ("openverse", "pixabay", "pexels")
    enqueue(conn, wid, priority=20, now=kctx.now())
    queue.run_once(kctx)
    hosts = {mock_http.host_of(c) for c in mock_http.calls}
    assert {"api.openverse.org", "pixabay.com", "api.pexels.com"} <= hosts  # the keyed providers answer 404 from the mock, which is just a provider error


def test_wikimedia_maxlag_body_puts_commons_in_cooldown_and_the_chain_moves_on(ctx, conn, cfg, mock_http, pinned_dns):
    """A 200 answer with `error.code == "maxlag"` is a 503 for the quota layer: cooldown from Retry-After (or 30 s), the
    request counted, Openverse answers the word."""
    body = {"error": {"code": "maxlag", "info": "Waiting for a database server: 6 seconds lagged.", "lag": 6}}
    mock_http.overrides["commons.wikimedia.org"] = lambda req: httpx.Response(200, json=body, headers={"Retry-After": "7"})
    wid = insert_word(conn, "apple")
    jid = enqueue(conn, wid)
    queue.run_once(ctx)
    assert json.loads(job(conn, jid)["result_json"])["provider"] == "openverse"
    st = quota.state(conn, "wikimedia")
    assert st["cooldown_until"] == "2026-10-14T00:00:07Z" and st["consecutive_errors"] == 1 and "maxlag" in st["last_error"]
    assert quota.counts(conn, "wikimedia", ctx.now()) == (1, 1) and quota.check(conn, "wikimedia", cfg, ctx.now()) == "cooldown"
    mock_http.overrides["commons.wikimedia.org"] = lambda req: httpx.Response(200, json=body)
    quota.mark_ok(conn, "wikimedia", ctx.now())
    conn.execute("UPDATE provider_state SET cooldown_until = NULL WHERE provider = 'wikimedia'")
    enqueue(conn, insert_word(conn, "pear"), now=ctx.now())
    queue.run_once(ctx)
    assert quota.state(conn, "wikimedia")["cooldown_until"] == "2026-10-14T00:00:30Z"


def test_admin_query_dropped_by_shape_rule_is_reported(ctx, conn, mock_http, pinned_dns, caplog):
    """An API.md 69 query that fails the shape rule or the blocklist is not refused (the request stays a 202): the handler
    logs `query_ignored`, prefixes the result detail and searches the content keywords (or the bare lemma) instead."""
    distinct_photos(mock_http)  # the refetch excludes the current photo by sha: every candidate needs its own bytes
    wid = insert_word(conn, "apple")
    set_content(conn, wid, ["red apple"])
    with caplog.at_level(logging.WARNING, logger="wd.images"):
        jid = service.admin_refetch(conn, wid, query="http://evil", now=ctx.now())
        queue.run_once(ctx)
    result = json.loads(job(conn, jid)["result_json"])
    assert result["status"] == "ready" and result["query"] == "red apple" and result["detail"] == "query ignored (shape/blocklist)"
    assert mock_http.calls_to("commons.wikimedia.org")[0].url.params["gsrsearch"] == "red apple filetype:bitmap"
    ignored = [r for r in caplog.records if getattr(r, "event", None) == "query_ignored" and r.word_id == wid]
    assert ignored and json.loads(logging_setup.JsonFormatter().format(ignored[0]))["word_id"] == wid  # word_id is an EXTRA_FIELD: it reaches the journal (final M-4)
    # a blocklisted query for a word whose tokens do not cover it is dropped the same way …
    jid2 = service.admin_refetch(conn, wid, query="world map", now=ctx.now())
    queue.run_once(ctx)
    result = json.loads(job(conn, jid2)["result_json"])
    assert result["detail"].startswith("query ignored (shape/blocklist)") and result["query"] == "red apple"
    # … while the lemma's own token lets it through
    world = insert_word(conn, "map")
    jid3 = service.admin_refetch(conn, world, query="world map", now=ctx.now())
    queue.run_once(ctx)
    result = json.loads(job(conn, jid3)["result_json"])
    assert result["status"] == "ready" and result["query"] == "world map" and "detail" not in result
    assert mock_http.calls_to("commons.wikimedia.org")[-1].url.params["gsrsearch"] == "world map filetype:bitmap"
    # no content keywords: a noun falls back to its bare lemma, and a failed chain keeps the prefix in front of its detail
    mock_http.overrides["commons.wikimedia.org"] = lambda req: httpx.Response(200, json=EMPTY_WIKIMEDIA)
    mock_http.overrides["api.openverse.org"] = lambda req: httpx.Response(200, json=EMPTY_OPENVERSE)
    bare = insert_word(conn, "pear")
    jid4 = service.admin_refetch(conn, bare, query="x" * 60, now=ctx.now())
    queue.run_once(ctx)
    result = json.loads(job(conn, jid4)["result_json"])
    assert result["status"] == "failed" and result["detail"] == "query ignored (shape/blocklist); no acceptable photo from any provider"
    assert mock_http.calls_to("commons.wikimedia.org")[-1].url.params["gsrsearch"] == "pear filetype:bitmap"


# ------------------------------------------------------------------------------- failed-image retries (PLAN §5.1 C7)
def all_empty(mock_http) -> None:
    mock_http.overrides["commons.wikimedia.org"] = lambda req: httpx.Response(200, json=EMPTY_WIKIMEDIA)
    mock_http.overrides["api.openverse.org"] = lambda req: httpx.Response(200, json=EMPTY_OPENVERSE)


def fetch_jobs(conn, word_id: int) -> list[dict]:
    return [db.row_to_dict(r) for r in conn.execute("SELECT * FROM jobs WHERE type='fetch_image' AND json_extract(payload_json,'$.word_id')=? ORDER BY id", (word_id,))]


def test_failed_word_is_retried_when_marked_unfamiliar_after_six_hours(ctx, conn, mock_http, pinned_dns, frozen_clock):
    """retry_if_failed (the hook for the bank / batch sites, R-16): a `failed` word is fetched again ≥ 6 h after its last
    fetch_image job ended, never while a fetch job is live, never for a function word; the job carries retry:true."""
    from wd.services import words

    all_empty(mock_http)
    wid = insert_word(conn, "apple")
    add_to_bank(conn, wid)
    enqueue(conn, wid)
    drain_images(ctx)
    assert image_state(conn, wid) == "failed" and service.last_fetch_finished_at(conn, wid) == "2026-10-14T00:00:00Z"
    assert service.retry_due(conn, words.word_row(conn, wid), ctx.now()) is False
    frozen_clock.advance(hours=1)
    assert service.retry_if_failed(conn, words.word_row(conn, wid), priority=20, now=ctx.now()) is None  # < 6 h
    assert len(fetch_jobs(conn, wid)) == 1
    frozen_clock.advance(hours=5)  # exactly 6 h: due
    jid = service.retry_if_failed(conn, words.word_row(conn, wid), priority=20, now=ctx.now())
    assert jid is not None
    j = job(conn, jid)
    assert j["type"] == "fetch_image" and j["dedupe_key"] == f"image:{wid}" and j["priority"] == 20 and j["status"] == "queued"
    assert json.loads(j["payload_json"]) == {"word_id": wid, "retry": True} and image_state(conn, wid) == "queued"
    assert service.auto_retries_30d(conn, wid, ctx.now()) == 1
    # a live fetch job blocks a second retry even when the word is marked failed again meanwhile
    conn.execute("UPDATE words SET image_state = 'failed' WHERE id = ?", (wid,))
    assert service.retry_if_failed(conn, words.word_row(conn, wid), priority=20, now=ctx.now()) is None
    drain_images(ctx)  # the retry runs (and fails again: the providers are still empty); the handler ignores the retry key
    assert image_state(conn, wid) == "failed" and job(conn, jid)["status"] == "done" and json.loads(job(conn, jid)["result_json"])["status"] == "failed"
    frozen_clock.advance(hours=6)
    assert service.retry_if_failed(conn, words.word_row(conn, wid), priority=20, now=ctx.now()) is not None
    # a function word the gate put on the card is never retried; a word that never had a fetch job is due at once
    of = insert_word(conn, "of", pos="i:100", image_state="failed")
    assert service.retry_if_failed(conn, words.word_row(conn, of), priority=20, now=ctx.now()) is None
    pear = insert_word(conn, "pear", image_state="failed")
    assert service.retry_if_failed(conn, words.word_row(conn, pear), priority=20, now=ctx.now()) is not None
    assert json.loads(fetch_jobs(conn, pear)[0]["payload_json"]) == {"word_id": pear, "retry": True}
    # a word that is not failed is left alone
    ready = insert_word(conn, "plum")
    assert service.retry_if_failed(conn, words.word_row(conn, ready), priority=20, now=ctx.now()) is None


def test_retry_is_capped_at_three_per_thirty_days(ctx, conn, mock_http, pinned_dns, frozen_clock):
    from wd.services import words

    all_empty(mock_http)
    wid = insert_word(conn, "apple")
    add_to_bank(conn, wid)
    enqueue(conn, wid)
    drain_images(ctx)
    for n in range(3):
        frozen_clock.advance(hours=6)
        assert service.retry_if_failed(conn, words.word_row(conn, wid), priority=20, now=ctx.now()) is not None, n
        drain_images(ctx)
        assert image_state(conn, wid) == "failed"
    frozen_clock.advance(hours=6)
    assert service.auto_retries_30d(conn, wid, ctx.now()) == 3
    assert service.retry_if_failed(conn, words.word_row(conn, wid), priority=20, now=ctx.now()) is None
    assert service.retry_failed_studied(conn, ctx.now()) == []
    # a manual 换一张 / admin refetch is not an automatic retry: it still runs and is not counted
    rid = request_refresh(conn, wid, now=ctx.now())
    assert "retry" not in json.loads(job(conn, rid)["payload_json"])
    drain_images(ctx)
    assert service.auto_retries_30d(conn, wid, ctx.now()) == 3 and len(fetch_jobs(conn, wid)) == 5
    frozen_clock.advance(days=31)
    assert service.auto_retries_30d(conn, wid, ctx.now()) == 0
    assert service.retry_if_failed(conn, words.word_row(conn, wid), priority=20, now=ctx.now()) is not None


def test_nightly_retry_requeues_only_studied_failed_words_within_limit(ctx, conn, mock_http, pinned_dns, frozen_clock):
    """retry_failed_studied: failed ∧ studied (bank new/learning or an open batch) ∧ retry_due, oldest first, ≤ limit;
    dry_run lists without queueing; a live job or a fetch younger than 6 h excludes the word."""
    all_empty(mock_http)
    apple = insert_word(conn, "apple")
    uid = add_to_bank(conn, apple)
    pear = insert_word(conn, "pear")
    conn.execute("INSERT INTO user_words(user_id, word_id, state, origin) VALUES (?,?,'learning','browse')", (uid, pear))
    lonely = insert_word(conn, "plum")  # in no bank and no batch
    of = insert_word(conn, "of", pos="i:100")  # a function word in the bank
    conn.execute("INSERT INTO user_words(user_id, word_id, state, origin) VALUES (?,?,'new','browse')", (uid, of))
    known = insert_word(conn, "fig")  # mastered: not studied any more
    conn.execute("INSERT INTO user_words(user_id, word_id, state, origin) VALUES (?,?,'known','browse')", (uid, known))
    batch_word = insert_word(conn, "kiwi")  # in an open batch of today
    bid = conn.execute("INSERT INTO push_batches(user_id, local_date, timezone, trigger) VALUES (?, '2026-10-14', 'Asia/Shanghai', 'manual') RETURNING id", (uid,)).fetchone()[0]
    conn.execute("INSERT INTO push_items(batch_id, word_id, kind, position) VALUES (?, ?, 'screen', 0)", (bid, batch_word))
    for w in (apple, pear, lonely, of, known, batch_word):
        enqueue(conn, w)
    drain_images(ctx)
    assert all(image_state(conn, w) == "failed" for w in (apple, pear, lonely, of, known, batch_word))
    assert service.retry_failed_studied(conn, ctx.now()) == []  # all fetched just now
    frozen_clock.advance(hours=6)
    before = conn.execute("SELECT COUNT(*) FROM jobs WHERE type = 'fetch_image'").fetchone()[0]
    dry = service.retry_failed_studied(conn, ctx.now(), dry_run=True)
    assert dry == [apple, pear, batch_word]  # ORDER BY updated_at, id — of (function word), plum (unstudied), fig (known) excluded
    assert conn.execute("SELECT COUNT(*) FROM jobs WHERE type = 'fetch_image'").fetchone()[0] == before and image_state(conn, apple) == "failed"
    assert service.retry_failed_studied(conn, ctx.now(), limit=1) == [apple]
    j = fetch_jobs(conn, apple)[-1]
    assert j["priority"] == service.RETRY_NIGHTLY_PRIORITY == 30 and j["status"] == "queued" and json.loads(j["payload_json"]) == {"word_id": apple, "retry": True}
    assert image_state(conn, apple) == "queued"
    assert service.retry_failed_studied(conn, ctx.now(), priority=35) == [pear, batch_word]  # apple has a live job now
    assert fetch_jobs(conn, pear)[-1]["priority"] == 35
    assert service.retry_failed_studied(conn, ctx.now()) == []
    assert conn.execute("SELECT COUNT(*) FROM jobs WHERE type = 'fetch_image'").fetchone()[0] == before + 3
    drain_images(ctx)  # the retries run and fail again; a fetch 1 h old is too recent for the next sweep
    frozen_clock.advance(hours=1)
    assert service.retry_failed_studied(conn, ctx.now()) == []
    frozen_clock.advance(hours=5)
    assert service.retry_failed_studied(conn, ctx.now(), limit=0) == []
    assert service.retry_failed_studied(conn, ctx.now()) == [apple, pear, batch_word]
    assert (service.RETRY_MIN_AGE_H, service.RETRY_MAX_AUTO_30D, service.RETRY_NIGHTLY_LIMIT) == (6, 3, 50)


def test_cli_images_retry_dry_run_lists_candidates(conn, capsys):
    """`wd images-retry [--limit N] [--dry-run]` (DEPLOY §9): the nightly sweep by hand, lemmas printed."""
    apple = insert_word(conn, "apple", image_state="failed")
    uid = add_to_bank(conn, apple)
    pear = insert_word(conn, "pear", image_state="failed")
    conn.execute("INSERT INTO user_words(user_id, word_id, state, origin) VALUES (?,?,'learning','browse')", (uid, pear))
    of = insert_word(conn, "of", pos="i:100", image_state="failed")
    conn.execute("INSERT INTO user_words(user_id, word_id, state, origin) VALUES (?,?,'new','browse')", (uid, of))
    insert_word(conn, "plum", image_state="failed")  # nobody studies it
    assert cli.main(["images-retry", "--dry-run"]) == 0
    out = capsys.readouterr().out
    assert "would requeue 2 failed-image word(s)" in out and "  apple\n" in out and "  pear\n" in out and "of" not in out.replace("would", "") and "plum" not in out
    assert conn.execute("SELECT COUNT(*) FROM jobs").fetchone()[0] == 0 and image_state(conn, apple) == "failed"
    assert cli.main(["images-retry", "--limit", "1"]) == 0
    out = capsys.readouterr().out
    assert "requeued 1 failed-image word(s)" in out and "(limit 1;" in out and "  apple" in out and "pear" not in out
    j = fetch_jobs(conn, apple)[0]
    assert j["priority"] == 30 and json.loads(j["payload_json"]) == {"word_id": apple, "retry": True} and image_state(conn, apple) == "queued"
    assert cli.main(["images-retry"]) == 0
    assert "requeued 1 failed-image word(s)" in capsys.readouterr().out and len(fetch_jobs(conn, pear)) == 1  # apple is live now
    assert cli.main(["images-retry"]) == 0
    assert "requeued 0" in capsys.readouterr().out


def test_outage_sweep_requeues_failed_words_whose_only_attempt_since_found_nothing(ctx, conn, mock_http, pinned_dns, frozen_clock):
    """retry_failed_since (`wd images-retry --since ISO`): library-wide — studied or not — but only the words whose single
    fetch_image attempt at/after `since` ended `failed`; a word fetched before the window, a function word (result `skipped`),
    a word with two attempts in the window and a word with a live job are left out; the job is priority 90 without a retry
    flag, the 6 h / 30-day rules do not apply, and a swept word that fails again is not swept twice."""
    from wd.images import handler

    all_empty(mock_http)
    early = insert_word(conn, "apple")  # failed before the window
    enqueue(conn, early)
    drain_images(ctx)
    frozen_clock.advance(hours=1)
    since = ctx.now()
    lonely = insert_word(conn, "pear")  # nobody studies it: swept all the same
    of = insert_word(conn, "of", pos="i:100")  # function word: result skipped, never swept
    twice = insert_word(conn, "plum")  # two attempts in the window: already had its second chance
    busy = insert_word(conn, "fig")  # a live job
    studied = insert_word(conn, "kiwi")  # studied words are swept too, without waiting 6 h
    add_to_bank(conn, studied)
    for w in (lonely, of, twice, busy, studied):
        enqueue(conn, w, now=ctx.now())
    drain_images(ctx)
    frozen_clock.advance(minutes=1)
    enqueue(conn, twice, now=ctx.now())
    drain_images(ctx)
    enqueue(conn, busy, now=ctx.now())  # a live job (the raw helper leaves image_state alone; the live job is what excludes the word)
    assert all(image_state(conn, w) == "failed" for w in (early, lonely, of, twice, busy, studied)) and service._live_fetch_exists(conn, busy)
    assert service.retry_failed_studied(conn, ctx.now()) == []  # the nightly rules: too recent
    before = conn.execute("SELECT COUNT(*) FROM jobs WHERE type = 'fetch_image'").fetchone()[0]
    assert service.retry_failed_since(conn, ctx.now(), since=since, limit=10, dry_run=True) == [lonely, studied]
    assert conn.execute("SELECT COUNT(*) FROM jobs WHERE type = 'fetch_image'").fetchone()[0] == before and image_state(conn, lonely) == "failed"
    frozen_clock.advance(minutes=1)
    assert service.retry_failed_since(conn, ctx.now(), since=ctx.now(), limit=10) == []  # a window after every attempt
    assert service.retry_failed_since(conn, ctx.now(), since=since, limit=0) == []
    assert service.retry_failed_since(conn, ctx.now(), since=since, limit=1) == [lonely]
    j = fetch_jobs(conn, lonely)[-1]
    assert j["priority"] == service.OUTAGE_SWEEP_PRIORITY == handler.PREWARM_PRIORITY == 90 and j["status"] == "queued"
    assert json.loads(j["payload_json"]) == {"word_id": lonely} and image_state(conn, lonely) == "queued"
    assert service.retry_failed_since(conn, ctx.now(), since=since, limit=10) == [studied]  # lonely is live now
    assert service.retry_failed_since(conn, ctx.now(), since=since, limit=10) == []
    assert conn.execute("SELECT COUNT(*) FROM jobs WHERE type = 'fetch_image'").fetchone()[0] == before + 2
    drain_images(ctx)  # the swept words fail again: two attempts in the window, never a third from the sweep
    assert image_state(conn, lonely) == "failed" and service.retry_failed_since(conn, ctx.now(), since=since, limit=10) == []
    assert service.auto_retries_30d(conn, lonely, ctx.now()) == 0  # not an automatic retry
    # a window that starts before the first attempt takes `early` (one failed attempt) and nothing else; the instant is normalised (offset form)
    assert service.retry_failed_since(conn, ctx.now(), since="2026-10-14T00:00:00Z", limit=10, dry_run=True) == [early]
    assert service.retry_failed_since(conn, ctx.now(), since="2026-10-13T23:00:00+00:00", limit=10, dry_run=True) == [early]


def test_cli_images_retry_since_runs_the_outage_sweep(ctx, conn, mock_http, pinned_dns, frozen_clock, capsys):
    """`wd images-retry --since ISO [--limit N] [--dry-run]` (DEPLOY §9): the outage sweep by hand; a bad instant is exit 2."""
    all_empty(mock_http)
    since = ctx.now()
    pear = insert_word(conn, "pear")
    enqueue(conn, pear, now=ctx.now())
    drain_images(ctx)
    assert image_state(conn, pear) == "failed"
    assert cli.main(["images-retry", "--since", "yesterday"]) == 2
    assert "ISO-8601" in capsys.readouterr().out
    assert cli.main(["images-retry", "--since", since, "--dry-run"]) == 0
    out = capsys.readouterr().out
    assert f"would requeue 1 failed-image word(s) whose only fetch since {since} found no photo" in out and "  pear\n" in out and "Wikimedia only" in out
    assert len(fetch_jobs(conn, pear)) == 1 and image_state(conn, pear) == "failed"
    assert cli.main(["images-retry", "--since", since, "--limit", "100"]) == 0
    out = capsys.readouterr().out
    assert "requeued 1 failed-image word(s) whose only fetch since" in out and "(limit 100;" in out and "  pear" in out
    j = fetch_jobs(conn, pear)[-1]
    assert j["priority"] == 90 and json.loads(j["payload_json"]) == {"word_id": pear} and image_state(conn, pear) == "queued"
    assert cli.main(["images-retry", "--since", since]) == 0
    assert "requeued 0" in capsys.readouterr().out


# ------------------------------------------------------------------------------------------ svg + mix
def test_activate_svg_sanitises_and_serves_a_svg_image(conn, cfg):
    """CLAUDE_INTEGRATION §6.7: the drawing is cleaned with allow_text=False (the headword the model printed is gone — that
    is what text_free = 1 certifies), labelled with exactly one <desc id="aigc-label">, stored and activated; a call without
    model / prompt_version (this one) leaves those two columns NULL."""
    wid = insert_word(conn, "abandon")
    svg = '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 800 500" onload="x()"><script>evil()</script><rect width="800" height="500" fill="#eee"/><text x="40" y="460" font-size="40">abandon</text></svg>'
    image_id = activate_svg(conn, cfg, wid, svg, "被遗弃在雪地里的汽车", now="2026-10-14T00:00:00Z")
    row = db.row_to_dict(conn.execute("SELECT * FROM word_images WHERE id=?", (image_id,)).fetchone())
    assert row["provider"] == "claude_svg" and row["mime"] == "image/svg+xml" and row["license"] == "generated" and row["status"] == "active"
    assert row["file_path"].endswith(".svg") and row["width"] == 800 and row["height"] == 500 and row["alt_zh"] == "被遗弃在雪地里的汽车"
    assert row["text_free"] == 1 and row["prompt_version"] is None and row["model"] is None and row["eval_json"] is None
    stored = (cfg.images_dir / row["file_path"]).read_text(encoding="utf-8")
    assert "<script" not in stored and "onload" not in stored and "<text" not in stored and "abandon" not in stored
    assert stored.startswith('<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 800 500"><desc id="aigc-label">AI-generated illustration · word-Dance · claude · 2026-10-14</desc>')
    assert stored.count('id="aigc-label"') == 1 and '<rect width="800" height="500" fill="#eee"/>' in stored
    assert tuple(conn.execute("SELECT image_state, active_image_id FROM words WHERE id=?", (wid,)).fetchone()) == ("ready", image_id)
    meta = image_meta(conn, wid)
    ImageMeta.model_validate(meta)
    assert meta["kind"] == "svg" and meta["provider"] == "claude_svg" and meta["attribution"] is None and meta["url"] == f"/media/images/{row['file_path']}"
    with pytest.raises(SvgRejected):
        activate_svg(conn, cfg, wid, "<html>no</html>", None)
    assert conn.execute("SELECT COUNT(*) FROM word_images WHERE word_id=?", (wid,)).fetchone()[0] == 1  # nothing stored on rejection


def test_svg_prompt_carries_scene_example_hook_and_style(conn, cfg):
    """The v2 user prompt (CLAUDE_INTEGRATION §5.5): scene = image_alt_zh, example sentence 1, the 「联想：」 hook, and the
    Style line chosen by images.style.style_for from WD_IMAGE_KID_STAGES — neutral by default, kid for a listed stage."""
    from wd.ai import svg as svg_handler
    from wd.services import words

    wid = insert_word(conn, "cat", stage_zk=1, stage_min=2, translation="n. 猫")
    content = {
        "word": "cat", "valid": True, "meaning_zh": "n. 猫", "meaning_en": "a small furry pet", "collocations": [], "difficulty": 1,
        "examples": [{"en": 'My cat sleeps on the "warm" sofa.', "zh": "我的猫睡在温暖的沙发上。"}, {"en": "Cats like fish.", "zh": "猫喜欢鱼。"}],
        "mnemonic_zh": "联想：一只猫蜷在沙发上睡觉。记住 c-a-t。", "image_keywords": ["cat on sofa"], "image_alt_zh": "一只猫睡在沙发上。",
    }
    cid = conn.execute("INSERT INTO word_contents(word_id, version, prompt_version, model, content_json) VALUES (?,1,'content-v2','m',?) RETURNING id", (wid, json.dumps(content, ensure_ascii=False))).fetchone()[0]
    conn.execute("UPDATE words SET active_content_id=?, content_state='ready' WHERE id=?", (cid, wid))
    word = words.word_row(conn, wid)
    neutral = svg_handler.prompt_for(conn, word, cfg=cfg)
    assert neutral == (
        'Draw an illustration for the word "cat" (n. 猫). Scene: 一只猫睡在沙发上。 Example sentence: "My cat sleeps on the \'warm\' sofa." '
        "Memory hook: 一只猫蜷在沙发上睡觉 Style: " + svg_handler.STYLE_TEXT["neutral"]
    )
    kid = svg_handler.prompt_for(conn, word, cfg=replace(cfg, image_kid_stages=("zk",)))
    assert kid.endswith("Style: " + svg_handler.STYLE_TEXT["kid"]) and kid.startswith(neutral[: neutral.index(" Style: ")])
    assert "6–11-year-olds" in svg_handler.STYLE_TEXT["kid"] and "teenagers and adults" in svg_handler.STYLE_TEXT["neutral"]
    assert svg_handler.prompt_for(conn, word, cfg=replace(cfg, image_kid_stages=("xs",))) == neutral  # the word is zk, not xs
    with pytest.raises(TypeError):  # cfg is required (PLAN §5.1 C3): no silent neutral default for a caller that forgot it
        svg_handler.prompt_for(conn, word)  # type: ignore[call-arg]
    # no content: dictionary hint as meaning and scene, no example / hook segments
    bare = insert_word(conn, "pear", translation="n. 梨\n[网络] 梨子")
    assert svg_handler.prompt_for(conn, words.word_row(conn, bare), cfg=cfg) == 'Draw an illustration for the word "pear" (n. 梨). Scene: n. 梨。 Style: ' + svg_handler.STYLE_TEXT["neutral"]
    assert svg_handler.hook_from("词根 ban 禁止") == "" and svg_handler.hook_from("联想: " + "猫" * 80) == "猫" * svg_handler.HOOK_MAX
    # the cut is at the first full stop (HOOK_STOP_RE): 「。」 or an ASCII period ending a sentence — never a decimal point or
    # an abbreviation, which used to leave `3` of a giraffe and `像 U` of a flag
    assert svg_handler.hook_from("联想：3.5 米高的长颈鹿。记住 g 开头") == "3.5 米高的长颈鹿"
    assert svg_handler.hook_from("联想：像 U.S. 国旗一样飘。") == "像 U.S. 国旗一样飘"
    assert svg_handler.hook_from("联想：ban 像 banner. 旗帜被禁止。") == "ban 像 banner"
    assert svg_handler.hook_from("联想：a dot at the very end.") == "a dot at the very end"
    assert svg_handler.hook_from("联想：没有句号的联想") == "没有句号的联想"
    assert svg_handler.SVG_PROMPT_VERSION == "svg-v2"


def test_svg_activation_records_prompt_version_model_and_text_free(ctx, conn, cfg):
    """The handler end to end with the fake claude (which still prints the headword in a <text>): the stored file carries no
    <text> and one aigc-label, and the row records prompt_version = svg-v2, model = model_used, text_free = 1 (0012)."""
    from wd.ai import svg as svg_handler

    wid = insert_word(conn, "plum")
    sid = queue.enqueue(conn, "generate_svg", {"word_id": wid, "requested": True}, dedupe_key=f"svg:{wid}:req", priority=10, now=ctx.now())
    assert worker.drain(ctx, ("generate_svg",)) == 1
    result = json.loads(job(conn, sid)["result_json"])
    assert job(conn, sid)["status"] == "done" and result["cost_usd"] > 0 and "image_id" in result
    row = db.row_to_dict(conn.execute("SELECT * FROM word_images WHERE id=?", (result["image_id"],)).fetchone())
    assert (row["provider"], row["prompt_version"], row["model"], row["text_free"], row["eval_json"]) == ("claude_svg", svg_handler.SVG_PROMPT_VERSION, "claude-sonnet-fake", 1, None)
    assert row["alt_zh"] == "一幅表示 plum 的简单示意图"  # the fake read the word from the v2 prompt's `for the word "…"` fragment
    stored = (cfg.images_dir / row["file_path"]).read_text(encoding="utf-8")
    assert "<text" not in stored and "plum" not in stored and stored.count('<desc id="aigc-label">') == 1
    assert '<desc id="aigc-label">AI-generated illustration · word-Dance · claude-sonnet-fake · ' + ctx.now()[:10] + "</desc>" in stored
    assert [c["kind"] for c in ai_calls(conn)] == ["svg"] and image_state(conn, wid) == "ready" and image_meta(conn, wid)["kind"] == "svg"
    assert tuple(conn.execute("SELECT COUNT(*), SUM(text_free) FROM word_images WHERE provider = 'claude_svg'").fetchone()) == (1, 1)


def test_svg_repaired_counts_the_sanitisers_repairs_and_only_for_an_accepted_drawing(ctx, conn, cfg, monkeypatch, caplog):
    """`svg_repaired` reports sanitize_svg.count_bare_ampersands — bare `&` outside CDATA, exactly what the repair rewrites — and
    only after activate_svg accepted the drawing; a rejected SVG logs svg_rejected alone (impl-review final M-2)."""
    from wd.ai import svg as svg_handler

    drawings = iter(
        [
            '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 800 500"><title><![CDATA[a & b]]></title><desc>c & d</desc><rect width="1" height="1"/></svg>',
            "<html>a & b & c</html>",
        ]
    )
    real_call = svg_handler.common.claude_call

    def call_with_a_canned_drawing(ctx_, conn_, **kw):
        return replace(real_call(ctx_, conn_, **kw), structured={"svg": next(drawings), "alt_zh": "测试"})

    monkeypatch.setattr(svg_handler.common, "claude_call", call_with_a_canned_drawing)
    plum = insert_word(conn, "plum")
    sid = queue.enqueue(conn, "generate_svg", {"word_id": plum, "requested": True}, dedupe_key=f"svg:{plum}:req", priority=10, now=ctx.now())
    with caplog.at_level(logging.INFO):
        assert worker.drain(ctx, ("generate_svg",)) == 1
    repaired = [r for r in caplog.records if getattr(r, "event", None) == "svg_repaired"]
    assert len(repaired) == 1 and repaired[0].repairs == 1  # the `&` inside CDATA is repaired by nobody and counted by nobody
    assert job(conn, sid)["status"] == "done" and "image_id" in json.loads(job(conn, sid)["result_json"]) and image_state(conn, plum) == "ready"
    caplog.clear()
    fig = insert_word(conn, "fig")
    sid2 = queue.enqueue(conn, "generate_svg", {"word_id": fig, "requested": True}, dedupe_key=f"svg:{fig}:req", priority=10, now=ctx.now())
    with caplog.at_level(logging.INFO):
        assert worker.drain(ctx, ("generate_svg",)) == 1
    assert [r.event for r in caplog.records if getattr(r, "event", None) in ("svg_repaired", "svg_rejected")] == ["svg_rejected"]
    assert job(conn, sid2)["status"] == "done" and json.loads(job(conn, sid2)["result_json"])["rejected"].startswith("root element is not") and image_state(conn, fig) == "failed"


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
