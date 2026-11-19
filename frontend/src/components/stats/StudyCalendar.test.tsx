// FRONTEND §4: the history page's calendar reads like a wall calendar — weeks are rows (Monday first) ending with the week of
// today, every day carries its date and one of three states, and the state is also there in words (touch has no hover).
import { render } from '@testing-library/react';
import { MemoryRouter } from 'react-router';
import { describe, expect, it } from 'vitest';
import { zh } from '@/i18n/zh';
import { formatMonthDay } from '@/utils/srsPreview';
import { CALENDAR_WEEKS_MAX, StudyCalendar, buildCalendar, calendarStart, cellTitle, dayState, hasEarlier, isoWeekday, weekdayName, type CalendarDay } from './StudyCalendar';

const TODAY = '2026-11-19'; // a Thursday
const DAYS: CalendarDay[] = [
  { date: '2026-11-02', graded: 20, goal_met: true },
  { date: '2026-11-04', graded: 0, goal_met: false },
  { date: '2026-11-10', graded: 12, goal_met: false },
  { date: '2026-11-11', graded: 0, goal_met: true }, // a screen-only batch, all screened: the goal without a grading
  { date: '2026-11-19', graded: 3, goal_met: false },
  { date: '2026-11-20', graded: 9, goal_met: true }, // never read: the day has not come
];

describe('calendar layout', () => {
  it('knows the weekday of a local date, Monday first', () => {
    expect([isoWeekday('2026-11-16'), isoWeekday(TODAY), isoWeekday('2026-11-22')]).toEqual([1, 4, 7]);
    expect(weekdayName(TODAY)).toBe(zh.history.weekday(zh.history.weekdays.charAt(3)));
    expect(zh.history.weekdays).toHaveLength(7);
  });

  it('ends with the week of today and starts on a Monday', () => {
    expect(calendarStart(TODAY)).toBe('2026-10-19');
    expect(calendarStart(TODAY, CALENDAR_WEEKS_MAX)).toBe('2026-08-31');
    expect(calendarStart('2026-11-22')).toBe('2026-10-19'); // a Sunday closes its own week
    expect(calendarStart('2026-11-23')).toBe('2026-10-26'); // a Monday opens the next one
    const rows = buildCalendar(DAYS, TODAY);
    expect(rows.map((r) => r.length)).toEqual([7, 7, 7, 7, 7]);
    expect(rows[0]?.[0]?.date).toBe('2026-10-19');
    expect(rows[4]?.[6]?.date).toBe('2026-11-22');
    expect(buildCalendar(DAYS, TODAY, CALENDAR_WEEKS_MAX)).toHaveLength(12);
  });

  it('labels a day with its date: M/D on the first cell and on a first of the month, the today mark today', () => {
    const cells = new Map(buildCalendar(DAYS, TODAY).flat().map((c) => [c.date, c]));
    expect(cells.get('2026-10-19')?.label).toBe('10/19');
    expect(cells.get('2026-10-20')?.label).toBe('20');
    expect(cells.get('2026-11-01')?.label).toBe('11/1');
    expect(cells.get('2026-11-02')?.label).toBe('2');
    expect(cells.get(TODAY)).toMatchObject({ label: zh.history.todayMark, today: true, future: false });
    expect(cells.get('2026-11-18')).toMatchObject({ today: false, future: false });
  });

  it('gives every day one of three states; a day that has not come has none', () => {
    expect(dayState(undefined)).toBe('none');
    const cells = new Map(buildCalendar(DAYS, TODAY).flat().map((c) => [c.date, c]));
    expect(cells.get('2026-11-02')?.state).toBe('done');
    expect(cells.get('2026-11-11')?.state).toBe('done');
    expect(cells.get('2026-11-10')?.state).toBe('some');
    expect(cells.get(TODAY)?.state).toBe('some');
    expect(cells.get('2026-11-04')?.state).toBe('none');
    expect(cells.get('2026-11-05')?.state).toBe('none'); // no row at all
    expect(cells.get('2026-11-20')).toMatchObject({ state: 'none', future: true });
  });

  it('offers the earlier weeks only when one of them holds a studied day', () => {
    expect(hasEarlier(DAYS, TODAY)).toBe(false);
    expect(hasEarlier([...DAYS, { date: '2026-10-18', graded: 0, goal_met: false }], TODAY)).toBe(false);
    expect(hasEarlier([...DAYS, { date: '2026-10-19', graded: 4, goal_met: false }], TODAY)).toBe(false); // the first cell of the short calendar
    expect(hasEarlier([...DAYS, { date: '2026-10-18', graded: 4, goal_met: false }], TODAY)).toBe(true);
    expect(hasEarlier([...DAYS, { date: '2026-09-01', graded: 0, goal_met: true }], TODAY)).toBe(true);
  });

  it('says a day in words: date, weekday and — once the day has come — its state', () => {
    const date = `${formatMonthDay('2026-11-10')} ${weekdayName('2026-11-10')}`;
    expect(cellTitle({ date: '2026-11-10', state: 'some', future: false })).toBe(`${date} · ${zh.history.dayState.some}`);
    expect(cellTitle({ date: '2026-11-10', state: 'none', future: true })).toBe(date);
    expect(new Set(Object.values(zh.history.dayState)).size).toBe(3);
  });
});

describe('<StudyCalendar>', () => {
  const view = (weeks?: number) =>
    render(
      <MemoryRouter>
        <StudyCalendar days={DAYS} today={TODAY} weeks={weeks} hrefFor={(date) => (date === '2026-11-02' || date === '2026-11-20' ? `/history/${date}` : null)} />
      </MemoryRouter>,
    );

  it('is a table with the seven weekdays as its header and one row per week', () => {
    const { container } = view();
    expect(Array.from(container.querySelectorAll('thead th'), (th) => th.textContent).join('')).toBe(zh.history.weekdays);
    expect(container.querySelectorAll('tbody tr')).toHaveLength(5);
    expect(container.querySelectorAll('tbody td')).toHaveLength(35);
    expect(view(CALENDAR_WEEKS_MAX).container.querySelectorAll('tbody tr')).toHaveLength(12);
  });

  it('marks each day with its state, in colour and in words', () => {
    const { container } = view();
    const cell = (date: string) => container.querySelector(`td[data-date="${date}"]`) as HTMLElement;
    expect(cell('2026-11-02').dataset.state).toBe('done');
    expect(cell('2026-11-02').querySelector('.cal__day')?.classList.contains('cal__day--done')).toBe(true);
    expect(cell('2026-11-10').querySelector('.cal__day')?.classList.contains('cal__day--some')).toBe(true);
    expect(cell('2026-11-02').querySelector('.visually-hidden')?.textContent).toBe(cellTitle({ date: '2026-11-02', state: 'done', future: false }));
    expect(cell('2026-11-02').querySelector('.cal__cell')?.getAttribute('title')).toContain(zh.history.dayState.done);
    expect(cell(TODAY).querySelector('.cal__day')?.classList.contains('cal__day--today')).toBe(true);
    expect(cell(TODAY).querySelector('.cal__day')?.textContent).toBe(zh.history.todayMark);
    // a day that has not come: no state, no tooltip
    expect(cell('2026-11-20').dataset.state).toBeUndefined();
    expect(cell('2026-11-20').querySelector('.cal__cell')?.hasAttribute('title')).toBe(false);
    expect(cell('2026-11-20').querySelector('.visually-hidden')?.textContent).not.toContain(zh.history.dayState.none);
  });

  it('links a day the page gives a target, never a day that has not come', () => {
    const { container } = view();
    const cell = (date: string) => container.querySelector(`td[data-date="${date}"]`) as HTMLElement;
    expect(cell('2026-11-02').querySelector('a.cal__cell')?.getAttribute('href')).toBe('/history/2026-11-02');
    expect(cell('2026-11-10').querySelector('a')).toBeNull();
    expect(cell('2026-11-20').querySelector('a')).toBeNull();
    expect(container.querySelectorAll('a.cal__cell')).toHaveLength(1);
  });

  it('explains the two marks under the grid', () => {
    const { container } = view();
    expect(Array.from(container.querySelectorAll('.cal__legend li'), (li) => li.textContent)).toEqual([zh.history.dayState.done, zh.history.dayState.some]);
  });
});
