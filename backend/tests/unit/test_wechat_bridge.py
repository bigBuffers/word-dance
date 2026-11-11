"""wd/wechat_bridge.py (slice 2-A, API.md §3.3 endpoints 112–116): the ticket / poll-secret / pairing-code hashes, pairing-code regeneration
on a live collision (finished rows keep their hash and are free), the throttle windows and the per-openid keys of 115 / 116, mp_token sign /
verify / expiry / malformed input (full-width digits, a non-ASCII signature — False, never an exception), the masked ip and the UA summary of
the confirmation page, the QR cache eviction and gc_tickets (the login_codes rule); plus wd/delivery/wechat.py — classify / read_secret (the
loose-mode warning once per process), the real client over an httpx mock transport (code2session answers, the stable token cache and its one
40001 / 42001 retry, the JPEG → PNG re-encoding, the secret scrubbed from every message) and the dev fake."""

from __future__ import annotations

import hashlib
import hmac
import io
import json
import logging
import re
from dataclasses import replace
from datetime import datetime, timedelta, timezone

import pytest

from wd import wechat_bridge as bridge
from wd.clock import to_iso

UTC = timezone.utc
NOW = datetime(2026, 10, 14, 0, 0, 0, tzinfo=UTC)


def _ticket_row(conn, ticket_hash: str, pair_hash: str | None, status: str, expires_at: str, consumed_at: str | None = None) -> None:
    conn.execute(
        "INSERT INTO wechat_tickets(ticket_hash, pair_hash, poll_hash, kind, status, created_at, expires_at, consumed_at) VALUES (?, ?, 'po', 'login', ?, ?, ?, ?)",
        (ticket_hash, pair_hash, status, to_iso(NOW - timedelta(minutes=1)), expires_at, consumed_at),
    )


# ------------------------------------------------------------------------------------ hashes
def test_ticket_poll_secret_and_pairing_code_shapes_and_hashes(settings):
    ticket = bridge.new_ticket()
    assert bridge.TICKET_RE.match(ticket) and len(ticket) == 26 and "=" not in ticket
    assert bridge.new_ticket() != ticket
    assert bridge.ticket_hash(ticket) == hashlib.sha256(ticket.encode("utf-8")).hexdigest()
    secret = bridge.new_poll_secret()
    assert len(secret) >= 43 and bridge.new_poll_secret() != secret  # token_urlsafe(32)
    assert bridge.poll_hash(secret) == hashlib.sha256(secret.encode("utf-8")).hexdigest()
    code = bridge.new_pairing_code()
    assert re.fullmatch(r"\d{6}", code)
    assert bridge.pair_hash(settings, "123456") == hmac.new(settings.secret_key.encode("utf-8"), b"pair:123456", hashlib.sha256).hexdigest()
    assert bridge.pair_hash(settings, "123456") != bridge.pair_hash(settings, "123457")
    assert bridge.pair_hash(replace(settings, secret_key="other-key"), "123456") != bridge.pair_hash(settings, "123456")
    assert bridge.openid_key("wx_abc") == "wx_scan:openid:" + hashlib.sha256(b"wx_abc").hexdigest()[:32]
    assert bridge.openid_key("wx_abc", scope="confirm") == "wx_confirm:openid:" + hashlib.sha256(b"wx_abc").hexdigest()[:32]
    assert "wx_abc" not in bridge.openid_key("wx_abc") and "wx_abc" not in bridge.openid_key("wx_abc", scope="confirm")  # the openid itself never lands in auth_throttle
    with pytest.raises(ValueError):
        bridge.openid_key("wx_abc", scope="poll")


def test_windows_are_sized_for_the_relay_and_a_classroom():
    """Behind the mainland relay every mini-program request shares ONE client IP, so the per-IP windows of 115 / 116 are site-wide caps and
    must stay wide (flood brakes); the brute-force brakes are per openid. The web windows fit thirty sheets behind one NAT polling every 2 s.
    114 has no window of its own (routers/auth_wechat.ticket_qr), and a confirmed / cancelled result is delivered for 60 s past expiry."""
    assert (bridge.TICKET_IP_MINUTE, bridge.TICKET_IP_HOUR) == (30, 300)
    assert bridge.POLL_IP_MINUTE == 1200 and bridge.POLL_IP_MINUTE >= 30 * 30  # 30 sheets × 30 polls a minute
    assert (bridge.SCAN_IP_MINUTE, bridge.CONFIRM_IP_MINUTE) == (600, 600)
    assert (bridge.SCAN_OPENID_MINUTE, bridge.CONFIRM_OPENID_MINUTE) == (10, 20)
    assert bridge.CONFIRM_OPENID_MINUTE >= 2 * bridge.SCAN_OPENID_MINUTE  # a scanner may confirm (or cancel) twice per scan it is allowed
    assert bridge.CONFIRM_GRACE_S == 60 and bridge.CONFIRM_GRACE_S < bridge.MP_TOKEN_TTL_S
    assert bridge.OPENID_KEY_SCOPES == ("scan", "confirm")


def test_unique_pairing_code_regenerates_while_a_live_ticket_holds_the_code(conn, settings, monkeypatch: pytest.MonkeyPatch):
    draws = iter(["111111", "111111", "222222", "333333", "444444"])
    monkeypatch.setattr(bridge, "new_pairing_code", lambda: next(draws))
    _ticket_row(conn, "th-live", bridge.pair_hash(settings, "111111"), "pending", to_iso(NOW + timedelta(minutes=2)))  # live: taken
    _ticket_row(conn, "th-scanned", bridge.pair_hash(settings, "333333"), "scanned", to_iso(NOW + timedelta(minutes=2)))  # live too
    _ticket_row(conn, "th-expired", bridge.pair_hash(settings, "222222"), "pending", to_iso(NOW - timedelta(seconds=1)))  # expired: free again
    code, h = bridge.unique_pairing_code(conn, settings, NOW)
    assert (code, h) == ("222222", bridge.pair_hash(settings, "222222"))  # two collisions with the live ticket, then the expired holder's code is free
    _ticket_row(conn, "th-done", bridge.pair_hash(settings, "444444"), "confirmed", to_iso(NOW + timedelta(minutes=2)))  # not live: free
    draws2 = iter(["333333", "444444"])
    monkeypatch.setattr(bridge, "new_pairing_code", lambda: next(draws2))
    assert bridge.unique_pairing_code(conn, settings, NOW)[0] == "444444"
    # finished rows keep their hash (116 must still find them by code) — consumed and cancelled holders free the code too
    _ticket_row(conn, "th-consumed", bridge.pair_hash(settings, "555555"), "consumed", to_iso(NOW + timedelta(minutes=2)), consumed_at=to_iso(NOW))
    _ticket_row(conn, "th-cancelled", bridge.pair_hash(settings, "666666"), "cancelled", to_iso(NOW + timedelta(minutes=2)))
    draws3 = iter(["555555"])
    monkeypatch.setattr(bridge, "new_pairing_code", lambda: next(draws3))
    assert bridge.unique_pairing_code(conn, settings, NOW)[0] == "555555"
    draws4 = iter(["666666"])
    monkeypatch.setattr(bridge, "new_pairing_code", lambda: next(draws4))
    assert bridge.unique_pairing_code(conn, settings, NOW)[0] == "666666"


# ----------------------------------------------------------------------------------- mp_token
def test_mp_token_sign_and_verify(settings):
    exp = int(NOW.timestamp()) + bridge.MP_TOKEN_TTL_S
    token = bridge.mp_token_sign(settings, ticket_id=7, openid="wx_abc", exp_unix=exp)
    head, sig = token.split(".")
    assert head == str(exp) and re.fullmatch(r"[0-9a-f]{64}", sig)
    assert sig == hmac.new(settings.secret_key.encode("utf-8"), f"mp:7:wx_abc:{exp}".encode("utf-8"), hashlib.sha256).hexdigest()
    ok = lambda **kw: bridge.mp_token_verify(settings, kw.pop("token", token), ticket_id=kw.pop("ticket_id", 7), openid=kw.pop("openid", "wx_abc"), now=kw.pop("now", NOW))  # noqa: E731
    assert ok() and ok(now=NOW + timedelta(seconds=299))
    assert not ok(now=NOW + timedelta(seconds=300))  # exp <= now: expired
    assert not ok(ticket_id=8) and not ok(openid="wx_abd")  # another ticket / another scanner
    assert not ok(token=head + "." + ("0" if sig[0] != "0" else "1") + sig[1:])  # a flipped bit
    assert not ok(token=str(exp + 60) + "." + sig)  # a later expiry with the old signature
    assert not bridge.mp_token_verify(replace(settings, secret_key="other-key"), token, ticket_id=7, openid="wx_abc", now=NOW)
    fullwidth_exp = str(exp).translate(str.maketrans("0123456789", "０１２３４５６７８９"))  # str.isdigit() / int() accept these
    malformed = (
        "", ".", "abc", "abc.def", f"{exp}", f"{exp}.", f".{sig}", "１２３.abc", "-5.abc", f"{exp}.{sig}.extra",
        f"{exp}{sig}",  # the dot missing
        f"{fullwidth_exp}.{sig}",  # full-width digits in the head: not ASCII → refused before int()
        f"{exp}.{'ｆ' * 64}",  # a non-ASCII signature segment: compare_digest on str would raise TypeError (a 500 on 116)
        f"{exp}.{sig[:-1]}é", f"{exp}.{sig}\u0000", f"{exp}.{'0' * 64}",
        f"{'9' * 13}.{sig}",  # more than 12 digits of exp
        f"{exp}\n.{sig}", f" {exp} . {sig}",
    )
    for bad in malformed:
        assert bridge.mp_token_verify(settings, bad, ticket_id=7, openid="wx_abc", now=NOW) is False, bad
    assert bridge.mp_token_verify(settings, None, ticket_id=7, openid="wx_abc", now=NOW) is False  # type: ignore[arg-type]
    assert bridge.MP_EXP_RE.match("1") and bridge.MP_EXP_RE.match("9" * 12) and not bridge.MP_EXP_RE.match("9" * 13) and not bridge.MP_EXP_RE.match("１")


# ------------------------------------------------------------------------- the confirmation page
@pytest.mark.parametrize(
    "ip, masked",
    [
        ("203.0.113.7", "203.0.113.*"),
        ("10.0.0.1", "10.0.0.*"),
        ("2001:db8:85a3::8a2e:370:7334", "2001:db8:85a3:0::*"),
        ("fe80::1", "fe80:0:0:0::*"),
        ("::ffff:192.0.2.9", "192.0.2.*"),  # an IPv4-mapped address is the IPv4 it carries
        ("testclient", "*"),
        ("", "*"),
        ("not an ip", "*"),
    ],
)
def test_web_ip_masked(ip, masked):
    assert bridge.web_ip_masked(ip) == masked


@pytest.mark.parametrize(
    "ua, summary",
    [
        ("Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/130.0.0.0 Safari/537.36", "Chrome · macOS"),
        ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/130.0.0.0 Safari/537.36 Edg/130.0.0.0", "Edge · Windows"),
        ("Mozilla/5.0 (X11; Linux x86_64; rv:131.0) Gecko/20100101 Firefox/131.0", "Firefox · Linux"),
        ("Mozilla/5.0 (iPhone; CPU iPhone OS 17_5 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.5 Mobile/15E148 Safari/604.1", "Safari · iOS"),
        ("Mozilla/5.0 (iPad; CPU OS 17_5 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) CriOS/130.0.0.0 Mobile/15E148 Safari/604.1", "Chrome · iOS"),
        ("Mozilla/5.0 (Linux; Android 14; Pixel 8) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/130.0.0.0 Mobile Safari/537.36 MicroMessenger/8.0.50", "WeChat · Android"),
        ("Mozilla/5.0 (Macintosh; Intel Mac OS X 14_5) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.5 Safari/605.1.15", "Safari · macOS"),
        ("curl/8.7.1", "other · other"),
        ("", "other · other"),
        (None, "other · other"),
    ],
)
def test_web_ua_summary(ua, summary):
    assert bridge.web_ua_summary(ua) == summary
    browser, system = summary.split(" · ")
    assert browser in bridge.UA_BROWSERS and system in bridge.UA_SYSTEMS


# ----------------------------------------------------------------------------------- QR cache
def test_qr_cache_evicts_expired_entries_first_then_the_oldest():
    cache = bridge.QrCache(max_entries=3)
    now = "2026-10-14T00:00:00Z"
    cache.put("a", b"A", "2026-10-14T00:03:00Z", now)
    cache.put("b", b"B", "2026-10-14T00:00:30Z", now)
    cache.put("c", b"C", "2026-10-14T00:03:00Z", now)
    assert cache.get("a", now) == b"A" and cache.get("b", now) == b"B" and len(cache) == 3
    assert cache.get("b", "2026-10-14T00:00:30Z") is None and len(cache) == 2  # expires_at <= now: dropped on read
    cache.put("b", b"B", "2026-10-14T00:00:30Z", now)
    cache.put("d", b"D", "2026-10-14T00:03:00Z", "2026-10-14T00:01:00Z")  # b expired meanwhile: evicted first, nothing else lost
    assert len(cache) == 3 and cache.get("b", "2026-10-14T00:01:00Z") is None and cache.get("a", now) == b"A"
    cache.put("e", b"E", "2026-10-14T00:03:00Z", "2026-10-14T00:01:00Z")  # full of live entries: the oldest (a) goes
    assert len(cache) == 3 and cache.get("a", now) is None and cache.get("c", now) == b"C" and cache.get("e", now) == b"E"
    cache.put("c", b"C2", "2026-10-14T00:04:00Z", "2026-10-14T00:01:00Z")  # a re-put replaces in place
    assert len(cache) == 3 and cache.get("c", now) == b"C2"
    assert cache.get("missing", now) is None


# ----------------------------------------------------------------------------------- gc_tickets
def test_gc_tickets_deletes_rows_expired_or_consumed_more_than_a_day_ago(conn, settings):
    day = timedelta(days=1)
    _ticket_row(conn, "t1", None, "pending", to_iso(NOW - day - timedelta(seconds=1)))  # expired more than a day ago → gone
    _ticket_row(conn, "t2", None, "pending", to_iso(NOW - day))  # expired exactly a day ago → gone (<=)
    _ticket_row(conn, "t3", None, "pending", to_iso(NOW - timedelta(hours=23)))  # expired an hour short of a day → kept
    _ticket_row(conn, "t4", "ph4", "pending", to_iso(NOW + timedelta(minutes=2)))  # live → kept
    _ticket_row(conn, "t5", None, "consumed", to_iso(NOW + timedelta(minutes=2)), consumed_at=to_iso(NOW - day - timedelta(minutes=1)))  # consumed more than a day ago → gone
    _ticket_row(conn, "t6", None, "consumed", to_iso(NOW - timedelta(hours=1)), consumed_at=to_iso(NOW - timedelta(hours=1)))  # consumed an hour ago → kept (audit)
    assert bridge.gc_tickets(conn, NOW) == 3
    assert [r[0] for r in conn.execute("SELECT ticket_hash FROM wechat_tickets ORDER BY id")] == ["t3", "t4", "t6"]
    assert bridge.gc_tickets(conn, NOW) == 0
    assert bridge.gc_tickets(conn, NOW + 2 * day) == 3 and conn.execute("SELECT COUNT(*) FROM wechat_tickets").fetchone()[0] == 0


# ------------------------------------------------------------------------- delivery/wechat.py: the adapter
import httpx  # noqa: E402

from wd.delivery import wechat  # noqa: E402


def _jpeg(width: int = 430, height: int = 430) -> bytes:
    from PIL import Image

    buf = io.BytesIO()
    Image.new("RGB", (width, height), (20, 20, 20)).save(buf, format="JPEG")
    return buf.getvalue()


@pytest.fixture
def wechat_api(settings, tmp_path, monkeypatch: pytest.MonkeyPatch):
    """A configured WechatApiClient over an httpx.MockTransport: ``routes[path] = callable(request) -> Response``; ``calls`` records requests."""
    secret_file = tmp_path / "wechat.secret"
    secret_file.write_text("app-s3cret\n", encoding="utf-8")
    secret_file.chmod(0o600)
    cfg = replace(settings, wechat_appid="wx1234567890", wechat_secret_file=str(secret_file))
    calls: list[httpx.Request] = []
    routes: dict[str, object] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(request)
        route = routes.get(request.url.path)
        if route is None:
            return httpx.Response(404, text="no route")
        return route(request)  # type: ignore[operator]

    monkeypatch.setattr(wechat, "CLIENT_FACTORY", lambda: httpx.Client(transport=httpx.MockTransport(handler)))
    client = wechat.WechatApiClient.from_settings(cfg)
    assert client is not None and client.configured
    return client, calls, routes


def test_classify_and_read_secret(settings, tmp_path, caplog, monkeypatch: pytest.MonkeyPatch):
    assert [wechat.classify(c) for c in (40029, 40163, 40226, 40013, 40125, -1, 41030, None)] == ["invalid_code", "invalid_code", "invalid_code", "config", "config", "temporary", "temporary", "temporary"]
    assert wechat.read_secret(settings) is None  # unset
    missing = replace(settings, wechat_secret_file=str(tmp_path / "nope"))
    assert wechat.read_secret(missing) is None
    f = tmp_path / "s"
    f.write_text("﻿secret-line\nsecond line\n", encoding="utf-8")
    f.chmod(0o644)
    monkeypatch.setattr(wechat, "_MODE_WARNED", set())
    loose = replace(settings, wechat_secret_file=str(f))
    with caplog.at_level(logging.WARNING, logger="wd.delivery.wechat"):
        assert wechat.read_secret(loose) == "secret-line"  # BOM stripped, first line only
        assert wechat.read_secret(loose) == "secret-line" and wechat.read_secret(loose) == "secret-line"
    assert caplog.text.count("chmod 600") == 1  # the loose mode is warned about once per process, not on every scan / token / picture
    assert wechat._MODE_WARNED == {str(f)}
    monkeypatch.setattr(wechat, "_MODE_WARNED", set())  # a fresh process warns again
    with caplog.at_level(logging.WARNING, logger="wd.delivery.wechat"):
        assert wechat.read_secret(loose) == "secret-line"
    assert caplog.text.count("chmod 600") == 2
    f.write_text("\n", encoding="utf-8")
    assert wechat.read_secret(replace(settings, wechat_secret_file=str(f))) is None
    with pytest.raises(ValueError):
        wechat.WechatError("bogus", "x")
    assert wechat.wechat_client_from_settings(settings) is None
    assert isinstance(wechat.wechat_client_from_settings(replace(settings, dev=True, auth_fake_providers=True)), wechat.FakeWechatClient)
    assert wechat.WechatApiClient.from_settings(settings) is None  # not configured


def test_code2session_success_and_failures(wechat_api):
    client, calls, routes = wechat_api
    answers = iter(
        [
            httpx.Response(200, json={"openid": "o-123", "session_key": "sk", "unionid": "u-1"}),
            httpx.Response(200, json={"errcode": 40029, "errmsg": "invalid code, rid: abc"}),
            httpx.Response(200, json={"errcode": 40013, "errmsg": "invalid appid app-s3cret echoed"}),
            httpx.Response(200, json={"errcode": -1, "errmsg": "system error"}),
            httpx.Response(502, text="<html>bad gateway</html>"),
            httpx.Response(200, json={"errcode": 0, "errmsg": "ok"}),  # no openid
        ]
    )
    routes["/sns/jscode2session"] = lambda request: next(answers)
    assert client.code2session("js-1") == "o-123"
    req = calls[-1]
    assert req.method == "GET" and req.url.host == "api.weixin.qq.com"
    assert dict(req.url.params) == {"appid": "wx1234567890", "secret": "app-s3cret", "js_code": "js-1", "grant_type": "authorization_code"}
    with pytest.raises(wechat.WechatError) as e:
        client.code2session("js-2")
    assert (e.value.kind, e.value.code) == ("invalid_code", 40029)
    with pytest.raises(wechat.WechatError) as e:
        client.code2session("js-3")
    assert (e.value.kind, e.value.code) == ("config", 40013) and "app-s3cret" not in str(e.value) and "***" in str(e.value)
    with pytest.raises(wechat.WechatError) as e:
        client.code2session("js-4")
    assert (e.value.kind, e.value.code) == ("temporary", -1)
    with pytest.raises(wechat.WechatError) as e:
        client.code2session("js-5")
    assert e.value.kind == "temporary" and e.value.code is None and "502" in str(e.value)
    with pytest.raises(wechat.WechatError) as e:
        client.code2session("js-6")
    assert e.value.kind == "temporary" and "no openid" in str(e.value)

    def boom(request):
        raise httpx.ConnectError("refused", request=request)

    routes["/sns/jscode2session"] = boom
    with pytest.raises(wechat.WechatError) as e:
        client.code2session("js-7")
    assert e.value.kind == "temporary" and "ConnectError" in str(e.value)


def test_stable_token_is_cached_and_refreshed_once_on_40001(wechat_api, monkeypatch: pytest.MonkeyPatch):
    client, calls, routes = wechat_api
    tokens = iter(["tok-1", "tok-2", "tok-3"])
    routes["/cgi-bin/stable_token"] = lambda request: httpx.Response(200, json={"access_token": next(tokens), "expires_in": 7200})
    qr_answers = iter(
        [
            httpx.Response(200, headers={"content-type": "application/json"}, json={"errcode": 40001, "errmsg": "invalid credential"}),
            httpx.Response(200, headers={"content-type": "image/jpeg"}, content=_jpeg()),
        ]
    )
    routes["/wxa/getwxacodeunlimit"] = lambda request: next(qr_answers)
    assert client.access_token() == "tok-1"
    assert client.access_token() == "tok-1"  # cached: no second request
    token_posts = [c for c in calls if c.url.path == "/cgi-bin/stable_token"]
    assert len(token_posts) == 1 and token_posts[0].method == "POST"
    assert json.loads(token_posts[0].read()) == {"grant_type": "client_credential", "appid": "wx1234567890", "secret": "app-s3cret", "force_refresh": False}
    png = client.qr_png("scene-abc", page="pages/confirm/confirm", env_version="trial")
    assert png[:8] == wechat.PNG_MAGIC  # WeChat's JPEG re-encoded to PNG
    qr_posts = [c for c in calls if c.url.path == "/wxa/getwxacodeunlimit"]
    assert len(qr_posts) == 2 and dict(qr_posts[0].url.params) == {"access_token": "tok-1"} and dict(qr_posts[1].url.params) == {"access_token": "tok-2"}
    assert json.loads([c for c in calls if c.url.path == "/cgi-bin/stable_token"][1].read())["force_refresh"] is True
    assert json.loads(qr_posts[1].read()) == {"scene": "scene-abc", "page": "pages/confirm/confirm", "check_path": False, "env_version": "trial"}
    # a second 40001 in a row is a failure, not a loop; a page error is temporary with WeChat's code; a non-image body is temporary
    qr_answers2 = iter(
        [
            httpx.Response(200, json={"errcode": 42001, "errmsg": "access_token expired"}),
            httpx.Response(200, json={"errcode": 40001, "errmsg": "invalid credential"}),
            httpx.Response(200, json={"errcode": 41030, "errmsg": "invalid page"}),
            httpx.Response(200, headers={"content-type": "image/jpeg"}, content=b"not really an image"),
        ]
    )
    routes["/wxa/getwxacodeunlimit"] = lambda request: next(qr_answers2)
    with pytest.raises(wechat.WechatError) as e:
        client.qr_png("s", page="p", env_version="release")
    assert (e.value.kind, e.value.code) == ("temporary", 40001)
    with pytest.raises(wechat.WechatError) as e:
        client.qr_png("s", page="p", env_version="release")
    assert (e.value.kind, e.value.code) == ("temporary", 41030)
    with pytest.raises(wechat.WechatError) as e:
        client.qr_png("s", page="p", env_version="release")
    assert e.value.kind == "temporary" and "not an image" in str(e.value)
    # the token endpoint refusing: config kind with WeChat's code, the secret scrubbed
    routes["/cgi-bin/stable_token"] = lambda request: httpx.Response(200, json={"errcode": 40125, "errmsg": "invalid appsecret app-s3cret"})
    with pytest.raises(wechat.WechatError) as e:
        client.access_token(force=True)
    assert (e.value.kind, e.value.code) == ("config", 40125) and "app-s3cret" not in str(e.value)
    # an unreadable secret file is a config failure before any request
    client.cfg = replace(client.cfg, wechat_secret_file=str(client.cfg.wechat_secret_file) + ".missing")
    n = len(calls)
    with pytest.raises(wechat.WechatError) as e:
        client.code2session("js")
    assert e.value.kind == "config" and len(calls) == n


def test_fake_client_and_as_png():
    from PIL import Image

    fake = wechat.FakeWechatClient()
    assert fake.configured and fake.code2session("abc") == "wx_abc"
    with pytest.raises(wechat.WechatError) as e:
        fake.code2session("bad-1")
    assert (e.value.kind, e.value.code) == ("invalid_code", 40029)
    with pytest.raises(wechat.WechatError) as e:
        fake.code2session("down-1")
    assert e.value.kind == "temporary"
    png = fake.qr_png("a" * 26, page="pages/confirm/confirm", env_version="develop")
    assert png[:8] == wechat.PNG_MAGIC
    with Image.open(io.BytesIO(png)) as img:
        assert img.size == (300, 300)
    assert fake.calls == [("code2session", "abc"), ("code2session", "bad-1"), ("code2session", "down-1"), ("qr_png", "a" * 26)]
    fake.fail_qr_with = wechat.WechatError("temporary", "down")
    with pytest.raises(wechat.WechatError):
        fake.qr_png("b" * 26, page="p", env_version="release")
    assert wechat.as_png(png) is png  # a PNG passes through untouched
    converted = wechat.as_png(_jpeg(64, 48))
    with Image.open(io.BytesIO(converted)) as img:
        assert img.format == "PNG" and img.size == (64, 48)
    with pytest.raises(wechat.WechatError):
        wechat.as_png(b"\x00\x01garbage")
