"""wd.audio (API.md 76): the text rule, voice choice from a localised `say -v ?` listing (tiers, the resolution probe), the
content-addressed cache and its size cap, the `say` and `youdao` providers against fakes, the synthesis slots and waiters, the
allow-listed child environment, the `auto` provider resolution, the startup warm-up, the periodic re-count of the cache and
the `wd audio-prewarm` / `wd audio-voices` commands (DEPLOY §9)."""

from __future__ import annotations

import hashlib
import json
import logging
import os
import re
import sqlite3
import stat
import threading
import time
from pathlib import Path

import httpx
import pytest

from wd import __version__, audio
from wd.config import ConfigError, Settings, ensure_dirs

LISTING = """Albert              en_US    # Hello! My name is Albert.
Bad News            en_US    # Hello! My name is Bad News.
Daniel              en_GB    # Hello! My name is Daniel.
Eddy (英语（美国）)       en_US    # Hello! My name is Eddy.
Samantha            en_US    # Hello! My name is Samantha.
Samantha (增强)      en_US    # Hello! My name is Samantha.
Stephanie (Premium) en_GB    # Hello! My name is Stephanie.
Ting-Ting           zh_CN    # 您好，我叫Ting-Ting。
Ava (Enhanced)      en_US    # Hello! My name is Ava.
Ava (Premium)       en_US    # Hello! My name is Ava.
Mónica              es_ES    # Hola, me llamo Mónica.
"""


@pytest.fixture
def fakes(fake_say) -> dict[str, Path]:
    return fake_say(LISTING)


def make_settings(test_env: dict[str, str], **overrides: str) -> Settings:
    cfg = Settings.from_env({**test_env, **overrides})
    ensure_dirs(cfg)
    return cfg


def calls(fakes: dict[str, Path]) -> list[str]:
    """`voice|text` of every synthesis the fake `say` ran (the voice probes excluded)."""
    lines = fakes["calls"].read_text(encoding="utf-8").splitlines() if fakes["calls"].exists() else []
    return [c for c in lines if not c.endswith("|" + audio.PROBE_TEXT)]


def probes(fakes: dict[str, Path]) -> list[str]:
    lines = fakes["calls"].read_text(encoding="utf-8").splitlines() if fakes["calls"].exists() else []
    return [c.split("|", 1)[0] for c in lines if c.endswith("|" + audio.PROBE_TEXT)]


# ------------------------------------------------------------------------------------------- text rule
@pytest.mark.parametrize(
    "raw, expected",
    [
        ("farmer", "farmer"),
        ("  farmer ", "farmer"),
        ("The farmer\tgrows   rice.", "The farmer grows rice."),
        ("café", "café"),
        ("rock 'n' roll", "rock 'n' roll"),
        ("it’s", "it’s"),
        ("and/or", "and/or"),
        ("Where are you going? (Hurry up!)", "Where are you going? (Hurry up!)"),
        ('"Hello," she said.', '"Hello," she said.'),  # dialogue-form example sentences open with a quote
        ("“Hello,” she said.", "“Hello,” she said."),
        ("‘Tis the season", "‘Tis the season"),
        ("(informal) hi", "(informal) hi"),
        ("Wait — what?", "Wait — what?"),
        ("pages 10–12", "pages 10–12"),
        ("Well… maybe.", "Well… maybe."),
        ("It costs $5 & 20%.", "It costs $5 & 20%."),
        ("e-mail me @ home", "e-mail me @ home"),
        ("A" * 300, "A" * 300),
    ],
)
def test_normalize_text_accepts_words_phrases_and_sentences(raw: str, expected: str):
    assert audio.normalize_text(raw) == expected


@pytest.mark.parametrize("raw", ["", "   ", "你好", "-ish", "a" * 301, "hello<script>", "x\u0000y", "naïve\n中", "a=b", "50€", "x`y", "a|b", "[x]", "{x}", "a\\b", "#1", "a*b", "a+b", "~x", "a^b"])
def test_normalize_text_rejects_everything_the_providers_must_not_see(raw: str):
    assert audio.normalize_text(raw) is None


# ---------------------------------------------------------------------------------------------- voices
def test_parse_voices_keeps_the_full_name_and_the_base_name_and_survives_the_one_space_rows():
    voices = {v.name: v for v in audio.parse_voices(LISTING)}
    assert voices["Bad News"].base == "Bad News" and voices["Bad News"].lang == "en_US"
    assert voices["Eddy (英语（美国）)"].base == "Eddy" and voices["Eddy (英语（美国）)"].qualified
    assert voices["Samantha (增强)"].base == "Samantha" and voices["Samantha (增强)"].qualified
    assert not voices["Samantha"].qualified
    assert voices["Stephanie (Premium)"].lang == "en_GB"  # 19 characters: `say` pads names to 20 columns, so one space precedes the tag
    assert voices["Mónica"].lang == "es_ES"
    assert len(voices) == 11


def test_voice_tiers_rank_premium_over_enhanced_over_compact():
    voices = {v.name: v for v in audio.parse_voices(LISTING)}
    assert voices["Ava (Premium)"].tier == 2 and voices["Stephanie (Premium)"].tier == 2
    assert voices["Ava (Enhanced)"].tier == 1 and voices["Samantha (增强)"].tier == 1
    assert voices["Samantha"].tier == 0
    assert audio.Voice("Ava (高级)", "Ava", "en_US").tier == 2  # the zh-CN label of Premium


def test_choose_voice_prefers_the_listed_order_and_the_best_tier():
    voices = audio.parse_voices(LISTING)
    assert audio.choose_voice(voices, "en-US") == "Ava (Premium)"  # not the alphabetically earlier "Ava (Enhanced)"
    without_ava = [v for v in voices if v.base != "Ava"]
    assert audio.choose_voice(without_ava, "en-US") == "Samantha (增强)"  # the enhanced Samantha over the compact one
    assert audio.choose_voice([v for v in without_ava if not v.qualified], "en-US") == "Samantha"
    assert audio.choose_voice(voices, "en-GB") == "Stephanie (Premium)"
    assert audio.choose_voice([v for v in voices if v.base != "Stephanie"], "en-GB") == "Daniel"


def test_choose_voice_skips_names_the_probe_rejects():
    voices = audio.parse_voices(LISTING)
    assert audio.choose_voice(voices, "en-US", resolves=lambda n: n != "Ava (Premium)") == "Ava (Enhanced)"
    assert audio.choose_voice(voices, "en-US", resolves=lambda n: not n.startswith("Ava")) == "Samantha (增强)"
    assert audio.choose_voice(voices, "en-US", resolves=lambda n: False) is None


def test_choose_voice_never_picks_a_novelty_or_eloquence_voice_and_falls_back_across_accents():
    voices = audio.parse_voices(LISTING)
    only_us = [v for v in voices if v.lang != "en_GB"]
    assert audio.choose_voice(only_us, "en-GB") == "Ava (Premium)"  # a US voice beats silence for en-GB
    jokes = [v for v in voices if v.base in ("Albert", "Bad News", "Eddy", "Ting-Ting")]
    assert audio.choose_voice(jokes, "en-US") is None
    assert audio.choose_voice([], "en-US") is None


def test_say_voices_are_read_once_and_a_failure_is_retried_only_after_a_while(fakes: dict[str, Path], monkeypatch: pytest.MonkeyPatch):
    assert [v.name for v in audio.say_voices()][:2] == ["Albert", "Bad News"]
    fakes["listing"].write_text("Nobody              en_US    # changed\n", encoding="utf-8")
    assert audio.say_voices()[0].name == "Albert"  # cached
    audio.reset_voice_cache()
    monkeypatch.setattr(audio, "SAY_BIN", str(fakes["say"].with_name("missing")))
    assert audio.say_voices() == []
    monkeypatch.setattr(audio, "SAY_BIN", str(fakes["say"]))
    assert audio.say_voices() == []  # the failure holds for VOICES_RETRY_S: no spawn per request
    monkeypatch.setattr(audio, "VOICES_RETRY_S", 0.0)
    assert audio.say_voices()[0].name == "Nobody"  # retried once the window passed


def test_say_resolves_compares_with_the_unknown_name_fallback_and_probes_once(test_env: dict[str, str], fakes: dict[str, Path]):
    cfg = make_settings(test_env, WD_AUDIO_PROVIDER="say")
    assert audio.say_resolves(cfg, "Samantha") is True
    assert audio.say_resolves(cfg, "Zoe (Premium)") is False  # the real `say` exits 0 and speaks with another voice
    assert audio.say_resolves(cfg, "Samantha") is True and audio.say_resolves(cfg, "Zoe (Premium)") is False
    assert sorted(probes(fakes)) == sorted(["Samantha", audio.UNKNOWN_VOICE, "Zoe (Premium)"])  # each name once
    assert not list(cfg.tmp_dir.glob("audio-probe-*"))


def test_say_voice_for_resolves_once_per_accent_and_refuses_an_override_say_does_not_know(test_env: dict[str, str], fakes: dict[str, Path]):
    cfg = make_settings(test_env, WD_AUDIO_PROVIDER="say")
    assert audio.say_voice_for(cfg, "en-US") == "Ava (Premium)"
    assert audio.say_voice_for(cfg, "en-GB") == "Stephanie (Premium)"
    assert audio.say_voice_for(cfg, "en-US") == "Ava (Premium)"
    assert sorted(probes(fakes)) == sorted(["Ava (Premium)", audio.UNKNOWN_VOICE, "Stephanie (Premium)"])
    override = make_settings(test_env, WD_AUDIO_PROVIDER="say", WD_AUDIO_SAY_VOICE="Samantha")
    assert audio.say_voice_for(override, "en-GB") == "Samantha"
    typo = make_settings(test_env, WD_AUDIO_PROVIDER="say", WD_AUDIO_SAY_VOICE="Samanta (Enhanced)")
    with pytest.raises(audio.AudioError) as e:
        audio.say_voice_for(typo, "en-US")
    assert e.value.reason == "failed" and "WD_AUDIO_SAY_VOICE" in e.value.detail and "Samanta (Enhanced)" in e.value.detail
    with pytest.raises(audio.AudioError):  # lookup() raises the same error, so the router answers 503 failed
        audio.lookup(typo, "en-US", "farmer")


# ----------------------------------------------------------------------------------------------- cache
def test_locate_is_content_addressed_by_provider_voice_accent_and_text(test_env: dict[str, str], fakes: dict[str, Path]):
    cfg = make_settings(test_env, WD_AUDIO_PROVIDER="say")
    clip, provider, voice = audio.locate(cfg, "en-US", "farmer")
    assert provider == "say" and voice == "Ava (Premium)"
    assert clip.media_type == "audio/mp4" and clip.path.suffix == ".m4a"
    assert clip.path.parent.parent == cfg.audio_dir and clip.path.parent.name == clip.path.stem[:2]
    assert audio.locate(cfg, "en-US", "farmer")[0] == clip
    assert audio.locate(cfg, "en-GB", "farmer")[0].path != clip.path
    assert audio.locate(cfg, "en-US", "Farmer")[0].path != clip.path
    other = make_settings(test_env, WD_AUDIO_PROVIDER="say", WD_AUDIO_SAY_VOICE="Samantha")
    assert audio.locate(other, "en-US", "farmer")[2] == "Samantha" and audio.locate(other, "en-US", "farmer")[0].path != clip.path
    youdao = make_settings(test_env, WD_AUDIO_PROVIDER="youdao")
    yclip, yprovider, yvoice = audio.locate(youdao, "en-US", "farmer")
    assert (yprovider, yvoice, yclip.media_type, yclip.path.suffix) == ("youdao", "", "audio/mpeg", ".mp3")


def test_locate_without_a_provider_or_a_voice(test_env: dict[str, str], fakes: dict[str, Path]):
    off = make_settings(test_env, WD_AUDIO_PROVIDER="off")
    with pytest.raises(audio.AudioError) as e:
        audio.locate(off, "en-US", "farmer")
    assert e.value.reason == "off"
    fakes["listing"].write_text("Ting-Ting           zh_CN    # 您好\n", encoding="utf-8")
    audio.reset_voice_cache()
    with pytest.raises(audio.AudioError) as e:
        audio.lookup(make_settings(test_env, WD_AUDIO_PROVIDER="say"), "en-US", "farmer")
    assert e.value.reason == "failed" and "WD_AUDIO_SAY_VOICE" in e.value.detail and "restart" in e.value.detail


def test_lookup_touches_a_served_clip_and_prune_removes_the_least_recently_played(test_env: dict[str, str], fakes: dict[str, Path]):
    cfg = make_settings(test_env, WD_AUDIO_PROVIDER="say")
    clips = [audio.synthesize(cfg, "en-US", word) for word in ("one", "two", "three")]
    for age, clip in zip((300, 200, 100), clips):
        os.utime(clip.path, (time.time() - age, time.time() - age))
    sizes = [c.path.stat().st_size for c in clips]
    assert audio.cache_bytes(cfg) == sum(sizes)
    assert audio.lookup(cfg, "en-US", "one") == clips[0]  # played again → newest
    assert clips[0].path.stat().st_mtime > clips[2].path.stat().st_mtime
    assert audio.prune(cfg, sizes[0] + sizes[2]) == 1
    assert clips[0].path.is_file() and not clips[1].path.is_file() and clips[2].path.is_file()
    assert audio.cache_bytes(cfg) == sizes[0] + sizes[2]
    assert audio.prune(cfg, sizes[0] + sizes[2]) == 0


def test_synthesis_beyond_the_cache_cap_prunes_to_ninety_percent(test_env: dict[str, str], fakes: dict[str, Path], monkeypatch: pytest.MonkeyPatch):
    cfg = make_settings(test_env, WD_AUDIO_PROVIDER="say", WD_AUDIO_CACHE_MB="16")
    probe = audio.synthesize(cfg, "en-US", "zero")
    size = probe.path.stat().st_size
    monkeypatch.setattr(audio, "MB", (3 * size) // 16 + 1)  # the 16 "MB" cap now holds three clips, not four
    for i, word in enumerate(("one", "two", "three")):
        clip = audio.synthesize(cfg, "en-US", word)
        os.utime(clip.path, (time.time() + i, time.time() + i))  # strictly increasing: zero < one < two < three
    kept = list(cfg.audio_dir.rglob("*.m4a"))
    assert len(kept) == 2 and not probe.path.is_file()  # the fourth clip tipped the cap: pruned to 90 % of it = two clips, oldest first
    assert {p.name for p in kept} == {audio.locate(cfg, "en-US", w)[0].path.name for w in ("two", "three")}
    assert audio.cache_bytes(cfg) == sum(p.stat().st_size for p in kept)


# ---------------------------------------------------------------------------------------- say provider
def test_say_synthesises_once_through_stdin_and_caches_the_clip(test_env: dict[str, str], fakes: dict[str, Path]):
    cfg = make_settings(test_env, WD_AUDIO_PROVIDER="say")
    assert audio.lookup(cfg, "en-US", "farmer") is None
    clip = audio.synthesize(cfg, "en-US", "farmer")
    assert clip.path.is_file() and clip.path.stat().st_size >= audio.MIN_CLIP_BYTES
    assert stat.S_IMODE(clip.path.stat().st_mode) == 0o600
    assert clip.path.read_bytes().startswith(b"Ava (Premium):farmer")  # the resolved voice; the text travelled on stdin
    assert calls(fakes) == ["Ava (Premium)|farmer"]
    assert audio.synthesize(cfg, "en-US", "farmer") == clip and audio.lookup(cfg, "en-US", "farmer") == clip
    assert calls(fakes) == ["Ava (Premium)|farmer"]  # a cache hit spawns nothing
    assert audio.synthesize(cfg, "en-GB", "farmer").path != clip.path
    assert calls(fakes) == ["Ava (Premium)|farmer", "Stephanie (Premium)|farmer"]
    assert [p.name for p in clip.path.parent.iterdir() if p.name.endswith((".tmp", ".aiff"))] == []


def test_say_failures_become_audio_errors_and_leave_no_debris(test_env: dict[str, str], fakes: dict[str, Path], monkeypatch: pytest.MonkeyPatch):
    cfg = make_settings(test_env, WD_AUDIO_PROVIDER="say")
    fakes["afconvert"].write_text("#!/bin/sh\necho 'Error: ExtAudioFileCreateWithURL failed' >&2\nexit 1\n", encoding="utf-8")
    with pytest.raises(audio.AudioError) as e:
        audio.synthesize(cfg, "en-US", "farmer")
    assert e.value.reason == "failed" and "afconvert" in e.value.detail and "ExtAudioFile" in e.value.detail
    assert audio.lookup(cfg, "en-US", "farmer") is None
    assert not list(cfg.audio_dir.rglob("*.tmp")) and not list(cfg.audio_dir.rglob("*.aiff"))
    # a missing binary and a short clip are failures too, never raw OSErrors; the detail never carries the text
    monkeypatch.setattr(audio, "AFCONVERT_BIN", str(fakes["afconvert"].with_name("nope")))
    with pytest.raises(audio.AudioError) as e:
        audio.synthesize(cfg, "en-US", "farmer")
    assert e.value.reason == "failed"
    fakes["afconvert"].write_text('#!/bin/sh\nfor last; do :; done\nprintf x > "$last"\n', encoding="utf-8")
    monkeypatch.setattr(audio, "AFCONVERT_BIN", str(fakes["afconvert"]))
    with pytest.raises(audio.AudioError) as e:
        audio.synthesize(cfg, "en-US", "farmer")
    assert e.value.reason == "failed" and "no audio" in e.value.detail and "farmer" not in e.value.detail


def test_a_hanging_say_is_killed_and_reported(test_env: dict[str, str], fakes: dict[str, Path], monkeypatch: pytest.MonkeyPatch):
    cfg = make_settings(test_env, WD_AUDIO_PROVIDER="say")
    audio.say_voice_for(cfg, "en-US")  # resolve the voice before the binary starts hanging
    fakes["say"].write_text("#!/bin/sh\nsleep 30\n", encoding="utf-8")
    monkeypatch.setattr(audio, "SAY_TIMEOUT_S", 0.3)
    started = time.monotonic()
    with pytest.raises(audio.AudioError) as e:
        audio.synthesize(cfg, "en-US", "farmer")
    assert e.value.reason == "failed" and "timed out" in e.value.detail
    assert time.monotonic() - started < 5
    assert not list(cfg.audio_dir.rglob("*.tmp")) and not list(cfg.audio_dir.rglob("*.aiff"))


def test_the_child_environment_is_an_allow_list(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("WD_SECRET_KEY", "hunter2")
    monkeypatch.setenv("HOME", "/Users/someone")
    env = audio._child_env()
    assert "WD_SECRET_KEY" not in env and env["HOME"] == "/Users/someone" and env["PATH"] == "/usr/bin:/bin"
    assert set(env) <= {"PATH", "LANG", "HOME", "TMPDIR"}


def test_no_slot_in_time_is_busy_not_a_queue(test_env: dict[str, str], fakes: dict[str, Path], monkeypatch: pytest.MonkeyPatch):
    cfg = make_settings(test_env, WD_AUDIO_PROVIDER="say")
    taken = threading.BoundedSemaphore(1)
    taken.acquire()
    monkeypatch.setattr(audio, "_slots", taken)
    monkeypatch.setattr(audio, "SLOT_WAIT_S", 0.05)
    with pytest.raises(audio.AudioError) as e:
        audio.synthesize(cfg, "en-US", "farmer")
    assert e.value.reason == "busy"
    assert calls(fakes) == []
    taken.release()
    assert audio.synthesize(cfg, "en-US", "farmer").path.is_file()


def test_too_many_waiters_is_busy_at_once(test_env: dict[str, str], fakes: dict[str, Path], monkeypatch: pytest.MonkeyPatch):
    cfg = make_settings(test_env, WD_AUDIO_PROVIDER="say")
    full = threading.BoundedSemaphore(1)
    full.acquire()
    monkeypatch.setattr(audio, "_waiters", full)
    monkeypatch.setattr(audio, "SLOT_WAIT_S", 5.0)
    started = time.monotonic()
    with pytest.raises(audio.AudioError) as e:
        audio.synthesize(cfg, "en-US", "farmer")
    assert e.value.reason == "busy" and "wait" in e.value.detail
    assert time.monotonic() - started < 1  # no 5 s wait on a threadpool thread
    full.release()
    assert audio.synthesize(cfg, "en-US", "farmer").path.is_file()


# ------------------------------------------------------------------------------------- youdao provider
def youdao_transport(responder):
    def handler(request: httpx.Request) -> httpx.Response:
        return responder(request)

    return httpx.MockTransport(handler)


def patch_youdao(monkeypatch: pytest.MonkeyPatch, responder) -> list[httpx.Request]:
    seen: list[httpx.Request] = []

    def responding(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return responder(request)

    monkeypatch.setattr(audio, "_youdao_client", lambda cfg: httpx.Client(transport=youdao_transport(responding), timeout=1.0))
    return seen


def test_youdao_fetches_the_accent_type_and_caches_an_mp3(test_env: dict[str, str], monkeypatch: pytest.MonkeyPatch):
    cfg = make_settings(test_env, WD_AUDIO_PROVIDER="youdao")
    seen = patch_youdao(monkeypatch, lambda r: httpx.Response(200, content=b"\xff\xfb" + b"\x00" * 1000, headers={"content-type": "audio/mpeg"}))
    clip = audio.synthesize(cfg, "en-GB", "The farmer’s “best” rice — 10%.")
    assert clip.media_type == "audio/mpeg" and clip.path.suffix == ".mp3" and clip.path.stat().st_size == 1002
    assert len(seen) == 1
    assert seen[0].url.host == "dict.youdao.com" and seen[0].url.path == "/dictvoice"
    assert dict(seen[0].url.params) == {"audio": "The farmer’s “best” rice — 10%.", "type": "1"}
    assert "audio=The+farmer%E2%80%99s+%E2%80%9Cbest%E2%80%9D+rice+%E2%80%94+10%25." in str(seen[0].url)  # the wire encoding
    audio.synthesize(cfg, "en-GB", "The farmer’s “best” rice — 10%.")
    assert len(seen) == 1
    audio.synthesize(cfg, "en-US", "The farmer’s “best” rice — 10%.")
    assert dict(seen[1].url.params)["type"] == "2"


def test_youdao_client_is_anonymous_and_ignores_proxy_variables(test_env: dict[str, str], monkeypatch: pytest.MonkeyPatch):
    cfg = make_settings(test_env, WD_AUDIO_PROVIDER="youdao", WD_PUBLIC_URL="https://words.example.com", WD_CONTACT_EMAIL="owner@example.com")
    monkeypatch.setenv("HTTPS_PROXY", "http://127.0.0.1:9")
    with audio._youdao_client(cfg) as client:
        ua = client.headers["user-agent"]
        assert ua == f"word-Dance/{__version__}" and "example.com" not in ua
        assert client.trust_env is False
        assert client.timeout.read == audio.YOUDAO_TIMEOUT_S


@pytest.mark.parametrize(
    "response",
    [
        lambda r: httpx.Response(200, content=b"<html>blocked</html>" * 50, headers={"content-type": "text/html"}),
        lambda r: httpx.Response(404, content=b"", headers={"content-type": "audio/mpeg"}),
        lambda r: httpx.Response(200, content=b"\xff\xfb", headers={"content-type": "audio/mpeg"}),
        lambda r: httpx.Response(200, content=b"\xff" * (audio.YOUDAO_MAX_BYTES + 1), headers={"content-type": "audio/mpeg"}),
        lambda r: (_ for _ in ()).throw(httpx.ConnectError("boom", request=r)),
    ],
)
def test_youdao_answers_that_are_not_audio_fail_cleanly(test_env: dict[str, str], monkeypatch: pytest.MonkeyPatch, response):
    cfg = make_settings(test_env, WD_AUDIO_PROVIDER="youdao")
    patch_youdao(monkeypatch, response)
    with pytest.raises(audio.AudioError) as e:
        audio.synthesize(cfg, "en-US", "farmer")
    assert e.value.reason == "failed"
    assert audio.lookup(cfg, "en-US", "farmer") is None
    assert not list(cfg.audio_dir.rglob("*.tmp"))


# --------------------------------------------------------------------------------------------- config
def test_auto_provider_follows_the_say_binary(test_env: dict[str, str], tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    from wd import config

    present = tmp_path / "say"
    present.write_text("#!/bin/sh\n", encoding="utf-8")
    monkeypatch.setattr(config, "SAY_BIN", str(present))
    cfg = Settings.from_env({**test_env, "WD_AUDIO_PROVIDER": ""})
    assert cfg.audio_provider == "auto" and cfg.audio_provider_effective == "say" and audio.provider_for(cfg) == "say"
    monkeypatch.setattr(config, "SAY_BIN", str(tmp_path / "absent"))
    assert cfg.audio_provider_effective == "off"
    assert Settings.from_env({**test_env, "WD_AUDIO_PROVIDER": "say"}).audio_provider_effective == "say"  # explicit wins
    assert Settings.from_env({**test_env, "WD_AUDIO_PROVIDER": "youdao"}).audio_provider_effective == "youdao"
    assert Settings.from_env({**test_env, "WD_AUDIO_SAY_VOICE": " Ava (Premium) "}).audio_say_voice == "Ava (Premium)"
    with pytest.raises(ConfigError, match="WD_AUDIO_PROVIDER"):
        Settings.from_env({**test_env, "WD_AUDIO_PROVIDER": "espeak"})
    assert cfg.audio_dir == cfg.data_dir / "audio" and cfg.audio_dir in cfg.runtime_dirs()


def test_cache_cap_is_an_integer_of_at_least_16_mb(test_env: dict[str, str]):
    assert Settings.from_env(test_env).audio_cache_mb == 256
    assert Settings.from_env({**test_env, "WD_AUDIO_CACHE_MB": "1024"}).audio_cache_mb == 1024
    with pytest.raises(ConfigError, match="WD_AUDIO_CACHE_MB"):
        Settings.from_env({**test_env, "WD_AUDIO_CACHE_MB": "8"})
    with pytest.raises(ConfigError, match="WD_AUDIO_CACHE_MB"):
        Settings.from_env({**test_env, "WD_AUDIO_CACHE_MB": "lots"})


def test_reporting_lists_the_three_variables(test_env: dict[str, str]):
    keys = {e["key"]: e for e in Settings.from_env({**test_env, "WD_AUDIO_SAY_VOICE": "Samantha"}).entries()}
    assert keys["WD_AUDIO_PROVIDER"]["value"] == "off" and keys["WD_AUDIO_PROVIDER"]["source"] == "env"
    assert keys["WD_AUDIO_SAY_VOICE"]["value"] == "Samantha"
    assert keys["WD_AUDIO_CACHE_MB"] == {"key": "WD_AUDIO_CACHE_MB", "value": "256", "source": "default"}
    assert os.environ.get("WD_AUDIO_PROVIDER") == "off"  # the test environment opts out so `auto` never picks the Mac's say


# --------------------------------------------------------------------------------- warm-up, re-count, prewarm
def test_warm_up_resolves_both_accents_on_a_thread_before_the_first_request(test_env: dict[str, str], fakes: dict[str, Path], caplog: pytest.LogCaptureFixture):
    cfg = make_settings(test_env, WD_AUDIO_PROVIDER="say")
    with caplog.at_level(logging.INFO, logger="wd.audio"):
        thread = audio.warm_up_async(cfg)
        assert thread is not None and thread.daemon
        thread.join(timeout=10)
        assert not thread.is_alive()
    assert sorted(r.getMessage() for r in caplog.records if getattr(r, "event", "") == "audio_voice") == ["say voice for en-GB: Stephanie (Premium)", "say voice for en-US: Ava (Premium)"]
    probed = len(probes(fakes))
    assert probed >= 2
    assert audio.say_voice_for(cfg, "en-US") == "Ava (Premium)" and audio.say_voice_for(cfg, "en-GB") == "Stephanie (Premium)"
    assert len(probes(fakes)) == probed, "the request path paid no probe after the warm-up"
    assert audio.warm_up_async(make_settings(test_env, WD_AUDIO_PROVIDER="off")) is None


def test_warm_up_logs_a_missing_voice_once_and_never_raises(test_env: dict[str, str], fake_say, caplog: pytest.LogCaptureFixture):
    fake_say("Ting-Ting           zh_CN    # 您好，我叫Ting-Ting。\n")
    cfg = make_settings(test_env, WD_AUDIO_PROVIDER="say")
    with caplog.at_level(logging.WARNING, logger="wd.audio"):
        audio.warm_up(cfg)
    assert [getattr(r, "event", "") for r in caplog.records] == ["audio_voice_failed"]
    assert "no English voice" in caplog.records[0].getMessage()


def test_the_running_total_is_recounted_from_disk_after_the_scan_interval(test_env: dict[str, str], fakes: dict[str, Path], monkeypatch: pytest.MonkeyPatch):
    cfg = make_settings(test_env, WD_AUDIO_PROVIDER="say")
    one = audio.synthesize(cfg, "en-US", "one").path.stat().st_size
    assert audio.cache_bytes(cfg) == one
    # another process (`wd audio-prewarm`) drops a clip in: the running total does not see it yet …
    foreign = cfg.audio_dir / "zz" / ("f" * 64 + ".m4a")
    foreign.parent.mkdir(parents=True)
    foreign.write_bytes(b"x" * 1000)
    two = audio.synthesize(cfg, "en-US", "two").path.stat().st_size
    assert audio.cache_bytes(cfg) == one + two
    # … until the interval has passed: the next synthesis re-counts from disk
    monkeypatch.setattr(audio, "SCAN_INTERVAL_S", 0.0)
    three = audio.synthesize(cfg, "en-US", "three").path.stat().st_size
    assert audio.cache_bytes(cfg) == one + two + three + 1000
    foreign.unlink()
    audio.synthesize(cfg, "en-US", "four")
    assert audio.cache_bytes(cfg) == sum(size for _m, size, _p in audio._scan(cfg.audio_dir))


def seed_tappable(conn: sqlite3.Connection) -> None:
    """What learners can tap: `farmer` with content (three examples, one the text rule refuses), `hop` and `zebra` in a bank
    without content, `ghost` in nobody's reach; one en-US and one en-GB learner."""
    conn.execute("INSERT INTO users (id, username, password_hash) VALUES (1, 'kid', 'x'), (2, 'mum', 'x')")
    conn.execute("INSERT INTO user_settings (user_id, accent) VALUES (1, 'en-US'), (2, 'en-GB')")
    conn.executemany(
        "INSERT INTO words (id, lemma, display, source, learn_rank) VALUES (?, ?, ?, 'seed', ?)",
        [(1, "farmer", "farmer", 20), (2, "hop", "hop", 10), (3, "ghost", "ghost", 30), (4, "zebra", "zebra", None)],
    )
    content = {"examples": [{"en": "The farmer grows rice.", "zh": "农民种水稻。"}, {"en": "  A   farmer   works  hard — every day. ", "zh": "…"}, {"en": "bad text ✓", "zh": "…"}, "junk"]}
    conn.execute("INSERT INTO word_contents (id, word_id, version, prompt_version, model, content_json) VALUES (11, 1, 1, 'content-v1', 'm', ?)", (json.dumps(content),))
    conn.execute("UPDATE words SET active_content_id = 11 WHERE id = 1")
    conn.execute("INSERT INTO user_words (user_id, word_id, state, origin) VALUES (1, 2, 'new', 'custom'), (1, 4, 'new', 'browse')")
    conn.execute("UPDATE words SET stage_xs = 1, is_public = 1, is_valid_english = 1 WHERE id = 3")  # a 小学 word the screening can draw
    conn.commit()


def test_prewarm_texts_are_the_tappable_headwords_and_examples_in_learning_order(conn: sqlite3.Connection):
    seed_tappable(conn)
    chosen = audio.prewarm_texts(conn)
    assert chosen.texts == ["hop", "farmer", "The farmer grows rice.", "A farmer works hard — every day.", "zebra"]
    assert chosen.refused == ["bad text ✓"]
    assert audio.prewarm_texts(conn, stages=("xs",)).texts == ["hop", "farmer", "The farmer grows rice.", "A farmer works hard — every day.", "ghost", "zebra"]
    with pytest.raises(ValueError):
        audio.prewarm_texts(conn, stages=("xs; DROP TABLE words",))
    assert audio.accents_in_use(conn) == ("en-US", "en-GB")
    conn.execute("DELETE FROM user_settings WHERE user_id = 2")
    assert audio.accents_in_use(conn) == ("en-US",)


def test_prewarm_makes_the_missing_clips_two_at_a_time_and_counts_the_cached_ones(test_env: dict[str, str], fakes: dict[str, Path]):
    cfg = make_settings(test_env, WD_AUDIO_PROVIDER="say")
    texts = ["hop", "farmer", "The farmer grows rice."]
    played = audio.synthesize(cfg, "en-US", "farmer").path  # a learner played it already
    old = time.time() - 300
    os.utime(played, (old, old))
    seen: list[int] = []
    report = audio.prewarm(cfg, texts, ("en-US", "en-GB"), progress=lambda r: seen.append(r.done))
    assert (report.clips, report.cached, report.todo, report.skipped, report.made, report.failed) == (6, 1, 5, 0, 5, 0)
    assert not report.aborted and not report.interrupted and report.seconds >= 0
    assert report.bytes_made == sum(audio.locate(cfg, a, t)[0].path.stat().st_size for a in ("en-US", "en-GB") for t in texts) - played.stat().st_size
    assert seen == [5]
    assert played.stat().st_mtime == pytest.approx(old)  # the cached clip was neither re-made nor touched
    made = calls(fakes)
    assert len(made) == 6 and made.count("Ava (Premium)|farmer") == 1
    assert {c.split("|", 1)[0] for c in made} == {"Ava (Premium)", "Stephanie (Premium)"}
    again = audio.prewarm(cfg, texts, ("en-US", "en-GB"))
    assert (again.cached, again.todo, again.made) == (6, 0, 0) and len(calls(fakes)) == 6
    # --limit bounds the clips to make, not the pairs: a cached pair does not use it up
    limited = audio.prewarm(cfg, ["new one", "new two", "new three"], ("en-US",), limit=1)
    assert (limited.clips, limited.cached, limited.todo, limited.made, limited.skipped) == (3, 0, 1, 1, 2)
    limited = audio.prewarm(cfg, ["new one", "new two", "new three"], ("en-US",), limit=1)
    assert (limited.cached, limited.todo, limited.made, limited.skipped) == (1, 1, 1, 1)
    assert audio.cache_bytes(cfg) == sum(size for _m, size, _p in audio._scan(cfg.audio_dir))


def test_prewarm_without_a_voice_raises_up_front(test_env: dict[str, str], fake_say):
    fake_say("Ting-Ting           zh_CN    # 您好，我叫Ting-Ting。\n")  # no English voice: nothing can even be located
    cfg = make_settings(test_env, WD_AUDIO_PROVIDER="say")
    with pytest.raises(audio.AudioError) as e:
        audio.prewarm(cfg, [f"text {i}" for i in range(20)], ("en-US",))
    assert e.value.reason == "failed" and "no English voice" in e.value.detail
    with pytest.raises(audio.AudioError) as e:
        audio.prewarm(make_settings(test_env, WD_AUDIO_PROVIDER="off"), ["text"], ("en-US",))
    assert e.value.reason == "off"


def test_prewarm_stops_after_five_failures_in_a_row_even_after_a_success(test_env: dict[str, str], fakes: dict[str, Path], tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    """`say` wedged half-way through a run: the streak rule stops it (the old 'nothing made yet' rule would have ground on)."""
    cfg = make_settings(test_env, WD_AUDIO_PROVIDER="say")
    first = tmp_path / "afconvert-first-run"  # mkdir is atomic: exactly one of the two concurrent runs wins, every later one fails
    flaky = tmp_path / "afconvert-flaky"
    flaky.write_text(f"#!/bin/sh\nmkdir '{first}' 2>/dev/null || exit 1\nexec '{fakes['afconvert']}' \"$@\"\n", encoding="utf-8")
    flaky.chmod(0o755)
    monkeypatch.setattr(audio, "AFCONVERT_BIN", str(flaky))
    report = audio.prewarm(cfg, [f"text {i}" for i in range(20)], ("en-US",))
    assert report.aborted and report.made == 1 and audio.PREWARM_ABORT_AFTER <= report.failed <= audio.PREWARM_ABORT_AFTER + 1 + audio.SLOTS  # the success may land after a failure; the attempts running at the abort are counted too
    assert report.done == report.made + report.failed
    assert all("afconvert" in e and "exited 1" in e for e in report.errors)


def test_scan_skips_a_clip_that_vanishes_mid_walk(test_env: dict[str, str], fakes: dict[str, Path], monkeypatch: pytest.MonkeyPatch):
    """The re-count runs on the request path while a prune or `wd audio-prewarm --purge-others` may be unlinking clips."""
    cfg = make_settings(test_env, WD_AUDIO_PROVIDER="say")
    keep = audio.synthesize(cfg, "en-US", "keep").path
    gone = audio.synthesize(cfg, "en-US", "gone").path
    real_stat = Path.stat

    def racy_stat(self: Path, *args, **kwargs):
        if self == gone and os.path.exists(str(self)):
            os.unlink(str(self))  # another process got there between the listing and the stat
        return real_stat(self, *args, **kwargs)

    monkeypatch.setattr(Path, "stat", racy_stat)
    assert [p for _m, _s, p in audio._scan(cfg.audio_dir)] == [keep]
    monkeypatch.setattr(audio, "SCAN_INTERVAL_S", 0.0)
    audio._account(cfg, 0)  # the re-count on the request path neither raises nor counts the vanished clip
    assert audio.cache_bytes(cfg) == real_stat(keep).st_size


def test_say_voice_for_keeps_the_choice_a_concurrent_first_call_stored(test_env: dict[str, str], fakes: dict[str, Path], caplog: pytest.LogCaptureFixture, monkeypatch: pytest.MonkeyPatch):
    cfg = make_settings(test_env, WD_AUDIO_PROVIDER="say")
    real = audio.choose_voice

    def racing(voices, accent, resolves=lambda name: True):
        chosen = real(voices, accent, resolves=resolves)
        with audio._choice_lock:
            audio._choices["\nen-US"] = "Samantha"  # the other thread finished (and logged) first
        return chosen

    monkeypatch.setattr(audio, "choose_voice", racing)
    with caplog.at_level(logging.INFO, logger="wd.audio"):
        assert audio.say_voice_for(cfg, "en-US") == "Samantha"
    assert [r for r in caplog.records if getattr(r, "event", "") == "audio_voice"] == []


def test_voice_key_fingerprints_the_provider_and_the_resolved_voices(test_env: dict[str, str], fakes: dict[str, Path]):
    assert audio.voice_key(make_settings(test_env, WD_AUDIO_PROVIDER="off")) == ""
    cfg = make_settings(test_env, WD_AUDIO_PROVIDER="say")
    before = audio.voice_key(cfg)  # the voices are not resolved yet
    assert re.fullmatch(r"[0-9a-f]{8}", before)
    audio.warm_up(cfg)
    after = audio.voice_key(cfg)
    assert re.fullmatch(r"[0-9a-f]{8}", after) and after != before and audio.voice_key(cfg) == after
    assert after == hashlib.sha256(b"say\n\nAva (Premium)\nStephanie (Premium)").hexdigest()[:8]
    assert audio.voice_key(make_settings(test_env, WD_AUDIO_PROVIDER="say", WD_AUDIO_SAY_VOICE="Samantha")) not in (before, after)  # an override is another key even before it resolves
    assert audio.voice_key(make_settings(test_env, WD_AUDIO_PROVIDER="youdao")) == hashlib.sha256(b"youdao").hexdigest()[:8]


def test_warm_up_sweeps_the_probe_files_of_an_earlier_process(test_env: dict[str, str], fakes: dict[str, Path]):
    cfg = make_settings(test_env, WD_AUDIO_PROVIDER="say")
    stale = cfg.tmp_dir / "audio-probe-4000000-1.aiff"  # no such process (pids stop at 99998 on macOS)
    stale.write_bytes(b"x")
    mine = cfg.tmp_dir / f"audio-probe-{os.getpid()}-7.aiff"
    mine.write_bytes(b"y")
    alive = cfg.tmp_dir / f"audio-probe-{os.getppid()}-3.aiff"  # another live process (wd audio-voices next door) keeps its probe
    alive.write_bytes(b"z")
    odd = cfg.tmp_dir / "audio-probe-x.aiff"
    odd.write_bytes(b"?")
    audio.warm_up(cfg)
    assert not stale.exists() and mine.exists() and alive.exists() and odd.exists()
    for f in (mine, alive, odd):
        f.unlink()


def test_purge_others_removes_only_the_clips_outside_the_set(test_env: dict[str, str], fakes: dict[str, Path]):
    cfg = make_settings(test_env, WD_AUDIO_PROVIDER="say")
    texts = ["hop", "farmer"]
    audio.prewarm(cfg, texts, ("en-US",))
    keep = audio.expected_paths(cfg, texts, ("en-US",))
    assert len(keep) == 2 and all(p.is_file() for p in keep)
    stale = cfg.audio_dir / "00" / ("0" * 64 + ".m4a")  # another voice's clip (the key carries the voice)
    stale.parent.mkdir(parents=True, exist_ok=True)
    stale.write_bytes(b"x" * 600)
    adhoc = audio.synthesize(cfg, "en-GB", "farmer").path  # a text outside the set
    adhoc_size = adhoc.stat().st_size
    assert audio.purge_others(cfg, keep) == (2, 600 + adhoc_size)
    assert not stale.exists() and not adhoc.exists() and all(p.is_file() for p in keep)
    assert audio.cache_bytes(cfg) == sum(p.stat().st_size for p in keep)
    assert audio.purge_others(cfg, keep) == (0, 0)


def test_cli_audio_voices_and_audio_prewarm(test_env: dict[str, str], fakes: dict[str, Path], conn: sqlite3.Connection, capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch, tmp_path: Path):
    from wd import cli

    seed_tappable(conn)
    monkeypatch.setenv("WD_AUDIO_PROVIDER", "off")
    assert cli.main(["audio-voices"]) == 0
    assert "provider: off" in capsys.readouterr().out
    assert cli.main(["audio-prewarm"]) == 2
    assert "resolves to off" in capsys.readouterr().err

    monkeypatch.setenv("WD_AUDIO_PROVIDER", "say")
    missing_db = tmp_path / "nowhere" / "x.db"
    assert cli.main(["audio-prewarm", "--db", str(missing_db)]) == 2  # never creates an empty database at a mistyped path
    assert "no database at" in capsys.readouterr().err and not missing_db.exists()

    monkeypatch.setenv("WD_AUDIO_SAY_VOICE", "Nobody")  # an override say does not know: no clips in a substituted voice
    assert cli.main(["audio-voices"]) == 1
    assert "en-US → none:" in capsys.readouterr().out
    assert cli.main(["audio-prewarm", "--dry-run"]) == 1
    assert "no voice — WD_AUDIO_SAY_VOICE='Nobody'" in capsys.readouterr().err
    monkeypatch.delenv("WD_AUDIO_SAY_VOICE")
    audio.reset_voice_cache()

    monkeypatch.setenv("WD_AUDIO_CACHE_MB", "16")
    monkeypatch.setattr(audio, "PREWARM_CLIP_ESTIMATE", 4 * audio.MB)  # 10 clips × 4 MB against a 16 MB cap: the run would prune its own clips
    assert cli.main(["audio-prewarm", "--dry-run"]) == 1
    captured = capsys.readouterr()
    assert "≈ 40 MB in the cache afterwards, cap WD_AUDIO_CACHE_MB=16" in captured.out and "more than 90 % of WD_AUDIO_CACHE_MB=16 — set it to at least 45" in captured.err
    old_db = tmp_path / "old.db"
    sqlite3.connect(old_db).close()  # a database without the schema
    assert cli.main(["audio-prewarm", "--db", str(old_db)]) == 1
    assert "schema version 0 has no words.learn_rank" in capsys.readouterr().err
    monkeypatch.delenv("WD_AUDIO_CACHE_MB")
    monkeypatch.setattr(audio, "PREWARM_CLIP_ESTIMATE", 20 * 1024)

    assert cli.main(["audio-voices"]) == 0
    out = capsys.readouterr().out
    assert "provider: say (WD_AUDIO_PROVIDER=say)" in out and "cache: 0.0 MB of 256 MB" in out
    assert re.search(r"Ava \(Premium\)\s+premium\s+resolves", out) and re.search(r"Samantha \(增强\)\s+enhanced\s+resolves", out) and re.search(r"Samantha\s+compact\s+resolves", out)
    assert "en-US → Ava (Premium)" in out and "en-GB → Stephanie (Premium)" in out and "Eddy" not in out

    assert cli.main(["audio-prewarm", "--dry-run"]) == 0
    out = capsys.readouterr().out
    assert "5 text(s) a learner can tap (headwords with content or in a bank and their example sentences; learning order); en-US → Ava (Premium), en-GB → Stephanie (Premium)" in out
    assert "1 text(s) the text rule refuses" in out and "'bad text ✓'" in out
    assert "10 clip(s) planned: 0 cached, 10 to synthesise; ≈ 0 MB in the cache afterwards, cap WD_AUDIO_CACHE_MB=256" in out
    assert "0 other clip(s) (0.0 MB) outside this set would be purged first" in out and calls(fakes) == []
    assert cli.main(["audio-prewarm", "--dry-run", "--stage", "xs"]) == 0
    out = capsys.readouterr().out
    assert "6 text(s) a learner can tap" in out and ", the headwords of xs;" in out and "12 clip(s) planned" in out

    assert cli.main(["audio-prewarm", "--accent", "en-US"]) == 0
    out = capsys.readouterr().out
    assert "5 clip(s) planned: 0 cached, 5 to synthesise" in out and "audio-prewarm: 5 clip(s) made" in out and "0 already cached, 0 failed" in out
    assert len(calls(fakes)) == 5 and all(c.startswith("Ava (Premium)|") for c in calls(fakes))

    assert cli.main(["audio-prewarm", "--limit", "2"]) == 0  # --limit counts the clips to make: the five cached ones do not use it up
    out = capsys.readouterr().out
    assert "10 clip(s) planned: 5 cached, 5 to synthesise, 2 in this run (--limit 2)" in out
    assert "audio-prewarm: 2 clip(s) made" in out and "5 already cached, 0 failed, 3 left for the next run (--limit)" in out
    assert len(calls(fakes)) == 7 and sum(c.startswith("Stephanie (Premium)|") for c in calls(fakes)) == 2

    cfg = Settings.from_env()
    stale = cfg.audio_dir / "00" / ("0" * 64 + ".m4a")
    stale.parent.mkdir(parents=True, exist_ok=True)
    stale.write_bytes(b"x" * 600)
    assert cli.main(["audio-prewarm", "--accent", "en-US", "--purge-others"]) == 0  # keeps the en-GB clips: the mum's accent is in use
    out = capsys.readouterr().out
    assert "1 other clip(s) (0.0 MB) outside this set are purged first" in out and "purged 1 other clip(s) (0.0 MB)" in out
    assert out.index("purged 1 other") < out.index("5 clip(s) planned: 5 cached, 0 to synthesise") and not stale.exists()
    assert len([p for _m, _s, p in audio._scan(cfg.audio_dir)]) == 7 and len(calls(fakes)) == 7

    assert cli.main(["audio-prewarm", "--purge-others"]) == 0
    out = capsys.readouterr().out
    assert "10 clip(s) planned: 7 cached, 3 to synthesise" in out and "3 clip(s) made" in out and "purged 0 other clip(s)" in out
    assert len(calls(fakes)) == 10 and sum(c.startswith("Stephanie (Premium)|") for c in calls(fakes)) == 5

    def pruned_during_the_run(cfg, texts, accents, *, limit=0, progress=None):  # the cap evicted one planned clip while the run went on
        victim = sorted(audio.expected_paths(cfg, texts, accents))[0]
        victim.unlink()
        return audio.PrewarmReport(clips=len(texts) * len(accents), cached=len(texts) * len(accents))

    monkeypatch.setattr(audio, "prewarm", pruned_during_the_run)
    assert cli.main(["audio-prewarm", "--accent", "en-US"]) == 1
    assert "1 clip(s) of the set were pruned by WD_AUDIO_CACHE_MB=256 during the run" in capsys.readouterr().err
