"""wd/delivery/apple.py — Sign in with Apple without a third-party library (API.md §3.3 endpoints 120 / 121): `verify_id_token` (good /
tampered / wrong aud / expired / wrong nonce or its sha256 / unknown kid → one JWKS refetch / alg none refused / wrong issuer / no sub), the
JWKS client's 24 h cache over `httpx.MockTransport` (force, TTL, the one-fetch-per-minute floor on forced refetches, a failed refetch
serving the cached keys with a warning, failures without a cache → `temporary`), the fake key's JWKS and signer, `authorize_url` for a
configured instance and the fake consent page, and the factory."""

from __future__ import annotations

import hashlib
import json
import logging
import types
from dataclasses import replace
from datetime import datetime, timedelta, timezone
from urllib.parse import parse_qs, urlsplit

import httpx
import pytest

from wd import rsa_verify
from wd.config import Settings
from wd.delivery import apple
from wd.delivery.apple import AppleError, AppleJwksClient, FakeAppleKeys, fake_id_token, fake_jwk, fake_sign, verify_id_token

NOW = datetime(2026, 10, 14, 0, 0, 0, tzinfo=timezone.utc)
NONCE = "0123456789abcdef0123456789abcdef"
AUD = "com.worddance.web"


class Keys:
    """A JWKS source whose answers are scripted per call (the unknown-kid refetch rule is asserted through `fetches`)."""

    def __init__(self, *answers):
        self.answers = list(answers)
        self.fetches = 0
        self.forced: list[bool] = []

    def jwks(self, force: bool = False):
        self.fetches += 1
        self.forced.append(force)
        answer = self.answers.pop(0) if len(self.answers) > 1 else self.answers[0]
        if isinstance(answer, Exception):
            raise answer
        return answer


def token(**overrides):
    """A fake id_token with any claim overridden (`None` removes it); header overrides through `header=`."""
    header = {"alg": "RS256", "kid": apple.FAKE_KEY_KID, "typ": "JWT", **overrides.pop("header", {})}
    header = {k: v for k, v in header.items() if v is not None}
    iat = int(NOW.timestamp())
    claims = {"iss": apple.APPLE_ISSUER, "aud": AUD, "sub": "apple_000123", "nonce": NONCE, "iat": iat, "exp": iat + 600, **overrides}
    claims = {k: v for k, v in claims.items() if v is not None}
    h = apple._b64url_json(header)
    p = apple._b64url_json(claims)
    sig = apple._b64url(fake_sign(f"{h}.{p}".encode("ascii")))
    return f"{h}.{p}.{sig}"


def refused(tok, *, code: str, keys=None, client_ids=(AUD,), now=NOW, nonce=NONCE, kind="invalid_token"):
    with pytest.raises(AppleError) as e:
        verify_id_token(tok, keys=keys or FakeAppleKeys(), client_ids=client_ids, now=now, nonce=nonce)
    assert (e.value.kind, e.value.code) == (kind, code), (e.value.kind, e.value.code, str(e.value))


def test_a_good_token_verifies_and_returns_the_claims():
    keys = FakeAppleKeys()
    claims = verify_id_token(token(), keys=keys, client_ids=("", AUD, "com.worddance.app"), now=NOW, nonce=NONCE)
    assert claims["sub"] == "apple_000123" and claims["aud"] == AUD and claims["iss"] == "https://appleid.apple.com" and keys.fetches == 1
    # fake_id_token is the same token shape the fake consent page mints
    minted = fake_id_token("apple_abc", aud="fake-apple", nonce=NONCE, now=NOW, exp_s=120)
    header, payload, _sig = minted.split(".")
    assert json.loads(rsa_verify.b64url_decode(header)) == {"alg": "RS256", "kid": "fake-apple-key-1", "typ": "JWT"}
    assert json.loads(rsa_verify.b64url_decode(payload)) == {"aud": "fake-apple", "exp": int(NOW.timestamp()) + 120, "iat": int(NOW.timestamp()), "iss": "https://appleid.apple.com", "nonce": NONCE, "sub": "apple_abc"}
    assert verify_id_token(minted, keys=keys, client_ids=("fake-apple",), now=NOW + timedelta(seconds=119), nonce=NONCE)["sub"] == "apple_abc"
    refused(minted, code="exp", client_ids=("fake-apple",), now=NOW + timedelta(seconds=120))
    # the hashed nonce Apple sends for native flows is accepted too; no nonce check when the caller has none
    hashed = token(nonce=hashlib.sha256(NONCE.encode()).hexdigest())
    assert verify_id_token(hashed, keys=keys, client_ids=(AUD,), now=NOW, nonce=NONCE)["sub"] == "apple_000123"
    assert verify_id_token(token(nonce="whatever"), keys=keys, client_ids=(AUD,), now=NOW, nonce=None)["sub"] == "apple_000123"
    # `aud` as a list (RFC 7519) works when one entry is ours
    assert verify_id_token(token(aud=["other", AUD]), keys=keys, client_ids=(AUD,), now=NOW, nonce=NONCE)["aud"] == ["other", AUD]


def test_tampered_tokens_are_refused_with_the_reason_in_code():
    good = token()
    h, p, s = good.split(".")
    other_payload = apple._b64url_json({**json.loads(rsa_verify.b64url_decode(p)), "sub": "apple_999"})
    refused(f"{h}.{other_payload}.{s}", code="signature")  # the payload changed under the signature
    refused(f"{h}.{p}.{s[:-2]}{'AA' if s[-2:] != 'AA' else 'BB'}", code="signature")
    refused(f"{h}.{p}.{s[:-1]}", code="signature")  # a signature of the wrong length
    refused(f"{h}.{p}.", code="signature")
    refused(f"{h}.{p}.###", code="signature")
    refused(f"{h}.{p}", code="format")
    refused("", code="format")
    refused("a.b.c.d", code="format")
    refused(f"not-base64url!.{p}.{s}", code="format")
    refused(f"{apple._b64url(b'[1]')}.{p}.{s}", code="format")
    refused(None, code="format")  # type: ignore[arg-type]
    # the same claims signed with another private exponent under Apple's kid: a foreign key never verifies
    foreign = apple._b64url(fake_sign(f"{h}.{p}".encode("ascii"), n=apple.FAKE_KEY_N, d=apple.FAKE_KEY_D + 2))
    refused(f"{h}.{p}.{foreign}", code="signature")
    refused(token(aud="other.app"), code="aud")
    refused(token(aud=None), code="aud")
    refused(token(aud=["x", "y"]), code="aud")
    refused(token(), code="aud", client_ids=("", ""))  # an instance without a client id accepts nothing
    refused(token(exp=int(NOW.timestamp())), code="exp")
    refused(token(exp=None), code="exp")
    refused(token(exp="soon"), code="exp")
    refused(token(exp=True), code="exp")
    refused(token(nonce="another-nonce"), code="nonce")
    refused(token(nonce=None), code="nonce")
    refused(token(iss="https://evil.example"), code="iss")
    refused(token(iss=None), code="iss")
    refused(token(sub=None), code="sub")
    refused(token(sub=""), code="sub")
    refused(token(sub=42), code="sub")


def test_alg_none_and_other_algorithms_are_refused_before_any_key_lookup():
    keys = Keys([fake_jwk()])
    for alg in ("none", "HS256", "RS512", "ES256", None, 1):
        h = apple._b64url_json({k: v for k, v in {"alg": alg, "kid": apple.FAKE_KEY_KID}.items() if v is not None})
        p = apple._b64url_json({"iss": apple.APPLE_ISSUER, "aud": AUD, "sub": "x", "nonce": NONCE, "exp": int(NOW.timestamp()) + 60})
        for sig in ("", apple._b64url(fake_sign(f"{h}.{p}".encode()))):
            refused(f"{h}.{p}.{sig}", code="alg", keys=keys)
    assert keys.fetches == 0
    refused(token(header={"kid": None}), code="kid", keys=keys)
    refused(token(header={"kid": 7}), code="kid", keys=keys)
    assert keys.fetches == 0


def test_an_unknown_kid_refetches_the_jwks_once():
    rotated = Keys([{"kty": "RSA", "kid": "old-key", "use": "sig", "alg": "RS256", "n": "AQAB", "e": "AQAB"}], [fake_jwk()])
    assert verify_id_token(token(), keys=rotated, client_ids=(AUD,), now=NOW, nonce=NONCE)["sub"] == "apple_000123"
    assert rotated.fetches == 2 and rotated.forced == [False, True]
    never = Keys([])
    refused(token(), code="kid", keys=never)
    assert never.fetches == 2 and never.forced == [False, True]  # once from the cache, once forced, then refused
    # a JWKS fetch failure surfaces as the provider's temporary error (502 provider_error in the router)
    down = Keys(AppleError("temporary", "JWKS fetch failed", code="jwks"))
    refused(token(), code="jwks", keys=down, kind="temporary")
    # a key set whose matching entry is unusable is a configuration problem, not a bad token
    short_n = apple._b64url_int(2**1023 + 1)
    weak = Keys([{"kty": "RSA", "kid": apple.FAKE_KEY_KID, "use": "sig", "alg": "RS256", "n": short_n, "e": "AQAB"}])
    refused(token(), code="key", keys=weak, kind="config")
    not_rsa = Keys([{"kty": "EC", "kid": apple.FAKE_KEY_KID, "crv": "P-256", "x": "a", "y": "b"}])
    refused(token(), code="key", keys=not_rsa, kind="config")
    garbage = Keys([{"kty": "RSA", "kid": apple.FAKE_KEY_KID, "n": "###", "e": "AQAB"}])
    refused(token(), code="key", keys=garbage, kind="config")


def test_fake_keys_serve_the_fixed_test_key():
    jwk = fake_jwk()
    assert set(jwk) == {"kty", "kid", "use", "alg", "n", "e"} and (jwk["kty"], jwk["kid"], jwk["use"], jwk["alg"], jwk["e"]) == ("RSA", "fake-apple-key-1", "sig", "RS256", "AQAB")
    assert rsa_verify.b64url_to_int(jwk["n"]) == apple.FAKE_KEY_N and apple.FAKE_KEY_N.bit_length() == 2048 and apple.FAKE_KEY_E == 65537
    assert apple.public_key_of(jwk) == (apple.FAKE_KEY_N, apple.FAKE_KEY_E)
    keys = FakeAppleKeys()
    assert keys.configured is True and keys.jwks() == [jwk] and keys.jwks(force=True) == [jwk] and keys.fetches == 2
    assert pow(pow(12345, apple.FAKE_KEY_D, apple.FAKE_KEY_N), apple.FAKE_KEY_E, apple.FAKE_KEY_N) == 12345
    assert apple.FAKE_SUB_PREFIX == "apple_" and apple.FAKE_AUDIENCE == "fake-apple" and apple.FAKE_CONSENT_PATH == "/api/auth/fake/apple"


def _mock_jwks_client(handler):
    transport = httpx.MockTransport(handler)

    def factory() -> httpx.Client:
        return httpx.Client(transport=transport)

    return factory


def test_jwks_client_caches_for_a_day_and_refetches_on_force(monkeypatch: pytest.MonkeyPatch):
    cfg = Settings.from_env({"WD_APPLE_CLIENT_ID": AUD, "WD_APPLE_CALLBACK_URL": "https://words.example.com/api/auth/apple/callback"})
    calls: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(request)
        return httpx.Response(200, json={"keys": [fake_jwk(), {"kty": "RSA", "kid": "other", "use": "sig", "alg": "RS256", "n": "AQAB", "e": "AQAB"}]})

    monkeypatch.setattr(apple, "CLIENT_FACTORY", _mock_jwks_client(handler))
    clock = {"now": 1000.0}
    monkeypatch.setattr(apple, "time", types.SimpleNamespace(monotonic=lambda: clock["now"]))
    client = AppleJwksClient.from_settings(cfg)
    assert client is not None and client.configured is True and AppleJwksClient.from_settings(Settings.from_env({})) is None
    keys = client.jwks()
    assert [k["kid"] for k in keys] == ["fake-apple-key-1", "other"] and len(calls) == 1
    assert str(calls[0].url) == "https://appleid.apple.com/auth/keys" and calls[0].method == "GET" and calls[0].headers["user-agent"].startswith("word-Dance/")
    clock["now"] += apple.JWKS_TTL_S - 1
    assert client.jwks() is keys and len(calls) == 1  # cached
    assert client.jwks(force=True) == keys and len(calls) == 2  # an unknown kid refetches through force
    clock["now"] += apple.JWKS_TTL_S  # the day passed
    assert client.jwks() == keys and len(calls) == 3
    # a verification through the real client: the token signed by the fake key verifies against the fetched set
    assert verify_id_token(token(), keys=client, client_ids=(cfg.apple_client_id, cfg.apple_app_id), now=NOW, nonce=NONCE)["sub"] == "apple_000123"
    assert len(calls) == 3
    assert apple.JWKS_TTL_S == 86400 and apple.TIMEOUT_S == 5.0


def test_forced_refetches_go_to_the_network_at_most_once_a_minute(monkeypatch: pytest.MonkeyPatch):
    """A forged id_token names any `kid` it likes; with a warm cache the real client answers a burst of them with ONE outbound JWKS fetch
    per JWKS_REFETCH_MIN_S (the reviewer's probe counted one fetch per forged POST), and the known kid never goes outbound at all."""
    cfg = Settings.from_env({"WD_APPLE_CLIENT_ID": AUD, "WD_APPLE_CALLBACK_URL": "https://words.example.com/api/auth/apple/callback"})
    calls: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(request)
        return httpx.Response(200, json={"keys": [fake_jwk()]})

    monkeypatch.setattr(apple, "CLIENT_FACTORY", _mock_jwks_client(handler))
    clock = {"now": 1000.0}
    monkeypatch.setattr(apple, "time", types.SimpleNamespace(monotonic=lambda: clock["now"]))
    client = AppleJwksClient(cfg)
    client.jwks()
    assert len(calls) == 1
    forged = token(header={"kid": "zzz"})
    refused(forged, code="kid", keys=client)  # inside the floor of the initial fetch: refused from the cache, no network
    assert len(calls) == 1
    clock["now"] += apple.JWKS_REFETCH_MIN_S
    refused(forged, code="kid", keys=client)  # the floor passed: one forced refetch (Apple may have rotated its keys)
    assert len(calls) == 2
    for i in range(25):
        refused(token(header={"kid": f"random-kid-{i}"}), code="kid", keys=client)  # the burst: refused from the cache
    assert len(calls) == 2
    assert verify_id_token(token(), keys=client, client_ids=(AUD,), now=NOW, nonce=NONCE)["sub"] == "apple_000123" and len(calls) == 2  # a genuine token never goes outbound
    clock["now"] += apple.JWKS_REFETCH_MIN_S
    refused(forged, code="kid", keys=client)
    assert len(calls) == 3  # one more per minute, never more
    assert client.jwks(force=True) == [fake_jwk()] and len(calls) == 3  # an explicit force inside the floor is the cached set too
    assert apple.JWKS_REFETCH_MIN_S == 60


def test_a_failed_refetch_after_the_ttl_serves_the_cached_keys(monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture):
    """Apple rotates keys rarely and is sometimes unreachable: a refetch that fails while a key set is cached logs a warning and keeps
    verifying genuine tokens with the cached keys; the retry waits for the floor; without any cache the failure still surfaces."""
    cfg = Settings.from_env({"WD_APPLE_CLIENT_ID": AUD, "WD_APPLE_CALLBACK_URL": "https://words.example.com/api/auth/apple/callback"})
    calls: list[httpx.Request] = []
    state = {"down": False}

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(request)
        if state["down"]:
            raise httpx.ConnectError("refused")
        return httpx.Response(200, json={"keys": [fake_jwk()]})

    monkeypatch.setattr(apple, "CLIENT_FACTORY", _mock_jwks_client(handler))
    clock = {"now": 1000.0}
    monkeypatch.setattr(apple, "time", types.SimpleNamespace(monotonic=lambda: clock["now"]))
    client = AppleJwksClient(cfg)
    keys = client.jwks()
    assert len(calls) == 1
    clock["now"] += apple.JWKS_TTL_S + 1
    state["down"] = True
    with caplog.at_level(logging.WARNING, logger="wd.delivery.apple"):
        assert client.jwks() == keys and len(calls) == 2  # the TTL refresh failed: the cached set is served
    stale = [r for r in caplog.records if getattr(r, "event", None) == "apple_jwks_stale"]
    assert len(stale) == 1 and stale[0].levelno == logging.WARNING and "jwks" in stale[0].getMessage()
    assert verify_id_token(token(), keys=client, client_ids=(AUD,), now=NOW, nonce=NONCE)["sub"] == "apple_000123" and len(calls) == 2  # inside the floor: no retry yet
    refused(token(header={"kid": "zzz"}), code="kid", keys=client)  # an unknown kid during the outage is refused, not a 502
    assert len(calls) == 2
    clock["now"] += apple.JWKS_REFETCH_MIN_S
    assert client.jwks() == keys and len(calls) == 3  # retried once the floor passed, still failing, still served
    state["down"] = False
    clock["now"] += apple.JWKS_REFETCH_MIN_S
    assert client.jwks() == keys and len(calls) == 4  # Apple is back: a fresh set
    clock["now"] += 10
    assert client.jwks() is not None and len(calls) == 4  # and cached again
    # without a cache there is nothing to serve: the failure is the provider's temporary error (the parametrized test below pins the shapes)
    state["down"] = True
    empty = AppleJwksClient(cfg)
    with pytest.raises(AppleError) as e:
        empty.jwks()
    assert e.value.kind == "temporary" and len(calls) == 5


@pytest.mark.parametrize(
    "handler",
    [
        lambda request: httpx.Response(500, text="boom"),
        lambda request: httpx.Response(200, text="<html>not json</html>"),
        lambda request: httpx.Response(200, json={"keys": "nope"}),
        lambda request: httpx.Response(200, json=["a"]),
        lambda request: (_ for _ in ()).throw(httpx.ConnectError("refused")),
    ],
)
def test_jwks_fetch_failures_are_temporary(monkeypatch: pytest.MonkeyPatch, handler):
    cfg = Settings.from_env({"WD_APPLE_CLIENT_ID": AUD, "WD_APPLE_CALLBACK_URL": "https://words.example.com/api/auth/apple/callback"})
    monkeypatch.setattr(apple, "CLIENT_FACTORY", _mock_jwks_client(handler))
    client = AppleJwksClient(cfg)
    with pytest.raises(AppleError) as e:
        client.jwks()
    assert e.value.kind == "temporary" and e.value.code == "jwks"
    with pytest.raises(AppleError) as e:
        verify_id_token(token(), keys=client, client_ids=(AUD,), now=NOW, nonce=NONCE)
    assert e.value.kind == "temporary"


def test_authorize_url_for_a_configured_instance_and_for_the_fake():
    cfg = Settings.from_env({"WD_APPLE_CLIENT_ID": AUD, "WD_APPLE_CALLBACK_URL": "https://words.example.com/api/auth/apple/callback"})
    url = apple.authorize_url(cfg, "12.abc.def", NONCE)
    parts = urlsplit(url)
    assert f"{parts.scheme}://{parts.netloc}{parts.path}" == "https://appleid.apple.com/auth/authorize"
    assert parts.query == (
        "response_type=code%20id_token&response_mode=form_post&client_id=com.worddance.web"
        "&redirect_uri=https%3A%2F%2Fwords.example.com%2Fapi%2Fauth%2Fapple%2Fcallback&state=12.abc.def"
        f"&nonce={NONCE}&scope=name%20email"
    )
    assert parse_qs(parts.query)["redirect_uri"] == ["https://words.example.com/api/auth/apple/callback"]
    # the fake consent page whenever Apple is not configured (the only way app.state.apple is non-None then is a FakeAppleKeys)
    plain = Settings.from_env({})
    assert apple.authorize_url(plain, "12.abc.def", NONCE) == f"/api/auth/fake/apple?state=12.abc.def&nonce={NONCE}"
    assert apple.authorize_url(replace(plain, dev=True, auth_fake_providers=True), "s", "n") == "/api/auth/fake/apple?state=s&nonce=n"


def test_factory_follows_the_settings():
    assert apple.apple_keys_from_settings(Settings.from_env({})) is None
    assert isinstance(apple.apple_keys_from_settings(Settings.from_env({"WD_DEV": "1", "WD_AUTH_FAKE_PROVIDERS": "1"})), FakeAppleKeys)
    real = apple.apple_keys_from_settings(Settings.from_env({"WD_APPLE_CLIENT_ID": AUD, "WD_APPLE_CALLBACK_URL": "https://words.example.com/api/auth/apple/callback", "WD_DEV": "1", "WD_AUTH_FAKE_PROVIDERS": "1"}))
    assert isinstance(real, AppleJwksClient)  # a configured provider beats the fakes
    with pytest.raises(ValueError):
        AppleError("bogus", "x")
    assert apple.KINDS == ("invalid_token", "config", "temporary")
