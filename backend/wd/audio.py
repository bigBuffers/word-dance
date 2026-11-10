"""Pronunciation clips for clients without an English voice (API.md endpoint 76, DESIGN §9 「Pronunciation clips」, FRONTEND §6.4).

The browser speaks with the Web Speech API and the mobile shell with the system TTS, but neither exists everywhere: Android's
WebView has no ``speechSynthesis``, the Android compatibility container of HarmonyOS NEXT (the family's Huawei tablet) has no TTS
engine the plugin can reach, and many domestic ROMs have no English voice. ``GET /media/audio?text=…&accent=en-US|en-GB``
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
* ``youdao`` — ``https://dict.youdao.com/dictvoice?audio=<text>&type=2|1`` (US / UK), the unofficial endpoint Chinese dictionary
  apps have used for years; opt-in because its terms are not published and every uncached text is sent to it. mp3.
* ``off`` — the endpoint answers 503 ``audio_unavailable`` ``{reason: "off"}`` and the clients keep whatever voice they have.
* ``auto`` (the default) — ``say`` when ``/usr/bin/say`` exists (the Mac that hosts the family instance), else ``off``.

Synthesis goes through :data:`SLOTS` semaphore slots (a stampede of cache misses must not fork twenty ``say`` processes); at
most :data:`MAX_WAITERS` requests wait for a slot (each pins a threadpool thread), a slot not obtained within :data:`SLOT_WAIT_S`
is ``AudioError('busy')``, a provider error ``AudioError('failed')``.

Two things keep the first tap fast: :func:`warm_up_async` (startup) resolves the voices — the listing and the probes, 1–3 s —
before anyone asks, and ``wd audio-prewarm`` (:func:`register_cli`) synthesises the clips of the study path (headwords with
content or in a bank and their example sentences, in learning order) ahead of time — anything else is made at the tap; ``wd audio-voices`` shows what ``say`` lists, what resolves
and what each accent gets. Another process adding or removing clips (that CLI next to the live service) is harmless: a clip
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
import time
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable

import httpx

from . import __version__
from .config import ConfigError, Settings, ensure_dirs

log = logging.getLogger("wd.audio")

ACCENTS: tuple[str, ...] = ("en-US", "en-GB")
MAX_TEXT_CHARS = 300  # above the 240 chars an example sentence may have (ai/content.py EXAMPLE_EN_MAX)
# one word, a phrase or an example sentence: Latin letters (the accented ones of café / naïve included), digits, spaces and the
# punctuation an English sentence carries — straight and typographic quotes, hyphen / en dash / em dash, ellipsis, $ % & @ /.
# Nothing else reaches a provider. The text never becomes an argument (stdin for `say`, an encoded query parameter for youdao);
# refusing a leading hyphen is defence in depth only.
TEXT_RE = re.compile(r"^(?!-)[A-Za-zÀ-ɏ0-9 '’‘“”\"\-–—….,;:!?()/&%$@]+$")

SAY_BIN = "/usr/bin/say"
AFCONVERT_BIN = "/usr/bin/afconvert"
SAY_TIMEOUT_S = 30
STDERR_EXCERPT_CHARS = 300
AAC_BITRATE = "48000"
YOUDAO_URL = "https://dict.youdao.com/dictvoice"
YOUDAO_TIMEOUT_S = 10.0
YOUDAO_TYPE = {"en-US": "2", "en-GB": "1"}
YOUDAO_MAX_BYTES = 2 * 1024 * 1024  # a sentence is ≈ 100 KB of mp3; anything bigger is not a clip
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
MEDIA = {"say": ("m4a", "audio/mp4"), "youdao": ("mp3", "audio/mpeg")}
CLIP_SUFFIXES = (".m4a", ".mp3")
MB = 1024 * 1024
_PREMIUM_RE = re.compile(r"premium|高级", re.IGNORECASE)


class AudioError(Exception):
    """No clip. ``reason``: ``off`` (no provider), ``busy`` (no synthesis slot in time) or ``failed`` (provider error)."""

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


def normalize_text(text: str) -> str | None:
    """Whitespace-collapsed ``text`` when the providers may speak it, else None."""
    spoken = " ".join(text.split())
    if not spoken or len(spoken) > MAX_TEXT_CHARS or not TEXT_RE.match(spoken):
        return None
    return spoken


def provider_for(cfg: Settings) -> str:
    """``say`` / ``youdao`` / ``off`` (``auto`` resolved, ``Settings.audio_provider_effective``)."""
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
_probes: dict[str, bytes | None] = {}  # voice name → the AIFF `say -v <name>` produced for PROBE_TEXT (None: say failed)
_choice_lock = threading.Lock()
_choices: dict[str, str] = {}  # "<override>\n<accent>" → the resolved voice name


def _probe(cfg: Settings, name: str) -> bytes | None:
    with _probe_lock:
        if name in _probes:
            return _probes[name]
    out = cfg.tmp_dir / f"audio-probe-{os.getpid()}-{threading.get_ident()}.aiff"
    try:
        _run([SAY_BIN, "-v", name, "-o", str(out)], stdin_text=PROBE_TEXT)
        data = out.read_bytes() if out.is_file() else None
    except AudioError as e:
        log.warning("say -v %r probe failed: %s", name, e.detail, extra={"event": "audio_voice_probe_failed"})
        data = None
    finally:
        out.unlink(missing_ok=True)
    with _probe_lock:
        _probes[name] = data
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


def say_voice_for(cfg: Settings, accent: str) -> str:
    """The ``say -v`` name used for ``accent``, resolved once per process (and per override): ``WD_AUDIO_SAY_VOICE`` when
    ``say`` resolves it, else the best installed preferred voice. ``AudioError('failed')`` names the problem otherwise — an
    override ``say`` does not know must not become a cache full of clips in another voice."""
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
    A failure is logged once (event ``audio_voice_failed``); the requests report it again. No-op for the other providers."""
    if provider_for(cfg) != "say":
        return
    _sweep_probes(cfg)
    for accent in ACCENTS:
        try:
            say_voice_for(cfg, accent)
        except AudioError as e:
            log.warning("no say voice for %s: %s", accent, e.detail, extra={"event": "audio_voice_failed"})
            return  # choose_voice falls back across accents: one accent without a voice means both
        except Exception:  # noqa: BLE001 — a daemon thread reports through the log, never through threading.excepthook
            log.exception("audio warm-up failed for %s", accent, extra={"event": "audio_voice_failed"})
            return


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
    far — for ``ServerFlags.audio_key`` (API.md §9): the client appends it to every clip URL, so a switched provider or voice is a new
    URL and no browser keeps playing last week's voice from its HTTP cache. Empty without a provider. Never blocks: a voice not
    resolved yet reads as a placeholder unique to this process (never the key of an earlier run) and the next ``/me`` after the
    warm-up settles it."""
    provider = provider_for(cfg)
    if provider == "off":
        return ""
    parts = [provider]
    if provider == "say":
        parts.append(cfg.audio_say_voice)
        with _choice_lock:
            parts.extend(_choices.get(f"{cfg.audio_say_voice}\n{accent}", _UNRESOLVED) for accent in ACCENTS)
    return hashlib.sha256("\n".join(parts).encode("utf-8")).hexdigest()[:8]


# ------------------------------------------------------------------------------------------------- cache
def locate(cfg: Settings, accent: str, text: str) -> tuple[Clip, str, str]:
    """``(clip, provider, voice)`` for a normalised ``text``: where the clip lives (it may not exist yet) and what makes it.

    Raises ``AudioError('off')`` without a provider and ``AudioError('failed')`` when ``say`` has no usable English voice.
    """
    provider = provider_for(cfg)
    if provider == "off":
        raise AudioError("off")
    voice = say_voice_for(cfg, accent) if provider == "say" else ""
    ext, media_type = MEDIA[provider]
    digest = hashlib.sha256(f"{provider}\n{voice}\n{accent}\n{text}".encode("utf-8")).hexdigest()
    return Clip(cfg.audio_dir / digest[:2] / f"{digest}.{ext}", media_type), provider, voice


def lookup(cfg: Settings, accent: str, text: str) -> Clip | None:
    """The cached clip (touched, so pruning removes the least recently played first), or None when it has to be synthesised."""
    clip, _provider, _voice = locate(cfg, accent, text)
    if not clip.path.is_file():
        return None
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
                _say(text, voice, tmp)
            else:
                _youdao(cfg, text, accent, tmp)
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


def _say(text: str, voice: str, out: Path) -> None:
    """``say`` → AIFF (the only format it writes without re-encoding surprises) → ``afconvert`` → AAC in an m4a."""
    aiff = out.with_name(out.name + ".aiff")
    try:
        _run([SAY_BIN, "-v", voice, "-o", str(aiff)], stdin_text=text)
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
    seen: set[str] = set()
    chosen = PrewarmSet(texts=[], refused=[])

    def add(raw: object) -> None:
        if not isinstance(raw, str) or not raw.strip():
            return
        spoken = normalize_text(raw)
        if spoken is None:
            chosen.refused.append(raw)
        elif spoken not in seen:
            seen.add(spoken)
            chosen.texts.append(spoken)

    for display, content_json in conn.execute(PREWARM_TEXTS_SQL.format(stages=stage_sql)):
        add(display)
        if not content_json:
            continue
        try:
            content = json.loads(content_json)
        except ValueError:
            continue
        examples = content.get("examples") if isinstance(content, dict) else None
        for example in examples if isinstance(examples, list) else []:
            if isinstance(example, dict):
                add(example.get("en"))
    return chosen


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
    `youdao` one request at a time with :data:`YOUDAO_PAUSE_S` between two (an unofficial endpoint). A clip already cached is
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

    with ThreadPoolExecutor(max_workers=SLOTS if provider == "say" else 1, thread_name_prefix="audio-prewarm") as pool:
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


def cmd_audio_voices(args: argparse.Namespace) -> int:
    """``wd audio-voices`` — the provider in force, the installed `say` voices of the preference lists (tier, whether `say`
    resolves them) and the voice each accent gets; exit 1 when an accent gets none, 2 on a configuration error."""
    _cli_logging()
    try:
        cfg = Settings.from_env()
        ensure_dirs(cfg)  # the probes write under tmp/
    except ConfigError as e:
        print(f"wd audio-voices: configuration error: {e}", file=sys.stderr)
        return 2
    provider = provider_for(cfg)
    print(
        f"provider: {provider} (WD_AUDIO_PROVIDER={cfg.audio_provider}); WD_AUDIO_SAY_VOICE: {cfg.audio_say_voice or '(unset — the best installed preferred voice)'}; "
        f"cache: {cache_bytes(cfg) / MB:.1f} MB of {cfg.audio_cache_mb} MB"
    )
    if provider != "say":
        print("no `say` voices to list: " + ("WD_AUDIO_PROVIDER resolves to off (say needs a Mac)" if provider == "off" else f"{provider} has one fixed voice per accent"))
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
                    probed = _probes.get(v.name)
                verdict = "probe failed — say exited non-zero (logged above)" if probed is None else "NOT resolved — say substitutes its fallback voice for this name"
            print(f"  {v.name:<26} {TIER_NAMES[v.tier]:<9} {verdict}")
    rc = 0
    for accent in ACCENTS:
        try:
            print(f"{accent} → {say_voice_for(cfg, accent)}")
        except AudioError as e:
            print(f"{accent} → none: {e.detail}")
            rc = 1
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
    """``wd audio-prewarm [--accent A …] [--stage S …] [--limit N] [--dry-run] [--purge-others] [--db PATH]`` — synthesise the clips of
    the study path (:func:`prewarm_texts`, plus the headwords of ``--stage``) for the accents in use, so those taps never wait for
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
        print("wd audio-prewarm: WD_AUDIO_PROVIDER resolves to off — nothing can synthesise (say on a Mac, or youdao, in .env)", file=sys.stderr)
        return 2
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
        voices = {accent: (say_voice_for(cfg, accent) if provider == "say" else provider) for accent in keep_accents}
    except AudioError as e:
        print(f"wd audio-prewarm: no voice — {e.detail}", file=sys.stderr)
        return 1
    scope = "headwords with content or in a bank and their example sentences" + (f", the headwords of {', '.join(args.stage)}" if args.stage else "")
    print(f"{len(chosen.texts)} text(s) a learner can tap ({scope}; learning order); " + ", ".join(f"{a} → {voices[a]}" for a in accents))
    if chosen.refused:
        print(f"{len(chosen.refused)} text(s) the text rule refuses (no server clip for those): " + "; ".join(repr(t[:60]) for t in chosen.refused[:5]))
    paths = expected_paths(cfg, chosen.texts, accents)
    keep = expected_paths(cfg, chosen.texts, keep_accents)
    missing = sum(1 for p in paths if not p.is_file())
    todo = min(missing, args.limit) if args.limit else missing
    others, other_bytes = _others(cfg, keep)
    if args.purge_others or args.dry_run:
        print(f"{others} other clip(s) ({other_bytes / MB:.1f} MB) outside this set" + (" would be purged first" if args.dry_run else " are purged first") + " — another voice's, or texts outside the set; the service must already run the voice above (its log: event audio_voice)")
    if args.purge_others and not args.dry_run:
        removed, freed = purge_others(cfg, keep)
        print(f"purged {removed} other clip(s) ({freed / MB:.1f} MB)")
    cap = cfg.audio_cache_mb * MB
    after = cache_bytes(cfg) + todo * _clip_estimate(cfg)
    print(f"{len(paths)} clip(s) planned: {len(paths) - missing} cached, {missing} to synthesise" + (f", {todo} in this run (--limit {args.limit})" if args.limit else "") + f"; ≈ {after / MB:.0f} MB in the cache afterwards, cap WD_AUDIO_CACHE_MB={cfg.audio_cache_mb}")
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


def _non_negative(value: str) -> int:
    n = int(value)
    if n < 0:
        raise argparse.ArgumentTypeError("must be 0 or more")
    return n


def register_cli(sub: argparse._SubParsersAction) -> None:
    from .schemas import STAGE_ORDER  # local: the request path imports this module without the schemas

    p = sub.add_parser("audio-voices", help="the pronunciation provider in force, the installed `say` voices of the preference lists (tier, resolution) and the voice each accent gets")
    p.set_defaults(func=cmd_audio_voices)
    p = sub.add_parser("audio-prewarm", help="synthesise the clips of the study path — headwords with content or in a bank and their example sentences, in learning order (--stage adds a stage's headwords); anything else is made at the tap — so those taps never wait; safe next to the live service")
    p.add_argument("--accent", action="append", choices=list(ACCENTS), metavar="ACCENT", help="en-US or en-GB (repeatable); default: en-US plus every accent a learner chose")
    p.add_argument("--stage", action="append", choices=list(STAGE_ORDER), metavar="STAGE", help="also the headwords of every public valid word of this stage (repeatable; what the welcome screening and 词库 browsing can tap)")
    p.add_argument("--limit", type=_non_negative, default=0, metavar="N", help="synthesise at most N missing clips (default: all)")
    p.add_argument("--dry-run", action="store_true", help="count the texts, the clips still missing and the cache after the run, synthesise nothing")
    p.add_argument("--purge-others", action="store_true", help="first delete the cached clips outside this set (another voice's after a voice change; keeps every accent in use) — only after the service was restarted with the new voice")
    p.add_argument("--db", default=None, metavar="PATH", help="use this database file instead of WD_DB_PATH")
    p.set_defaults(func=cmd_audio_prewarm)


__all__ = [
    "ACCENTS",
    "AudioError",
    "Clip",
    "MAX_TEXT_CHARS",
    "PREFERRED_VOICES",
    "PrewarmReport",
    "PrewarmSet",
    "SCAN_INTERVAL_S",
    "join_warm_up",
    "voice_key",
    "Voice",
    "accents_in_use",
    "cache_bytes",
    "choose_voice",
    "cmd_audio_prewarm",
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
    "register_cli",
    "reset_cache_accounting",
    "reset_voice_cache",
    "say_resolves",
    "say_voice_for",
    "say_voices",
    "synthesize",
    "warm_up",
    "warm_up_async",
]
