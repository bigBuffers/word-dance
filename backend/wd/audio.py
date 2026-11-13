"""Pronunciation clips for clients without an English voice (API.md endpoint 76, DESIGN §9 「Pronunciation clips」, FRONTEND §6.4).

The browser speaks with the Web Speech API and the mobile shell with the system TTS, but neither exists everywhere: Android's
WebView has no ``speechSynthesis``, the Android compatibility container of HarmonyOS NEXT (the family's Huawei tablet) has no TTS
engine the plugin can reach, and many domestic ROMs have no English voice. ``GET /media/audio?text=…&accent=en-US|en-GB|zh-CN``
(``routers/audio.py``) therefore serves a short clip synthesised **once** on the server and cached under
``$WD_DATA_DIR/audio/<2hex>/<sha256>.m4a|.mp3`` — the key is provider + voice + accent + text, so deleting the directory only
costs a re-synthesis. The cache is bounded by ``WD_AUDIO_CACHE_MB`` (least recently played clips go first; a served clip is touched).

Providers (``WD_AUDIO_PROVIDER``, DEPLOY §4):

* ``say`` — macOS only: ``/usr/bin/say -v <voice> -o clip.aiff`` (the text on stdin, never an argument) then
  ``/usr/bin/afconvert -f m4af -d aac -b 48000`` (≈ 8 KB per word; ``say``'s own m4a output carries 30 KB of container
  overhead). The voice is ``WD_AUDIO_SAY_VOICE`` or the best installed one of :data:`PREFERRED_VOICES` for the accent
  (:func:`choose_voice`: Premium > Enhanced > compact). ``say`` exits 0 for a voice name it cannot resolve and silently
  substitutes a fixed fallback voice, so every candidate is **probed** once per process (:func:`say_resolves`) before it is used
  and cached — a misspelt override is a 503 ``failed`` with the reason in the log, never clips in another voice.
  **Chinese** (``accent=zh-CN``, :data:`ZH` — the gloss and the translated sentence 磨耳朵 reads out, API.md 123; the HarmonyOS
  tablet has no voice of its own, so the server must speak them) is `say` only so far and keeps to itself: its own text rule
  (:data:`ZH_TEXT_RE`, at least one Han character), its own voice (``WD_AUDIO_SAY_VOICE_ZH`` — a listed Chinese voice, no
  Eloquence one — or :func:`choose_zh_voice`, never an English voice and never the other way round) and its own probe — an English voice given Chinese exits 0 and writes a
  header-only AIFF of silence, and on a zh-CN Mac the fallback voice of the comparison above *is* the Chinese voice, so a
  candidate counts when its AIFF for :data:`ZH_PROBE_TEXT` reaches :data:`SILENT_AIFF_BYTES` (:func:`say_speaks_zh`); the same
  floor guards every Chinese synthesis, so silence is never cached. A Mac without a Chinese voice is a settled "none":
  ``ServerFlags.audio_zh`` (:func:`speaks_zh`) is false, the requests answer 503 ``failed``, English is untouched. Until the
  voice is resolved — the seconds of the warm-up — the flag is optimistic: a page keeps it for its whole session.
* ``youdao`` — ``https://dict.youdao.com/dictvoice?audio=<text>&type=2|1`` (US / UK), the unofficial endpoint Chinese dictionary
  apps have used for years; opt-in because its terms are not published and every uncached text is sent to it. mp3.
* ``bailian`` — 阿里云百炼 CosyVoice / Qwen-Audio TTS over its synchronous HTTP API (slice server-audio-2): ``POST`` the text to
  ``WD_BAILIAN_TTS_URL`` (``https://{WorkspaceId}.{region}.maas.aliyuncs.com/api/v1/services/audio/tts/SpeechSynthesizer``) with the
  model ``WD_BAILIAN_TTS_MODEL`` and the accent's voice from ``WD_BAILIAN_TTS_VOICES``, then fetch the pre-signed OSS URL the answer
  names — over https, with a separate anonymous client, so the API key (the first line of the 0600 ``WD_BAILIAN_API_KEY_FILE``, read
  at call time) never reaches OSS. mp3 24 kHz. Why it exists: the macOS SLA keeps the ``say`` voices personal and non-commercial, so a
  public deployment (or any Linux server) needs a licensed cloud voice; 1 元 per 10 000 characters with ``cosyvoice-v3-flash``. 429 /
  5xx answers are ``busy`` (the client retries later), 4xx and malformed answers ``failed``; consecutive POSTs are paced
  :data:`BAILIAN_PACE_S` apart (≤ 150 RPM under the documented 180). The owner opts in explicitly — ``auto`` never picks it.
* ``off`` — the endpoint answers 503 ``audio_unavailable`` ``{reason: "off"}`` and the clients keep whatever voice they have.
* ``cache`` — read-only: serves the ``say`` clips another host synthesised (the same content-addressed names, that host's voices
  named in ``WD_AUDIO_CACHE_VOICES``); a text without a clip is 503 ``{reason: "missing"}`` and the client falls back to the
  device's own voice. The loop that fills it: ``wd audio-texts`` on this host → ``wd audio-prewarm --texts FILE`` on the host with
  ``say`` → ``rsync`` of ``audio/`` back (DEPLOY §9, ops.md §5). This is how a Linux server plays the Mac's Ava / Serena clips.
* ``auto`` (the default) — ``say`` when ``/usr/bin/say`` exists (the Mac that hosts the family instance), else ``off``.

Synthesis goes through :data:`SLOTS` semaphore slots (a stampede of cache misses must not fork twenty ``say`` processes); at
most :data:`MAX_WAITERS` requests wait for a slot (each pins a threadpool thread), a slot not obtained within :data:`SLOT_WAIT_S`
is ``AudioError('busy')``, a provider error ``AudioError('failed')``.

Two things keep the first tap fast: :func:`warm_up_async` (startup) resolves the voices — the listing and the probes, 1–3 s —
before anyone asks, and ``wd audio-prewarm`` (:func:`register_cli`) synthesises the clips of the study path (headwords with
content or in a bank and their example sentences, in learning order) ahead of time — anything else is made at the tap; ``wd audio-voices`` shows what ``say`` lists, what resolves
and what each accent — and Chinese — gets; ``wd audio-probe`` synthesises one clip through the provider in force (the day-0 check of a 百炼 key).
Another process adding or removing clips (that CLI next to the live service) is harmless: a clip
appears atomically under its content-addressed name, and the running total behind the cap is re-counted from disk every
:data:`SCAN_INTERVAL_S` when a clip is added.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import logging
import os
import re
import signal
import sqlite3
import stat
import subprocess
import sys
import threading
from urllib.parse import urlsplit
import time
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable, Iterable, Iterator

import httpx

from . import __version__
from .config import ConfigError, Settings, ensure_dirs

log = logging.getLogger("wd.audio")

ACCENTS: tuple[str, ...] = ("en-US", "en-GB")
ZH = "zh-CN"  # the one language next to the English accents: the Chinese gloss and the translated sentence 磨耳朵 reads out (API.md 123)
# every value `accent` takes on endpoint 76. ACCENTS stays "the English accents": user_settings.accent, the prewarm commands,
# WD_AUDIO_CACHE_VOICES and WD_BAILIAN_TTS_VOICES know those two only — Chinese is spoken by `say` alone so far
LANGS: tuple[str, ...] = (*ACCENTS, ZH)
MAX_TEXT_CHARS = 300  # above the 240 chars an example sentence may have (ai/content.py EXAMPLE_EN_MAX)
# one word, a phrase or an example sentence: Latin letters (the accented ones of café / naïve included), digits, spaces and the
# punctuation an English sentence carries — straight and typographic quotes, hyphen / en dash / em dash, ellipsis, $ % & @ /.
# Nothing else reaches a provider. The text never becomes an argument (stdin for `say`, an encoded query parameter for youdao);
# refusing a leading hyphen is defence in depth only.
TEXT_RE = re.compile(r"^(?!-)[A-Za-zÀ-ɏ0-9 '’‘“”\"\-–—….,;:!?()/&%$@]+$")
# a Chinese gloss or the translation of an example sentence (`accent=zh-CN`): Han characters (the ranges of ai/common.CJK_RE), the
# full-width punctuation of a Chinese sentence — ， 。 ！ ？ ； ： 、 （ ） 《 》 「 」 『 』 【 】 ～ · —, six symbols of a quantity — ℃ ° ％ ￥ ¥ 〇:
# the Chinese voice reads each as the word it stands for (measured with Tingting: 「30℃」 is byte for byte 「30摄氏度」, 「￥20」 is
# 「20元」, 「二〇〇八年」 is 「二零零八年」) and a translation carrying one would otherwise be dropped whole, while `+` `=` `~` are not read
# that way (「A+」 comes out as 「A」) and stay refused — and everything TEXT_RE lets through (a translation carries `Tom`, `GDP`,
# digits; … — “ ” ‘ ’ are in that class already), with at least one Han character (HAN_RE; 〇 is none): a text
# without any belongs to an English voice. The compatibility ideographs are spelled as escapes on purpose: a tool that NFC-normalises
# this file turns the literal U+F900 into U+8C48 and the range into one that swallows Hangul (test_audio.py pins both rules)
ZH_TEXT_RE = re.compile(r"^(?!-)[㐀-䶿一-鿿\uf900-\ufaff，。！？；：、（）《》「」『』【】～·℃°％￥¥〇A-Za-zÀ-ɏ0-9 '’‘“”\"\-–—….,;:!?()/&%$@]+$")
HAN_RE = re.compile(r"[㐀-䶿一-鿿\uf900-\ufaff]")

SAY_BIN = "/usr/bin/say"
AFCONVERT_BIN = "/usr/bin/afconvert"
SAY_TIMEOUT_S = 30
STDERR_EXCERPT_CHARS = 300
AAC_BITRATE = "48000"
YOUDAO_URL = "https://dict.youdao.com/dictvoice"
YOUDAO_TIMEOUT_S = 10.0
YOUDAO_TYPE = {"en-US": "2", "en-GB": "1"}
YOUDAO_MAX_BYTES = 2 * 1024 * 1024  # a sentence is ≈ 100 KB of mp3; anything bigger is not a clip
# 阿里云百炼 cloud TTS (provider `bailian`): the synchronous SpeechSynthesizer POST answers a pre-signed OSS URL (24 h) of the clip
BAILIAN_TIMEOUT_S = 15.0  # the synthesis POST (a sentence synthesises in well under a second; the budget covers a slow peak)
BAILIAN_DOWNLOAD_TIMEOUT_S = 15.0  # the OSS download of the clip
BAILIAN_DOWNLOAD_HOST_SUFFIX = ".aliyuncs.com"  # the pre-signed clip URLs live on 阿里云 OSS (dashscope-result-*.oss-*.aliyuncs.com); anything else is refused
BAILIAN_MAX_BYTES = 4 * 1024 * 1024  # a 300-char sentence is ≈ 200 KB of mp3 at 24 kHz; anything bigger is not a clip
BAILIAN_FORMAT = "mp3"
BAILIAN_SAMPLE_RATE = 24000
BAILIAN_RPM = 180  # the documented limit per model and account (cosyvoice-v3-flash, qwen-audio-3.1-tts-*)
BAILIAN_PACE_S = 0.4  # consecutive POSTs ≥ this apart across this process (wd audio-prewarm's two workers) → ≤ 150 RPM, under BAILIAN_RPM
BAILIAN_PRICE_CNY_PER_10K_CHARS = {  # 北京 list prices (元 / 万字符) for the `wd audio-prewarm --dry-run` estimate; qwen-audio-3.1-tts-flash is billed per token and is absent
    "cosyvoice-v3-flash": 1.0,
    "cosyvoice-v3-plus": 2.0,
    "cosyvoice-v2": 2.0,
    "qwen-audio-3.1-tts-plus": 1.4,
    "qwen-audio-3.0-tts-flash": 1.0,
    "qwen-audio-3.0-tts-plus": 1.4,
}
BAILIAN_MESSAGE_CHARS = 80  # of the provider's `message` in an AudioError detail (never the key, never the OSS URL)
MIN_CLIP_BYTES = 256  # anything shorter is an error page or an empty file, not audio
SLOTS = 2
SLOT_WAIT_S = 8.0
MAX_WAITERS = 6
VOICES_RETRY_S = 60.0  # a failing `say -v ?` is not re-run on every request
SCAN_INTERVAL_S = 300.0  # the running total of cached bytes is re-counted from disk this often (another process may add or remove clips)
WARM_UP_JOIN_S = 10.0  # how long shutdown / a test teardown waits for the warm-up thread
YOUDAO_PAUSE_S = 0.5  # between two bulk requests to the unofficial endpoint (wd audio-prewarm)
PROBE_TEXT = "hello"
UNKNOWN_VOICE = "wd-no-such-voice-7f3a"  # what `say` falls back to for this name is what it falls back to for any unknown name
ZH_PROBE_TEXT = "你好，世界"  # what a candidate Chinese voice is asked to speak (say_speaks_zh)
# measured on macOS 26: an English voice given Chinese text exits 0 and writes a 4608-byte AIFF of silence (Ava (Premium) on 「月亮」),
# Tingting writes 62 KB for ZH_PROBE_TEXT, and the shortest real clips are 17–19 KB (「好」, "a") — anything under this is no speech
SILENT_AIFF_BYTES = 8192

# `say` voices by base name in order of preference per accent. Of one base name the best installed tier wins — "(Premium)" over
# "(Enhanced)" over the compact voice (the tier label may be localised on some systems — "(高级)" / "(增强)" —; this zh-CN macOS 26
# host prints English tiers; `_PREMIUM_RE` accepts both). The Eloquence voices (Eddy, Flo, Reed,
# Rocko, Sandy, Shelley, Grandma, Grandpa) and the novelty ones (Albert, Bad News, Bells …) are never chosen: better no clip
# than a joke.
PREFERRED_VOICES: dict[str, tuple[str, ...]] = {
    "en-US": ("Ava", "Zoe", "Allison", "Samantha", "Nicky", "Joelle", "Evan", "Tom", "Alex"),
    "en-GB": ("Serena", "Kate", "Stephanie", "Jamie", "Oliver", "Daniel"),
}
VOICE_LANG = {"en-US": "en_US", "en-GB": "en_GB"}
# Chinese (`accent=zh-CN`) has its own rule (choose_zh_voice) and never shares a voice with an English accent in either direction:
# of the zh_CN voices `say` lists the best tier wins, then this order, then the name. Tingting is the compact voice macOS ships with
# — and, on a zh-CN system, the voice `say` substitutes for a name it does not know, which is why Chinese has its own probe
# (say_speaks_zh). The Eloquence voices exist in zh_CN too ("Eddy (中文（中国大陆）)", a qualified name that would outrank the compact
# Tingting by tier) and are never chosen here either.
ZH_VOICE_LANG = "zh_CN"
PREFERRED_ZH_VOICES: tuple[str, ...] = ("Lili", "Lilian", "Yu-shu", "Shanshan", "Tingting", "Ting-Ting")
ELOQUENCE_VOICES = frozenset({"Eddy", "Flo", "Reed", "Rocko", "Sandy", "Shelley", "Grandma", "Grandpa"})
MEDIA = {"say": ("m4a", "audio/mp4"), "youdao": ("mp3", "audio/mpeg"), "bailian": ("mp3", "audio/mpeg"), "cache": ("m4a", "audio/mp4")}  # cache mirrors say clips
CLIP_SUFFIXES = (".m4a", ".mp3")
MB = 1024 * 1024
_PREMIUM_RE = re.compile(r"premium|高级", re.IGNORECASE)


class AudioError(Exception):
    """No clip. ``reason``: ``off`` (no provider), ``busy`` (no synthesis slot in time), ``failed`` (provider error) or ``missing``
    (the read-only ``cache`` provider has no clip for this text)."""

    def __init__(self, reason: str, detail: str = ""):
        super().__init__(detail or reason)
        self.reason = reason
        self.detail = detail


@dataclass(frozen=True)
class Clip:
    path: Path
    media_type: str


@dataclass(frozen=True)
class Voice:
    name: str  # what `say -v` takes: "Samantha", "Samantha (Enhanced)", "Eddy (英语（美国）)"
    base: str  # "Samantha"
    lang: str  # "en_US"

    @property
    def qualified(self) -> bool:
        return self.name != self.base

    @property
    def tier(self) -> int:
        """2 for a Premium voice, 1 for any other qualified one (Enhanced …), 0 for the compact voice."""
        if not self.qualified:
            return 0
        return 2 if _PREMIUM_RE.search(self.name[len(self.base) :]) else 1


def normalize_text(text: str, lang: str = "en-US") -> str | None:
    """Whitespace-collapsed ``text`` when the providers may speak it, else None. ``lang`` picks the rule: :data:`TEXT_RE` for the
    English accents (the default — every caller that speaks English passes nothing), :data:`ZH_TEXT_RE` plus at least one Han
    character for :data:`ZH`."""
    spoken = " ".join(text.split())
    if not spoken or len(spoken) > MAX_TEXT_CHARS:
        return None
    if lang == ZH:
        return spoken if ZH_TEXT_RE.match(spoken) and HAN_RE.search(spoken) else None
    return spoken if TEXT_RE.match(spoken) else None


def provider_for(cfg: Settings) -> str:
    """``say`` / ``youdao`` / ``bailian`` / ``cache`` / ``off`` (``auto`` resolved, ``Settings.audio_provider_effective``)."""
    return cfg.audio_provider_effective


# ------------------------------------------------------------------------------------------------ voices
# "Samantha (增强)      en_US    # Hello! My name is Samantha." — the name is padded to a 20-column field, so a 19-character
# name is followed by ONE space; the language tag (xx_YY) and the `#` of the sample sentence anchor the end of the name
_VOICE_RE = re.compile(r"^(?P<name>\S.*?)\s+(?P<lang>[a-z]{2,3}_[A-Za-z0-9]+)\s*#")


def parse_voices(listing: str) -> list[Voice]:
    """The rows of ``say -v '?'`` as :class:`Voice` records."""
    voices: list[Voice] = []
    for line in listing.splitlines():
        m = _VOICE_RE.match(line)
        if not m:
            continue
        name = m.group("name").strip()
        voices.append(Voice(name=name, base=name.split(" (", 1)[0].strip(), lang=m.group("lang")))
    return voices


def choose_voice(voices: list[Voice], accent: str, resolves=lambda name: True) -> str | None:
    """The ``say -v`` name for ``accent``: the first preferred base name that is installed, its best tier first (Premium >
    Enhanced > compact), skipping names ``resolves`` rejects (the probe of :func:`say_resolves`); else the other accent's
    choice; else None."""
    for acc in (accent, *(a for a in ACCENTS if a != accent)):
        lang = VOICE_LANG[acc]
        for base in PREFERRED_VOICES[acc]:
            for v in sorted((v for v in voices if v.lang == lang and v.base == base), key=lambda v: (-v.tier, v.name)):
                if resolves(v.name):
                    return v.name
    return None


def choose_zh_voice(voices: list[Voice], speaks=lambda name: True) -> str | None:
    """The ``say -v`` name for Chinese (:data:`ZH`): of the installed zh_CN voices the best tier first (Premium > Enhanced >
    compact), inside a tier the order of :data:`PREFERRED_ZH_VOICES`, then the name — never an Eloquence voice, skipping names
    ``speaks`` rejects (the probe of :func:`say_speaks_zh`); else None. There is no fallback across languages: an English voice
    given Chinese writes silence, and a Chinese voice reading English is not what an accent setting asked for."""
    rank = {base: i for i, base in enumerate(PREFERRED_ZH_VOICES)}
    candidates = (v for v in voices if v.lang == ZH_VOICE_LANG and v.base not in ELOQUENCE_VOICES)
    for v in sorted(candidates, key=lambda v: (-v.tier, rank.get(v.base, len(rank)), v.name)):
        if speaks(v.name):
            return v.name
    return None


_voices_lock = threading.Lock()
_voices_cache: list[Voice] | None = None
_voices_failed_at = 0.0


def say_voices() -> list[Voice]:
    """``say -v '?'`` parsed, read once per process (a failure is logged and retried after :data:`VOICES_RETRY_S`)."""
    global _voices_cache, _voices_failed_at
    with _voices_lock:
        if _voices_cache is None:
            if time.monotonic() - _voices_failed_at < VOICES_RETRY_S:
                return []
            try:
                _voices_cache = parse_voices(_output([SAY_BIN, "-v", "?"]))
            except AudioError as e:
                _voices_failed_at = time.monotonic()
                log.error("say -v ? failed: %s", e.detail, extra={"event": "audio_voices_failed"})
                return []
        return list(_voices_cache)


_probe_lock = threading.Lock()
_probes: dict[tuple[str, str], bytes | None] = {}  # (voice name, probe text) → the AIFF `say -v <name>` produced for it (None: say failed)
_choice_lock = threading.Lock()
_choices: dict[str, str] = {}  # "<override>\n<accent>" → the resolved voice name; for ZH "" = resolved: no Chinese voice


def _probe(cfg: Settings, name: str, text: str = PROBE_TEXT) -> bytes | None:
    with _probe_lock:
        if (name, text) in _probes:
            return _probes[(name, text)]
    out = cfg.tmp_dir / f"audio-probe-{os.getpid()}-{threading.get_ident()}.aiff"
    try:
        _run([SAY_BIN, "-v", name, "-o", str(out)], stdin_text=text)
        data = out.read_bytes() if out.is_file() else None
    except AudioError as e:
        log.warning("say -v %r probe failed: %s", name, e.detail, extra={"event": "audio_voice_probe_failed"})
        data = None
    finally:
        out.unlink(missing_ok=True)
    with _probe_lock:
        _probes[(name, text)] = data
    return data


def say_resolves(cfg: Settings, name: str) -> bool:
    """Whether ``say -v name`` really speaks with that voice. ``say`` exits 0 for a name it cannot resolve and substitutes a
    fixed fallback voice, so the clip for :data:`PROBE_TEXT` is compared with the one for a name that certainly does not exist
    (both probes run once per process)."""
    mine = _probe(cfg, name)
    if mine is None:
        return False
    unknown = _probe(cfg, UNKNOWN_VOICE)
    return unknown is None or mine != unknown


def say_speaks_zh(cfg: Settings, name: str) -> bool:
    """Whether ``say -v name`` speaks Chinese: its AIFF for :data:`ZH_PROBE_TEXT` is a real clip (≥ :data:`SILENT_AIFF_BYTES`), not
    the header-only file an English voice writes for Chinese text while exiting 0. Deliberately not the comparison of
    :func:`say_resolves`: on a zh-CN system the voice `say` substitutes for an unknown name IS the Chinese voice (Tingting on
    this Mac), so the wanted voice and the bogus name produce the same bytes and that test would call it unresolved. Probed once
    per process and voice."""
    data = _probe(cfg, name, ZH_PROBE_TEXT)
    return data is not None and len(data) >= SILENT_AIFF_BYTES


def _no_zh_voice(cfg: Settings) -> AudioError:
    if cfg.audio_say_voice_zh:
        return AudioError(
            "failed",
            f"WD_AUDIO_SAY_VOICE_ZH={cfg.audio_say_voice_zh!r} is not an installed voice that speaks Chinese (compare `say -v '?'`: a zh_… row, and no Eloquence voice — `say` does not resolve those)",
        )
    return AudioError(
        "failed",
        "say has no Chinese voice (zh_CN); download one in System Settings → Accessibility → Spoken Content (then restart the service) or set WD_AUDIO_SAY_VOICE_ZH",
    )


def _zh_override(cfg: Settings, voices: list[Voice]) -> Voice | None:
    """The row `say` lists for ``WD_AUDIO_SAY_VOICE_ZH`` when it can be the Chinese voice: a ``zh_…`` voice (台湾's Meijia and 香港's
    Sinji read the text too) that is no Eloquence one — else None. The size probe cannot make this call (measured on macOS 26):
    `say` does not resolve the zh_CN Eloquence rows (``Eddy (中文（中国大陆）)`` …) and speaks them with its fallback voice — Tingting
    on a zh-CN Mac: real clips, under another voice's name and key —, and the classic en_US voices (Fred, Albert, Kathy) write
    8–11 s of noise for Chinese text where the newer ones write silence."""
    row = next((v for v in voices if v.name == cfg.audio_say_voice_zh), None)
    return row if row is not None and row.lang.startswith("zh") and row.base not in ELOQUENCE_VOICES else None


def _say_zh_voice(cfg: Settings) -> str:
    """:func:`say_voice_for` for :data:`ZH`: ``WD_AUDIO_SAY_VOICE_ZH`` when `say` lists that name as a Chinese voice other than an
    Eloquence one (:func:`_zh_override`) and it speaks Chinese (the listing stands in for the unknown-name comparison, which
    cannot tell a typo from the fallback voice here — and for the size probe where that one is fooled), else
    :func:`choose_zh_voice`. Having none is a **resolved** answer — the empty choice is remembered, so :func:`voice_key` settles,
    :func:`speaks_zh` reads false and no request probes again — and every call raises the same ``AudioError('failed')`` naming the
    remedy. Only a listing that could not be read is no answer yet (retried like the English one)."""
    key = f"{cfg.audio_say_voice_zh}\n{ZH}"
    with _choice_lock:
        hit = _choices.get(key)
    if hit is None:
        voices = say_voices()
        if not voices:
            raise AudioError("failed", "say lists no voices (`say -v '?'` failed or printed nothing — the reason is in the log)")
        if cfg.audio_say_voice_zh:
            row = _zh_override(cfg, voices)
            chosen = row.name if row is not None and say_speaks_zh(cfg, row.name) else ""
        else:
            chosen = choose_zh_voice(voices, speaks=lambda name: say_speaks_zh(cfg, name)) or ""
        with _choice_lock:
            first = key not in _choices  # else a concurrent first call resolved (and logged) it meanwhile
            hit = _choices.setdefault(key, chosen)
        if first and hit:
            log.info("say voice for %s: %s", ZH, hit, extra={"event": "audio_voice_zh"})
    if not hit:
        raise _no_zh_voice(cfg)
    return hit


def say_voice_for(cfg: Settings, accent: str) -> str:
    """The ``say -v`` name used for ``accent``, resolved once per process (and per override): ``WD_AUDIO_SAY_VOICE`` when
    ``say`` resolves it, else the best installed preferred voice. ``AudioError('failed')`` names the problem otherwise — an
    override ``say`` does not know must not become a cache full of clips in another voice. :data:`ZH` goes its own way
    (:func:`_say_zh_voice`: ``WD_AUDIO_SAY_VOICE_ZH``, the zh_CN voices, the size probe) — ``WD_AUDIO_SAY_VOICE`` is an English
    voice and never speaks Chinese."""
    if accent == ZH:
        return _say_zh_voice(cfg)
    key = f"{cfg.audio_say_voice}\n{accent}"
    with _choice_lock:
        hit = _choices.get(key)
    if hit:
        return hit
    if cfg.audio_say_voice:
        if not say_resolves(cfg, cfg.audio_say_voice):
            raise AudioError("failed", f"WD_AUDIO_SAY_VOICE={cfg.audio_say_voice!r} is not a voice this Mac's say resolves (compare `say -v '?'`)")
        chosen = cfg.audio_say_voice
    else:
        chosen = choose_voice(say_voices(), accent, resolves=lambda name: say_resolves(cfg, name))
        if chosen is None:
            raise AudioError(
                "failed",
                "say has no English voice it resolves; download one in System Settings → Accessibility → Spoken Content (then restart the service) or set WD_AUDIO_SAY_VOICE",
            )
    with _choice_lock:
        if key in _choices:  # a concurrent first call resolved (and logged) it meanwhile
            return _choices[key]
        _choices[key] = chosen
    log.info("say voice for %s: %s", accent, chosen, extra={"event": "audio_voice"})
    return chosen


def reset_voice_cache() -> None:
    """Forgets the listing, the probes and the resolved choices (tests; a downloaded voice otherwise needs a restart) — after a
    running warm-up finished, so it cannot refill them."""
    global _voices_cache, _voices_failed_at
    join_warm_up()
    with _voices_lock:
        _voices_cache = None
        _voices_failed_at = 0.0
    with _probe_lock:
        _probes.clear()
    with _choice_lock:
        _choices.clear()


def _sweep_probes(cfg: Settings) -> None:
    """Removes the probe files of processes that no longer run (a SIGTERM during their probes); a live process — `wd audio-voices`
    next door, a second instance — keeps its probe. Never raises."""
    try:
        for probe in cfg.tmp_dir.glob("audio-probe-*.aiff"):
            try:
                pid = int(probe.name.split("-")[2])
            except (IndexError, ValueError):
                continue
            try:
                os.kill(pid, 0)  # signal 0: exists?
            except ProcessLookupError:
                probe.unlink(missing_ok=True)
            except OSError:  # alive but not ours to signal
                continue
    except OSError:
        pass


def warm_up(cfg: Settings) -> None:
    """Resolves the `say` voice of every accent now — the listing and the probes, 1–3 s — so no learner's first tap pays for it.
    A failure is logged once (event ``audio_voice_failed``); the requests report it again. Then the Chinese voice (:data:`ZH`),
    whatever became of the English ones: a Mac without one is a supported state — one INFO line (event ``audio_voice_zh_missing``),
    ``ServerFlags.audio_zh`` reads false from then on and 磨耳朵 reads the English only. No-op for the other providers."""
    if provider_for(cfg) != "say":
        return
    _sweep_probes(cfg)
    for accent in ACCENTS:
        try:
            say_voice_for(cfg, accent)
        except AudioError as e:
            log.warning("no say voice for %s: %s", accent, e.detail, extra={"event": "audio_voice_failed"})
            break  # choose_voice falls back across accents: one accent without a voice means both
        except Exception:  # noqa: BLE001 — a daemon thread reports through the log, never through threading.excepthook
            log.exception("audio warm-up failed for %s", accent, extra={"event": "audio_voice_failed"})
            return
    try:
        say_voice_for(cfg, ZH)
    except AudioError as e:
        log.info("no say voice for %s: %s", ZH, e.detail, extra={"event": "audio_voice_zh_missing"})
    except Exception:  # noqa: BLE001 — as above
        log.exception("audio warm-up failed for %s", ZH, extra={"event": "audio_voice_zh_missing"})


_warm_up_lock = threading.Lock()
_warm_up_thread: threading.Thread | None = None
_UNRESOLVED = f"?{os.getpid()}-{time.time_ns()}"  # the placeholder of a voice not resolved yet: unique to this process, so an unsettled key never matches a cached one


def warm_up_async(cfg: Settings) -> threading.Thread | None:
    """:func:`warm_up` on a daemon thread (startup must not wait for `say`); None when there is nothing to warm. The thread is kept
    so :func:`join_warm_up` (shutdown, test teardown) can wait for it."""
    global _warm_up_thread
    if provider_for(cfg) != "say":
        return None
    thread = threading.Thread(target=warm_up, args=(cfg,), name="audio-warm-up", daemon=True)
    with _warm_up_lock:
        _warm_up_thread = thread
    thread.start()
    return thread


def join_warm_up(timeout: float = WARM_UP_JOIN_S) -> None:
    """Waits (at most ``timeout``) for a running warm-up — before a shutdown or before a test forgets the voice caches."""
    with _warm_up_lock:
        thread = _warm_up_thread
    if thread is not None and thread.is_alive():
        thread.join(timeout=timeout)


def voice_key(cfg: Settings) -> str:
    """A short fingerprint of what makes the clips — the provider, ``WD_AUDIO_SAY_VOICE`` and the voice of each accent as resolved so
    far, then the Chinese voice (its name; empty once it is settled that there is none) (``bailian``: the model and the two configured
    voices) — for ``ServerFlags.audio_key`` (API.md §9): the client appends it to
    every clip URL, so a switched provider, model or voice is a new URL and no browser keeps playing last week's voice from its HTTP
    cache. Empty without a provider. Never blocks: a voice not resolved yet reads as a placeholder unique to this process (never the
    key of an earlier run) and the next ``/me`` after the warm-up settles it."""
    provider = provider_for(cfg)
    if provider == "off":
        return ""
    parts = [provider]
    if provider == "say":
        parts.append(cfg.audio_say_voice)
        with _choice_lock:
            parts.extend(_choices.get(f"{cfg.audio_say_voice}\n{accent}", _UNRESOLVED) for accent in ACCENTS)
            parts.append(_choices.get(f"{cfg.audio_say_voice_zh}\n{ZH}", _UNRESOLVED))
    elif provider == "cache":
        voices = cfg.audio_cache_voice_map
        parts.extend(voices.get(accent, "?") for accent in ACCENTS)
    elif provider == "bailian":
        voices = cfg.bailian_voice_map
        parts.append(cfg.bailian_tts_model)
        parts.extend(voices.get(accent, "?") for accent in ACCENTS)
    return hashlib.sha256("\n".join(parts).encode("utf-8")).hexdigest()[:8]


def speaks_zh(cfg: Settings) -> bool:
    """``ServerFlags.audio_zh`` (API.md §9): endpoint 76 answers ``accent=zh-CN`` — the provider is `say` and its Chinese voice is
    resolved to a name, or **not resolved yet**: the 2–3 s of the warm-up after a start. A page reads ``/me`` once and keeps the
    flag for its session, and the HarmonyOS tablet has no voice of its own, so a False in that window was a session without
    Chinese; the optimistic answer costs a Mac without a Chinese voice one 503 ``failed`` — the request resolves the voice itself,
    as an English one does (:func:`locate`), and the client then stops asking. Only what this process already knows makes it
    False: the settled "none", or a cached listing with no voice to resolve — no zh_CN voice but Eloquence ones, or an override
    that is not a listed Chinese voice (:func:`_zh_override`). Never blocks and never runs `say`: the listing is read as it stands,
    without the lock :func:`say_voices` holds across ``say -v '?'``. The other providers have no Chinese clips yet
    (docs/LISTEN_MODE_DESIGN.md §8)."""
    if provider_for(cfg) != "say":
        return False
    with _choice_lock:
        hit = _choices.get(f"{cfg.audio_say_voice_zh}\n{ZH}")
    if hit is not None:
        return bool(hit)
    voices = _voices_cache  # one read of the reference (the list is replaced, never changed in place) — not say_voices(): that waits for a listing in flight
    if voices is None:
        return True
    return (_zh_override(cfg, voices) if cfg.audio_say_voice_zh else choose_zh_voice(voices)) is not None


# ------------------------------------------------------------------------------------------------- cache
def locate(cfg: Settings, accent: str, text: str) -> tuple[Clip, str, str]:
    """``(clip, provider, voice)`` for a normalised ``text``: where the clip lives (it may not exist yet) and what makes it.

    Raises ``AudioError('off')`` without a provider and ``AudioError('failed')`` when ``say`` has no usable English voice — or,
    for :data:`ZH`, no Chinese one. Chinese under another provider is ``missing`` (``cache``: the mirror holds English clips only)
    or ``failed`` (``bailian`` / ``youdao``: no Chinese voice is configured there), never a lookup in a two-accent voice map.
    """
    provider = provider_for(cfg)
    if provider == "off":
        raise AudioError("off")
    if accent == ZH and provider != "say":
        if provider == "cache":
            raise AudioError("missing", "the read-only cache mirrors English clips only — no Chinese clip exists for any text yet")
        raise AudioError("failed", f"{provider} has no Chinese voice — only `say` speaks {ZH} so far")
    if provider == "cache":  # the clips another host made with `say`: the same key, that host's voices
        key_provider, voice = "say", cfg.audio_cache_voice_map[accent]
    elif provider == "bailian":  # the voice is part of the key: a new voice is new clips, the old ones age out under the cap
        key_provider, voice = "bailian", cfg.bailian_voice_map[accent]
    else:
        key_provider, voice = provider, (say_voice_for(cfg, accent) if provider == "say" else "")
    ext, media_type = MEDIA[provider]
    digest = hashlib.sha256(f"{key_provider}\n{voice}\n{accent}\n{text}".encode("utf-8")).hexdigest()
    return Clip(cfg.audio_dir / digest[:2] / f"{digest}.{ext}", media_type), provider, voice


def lookup(cfg: Settings, accent: str, text: str) -> Clip | None:
    """The cached clip (touched, so pruning removes the least recently played first), or None when it has to be synthesised."""
    clip, provider, _voice = locate(cfg, accent, text)
    if not clip.path.is_file():
        return None
    if provider != "cache":  # a mirrored clip is pruned by the host that made it; touching it would only make rsync re-send it
        try:
            os.utime(clip.path)
        except OSError:
            pass
    return clip


_slots = threading.BoundedSemaphore(SLOTS)
_waiters = threading.BoundedSemaphore(MAX_WAITERS)


def synthesize(cfg: Settings, accent: str, text: str) -> Clip:
    """The clip for ``text`` (normalised), produced now when it is not cached. Atomic: the file appears complete or not at all."""
    clip, provider, voice = locate(cfg, accent, text)
    if clip.path.is_file():
        return clip
    if provider == "cache":
        raise AudioError("missing", "the read-only cache has no clip for this text — synthesise it on the host with `say` and sync audio/ (DEPLOY §9: wd audio-texts, wd audio-prewarm --texts)")
    if not _waiters.acquire(blocking=False):
        raise AudioError("busy", f"{MAX_WAITERS} requests already wait for a synthesis slot")
    try:
        if not _slots.acquire(timeout=SLOT_WAIT_S):
            raise AudioError("busy", f"no synthesis slot within {SLOT_WAIT_S:g} s")
    finally:
        _waiters.release()
    try:
        if clip.path.is_file():  # produced by another request while this one waited for the slot
            return clip
        clip.path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        tmp = clip.path.with_name(f"{clip.path.name}.{os.getpid()}-{threading.get_ident()}.tmp")
        try:
            if provider == "say":
                _say(text, voice, tmp, min_aiff=SILENT_AIFF_BYTES if accent == ZH else 0)
            elif provider == "youdao":
                _youdao(cfg, text, accent, tmp)
            elif provider == "bailian":
                _bailian(cfg, text, accent, tmp)
            else:  # pragma: no cover — provider_for() never returns anything else
                raise AudioError("failed", f"no synthesis for provider {provider!r}")
            size = tmp.stat().st_size if tmp.is_file() else 0
            if size < MIN_CLIP_BYTES:
                raise AudioError("failed", f"{provider} produced no audio ({size} bytes for a {len(text)}-char text)")
            os.chmod(tmp, 0o600)
            os.replace(tmp, clip.path)
        finally:
            tmp.unlink(missing_ok=True)
    finally:
        _slots.release()
    _account(cfg, size)
    return clip


_size_lock = threading.Lock()
_prune_lock = threading.Lock()
_cache_bytes: int | None = None  # bytes of clips under audio_dir: scanned on first use, kept current by synthesize(), re-scanned every SCAN_INTERVAL_S
_scanned_at = 0.0  # time.monotonic() of that scan


def _scan(root: Path) -> list[tuple[float, int, Path]]:
    """``(mtime, size, path)`` of every clip under ``root``; a clip or shard removed meanwhile (a prune on another thread,
    `wd audio-prewarm --purge-others` next door) is simply not counted — this walk runs on the request path and must never raise."""
    found: list[tuple[float, int, Path]] = []
    try:
        shards = list(root.iterdir())
    except OSError:  # no cache directory (yet, or any more)
        return found
    for sub in shards:
        try:
            entries = list(sub.iterdir()) if sub.is_dir() else []
        except OSError:  # the shard vanished between the two calls
            continue
        for f in entries:
            if f.suffix not in CLIP_SUFFIXES:
                continue
            try:
                st = f.stat()
            except OSError:  # unlinked between the listing and the stat
                continue
            if stat.S_ISREG(st.st_mode):
                found.append((st.st_mtime, st.st_size, f))
    return found


def _rescan(root: Path) -> int:
    """(under ``_size_lock``) counts the clips on disk and remembers when."""
    global _cache_bytes, _scanned_at
    _cache_bytes = sum(size for _mtime, size, _path in _scan(root))
    _scanned_at = time.monotonic()
    return _cache_bytes


def cache_bytes(cfg: Settings) -> int:
    """Bytes of cached clips (the running total, scanned on first use)."""
    with _size_lock:
        return _rescan(cfg.audio_dir) if _cache_bytes is None else _cache_bytes


def _account(cfg: Settings, added: int) -> None:
    global _cache_bytes
    with _size_lock:
        if _cache_bytes is None or time.monotonic() - _scanned_at > SCAN_INTERVAL_S:
            total = _rescan(cfg.audio_dir)  # sees the new clip — and whatever another process (wd audio-prewarm) added or removed
        else:
            _cache_bytes += added
            total = _cache_bytes
    cap = cfg.audio_cache_mb * MB
    if total > cap:
        prune(cfg, cap * 9 // 10)


def prune(cfg: Settings, target_bytes: int) -> int:
    """Removes the least recently played clips (by mtime — :func:`lookup` touches a served clip) until at most ``target_bytes``
    remain; returns how many were removed."""
    global _cache_bytes, _scanned_at
    with _prune_lock:
        entries = sorted(_scan(cfg.audio_dir))
        total = sum(size for _mtime, size, _path in entries)
        removed = 0
        for _mtime, size, path in entries:
            if total <= target_bytes:
                break
            try:
                path.unlink()
            except OSError:
                continue
            total -= size
            removed += 1
        with _size_lock:
            _cache_bytes = total
            _scanned_at = time.monotonic()
    if removed:
        log.info("audio cache over WD_AUDIO_CACHE_MB=%d: %d clip(s) removed, %d bytes kept", cfg.audio_cache_mb, removed, total, extra={"event": "audio_cache_pruned"})
    return removed


def reset_cache_accounting() -> None:
    """Forgets the running total (tests)."""
    global _cache_bytes, _scanned_at
    with _size_lock:
        _cache_bytes = None
        _scanned_at = 0.0


# ---------------------------------------------------------------------------------------------- providers
def _child_env() -> dict[str, str]:
    """An allow-listed environment for `say` / `afconvert` (DESIGN §10 Subprocess): never a copy of the service's env."""
    env = {"PATH": "/usr/bin:/bin", "LANG": "en_US.UTF-8"}
    for key in ("HOME", "TMPDIR"):
        value = os.environ.get(key)
        if value:
            env[key] = value
    return env


def _spawn(argv: list[str], *, stdout: int) -> subprocess.Popen[bytes]:
    try:
        return subprocess.Popen(argv, stdin=subprocess.PIPE, stdout=stdout, stderr=subprocess.PIPE, env=_child_env(), cwd="/", start_new_session=True)
    except OSError as e:
        raise AudioError("failed", f"{argv[0]}: {e}") from e


def _communicate(proc: subprocess.Popen[bytes], argv: list[str], stdin_text: str | None) -> bytes:
    try:
        out, err = proc.communicate(input=(stdin_text or "").encode("utf-8"), timeout=SAY_TIMEOUT_S)
    except subprocess.TimeoutExpired:
        try:
            os.killpg(proc.pid, signal.SIGKILL)
        except OSError:
            proc.kill()
        try:
            proc.communicate(timeout=5)
        except (subprocess.TimeoutExpired, OSError, ValueError):
            pass
        raise AudioError("failed", f"{argv[0]} timed out after {SAY_TIMEOUT_S} s") from None
    if proc.returncode != 0:
        excerpt = err.decode("utf-8", "replace").strip()[:STDERR_EXCERPT_CHARS]
        raise AudioError("failed", f"{argv[0]} exited {proc.returncode}: {excerpt or 'no stderr'}")
    return out


def _run(argv: list[str], *, stdin_text: str | None = None) -> None:
    """Runs ``argv`` (stdout discarded, stderr kept for the error) with ``stdin_text`` on stdin; ``AudioError('failed')`` on any failure."""
    _communicate(_spawn(argv, stdout=subprocess.DEVNULL), argv, stdin_text)


def _output(argv: list[str]) -> str:
    """``argv``'s stdout (the `say -v ?` listing); ``AudioError('failed')`` on any failure."""
    return _communicate(_spawn(argv, stdout=subprocess.PIPE), argv, None).decode("utf-8", "replace")


def _say(text: str, voice: str, out: Path, *, min_aiff: int = 0) -> None:
    """``say`` → AIFF (the only format it writes without re-encoding surprises) → ``afconvert`` → AAC in an m4a.

    An AIFF under ``min_aiff`` bytes (the Chinese clips pass :data:`SILENT_AIFF_BYTES`) is ``AudioError('failed', 'silent clip …')``
    before anything is converted: `say` exits 0 with a header-only file when its voice cannot speak the text's language — a Chinese
    voice removed since the probe is replaced by the system's fallback voice —, and the AAC of that passes ``MIN_CLIP_BYTES`` and
    would be cached, and kept by browsers for a week, as a clip of silence."""
    aiff = out.with_name(out.name + ".aiff")
    try:
        _run([SAY_BIN, "-v", voice, "-o", str(aiff)], stdin_text=text)
        if min_aiff:
            size = aiff.stat().st_size if aiff.is_file() else 0
            if size < min_aiff:
                raise AudioError("failed", f"silent clip: say -v {voice!r} wrote {size} bytes of AIFF for a {len(text)}-char text (a spoken clip has at least {min_aiff})")
        _run([AFCONVERT_BIN, "-f", "m4af", "-d", "aac", "-b", AAC_BITRATE, str(aiff), str(out)])
    finally:
        aiff.unlink(missing_ok=True)


def _youdao_client(cfg: Settings) -> httpx.Client:  # noqa: ARG001 — the signature is what tests patch
    # a neutral User-Agent: the image providers' one carries the operator's e-mail and public URL (Wikimedia wants a contact);
    # Youdao gets neither, only the text. No proxy from the environment (like the AI fallback adapter).
    return httpx.Client(timeout=YOUDAO_TIMEOUT_S, follow_redirects=False, trust_env=False, headers={"User-Agent": f"word-Dance/{__version__}", "Accept": "audio/mpeg, audio/*;q=0.9"})


def _youdao(cfg: Settings, text: str, accent: str, out: Path) -> None:
    size = 0
    try:
        with _youdao_client(cfg) as client, client.stream("GET", YOUDAO_URL, params={"audio": text, "type": YOUDAO_TYPE[accent]}) as r:
            ctype = r.headers.get("content-type", "")
            if r.status_code != 200 or not ctype.lower().startswith("audio/"):
                raise AudioError("failed", f"youdao answered {r.status_code} {ctype or 'without content-type'}")
            with out.open("wb") as fh:
                for chunk in r.iter_bytes():
                    size += len(chunk)
                    if size > YOUDAO_MAX_BYTES:
                        raise AudioError("failed", f"youdao answered more than {YOUDAO_MAX_BYTES} bytes")
                    fh.write(chunk)
    except httpx.HTTPError as e:
        raise AudioError("failed", f"youdao: {e.__class__.__name__}") from e
    if size < MIN_CLIP_BYTES:
        raise AudioError("failed", f"youdao answered {size} bytes")


# ---------------------------------------------------------------------------------- bailian (阿里云百炼 TTS)
#: test hook: the transport both 百炼 clients use (None = the real network); an ``httpx.MockTransport`` sees the synthesis POST with
#: its headers and the anonymous OSS GET alike, so a test can check what each request carries
BAILIAN_TRANSPORT: httpx.BaseTransport | None = None
_key_mode_lock = threading.Lock()
_key_mode_warned = False  # the group/other-readable warning of read_key(): once per process (config.py warns once more at startup)
_bailian_pace_lock = threading.Lock()
_bailian_last_post = 0.0  # time.monotonic() of the last synthesis POST this process sent (under _bailian_pace_lock)


def read_key(cfg: Settings) -> str:
    """The first line of ``WD_BAILIAN_API_KEY_FILE`` (``utf-8-sig``, stripped), read at call time — never cached on the module, never
    in a log line. ``AudioError('failed', 'bailian: API key file unreadable')`` when the variable is unset, the file cannot be read or its
    first line is not a printable ASCII token; the detail never carries the file's contents. A group/other-readable mode warns once
    per process (chmod 600 it), like ``delivery/aliyun.read_secret``."""
    global _key_mode_warned
    path_text = (cfg.bailian_api_key_file or "").strip()
    if not path_text:
        raise AudioError("failed", "bailian: API key file unreadable (WD_BAILIAN_API_KEY_FILE is not set)")
    path = Path(path_text).expanduser()
    try:
        mode = stat.S_IMODE(path.stat().st_mode)
        with path.open(encoding="utf-8-sig") as f:
            key = f.readline().strip()
    except OSError as e:
        raise AudioError("failed", f"bailian: API key file unreadable ({e.__class__.__name__})") from e
    if mode & 0o077:
        with _key_mode_lock:
            warn = not _key_mode_warned
            _key_mode_warned = True
        if warn:
            log.warning("WD_BAILIAN_API_KEY_FILE is readable by group/others (mode %o); chmod 600 it", mode, extra={"event": "audio_key_file_mode"})
    if not key or not key.isascii() or not key.isprintable():
        raise AudioError("failed", "bailian: API key file unreadable (no printable ASCII key on its first line)")
    return key


def _bailian_client(cfg: Settings, key: str) -> httpx.Client:  # noqa: ARG001 — the signature is what tests may patch
    """The synthesis client: the bearer key, JSON, a neutral User-Agent (no operator e-mail or URL), no proxy from the environment."""
    return httpx.Client(
        timeout=BAILIAN_TIMEOUT_S,
        follow_redirects=False,
        trust_env=False,
        headers={"Authorization": f"Bearer {key}", "Content-Type": "application/json", "Accept": "application/json", "User-Agent": f"word-Dance/{__version__}"},
        transport=BAILIAN_TRANSPORT,
    )


def _bailian_download_client(cfg: Settings) -> httpx.Client:  # noqa: ARG001
    """The OSS download client: SEPARATE and anonymous — the clip URL is pre-signed, the API key must never travel to OSS."""
    return httpx.Client(
        timeout=BAILIAN_DOWNLOAD_TIMEOUT_S,
        follow_redirects=False,
        trust_env=False,
        headers={"Accept": "audio/mpeg, audio/*;q=0.9, application/octet-stream;q=0.8", "User-Agent": f"word-Dance/{__version__}"},
        transport=BAILIAN_TRANSPORT,
    )


def _pace_bailian() -> None:
    """Sleeps so that two consecutive synthesis POSTs of this process are ≥ :data:`BAILIAN_PACE_S` apart — across the two
    synthesis slots and ``wd audio-prewarm``'s two workers alike — which keeps the process under 150 RPM against the documented
    :data:`BAILIAN_RPM`. The lock is held while sleeping on purpose: the next caller queues behind this one."""
    global _bailian_last_post
    with _bailian_pace_lock:
        wait = _bailian_last_post + BAILIAN_PACE_S - time.monotonic()
        if wait > 0:
            time.sleep(wait)
        _bailian_last_post = time.monotonic()


def _scrub(message: str, key: str) -> str:
    """The provider's ``message`` fit for an error detail: the key (should it ever be echoed) replaced, cut to :data:`BAILIAN_MESSAGE_CHARS`."""
    return " ".join(message.replace(key, "***").split())[:BAILIAN_MESSAGE_CHARS]


def _bailian(cfg: Settings, text: str, accent: str, out: Path) -> None:
    """One clip through 百炼: ``POST`` the synthesis request, then ``GET`` the pre-signed OSS URL of the answer into ``out``.

    429 and 5xx (the documented ``Throttling*`` / ``InternalError`` / ``ServiceUnavailable`` answers) are ``AudioError('busy')`` — the
    route answers 503 ``{reason:"busy"}`` and the client retries later; 400 / 401 / 403 / 404 (``InvalidParameter`` — a voice the model
    does not know —, ``InvalidApiKey``, ``Arrearage`` / ``AccessDenied``, ``ModelNotFound``), an answer without ``output.audio.url`` and a
    download that is not audio are ``AudioError('failed')`` whose detail carries the provider's ``code`` and the first
    :data:`BAILIAN_MESSAGE_CHARS` of its ``message`` — never the key, never the signed URL; a transport failure is
    ``failed`` with the exception's class name. The text is logged at DEBUG only, its length at INFO.
    """
    key = read_key(cfg)
    voice = cfg.bailian_voice_map[accent]
    model = cfg.bailian_tts_model
    inputs: dict[str, object] = {"text": text, "voice": voice, "format": BAILIAN_FORMAT, "sample_rate": BAILIAN_SAMPLE_RATE}
    if model.startswith("qwen-audio"):
        inputs["language_hints"] = ["en"]  # the Qwen-Audio-TTS models take the hint; CosyVoice's English voices need none
    payload = {"model": model, "input": inputs}
    log.debug("bailian synthesis of %r (%s, %s)", text, accent, voice)
    _pace_bailian()
    try:
        with _bailian_client(cfg, key) as client:
            r = client.post(cfg.bailian_tts_url, json=payload)
    except (httpx.HTTPError, httpx.InvalidURL) as e:
        raise AudioError("failed", f"bailian: {e.__class__.__name__}") from e
    try:
        data = r.json()
    except ValueError:
        data = None
    body = data if isinstance(data, dict) else {}
    code = str(body.get("code") or "")
    message = _scrub(str(body.get("message") or ""), key)
    if r.status_code == 429 or r.status_code >= 500:
        raise AudioError("busy", f"bailian answered {r.status_code}{' ' + code if code else ''}: {message or 'retry later'}")
    if r.status_code != 200 or code:
        raise AudioError("failed", f"bailian {code or f'HTTP {r.status_code}'}: {message or 'no message'}")
    output = body.get("output") if isinstance(body.get("output"), dict) else {}
    audio_part = output.get("audio") if isinstance(output.get("audio"), dict) else {}
    url = audio_part.get("url")
    if not isinstance(url, str) or not url:
        raise AudioError("failed", "bailian: answer without output.audio.url")
    if url.startswith("http://"):  # the documented example is plain http; OSS serves https on the same path — never download audio in clear
        url = "https://" + url[len("http://") :]
    if not url.startswith("https://"):
        raise AudioError("failed", "bailian: output.audio.url is not an https URL")
    host = urlsplit(url).hostname or ""
    if not (host == BAILIAN_DOWNLOAD_HOST_SUFFIX.lstrip(".") or host.endswith(BAILIAN_DOWNLOAD_HOST_SUFFIX)):
        raise AudioError("failed", "bailian: output.audio.url is not on aliyuncs.com")  # the anonymous download client fetches nothing the provider's answer could point elsewhere
    size = 0
    try:
        with _bailian_download_client(cfg) as client, client.stream("GET", url) as dl:
            ctype = dl.headers.get("content-type", "").lower()
            if dl.status_code != 200 or not (ctype.startswith("audio/") or ctype.startswith("application/octet-stream")):
                raise AudioError("failed", f"bailian clip download answered {dl.status_code} {ctype.split(';')[0] or 'without content-type'}")
            with out.open("wb") as fh:
                for chunk in dl.iter_bytes():
                    size += len(chunk)
                    if size > BAILIAN_MAX_BYTES:
                        raise AudioError("failed", f"bailian clip larger than {BAILIAN_MAX_BYTES} bytes")
                    fh.write(chunk)
    except (httpx.HTTPError, httpx.InvalidURL) as e:
        raise AudioError("failed", f"bailian: {e.__class__.__name__}") from e
    if size < MIN_CLIP_BYTES:
        raise AudioError("failed", f"bailian clip of {size} bytes")
    usage = body.get("usage") if isinstance(body.get("usage"), dict) else {}
    log.info("bailian clip made: %d chars, %d bytes, %s %s, billed characters %s", len(text), size, accent, voice, usage.get("characters", "-"), extra={"event": "audio_bailian_clip"})


def bailian_price_line(cfg: Settings, characters: int) -> str:
    """The ``wd audio-prewarm`` estimate: the characters to send (an English letter, digit, space or punctuation mark counts 1) and,
    for a model in :data:`BAILIAN_PRICE_CNY_PER_10K_CHARS`, ``characters / 10000 × price`` 元 — an estimate at the 北京 list price;
    the console bill decides."""
    price = BAILIAN_PRICE_CNY_PER_10K_CHARS.get(cfg.bailian_tts_model)
    head = f"≈ {characters} characters to send to 百炼 (model {cfg.bailian_tts_model})"
    if price is None:
        return head + ": price per 10 000 characters unknown for this model — see the 百炼 model-pricing page"
    return head + f": ≈ ¥{characters / 10000 * price:.2f} at ¥{price:g} per 10 000 characters (an estimate at the 北京 list price; the console bill decides)"


# ------------------------------------------------------------------------------------------ prewarm (CLI)
PREWARM_FROM_VERSION = 14  # words.learn_rank (0014) orders the work: what a 小学 learner meets first is made first
PREWARM_ABORT_AFTER = 5  # consecutive failed attempts: the provider is down (no voice, say wedged …) — stop, do not log thousands of errors
PREWARM_PROGRESS_EVERY = 100  # clips between two progress lines
PREWARM_CLIP_ESTIMATE = 20 * 1024  # bytes per clip for the cap check when the cache holds nothing to average yet (≈ 8 KB a word, 15–30 KB a sentence)
TIER_NAMES = {2: "premium", 1: "enhanced", 0: "compact"}
PREWARM_TEXTS_SQL = """
SELECT w.display, wc.content_json
FROM words w
LEFT JOIN word_contents wc ON wc.id = w.active_content_id
WHERE w.merged_into_word_id IS NULL
  AND (w.active_content_id IS NOT NULL OR EXISTS (SELECT 1 FROM user_words uw WHERE uw.word_id = w.id){stages})
ORDER BY w.learn_rank IS NULL, w.learn_rank, w.id
"""


@dataclass
class PrewarmSet:
    texts: list[str]  # normalised, distinct, in learning order
    refused: list[str]  # raw texts the text rule refuses — the server cannot play those for anybody


def prewarm_texts(conn: sqlite3.Connection, stages: tuple[str, ...] = ()) -> PrewarmSet:
    """The texts of the study path: the display form of each word with active content or in somebody's bank (the headword's 🔊)
    and the English of every example sentence of that content (ExampleList's 🔊) — plus, for each of ``stages`` (``xs`` …), the
    display form of every public valid word of the stage (what the welcome screening and 词库 browsing can tap) — distinct, in
    learning order. Anything else a learner taps is synthesised at the tap."""
    for stage in stages:
        if not re.fullmatch(r"[a-z0-9]+", stage):
            raise ValueError(f"not a stage code: {stage!r}")
    stage_sql = "".join(f" OR (w.stage_{stage} = 1 AND w.is_public = 1 AND w.is_valid_english = 1)" for stage in stages)

    def raws() -> Iterator[object]:
        for display, content_json in conn.execute(PREWARM_TEXTS_SQL.format(stages=stage_sql)):
            yield display
            if not content_json:
                continue
            try:
                content = json.loads(content_json)
            except ValueError:
                continue
            examples = content.get("examples") if isinstance(content, dict) else None
            for example in examples if isinstance(examples, list) else []:
                if isinstance(example, dict):
                    yield example.get("en")

    return _collect(raws())


def _collect(raws: Iterable[object]) -> PrewarmSet:
    """Normalises and de-duplicates ``raws`` in order; what the text rule refuses goes to ``refused``."""
    seen: set[str] = set()
    chosen = PrewarmSet(texts=[], refused=[])
    for raw in raws:
        if not isinstance(raw, str) or not raw.strip():
            continue
        spoken = normalize_text(raw)
        if spoken is None:
            chosen.refused.append(raw)
        elif spoken not in seen:
            seen.add(spoken)
            chosen.texts.append(spoken)
    return chosen


def texts_from_file(path: Path) -> PrewarmSet:
    """The texts of ``wd audio-texts`` written by another host (one per line, UTF-8, a BOM tolerated), for ``wd audio-prewarm
    --texts``; ``OSError`` / ``UnicodeDecodeError`` are the caller's to report."""
    return _collect(path.read_text(encoding="utf-8-sig").splitlines())


def accents_in_use(conn: sqlite3.Connection) -> tuple[str, ...]:
    """``en-US`` (the default accent) plus every accent some learner chose."""
    chosen = {row[0] for row in conn.execute("SELECT DISTINCT accent FROM user_settings")}
    return tuple(a for a in ACCENTS if a == "en-US" or a in chosen)


@dataclass
class PrewarmReport:
    clips: int = 0  # accent × text pairs planned
    cached: int = 0  # of them already on disk before the run
    todo: int = 0  # clips this run set out to make (the missing ones, --limit applied)
    skipped: int = 0  # missing clips beyond --limit
    made: int = 0
    failed: int = 0
    bytes_made: int = 0
    seconds: float = 0.0
    errors: list[str] = field(default_factory=list)  # the first few failure details
    aborted: bool = False  # stopped early: PREWARM_ABORT_AFTER attempts failed in a row
    interrupted: bool = False  # Ctrl-C

    @property
    def done(self) -> int:
        return self.made + self.failed


def prewarm(cfg: Settings, texts: list[str], accents: tuple[str, ...], *, limit: int = 0, progress: Callable[[PrewarmReport], None] | None = None) -> PrewarmReport:
    """Synthesises the missing clips of ``texts`` for each of ``accents`` (accent by accent, the texts in their order): with `say`
    through the usual :data:`SLOTS` of this process — two `say` processes at a time next to whatever the live service runs —, with
    `youdao` one request at a time with :data:`YOUDAO_PAUSE_S` between two (an unofficial endpoint), with `bailian` two workers whose
    POSTs :func:`_pace_bailian` keeps :data:`BAILIAN_PACE_S` apart (under the documented RPM). A clip already cached is
    counted, not touched (its place in the pruning order is the learner's); ``limit`` bounds the clips to make, not the pairs.
    Stops after :data:`PREWARM_ABORT_AFTER` failures in a row (the provider went down) and on Ctrl-C, both reported, never raised;
    only a provider that cannot even locate the clips (no voice resolves, `off`) raises ``AudioError`` up front. ``progress`` runs
    every :data:`PREWARM_PROGRESS_EVERY` clips and at the end."""
    pairs = [(accent, text) for accent in accents for text in texts]
    missing = [pair for pair in pairs if not locate(cfg, *pair)[0].path.is_file()]
    jobs = missing[:limit] if limit > 0 else missing
    report = PrewarmReport(clips=len(pairs), cached=len(pairs) - len(missing), todo=len(jobs), skipped=len(missing) - len(jobs))
    provider = provider_for(cfg)
    started = time.monotonic()

    def one(job: tuple[str, str]) -> tuple[str, int, str]:
        accent, text = job
        try:
            clip = synthesize(cfg, accent, text)  # returns the clip another process made meanwhile as well
            size = clip.path.stat().st_size
        except (AudioError, OSError) as e:
            detail = f"{e.reason}: {e.detail}" if isinstance(e, AudioError) else str(e)
            return "failed", 0, f"{accent}, a {len(text)}-char text: {detail}"
        if provider == "youdao":
            time.sleep(YOUDAO_PAUSE_S)
        return "made", size, ""

    streak = 0

    def tally(outcome: str, size: int, detail: str) -> None:
        nonlocal streak
        if outcome == "made":
            report.made += 1
            report.bytes_made += size
            streak = 0
        else:
            report.failed += 1
            streak += 1
            if len(report.errors) < 5:
                report.errors.append(detail)
        report.seconds = time.monotonic() - started
        if progress and (report.done % PREWARM_PROGRESS_EVERY == 0 or report.done == report.todo):
            progress(report)

    with ThreadPoolExecutor(max_workers=SLOTS if provider in ("say", "bailian") else 1, thread_name_prefix="audio-prewarm") as pool:
        futures = [pool.submit(one, job) for job in jobs]
        try:
            for i, future in enumerate(futures):
                tally(*future.result())
                if streak >= PREWARM_ABORT_AFTER:
                    report.aborted = True
                    pool.shutdown(wait=True, cancel_futures=True)  # the queued jobs are dropped, the running ones finish …
                    for late in futures[i + 1 :]:
                        if late.done() and not late.cancelled():
                            tally(*late.result())  # … and count: a clip is on disk, or an attempt failed
                    break
        except KeyboardInterrupt:
            report.interrupted = True
            pool.shutdown(wait=False, cancel_futures=True)
    report.seconds = time.monotonic() - started
    return report


def expected_paths(cfg: Settings, texts: list[str], accents: tuple[str, ...]) -> set[Path]:
    """Where the clips of ``texts`` × ``accents`` live with the provider and voice in force."""
    return {locate(cfg, accent, text)[0].path for accent in accents for text in texts}


TMP_LITTER_AGE_S = 3600.0  # a synthesis killed outright (SIGKILL, a dropped terminal) leaves its .tmp / .tmp.aiff; older than this they are litter


def purge_others(cfg: Settings, keep: set[Path]) -> tuple[int, int]:
    """Deletes every cached clip whose path is not in ``keep`` — the clips of a voice no longer chosen, and of every text outside
    the set (ad-hoc taps, a stage not named this time: one re-synthesis each at the next tap) — plus the temp files of a synthesis
    killed outright more than :data:`TMP_LITTER_AGE_S` ago; returns ``(removed clips, bytes)``. Safe next to the live service: the
    key carries the voice, so it never asks for another voice's clip again."""
    removed = freed = 0
    for _mtime, size, path in _scan(cfg.audio_dir):
        if path in keep:
            continue
        try:
            path.unlink()
        except OSError:
            continue
        removed += 1
        freed += size
    cutoff = time.time() - TMP_LITTER_AGE_S
    try:
        for litter in cfg.audio_dir.glob("*/*.tmp*"):
            try:
                if litter.stat().st_mtime < cutoff:
                    litter.unlink()
            except OSError:
                continue
    except OSError:
        pass
    if removed:
        reset_cache_accounting()
    return removed, freed


def _cli_logging() -> None:
    """The CLI commands log to stderr — this module at INFO (voice choice, probes, pruning), everything else at WARNING (httpx would
    print one line per youdao request, text included); the service's log file stays the service's: never ``configure_logging`` here."""
    logging.basicConfig(level=logging.WARNING, stream=sys.stderr, format="%(levelname)s %(name)s: %(message)s")
    log.setLevel(logging.INFO)


def _no_zh_line(provider: str) -> str:
    """The Chinese line of ``wd audio-voices`` under a provider other than `say`."""
    return f"{ZH} → none: {provider} has no Chinese clips yet — only `say` speaks Chinese (ServerFlags.audio_zh is false; 磨耳朵 reads Chinese with the device's own voice)"


def cmd_audio_voices(args: argparse.Namespace) -> int:
    """``wd audio-voices`` — the provider in force, the installed `say` voices of the preference lists (tier, whether `say`
    resolves them), the voice each accent gets and, last, the Chinese voice (``zh-CN``, what 磨耳朵 reads glosses and translations
    with — none is a supported state, not an error); exit 1 when an English accent gets none, 2 on a configuration error."""
    _cli_logging()
    try:
        cfg = Settings.from_env()
        ensure_dirs(cfg)  # the probes write under tmp/
    except ConfigError as e:
        print(f"wd audio-voices: configuration error: {e}", file=sys.stderr)
        return 2
    provider = provider_for(cfg)
    if provider == "cache":
        clips = _scan(cfg.audio_dir)
        print(f"provider: cache (WD_AUDIO_PROVIDER={cfg.audio_provider}) — a read-only mirror of the `say` clips another host synthesised: {len(clips)} clip(s), {sum(size for _m, size, _p in clips) / MB:.1f} MB (WD_AUDIO_CACHE_MB is not enforced here: the host that synthesises bounds it)")
        for accent in ACCENTS:
            print(f"{accent} → {cfg.audio_cache_voice_map.get(accent, '?')} (WD_AUDIO_CACHE_VOICES)")
        print(_no_zh_line(provider))
        return 0
    if provider == "bailian":
        print(f"provider: bailian (WD_AUDIO_PROVIDER=bailian, model {cfg.bailian_tts_model}, region {cfg.bailian_region}); cache: {cache_bytes(cfg) / MB:.1f} MB of {cfg.audio_cache_mb} MB")
        for accent in ACCENTS:
            print(f"{accent} → {cfg.bailian_voice_map.get(accent, '?')} (WD_BAILIAN_TTS_VOICES)")
        print(_no_zh_line(provider))
        print("no `say` voices to list: bailian synthesises in the cloud with the voices above (`wd audio-probe` makes one clip with them)")
        return 0
    print(
        f"provider: {provider} (WD_AUDIO_PROVIDER={cfg.audio_provider}); WD_AUDIO_SAY_VOICE: {cfg.audio_say_voice or '(unset — the best installed preferred voice)'}; "
        f"cache: {cache_bytes(cfg) / MB:.1f} MB of {cfg.audio_cache_mb} MB"
    )
    if provider != "say":
        print("no `say` voices to list: " + ("WD_AUDIO_PROVIDER resolves to off (say needs a Mac)" if provider == "off" else f"{provider} has one fixed voice per accent"))
        if provider != "off":
            print(_no_zh_line(provider))
        return 0
    voices = say_voices()
    if not voices:
        print("`say -v ?` failed or listed nothing (the error is logged above)", file=sys.stderr)
        return 1
    for accent in ACCENTS:
        installed = [v for v in voices if v.lang == VOICE_LANG[accent]]
        preferred = [v for base in PREFERRED_VOICES[accent] for v in sorted((v for v in installed if v.base == base), key=lambda v: (-v.tier, v.name))]
        print(f"{accent}: {len(installed)} voice(s) installed, {len(preferred)} of the preference list ({', '.join(PREFERRED_VOICES[accent])}):")
        for v in preferred:
            if say_resolves(cfg, v.name):
                verdict = "resolves"
            else:
                with _probe_lock:
                    probed = _probes.get((v.name, PROBE_TEXT))
                verdict = "probe failed — say exited non-zero (logged above)" if probed is None else "NOT resolved — say substitutes its fallback voice for this name"
            print(f"  {v.name:<26} {TIER_NAMES[v.tier]:<9} {verdict}")
    rc = 0
    for accent in ACCENTS:
        try:
            print(f"{accent} → {say_voice_for(cfg, accent)}")
        except AudioError as e:
            print(f"{accent} → none: {e.detail}")
            rc = 1
    try:  # the Chinese voice: its own override, its own probe (say_speaks_zh) — and none is not a failure
        print(f"{ZH} → {say_voice_for(cfg, ZH)}" + (" (WD_AUDIO_SAY_VOICE_ZH)" if cfg.audio_say_voice_zh else " (the best installed zh_CN voice; WD_AUDIO_SAY_VOICE_ZH overrides)"))
    except AudioError as e:
        print(f"{ZH} → none: {e.detail} — 磨耳朵 then reads the English only (ServerFlags.audio_zh is false)")
    return rc


def _others(cfg: Settings, keep: set[Path]) -> tuple[int, int]:
    """``(count, bytes)`` of the cached clips outside ``keep`` (what ``--purge-others`` would delete)."""
    outside = [(size, path) for _mtime, size, path in _scan(cfg.audio_dir) if path not in keep]
    return len(outside), sum(size for size, _path in outside)


def _clip_estimate(cfg: Settings) -> int:
    """Bytes a new clip will take, from the clips on disk (else :data:`PREWARM_CLIP_ESTIMATE`)."""
    sizes = [size for _mtime, size, _path in _scan(cfg.audio_dir)]
    return sum(sizes) // len(sizes) if sizes else PREWARM_CLIP_ESTIMATE


def cmd_audio_prewarm(args: argparse.Namespace) -> int:
    """``wd audio-prewarm [--accent A …] [--stage S …] [--limit N] [--dry-run] [--purge-others] [--texts FILE] [--db PATH]`` — synthesise
    the clips of the study path (:func:`prewarm_texts`, plus the headwords of ``--stage``) for the accents in use, so those taps never wait for
    `say`; ``--purge-others`` first deletes the clips outside the set; safe next to the live service (DEPLOY §9). Exit 0 when every
    clip is there, 1 when a clip failed / the voice does not resolve / the schema is too old / the cap is too small, 2 without a
    provider or a database, 130 on Ctrl-C."""
    _cli_logging()
    try:
        cfg = Settings.from_env()
    except ConfigError as e:
        print(f"wd audio-prewarm: configuration error: {e}", file=sys.stderr)
        return 2
    provider = provider_for(cfg)
    if provider == "off":
        print("wd audio-prewarm: WD_AUDIO_PROVIDER resolves to off — nothing can synthesise (say on a Mac, bailian or youdao, in .env)", file=sys.stderr)
        return 2
    if provider == "cache":
        print("wd audio-prewarm: WD_AUDIO_PROVIDER=cache serves clips another host synthesised — `wd audio-texts > texts.txt` here, `wd audio-prewarm --texts texts.txt` on the host with say, then sync audio/ back (DEPLOY §9)", file=sys.stderr)
        return 2
    if args.texts and (args.purge_others or args.stage or args.db):
        print("wd audio-prewarm: --texts takes the texts from a file; --purge-others, --stage and --db need this host's database", file=sys.stderr)
        return 2
    if args.texts:
        texts_path = Path(args.texts).expanduser()
        try:
            chosen = texts_from_file(texts_path)
        except (OSError, UnicodeDecodeError) as e:
            print(f"wd audio-prewarm: cannot read {texts_path} as UTF-8 text, one per line (the output of `wd audio-texts`): {e}", file=sys.stderr)
            return 2
        accents = tuple(dict.fromkeys(args.accent)) if args.accent else ACCENTS  # another host's learners: both accents unless told
        keep_accents = accents
    else:
        from . import db  # local: the request path imports this module and never opens the database here

        path = Path(args.db).expanduser() if args.db else cfg.db_path
        if not path.is_file():
            print(f"wd audio-prewarm: no database at {path} — set WD_DATA_DIR / WD_DB_PATH (the Mac: WD_DATA_DIR=/Users/sqin/word-dance-data) or pass --db", file=sys.stderr)
            return 2
        conn = db.connect(path)
        try:
            version = db.current_version(conn)
            if version < PREWARM_FROM_VERSION:
                print(f"wd audio-prewarm: schema version {version} has no words.learn_rank (migration {PREWARM_FROM_VERSION:04d}) — run `wd migrate` first", file=sys.stderr)
                return 1
            chosen = prewarm_texts(conn, stages=tuple(dict.fromkeys(args.stage or ())))
            in_use = accents_in_use(conn)
            accents = tuple(dict.fromkeys(args.accent)) if args.accent else in_use
            keep_accents = tuple(a for a in ACCENTS if a in in_use or a in accents)  # --purge-others keeps every accent in use, --accent or not
        finally:
            conn.close()
    ensure_dirs(cfg)
    try:
        voices = {accent: (say_voice_for(cfg, accent) if provider == "say" else cfg.bailian_voice_map[accent] if provider == "bailian" else provider) for accent in keep_accents}
    except AudioError as e:
        print(f"wd audio-prewarm: no voice — {e.detail}", file=sys.stderr)
        return 1
    if args.texts:
        scope = f"from {args.texts}"
    else:
        scope = "headwords with content or in a bank and their example sentences" + (f", the headwords of {', '.join(args.stage)}" if args.stage else "") + "; learning order"
    print(f"{len(chosen.texts)} text(s) a learner can tap ({scope}); " + ", ".join(f"{a} → {voices[a]}" for a in accents))
    if chosen.refused:
        print(f"{len(chosen.refused)} text(s) the text rule refuses (no server clip for those): " + "; ".join(repr(t[:60]) for t in chosen.refused[:5]))
    paths = expected_paths(cfg, chosen.texts, accents)
    keep = expected_paths(cfg, chosen.texts, keep_accents)
    missing = sum(1 for p in paths if not p.is_file())
    todo = min(missing, args.limit) if args.limit else missing
    if (args.purge_others or args.dry_run) and not args.texts:  # --texts never purges (refused above): another host's set says nothing about this cache
        others, other_bytes = _others(cfg, keep)
        print(f"{others} other clip(s) ({other_bytes / MB:.1f} MB) outside this set" + (" would be purged first" if args.dry_run else " are purged first") + " — another voice's, or texts outside the set; the service must already run the voice above (its log: event audio_voice)")
    if args.purge_others and not args.dry_run:
        removed, freed = purge_others(cfg, keep)
        print(f"purged {removed} other clip(s) ({freed / MB:.1f} MB)")
    cap = cfg.audio_cache_mb * MB
    after = cache_bytes(cfg) + todo * _clip_estimate(cfg)
    print(f"{len(paths)} clip(s) planned: {len(paths) - missing} cached, {missing} to synthesise" + (f", {todo} in this run (--limit {args.limit})" if args.limit else "") + f"; ≈ {after / MB:.0f} MB in the cache afterwards, cap WD_AUDIO_CACHE_MB={cfg.audio_cache_mb}")
    if provider == "bailian":  # every clip of this run is one paid request: the characters it will bill, at the model's list price
        jobs = [(accent, text) for accent in accents for text in chosen.texts if not locate(cfg, accent, text)[0].path.is_file()]
        if args.limit:
            jobs = jobs[: args.limit]
        print(bailian_price_line(cfg, sum(len(text) for _accent, text in jobs)))
    if after > cap * 9 // 10:
        needed = -(-after * 10 // (9 * MB))  # the smallest cap the 90 % rule accepts
        print(f"wd audio-prewarm: the cache would hold ≈ {after / MB:.0f} MB, more than 90 % of WD_AUDIO_CACHE_MB={cfg.audio_cache_mb} — set it to at least {needed} (or narrow the set); otherwise the run would prune its own clips", file=sys.stderr)
        return 1
    if args.dry_run:
        return 0
    report = prewarm(
        cfg,
        chosen.texts,
        accents,
        limit=args.limit,
        progress=lambda r: print(f"  {r.done}/{r.todo}: {r.made} made ({r.bytes_made / MB:.1f} MB), {r.failed} failed, {r.seconds:.0f} s", flush=True),
    )
    print(
        f"audio-prewarm: {report.made} clip(s) made ({report.bytes_made / MB:.1f} MB) in {report.seconds:.0f} s, {report.cached} already cached, {report.failed} failed"
        + (f", {report.skipped} left for the next run (--limit)" if report.skipped else "")
        + (f" — stopped early: the last {PREWARM_ABORT_AFTER} attempts failed" if report.aborted else "")
        + (" — interrupted" if report.interrupted else "")
    )
    for detail in report.errors:
        print(f"  failed: {detail}")
    if report.interrupted:
        return 130
    rc = 0 if report.failed == 0 else 1
    if not report.aborted:
        gone = sum(1 for p in paths if not p.is_file()) - report.failed - report.skipped
        if gone > 0:
            print(f"wd audio-prewarm: {gone} clip(s) of the set were pruned by WD_AUDIO_CACHE_MB={cfg.audio_cache_mb} during the run — raise the cap and run again", file=sys.stderr)
            rc = 1
    print(f"cache: {cache_bytes(cfg) / MB:.1f} MB of {cfg.audio_cache_mb} MB")
    return rc


def cmd_audio_texts(args: argparse.Namespace) -> int:
    """``wd audio-texts [--stage S …] [--db PATH]`` — the texts ``wd audio-prewarm`` would synthesise on this host, one per line on
    stdout (the study path, ``--stage`` adding a stage's headwords), for the host that has `say` when this one serves a read-only
    cache: ``wd audio-prewarm --texts FILE`` there, then sync ``audio/`` back (DEPLOY §9). Exit 1 below schema 14, 2 without a
    database."""
    _cli_logging()
    try:
        cfg = Settings.from_env()
    except ConfigError as e:
        print(f"wd audio-texts: configuration error: {e}", file=sys.stderr)
        return 2
    from . import db  # local, like cmd_audio_prewarm

    path = Path(args.db).expanduser() if args.db else cfg.db_path
    if not path.is_file():
        print(f"wd audio-texts: no database at {path} — set WD_DATA_DIR / WD_DB_PATH or pass --db", file=sys.stderr)
        return 2
    conn = db.connect(path)
    try:
        version = db.current_version(conn)
        if version < PREWARM_FROM_VERSION:
            print(f"wd audio-texts: schema version {version} has no words.learn_rank (migration {PREWARM_FROM_VERSION:04d}) — run `wd migrate` first", file=sys.stderr)
            return 1
        chosen = prewarm_texts(conn, stages=tuple(dict.fromkeys(args.stage or ())))
    finally:
        conn.close()
    for text in chosen.texts:
        print(text)
    print(f"{len(chosen.texts)} text(s); {len(chosen.refused)} refused by the text rule", file=sys.stderr)
    return 0


PROBE_DEFAULT_TEXT = "The cat sat on the mat."  # what `wd audio-probe` speaks when no TEXT is given
PROBE_DEFAULT_TEXT_ZH = "今晚的月亮很亮。"  # … with --accent zh-CN


def cmd_audio_probe(args: argparse.Namespace) -> int:
    """``wd audio-probe [--accent en-US|en-GB|zh-CN] [TEXT]`` — synthesise ONE clip through the provider in force (any provider) and print the
    provider, the voice, the bytes, the media type and the path: the day-0 check of a 百炼 key, workspace and voice, like `wd sms-probe`
    — and, with ``--accent zh-CN``, of the Chinese voice 磨耳朵 uses (`say` only: the other providers answer `failed` / `missing`).
    A clip already cached is served from the cache and says so (pass another TEXT to reach the provider). Exit 0 made, 1 on
    ``AudioError`` (its kind and message — `busy` = 429 / 5xx, retry in a minute), 2 on a configuration error, a text the rule refuses
    or a provider that resolves to `off`."""
    _cli_logging()
    try:
        cfg = Settings.from_env()
        ensure_dirs(cfg)  # the clip lands under audio/
    except ConfigError as e:
        print(f"wd audio-probe: configuration error: {e}", file=sys.stderr)
        return 2
    provider = provider_for(cfg)
    if provider == "off":
        print("wd audio-probe: WD_AUDIO_PROVIDER resolves to off — nothing can synthesise (say on a Mac, bailian or youdao, in .env)", file=sys.stderr)
        return 2
    accent = args.accent or "en-US"
    spoken = normalize_text(args.text or (PROBE_DEFAULT_TEXT_ZH if accent == ZH else PROBE_DEFAULT_TEXT), accent)
    if spoken is None:
        rule = "characters with at least one Chinese character, Chinese punctuation and what an English sentence may carry" if accent == ZH else "Latin letters, digits, spaces and the punctuation of an English sentence"
        print(f"wd audio-probe: the text rule refuses that text (1–{MAX_TEXT_CHARS} {rule})", file=sys.stderr)
        return 2
    started = time.monotonic()
    try:
        clip, _provider, voice = locate(cfg, accent, spoken)
        cached = clip.path.is_file()
        clip = synthesize(cfg, accent, spoken)
    except AudioError as e:
        print(f"wd audio-probe: {provider} failed — {e.reason}: {e.detail or '-'}" + (" (429 / 5xx: the provider is throttling or down, usually over within a minute)" if e.reason == "busy" else ""), file=sys.stderr)
        return 1
    size = clip.path.stat().st_size
    print(f"audio-probe: provider {provider}" + (f" (model {cfg.bailian_tts_model})" if provider == "bailian" else "") + f", {accent} → {voice or '(fixed)'}, {len(spoken)} chars → {size} bytes {clip.media_type} in {time.monotonic() - started:.2f} s")
    print(f"  {clip.path}" + ("  (already cached — pass another TEXT to exercise the provider)" if cached else ""))
    return 0


def _non_negative(value: str) -> int:
    n = int(value)
    if n < 0:
        raise argparse.ArgumentTypeError("must be 0 or more")
    return n


def register_cli(sub: argparse._SubParsersAction) -> None:
    from .schemas import STAGE_ORDER  # local: the request path imports this module without the schemas

    p = sub.add_parser("audio-voices", help="the pronunciation provider in force, the installed `say` voices of the preference lists (tier, resolution) and the voice each accent gets")
    p.set_defaults(func=cmd_audio_voices)
    p = sub.add_parser("audio-probe", help="synthesise ONE clip through the configured provider and print provider, voice, bytes, media type and path — the day-0 check of a 百炼 key (exit 1 with the kind and message on failure)")
    p.add_argument("--accent", choices=list(LANGS), default="en-US", metavar="ACCENT", help="en-US (default), en-GB or zh-CN (the Chinese voice 磨耳朵 reads glosses and translations with)")
    p.add_argument("text", nargs="?", default=None, metavar="TEXT", help=f"the text to speak (default: {PROBE_DEFAULT_TEXT!r}; with --accent zh-CN {PROBE_DEFAULT_TEXT_ZH!r})")
    p.set_defaults(func=cmd_audio_probe)
    p = sub.add_parser("audio-prewarm", help="synthesise the clips of the study path — headwords with content or in a bank and their example sentences, in learning order (--stage adds a stage's headwords); anything else is made at the tap — so those taps never wait; safe next to the live service")
    p.add_argument("--accent", action="append", choices=list(ACCENTS), metavar="ACCENT", help="en-US or en-GB (repeatable); default: en-US plus every accent a learner chose")
    p.add_argument("--stage", action="append", choices=list(STAGE_ORDER), metavar="STAGE", help="also the headwords of every public valid word of this stage (repeatable; what the welcome screening and 词库 browsing can tap)")
    p.add_argument("--limit", type=_non_negative, default=0, metavar="N", help="synthesise at most N missing clips (default: all)")
    p.add_argument("--dry-run", action="store_true", help="count the texts, the clips still missing and the cache after the run, synthesise nothing")
    p.add_argument("--purge-others", action="store_true", help="first delete the cached clips outside this set (another voice's after a voice change; keeps every accent in use) — only after the service was restarted with the new voice")
    p.add_argument("--texts", default=None, metavar="FILE", help="synthesise the texts of this UTF-8 file (one per line — the output of `wd audio-texts` on the host that serves a read-only cache) instead of this host's database; both accents unless --accent says; not with --stage / --purge-others / --db")
    p.add_argument("--db", default=None, metavar="PATH", help="use this database file instead of WD_DB_PATH")
    p.set_defaults(func=cmd_audio_prewarm)
    p = sub.add_parser("audio-texts", help="print the texts `wd audio-prewarm` would synthesise here, one per line — for the host with `say` when this one serves a read-only cache (WD_AUDIO_PROVIDER=cache)")
    p.add_argument("--stage", action="append", choices=list(STAGE_ORDER), metavar="STAGE", help="also the headwords of every public valid word of this stage (repeatable)")
    p.add_argument("--db", default=None, metavar="PATH", help="use this database file instead of WD_DB_PATH")
    p.set_defaults(func=cmd_audio_texts)


__all__ = [
    "ACCENTS",
    "AudioError",
    "Clip",
    "LANGS",
    "MAX_TEXT_CHARS",
    "PREFERRED_VOICES",
    "PREFERRED_ZH_VOICES",
    "PrewarmReport",
    "PrewarmSet",
    "SCAN_INTERVAL_S",
    "ZH",
    "join_warm_up",
    "voice_key",
    "Voice",
    "accents_in_use",
    "bailian_price_line",
    "cache_bytes",
    "choose_voice",
    "choose_zh_voice",
    "cmd_audio_prewarm",
    "cmd_audio_probe",
    "cmd_audio_texts",
    "cmd_audio_voices",
    "expected_paths",
    "locate",
    "lookup",
    "normalize_text",
    "parse_voices",
    "prewarm",
    "prewarm_texts",
    "provider_for",
    "prune",
    "purge_others",
    "read_key",
    "register_cli",
    "reset_cache_accounting",
    "reset_voice_cache",
    "say_resolves",
    "say_speaks_zh",
    "say_voice_for",
    "say_voices",
    "speaks_zh",
    "synthesize",
    "texts_from_file",
    "warm_up",
    "warm_up_async",
]
