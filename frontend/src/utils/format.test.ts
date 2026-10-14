import { describe, expect, it } from 'vitest';
import { clientEventId, formatBadge, formatBytes, formatDecimal, formatInt, formatPercent, formatUsd, joinDot, parseIntInRange, truncate } from './format';

describe('format helpers', () => {
  it('formats integers, money, bytes and percentages', () => {
    expect(formatInt(4722)).toBe('4,722');
    expect(formatInt(Number.NaN)).toBe('0');
    expect(formatUsd(0.04)).toBe('$0.04');
    expect(formatUsd(0.004)).toBe('$0.004');
    expect(formatUsd(12)).toBe('$12.00');
    expect(formatUsd(Number.NaN)).toBe('$0.00');
    expect(formatBytes(0)).toBe('0 B');
    expect(formatBytes(512)).toBe('512 B');
    expect(formatBytes(1536)).toBe('1.5 KB');
    expect(formatBytes(5 * 1024 * 1024)).toBe('5.0 MB');
    expect(formatBytes(120 * 1024 * 1024)).toBe('120 MB');
    expect(formatPercent(21, 50)).toBe('42%');
    expect(formatPercent(3, 0)).toBe('0%');
    expect(formatPercent(80, 50)).toBe('100%');
    expect(formatDecimal(2.5)).toBe('2.50');
  });

  it('truncates, clamps and caps badges', () => {
    expect(truncate('abandon', 10)).toBe('abandon');
    expect(truncate('abandonment', 6)).toBe('aband…');
    expect(parseIntInRange(' 12 ', 0, 50)).toBe(12);
    expect(parseIntInRange('99', 0, 50)).toBe(50);
    expect(parseIntInRange('-3', 0, 50)).toBe(0);
    expect(parseIntInRange('x', 0, 50)).toBeNull();
    expect(formatBadge(7)).toBe('7');
    expect(formatBadge(120)).toBe('99+');
    expect(joinDot(['a', null, '', 'b'])).toBe('a · b');
  });

  it('generates distinct UUID v4 client event ids', () => {
    const ids = new Set(Array.from({ length: 50 }, () => clientEventId()));
    expect(ids.size).toBe(50);
    for (const id of ids) expect(id).toMatch(/^[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/);
  });
});
