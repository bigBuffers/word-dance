"""GET /media/audio (API.md 76): session required, provider off → 503 {reason:off}, validation, a say clip served and cached with
its headers (ranges included — the client plays the URL in an <audio> element), the per-user miss limit, provider failures and an
unresolvable WD_AUDIO_SAY_VOICE → 503 {reason:failed}, and the log that never carries the learner's text; `accent=zh-CN` (磨耳朵):
a Chinese clip by the Chinese voice, its own text rule, 503 failed / missing without a Chinese voice, and `ServerFlags.audio_zh`
(optimistic until the voice is resolved)."""

from __future__ import annotations

import logging
import hashlib
import re
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from wd import audio
from wd.routers import audio as audio_router

LISTING = "Samantha            en_US    # Hello! My name is Samantha.\nDaniel              en_GB    # Hello! My name is Daniel.\n"


@pytest.fixture
def fakes(fake_say) -> dict[str, Path]:
    return fake_say(LISTING)


@pytest.fixture
def say_client(test_env: dict[str, str], monkeypatch: pytest.MonkeyPatch, request: pytest.FixtureRequest, fakes: dict[str, Path]) -> TestClient:
    """A client whose app runs with WD_AUDIO_PROVIDER=say (the env is changed before the `settings` fixture is built)."""
    monkeypatch.setenv("WD_AUDIO_PROVIDER", "say")
    return request.getfixturevalue("client")


def calls(fakes: dict[str, Path]) -> list[str]:
    lines = fakes["calls"].read_text(encoding="utf-8").splitlines() if fakes["calls"].exists() else []
    return [c for c in lines if not c.endswith(("|" + audio.PROBE_TEXT, "|" + audio.ZH_PROBE_TEXT))]


def test_requires_a_session(client: TestClient):
    r = client.get("/media/audio", params={"text": "farmer"})
    assert r.status_code == 401 and r.json()["error"]["code"] == "unauthorized"
    assert client.get("/media/audio", params={"text": "你好"}).status_code == 401  # the session check comes before validation


def test_provider_off_answers_503_with_the_reason(client: TestClient, login):
    login("alice")
    r = client.get("/media/audio", params={"text": "farmer"})
    assert r.status_code == 503
    assert r.json()["error"] == {"code": "audio_unavailable", "message": "服务器暂时无法提供发音", "details": {"reason": "off"}}
    assert client.get("/api/auth/me").json()["server"]["audio"] is False


def test_validation_comes_before_the_provider(say_client: TestClient, login, fakes):
    login("alice")
    r = say_client.get("/media/audio", params={"text": "farmer", "accent": "fr-FR"})
    assert r.status_code == 400 and r.json()["error"]["code"] == "validation_error" and "accent" in r.json()["error"]["details"]["fields"]
    r = say_client.get("/media/audio", params={"text": "你好"})  # under an English accent (the default): Chinese belongs to accent=zh-CN
    assert r.status_code == 400 and r.json()["error"]["details"]["fields"] == {"text": "1–300 个英文字母、数字或常见标点"}
    assert say_client.get("/media/audio", params={"text": "你好", "accent": "en-GB"}).status_code == 400
    assert say_client.get("/media/audio", params={"text": "-ish"}).status_code == 400
    assert say_client.get("/media/audio", params={"text": "a" * 301}).status_code == 400  # the text rule
    assert say_client.get("/media/audio", params={"text": "a" * 401}).status_code == 400  # the query bound
    assert say_client.get("/media/audio").status_code == 400
    assert calls(fakes) == []


def test_a_clip_is_synthesised_once_and_served_with_cache_headers(say_client: TestClient, login, fakes):
    login("alice")
    assert say_client.get("/api/auth/me").json()["server"]["audio"] is True
    r = say_client.get("/media/audio", params={"text": "  farmer "})
    assert r.status_code == 200, r.text
    assert r.headers["content-type"] == "audio/mp4"
    assert r.headers["cache-control"] == "private, max-age=604800"
    assert r.headers["x-content-type-options"] == "nosniff"
    assert r.headers["accept-ranges"] == "bytes"
    assert r.content.startswith(b"Samantha:farmer") and len(r.content) >= audio.MIN_CLIP_BYTES
    assert calls(fakes) == ["Samantha|farmer"]
    again = say_client.get("/media/audio", params={"text": "farmer"})
    assert again.status_code == 200 and again.content == r.content
    assert calls(fakes) == ["Samantha|farmer"]  # normalised text → the same cached clip, no second spawn
    british = say_client.get("/media/audio", params={"text": "farmer", "accent": "en-GB"})
    assert british.status_code == 200 and calls(fakes) == ["Samantha|farmer", "Daniel|farmer"]
    sentence = say_client.get("/media/audio", params={"text": '"Hello," she said — it’s 5 o’clock…'})
    assert sentence.status_code == 200 and sentence.content.startswith(b'Samantha:"Hello," she said')


def test_an_audio_element_can_ask_for_a_range(say_client: TestClient, login, fakes):
    login("alice")
    whole = say_client.get("/media/audio", params={"text": "farmer"})
    part = say_client.get("/media/audio", params={"text": "farmer"}, headers={"Range": "bytes=0-9"})
    assert part.status_code == 206 and part.content == whole.content[:10]
    assert part.headers["content-range"] == f"bytes 0-9/{len(whole.content)}"
    assert part.headers["cache-control"] == "private, max-age=604800"
    assert calls(fakes) == ["Samantha|farmer"]


def test_the_miss_limit_counts_synthesis_not_cache_hits(say_client: TestClient, login, fakes, monkeypatch: pytest.MonkeyPatch):
    login("alice")
    monkeypatch.setattr(audio_router, "SYNTH_PER_MINUTE", 2)
    assert say_client.get("/media/audio", params={"text": "one"}).status_code == 200
    assert say_client.get("/media/audio", params={"text": "two"}).status_code == 200
    r = say_client.get("/media/audio", params={"text": "three"})
    assert r.status_code == 429 and r.json()["error"]["code"] == "rate_limited" and r.headers["retry-after"]
    assert say_client.get("/media/audio", params={"text": "one"}).status_code == 200  # cached words keep playing
    assert calls(fakes) == ["Samantha|one", "Samantha|two"]
    login("bob")  # the budget is per user
    assert say_client.get("/media/audio", params={"text": "three"}).status_code == 200


def test_a_provider_failure_is_503_failed_and_the_log_keeps_the_text_out(say_client: TestClient, login, fakes, caplog: pytest.LogCaptureFixture):
    login("alice")
    fakes["afconvert"].write_text("#!/bin/sh\necho boom >&2\nexit 2\n", encoding="utf-8")
    with caplog.at_level(logging.WARNING, logger="wd.routers.audio"):
        r = say_client.get("/media/audio", params={"text": "secretword"})
    assert r.status_code == 503 and r.json()["error"]["details"] == {"reason": "failed"}
    warnings = [rec for rec in caplog.records if rec.levelno == logging.WARNING and rec.name == "wd.routers.audio"]
    assert len(warnings) == 1 and "10-char" in warnings[0].getMessage() and "boom" in warnings[0].getMessage()
    assert "secretword" not in warnings[0].getMessage()


def test_an_override_say_cannot_resolve_is_503_failed_not_clips_in_another_voice(test_env, monkeypatch: pytest.MonkeyPatch, request: pytest.FixtureRequest, fakes):
    monkeypatch.setenv("WD_AUDIO_PROVIDER", "say")
    monkeypatch.setenv("WD_AUDIO_SAY_VOICE", "Samanta (Enhanced)")  # a typo: the real `say` would silently speak with another voice
    client: TestClient = request.getfixturevalue("client")  # built only now, with the env above (a `login` parameter would build it earlier)
    request.getfixturevalue("login")("alice")
    r = client.get("/media/audio", params={"text": "farmer"})
    assert r.status_code == 503 and r.json()["error"]["details"] == {"reason": "failed"}
    assert calls(fakes) == []


def test_me_carries_the_voice_fingerprint(say_client: TestClient, login, fakes):
    """API.md §9.1 `ServerFlags.audio_key`: provider + the resolved voice per accent — the client's clip URLs change with the voice."""
    from wd import audio
    from wd.config import Settings

    login("alice")
    audio.join_warm_up()
    before = say_client.get("/api/auth/me").json()["server"]
    assert before["audio"] is True and re.fullmatch(r"[0-9a-f]{8}", before["audio_key"])
    r = say_client.get("/media/audio", params={"text": "farmer", "accent": "en-US", "v": before["audio_key"]})  # the client's `v` is accepted and ignored
    assert r.status_code == 200
    audio.say_voice_for(Settings.from_env(), "en-GB")
    after = say_client.get("/api/auth/me").json()["server"]["audio_key"]  # both voices resolved: the settled key (§9.1: the first /me after a start may differ)
    assert after == hashlib.sha256(b"say\n\nSamantha\nDaniel\n").hexdigest()[:8] == audio.voice_key(Settings.from_env())  # this module's LISTING: no Chinese voice — a settled empty name
    assert say_client.get("/api/auth/me").json()["server"]["audio_key"] == after


def test_me_without_a_provider_has_an_empty_voice_fingerprint(client: TestClient, login):
    login("alice")
    server = client.get("/api/auth/me").json()["server"]
    assert server["audio"] is False and server["audio_key"] == ""


@pytest.fixture
def cache_client(test_env: dict[str, str], monkeypatch: pytest.MonkeyPatch, request: pytest.FixtureRequest, fakes: dict[str, Path]) -> TestClient:
    """A client whose app serves a read-only mirror of `say` clips (WD_AUDIO_PROVIDER=cache) — the Linux server of DEPLOY §4."""
    monkeypatch.setenv("WD_AUDIO_PROVIDER", "cache")
    monkeypatch.setenv("WD_AUDIO_CACHE_VOICES", "en-US=Samantha;en-GB=Daniel")  # this module's LISTING: what the fake say made them with
    return request.getfixturevalue("client")


def test_a_read_only_cache_serves_mirrored_clips_and_answers_missing_for_the_rest(cache_client: TestClient, login, fakes, test_env: dict[str, str], monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture):
    from wd import audio
    from wd.config import Settings

    login("alice")
    mac = Settings.from_env({**test_env, "WD_AUDIO_PROVIDER": "say"})
    audio.synthesize(mac, "en-US", "farmer")  # the Mac made it; rsync brought it here (the same directory in this test)
    server = cache_client.get("/api/auth/me").json()["server"]
    assert server["audio"] is True and server["audio_key"] == hashlib.sha256(b"cache\nSamantha\nDaniel").hexdigest()[:8]  # the pair of WD_AUDIO_CACHE_VOICES, not say's key
    r = cache_client.get("/media/audio", params={"text": "farmer"})
    assert r.status_code == 200 and r.headers["content-type"].startswith("audio/mp4") and r.headers["cache-control"] == "private, max-age=604800"
    monkeypatch.setattr(audio_router, "SYNTH_PER_MINUTE", 1)  # a miss costs no budget here: nothing is synthesised
    with caplog.at_level(logging.INFO, logger="wd.routers.audio"):
        for text in ("zebra", "lion"):
            r = cache_client.get("/media/audio", params={"text": text})
            assert r.status_code == 503 and r.json()["error"]["details"] == {"reason": "missing"}
    events = [r for r in caplog.records if getattr(r, "event", "") == "audio_clip_missing"]
    assert len(events) == 2 and all(r.levelno == logging.INFO and "zebra" not in r.getMessage() for r in events)
    assert not [r for r in caplog.records if getattr(r, "event", "") == "audio_unavailable"]
    assert len(calls(fakes)) == 1  # the server synthesised nothing


# ------------------------------------------------------------- Chinese clips (accent zh-CN: 磨耳朵, API.md 76 / 123)
ZH_LISTING = LISTING + "Tingting            zh_CN    # 你好！我叫婷婷。\n"


@pytest.fixture
def zh_fakes(fake_say) -> dict[str, Path]:
    """A Mac with a Chinese voice — Tingting, which on a zh-CN system is also what `say` substitutes for an unknown name."""
    return fake_say(ZH_LISTING, fallback="Tingting")


@pytest.fixture
def zh_client(test_env: dict[str, str], monkeypatch: pytest.MonkeyPatch, request: pytest.FixtureRequest, zh_fakes: dict[str, Path]) -> TestClient:
    monkeypatch.setenv("WD_AUDIO_PROVIDER", "say")
    return request.getfixturevalue("client")


def test_a_chinese_clip_is_made_once_by_the_chinese_voice(zh_client: TestClient, login, zh_fakes):
    login("alice")
    audio.join_warm_up()  # the startup warm-up resolves the Chinese voice after the two accents
    server = zh_client.get("/api/auth/me").json()["server"]
    assert server["audio"] is True and server["audio_zh"] is True
    assert server["audio_key"] == hashlib.sha256(b"say\n\nSamantha\nDaniel\nTingting").hexdigest()[:8]  # the Chinese voice is part of the fingerprint
    r = zh_client.get("/media/audio", params={"text": "  分享，共用 ", "accent": "zh-CN", "v": server["audio_key"]})
    assert r.status_code == 200, r.text
    assert r.headers["content-type"] == "audio/mp4" and r.headers["cache-control"] == "private, max-age=604800" and r.headers["accept-ranges"] == "bytes"
    assert r.content.startswith("Tingting:分享，共用".encode()) and len(r.content) >= audio.SILENT_AIFF_BYTES
    assert calls(zh_fakes) == ["Tingting|分享，共用"]
    again = zh_client.get("/media/audio", params={"text": "分享，共用", "accent": "zh-CN"})
    assert again.status_code == 200 and again.content == r.content and calls(zh_fakes) == ["Tingting|分享，共用"]  # a hit: no second spawn
    sentence = zh_client.get("/media/audio", params={"text": "Tom 说：“今晚的月亮很亮。”", "accent": "zh-CN"})  # a translation carries names and typographic quotes
    assert sentence.status_code == 200 and sentence.content.startswith("Tingting:Tom 说：".encode())
    # the accents keep their voices and their rule
    assert zh_client.get("/media/audio", params={"text": "share"}).content.startswith(b"Samantha:share")
    assert zh_client.get("/media/audio", params={"text": "分享，共用", "accent": "en-GB"}).status_code == 400


def test_chinese_text_follows_its_own_rule(zh_client: TestClient, login, zh_fakes):
    login("alice")
    for text in ("share", "GDP 5%", "，。", "-好", "好" * 301, "你好<b>", "日本語です"):
        r = zh_client.get("/media/audio", params={"text": text, "accent": "zh-CN"})
        assert r.status_code == 400 and r.json()["error"]["code"] == "validation_error", text
        assert r.json()["error"]["details"]["fields"] == {"text": "1–300 个字符，需含汉字"}, text
    r = zh_client.get("/media/audio", params={"text": "月亮", "accent": "zh-TW"})
    assert r.status_code == 400 and r.json()["error"]["details"]["fields"] == {"accent": "只支持 en-US、en-GB 或 zh-CN"}
    assert calls(zh_fakes) == []


def test_chinese_misses_count_against_the_same_budget(zh_client: TestClient, login, zh_fakes, monkeypatch: pytest.MonkeyPatch):
    login("alice")
    monkeypatch.setattr(audio_router, "SYNTH_PER_MINUTE", 2)
    assert zh_client.get("/media/audio", params={"text": "月亮", "accent": "zh-CN"}).status_code == 200
    assert zh_client.get("/media/audio", params={"text": "moon"}).status_code == 200
    r = zh_client.get("/media/audio", params={"text": "太阳", "accent": "zh-CN"})
    assert r.status_code == 429 and r.json()["error"]["code"] == "rate_limited"
    assert zh_client.get("/media/audio", params={"text": "月亮", "accent": "zh-CN"}).status_code == 200  # hits stay free
    assert calls(zh_fakes) == ["Tingting|月亮", "Samantha|moon"]


def test_without_a_chinese_voice_chinese_is_503_failed_and_spends_no_budget(say_client: TestClient, login, fakes, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture):
    """This module's LISTING: a Mac with English voices only — a supported state, the client is told by `audio_zh`."""
    login("alice")
    audio.join_warm_up()
    server = say_client.get("/api/auth/me").json()["server"]
    assert server["audio"] is True and server["audio_zh"] is False
    monkeypatch.setattr(audio_router, "SYNTH_PER_MINUTE", 1)
    with caplog.at_level(logging.WARNING, logger="wd.routers.audio"):
        for _ in range(3):
            r = say_client.get("/media/audio", params={"text": "月亮", "accent": "zh-CN"})
            assert r.status_code == 503 and r.json()["error"]["details"] == {"reason": "failed"}
    warnings = [rec.getMessage() for rec in caplog.records if getattr(rec, "event", "") == "audio_unavailable"]
    assert len(warnings) == 3 and all("no Chinese voice" in w and "2-char zh-CN text" in w and "月亮" not in w for w in warnings)
    assert say_client.get("/media/audio", params={"text": "farmer"}).status_code == 200  # the minute's one miss was not spent on the refusals
    assert calls(fakes) == ["Samantha|farmer"]
    assert say_client.get("/api/auth/me").json()["server"]["audio_key"] == server["audio_key"]  # settled: the refusals change nothing


def test_audio_zh_is_optimistic_before_the_chinese_voice_is_resolved(zh_client: TestClient, login, zh_fakes):
    """The 2–3 s after a restart: a page that loads now keeps its `/me` for the session, and on the tablet (no voice of its own) a
    false flag was a session without Chinese. Unresolved reads true; the first Chinese clip resolves the voice in its own request,
    exactly as the first English one does."""
    login("alice")
    audio.reset_voice_cache()  # joins the startup warm-up and forgets what it found: the process as it is before the warm-up got anywhere
    asked = zh_fakes["calls"].read_text(encoding="utf-8")  # that warm-up's probes
    server = zh_client.get("/api/auth/me").json()["server"]
    assert server["audio"] is True and server["audio_zh"] is True
    assert zh_fakes["calls"].read_text(encoding="utf-8") == asked  # the flag asked `say` nothing — no probe, no clip
    r = zh_client.get("/media/audio", params={"text": "月亮", "accent": "zh-CN", "v": server["audio_key"]})
    assert r.status_code == 200 and r.content.startswith("Tingting:月亮".encode()) and calls(zh_fakes) == ["Tingting|月亮"]
    assert zh_client.get("/api/auth/me").json()["server"]["audio_zh"] is True


def test_an_optimistic_audio_zh_without_a_chinese_voice_is_one_503_failed_and_then_false(say_client: TestClient, login, fakes):
    """This module's LISTING (English voices only) in the same window: the flag cannot know yet, the clip request finds out — 503
    `failed`, which the client takes as "no Chinese from the server this session" (FRONTEND §6.4) — and the next `/me` is settled."""
    login("alice")
    audio.reset_voice_cache()
    assert say_client.get("/api/auth/me").json()["server"]["audio_zh"] is True
    r = say_client.get("/media/audio", params={"text": "月亮", "accent": "zh-CN"})
    assert r.status_code == 503 and r.json()["error"]["details"] == {"reason": "failed"}
    assert say_client.get("/api/auth/me").json()["server"]["audio_zh"] is False
    assert calls(fakes) == []


def test_a_read_only_cache_has_no_chinese_clips(cache_client: TestClient, login, fakes, caplog: pytest.LogCaptureFixture):
    login("alice")
    assert cache_client.get("/api/auth/me").json()["server"]["audio_zh"] is False
    with caplog.at_level(logging.INFO, logger="wd.routers.audio"):
        r = cache_client.get("/media/audio", params={"text": "月亮", "accent": "zh-CN"})
    assert r.status_code == 503 and r.json()["error"]["details"] == {"reason": "missing"}  # the client speaks this one itself, like any unsynced text
    assert [getattr(rec, "event", "") for rec in caplog.records if rec.name == "wd.routers.audio"] == ["audio_clip_missing"]
    assert cache_client.get("/media/audio", params={"text": "farmer", "accent": "zh-CN"}).status_code == 400  # the text rule still comes first
    assert calls(fakes) == []
