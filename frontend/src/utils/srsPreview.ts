// srsPreview — client mirror of backend/wd/services/srs.py (DESIGN §7): the same constants and formulas
// as `grade()` so the study card can show 「下次：模糊 → 明天 · 记住了 → 3 天后」 before the user picks,
// plus `humanize()` == `GradeResponse.next_due_zh` (API.md §9.1 thresholds). Pinned byte-for-byte by
// srsPreview.test.ts against backend/tests/fixtures/srs_trajectory.json (fuzz disabled there).
//
// The server stays authoritative: after a grade the card shows the server's `next_due_zh`; this module
// only predicts. The local-date helpers mirror clock.py's `local_date()` (calendar date in the user's
// timezone, no 04:00 rollover) and are shared by the pages until WP7's utils/date.ts lands.
import type { Grade, Srs, UserState, UserWord } from '@/api/types';
import { zh } from '@/i18n/zh';

// ---- constants (DESIGN §7, "constants in one place") -----------------------------------------------
export const EASE_START = 2.5;
export const EASE_MIN = 1.3;
export const EASE_MAX = 3.0;
export const LEARNING_STEP_MIN = 10;
export const GRADUATING_INTERVAL = 1;
export const HARD_FACTOR = 1.2;
export const HARD_EASE_DELTA = -0.15;
export const AGAIN_EASE_DELTA = -0.2;
export const LAPSE_FACTOR = 0.5;
export const EASE_RECOVERY_EVERY = 3;
export const EASE_RECOVERY_DELTA = 0.05;
export const MAX_INTERVAL = 180;
export const FUZZ_PCT = 0.05;
export const FUZZ_MIN_INTERVAL = 3;
export const MASTERY_MIN_INTERVAL = 30;
export const MASTERY_MIN_CONSEC = 3;

export type PreviewGrade = 'again' | 'hard' | 'good';

/** The SRS fields of a `user_words` row the formulas read (= `UserWord.srs` + `state`). */
export interface SrsSnapshot {
  state: UserState;
  ease: number;
  interval_days: number;
  step: 0 | 1;
  repetitions: number;
  lapses: number;
  consecutive_good: number;
  due_at: string | null;
}

export interface PreviewOptions {
  /** Reference instant (default: now). */
  now?: Date;
  /** `user_words.id` — seeds the deterministic fuzz; `null` disables fuzz like the fixture. */
  uwId?: number | null;
  /** Apply the ±5 % fuzz of intervals ≥ 3 days (default true; the fixture test passes false). */
  fuzz?: boolean;
  /** IANA timezone of the study day (default: the browser's). */
  timeZone?: string;
}

export interface PreviewResult extends SrsSnapshot {
  /** Minutes until the card re-appears while in the learning step, else null. */
  requeue_minutes: number | null;
  /** Local date (`YYYY-MM-DD`) the card becomes due again when it left the step, else null. */
  due_local_date: string | null;
  mastery_suggested: boolean;
  next_due_zh: string;
}

// ---- small numeric helpers mirroring srs.py ---------------------------------------------------------
/** Half-up rounding (Python `round()` is banker's; srs.py uses floor(x + 0.5)). */
export const rnd = (x: number): number => Math.floor(x + 0.5);
/** `q2()`: clamp the ease to [1.3, 3.0] and round to 2 decimals. */
export const q2 = (e: number): number => Math.round(Math.min(EASE_MAX, Math.max(EASE_MIN, e)) * 100) / 100;
/** `clamp()`: interval in [1, 180] days. */
export const clampInterval = (i: number): number => Math.trunc(Math.min(MAX_INTERVAL, Math.max(1, i)));

let crcTable: Uint32Array | null = null;
/** zlib.crc32-compatible CRC-32 of an ASCII/UTF-8 string (unsigned). */
export function crc32(text: string): number {
  if (!crcTable) {
    crcTable = new Uint32Array(256);
    for (let n = 0; n < 256; n++) {
      let c = n;
      for (let k = 0; k < 8; k++) c = c & 1 ? 0xedb88320 ^ (c >>> 1) : c >>> 1;
      crcTable[n] = c >>> 0;
    }
  }
  const bytes = new TextEncoder().encode(text);
  let crc = 0xffffffff;
  for (const b of bytes) crc = (crcTable[(crc ^ b) & 0xff] ?? 0) ^ (crc >>> 8);
  return (crc ^ 0xffffffff) >>> 0;
}

/** Deterministic ±5 % fuzz for intervals ≥ 3 days, seeded by `uw_id:repetitions` (srs.py `fuzz`). */
export function fuzz(uwId: number, reps: number, iv: number): number {
  if (iv < FUZZ_MIN_INTERVAL) return iv;
  const frac = (crc32(`${uwId}:${reps}`) % 101) / 100;
  return Math.max(1, rnd(iv * (1 + (frac - 0.5) * 2 * FUZZ_PCT)));
}

// ---- local dates (clock.py mirror) -----------------------------------------------------------------
const LOCAL_DATE_RE = /^(\d{4})-(\d{2})-(\d{2})$/;

/** `YYYY-MM-DD` of `date` in `timeZone` (falls back to the browser zone for an unknown zone). */
export function localDateOf(date: Date, timeZone?: string): string {
  const opts: Intl.DateTimeFormatOptions = { year: 'numeric', month: '2-digit', day: '2-digit' };
  let parts: Intl.DateTimeFormatPart[];
  try {
    parts = new Intl.DateTimeFormat('en-CA', timeZone ? { ...opts, timeZone } : opts).formatToParts(date);
  } catch {
    parts = new Intl.DateTimeFormat('en-CA', opts).formatToParts(date);
  }
  const get = (type: string) => parts.find((p) => p.type === type)?.value ?? '';
  return `${get('year')}-${get('month')}-${get('day')}`;
}

/** Parses `YYYY-MM-DD` into `[year, month, day]`, or null. */
export function parseLocalDate(s: string): [number, number, number] | null {
  const m = LOCAL_DATE_RE.exec(s);
  if (!m) return null;
  return [Number(m[1]), Number(m[2]), Number(m[3])];
}

/** Whole days from local date `a` to local date `b` (`b − a`); 0 for unparsable input. */
export function daysBetween(a: string, b: string): number {
  const pa = parseLocalDate(a);
  const pb = parseLocalDate(b);
  if (!pa || !pb) return 0;
  const ua = Date.UTC(pa[0], pa[1] - 1, pa[2]);
  const ub = Date.UTC(pb[0], pb[1] - 1, pb[2]);
  return Math.round((ub - ua) / 86_400_000);
}

/** `YYYY-MM-DD` shifted by `n` days. */
export function addDays(localDate: string, n: number): string {
  const p = parseLocalDate(localDate);
  if (!p) return localDate;
  const d = new Date(Date.UTC(p[0], p[1] - 1, p[2] + n));
  return `${d.getUTCFullYear()}-${String(d.getUTCMonth() + 1).padStart(2, '0')}-${String(d.getUTCDate()).padStart(2, '0')}`;
}

/** A `Date` at local midnight of a `YYYY-MM-DD` (browser zone), or the parsed instant of an ISO datetime. */
export function toDate(input: string | Date): Date | null {
  if (input instanceof Date) return Number.isNaN(input.getTime()) ? null : input;
  const p = parseLocalDate(input);
  if (p) return new Date(p[0], p[1] - 1, p[2]);
  const t = Date.parse(input);
  return Number.isNaN(t) ? null : new Date(t);
}

/** 「10月12日」 for a local date (`YYYY-MM-DD`) or an ISO instant (rendered in `timeZone`). */
export function formatMonthDay(input: string | Date, timeZone?: string): string {
  const d = toDate(input);
  if (!d) return typeof input === 'string' ? input : '';
  const isLocalDate = typeof input === 'string' && LOCAL_DATE_RE.test(input);
  const opts: Intl.DateTimeFormatOptions = { month: 'long', day: 'numeric' };
  try {
    return new Intl.DateTimeFormat('zh-CN', timeZone && !isLocalDate ? { ...opts, timeZone } : opts).format(d);
  } catch {
    return new Intl.DateTimeFormat('zh-CN', opts).format(d);
  }
}

/** 「10月12日 08:00」 for an ISO instant in `timeZone` (used for next push / history rows). */
export function formatDateTime(iso: string, timeZone?: string): string {
  const d = toDate(iso);
  if (!d) return iso;
  const opts: Intl.DateTimeFormatOptions = { month: 'long', day: 'numeric', hour: '2-digit', minute: '2-digit', hour12: false };
  try {
    return new Intl.DateTimeFormat('zh-CN', timeZone ? { ...opts, timeZone } : opts).format(d);
  } catch {
    return new Intl.DateTimeFormat('zh-CN', opts).format(d);
  }
}

// ---- humanize (== GradeResponse.next_due_zh) --------------------------------------------------------
/** DESIGN §7 `humanize`: step 1 → 10 分钟后; 1 → 明天; 2–59 → N 天后; ≥ 60 → 约 M 个月后 (M = rnd(N/30)). */
export function humanize(step: 0 | 1, intervalDays: number): string {
  if (step === 1) return zh.study.nextDue.tenMin;
  if (intervalDays === 1) return zh.study.nextDue.tomorrow;
  if (intervalDays < 60) return zh.study.nextDue.days(intervalDays);
  return zh.study.nextDue.months(rnd(intervalDays / 30));
}

export function masterySuggested(s: Pick<SrsSnapshot, 'step' | 'interval_days' | 'consecutive_good'>): boolean {
  return s.step === 0 && s.interval_days >= MASTERY_MIN_INTERVAL && s.consecutive_good >= MASTERY_MIN_CONSEC;
}

/** A fresh `new` row (DESIGN §4 defaults). */
export function freshSnapshot(): SrsSnapshot {
  return { state: 'new', ease: EASE_START, interval_days: 0, step: 0, repetitions: 0, lapses: 0, consecutive_good: 0, due_at: null };
}

/** Snapshot of a bank row (`StudyItem.mine`); a missing row previews like a fresh word. */
export function snapshotOf(mine: Pick<UserWord, 'state' | 'srs'> | null | undefined): SrsSnapshot {
  if (!mine) return freshSnapshot();
  const s: Srs = mine.srs;
  return {
    state: mine.state,
    ease: s.ease,
    interval_days: s.interval_days,
    step: s.step,
    repetitions: s.repetitions,
    lapses: s.lapses,
    consecutive_good: s.consecutive_good,
    due_at: s.due_at,
  };
}

// ---- grade mirror ----------------------------------------------------------------------------------
/** Applies `grade` to `s` exactly as srs.py `grade()` does (master/skip are state-machine actions, not here). */
export function previewGrade(s: SrsSnapshot, g: PreviewGrade, options: PreviewOptions = {}): PreviewResult {
  const now = options.now ?? new Date();
  const useFuzz = options.fuzz ?? true;
  const uwId = options.uwId ?? null;
  const today = localDateOf(now, options.timeZone);
  const applyFuzz = (iv: number) => (useFuzz && uwId !== null ? fuzz(uwId, s.repetitions, iv) : iv);

  let ease = s.ease;
  let interval = s.interval_days;
  let step: 0 | 1 = s.step;
  let lapses = s.lapses;
  let cg = s.consecutive_good;
  let requeue: number | null = null;
  let dueLocal: string | null = null;

  if (s.step === 1 || s.state === 'new') {
    // learning or relearning step
    if (g === 'again') {
      step = 1;
      cg = 0;
      requeue = LEARNING_STEP_MIN;
    } else if (g === 'hard') {
      step = 1;
      requeue = LEARNING_STEP_MIN;
    } else if (s.step === 1) {
      // good on the step → graduate (or relearn at half the old interval)
      interval = interval === 0 ? GRADUATING_INTERVAL : Math.max(1, rnd(interval * LAPSE_FACTOR));
      step = 0;
      cg += 1;
      dueLocal = addDays(today, interval);
    } else {
      // first exposure graded good → the 10-minute step
      step = 1;
      requeue = LEARNING_STEP_MIN;
    }
  } else {
    // review phase (overdue credit)
    const dueLocalPrev = s.due_at ? localDateOf(new Date(s.due_at), options.timeZone) : today;
    const delay = Math.max(0, daysBetween(dueLocalPrev, today));
    if (g === 'again') {
      lapses += 1;
      ease = q2(ease + AGAIN_EASE_DELTA);
      cg = 0;
      step = 1;
      requeue = LEARNING_STEP_MIN;
    } else if (g === 'hard') {
      ease = q2(ease + HARD_EASE_DELTA);
      cg = 0;
      interval = clampInterval(applyFuzz(Math.max(interval + 1, rnd((interval + delay / 4) * HARD_FACTOR))));
      dueLocal = addDays(today, interval);
    } else {
      cg += 1;
      if (cg % EASE_RECOVERY_EVERY === 0) ease = q2(ease + EASE_RECOVERY_DELTA);
      interval = clampInterval(applyFuzz(rnd((interval + delay / 2) * ease)));
      dueLocal = addDays(today, interval);
    }
  }

  const dueAt = step === 1 ? new Date(now.getTime() + LEARNING_STEP_MIN * 60_000).toISOString() : dueLocal ? (toDate(dueLocal)?.toISOString() ?? null) : s.due_at;
  const next: SrsSnapshot = {
    state: 'learning',
    ease,
    interval_days: interval,
    step,
    repetitions: s.repetitions + 1,
    lapses,
    consecutive_good: cg,
    due_at: dueAt,
  };
  return { ...next, requeue_minutes: requeue, due_local_date: dueLocal, mastery_suggested: masterySuggested(next), next_due_zh: humanize(step, interval) };
}

/** The 「下次」 preview strings for the grade bar (`StudyCard.preview`). */
export function previewAll(s: SrsSnapshot, options: PreviewOptions = {}): Record<Grade, string> {
  return {
    again: previewGrade(s, 'again', options).next_due_zh,
    hard: previewGrade(s, 'hard', options).next_due_zh,
    good: previewGrade(s, 'good', options).next_due_zh,
    master: zh.study.nextDue.mastered,
    skip: zh.study.nextDue.skipped,
  };
}
