"""WD-SRS (WP4, DESIGN §7): pure functions, table-tested, constants in one place.

Nothing here touches the database. :func:`grade` takes the SRS fields of a ``user_words`` row as a
:class:`SrsState`, applies one ``again`` / ``hard`` / ``good`` grade and returns the new state together with
the ``requeue_min`` hint (10 while the card sits in the learning step), ``mastery_suggested`` and the
``GradeResponse.next_due_zh`` string (:func:`humanize`, mirrored byte-for-byte by the client's
``utils/srsPreview.ts`` and pinned in ``tests/fixtures/srs_trajectory.json``).

``master`` and ``skip`` are not grades of the SRS: the state machine (``services/bank.apply_action``) and
``batches.grade_item`` handle them (DESIGN §7 "Grade → effect on push items").
"""

from __future__ import annotations

import math
import zlib
from dataclasses import dataclass, replace
from datetime import date, datetime, timedelta
from typing import Any, Mapping

from ..clock import UTC, day_start, local_date, parse_iso, to_iso

# ------------------------------------------------------------------------------- constants (DESIGN §7)
EASE_START, EASE_MIN, EASE_MAX = 2.5, 1.3, 3.0
LEARNING_STEP_MIN = 10  # one intra-session re-check, then graduate
GRADUATING_INTERVAL = 1  # days
HARD_FACTOR, HARD_EASE_DELTA = 1.2, -0.15
AGAIN_EASE_DELTA, LAPSE_FACTOR = -0.20, 0.5
EASE_RECOVERY_EVERY, EASE_RECOVERY_DELTA = 3, +0.05
MAX_INTERVAL = 180
FUZZ_PCT, FUZZ_MIN_INTERVAL = 0.05, 3
MASTERY_MIN_INTERVAL, MASTERY_MIN_CONSEC = 30, 3

GRADES: tuple[str, ...] = ("again", "hard", "good")

# next_due_zh strings that are not produced by humanize() (set by grade_item, API.md §9.1)
NEXT_DUE_MASTER = "已掌握"
NEXT_DUE_SKIP = "已跳过"
NEXT_DUE_TOMORROW = "明天"
NEXT_DUE_TODAY = "今天"  # a 推荐词 graded 不熟悉 whose study card was appended to today's queue
NEXT_DUE_KNOWN = "已认识"  # a 推荐词 graded 认识


@dataclass
class SrsState:
    """The SRS columns of a ``user_words`` row (``due_at`` / ``last_graded_at`` as aware UTC datetimes)."""

    state: str = "new"
    ease: float = EASE_START
    interval_days: int = 0
    step: int = 0
    repetitions: int = 0
    lapses: int = 0
    consecutive_good: int = 0
    due_at: datetime | None = None
    last_graded_at: datetime | None = None

    @classmethod
    def from_row(cls, row: Mapping[str, Any]) -> "SrsState":
        return cls(
            state=str(row.get("state") or "new"),
            ease=float(row.get("ease") if row.get("ease") is not None else EASE_START),
            interval_days=int(row.get("interval_days") or 0),
            step=int(row.get("step") or 0),
            repetitions=int(row.get("repetitions") or 0),
            lapses=int(row.get("lapses") or 0),
            consecutive_good=int(row.get("consecutive_good") or 0),
            due_at=_parse(row.get("due_at")),
            last_graded_at=_parse(row.get("last_graded_at")),
        )

    def to_row(self) -> dict[str, Any]:
        """Column values for an ``UPDATE user_words`` (timestamps as ISO strings)."""
        return {
            "state": self.state,
            "ease": self.ease,
            "interval_days": int(self.interval_days),
            "step": int(self.step),
            "repetitions": int(self.repetitions),
            "lapses": int(self.lapses),
            "consecutive_good": int(self.consecutive_good),
            "due_at": None if self.due_at is None else to_iso(self.due_at),
            "last_graded_at": None if self.last_graded_at is None else to_iso(self.last_graded_at),
        }


def _parse(value: Any) -> datetime | None:
    if value is None or value == "":
        return None
    if isinstance(value, datetime):
        return value if value.tzinfo is not None else value.replace(tzinfo=UTC)
    return parse_iso(str(value))


# ---------------------------------------------------------------------------------------- arithmetic
def rnd(x: float) -> int:
    """Half-up rounding (Python's ``round`` is banker's rounding)."""
    return int(math.floor(x + 0.5))


def q2(e: float) -> float:
    """Ease clamped to ``EASE_MIN``–``EASE_MAX`` and rounded to 2 decimals."""
    return round(min(EASE_MAX, max(EASE_MIN, e)), 2)


def clamp(i: float) -> int:
    """Interval clamped to 1–``MAX_INTERVAL`` days."""
    return int(min(MAX_INTERVAL, max(1, i)))


def fuzz(uw_id: int, reps: int, iv: int) -> int:
    """Deterministic ±``FUZZ_PCT`` jitter for intervals ≥ ``FUZZ_MIN_INTERVAL`` days, keyed by ``(uw_id, reps)``.

    The same row graded the same number of times always gets the same jitter, so replays are reproducible.
    """
    if iv < FUZZ_MIN_INTERVAL:
        return int(iv)
    unit = (zlib.crc32(f"{uw_id}:{reps}".encode()) % 101) / 100  # 0.00 … 1.00
    return max(1, rnd(iv * (1 + (unit - 0.5) * 2 * FUZZ_PCT)))


def mastery_suggested(s: SrsState) -> bool:
    """API.md §9.1: ``step == 0 and interval_days >= 30 and consecutive_good >= 3``."""
    return s.step == 0 and s.interval_days >= MASTERY_MIN_INTERVAL and s.consecutive_good >= MASTERY_MIN_CONSEC


def humanize(s: SrsState) -> str:
    """``GradeResponse.next_due_zh`` for an SRS grade (DESIGN §7 thresholds; master/skip are set by the caller)."""
    if s.step == 1:
        return f"{LEARNING_STEP_MIN} 分钟后"
    if s.interval_days == 1:
        return "明天"
    if s.interval_days < 60:
        return f"{s.interval_days} 天后"
    return f"约 {rnd(s.interval_days / 30)} 个月后"


# --------------------------------------------------------------------------------------------- grade
def grade(
    uw_id: int,
    s: SrsState,
    g: str,
    now: datetime,
    tz: str,
    today: date,
    *,
    fuzz_enabled: bool = True,
) -> tuple[SrsState, int | None, bool, str]:
    """Apply ``g`` ∈ again|hard|good to ``s`` (DESIGN §7 algorithm, verbatim).

    Returns ``(new_state, requeue_min, mastery_suggested, next_due_zh)``. ``requeue_min`` is 10 while the card
    sits in the learning/relearning step (an *intermediate* grade) and None once it graduated or was graded
    in the review phase (a *final* grade). ``today`` is the calendar date in ``tz`` (the study day), ``now``
    the UTC instant of the grade. ``fuzz_enabled=False`` reproduces the pinned trajectory exactly.
    """
    if g not in GRADES:
        raise ValueError(f"unknown grade {g!r}")
    if now.tzinfo is None:
        now = now.replace(tzinfo=UTC)
    s = replace(s)
    step_due = now + timedelta(minutes=LEARNING_STEP_MIN)

    def jitter(iv: int) -> int:
        return fuzz(uw_id, s.repetitions, iv) if fuzz_enabled else int(iv)

    if s.step == 1 or s.state == "new":  # learning or relearning step
        if g == "again":
            s.step, s.consecutive_good, s.due_at = 1, 0, step_due
        elif g == "hard":
            s.step, s.due_at = 1, step_due  # repeat the step
        elif s.step == 1:  # good on the step → graduate
            s.interval_days = GRADUATING_INTERVAL if s.interval_days == 0 else max(1, rnd(s.interval_days * LAPSE_FACTOR))
            s.step, s.due_at = 0, day_start(today + timedelta(days=s.interval_days), tz)
            s.consecutive_good += 1
        else:  # first exposure graded good → the 10-minute step
            s.step, s.due_at = 1, step_due
    else:  # review phase
        elapsed = (today - local_date(s.due_at, tz)).days if s.due_at is not None else 0
        delay = max(0, elapsed)  # overdue credit
        if g == "again":
            s.lapses += 1
            s.ease = q2(s.ease + AGAIN_EASE_DELTA)
            s.consecutive_good = 0
            s.step, s.due_at = 1, step_due  # relearning; interval_days kept for the ×0.5 rule
        elif g == "hard":
            s.ease = q2(s.ease + HARD_EASE_DELTA)
            s.consecutive_good = 0
            s.interval_days = clamp(jitter(max(s.interval_days + 1, rnd((s.interval_days + delay / 4) * HARD_FACTOR))))
            s.due_at = day_start(today + timedelta(days=s.interval_days), tz)
        else:
            s.consecutive_good += 1
            if s.consecutive_good % EASE_RECOVERY_EVERY == 0:
                s.ease = q2(s.ease + EASE_RECOVERY_DELTA)
            s.interval_days = clamp(jitter(rnd((s.interval_days + delay / 2) * s.ease)))
            s.due_at = day_start(today + timedelta(days=s.interval_days), tz)

    s.repetitions += 1
    s.last_graded_at = now
    s.state = "learning"
    requeue_min = LEARNING_STEP_MIN if s.step == 1 else None
    return s, requeue_min, mastery_suggested(s), humanize(s)


def is_final(s: SrsState) -> bool:
    """DESIGN §7: an again/hard/good grade is final iff it leaves the card out of the 10-minute step."""
    return s.step == 0


__all__ = [
    "AGAIN_EASE_DELTA",
    "EASE_MAX",
    "EASE_MIN",
    "EASE_RECOVERY_DELTA",
    "EASE_RECOVERY_EVERY",
    "EASE_START",
    "FUZZ_MIN_INTERVAL",
    "FUZZ_PCT",
    "GRADES",
    "GRADUATING_INTERVAL",
    "HARD_EASE_DELTA",
    "HARD_FACTOR",
    "LAPSE_FACTOR",
    "LEARNING_STEP_MIN",
    "MASTERY_MIN_CONSEC",
    "MASTERY_MIN_INTERVAL",
    "MAX_INTERVAL",
    "NEXT_DUE_KNOWN",
    "NEXT_DUE_MASTER",
    "NEXT_DUE_SKIP",
    "NEXT_DUE_TODAY",
    "NEXT_DUE_TOMORROW",
    "SrsState",
    "clamp",
    "fuzz",
    "grade",
    "humanize",
    "is_final",
    "mastery_suggested",
    "q2",
    "rnd",
]
