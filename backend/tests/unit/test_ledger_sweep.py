"""ledger.close_orphans — the service-start sweep that finishes ai_calls rows left `running` by an ungraceful stop, so their
reservation no longer counts against the daily cap and the svg / dance sub-caps (CLAUDE_INTEGRATION §7)."""

from __future__ import annotations

import pytest

from wd import db
from wd.ai import ledger

NOW = "2026-11-08T05:00:00Z"


def test_close_orphans_finishes_running_rows_and_frees_their_reservation(conn):
    with db.tx(conn):
        conn.execute("INSERT INTO ai_calls(kind, status, model_requested, max_budget_usd, reserved_usd) VALUES ('dance', 'running', 'sonnet', 0.25, 0.07)")
        conn.execute("INSERT INTO ai_calls(kind, status, model_requested, max_budget_usd, reserved_usd) VALUES ('content', 'running', 'sonnet', 0.25, 0.05)")
        conn.execute("INSERT INTO ai_calls(kind, status, model_requested, max_budget_usd, reserved_usd, cost_usd) VALUES ('svg', 'success', 'sonnet', 0.1, 0, 0.012)")
    assert ledger.reserved_running(conn, kind="dance") == pytest.approx(0.07) and ledger.reserved_running(conn) == pytest.approx(0.12)
    assert ledger.close_orphans(conn, now=NOW) == 2
    rows = [tuple(r) for r in conn.execute("SELECT kind, status, error, finished_at FROM ai_calls ORDER BY id")]
    assert rows[0] == ("dance", "error", "interrupted: process restart", NOW) and rows[1][1] == "error"
    assert rows[2] == ("svg", "success", None, None)  # finished rows untouched
    assert ledger.reserved_running(conn) == 0
    assert ledger.close_orphans(conn, now=NOW) == 0  # idempotent
