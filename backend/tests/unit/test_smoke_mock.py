"""wd.smoke_mock: WD_SMOKE_MOCK_HTTP=1 (+ WD_DEV=1) makes every default httpx.Client of the process answer from the
provider fixtures and pins the SSRF DNS step — `make smoke` must never talk to Wikimedia/Openverse."""

from __future__ import annotations

from dataclasses import replace

import httpx
import pytest

from wd import smoke_mock
from wd.images import fetch
from wd.images.providers import base


@pytest.fixture
def installed():
    smoke_mock.uninstall()
    try:
        yield smoke_mock.install()
    finally:
        smoke_mock.uninstall()


def test_install_routes_every_default_client_to_the_fixtures(settings, installed):
    assert isinstance(httpx.Client()._transport, httpx.MockTransport)
    assert isinstance(base.make_client(settings)._transport, httpx.MockTransport)  # providers
    assert isinstance(fetch.download_client(settings)._transport, httpx.MockTransport)  # downloads
    assert isinstance(httpx.Client(transport=httpx.HTTPTransport())._transport, httpx.HTTPTransport)  # an injected transport wins
    with base.make_client(settings) as c:
        r = c.get("https://commons.wikimedia.org/w/api.php?action=query&generator=search&gsrsearch=abandon")
        assert r.status_code == 200 and "query" in r.json()
        assert c.get("https://api.openverse.org/v1/images/?q=abandon&page_size=20").json()["result_count"] >= 1
        img = c.get(f"https://{smoke_mock.PUBLIC_IP}/wikipedia/commons/x.jpg", headers={"Host": "upload.wikimedia.org"})  # DNS-pinned URL
        assert img.headers["content-type"] == "image/jpeg" and img.content[:3] == b"\xff\xd8\xff"
        assert c.get("https://example.com/").status_code == 404
    assert len(installed.calls_to("commons.wikimedia.org")) == 1 and len(installed.calls) == 4
    assert fetch.resolve_host("thumb.wikimedia.org") == [smoke_mock.PUBLIC_IP]  # no real DNS during the pin step


def test_uninstall_restores_httpx_and_dns(settings):
    smoke_mock.install()
    smoke_mock.uninstall()
    assert smoke_mock.active() is None
    assert isinstance(httpx.Client()._transport, httpx.HTTPTransport)
    assert isinstance(base.make_client(settings)._transport, httpx.HTTPTransport)
    assert fetch.resolve_host.__name__ == "resolve_host"
    smoke_mock.uninstall()  # idempotent


def test_the_flag_is_honoured_only_together_with_dev(settings):
    try:
        assert smoke_mock.install_if_enabled(replace(settings, smoke_mock_http=False, dev=True)) is None
        assert smoke_mock.install_if_enabled(replace(settings, smoke_mock_http=True, dev=False)) is None  # production never mocks itself
        assert smoke_mock.install_from_env({"WD_SMOKE_MOCK_HTTP": "1"}) is None
        assert smoke_mock.install_from_env({"WD_SMOKE_MOCK_HTTP": "0", "WD_DEV": "1"}) is None
        assert smoke_mock.active() is None
        mock = smoke_mock.install_if_enabled(replace(settings, smoke_mock_http=True, dev=True))
        assert mock is not None and smoke_mock.active() is mock
        assert smoke_mock.install() is mock and smoke_mock.install_from_env({"WD_SMOKE_MOCK_HTTP": "1", "WD_DEV": "1"}) is mock  # idempotent
    finally:
        smoke_mock.uninstall()


def test_create_app_installs_the_mock_for_wd_serve(settings, frozen_clock):
    from wd.main import create_app

    try:
        create_app(replace(settings, smoke_mock_http=True, dev=False), clock=frozen_clock, configure_logs=False)
        assert smoke_mock.active() is None
        create_app(replace(settings, smoke_mock_http=True, dev=True), clock=frozen_clock, configure_logs=False)
        assert smoke_mock.active() is not None and isinstance(httpx.Client()._transport, httpx.MockTransport)
    finally:
        smoke_mock.uninstall()


def test_cli_main_installs_the_mock_for_every_wd_subprocess(test_env, monkeypatch):
    """`make smoke` drains the queue with `wd worker-once` subprocesses (and may run `wd fetch-image`): their process
    must mock the providers like `wd serve` does, under the same WD_SMOKE_MOCK_HTTP=1 + WD_DEV=1 gate."""
    from wd import cli

    monkeypatch.setenv("WD_SMOKE_MOCK_HTTP", "1")
    monkeypatch.delenv("WD_DEV", raising=False)
    try:
        assert cli.main(["version"]) == 0
        assert smoke_mock.active() is None  # the flag alone is refused: a production `wd` command never mocks itself
        monkeypatch.setenv("WD_DEV", "1")
        assert cli.main(["version"]) == 0
        mock = smoke_mock.active()
        assert mock is not None and isinstance(httpx.Client()._transport, httpx.MockTransport)
        assert fetch.resolve_host("thumb.wikimedia.org") == [smoke_mock.PUBLIC_IP]  # the SSRF pin step needs no DNS either
        assert cli.main(["worker-once"]) == 0 and smoke_mock.active() is mock  # the real smoke subcommand keeps the same mock
    finally:
        smoke_mock.uninstall()


def test_missing_fixtures_degrade_to_empty_provider_answers(tmp_path):
    mock = smoke_mock.MockHttp(tmp_path)
    with httpx.Client(transport=mock.transport) as c:
        assert c.get("https://api.openverse.org/v1/images/?q=x").json()["results"] == []
        assert c.get("https://commons.wikimedia.org/w/api.php").json() == {"batchcomplete": ""}
