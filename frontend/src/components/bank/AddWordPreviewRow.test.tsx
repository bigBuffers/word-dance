import { fireEvent, render, screen } from '@testing-library/react';
import { describe, expect, it, vi } from 'vitest';
import type { LookupPreview, Srs, UserWord, WordBrief } from '@/api/types';
import { zh } from '@/i18n/zh';
import { AddWordPreviewRow } from './AddWordPreviewRow';

const brief = (id: number, display: string, translation = ''): WordBrief => ({
  id,
  lemma: display.toLowerCase(),
  display,
  kind: 'word',
  phonetic: null,
  translation_short: translation,
  stages: ['cet4'],
  stage_min: 4,
  cet6_star: false,
  frq: 100,
  collins: null,
  oxford: null,
  difficulty: null,
  is_public: true,
  is_valid_english: true,
  my_state: null,
  content_state: 'none',
  image_state: 'none',
});

const srs: Srs = { ease: 2.5, interval_days: 0, step: 0, repetitions: 0, lapses: 0, consecutive_good: 0, due_at: null, last_graded_at: null, mastery_suggested: false };
const mine: UserWord = {
  id: 1,
  word_id: 1,
  state: 'new',
  origin: 'browse',
  priority: 50,
  note: null,
  input_text: null,
  needs_attention: false,
  attention_msg: null,
  suggested_word: null,
  srs,
  times_pushed: 0,
  times_added: 1,
  added_at: '2026-10-14T00:00:00Z',
  first_added_at: '2026-10-14T00:00:00Z',
  mastered_at: null,
};

const preview = (over: Partial<LookupPreview>): LookupPreview => ({
  input: 'abandon',
  normalized: 'abandon',
  valid: true,
  reason_zh: null,
  via: 'exact',
  match: brief(1, 'abandon', 'v. give up'),
  lemma_note_zh: null,
  candidates: [],
  suggestions: [],
  mine: null,
  ...over,
});

const row = (props: Partial<Parameters<typeof AddWordPreviewRow>[0]>) =>
  render(
    <ul>
      <AddWordPreviewRow input="abandon" preview={null} {...props} />
    </ul>,
  );

describe('AddWordPreviewRow', () => {
  it('shows a client-side rejection without a preview', () => {
    row({ input: 'abc123', invalidMessage: zh.errors.invalidWord });
    expect(screen.getByText(zh.errors.invalidWord)).toBeTruthy();
  });

  it('shows a skeleton while loading', () => {
    row({ loading: true });
    expect(screen.getByRole('listitem').getAttribute('aria-busy')).toBe('true');
  });

  it('exact / ecdict matches read as recognised, or already-in-bank when mine is set', () => {
    const { rerender } = row({ preview: preview({}) });
    expect(screen.getByText(zh.bank.preview.exact, { exact: false })).toBeTruthy();
    expect(screen.getByText('v. give up', { exact: false })).toBeTruthy();
    rerender(
      <ul>
        <AddWordPreviewRow input="abandon" preview={preview({ via: 'ecdict', mine })} />
      </ul>,
    );
    expect(screen.getByText(zh.bank.preview.inBank, { exact: false })).toBeTruthy();
    expect(screen.getByText(zh.bank.tabs.new)).toBeTruthy();
  });

  it('form matches prefer the server lemma note and fall back to the zh template', () => {
    const { rerender } = row({ input: 'went', preview: preview({ via: 'form', match: brief(2, 'go'), lemma_note_zh: 'server lemma note' }) });
    expect(screen.getByText('server lemma note', { exact: false })).toBeTruthy();
    rerender(
      <ul>
        <AddWordPreviewRow input="went" preview={preview({ via: 'form', match: brief(2, 'go'), lemma_note_zh: null })} />
      </ul>,
    );
    expect(screen.getByText(zh.bank.preview.form('go', zh.bank.formKinds.alt), { exact: false })).toBeTruthy();
  });

  it('ambiguous forms render candidate chips that report the pick and show the chosen one pressed', () => {
    const onPick = vi.fn();
    const base = brief(3, 'base');
    const basis = brief(4, 'basis');
    row({ input: 'bases', preview: preview({ via: 'ambiguous', match: null, candidates: [base, basis] }), onPick, chosenId: 4 });
    expect(screen.getByText(zh.bank.preview.ambiguous)).toBeTruthy();
    const chips = screen.getAllByRole('button');
    expect(chips).toHaveLength(2);
    expect(chips[1]?.getAttribute('aria-pressed')).toBe('true');
    fireEvent.click(chips[0] as HTMLElement);
    expect(onPick).toHaveBeenCalledWith(base);
  });

  it('unknown words read as pending AI validation and offer prefix suggestions', () => {
    const onPick = vi.fn();
    row({ input: 'abandonned', preview: preview({ via: 'none', match: null, suggestions: [brief(1, 'abandon')] }), onPick });
    expect(screen.getByText(zh.bank.preview.none)).toBeTruthy();
    fireEvent.click(screen.getByRole('button'));
    expect(onPick).toHaveBeenCalledTimes(1);
  });

  it('server-side invalid lines show the reason', () => {
    row({ input: 'x', preview: preview({ via: 'invalid', valid: false, match: null, reason_zh: 'server reason' }) });
    expect(screen.getByText('server reason', { exact: false })).toBeTruthy();
  });
});
