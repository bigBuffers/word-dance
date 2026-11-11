"""wd/security.py: passwords + common list, sessions, throttle/lockout schedule (per identifier + IP), invites, verification codes
(login_codes: phones, e-mails, the stale-phone challenge), identities, URL check, DTOs, CLI (incl. unlock / sms-probe)."""

from __future__ import annotations

import logging
import os
import re
import sqlite3
import types
from datetime import datetime, timedelta, timezone

import httpx
import pytest

import fake_aliyun
from wd import cli, db, schemas, security
from wd.delivery import aliyun, sms
from wd.services import bank
from wd.clock import compute_next_push, to_iso
from wd.deps import hash_token
from wd.errors import ApiError

UTC = timezone.utc
NOW = datetime(2026, 10, 14, 0, 0, 0, tzinfo=UTC)
INVITE_RE = re.compile(r"^[A-Z0-9-]{10,}$")
IP = "1.2.3.4"
PHONE = "+8613800138000"


@pytest.fixture(autouse=True)
def fast_bcrypt(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr(security, "BCRYPT_ROUNDS", 4)


def make_user(conn: sqlite3.Connection, username: str = "alice", password: str = "Correct-Horse-7", role: str = "user") -> int:
    return security.create_user(conn, username=username, password_hash=security.hash_password(password), now=NOW, role=role, password_set_at=to_iso(NOW))


# ------------------------------------------------------------------------------------ passwords
def test_hash_and_verify_roundtrip():
    h = security.hash_password("Correct-Horse-7")
    assert h.startswith("$2b$04$")
    assert security.verify_password("Correct-Horse-7", h)
    assert not security.verify_password("correct-horse-7", h)
    assert not security.verify_password("Correct-Horse-7", None)  # unknown user → dummy hash, always False
    assert not security.verify_password("x", "not-a-bcrypt-hash")


def test_default_cost_is_12(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr(security, "BCRYPT_ROUNDS", 12)
    assert security.hash_password("Correct-Horse-7").startswith("$2b$12$")


def test_long_multibyte_passwords_are_truncated_to_72_bytes_not_rejected():
    pw = "汉" * 64  # 192 bytes: bcrypt 5 would raise without manual truncation
    h = security.hash_password(pw)
    assert security.verify_password(pw, h)
    assert security.verify_password("汉" * 24 + "x", h)  # same first 72 bytes — the classic bcrypt limit, documented


def test_common_password_list_shape():
    common = security.common_passwords()
    assert len(common) >= 1000
    assert all(p == p.lower() and len(p) >= 8 for p in common)
    assert {"password", "12345678", "qwertyuiop", "iloveyou", "woaini1314", "password123"} <= common


@pytest.mark.parametrize(
    "password,username,expected",
    [
        ("short7", "alice", "密码至少 8 位"),
        ("x" * 65, "alice", "密码不超过 64 个字符"),
        ("Alice_Wonder", "alice_wonder", "密码不能与用户名相同"),
        ("password123", "alice", "该密码过于常见，请换一个"),
        ("PASSWORD123", "alice", "该密码过于常见，请换一个"),  # case-insensitive membership
        ("Correct-Horse-7", "alice", None),
        ("Passw0rd!xyz", None, None),  # the conftest login() default must pass
    ],
)
def test_password_policy_table(password, username, expected):
    assert security.password_problem(password, username) == expected


def test_check_password_raises_weak_password():
    with pytest.raises(ApiError) as e:
        security.check_password("password123", "alice")
    assert e.value.code == "weak_password" and e.value.status == 400 and e.value.details["reason"]
    security.check_password("Correct-Horse-7", "alice")


# ------------------------------------------------------------------------------------- sessions
def test_create_session_rows_and_cap(conn: sqlite3.Connection):
    uid = make_user(conn)
    token = security.create_session(conn, uid, NOW, session_days=30, user_agent="UA " * 100, ip="10.0.0.9")
    row = conn.execute("SELECT * FROM sessions WHERE token_hash = ?", (hash_token(token),)).fetchone()
    assert row is not None and row["user_id"] == uid and row["expires_at"] == "2026-11-13T00:00:00Z"
    assert len(row["user_agent"]) == 200 and row["ip"] == "10.0.0.9" and row["actor_user_id"] is None  # a self login (0018)
    guardian = make_user(conn, "mum")
    child_session = security.create_session(conn, uid, NOW, session_days=30, actor_user_id=guardian)
    assert conn.execute("SELECT actor_user_id FROM sessions WHERE token_hash = ?", (hash_token(child_session),)).fetchone()[0] == guardian
    tokens = [token]
    for i in range(1, 26):
        tokens.append(security.create_session(conn, uid, NOW + timedelta(seconds=i), session_days=30))
    assert conn.execute("SELECT COUNT(*) FROM sessions WHERE user_id = ?", (uid,)).fetchone()[0] == security.MAX_SESSIONS_PER_USER
    live = {r[0] for r in conn.execute("SELECT token_hash FROM sessions WHERE user_id = ?", (uid,))}
    assert hash_token(tokens[-1]) in live and hash_token(tokens[0]) not in live  # newest kept, oldest evicted


def test_delete_and_gc_sessions(conn: sqlite3.Connection):
    uid = make_user(conn)
    keep = security.create_session(conn, uid, NOW, session_days=30)
    security.create_session(conn, uid, NOW, session_days=30)
    security.create_session(conn, uid, NOW - timedelta(days=40), session_days=30)  # already expired
    assert security.gc_sessions(conn, to_iso(NOW)) == 1
    assert security.delete_sessions(conn, uid, keep_token_hash=hash_token(keep)) == 1
    assert conn.execute("SELECT COUNT(*) FROM sessions").fetchone()[0] == 1
    security.delete_session(conn, hash_token(keep))
    assert conn.execute("SELECT COUNT(*) FROM sessions").fetchone()[0] == 0


# ------------------------------------------------------------------------------- throttle / lockout
def test_fixed_window_throttle(conn: sqlite3.Connection):
    for _ in range(3):
        assert security.throttle_hit(conn, "t:x", limit=3, window_s=60, now=NOW) is None
    assert security.throttle_hit(conn, "t:x", limit=3, window_s=60, now=NOW + timedelta(seconds=10)) == 50
    with pytest.raises(ApiError) as e:
        security.rate_limit(conn, "t:x", limit=3, window_s=60, now=NOW + timedelta(seconds=10))
    assert e.value.code == "rate_limited" and e.value.status == 429 and e.value.details == {"retry_after_s": 50}
    assert e.value.to_response().headers["Retry-After"] == "50"
    assert security.throttle_hit(conn, "t:x", limit=3, window_s=60, now=NOW + timedelta(seconds=60)) is None  # new window
    assert conn.execute("SELECT count FROM auth_throttle WHERE key = 't:x'").fetchone()[0] == 1
    assert security.throttle_hit(conn, "t:y", limit=3, window_s=60, now=NOW) is None  # keys are independent


@pytest.mark.parametrize(
    "failures,expected",
    [(1, None), (9, None), (10, 900), (11, None), (14, None), (15, 1800), (20, 3600), (25, 7200), (30, 14400), (35, 28800), (40, 57600), (45, 86400), (50, 86400), (100, 86400)],
)
def test_lockout_schedule(failures, expected):
    assert security.lock_seconds_for(failures) == expected


def test_lockout_persisted_and_reset(conn: sqlite3.Connection):
    assert security.lockout_key(" Alice ", IP) == "login:user:alice:1.2.3.4"  # per identifier AND client IP (AUTH_SIGNUP_DESIGN §5.3)
    for i in range(9):
        assert security.record_login_failure(conn, "Alice", NOW, ip=IP) is None
        assert security.lockout_remaining(conn, "alice", NOW, ip=IP) is None
    assert security.record_login_failure(conn, "alice", NOW, ip=IP) == 900  # 10th failure locks (key is case-insensitive)
    assert security.lockout_remaining(conn, "ALICE", NOW + timedelta(seconds=1), ip=IP) == 899
    assert security.lockout_remaining(conn, "alice", NOW, ip="9.9.9.9") is None  # a stranger's failures never lock the owner's own IP out
    with pytest.raises(ApiError) as e:
        security.check_lockout(conn, "alice", NOW, ip=IP)
    assert e.value.code == "account_locked" and e.value.status == 423 and e.value.details == {"retry_after_s": 900}
    security.check_lockout(conn, "alice", NOW, ip="9.9.9.9")
    assert security.lockout_remaining(conn, "alice", NOW + timedelta(seconds=900), ip=IP) is None
    # failures 11–14 do not lock again; the 15th locks for 30 minutes
    later = NOW + timedelta(seconds=901)
    for _ in range(4):
        assert security.record_login_failure(conn, "alice", later, ip=IP) is None
    assert security.record_login_failure(conn, "alice", later, ip=IP) == 1800
    security.clear_login_failures(conn, "alice", ip=IP)
    assert conn.execute("SELECT COUNT(*) FROM auth_throttle").fetchone()[0] == 0
    # a stale streak (older than 24 h, not locked) starts over
    security.record_login_failure(conn, "bob", NOW, ip=IP)
    security.record_login_failure(conn, "bob", NOW, ip=IP)
    assert conn.execute("SELECT count FROM auth_throttle WHERE key = 'login:user:bob:1.2.3.4'").fetchone()[0] == 2
    security.record_login_failure(conn, "bob", NOW + timedelta(days=2), ip=IP)
    assert conn.execute("SELECT count FROM auth_throttle WHERE key = 'login:user:bob:1.2.3.4'").fetchone()[0] == 1
    # `wd unlock`: every IP of the identifier (and a pre-0018 row without one), nothing else
    for ip in (IP, "5.6.7.8"):
        for _ in range(10):
            security.record_login_failure(conn, "Carol", NOW, ip=ip)
    conn.execute("INSERT INTO auth_throttle(key, window_start, count, blocked_until) VALUES ('login:user:carol', ?, 10, ?)", (to_iso(NOW), to_iso(NOW + timedelta(hours=1))))
    conn.execute("INSERT INTO auth_throttle(key, window_start, count) VALUES ('login:user:carol_x:1.2.3.4', ?, 3)", (to_iso(NOW),))  # `_` is literal, not a LIKE wildcard
    assert security.unlock_identifier(conn, " CAROL ") == 3
    assert security.lockout_remaining(conn, "carol", NOW, ip=IP) is None and security.lockout_remaining(conn, "carol", NOW, ip="5.6.7.8") is None
    assert {r[0] for r in conn.execute("SELECT key FROM auth_throttle")} == {"login:user:bob:1.2.3.4", "login:user:carol_x:1.2.3.4"}
    assert security.unlock_identifier(conn, "nobody") == 0


def test_lockout_key_is_the_canonical_identifier(conn: sqlite3.Connection):
    """The lockout bucket follows resolve_identifier's spellings (API.md 3): any spelling of a number is its E.164, an e-mail is
    NFKC lower-cased — so respelling the number never opens a fresh bucket and `wd unlock` finds the rows whatever the victim typed."""
    assert security.canonical_identifier(" 138 0013 8000 ") == security.canonical_identifier("+86 138-0013-8000") == security.canonical_identifier("008613800138000") == PHONE
    assert security.canonical_identifier("ｂob@Example.com") == "bob@example.com" and security.canonical_identifier(" Alice ") == "alice"
    assert security.lockout_key("138 0013 8000", IP) == security.lockout_key("+86 138-0013-8000", IP) == "login:user:+8613800138000:1.2.3.4"
    assert security.lockout_key("ｂob@Example.com", IP) == "login:user:bob@example.com:1.2.3.4"
    for _ in range(10):
        security.record_login_failure(conn, "138 0013 8000", NOW, ip=IP)
    assert security.lockout_remaining(conn, "+8613800138000", NOW, ip=IP) == 900 and security.lockout_remaining(conn, "8613800138000", NOW, ip=IP) == 900
    assert security.lockout_remaining(conn, "138 0013 8000", NOW, ip="9.9.9.9") is None  # still per client IP
    assert [r[0] for r in conn.execute("SELECT key FROM auth_throttle WHERE key LIKE 'login:user:%'")] == ["login:user:+8613800138000:1.2.3.4"]
    assert security.unlock_identifier(conn, "13800138000") == 1  # yet another spelling finds the row
    assert security.lockout_remaining(conn, "138 0013 8000", NOW, ip=IP) is None
    for _ in range(10):
        security.record_login_failure(conn, "ｂob@Example.com", NOW, ip=IP)
    assert security.lockout_remaining(conn, "bob@example.com", NOW, ip=IP) == 900
    assert security.unlock_identifier(conn, "BOB@example.com") == 1


def test_throttle_check_reads_the_window_without_counting(conn: sqlite3.Connection):
    """The failures-only login:ip rule: check first, count on the failure path only."""
    assert security.throttle_check(conn, "login:ip:x", limit=3, window_s=600, now=NOW) is None
    for _ in range(3):
        assert security.throttle_hit(conn, "login:ip:x", limit=3, window_s=600, now=NOW) is None
    assert security.throttle_check(conn, "login:ip:x", limit=3, window_s=600, now=NOW + timedelta(seconds=10)) == 590
    assert conn.execute("SELECT count FROM auth_throttle WHERE key = 'login:ip:x'").fetchone()[0] == 3  # checking did not count
    assert security.throttle_check(conn, "login:ip:x", limit=3, window_s=600, now=NOW + timedelta(seconds=600)) is None  # the window is over
    assert security.throttle_check(conn, "login:ip:x", limit=4, window_s=600, now=NOW) is None  # under a higher limit


def test_account_password_recheck_has_its_own_budget(conn: sqlite3.Connection):
    uid = make_user(conn)
    user = security.load_user(conn, uid)
    key = security.password_check_key(uid)
    for _ in range(security.PASSWORD_CHECK_LIMIT):
        with pytest.raises(ApiError) as e:
            security.verify_account_password(conn, user, "wrong-password-1", now=NOW)
        assert e.value.code == "invalid_credentials"
    assert conn.execute("SELECT count FROM auth_throttle WHERE key = ?", (key,)).fetchone()[0] == 10  # wrong guesses stay counted
    with pytest.raises(ApiError) as e:
        security.verify_account_password(conn, user, "Correct-Horse-7", now=NOW + timedelta(seconds=1))  # even the right password
    assert e.value.code == "rate_limited" and e.value.status == 429 and e.value.details == {"retry_after_s": 899}
    assert conn.execute("SELECT COUNT(*) FROM auth_throttle WHERE key LIKE 'login:user:alice:%'").fetchone()[0] == 0  # not the login lockout
    security.verify_account_password(conn, user, "Correct-Horse-7", now=NOW + timedelta(seconds=900))  # a new window
    assert conn.execute("SELECT COUNT(*) FROM auth_throttle WHERE key = ?", (key,)).fetchone()[0] == 0  # cleared by the correct password
    with pytest.raises(ApiError):
        security.verify_account_password(conn, user, "typo-password-1", now=NOW + timedelta(seconds=901))
    security.verify_account_password(conn, user, "Correct-Horse-7", now=NOW + timedelta(seconds=902))
    assert conn.execute("SELECT COUNT(*) FROM auth_throttle WHERE key = ?", (key,)).fetchone()[0] == 0  # a typo never accumulates


def test_mutation_throttle_300_per_minute_per_user(conn: sqlite3.Connection):
    for i in range(security.MUTATION_LIMIT):
        security.throttle_mutation(conn, 7, NOW + timedelta(seconds=i % 60))
    with pytest.raises(ApiError) as e:
        security.throttle_mutation(conn, 7, NOW + timedelta(seconds=59))
    assert e.value.code == "rate_limited" and e.value.status == 429 and e.value.details == {"retry_after_s": 1}
    security.throttle_mutation(conn, 8, NOW + timedelta(seconds=59))  # users are independent
    security.throttle_mutation(conn, 7, NOW + timedelta(seconds=60))  # the next window
    assert conn.execute("SELECT count FROM auth_throttle WHERE key = 'mutate:user:7'").fetchone()[0] == 1


# --------------------------------------------------------------------------------- invite codes
def test_invite_code_format_and_hash():
    code = security.generate_invite_code()
    assert INVITE_RE.match(code) and re.fullmatch(r"[A-Z2-9]{4}(-[A-Z2-9]{4}){3}", code)
    assert not set(code) & set("IO01")
    assert security.hash_invite_code(code) == security.hash_invite_code(code.lower()) == security.hash_invite_code(" " + code + " ")
    assert security.generate_invite_code() != code


def test_invite_consumption_is_atomic_and_expiring(conn: sqlite3.Connection):
    uid = make_user(conn, role="admin")
    invite_id, code, expires_at = security.create_invite(conn, created_by=uid, max_uses=1, expires_in_days=None, note=" friends ", now=NOW)
    row = conn.execute("SELECT * FROM invite_codes WHERE id = ?", (invite_id,)).fetchone()
    assert row["code_hash"] == security.hash_invite_code(code) and row["note"] == "friends" and expires_at is None and row["uses"] == 0
    assert code not in str(tuple(row))  # only the hash is stored
    assert security.consume_invite(conn, code, NOW) is True
    assert security.consume_invite(conn, code, NOW) is False  # second use fails
    assert security.consume_invite(conn, "NOPE-NOPE-NOPE-NOPE", NOW) is False
    assert security.consume_invite(conn, "", NOW) is False
    _, code2, exp2 = security.create_invite(conn, created_by=None, max_uses=2, expires_in_days=7, now=NOW)
    assert exp2 == "2026-10-21T00:00:00Z"
    assert security.consume_invite(conn, code2.lower(), NOW) and security.consume_invite(conn, code2, NOW + timedelta(days=6))
    assert security.consume_invite(conn, code2, NOW) is False  # max_uses reached
    _, code3, _ = security.create_invite(conn, created_by=None, max_uses=5, expires_in_days=1, now=NOW)
    assert security.consume_invite(conn, code3, NOW + timedelta(days=1)) is False  # expires_at > now required
    items = security.list_invites(conn)
    assert [i["max_uses"] for i in items] == [5, 2, 1] and all("code" not in i for i in items) and items[-1]["created_by"] == uid
    with pytest.raises(ValueError):
        security.create_invite(conn, created_by=None, max_uses=0, now=NOW)


# ------------------------------------------------------------------- verification codes (login_codes)
def test_login_code_hash_is_hmac_of_code_channel_target_purpose():
    import hashlib
    import hmac

    assert security.login_code_hash("k", "123456", "phone", PHONE, "login") == hmac.new(b"k", b"123456:phone:+8613800138000:login", hashlib.sha256).hexdigest()
    assert security.login_code_hash("k", "123456", "phone", PHONE, "login") != security.login_code_hash("k", "123456", "phone", PHONE, "reauth")
    assert security.login_code_hash("k", "123456", "phone", PHONE, "login") != security.login_code_hash("k", "123456", "email", PHONE, "login")
    assert security.login_code_hash("k", "123456", "phone", PHONE, "login") != security.login_code_hash("other", "123456", "phone", PHONE, "login")
    assert security.LOGIN_CODE_TTL_S == 600 and security.LOGIN_CODE_MAX_ATTEMPTS == 5 and security.CHALLENGE_TTL_S == 600


def test_login_code_lifecycle(conn: sqlite3.Connection):
    code = security.issue_login_code(conn, channel="phone", target=PHONE, purpose="login", user_id=None, ip=IP, secret_key="s", now=NOW)
    assert re.fullmatch(r"\d{6}", code)
    row = conn.execute("SELECT * FROM login_codes WHERE target = ?", (PHONE,)).fetchone()
    assert row["code_hash"] == security.login_code_hash("s", code, "phone", PHONE, "login") and row["used_at"] is None and row["attempts"] == 0
    assert row["expires_at"] == "2026-10-14T00:10:00Z" and row["ip"] == IP and row["user_id"] is None and row["created_at"] == to_iso(NOW)
    assert code not in str(tuple(row))  # only the hash is stored
    wrong = "000000" if code != "000000" else "111111"
    with pytest.raises(ApiError) as e:
        security.verify_login_code(conn, channel="phone", target=PHONE, purpose="login", code=wrong, secret_key="s", now=NOW)
    assert e.value.code == "invalid_code" and e.value.status == 400 and e.value.details == {"attempts_left": 4}
    with pytest.raises(ApiError) as e:
        security.verify_login_code(conn, channel="phone", target=PHONE, purpose="login", code=code, secret_key="other-key", now=NOW)  # a rotated key invalidates codes
    assert e.value.details == {"attempts_left": 3}
    with pytest.raises(ApiError) as e:
        security.verify_login_code(conn, channel="phone", target=PHONE, purpose="reauth", code=code, secret_key="s", now=NOW)  # another purpose: no live code
    assert e.value.details == {"attempts_left": 0}
    row_id = security.verify_login_code(conn, channel="phone", target=PHONE, purpose="login", code=code, secret_key="s", now=NOW + timedelta(minutes=9))
    assert row_id == row["id"]
    assert conn.execute("SELECT used_at FROM login_codes WHERE id = ?", (row_id,)).fetchone()[0] is None  # verified, not consumed: the caller's transaction does that
    assert security.verify_login_code(conn, channel="phone", target=PHONE, purpose="login", code=code, secret_key="s", now=NOW + timedelta(minutes=9)) == row_id  # still live until marked
    with db.tx(conn):
        assert security.mark_login_code_used(conn, row_id, NOW + timedelta(minutes=9)) is True
        assert security.mark_login_code_used(conn, row_id, NOW + timedelta(minutes=9)) is False  # a concurrent request lost
    assert security.load_login_code(conn, row_id)["used_at"] == "2026-10-14T00:09:00Z"
    with pytest.raises(ApiError) as e:
        security.verify_login_code(conn, channel="phone", target=PHONE, purpose="login", code=code, secret_key="s", now=NOW + timedelta(minutes=9))  # single use
    assert e.value.details == {"attempts_left": 0}
    # expiry at exactly 10 minutes
    code2 = security.issue_login_code(conn, channel="phone", target=PHONE, purpose="login", user_id=None, ip=IP, secret_key="s", now=NOW)
    with pytest.raises(ApiError) as e:
        security.verify_login_code(conn, channel="phone", target=PHONE, purpose="login", code=code2, secret_key="s", now=NOW + timedelta(minutes=10))
    assert e.value.details == {"attempts_left": 0}
    # a newer code voids the older unused one of the same triple; another purpose / target is untouched
    code3 = security.issue_login_code(conn, channel="phone", target=PHONE, purpose="login", user_id=None, ip=IP, secret_key="s", now=NOW)
    other = security.issue_login_code(conn, channel="phone", target="+8613900139000", purpose="login", user_id=None, ip=IP, secret_key="s", now=NOW)
    assert conn.execute("SELECT COUNT(*) FROM login_codes WHERE target = ? AND used_at IS NULL", (PHONE,)).fetchone()[0] == 1
    with pytest.raises(ApiError) as e:
        security.verify_login_code(conn, channel="phone", target=PHONE, purpose="login", code=code2, secret_key="s", now=NOW)
    assert e.value.details == {"attempts_left": 4}  # the voided code is just a wrong guess against the live one
    assert security.verify_login_code(conn, channel="phone", target="+8613900139000", purpose="login", code=other, secret_key="s", now=NOW)
    # burn after 5 wrong attempts (one was spent above)
    wrong3 = "000000" if code3 != "000000" else "111111"
    for left in (3, 2, 1, 0):
        with pytest.raises(ApiError) as e:
            security.verify_login_code(conn, channel="phone", target=PHONE, purpose="login", code=wrong3, secret_key="s", now=NOW)
        assert e.value.details == {"attempts_left": left}
    with pytest.raises(ApiError) as e:
        security.verify_login_code(conn, channel="phone", target=PHONE, purpose="login", code=code3, secret_key="s", now=NOW)
    assert e.value.details == {"attempts_left": 0}
    assert conn.execute("SELECT used_at FROM login_codes WHERE code_hash = ?", (security.login_code_hash("s", code3, "phone", PHONE, "login"),)).fetchone()[0] == to_iso(NOW)  # burnt
    # void_login_codes: a send that failed after the row was written
    code4 = security.issue_login_code(conn, channel="email", target="a@example.com", purpose="bind_email", user_id=None, ip=None, secret_key="s", now=NOW)
    assert security.void_login_codes(conn, channel="email", target="a@example.com", purpose="bind_email", now=NOW) == 1
    with pytest.raises(ApiError):
        security.verify_login_code(conn, channel="email", target="a@example.com", purpose="bind_email", code=code4, secret_key="s", now=NOW)
    with pytest.raises(ValueError):
        security.issue_login_code(conn, channel="fax", target=PHONE, purpose="login", user_id=None, ip=None, secret_key="s", now=NOW)
    with pytest.raises(ValueError):
        security.issue_login_code(conn, channel="phone", target=PHONE, purpose="dance", user_id=None, ip=None, secret_key="s", now=NOW)


def test_verify_login_code_counts_concurrent_wrong_guesses_atomically(conn: sqlite3.Connection, connect):
    """Eight connections guess the same code at the same instant: the lookup, the compare and the count share one BEGIN IMMEDIATE,
    so exactly five guesses are compared (attempts_left 4, 3, 2, 1, 0), the row is burnt by the fifth and the other three find no
    live row — the 5-attempt budget of AUTH_SIGNUP_DESIGN §5.1 holds under a flood (it did not when the count was read, then written)."""
    import threading

    code = security.issue_login_code(conn, channel="phone", target=PHONE, purpose="login", user_id=None, ip=IP, secret_key="s", now=NOW)
    wrong = "000000" if code != "000000" else "111111"
    barrier = threading.Barrier(8)
    results: list[int] = []
    errors: list[BaseException] = []
    lock = threading.Lock()

    def guess() -> None:
        c = connect()
        try:
            barrier.wait(timeout=30)
            try:
                security.verify_login_code(c, channel="phone", target=PHONE, purpose="login", code=wrong, secret_key="s", now=NOW)
            except ApiError as e:
                with lock:
                    results.append(int((e.details or {})["attempts_left"]))
        except BaseException as e:  # noqa: BLE001 — reported by the main thread
            with lock:
                errors.append(e)
        finally:
            c.close()

    threads = [threading.Thread(target=guess) for _ in range(8)]
    for t in threads:
        t.start()
    for t in threads:
        t.join(timeout=60)
    assert errors == [] and sorted(results) == [0, 0, 0, 0, 1, 2, 3, 4]
    row = conn.execute("SELECT attempts, used_at FROM login_codes WHERE target = ?", (PHONE,)).fetchone()
    assert (row["attempts"], row["used_at"]) == (5, to_iso(NOW))  # burnt exactly at the fifth guess, never counted past it
    with pytest.raises(ApiError) as e:
        security.verify_login_code(conn, channel="phone", target=PHONE, purpose="login", code=code, secret_key="s", now=NOW)
    assert e.value.details == {"attempts_left": 0}


def test_login_codes_bound_to_a_user_and_the_target_less_lookup(conn: sqlite3.Connection):
    """bind_* / reauth rows carry user_id: another user's code never verifies; with target=None the newest live row of
    (purpose, user_id) is used whatever its channel (endpoint 87's reauth code to the phone OR the e-mail)."""
    alice, bob = make_user(conn, "alice"), make_user(conn, "bob")
    code = security.issue_login_code(conn, channel="phone", target=PHONE, purpose="bind_phone", user_id=alice, ip=IP, secret_key="s", now=NOW)
    with pytest.raises(ApiError) as e:
        security.verify_login_code(conn, channel="phone", target=PHONE, purpose="bind_phone", code=code, secret_key="s", now=NOW, user_id=bob)
    assert e.value.details == {"attempts_left": 0}  # not bob's code: no live row for him, nothing counted against alice's
    assert conn.execute("SELECT attempts FROM login_codes WHERE user_id = ?", (alice,)).fetchone()[0] == 0
    row_id = security.verify_login_code(conn, channel="phone", target=PHONE, purpose="bind_phone", code=code, secret_key="s", now=NOW, user_id=alice)
    assert security.load_login_code(conn, row_id)["user_id"] == alice
    # reauth: the phone code first, then an e-mail one — target=None finds the newest live row of the user
    first = security.issue_login_code(conn, channel="phone", target=PHONE, purpose="reauth", user_id=alice, ip=IP, secret_key="s", now=NOW)
    second = security.issue_login_code(conn, channel="email", target="alice@example.com", purpose="reauth", user_id=alice, ip=IP, secret_key="s", now=NOW + timedelta(seconds=1))
    assert conn.execute("SELECT COUNT(*) FROM login_codes WHERE purpose = 'reauth' AND used_at IS NULL").fetchone()[0] == 2  # different targets: both live
    with pytest.raises(ApiError) as e:
        security.verify_login_code(conn, channel=None, target=None, purpose="reauth", code=first, secret_key="s", now=NOW + timedelta(seconds=2), user_id=alice)
    assert e.value.details == {"attempts_left": 4}  # the newest row is the e-mail one
    assert security.verify_login_code(conn, channel=None, target=None, purpose="reauth", code=second, secret_key="s", now=NOW + timedelta(seconds=2), user_id=alice)
    with pytest.raises(ValueError):
        security.verify_login_code(conn, channel=None, target=None, purpose="reauth", code=second, secret_key="s", now=NOW, user_id=None)
    # a login code may also name its account (the challenge e-mail, a reset): user_id narrows, None matches any row
    code_r = security.issue_login_code(conn, channel="email", target="alice@example.com", purpose="reset_password", user_id=alice, ip=IP, secret_key="s", now=NOW)
    assert security.verify_login_code(conn, channel="email", target="alice@example.com", purpose="reset_password", code=code_r, secret_key="s", now=NOW)
    assert security.verify_login_code(conn, channel="email", target="alice@example.com", purpose="reset_password", code=code_r, secret_key="s", now=NOW, user_id=alice)
    with pytest.raises(ApiError):
        security.verify_login_code(conn, channel="email", target="alice@example.com", purpose="reset_password", code=code_r, secret_key="s", now=NOW, user_id=bob)
    # the account's deletion takes its codes along (0018 cascade)
    conn.execute("DELETE FROM users WHERE id = ?", (alice,))
    assert conn.execute("SELECT COUNT(*) FROM login_codes WHERE user_id = ?", (alice,)).fetchone()[0] == 0


def test_challenge_token_lifecycle(conn: sqlite3.Connection):
    """The stale-phone challenge (AUTH_SIGNUP_DESIGN §5.3): an opaque token in login_codes(purpose='challenge') bound to the old account."""
    alice = make_user(conn, "alice")
    token = security.issue_challenge_token(conn, target=PHONE, user_id=alice, ip=IP, secret_key="s", now=NOW)
    assert len(token) >= 40 and token not in str(conn.execute("SELECT * FROM login_codes").fetchall())
    row = conn.execute("SELECT * FROM login_codes WHERE purpose = 'challenge'").fetchone()
    assert row["channel"] == "phone" and row["target"] == PHONE and row["user_id"] == alice and row["expires_at"] == "2026-10-14T00:10:00Z"
    assert row["code_hash"] == security.login_code_hash("s", token, "phone", PHONE, "challenge")
    found = security.verify_challenge_token(conn, token=token, secret_key="s", now=NOW + timedelta(minutes=9))
    assert found["id"] == row["id"] and found["user_id"] == alice and found["target"] == PHONE
    for bad in (token + "x", "", token.upper()):
        with pytest.raises(ApiError) as e:
            security.verify_challenge_token(conn, token=bad, secret_key="s", now=NOW)
        assert e.value.code == "challenge_expired" and e.value.status == 400
    with pytest.raises(ApiError):
        security.verify_challenge_token(conn, token=token, secret_key="other", now=NOW)
    with pytest.raises(ApiError):
        security.verify_challenge_token(conn, token=token, secret_key="s", now=NOW + timedelta(minutes=10))  # expired
    # a second challenge for the same number replaces the first; consuming it ends it
    token2 = security.issue_challenge_token(conn, target=PHONE, user_id=alice, ip=IP, secret_key="s", now=NOW)
    with pytest.raises(ApiError):
        security.verify_challenge_token(conn, token=token, secret_key="s", now=NOW)
    found2 = security.verify_challenge_token(conn, token=token2, secret_key="s", now=NOW)
    with db.tx(conn):
        assert security.mark_login_code_used(conn, found2["id"], NOW)
    with pytest.raises(ApiError):
        security.verify_challenge_token(conn, token=token2, secret_key="s", now=NOW)


def test_phone_normalisation_masks_and_placeholders(conn: sqlite3.Connection):
    for raw in ("13800138000", "+8613800138000", "8613800138000", "008613800138000", " 138 0013-8000 ", "+86 138-0013-8000"):
        assert security.normalize_phone(raw) == PHONE, raw
    for raw in ("", "1380013800", "138001380001", "+15551234567", "+8603800138000", "abc", "+86 2 3800138000"):
        assert security.normalize_phone(raw) is None, raw
    assert security.phone_prefix(PHONE) == "1380013"
    assert security.mask_phone(PHONE) == "138****8000" and security.mask_phone("13800138000") == "138****8000" and security.mask_phone("") == "****"
    assert security.mask_email("alice@qq.com") == "a***@qq.com" and security.mask_email("x@example.com") == "x***@example.com" and security.mask_email("odd") == "o***"
    name = security.placeholder_username(conn)
    assert security.PLACEHOLDER_USERNAME_RE.match(name) and schemas.USERNAME_RE.match(name)
    taken = {security.placeholder_username(conn) for _ in range(20)}
    assert len(taken) == 20
    h = security.unusable_password_hash()
    assert h.startswith("$2b$04$") and not security.verify_password("", h) and security.unusable_password_hash() != h


def test_identities_and_user_dto_fields(conn: sqlite3.Connection):
    alice = make_user(conn, "alice")
    assert security.phone_identity(conn, alice) is None and security.identity_by_subject(conn, "phone", PHONE) is None
    conn.execute("INSERT INTO identities(user_id, provider, subject, verified_at, last_login_at) VALUES (?, 'phone', ?, ?, ?)", (alice, PHONE, to_iso(NOW), to_iso(NOW)))
    ident = security.phone_identity(conn, alice)
    assert ident is not None and ident["subject"] == PHONE and security.identity_by_subject(conn, "phone", PHONE)["user_id"] == alice
    row = security.load_user(conn, alice)
    dto = security.user_dto(row)
    assert (dto["has_password"], dto["phone_masked"], dto["needs_profile"], dto["age_band"]) == (True, None, False, None)
    assert security.user_dto_for(conn, row)["phone_masked"] == "138****8000"
    schemas.User.model_validate(security.user_dto_for(conn, row))
    conn.execute("UPDATE identities SET disputed_at = ? WHERE user_id = ?", (to_iso(NOW), alice))
    assert security.phone_identity(conn, alice) is None and security.user_dto_for(conn, row)["phone_masked"] is None  # a disputed row no longer counts
    # a code-created account: placeholder name, unusable password, no age band → needs_profile until endpoint 89
    with db.tx(conn):
        bob = security.create_user(conn, username=security.placeholder_username(conn), password_hash=security.unusable_password_hash(), now=NOW, password_set_at=None, email="bob@example.com", email_verified_at=to_iso(NOW))
    b = security.load_user(conn, bob)
    assert b["password_set_at"] is None and b["email_verified_at"] == to_iso(NOW) and b["account_kind"] == "learner"
    dto = security.user_dto(b)
    assert (dto["has_password"], dto["needs_profile"], dto["email_verified"]) == (False, True, True)
    conn.execute("UPDATE users SET age_band = '14plus' WHERE id = ?", (bob,))
    dto = security.user_dto(security.load_user(conn, bob))
    assert (dto["needs_profile"], dto["age_band"]) == (False, "14plus")
    # set_password stamps password_set_at (the only writer)
    security.set_password(conn, bob, security.hash_password("Fresh-Horse-9"), NOW + timedelta(hours=1))
    b = security.load_user(conn, bob)
    assert b["password_set_at"] == "2026-10-14T01:00:00Z" and security.user_dto(b)["has_password"] is True
    # a row without the 0018 columns (an older dict in a test) still renders
    legacy = {k: v for k, v in dict(row).items() if k not in ("password_set_at", "age_band", "account_kind", "guardian_user_id", "profile_prompted_at")}
    assert security.user_dto(legacy)["has_password"] is False and security.user_dto(legacy)["age_band"] is None
    assert (security.user_dto(legacy)["account_kind"], security.user_dto(legacy)["is_child"], security.user_dto(legacy, now=NOW)["needs_profile_prompt"]) == ("learner", False, True)
    # slice 1-B: the child columns join create_user's INSERT; a child is never prompted, a guardian's kind is carried
    with db.tx(conn):
        kid = security.create_user(conn, username="u_kidkidki", password_hash=security.unusable_password_hash(), now=NOW, password_set_at=None, guardian_user_id=alice, age_band="u14", age_declared_at=to_iso(NOW), age_declared_ip="1.2.3.4", guardian_consent_at=to_iso(NOW))
        parent = security.create_user(conn, username="u_parentpa", password_hash=security.unusable_password_hash(), now=NOW, password_set_at=None, account_kind="guardian")
    k = security.load_user(conn, kid)
    assert (k["guardian_user_id"], k["age_band"], k["age_declared_ip"], k["guardian_consent_at"], k["account_kind"]) == (alice, "u14", "1.2.3.4", to_iso(NOW), "learner")
    assert (security.user_dto(k, now=NOW)["is_child"], security.user_dto(k, now=NOW)["needs_profile_prompt"]) == (True, False)
    g = security.user_dto(security.load_user(conn, parent), now=NOW)
    assert (g["account_kind"], g["is_child"], g["needs_profile"], g["needs_profile_prompt"]) == ("guardian", False, True, False)  # the placeholder account goes through 89 first
    with pytest.raises(ValueError):
        security.create_user(conn, username="x", password_hash="h", now=NOW, password_set_at=None, account_kind="teacher")


# ------------------------------------------------------------------------------- webhook host check
@pytest.mark.parametrize(
    "url,ok",
    [
        ("https://hooks.example.com/x?token=1", True),
        ("https://qyapi.weixin.qq.com/cgi-bin/webhook/send?key=abc", True),
        ("https://open.feishu.cn:443/open-apis/bot/v2/hook/abc", True),
        ("https://xn--fsq.example.com/", True),
        ("http://hooks.example.com/x", False),
        ("https://10.0.0.1/x", False),
        ("https://127.0.0.1/x", False),
        ("https://169.254.169.254/latest", False),
        ("https://100.64.0.1/", False),
        ("https://8.8.8.8/", False),  # raw IPs are never allowed, public or not
        ("https://[::1]/", False),
        ("https://[fe80::1]/", False),
        ("https://[2001:db8::1]/", False),
        ("https://localhost/x", False),
        ("https://LOCALHOST:8443/x", False),
        ("https://nas.local/x", False),
        ("https://db.internal/x", False),
        ("https://router.lan/", False),
        ("https://intranet/", False),
        ("https://user:pw@hooks.example.com/", False),
        ("https://hooks.example.com:70000/", False),
        ("https://127.1/", False),
        ("https://2130706433/", False),
        ("https://0x7f000001/", False),
        ("https://hooks.ex_ample.com/", False),
        ("https://-bad.example.com/", False),
        ("https:///x", False),
        ("ftp://hooks.example.com/", False),
        ("", False),
        ("not a url", False),
    ],
)
def test_is_safe_https_url(url, ok):
    assert security.is_safe_https_url(url) is ok


# ------------------------------------------------------------------------------------- accounts
def test_create_user_writes_settings_with_next_push_at(conn: sqlite3.Connection):
    uid = make_user(conn, "张三")
    user = security.load_user(conn, uid)
    assert user["role"] == "user" and user["onboarding_state"] == "pending" and user["created_at"] == to_iso(NOW)
    dto = security.user_dto(user)
    assert dto == {"id": uid, "username": "张三", "display_name": "张三", "email": None, "email_verified": False, "role": "user", "onboarding_state": "pending", "created_at": "2026-10-14T00:00:00Z", "has_password": True, "phone_masked": None, "needs_profile": False, "age_band": None, "account_kind": "learner", "is_child": False, "needs_profile_prompt": False}
    # the legacy 「补充信息」 prompt (API.md §9.1, slice 1-B): only with `now`, never for a declared / child / placeholder account, snoozed 30 days
    assert security.user_dto(user, now=NOW)["needs_profile_prompt"] is True
    conn.execute("UPDATE users SET profile_prompted_at = ? WHERE id = ?", (to_iso(NOW), uid))
    assert security.user_dto(security.load_user(conn, uid), now=NOW + timedelta(days=29))["needs_profile_prompt"] is False
    assert security.user_dto(security.load_user(conn, uid), now=NOW + timedelta(days=30))["needs_profile_prompt"] is True
    conn.execute("UPDATE users SET age_band = 'adult' WHERE id = ?", (uid,))
    assert security.user_dto(security.load_user(conn, uid), now=NOW + timedelta(days=31))["needs_profile_prompt"] is False
    assert user["password_set_at"] == to_iso(NOW)
    settings = security.settings_dto(conn, uid)
    assert settings["next_push_at"] == to_iso(compute_next_push(NOW, "Asia/Shanghai", "08:00")) == "2026-10-15T00:00:00Z"
    assert settings["stages"] == ["xs", "zk"] and settings["current_stage"] == "xs" and settings["email_verified"] is False  # K-12 DDL defaults
    assert settings["push_enabled"] is True and settings["webhook_url"] is None and settings["updated_at"] == "2026-10-14T00:00:00Z"
    assert security.load_user_by_name(conn, "张三")["id"] == uid and security.load_user_by_name(conn, "nobody") is None
    assert security.username_taken(conn, "张三") and not security.username_taken(conn, "李四")
    with pytest.raises(ValueError):
        security.create_user(conn, username="x", password_hash="h", now=NOW, role="root", password_set_at=None)


def test_settings_row_to_dto_falls_back_on_unknown_stage_codes_and_indices(conn: sqlite3.Connection, caplog):
    """The DTO shares bank.known_stages with the study paths (PLAN §2.1): a stages_json naming no known code → DEFAULT_STAGES
    plus a stage_fallback warning instead of a response-validation 500; an index this build does not know (older server,
    newer row) → the first target stage, so `current_stage ∈ stages` holds on the wire (impl-review final F2)."""
    uid = make_user(conn, "legacy")
    row = security.load_settings_row(conn, uid)
    assert row is not None
    with caplog.at_level(logging.WARNING):
        dto = security.settings_row_to_dto({**row, "stages_json": '["cet9"]'})
        assert dto["stages"] == list(bank.DEFAULT_STAGES) and dto["current_stage"] == "xs"
        schemas.Settings.model_validate(dto)
        dto = security.settings_row_to_dto({**row, "stages_json": '["gk","cet4"]', "current_stage": 9})
        assert dto["stages"] == ["gk", "cet4"] and dto["current_stage"] == "gk"
        schemas.Settings.model_validate(dto)
        dto = security.settings_row_to_dto({**row, "stages_json": '["cet9","gk"]', "current_stage": 3})
        assert dto["stages"] == ["gk"] and dto["current_stage"] == "gk"  # unknown codes dropped, known ones kept, no fallback
    events = [r for r in caplog.records if getattr(r, "event", None) == "stage_fallback"]
    assert len(events) == 2 and all(r.user_id == uid for r in events)


def test_last_admin_guard_helpers(conn: sqlite3.Connection):
    a = make_user(conn, "alice", role="admin")
    b = make_user(conn, "bob", role="admin")
    assert security.other_active_admins(conn, a) == 1
    assert not security.is_last_active_admin(conn, security.load_user(conn, a))
    conn.execute("UPDATE users SET is_active = 0 WHERE id = ?", (b,))
    assert security.is_last_active_admin(conn, security.load_user(conn, a))
    assert not security.is_last_active_admin(conn, security.load_user(conn, b))  # inactive: not "the last active admin"


# ------------------------------------------------------------------------------------------- CLI
def test_cli_refuses_unmigrated_db(settings, capsys):
    with pytest.raises(SystemExit) as e:
        cli.main(["invite"])
    assert e.value.code == 2 and "wd migrate" in capsys.readouterr().err


def test_cli_create_admin_set_password_promote_demote_invite(settings, monkeypatch: pytest.MonkeyPatch, capsys):
    assert cli.main(["migrate"]) == 0
    capsys.readouterr()
    # install.sh's unattended form on a fresh DB without WD_ADMIN_USERNAME: a hint and exit 0 (install.sh runs
    # under `set -e`; a non-zero status here would abort it before the systemd steps), no user created
    monkeypatch.delenv("WD_ADMIN_USERNAME", raising=False)
    monkeypatch.delenv("WD_ADMIN_PASSWORD", raising=False)
    assert cli.main(["create-admin", "--if-none"]) == 0
    assert "first account registered" in capsys.readouterr().out
    assert cli.main(["create-admin"]) == 2  # the explicit form still demands a username
    assert "WD_ADMIN_USERNAME" in capsys.readouterr().err
    # non-interactive without a password source → exit 2
    assert cli.main(["create-admin", "--username", "root1"]) == 2
    assert "WD_ADMIN_PASSWORD" in capsys.readouterr().err
    monkeypatch.setenv("ROOT_PW", "Correct-Horse-7")
    assert cli.main(["create-admin", "--username", "root1", "--password-env", "ROOT_PW"]) == 0
    assert "created admin root1" in capsys.readouterr().out
    assert cli.main(["create-admin", "--username", "root1", "--password-env", "ROOT_PW"]) == 1  # exists
    assert cli.main(["create-admin", "--if-none", "--username", "other", "--password-env", "ROOT_PW"]) == 0
    assert "nothing to do" in capsys.readouterr().out
    monkeypatch.setenv("ROOT_PW", "password123")
    assert cli.main(["create-admin", "--username", "root2", "--password-env", "ROOT_PW"]) == 2  # weak
    assert "weak password" in capsys.readouterr().err
    monkeypatch.setenv("WD_ADMIN_USERNAME", "root3")
    monkeypatch.setenv("WD_ADMIN_PASSWORD", "Another-Horse-8")
    assert cli.main(["create-admin"]) == 0  # unattended install.sh form
    capsys.readouterr()
    c = db.connect(settings.db_path)
    try:
        rows = {r["username"]: r for r in c.execute("SELECT * FROM users")}
        assert rows["root1"]["role"] == "admin" and rows["root3"]["role"] == "admin" and "root2" not in rows
        assert security.verify_password("Correct-Horse-7", rows["root1"]["password_hash"])
        assert c.execute("SELECT next_push_at FROM user_settings WHERE user_id = ?", (rows["root1"]["id"],)).fetchone()[0] is not None
        root1 = int(rows["root1"]["id"])
        security.create_session(c, root1, NOW, session_days=30)
    finally:
        c.close()
    # set-password revokes sessions
    monkeypatch.setenv("NEW_PW", "Fresh-Horse-9")
    assert cli.main(["set-password", "root1", "--password-env", "NEW_PW"]) == 0
    assert cli.main(["set-password", "ghost", "--password-env", "NEW_PW"]) == 1
    capsys.readouterr()
    c = db.connect(settings.db_path)
    try:
        assert security.verify_password("Fresh-Horse-9", c.execute("SELECT password_hash FROM users WHERE id = ?", (root1,)).fetchone()[0])
        assert c.execute("SELECT COUNT(*) FROM sessions WHERE user_id = ?", (root1,)).fetchone()[0] == 0
    finally:
        c.close()
    # promote / demote with the last-admin guard
    assert cli.main(["demote", "root1"]) == 0 and cli.main(["demote", "root3"]) == 1  # root3 is now the last admin
    assert "last active admin" in capsys.readouterr().err
    assert cli.main(["promote", "root1"]) == 0 and cli.main(["promote", "root1"]) == 0 and cli.main(["promote", "ghost"]) == 1
    capsys.readouterr()
    c = db.connect(settings.db_path)
    try:
        assert c.execute("SELECT role FROM users WHERE username = 'root1'").fetchone()[0] == "admin"
        # a code-created account: unusable hash, password_set_at NULL (API.md 81)
        with db.tx(c):
            codey = security.placeholder_username(c)
            security.create_user(c, username=codey, password_hash=security.unusable_password_hash(), now=NOW, password_set_at=None, email="code@example.com", email_verified_at=to_iso(NOW))
    finally:
        c.close()
    # promote refuses an account without a password — the API 57 rule (admin_needs_password): admins sign in with a password only,
    # so the promotion would make an admin nobody can log in as; set-password first, then it goes through
    assert cli.main(["promote", codey]) == 1
    err = capsys.readouterr().err
    assert "admin_needs_password" in err and "has no password" in err and "set-password" in err
    c = db.connect(settings.db_path)
    try:
        assert c.execute("SELECT role FROM users WHERE username = ?", (codey,)).fetchone()[0] == "user"  # no UPDATE
    finally:
        c.close()
    assert cli.main(["set-password", codey, "--password-env", "NEW_PW"]) == 0
    assert cli.main(["promote", codey]) == 0
    capsys.readouterr()
    c = db.connect(settings.db_path)
    try:
        role, password_set_at = c.execute("SELECT role, password_set_at FROM users WHERE username = ?", (codey,)).fetchone()
        assert role == "admin" and password_set_at is not None
    finally:
        c.close()
    # invite prints only the code on stdout
    assert cli.main(["invite", "--uses", "2", "--days", "7", "--note", "friends"]) == 0
    out, err = capsys.readouterr()
    lines = out.strip().splitlines()
    assert len(lines) == 1 and INVITE_RE.match(lines[0]) and "expires" in err
    c = db.connect(settings.db_path)
    try:
        row = c.execute("SELECT * FROM invite_codes").fetchone()
        assert row["max_uses"] == 2 and row["uses"] == 0 and row["note"] == "friends" and row["code_hash"] == security.hash_invite_code(lines[0])
        assert row["expires_at"] is not None and row["created_by"] is None
    finally:
        c.close()
    assert cli.main(["invite", "--uses", "0"]) == 2 and cli.main(["invite", "--days", "400"]) == 2


def test_cli_set_password_never_takes_the_admin_password_implicitly(settings, monkeypatch: pytest.MonkeyPatch, capsys):
    """The bootstrap secret often lingers in ``$WD_DATA_DIR/.env`` (``cli.main`` loads it into the environment): only
    ``create-admin`` may read ``WD_ADMIN_PASSWORD``; ``set-password`` prompts, or needs an explicit ``--password-env``."""
    assert cli.main(["migrate"]) == 0
    monkeypatch.setenv("WD_ADMIN_USERNAME", "root1")
    monkeypatch.setenv("WD_ADMIN_PASSWORD", "Adm1n-Secret-Pw")
    assert cli.main(["create-admin", "--if-none"]) == 0  # the unattended install.sh form still reads the variable …
    out, err = capsys.readouterr()
    assert "created admin root1" in out and "WD_ADMIN_PASSWORD" in err  # … and says so
    c = db.connect(settings.db_path)
    try:
        bob = make_user(c, "bob", "Bobs-Own-Pw-1")
    finally:
        c.close()

    def bob_hash() -> str:
        c = db.connect(settings.db_path)
        try:
            return str(c.execute("SELECT password_hash FROM users WHERE id = ?", (bob,)).fetchone()[0])
        finally:
            c.close()

    # non-interactive (pytest's stdin is not a tty) with WD_ADMIN_PASSWORD still set: refused, nothing changed
    assert cli.main(["set-password", "bob"]) == 2
    err = capsys.readouterr().err
    assert "--password-env" in err and "WD_ADMIN_PASSWORD" not in err
    assert security.verify_password("Bobs-Own-Pw-1", bob_hash()) and not security.verify_password("Adm1n-Secret-Pw", bob_hash())
    # interactive: prompts twice even though WD_ADMIN_PASSWORD is set
    prompts: list[str] = []
    answers = ["Fresh-Horse-9", "Fresh-Horse-9", "Fresh-Horse-9", "Other-Horse-9"]
    monkeypatch.setattr(security.sys, "stdin", types.SimpleNamespace(isatty=lambda: True))
    monkeypatch.setattr(security.getpass, "getpass", lambda prompt="": (prompts.append(prompt), answers.pop(0))[1])
    assert cli.main(["set-password", "bob"]) == 0
    assert prompts == ["password for bob: ", "repeat password: "]
    assert "password updated for bob" in capsys.readouterr().out
    assert security.verify_password("Fresh-Horse-9", bob_hash()) and not security.verify_password("Adm1n-Secret-Pw", bob_hash())
    assert cli.main(["set-password", "bob"]) == 2  # mismatching repeat
    assert "do not match" in capsys.readouterr().err
    assert security.verify_password("Fresh-Horse-9", bob_hash())
    # an explicit variable is still honoured (and named)
    monkeypatch.setenv("NEW_PW", "Newer-Horse-10")
    assert cli.main(["set-password", "bob", "--password-env", "NEW_PW"]) == 0
    assert "NEW_PW" in capsys.readouterr().err
    assert security.verify_password("Newer-Horse-10", bob_hash())


def test_cli_commands_are_registered(settings):
    parser = cli.build_parser()
    commands = set(parser._subparsers._group_actions[0].choices)  # type: ignore[union-attr]
    assert {"create-admin", "set-password", "promote", "demote", "invite", "unlock", "sms-probe"} <= commands
    assert cli.COMMAND_OWNERS["wd.security"] == ("create-admin", "set-password", "promote", "demote", "invite", "unlock", "sms-probe")
    assert os.path.isfile(security.COMMON_PASSWORDS_PATH)


def test_cli_unlock_clears_every_ip_of_the_identifier(settings, capsys):
    assert cli.main(["migrate"]) == 0
    capsys.readouterr()
    c = db.connect(settings.db_path)
    try:
        for ip in (IP, "5.6.7.8"):
            for _ in range(10):
                security.record_login_failure(c, "Alice", NOW, ip=ip)
        security.record_login_failure(c, "bob", NOW, ip=IP)
    finally:
        c.close()
    assert cli.main(["unlock", "alice"]) == 0
    out, err = capsys.readouterr()
    assert out.strip() == "unlocked: 2 lockout row(s) removed" and "alice" not in out  # the identifier may be a phone / e-mail: not echoed
    assert cli.main(["unlock", "alice"]) == 0 and "0 lockout row(s)" in capsys.readouterr().out
    assert cli.main(["unlock", "  "]) == 2 and "identifier" in capsys.readouterr().err
    c = db.connect(settings.db_path)
    try:
        assert [r[0] for r in c.execute("SELECT key FROM auth_throttle")] == ["login:user:bob:1.2.3.4"]
    finally:
        c.close()


def _sms_env(monkeypatch: pytest.MonkeyPatch, tmp_path) -> None:
    secret = tmp_path / "aliyun.secret"
    secret.write_text("testsecret\n", encoding="utf-8")
    secret.chmod(0o600)
    monkeypatch.setenv("WD_SMS_PROVIDER", "aliyun_verify")
    monkeypatch.setenv("WD_ALIYUN_ACCESS_KEY_ID", "LTAI-test-id")
    monkeypatch.setenv("WD_ALIYUN_ACCESS_KEY_SECRET_FILE", str(secret))
    monkeypatch.setenv("WD_ALIYUN_SMS_SIGN_NAME", "速通互联验证码")


def test_cli_sms_probe(settings, monkeypatch: pytest.MonkeyPatch, capsys, tmp_path):
    """`wd sms-probe <number>`: exit 2 without a provider / for a non-mainland number; one real code through the configured sender,
    the provider's answer printed, never the code or the full number; exit 1 when the provider refuses."""
    assert cli.main(["sms-probe", "13800138000"]) == 2
    assert "WD_SMS_PROVIDER" in capsys.readouterr().err
    _sms_env(monkeypatch, tmp_path)
    assert cli.main(["sms-probe", "+15551234567"]) == 2
    assert "mainland" in capsys.readouterr().err
    calls: list[dict] = []
    transport = fake_aliyun.transport("ok", calls=calls, secret="testsecret")
    monkeypatch.setattr(aliyun, "CLIENT_FACTORY", lambda: httpx.Client(transport=transport))
    assert cli.main(["sms-probe", "138 0013 8000"]) == 0
    out, err = capsys.readouterr()
    assert out.startswith("sms-probe: code sent to 138****8000 via aliyun_verify, template 100001") and "Code=OK" in out and "RequestId=FAKE-" in out
    assert "13800138000" not in out and err == ""
    assert len(calls) == 1 and calls[0]["params"]["PhoneNumber"] == "13800138000" and calls[0]["params"]["TemplateCode"] == "100001"
    sent_code = __import__("json").loads(calls[0]["params"]["TemplateParam"])["code"]
    assert re.fullmatch(r"\d{6}", sent_code) and sent_code not in out
    fake_aliyun.set_mode(transport, "FREQUENCY_FAIL")
    assert cli.main(["sms-probe", "13800138000"]) == 1
    out, err = capsys.readouterr()
    assert out == "" and "refused the send to 138****8000" in err and "FREQUENCY_FAIL" in err and "rate_limited" in err
    # the recording double (what the integration tests install) works through the same path
    recorder = sms.RecordingSmsSender()
    monkeypatch.setattr(sms, "sms_sender_from_settings", lambda cfg: recorder)
    assert cli.main(["sms-probe", "13800138000"]) == 0
    assert "138****8000" in capsys.readouterr().out and len(recorder.sent) == 1 and recorder.sent[0].to == PHONE and recorder.sent[0].minutes == 10
    recorder.fail_with = sms.SmsError("config", "FUNCTION_NOT_OPENED: 没有开通融合认证功能")
    assert cli.main(["sms-probe", "13800138000"]) == 1 and "config" in capsys.readouterr().err
