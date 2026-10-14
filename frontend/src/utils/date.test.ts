import { describe, expect, it } from 'vitest';
import {
  daysBetween,
  daysUntil,
  detectTimeZone,
  formatDateTime,
  formatFullDate,
  formatLocalDate,
  formatMonthDay,
  formatTime,
  isValidPushTime,
  isValidTimeZone,
  localDateIn,
  normalizePushTime,
  parseIso,
} from './date';

const ISO = '2026-10-15T00:00:00Z'; // 08:00 in Asia/Shanghai, 20:00 the day before in New York

describe('date formatting', () => {
  it('renders API timestamps in the given timezone with zh-CN patterns', () => {
    expect(formatMonthDay(ISO, 'Asia/Shanghai')).toBe('10月15日');
    expect(formatDateTime(ISO, 'Asia/Shanghai')).toBe('10月15日 08:00');
    expect(formatTime(ISO, 'Asia/Shanghai')).toBe('08:00');
    expect(formatFullDate(ISO, 'Asia/Shanghai')).toBe('2026年10月15日');
    expect(formatDateTime(ISO, 'America/New_York')).toBe('10月14日 20:00');
  });

  it('falls back to Asia/Shanghai for a missing or invalid timezone and to "" for bad input', () => {
    expect(formatTime(ISO)).toBe('08:00');
    expect(formatTime(ISO, 'Nope/Zone')).toBe('08:00');
    expect(formatMonthDay(null)).toBe('');
    expect(formatMonthDay('garbage')).toBe('');
    expect(parseIso('garbage')).toBeNull();
    expect(parseIso(ISO)?.toISOString()).toBe('2026-10-15T00:00:00.000Z');
  });

  it('computes local dates and day distances in the timezone', () => {
    expect(localDateIn(ISO, 'Asia/Shanghai')).toBe('2026-10-15');
    expect(localDateIn(ISO, 'America/New_York')).toBe('2026-10-14');
    expect(daysBetween('2026-10-14', '2026-10-17')).toBe(3);
    expect(daysBetween('2026-10-17', '2026-10-14')).toBe(-3);
    expect(daysBetween('bad', '2026-10-14')).toBeNull();
    const now = new Date('2026-10-14T12:00:00Z');
    expect(daysUntil('2026-10-15T00:00:00Z', now, 'Asia/Shanghai')).toBe(1);
    expect(daysUntil('2026-10-15T00:00:00Z', now, 'America/New_York')).toBe(0);
    expect(daysUntil(null, now)).toBeNull();
    expect(formatLocalDate('2026-10-12')).toBe('10月12日');
    expect(formatLocalDate('nope')).toBe('nope');
  });
});

describe('timezone and push time helpers', () => {
  it('validates timezones and detects one', () => {
    expect(isValidTimeZone('Asia/Shanghai')).toBe(true);
    expect(isValidTimeZone('Europe/Berlin')).toBe(true);
    expect(isValidTimeZone('Nope/Zone')).toBe(false);
    expect(isValidTimeZone('')).toBe(false);
    expect(isValidTimeZone(detectTimeZone())).toBe(true);
  });

  it('validates and normalises HH:MM', () => {
    expect(isValidPushTime('08:00')).toBe(true);
    expect(isValidPushTime('23:59')).toBe(true);
    expect(isValidPushTime('24:00')).toBe(false);
    expect(isValidPushTime('8:00')).toBe(false);
    expect(normalizePushTime('8:05')).toBe('08:05');
    expect(normalizePushTime(' 21:30 ')).toBe('21:30');
    expect(normalizePushTime('25:00')).toBeNull();
    expect(normalizePushTime('abc')).toBeNull();
  });
});
