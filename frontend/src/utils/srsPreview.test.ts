// Pins utils/srsPreview against backend/tests/fixtures/srs_trajectory.json (DESIGN §7, FRONTEND §7):
// the 1 → 3 → 8 → 20 → 51 → 133 → 180 trajectory, the eases/steps/consecutive_good columns, the lapse
// case and every `next_due_zh` string — byte-for-byte what `GradeResponse.next_due_zh` carries.
import { describe, expect, it } from 'vitest';
import rawFixture from '../../../backend/tests/fixtures/srs_trajectory.json';
import { zh } from '@/i18n/zh';
import {
  addDays,
  crc32,
  daysBetween,
  formatMonthDay,
  freshSnapshot,
  fuzz,
  humanize,
  localDateOf,
  previewAll,
  previewGrade,
  rnd,
  snapshotOf,
  toDate,
  type PreviewGrade,
  type SrsSnapshot,
} from './srsPreview';

interface Fixture {
  ease_start: number;
  grades: PreviewGrade[];
  intervals: number[];
  eases: number[];
  steps: (0 | 1)[];
  consecutive_good: number[];
  next_due_zh: string[];
  mastery_suggested_from_step: number;
  lapse: {
    after_step: number;
    state_before: { state: 'learning'; ease: number; interval_days: number; step: 0 | 1; repetitions: number; lapses: number; consecutive_good: number };
    grades: PreviewGrade[];
    intervals: number[];
    eases: number[];
    steps: (0 | 1)[];
    lapses: number[];
    consecutive_good: number[];
    next_due_zh: string[];
    mastery_suggested: boolean[];
  };
  humanize: { cases: { step: 0 | 1; interval_days: number; zh: string }[]; master: string; skip: string; screen_unfamiliar_no_study_row: string };
}

const fixture = rawFixture as unknown as Fixture;

/** Local noon of a `YYYY-MM-DD` (so the study day is unambiguous in the browser zone). */
const noonOf = (localDate: string): Date => new Date((toDate(localDate) as Date).getTime() + 12 * 3_600_000);

/** Applies one grade "on the due day": the step is re-checked 10 minutes later, a review on its due date. */
function step(s: SrsSnapshot, grade: PreviewGrade, now: Date) {
  const res = previewGrade(s, grade, { now, fuzz: false });
  const next: SrsSnapshot = {
    state: res.state,
    ease: res.ease,
    interval_days: res.interval_days,
    step: res.step,
    repetitions: res.repetitions,
    lapses: res.lapses,
    consecutive_good: res.consecutive_good,
    due_at: res.due_at,
  };
  const nextNow = res.step === 1 ? new Date(now.getTime() + 10 * 60_000) : res.due_local_date ? noonOf(res.due_local_date) : now;
  return { res, next, nextNow };
}

describe('srsPreview — pinned trajectory', () => {
  it('reproduces intervals, eases, steps, consecutive_good, next_due_zh and mastery_suggested', () => {
    let s = freshSnapshot();
    expect(s.ease).toBe(fixture.ease_start);
    let now = noonOf('2026-10-14');
    fixture.grades.forEach((grade, i) => {
      const { res, next, nextNow } = step(s, grade, now);
      expect(res.interval_days, `interval at step ${i}`).toBe(fixture.intervals[i]);
      expect(res.ease, `ease at step ${i}`).toBe(fixture.eases[i]);
      expect(res.step, `step at step ${i}`).toBe(fixture.steps[i]);
      expect(res.consecutive_good, `consecutive_good at step ${i}`).toBe(fixture.consecutive_good[i]);
      expect(res.next_due_zh, `next_due_zh at step ${i}`).toBe(fixture.next_due_zh[i]);
      expect(res.mastery_suggested, `mastery at step ${i}`).toBe(i >= fixture.mastery_suggested_from_step);
      expect(res.repetitions).toBe(i + 1);
      expect(res.state).toBe('learning');
      s = next;
      now = nextNow;
    });
  });

  it('reproduces the lapse case (again at 20 d → ease 2.35 → relearn → 10 d)', () => {
    let s = freshSnapshot();
    let now = noonOf('2026-10-14');
    for (let i = 0; i <= fixture.lapse.after_step; i++) {
      const r = step(s, fixture.grades[i] as PreviewGrade, now);
      s = r.next;
      now = r.nextNow;
    }
    const before = fixture.lapse.state_before;
    expect(s).toMatchObject({ state: before.state, ease: before.ease, interval_days: before.interval_days, step: before.step, repetitions: before.repetitions, lapses: before.lapses, consecutive_good: before.consecutive_good });
    fixture.lapse.grades.forEach((grade, i) => {
      const { res, next, nextNow } = step(s, grade, now);
      expect(res.interval_days).toBe(fixture.lapse.intervals[i]);
      expect(res.ease).toBe(fixture.lapse.eases[i]);
      expect(res.step).toBe(fixture.lapse.steps[i]);
      expect(res.lapses).toBe(fixture.lapse.lapses[i]);
      expect(res.consecutive_good).toBe(fixture.lapse.consecutive_good[i]);
      expect(res.next_due_zh).toBe(fixture.lapse.next_due_zh[i]);
      expect(res.mastery_suggested).toBe(fixture.lapse.mastery_suggested[i]);
      s = next;
      now = nextNow;
    });
  });

  it('humanize matches every fixture case and the master/skip strings', () => {
    for (const c of fixture.humanize.cases) expect(humanize(c.step, c.interval_days)).toBe(c.zh);
    const all = previewAll(freshSnapshot(), { fuzz: false });
    expect(all.master).toBe(fixture.humanize.master);
    expect(all.skip).toBe(fixture.humanize.skip);
    expect(all.again).toBe(zh.study.nextDue.tenMin);
    expect(all.good).toBe(zh.study.nextDue.tenMin); // first exposure graded good → the step
    expect(zh.study.nextDue.tomorrow).toBe(fixture.humanize.screen_unfamiliar_no_study_row);
  });

  it('applies overdue credit in the review phase (delay/2 for good, delay/4 for hard)', () => {
    const s: SrsSnapshot = { state: 'learning', ease: 2.5, interval_days: 8, step: 0, repetitions: 4, lapses: 0, consecutive_good: 3, due_at: noonOf('2026-10-10').toISOString() };
    const onTime = previewGrade(s, 'good', { now: noonOf('2026-10-10'), fuzz: false });
    expect(onTime.interval_days).toBe(rnd(8 * 2.5));
    const late = previewGrade(s, 'good', { now: noonOf('2026-10-14'), fuzz: false }); // 4 days late
    expect(late.interval_days).toBe(rnd((8 + 2) * 2.5));
    const hard = previewGrade(s, 'hard', { now: noonOf('2026-10-14'), fuzz: false });
    expect(hard.ease).toBe(2.35);
    expect(hard.interval_days).toBe(Math.max(9, rnd((8 + 1) * 1.2)));
    expect(hard.consecutive_good).toBe(0);
  });

  it('keeps ease within [1.3, 3.0] and intervals within [1, 180]', () => {
    const low: SrsSnapshot = { state: 'learning', ease: 1.3, interval_days: 5, step: 0, repetitions: 9, lapses: 3, consecutive_good: 0, due_at: null };
    expect(previewGrade(low, 'again', { fuzz: false }).ease).toBe(1.3);
    const high: SrsSnapshot = { state: 'learning', ease: 3.0, interval_days: 170, step: 0, repetitions: 9, lapses: 0, consecutive_good: 2, due_at: null };
    const res = previewGrade(high, 'good', { fuzz: false });
    expect(res.ease).toBe(3.0);
    expect(res.interval_days).toBe(180);
    expect(res.next_due_zh).toBe(zh.study.nextDue.months(6));
  });
});

describe('srsPreview — fuzz and helpers', () => {
  it('crc32 matches zlib (standard check value) and fuzz is deterministic within ±5 %', () => {
    expect(crc32('123456789')).toBe(0xcbf43926);
    expect(fuzz(7, 3, 2)).toBe(2); // below FUZZ_MIN_INTERVAL: untouched
    for (const iv of [3, 8, 20, 51, 133]) {
      const a = fuzz(42, 5, iv);
      expect(fuzz(42, 5, iv)).toBe(a);
      expect(a).toBeGreaterThanOrEqual(Math.max(1, rnd(iv * 0.95)) - 1);
      expect(a).toBeLessThanOrEqual(rnd(iv * 1.05) + 1);
    }
    // the fixture's 20-day step: ease 2.55, consecutive_good 4 → rnd(20 × 2.55) = 51 without fuzz
    const s: SrsSnapshot = { state: 'learning', ease: 2.55, interval_days: 20, step: 0, repetitions: 5, lapses: 0, consecutive_good: 4, due_at: null };
    const fuzzed = previewGrade(s, 'good', { uwId: 11, fuzz: true });
    expect(fuzzed.interval_days).toBeGreaterThanOrEqual(47);
    expect(fuzzed.interval_days).toBeLessThanOrEqual(54);
    expect(previewGrade(s, 'good', { uwId: null, fuzz: true }).interval_days).toBe(51); // no row id → no fuzz
  });

  it('snapshotOf reads a UserWord and defaults to a fresh row', () => {
    expect(snapshotOf(null)).toEqual(freshSnapshot());
    const snap = snapshotOf({
      state: 'learning',
      srs: { ease: 2.6, interval_days: 3, step: 0, repetitions: 2, lapses: 0, consecutive_good: 2, due_at: '2026-10-20T00:00:00Z', last_graded_at: null, mastery_suggested: false },
    });
    expect(snap).toMatchObject({ state: 'learning', ease: 2.6, interval_days: 3, step: 0, repetitions: 2, due_at: '2026-10-20T00:00:00Z' });
  });

  it('local date helpers mirror clock.local_date', () => {
    expect(localDateOf(new Date('2026-10-14T20:00:00Z'), 'Asia/Shanghai')).toBe('2026-10-15');
    expect(localDateOf(new Date('2026-10-14T20:00:00Z'), 'UTC')).toBe('2026-10-14');
    expect(localDateOf(new Date('2026-10-14T20:00:00Z'), 'Not/AZone')).toBe(localDateOf(new Date('2026-10-14T20:00:00Z')));
    expect(addDays('2026-10-30', 3)).toBe('2026-11-02');
    expect(addDays('2026-01-01', -1)).toBe('2025-12-31');
    expect(daysBetween('2026-10-10', '2026-10-14')).toBe(4);
    expect(daysBetween('garbage', '2026-10-14')).toBe(0);
    expect(formatMonthDay('2026-10-12')).toBe(new Intl.DateTimeFormat('zh-CN', { month: 'long', day: 'numeric' }).format(new Date(2026, 9, 12)));
    expect(formatMonthDay('nonsense')).toBe('nonsense');
  });
});
