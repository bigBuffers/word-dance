// HeatStrip — 12 weeks × 7 days of study activity (FRONTEND §4): 5 intensity levels, a ring on days
// whose goal was met, tooltip "<date> · total(32)" (`title` + `aria-label`). Weeks are columns
// (Monday first); the window is the 12 full weeks ending with the week of `today`.
import { zh } from '@/i18n/zh';
import { addDays, formatMonthDay, localDateOf, parseLocalDate } from '@/utils/srsPreview';
import './stats.css';

export interface HeatDay {
  date: string;
  graded: number;
  goal_met: boolean;
}

export interface HeatStripProps {
  days: readonly HeatDay[];
  /** Reference local date (`YYYY-MM-DD`, default: today in `timeZone`). */
  today?: string;
  timeZone?: string;
  weeks?: number;
  className?: string;
}

export interface HeatCell {
  date: string;
  graded: number;
  goalMet: boolean;
  /** 0 = no activity … 4 = top quarter of the strip's maximum. */
  level: 0 | 1 | 2 | 3 | 4;
  future: boolean;
}

/** ISO weekday 1 (Mon) … 7 (Sun) of a local date. */
export function isoWeekday(localDate: string): number {
  const p = parseLocalDate(localDate);
  if (!p) return 1;
  const d = new Date(Date.UTC(p[0], p[1] - 1, p[2])).getUTCDay();
  return d === 0 ? 7 : d;
}

export function heatLevel(graded: number, max: number): HeatCell['level'] {
  if (graded <= 0 || max <= 0) return 0;
  const q = graded / max;
  if (q <= 0.25) return 1;
  if (q <= 0.5) return 2;
  if (q <= 0.75) return 3;
  return 4;
}

/** Lays the cells out: `weeks × 7` chronological cells ending on the Sunday of `today`'s week. */
export function buildHeatCells(days: readonly HeatDay[], today: string, weeks = 12): HeatCell[] {
  const byDate = new Map(days.map((d) => [d.date, d]));
  const max = days.reduce((m, d) => Math.max(m, d.graded), 0);
  const end = addDays(today, 7 - isoWeekday(today)); // Sunday of the current week
  const start = addDays(end, -(weeks * 7 - 1));
  const cells: HeatCell[] = [];
  for (let i = 0; i < weeks * 7; i++) {
    const date = addDays(start, i);
    const day = byDate.get(date);
    const graded = day?.graded ?? 0;
    cells.push({ date, graded, goalMet: day?.goal_met ?? false, level: heatLevel(graded, max), future: date > today });
  }
  return cells;
}

export function heatTooltip(cell: Pick<HeatCell, 'date' | 'graded'>): string {
  return `${formatMonthDay(cell.date)} · ${zh.common.total(cell.graded)}`;
}

export function HeatStrip({ days, today, timeZone, weeks = 12, className }: HeatStripProps) {
  const ref = today ?? localDateOf(new Date(), timeZone);
  const cells = buildHeatCells(days, ref, weeks);
  return (
    <div className={['heat', className].filter(Boolean).join(' ')}>
      <ul className="heat__grid" aria-label={zh.history.heat} style={{ gridTemplateColumns: `repeat(${weeks}, 1fr)` }}>
        {cells.map((cell) => {
          const tip = heatTooltip(cell);
          return (
            <li
              key={cell.date}
              className={['heat__cell', cell.goalMet && 'heat__cell--goal', cell.future && 'heat__cell--future'].filter(Boolean).join(' ')}
              data-level={cell.level}
              title={cell.future ? undefined : tip}
              aria-label={cell.future ? undefined : tip}
              aria-hidden={cell.future || undefined}
            />
          );
        })}
      </ul>
      <div className="heat__legend" aria-hidden="true">
        {[0, 1, 2, 3, 4].map((level) => (
          <span key={level} className="heat__cell heat__cell--legend" data-level={level} />
        ))}
      </div>
    </div>
  );
}
