"""Shared pytest fixtures (Phase 0 — TASKS.md P0 step 7).

* a temporary ``WD_DATA_DIR`` per test with the ``WD_*`` test environment (worker off, fake claude, open
  registration, fixed secret, mini seed as ``WD_SEED_PATH``);
* ``settings`` / ``conn`` (migrated DB) / ``frozen_clock`` / ``app`` / ``client`` (TestClient running the
  lifespan, ``X-WD-Request: 1`` preset) / ``raw_client`` (no preset header);
* ``login`` — register-or-login helper through the WP2 auth endpoints;
* ``seeded`` — the 60-record mini seed imported with ``wd.seed.import_seed`` (skips while WP1 is absent);
* ``mock_http`` — ``httpx.MockTransport`` for api.openverse.org / commons.wikimedia.org / thumb.wikimedia.org /
  upload.wikimedia.org / live.staticflickr.com (probe fixtures + a Pillow-generated 640×400 JPEG; query strings
  ignored; matches on the ``Host`` header first so DNS-pinned IP URLs still hit); installed as the default
  transport of every ``httpx.Client`` created while the fixture is active.
"""

from __future__ import annotations

import io
import json
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
    skip = pytest.mark.skip(reason="needs the full 9,162-word seed (set WD_FULL_SEED_DB)")
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
        "WD_SMOKE_MOCK_HTTP": "1",
        "WD_PUBLIC_URL": "",
        "WD_CONTACT_EMAIL": "tests@example.com",
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
    """The mini seed imported through WP1's ``wd.seed.import_seed``; skipped while that module does not exist."""
    try:
        from wd.seed import import_seed  # type: ignore[import-not-found]
    except ModuleNotFoundError as e:
        if e.name == "wd.seed":
            pytest.skip("wd.seed (WP1) is not available yet")
        raise
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
_JPEG_CACHE: dict[str, bytes] = {}


def sample_jpeg() -> bytes:
    """A 640×400 JPEG generated with Pillow (cached per process)."""
    if "jpeg" not in _JPEG_CACHE:
        from PIL import Image, ImageDraw

        img = Image.new("RGB", (640, 400), (200, 60, 40))
        draw = ImageDraw.Draw(img)
        draw.ellipse((160, 60, 480, 340), fill=(240, 240, 220))
        buf = io.BytesIO()
        img.save(buf, format="JPEG", quality=85)
        _JPEG_CACHE["jpeg"] = buf.getvalue()
    return _JPEG_CACHE["jpeg"]


class MockHttp:
    """Routes provider traffic to fixtures; records every request in ``calls``."""

    IMAGE_HOSTS = ("thumb.wikimedia.org", "upload.wikimedia.org", "live.staticflickr.com")

    def __init__(self) -> None:
        self.calls: list[httpx.Request] = []
        self.openverse = json.loads((FIXTURES_DIR / "openverse_search.json").read_text(encoding="utf-8"))
        self.wikimedia = json.loads((FIXTURES_DIR / "wikimedia_search.json").read_text(encoding="utf-8"))
        self.overrides: dict[str, Callable[[httpx.Request], httpx.Response]] = {}
        self.transport = httpx.MockTransport(self.handle)

    def host_of(self, request: httpx.Request) -> str:
        host = request.headers.get("host") or request.url.host
        return host.split(":")[0].lower()

    def handle(self, request: httpx.Request) -> httpx.Response:
        self.calls.append(request)
        host = self.host_of(request)
        path = request.url.path  # query strings (?utm_source=…) are ignored on purpose
        if host in self.overrides:
            return self.overrides[host](request)
        if host == "api.openverse.org" and path.startswith("/v1/images"):
            return httpx.Response(200, json=self.openverse, headers={"x-ratelimit-limit-anon_burst": "20/min", "x-ratelimit-limit-anon_sustained": "200/day"})
        if host == "commons.wikimedia.org" and path == "/w/api.php":
            return httpx.Response(200, json=self.wikimedia)
        if host in self.IMAGE_HOSTS:
            return httpx.Response(200, content=sample_jpeg(), headers={"Content-Type": "image/jpeg"})
        return httpx.Response(404, text=f"mock_http: no route for {host}{path}")

    def calls_to(self, host: str) -> list[httpx.Request]:
        return [r for r in self.calls if self.host_of(r) == host]


@pytest.fixture
def mock_http(monkeypatch: pytest.MonkeyPatch) -> MockHttp:
    mock = MockHttp()
    original_init = httpx.Client.__init__

    def patched_init(self, *args, **kwargs):
        if kwargs.get("transport") is None:
            kwargs["transport"] = mock.transport
        original_init(self, *args, **kwargs)

    monkeypatch.setattr(httpx.Client, "__init__", patched_init)
    return mock
