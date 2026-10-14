// date — UTC ISO timestamps from the API (`YYYY-MM-DDTHH:MM:SSZ`, API.md §1) rendered in the user's
// timezone through `Intl` (zh-CN patterns such as 10月15日 / 10月15日 08:00 come from the locale data,
// so no Chinese copy lives in this file — FRONTEND §8), plus timezone detection for onboarding/settings.

export const DEFAULT_TIMEZONE = 'Asia/Shanghai';
export const PUSH_TIME_RE = /^([01]\d|2[0-3]):[0-5]\d$/;
const DAY_MS = 86_400_000;

export function parseIso(value: string | Date | null | undefined): Date | null {
  if (value instanceof Date) return Number.isNaN(value.getTime()) ? null : value;
  if (!value) return null;
  const t = Date.parse(value);
  return Number.isNaN(t) ? null : new Date(t);
}

/** `Intl.DateTimeFormat().resolvedOptions().timeZone`, or the default when unavailable/invalid. */
export function detectTimeZone(): string {
  try {
    const tz = Intl.DateTimeFormat().resolvedOptions().timeZone;
    return tz && isValidTimeZone(tz) ? tz : DEFAULT_TIMEZONE;
  } catch {
    return DEFAULT_TIMEZONE;
  }
}

export function isValidTimeZone(tz: string): boolean {
  if (!tz) return false;
  try {
    new Intl.DateTimeFormat('en-US', { timeZone: tz });
    return true;
  } catch {
    return false;
  }
}

export function isValidPushTime(value: string): boolean {
  return PUSH_TIME_RE.test(value);
}

function safeZone(tz: string | null | undefined): string {
  return tz && isValidTimeZone(tz) ? tz : DEFAULT_TIMEZONE;
}

function format(value: string | Date | null | undefined, tz: string | null | undefined, options: Intl.DateTimeFormatOptions): string {
  const d = parseIso(value);
  if (!d) return '';
  try {
    return new Intl.DateTimeFormat('zh-CN', { timeZone: safeZone(tz), ...options }).format(d);
  } catch {
    return '';
  }
}

/** `10月15日` in `tz`. */
export function formatMonthDay(value: string | Date | null | undefined, tz?: string | null): string {
  return format(value, tz, { month: 'long', day: 'numeric' });
}

/** `2026年10月15日` in `tz`. */
export function formatFullDate(value: string | Date | null | undefined, tz?: string | null): string {
  return format(value, tz, { year: 'numeric', month: 'long', day: 'numeric' });
}

/** `10月15日 08:00` in `tz` (24-hour clock). */
export function formatDateTime(value: string | Date | null | undefined, tz?: string | null): string {
  return format(value, tz, { month: 'long', day: 'numeric', hour: '2-digit', minute: '2-digit', hourCycle: 'h23' });
}

/** `08:00` in `tz` (24-hour clock). */
export function formatTime(value: string | Date | null | undefined, tz?: string | null): string {
  return format(value, tz, { hour: '2-digit', minute: '2-digit', hourCycle: 'h23' });
}

/** The local calendar date `YYYY-MM-DD` of an instant in `tz`. */
export function localDateIn(value: string | Date, tz?: string | null): string {
  const d = parseIso(value);
  if (!d) return '';
  try {
    return new Intl.DateTimeFormat('en-CA', { timeZone: safeZone(tz), year: 'numeric', month: '2-digit', day: '2-digit' }).format(d);
  } catch {
    return '';
  }
}

/** Parses a `YYYY-MM-DD` local date as UTC midnight (for day arithmetic only). */
export function parseLocalDate(value: string): Date | null {
  const m = /^(\d{4})-(\d{2})-(\d{2})$/.exec(value);
  if (!m) return null;
  const d = new Date(Date.UTC(Number(m[1]), Number(m[2]) - 1, Number(m[3])));
  return Number.isNaN(d.getTime()) ? null : d;
}

/** Calendar days from `from` to `to` (both `YYYY-MM-DD`); negative when `to` is earlier. */
export function daysBetween(from: string, to: string): number | null {
  const a = parseLocalDate(from);
  const b = parseLocalDate(to);
  if (!a || !b) return null;
  return Math.round((b.getTime() - a.getTime()) / DAY_MS);
}

/** Calendar days from `now` until `value`, both taken in `tz` (0 = today, 1 = tomorrow, negative = past). */
export function daysUntil(value: string | Date | null | undefined, now: Date = new Date(), tz?: string | null): number | null {
  const d = parseIso(value);
  if (!d) return null;
  return daysBetween(localDateIn(now, tz), localDateIn(d, tz));
}

/** `YYYY-MM-DD` as a local month/day label (`10月15日`); invalid input renders as the raw string. */
export function formatLocalDate(value: string): string {
  const d = parseLocalDate(value);
  if (!d) return value;
  return formatMonthDay(d, 'UTC');
}

/** Normalises `H:MM` / `HH:MM` input to `HH:MM`; `null` when it is not a time. */
export function normalizePushTime(value: string): string | null {
  const m = /^\s*(\d{1,2}):(\d{2})\s*$/.exec(value);
  if (!m) return null;
  const h = Number(m[1]);
  const min = Number(m[2]);
  if (h > 23 || min > 59) return null;
  return `${String(h).padStart(2, '0')}:${String(min).padStart(2, '0')}`;
}
