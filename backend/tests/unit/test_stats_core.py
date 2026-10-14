"""stats_core.on_action — every row of the DESIGN §7.1 delta table, the restore reversals and the never-below-0 rule."""

from __future__ import annotations

import pytest

from wd.services import stats_core
from wd.services.stats_core import COLUMNS, deltas_for, on_action

USER = 1
DAY = "2026-10-14"


def expect(**kw: int) -> dict[str, int]:
    d = dict.fromkeys(COLUMNS, 0)
    d.update(kw)
    return d


def row(conn, user_id: int = USER, day: str = DAY) -> dict[str, int] | None:
    r = conn.execute("SELECT * FROM daily_stats WHERE user_id=? AND local_date=?", (user_id, day)).fetchone()
    return None if r is None else {k: r[k] for k in COLUMNS}


def make_user(conn, user_id: int = USER) -> None:
    conn.execute("INSERT INTO users(id, username, password_hash) VALUES (?, ?, 'x')", (user_id, f"u{user_id}"))


# (description, kwargs, expected deltas) — the §7.1 table
TABLE = [
    ("good on a review card", dict(action="good", context="today", new_state="learning", item_kind="review", elapsed_ms=4000), expect(graded=1, good=1, study_ms=4000)),
    ("again on a new card (intermediate)", dict(action="again", context="today", new_state="learning", item_kind="new", elapsed_ms=2500), expect(graded=1, again=1, study_ms=2500)),
    ("hard on an extra card", dict(action="hard", context="extra", new_state="learning", item_kind="extra", elapsed_ms=None), expect(graded=1, hard=1)),
    ("study_ms is capped at 60 s", dict(action="good", context="today", new_state="learning", item_kind="new", elapsed_ms=600_000), expect(graded=1, good=1, study_ms=60_000)),
    ("master as a card grade", dict(action="master", context="today", new_state="mastered", item_kind="new", elapsed_ms=3000), expect(graded=1, mastered=1, study_ms=3000)),
    ("master from the detail page", dict(action="master", context="detail", new_state="mastered", item_kind=None, elapsed_ms=None), expect(mastered=1)),
    ("known as bank synonym (new_state mastered)", dict(action="known", context="bank", new_state="mastered", item_kind=None, elapsed_ms=None), expect(mastered=1)),
    ("known from browse", dict(action="known", context="browse", new_state="known", item_kind=None, elapsed_ms=None), expect(known=1)),
    ("known verdict on the screen page", dict(action="known", context="screen_page", new_state="known", item_kind=None, elapsed_ms=None), expect(known=1, screened=1)),
    ("known verdict during onboarding", dict(action="known", context="onboarding", new_state="known", item_kind=None, elapsed_ms=None), expect(known=1, screened=1)),
    ("known verdict on an in-batch 推荐词", dict(action="known", context="today", new_state="known", item_kind="screen", elapsed_ms=None), expect(known=1, screened=1)),
    ("unfamiliar from ∅ on browse", dict(action="unfamiliar", context="browse", new_state="new", item_kind=None, elapsed_ms=None, prev_state=None), expect(added=1)),
    ("unfamiliar from ∅ on the screen page", dict(action="unfamiliar", context="screen_page", new_state="new", item_kind=None, elapsed_ms=None, prev_state=None), expect(added=1, screened=1)),
    ("unfamiliar from ∅ on an in-batch 推荐词", dict(action="unfamiliar", context="today", new_state="new", item_kind="screen", elapsed_ms=None, prev_state=None), expect(added=1, screened=1)),
    ("idempotent unfamiliar (status exists)", dict(action="unfamiliar", context="bank", new_state="learning", item_kind=None, elapsed_ms=None, prev_state="learning"), expect()),
    ("readd", dict(action="readd", context="bank", new_state="new", item_kind=None, elapsed_ms=None, prev_state="mastered"), expect(added=1)),
    ("add_custom", dict(action="add_custom", context="api", new_state="new", item_kind=None, elapsed_ms=None), expect(added=1)),
    ("import", dict(action="import", context="api", new_state="learning", item_kind=None, elapsed_ms=None), expect(added=1)),
    ("skip", dict(action="skip", context="today", new_state="new", item_kind="new", elapsed_ms=1000), expect()),
    ("remove", dict(action="remove", context="bank", new_state="removed", item_kind=None, elapsed_ms=None), expect()),
    ("reset", dict(action="reset", context="bank", new_state="new", item_kind=None, elapsed_ms=None), expect()),
    ("consolidate", dict(action="consolidate", context="consolidate", new_state="learning", item_kind=None, elapsed_ms=None), expect()),
    ("note", dict(action="note", context="bank", new_state="new", item_kind=None, elapsed_ms=None), expect()),
    ("attention", dict(action="attention", context="bank", new_state="new", item_kind=None, elapsed_ms=None), expect()),
]


@pytest.mark.parametrize("desc,kwargs,expected", TABLE, ids=[t[0] for t in TABLE])
def test_delta_table(conn, desc, kwargs, expected):
    make_user(conn)
    applied = on_action(conn, USER, DAY, **kwargs)
    assert applied == expected
    if any(expected.values()):
        assert row(conn) == expected
    else:
        assert row(conn) is None  # no-op actions create no row


RESTORE = [
    (
        "restore of a card master grade",
        dict(action="master", context="today", new_state="mastered", item_kind="new", elapsed_ms=3000),
        dict(action="master", context="today", new_state="mastered", prev_state="new", item_kind="new"),
        expect(study_ms=3000),  # graded−1, mastered−1; study_ms is not reversed
    ),
    (
        "restore of a page master",
        dict(action="master", context="detail", new_state="mastered", item_kind=None, elapsed_ms=None),
        dict(action="master", context="detail", new_state="mastered", prev_state="learning", item_kind=None),
        expect(),
    ),
    (
        "restore of a bank-synonym known",
        dict(action="known", context="bank", new_state="mastered", item_kind=None, elapsed_ms=None),
        dict(action="known", context="bank", new_state="mastered", prev_state="new", item_kind=None),
        expect(),
    ),
    (
        "restore of a screen-page known",
        dict(action="known", context="screen_page", new_state="known", item_kind=None, elapsed_ms=None),
        dict(action="known", context="screen_page", new_state="known", prev_state=None, item_kind=None),
        expect(),
    ),
    (
        "restore of an in-batch 推荐词 known",
        dict(action="known", context="today", new_state="known", item_kind="screen", elapsed_ms=None),
        dict(action="known", context="today", new_state="known", prev_state=None, item_kind="screen"),
        expect(),
    ),
    (
        "restore of a ∅→new unfamiliar on the screen page",
        dict(action="unfamiliar", context="screen_page", new_state="new", item_kind=None, elapsed_ms=None, prev_state=None),
        dict(action="unfamiliar", context="screen_page", new_state="new", prev_state=None, item_kind=None),
        expect(),
    ),
    (
        "restore of a ∅→new unfamiliar from 词库",
        dict(action="unfamiliar", context="browse", new_state="new", item_kind=None, elapsed_ms=None, prev_state=None),
        dict(action="unfamiliar", context="browse", new_state="new", prev_state=None, item_kind=None),
        expect(),
    ),
]


@pytest.mark.parametrize("desc,forward,undone,after", RESTORE, ids=[t[0] for t in RESTORE])
def test_restore_reverses_exactly(conn, desc, forward, undone, after):
    make_user(conn)
    on_action(conn, USER, DAY, **forward)
    on_action(conn, USER, DAY, action="restore", context="today", new_state=None, item_kind=None, elapsed_ms=None, undone=undone)
    assert row(conn) == after


def test_restore_deltas_are_pure_negations():
    forward = deltas_for(action="master", context="today", new_state="mastered", item_kind="review", elapsed_ms=None)
    back = deltas_for(action="restore", context="today", new_state=None, item_kind=None, elapsed_ms=None, undone={"action": "master", "context": "today", "new_state": "mastered", "prev_state": "learning", "item_kind": "review"})
    assert back == {k: -v for k, v in forward.items()}
    forward = deltas_for(action="unfamiliar", context="onboarding", new_state="new", item_kind=None, elapsed_ms=None, prev_state=None)
    back = deltas_for(action="restore", context="onboarding", new_state=None, item_kind=None, elapsed_ms=None, undone={"action": "unfamiliar", "context": "onboarding", "new_state": "new", "prev_state": None})
    assert back == {k: -v for k, v in forward.items()}


def test_restore_of_non_undoable_rows_changes_nothing():
    for undone in (
        {"action": "readd", "context": "bank", "new_state": "new", "prev_state": "mastered"},
        {"action": "unfamiliar", "context": "bank", "new_state": "learning", "prev_state": "learning"},  # idempotent unfamiliar
        {"action": "good", "context": "today", "new_state": "learning", "prev_state": "new", "item_kind": "new"},
        {},
    ):
        assert deltas_for(action="restore", context="today", new_state=None, item_kind=None, elapsed_ms=None, undone=undone) == expect()


def test_never_below_zero_on_a_day_without_rows(conn):
    make_user(conn)
    on_action(conn, USER, DAY, action="restore", context="today", new_state=None, item_kind=None, elapsed_ms=None, undone={"action": "master", "context": "today", "new_state": "mastered", "prev_state": "learning", "item_kind": "new"})
    assert row(conn) == expect()  # a row exists (the upsert ran) but nothing went negative
    on_action(conn, USER, DAY, action="restore", context="screen_page", new_state=None, item_kind=None, elapsed_ms=None, undone={"action": "unfamiliar", "context": "screen_page", "new_state": "new", "prev_state": None})
    assert row(conn) == expect()


def test_accumulates_across_calls_and_days(conn):
    make_user(conn)
    for _ in range(3):
        on_action(conn, USER, DAY, action="good", context="today", new_state="learning", item_kind="review", elapsed_ms=10_000)
    on_action(conn, USER, DAY, action="again", context="today", new_state="learning", item_kind="new", elapsed_ms=70_000)
    on_action(conn, USER, "2026-10-15", action="good", context="today", new_state="learning", item_kind="review", elapsed_ms=1)
    assert row(conn) == expect(graded=4, good=3, again=1, study_ms=90_000)
    assert row(conn, day="2026-10-15") == expect(graded=1, good=1, study_ms=1)
    assert conn.execute("SELECT COUNT(*) FROM daily_stats").fetchone()[0] == 2


def test_joins_an_open_transaction(conn):
    make_user(conn)
    from wd import db

    with db.tx(conn):
        on_action(conn, USER, DAY, action="add_custom", context="api", new_state="new", item_kind=None, elapsed_ms=None)
        assert conn.in_transaction
    assert row(conn) == expect(added=1)


def test_is_screening_helper():
    assert stats_core.is_screening("screen_page", None)
    assert stats_core.is_screening("onboarding", None)
    assert stats_core.is_screening("today", "screen")
    assert not stats_core.is_screening("today", "new")
    assert not stats_core.is_screening("browse", None)
