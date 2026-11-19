// StudyCalendar — the history page's calendar (FRONTEND §4). Weeks are rows, Monday first, like a wall calendar, ending with the
// week of `today`; every day shows its date and one of three states: the day's goal met (filled), studied without finishing
// (tinted), nothing. Today reads zh.history.todayMark; the first cell and every first of a month read M/D. A day the page
// gives a link (its batch) opens that day. The state is also spelt out per cell (`title` + hidden text): touch has no hover.
import { Link } from 'react-router';
import { cx } from '@/components/ui/cx';
import { zh } from '@/i18n/zh';
import { addDays, formatMonthDay, parseLocalDate } from '@/utils/srsPreview';
import './stats.css';

export interface CalendarDay {
  date: string;
  graded: number;
  goal_met: boolean;
}

/** `done` = the day's goal was met · `some` = something was graded that day · `none`. */
export type DayState = 'done' | 'some' | 'none';

export interface CalendarCell {
  date: string;
  state: DayState;
  /** Day of the month, M/D on the first cell and on a first of the month, zh.history.todayMark today. */
  label: string;
  today: boolean;
  future: boolean;
}

/** Rows of the short calendar, and of the long one behind "show earlier" (the 84 days the page loads). */
export const CALENDAR_WEEKS = 5;
export const CALENDAR_WEEKS_MAX = 12;

/** ISO weekday 1 (Mon) … 7 (Sun) of a local date. */
export function isoWeekday(localDate: string): number {
  const p = parseLocalDate(localDate);
  if (!p) return 1;
  const d = new Date(Date.UTC(p[0], p[1] - 1, p[2])).getUTCDay();
  return d === 0 ? 7 : d;
}

/** zh.history.weekday of a local date. */
export function weekdayName(localDate: string): string {
  return zh.history.weekday(zh.history.weekdays.charAt(isoWeekday(localDate) - 1));
}

export function dayState(day: Pick<CalendarDay, 'graded' | 'goal_met'> | undefined): DayState {
  if (!day) return 'none';
  if (day.goal_met) return 'done';
  return day.graded > 0 ? 'some' : 'none';
}

/** Monday of the first row: `weeks` rows ending with the week of `today`. */
export function calendarStart(today: string, weeks = CALENDAR_WEEKS): string {
  return addDays(today, 7 - isoWeekday(today) - (weeks * 7 - 1));
}

function cellLabel(date: string, today: string, first: boolean): string {
  if (date === today) return zh.history.todayMark;
  const p = parseLocalDate(date);
  if (!p) return date;
  return first || p[2] === 1 ? `${p[1]}/${p[2]}` : String(p[2]);
}

/** `weeks` rows of seven chronological cells; the last row is the week of `today`, its later days are `future`. */
export function buildCalendar(days: readonly CalendarDay[], today: string, weeks = CALENDAR_WEEKS): CalendarCell[][] {
  const byDate = new Map(days.map((d) => [d.date, d]));
  const start = calendarStart(today, weeks);
  const rows: CalendarCell[][] = [];
  for (let w = 0; w < weeks; w++) {
    const row: CalendarCell[] = [];
    for (let i = 0; i < 7; i++) {
      const date = addDays(start, w * 7 + i);
      const future = date > today;
      row.push({ date, state: future ? 'none' : dayState(byDate.get(date)), label: cellLabel(date, today, w === 0 && i === 0), today: date === today, future });
    }
    rows.push(row);
  }
  return rows;
}

/** Whether a week before the short calendar holds a studied day: "show earlier" is offered only then. */
export function hasEarlier(days: readonly CalendarDay[], today: string, weeks = CALENDAR_WEEKS): boolean {
  const start = calendarStart(today, weeks);
  return days.some((d) => d.date < start && dayState(d) !== 'none');
}

/** A cell in words: the date with its weekday, and the state of a day that has come. */
export function cellTitle(cell: Pick<CalendarCell, 'date' | 'state' | 'future'>): string {
  const date = `${formatMonthDay(cell.date)} ${weekdayName(cell.date)}`;
  return cell.future ? date : `${date} · ${zh.history.dayState[cell.state]}`;
}

export interface StudyCalendarProps {
  days: readonly CalendarDay[];
  /** Reference local date (`YYYY-MM-DD`). */
  today: string;
  weeks?: number;
  /** Where a day leads; a day without a link is plain text. */
  hrefFor?: (date: string) => string | null;
  className?: string;
}

export function StudyCalendar({ days, today, weeks = CALENDAR_WEEKS, hrefFor, className }: StudyCalendarProps) {
  const rows = buildCalendar(days, today, weeks);
  return (
    <div className={cx('cal', className)}>
      <table className="cal__grid" aria-label={zh.history.calendar}>
        <thead>
          <tr>
            {Array.from(zh.history.weekdays, (d) => (
              <th key={d} scope="col" abbr={zh.history.weekday(d)}>
                {d}
              </th>
            ))}
          </tr>
        </thead>
        <tbody>
          {rows.map((row) => (
            <tr key={row[0]?.date}>
              {row.map((cell) => {
                const title = cellTitle(cell);
                const href = cell.future ? null : (hrefFor?.(cell.date) ?? null);
                const day = (
                  <>
                    <span
                      className={cx('cal__day', `cal__day--${cell.state}`, cell.today && 'cal__day--today', cell.future && 'cal__day--future', cell.label.includes('/') && 'cal__day--month')}
                      aria-hidden="true"
                    >
                      {cell.label}
                    </span>
                    <span className="visually-hidden">{title}</span>
                  </>
                );
                return (
                  <td key={cell.date} data-date={cell.date} data-state={cell.future ? undefined : cell.state}>
                    {href ? (
                      <Link className="cal__cell" to={href} title={title}>
                        {day}
                      </Link>
                    ) : (
                      <span className="cal__cell" title={cell.future ? undefined : title}>
                        {day}
                      </span>
                    )}
                  </td>
                );
              })}
            </tr>
          ))}
        </tbody>
      </table>
      <ul className="cal__legend">
        <li>
          <span className="cal__dot cal__dot--done" aria-hidden="true" />
          {zh.history.dayState.done}
        </li>
        <li>
          <span className="cal__dot cal__dot--some" aria-hidden="true" />
          {zh.history.dayState.some}
        </li>
      </ul>
    </div>
  );
}
