// FRONTEND §4: the heat-strip tooltip and the history day rows describe activity ("studied N words"), not a total.
import { render } from '@testing-library/react';
import { describe, expect, it } from 'vitest';
import type { DayStats } from '@/api/types';
import { zh } from '@/i18n/zh';
import { dayRowText } from '@/pages/HistoryPage';
import { formatMonthDay } from '@/utils/srsPreview';
import { HeatStrip, heatTooltip } from './HeatStrip';

const day = (over: Partial<DayStats>): DayStats => ({
  date: '2026-10-12',
  graded: 0,
  again: 0,
  hard: 0,
  good: 0,
  mastered: 0,
  known: 0,
  screened: 0,
  added: 0,
  study_minutes: 0,
  batch_id: null,
  batch_total: null,
  batch_done: null,
  offline: false,
  ...over,
});

describe('heatTooltip / dayRowText', () => {
  it('uses history.gradedCount for a day of gradings', () => {
    expect(heatTooltip({ date: '2026-10-12', graded: 32 })).toBe(`${formatMonthDay('2026-10-12')} · ${zh.history.gradedCount(32)}`);
    expect(heatTooltip({ date: '2026-10-12', graded: 32 })).not.toContain(zh.common.total(32));
    expect(dayRowText(day({ graded: 5 }))).toBe(`${formatMonthDay('2026-10-12')} · ${zh.history.gradedCount(5)}`);
    expect(dayRowText(day({ date: '2026-10-13', graded: 41, batch_id: 7, batch_total: 41, batch_done: 41 }))).toBe(`${formatMonthDay('2026-10-13')} · ${zh.history.completed(41, 41)} 🔥`);
  });

  it('puts the tooltip on every past cell as title and aria-label', () => {
    const { container } = render(<HeatStrip days={[{ date: '2026-10-12', graded: 32, goal_met: true }]} today="2026-10-14" weeks={2} />);
    const cell = container.querySelector('li.heat__cell[title]') as HTMLElement;
    expect(cell.getAttribute('title')).toBe(cell.getAttribute('aria-label'));
    const target = Array.from(container.querySelectorAll('li.heat__cell[title]')).find((el) => el.getAttribute('title')?.includes(zh.history.gradedCount(32)));
    expect(target).toBeTruthy();
    expect(target?.classList.contains('heat__cell--goal')).toBe(true);
  });
});
