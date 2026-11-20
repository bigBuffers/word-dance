import { act, fireEvent, render, screen } from '@testing-library/react';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import type { Srs, UserWord, WordBrief, WordDetail } from '@/api/types';
import { zh } from '@/i18n/zh';
import { ATTENTION_POLL_MS, AttentionBadge, attentionState, isPollingState } from './AttentionBadge';

const ISO = '2026-10-14T00:00:00Z';
const srs: Srs = { ease: 2.5, interval_days: 0, step: 0, repetitions: 0, lapses: 0, consecutive_good: 0, due_at: null, last_graded_at: null, mastery_suggested: false };

const word = (over: Partial<WordBrief> = {}): WordBrief => ({
  id: 7,
  lemma: 'zzqx',
  display: 'zzqx',
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
  is_public: false,
  is_valid_english: null,
  my_state: 'new',
  content_state: 'none',
  image_state: 'none',
  ...over,
});

const mine = (over: Partial<UserWord> = {}): UserWord => ({
  id: 1,
  word_id: 7,
  state: 'new',
  origin: 'custom',
  priority: 100,
  note: null,
  input_text: 'zzqx',
  needs_attention: false,
  attention_msg: null,
  suggested_word: null,
  srs,
  times_pushed: 0,
  times_added: 1,
  added_at: ISO,
  first_added_at: ISO,
  mastered_at: null,
  ...over,
});

const detail = (w: WordBrief, m: UserWord | null): WordDetail => ({
  word: { ...w, definition: null, translation: null, pos: null, exam_tags: [], bnc: null, forms: [], source: 'user', confusables: [], dance: null },
  content: null,
  content_state: 'none',
  content_deferred_until: null,
  image: { id: null, url: '/media/card/7.svg', kind: 'card', provider: 'card_svg', mime: 'image/svg+xml', width: 800, height: 500, alt_zh: null, attribution: null, dancing: false, word_layer: false, hook_zh: null, note_zh: null },
  mine: m,
  redirected_from: null,
  history: [],
});

const json = (body: unknown) => new Response(JSON.stringify(body), { status: 200, headers: { 'Content-Type': 'application/json' } });

describe('attentionState', () => {
  it('derives the API.md 9.1 badge state from needs_attention / attention_msg / is_valid_english', () => {
    expect(attentionState(mine({ needs_attention: true, attention_msg: 'not english' }), word())).toBe('flagged');
    expect(attentionState(mine({ needs_attention: true, attention_msg: null }), word())).toBe('rechecking');
    expect(attentionState(mine(), word({ is_valid_english: null }))).toBe('pending');
    expect(attentionState(mine(), word({ is_valid_english: false }))).toBe('collect_only');
    expect(attentionState(mine({ suggested_word: word({ id: 8, display: 'receive' }) }), word({ is_valid_english: true }))).toBe('suggestion');
    expect(attentionState(mine(), word({ is_valid_english: true }))).toBe('none');
    expect(attentionState(null, word())).toBe('none');
    expect(isPollingState('pending')).toBe(true);
    expect(isPollingState('rechecking')).toBe(true);
    expect(isPollingState('flagged')).toBe(false);
  });
});

describe('AttentionBadge', () => {
  it('flagged + unvalidated: message with edit / retry / keep / delete buttons wired to the handlers', () => {
    const handlers = { onKeep: vi.fn(), onRetry: vi.fn(), onEdit: vi.fn(), onRemove: vi.fn(), onReplace: vi.fn() };
    render(<AttentionBadge mine={mine({ needs_attention: true, attention_msg: 'cannot validate now' })} word={word({ is_valid_english: null })} poll={false} {...handlers} />);
    expect(screen.getByRole('alert').textContent).toContain('cannot validate now');
    fireEvent.click(screen.getByRole('button', { name: zh.bank.edit }));
    fireEvent.click(screen.getByRole('button', { name: zh.bank.retry }));
    fireEvent.click(screen.getByRole('button', { name: zh.bank.keep }));
    fireEvent.click(screen.getByRole('button', { name: zh.common.delete }));
    expect(handlers.onEdit).toHaveBeenCalledTimes(1);
    expect(handlers.onRetry).toHaveBeenCalledTimes(1);
    expect(handlers.onKeep).toHaveBeenCalledTimes(1);
    expect(handlers.onRemove).toHaveBeenCalledTimes(1);
    expect(screen.queryByRole('button', { name: zh.bank.replaceWith('receive') })).toBeNull();
  });

  it('flagged + rejected word: no retry, keep reads collect-only, replace-with offered when a suggestion exists', () => {
    const onReplace = vi.fn();
    const onRetry = vi.fn();
    render(
      <AttentionBadge
        mine={mine({ needs_attention: true, attention_msg: 'not english', suggested_word: word({ id: 8, display: 'receive', is_valid_english: true }) })}
        word={word({ is_valid_english: false })}
        poll={false}
        onRetry={onRetry}
        onKeep={vi.fn()}
        onReplace={onReplace}
      />,
    );
    expect(screen.queryByRole('button', { name: zh.bank.retry })).toBeNull();
    expect(screen.getByRole('button', { name: zh.bank.keepOnly })).toBeTruthy();
    fireEvent.click(screen.getByRole('button', { name: zh.bank.replaceWith('receive') }));
    expect(onReplace).toHaveBeenCalledTimes(1);
  });

  it('renders the pending / re-validating / collect-only chips without buttons', () => {
    const { rerender } = render(<AttentionBadge mine={mine()} word={word({ is_valid_english: null })} poll={false} onKeep={vi.fn()} />);
    expect(screen.getByText(zh.bank.pendingAi)).toBeTruthy();
    expect(screen.queryAllByRole('button')).toHaveLength(0);
    rerender(<AttentionBadge mine={mine({ needs_attention: true })} word={word()} poll={false} onKeep={vi.fn()} />);
    expect(screen.getByText(zh.bank.retrying)).toBeTruthy();
    rerender(<AttentionBadge mine={mine()} word={word({ is_valid_english: false })} poll={false} onKeep={vi.fn()} />);
    expect(screen.getByText(zh.bank.keepOnly)).toBeTruthy();
    expect(screen.queryAllByRole('button')).toHaveLength(0);
    rerender(<AttentionBadge mine={mine()} word={word({ is_valid_english: true })} poll={false} onKeep={vi.fn()} />);
    expect(document.body.textContent).toBe('');
  });

  describe('polling', () => {
    beforeEach(() => vi.useFakeTimers());
    afterEach(() => {
      vi.useRealTimers();
      vi.unstubAllGlobals();
    });

    it('polls GET /api/words/{id} every 3 s while re-validating and reports the resolved detail once', async () => {
      const resolved = detail(word({ is_valid_english: true }), mine({ needs_attention: false }));
      const fetchMock = vi.fn<typeof fetch>(() => Promise.resolve(json(resolved)));
      vi.stubGlobal('fetch', fetchMock);
      const onUpdate = vi.fn();
      render(<AttentionBadge mine={mine({ needs_attention: true })} word={word()} onUpdate={onUpdate} />);
      expect(fetchMock).not.toHaveBeenCalled();
      await act(async () => {
        await vi.advanceTimersByTimeAsync(ATTENTION_POLL_MS);
      });
      expect(fetchMock).toHaveBeenCalledTimes(1);
      expect(String(fetchMock.mock.calls[0]?.[0])).toBe('/api/words/7');
      expect(onUpdate).toHaveBeenCalledTimes(1);
      expect(onUpdate.mock.calls[0]?.[0]).toEqual(resolved);
      await act(async () => {
        await vi.advanceTimersByTimeAsync(ATTENTION_POLL_MS * 3);
      });
      expect(fetchMock).toHaveBeenCalledTimes(1); // resolved → polling stopped
    });

    it('keeps polling while the state is unchanged', async () => {
      const still = detail(word({ is_valid_english: null }), mine({ needs_attention: true }));
      const fetchMock = vi.fn<typeof fetch>(() => Promise.resolve(json(still)));
      vi.stubGlobal('fetch', fetchMock);
      const onUpdate = vi.fn();
      render(<AttentionBadge mine={mine({ needs_attention: true })} word={word()} onUpdate={onUpdate} />);
      await act(async () => {
        await vi.advanceTimersByTimeAsync(ATTENTION_POLL_MS * 3);
      });
      expect(fetchMock).toHaveBeenCalledTimes(3);
      expect(onUpdate).not.toHaveBeenCalled();
    });
  });
});
