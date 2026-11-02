import { render, screen } from '@testing-library/react';
import { describe, expect, it } from 'vitest';
import type { Srs } from '@/api/types';
import { zh } from '@/i18n/zh';
import { classifyDue, formatDue, formatDueSentence, StateBadge, stateLabel } from './StateBadge';

const DAY = 86_400_000;
// a local noon so that whole-day offsets never cross a day boundary
const now = new Date(2026, 9, 14, 12, 0, 0).getTime();
const plusDays = (d: number) => new Date(now + d * DAY).toISOString();

const srs = (over: Partial<Srs> = {}): Srs => ({
  ease: 2.5,
  interval_days: 3,
  step: 0,
  repetitions: 2,
  lapses: 0,
  consecutive_good: 2,
  due_at: plusDays(3),
  last_graded_at: null,
  mastery_suggested: false,
  ...over,
});

describe('formatDue', () => {
  it('mirrors the DESIGN §7 humanize thresholds', () => {
    expect(formatDue(plusDays(1), 1, now)).toBe(zh.study.nextDue.tenMin);
    expect(formatDue(null, 1, now)).toBe(zh.study.nextDue.tenMin);
    expect(formatDue(plusDays(1), 0, now)).toBe(zh.study.nextDue.tomorrow);
    expect(formatDue(plusDays(2), 0, now)).toBe(zh.study.nextDue.days(2));
    expect(formatDue(plusDays(8), 0, now)).toBe(zh.study.nextDue.days(8));
    expect(formatDue(plusDays(59), 0, now)).toBe(zh.study.nextDue.days(59));
    expect(formatDue(plusDays(60), 0, now)).toBe(zh.study.nextDue.months(2));
    expect(formatDue(plusDays(133), 0, now)).toBe(zh.study.nextDue.months(4));
    expect(formatDue(plusDays(180), 0, now)).toBe(zh.study.nextDue.months(6));
  });

  it('labels a due review (the most actionable state): overdue for earlier days, today for the due day at any hour and after the elapsed step', () => {
    expect(formatDue(plusDays(-1), 0, now)).toBe(zh.study.nextDue.overdue);
    expect(formatDue(plusDays(-30), 0, now)).toBe(zh.study.nextDue.overdue);
    expect(formatDue(new Date(now - 3_600_000).toISOString(), 0, now)).toBe(zh.study.nextDue.today);
    expect(formatDue(new Date(now + 3_600_000).toISOString(), 0, now)).toBe(zh.study.nextDue.today);
    expect(formatDue(plusDays(-1), 1, now)).toBe(zh.study.nextDue.today);
    expect(classifyDue(plusDays(-1), 0, now)).toBe('overdue');
    expect(classifyDue(plusDays(3), 0, now)).toBe('future');
  });

  it('returns null only when the due date is missing or unparsable', () => {
    expect(formatDue(null, 0, now)).toBeNull();
    expect(formatDue('garbage', 0, now)).toBeNull();
    expect(formatDueSentence(null, 0, now)).toBeNull();
  });

  it('formatDueSentence wraps future / today labels in bank.dueIn and leaves overdue bare', () => {
    expect(formatDueSentence(plusDays(3), 0, now)).toBe(zh.bank.dueIn(zh.study.nextDue.days(3)));
    expect(formatDueSentence(new Date(now - 3_600_000).toISOString(), 0, now)).toBe(zh.bank.dueIn(zh.study.nextDue.today));
    expect(formatDueSentence(plusDays(-1), 0, now)).toBe(zh.study.nextDue.overdue);
  });
});

describe('StateBadge', () => {
  it('renders the state label and the due suffix for learning words', () => {
    render(<StateBadge state="learning" srs={srs()} now={now} />);
    expect(screen.getByText(zh.bank.tabs.learning, { exact: false }).textContent).toBe(`${zh.bank.tabs.learning} · ${zh.study.nextDue.days(3)}`);
  });

  it('shows the overdue suffix for a learning word whose review date has passed', () => {
    render(<StateBadge state="learning" srs={srs({ due_at: plusDays(-2) })} now={now} />);
    expect(screen.getByText(zh.bank.tabs.learning, { exact: false }).textContent).toBe(`${zh.bank.tabs.learning} · ${zh.study.nextDue.overdue}`);
  });

  it('renders the unmarked label for null and no suffix for other states', () => {
    const { rerender } = render(<StateBadge state={null} />);
    expect(screen.getByText(zh.vocab.status.unmarked)).toBeTruthy();
    rerender(<StateBadge state="mastered" srs={srs()} now={now} />);
    expect(screen.getByText(zh.bank.tabs.mastered).textContent).toBe(zh.bank.tabs.mastered);
    expect(stateLabel('removed')).toBe(zh.bank.tabs.removed);
  });
});
