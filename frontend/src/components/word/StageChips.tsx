// StageChips — stage chips (zh.stages.*) in canonical order; `cet6_star` adds a star to the cet6 chip (FRONTEND §4).
import type { Stage, StageIndex } from '@/api/types';
import { cx } from '@/components/ui/cx';
import { zh } from '@/i18n/zh';
import './word.css';

export const STAGE_ORDER: readonly Stage[] = ['zk', 'gk', 'cet4', 'cet6'];
export const STAGE_INDEX: Record<Stage, StageIndex> = { zk: 1, gk: 2, cet4: 3, cet6: 4 };
export const STAGE_BY_INDEX: Record<StageIndex, Stage> = { 1: 'zk', 2: 'gk', 3: 'cet4', 4: 'cet6' };

export function isStage(value: unknown): value is Stage {
  return typeof value === 'string' && (STAGE_ORDER as readonly string[]).includes(value);
}

export interface StageChipsProps {
  stages: readonly Stage[];
  /** The word's lowest stage — rendered emphasised. */
  stageMin?: StageIndex | null;
  /** Adds a star to the cet6 chip. */
  cet6Star?: boolean;
  size?: 'sm' | 'md';
  className?: string;
}

export function StageChips({ stages, stageMin = null, cet6Star = false, size = 'sm', className }: StageChipsProps) {
  const ordered = STAGE_ORDER.filter((s) => stages.includes(s));
  if (ordered.length === 0) return null;
  return (
    <ul className={cx('chips', size === 'md' && 'chips--md', className)} aria-label={zh.word.examTags}>
      {ordered.map((stage) => (
        <li key={stage} className={cx('chip', 'chip--stage', stageMin === STAGE_INDEX[stage] && 'chip--min')}>
          {zh.stages[stage]}
          {stage === 'cet6' && cet6Star && (
            <span className="chip__star" role="img" aria-label={zh.stages.star} title={zh.stages.star}>
              ★
            </span>
          )}
        </li>
      ))}
    </ul>
  );
}
