// WordDetailPage render tests (FRONTEND §5.8): the remove / reset confirmations explain what happens, the bank
// panel reads "not reviewed yet" for a never-graded row and names an overdue review, and ECDICT's pos ratio is
// shown as readable shares.
import { fireEvent, render, screen, waitFor, within } from '@testing-library/react';
import { MemoryRouter, Route, Routes } from 'react-router';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import type { UserWord, WordDetail } from '@/api/types';
import { zh } from '@/i18n/zh';

const h = vi.hoisted(() => ({ detail: null as unknown, settings: { timezone: 'Asia/Shanghai', accent: 'en-US', show_images: false, zh_examples: 'tap', dance_mode: 'full' as 'full' | 'off' } }));

vi.mock('@/api/endpoints', () => ({
  getWord: vi.fn(() => Promise.resolve(h.detail)),
  getWordContent: vi.fn(),
  getWordImage: vi.fn(),
  markWord: vi.fn(() => new Promise(() => undefined)),
  refreshWordImage: vi.fn(),
  reportWord: vi.fn(),
  requestWordContent: vi.fn(),
}));
vi.mock('@/auth/AuthContext', () => {
  const fake = {
    get settings() {
      return h.settings;
    },
    counters: { suggestions_open: 0, attention: 0 },
    refreshCounters: vi.fn(() => Promise.resolve()),
  };
  return { useAuth: () => fake, useOptionalAuth: () => fake };
});

import WordDetailPage from './WordDetailPage';

const DAY = 86_400_000;

function mineRow(over: Partial<UserWord> = {}): UserWord {
  return {
    id: 11,
    word_id: 1,
    state: 'learning',
    origin: 'browse',
    priority: 50,
    note: null,
    input_text: null,
    needs_attention: false,
    attention_msg: null,
    suggested_word: null,
    srs: { ease: 2.5, interval_days: 3, step: 0, repetitions: 4, lapses: 1, consecutive_good: 2, due_at: new Date(Date.now() - 2 * DAY).toISOString(), last_graded_at: null, mastery_suggested: false },
    times_pushed: 3,
    times_added: 1,
    added_at: '2026-10-20T00:00:00Z',
    first_added_at: '2026-10-20T00:00:00Z',
    mastered_at: null,
    ...over,
  };
}

function detailOf(mine: UserWord | null, word: Partial<WordDetail['word']> = {}): WordDetail {
  return {
    word: {
      id: 1,
      lemma: 'abandon',
      display: 'abandon',
      kind: 'word',
      phonetic: null,
      translation_short: 'v. give up',
      stages: ['cet4'],
      stage_min: 4,
      cet6_star: false,
      frq: 1000,
      collins: 3,
      oxford: true,
      difficulty: 2,
      is_public: true,
      is_valid_english: true,
      my_state: mine?.state ?? null,
      content_state: 'none',
      image_state: 'none',
      definition: null,
      translation: 'v. give up\nn. wild abandon',
      pos: 'n:4/v:96',
      exam_tags: [],
      bnc: null,
      forms: [],
      source: 'seed',
      confusables: [], dance: null,
      ...word,
    },
    content: null,
    content_state: 'none',
    content_deferred_until: null,
    image: { id: null, url: '/media/card/1.svg', kind: 'card', provider: 'card_svg', mime: 'image/svg+xml', width: null, height: null, alt_zh: null, attribution: null },
    mine,
    redirected_from: null,
    history: [],
  };
}

function renderDetail() {
  return render(
    <MemoryRouter initialEntries={['/words/1']}>
      <Routes>
        <Route path="/words/:idOrLemma" element={<WordDetailPage />} />
      </Routes>
    </MemoryRouter>,
  );
}

const dialog = () => document.querySelector('dialog.confirm') as HTMLElement;

describe('WordDetailPage', () => {
  beforeEach(() => {
    h.detail = detailOf(mineRow());
  });

  it('the remove and reset confirmations carry a title and an explanatory sentence', async () => {
    renderDetail();
    fireEvent.click(await screen.findByRole('button', { name: zh.word.remove }));
    expect(within(dialog()).getByRole('heading').textContent).toBe(zh.word.remove);
    expect(dialog().querySelector('.confirm__message')?.textContent).toBe(zh.word.removeConfirm);
    expect(within(dialog()).getByRole('button', { name: zh.word.remove })).toBeTruthy();
    fireEvent.click(within(dialog()).getByRole('button', { name: zh.common.cancel }));
    await waitFor(() => expect(document.querySelector('dialog.confirm[open]')).toBeNull());

    fireEvent.click(screen.getByRole('button', { name: zh.word.reset }));
    expect(within(dialog()).getByRole('heading').textContent).toBe(zh.word.reset);
    expect(dialog().querySelector('.confirm__message')?.textContent).toBe(zh.word.resetConfirm);
  });

  it('shows the SRS line, the bare overdue label for a review due on an earlier day, and readable pos shares', async () => {
    renderDetail();
    await screen.findByRole('button', { name: zh.word.remove });
    expect(screen.getByText(zh.study.srsLine(4, 3))).toBeTruthy();
    expect(screen.getByText(zh.study.nextDue.overdue, { selector: 'dd' })).toBeTruthy();
    expect(screen.queryByText(zh.bank.dueIn(zh.study.nextDue.overdue))).toBeNull();
    expect(screen.getByText('v. 96% · n. 4%')).toBeTruthy();
    expect(screen.queryByText('n:4/v:96')).toBeNull();
  });

  it('a never-graded bank row reads "not reviewed yet" instead of a zeroth review', async () => {
    h.detail = detailOf(mineRow({ state: 'new', srs: { ease: 2.5, interval_days: 0, step: 0, repetitions: 0, lapses: 0, consecutive_good: 0, due_at: null, last_graded_at: null, mastery_suggested: false } }));
    renderDetail();
    await screen.findByRole('button', { name: zh.word.remove });
    expect(screen.getByText(zh.study.srsNew)).toBeTruthy();
    expect(screen.queryByText(zh.study.srsLine(0, 0))).toBeNull();
    expect(screen.queryByText(zh.bank.sort.due, { selector: 'dt' })).toBeNull();
  });
});

describe('WordDetailPage word dance (FRONTEND §6.5)', () => {
  const spec = { version: 1 as const, letters: ['a', 'ban', 'don'], stress: 1, marks: { double: [] as [number, number][], silent: [] as number[] }, source: 'rule' as const };
  beforeEach(() => {
    h.settings.dance_mode = 'full';
  });

  it('shows the syllable chips and a dancing headword named after the word', async () => {
    h.detail = detailOf(mineRow(), { dance: spec });
    const { container } = renderDetail();
    await screen.findByRole('heading', { level: 1, name: 'abandon' });
    const chips = within(screen.getByRole('list', { name: zh.word.syllables })).getAllByRole('listitem');
    expect(chips.map((c) => c.textContent)).toEqual(['a', 'ban', 'don']);
    expect(chips.map((c) => c.classList.contains('syl__chip--stressed'))).toEqual([false, true, false]);
    expect(container.querySelector('.dword')).not.toBeNull();
  });

  it('dance_mode off → the plain headword without chips', async () => {
    h.settings.dance_mode = 'off';
    h.detail = detailOf(mineRow(), { dance: spec });
    const { container } = renderDetail();
    await screen.findByRole('heading', { level: 1 });
    expect(screen.queryByRole('list', { name: zh.word.syllables })).toBeNull();
    expect(container.querySelector('.dword')).toBeNull();
  });
});
