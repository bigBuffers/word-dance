"""Shared pytest fixtures (Phase 0 — TASKS.md P0 step 7).

* a temporary ``WD_DATA_DIR`` per test with the ``WD_*`` test environment (worker off, fake claude, open
  registration, fixed secret, mini seed as ``WD_SEED_PATH``);
* ``settings`` / ``conn`` (migrated DB) / ``frozen_clock`` / ``app`` / ``client`` (TestClient running the
  lifespan, ``X-WD-Request: 1`` preset) / ``raw_client`` (no preset header);
* ``login`` — register-or-login helper through the WP2 auth endpoints;
* ``seeded`` — the 62-record mini seed (v2, PLAN §6 S2) imported with ``wd.seed.import_seed``;
* ``mock_http`` — ``httpx.MockTransport`` for api.openverse.org / commons.wikimedia.org / thumb.wikimedia.org /
  upload.wikimedia.org / live.staticflickr.com (probe fixtures + a Pillow-generated 640×400 JPEG; query strings
  ignored; matches on the ``Host`` header first so DNS-pinned IP URLs still hit); installed as the default
  transport of every ``httpx.Client`` created while the fixture is active.
"""

from __future__ import annotations

import os
import sqlite3
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Callable, Iterator

import httpx
import pytest
from fastapi.testclient import TestClient

TESTS_DIR = Path(__file__).resolve().parent
FIXTURES_DIR = TESTS_DIR / "fixtures"
FAKE_CLAUDE = TESTS_DIR / "fake_claude.py"
MINI_SEED = FIXTURES_DIR / "mini_seed.jsonl"
UTC = timezone.utc


def pytest_configure(config: pytest.Config) -> None:
    config.addinivalue_line("markers", "full_seed: needs the full seed (WD_FULL_SEED_DB); skipped on the mini seed")


def pytest_collection_modifyitems(config: pytest.Config, items: list[pytest.Item]) -> None:
    if os.environ.get("WD_FULL_SEED_DB"):
        return
    skip = pytest.mark.skip(reason="needs the full seed (data/seed/stats.json total_words records; set WD_FULL_SEED_DB=<imported db>)")
    for item in items:
        if "full_seed" in item.keywords:
            item.add_marker(skip)


# ------------------------------------------------------------------------------------- clock
class FrozenClock:
    """A settable clock implementing ``wd.clock.Clock``."""

    def __init__(self, start: datetime | None = None):
        self._now = (start or datetime(2026, 10, 14, 0, 0, 0, tzinfo=UTC)).astimezone(UTC).replace(microsecond=0)

    def now_utc(self) -> datetime:
        return self._now

    def set(self, when: datetime) -> None:
        self._now = when.astimezone(UTC).replace(microsecond=0)

    def advance(self, seconds: float = 0, *, minutes: float = 0, hours: float = 0, days: float = 0) -> datetime:
        self._now = self._now + timedelta(seconds=seconds, minutes=minutes, hours=hours, days=days)
        return self._now


@pytest.fixture
def frozen_clock() -> FrozenClock:
    return FrozenClock()


# -------------------------------------------------------------------------------- environment
@pytest.fixture
def fixtures_dir() -> Path:
    return FIXTURES_DIR


@pytest.fixture
def fake_claude_path() -> Path:
    return FAKE_CLAUDE


@pytest.fixture
def data_dir(tmp_path: Path) -> Path:
    d = tmp_path / "data"
    d.mkdir(mode=0o700)
    return d


@pytest.fixture
def fake_say(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Iterator[Callable[..., dict[str, Path]]]:
    """Installs `say` / `afconvert` stand-ins for wd.audio (tests call it with a `say -v ?` listing). `say -v ?` prints the
    listing; `say -v V -o X` writes `V:<stdin>` to X when V is a listed name and `fallback:<stdin>` otherwise — like the real
    say, which exits 0 and substitutes one fixed voice for every name it cannot resolve — and appends `V|<stdin>` to calls.log
    (the voice probes of wd.audio appear there as `…|hello`, the Chinese ones as `…|你好，世界`); `afconvert` copies its input to
    its output padded past MIN_CLIP_BYTES. The paths are patched into wd.audio; its voice and cache accounting are reset before
    and after.

    Chinese text (a Han character on stdin) behaves as measured on macOS 26: the voice that speaks — V, or the substitute for an
    unlisted name — writes `<speaker>:<stdin>` padded past SILENT_AIFF_BYTES when its listing row says `zh_…`, and any other
    voice a 4608-byte header-only AIFF of silence, exit 0 either way. `fallback=NAME` (a listed voice) makes that voice the
    substitute for unknown names, its output byte for byte — a zh-CN system, where `say` falls back to Tingting. `noisy=(NAME, …)`
    names voices that are not Chinese and write a clip of that size for Chinese text all the same — the classic en_US voices
    (Fred, Albert, Kathy) do: 8–11 s of noise where the newer ones write silence."""
    from wd import audio

    def install(listing_text: str, fallback: str = "fallback", noisy: tuple[str, ...] = ()) -> dict[str, Path]:
        listing = tmp_path / "voices.txt"
        listing.write_text(listing_text, encoding="utf-8")
        loud = tmp_path / "noisy.txt"
        loud.write_text("".join(f"{name}\n" for name in noisy), encoding="utf-8")
        calls = tmp_path / "calls.log"
        say = tmp_path / "say"
        say.write_text(
            "#!/bin/sh\n"
            f'if [ "$1" = "-v" ] && [ "$2" = "?" ]; then cat "{listing}"; exit 0; fi\n'
            'while [ $# -gt 0 ]; do case "$1" in -v) voice=$2; shift;; -o) out=$2; shift;; esac; shift; done\n'
            "text=$(cat)\n"
            f'if grep -q -F -- "$voice " "{listing}"; then speaker=$voice; else speaker=\'{fallback}\'; fi\n'
            # a Han character = a UTF-8 lead byte E4–E9 (the accented Latin letters and typographic punctuation of English lead with C3–E2)
            "if printf '%s' \"$text\" | LC_ALL=C grep -q \"$(printf '[\\344-\\351]')\"; then\n"
            f'  if grep -F -- "$speaker " "{listing}" | grep -q " zh_" || grep -q -x -F -- "$speaker" "{loud}"; then {{ printf \'%s:%s\' "$speaker" "$text"; head -c 9000 /dev/zero; }} > "$out"\n'
            '  else head -c 4608 /dev/zero > "$out"; fi\n'
            'else printf \'%s:%s\' "$speaker" "$text" > "$out"; fi\n'
            f'printf \'%s|%s\\n\' "$voice" "$text" >> "{calls}"\n',
            encoding="utf-8",
        )
        afconvert = tmp_path / "afconvert"
        afconvert.write_text(
            "#!/bin/sh\n"
            "for last; do :; done\n"
            "n=$#; i=0; for a; do i=$((i+1)); [ $i -eq $((n-1)) ] && src=$a; done\n"
            '{ cat "$src"; head -c 400 /dev/zero; } > "$last"\n',
            encoding="utf-8",
        )
        for script in (say, afconvert):
            script.chmod(0o755)
        monkeypatch.setattr(audio, "SAY_BIN", str(say))
        monkeypatch.setattr(audio, "AFCONVERT_BIN", str(afconvert))
        audio.reset_voice_cache()
        audio.reset_cache_accounting()
        return {"say": say, "afconvert": afconvert, "calls": calls, "listing": listing}

    yield install
    audio.reset_voice_cache()
    audio.reset_cache_accounting()


@pytest.fixture
def test_env(monkeypatch: pytest.MonkeyPatch, data_dir: Path) -> dict[str, str]:
    """The ``WD_*`` test environment; also drops ``CLAUDECODE`` (fake_claude exits 3 when it is present)."""
    env = {
        "WD_DATA_DIR": str(data_dir),
        "WD_DB_PATH": str(data_dir / "word-dance.db"),
        "WD_WORKER_ENABLED": "0",
        "WD_CLAUDE_BIN": str(FAKE_CLAUDE),
        "WD_CLAUDE_CWD": str(data_dir / "claude-cwd"),
        "WD_REGISTRATION_MODE": "open",
        "WD_SECRET_KEY": "test-secret-key-not-for-production",
        "WD_SEED_PATH": str(MINI_SEED),
        "WD_FRONTEND_DIST": str(data_dir / "no-dist"),
        "WD_TZ": "Asia/Shanghai",
        "WD_LOG_LEVEL": "WARNING",
        "WD_LOG_FORMAT": "text",
        "WD_AI_ENABLED": "1",
        "WD_IMAGES_ENABLED": "1",
        "WD_AUDIO_PROVIDER": "off",  # `auto` would pick `say` on a Mac; the audio tests opt in explicitly
        "WD_SMOKE_MOCK_HTTP": "1",
        "WD_PUBLIC_URL": "",
        "WD_CONTACT_EMAIL": "tests@example.com",
        "WD_CAPTCHA": "off",  # the image captcha in front of the public code sends; the captcha tests opt in explicitly
    }
    for k in list(os.environ):
        if k.startswith("WD_") and k not in env:
            monkeypatch.delenv(k, raising=False)
    for k, v in env.items():
        monkeypatch.setenv(k, v)
    monkeypatch.delenv("CLAUDECODE", raising=False)
    monkeypatch.delenv("FAKE_CLAUDE_MODE", raising=False)
    monkeypatch.delenv("WEB_CONCURRENCY", raising=False)
    return env


@pytest.fixture(autouse=True)
def _no_smoke_mock_leak() -> Iterator[None]:
    """``create_app`` installs the process-wide ``wd.smoke_mock`` for a ``dev=True`` settings copy (the test env carries
    ``WD_SMOKE_MOCK_HTTP=1`` like the smoke run); never let that outlive the test that built such an app."""
    yield
    from wd.smoke_mock import uninstall

    uninstall()


@pytest.fixture
def settings(test_env: dict[str, str]):
    from wd.config import Settings, ensure_dirs

    cfg = Settings.from_env()
    ensure_dirs(cfg)
    return cfg


@pytest.fixture
def conn(settings) -> Iterator[sqlite3.Connection]:
    """A migrated database connection (closed afterwards)."""
    from wd import db

    c = db.connect(settings.db_path)
    db.run_migrations(c)
    try:
        yield c
    finally:
        c.close()


@pytest.fixture
def connect(settings) -> Callable[[], sqlite3.Connection]:
    """Connection factory for code that needs its own connections (queue drains, threads)."""
    from wd import db

    def factory() -> sqlite3.Connection:
        return db.connect(settings.db_path)

    return factory


# --------------------------------------------------------------------------------------- app
@pytest.fixture
def app(settings, frozen_clock: FrozenClock):
    from wd.main import create_app

    return create_app(settings, clock=frozen_clock, configure_logs=False)


@pytest.fixture
def client(app) -> Iterator[TestClient]:
    """TestClient with the lifespan running and ``X-WD-Request: 1`` preset (API.md §1 CSRF rule)."""
    with TestClient(app, base_url="http://testserver") as c:
        c.headers["X-WD-Request"] = "1"
        yield c


@pytest.fixture
def raw_client(app) -> Iterator[TestClient]:
    """TestClient without the CSRF header (for the 403 tests)."""
    with TestClient(app, base_url="http://testserver") as c:
        yield c


@pytest.fixture
def login(client: TestClient) -> Callable[..., dict[str, Any]]:
    """``login(username, password='Passw0rd!xyz', **register_fields) -> user`` — registers when the login fails."""

    def _login(username: str, password: str = "Passw0rd!xyz", **register_fields: Any) -> dict[str, Any]:
        r = client.post("/api/auth/login", json={"username": username, "password": password})
        if r.status_code == 200:
            return r.json()["user"]
        body = {"username": username, "password": password, **register_fields}
        r = client.post("/api/auth/register", json=body)
        assert r.status_code == 201, r.text
        return r.json()["user"]

    return _login


@pytest.fixture
def seeded(conn: sqlite3.Connection) -> sqlite3.Connection:
    """The mini seed imported through WP1's ``wd.seed.import_seed``."""
    from wd.seed import import_seed

    import_seed(conn, str(MINI_SEED))
    return conn


@pytest.fixture
def fake_claude_env(test_env: dict[str, str]) -> Callable[[str], dict[str, str]]:
    """``fake_claude_env(mode) -> env dict`` for spawning ``fake_claude.py`` directly (no ``CLAUDECODE``)."""

    def _env(mode: str = "ok") -> dict[str, str]:
        env = {k: v for k, v in os.environ.items() if k != "CLAUDECODE"}
        env["FAKE_CLAUDE_MODE"] = mode
        return env

    return _env


# --------------------------------------------------------------------------------- mock http
def sample_jpeg() -> bytes:
    """A 640×400 JPEG generated with Pillow (cached per process) — the smoke mock's, so fixture and smoke run agree."""
    from wd.smoke_mock import sample_jpeg as _sample_jpeg

    return _sample_jpeg()


@pytest.fixture
def mock_http(monkeypatch: pytest.MonkeyPatch):
    """``wd.smoke_mock.MockHttp`` (the class ``WD_SMOKE_MOCK_HTTP=1`` installs process-wide) scoped to one test."""
    from wd.smoke_mock import MockHttp

    mock = MockHttp(FIXTURES_DIR)
    original_init = httpx.Client.__init__

    def patched_init(self, *args, **kwargs):
        if kwargs.get("transport") is None:
            kwargs["transport"] = mock.transport
        original_init(self, *args, **kwargs)

    monkeypatch.setattr(httpx.Client, "__init__", patched_init)
    return mock
