// study/queue.ts — pure reducer for the in-session card queue (FRONTEND §5.2, API.md 45, DESIGN §7).
//
// State: `{batchId, order, cursor, revealed, requeue, pending, graded, startedAt}` plus `clock`, the
// last instant an action reported (so the reducer stays pure while it decides which requeues are due).
//
// Model
// * `order` is the sequence of EVERY item of the batch (ungraded first, skipped after unskipped, then
//   the already-graded history); an item never leaves `order` except through `remove` (stale item).
// * `graded` maps item id → the FINAL result stored by the server (`GradeResponse.item.result !== null`).
//   An intermediate grade (`result === null` + `requeue_at`, the 10-minute step) never enters `graded`:
//   the card is parked in `requeue` and moved ≥ REQUEUE_GAP cards later (or to the end) — it stays
//   ungraded and is graded again later with a fresh `client_event_id`.
// * `cursor` points at the current card; `settle()` advances it over graded items and rotates a parked
//   card to the end while another gradable card exists, so the current card is always gradable, or the
//   session is waiting (every remaining card is parked) or complete (every card graded).
// * `pending` holds grade events not yet acknowledged by the server (mirrored to localStorage by the
//   page). `submit` parks the card optimistically (the card advances at once, §5.1.6); `grade` applies
//   the server's answer. There is NO `undo` action: the only undo is the server `restore` (§5.1.3).
import type { Grade, GradeResponse, ScreenVerdict, StudyItem } from '@/api/types';

/** A requeued card re-enters the visible queue at least this many cards later (or at the end). */
export const REQUEUE_GAP = 10;
/** The learning step (DESIGN §7 `LEARNING_STEP_MIN`), used while the server's `requeue_at` is unknown. */
export const DEFAULT_REQUEUE_MS = 10 * 60_000;
/** Retry backoff for pending grade events (FRONTEND §5.1.6: 1 s, 3 s, 10 s…). */
export const RETRY_BACKOFF_MS: readonly number[] = [1_000, 3_000, 10_000, 30_000, 60_000];

export interface RequeueEntry {
  itemId: number;
  /** UTC ISO instant the card may be shown again. */
  at: string;
  /** Set between `submit` and the server's answer (the final/intermediate outcome is not known yet). */
  provisional?: boolean;
}

export interface GradeEvent {
  client_event_id: string;
  item_id: number;
  grade: Grade | ScreenVerdict;
  elapsed_ms: number | null;
  created_at: string;
  /** Failed delivery attempts so far. */
  attempts: number;
  /** Earliest instant for the next delivery attempt. */
  next_attempt_at: string;
}

export interface QueueState {
  batchId: number | null;
  order: number[];
  cursor: number;
  revealed: boolean;
  requeue: RequeueEntry[];
  pending: GradeEvent[];
  graded: Record<number, string>;
  startedAt: string | null;
  /** Last reported instant (ISO); `settle()` measures requeue due-ness against it. */
  clock: string;
}

export type QueueAction =
  | { type: 'load'; batchId: number; items: readonly StudyItem[]; now: string; pending?: readonly GradeEvent[] }
  | { type: 'reveal' }
  | { type: 'hide' }
  | { type: 'submit'; event: GradeEvent; now: string }
  | { type: 'grade'; itemId: number; clientEventId: string | null; response: GradeResponse; now: string; requeueAt?: string | null }
  | { type: 'fail'; clientEventId: string; now: string }
  | { type: 'drop'; clientEventId: string }
  | { type: 'skip'; itemId: number }
  | { type: 'tick'; now: string }
  | { type: 'reviewNow' }
  | { type: 'flushPending'; acked: readonly string[] }
  | { type: 'restore'; itemId: number }
  | { type: 'remove'; itemId: number }
  | { type: 'append'; itemId: number };

/** A fresh UUID v4 `client_event_id` (API.md §1 idempotency); falls back when `randomUUID` is absent. */
export function newClientEventId(): string {
  const c = globalThis.crypto;
  if (c && typeof c.randomUUID === 'function') return c.randomUUID();
  const bytes = new Uint8Array(16);
  if (c && typeof c.getRandomValues === 'function') c.getRandomValues(bytes);
  else for (let i = 0; i < bytes.length; i++) bytes[i] = Math.floor(Math.random() * 256);
  bytes[6] = ((bytes[6] ?? 0) & 0x0f) | 0x40;
  bytes[8] = ((bytes[8] ?? 0) & 0x3f) | 0x80;
  const hex = Array.from(bytes, (b) => b.toString(16).padStart(2, '0')).join('');
  return `${hex.slice(0, 8)}-${hex.slice(8, 12)}-${hex.slice(12, 16)}-${hex.slice(16, 20)}-${hex.slice(20)}`;
}

export function initialQueue(now: string = new Date().toISOString()): QueueState {
  return { batchId: null, order: [], cursor: 0, revealed: false, requeue: [], pending: [], graded: {}, startedAt: null, clock: now };
}

const ms = (iso: string): number => {
  const t = Date.parse(iso);
  return Number.isNaN(t) ? 0 : t;
};

export function backoffMs(attempts: number): number {
  return RETRY_BACKOFF_MS[Math.min(Math.max(attempts, 1), RETRY_BACKOFF_MS.length) - 1] ?? 60_000;
}

function isParked(s: QueueState, itemId: number): boolean {
  const entry = s.requeue.find((r) => r.itemId === itemId);
  if (!entry) return false;
  return entry.provisional === true || ms(entry.at) > ms(s.clock);
}

/**
 * Normalises the queue after an action: drops due requeues, advances the cursor over graded items and
 * rotates a parked current card to the end while a gradable card exists later. Returns the same object
 * when nothing changes (cheap re-render guard for the 1-s tick).
 */
export function settle(s: QueueState): QueueState {
  const nowMs = ms(s.clock);
  const requeue = s.requeue.filter((r) => r.provisional === true || ms(r.at) > nowMs);
  const parked = new Set(requeue.map((r) => r.itemId));
  const order = s.order.slice();
  let cursor = Math.min(Math.max(s.cursor, 0), order.length);
  let moves = order.length;
  while (cursor < order.length) {
    const id = order[cursor];
    if (id === undefined) break;
    if (id in s.graded) {
      cursor += 1;
      continue;
    }
    if (parked.has(id)) {
      const later = order.findIndex((x, k) => k > cursor && !(x in s.graded) && !parked.has(x));
      if (later === -1 || moves-- <= 0) break;
      order.splice(cursor, 1);
      order.push(id);
      continue;
    }
    break;
  }
  const unchanged = requeue.length === s.requeue.length && cursor === s.cursor && order.every((id, i) => id === s.order[i]);
  return unchanged ? s : { ...s, requeue, order, cursor };
}

/** Moves `itemId` out of its position to `index` (after removal); no-op when absent. */
function moveTo(order: readonly number[], itemId: number, index: number): number[] {
  const i = order.indexOf(itemId);
  if (i === -1) return order.slice();
  const next = order.slice();
  next.splice(i, 1);
  next.splice(Math.min(Math.max(index, 0), next.length), 0, itemId);
  return next;
}

function removeFrom(order: readonly number[], itemId: number): number[] {
  return order.filter((id) => id !== itemId);
}

function withoutRequeue(requeue: readonly RequeueEntry[], itemId: number): RequeueEntry[] {
  return requeue.filter((r) => r.itemId !== itemId);
}

function orderOf(items: readonly StudyItem[]): { order: number[]; graded: Record<number, string>; requeue: RequeueEntry[] } {
  const fresh: number[] = [];
  const skipped: number[] = [];
  const parked: number[] = [];
  const done: number[] = [];
  const graded: Record<number, string> = {};
  const requeue: RequeueEntry[] = [];
  for (const it of items) {
    if (it.result !== null) {
      done.push(it.item_id);
      graded[it.item_id] = it.result;
    } else if (it.requeue_at) {
      parked.push(it.item_id);
      requeue.push({ itemId: it.item_id, at: it.requeue_at });
    } else if (it.skip_count > 0) {
      skipped.push(it.item_id);
    } else {
      fresh.push(it.item_id);
    }
  }
  return { order: [...fresh, ...skipped, ...parked, ...done], graded, requeue };
}

export function queueReducer(state: QueueState, action: QueueAction): QueueState {
  switch (action.type) {
    case 'load': {
      const { order, graded, requeue } = orderOf(action.items);
      const pending = action.pending ? action.pending.slice() : [];
      // cards whose grade is still in flight stay parked until the server answers (reload / /more)
      const provisionalAt = new Date(ms(action.now) + DEFAULT_REQUEUE_MS).toISOString();
      for (const ev of pending) {
        if (ev.grade === 'skip' || !order.includes(ev.item_id) || ev.item_id in graded) continue;
        if (!requeue.some((r) => r.itemId === ev.item_id)) requeue.push({ itemId: ev.item_id, at: provisionalAt, provisional: true });
      }
      return settle({
        batchId: action.batchId,
        order,
        cursor: 0,
        revealed: false,
        requeue,
        pending,
        graded,
        startedAt: state.batchId === action.batchId && state.startedAt ? state.startedAt : action.now,
        clock: action.now,
      });
    }

    case 'reveal':
      return state.revealed ? state : { ...state, revealed: true };

    case 'hide':
      return state.revealed ? { ...state, revealed: false } : state;

    case 'submit': {
      const { event } = action;
      if (state.pending.some((p) => p.client_event_id === event.client_event_id)) return state;
      const pending = [...state.pending, event];
      if (!state.order.includes(event.item_id)) return settle({ ...state, pending, clock: action.now });
      if (event.grade === 'skip') {
        // skip semantics: to the end, nothing parked (the server only bumps skip_count)
        return settle({ ...state, pending, order: moveTo(state.order, event.item_id, state.order.length), revealed: false, clock: action.now });
      }
      const order = moveTo(state.order, event.item_id, state.cursor + REQUEUE_GAP);
      const at = new Date(ms(action.now) + DEFAULT_REQUEUE_MS).toISOString();
      const requeue = [...withoutRequeue(state.requeue, event.item_id), { itemId: event.item_id, at, provisional: true }];
      return settle({ ...state, pending, order, requeue, revealed: false, clock: action.now });
    }

    case 'grade': {
      const { itemId, response } = action;
      const pending = action.clientEventId === null ? state.pending : state.pending.filter((p) => p.client_event_id !== action.clientEventId);
      let order = state.order.slice();
      let requeue = state.requeue.slice();
      const graded = { ...state.graded };
      const result = response.item.result;
      const requeueAt = action.requeueAt === undefined ? response.item.requeue_at : action.requeueAt;
      if (result !== null) {
        graded[itemId] = result;
        requeue = withoutRequeue(requeue, itemId);
      } else if (requeueAt !== null) {
        if (!order.includes(itemId)) order.splice(Math.min(state.cursor + REQUEUE_GAP, order.length), 0, itemId);
        else {
          const idx = order.indexOf(itemId);
          if (idx < state.cursor || idx < state.cursor + REQUEUE_GAP) order = moveTo(order, itemId, state.cursor + REQUEUE_GAP);
        }
        requeue = [...withoutRequeue(requeue, itemId), { itemId, at: requeueAt }];
        delete graded[itemId];
      } else {
        // skip acknowledged (result null, no requeue): nothing parked
        requeue = withoutRequeue(requeue, itemId);
      }
      const extra = response.study_item;
      if (extra && !order.includes(extra.item_id)) order.push(extra.item_id);
      return settle({ ...state, order, requeue, graded, pending, clock: action.now });
    }

    case 'fail': {
      const pending = state.pending.map((p) => {
        if (p.client_event_id !== action.clientEventId) return p;
        const attempts = p.attempts + 1;
        return { ...p, attempts, next_attempt_at: new Date(ms(action.now) + backoffMs(attempts)).toISOString() };
      });
      return { ...state, pending, clock: action.now };
    }

    case 'drop': {
      const event = state.pending.find((p) => p.client_event_id === action.clientEventId);
      if (!event) return state;
      const pending = state.pending.filter((p) => p !== event);
      // a provisional park for this event is released (the card is gradable again)
      const requeue = state.requeue.filter((r) => !(r.itemId === event.item_id && r.provisional === true));
      return settle({ ...state, pending, requeue });
    }

    case 'skip':
      if (!state.order.includes(action.itemId)) return state;
      return settle({ ...state, order: moveTo(state.order, action.itemId, state.order.length), revealed: false });

    case 'tick': {
      const settled = settle({ ...state, clock: action.now });
      const unchanged = settled.requeue.length === state.requeue.length && settled.cursor === state.cursor && settled.order.length === state.order.length && settled.order.every((id, i) => id === state.order[i]);
      // nothing became due and nothing moved: keep the identity so useReducer bails out of a re-render
      return unchanged ? state : settled;
    }

    case 'reviewNow': {
      // make the first parked card (from the cursor on) gradable now
      const nowMs = ms(state.clock);
      const target = state.order.slice(state.cursor).find((id) => !(id in state.graded) && state.requeue.some((r) => r.itemId === id && (r.provisional || ms(r.at) > nowMs)));
      if (target === undefined) return state;
      const order = moveTo(state.order, target, state.cursor);
      return settle({ ...state, order, requeue: withoutRequeue(state.requeue, target), revealed: false });
    }

    case 'flushPending': {
      const acked = new Set(action.acked);
      const pending = state.pending.filter((p) => !acked.has(p.client_event_id));
      return pending.length === state.pending.length ? state : { ...state, pending };
    }

    case 'restore': {
      // after a successful server `restore`: back out of `graded`, re-insert at the cursor
      const graded = { ...state.graded };
      delete graded[action.itemId];
      const idx = state.order.indexOf(action.itemId);
      // a graded card sits before the cursor; taking it out shifts the current card one slot left
      const cursor = idx !== -1 && idx < state.cursor ? state.cursor - 1 : state.cursor;
      const base = idx === -1 ? [...state.order, action.itemId] : state.order;
      const order = moveTo(base, action.itemId, cursor);
      return settle({ ...state, order, cursor, graded, requeue: withoutRequeue(state.requeue, action.itemId), revealed: false });
    }

    case 'remove': {
      const idx = state.order.indexOf(action.itemId);
      if (idx === -1) return state;
      const graded = { ...state.graded };
      delete graded[action.itemId];
      const cursor = idx < state.cursor ? state.cursor - 1 : state.cursor;
      return settle({ ...state, order: removeFrom(state.order, action.itemId), cursor, graded, requeue: withoutRequeue(state.requeue, action.itemId) });
    }

    case 'append':
      if (state.order.includes(action.itemId)) return state;
      return settle({ ...state, order: [...state.order, action.itemId] });

    default:
      return state;
  }
}

// ---- selectors --------------------------------------------------------------------------------------

/** The current gradable card, or null while waiting / complete. */
export function selectCurrent(s: QueueState): number | null {
  const id = s.order[s.cursor];
  if (id === undefined || id in s.graded || isParked(s, id)) return null;
  return id;
}

export function selectDone(s: QueueState): number {
  return Object.keys(s.graded).length;
}

export function selectTotal(s: QueueState): number {
  return s.order.length;
}

export function selectRemaining(s: QueueState): number {
  return s.order.filter((id) => !(id in s.graded)).length;
}

/** Every card carries a final result. */
export function isComplete(s: QueueState): boolean {
  return s.order.length > 0 && s.order.every((id) => id in s.graded);
}

/** Parked cards that block the session (not due yet), soonest first. */
export function selectWaiting(s: QueueState): RequeueEntry[] {
  const nowMs = ms(s.clock);
  return s.requeue
    .filter((r) => !(r.itemId in s.graded) && (r.provisional === true || ms(r.at) > nowMs))
    .slice()
    .sort((a, b) => ms(a.at) - ms(b.at));
}

/** True when nothing is gradable but ungraded cards remain (all parked). */
export function isWaiting(s: QueueState): boolean {
  return !isComplete(s) && selectCurrent(s) === null && s.order.length > 0;
}

/** Pending events due for another delivery attempt at `nowIso`. */
export function selectDuePending(s: QueueState, nowIso: string): GradeEvent[] {
  const nowMs = ms(nowIso);
  return s.pending.filter((p) => p.attempts > 0 && ms(p.next_attempt_at) <= nowMs);
}
