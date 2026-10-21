// FRONTEND §5.2 / §7 reducer contract: requeue placement (an intermediate grade keeps the item in `order`
// and out of `graded`; the later final grade moves it to `graded`), `load` of an item carrying
// `requeue_at` lands in `requeue`, skip ordering, pending flush, `restore` re-insert, `study_item`
// append, and — compile-time — that no `undo` action exists.
import { describe, expect, it } from 'vitest';
import type { GradeResponse, ImageMeta, StudyItem, TodayCounts } from '@/api/types';
import {
  DEFAULT_REQUEUE_MS,
  REQUEUE_GAP,
  backoffMs,
  initialQueue,
  isComplete,
  isWaiting,
  newClientEventId,
  queueReducer,
  selectCurrent,
  selectDone,
  selectDuePending,
  selectRemaining,
  selectWaiting,
  type GradeEvent,
  type QueueAction,
  type QueueState,
} from './queue';

// ---- compile-time: the action union has no `undo` (FRONTEND §5.2) ---------------------------------
type UndoActions = Extract<QueueAction['type'], 'undo'>;
const noUndo: [UndoActions] extends [never] ? true : false = true;

// ---- fixtures ---------------------------------------------------------------------------------------
const T0 = '2026-10-14T08:00:00.000Z';
const at = (offsetMs: number, base = T0) => new Date(Date.parse(base) + offsetMs).toISOString();
const image: ImageMeta = { id: null, url: '/media/card/1.svg', kind: 'card', provider: 'card_svg', mime: 'image/svg+xml', width: 800, height: 500, alt_zh: null, attribution: null };
const counts: TodayCounts = { total: 0, done: 0, review: 0, review_done: 0, new: 0, new_done: 0, screen: 0, screen_done: 0, extra: 0, extra_done: 0, pending_content: 0, deferred_reviews: 0 };

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
      stage_min: 3,
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
      confusables: [],
    },
    mine: null,
    content: null,
    content_state: 'none',
    content_deferred_until: null,
    image,
    ...over,
  };
}

function response(itemId: number, result: string | null, requeueAt: string | null, over: Partial<GradeResponse> = {}): GradeResponse {
  return { item: { item_id: itemId, result, skip_count: 0, requeue_at: requeueAt }, mine: null, next_due_zh: '', mastery_suggested: false, today: counts, duplicate: false, study_item: null, ...over };
}

function event(itemId: number, grade: GradeEvent['grade'] = 'good', id = `ev-${itemId}-${grade}`): GradeEvent {
  return { client_event_id: id, item_id: itemId, grade, elapsed_ms: 1200, created_at: T0, attempts: 0, next_attempt_at: T0 };
}

function loaded(items: StudyItem[], pending?: GradeEvent[]): QueueState {
  return queueReducer(initialQueue(T0), { type: 'load', batchId: 7, items, now: T0, ...(pending ? { pending } : {}) });
}

const range = (n: number, from = 1) => Array.from({ length: n }, (_, i) => item(from + i));

describe('queue reducer — load', () => {
  it('orders ungraded first (skipped after unskipped), then graded; items with requeue_at land in requeue', () => {
    const s = loaded([item(1, { result: 'good' }), item(2, { skip_count: 1 }), item(3), item(4, { requeue_at: at(5 * 60_000) }), item(5)]);
    expect(s.batchId).toBe(7);
    expect(s.order).toEqual([3, 5, 2, 4, 1]);
    expect(s.graded).toEqual({ 1: 'good' });
    expect(s.requeue).toEqual([{ itemId: 4, at: at(5 * 60_000) }]);
    expect(selectCurrent(s)).toBe(3);
    expect(selectDone(s)).toBe(1);
    expect(selectRemaining(s)).toBe(4);
    expect(s.startedAt).toBe(T0);
    expect(noUndo).toBe(true);
  });

  it('seeds pending events and re-parks their cards until the server answers', () => {
    const s = loaded([item(1), item(2)], [event(1)]);
    expect(s.pending).toHaveLength(1);
    expect(s.requeue).toEqual([{ itemId: 1, at: at(DEFAULT_REQUEUE_MS), provisional: true }]);
    expect(selectCurrent(s)).toBe(2);
  });
});

describe('queue reducer — grading', () => {
  it('an intermediate grade keeps the item in order and out of graded; the later final grade moves it to graded', () => {
    let s = loaded(range(15));
    s = queueReducer(s, { type: 'submit', event: event(1), now: T0 });
    expect(s.pending).toHaveLength(1);
    expect(selectCurrent(s)).toBe(2); // the card advanced at once
    expect(s.order.indexOf(1)).toBe(REQUEUE_GAP); // ≥ 10 cards later
    expect(s.requeue[0]).toMatchObject({ itemId: 1, provisional: true });

    const requeueAt = at(10 * 60_000);
    s = queueReducer(s, { type: 'grade', itemId: 1, clientEventId: 'ev-1-good', response: response(1, null, requeueAt), now: at(300) });
    expect(s.pending).toHaveLength(0);
    expect(s.order).toContain(1);
    expect(1 in s.graded).toBe(false);
    expect(s.requeue).toEqual([{ itemId: 1, at: requeueAt }]);
    expect(selectDone(s)).toBe(0);

    // grade everything else finally; the parked card is skipped over while not due
    for (const id of [2, 3, 4, 5, 6, 7, 8, 9, 10, 11, 12, 13, 14, 15]) {
      s = queueReducer(s, { type: 'grade', itemId: id, clientEventId: null, response: response(id, 'good', null), now: at(400) });
    }
    expect(selectDone(s)).toBe(14);
    expect(isWaiting(s)).toBe(true);
    expect(selectCurrent(s)).toBeNull();
    expect(selectWaiting(s)).toEqual([{ itemId: 1, at: requeueAt }]);

    // ten minutes later the tick makes it due and it is the current card again
    s = queueReducer(s, { type: 'tick', now: at(10 * 60_000 + 1) });
    expect(selectCurrent(s)).toBe(1);
    expect(isWaiting(s)).toBe(false);

    // the second grade is a NEW event with a fresh client_event_id and a final result
    s = queueReducer(s, { type: 'submit', event: event(1, 'good', 'ev-1-second'), now: at(10 * 60_000 + 2) });
    expect(s.pending.map((p) => p.client_event_id)).toEqual(['ev-1-second']);
    s = queueReducer(s, { type: 'grade', itemId: 1, clientEventId: 'ev-1-second', response: response(1, 'good', null), now: at(10 * 60_000 + 3) });
    expect(s.graded[1]).toBe('good');
    expect(s.requeue).toEqual([]);
    expect(isComplete(s)).toBe(true);
    expect(selectDone(s)).toBe(15);
  });

  it('places a requeued card at the end when fewer than REQUEUE_GAP cards remain', () => {
    let s = loaded(range(4));
    s = queueReducer(s, { type: 'submit', event: event(1, 'again'), now: T0 });
    expect(s.order).toEqual([2, 3, 4, 1]);
    expect(selectCurrent(s)).toBe(2);
  });

  it('a final grade on submit moves straight to graded when the server answers', () => {
    let s = loaded(range(3));
    s = queueReducer(s, { type: 'submit', event: event(2, 'master', 'm2'), now: T0 });
    s = queueReducer(s, { type: 'grade', itemId: 2, clientEventId: 'm2', response: response(2, 'master', null), now: at(100) });
    expect(s.graded).toEqual({ 2: 'master' });
    expect(s.requeue).toEqual([]);
    expect(s.order).toContain(2); // history stays in order
    expect(selectCurrent(s)).toBe(1);
  });

  it('appends response.study_item to the end of the queue', () => {
    let s = loaded([item(1, { kind: 'screen' }), item(2)]);
    s = queueReducer(s, { type: 'submit', event: event(1, 'unfamiliar', 'u1'), now: T0 });
    s = queueReducer(s, { type: 'grade', itemId: 1, clientEventId: 'u1', response: response(1, 'unfamiliar', null, { study_item: item(99) }), now: at(100) });
    expect(s.order).toEqual([2, 1, 99]);
    expect(s.graded).toEqual({ 1: 'unfamiliar' });
    expect(selectCurrent(s)).toBe(2);
    // appending twice is a no-op
    expect(queueReducer(s, { type: 'append', itemId: 99 })).toBe(s);
  });

  it('acknowledges a skip without parking anything', () => {
    let s = loaded(range(3));
    s = queueReducer(s, { type: 'submit', event: event(1, 'skip', 's1'), now: T0 });
    expect(s.order).toEqual([2, 3, 1]);
    expect(s.requeue).toEqual([]);
    s = queueReducer(s, { type: 'grade', itemId: 1, clientEventId: 's1', response: response(1, null, null), now: at(50) });
    expect(s.pending).toEqual([]);
    expect(s.requeue).toEqual([]);
    expect(selectCurrent(s)).toBe(2);
  });
});

describe('queue reducer — skip, waiting, reviewNow, restore, remove', () => {
  it('skip moves the card to the end and hides the back', () => {
    let s = loaded(range(3));
    s = queueReducer(s, { type: 'reveal' });
    expect(s.revealed).toBe(true);
    s = queueReducer(s, { type: 'skip', itemId: 1 });
    expect(s.order).toEqual([2, 3, 1]);
    expect(s.revealed).toBe(false);
    expect(selectCurrent(s)).toBe(2);
    expect(queueReducer(s, { type: 'skip', itemId: 42 })).toBe(s);
  });

  it('reviewNow makes the parked card gradable immediately', () => {
    let s = loaded([item(1, { requeue_at: at(9 * 60_000) })]);
    expect(isWaiting(s)).toBe(true);
    s = queueReducer(s, { type: 'reviewNow' });
    expect(selectCurrent(s)).toBe(1);
    expect(s.requeue).toEqual([]);
  });

  it('restore removes the item from graded and re-inserts it at the cursor', () => {
    let s = loaded(range(3));
    s = queueReducer(s, { type: 'grade', itemId: 1, clientEventId: null, response: response(1, 'master', null), now: T0 });
    expect(selectCurrent(s)).toBe(2);
    s = queueReducer(s, { type: 'restore', itemId: 1 });
    expect(1 in s.graded).toBe(false);
    expect(selectCurrent(s)).toBe(1);
    expect(s.order).toEqual([1, 2, 3]);
    expect(s.revealed).toBe(false);
  });

  it('remove drops a stale item and keeps the cursor consistent', () => {
    let s = loaded(range(4));
    s = queueReducer(s, { type: 'grade', itemId: 1, clientEventId: null, response: response(1, 'good', null), now: T0 });
    expect(s.cursor).toBe(1);
    s = queueReducer(s, { type: 'remove', itemId: 1 });
    expect(s.order).toEqual([2, 3, 4]);
    expect(s.cursor).toBe(0);
    expect(s.graded).toEqual({});
    s = queueReducer(s, { type: 'remove', itemId: 3 });
    expect(s.order).toEqual([2, 4]);
    expect(queueReducer(s, { type: 'remove', itemId: 3 })).toBe(s);
  });

  it('tick returns the same state object when nothing is due (cheap re-render guard)', () => {
    const s = loaded(range(2));
    expect(queueReducer(s, { type: 'tick', now: at(1000) })).toBe(s);
  });
});

describe('queue reducer — pending flush', () => {
  it('fail backs off (1 s, 3 s, 10 s…), flushPending removes acknowledged events, drop releases the park', () => {
    let s = loaded(range(3));
    s = queueReducer(s, { type: 'submit', event: event(1, 'good', 'a'), now: T0 });
    s = queueReducer(s, { type: 'submit', event: event(2, 'good', 'b'), now: T0 });
    expect(s.pending.map((p) => p.client_event_id)).toEqual(['a', 'b']);
    expect(selectDuePending(s, at(5000))).toEqual([]); // first attempts are made inline, not by the retry loop

    s = queueReducer(s, { type: 'fail', clientEventId: 'a', now: at(0) });
    expect(s.pending[0]).toMatchObject({ attempts: 1, next_attempt_at: at(backoffMs(1)) });
    expect(backoffMs(1)).toBe(1000);
    expect(backoffMs(2)).toBe(3000);
    expect(backoffMs(3)).toBe(10_000);
    expect(backoffMs(99)).toBe(60_000);
    expect(selectDuePending(s, at(999))).toEqual([]);
    expect(selectDuePending(s, at(1000)).map((p) => p.client_event_id)).toEqual(['a']);

    s = queueReducer(s, { type: 'flushPending', acked: ['b'] });
    expect(s.pending.map((p) => p.client_event_id)).toEqual(['a']);
    expect(queueReducer(s, { type: 'flushPending', acked: ['zzz'] })).toBe(s);

    // the card of a dropped event (non-retryable 4xx) comes back to the queue
    s = queueReducer(s, { type: 'drop', clientEventId: 'a' });
    expect(s.pending).toEqual([]);
    expect(s.requeue.some((r) => r.itemId === 1)).toBe(false);
    expect(s.order).toContain(1);
  });

  it('ignores a duplicate submit of the same client_event_id', () => {
    let s = loaded(range(2));
    s = queueReducer(s, { type: 'submit', event: event(1, 'good', 'dup'), now: T0 });
    expect(queueReducer(s, { type: 'submit', event: event(1, 'good', 'dup'), now: T0 })).toBe(s);
  });

  it('generates UUID v4 client_event_ids', () => {
    const id = newClientEventId();
    expect(id).toMatch(/^[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/);
    expect(newClientEventId()).not.toBe(id);
  });
});
