"""wd/security.py: passwords + common list, sessions, throttle/lockout schedule, invites, e-mail codes, URL check, DTOs, CLI."""

from __future__ import annotations

import os
import re
import sqlite3
from datetime import datetime, timedelta, timezone

import pytest

from wd import cli, db, security
from wd.clock import compute_next_push, to_iso
from wd.deps import hash_token
from wd.errors import ApiError

UTC = timezone.utc
NOW = datetime(2026, 10, 14, 0, 0, 0, tzinfo=UTC)
INVITE_RE = re.compile(r"^[A-Z0-9-]{10,}$")


@pytest.fixture(autouse=True)
def fast_bcrypt(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr(security, "BCRYPT_ROUNDS", 4)


def make_user(conn: sqlite3.Connection, username: str = "alice", password: str = "Correct-Horse-7", role: str = "user") -> int:
    return security.create_user(conn, username=username, password_hash=security.hash_password(password), now=NOW, role=role)


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
    assert len(row["user_agent"]) == 200 and row["ip"] == "10.0.0.9"
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
    for i in range(9):
        assert security.record_login_failure(conn, "Alice", NOW) is None
        assert security.lockout_remaining(conn, "alice", NOW) is None
    assert security.record_login_failure(conn, "alice", NOW) == 900  # 10th failure locks (key is case-insensitive)
    assert security.lockout_remaining(conn, "ALICE", NOW + timedelta(seconds=1)) == 899
    with pytest.raises(ApiError) as e:
        security.check_lockout(conn, "alice", NOW)
    assert e.value.code == "account_locked" and e.value.status == 423 and e.value.details == {"retry_after_s": 900}
    assert security.lockout_remaining(conn, "alice", NOW + timedelta(seconds=900)) is None
    # failures 11–14 do not lock again; the 15th locks for 30 minutes
    later = NOW + timedelta(seconds=901)
    for _ in range(4):
        assert security.record_login_failure(conn, "alice", later) is None
    assert security.record_login_failure(conn, "alice", later) == 1800
    security.clear_login_failures(conn, "alice")
    assert conn.execute("SELECT COUNT(*) FROM auth_throttle").fetchone()[0] == 0
    # a stale streak (older than 24 h, not locked) starts over
    security.record_login_failure(conn, "bob", NOW)
    security.record_login_failure(conn, "bob", NOW)
    assert conn.execute("SELECT count FROM auth_throttle WHERE key = 'login:user:bob'").fetchone()[0] == 2
    security.record_login_failure(conn, "bob", NOW + timedelta(days=2))
    assert conn.execute("SELECT count FROM auth_throttle WHERE key = 'login:user:bob'").fetchone()[0] == 1


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


# ---------------------------------------------------------------------------------- e-mail codes
def test_email_code_hash_is_hmac_of_code_and_user():
    import hashlib
    import hmac

    assert security.email_code_hash("k", "123456", 7) == hmac.new(b"k", b"123456:7", hashlib.sha256).hexdigest()
    assert security.email_code_hash("k", "123456", 7) != security.email_code_hash("k", "123456", 8)
    assert security.email_code_hash("k", "123456", 7) != security.email_code_hash("other", "123456", 7)


def test_email_code_lifecycle(conn: sqlite3.Connection):
    uid = make_user(conn)
    code = security.issue_email_code(conn, uid, "a@example.com", secret_key="s", now=NOW)
    assert re.fullmatch(r"\d{6}", code)
    row = conn.execute("SELECT * FROM email_codes WHERE user_id = ?", (uid,)).fetchone()
    assert row["code_hash"] == security.email_code_hash("s", code, uid) and row["expires_at"] == "2026-10-14T00:15:00Z" and row["used_at"] is None
    wrong = "000000" if code != "000000" else "111111"
    with pytest.raises(ApiError) as e:
        security.verify_email_code(conn, uid, wrong, secret_key="s", now=NOW)
    assert e.value.code == "invalid_code" and e.value.details == {"attempts_left": 4}
    with pytest.raises(ApiError) as e:
        security.verify_email_code(conn, uid, code, secret_key="other-key", now=NOW)  # a rotated key invalidates codes
    assert e.value.details == {"attempts_left": 3}
    assert security.verify_email_code(conn, uid, code, secret_key="s", now=NOW + timedelta(minutes=14)) == "a@example.com"
    with pytest.raises(ApiError) as e:
        security.verify_email_code(conn, uid, code, secret_key="s", now=NOW)  # single use
    assert e.value.details == {"attempts_left": 0}
    # expiry
    code2 = security.issue_email_code(conn, uid, "a@example.com", secret_key="s", now=NOW)
    with pytest.raises(ApiError) as e:
        security.verify_email_code(conn, uid, code2, secret_key="s", now=NOW + timedelta(minutes=15))
    assert e.value.details == {"attempts_left": 0}
    # burn after 5 wrong attempts
    code3 = security.issue_email_code(conn, uid, "a@example.com", secret_key="s", now=NOW)
    assert conn.execute("SELECT COUNT(*) FROM email_codes WHERE user_id = ? AND used_at IS NULL", (uid,)).fetchone()[0] == 1  # older unused code dropped
    wrong3 = "000000" if code3 != "000000" else "111111"
    for left in (4, 3, 2, 1, 0):
        with pytest.raises(ApiError) as e:
            security.verify_email_code(conn, uid, wrong3, secret_key="s", now=NOW)
        assert e.value.details == {"attempts_left": left}
    with pytest.raises(ApiError) as e:
        security.verify_email_code(conn, uid, code3, secret_key="s", now=NOW)
    assert e.value.details == {"attempts_left": 0}


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
    assert dto == {"id": uid, "username": "张三", "display_name": "张三", "email": None, "email_verified": False, "role": "user", "onboarding_state": "pending", "created_at": "2026-10-14T00:00:00Z"}
    settings = security.settings_dto(conn, uid)
    assert settings["next_push_at"] == to_iso(compute_next_push(NOW, "Asia/Shanghai", "08:00")) == "2026-10-15T00:00:00Z"
    assert settings["stages"] == ["cet4", "cet6"] and settings["current_stage"] == "cet4" and settings["email_verified"] is False
    assert settings["push_enabled"] is True and settings["webhook_url"] is None and settings["updated_at"] == "2026-10-14T00:00:00Z"
    assert security.load_user_by_name(conn, "张三")["id"] == uid and security.load_user_by_name(conn, "nobody") is None
    assert security.username_taken(conn, "张三") and not security.username_taken(conn, "李四")
    with pytest.raises(ValueError):
        security.create_user(conn, username="x", password_hash="h", now=NOW, role="root")


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
    # non-interactive without a password source → exit 2
    monkeypatch.delenv("WD_ADMIN_PASSWORD", raising=False)
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


def test_cli_commands_are_registered(settings):
    parser = cli.build_parser()
    commands = set(parser._subparsers._group_actions[0].choices)  # type: ignore[union-attr]
    assert {"create-admin", "set-password", "promote", "demote", "invite"} <= commands
    assert os.path.isfile(security.COMMON_PASSWORDS_PATH)
