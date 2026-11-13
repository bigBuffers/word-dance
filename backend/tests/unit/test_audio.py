"""wd.audio (API.md 76): the text rule, voice choice from a localised `say -v ?` listing (tiers, the resolution probe), the
content-addressed cache and its size cap, the `say`, `youdao` and `bailian` (阿里云百炼 cloud TTS, through an httpx.MockTransport in
front of both of its clients) providers against fakes, the synthesis slots and waiters, the allow-listed child environment, the
`auto` provider resolution, the startup warm-up, the periodic re-count of the cache and the `wd audio-prewarm` / `wd audio-voices` /
`wd audio-probe` commands (DEPLOY §9); and the Chinese clips of 磨耳朵 (`accent=zh-CN`): their text rule, the voice choice by tier
that never crosses languages, the size probe on a system whose fallback voice is the Chinese voice, the override that must be a
listed Chinese voice, the floor that keeps silence out of the cache, the settled "no Chinese voice", `speaks_zh` (optimistic until
the voice is resolved, never running `say`) and the other providers' `missing` / `failed`."""

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
    """`voice|text` of every synthesis the fake `say` ran (the voice probes — the English and the Chinese one — excluded)."""
    lines = fakes["calls"].read_text(encoding="utf-8").splitlines() if fakes["calls"].exists() else []
    return [c for c in lines if not c.endswith(("|" + audio.PROBE_TEXT, "|" + audio.ZH_PROBE_TEXT))]


def probes(fakes: dict[str, Path]) -> list[str]:
    lines = fakes["calls"].read_text(encoding="utf-8").splitlines() if fakes["calls"].exists() else []
    return [c.split("|", 1)[0] for c in lines if c.endswith("|" + audio.PROBE_TEXT)]


def zh_probes(fakes: dict[str, Path]) -> list[str]:
    """The voices asked to speak ZH_PROBE_TEXT (say_speaks_zh), in order."""
    lines = fakes["calls"].read_text(encoding="utf-8").splitlines() if fakes["calls"].exists() else []
    return [c.split("|", 1)[0] for c in lines if c.endswith("|" + audio.ZH_PROBE_TEXT)]


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


def test_cache_provider_needs_the_voices_of_both_accents(test_env: dict[str, str]):
    voices = "en-US=Ava (Premium); en-GB=Serena (Premium)"
    cfg = Settings.from_env({**test_env, "WD_AUDIO_PROVIDER": "cache", "WD_AUDIO_CACHE_VOICES": voices})
    assert cfg.audio_provider_effective == "cache" and audio.provider_for(cfg) == "cache"
    assert cfg.audio_cache_voice_map == {"en-US": "Ava (Premium)", "en-GB": "Serena (Premium)"}
    assert {e["key"]: e["value"] for e in cfg.entries()}["WD_AUDIO_CACHE_VOICES"] == voices
    with pytest.raises(ConfigError, match="both accents"):
        Settings.from_env({**test_env, "WD_AUDIO_PROVIDER": "cache"})
    with pytest.raises(ConfigError, match="both accents"):
        Settings.from_env({**test_env, "WD_AUDIO_PROVIDER": "cache", "WD_AUDIO_CACHE_VOICES": "en-US=Ava (Premium)"})
    for bad in ("en-US:Ava", "fr-FR=Amelie;en-GB=Serena (Premium)", "en-US=;en-GB=Daniel", "en-US=Ava;en-US=Samantha"):
        with pytest.raises(ConfigError, match="WD_AUDIO_CACHE_VOICES"):
            Settings.from_env({**test_env, "WD_AUDIO_PROVIDER": "say", "WD_AUDIO_CACHE_VOICES": bad})
    assert Settings.from_env({**test_env, "WD_AUDIO_CACHE_VOICES": "en-US=Ava (Premium)"}).audio_cache_voice_map == {"en-US": "Ava (Premium)"}  # only cache needs both


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
    assert report.aborted and report.made == 1 and report.failed >= audio.PREWARM_ABORT_AFTER  # the one success may land before or after the first failure
    assert report.done == report.made + report.failed < report.todo  # every attempt that ran is counted, the queued rest was dropped
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
    assert after == hashlib.sha256(b"say\n\nAva (Premium)\nStephanie (Premium)\nTing-Ting").hexdigest()[:8]  # the two accents, then the Chinese voice (LISTING has one)
    assert audio.voice_key(make_settings(test_env, WD_AUDIO_PROVIDER="say", WD_AUDIO_SAY_VOICE="Samantha")) not in (before, after)  # an override is another key even before it resolves
    assert audio.voice_key(make_settings(test_env, WD_AUDIO_PROVIDER="youdao")) == hashlib.sha256(b"youdao").hexdigest()[:8]


def test_cache_provider_serves_the_clips_say_made_and_reports_a_missing_one(test_env: dict[str, str], fakes: dict[str, Path], monkeypatch: pytest.MonkeyPatch):
    """A Linux server mirrors the Mac's audio/ and names the voices: the same content-addressed clips play, a text without one is `missing`."""
    mac = make_settings(test_env, WD_AUDIO_PROVIDER="say")
    made = {accent: audio.synthesize(mac, accent, "farmer").path for accent in audio.ACCENTS}  # Ava (Premium) / Stephanie (Premium) from LISTING
    linux = make_settings(test_env, WD_AUDIO_PROVIDER="cache", WD_AUDIO_CACHE_VOICES="en-US=Ava (Premium);en-GB=Stephanie (Premium)")
    for accent in audio.ACCENTS:
        clip, provider, voice = audio.locate(linux, accent, "farmer")
        assert (clip.path, clip.media_type, provider) == (made[accent], "audio/mp4", "cache")
        assert audio.lookup(linux, accent, "farmer") is not None and audio.synthesize(linux, accent, "farmer").path == made[accent]
    with pytest.raises(audio.AudioError) as e:
        audio.synthesize(linux, "en-US", "zebra")
    assert e.value.reason == "missing" and "wd audio-texts" in e.value.detail
    assert audio.lookup(linux, "en-US", "zebra") is None and len(calls(fakes)) == 2  # nothing was synthesised here
    other = make_settings(test_env, WD_AUDIO_PROVIDER="cache", WD_AUDIO_CACHE_VOICES="en-US=Samantha;en-GB=Daniel")
    assert audio.lookup(other, "en-US", "farmer") is None  # another voice is another name: a wrong WD_AUDIO_CACHE_VOICES never hits
    assert audio.voice_key(linux) == hashlib.sha256(b"cache\nAva (Premium)\nStephanie (Premium)").hexdigest()[:8]
    assert len({audio.voice_key(linux), audio.voice_key(other), audio.voice_key(mac)}) == 3
    assert audio.warm_up_async(linux) is None
    # the mirror is served whole: the cap is the synthesising host's business, nothing here prunes or touches
    before = {p: p.stat().st_mtime for p in made.values()}
    tiny = make_settings(test_env, WD_AUDIO_PROVIDER="cache", WD_AUDIO_CACHE_VOICES="en-US=Ava (Premium);en-GB=Stephanie (Premium)", WD_AUDIO_CACHE_MB="16")
    monkeypatch.setattr(audio, "MB", 1)  # 16 bytes of cap against two clips
    audio.reset_cache_accounting()
    for accent in audio.ACCENTS:
        assert audio.lookup(tiny, accent, "farmer") is not None
    assert all(p.is_file() and p.stat().st_mtime == before[p] for p in made.values()) and len(calls(fakes)) == 2


def test_texts_from_file_reads_the_output_of_audio_texts(tmp_path: Path):
    plain = tmp_path / "texts.txt"
    plain.write_text("farmer\n  The   farmer grows rice. \nbad ✓\nfarmer\n\n", encoding="utf-8")
    assert audio.texts_from_file(plain) == audio.PrewarmSet(texts=["farmer", "The farmer grows rice."], refused=["bad ✓"])
    windows = tmp_path / "windows.txt"
    windows.write_bytes("\ufefffarmer\r\nhop\r\n".encode("utf-8"))  # a BOM and CRLF from an editor on the way
    assert audio.texts_from_file(windows).texts == ["farmer", "hop"]
    latin = tmp_path / "latin.txt"
    latin.write_bytes("café\n".encode("latin-1"))
    with pytest.raises(UnicodeDecodeError):
        audio.texts_from_file(latin)


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


def test_cli_audio_texts_and_prewarm_from_a_file_feed_a_read_only_cache(test_env: dict[str, str], fakes: dict[str, Path], conn: sqlite3.Connection, capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch, tmp_path: Path):
    """The sync loop of DEPLOY §9: `wd audio-texts` on the server, `wd audio-prewarm --texts` on the Mac, rsync, and the server's cache mode."""
    from wd import cli

    seed_tappable(conn)
    monkeypatch.setenv("WD_AUDIO_PROVIDER", "say")
    assert cli.main(["audio-texts"]) == 0
    captured = capsys.readouterr()
    assert captured.out.splitlines() == ["hop", "farmer", "The farmer grows rice.", "A farmer works hard — every day.", "zebra"]
    assert "5 text(s); 1 refused by the text rule" in captured.err
    assert cli.main(["audio-texts", "--stage", "xs"]) == 0
    assert capsys.readouterr().out.splitlines() == ["hop", "farmer", "The farmer grows rice.", "A farmer works hard — every day.", "ghost", "zebra"]
    assert cli.main(["audio-texts", "--db", str(tmp_path / "nowhere.db")]) == 2
    old_db = tmp_path / "old.db"
    sqlite3.connect(old_db).close()
    assert cli.main(["audio-texts", "--db", str(old_db)]) == 1
    assert "schema version 0" in capsys.readouterr().err

    texts = tmp_path / "texts.txt"
    texts.write_text("farmer\nThe farmer grows rice.\nbad ✓\n", encoding="utf-8")
    latin = tmp_path / "latin.txt"
    latin.write_bytes("café\n".encode("latin-1"))
    for bad in (["--texts", str(texts), "--purge-others"], ["--texts", str(texts), "--stage", "xs"], ["--texts", str(texts), "--db", str(tmp_path / "x.db")], ["--texts", str(tmp_path / "missing.txt")], ["--texts", str(latin)]):
        assert cli.main(["audio-prewarm", *bad]) == 2, bad
    err = capsys.readouterr().err
    assert "cannot read" in err and "need this host's database" in err
    assert cli.main(["audio-prewarm", "--texts", str(texts), "--dry-run"]) == 0
    out = capsys.readouterr().out
    assert "4 clip(s) planned: 0 cached, 4 to synthesise" in out and "purged" not in out  # another host's set says nothing about this cache
    assert cli.main(["audio-prewarm", "--texts", str(texts)]) == 0  # both accents: the other host's learners are unknown
    out = capsys.readouterr().out
    assert f"2 text(s) a learner can tap (from {texts})" in out and "1 text(s) the text rule refuses" in out and "4 clip(s) planned: 0 cached, 4 to synthesise" in out
    assert "audio-prewarm: 4 clip(s) made" in out and len(calls(fakes)) == 4
    assert cli.main(["audio-prewarm", "--texts", str(texts), "--accent", "en-US"]) == 0
    assert "2 clip(s) planned: 2 cached, 0 to synthesise" in capsys.readouterr().out

    # the server side: the mirrored clips play, nothing is synthesised, prewarm refuses
    monkeypatch.setenv("WD_AUDIO_PROVIDER", "cache")
    monkeypatch.setenv("WD_AUDIO_CACHE_VOICES", "en-US=Ava (Premium);en-GB=Stephanie (Premium)")
    assert cli.main(["audio-voices"]) == 0
    out = capsys.readouterr().out
    assert "provider: cache (WD_AUDIO_PROVIDER=cache) — a read-only mirror of the `say` clips another host synthesised: 4 clip(s)" in out and "not enforced here" in out
    assert "en-US → Ava (Premium) (WD_AUDIO_CACHE_VOICES)" in out and "en-GB → Stephanie (Premium)" in out and "WD_AUDIO_SAY_VOICE" not in out
    assert cli.main(["audio-prewarm", "--dry-run"]) == 2
    assert "serves clips another host synthesised" in capsys.readouterr().err
    assert cli.main(["audio-texts"]) == 0 and len(capsys.readouterr().out.splitlines()) == 5


# ------------------------------------------------------------------------------------- bailian provider
BAILIAN_URL = "https://llm-ws1.cn-beijing.maas.aliyuncs.com/api/v1/services/audio/tts/SpeechSynthesizer"
OSS_URL = "http://dashscope-result-bj.oss-cn-beijing.aliyuncs.com/1d/2026-11-11/clip.mp3?Expires=1766113409&OSSAccessKeyId=LTAI5tXYZ&Signature=abc%2Fdef%3D"
MP3 = b"\xff\xfb" + b"\x00" * 1500
BAILIAN_KEY = "sk-bailian-test-key"


def bailian_env(tmp_path: Path, **extra: str) -> dict[str, str]:
    """A 0600 key file, the workspace id and the provider — what `bailian` needs to start (DEPLOY §4)."""
    key = tmp_path / "bailian.key"
    key.write_text(BAILIAN_KEY + "\n", encoding="utf-8")
    key.chmod(0o600)
    return {"WD_AUDIO_PROVIDER": "bailian", "WD_BAILIAN_API_KEY_FILE": str(key), "WD_BAILIAN_WORKSPACE_ID": "llm-ws1", **extra}


def tts_answer(url: str = OSS_URL, characters: int = 23) -> dict:
    """The documented non-streaming SpeechSynthesizer answer: the clip as a pre-signed OSS URL (plain http in the docs), never inline."""
    return {"request_id": "5c63c65c-0000", "output": {"finish_reason": "stop", "audio": {"data": "", "url": url, "id": "audio_5c63c65c", "expires_at": 1766113409}}, "usage": {"characters": characters}}


def mp3_download(request: httpx.Request) -> httpx.Response:
    return httpx.Response(200, content=MP3, headers={"content-type": "audio/mpeg"})


def patch_bailian(monkeypatch: pytest.MonkeyPatch, synth, download=mp3_download) -> list[httpx.Request]:
    """One MockTransport in front of both 百炼 clients — the synthesis POST and the anonymous OSS GET —, so a test sees the headers each
    request really carries; the pacing is off unless a test turns it on."""
    seen: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return synth(request) if request.method == "POST" else download(request)

    monkeypatch.setattr(audio, "BAILIAN_TRANSPORT", httpx.MockTransport(handler))
    monkeypatch.setattr(audio, "BAILIAN_PACE_S", 0.0)
    return seen


def test_bailian_posts_the_synthesis_and_fetches_the_clip_over_https_without_the_key(test_env: dict[str, str], tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    cfg = make_settings(test_env, **bailian_env(tmp_path))
    seen = patch_bailian(monkeypatch, lambda r: httpx.Response(200, json=tts_answer()))
    assert audio.lookup(cfg, "en-GB", "The cat sat on the mat.") is None
    clip = audio.synthesize(cfg, "en-GB", "The cat sat on the mat.")
    assert clip.media_type == "audio/mpeg" and clip.path.suffix == ".mp3" and clip.path.read_bytes() == MP3
    assert stat.S_IMODE(clip.path.stat().st_mode) == 0o600 and clip.path.parent.parent == cfg.audio_dir
    assert clip.path.name == hashlib.sha256(b"bailian\nloongemily_v3\nen-GB\nThe cat sat on the mat.").hexdigest() + ".mp3"
    post, get = seen
    assert post.method == "POST" and str(post.url) == BAILIAN_URL
    assert post.headers["authorization"] == f"Bearer {BAILIAN_KEY}" and post.headers["content-type"] == "application/json" and post.headers["user-agent"] == f"word-Dance/{__version__}"
    assert json.loads(post.content) == {"model": "cosyvoice-v3-flash", "input": {"text": "The cat sat on the mat.", "voice": "loongemily_v3", "format": "mp3", "sample_rate": 24000}}
    assert get.method == "GET" and get.url.scheme == "https" and get.url.host == "dashscope-result-bj.oss-cn-beijing.aliyuncs.com"  # the documented http:// URL is fetched over https
    assert get.url.path == "/1d/2026-11-11/clip.mp3" and get.url.params["Signature"] == "abc/def=" and get.url.params["Expires"] == "1766113409"
    assert "authorization" not in get.headers and get.headers["user-agent"] == f"word-Dance/{__version__}"  # anonymous: the key never reaches OSS
    assert audio.synthesize(cfg, "en-GB", "The cat sat on the mat.") == clip and audio.lookup(cfg, "en-GB", "The cat sat on the mat.") == clip
    assert len(seen) == 2  # a cache hit asks nobody
    other = audio.synthesize(cfg, "en-US", "The cat sat on the mat.")
    assert other.path != clip.path and json.loads(seen[2].content)["input"]["voice"] == "loongabby_v3"
    assert not list(cfg.audio_dir.rglob("*.tmp"))


def test_bailian_accepts_an_octet_stream_download_and_an_https_url_as_is(test_env: dict[str, str], tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    cfg = make_settings(test_env, **bailian_env(tmp_path))
    seen = patch_bailian(monkeypatch, lambda r: httpx.Response(200, json=tts_answer(url="https://dashscope-result-sh.oss-cn-shanghai.aliyuncs.com/x.mp3?sig=1")), lambda r: httpx.Response(200, content=MP3, headers={"content-type": "application/octet-stream"}))
    assert audio.synthesize(cfg, "en-US", "farmer").path.read_bytes() == MP3
    assert str(seen[1].url) == "https://dashscope-result-sh.oss-cn-shanghai.aliyuncs.com/x.mp3?sig=1"


def test_bailian_downloads_only_from_aliyuncs_hosts(test_env: dict[str, str], tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    """The anonymous download client follows the provider's answer; an answer pointing anywhere else is refused before any request."""
    cfg = make_settings(test_env, **bailian_env(tmp_path))
    seen = patch_bailian(monkeypatch, lambda r: httpx.Response(200, json=tts_answer(url="https://oss.example.com/x.mp3?sig=1")), lambda r: httpx.Response(200, content=MP3, headers={"content-type": "audio/mpeg"}))
    with pytest.raises(audio.AudioError) as e:
        audio.synthesize(cfg, "en-US", "farmer")
    assert e.value.reason == "failed" and "aliyuncs.com" in str(e.value) and len(seen) == 1  # the POST happened, no GET
    assert not list(cfg.audio_dir.rglob("*.mp3"))


def test_bailian_clients_carry_the_key_only_towards_the_api_and_ignore_proxy_variables(test_env: dict[str, str], tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    cfg = make_settings(test_env, **bailian_env(tmp_path, WD_PUBLIC_URL="https://words.example.com", WD_CONTACT_EMAIL="owner@example.com"))
    monkeypatch.setenv("HTTPS_PROXY", "http://127.0.0.1:9")
    with audio._bailian_client(cfg, "sk-x") as client:
        assert client.headers["authorization"] == "Bearer sk-x" and client.headers["content-type"] == "application/json"
        assert client.headers["user-agent"] == f"word-Dance/{__version__}" and "example.com" not in client.headers["user-agent"]
        assert client.trust_env is False and client.timeout.read == audio.BAILIAN_TIMEOUT_S
    with audio._bailian_download_client(cfg) as client:
        assert "authorization" not in client.headers and client.trust_env is False and client.timeout.read == audio.BAILIAN_DOWNLOAD_TIMEOUT_S


def test_bailian_key_is_read_at_call_time_and_an_unreadable_file_fails_without_its_contents(test_env: dict[str, str], tmp_path: Path, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture):
    env = bailian_env(tmp_path)
    cfg = make_settings(test_env, **env)
    assert audio.read_key(cfg) == BAILIAN_KEY
    key = Path(env["WD_BAILIAN_API_KEY_FILE"])
    key.write_text("﻿sk-rotated \nsecond line\n", encoding="utf-8")
    assert audio.read_key(cfg) == "sk-rotated"  # no cache: a rotated key is used by the next clip; a BOM and the trailing space are stripped
    key.chmod(0o644)
    monkeypatch.setattr(audio, "_key_mode_warned", False)
    with caplog.at_level(logging.WARNING, logger="wd.audio"):
        audio.read_key(cfg)
        audio.read_key(cfg)
    warned = [r.getMessage() for r in caplog.records if getattr(r, "event", "") == "audio_key_file_mode"]
    assert len(warned) == 1 and "chmod 600" in warned[0] and "sk-rotated" not in caplog.text  # once per process, never the key
    key.write_text("\n", encoding="utf-8")
    with pytest.raises(audio.AudioError) as e:
        audio.read_key(cfg)
    assert e.value.reason == "failed" and "API key file unreadable" in e.value.detail
    key.unlink()
    with pytest.raises(audio.AudioError) as e:
        audio.synthesize(cfg, "en-US", "farmer")
    assert e.value.reason == "failed" and "API key file unreadable" in e.value.detail and str(key) not in e.value.detail
    assert audio.lookup(cfg, "en-US", "farmer") is None and not list(cfg.audio_dir.rglob("*.tmp"))
    with pytest.raises(audio.AudioError) as e:  # a Settings without the variable (from_env refuses that under bailian; a hand-built one gets this)
        audio.read_key(make_settings(test_env))
    assert "WD_BAILIAN_API_KEY_FILE" in e.value.detail


@pytest.mark.parametrize(
    "status, body, reason, needle",
    [
        (401, {"code": "InvalidApiKey", "message": "Invalid API-key provided.", "request_id": "r"}, "failed", "bailian InvalidApiKey: Invalid API-key provided."),
        (401, {"code": "InvalidApiKey", "message": f"Incorrect API key provided: {BAILIAN_KEY}"}, "failed", "Incorrect API key provided: ***"),
        (400, {"code": "InvalidParameter", "message": "The requested voice 'loongabby_v3' is not supported." + " x" * 60}, "failed", "InvalidParameter: The requested voice 'loongabby_v3' is not supported."),
        (403, {"code": "Arrearage", "message": "Access denied, please make sure your account is in good standing."}, "failed", "bailian Arrearage: Access denied"),
        (404, {"code": "ModelNotFound", "message": "The model cosyvoice-v9 does not exist"}, "failed", "bailian ModelNotFound"),
        (429, {"code": "Throttling.RateQuota", "message": "Requests rate limit exceeded, please try again later."}, "busy", "bailian answered 429 Throttling.RateQuota: Requests rate limit exceeded"),
        (503, {"code": "ServiceUnavailable", "message": "Service unavailable"}, "busy", "bailian answered 503 ServiceUnavailable"),
        (500, "<html>bad gateway</html>", "busy", "bailian answered 500: retry later"),
        (200, {"code": "DataInspectionFailed", "message": "Input or output data may contain inappropriate content.", "request_id": "r"}, "failed", "bailian DataInspectionFailed"),
        (200, {"request_id": "r", "output": {"finish_reason": "stop", "audio": {"data": "", "url": ""}}}, "failed", "without output.audio.url"),
        (200, {"request_id": "r", "output": {"finish_reason": "stop", "audio": {"data": "", "url": "ftp://oss/x.mp3"}}}, "failed", "not an https URL"),
        (200, "<html>a captive portal</html>", "failed", "without output.audio.url"),
    ],
)
def test_bailian_answers_become_busy_or_failed_without_the_key(test_env: dict[str, str], tmp_path: Path, monkeypatch: pytest.MonkeyPatch, status: int, body, reason: str, needle: str):
    cfg = make_settings(test_env, **bailian_env(tmp_path))
    seen = patch_bailian(monkeypatch, lambda r: httpx.Response(status, text=body) if isinstance(body, str) else httpx.Response(status, json=body))
    with pytest.raises(audio.AudioError) as e:
        audio.synthesize(cfg, "en-US", "farmer")
    assert e.value.reason == reason and needle in e.value.detail, e.value.detail
    assert BAILIAN_KEY not in e.value.detail and "Signature" not in e.value.detail and len(e.value.detail) <= 120  # the message is cut at 80 chars
    assert len(seen) == 1  # nothing was downloaded
    assert audio.lookup(cfg, "en-US", "farmer") is None and not list(cfg.audio_dir.rglob("*.tmp"))


@pytest.mark.parametrize(
    "download, needle",
    [
        (lambda r: httpx.Response(200, content=b"<html>expired</html>" * 40, headers={"content-type": "text/html"}), "answered 200 text/html"),
        (lambda r: httpx.Response(403, content=b"<Error/>", headers={"content-type": "application/xml"}), "answered 403 application/xml"),
        (lambda r: httpx.Response(200, content=b"\xff\xfb", headers={"content-type": "audio/mpeg"}), "clip of 2 bytes"),
        (lambda r: httpx.Response(200, content=b"\xff" * (audio.BAILIAN_MAX_BYTES + 1), headers={"content-type": "audio/mpeg"}), "larger than"),
        (lambda r: (_ for _ in ()).throw(httpx.ReadTimeout("slow", request=r)), "bailian: ReadTimeout"),
    ],
)
def test_bailian_downloads_that_are_not_a_clip_fail_cleanly(test_env: dict[str, str], tmp_path: Path, monkeypatch: pytest.MonkeyPatch, download, needle: str):
    cfg = make_settings(test_env, **bailian_env(tmp_path))
    seen = patch_bailian(monkeypatch, lambda r: httpx.Response(200, json=tts_answer()), download)
    with pytest.raises(audio.AudioError) as e:
        audio.synthesize(cfg, "en-US", "farmer")
    assert e.value.reason == "failed" and needle in e.value.detail, e.value.detail
    assert len(seen) == 2 and "authorization" not in seen[1].headers
    assert audio.lookup(cfg, "en-US", "farmer") is None and not list(cfg.audio_dir.rglob("*.tmp"))


def test_bailian_transport_errors_are_failed_with_the_exception_class(test_env: dict[str, str], tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    cfg = make_settings(test_env, **bailian_env(tmp_path))
    patch_bailian(monkeypatch, lambda r: (_ for _ in ()).throw(httpx.ConnectError("boom", request=r)))
    with pytest.raises(audio.AudioError) as e:
        audio.synthesize(cfg, "en-US", "farmer")
    assert e.value.reason == "failed" and e.value.detail == "bailian: ConnectError"


def test_bailian_qwen_audio_model_adds_the_language_hint(test_env: dict[str, str], tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    cfg = make_settings(test_env, **bailian_env(tmp_path, WD_BAILIAN_TTS_MODEL="qwen-audio-3.1-tts-flash", WD_BAILIAN_TTS_VOICES="en-US=Abby_v3.1;en-GB=Emily_v3.1", WD_BAILIAN_REGION="ap-southeast-1"))
    seen = patch_bailian(monkeypatch, lambda r: httpx.Response(200, json=tts_answer()))
    audio.synthesize(cfg, "en-US", "farmer")
    assert str(seen[0].url) == "https://llm-ws1.ap-southeast-1.maas.aliyuncs.com/api/v1/services/audio/tts/SpeechSynthesizer"
    assert json.loads(seen[0].content) == {"model": "qwen-audio-3.1-tts-flash", "input": {"text": "farmer", "voice": "Abby_v3.1", "format": "mp3", "sample_rate": 24000, "language_hints": ["en"]}}


def test_bailian_locate_and_voice_key_carry_the_voices_and_the_model(test_env: dict[str, str], tmp_path: Path):
    cfg = make_settings(test_env, **bailian_env(tmp_path))
    clip, provider, voice = audio.locate(cfg, "en-US", "farmer")
    assert (provider, voice, clip.media_type, clip.path.suffix) == ("bailian", "loongabby_v3", "audio/mpeg", ".mp3")
    assert clip.path.name == hashlib.sha256(b"bailian\nloongabby_v3\nen-US\nfarmer").hexdigest() + ".mp3"
    assert audio.locate(cfg, "en-GB", "farmer")[2] == "loongemily_v3" and audio.locate(cfg, "en-GB", "farmer")[0].path != clip.path
    assert audio.voice_key(cfg) == hashlib.sha256(b"bailian\ncosyvoice-v3-flash\nloongabby_v3\nloongemily_v3").hexdigest()[:8]
    other_voice = make_settings(test_env, **bailian_env(tmp_path, WD_BAILIAN_TTS_VOICES="en-US=loongandy_v3;en-GB=loongemily_v3"))
    assert audio.locate(other_voice, "en-US", "farmer")[0].path != clip.path  # a new voice = new clips (the old ones age out under the cap)
    assert audio.locate(other_voice, "en-GB", "farmer")[0].path == audio.locate(cfg, "en-GB", "farmer")[0].path  # the unchanged accent keeps its clips
    assert audio.voice_key(other_voice) != audio.voice_key(cfg)
    other_model = make_settings(test_env, **bailian_env(tmp_path, WD_BAILIAN_TTS_MODEL="cosyvoice-v3-plus"))
    assert audio.voice_key(other_model) not in (audio.voice_key(cfg), audio.voice_key(other_voice))  # the browser's clip URLs change with the model too
    assert len({audio.voice_key(cfg), audio.voice_key(make_settings(test_env, WD_AUDIO_PROVIDER="youdao"))}) == 2
    assert audio.warm_up_async(cfg) is None  # no `say` probes to run


def test_prewarm_with_bailian_uses_two_paced_workers_and_stops_after_five_failures(test_env: dict[str, str], tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    cfg = make_settings(test_env, **bailian_env(tmp_path))
    workers: list[int | None] = []
    real_pool = audio.ThreadPoolExecutor

    class RecordingPool(real_pool):  # type: ignore[misc, valid-type]
        def __init__(self, max_workers=None, **kwargs):
            workers.append(max_workers)
            super().__init__(max_workers=max_workers, **kwargs)

    monkeypatch.setattr(audio, "ThreadPoolExecutor", RecordingPool)
    stamps: list[float] = []

    def synth(request: httpx.Request) -> httpx.Response:
        stamps.append(time.monotonic())
        return httpx.Response(200, json=tts_answer())

    patch_bailian(monkeypatch, synth)
    monkeypatch.setattr(audio, "BAILIAN_PACE_S", 0.12)
    monkeypatch.setattr(audio, "_bailian_last_post", 0.0)
    texts = [f"text {i}" for i in range(6)]
    report = audio.prewarm(cfg, texts, ("en-US",))
    assert (report.clips, report.made, report.failed, report.aborted) == (6, 6, 0, False) and workers == [2]
    gaps = [b - a for a, b in zip(sorted(stamps), sorted(stamps)[1:])]
    assert len(gaps) == 5 and all(gap >= 0.12 - 0.02 for gap in gaps), gaps  # ≥ BAILIAN_PACE_S between two consecutive POSTs, across both workers
    assert report.seconds >= 5 * 0.1
    # the provider refuses every request (a wrong key): the streak rule stops the run, the detail names the code without the key
    patch_bailian(monkeypatch, lambda r: httpx.Response(401, json={"code": "InvalidApiKey", "message": "Invalid API-key provided."}))
    report = audio.prewarm(cfg, [f"other {i}" for i in range(20)], ("en-US",))
    assert report.aborted and report.made == 0 and report.failed >= audio.PREWARM_ABORT_AFTER and report.done < report.todo
    assert all("failed: bailian InvalidApiKey" in detail and BAILIAN_KEY not in detail for detail in report.errors) and workers == [2, 2]
    patch_bailian(monkeypatch, lambda r: httpx.Response(429, json={"code": "Throttling.RateQuota", "message": "Requests rate limit exceeded, please try again later."}))
    report = audio.prewarm(cfg, [f"later {i}" for i in range(20)], ("en-US",))
    assert report.aborted and all(detail.startswith("en-US, a ") and "busy: bailian answered 429" in detail for detail in report.errors)


def test_bailian_price_line_estimates_the_characters_at_the_list_price(test_env: dict[str, str], tmp_path: Path):
    cfg = make_settings(test_env, **bailian_env(tmp_path))
    assert audio.bailian_price_line(cfg, 1_130_000) == "≈ 1130000 characters to send to 百炼 (model cosyvoice-v3-flash): ≈ ¥113.00 at ¥1 per 10 000 characters (an estimate at the 北京 list price; the console bill decides)"
    plus = make_settings(test_env, **bailian_env(tmp_path, WD_BAILIAN_TTS_MODEL="cosyvoice-v3-plus"))
    assert "≈ ¥2.00 at ¥2 per 10 000 characters" in audio.bailian_price_line(plus, 10_000)
    per_token = make_settings(test_env, **bailian_env(tmp_path, WD_BAILIAN_TTS_MODEL="qwen-audio-3.1-tts-flash"))
    assert audio.bailian_price_line(per_token, 500) == "≈ 500 characters to send to 百炼 (model qwen-audio-3.1-tts-flash): price per 10 000 characters unknown for this model — see the 百炼 model-pricing page"


def test_cli_audio_voices_probe_and_prewarm_with_bailian(test_env: dict[str, str], fakes: dict[str, Path], tmp_path: Path, conn: sqlite3.Connection, capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch):
    """DEPLOY §9: `wd audio-voices` names the model and both voices, `wd audio-probe` is the day-0 check of the key (any provider), and
    `wd audio-prewarm` prices the characters of the run and makes the clips through the cloud."""
    from wd import cli

    seed_tappable(conn)
    for key, value in bailian_env(tmp_path).items():
        monkeypatch.setenv(key, value)
    seen = patch_bailian(monkeypatch, lambda r: httpx.Response(200, json=tts_answer()))
    assert cli.main(["audio-voices"]) == 0
    out = capsys.readouterr().out
    assert "provider: bailian (WD_AUDIO_PROVIDER=bailian, model cosyvoice-v3-flash, region cn-beijing); cache: 0.0 MB of 256 MB" in out
    assert "en-US → loongabby_v3 (WD_BAILIAN_TTS_VOICES)" in out and "en-GB → loongemily_v3 (WD_BAILIAN_TTS_VOICES)" in out
    assert "Ava" not in out and "WD_AUDIO_SAY_VOICE" not in out and "no `say` voices to list" in out

    assert cli.main(["audio-probe"]) == 0
    out = capsys.readouterr().out
    assert "audio-probe: provider bailian (model cosyvoice-v3-flash), en-US → loongabby_v3, 23 chars → 1502 bytes audio/mpeg in " in out
    assert len(seen) == 2 and json.loads(seen[0].content)["input"] == {"text": "The cat sat on the mat.", "voice": "loongabby_v3", "format": "mp3", "sample_rate": 24000}
    cfg = Settings.from_env()
    assert str(audio.locate(cfg, "en-US", "The cat sat on the mat.")[0].path) in out and "already cached" not in out
    assert cli.main(["audio-probe", "--accent", "en-GB", "Hello, world!"]) == 0
    assert "en-GB → loongemily_v3, 13 chars → 1502 bytes" in capsys.readouterr().out and json.loads(seen[2].content)["input"]["voice"] == "loongemily_v3"
    assert cli.main(["audio-probe"]) == 0 and len(seen) == 4  # the default text is cached now: served, flagged, nothing asked
    assert "already cached — pass another TEXT" in capsys.readouterr().out
    assert cli.main(["audio-probe", "你好"]) == 2
    assert "text rule refuses" in capsys.readouterr().err
    patch_bailian(monkeypatch, lambda r: httpx.Response(401, json={"code": "InvalidApiKey", "message": "Invalid API-key provided."}))
    assert cli.main(["audio-probe", "A brand new sentence."]) == 1
    err = capsys.readouterr().err
    assert "wd audio-probe: bailian failed — failed: bailian InvalidApiKey: Invalid API-key provided." in err and BAILIAN_KEY not in err
    patch_bailian(monkeypatch, lambda r: httpx.Response(429, json={"code": "Throttling.RateQuota", "message": "Requests rate limit exceeded, please try again later."}))
    assert cli.main(["audio-probe", "A brand new sentence."]) == 1
    err = capsys.readouterr().err
    assert "busy: bailian answered 429 Throttling.RateQuota" in err and "within a minute" in err
    monkeypatch.setenv("WD_AUDIO_PROVIDER", "off")
    assert cli.main(["audio-probe"]) == 2
    assert "resolves to off" in capsys.readouterr().err
    monkeypatch.setenv("WD_AUDIO_PROVIDER", "say")  # any provider: the Mac's say through the fakes
    assert cli.main(["audio-probe"]) == 0
    assert "audio-probe: provider say, en-US → Ava (Premium), 23 chars → " in capsys.readouterr().out and calls(fakes) == ["Ava (Premium)|The cat sat on the mat."]
    monkeypatch.setenv("WD_AUDIO_PROVIDER", "bailian")

    seen = patch_bailian(monkeypatch, lambda r: httpx.Response(200, json=tts_answer()))
    assert cli.main(["audio-prewarm", "--dry-run"]) == 0
    out = capsys.readouterr().out
    assert "5 text(s) a learner can tap (headwords with content or in a bank and their example sentences; learning order); en-US → loongabby_v3, en-GB → loongemily_v3" in out
    assert "10 clip(s) planned: 0 cached, 10 to synthesise" in out
    assert "≈ 136 characters to send to 百炼 (model cosyvoice-v3-flash): ≈ ¥0.01 at ¥1 per 10 000 characters (an estimate" in out and seen == []
    assert cli.main(["audio-prewarm", "--accent", "en-US", "--limit", "2"]) == 0
    out = capsys.readouterr().out
    assert "≈ 9 characters to send to 百炼" in out  # hop + farmer: the two clips of this run, not the whole plan
    assert "audio-prewarm: 2 clip(s) made" in out and len(seen) == 4 and {json.loads(r.content)["input"]["text"] for r in seen if r.method == "POST"} == {"hop", "farmer"}  # two workers: either may finish first
    assert cli.main(["audio-prewarm"]) == 0
    out = capsys.readouterr().out
    assert "10 clip(s) planned: 2 cached, 8 to synthesise" in out and "≈ 127 characters to send" in out and "audio-prewarm: 8 clip(s) made" in out and len(seen) == 20


# ------------------------------------------------------------- Chinese clips (accent zh-CN: 磨耳朵, API.md 76 / 123)
ZH_LISTING = """Binbin (Enhanced)   zh_CN    # 你好！我叫彬彬。
Daniel              en_GB    # Hello! My name is Daniel.
Eddy (中文（中国大陆）)     zh_CN    # 你好！我叫Eddy。
Lili                zh_CN    # 你好！我叫莉莉。
Lili (Enhanced)     zh_CN    # 你好！我叫莉莉。
Meijia              zh_TW    # 你好，我叫美佳。
Samantha            en_US    # Hello! My name is Samantha.
Tingting            zh_CN    # 你好！我叫婷婷。
Yu-shu (Premium)    zh_CN    # 你好！我叫语舒。
"""


@pytest.mark.parametrize(
    "raw, expected",
    [
        ("月亮", "月亮"),
        ("好", "好"),
        ("分享，共用", "分享，共用"),
        ("  今晚的月亮　很亮。 ", "今晚的月亮 很亮。"),  # the ideographic space collapses like any whitespace
        ("你好\n世界", "你好 世界"),
        ("车坏了之后,车主把它丢弃在了高速公路上。", "车坏了之后,车主把它丢弃在了高速公路上。"),  # ASCII punctuation in a translation
        ("Tom 说：“GDP 增长了 5%！”", "Tom 说：“GDP 增长了 5%！”"),  # what the English rule lets through stays
        ("《哈利·波特》是一本书吗？", "《哈利·波特》是一本书吗？"),
        ("他说「你好」——然后走了……", "他说「你好」——然后走了……"),
        ("（非正式）你好；再见、回头见", "（非正式）你好；再见、回头见"),
        ("【计】『缓存』～", "【计】『缓存』～"),
        ("在…上面", "在…上面"),
        ("T恤衫", "T恤衫"),
        # the six symbols of a quantity the Chinese voice reads as the words they stand for (Tingting: 「30℃」 is byte for byte 「30摄氏度」)
        ("水在100℃时沸腾。", "水在100℃时沸腾。"),
        ("今天气温30°C，转了90°。", "今天气温30°C，转了90°。"),
        ("占20％", "占20％"),
        ("这本书卖￥20，那本卖¥30。", "这本书卖￥20，那本卖¥30。"),
        ("二〇〇八年", "二〇〇八年"),
        ("好" * 300, "好" * 300),
    ],
)
def test_normalize_text_accepts_chinese_glosses_and_translations(raw: str, expected: str):
    assert audio.normalize_text(raw, audio.ZH) == expected


@pytest.mark.parametrize("raw", ["", "   ", "farmer", "GDP 5%", "，。！", "-好", "好" * 301, "你好<script>", "你\u0000好", "日本語です", "한국어", "你好=世界", "50€的书", "好|坏", "[好]", "{好}", "好#1", "好*", "好+", "好^", "〈好〉", "好\\坏"])
def test_normalize_text_rejects_what_a_chinese_voice_must_not_see(raw: str):
    assert audio.normalize_text(raw, audio.ZH) is None


@pytest.mark.parametrize("raw", ["〇", "℃", "30℃", "20％ ￥5 ¥5 90°", "1+1=2 等于二", "他得了A+。", "3~5个", "好~"])
def test_the_quantity_symbols_are_no_han_characters_and_bring_no_other_symbol_along(raw: str):
    """℃ ° ％ ￥ ¥ 〇 are let through because the voice reads them as words; a text still needs a Han character of its own (〇 is none —
    HAN_RE is what content validation calls CJK), and `+` `=` `~` stay refused: the voice drops or skips them (「A+」 is read 「A」,
    「3~5」 without the 到), and the glosses of 磨耳朵 rely on a sense like 「A+级」 being refused."""
    assert audio.normalize_text(raw, audio.ZH) is None


def test_the_chinese_rule_is_the_english_class_plus_han_and_chinese_punctuation():
    english = audio.TEXT_RE.pattern[len("^(?!-)[") : -len("]+$")]
    assert audio.ZH_TEXT_RE.pattern == "^(?!-)[" + "㐀-䶿一-鿿" + r"\uf900-\ufaff" + "，。！？；：、（）《》「」『』【】～·" + "℃°％￥¥〇" + english + "]+$"  # the two rules cannot drift apart
    from wd.ai import common

    assert all(bool(audio.HAN_RE.search(chr(cp))) == common.has_cjk(chr(cp)) for cp in range(0x10000))  # "a Han character" is what content validation calls CJK
    assert audio.ACCENTS == ("en-US", "en-GB") and audio.ZH == "zh-CN" and audio.LANGS == ("en-US", "en-GB", "zh-CN")
    # the language decides the rule: Chinese is still no English text, English alone is no Chinese text
    assert audio.normalize_text("你好") is None and audio.normalize_text("你好", "en-GB") is None and audio.normalize_text("hello", audio.ZH) is None


def test_choose_zh_voice_takes_the_best_tier_then_the_preference_order_and_never_an_eloquence_voice():
    voices = audio.parse_voices(ZH_LISTING)
    assert audio.choose_zh_voice(voices) == "Yu-shu (Premium)"  # the tier first: Lili leads the list but is only Enhanced here
    below_premium = [v for v in voices if v.tier < 2]
    assert audio.choose_zh_voice(below_premium) == "Lili (Enhanced)"  # inside a tier the preference order — not the alphabetically earlier Binbin …
    assert audio.choose_zh_voice(below_premium, speaks=lambda n: n != "Lili (Enhanced)") == "Binbin (Enhanced)"  # … which is still a candidate
    assert audio.parse_voices(ZH_LISTING)[2].tier == 1  # "Eddy (中文（中国大陆）)": a qualified name, so it would outrank every compact voice
    compact = [v for v in voices if not v.qualified or v.base == "Eddy"]
    assert audio.choose_zh_voice(compact) == "Lili" and audio.choose_zh_voice([v for v in compact if v.base != "Lili"]) == "Tingting"
    assert audio.choose_zh_voice(compact, speaks=lambda n: False) is None
    assert audio.choose_zh_voice([v for v in voices if v.lang != "zh_CN" or v.base == "Eddy"]) is None  # 台湾's Meijia, the English voices, Eloquence: none
    assert audio.choose_zh_voice([]) is None


def test_no_voice_crosses_languages():
    voices = audio.parse_voices(ZH_LISTING)
    chinese = [v for v in voices if v.lang.startswith("zh")]
    assert audio.choose_voice(chinese, "en-US") is None and audio.choose_voice(chinese, "en-GB") is None  # an English accent never gets a Chinese voice
    assert audio.choose_zh_voice([v for v in voices if v.lang.startswith("en")]) is None  # … nor Chinese an English one


def test_say_speaks_zh_goes_by_the_size_of_the_clip_not_by_the_unknown_name_comparison(test_env: dict[str, str], fake_say, monkeypatch: pytest.MonkeyPatch):
    """This Mac: `say` substitutes Tingting for a name it does not know, so the comparison of say_resolves calls the real Tingting
    unresolved. What a voice writes for Chinese text is the test — an English voice exits 0 with a header-only AIFF."""
    fakes = fake_say(ZH_LISTING, fallback="Tingting")
    cfg = make_settings(test_env, WD_AUDIO_PROVIDER="say")
    assert audio.say_resolves(cfg, "Tingting") is False  # byte for byte what the unknown name produced
    assert audio.say_speaks_zh(cfg, "Tingting") is True
    assert audio.say_speaks_zh(cfg, "Samantha") is False  # 4608 bytes of silence
    assert audio.say_speaks_zh(cfg, "Tingting") is True and audio.say_speaks_zh(cfg, "Samantha") is False
    assert zh_probes(fakes) == ["Tingting", "Samantha"]  # each voice once per process
    assert sorted(probes(fakes)) == sorted(["Tingting", audio.UNKNOWN_VOICE])  # the two probe texts are cached apart
    assert not list(cfg.tmp_dir.glob("audio-probe-*"))
    monkeypatch.setattr(audio, "SAY_BIN", str(fakes["say"].with_name("missing")))
    assert audio.say_speaks_zh(cfg, "Lili") is False  # a probe that fails is no voice


def test_say_voice_for_chinese_resolves_once_with_its_own_override(test_env: dict[str, str], fake_say, caplog: pytest.LogCaptureFixture):
    fakes = fake_say(ZH_LISTING, fallback="Tingting")
    cfg = make_settings(test_env, WD_AUDIO_PROVIDER="say")
    assert audio.speaks_zh(cfg) is True and zh_probes(fakes) == []  # not resolved yet: optimistic — and the flag never asks `say`
    with caplog.at_level(logging.INFO, logger="wd.audio"):
        assert audio.say_voice_for(cfg, audio.ZH) == "Yu-shu (Premium)"
        assert audio.say_voice_for(cfg, audio.ZH) == "Yu-shu (Premium)"
    assert zh_probes(fakes) == ["Yu-shu (Premium)"] and probes(fakes) == []  # one size probe, no comparison with the unknown name
    assert [r.getMessage() for r in caplog.records if getattr(r, "event", "") == "audio_voice_zh"] == ["say voice for zh-CN: Yu-shu (Premium)"]
    assert audio.speaks_zh(cfg) is True
    assert audio.say_voice_for(cfg, "en-US") == "Samantha" and audio.say_voice_for(cfg, "en-GB") == "Daniel"  # English as before
    # WD_AUDIO_SAY_VOICE is the English override and never speaks Chinese; WD_AUDIO_SAY_VOICE_ZH is the Chinese one and never speaks English
    english = make_settings(test_env, WD_AUDIO_PROVIDER="say", WD_AUDIO_SAY_VOICE="Daniel")
    assert audio.say_voice_for(english, audio.ZH) == "Yu-shu (Premium)" and audio.say_voice_for(english, "en-US") == "Daniel"
    chinese = make_settings(test_env, WD_AUDIO_PROVIDER="say", WD_AUDIO_SAY_VOICE_ZH=" Tingting ")
    assert chinese.audio_say_voice_zh == "Tingting" and {e["key"]: e["value"] for e in chinese.entries()}["WD_AUDIO_SAY_VOICE_ZH"] == "Tingting"
    assert audio.say_voice_for(chinese, audio.ZH) == "Tingting" and audio.say_voice_for(chinese, "en-US") == "Samantha" and audio.speaks_zh(chinese)
    assert audio.locate(chinese, audio.ZH, "月亮")[2] == "Tingting" and audio.locate(chinese, audio.ZH, "月亮")[0].path != audio.locate(cfg, audio.ZH, "月亮")[0].path
    assert audio.say_voice_for(make_settings(test_env, WD_AUDIO_PROVIDER="say", WD_AUDIO_SAY_VOICE_ZH="Meijia"), audio.ZH) == "Meijia"  # any listed Chinese voice that speaks will do (台湾's: zh_TW)


def test_a_chinese_override_must_be_a_listed_voice_that_speaks_chinese(test_env: dict[str, str], fake_say):
    fakes = fake_say(ZH_LISTING, fallback="Tingting")
    typo = make_settings(test_env, WD_AUDIO_PROVIDER="say", WD_AUDIO_SAY_VOICE_ZH="Tingtin")  # `say` would speak it — with its fallback voice, under the wrong key
    with pytest.raises(audio.AudioError) as e:
        audio.say_voice_for(typo, audio.ZH)
    assert e.value.reason == "failed" and "WD_AUDIO_SAY_VOICE_ZH='Tingtin'" in e.value.detail and "say -v '?'" in e.value.detail
    assert zh_probes(fakes) == []  # not in the listing: the size probe could not tell it from Tingting
    english = make_settings(test_env, WD_AUDIO_PROVIDER="say", WD_AUDIO_SAY_VOICE_ZH="Samantha")
    for _ in range(2):
        with pytest.raises(audio.AudioError) as e:  # lookup() raises the same error, so the router answers 503 failed
            audio.lookup(english, audio.ZH, "月亮")
        assert e.value.reason == "failed" and "WD_AUDIO_SAY_VOICE_ZH='Samantha'" in e.value.detail
    assert zh_probes(fakes) == []  # an en_US row: refused by the listing, so no request ever asks `say` — once or again
    assert audio.speaks_zh(typo) is False and audio.speaks_zh(english) is False
    assert audio.synthesize(english, "en-US", "farmer").path.is_file()  # English does not care
    assert audio.say_voice_for(english, "en-GB") == "Daniel" and audio.voice_key(english) == hashlib.sha256(b"say\n\nSamantha\nDaniel\n").hexdigest()[:8]  # … and settled: an empty name, not the placeholder


def test_a_chinese_override_is_never_an_eloquence_row_or_an_english_voice_that_makes_noise(test_env: dict[str, str], fake_say):
    """Measured on this Mac: `say -v 'Eddy (中文（中国大陆）)'` — a zh_CN row of the listing, like the seven other Eloquence names — is
    not resolved and comes out as Tingting, byte for byte; and the classic en_US voices (Fred, Albert, Kathy) do not write silence
    for Chinese text but 8–11 s of noise. Both pass the size probe, so the listing row decides before it: the override must be a
    Chinese voice and no Eloquence one — else Tingting's clips under another voice's key, or noise for a gloss."""
    fakes = fake_say(ZH_LISTING + "Fred                en_US    # Hello! My name is Fred.\n", fallback="Tingting", noisy=("Fred",))
    probe = make_settings(test_env, WD_AUDIO_PROVIDER="say")
    assert audio.say_speaks_zh(probe, "Eddy (中文（中国大陆）)") is True and audio.say_speaks_zh(probe, "Fred") is True  # the size probe alone lets both through
    audio.reset_voice_cache()
    fakes["calls"].unlink()
    for name in ("Eddy (中文（中国大陆）)", "Fred"):
        cfg = make_settings(test_env, WD_AUDIO_PROVIDER="say", WD_AUDIO_SAY_VOICE_ZH=name)
        for ask in (lambda: audio.say_voice_for(cfg, audio.ZH), lambda: audio.lookup(cfg, audio.ZH, "月亮")):  # the router's path: 503 failed
            with pytest.raises(audio.AudioError) as e:
                ask()
            assert e.value.reason == "failed" and f"WD_AUDIO_SAY_VOICE_ZH={name!r}" in e.value.detail and "Eloquence" in e.value.detail
        assert audio.speaks_zh(cfg) is False
    assert zh_probes(fakes) == [] and calls(fakes) == []  # refused by their rows: neither was asked to speak
    # the Chinese voices of the other regions stay eligible — the rule is "a zh_… row", not "zh_CN"
    assert audio.say_voice_for(make_settings(test_env, WD_AUDIO_PROVIDER="say", WD_AUDIO_SAY_VOICE_ZH="Meijia"), audio.ZH) == "Meijia" and zh_probes(fakes) == ["Meijia"]


def test_a_mac_without_a_chinese_voice_is_a_settled_none(test_env: dict[str, str], fake_say, caplog: pytest.LogCaptureFixture):
    fakes = fake_say("Daniel              en_GB    # Hello! My name is Daniel.\nEddy (中文（中国大陆）)     zh_CN    # 你好！我叫Eddy。\nMeijia              zh_TW    # 你好，我叫美佳。\nSamantha            en_US    # Hello! My name is Samantha.\n")
    cfg = make_settings(test_env, WD_AUDIO_PROVIDER="say")
    before = audio.voice_key(cfg)
    with caplog.at_level(logging.INFO, logger="wd.audio"):
        audio.warm_up(cfg)
    assert [getattr(r, "event", "") for r in caplog.records] == ["audio_voice", "audio_voice", "audio_voice_zh_missing"]
    missing = caplog.records[-1]
    assert missing.levelno == logging.INFO and "no Chinese voice" in missing.getMessage() and "Spoken Content" in missing.getMessage() and "WD_AUDIO_SAY_VOICE_ZH" in missing.getMessage()
    settled = audio.voice_key(cfg)
    assert settled == hashlib.sha256(b"say\n\nSamantha\nDaniel\n").hexdigest()[:8] and settled != before  # an empty name, not the placeholder of an unresolved voice
    for _ in range(2):
        with pytest.raises(audio.AudioError) as e:
            audio.lookup(cfg, audio.ZH, "月亮")
        assert e.value.reason == "failed" and "no Chinese voice" in e.value.detail and "月亮" not in e.value.detail
    assert audio.voice_key(cfg) == settled and audio.speaks_zh(cfg) is False  # the browsers' clip URLs stay put
    assert zh_probes(fakes) == []  # Eloquence is no candidate and Meijia is zh_TW: nothing to probe, now or later
    assert audio.synthesize(cfg, "en-US", "farmer").path.read_bytes().startswith(b"Samantha:farmer")


def test_a_listing_that_cannot_be_read_is_no_verdict_about_chinese(test_env: dict[str, str], fakes: dict[str, Path], monkeypatch: pytest.MonkeyPatch):
    cfg = make_settings(test_env, WD_AUDIO_PROVIDER="say")
    monkeypatch.setattr(audio, "SAY_BIN", str(fakes["say"].with_name("missing")))
    with pytest.raises(audio.AudioError) as e:
        audio.say_voice_for(cfg, audio.ZH)
    assert e.value.reason == "failed" and "lists no voices" in e.value.detail
    assert audio.speaks_zh(cfg) is True  # no verdict either way: the flag stays optimistic, the request above answered 503 failed
    monkeypatch.setattr(audio, "SAY_BIN", str(fakes["say"]))
    monkeypatch.setattr(audio, "VOICES_RETRY_S", 0.0)
    assert audio.say_voice_for(cfg, audio.ZH) == "Ting-Ting" and audio.speaks_zh(cfg) is True  # nothing was remembered against it


def test_speaks_zh_is_optimistic_until_the_chinese_voice_is_resolved_and_never_runs_say(test_env: dict[str, str], fake_say, monkeypatch: pytest.MonkeyPatch):
    """`ServerFlags.audio_zh` in the 2–3 s after a start, before the warm-up has got to the Chinese voice. A page reads `/me` once and
    keeps the flag for its session, and the HarmonyOS tablet has no voice of its own: a False in that window was a session without
    Chinese. So "not resolved yet" reads True — unless the listing this process already holds says there is no voice to resolve —,
    and whoever then asks for a Chinese clip resolves the voice in that request. The flag itself spawns nothing."""
    fakes = fake_say(ZH_LISTING, fallback="Tingting")
    by_listing = make_settings(test_env, WD_AUDIO_PROVIDER="say")
    named = make_settings(test_env, WD_AUDIO_PROVIDER="say", WD_AUDIO_SAY_VOICE_ZH="Tingting")
    refused = [make_settings(test_env, WD_AUDIO_PROVIDER="say", WD_AUDIO_SAY_VOICE_ZH=name) for name in ("Tingtin", "Samantha", "Eddy (中文（中国大陆）)")]

    def no_child(*args, **kwargs):
        pytest.fail("speaks_zh ran a child process")

    with monkeypatch.context() as m:
        m.setattr(audio, "_spawn", no_child)
        assert all(audio.speaks_zh(cfg) is True for cfg in (by_listing, named, *refused))  # nothing is known yet: nobody is told "no Chinese"
    assert len(audio.say_voices()) == 9  # the warm-up has read the listing (the English accents come first) — the Chinese choice is still open
    with monkeypatch.context() as m:
        m.setattr(audio, "_spawn", no_child)
        assert audio.speaks_zh(by_listing) is True and audio.speaks_zh(named) is True  # a zh_CN voice to probe, the named one among them
        assert [audio.speaks_zh(cfg) for cfg in refused] == [False, False, False]  # the listing settles these before any probe: unlisted, English, Eloquence
    assert zh_probes(fakes) == [] and calls(fakes) == []
    # resolved: the answer is the choice — a name, or the settled "none" when the candidate does not speak after all
    assert audio.say_voice_for(named, audio.ZH) == "Tingting" and audio.speaks_zh(named) is True
    monkeypatch.setattr(audio, "SILENT_AIFF_BYTES", 1 << 20)  # from here on no candidate's probe clip counts as speech
    with pytest.raises(audio.AudioError, match="no Chinese voice"):
        audio.say_voice_for(by_listing, audio.ZH)
    assert audio.speaks_zh(by_listing) is False and audio.speaks_zh(named) is True


def test_speaks_zh_reads_the_cached_listing_of_a_mac_without_a_chinese_voice(test_env: dict[str, str], fake_say):
    fakes = fake_say("Daniel              en_GB    # Hello! My name is Daniel.\nEddy (中文（中国大陆）)     zh_CN    # 你好！我叫Eddy。\nMeijia              zh_TW    # 你好，我叫美佳。\nSamantha            en_US    # Hello! My name is Samantha.\n")
    cfg = make_settings(test_env, WD_AUDIO_PROVIDER="say")
    taiwan = make_settings(test_env, WD_AUDIO_PROVIDER="say", WD_AUDIO_SAY_VOICE_ZH="Meijia")
    assert audio.speaks_zh(cfg) is True and audio.speaks_zh(taiwan) is True  # before the listing: optimistic
    assert audio.say_voice_for(cfg, "en-US") == "Samantha"  # the first English request (or the warm-up) reads the listing …
    assert audio.speaks_zh(cfg) is False  # … and it has no zh_CN voice but an Eloquence one: no need to wait for the Chinese resolution
    assert audio.speaks_zh(taiwan) is True  # named, 台湾's voice is a candidate
    assert zh_probes(fakes) == []
    assert audio.voice_key(cfg) != hashlib.sha256(b"say\n\nSamantha\nDaniel\n").hexdigest()[:8]  # the fingerprint still waits for the resolution itself


def test_speaks_zh_never_waits_for_a_listing_in_flight(test_env: dict[str, str], fake_say):
    """say_voices holds its lock across `say -v '?'` (0.4 s on this Mac, SAY_TIMEOUT_S at worst): `/me` must not queue behind it."""
    fake_say(ZH_LISTING, fallback="Tingting")
    cfg = make_settings(test_env, WD_AUDIO_PROVIDER="say")
    answers: list[bool] = []
    asker = threading.Thread(target=lambda: answers.append(audio.speaks_zh(cfg)), daemon=True)
    with audio._voices_lock:  # the warm-up thread is inside the listing
        asker.start()
        asker.join(timeout=5)
        assert not asker.is_alive() and answers == [True]


def test_warm_up_resolves_the_chinese_voice_after_the_accents_and_without_them(test_env: dict[str, str], fake_say, caplog: pytest.LogCaptureFixture):
    fakes = fake_say(LISTING)
    cfg = make_settings(test_env, WD_AUDIO_PROVIDER="say")
    with caplog.at_level(logging.INFO, logger="wd.audio"):
        audio.warm_up(cfg)
    assert [(getattr(r, "event", ""), r.getMessage()) for r in caplog.records] == [
        ("audio_voice", "say voice for en-US: Ava (Premium)"),
        ("audio_voice", "say voice for en-GB: Stephanie (Premium)"),
        ("audio_voice_zh", "say voice for zh-CN: Ting-Ting"),
    ]
    assert audio.speaks_zh(cfg) is True and zh_probes(fakes) == ["Ting-Ting"]
    assert audio.lookup(cfg, audio.ZH, "月亮") is None and zh_probes(fakes) == ["Ting-Ting"]  # the request path pays no probe
    # a Mac with a Chinese voice only: English fails as loudly as before, Chinese is served all the same
    fake_say("Tingting            zh_CN    # 你好！我叫婷婷。\n", fallback="Tingting")
    audio.warm_up(cfg)
    assert audio.speaks_zh(cfg) is True and audio.say_voice_for(cfg, audio.ZH) == "Tingting"
    with pytest.raises(audio.AudioError) as e:
        audio.say_voice_for(cfg, "en-US")
    assert "no English voice" in e.value.detail


def test_chinese_clips_are_made_by_the_chinese_voice_under_their_own_key(test_env: dict[str, str], fakes: dict[str, Path]):
    cfg = make_settings(test_env, WD_AUDIO_PROVIDER="say")
    assert audio.lookup(cfg, audio.ZH, "月亮") is None
    clip = audio.synthesize(cfg, audio.ZH, "月亮")
    assert clip.media_type == "audio/mp4" and clip.path.name == hashlib.sha256("say\nTing-Ting\nzh-CN\n月亮".encode()).hexdigest() + ".m4a"
    assert clip.path.read_bytes().startswith("Ting-Ting:月亮".encode()) and clip.path.stat().st_size >= audio.SILENT_AIFF_BYTES
    assert stat.S_IMODE(clip.path.stat().st_mode) == 0o600 and calls(fakes) == ["Ting-Ting|月亮"]
    assert audio.synthesize(cfg, audio.ZH, "月亮") == clip == audio.lookup(cfg, audio.ZH, "月亮") and calls(fakes) == ["Ting-Ting|月亮"]  # a hit spawns nothing
    assert audio.synthesize(cfg, "en-US", "moon").path.read_bytes().startswith(b"Ava (Premium):moon")  # the accents keep their voices
    assert [p.name for p in clip.path.parent.iterdir() if p.name.endswith((".tmp", ".aiff"))] == []


def test_a_silent_chinese_clip_is_refused_and_never_cached(test_env: dict[str, str], fakes: dict[str, Path]):
    """The Chinese voice was removed after the probe: `say` substitutes its fallback voice, exits 0 and writes a header-only AIFF —
    whose AAC passes MIN_CLIP_BYTES. The floor on the AIFF keeps the silence out of the cache."""
    cfg = make_settings(test_env, WD_AUDIO_PROVIDER="say")
    assert audio.say_voice_for(cfg, audio.ZH) == "Ting-Ting"
    fakes["listing"].write_text("".join(line for line in LISTING.splitlines(keepends=True) if not line.startswith("Ting-Ting")), encoding="utf-8")
    with pytest.raises(audio.AudioError) as e:
        audio.synthesize(cfg, audio.ZH, "月亮")
    assert e.value.reason == "failed" and e.value.detail.startswith("silent clip") and "4608 bytes" in e.value.detail and "月亮" not in e.value.detail
    assert audio.lookup(cfg, audio.ZH, "月亮") is None
    assert not list(cfg.audio_dir.rglob("*.m4a")) and not list(cfg.audio_dir.rglob("*.tmp")) and not list(cfg.audio_dir.rglob("*.aiff"))
    # the same header-only file from an English voice given Chinese: without the floor it converts into a "clip" MIN_CLIP_BYTES accepts
    out = cfg.tmp_dir / "silence.m4a"
    audio._say("月亮", "Samantha", out)
    assert out.stat().st_size >= audio.MIN_CLIP_BYTES
    out.unlink()
    with pytest.raises(audio.AudioError, match="silent clip"):
        audio._say("月亮", "Samantha", out, min_aiff=audio.SILENT_AIFF_BYTES)
    assert not out.exists() and not list(cfg.tmp_dir.glob("*.aiff"))
    assert audio.synthesize(cfg, "en-US", "a").path.is_file()  # English has no floor: a short word's clip is short


def test_chinese_under_the_other_providers_is_missing_or_failed_never_a_key_error(test_env: dict[str, str], tmp_path: Path, fakes: dict[str, Path]):
    cache = make_settings(test_env, WD_AUDIO_PROVIDER="cache", WD_AUDIO_CACHE_VOICES="en-US=Ava (Premium);en-GB=Stephanie (Premium)")
    for call in (audio.locate, audio.lookup, audio.synthesize):
        with pytest.raises(audio.AudioError) as e:
            call(cache, audio.ZH, "月亮")
        assert e.value.reason == "missing"  # the mirror holds English clips only: this text's clip is simply not there
    for cfg in (make_settings(test_env, **bailian_env(tmp_path)), make_settings(test_env, WD_AUDIO_PROVIDER="youdao")):
        for call in (audio.locate, audio.lookup, audio.synthesize):
            with pytest.raises(audio.AudioError) as e:
                call(cfg, audio.ZH, "月亮")
            assert e.value.reason == "failed" and "no Chinese voice" in e.value.detail
        assert audio.speaks_zh(cfg) is False
    off = make_settings(test_env, WD_AUDIO_PROVIDER="off")
    with pytest.raises(audio.AudioError) as e:
        audio.locate(off, audio.ZH, "月亮")
    assert e.value.reason == "off" and audio.speaks_zh(off) is False and audio.speaks_zh(cache) is False
    assert calls(fakes) == [] and zh_probes(fakes) == []  # nobody asked `say`


def test_cli_audio_voices_and_audio_probe_know_the_chinese_voice(test_env: dict[str, str], fake_say, tmp_path: Path, capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch):
    """DEPLOY §9: `wd audio-voices` ends with the Chinese voice (none is not an error) and `wd audio-probe --accent zh-CN` makes one
    Chinese clip — the check after downloading a voice or setting WD_AUDIO_SAY_VOICE_ZH."""
    from wd import cli

    fakes = fake_say(ZH_LISTING, fallback="Tingting")
    monkeypatch.setenv("WD_AUDIO_PROVIDER", "say")
    assert cli.main(["audio-voices"]) == 0
    out = capsys.readouterr().out
    assert "en-US → Samantha" in out and "en-GB → Daniel" in out
    assert out.rstrip().splitlines()[-1] == "zh-CN → Yu-shu (Premium) (the best installed zh_CN voice; WD_AUDIO_SAY_VOICE_ZH overrides)"
    assert cli.main(["audio-probe", "--accent", "zh-CN"]) == 0
    assert "audio-probe: provider say, zh-CN → Yu-shu (Premium), 8 chars → " in capsys.readouterr().out and calls(fakes) == ["Yu-shu (Premium)|今晚的月亮很亮。"]
    assert cli.main(["audio-probe", "--accent", "zh-CN", "你好"]) == 0
    assert "zh-CN → Yu-shu (Premium), 2 chars → " in capsys.readouterr().out
    assert cli.main(["audio-probe", "--accent", "zh-CN", "hello"]) == 2
    err = capsys.readouterr().err
    assert "text rule refuses" in err and "at least one Chinese character" in err
    monkeypatch.setenv("WD_AUDIO_SAY_VOICE_ZH", "Tingting")
    assert cli.main(["audio-voices"]) == 0
    assert capsys.readouterr().out.rstrip().splitlines()[-1] == "zh-CN → Tingting (WD_AUDIO_SAY_VOICE_ZH)"
    monkeypatch.setenv("WD_AUDIO_SAY_VOICE_ZH", "Samantha")
    assert cli.main(["audio-voices"]) == 0  # English resolves: a Mac without a Chinese voice is no failure
    last = capsys.readouterr().out.rstrip().splitlines()[-1]
    assert last.startswith("zh-CN → none: WD_AUDIO_SAY_VOICE_ZH='Samantha' is not an installed voice that speaks Chinese") and "磨耳朵" in last
    assert cli.main(["audio-probe", "--accent", "zh-CN"]) == 1
    assert "wd audio-probe: say failed — failed: WD_AUDIO_SAY_VOICE_ZH='Samantha'" in capsys.readouterr().err
    monkeypatch.delenv("WD_AUDIO_SAY_VOICE_ZH")
    # the other providers have no Chinese clips: the line says so, the probe fails with the reason
    monkeypatch.setenv("WD_AUDIO_PROVIDER", "cache")
    monkeypatch.setenv("WD_AUDIO_CACHE_VOICES", "en-US=Samantha;en-GB=Daniel")
    assert cli.main(["audio-voices"]) == 0
    assert capsys.readouterr().out.rstrip().splitlines()[-1].startswith("zh-CN → none: cache has no Chinese clips yet")
    assert cli.main(["audio-probe", "--accent", "zh-CN"]) == 1
    assert "cache failed — missing:" in capsys.readouterr().err
    monkeypatch.setenv("WD_AUDIO_PROVIDER", "youdao")
    assert cli.main(["audio-voices"]) == 0
    assert capsys.readouterr().out.rstrip().splitlines()[-1].startswith("zh-CN → none: youdao has no Chinese clips yet")
    for key, value in bailian_env(tmp_path).items():
        monkeypatch.setenv(key, value)
    assert cli.main(["audio-voices"]) == 0
    assert "\nzh-CN → none: bailian has no Chinese clips yet" in capsys.readouterr().out
    assert cli.main(["audio-probe", "--accent", "zh-CN"]) == 1  # no request leaves the box: there is no Chinese voice to ask for
    assert "bailian failed — failed: bailian has no Chinese voice" in capsys.readouterr().err
    monkeypatch.setenv("WD_AUDIO_PROVIDER", "off")
    assert cli.main(["audio-voices"]) == 0
    assert "zh-CN" not in capsys.readouterr().out
