// Pure helpers of the vocabulary browser (optimistic state, toast copy, undo eligibility — FRONTEND 5.5 / API.md 26)
// plus the accessible names of the filter controls and the stage tabs (PLAN §6 S4: one tab per stage, the new-only
// switch hidden on the lowest stage and labelled per stage elsewhere, rows narrowed to `settings.stages`).
import { fireEvent, render, screen, within } from '@testing-library/react';
import { MemoryRouter } from 'react-router';
import { afterEach, describe, expect, it, vi } from 'vitest';
import { getVocab } from '@/api/endpoints';
import type { Page, WordBrief } from '@/api/types';
import { STAGE_ORDER } from '@/components/word/StageChips';
import { zh } from '@/i18n/zh';
import VocabPage, { TABS, markToast, markUndoable, optimisticState } from './VocabPage';

vi.mock('@/api/endpoints', async (importOriginal) => ({
  ...(await importOriginal<typeof import('@/api/endpoints')>()),
  getVocab: vi.fn(async () => ({ items: [], page: 1, page_size: 50, total: 0 })),
  getVocabLetters: vi.fn(async () => ({ items: [] })),
}));
vi.mock('@/auth/AuthContext', () => {
  const fake = { settings: { stages: ['xs', 'zk'], current_stage: 'xs' } }; // the rows narrow their chips to these (`onlyStages`)
  return { useAuth: () => fake, useOptionalAuth: () => fake };
});

const TAB_KEY = 'wd.vocabTab';
const renderAt = (tab: string) => {
  window.localStorage.setItem(TAB_KEY, JSON.stringify(tab));
  return render(
    <MemoryRouter>
      <VocabPage />
    </MemoryRouter>,
  );
};

describe('stage tabs', () => {
  afterEach(() => window.localStorage.removeItem(TAB_KEY));

  it('shows one tab per stage after the all tab, in canonical order, and no new-only switch on all', () => {
    expect(TABS).toEqual(['all', ...STAGE_ORDER]);
    expect(TABS).toHaveLength(STAGE_ORDER.length + 1);
    renderAt('all');
    expect(screen.getAllByRole('tab').map((t) => t.textContent)).toEqual([zh.common.all, ...STAGE_ORDER.map((s) => zh.stages[s])]);
    expect(screen.queryByRole('switch')).toBeNull();
  });

  it('hides the new-only switch on the lowest stage, where it would be an identity filter', () => {
    renderAt('xs');
    expect(screen.getByRole('tab', { selected: true }).textContent).toBe(zh.stages.xs);
    expect(screen.queryByRole('switch')).toBeNull();
  });

  it.each([
    ['zk', zh.stages.newOnlyZk],
    ['gk', zh.stages.newOnly],
    ['cet4', zh.stages.newOnly],
    ['cet6', zh.stages.newOnlyCet6],
  ])('labels the new-only switch on %s per stage', (tab, label) => {
    renderAt(tab);
    expect(screen.getByRole('switch', { name: label })).toBeTruthy();
  });
});

describe('rows', () => {
  const empty: Page<WordBrief> = { items: [], page: 1, page_size: 50, total: 0 };
  afterEach(() => {
    vi.mocked(getVocab).mockResolvedValue(empty);
    window.localStorage.removeItem(TAB_KEY);
  });

  it('narrows each row\'s stage chips to my target stages plus the word\'s lowest stage (`onlyStages={settings.stages}`)', async () => {
    const apple: WordBrief = {
      id: 1,
      lemma: 'apple',
      display: 'apple',
      kind: 'word',
      phonetic: 'ˈæpl',
      translation_short: 'n. fruit',
      stages: ['xs', 'zk', 'gk', 'cet4'],
      stage_min: 1,
      cet6_star: false,
      frq: 500,
      collins: 5,
      oxford: true,
      difficulty: null,
      is_public: true,
      is_valid_english: true,
      my_state: null,
      content_state: 'ready',
      image_state: 'ready',
    };
    vi.mocked(getVocab).mockResolvedValue({ ...empty, items: [apple], total: 1 });
    renderAt('all');
    const chips = within(await screen.findByRole('list', { name: zh.word.examTags })).getAllByRole('listitem');
    expect(chips.map((li) => li.textContent)).toEqual([zh.stages.xs, zh.stages.zk]); // settings.stages = ['xs', 'zk']; gk / cet4 hidden
  });
});

describe('filter controls', () => {
  it('the status and sort selects are named after their purpose, not their current option', async () => {
    render(
      <MemoryRouter>
        <VocabPage />
      </MemoryRouter>,
    );
    const status = (await screen.findByRole('combobox', { name: zh.common.status })) as HTMLSelectElement;
    const sort = screen.getByRole('combobox', { name: zh.common.sort }) as HTMLSelectElement;
    fireEvent.change(status, { target: { value: 'unfamiliar' } });
    fireEvent.change(sort, { target: { value: 'alpha' } });
    expect(status.value).toBe('unfamiliar');
    expect(sort.value).toBe('alpha');
    expect(screen.getByRole('combobox', { name: zh.common.status })).toBe(status);
    expect(screen.getByRole('combobox', { name: zh.common.sort })).toBe(sort);
    expect(screen.queryByRole('combobox', { name: zh.vocab.status.all })).toBeNull();
    expect(screen.queryByRole('combobox', { name: zh.vocab.sort.freq })).toBeNull();
  });
});

describe('optimisticState', () => {
  it('mirrors the DESIGN 4 transitions', () => {
    expect(optimisticState('unfamiliar', null)).toBe('new');
    expect(optimisticState('unfamiliar', 'mastered')).toBe('new');
    expect(optimisticState('known', null)).toBe('known');
    expect(optimisticState('known', 'learning')).toBe('mastered'); // known on a bank word is the mastered synonym
    expect(optimisticState('mastered', null)).toBe('known'); // never studied → treated as known
    expect(optimisticState('mastered', 'new')).toBe('mastered');
    expect(optimisticState('remove', 'learning')).toBe('removed');
    expect(optimisticState('reset', 'learning')).toBe('new');
    expect(optimisticState('restore', 'mastered')).toBe('mastered');
  });
});

describe('markToast / markUndoable', () => {
  it('picks the copy from the action and server status', () => {
    expect(markToast('unfamiliar', 'added')).toBe(zh.vocab.addedToBank);
    expect(markToast('unfamiliar', 'readded')).toBe(zh.bank.status.readded);
    expect(markToast('unfamiliar', 'exists')).toBe(zh.vocab.inBank);
    expect(markToast('known', 'added')).toBe(zh.vocab.status.known);
    expect(markToast('mastered', 'added')).toBe(zh.study.mastered);
    expect(markToast('remove', 'added')).toBe(zh.bank.tabs.removed);
  });

  it('offers the server undo only when a restore can succeed', () => {
    expect(markUndoable('unfamiliar', 'added')).toBe(true);
    expect(markUndoable('known', 'added')).toBe(true);
    expect(markUndoable('mastered', 'added')).toBe(true);
    expect(markUndoable('unfamiliar', 'exists')).toBe(false);
    expect(markUndoable('unfamiliar', 'readded')).toBe(false);
    expect(markUndoable('mastered', 'noop')).toBe(false);
    expect(markUndoable('remove', 'added')).toBe(false);
    expect(markUndoable('reset', 'added')).toBe(false);
  });
});
