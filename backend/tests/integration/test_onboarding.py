"""Endpoints 12–13 and the DESIGN §4/§6.2 onboarding gate: pending → screen → done, next_push_at, stage mapping."""

from __future__ import annotations

from datetime import datetime, timezone

import pytest
from fastapi import APIRouter, Depends
from fastapi.testclient import TestClient

from wd import db, security
from wd.clock import compute_next_push, to_iso
from wd.deps import current_user, require_onboarded

PW = "Correct-Horse-7"
NOW = datetime(2026, 10, 14, 0, 0, 0, tzinfo=timezone.utc)
NOW_ISO = "2026-10-14T00:00:00Z"
STEP1 = {"stages": ["gk", "cet4"], "current_stage": "cet4", "timezone": "America/New_York", "push_time": "07:30"}


@pytest.fixture(autouse=True)
def fast_bcrypt(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr(security, "BCRYPT_ROUNDS", 4)


def register(client: TestClient, username: str = "alice"):
    r = client.post("/api/auth/register", json={"username": username, "password": PW})
    assert r.status_code == 201, r.text
    return r.json()


def error(r) -> dict:
    return r.json()["error"]


def settings_row(settings, user_id: int) -> dict:
    c = db.connect(settings.db_path)
    try:
        row = c.execute("SELECT * FROM user_settings WHERE user_id = ?", (user_id,)).fetchone()
        return {k: row[k] for k in row.keys()}
    finally:
        c.close()


def _all_paths(routes) -> set[str]:
    paths: set[str] = set()
    for r in routes:
        inner = getattr(r, "original_router", None)
        if inner is not None:
            paths |= _all_paths(inner.routes)
        p = getattr(r, "path", None)
        if p:
            paths.add(p)
    return paths


def ensure_gate_routes(app) -> None:
    """``/api/today`` (WP4) and ``/api/vocab`` / ``/api/bank`` (WP3) are other packages' routes.

    While they are absent, mount stand-ins wired exactly like the real ones (``require_onboarded`` for the ``O``
    endpoint, ``current_user`` for the ``U`` endpoints) *before* the SPA catch-all, so the gate itself is exercised
    end-to-end; once the real routers land the stand-ins are skipped and the same assertions run against them.
    """
    existing = _all_paths(app.router.routes)
    extra = APIRouter()
    if "/api/today" not in existing:

        @extra.get("/api/today")
        def today(user=Depends(require_onboarded)):
            return {"status": "none", "batch": None}

    if "/api/vocab" not in existing:

        @extra.get("/api/vocab")
        def vocab(user=Depends(current_user)):
            return {"items": [], "page": 1, "page_size": 50, "total": 0}

    if "/api/bank" not in existing:

        @extra.get("/api/bank")
        def bank(user=Depends(current_user)):
            return {"items": [], "page": 1, "page_size": 50, "total": 0}

    if extra.routes:
        app.include_router(extra)
        routes = app.router.routes
        included = routes.pop()  # appended after the SPA catch-all → move it in front of `/{path:path}`
        spa_index = next(i for i, r in enumerate(routes) if getattr(r, "path", None) == "/{path:path}")
        routes.insert(spa_index, included)


def test_fresh_user_has_next_push_at_from_defaults(client: TestClient, settings):
    alice = register(client)
    expected = to_iso(compute_next_push(NOW, "Asia/Shanghai", "08:00"))
    assert expected == "2026-10-15T00:00:00Z"
    assert alice["settings"]["next_push_at"] == expected
    row = settings_row(settings, alice["user"]["id"])
    assert row["next_push_at"] == expected and row["current_stage"] == 1 and row["stages_json"] == '["xs","zk"]'  # K-12 DDL defaults (0011 / bank.DEFAULT_*)


def test_complete_straight_after_registration_is_409(client: TestClient):
    register(client)
    r = client.post("/api/onboarding/complete")
    assert r.status_code == 409
    assert error(r)["code"] == "invalid_transition" and error(r)["details"]["from"] == "pending"
    assert client.get("/api/auth/me").json()["user"]["onboarding_state"] == "pending"


def test_step1_then_complete_is_idempotent(client: TestClient, settings):
    alice = register(client)
    r = client.post("/api/onboarding", json=STEP1)
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["onboarding_state"] == "screen" and set(body) == {"settings", "onboarding_state"}
    st = body["settings"]
    assert st["stages"] == ["gk", "cet4"] and st["current_stage"] == "cet4" and st["timezone"] == "America/New_York" and st["push_time"] == "07:30"
    expected = to_iso(compute_next_push(NOW, "America/New_York", "07:30"))
    assert st["next_push_at"] == expected == "2026-10-14T11:30:00Z" and st["updated_at"] == NOW_ISO
    row = settings_row(settings, alice["user"]["id"])
    assert row["current_stage"] == 4 and row["stages_json"] == '["gk","cet4"]' and row["next_push_at"] == expected  # 'cet4' stored as 4 (xs=1 … cet6=5)
    assert client.get("/api/auth/me").json()["user"]["onboarding_state"] == "screen"
    assert client.get("/api/settings").json()["current_stage"] == "cet4"  # read back as the Stage string
    r = client.post("/api/onboarding/complete")
    assert r.status_code == 200 and r.json() == {"onboarding_state": "done"}
    r = client.post("/api/onboarding/complete")
    assert r.status_code == 200 and r.json() == {"onboarding_state": "done"}
    assert client.get("/api/auth/me").json()["user"]["onboarding_state"] == "done"
    r = client.post("/api/onboarding", json=STEP1)  # step 1 is closed once done
    assert r.status_code == 409 and error(r)["code"] == "invalid_transition" and error(r)["details"]["from"] == "done"


def test_step1_can_be_reposted_until_done(client: TestClient, settings):
    alice = register(client)
    assert client.post("/api/onboarding", json=STEP1).status_code == 200
    r = client.post("/api/onboarding", json={"stages": ["zk"], "current_stage": "zk", "timezone": "Asia/Shanghai", "push_time": "21:00"})
    assert r.status_code == 200 and r.json()["onboarding_state"] == "screen"
    st = r.json()["settings"]
    assert st["stages"] == ["zk"] and st["current_stage"] == "zk" and st["next_push_at"] == "2026-10-14T13:00:00Z"
    assert settings_row(settings, alice["user"]["id"])["current_stage"] == 2  # 'zk' stored as 2


@pytest.mark.parametrize(
    "body,field",
    [
        ({**STEP1, "current_stage": "cet6"}, "current_stage"),  # not in stages
        ({**STEP1, "stages": []}, "stages"),
        ({**STEP1, "stages": ["cet5", "cet4"]}, "stages"),
        ({**STEP1, "timezone": "Mars/Olympus"}, "timezone"),
        ({**STEP1, "push_time": "25:00"}, "push_time"),
        ({**STEP1, "push_time": "8:00"}, "push_time"),
        ({k: v for k, v in STEP1.items() if k != "timezone"}, "timezone"),
        ({**STEP1, "extra": 1}, "extra"),
    ],
)
def test_step1_validation(client: TestClient, body, field):
    register(client)
    r = client.post("/api/onboarding", json=body)
    assert r.status_code == 400 and error(r)["code"] == "validation_error", r.text
    fields = error(r)["details"]["fields"]
    assert any(k == field or k.startswith(field + ".") for k in fields) or "body" in fields, fields  # list items → stages.0
    assert client.get("/api/auth/me").json()["user"]["onboarding_state"] == "pending"


def test_gate_blocks_today_but_not_browsing_until_complete(client: TestClient, app):
    ensure_gate_routes(app)
    r = client.get("/api/today")
    assert r.status_code == 401  # guest
    register(client)
    r = client.get("/api/today")
    assert r.status_code == 409 and error(r)["code"] == "onboarding_required" and error(r)["details"]["onboarding_state"] == "pending"
    assert client.get("/api/vocab").status_code == 200
    assert client.get("/api/bank").status_code == 200
    assert client.get("/api/settings").status_code == 200
    assert client.post("/api/onboarding", json=STEP1).status_code == 200
    r = client.get("/api/today")
    assert r.status_code == 409 and error(r)["details"]["onboarding_state"] == "screen"  # step 2 (筛词) is skippable but complete must be called
    assert client.post("/api/onboarding/complete").status_code == 200
    assert client.get("/api/today").status_code == 200
    assert client.get("/api/vocab").status_code == 200
