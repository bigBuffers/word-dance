// StageChips — stage chips (zh.stages.*) in canonical order; `cet6_star` adds a star to the cet6 chip (FRONTEND §4).
// `only` narrows the chips to the learner's target stages plus the word's lowest stage (lists and study cards pass
// `settings.stages`; the detail page and onboarding show every stage), and a word outside every official list
// (`stages === []`, `stage_min === null`) renders one dashed "outside the lists" chip instead of nothing.
import type { Stage, StageIndex } from '@/api/types';
import { cx } from '@/components/ui/cx';
import { zh } from '@/i18n/zh';
import './word.css';

// Mirror of backend/wd/schemas.py STAGE_ORDER / STAGE_INDEX: scripts/check_contract.py diffs the Stage / StageIndex
// unions of api/types.ts against schemas.py in order, so this is the only other copy. Index = position + 1
// (xs = 1 … cet6 = 5; migration 0011 renumbered the stored 1..4 to 2..5 — API.md §9.1).
export const STAGE_ORDER: readonly Stage[] = ['xs', 'zk', 'gk', 'cet4', 'cet6'];
export const STAGE_INDEX: Record<Stage, StageIndex> = { xs: 1, zk: 2, gk: 3, cet4: 4, cet6: 5 };
export const STAGE_BY_INDEX: Record<StageIndex, Stage> = { 1: 'xs', 2: 'zk', 3: 'gk', 4: 'cet4', 5: 'cet6' };

export function isStage(value: unknown): value is Stage {
  return typeof value === 'string' && (STAGE_ORDER as readonly string[]).includes(value);
}

export interface StageChipsProps {
  stages: readonly Stage[];
  /** The word's lowest stage — rendered emphasised and never hidden by `only`. */
  stageMin?: StageIndex | null;
  /** Adds a star to the cet6 chip. */
  cet6Star?: boolean;
  /** Show only these stages (the learner's target stages) plus the word's lowest stage; omitted = every stage. */
  only?: readonly Stage[];
  size?: 'sm' | 'md';
  className?: string;
}

export function StageChips({ stages, stageMin = null, cet6Star = false, only, size = 'sm', className }: StageChipsProps) {
  const listClass = cx('chips', size === 'md' && 'chips--md', className);
  if (stages.length === 0) {
    // Outside every official list (PLAN P6): such words appear only under the "all" tab and in search, so say why.
    return (
      <ul className={listClass} aria-label={zh.word.examTags}>
        <li className="chip chip--stage chip--outside">{zh.stages.outside}</li>
      </ul>
    );
  }
  const ordered = STAGE_ORDER.filter((s) => stages.includes(s) && (!only || only.includes(s) || (stageMin !== null && STAGE_INDEX[s] === stageMin)));
  if (ordered.length === 0) return null;
  return (
    <ul className={listClass} aria-label={zh.word.examTags}>
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
