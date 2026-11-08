// StudyPage render tests (FRONTEND §5.1.3 / §5.1.6):
//  * a grade event left over from a previous load whose re-post fails transiently re-enters the backoff loop
//    (it is not parked forever);
//  * undo of a mastered grade keeps the server's restored `mine`, so the re-opened card previews as before;
//  * undo while the master grade is still unacknowledged cancels the event locally (no server restore, no retry);
//  * a double tap on a screen card's verdict button grades one card; keys stay unlocked;
//  * both StudyCard sites (live card, read-only replay) get `onlyStages={settings.stages}` (PLAN §6 S4): header chips =
//    my target stages plus the word's lowest stage.
import { act, fireEvent, render, screen, within } from '@testing-library/react';
import { MemoryRouter } from 'react-router';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { ApiError } from '@/api/client';
import type { GradeResponse, ImageMeta, StudyItem, TodayCounts, TodayResponse, UserWord } from '@/api/types';
import { ToastProvider } from '@/components/ui/Toast';
import { TAP_LOCK_MS } from '@/hooks/useTapLock';
import { zh } from '@/i18n/zh';

vi.mock('@/api/endpoints', () => ({
  getToday: vi.fn(),
  getBatch: vi.fn(),
  gradeItem: vi.fn(),
  markWord: vi.fn(),
  completeToday: vi.fn(),
  buildToday: vi.fn(),
  getWordContent: vi.fn(),
  requestMore: vi.fn(),
  requestWordContent: vi.fn(),
}));
vi.mock('@/auth/AuthContext', async (importOriginal) => {
  const actual = await importOriginal<typeof import('@/auth/AuthContext')>();
  const fake = { user: { id: 1 }, settings: { timezone: 'UTC', auto_pronounce: false, accent: 'en-US', zh_examples: 'tap', dance_mode: 'full', show_images: false, stages: ['xs', 'cet6'] } };
  return { ...actual, useAuth: () => fake, useOptionalAuth: () => fake };
});
vi.mock('@/components/layout/AppLayout', () => ({ setTodayUngraded: () => undefined }));

import { completeToday, gradeItem, getToday, markWord } from '@/api/endpoints';
import StudyPage, { PENDING_GRADES_KEY } from './StudyPage';

const T0 = '2026-10-28T08:00:00.000Z';
const image: ImageMeta = { id: null, url: '/media/card/1.svg', kind: 'card', provider: 'card_svg', mime: 'image/svg+xml', width: 800, height: 500, alt_zh: null, attribution: null };
const counts: TodayCounts = { total: 2, done: 0, review: 0, review_done: 0, new: 2, new_done: 0, screen: 0, screen_done: 0, extra: 0, extra_done: 0, pending_content: 0, deferred_reviews: 0 };

function mine(id: number, over: Partial<UserWord> = {}): UserWord {
  return {
    id: 100 + id,
    word_id: 100 + id,
    state: 'new',
    origin: 'browse',
    priority: 50,
    note: null,
    input_text: null,
    needs_attention: false,
    attention_msg: null,
    suggested_word: null,
    srs: { ease: 2.5, interval_days: 0, step: 0, repetitions: 0, lapses: 0, consecutive_good: 0, due_at: null, last_graded_at: null, mastery_suggested: false },
    times_pushed: 1,
    times_added: 1,
    added_at: T0,
    first_added_at: T0,
    mastered_at: null,
    ...over,
  };
}

function item(id: number, over: Partial<StudyItem> = {}): StudyItem {
  return {
    item_id: id,
    kind: 'new',
    position: id,
    result: null,
    skip_count: 0,
    requeue_at: null,
    word: {
      id: 100 + id,
      lemma: `w${id}`,
      display: `w${id}`,
      kind: 'word',
      phonetic: null,
      translation_short: 'x',
      stages: ['cet4'],
      stage_min: 4,
      cet6_star: false,
      frq: null,
      collins: null,
      oxford: null,
      difficulty: null,
      is_public: true,
      is_valid_english: true,
      my_state: 'new',
      content_state: 'none',
      image_state: 'none',
      definition: null,
      translation: null,
      pos: null,
      forms: [],
      confusables: [], dance: null,
    },
    mine: mine(id),
    content: null,
    content_state: 'none',
    content_deferred_until: null,
    image,
    ...over,
  };
}

function today(items: StudyItem[]): TodayResponse {
  return {
    status: 'published',
    local_date: '2026-10-28',
    push_time: '08:00',
    next_push_at: null,
    can_build_now: false,
    streak_days: 1,
    goal_met: false,
    added: null,
    previous_open_batch: null,
    suggestions_open: 0,
    batch: {
      id: 7,
      local_date: '2026-10-28',
      timezone: 'UTC',
      status: 'published',
      trigger: 'scheduler',
      gradable: true,
      counts: { ...counts, total: items.length, new: items.length },
      items,
      extra_rounds: 0,
      can_request_more: false,
      built_at: T0,
      published_at: T0,
      completed_at: null,
    },
  } as TodayResponse;
}

const graded = (id: number, result: string, over: Partial<GradeResponse> = {}): GradeResponse => ({
  item: { item_id: id, result, skip_count: 0, requeue_at: null },
  mine: null,
  next_due_zh: zh.study.nextDue.tomorrow,
  mastery_suggested: false,
  today: counts,
  duplicate: false,
  study_item: null,
  ...over,
});

const advance = (ms: number) =>
  act(async () => {
    await vi.advanceTimersByTimeAsync(ms);
  });
const flush = () =>
  act(async () => {
    await Promise.resolve();
  });
/** First button whose accessible name starts with `name` (the skip button exists twice: header and grade bar). */
const button = (name: string) => {
  const found = screen.getAllByRole('button', { name: new RegExp(`^${name}`) });
  if (!found[0]) throw new Error(`no button ${name}`);
  return found[0];
};

function renderStudy() {
  return render(
    <MemoryRouter initialEntries={['/study']}>
      <ToastProvider>
        <StudyPage />
      </ToastProvider>
    </MemoryRouter>,
  );
}

describe('StudyPage', () => {
  beforeEach(() => {
    vi.useFakeTimers({ toFake: ['setTimeout', 'clearTimeout', 'setInterval', 'clearInterval', 'Date'] });
    vi.setSystemTime(new Date(T0));
    window.localStorage.clear();
    vi.mocked(completeToday).mockResolvedValue({ summary: { local_date: '2026-10-28', review: 0, new: 1, extra: 0, screen: 0, again: 0, hard: 0, good: 1, mastered: 0, known: 0, unfamiliar: 0, study_minutes: 1, streak_days: 1, goal_met: true, next_push_at: null, can_request_more: false } } as never);
  });
  afterEach(() => {
    vi.useRealTimers();
    window.localStorage.clear();
  });

  it('a stored grade whose re-post fails transiently is retried with backoff instead of parking the card forever', async () => {
    const created = new Date(Date.parse(T0) - 60_000).toISOString();
    window.localStorage.setItem(PENDING_GRADES_KEY, JSON.stringify({ batchId: 7, events: [{ client_event_id: 'ev-stuck', item_id: 1, grade: 'good', elapsed_ms: 1500, created_at: created, attempts: 0, next_attempt_at: created }] }));
    vi.mocked(getToday).mockResolvedValue(today([item(1)]));
    vi.mocked(gradeItem)
      .mockRejectedValueOnce(new ApiError('internal_error', 503, ''))
      .mockImplementation(async (id: number) => graded(id, 'good'));
    renderStudy();

    await vi.waitFor(() => expect(gradeItem).toHaveBeenCalledTimes(1)); // the flush
    await vi.waitFor(() => expect(screen.getByText(zh.study.waiting(1, 10))).toBeTruthy()); // card parked while the grade is unacknowledged
    const stored = JSON.parse(window.localStorage.getItem(PENDING_GRADES_KEY) ?? 'null') as { events: { attempts: number }[] };
    expect(stored.events[0]?.attempts).toBe(1); // the failed flush counts as an attempt → eligible for the retry loop

    await advance(2_000); // first backoff step is 1 s
    await vi.waitFor(() => expect(gradeItem).toHaveBeenCalledTimes(2));
    await advance(2_000);
    expect(window.localStorage.getItem(PENDING_GRADES_KEY)).toBeNull();
    expect(screen.queryByText(zh.study.waiting(1, 10))).toBeNull();
    await vi.waitFor(() => expect(completeToday).toHaveBeenCalledTimes(1));
  });

  it('undo of a mastered grade keeps the restored `mine` so the re-opened card previews like a new card again', async () => {
    const [w1, w2] = [item(1), item(2)];
    vi.mocked(getToday).mockResolvedValue(today([w1, w2]));
    vi.mocked(gradeItem).mockImplementation(async (id: number, body) =>
      body.grade === 'master'
        ? graded(id, 'master', { next_due_zh: zh.study.nextDue.mastered, mine: mine(id, { state: 'mastered', mastered_at: T0, srs: { ...mine(id).srs, due_at: null } }) })
        : graded(id, 'good'),
    );
    vi.mocked(markWord).mockResolvedValue({ word_id: 101, state: 'new', mine: mine(1), status: 'restored' });
    renderStudy();

    await vi.waitFor(() => screen.getByRole('group', { name: 'w1' }));
    fireEvent.click(button(zh.study.reveal));
    fireEvent.click(button(zh.study.master)); // not suggested → confirm dialog
    const dialog = document.querySelector('dialog.confirm') as HTMLElement;
    fireEvent.click(within(dialog).getByRole('button', { name: zh.study.master }));
    await vi.waitFor(() => expect(gradeItem).toHaveBeenCalledWith(1, expect.objectContaining({ grade: 'master' })));
    await flush();
    await vi.waitFor(() => screen.getByRole('group', { name: 'w2' }));

    fireEvent.click(screen.getByRole('button', { name: zh.common.undo }));
    await vi.waitFor(() => expect(markWord).toHaveBeenCalledWith(101, { action: 'restore', context: 'today' }));
    await vi.waitFor(() => screen.getByRole('group', { name: 'w1' })); // re-inserted at the cursor
    await vi.waitFor(() => screen.getByText(zh.study.restored));
    fireEvent.click(button(zh.study.reveal));
    expect(screen.queryByText(zh.study.lastMastered('').trim(), { exact: false })).toBeNull();
    const good = button(zh.study.good);
    expect(good.textContent).toContain(zh.study.nextDue.tenMin); // learning step of a new card
    expect(good.textContent).not.toContain(zh.study.nextDue.tomorrow); // what the stale mastered row would preview
  });

  it('undo while the master grade is still unacknowledged cancels the event locally: no server restore, no retry', async () => {
    const suggested = (id: number) => item(id, { kind: 'review', mine: mine(id, { state: 'learning', srs: { ease: 2.5, interval_days: 20, step: 0, repetitions: 5, lapses: 0, consecutive_good: 5, due_at: T0, last_graded_at: null, mastery_suggested: true } }) });
    vi.mocked(getToday).mockResolvedValue(today([suggested(1), suggested(2)]));
    vi.mocked(gradeItem)
      .mockRejectedValueOnce(new ApiError('network', 0, ''))
      .mockImplementation(async (id: number) => graded(id, 'master', { next_due_zh: zh.study.nextDue.mastered }));
    renderStudy();

    await vi.waitFor(() => screen.getByRole('group', { name: 'w1' }));
    fireEvent.click(button(zh.study.reveal));
    fireEvent.click(button(zh.study.master)); // suggested → immediate 8-s undo toast
    await vi.waitFor(() => screen.getByText(zh.study.mastered));
    await vi.waitFor(() => expect(gradeItem).toHaveBeenCalledTimes(1));
    await flush();

    fireEvent.click(screen.getByRole('button', { name: zh.common.undo }));
    await vi.waitFor(() => screen.getByText(zh.study.restored));
    expect(markWord).not.toHaveBeenCalled(); // nothing to restore server-side
    await vi.waitFor(() => screen.getByRole('group', { name: 'w1' })); // card re-opened at the cursor
    await advance(15_000); // past every backoff step: the cancelled event is never re-sent
    expect(gradeItem).toHaveBeenCalledTimes(1);
    expect(window.localStorage.getItem(PENDING_GRADES_KEY)).toBeNull();
    expect(screen.getByText(zh.history.completed(0, 2))).toBeTruthy();
  });

  it('a double tap on a screen card grades one card; taps work after the lock and keys are never locked', async () => {
    const screenItem = (id: number) => item(id, { kind: 'screen', mine: null });
    vi.mocked(getToday).mockResolvedValue(today([screenItem(1), screenItem(2), screenItem(3)]));
    vi.mocked(gradeItem).mockImplementation(async (id: number, body) => graded(id, String(body.grade), { next_due_zh: zh.study.nextDue.mastered }));
    renderStudy();

    await vi.waitFor(() => screen.getByRole('group', { name: 'w1' }));
    fireEvent.click(button(zh.study.known));
    expect(screen.queryByRole('group', { name: 'w2' })).not.toBeNull(); // advanced at once
    fireEvent.click(button(zh.study.known)); // w2's button, under the finger
    await flush();
    expect(vi.mocked(gradeItem).mock.calls.map((c) => c[0])).toEqual([1]);
    expect(screen.queryByRole('group', { name: 'w2' })).not.toBeNull();

    await advance(TAP_LOCK_MS + 50);
    fireEvent.click(button(zh.study.known));
    await flush();
    expect(vi.mocked(gradeItem).mock.calls.map((c) => c[0])).toEqual([1, 2]);
    fireEvent.keyDown(window, { key: '1' }); // keyboard right after a tap: intended rapid flow
    await flush();
    expect(vi.mocked(gradeItem).mock.calls.map((c) => c[0])).toEqual([1, 2, 3]);
  });

  it('passes my target stages to both StudyCard sites: the live card and the read-only replay narrow the header chips alike', async () => {
    const wide = item(1, { word: { ...item(1).word, stages: ['zk', 'gk', 'cet4', 'cet6'], stage_min: 2 } });
    const chipTexts = () => within(screen.getByRole('list', { name: zh.word.examTags })).getAllByRole('listitem').map((li) => li.textContent);
    const expected = [zh.stages.zk, zh.stages.cet6]; // settings.stages = ['xs', 'cet6'] + the lowest stage zk; gk / cet4 hidden

    // the live card of today's gradable batch
    const live = today([wide]);
    vi.mocked(getToday).mockResolvedValue(live);
    const session = renderStudy();
    await vi.waitFor(() => screen.getByRole('group', { name: 'w1' }));
    expect(chipTexts()).toEqual(expected);
    session.unmount();

    // the read-only replay of an older batch (`batch.gradable: false` → the other StudyCard site, back face)
    vi.mocked(getToday).mockResolvedValue({ ...live, batch: { ...live.batch!, gradable: false } });
    renderStudy();
    await vi.waitFor(() => screen.getByRole('group', { name: 'w1' }));
    expect(chipTexts()).toEqual(expected);
  });
});

describe('StudyPage word dance (FRONTEND §5.1.1, §6.5; element.animate stubbed)', () => {
  const spec = { version: 1 as const, letters: ['w', '1'], stress: 0, marks: { double: [] as [number, number][], silent: [] as number[] }, semantic: null, source: 'rule' as const };
  const danced = (id: number, over: Partial<StudyItem> = {}): StudyItem => {
    const it = item(id, over);
    it.word = { ...it.word, dance: spec };
    return it;
  };
  let animate: ReturnType<typeof vi.fn>;
  beforeEach(() => {
    vi.useFakeTimers({ toFake: ['setTimeout', 'clearTimeout', 'setInterval', 'clearInterval', 'Date'] });
    vi.setSystemTime(new Date(T0));
    window.localStorage.clear();
    animate = vi.fn(() => ({ finished: Promise.resolve(), cancel: () => undefined }));
    Object.defineProperty(Element.prototype, 'animate', { value: animate, configurable: true, writable: true });
  });
  afterEach(() => {
    delete (Element.prototype as unknown as { animate?: unknown }).animate;
    vi.useRealTimers();
    window.localStorage.clear();
  });

  it('a new card dances on show (autoplay) and shows the syllable chips; key P replays it', async () => {
    vi.mocked(getToday).mockResolvedValue(today([danced(1)]));
    const { container } = renderStudy();
    await vi.waitFor(() => expect(container.querySelector('.dword')).not.toBeNull());
    expect(within(screen.getByRole('list', { name: zh.word.syllables })).getAllByRole('listitem').map((c) => c.textContent)).toEqual(['w', '1']);
    const steps = animate.mock.calls.length;
    expect(steps).toBeGreaterThan(0); // the mount-time autoplay of the first exposure
    fireEvent.keyDown(window, { key: 'p' });
    await flush();
    expect(animate.mock.calls.length).toBe(2 * steps);
  });

  it('a review with three repetitions keeps the chips but does not dance on show; a screen item never dances', async () => {
    vi.mocked(getToday).mockResolvedValue(today([danced(1, { kind: 'review', mine: mine(1, { state: 'learning', srs: { ...mine(1).srs, repetitions: 3, interval_days: 8 } }) })]));
    const first = renderStudy();
    await vi.waitFor(() => expect(first.container.querySelector('.dword')).not.toBeNull());
    expect(screen.getByRole('list', { name: zh.word.syllables })).toBeTruthy();
    expect(animate).not.toHaveBeenCalled();
    first.unmount();

    vi.mocked(getToday).mockResolvedValue(today([danced(2, { kind: 'screen' })]));
    const second = renderStudy();
    await vi.waitFor(() => expect(screen.getByRole('heading', { level: 2 }).textContent).toBe('w2'));
    expect(second.container.querySelector('.dword')).toBeNull();
    expect(screen.queryByRole('list', { name: zh.word.syllables })).toBeNull();
    fireEvent.keyDown(window, { key: 'p' });
    await flush();
    expect(animate).not.toHaveBeenCalled();
  });
});
