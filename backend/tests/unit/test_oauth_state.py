"""wd/oauth_state.py — the signed OAuth `state` of endpoints 118 / 120 (verified by 119 / 121), the `wd_oauth` browser secret that binds
a flow to the browser that started it, and the one-time cross-origin grant of 122 (API.md §3.3): the state format and TTL, every
tampering → 401 `invalid_identity_token` (never a ValueError / TypeError out of a crafted string — Unicode digits, non-ASCII hex,
oversized parts), `safe_next`, the browser-secret helpers and cookie constants, the grant's kv key shape and payload (provider, subject,
kind, uid, invite, next, bh, nonce), single use, the embedded expiry and the hourly GC."""

from __future__ import annotations

import hashlib
import json
import re
from datetime import datetime, timezone

import pytest

from wd import db, oauth_state
from wd.clock import to_iso
from wd.errors import ApiError

NOW = datetime(2026, 10, 14, 0, 0, 0, tzinfo=timezone.utc)
NOW_UNIX = int(NOW.timestamp())
BH = "b" * 64


def test_state_format_and_roundtrip(settings):
    payload = {"kind": "login", "next": "/bank", "invite": "ABCD-EFGH-JKLM-NPQR", "bh": BH}
    state = oauth_state.sign(settings, "qq", payload, NOW)
    exp, body, mac = state.split(".")
    assert int(exp) == NOW_UNIX + oauth_state.STATE_TTL_S == NOW_UNIX + 600
    assert json.loads(oauth_state.b64url_decode(body)) == payload and "=" not in body and re.fullmatch(r"[0-9a-f]{64}", mac)
    assert oauth_state.b64url_decode(body) == json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()  # compact, sorted keys
    assert state.isascii()  # by construction: digits, the base64url alphabet, hex — the ASCII guard of `verify` never refuses a genuine state
    assert oauth_state.verify(settings, "qq", state, NOW) == payload
    assert oauth_state.verify(settings, "qq", state, datetime.fromtimestamp(NOW_UNIX + 599, tz=timezone.utc)) == payload
    # the signature covers the provider and the expiry: the same payload signed for Apple is a different state
    assert oauth_state.sign(settings, "apple", payload, NOW) != state
    assert oauth_state.sign(settings, "qq", payload, NOW) == state  # deterministic for one instant


def _invalid(settings, provider: str, state, now=NOW) -> None:
    with pytest.raises(ApiError) as e:  # anything else (ValueError, TypeError) would be an HTTP 500 out of the public callbacks
        oauth_state.verify(settings, provider, state, now)
    assert e.value.code == "invalid_identity_token" and e.value.status == 401


def test_every_tampering_is_invalid_identity_token(settings):
    from dataclasses import replace

    payload = {"kind": "bind", "uid": 7, "next": "/settings", "nonce": "a" * 32, "bh": BH}
    state = oauth_state.sign(settings, "apple", payload, NOW)
    exp, body, mac = state.split(".")
    _invalid(settings, "qq", state)  # another provider
    _invalid(settings, "apple", state, datetime.fromtimestamp(NOW_UNIX + 600, tz=timezone.utc))  # exp <= now
    _invalid(settings, "apple", f"{int(exp) + 1}.{body}.{mac}")  # a longer life
    other_body = oauth_state.b64url_encode(json.dumps({**payload, "uid": 8}, sort_keys=True, separators=(",", ":")).encode())
    _invalid(settings, "apple", f"{exp}.{other_body}.{mac}")  # another user
    _invalid(settings, "apple", f"{exp}.{body}.{mac[:-1]}{'0' if mac[-1] != '0' else '1'}")  # a flipped signature char
    _invalid(settings, "apple", f"{exp}.{body}.{mac[:-1]}")
    _invalid(settings, "apple", state + ".x")
    _invalid(settings, "apple", f"abc.{body}.{mac}")  # a non-integer exp
    _invalid(settings, "apple", f"{exp}..{mac}")
    for junk in ("", "a", "a.b", "1.2.3", "x" * 5000, None, 42):
        _invalid(settings, "apple", junk)  # type: ignore[arg-type]
    # a correctly signed body that is not a JSON object is refused too
    for raw in (b"[1,2]", b"not json", b"\xff\xfe"):
        bad_body = oauth_state.b64url_encode(raw)
        bad_state = f"{exp}.{bad_body}.{oauth_state._state_mac(settings, 'apple', int(exp), bad_body)}"
        _invalid(settings, "apple", bad_state)
    # another secret key signs differently
    _invalid(replace(settings, secret_key="another-secret"), "apple", state)


def test_non_ascii_and_oversized_parts_are_refused_not_crashes(settings):
    """`str.isdigit()` admits '²' (which `int()` rejects) and '１２' / '١٢٣' (which `int()` reads as 12 / 123); `hmac.compare_digest` on str
    raises TypeError for non-ASCII — none of that may surface as a 500 from a crafted query string or form body."""
    payload = {"kind": "login", "next": "/", "bh": BH}
    state = oauth_state.sign(settings, "qq", payload, NOW)
    exp, body, mac = state.split(".")
    _invalid(settings, "qq", f"²².{body}.{mac}")  # a Unicode digit exp: isdigit() true, int() raises
    _invalid(settings, "qq", f"².eyJraW5kIjoibG9naW4ifQ.00")  # the reviewer's exact crafted state
    _invalid(settings, "qq", f"１２.{body}.{mac}")  # full-width digits (int() would accept them)
    _invalid(settings, "qq", f"١٢٣.{body}.{mac}")  # Arabic-Indic digits
    _invalid(settings, "qq", f"{exp}.{body}.{mac[:-1]}é")  # a non-ASCII hex char in the MAC
    _invalid(settings, "qq", f"{exp}.{body}é.{mac}")  # non-ASCII in the body
    _invalid(settings, "qq", f"1800000000.abc.dé")  # the reviewer's TypeError reproduction
    _invalid(settings, "qq", f"-{exp}.{body}.{mac}")  # a sign is not a digit
    _invalid(settings, "qq", f"+{exp}.{body}.{mac}")
    _invalid(settings, "qq", f" {exp}.{body}.{mac}")  # int() would strip the blank; the format does not
    _invalid(settings, "qq", f"{'9' * 13}.{body}.{mac}")  # an exp beyond 12 digits
    _invalid(settings, "qq", f"{exp}.{'A' * 4000}.{mac}")  # an oversized body inside STATE_MAX_LEN (wrong MAC)
    _invalid(settings, "qq", f"{exp}.{body}.{'f' * 5000}")  # beyond STATE_MAX_LEN
    _invalid(settings, "qq", f"{exp}.{body}.{mac}\n")  # trailing whitespace
    _invalid(settings, "qq", f"{exp}.{body}.{mac.upper()}")  # the hex is lower-case
    assert oauth_state.verify(settings, "qq", state, NOW) == payload  # the genuine one still passes
    assert oauth_state.STATE_MAX_LEN == 4096


def test_safe_next_keeps_same_origin_paths_only():
    assert oauth_state.safe_next("/bank") == "/bank" and oauth_state.safe_next("/settings?tab=login#x") == "/settings?tab=login#x" and oauth_state.safe_next("/") == "/"
    assert oauth_state.safe_next("/a?u=http://x") == "/a?u=http://x"  # a URL inside the query is fine
    for bad in (None, "", "bank", "//evil.example", "/\\evil.example", "https://evil.example/", "javascript:alert(1)", "/x:y", " /bank", "/bank\n", "/a\tb", "/" + "a" * 600, 5):
        assert oauth_state.safe_next(bad) == "/", bad  # type: ignore[arg-type]
    assert oauth_state.NEXT_MAX_LEN == 512


def test_new_nonce_and_b64url_helpers():
    nonce = oauth_state.new_nonce()
    assert re.fullmatch(r"[0-9a-f]{32}", nonce) and oauth_state.new_nonce() != nonce and oauth_state.NONCE_HEX_LEN == 32
    assert oauth_state.b64url_encode(b"\xfb\xff") == "-_8" and oauth_state.b64url_decode("-_8") == b"\xfb\xff" and oauth_state.b64url_decode("YQ==") == b"a"
    for bad in ("###", "é", " YQ", "a"):
        with pytest.raises(ValueError):
            oauth_state.b64url_decode(bad)


def test_browser_secret_and_the_oauth_cookie_constants():
    secret = oauth_state.new_browser_secret()
    assert re.fullmatch(r"[A-Za-z0-9_-]{43}", secret) and oauth_state.new_browser_secret() != secret  # 32 urlsafe random bytes, no padding
    assert oauth_state.browser_hash(secret) == hashlib.sha256(secret.encode()).hexdigest() and re.fullmatch(r"[0-9a-f]{64}", oauth_state.browser_hash(secret))
    assert oauth_state.browser_hash(secret) != oauth_state.browser_hash(secret + "x")
    assert (oauth_state.OAUTH_COOKIE, oauth_state.OAUTH_COOKIE_PATH, oauth_state.OAUTH_COOKIE_TTL_S, oauth_state.BROWSER_SECRET_BYTES) == ("wd_oauth", "/api/auth", 600, 32)
    assert oauth_state.OAUTH_COOKIE_TTL_S == oauth_state.STATE_TTL_S  # the cookie lives exactly as long as the state it is bound to
    assert oauth_state.OAUTH_COOKIE_PATH.startswith("/api/auth") and not oauth_state.OAUTH_COOKIE_PATH.endswith("/")  # covers /api/auth/{qq,apple}/start and /api/auth/oauth/finish
    assert oauth_state.GRANT_PROVIDERS == ("qq", "apple") and oauth_state.STATE_KINDS == ("login", "bind")


def test_grant_is_single_use_and_lives_sixty_seconds(settings, conn):
    with db.tx(conn):
        grant = oauth_state.issue_grant(conn, settings, provider="qq", subject="qq_abc", kind="login", uid=None, invite="ABCD-EFGH-JKLM-NPQR", next="/bank", bh=BH, now=NOW)
    assert len(grant) >= 43 and "=" not in grant  # 32 urlsafe random bytes
    rows = conn.execute("SELECT key, value, updated_at FROM kv WHERE key LIKE 'oauth_grant:%'").fetchall()
    assert len(rows) == 1
    key = str(rows[0]["key"])
    assert key == f"oauth_grant:2026-10-14T00:01:00Z:{oauth_state.grant_hash(grant)}" and grant not in key
    assert key[oauth_state.GRANT_KEY_EXPIRY_START - 1 : oauth_state.GRANT_KEY_EXPIRY_START - 1 + oauth_state.GRANT_KEY_EXPIRY_LEN] == "2026-10-14T00:01:00Z"
    assert conn.execute("SELECT substr(key, 13, 20) FROM kv WHERE key = ?", (key,)).fetchone()[0] == "2026-10-14T00:01:00Z"  # the SQL the GC uses
    expected = {"provider": "qq", "subject": "qq_abc", "kind": "login", "invite": "ABCD-EFGH-JKLM-NPQR", "next": "/bank", "bh": BH}
    assert json.loads(rows[0]["value"]) == expected and rows[0]["updated_at"] == to_iso(NOW)  # the VERIFIED subject, not an account: 122 resolves it
    # redeemed once, deleted in the same transaction; a second redeem is None
    assert oauth_state.redeem_grant(conn, grant, datetime.fromtimestamp(NOW_UNIX + 59, tz=timezone.utc)) == expected
    assert conn.execute("SELECT COUNT(*) FROM kv WHERE key LIKE 'oauth_grant:%'").fetchone()[0] == 0
    assert oauth_state.redeem_grant(conn, grant, NOW) is None
    for junk in ("", "x", None, "a" * 200):
        assert oauth_state.redeem_grant(conn, junk, NOW) is None  # type: ignore[arg-type]
    # an expired grant is None AND removed; a bind grant carries uid and the Apple nonce, never an invite; `next` is sanitised at issue time
    bind = oauth_state.issue_grant(conn, settings, provider="apple", subject="apple_1", kind="bind", uid=4, invite="ignored", next="//evil", bh=BH, now=NOW, nonce="a" * 32)
    assert json.loads(conn.execute("SELECT value FROM kv WHERE key LIKE 'oauth_grant:%'").fetchone()[0]) == {
        "provider": "apple",
        "subject": "apple_1",
        "kind": "bind",
        "uid": 4,
        "invite": None,
        "next": "/",
        "bh": BH,
        "nonce": "a" * 32,
    }
    assert oauth_state.redeem_grant(conn, bind, datetime.fromtimestamp(NOW_UNIX + 60, tz=timezone.utc)) is None  # exp <= now
    assert conn.execute("SELECT COUNT(*) FROM kv WHERE key LIKE 'oauth_grant:%'").fetchone()[0] == 0
    # a login grant without an invite spells it out as null (one shape for 122 to read)
    login = oauth_state.issue_grant(conn, settings, provider="apple", subject="apple_2", kind="login", uid=9, invite=None, next="/x", bh=BH, now=NOW)
    assert oauth_state.redeem_grant(conn, login, NOW) == {"provider": "apple", "subject": "apple_2", "kind": "login", "invite": None, "next": "/x", "bh": BH}  # uid is a bind field
    # programming errors, not request errors
    with pytest.raises(ValueError):
        oauth_state.issue_grant(conn, settings, provider="wechat_mini", subject="wx_1", kind="login", uid=None, invite=None, next="/", bh=BH, now=NOW)
    with pytest.raises(ValueError):
        oauth_state.issue_grant(conn, settings, provider="qq", subject="qq_1", kind="scan", uid=None, invite=None, next="/", bh=BH, now=NOW)
    with pytest.raises(ValueError):
        oauth_state.issue_grant(conn, settings, provider="qq", subject="qq_1", kind="bind", uid=None, invite=None, next="/", bh=BH, now=NOW)
    assert oauth_state.GRANT_TTL_S == 60 and oauth_state.GRANT_BYTES == 32 and oauth_state.GRANT_KEY_PREFIX == "oauth_grant:"


def test_gc_grants_deletes_only_the_expired_rows(settings, conn):
    old = oauth_state.issue_grant(conn, settings, provider="qq", subject="qq_1", kind="login", uid=None, invite=None, next="/", bh=BH, now=NOW)
    fresh = oauth_state.issue_grant(conn, settings, provider="apple", subject="apple_2", kind="login", uid=None, invite=None, next="/", bh=BH, now=datetime.fromtimestamp(NOW_UNIX + 30, tz=timezone.utc))
    db.kv_set(conn, "oauth_grant_unrelated", "x")  # a key that merely starts alike is left alone
    db.kv_set(conn, "seed_version", "y")
    assert oauth_state.gc_grants(conn, datetime.fromtimestamp(NOW_UNIX + 61, tz=timezone.utc)) == 1
    assert oauth_state.redeem_grant(conn, old, NOW) is None
    assert oauth_state.redeem_grant(conn, fresh, datetime.fromtimestamp(NOW_UNIX + 61, tz=timezone.utc)) == {"provider": "apple", "subject": "apple_2", "kind": "login", "invite": None, "next": "/", "bh": BH}
    assert conn.execute("SELECT COUNT(*) FROM kv WHERE key IN ('oauth_grant_unrelated', 'seed_version')").fetchone()[0] == 2
    assert oauth_state.gc_grants(conn, datetime.fromtimestamp(NOW_UNIX + 3600, tz=timezone.utc)) == 0
