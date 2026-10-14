import { fireEvent, render, screen } from '@testing-library/react';
import { describe, expect, it, vi } from 'vitest';
import type { Suggestion, WordBrief } from '@/api/types';
import { zh } from '@/i18n/zh';
import { canUndo, SuggestionRow, suggestionText } from './SuggestionRow';

const NOW = new Date('2026-10-14T12:00:00Z');

const brief = (id: number, display: string): WordBrief => ({
  id,
  lemma: display.toLowerCase(),
  display,
  kind: 'word',
  phonetic: null,
  translation_short: '',
  stages: [],
  stage_min: null,
  cet6_star: false,
  frq: null,
  collins: null,
  oxford: null,
  difficulty: null,
  is_public: true,
  is_valid_english: true,
  my_state: null,
  content_state: 'none',
  image_state: 'none',
});

const suggestion = (over: Partial<Suggestion>): Suggestion => ({
  id: 1,
  type: 'fix_spelling',
  status: 'open',
  user_word: null,
  target: null,
  payload: { from: 'abandonned', to: 'abandon' },
  created_at: '2026-10-14T00:00:00Z',
  expires_at: '2026-11-13T00:00:00Z',
  resolved_at: null,
  ...over,
});

describe('suggestionText', () => {
  it('uses the FRONTEND 5.7 copy per type, preferring the word rows over payload strings', () => {
    expect(suggestionText(suggestion({}))).toBe(zh.suggestions.fix_spelling('abandonned', 'abandon'));
    expect(suggestionText(suggestion({ type: 'lemmatize', payload: { from: 'analyses', to: 'analysis' } }))).toBe(zh.suggestions.lemmatize('analyses', 'analysis'));
    expect(suggestionText(suggestion({ type: 'lemmatize', status: 'auto', payload: { from: 'ran', to: 'run' } }))).toBe(zh.suggestions.auto_lemmatize('ran', 'run'));
    expect(suggestionText(suggestion({ type: 'merge_duplicate', payload: { from: 'colour', to: 'color' } }))).toBe(zh.suggestions.merge_duplicate('colour', 'color'));
    expect(suggestionText(suggestion({ type: 'invalid_word', payload: { from: 'zzzq' } }))).toBe(zh.suggestions.invalid_word('zzzq'));
    expect(suggestionText(suggestion({ type: 'split_phrase', payload: { to: 'negotiate' } }))).toBe(zh.suggestions.split_phrase('negotiate'));
    expect(suggestionText(suggestion({ type: 'fill_data', status: 'auto', payload: { from: 'gdp', fields: ['phonetic'] } }))).toBe(zh.suggestions.fill_data('gdp'));
    expect(suggestionText(suggestion({ type: 'confusable_group', payload: { group: ['abandon', 'abundant'] } }))).toBe(`${zh.study.confusable} · abandon · abundant`);
    const withRows = suggestion({ user_word: { ...brief(5, 'Recieve'), mine: null as never } as never, target: brief(6, 'receive'), payload: { from: 'x', to: 'y' } });
    expect(suggestionText(withRows)).toBe(zh.suggestions.fix_spelling('Recieve', 'receive'));
  });
});

describe('canUndo', () => {
  it('is true only for auto rows inside the undo window', () => {
    expect(canUndo(suggestion({ status: 'auto', expires_at: '2026-10-20T00:00:00Z' }), NOW)).toBe(true);
    expect(canUndo(suggestion({ status: 'auto', expires_at: null }), NOW)).toBe(true);
    expect(canUndo(suggestion({ status: 'auto', expires_at: '2026-10-01T00:00:00Z' }), NOW)).toBe(false);
    expect(canUndo(suggestion({ status: 'open' }), NOW)).toBe(false);
    expect(canUndo(suggestion({ status: 'undone' }), NOW)).toBe(false);
  });
});

describe('SuggestionRow', () => {
  it('open rows offer accept / keep and report the expiry', () => {
    const onAccept = vi.fn();
    const onReject = vi.fn();
    const s = suggestion({});
    render(
      <ul>
        <SuggestionRow s={s} now={NOW} onAccept={onAccept} onReject={onReject} onUndo={vi.fn()} />
      </ul>,
    );
    expect(screen.getByText(zh.suggestions.fix_spelling('abandonned', 'abandon'))).toBeTruthy();
    expect(screen.getByText(zh.suggestions.expiresIn(30))).toBeTruthy();
    fireEvent.click(screen.getByRole('button', { name: zh.suggestions.accept }));
    fireEvent.click(screen.getByRole('button', { name: zh.suggestions.reject }));
    expect(onAccept).toHaveBeenCalledWith(s);
    expect(onReject).toHaveBeenCalledWith(s);
    expect(screen.queryByRole('button', { name: zh.suggestions.undo })).toBeNull();
  });

  it('auto rows offer undo only inside the 7-day window', () => {
    const onUndo = vi.fn();
    const live = suggestion({ id: 2, type: 'lemmatize', status: 'auto', payload: { from: 'ran', to: 'run' }, expires_at: '2026-10-20T00:00:00Z' });
    const { rerender } = render(
      <ul>
        <SuggestionRow s={live} now={NOW} onUndo={onUndo} />
      </ul>,
    );
    expect(screen.getByText(zh.suggestions.auto_lemmatize('ran', 'run'))).toBeTruthy();
    fireEvent.click(screen.getByRole('button', { name: zh.suggestions.undo }));
    expect(onUndo).toHaveBeenCalledWith(live);
    rerender(
      <ul>
        <SuggestionRow s={{ ...live, expires_at: '2026-10-01T00:00:00Z' }} now={NOW} onUndo={onUndo} />
      </ul>,
    );
    expect(screen.queryByRole('button', { name: zh.suggestions.undo })).toBeNull();
  });
});
