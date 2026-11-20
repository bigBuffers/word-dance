// TodayPage: the two entries of the listen page (FRONTEND §5.3 / §5.9, docs/LISTEN_MODE_DESIGN.md §3.1) — under the study CTA while
// the batch is unfinished, on the done card afterwards, and only while the batch holds a review / new / extra word that is still
// in the bank: the rule of the playlist itself (endpoint 123), so the entry never opens an empty list (screen items are not
// listened to, nor are words that have left the bank; no batch, no entry).
import { render, screen } from '@testing-library/react';
import { MemoryRouter } from 'react-router';
import { describe, expect, it, vi } from 'vitest';
import type { ImageMeta, ItemKind, StudyItem, TodayCounts, TodayResponse, UserState } from '@/api/types';
import { ToastProvider } from '@/components/ui/Toast';
import { zh } from '@/i18n/zh';

vi.mock('@/api/endpoints', () => ({ getToday: vi.fn(), getBank: vi.fn(), buildToday: vi.fn(), requestMore: vi.fn() }));
vi.mock('@/auth/AuthContext', async (importOriginal) => {
  const actual = await importOriginal<typeof import('@/auth/AuthContext')>();
  const fake = { user: { id: 1 }, settings: { push_time: '08:00' } };
  return { ...actual, useAuth: () => fake, useOptionalAuth: () => fake };
});
vi.mock('@/components/layout/AppLayout', () => ({ setTodayUngraded: () => undefined, hasUngradedItems: () => false }));

import { getBank, getToday } from '@/api/endpoints';
import TodayPage from './TodayPage';

const T0 = '2026-11-12T00:00:00.000Z';
const image: ImageMeta = { id: null, url: '/media/card/1.svg', kind: 'card', provider: 'card_svg', mime: 'image/svg+xml', width: 800, height: 500, alt_zh: null, attribution: null, dancing: false, word_layer: false, hook_zh: null, note_zh: null };

let nextId = 0;
/**
 * `n` batch items of one kind as GET /api/today serialises them: `state` is the word's state in the bank now (null = not in it:
 * an unmarked screen item), `result` the item's final grade (null = not graded yet).
 */
function items(n: number, kind: ItemKind, state: UserState | null, result: string | null = null): StudyItem[] {
  return Array.from({ length: n }, (): StudyItem => {
    const id = (nextId += 1);
    return {
      item_id: id,
      kind,
      position: id,
      result,
      skip_count: 0,
      requeue_at: null,
      word: {
        id: 100 + id, lemma: `w${id}`, display: `w${id}`, kind: 'word', phonetic: null, translation_short: 'x', stages: ['cet4'], stage_min: 4, cet6_star: false,
        frq: null, collins: null, oxford: null, difficulty: null, is_public: true, is_valid_english: true, my_state: state, content_state: 'none', image_state: 'none',
        definition: null, translation: null, pos: null, forms: [], confusables: [], dance: null,
      },
      mine: state === null ? null : {
        id: 100 + id, word_id: 100 + id, state, origin: 'browse', priority: 50, note: null, input_text: null, needs_attention: false, attention_msg: null, suggested_word: null,
        srs: { ease: 2.5, interval_days: 0, step: 0, repetitions: 0, lapses: 0, consecutive_good: 0, due_at: null, last_graded_at: null, mastery_suggested: false },
        times_pushed: 1, times_added: 1, added_at: T0, first_added_at: T0, mastered_at: null,
      },
      content: null,
      content_state: 'none',
      content_deferred_until: null,
      image,
    };
  });
}

/** The counts GET /api/today reports for these items: per kind, graded ones included. */
function countsOf(list: StudyItem[]): TodayCounts {
  const of = (kind: ItemKind) => list.filter((it) => it.kind === kind);
  const graded = (rows: StudyItem[]) => rows.filter((it) => it.result !== null).length;
  return {
    total: list.length, done: graded(list), review: of('review').length, review_done: graded(of('review')), new: of('new').length, new_done: graded(of('new')),
    screen: of('screen').length, screen_done: graded(of('screen')), extra: of('extra').length, extra_done: graded(of('extra')), pending_content: 0, deferred_reviews: 0,
  };
}

function today(list: StudyItem[] | null, over: Partial<TodayResponse> = {}): TodayResponse {
  return {
    status: list ? 'published' : 'none',
    local_date: '2026-11-12',
    push_time: '08:00',
    next_push_at: null,
    can_build_now: true,
    streak_days: 2,
    goal_met: false,
    added: null,
    previous_open_batch: null,
    suggestions_open: 0,
    batch: list
      ? { id: 7, local_date: '2026-11-12', timezone: 'UTC', status: 'published', trigger: 'scheduler', gradable: true, counts: countsOf(list), items: list, extra_rounds: 0, can_request_more: true, built_at: T0, published_at: T0, completed_at: null }
      : null,
    ...over,
  };
}

async function renderToday(data: TodayResponse) {
  vi.mocked(getToday).mockResolvedValue(data);
  vi.mocked(getBank).mockResolvedValue({ items: [], total: 3, page: 1, page_size: 1 } as never);
  const view = render(
    <MemoryRouter initialEntries={['/today']}>
      <ToastProvider>
        <TodayPage />
      </ToastProvider>
    </MemoryRouter>,
  );
  await screen.findByText(zh.today.streak(2));
  return view;
}

const listenLink = () => screen.queryByRole('link', { name: zh.today.listen });

describe('TodayPage: the listen entry', () => {
  it('sits right under the study CTA as a secondary block button while the batch is unfinished', async () => {
    await renderToday(today([...items(2, 'review', 'learning', 'good'), ...items(3, 'review', 'learning'), ...items(4, 'new', 'new'), ...items(3, 'screen', null)]));
    const cta = screen.getByRole('link', { name: zh.today.resume });
    const entry = listenLink();
    expect(entry?.getAttribute('href')).toBe('/listen');
    expect(entry?.className).toBe('btn btn--secondary btn--lg btn--block today__listen');
    expect(cta.nextElementSibling).toBe(entry);
  });

  it('is offered for extra words alone, and not for a batch of screen items only', async () => {
    const first = await renderToday(today(items(3, 'extra', 'learning')));
    expect(listenLink()).not.toBeNull();
    first.unmount();
    await renderToday(today(items(15, 'screen', null)));
    expect(screen.getByRole('link', { name: zh.today.start })).toBeTruthy();
    expect(listenLink()).toBeNull();
  });

  it('stays on the done card: words already studied can still be listened to', async () => {
    await renderToday(today([...items(5, 'review', 'learning', 'good'), ...items(4, 'new', 'learning', 'good')], { goal_met: true }));
    const card = screen.getByText(zh.today.done).closest('.today__done');
    expect(card).not.toBeNull();
    expect(listenLink()?.closest('.today__done')).toBe(card);
    expect(listenLink()?.className).toBe('btn btn--secondary btn--md');
    expect(screen.queryByRole('link', { name: zh.today.resume })).toBeNull(); // everything graded: nothing to resume
  });

  it('is not offered when every word of the day has left the bank — the playlist would be empty — and is back with one that returned', async () => {
    const gone = [
      ...items(2, 'review', 'mastered', 'master'), // graded so on the card
      ...items(1, 'new', 'mastered', 'good'), // marked so on its word page after the grade
      ...items(1, 'extra', 'removed', 'good'), // taken out of the bank after the grade
      ...items(1, 'screen', 'known', 'known'),
      ...items(1, 'screen', 'new', 'unfamiliar'), // in the bank, but with today's batch full it is studied from tomorrow: no `new` row today
    ];
    const first = await renderToday(today(gone, { goal_met: true }));
    expect(screen.getByText(zh.today.done)).toBeTruthy();
    expect(listenLink()).toBeNull();
    first.unmount();
    await renderToday(today([...gone, ...items(1, 'review', 'new', 'master')], { goal_met: true })); // graded so, then added again: the word's state decides, not the grade
    expect(listenLink()?.closest('.today__done')).not.toBeNull();
  });

  it('is absent before a batch exists', async () => {
    await renderToday(today(null));
    expect(screen.getByText(zh.today.notYet('08:00'))).toBeTruthy();
    expect(listenLink()).toBeNull();
  });
});
