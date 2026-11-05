// StageChips (FRONTEND §4, PLAN §6 S4): the five-stage canonical order mirrored from schemas.py, the lowest stage
// emphasised by its 1–5 index, `only` narrowing to the learner's target stages plus the lowest stage, and the dashed
// outside-the-lists chip for a word that is in no official list.
import { render, screen } from '@testing-library/react';
import { describe, expect, it } from 'vitest';
import { zh } from '@/i18n/zh';
import { STAGE_BY_INDEX, STAGE_INDEX, STAGE_ORDER, StageChips, isStage } from './StageChips';

const chips = () => screen.getAllByRole('listitem');
const texts = () => chips().map((li) => li.textContent);

describe('stage constants', () => {
  it('mirror schemas.py: five codes, index = position + 1, the two maps are inverses', () => {
    expect(STAGE_ORDER).toEqual(['xs', 'zk', 'gk', 'cet4', 'cet6']);
    STAGE_ORDER.forEach((stage, i) => {
      expect(STAGE_INDEX[stage]).toBe(i + 1);
      expect(STAGE_BY_INDEX[STAGE_INDEX[stage]]).toBe(stage);
    });
    expect(isStage('xs')).toBe(true);
    expect(isStage('all')).toBe(false);
    expect(isStage(1)).toBe(false);
  });
});

describe('StageChips', () => {
  it('renders every stage in canonical order whatever the input order', () => {
    render(<StageChips stages={['cet6', 'xs', 'cet4', 'zk', 'gk']} />);
    expect(texts()).toEqual([zh.stages.xs, zh.stages.zk, zh.stages.gk, zh.stages.cet4, zh.stages.cet6]);
  });

  it('emphasises the lowest stage by its 1–5 index', () => {
    render(<StageChips stages={['xs', 'zk', 'gk', 'cet4']} stageMin={1} />);
    const [first, ...rest] = chips();
    expect(first?.classList.contains('chip--min')).toBe(true);
    expect(rest.every((li) => !li.classList.contains('chip--min'))).toBe(true);
  });

  it('`only` keeps the target stages and never drops the lowest stage', () => {
    // a primary-school word that is also in zk / gk / cet4; the learner targets xs only → one chip
    const view = render(<StageChips stages={['xs', 'zk', 'gk', 'cet4']} stageMin={1} only={['xs']} />);
    expect(texts()).toEqual([zh.stages.xs]);
    view.unmount();
    // a cet4 word for the same learner: nothing in `only`, so the lowest stage is kept
    render(<StageChips stages={['cet4', 'cet6']} stageMin={4} only={['xs']} />);
    expect(texts()).toEqual([zh.stages.cet4]);
  });

  it('`only` with several targets renders the intersection plus the lowest stage, in order, with the star', () => {
    render(<StageChips stages={['xs', 'zk', 'gk', 'cet4', 'cet6']} stageMin={1} only={['gk', 'cet6']} cet6Star />);
    expect(texts()).toEqual([zh.stages.xs, zh.stages.gk, `${zh.stages.cet6}★`]);
  });

  it('a word outside every list renders the single dashed chip', () => {
    render(<StageChips stages={[]} stageMin={null} only={['xs']} />);
    expect(texts()).toEqual([zh.stages.outside]);
    expect(chips()[0]?.classList.contains('chip--outside')).toBe(true);
    expect(chips()[0]?.classList.contains('chip--min')).toBe(false);
  });
});
