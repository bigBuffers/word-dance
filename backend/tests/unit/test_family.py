"""wd/family.py (slice 1-B): the 家长 PIN rules and hashing, the family-code HMAC, child login codes (issue / void / consume / collision
regeneration), claim codes (attempts, burn at 5, wrong target / user), the gate lockout cadence and gate_check paths, the two-factor
readiness matrix, children / child_dto, delete_user_rows and the hourly GC rule."""

from __future__ import annotations

import sqlite3
from datetime import datetime, timedelta, timezone

import pytest

from wd import db, family, security
from wd.clock import to_iso
from wd.deps import hash_token
from wd.errors import ApiError
from wd.jobs import queue

UTC = timezone.utc
NOW = datetime(2026, 10, 14, 0, 0, 0, tzinfo=UTC)
PHONE = "+8613800138000"
OTHER = "+8613900139000"
SECRET = "test-secret-key-not-for-production"


@pytest.fixture(autouse=True)
def fast_bcrypt(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr(security, "BCRYPT_ROUNDS", 4)


def make_user(conn: sqlite3.Connection, username: str = "alice", *, password: str | None = "Correct-Horse-7", **cols) -> int:
    pw_hash = security.hash_password(password) if password else security.unusable_password_hash()
    uid = security.create_user(conn, username=username, password_hash=pw_hash, now=NOW, password_set_at=to_iso(NOW) if password else None, **cols)
    return uid


def make_guardian(conn: sqlite3.Connection, username: str = "mum", *, phone: str | None = PHONE, password: str | None = "Correct-Horse-7", email_verified: bool = False, pin: str | None = None) -> int:
    uid = make_user(conn, username, password=password, account_kind="guardian", age_band="adult", age_declared_at=to_iso(NOW), email=f"{username}@example.com" if email_verified else None, email_verified_at=to_iso(NOW) if email_verified else None)
    if phone:
        conn.execute("INSERT INTO identities(user_id, provider, subject, verified_at, last_login_at) VALUES (?, 'phone', ?, ?, ?)", (uid, phone, to_iso(NOW), to_iso(NOW)))
    if pin:
        conn.execute("UPDATE users SET guardian_pin_hash = ? WHERE id = ?", (family.hash_pin(pin), uid))
    return uid


def make_child(conn: sqlite3.Connection, guardian_id: int, display_name: str = "小明", *, username: str | None = None, password: str | None = None) -> int:
    with db.tx(conn):
        return family.create_child(
            conn,
            guardian_id=guardian_id,
            display_name=display_name,
            username=username or security.placeholder_username(conn),
            password_hash=security.hash_password(password) if password else security.unusable_password_hash(),
            password_set_at=to_iso(NOW) if password else None,
            now=NOW,
            ip="1.2.3.4",
        )


def throttle(conn: sqlite3.Connection, key: str) -> dict | None:
    return db.row_to_dict(conn.execute("SELECT * FROM auth_throttle WHERE key = ?", (key,)).fetchone())


# ------------------------------------------------------------------------------------------- PIN
@pytest.mark.parametrize("pin", ["123456", "654321", "012345", "890123", "987654", "111111", "000000", "777777"])
def test_pin_problem_refuses_straights_and_repeats(pin):
    assert family.pin_problem(pin) == "PIN 不能是连号或重复数字"


@pytest.mark.parametrize("pin", ["12345", "1234567", "12345a", "", "１２３４５６", "12 3456"])
def test_pin_problem_refuses_anything_but_six_digits(pin):
    assert family.pin_problem(pin) == "家长 PIN 为 6 位数字"


@pytest.mark.parametrize("pin", ["135790", "112233", "121212", "246813", "908172", "100000", "123455"])
def test_pin_problem_accepts_ordinary_pins(pin):
    assert family.pin_problem(pin) is None and family.PIN_RE.match(pin)


def test_hash_and_verify_pin_with_the_dummy_path():
    h = family.hash_pin("135790")
    assert h.startswith("$2b$04$") and h != family.hash_pin("135790")  # salted
    assert family.verify_pin("135790", h) and not family.verify_pin("135791", h) and not family.verify_pin("", h)
    assert not family.verify_pin("135790", None)  # no PIN set: the dummy path, always False
    assert family.pin_problem("135790") is None


# ------------------------------------------------------------------------------------- family codes
def test_family_code_hash_shape():
    h = family.family_code_hash(SECRET, "12345678", "child_login", None)
    assert len(h) == 64 and int(h, 16) >= 0
    assert h == family.family_code_hash(SECRET, "12345678", "child_login", "")  # None and '' are the same message
    assert h != family.family_code_hash(SECRET, "12345679", "child_login", None)
    assert h != family.family_code_hash(SECRET, "12345678", "claim_guardian", None)
    assert h != family.family_code_hash(SECRET, "12345678", "child_login", PHONE)
    assert h != family.family_code_hash("another-secret", "12345678", "child_login", None)
    assert h != security.login_code_hash(SECRET, "12345678", "phone", "", "login")  # a login code can never be replayed as a child code


def test_issue_and_consume_child_code(conn: sqlite3.Connection, settings):
    mum = make_guardian(conn)
    kid = make_child(conn, mum)
    code = family.issue_child_code(conn, child_id=kid, ip="1.2.3.4", secret_key=SECRET, now=NOW)
    assert len(code) == 8 and code.isdigit()
    row = db.row_to_dict(conn.execute("SELECT * FROM family_codes").fetchone())
    assert (row["kind"], row["user_id"], row["target"], row["attempts"], row["used_at"], row["ip"], row["expires_at"]) == ("child_login", kid, None, 0, None, "1.2.3.4", "2026-10-14T00:10:00Z")
    assert row["code_hash"] == family.family_code_hash(SECRET, code, "child_login", None) and code not in str(row)
    assert not conn.in_transaction
    # a second code voids the first (one live code per child)
    code2 = family.issue_child_code(conn, child_id=kid, ip=None, secret_key=SECRET, now=NOW + timedelta(minutes=1))
    rows = [db.row_to_dict(r) for r in conn.execute("SELECT * FROM family_codes ORDER BY id")]
    assert rows[0]["used_at"] == "2026-10-14T00:01:00Z" and rows[1]["used_at"] is None and rows[1]["ip"] is None
    with db.tx(conn):
        assert family.consume_child_code(conn, code=code, secret_key=SECRET, now=NOW + timedelta(minutes=2)) is None  # voided
        got = family.consume_child_code(conn, code=f" {code2} ", secret_key=SECRET, now=NOW + timedelta(minutes=2))
        assert got is not None and got["user_id"] == kid and got["used_at"] == "2026-10-14T00:02:00Z"
        assert family.consume_child_code(conn, code=code2, secret_key=SECRET, now=NOW + timedelta(minutes=2)) is None  # single use
    assert conn.execute("SELECT used_at FROM family_codes WHERE id = 2").fetchone()[0] == "2026-10-14T00:02:00Z"
    # expiry: 10 minutes
    code3 = family.issue_child_code(conn, child_id=kid, ip=None, secret_key=SECRET, now=NOW)
    with db.tx(conn):
        assert family.consume_child_code(conn, code=code3, secret_key=SECRET, now=NOW + timedelta(seconds=600)) is None
        assert family.consume_child_code(conn, code="00000000", secret_key=SECRET, now=NOW) is None  # a miss changes nothing
    assert conn.execute("SELECT attempts, used_at FROM family_codes WHERE id = 3").fetchone()[:] == (0, None)


def test_child_code_is_regenerated_while_a_live_row_shares_its_hash(conn: sqlite3.Connection, monkeypatch: pytest.MonkeyPatch):
    mum = make_guardian(conn)
    kid1 = make_child(conn, mum, "一")
    kid2 = make_child(conn, mum, "二")
    draws = iter([12345678, 12345678, 87654321])
    monkeypatch.setattr(family.secrets, "randbelow", lambda n: next(draws))
    assert family.issue_child_code(conn, child_id=kid1, ip=None, secret_key=SECRET, now=NOW) == "12345678"
    assert family.issue_child_code(conn, child_id=kid2, ip=None, secret_key=SECRET, now=NOW) == "87654321"  # the duplicate draw was skipped
    hashes = [r[0] for r in conn.execute("SELECT code_hash FROM family_codes WHERE used_at IS NULL")]
    assert len(hashes) == 2 == len(set(hashes))
    monkeypatch.setattr(family.secrets, "randbelow", lambda n: 5)
    assert family.issue_child_code(conn, child_id=kid1, ip=None, secret_key=SECRET, now=NOW) == "00000005"  # zero-padded to 8 digits


def test_issue_and_verify_claim_code(conn: sqlite3.Connection):
    legacy = make_user(conn, "legacy")
    other = make_user(conn, "other")
    code = family.issue_claim_code(conn, user_id=legacy, target=PHONE, ip="1.2.3.4", secret_key=SECRET, now=NOW)
    assert len(code) == 6 and code.isdigit()
    row = db.row_to_dict(conn.execute("SELECT * FROM family_codes").fetchone())
    assert (row["kind"], row["user_id"], row["target"], row["expires_at"], row["ip"]) == ("claim_guardian", legacy, PHONE, "2026-10-14T00:10:00Z", "1.2.3.4")
    assert row["code_hash"] == family.family_code_hash(SECRET, code, "claim_guardian", PHONE) and code not in str(row)
    wrong = "000000" if code != "000000" else "000001"
    for left in (4, 3, 2):
        with pytest.raises(ApiError) as e:
            family.verify_claim_code(conn, user_id=legacy, target=PHONE, code=wrong, secret_key=SECRET, now=NOW)
        assert (e.value.code, e.value.status, e.value.details) == ("invalid_code", 400, {"attempts_left": left})
    assert not conn.in_transaction and conn.execute("SELECT attempts FROM family_codes WHERE id = 1").fetchone()[0] == 3
    # a wrong target or user finds no live row: attempts_left 0 and the real row is not touched
    for kwargs in ({"user_id": legacy, "target": OTHER}, {"user_id": other, "target": PHONE}):
        with pytest.raises(ApiError) as e:
            family.verify_claim_code(conn, code=code, secret_key=SECRET, now=NOW, **kwargs)
        assert e.value.details == {"attempts_left": 0}
    assert conn.execute("SELECT attempts FROM family_codes WHERE id = 1").fetchone()[0] == 3
    # the right code is only checked, not consumed
    assert family.verify_claim_code(conn, user_id=legacy, target=PHONE, code=f" {code} ", secret_key=SECRET, now=NOW) == 1
    assert conn.execute("SELECT used_at FROM family_codes WHERE id = 1").fetchone()[0] is None
    # two more wrong guesses burn it (5 in all): used_at set, even the right code is dead afterwards
    for left in (1, 0):
        with pytest.raises(ApiError) as e:
            family.verify_claim_code(conn, user_id=legacy, target=PHONE, code=wrong, secret_key=SECRET, now=NOW)
        assert e.value.details == {"attempts_left": left}
    assert conn.execute("SELECT attempts, used_at FROM family_codes WHERE id = 1").fetchone()[:] == (5, to_iso(NOW))
    with pytest.raises(ApiError) as e:
        family.verify_claim_code(conn, user_id=legacy, target=PHONE, code=code, secret_key=SECRET, now=NOW)
    assert e.value.details == {"attempts_left": 0}
    # a new code voids the older unused rows of (user, target); expiry; consumption inside the caller's transaction
    code2 = family.issue_claim_code(conn, user_id=legacy, target=PHONE, ip=None, secret_key=SECRET, now=NOW)
    code3 = family.issue_claim_code(conn, user_id=legacy, target=PHONE, ip=None, secret_key=SECRET, now=NOW + timedelta(minutes=1))
    assert conn.execute("SELECT used_at FROM family_codes WHERE id = 2").fetchone()[0] == "2026-10-14T00:01:00Z"
    with pytest.raises(ApiError):
        family.verify_claim_code(conn, user_id=legacy, target=PHONE, code=code2, secret_key=SECRET, now=NOW + timedelta(minutes=1))
    with pytest.raises(ApiError) as e:
        family.verify_claim_code(conn, user_id=legacy, target=PHONE, code=code3, secret_key=SECRET, now=NOW + timedelta(minutes=11))
    assert e.value.details == {"attempts_left": 0}  # expired
    row_id = family.verify_claim_code(conn, user_id=legacy, target=PHONE, code=code3, secret_key=SECRET, now=NOW + timedelta(minutes=5))
    with db.tx(conn):
        assert family.mark_family_code_used(conn, row_id, NOW + timedelta(minutes=5)) is True
        assert family.mark_family_code_used(conn, row_id, NOW + timedelta(minutes=5)) is False  # a concurrent request won
    # void by kind + user (the failed-send hook of endpoint 108); an unknown kind is a programming error
    code4 = family.issue_claim_code(conn, user_id=legacy, target=OTHER, ip=None, secret_key=SECRET, now=NOW)
    family.issue_child_code(conn, child_id=legacy, ip=None, secret_key=SECRET, now=NOW)  # a child code of the same user is another kind
    assert family.void_family_codes(conn, kind="claim_guardian", user_id=legacy, now=NOW + timedelta(minutes=6)) == 1
    assert conn.execute("SELECT COUNT(*) FROM family_codes WHERE kind = 'child_login' AND used_at IS NULL").fetchone()[0] == 1
    with pytest.raises(ApiError):
        family.verify_claim_code(conn, user_id=legacy, target=OTHER, code=code4, secret_key=SECRET, now=NOW + timedelta(minutes=6))
    with pytest.raises(ValueError):
        family.void_family_codes(conn, kind="join", user_id=legacy, now=NOW)


def test_gc_family_codes_follows_the_login_codes_rule(conn: sqlite3.Connection):
    uid = make_user(conn)
    conn.executemany(
        "INSERT INTO family_codes(id, kind, user_id, target, code_hash, expires_at, used_at) VALUES (?, ?, ?, ?, 'h', ?, ?)",
        [
            (1, "child_login", uid, None, "2026-10-14T00:59:00Z", None),  # expired, unused → gone
            (2, "child_login", uid, None, "2026-10-14T01:10:00Z", None),  # live → kept
            (3, "claim_guardian", uid, PHONE, "2026-10-13T00:10:00Z", "2026-10-13T00:05:00Z"),  # used yesterday → gone
            (4, "claim_guardian", uid, PHONE, "2026-10-14T01:10:00Z", "2026-10-13T00:55:00Z"),  # used more than a day ago, unexpired → gone
            (5, "child_login", uid, None, "2026-10-14T00:40:00Z", "2026-10-14T00:30:00Z"),  # used half an hour ago and expired since → kept a day (audit)
            (6, "claim_guardian", uid, PHONE, "2026-10-14T01:10:00Z", "2026-10-14T00:00:00Z"),  # used an hour ago → kept
        ],
    )
    assert family.gc_family_codes(conn, datetime(2026, 10, 14, 1, 0, tzinfo=UTC)) == 3
    assert [r[0] for r in conn.execute("SELECT id FROM family_codes ORDER BY id")] == [2, 5, 6]
    assert not conn.in_transaction


# -------------------------------------------------------------------------------------- the 家长门
def test_gate_lockout_follows_the_login_cadence(conn: sqlite3.Connection):
    mum = make_guardian(conn)
    key = f"gate:user:{mum}"
    assert family.gate_locked(conn, mum, NOW) is None
    for _ in range(9):
        assert family.gate_failure(conn, mum, NOW) is None
    assert family.gate_locked(conn, mum, NOW) is None and throttle(conn, key)["count"] == 9
    assert family.gate_failure(conn, mum, NOW) == 900  # the 10th failure locks 15 minutes
    assert family.gate_locked(conn, mum, NOW) == 900 and family.gate_locked(conn, mum, NOW + timedelta(seconds=899)) == 1
    assert family.gate_locked(conn, mum, NOW + timedelta(seconds=900)) is None
    for _ in range(4):
        assert family.gate_failure(conn, mum, NOW + timedelta(seconds=901)) is None
    assert family.gate_failure(conn, mum, NOW + timedelta(seconds=901)) == 1800  # the 15th doubles
    assert throttle(conn, key)["count"] == 15 and throttle(conn, key)["blocked_until"] == to_iso(NOW + timedelta(seconds=901 + 1800))
    family.gate_cleared(conn, mum)
    assert throttle(conn, key) is None and family.gate_locked(conn, mum, NOW) is None and not conn.in_transaction
    # a streak older than 24 h (and not locked) starts over
    assert family.gate_failure(conn, mum, NOW) is None and throttle(conn, key)["count"] == 1
    assert family.gate_failure(conn, mum, NOW + timedelta(hours=25)) is None and throttle(conn, key)["count"] == 1
    # the cap: 24 h
    assert security.lock_seconds_for(10 + 5 * 10) == 24 * 3600


def test_gate_check_paths(conn: sqlite3.Connection, settings):
    mum = make_guardian(conn, pin="135790")
    guardian = security.load_user(conn, mum)
    key = f"gate:user:{mum}"
    kw = dict(now=NOW, cfg=settings, ip="1.2.3.4")
    # PIN
    with pytest.raises(ApiError) as e:
        family.gate_check(conn, guardian, pin="135791", password=None, code=None, **kw)
    assert (e.value.code, e.value.status) == ("invalid_pin", 401) and throttle(conn, key)["count"] == 1
    assert family.gate_check(conn, guardian, pin="135790", password=None, code=None, **kw) is None and throttle(conn, key) is None  # cleared
    # password (its own pwcheck budget; a wrong one counts on the gate too)
    with pytest.raises(ApiError) as e:
        family.gate_check(conn, guardian, pin=None, password="wrong-password-1", code=None, **kw)
    assert (e.value.code, e.value.status) == ("invalid_credentials", 401) and throttle(conn, key)["count"] == 1
    assert family.gate_check(conn, guardian, pin=None, password="Correct-Horse-7", code=None, **kw) is None and throttle(conn, key) is None
    # code: the newest live reauth code of the guardian whatever its channel; returned for the caller to consume
    reauth = security.issue_login_code(conn, channel="phone", target=PHONE, purpose="reauth", user_id=mum, ip=None, secret_key=settings.secret_key, now=NOW)
    wrong = "000000" if reauth != "000000" else "000001"
    with pytest.raises(ApiError) as e:
        family.gate_check(conn, guardian, pin=None, password=None, code=wrong, **kw)
    assert (e.value.code, e.value.details) == ("invalid_code", {"attempts_left": 4}) and throttle(conn, key)["count"] == 1
    row_id = family.gate_check(conn, guardian, pin=None, password=None, code=reauth, **kw)
    assert row_id is not None and conn.execute("SELECT used_at FROM login_codes WHERE id = ?", (row_id,)).fetchone()[0] is None  # not consumed here
    assert throttle(conn, key) is None
    # exactly one factor
    for factors in ({}, {"pin": "135790", "password": "Correct-Horse-7"}):
        with pytest.raises(ApiError) as e:
            family.gate_check(conn, guardian, **{"pin": None, "password": None, "code": None, **factors}, **kw)
        assert e.value.code == "validation_error" and e.value.details == {"fields": {"body": "PIN、密码和验证码必须且只能提供一个"}}
    # no password on the account → a field error, not a counted failure
    dad = make_guardian(conn, "dad", phone=OTHER, password=None, email_verified=True)
    with pytest.raises(ApiError) as e:
        family.gate_check(conn, security.load_user(conn, dad), pin=None, password="Correct-Horse-7", code=None, **kw)
    assert e.value.code == "validation_error" and e.value.details == {"fields": {"password": "账号没有密码，请用 PIN 或验证码"}} and throttle(conn, f"gate:user:{dad}") is None
    # no PIN set: the dummy path fails and counts
    with pytest.raises(ApiError) as e:
        family.gate_check(conn, security.load_user(conn, dad), pin="135790", password=None, code=None, **kw)
    assert e.value.code == "invalid_pin" and throttle(conn, f"gate:user:{dad}")["count"] == 1
    # locked: checked first, whatever the factor
    for _ in range(9):
        family.gate_failure(conn, mum, NOW)
    assert family.gate_failure(conn, mum, NOW) == 900
    with pytest.raises(ApiError) as e:
        family.gate_check(conn, guardian, pin="135790", password=None, code=None, **kw)
    assert (e.value.code, e.value.status, e.value.details) == ("account_locked", 423, {"retry_after_s": 900})
    assert family.gate_check(conn, guardian, pin="135790", password=None, code=None, now=NOW + timedelta(seconds=900), cfg=settings) is None
    assert not conn.in_transaction


def test_stamp_gate_and_gate_until(conn: sqlite3.Connection, settings):
    mum = make_guardian(conn)
    token = security.create_session(conn, mum, NOW, session_days=30)
    family.stamp_gate(conn, hash_token(token), NOW)
    assert conn.execute("SELECT guardian_gate_at FROM sessions").fetchone()[0] == to_iso(NOW)
    user = {"id": mum, "account_kind": "guardian", "session_gate_at": to_iso(NOW), "session_actor_user_id": None}
    assert family.gate_until(user, NOW) == "2026-10-14T00:10:00Z"
    assert family.gate_until(user, NOW + timedelta(seconds=599)) == "2026-10-14T00:10:00Z"
    assert family.gate_until(user, NOW + timedelta(seconds=600)) is None  # 10 minutes, not a second more
    assert family.gate_until({**user, "session_gate_at": None}, NOW) is None
    assert family.gate_until({**user, "account_kind": "learner"}, NOW) is None
    assert family.gate_until({**user, "session_actor_user_id": 7}, NOW) is None  # a switched child session is never gated


# ------------------------------------------------------------------------------------------ readiness
@pytest.mark.parametrize(
    "phone,password,email,ready,missing",
    [
        (PHONE, "Correct-Horse-7", False, True, []),
        (PHONE, None, True, True, []),
        (PHONE, "Correct-Horse-7", True, True, []),
        (PHONE, None, False, False, ["second_factor"]),
        (None, "Correct-Horse-7", False, False, ["phone"]),
        (None, None, True, False, ["phone"]),
        (None, None, False, False, ["phone", "second_factor"]),
    ],
)
def test_guardian_ready_matrix(conn: sqlite3.Connection, phone, password, email, ready, missing):
    uid = make_guardian(conn, phone=phone, password=password, email_verified=email)
    user = security.load_user(conn, uid)
    state = family.guardian_ready(conn, user)
    assert (state["ready"], state["missing"], state["phone"], state["second_factor"]) == (ready, missing, phone is not None, password is not None or email)
    if ready:
        family.require_ready(conn, user)
    else:
        with pytest.raises(ApiError) as e:
            family.require_ready(conn, user)
        assert (e.value.code, e.value.status, e.value.details) == ("guardian_factors_required", 409, {"missing": missing})


def test_predicates():
    assert family.is_child({"guardian_user_id": 3}) and not family.is_child({"guardian_user_id": None}) and not family.is_child({})
    assert family.is_guardian({"account_kind": "guardian"}) and not family.is_guardian({"account_kind": "learner"}) and not family.is_guardian({})
    assert (family.CHILD_SESSION_DAYS, family.GATE_TTL_S, family.MAX_CHILDREN, family.CHILD_CODE_LEN, family.FAMILY_CODE_TTL_S, family.FAMILY_CODE_MAX_ATTEMPTS) == (90, 600, 10, 8, 600, 5)
    assert (family.CHILD_CODE_ISSUE_LIMIT, family.CHILD_CODE_ISSUE_WINDOW_S, family.CHILD_LOGIN_IP_LIMIT, family.CHILD_LOGIN_IP_WINDOW_S, family.PROFILE_PROMPT_SNOOZE_DAYS) == (5, 3600, 10, 3600, 30)


# ------------------------------------------------------------------------------------------- children
def test_children_child_of_and_child_dto(conn: sqlite3.Connection, seeded):
    mum = make_guardian(conn)
    dad = make_guardian(conn, "dad", phone=OTHER)
    kid1 = make_child(conn, mum, "小明")
    conn.execute("UPDATE users SET created_at = '2026-10-13T00:00:00Z' WHERE id = ?", (kid1,))  # older than the second one
    kid2 = make_child(conn, mum, "小红", username="xiaohong", password="Kid-Pass-Word-9")
    other = make_child(conn, dad, "别人家的")
    assert [c["id"] for c in family.children_of(conn, mum)] == [kid1, kid2] and [c["id"] for c in family.children_of(conn, dad)] == [other]
    row = family.child_of(conn, mum, kid1)
    assert (row["guardian_user_id"], row["age_band"], row["account_kind"], row["guardian_consent_at"], row["age_declared_ip"], row["onboarding_state"]) == (mum, "u14", "learner", to_iso(NOW), "1.2.3.4", "pending")
    for guardian_id, child_id in ((mum, other), (dad, kid1), (mum, mum), (mum, 999)):
        with pytest.raises(ApiError) as e:
            family.child_of(conn, guardian_id, child_id)
        assert (e.value.code, e.value.status) == ("not_found", 404)
    # the DTO: placeholder → username None; sessions = live rows whatever actor_user_id; the admin figures
    token_live = security.create_session(conn, kid1, NOW, session_days=90)
    security.create_session(conn, kid1, NOW, session_days=30, actor_user_id=mum)
    conn.execute("INSERT INTO sessions(token_hash, user_id, created_at, expires_at, last_seen_at) VALUES ('dead', ?, ?, ?, ?)", (kid1, to_iso(NOW - timedelta(days=40)), to_iso(NOW - timedelta(days=10)), to_iso(NOW - timedelta(days=40))))
    (word_id,) = conn.execute("SELECT id FROM words ORDER BY id LIMIT 1").fetchone()
    conn.execute("INSERT INTO user_words(user_id, word_id, state, origin) VALUES (?, ?, 'learning', 'browse')", (kid1, word_id))
    conn.execute("INSERT INTO daily_stats(user_id, local_date, graded) VALUES (?, '2026-10-14', 3), (?, '2026-10-13', 1)", (kid1, kid1))
    conn.execute("UPDATE users SET last_login_at = ? WHERE id = ?", (to_iso(NOW), kid1))
    dto = family.child_dto(conn, family.child_of(conn, mum, kid1), now=NOW + timedelta(hours=1))
    assert dto == {
        "id": kid1,
        "display_name": "小明",
        "username": None,
        "has_password": False,
        "phone_masked": None,
        "age_band": "u14",
        "onboarding_state": "pending",
        "created_at": "2026-10-13T00:00:00Z",
        "last_login_at": to_iso(NOW),
        "bank_size": 1,
        "streak_days": 2,
        "sessions": 2,
    }
    assert hash_token(token_live)  # the live rows counted above
    conn.execute("INSERT INTO identities(user_id, provider, subject, verified_at) VALUES (?, 'phone', ?, ?)", (kid2, "+8613700137000", to_iso(NOW)))
    dto2 = family.child_dto(conn, family.child_of(conn, mum, kid2), now=NOW)
    assert (dto2["username"], dto2["has_password"], dto2["phone_masked"], dto2["sessions"], dto2["bank_size"], dto2["streak_days"], dto2["last_login_at"]) == ("xiaohong", True, "137****7000", 0, 0, 0, None)
    from wd import schemas

    schemas.ChildAccount.model_validate(dto)
    schemas.ChildAccount.model_validate(dto2)


def test_delete_user_rows_cascades_and_applies_the_private_word_rule(conn: sqlite3.Connection, seeded):
    mum = make_guardian(conn)
    kid = make_child(conn, mum)
    other = make_user(conn, "other")
    ids = [r[0] for r in conn.execute("SELECT id FROM words ORDER BY id LIMIT 3")]
    mine_only, shared, public = ids
    conn.execute("UPDATE words SET is_public = 0, created_by_user_id = ? WHERE id IN (?, ?)", (kid, mine_only, shared))
    conn.executemany("INSERT INTO user_words(user_id, word_id, state, origin) VALUES (?, ?, 'new', 'browse')", [(kid, mine_only), (kid, shared), (other, shared), (kid, public)])
    job = queue.enqueue(conn, "send_webhook", {"x": 1}, dedupe_key=f"content:{mine_only}", now=to_iso(NOW))
    job_kept = queue.enqueue(conn, "send_webhook", {"x": 2}, dedupe_key=f"content:{shared}", now=to_iso(NOW))
    security.create_session(conn, kid, NOW, session_days=30, actor_user_id=mum)
    family.issue_child_code(conn, child_id=kid, ip=None, secret_key=SECRET, now=NOW)
    conn.execute("INSERT INTO identities(user_id, provider, subject) VALUES (?, 'phone', ?)", (kid, OTHER))
    with db.tx(conn):
        assert family.delete_user_rows(conn, kid, to_iso(NOW)) == 1
    assert conn.execute("SELECT COUNT(*) FROM users WHERE id = ?", (kid,)).fetchone()[0] == 0
    for table in ("sessions", "family_codes", "identities", "user_settings", "user_words"):
        assert conn.execute(f"SELECT COUNT(*) FROM {table} WHERE user_id = ?", (kid,)).fetchone()[0] == 0, table
    assert conn.execute("SELECT COUNT(*) FROM words WHERE id = ?", (mine_only,)).fetchone()[0] == 0  # orphaned private word gone
    assert conn.execute("SELECT COUNT(*) FROM words WHERE id IN (?, ?)", (shared, public)).fetchone()[0] == 2  # referenced / public words stay
    assert conn.execute("SELECT status, finished_at FROM jobs WHERE id = ?", (job,)).fetchone()[:] == ("cancelled", to_iso(NOW))
    assert conn.execute("SELECT status FROM jobs WHERE id = ?", (job_kept,)).fetchone()[0] == "queued"
    assert conn.execute("SELECT COUNT(*) FROM users WHERE id = ?", (mum,)).fetchone()[0] == 1
    # a guardian with a child attached cannot be deleted (ON DELETE RESTRICT): the caller frees or deletes the children first
    make_child(conn, mum, "二")
    with pytest.raises(sqlite3.IntegrityError):
        with db.tx(conn):
            family.delete_user_rows(conn, mum, to_iso(NOW))
    assert conn.execute("SELECT COUNT(*) FROM users WHERE id = ?", (mum,)).fetchone()[0] == 1
