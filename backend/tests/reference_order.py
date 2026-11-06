"""``reference_order`` — the Python twin of the learning-order ``ORDER BY`` for the pinned tests (docs/analysis/2026-11-06-learn-order/
DESIGN.md §3 Lane C, §4.1 item 11, §4.2, §4.3).

It reads the STORED ``words.learn_rank`` column and sorts in Python by the tuple the five sites express in SQL — the stage distance
of :func:`wd.services.learn_order.stage_distance` when a 主攻阶段 ``cur`` applies, then ``learn_rank IS NULL``, ``learn_rank``,
``(frq IS NULL OR frq = 0)``, ``frq`` (SQLite puts NULL before 0 inside that bucket), ``lemma`` (UNIQUE, so the order is total).
A test therefore pins the MECHANISM — "the SQL order equals the stored key's order" — and never a policy literal: no lemma list of
the seed is typed into a test, and the same assertion holds on an unfilled database (every ``learn_rank`` NULL → the pre-0014
frequency order inside each stage-distance group) and on a filled one.

Importable from any test module like ``fake_claude`` / ``fake_openai`` (pytest's prepend import mode puts ``backend/tests`` on
``sys.path``); scripts add the directory themselves.
"""

from __future__ import annotations

import sqlite3
from typing import Any, Mapping, Sequence

from wd import db
from wd.images.style import FUNCTION_POS, dominant_pos
from wd.services.learn_order import stage_distance

# FACTS §2 / DESIGN §1.6: the 24 auxiliary and modal forms of the acceptance predicate ``facts_closed`` — a measurement gate for the
# full-seed assertions ("0 FACTS-closed words in the first 30"), deliberately wider than the policy's own closed class
AUX_FACTS: frozenset[str] = frozenset(
    "be am is are was were been being do does did done have has had can could will would shall should may might must ought".split()
)
ROW_COLUMNS = "w.lemma, w.stage_min, w.learn_rank, w.frq"


def order_key(row: Mapping[str, Any], cur: int | None) -> tuple:
    """The sort tuple of one ``words`` row (keys ``lemma``, ``stage_min``, ``learn_rank``, ``frq``): ``learn_order.stage_distance_sql``
    when ``cur`` is given, then ``learn_order.ORDER_SQL`` — NULL key last, the key, unknown frequency last (NULL before 0), ``frq``,
    ``lemma``."""
    lemma, stage_min, rank, frq = row["lemma"], row["stage_min"], row["learn_rank"], row["frq"]
    unknown = frq is None or frq == 0
    tail = (rank is None, 0 if rank is None else rank, unknown, frq is not None, 0 if frq is None else frq, lemma)
    return tail if cur is None else (stage_distance(stage_min, cur), *tail)


def reference_order(conn_or_settings: Any, where_sql: str, *, cur: int | None = None, params: Sequence[Any] | Mapping[str, Any] = ()) -> list[str]:
    """Lemmas of ``SELECT … FROM words w WHERE {where_sql}`` in the learning order read from the stored column.

    ``conn_or_settings`` is an open ``sqlite3.Connection`` or a ``Settings`` (``db_path``; a private connection is opened and closed);
    ``where_sql`` may use bare column names or the alias ``w`` (and subqueries such as the ``NOT EXISTS`` of 筛词); ``params`` binds its
    placeholders (a tuple for ``?``, a dict for ``:name``); ``cur`` is the 主攻阶段 index of the stage-distance prefix (None = no prefix,
    the plain ``ORDER_SQL``).
    """
    own = not isinstance(conn_or_settings, sqlite3.Connection)
    conn = db.connect(conn_or_settings.db_path) if own else conn_or_settings
    try:
        rows = conn.execute(f"SELECT {ROW_COLUMNS} FROM words w WHERE {where_sql}", params).fetchall()
    finally:
        if own:
            conn.close()
    dicts = [{"lemma": r[0], "stage_min": r[1], "learn_rank": r[2], "frq": r[3]} for r in rows]
    return [d["lemma"] for d in sorted(dicts, key=lambda d: order_key(d, cur))]


def facts_closed(row: Mapping[str, Any]) -> bool:
    """DESIGN §1.6 acceptance predicate over a row with ``lemma`` / ``pos`` / ``sources``: dominant pos in the image gate ``FUNCTION_POS``
    (interjections included), one of the 24 :data:`AUX_FACTS` forms, or an ``inherit:`` token — a superset of the policy's closed class."""
    return dominant_pos(row["pos"]) in FUNCTION_POS or row["lemma"] in AUX_FACTS or "inherit:" in str(row["sources"] or "")


__all__ = ["AUX_FACTS", "ROW_COLUMNS", "facts_closed", "order_key", "reference_order"]
