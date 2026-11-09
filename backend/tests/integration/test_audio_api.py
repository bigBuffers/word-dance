"""GET /media/audio (API.md 76): session required, provider off → 503 {reason:off}, validation, a say clip served and cached with
its headers (ranges included — the client plays the URL in an <audio> element), the per-user miss limit, provider failures and an
unresolvable WD_AUDIO_SAY_VOICE → 503 {reason:failed}, and the log that never carries the learner's text."""

from __future__ import annotations

import logging
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
    return [c for c in lines if not c.endswith("|" + audio.PROBE_TEXT)]


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
    r = say_client.get("/media/audio", params={"text": "你好"})
    assert r.status_code == 400 and "text" in r.json()["error"]["details"]["fields"]
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
