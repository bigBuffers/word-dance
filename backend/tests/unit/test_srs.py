"""services/srs.py (WP4): the pinned trajectory of tests/fixtures/srs_trajectory.json (fuzz disabled), the lapse case,
the hard path, overdue credit, deterministic fuzz, ease bounds and the never-shortens / never-above-180 properties."""

from __future__ import annotations

import json
import random
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

import pytest

from wd.clock import day_start, local_date
from wd.services import srs

UTC = timezone.utc
TZ = "Asia/Shanghai"
FIXTURE = json.loads((Path(__file__).resolve().parents[1] / "fixtures" / "srs_trajectory.json").read_text(encoding="utf-8"))
START = datetime(2026, 10, 14, 1, 0, tzinfo=UTC)  # 09:00 Shanghai


def run(grades, *, state: srs.SrsState | None = None, now: datetime = START, fuzz: bool = False, uw_id: int = 1):
    """Apply ``grades`` when each one is due: 10 min later on the step, 09:00 local of the due day in review."""
    s = state or srs.SrsState()
    out = []
    for g in grades:
        today = local_date(now, TZ)
        s, requeue, suggested, zh = srs.grade(uw_id, s, g, now, TZ, today, fuzz_enabled=fuzz)
        out.append((s, requeue, suggested, zh))
        assert s.due_at is not None
        now = s.due_at if s.step == 1 else s.due_at + timedelta(hours=9)
    return out


# ------------------------------------------------------------------------------------------ fixture
def test_pinned_trajectory_exact():
    results = run(FIXTURE["grades"])
    assert [r[0].interval_days for r in results] == FIXTURE["intervals"]
    assert [r[0].ease for r in results] == FIXTURE["eases"]
    assert [r[0].step for r in results] == FIXTURE["steps"]
    assert [r[0].consecutive_good for r in results] == FIXTURE["consecutive_good"]
    assert [r[3] for r in results] == FIXTURE["next_due_zh"]
    assert [r[2] for r in results] == [i >= FIXTURE["mastery_suggested_from_step"] for i in range(len(results))]
    assert [r[1] for r in results] == [10, None, None, None, None, None, None, None]
    assert [r[0].repetitions for r in results] == list(range(1, 9))
    assert all(r[0].state == "learning" for r in results)
    assert results[0][0].due_at == START + timedelta(minutes=10)  # the 10-minute step
    assert results[1][0].due_at == day_start(date(2026, 10, 15), TZ)  # graduated: local midnight of tomorrow


def test_lapse_case():
    lapse = FIXTURE["lapse"]
    results = run(FIXTURE["grades"][: lapse["after_step"] + 1])
    s, _, _, _ = results[-1]
    before = lapse["state_before"]
    assert (s.state, s.ease, s.interval_days, s.step, s.repetitions, s.lapses, s.consecutive_good) == (
        before["state"],
        before["ease"],
        before["interval_days"],
        before["step"],
        before["repetitions"],
        before["lapses"],
        before["consecutive_good"],
    )
    due_day = s.due_at + timedelta(hours=9)
    after = run(lapse["grades"], state=s, now=due_day)
    assert [r[0].interval_days for r in after] == lapse["intervals"]
    assert [r[0].ease for r in after] == lapse["eases"]
    assert [r[0].step for r in after] == lapse["steps"]
    assert [r[0].lapses for r in after] == lapse["lapses"]
    assert [r[0].consecutive_good for r in after] == lapse["consecutive_good"]
    assert [r[3] for r in after] == lapse["next_due_zh"]
    assert [r[2] for r in after] == lapse["mastery_suggested"]
    assert after[0][1] == 10 and after[1][1] is None


@pytest.mark.parametrize("case", FIXTURE["humanize"]["cases"])
def test_humanize_cases(case):
    assert srs.humanize(srs.SrsState(step=case["step"], interval_days=case["interval_days"])) == case["zh"]


def test_humanize_constants_match_fixture():
    assert srs.NEXT_DUE_MASTER == FIXTURE["humanize"]["master"]
    assert srs.NEXT_DUE_SKIP == FIXTURE["humanize"]["skip"]
    assert srs.NEXT_DUE_TOMORROW == FIXTURE["humanize"]["screen_unfamiliar_no_study_row"]
    assert srs.EASE_START == FIXTURE["ease_start"]


# ---------------------------------------------------------------------------------------- hard path
def test_hard_on_a_new_card_and_on_the_step():
    (s1, requeue1, _, zh1), (s2, requeue2, _, zh2), (s3, requeue3, _, zh3) = run(["hard", "hard", "good"])
    assert (s1.step, requeue1, zh1, s1.interval_days, s1.ease) == (1, 10, "10 分钟后", 0, 2.5)  # repeats the step, no ease penalty
    assert (s2.step, requeue2, zh2) == (1, 10, "10 分钟后")
    assert (s3.step, requeue3, zh3, s3.interval_days) == (0, None, "明天", 1)  # good on the step graduates to 1 day


def test_hard_in_review_grows_slowly_and_costs_ease():
    s = srs.SrsState(state="learning", ease=2.5, interval_days=8, step=0, repetitions=4, consecutive_good=3, due_at=day_start(date(2026, 10, 14), TZ))
    (s2, requeue, suggested, zh), = run(["hard"], state=s, now=START)
    assert requeue is None and suggested is False
    assert s2.ease == 2.35 and s2.consecutive_good == 0
    assert s2.interval_days == max(8 + 1, srs.rnd(8 * 1.2)) == 10 and zh == "10 天后"
    assert s2.due_at == day_start(date(2026, 10, 24), TZ)


def test_overdue_credit_for_good_and_hard():
    due = day_start(date(2026, 10, 9), TZ)  # 5 days overdue on 2026-10-14
    s = srs.SrsState(state="learning", ease=2.5, interval_days=10, step=0, repetitions=5, consecutive_good=1, due_at=due)
    (good,) = run(["good"], state=s, now=START)
    assert good[0].interval_days == srs.rnd((10 + 5 / 2) * 2.5) == 31  # on time it would be 25
    (hard,) = run(["hard"], state=s, now=START)
    assert hard[0].interval_days == max(11, srs.rnd((10 + 5 / 4) * 1.2)) == 14
    on_time = srs.SrsState(state="learning", ease=2.5, interval_days=10, step=0, repetitions=5, consecutive_good=1, due_at=day_start(date(2026, 10, 14), TZ))
    assert run(["good"], state=on_time, now=START)[0][0].interval_days == 25
    early = srs.SrsState(state="learning", ease=2.5, interval_days=10, step=0, repetitions=5, consecutive_good=1, due_at=day_start(date(2026, 10, 20), TZ))
    assert run(["good"], state=early, now=START)[0][0].interval_days == 25  # delay never negative


def test_again_in_review_lapses_and_relearns_at_half():
    s = srs.SrsState(state="learning", ease=2.5, interval_days=51, step=0, repetitions=6, consecutive_good=5, due_at=day_start(date(2026, 10, 14), TZ))
    (a, b) = run(["again", "good"], state=s, now=START)
    assert (a[0].lapses, a[0].ease, a[0].consecutive_good, a[0].step, a[0].interval_days, a[1]) == (1, 2.3, 0, 1, 51, 10)
    assert (b[0].interval_days, b[0].step, b[1], b[3]) == (26, 0, None, "26 天后")  # max(1, rnd(51 × 0.5)) = 26


# --------------------------------------------------------------------------------------------- fuzz
def test_fuzz_is_deterministic_and_bounded():
    assert srs.fuzz(1, 0, 1) == 1 and srs.fuzz(1, 0, 2) == 2  # below 3 days: untouched
    for iv in (3, 10, 51, 133, 180):
        for uw_id in range(1, 40):
            for reps in range(0, 5):
                v = srs.fuzz(uw_id, reps, iv)
                assert srs.fuzz(uw_id, reps, iv) == v  # same key → same value
                assert abs(v - iv) <= srs.rnd(iv * srs.FUZZ_PCT) + 1
                assert v >= 1
    values = {srs.fuzz(uw_id, 0, 100) for uw_id in range(1, 300)}
    assert len(values) > 3 and min(values) >= 95 and max(values) <= 105


def test_grade_with_fuzz_enabled_stays_within_five_percent_of_the_pinned_value():
    pinned = run(FIXTURE["grades"], fuzz=False)
    fuzzy = run(FIXTURE["grades"], fuzz=True, uw_id=7)
    for (p, *_), (f, *_) in zip(pinned, fuzzy):
        if p.interval_days < srs.FUZZ_MIN_INTERVAL:
            assert f.interval_days == p.interval_days
        else:
            assert abs(f.interval_days - p.interval_days) <= max(1, srs.rnd(p.interval_days * 0.06))
        assert f.interval_days <= srs.MAX_INTERVAL


# ------------------------------------------------------------------------------------------- bounds
def test_ease_bounds():
    s = srs.SrsState(state="learning", ease=1.4, interval_days=5, step=0, repetitions=3, due_at=day_start(date(2026, 10, 14), TZ))
    results = run(["again", "good", "again", "good", "again", "good"], state=s, now=START)
    assert min(r[0].ease for r in results) == srs.EASE_MIN
    high = srs.SrsState(state="learning", ease=2.95, interval_days=20, step=0, repetitions=3, consecutive_good=2, due_at=day_start(date(2026, 10, 14), TZ))
    results = run(["good"] * 12, state=high, now=START)
    assert max(r[0].ease for r in results) == srs.EASE_MAX
    assert all(srs.EASE_MIN <= r[0].ease <= srs.EASE_MAX for r in results)
    assert srs.q2(5.0) == 3.0 and srs.q2(0.1) == 1.3 and srs.q2(2.555) == 2.56


def test_properties_random_sequences():
    rng = random.Random(20261014)
    for trial in range(60):
        grades = [rng.choice(["again", "hard", "good", "good", "good"]) for _ in range(25)]
        prev_interval = 0
        prev_step = 0
        for s, requeue, _suggested, zh in run(grades, fuzz=True, uw_id=trial + 1):
            assert 0 <= s.interval_days <= srs.MAX_INTERVAL
            assert srs.EASE_MIN <= s.ease <= srs.EASE_MAX
            assert s.step in (0, 1) and (requeue == 10) == (s.step == 1)
            assert zh == srs.humanize(s)
            prev_interval, prev_step = s.interval_days, s.step


def test_good_in_review_never_shortens_and_caps_at_180():
    for ease in (1.3, 2.0, 2.5, 3.0):
        for iv in range(1, 181):
            s = srs.SrsState(state="learning", ease=ease, interval_days=iv, step=0, repetitions=3, consecutive_good=1, due_at=day_start(date(2026, 10, 14), TZ))
            (res,) = run(["good"], state=s, now=START, fuzz=True, uw_id=iv)
            assert res[0].interval_days >= min(iv, srs.MAX_INTERVAL)
            assert res[0].interval_days <= srs.MAX_INTERVAL
            assert res[0].due_at == day_start(date(2026, 10, 14) + timedelta(days=res[0].interval_days), TZ)


def test_mastery_suggested_rule():
    assert srs.mastery_suggested(srs.SrsState(step=0, interval_days=30, consecutive_good=3))
    assert not srs.mastery_suggested(srs.SrsState(step=1, interval_days=30, consecutive_good=3))
    assert not srs.mastery_suggested(srs.SrsState(step=0, interval_days=29, consecutive_good=3))
    assert not srs.mastery_suggested(srs.SrsState(step=0, interval_days=30, consecutive_good=2))


def test_grade_is_pure_and_validates_input():
    s = srs.SrsState()
    s2, *_ = srs.grade(1, s, "good", START, TZ, date(2026, 10, 14))
    assert s.step == 0 and s.repetitions == 0 and s2.step == 1  # the input is not mutated
    with pytest.raises(ValueError):
        srs.grade(1, s, "master", START, TZ, date(2026, 10, 14))
    row = {"state": "learning", "ease": 2.6, "interval_days": 3, "step": 0, "repetitions": 2, "lapses": 0, "consecutive_good": 2, "due_at": "2026-10-14T16:00:00Z", "last_graded_at": None}
    st = srs.SrsState.from_row(row)
    assert st.due_at == datetime(2026, 10, 14, 16, 0, tzinfo=UTC) and st.to_row()["due_at"] == "2026-10-14T16:00:00Z"
    assert srs.rnd(2.5) == 3 and srs.rnd(0.5) == 1 and srs.rnd(7.49) == 7 and srs.clamp(400) == 180 and srs.clamp(0) == 1
