// HistoryPage (FRONTEND §5.8): a calendar and ONE row per day. The page used to show an unlabelled 12 × 7 heat grid, a list of day
// rows and, below it, the same days again as batch cards; these tests pin what replaced them — each day appears once, with a
// status in words and what the day held, and the calendar and the rows agree on which days are finished.
import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import { MemoryRouter } from 'react-router';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import type { HistoryResponse } from '@/api/endpoints';
import type { BatchSummary, DayStats, Page, Stats, TodayCounts } from '@/api/types';
import { CALENDAR_WEEKS, CALENDAR_WEEKS_MAX } from '@/components/stats/StudyCalendar';
import { zh } from '@/i18n/zh';
import { addDays } from '@/utils/srsPreview';

vi.mock('@/api/endpoints', () => ({ getHistory: vi.fn(), getHistoryBatches: vi.fn(), getStats: vi.fn() }));
vi.mock('@/auth/AuthContext', async (importOriginal) => {
  const actual = await importOriginal<typeof import('@/auth/AuthContext')>();
  const fake = { user: { id: 1 }, settings: { timezone: 'Asia/Shanghai' } };
  return { ...actual, useAuth: () => fake, useOptionalAuth: () => fake };
});

import { getHistory, getHistoryBatches, getStats } from '@/api/endpoints';
import HistoryPage, { HISTORY_DAYS, batchGoalMet, batchStatus, buildDayRows, dayGoalMet, kindsText } from './HistoryPage';

const TODAY = '2026-11-19';

function counts(over: Partial<TodayCounts> = {}): TodayCounts {
  const c = { review: 0, review_done: 0, new: 0, new_done: 0, screen: 0, screen_done: 0, extra: 0, extra_done: 0, pending_content: 0, deferred_reviews: 0, ...over };
  return { total: c.review + c.new + c.screen + c.extra, done: c.review_done + c.new_done + c.screen_done + c.extra_done, ...c };
}

function batch(id: number, local_date: string, c: Partial<TodayCounts> = {}, completed_at: string | null = null): BatchSummary {
  return { id, local_date, status: 'published', trigger: 'scheduled', counts: counts(c), published_at: `${local_date}T01:00:00Z`, completed_at };
}

function day(date: string, over: Partial<DayStats> = {}): DayStats {
  return { date, graded: 0, again: 0, hard: 0, good: 0, mastered: 0, known: 0, screened: 0, added: 0, study_minutes: 0, batch_id: null, batch_total: null, batch_done: null, offline: false, ...over };
}

/** The 84 days GET /api/history answers with, ascending; `over` fills the days that hold something. */
function window84(over: Record<string, Partial<DayStats>> = {}): DayStats[] {
  return Array.from({ length: HISTORY_DAYS }, (_, i) => {
    const date = addDays(TODAY, i - (HISTORY_DAYS - 1));
    return day(date, over[date]);
  });
}

/** The day fields of a batch, as the server derives them (batch_total / batch_done over its visible items). */
const ofBatch = (b: BatchSummary, graded = 0): Partial<DayStats> => ({ batch_id: b.id, batch_total: b.counts.total, batch_done: b.counts.done, graded });

describe('day status and contents', () => {
  it('takes the goal of a batch from the same rule as the server', () => {
    expect(batchGoalMet(batch(1, TODAY, { review: 3, review_done: 3, screen: 15 }))).toBe(true); // every study item final, screening left
    expect(batchGoalMet(batch(1, TODAY, { review: 3, review_done: 2, screen: 15, screen_done: 15 }))).toBe(false);
    expect(batchGoalMet(batch(1, TODAY, { screen: 15, screen_done: 15 }))).toBe(true); // a screen-only batch counts its screen items
    expect(batchGoalMet(batch(1, TODAY, { screen: 15, screen_done: 14 }))).toBe(false);
    expect(batchGoalMet(batch(1, TODAY))).toBe(false); // nothing was due
    expect(batchGoalMet(batch(1, TODAY, { review: 3, review_done: 3, extra: 5 }, '2026-11-19T03:00:00Z'))).toBe(true); // completed once: more words asked for later
    expect(dayGoalMet({ batch_total: 5, batch_done: 5 })).toBe(true);
    expect(dayGoalMet({ batch_total: 0, batch_done: 0 })).toBe(false);
    expect(dayGoalMet({ batch_total: null, batch_done: null })).toBe(false);
  });

  it('names four states: finished, today under way, today untouched, an older day left open', () => {
    expect(batchStatus(batch(1, '2026-11-18', { review: 3, review_done: 3 }), TODAY)).toBe('done');
    expect(batchStatus(batch(1, TODAY, { review: 3, review_done: 3 }), TODAY)).toBe('done');
    expect(batchStatus(batch(1, TODAY, { review: 3, review_done: 1 }), TODAY)).toBe('progress');
    expect(batchStatus(batch(1, TODAY, { review: 3 }), TODAY)).toBe('pending');
    expect(batchStatus(batch(1, '2026-11-18', { review: 3, review_done: 1 }), TODAY)).toBe('unfinished');
    expect(batchStatus(batch(1, '2026-11-18', { review: 3 }), TODAY)).toBe('unfinished');
    expect(new Set(Object.values(zh.history.status)).size).toBe(4);
    expect(zh.history.status.done).toBe(zh.history.dayState.done); // the rows and the calendar legend use one word for a finished day
  });

  it('lists what the day held: totals once all is done, done/total while something is left, absent kinds left out', () => {
    const { review, new: fresh, screen: screening, extra } = zh.today.counts;
    expect(kindsText(counts({ review: 6, review_done: 6, new: 10, new_done: 10, screen: 45, screen_done: 45 }))).toBe(`${review} 6 · ${fresh} 10 · ${screening} 45`);
    expect(kindsText(counts({ review: 5, review_done: 5 }))).toBe(`${review} 5`);
    expect(kindsText(counts({ review: 14, review_done: 5, new: 10, screen: 15 }))).toBe(`${review} 5/14 · ${fresh} 0/10 · ${screening} 0/15`);
    expect(kindsText(counts({ review: 3, review_done: 3, screen: 15, extra: 4, extra_done: 4 }))).toBe(`${review} 3/3 · ${screening} 0/15 · ${extra} 4/4`);
  });
});

describe('buildDayRows', () => {
  const b19 = batch(33, '2026-11-19', { review: 14 });
  const b18 = batch(31, '2026-11-18', { review: 6, review_done: 6 });
  const b15 = batch(25, '2026-11-15');

  it('makes one row per batch — a batch without items is a note, not a card — newest first', () => {
    expect(buildDayRows([b18, b15, b19], [], true)).toEqual([
      { kind: 'batch', date: '2026-11-19', batch: b19 },
      { kind: 'batch', date: '2026-11-18', batch: b18 },
      { kind: 'idle', date: '2026-11-15' },
    ]);
  });

  it('adds the batch-less days that were studied or offline, and no other day', () => {
    const days = [
      day('2026-11-14'), // nothing
      day('2026-11-15', ofBatch(b15)),
      day('2026-11-16', { graded: 4 }),
      day('2026-11-17', { offline: true }),
      day('2026-11-18', ofBatch(b18, 9)),
      day('2026-11-19', ofBatch(b19)),
      day('2026-11-20', { graded: 2, offline: true }), // studied on a day the server was partly down: what was studied wins
    ];
    expect(buildDayRows([b19, b18, b15], days, true).map((r) => `${r.date} ${r.kind}`)).toEqual([
      '2026-11-20 graded',
      '2026-11-19 batch',
      '2026-11-18 batch',
      '2026-11-17 offline',
      '2026-11-16 graded',
      '2026-11-15 idle',
    ]);
  });

  it('holds back a batch-less day older than the oldest loaded batch until the remaining batches are loaded', () => {
    const days = [day('2026-11-01', { graded: 3 }), day('2026-11-17', { graded: 2 })];
    expect(buildDayRows([b19, b18], days, false).map((r) => r.date)).toEqual(['2026-11-19', '2026-11-18']);
    expect(buildDayRows([b19, b18], days, true).map((r) => r.date)).toEqual(['2026-11-19', '2026-11-18', '2026-11-17', '2026-11-01']);
    expect(buildDayRows([], days, true).map((r) => r.date)).toEqual(['2026-11-17', '2026-11-01']);
  });

  it('never shows a date twice when the two requests saw the day differently', () => {
    const days = [day('2026-11-19', { graded: 2 })]; // read before today's batch was published
    expect(buildDayRows([b19], days, true)).toEqual([{ kind: 'batch', date: '2026-11-19', batch: b19 }]);
  });
});

describe('<HistoryPage>', () => {
  const b19 = batch(33, '2026-11-19', { review: 14, new: 10, screen: 15 });
  const b18 = batch(31, '2026-11-18', { review: 6, review_done: 6, new: 10, new_done: 10, screen: 45, screen_done: 45 }, '2026-11-18T07:00:00Z');
  const b16 = batch(27, '2026-11-16', { review: 5, review_done: 5, screen: 15 });
  const b15 = batch(25, '2026-11-15');
  const b10 = batch(15, '2026-11-10', { review: 20, review_done: 12 });
  const batches = [b19, b18, b16, b15, b10];
  const days = (over: Record<string, Partial<DayStats>> = {}) =>
    window84({
      '2026-11-19': ofBatch(b19),
      '2026-11-18': ofBatch(b18, 28),
      '2026-11-16': ofBatch(b16, 6),
      '2026-11-15': ofBatch(b15),
      '2026-11-12': { graded: 4 },
      '2026-11-11': { offline: true },
      '2026-11-10': ofBatch(b10, 14),
      ...over,
    });
  const heatmap = (rows: DayStats[], met: string[]) => rows.map((d) => ({ date: d.date, graded: d.graded, goal_met: met.includes(d.date) }));

  function serve(rows: DayStats[], pages: BatchSummary[][], stats: Partial<Stats> | null = { heatmap: heatmap(rows, ['2026-11-18', '2026-11-16']), stubborn: [] }) {
    const total = pages.flat().length;
    vi.mocked(getHistory).mockResolvedValue({ days: rows, streak_days: 3, longest_streak: 6 } satisfies HistoryResponse);
    vi.mocked(getHistoryBatches).mockImplementation(async (page = 1) => ({ items: pages[page - 1] ?? [], page, page_size: 20, total }) satisfies Page<BatchSummary>);
    if (stats) vi.mocked(getStats).mockResolvedValue(stats as Stats);
    else vi.mocked(getStats).mockRejectedValue(new Error('down'));
    return render(
      <MemoryRouter>
        <HistoryPage />
      </MemoryRouter>,
    );
  }

  const cell = (container: HTMLElement, date: string) => container.querySelector(`td[data-date="${date}"]`) as HTMLElement;
  const dayRows = (container: HTMLElement) => Array.from(container.querySelectorAll('.history__days > li')) as HTMLElement[];

  beforeEach(() => {
    vi.useFakeTimers({ toFake: ['Date'], now: new Date('2026-11-19T04:00:00Z') }); // noon of the 19th in Asia/Shanghai
  });
  afterEach(() => {
    vi.useRealTimers();
    vi.clearAllMocks();
  });

  it('asks for the 84 days ending today', async () => {
    serve(days(), [batches]);
    await screen.findByRole('table');
    expect(vi.mocked(getHistory).mock.calls[0]?.[0]).toEqual({ from: '2026-08-28', to: TODAY });
  });

  it('shows each day once: a status in words and what the day held, linking to the batch', async () => {
    const { container } = serve(days(), [batches]);
    await screen.findByRole('table');
    await waitFor(() => expect(cell(container, '2026-11-16').dataset.state).toBe('done')); // Stats.heatmap is in
    const rows = dayRows(container);
    expect(rows).toHaveLength(7);
    const { review, new: fresh, screen: screening } = zh.today.counts;
    const card = (row: HTMLElement | undefined) => ({
      href: row?.querySelector('a.history__day')?.getAttribute('href') ?? null,
      status: row?.querySelector('.history__status')?.textContent ?? null,
      kinds: row?.querySelector('.history__day-kinds')?.textContent ?? null,
    });
    expect(card(rows[0])).toEqual({ href: '/history/33', status: zh.history.status.pending, kinds: `${review} 0/14 · ${fresh} 0/10 · ${screening} 0/15` });
    expect(rows[0]?.querySelector('.history__day-date')?.textContent).toContain(zh.history.today);
    expect(card(rows[1])).toEqual({ href: '/history/31', status: zh.history.status.done, kinds: `${review} 6 · ${fresh} 10 · ${screening} 45` });
    expect(rows[1]?.querySelector('.history__day-date')?.textContent).not.toContain(zh.history.today);
    expect(card(rows[2])).toEqual({ href: '/history/27', status: zh.history.status.done, kinds: `${review} 5/5 · ${screening} 0/15` });
    expect(card(rows[6])).toEqual({ href: '/history/15', status: zh.history.status.unfinished, kinds: `${review} 12/20` });
    // the days without a card are one muted line each, and lead nowhere
    expect(rows[3]?.textContent).toContain(zh.history.noTasks);
    expect(rows[4]?.textContent).toContain(zh.history.gradedCount(4));
    expect(rows[5]?.textContent).toContain(zh.history.offline);
    expect(rows[5]?.classList.contains('history__note--offline')).toBe(true);
    expect([rows[3], rows[4], rows[5]].map((r) => r?.querySelector('a'))).toEqual([null, null, null]);
    // no second list of the same days, no fraction that reads 0/0
    expect(container.querySelector('.history__batches')).toBeNull();
    expect(container.textContent).not.toContain(zh.history.completed(0, 0));
    expect(screen.getByText(zh.today.streak(3))).toBeTruthy();
    expect(screen.getByText(zh.history.longest(6))).toBeTruthy();
  });

  it('draws the same days on the calendar: finished, partly studied, nothing — and a studied day opens its batch', async () => {
    const { container } = serve(days(), [batches]);
    await screen.findByRole('table');
    await waitFor(() => expect(cell(container, '2026-11-16').dataset.state).toBe('done'));
    expect(container.querySelectorAll('table')).toHaveLength(1);
    expect(container.querySelectorAll('tbody tr')).toHaveLength(CALENDAR_WEEKS);
    expect(cell(container, '2026-11-18').dataset.state).toBe('done');
    expect(cell(container, '2026-11-18').querySelector('a')?.getAttribute('href')).toBe('/history/31');
    expect(cell(container, '2026-11-10').dataset.state).toBe('some');
    expect(cell(container, '2026-11-10').querySelector('a')?.getAttribute('href')).toBe('/history/15');
    expect(cell(container, '2026-11-12').dataset.state).toBe('some'); // studied without a batch: marked, nothing to open
    expect(cell(container, '2026-11-12').querySelector('a')).toBeNull();
    expect(cell(container, '2026-11-15').dataset.state).toBe('none'); // a batch without items is no day to open
    expect(cell(container, '2026-11-15').querySelector('a')).toBeNull();
    expect(cell(container, TODAY).dataset.state).toBe('none');
    expect(cell(container, TODAY).querySelector('a')?.getAttribute('href')).toBe('/history/33');
    expect(screen.queryByRole('button', { name: zh.history.earlier })).toBeNull(); // nothing before these five weeks
  });

  it('falls back to the day rows for the finished days while the stats are not there', async () => {
    const { container } = serve(days(), [batches], null);
    await screen.findByRole('table');
    expect(cell(container, '2026-11-18').dataset.state).toBe('done'); // 61/61
    expect(cell(container, '2026-11-16').dataset.state).toBe('some'); // 5/20 by the fraction alone: screening left
    expect(dayRows(container)).toHaveLength(7);
  });

  it('opens the earlier weeks on demand when one of them was studied', async () => {
    const { container } = serve(days({ '2026-09-08': { graded: 5 } }), [batches]);
    const button = await screen.findByRole('button', { name: zh.history.earlier });
    expect(button.getAttribute('aria-expanded')).toBe('false');
    expect(cell(container, '2026-09-08')).toBeNull();
    fireEvent.click(button);
    expect(container.querySelectorAll('tbody tr')).toHaveLength(CALENDAR_WEEKS_MAX);
    expect(cell(container, '2026-09-08').dataset.state).toBe('some');
    const collapse = screen.getByRole('button', { name: zh.history.collapse });
    expect(collapse.getAttribute('aria-expanded')).toBe('true');
    fireEvent.click(collapse);
    expect(container.querySelectorAll('tbody tr')).toHaveLength(CALENDAR_WEEKS);
  });

  it('loads older batches on demand and then places the batch-less days between them', async () => {
    const b1030 = batch(5, '2026-10-30', { review: 4, review_done: 4 });
    const rows = days({ '2026-11-01': { graded: 3 }, '2026-10-30': ofBatch(b1030, 4) });
    const { container } = serve(rows, [batches, [b1030]]);
    const more = await screen.findByRole('button', { name: zh.common.loadMore });
    expect(dayRows(container).map((r) => r.textContent ?? '').some((t) => t.includes(zh.history.gradedCount(3)))).toBe(false);
    fireEvent.click(more);
    await waitFor(() => expect(dayRows(container)).toHaveLength(9));
    const texts = dayRows(container).map((r) => r.textContent ?? '');
    expect(texts[7]).toContain(zh.history.gradedCount(3));
    expect(dayRows(container)[8]?.querySelector('a')?.getAttribute('href')).toBe('/history/5');
    expect(screen.queryByRole('button', { name: zh.common.loadMore })).toBeNull();
    expect(vi.mocked(getHistoryBatches).mock.calls.map((c) => c[0])).toEqual([1, 2]);
  });

  it('asks again for a page that failed instead of skipping it', async () => {
    const b1030 = batch(5, '2026-10-30', { review: 4, review_done: 4 });
    const { container } = serve(days({ '2026-10-30': ofBatch(b1030, 4) }), [batches, [b1030]]);
    const more = await screen.findByRole('button', { name: zh.common.loadMore });
    vi.mocked(getHistoryBatches).mockRejectedValueOnce(new Error('down'));
    fireEvent.click(more);
    await waitFor(() => expect(vi.mocked(getHistoryBatches).mock.calls).toHaveLength(2));
    await waitFor(() => expect(screen.getByRole('button', { name: zh.common.loadMore }).hasAttribute('disabled')).toBe(false));
    expect(dayRows(container)).toHaveLength(7); // what was loaded stays
    fireEvent.click(screen.getByRole('button', { name: zh.common.loadMore }));
    await waitFor(() => expect(dayRows(container)).toHaveLength(8));
    expect(vi.mocked(getHistoryBatches).mock.calls.map((c) => c[0])).toEqual([1, 2, 2]);
  });

  it('keeps the calendar and offers a retry when the batches cannot be loaded — never a list of the batch-less days alone', async () => {
    vi.mocked(getHistory).mockResolvedValue({ days: days(), streak_days: 3, longest_streak: 6 });
    vi.mocked(getStats).mockRejectedValue(new Error('down'));
    vi.mocked(getHistoryBatches).mockRejectedValueOnce(new Error('down')).mockResolvedValue({ items: batches, page: 1, page_size: 20, total: batches.length });
    const { container } = render(
      <MemoryRouter>
        <HistoryPage />
      </MemoryRouter>,
    );
    await screen.findByRole('table');
    expect(dayRows(container)).toHaveLength(0);
    expect(screen.queryByText(zh.history.empty)).toBeNull();
    fireEvent.click(screen.getByRole('button', { name: zh.common.retry }));
    await waitFor(() => expect(dayRows(container)).toHaveLength(7));
  });

  it('lists the stubborn words under the days', async () => {
    const rows = days();
    const word = { id: 7, display: 'abandon', translation_short: 'x' };
    const { container } = serve(rows, [batches], { heatmap: heatmap(rows, []), stubborn: [word] } as unknown as Stats);
    await screen.findByText('abandon');
    const sections = Array.from(container.querySelectorAll('section.history__section'), (s) => s.getAttribute('aria-label'));
    expect(sections).toEqual([zh.history.calendar, zh.history.days, zh.history.stubborn]);
    expect(screen.getByText('abandon').closest('a')?.getAttribute('href')).toBe('/words/7');
  });

  it('tells a fresh account where its records will appear', async () => {
    serve(window84(), [[]], { heatmap: [], stubborn: [] });
    expect(await screen.findByText(zh.history.empty)).toBeTruthy();
    expect(screen.queryByRole('table')).toBeNull();
  });
});
