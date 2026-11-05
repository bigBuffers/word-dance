import { fireEvent, render, screen, within } from '@testing-library/react';
import { MemoryRouter } from 'react-router';
import { afterEach, describe, expect, it, vi } from 'vitest';
import { getBank } from '@/api/endpoints';
import type { BankItem, BankResponse, UserWord, WordDetail } from '@/api/types';
import { briefOf } from '@/components/bank/AttentionBadge';
import { zh } from '@/i18n/zh';
import BankPage, { rowBelongsToTab } from './BankPage';

const learningRow: UserWord = {
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
  srs: { ease: 2.5, interval_days: 3, step: 0, repetitions: 4, lapses: 1, consecutive_good: 2, due_at: '2099-01-01T00:00:00Z', last_graded_at: null, mastery_suggested: false },
  times_pushed: 3,
  times_added: 1,
  added_at: '2026-10-20T00:00:00Z',
  first_added_at: '2026-10-20T00:00:00Z',
  mastered_at: null,
};
const bankItem: BankItem = {
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
  my_state: 'learning',
  content_state: 'none',
  image_state: 'none',
  mine: learningRow,
};
const bankResponse: BankResponse = { items: [bankItem], page: 1, page_size: 50, total: 1, counts: { new: 0, learning: 1, mastered: 0, known: 0, removed: 0, attention: 0, due_today: 0 } };

vi.mock('@/api/endpoints', async (importOriginal) => ({
  ...(await importOriginal<typeof import('@/api/endpoints')>()),
  getBank: vi.fn(() => Promise.resolve(bankResponse)),
  markWord: vi.fn(() => new Promise(() => undefined)),
}));
vi.mock('@/auth/AuthContext', () => {
  // the rows narrow their stage chips to `settings.stages` (`onlyStages`, PLAN §6 S4)
  const fake = { settings: { timezone: 'Asia/Shanghai', accent: 'en-US', stages: ['xs', 'cet6'] }, counters: { suggestions_open: 0, attention: 0 }, refreshCounters: vi.fn(() => Promise.resolve()) };
  return { useAuth: () => fake, useOptionalAuth: () => fake };
});

describe('BankPage', () => {
  afterEach(() => {
    vi.mocked(getBank).mockImplementation(() => Promise.resolve(bankResponse));
  });

  it('names the sort control "sort", not its first option, and keeps that name after a change', async () => {
    render(
      <MemoryRouter>
        <BankPage />
      </MemoryRouter>,
    );
    const sort = (await screen.findByRole('combobox', { name: zh.common.sort })) as HTMLSelectElement;
    fireEvent.change(sort, { target: { value: 'due' } });
    expect(sort.value).toBe('due');
    expect(screen.getByRole('combobox', { name: zh.common.sort })).toBe(sort);
    expect(screen.queryByRole('combobox', { name: zh.bank.sort.added })).toBeNull();
  });

  it('the reset confirmation names the word in its title and explains the consequence', async () => {
    render(
      <MemoryRouter>
        <BankPage />
      </MemoryRouter>,
    );
    fireEvent.click(await screen.findByRole('button', { name: `${zh.common.more} · abandon` }));
    fireEvent.click(await screen.findByRole('button', { name: zh.word.reset }));
    const dialog = document.querySelector('dialog.confirm') as HTMLElement;
    expect(dialog.querySelector('.confirm__title')?.textContent).toBe(`${zh.word.reset} · abandon`);
    expect(dialog.querySelector('.confirm__message')?.textContent).toBe(zh.word.resetConfirm);
  });

  it('narrows each row\'s stage chips to my target stages plus the word\'s lowest stage (`onlyStages={settings.stages}`)', async () => {
    const wide: BankItem = { ...bankItem, stages: ['zk', 'gk', 'cet4', 'cet6'], stage_min: 2 };
    vi.mocked(getBank).mockResolvedValue({ ...bankResponse, items: [wide] });
    render(
      <MemoryRouter>
        <BankPage />
      </MemoryRouter>,
    );
    const chips = within(await screen.findByRole('list', { name: zh.word.examTags })).getAllByRole('listitem');
    expect(chips.map((li) => li.textContent)).toEqual([zh.stages.zk, zh.stages.cet6]); // settings.stages = ['xs', 'cet6'] + the lowest stage zk; gk / cet4 hidden
  });
});

describe('rowBelongsToTab', () => {
  it('matches the state tabs on mine.state and the attention tab on needs_attention', () => {
    expect(rowBelongsToTab('new', { state: 'new', needs_attention: false })).toBe(true);
    expect(rowBelongsToTab('learning', { state: 'new', needs_attention: false })).toBe(false);
    expect(rowBelongsToTab('attention', { state: 'new', needs_attention: true })).toBe(true);
    expect(rowBelongsToTab('attention', { state: 'new', needs_attention: false })).toBe(false);
    expect(rowBelongsToTab('removed', { state: 'removed', needs_attention: true })).toBe(true);
  });
});

describe('briefOf', () => {
  it('strips the detail-only fields so the list row keeps the WordBrief shape', () => {
    const word: WordDetail['word'] = {
      id: 1,
      lemma: 'abandon',
      display: 'abandon',
      kind: 'word',
      phonetic: null,
      translation_short: 'give up',
      stages: ['cet4'],
      stage_min: 4,
      cet6_star: false,
      frq: 1,
      collins: null,
      oxford: null,
      difficulty: null,
      is_public: true,
      is_valid_english: true,
      my_state: 'new',
      content_state: 'none',
      image_state: 'none',
      definition: 'def',
      translation: 'long translation',
      pos: 'v',
      exam_tags: ['cet4'],
      bnc: 10,
      forms: [{ form: 'abandoned', kind: 'p' }],
      source: 'seed',
      confusables: ['abundant'],
    };
    const brief = briefOf(word);
    expect(brief).toEqual({
      id: 1,
      lemma: 'abandon',
      display: 'abandon',
      kind: 'word',
      phonetic: null,
      translation_short: 'give up',
      stages: ['cet4'],
      stage_min: 4,
      cet6_star: false,
      frq: 1,
      collins: null,
      oxford: null,
      difficulty: null,
      is_public: true,
      is_valid_english: true,
      my_state: 'new',
      content_state: 'none',
      image_state: 'none',
    });
    expect('confusables' in brief).toBe(false);
  });
});
