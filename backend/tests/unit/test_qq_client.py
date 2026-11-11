"""wd/delivery/qq.py — the QQ 互联 adapter of API.md §3.3 endpoints 118 / 119: the authorize URL, `exchange` / `openid` over
`httpx.MockTransport` (`fmt=json`, the legacy JSONP and urlencoded answers, QQ's numeric error codes → `invalid_code` / `config` /
`temporary`, the key scrubbed from messages, transport failures), `read_key`, the fake client's deterministic mapping and the factory."""

from __future__ import annotations

import os
from pathlib import Path
from urllib.parse import parse_qs, urlsplit

import httpx
import pytest

from wd.config import Settings
from wd.delivery import qq
from wd.delivery.qq import FakeQQClient, QQApiClient, QQError

CALLBACK = "https://relay.example.cn/api/auth/qq/callback"


def _key_file(tmp_path: Path, text: str = "APPKEY-secret-123\n") -> str:
    path = tmp_path / "qq.key"
    path.write_text(text, encoding="utf-8")
    os.chmod(path, 0o600)
    return str(path)


def _cfg(tmp_path: Path) -> Settings:
    return Settings.from_env({"WD_QQ_APPID": "101000000", "WD_QQ_KEY_FILE": _key_file(tmp_path), "WD_QQ_CALLBACK_URL": CALLBACK})


def _install(monkeypatch: pytest.MonkeyPatch, handler) -> list[httpx.Request]:
    calls: list[httpx.Request] = []

    def recording(request: httpx.Request) -> httpx.Response:
        calls.append(request)
        return handler(request)

    transport = httpx.MockTransport(recording)
    monkeypatch.setattr(qq, "CLIENT_FACTORY", lambda: httpx.Client(transport=transport))
    return calls


def test_authorize_url_matches_the_documented_shape(tmp_path: Path):
    client = QQApiClient.from_settings(_cfg(tmp_path))
    assert client is not None and client.configured is True and QQApiClient.from_settings(Settings.from_env({})) is None
    url = client.authorize_url("12.abc.def")
    parts = urlsplit(url)
    assert f"{parts.scheme}://{parts.netloc}{parts.path}" == "https://graph.qq.com/oauth2.0/authorize"
    assert parts.query == "response_type=code&client_id=101000000&redirect_uri=https%3A%2F%2Frelay.example.cn%2Fapi%2Fauth%2Fqq%2Fcallback&state=12.abc.def&scope=get_user_info"
    assert parse_qs(parts.query)["redirect_uri"] == [CALLBACK]


def test_exchange_and_openid_with_fmt_json(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/oauth2.0/token":
            return httpx.Response(200, json={"access_token": "TOKEN-1", "expires_in": "7776000", "refresh_token": "R"})
        return httpx.Response(200, json={"client_id": "101000000", "openid": "OPENID-1"})

    calls = _install(monkeypatch, handler)
    client = QQApiClient(_cfg(tmp_path))
    assert client.exchange("CODE-1") == "TOKEN-1"
    token_call = parse_qs(calls[0].url.query.decode())
    assert calls[0].method == "GET" and calls[0].url.host == "graph.qq.com" and calls[0].url.path == "/oauth2.0/token"
    assert token_call == {"grant_type": ["authorization_code"], "client_id": ["101000000"], "client_secret": ["APPKEY-secret-123"], "code": ["CODE-1"], "redirect_uri": [CALLBACK], "fmt": ["json"]}
    assert calls[0].headers["user-agent"].startswith("word-Dance/")
    assert client.openid("TOKEN-1") == "OPENID-1"
    assert parse_qs(calls[1].url.query.decode()) == {"access_token": ["TOKEN-1"], "fmt": ["json"]} and calls[1].url.path == "/oauth2.0/me"


def test_legacy_answers_are_parsed_too(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/oauth2.0/token":
            return httpx.Response(200, text="access_token=TOKEN-2&expires_in=7776000&refresh_token=R")
        return httpx.Response(200, text='callback( {"client_id":"101000000","openid":"OPENID-2"} );\n')

    _install(monkeypatch, handler)
    client = QQApiClient(_cfg(tmp_path))
    assert client.exchange("CODE-2") == "TOKEN-2" and client.openid("TOKEN-2") == "OPENID-2"
    assert qq.parse_answer('callback( {"error":100016,"error_description":"access token check failed"} );') == {"error": 100016, "error_description": "access token check failed"}
    assert qq.parse_answer("") == {} and qq.parse_answer("<html>busy</html>") == {} and qq.parse_answer("[1]") == {} and qq.parse_answer("callback( [1] );") == {}


@pytest.mark.parametrize(
    ("body", "status", "kind", "code"),
    [
        ('{"error":100019,"error_description":"code to user error"}', 200, "invalid_code", "100019"),
        ('{"error":100020,"error_description":"code is reused error"}', 400, "invalid_code", "100020"),
        ('callback( {"error":100016,"error_description":"access token check failed"} );', 200, "invalid_code", "100016"),
        ('{"error":100005,"error_description":"client secret is invalid"}', 200, "config", "100005"),
        ('{"error":100010,"error_description":"redirect uri is illegal"}', 200, "config", "100010"),
        ('{"error":100030,"error_description":"user does not grant"}', 200, "temporary", "100030"),
        ("<html>502 Bad Gateway</html>", 502, "temporary", "HTTP_502"),
        ("", 200, "temporary", "HTTP_200"),
        ('{"expires_in":"1"}', 200, "temporary", None),
    ],
)
def test_provider_refusals_map_to_the_closed_vocabulary(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, body: str, status: int, kind: str, code: str | None):
    _install(monkeypatch, lambda request: httpx.Response(status, text=body))
    client = QQApiClient(_cfg(tmp_path))
    with pytest.raises(QQError) as e:
        client.exchange("CODE-3")
    assert (e.value.kind, e.value.code) == (kind, code)
    assert "APPKEY-secret-123" not in str(e.value) and "CODE-3" not in str(e.value)
    assert qq.classify("100019") == "invalid_code" and qq.classify("100001") == "config" and qq.classify(None) == "temporary" and qq.classify("") == "temporary"


def test_transport_failures_and_a_missing_key_file(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture):
    def boom(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectTimeout("timed out")

    _install(monkeypatch, boom)
    cfg = _cfg(tmp_path)
    client = QQApiClient(cfg)
    with pytest.raises(QQError) as e:
        client.openid("TOKEN-9")
    assert e.value.kind == "temporary" and e.value.code is None and "Network.ConnectTimeout" in str(e.value) and "TOKEN-9" not in str(e.value)
    # the key is read at call time: an unreadable file is a config error, never a network call
    assert qq.read_key(cfg) == "APPKEY-secret-123"
    Path(cfg.qq_key_file).write_text("\n", encoding="utf-8")
    assert qq.read_key(cfg) is None
    Path(cfg.qq_key_file).unlink()
    assert qq.read_key(cfg) is None and qq.read_key(Settings.from_env({})) is None
    with pytest.raises(QQError) as e:
        client.exchange("CODE-9")
    assert e.value.kind == "config" and "WD_QQ_KEY_FILE" in str(e.value)
    # a group-readable key file only warns
    key = Path(_key_file(tmp_path, "APPKEY-2\n"))
    key.chmod(0o644)
    with caplog.at_level("WARNING", logger="wd.delivery.qq"):
        assert qq.read_key(Settings.from_env({"WD_QQ_APPID": "1", "WD_QQ_KEY_FILE": str(key), "WD_QQ_CALLBACK_URL": CALLBACK})) == "APPKEY-2"
    assert any("chmod 600" in r.getMessage() for r in caplog.records)


def test_fake_client_maps_codes_tokens_and_openids_by_prefix():
    fake = FakeQQClient()
    assert fake.configured is True
    assert fake.authorize_url("12.abc.def") == "/api/auth/fake/qq?state=12.abc.def"
    assert fake.exchange("qq-code-alice") == "qq-token-alice" and fake.openid("qq-token-alice") == "qq_alice"
    assert fake.calls == [("authorize_url", "12.abc.def"), ("exchange", "qq-code-alice"), ("openid", "qq-token-alice")]
    for bad in ("bad-code", "badqq-code-x", "nonsense", "qq-code-", ""):
        with pytest.raises(QQError) as e:
            fake.exchange(bad)
        assert e.value.kind == "invalid_code"
    for bad in ("bad-token", "qq-code-alice", "qq-token-"):
        with pytest.raises(QQError) as e:
            fake.openid(bad)
        assert e.value.kind == "invalid_code"
    for down in (fake.exchange, fake.openid):
        with pytest.raises(QQError) as e:
            down("down-x")
        assert e.value.kind == "temporary"
    with pytest.raises(ValueError):
        QQError("bogus", "x")
    assert qq.KINDS == ("invalid_code", "config", "temporary") and qq.FAKE_CODE_PREFIX == "qq-code-" and qq.FAKE_TOKEN_PREFIX == "qq-token-" and qq.FAKE_OPENID_PREFIX == "qq_"


def test_factory_follows_the_settings(tmp_path: Path):
    assert qq.qq_client_from_settings(Settings.from_env({})) is None
    assert isinstance(qq.qq_client_from_settings(Settings.from_env({"WD_DEV": "1", "WD_AUTH_FAKE_PROVIDERS": "1"})), FakeQQClient)
    real = qq.qq_client_from_settings(Settings.from_env({"WD_QQ_APPID": "101000000", "WD_QQ_KEY_FILE": _key_file(tmp_path), "WD_QQ_CALLBACK_URL": CALLBACK, "WD_DEV": "1", "WD_AUTH_FAKE_PROVIDERS": "1"}))
    assert isinstance(real, QQApiClient)  # a configured provider beats the fakes
