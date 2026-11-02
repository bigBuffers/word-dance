"""``WD_SMOKE_MOCK_HTTP=1``: fixture-backed ``httpx`` transport for the smoke run and the tests (DEPLOY §4, DESIGN §12).

:func:`install` makes an ``httpx.MockTransport`` the default transport of every ``httpx.Client`` created in this
process — image providers (``images/providers/base.make_client``), downloads (``images/fetch.download_client``),
webhooks (``delivery/webhook._client``) — and pins ``images.fetch.resolve_host`` to a public test address so the SSRF
pin step needs no DNS: nothing leaves the box, offline or not. Routes (query strings ignored, matched on the ``Host``
header first so DNS-pinned IP URLs still hit): ``api.openverse.org/v1/images*`` → ``openverse_search.json``,
``commons.wikimedia.org/w/api.php`` → ``wikimedia_search.json``, the Wikimedia / Flickr image hosts → a
Pillow-generated 640×400 JPEG, everything else 404. Fixtures are read from ``WD_SMOKE_FIXTURES_DIR`` (default
``<backend>/tests/fixtures``; missing files degrade to empty provider answers with a warning).

Honoured only together with ``WD_DEV=1`` (:func:`install_if_enabled` / :func:`install_from_env`), so a production
``.env`` can never mock itself. ``main.create_app`` calls it for ``wd serve`` **and** ``cli.main`` calls it for every
other ``wd`` command, so the ``wd worker-once`` / ``wd tick --once`` / ``wd fetch-image`` subprocesses ``make smoke``
spawns mock their providers exactly like the server (a worker process that forgot would hit the real providers, or
silently fall back to the card). ``tests/conftest.py`` reuses :class:`MockHttp`, so the pytest fixture and the smoke
run cannot diverge.
"""

from __future__ import annotations

import io
import json
import logging
import os
import threading
from pathlib import Path
from typing import Any, Callable, Mapping

import httpx

log = logging.getLogger("wd.smoke_mock")

PUBLIC_IP = "93.184.216.34"  # what `images.fetch.resolve_host` answers while the mock is installed (a public, non-reserved address)
IMAGE_HOSTS: tuple[str, ...] = ("thumb.wikimedia.org", "upload.wikimedia.org", "live.staticflickr.com")
DEFAULT_FIXTURES_DIR = Path(__file__).resolve().parents[1] / "tests" / "fixtures"
EMPTY_OPENVERSE: dict[str, Any] = {"result_count": 0, "page_count": 0, "page_size": 20, "page": 1, "results": []}
EMPTY_WIKIMEDIA: dict[str, Any] = {"batchcomplete": ""}
TRUE_VALUES = ("1", "true", "yes", "on")  # config.Settings.from_env flag spelling

_JPEG_CACHE: dict[str, bytes] = {}
_lock = threading.Lock()
_state: dict[str, Any] = {}  # {"mock": MockHttp, "client_init": original httpx.Client.__init__, "resolve_host": original}


def fixtures_dir() -> Path:
    return Path(os.environ.get("WD_SMOKE_FIXTURES_DIR") or DEFAULT_FIXTURES_DIR)


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


def _load_fixture(directory: Path, name: str, fallback: Mapping[str, Any]) -> dict[str, Any]:
    path = directory / name
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as e:
        log.warning("smoke mock: fixture %s unavailable (%s); providers answer empty", path, e)
        return dict(fallback)
    return data if isinstance(data, dict) else dict(fallback)


class MockHttp:
    """Routes provider traffic to fixtures; records every request in ``calls`` (``overrides[host]`` replaces a route)."""

    IMAGE_HOSTS = IMAGE_HOSTS

    def __init__(self, fixtures: Path | None = None) -> None:
        directory = fixtures or fixtures_dir()
        self.calls: list[httpx.Request] = []
        self.openverse = _load_fixture(directory, "openverse_search.json", EMPTY_OPENVERSE)
        self.wikimedia = _load_fixture(directory, "wikimedia_search.json", EMPTY_WIKIMEDIA)
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


def active() -> MockHttp | None:
    """The installed mock, if any."""
    return _state.get("mock")


def install(fixtures: Path | None = None) -> MockHttp:
    """Install the process-wide mock (idempotent): default ``httpx.Client`` transport + pinned ``resolve_host``."""
    with _lock:
        mock = _state.get("mock")
        if mock is not None:
            return mock
        mock = MockHttp(fixtures)
        original_init = httpx.Client.__init__

        def patched_init(self: httpx.Client, *args: Any, **kwargs: Any) -> None:
            if kwargs.get("transport") is None:  # an explicitly injected transport always wins
                kwargs["transport"] = mock.transport
            original_init(self, *args, **kwargs)

        def pinned_resolve_host(host: str) -> list[str]:
            return [PUBLIC_IP]

        httpx.Client.__init__ = patched_init  # type: ignore[method-assign]
        from .images import fetch

        _state.update(mock=mock, client_init=original_init, patched_init=patched_init, resolve_host=fetch.resolve_host, pinned=pinned_resolve_host)
        fetch.resolve_host = pinned_resolve_host  # type: ignore[assignment]
        log.warning("WD_SMOKE_MOCK_HTTP: outbound httpx traffic is served from fixtures (%s); nothing leaves this process", fixtures or fixtures_dir())
        return mock


def uninstall() -> None:
    """Undo :func:`install` (tests). A patch somebody layered on top of ours (pytest ``monkeypatch``) is left alone."""
    with _lock:
        if not _state:
            return
        if httpx.Client.__init__ is _state["patched_init"]:
            httpx.Client.__init__ = _state["client_init"]  # type: ignore[method-assign]
        from .images import fetch

        if fetch.resolve_host is _state["pinned"]:
            fetch.resolve_host = _state["resolve_host"]
        _state.clear()


def install_if_enabled(cfg: Any) -> MockHttp | None:
    """:func:`install` when ``cfg.smoke_mock_http`` and ``cfg.dev`` are both set; a flag without ``WD_DEV=1`` is refused."""
    if not getattr(cfg, "smoke_mock_http", False):
        return None
    if not getattr(cfg, "dev", False):
        log.warning("WD_SMOKE_MOCK_HTTP=1 ignored: it needs WD_DEV=1 (a production instance never mocks its providers)")
        return None
    return install()


def install_from_env(env: Mapping[str, str] | None = None) -> MockHttp | None:
    """The same gate read straight from the environment (for CLI entry points that have no ``Settings`` yet)."""
    e = os.environ if env is None else env
    on = str(e.get("WD_SMOKE_MOCK_HTTP", "")).strip().lower() in TRUE_VALUES
    dev = str(e.get("WD_DEV", "")).strip().lower() in TRUE_VALUES
    if not on:
        return None
    if not dev:
        log.warning("WD_SMOKE_MOCK_HTTP=1 ignored: it needs WD_DEV=1 (a production instance never mocks its providers)")
        return None
    return install()


__all__ = ["MockHttp", "PUBLIC_IP", "active", "fixtures_dir", "install", "install_from_env", "install_if_enabled", "sample_jpeg", "uninstall"]
