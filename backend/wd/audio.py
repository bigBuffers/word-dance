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
"""

from __future__ import annotations

import hashlib
import logging
import os
import re
import signal
import subprocess
import threading
import time
from dataclasses import dataclass
from pathlib import Path

import httpx

from . import __version__
from .config import Settings

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
PROBE_TEXT = "hello"
UNKNOWN_VOICE = "wd-no-such-voice-7f3a"  # what `say` falls back to for this name is what it falls back to for any unknown name

# `say` voices by base name in order of preference per accent. Of one base name the best installed tier wins — "(Premium)" over
# "(Enhanced)" (localised on a zh-CN Mac: "(高级)" / "(增强)") over the compact voice. The Eloquence voices (Eddy, Flo, Reed,
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
    log.info("say voice for %s: %s", accent, chosen, extra={"event": "audio_voice"})
    with _choice_lock:
        _choices[key] = chosen
    return chosen


def reset_voice_cache() -> None:
    """Forgets the listing, the probes and the resolved choices (tests; a downloaded voice otherwise needs a restart)."""
    global _voices_cache, _voices_failed_at
    with _voices_lock:
        _voices_cache = None
        _voices_failed_at = 0.0
    with _probe_lock:
        _probes.clear()
    with _choice_lock:
        _choices.clear()


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
_cache_bytes: int | None = None  # bytes of clips under audio_dir, scanned once per process and kept current by synthesize()


def _scan(root: Path) -> list[tuple[float, int, Path]]:
    """``(mtime, size, path)`` of every clip under ``root``."""
    found: list[tuple[float, int, Path]] = []
    if not root.is_dir():
        return found
    for sub in root.iterdir():
        if not sub.is_dir():
            continue
        for f in sub.iterdir():
            if f.suffix in CLIP_SUFFIXES and f.is_file():
                st = f.stat()
                found.append((st.st_mtime, st.st_size, f))
    return found


def cache_bytes(cfg: Settings) -> int:
    """Bytes of cached clips (the running total, scanned on first use)."""
    global _cache_bytes
    with _size_lock:
        if _cache_bytes is None:
            _cache_bytes = sum(size for _mtime, size, _path in _scan(cfg.audio_dir))
        return _cache_bytes


def _account(cfg: Settings, added: int) -> None:
    global _cache_bytes
    with _size_lock:
        if _cache_bytes is None:
            _cache_bytes = sum(size for _mtime, size, _path in _scan(cfg.audio_dir))  # the scan already sees the new clip
        else:
            _cache_bytes += added
        total = _cache_bytes
    cap = cfg.audio_cache_mb * MB
    if total > cap:
        prune(cfg, cap * 9 // 10)


def prune(cfg: Settings, target_bytes: int) -> int:
    """Removes the least recently played clips (by mtime — :func:`lookup` touches a served clip) until at most ``target_bytes``
    remain; returns how many were removed."""
    global _cache_bytes
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
    if removed:
        log.info("audio cache over WD_AUDIO_CACHE_MB=%d: %d clip(s) removed, %d bytes kept", cfg.audio_cache_mb, removed, total, extra={"event": "audio_cache_pruned"})
    return removed


def reset_cache_accounting() -> None:
    """Forgets the running total (tests)."""
    global _cache_bytes
    with _size_lock:
        _cache_bytes = None


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


__all__ = [
    "ACCENTS",
    "AudioError",
    "Clip",
    "MAX_TEXT_CHARS",
    "PREFERRED_VOICES",
    "Voice",
    "cache_bytes",
    "choose_voice",
    "locate",
    "lookup",
    "normalize_text",
    "parse_voices",
    "provider_for",
    "prune",
    "reset_cache_accounting",
    "reset_voice_cache",
    "say_resolves",
    "say_voice_for",
    "say_voices",
    "synthesize",
]
