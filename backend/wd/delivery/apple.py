"""Sign in with Apple — the web redirect flow's provider adapter (API.md §3.3 endpoints 120 / 121; docs/AUTH_SIGNUP_DESIGN.md §5.3, owner
decision D6: web + iOS, the iOS Capacitor plugin deferred).

Slice 2-A: the names, signatures and docstrings here are what ``routers/auth_oauth.py``, ``routers/auth_fake.py`` and the tests build
against.

* :class:`AppleKeys` is the Protocol the router reaches through ``app.state.apple`` (built by :func:`apple_keys_from_settings`, None while
  Apple login is off → 409 ``provider_unconfigured``): ``jwks(force=False) -> list[dict]`` — the JSON Web Key Set Apple's id_tokens are
  signed with. :class:`AppleJwksClient` fetches ``GET https://appleid.apple.com/auth/keys`` over ``httpx`` (5 s, ``trust_env=False``) and
  caches it for :data:`JWKS_TTL_S` (24 h) in the process; ``force`` refetches — but the client goes to the network at most once per
  :data:`JWKS_REFETCH_MIN_S` (60 s) while it holds a key set, so a flood of forged tokens with unknown ``kid`` values costs one outbound
  request a minute, not one per request (an unknown ``kid`` inside the window is simply refused); and when a refetch after the TTL
  fails, the cached keys keep serving (a warning, ``apple_jwks_stale``) instead of every Apple login failing for the outage.
* :func:`verify_id_token` checks the id_token Apple posts to 121 without any third-party library (the CSP forbids one and the box
  keeps its dependency list short): header ``alg == RS256`` and a ``kid`` present in the JWKS, ``iss == https://appleid.apple.com``,
  ``aud ∈ client_ids`` (the Services ID; the iOS bundle id once the plugin exists), ``exp > now``, ``nonce`` equal to the state's nonce
  or to its sha256 hex (Apple hashes it for native flows), and the signature as PKCS#1 v1.5 SHA-256 verified by
  ``wd.rsa_verify.verify_pkcs1_v15_sha256`` (pure Python ``pow``). Any failure → :class:`AppleError` ``kind='invalid_token'`` → 401
  ``invalid_identity_token``; a JWKS fetch failure → ``kind='temporary'`` → 502 ``provider_error``.
* :func:`authorize_url` builds the 302 target of 120 (``response_type=code id_token``, ``response_mode=form_post``, ``scope=name email``,
  the signed ``state`` and the ``nonce``). The ``user`` form field Apple sends on the first authorisation (name / e-mail) is ignored by
  the callback — nothing of it is stored.
* :class:`FakeAppleKeys` (``WD_AUTH_FAKE_PROVIDERS=1``, dev only) serves the JWKS of a fixed 2048-bit RSA test key whose constants
  (:data:`FAKE_KEY_N`, :data:`FAKE_KEY_E`, :data:`FAKE_KEY_D`, generated once by the implementer with a throwaway script; the private
  exponent lives only here and in the test module) also sign the id_tokens the fake consent page mints with :func:`fake_id_token`.

Nothing but ids ever reaches a log line: no ``sub``, no token, no e-mail.
"""

from __future__ import annotations

import base64
import hashlib
import json
import logging
import time
from datetime import datetime
from typing import Any, Callable, Protocol, Sequence, runtime_checkable
from urllib.parse import quote, urlencode

import httpx

from .. import __version__, rsa_verify
from ..config import Settings

log = logging.getLogger("wd.delivery.apple")

APPLE_ISSUER = "https://appleid.apple.com"
APPLE_AUTHORIZE_URL = APPLE_ISSUER + "/auth/authorize"
APPLE_JWKS_URL = APPLE_ISSUER + "/auth/keys"
APPLE_SCOPE = "name email"
APPLE_RESPONSE_TYPE = "code id_token"
APPLE_RESPONSE_MODE = "form_post"
TIMEOUT_S = 5.0
CONNECT_TIMEOUT_S = 5.0
JWKS_TTL_S = 86400  # the fetched key set is reused for a day; an unknown kid refetches once before failing
JWKS_REFETCH_MIN_S = 60  # while a key set is cached, at most one network fetch per minute — forced (unknown kid) or a TTL refresh retry alike
KINDS: tuple[str, ...] = ("invalid_token", "config", "temporary")  # AppleError.kind
FAKE_CONSENT_PATH = "/api/auth/fake/apple"  # routers/auth_fake.py (dev only)
FAKE_AUDIENCE = "fake-apple"  # the fake consent page's `aud` when WD_APPLE_CLIENT_ID is empty
FAKE_SUB_PREFIX = "apple_"  # the fake consent page mints `sub = "apple_" + random`
FAKE_KEY_KID = "fake-apple-key-1"
#: the fixed 2048-bit RSA test key of the fake provider, generated ONCE with a throwaway pure-Python Miller-Rabin script (slice 2-A B2) and
#: hard-coded: the modulus and public exponent appear in the JWKS the fake serves, the private exponent only signs the fake consent page's
#: id_tokens (and the tests' tokens). Never a key of any real Apple account; worthless outside a dev box, where it signs nothing but fake logins.
FAKE_KEY_N: int = 22878524525649028894669926281137261933754802073246780711405780699700137014824239099363030796718214684985159264906354196779941354902245003188017200164713496122850548626335919963448702404529204709245986900796039615929523039158285005469054204017633248675000916799685051548765805287931579819334564415607144200339638752246124396446673301383504049341032490423467669889786210438011753655500732300770150446946048352451742152908384986116546873551263503904826130265096379848761908818389878887119473942522537540817592425153058406473535319578667978681343944363165432669219098305218672414566034525368989058629846232028618726746581
FAKE_KEY_E: int = 65537
FAKE_KEY_D: int = 1700345962331278628693921653933645399756415493511554650809156756382874442909427691124440884586039095120183476349888226558522656734212885076796844190339476345276321920773390331598452282479524907114452762516628926549715799364942195864754196319924426598467441529244029553247036728965206561255837612757961115305900743298108604208791470666930957645312029002235597541666891464895637761060964581601370974901502761700475167945353039263208284846517154801551853820032807063867840927119044567350015563297627676286854163782415113114253141982197289283615106925464465151768457910343727937155896672914732437137519692552447479639105
MESSAGE_MAX = 200

#: test hook: a factory returning the ``httpx.Client`` the JWKS fetch uses (None = a real client, ``trust_env=False``)
CLIENT_FACTORY: Callable[[], httpx.Client] | None = None


class AppleError(Exception):
    """A failed Apple step: ``kind`` ∈ :data:`KINDS` — ``invalid_token`` (the id_token fails :func:`verify_id_token`; the router answers
    401 ``invalid_identity_token``), ``config`` (an unusable key set / client id), ``temporary`` (the JWKS could not be fetched; 502
    ``provider_error``). ``code`` = a short machine reason for the log (``alg``, ``kid``, ``iss``, ``aud``, ``exp``, ``nonce``, ``signature``,
    ``jwks``), never a token fragment."""

    def __init__(self, kind: str, message: str, *, code: str | None = None):
        if kind not in KINDS:
            raise ValueError(f"unknown AppleError kind {kind!r}")
        super().__init__(message)
        self.kind = kind
        self.code = code


@runtime_checkable
class AppleKeys(Protocol):
    """The JWKS source endpoint 121 verifies against (``app.state.apple``)."""

    def jwks(self, force: bool = False) -> list[dict[str, Any]]:
        """The ``keys`` list of Apple's JWKS (``{kty, kid, use, alg, n, e}`` dicts); ``force`` bypasses the cache. Raises :class:`AppleError`."""
        ...


def _client(timeout_s: float = TIMEOUT_S) -> httpx.Client:
    if CLIENT_FACTORY is not None:
        return CLIENT_FACTORY()
    return httpx.Client(trust_env=False, timeout=httpx.Timeout(float(timeout_s), connect=min(CONNECT_TIMEOUT_S, float(timeout_s))))


class AppleJwksClient:
    """``GET https://appleid.apple.com/auth/keys`` with a :data:`JWKS_TTL_S` process-local cache, a :data:`JWKS_REFETCH_MIN_S` floor between
    network fetches once a key set is held (a ``force`` inside the floor returns the cached set — an unknown ``kid`` is then just an
    unknown ``kid``), and stale serving: a refetch that fails while keys are cached logs a warning and returns the cached keys."""

    def __init__(self, cfg: Settings):
        self.cfg = cfg
        self._keys: list[dict[str, Any]] | None = None
        self._fetched_at: float = 0.0  # monotonic instant of the cached (successful) fetch
        self._attempted_at: float = 0.0  # monotonic instant of the last network attempt, successful or not (the refetch floor)

    @classmethod
    def from_settings(cls, cfg: Settings) -> "AppleJwksClient | None":
        """The client when ``cfg.apple_configured``, else None (a hand-built Settings without the pair gets None like the mailer)."""
        if not cfg.apple_configured:
            return None
        return cls(cfg)

    @property
    def configured(self) -> bool:
        return True

    def jwks(self, force: bool = False) -> list[dict[str, Any]]:
        now = time.monotonic()
        if self._keys is not None:
            if now - self._attempted_at < JWKS_REFETCH_MIN_S:
                return self._keys  # one network attempt per minute at most: a forced refetch or a failed TTL refresh is not retried sooner
            if not force and now - self._fetched_at < JWKS_TTL_S:
                return self._keys
        self._attempted_at = now
        try:
            keys = self._fetch()
        except AppleError as e:
            if self._keys is not None:  # the TTL passed (or a kid was unknown) and Apple is unreachable: the known keys still verify genuine tokens
                log.warning("apple JWKS refetch failed (%s); serving the cached key set", e.code or "-", extra={"event": "apple_jwks_stale"})
                return self._keys
            raise
        self._keys = keys
        self._fetched_at = now
        log.info("apple JWKS fetched (%d keys)", len(keys), extra={"event": "apple_jwks_fetched"})
        return keys

    def _fetch(self) -> list[dict[str, Any]]:
        """One ``GET`` of the JWKS; :class:`AppleError` ``temporary`` on any network / HTTP / shape failure."""
        client = _client()
        try:
            response = client.get(APPLE_JWKS_URL, headers={"User-Agent": f"word-Dance/{__version__}", "Accept": "application/json"})
        except (httpx.HTTPError, httpx.InvalidURL, OSError) as e:
            name = e.__class__.__name__
            raise AppleError("temporary", f"JWKS fetch failed: Network.{name}: {str(e)[:MESSAGE_MAX]}", code="jwks") from e
        finally:
            client.close()
        if response.status_code != 200:
            raise AppleError("temporary", f"JWKS fetch answered HTTP {response.status_code}", code="jwks")
        try:
            data = response.json()
        except ValueError as e:
            raise AppleError("temporary", "JWKS fetch answered no JSON", code="jwks") from e
        keys = data.get("keys") if isinstance(data, dict) else None
        if not isinstance(keys, list) or not all(isinstance(k, dict) for k in keys):
            raise AppleError("temporary", "JWKS answer without a keys list", code="jwks")
        return keys


class FakeAppleKeys:
    """The dev / test double (``WD_AUTH_FAKE_PROVIDERS=1``; the integration tests install it as ``app.state.apple``): serves the JWKS of the
    fixed test key (:data:`FAKE_KEY_N` / :data:`FAKE_KEY_E` under :data:`FAKE_KEY_KID`). ``fetches`` counts the ``jwks`` calls (the
    unknown-kid refetch rule is asserted through it)."""

    def __init__(self) -> None:
        self.fetches = 0

    @property
    def configured(self) -> bool:
        return True

    def jwks(self, force: bool = False) -> list[dict[str, Any]]:
        self.fetches += 1
        return [fake_jwk()]


def authorize_url(cfg: Settings, state: str, nonce: str) -> str:
    """The 302 target of endpoint 120: ``APPLE_AUTHORIZE_URL?response_type=code%20id_token&response_mode=form_post&client_id=<WD_APPLE_CLIENT_ID>
    &redirect_uri=<WD_APPLE_CALLBACK_URL>&state=…&nonce=…&scope=name%20email`` — or, under ``cfg.auth_fake_providers`` without a real
    client id, the fake consent page :data:`FAKE_CONSENT_PATH` with ``state`` and ``nonce`` as query parameters. The fake page is also what
    an unconfigured instance gets: ``app.state.apple`` is non-None there only for a :class:`FakeAppleKeys` (the flag, or a test)."""
    if cfg.apple_configured:
        query = urlencode(
            {
                "response_type": APPLE_RESPONSE_TYPE,
                "response_mode": APPLE_RESPONSE_MODE,
                "client_id": cfg.apple_client_id,
                "redirect_uri": cfg.apple_callback_url,
                "state": state,
                "nonce": nonce,
                "scope": APPLE_SCOPE,
            },
            quote_via=quote,
        )
        return f"{APPLE_AUTHORIZE_URL}?{query}"
    return f"{FAKE_CONSENT_PATH}?{urlencode({'state': state, 'nonce': nonce})}"


def verify_id_token(token: str, *, keys: AppleKeys, client_ids: Sequence[str], now: datetime, nonce: str | None) -> dict[str, Any]:
    """The verified claims of an Apple id_token (a compact JWS ``header.payload.signature``), or :class:`AppleError`.

    Checks, in order: three base64url parts; header ``alg == "RS256"`` (``none`` and every other alg refused) and a ``kid`` found in
    ``keys.jwks()`` (an unknown kid → ``keys.jwks(force=True)`` once, then ``invalid_token``; the real client fetches at most once per
    :data:`JWKS_REFETCH_MIN_S`, so a forged kid cannot drive outbound traffic); the RSA public key of that JWK with a
    modulus of at least 2048 bits; the PKCS#1 v1.5 SHA-256 signature over ``header.payload`` (``wd.rsa_verify``); ``iss`` ==
    :data:`APPLE_ISSUER`; ``aud`` ∈ ``client_ids`` (empty strings ignored); ``exp`` > ``now``; when ``nonce`` is given, the claim equals it
    or its sha256 hex. Returns the payload dict (``sub`` is what the caller keeps; ``email`` is never stored).
    """
    if not isinstance(token, str) or token.count(".") != 2:
        raise AppleError("invalid_token", "id_token is not a compact JWS", code="format")
    header_b64, payload_b64, signature_b64 = token.split(".")
    header = _json_part(header_b64, "header")
    if header.get("alg") != "RS256":
        raise AppleError("invalid_token", "id_token alg is not RS256", code="alg")
    kid = header.get("kid")
    if not isinstance(kid, str) or not kid:
        raise AppleError("invalid_token", "id_token header without kid", code="kid")
    jwk = _find_key(keys.jwks(), kid)
    if jwk is None:
        jwk = _find_key(keys.jwks(force=True), kid)  # Apple rotated its keys: refetch once
    if jwk is None:
        raise AppleError("invalid_token", "id_token kid is not in Apple's JWKS", code="kid")
    n, e = public_key_of(jwk)
    try:
        signature = rsa_verify.b64url_decode(signature_b64)
    except ValueError as exc:
        raise AppleError("invalid_token", "id_token signature is not base64url", code="signature") from exc
    try:
        valid = rsa_verify.verify_pkcs1_v15_sha256(f"{header_b64}.{payload_b64}".encode("ascii"), signature, n=n, e=e)
    except ValueError as exc:  # a modulus shorter than 2048 bits or a bad exponent: the key set is unusable, not the token
        raise AppleError("config", f"Apple JWK {kid!r} is unusable: {exc}", code="key") from exc
    if not valid:
        raise AppleError("invalid_token", "id_token signature does not verify", code="signature")
    payload = _json_part(payload_b64, "payload")
    if payload.get("iss") != APPLE_ISSUER:
        raise AppleError("invalid_token", "id_token iss is not Apple", code="iss")
    accepted = {c for c in client_ids if isinstance(c, str) and c}
    aud = payload.get("aud")
    audiences = {aud} if isinstance(aud, str) else ({a for a in aud if isinstance(a, str)} if isinstance(aud, list) else set())
    if not accepted or not (audiences & accepted):
        raise AppleError("invalid_token", "id_token aud is not this application", code="aud")
    exp = payload.get("exp")
    if not isinstance(exp, (int, float)) or isinstance(exp, bool) or float(exp) <= now.timestamp():
        raise AppleError("invalid_token", "id_token has expired", code="exp")
    if nonce is not None:
        claim = payload.get("nonce")
        if not isinstance(claim, str) or claim not in (nonce, hashlib.sha256(nonce.encode("utf-8")).hexdigest()):
            raise AppleError("invalid_token", "id_token nonce does not match the state", code="nonce")
    sub = payload.get("sub")
    if not isinstance(sub, str) or not sub:
        raise AppleError("invalid_token", "id_token without sub", code="sub")
    return payload


def fake_id_token(sub: str, *, aud: str, nonce: str, now: datetime, exp_s: int = 600) -> str:
    """An id_token signed with the fake test key (:data:`FAKE_KEY_D`, ``kid`` :data:`FAKE_KEY_KID`) for the fake consent page and the
    tests: ``{iss: APPLE_ISSUER, aud, sub, nonce, iat: now, exp: now + exp_s}``. Dev / test only."""
    iat = int(now.timestamp())
    header = _b64url_json({"alg": "RS256", "kid": FAKE_KEY_KID, "typ": "JWT"})
    payload = _b64url_json({"iss": APPLE_ISSUER, "aud": aud, "sub": sub, "nonce": nonce, "iat": iat, "exp": iat + int(exp_s)})
    signing_input = f"{header}.{payload}"
    return f"{signing_input}.{_b64url(fake_sign(signing_input.encode('ascii')))}"


def fake_sign(message: bytes, *, n: int = FAKE_KEY_N, d: int = FAKE_KEY_D) -> bytes:
    """RSASSA-PKCS1-v1_5 SHA-256 signing with a private exponent — the fake provider's and the tests' signer (``pow`` with ``d``; never
    used for anything real)."""
    k = rsa_verify.modulus_bytes(n)
    t = rsa_verify.SHA256_DIGEST_INFO + hashlib.sha256(message).digest()
    em = b"\x00\x01" + b"\xff" * (k - 3 - len(t)) + b"\x00" + t
    return pow(int.from_bytes(em, "big"), d, n).to_bytes(k, "big")


def fake_jwk() -> dict[str, Any]:
    """The JWK of the fake test key as Apple would publish it (``{kty, kid, use, alg, n, e}``)."""
    return {"kty": "RSA", "kid": FAKE_KEY_KID, "use": "sig", "alg": "RS256", "n": _b64url_int(FAKE_KEY_N), "e": _b64url_int(FAKE_KEY_E)}


def public_key_of(jwk: dict[str, Any]) -> tuple[int, int]:
    """``(n, e)`` of an RSA JWK; :class:`AppleError` ``config`` when the entry is not a usable RSA key."""
    if jwk.get("kty") != "RSA" or not isinstance(jwk.get("n"), str) or not isinstance(jwk.get("e"), str):
        raise AppleError("config", "Apple JWK is not an RSA key", code="key")
    try:
        return rsa_verify.b64url_to_int(jwk["n"]), rsa_verify.b64url_to_int(jwk["e"])
    except ValueError as e:
        raise AppleError("config", "Apple JWK n / e are not base64url integers", code="key") from e


def _find_key(keys: list[dict[str, Any]], kid: str) -> dict[str, Any] | None:
    return next((k for k in keys if isinstance(k, dict) and k.get("kid") == kid), None)


def _json_part(text: str, what: str) -> dict[str, Any]:
    try:
        data = json.loads(rsa_verify.b64url_decode(text).decode("utf-8"))
    except (ValueError, UnicodeDecodeError) as e:
        raise AppleError("invalid_token", f"id_token {what} is not base64url JSON", code="format") from e
    if not isinstance(data, dict):
        raise AppleError("invalid_token", f"id_token {what} is not an object", code="format")
    return data


def _b64url(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode("ascii")


def _b64url_json(obj: dict[str, Any]) -> str:
    return _b64url(json.dumps(obj, sort_keys=True, separators=(",", ":")).encode("utf-8"))


def _b64url_int(value: int) -> str:
    return _b64url(value.to_bytes((value.bit_length() + 7) // 8, "big"))


def apple_keys_from_settings(cfg: Settings) -> AppleKeys | None:
    """``app.state.apple``: the :class:`AppleJwksClient` when ``cfg.apple_configured``, :class:`FakeAppleKeys` when ``cfg.auth_fake_providers``
    (dev only), else None (``ServerFlags.apple_enabled`` false, endpoints 120 / 121 answer 409 ``provider_unconfigured``)."""
    if cfg.apple_configured:
        return AppleJwksClient.from_settings(cfg)
    if cfg.auth_fake_providers:
        return FakeAppleKeys()
    return None


__all__ = [
    "APPLE_AUTHORIZE_URL",
    "APPLE_ISSUER",
    "APPLE_JWKS_URL",
    "APPLE_RESPONSE_MODE",
    "APPLE_RESPONSE_TYPE",
    "APPLE_SCOPE",
    "CLIENT_FACTORY",
    "FAKE_AUDIENCE",
    "FAKE_CONSENT_PATH",
    "FAKE_KEY_D",
    "FAKE_KEY_E",
    "FAKE_KEY_KID",
    "FAKE_KEY_N",
    "FAKE_SUB_PREFIX",
    "AppleError",
    "AppleJwksClient",
    "AppleKeys",
    "FakeAppleKeys",
    "JWKS_REFETCH_MIN_S",
    "JWKS_TTL_S",
    "KINDS",
    "MESSAGE_MAX",
    "TIMEOUT_S",
    "apple_keys_from_settings",
    "authorize_url",
    "fake_id_token",
    "fake_jwk",
    "fake_sign",
    "public_key_of",
    "verify_id_token",
]
