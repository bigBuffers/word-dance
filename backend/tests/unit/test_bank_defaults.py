"""services/bank.py defaults (PLAN §0 / SM D-4, D-13 ③, D-16): the K-12 defaults a settings row that does not exist yet gets
are the user_settings DDL defaults (0011_primary_stage.sql) — bound here so the two sources cannot drift —, the
stage_fallback warning when a stored stages_json names no known code, and current_stage_index's `is None` rule."""

from __future__ import annotations

import json
import logging

from wd.schemas import STAGE_ORDER, stage_to_index
from wd.services import bank, words


def make_user(conn, username: str = "alice", **cols) -> int:
    uid = int(conn.execute("INSERT INTO users(username, password_hash) VALUES (?, 'x')", (username,)).lastrowid)
    if cols:
        names = ["user_id", *cols]
        conn.execute(f"INSERT INTO user_settings({', '.join(names)}) VALUES ({', '.join('?' * len(names))})", (uid, *cols.values()))
    return uid


def test_defaults_mirror_user_settings_ddl(conn):
    cols = {r["name"]: r["dflt_value"] for r in conn.execute("PRAGMA table_info(user_settings)")}
    assert json.loads(cols["stages_json"].strip("'")) == list(bank.DEFAULT_STAGES) == ["xs", "zk"]
    assert int(cols["current_stage"]) == bank.DEFAULT_CURRENT_STAGE == stage_to_index("xs") == 1
    assert bank.DEFAULT_CURRENT_STAGE in {stage_to_index(s) for s in bank.DEFAULT_STAGES}  # current_stage ∈ stages (schemas validator)
    assert set(bank.DEFAULT_STAGES) <= set(STAGE_ORDER) and words.STAGES == STAGE_ORDER
    # a row inserted with the DDL defaults reads back exactly as the Python defaults describe it
    uid = make_user(conn, "fresh", next_push_at="2026-10-15T00:00:00Z")
    row = bank.user_settings_row(conn, uid)
    assert row["stages"] == list(bank.DEFAULT_STAGES) and row["current_stage"] == bank.DEFAULT_CURRENT_STAGE
    assert json.loads(row["stages_json"]) == list(bank.DEFAULT_STAGES)


def test_missing_row_gets_the_python_defaults(conn):
    uid = make_user(conn, "norow")
    row = bank.user_settings_row(conn, uid)
    assert row["stages"] == ["xs", "zk"] and row["current_stage"] == 1 and row["timezone"] == bank.DEFAULT_TIMEZONE
    assert bank.current_stage_index(row) == stage_to_index("xs")


def test_unknown_stage_codes_fall_back_with_a_warning(conn, caplog):
    caplog.set_level(logging.WARNING, logger="wd.bank")
    uid = make_user(conn, "legacy", stages_json='["cet9"]', current_stage=4, next_push_at="2026-10-15T00:00:00Z")
    row = bank.user_settings_row(conn, uid)
    assert row["stages"] == list(bank.DEFAULT_STAGES) and row["current_stage"] == 4  # the stored 主攻阶段 is kept as is
    fallbacks = [r for r in caplog.records if getattr(r, "event", None) == "stage_fallback"]
    assert len(fallbacks) == 1 and fallbacks[0].user_id == uid and "cet9" in fallbacks[0].getMessage()
    caplog.clear()
    uid2 = make_user(conn, "mixed", stages_json='["cet9", "gk"]', current_stage=3, next_push_at="2026-10-15T00:00:00Z")
    assert bank.user_settings_row(conn, uid2)["stages"] == ["gk"]  # unknown codes are dropped, known ones kept — no fallback
    assert [r for r in caplog.records if getattr(r, "event", None) == "stage_fallback"] == []
    uid3 = make_user(conn, "broken", stages_json="not json", current_stage=2, next_push_at="2026-10-15T00:00:00Z")
    assert bank.user_settings_row(conn, uid3)["stages"] == list(bank.DEFAULT_STAGES)
    assert len([r for r in caplog.records if getattr(r, "event", None) == "stage_fallback"]) == 1


def test_current_stage_index_uses_is_none_not_falsiness():
    assert bank.current_stage_index({"current_stage": None}) == bank.DEFAULT_CURRENT_STAGE
    assert bank.current_stage_index({}) == bank.DEFAULT_CURRENT_STAGE
    assert bank.current_stage_index({"current_stage": 5}) == 5 and bank.current_stage_index({"current_stage": "3"}) == 3
    assert bank.current_stage_index({"current_stage": 0}) == 0  # a falsy stored value is returned, never replaced by the default (SM D-16)
