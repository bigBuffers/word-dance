// StudyPage — the card session (FRONTEND §5.1–5.2, API.md 43–47). `/study` loads today's batch,
// `/study?batch=<id>` loads `GET /api/batches/{id}`: with the grade bar when `batch.gradable` (today's,
// or yesterday's open batch), otherwise a read-only replay.
//
// Grades are optimistic: the card advances at once and the event is POSTed immediately with a fixed
// `client_event_id`; failed deliveries stay in the reducer's `pending` (mirrored to
// localStorage['wd.pendingGrades'], flushed on reload before refetching) and retry with backoff. A
// final grade (`result !== null`) moves the item to `graded`; an intermediate one (`result:null` +
// `requeue_at`) parks it for the 10-minute step and the same item is graded again later with a new
// event. The only undo is the server `restore` (mastered's 8-s toast, screen card verdicts' 5-s toast) —
// except for a grade the server never acknowledged (still in `pending` after a transient failure), which
// undo cancels locally instead, so a retried delivery cannot master a word the user undid.
import { useCallback, useEffect, useReducer, useRef, useState } from 'react';
import { Link, useSearchParams } from 'react-router';
import { errorMessage, isApiError } from '@/api/client';
import { buildToday, completeToday, getBatch, getToday, getWordContent, gradeItem, markWord, requestMore, requestWordContent } from '@/api/endpoints';
import type { ContentResponse, GradeBody, MoreSource } from '@/api/endpoints';
import type { Grade, GradeResponse, ScreenVerdict, SessionSummary as SessionSummaryDto, StudyItem, TodayResponse, WordBrief } from '@/api/types';
import { useAuth } from '@/auth/AuthContext';
import { setTodayUngraded } from '@/components/layout/AppLayout';
import { SessionSummary } from '@/components/study/SessionSummary';
import { StudyCard, resultLabel } from '@/components/study/StudyCard';
import { Button } from '@/components/ui/Button';
import { ConfirmDialog } from '@/components/ui/ConfirmDialog';
import { EmptyState } from '@/components/ui/EmptyState';
import { Skeleton } from '@/components/ui/Skeleton';
import { useApi } from '@/hooks/useApi';
import { useKeyboard } from '@/hooks/useKeyboard';
import { readPref, removePref, useLocalPref, writePref } from '@/hooks/useLocalPref';
import { usePageTitle } from '@/hooks/usePageTitle';
import { speak } from '@/hooks/useSpeech';
import { useTapLock } from '@/hooks/useTapLock';
import { UNDO_LIST_MS, UNDO_MASTER_MS, useToast } from '@/hooks/useToast';
import { zh } from '@/i18n/zh';
import { routePaths } from '@/routes';
import {
  backoffMs,
  initialQueue,
  isComplete,
  isWaiting,
  newClientEventId,
  queueReducer,
  selectCurrent,
  selectDone,
  selectDuePending,
  selectTotal,
  selectWaiting,
  type GradeEvent,
} from '@/study/queue';
import { localDateOf, previewAll, snapshotOf } from '@/utils/srsPreview';
import './StudyPage.css';

/** localStorage mirror of unacknowledged grade events (FRONTEND §3). */
export const PENDING_GRADES_KEY = 'wd.pendingGrades';
const ZH_TOGGLE_KEY = 'wd.zhToggle';
const CONTENT_POLL_MS = 5_000;
const CONTENT_POLL_MAX = 24;
/** "zh.study.pendingSync(n)" appears when more than one event waits for longer than this. */
const SYNC_BANNER_AFTER_MS = 10_000;
/** Dev override of the 10-minute requeue (`VITE_REQUEUE_SECONDS=30` in docs/qa-study.md). */
const REQUEUE_OVERRIDE_MS: number | null = (() => {
  const raw = import.meta.env['VITE_REQUEUE_SECONDS'] as string | undefined;
  const n = raw ? Number(raw) : Number.NaN;
  return Number.isFinite(n) && n > 0 ? n * 1000 : null;
})();

interface StoredPending {
  batchId: number | null;
  events: GradeEvent[];
}

function gradeBody(ev: GradeEvent): GradeBody {
  const body: GradeBody = { client_event_id: ev.client_event_id, grade: ev.grade };
  if (ev.elapsed_ms !== null) body.elapsed_ms = ev.elapsed_ms;
  return body;
}

/** Transient failure → keep the event and retry later; anything else is final. */
function isTransient(e: unknown): boolean {
  if (!isApiError(e)) return true;
  return e.status === 0 || e.status === 429 || e.status >= 500;
}

/**
 * Sends the events left over from a previous page load (before the batch is fetched). A transient failure
 * counts as a failed attempt (attempts + backoff, like the reducer's `fail`), so the leftover seeded into the
 * queue is picked up by `selectDuePending` and retried in-session instead of staying parked until a reload.
 */
async function flushStoredPending(): Promise<GradeEvent[]> {
  const stored = readPref<StoredPending | null>(PENDING_GRADES_KEY, null);
  if (!stored || !Array.isArray(stored.events) || stored.events.length === 0) return [];
  const leftovers: GradeEvent[] = [];
  for (const ev of stored.events) {
    try {
      await gradeItem(ev.item_id, gradeBody(ev));
    } catch (e) {
      if (isTransient(e)) {
        const attempts = (ev.attempts ?? 0) + 1;
        leftovers.push({ ...ev, attempts, next_attempt_at: new Date(Date.now() + backoffMs(attempts)).toISOString() });
      }
    }
  }
  if (leftovers.length > 0) writePref(PENDING_GRADES_KEY, { batchId: stored.batchId, events: leftovers });
  else removePref(PENDING_GRADES_KEY);
  return leftovers;
}

/** API.md 24: `queued` with neither eta nor deferral means the AI is switched off → treat as deferred. */
function deferredFrom(res: ContentResponse, nowIso: string): string | null {
  if (res.deferred_until) return res.deferred_until;
  if (res.state === 'queued' && res.eta_s === null) return nowIso;
  return null;
}

function parseBatchParam(raw: string | null): number | null {
  if (!raw) return null;
  const n = Number(raw);
  return Number.isInteger(n) && n > 0 ? n : null;
}

export default function StudyPage() {
  usePageTitle(zh.study.title);
  const [params] = useSearchParams();
  const batchParam = parseBatchParam(params.get('batch'));
  const { settings } = useAuth();
  const toast = useToast();

  const [queue, dispatch] = useReducer(queueReducer, undefined, () => initialQueue());
  const queueRef = useRef(queue);
  queueRef.current = queue;
  const [items, setItems] = useState<Record<number, StudyItem>>({});
  const [zhForced, setZhForced] = useLocalPref<boolean>(ZH_TOGGLE_KEY, false);
  const [hint, setHint] = useState(false);
  const [confirmMaster, setConfirmMaster] = useState<StudyItem | null>(null);
  const [summary, setSummary] = useState<SessionSummaryDto | null>(null);
  const [moreBusy, setMoreBusy] = useState(false);
  const [requestingContent, setRequestingContent] = useState(false);
  const [replayIndex, setReplayIndex] = useState(0);
  const [now, setNow] = useState(() => Date.now());
  const leftoverRef = useRef<GradeEvent[]>([]);
  /** In-flight delivery per `client_event_id` (first attempt or a retry). */
  const deliveries = useRef(new Map<string, Promise<GradeResponse | null>>());
  /** How the last attempt of an event ended — read by undo right after awaiting its in-flight delivery. */
  const outcomes = useRef(new Map<string, 'acked' | 'pending' | 'dropped'>());
  const shownAt = useRef(Date.now());
  const unfamiliarRef = useRef<Map<number, WordBrief>>(new Map());
  const lastUndo = useRef<(() => Promise<void>) | null>(null);
  const tapLock = useTapLock();

  const { data, error, loading, reload, setData } = useApi<TodayResponse>(
    async (signal) => {
      leftoverRef.current = await flushStoredPending();
      return batchParam !== null ? getBatch(batchParam, signal) : getToday(signal);
    },
    [batchParam],
  );
  const batch = data?.batch ?? null;
  const gradable = batch?.gradable ?? false;
  const timeZone = settings?.timezone ?? batch?.timezone;
  const isToday = batch !== null && batch.local_date === localDateOf(new Date(), timeZone);

  // ---- load the queue whenever the server hands us a batch ----------------------------------------
  useEffect(() => {
    if (!batch) return;
    setItems(Object.fromEntries(batch.items.map((it) => [it.item_id, it])));
    const seeded = [...queueRef.current.pending, ...leftoverRef.current.filter((ev) => !queueRef.current.pending.some((p) => p.client_event_id === ev.client_event_id))];
    leftoverRef.current = [];
    dispatch({ type: 'load', batchId: batch.id, items: batch.items, now: new Date().toISOString(), pending: seeded });
    setSummary(null);
    setReplayIndex(0);
  }, [batch]);

  // ---- clock: 1-s tick drives requeue due-ness, the waiting countdown and the retry loop -----------
  useEffect(() => {
    const timer = setInterval(() => {
      const d = new Date();
      dispatch({ type: 'tick', now: d.toISOString() });
      const q = queueRef.current;
      if (q.requeue.length > 0 || q.pending.length > 0) setNow(d.getTime());
    }, 1000);
    return () => clearInterval(timer);
  }, []);

  // ---- pending events ↔ localStorage ---------------------------------------------------------------
  useEffect(() => {
    if (queue.pending.length === 0) removePref(PENDING_GRADES_KEY);
    else writePref<StoredPending>(PENDING_GRADES_KEY, { batchId: queue.batchId, events: queue.pending });
    for (const id of outcomes.current.keys()) if (!queue.pending.some((p) => p.client_event_id === id)) outcomes.current.delete(id);
  }, [queue.pending, queue.batchId]);

  const currentId = selectCurrent(queue);
  const current = currentId !== null ? (items[currentId] ?? null) : null;
  const complete = batch !== null && isComplete(queue);
  const waiting = isWaiting(queue);

  // ---- shell today-badge (WP7 AppLayout): "ungraded items exist" for today's batch, once the queue holds it
  useEffect(() => {
    if (!batch || !isToday || queue.batchId !== batch.id) return;
    setTodayUngraded(!complete);
  }, [batch, isToday, queue.batchId, complete]);

  // ---- per-card bookkeeping: elapsed timer, hint reset, auto-pronounce -----------------------------
  // keyed on the card id and its display string only: a content-poll patch of the same card must not
  // restart the timer or pronounce the word again
  const currentDisplay = current?.word.display ?? null;
  const autoPronounce = settings?.auto_pronounce ?? false;
  const accent = settings?.accent ?? 'en-US';
  // word dance (FRONTEND §5.1.1, §6.5): every card plays the dance when it shows — the front face of a new / review / extra
  // card and a screen (recommended-word) card alike, however often the word has been reviewed (`danceAutoplay`, played in the mount's layout phase
  // so the word never flashes whole first); 🔊 (WordHeader) and key P (`danceToken`) replay it at any time
  const danceMode = settings?.dance_mode ?? 'full';
  const [danceToken, setDanceToken] = useState(0);
  const danceAutoplay = danceMode !== 'off' && current !== null;
  useEffect(() => {
    shownAt.current = Date.now();
    setHint(false);
    if (currentId !== null && currentDisplay && autoPronounce) speak(currentDisplay, accent);
  }, [currentId, currentDisplay, autoPronounce, accent]);

  const patchItem = useCallback((itemId: number, patch: Partial<StudyItem>) => {
    setItems((prev) => {
      const it = prev[itemId];
      return it ? { ...prev, [itemId]: { ...it, ...patch } } : prev;
    });
  }, []);

  // ---- content polling for the visible card (5 s, max 24, only while not deferred) -----------------
  const pollKey = current ? `${current.item_id}:${current.content_state}:${current.content_deferred_until ?? ''}` : '';
  useEffect(() => {
    if (!current || current.content_state !== 'queued' || current.content_deferred_until !== null) return;
    const itemId = current.item_id;
    const wordId = current.word.id;
    let count = 0;
    let cancelled = false;
    const timer = setInterval(async () => {
      if (cancelled || document.visibilityState === 'hidden') return;
      if (++count > CONTENT_POLL_MAX) {
        clearInterval(timer);
        return;
      }
      try {
        const res = await getWordContent(wordId);
        if (cancelled) return;
        const deferred = deferredFrom(res, new Date().toISOString());
        if (res.state === 'ready' && res.content) patchItem(itemId, { content: res.content, content_state: 'ready', content_deferred_until: null });
        else if (deferred) patchItem(itemId, { content_deferred_until: deferred, content_state: res.state });
        else if (res.state !== 'queued') patchItem(itemId, { content_state: res.state });
      } catch {
        /* keep polling; the card is usable with dictionary data */
      }
    }, CONTENT_POLL_MS);
    return () => {
      cancelled = true;
      clearInterval(timer);
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [pollKey, patchItem]);

  // ---- delivery of grade events ------------------------------------------------------------------
  const applyResponse = useCallback(
    (ev: GradeEvent, res: GradeResponse) => {
      const nowIso = new Date().toISOString();
      if (res.study_item) {
        const extra = res.study_item;
        setItems((prev) => ({ ...prev, [extra.item_id]: extra }));
      }
      const intermediate = res.item.result === null && res.item.requeue_at !== null;
      const requeueAt = intermediate && REQUEUE_OVERRIDE_MS !== null ? new Date(Date.now() + REQUEUE_OVERRIDE_MS).toISOString() : undefined;
      dispatch({ type: 'grade', itemId: ev.item_id, clientEventId: ev.client_event_id, response: res, now: nowIso, requeueAt });
      patchItem(ev.item_id, { mine: res.mine, result: res.item.result, requeue_at: res.item.requeue_at, skip_count: res.item.skip_count });
      if (res.duplicate) return;
      if (intermediate) toast.toast(zh.study.requeue, { id: 'requeue' });
    },
    [patchItem, toast],
  );

  const deliver = useCallback(
    (ev: GradeEvent): Promise<GradeResponse | null> => {
      const running = deliveries.current.get(ev.client_event_id);
      if (running) return running;
      const id = ev.client_event_id;
      const attempt = (async (): Promise<GradeResponse | null> => {
        try {
          const res = await gradeItem(ev.item_id, gradeBody(ev));
          outcomes.current.set(id, 'acked');
          applyResponse(ev, res);
          return res;
        } catch (e) {
          if (isApiError(e) && e.code === 'item_already_graded') {
            outcomes.current.set(id, 'acked');
            dispatch({ type: 'drop', clientEventId: id });
            void reload();
            return null;
          }
          if (isApiError(e) && e.code === 'invalid_transition') {
            outcomes.current.set(id, 'dropped');
            dispatch({ type: 'drop', clientEventId: id });
            dispatch({ type: 'remove', itemId: ev.item_id });
            return null;
          }
          if (isTransient(e)) {
            outcomes.current.set(id, 'pending');
            dispatch({ type: 'fail', clientEventId: id, now: new Date().toISOString() });
            return null;
          }
          outcomes.current.set(id, 'dropped');
          dispatch({ type: 'drop', clientEventId: id });
          toast.error(errorMessage(e));
          return null;
        } finally {
          deliveries.current.delete(id);
        }
      })();
      deliveries.current.set(id, attempt);
      return attempt;
    },
    [applyResponse, reload, toast],
  );

  // retry loop: backoff 1 s, 3 s, 10 s…
  useEffect(() => {
    for (const ev of selectDuePending(queue, new Date(now).toISOString())) void deliver(ev);
  }, [now, queue, deliver]);

  const submittingItems = useRef(new Set<number>());
  const submit = useCallback(
    (item: StudyItem, grade: Grade | ScreenVerdict): Promise<GradeResponse | null> => {
      // a double tap on the same card must not produce two events (the first one already advanced the card)
      if (submittingItems.current.has(item.item_id)) return Promise.resolve(null);
      submittingItems.current.add(item.item_id);
      const nowIso = new Date().toISOString();
      const ev: GradeEvent = {
        client_event_id: newClientEventId(),
        item_id: item.item_id,
        grade,
        elapsed_ms: Math.max(0, Math.min(Date.now() - shownAt.current, 600_000)),
        created_at: nowIso,
        attempts: 0,
        next_attempt_at: nowIso,
      };
      dispatch({ type: 'submit', event: ev, now: nowIso });
      tapLock.arm();
      return deliver(ev).finally(() => submittingItems.current.delete(item.item_id));
    },
    [deliver, tapLock],
  );

  // ---- user actions ----------------------------------------------------------------------------------
  const restoreItem = useCallback(
    async (item: StudyItem, extraItemId: number | null, successMessage: string) => {
      try {
        // a grade of this card that the server has not acknowledged yet (first attempt in flight, or parked
        // in `pending` after a transient failure): wait for the attempt under way, then decide
        const unacked = queueRef.current.pending.find((p) => p.item_id === item.item_id);
        if (unacked) {
          await deliveries.current.get(unacked.client_event_id);
          if ((outcomes.current.get(unacked.client_event_id) ?? 'pending') === 'pending') {
            // never reached the server: nothing to restore there — cancel the event and re-open the card
            dispatch({ type: 'drop', clientEventId: unacked.client_event_id });
            dispatch({ type: 'restore', itemId: item.item_id });
            patchItem(item.item_id, { result: null, requeue_at: null });
            toast.success(successMessage);
            return;
          }
        }
        // the server puts the prior SRS snapshot back: keep its `mine` so the re-opened card previews from it
        const r = await markWord(item.word.id, { action: 'restore', context: 'today' });
        dispatch({ type: 'restore', itemId: item.item_id });
        if (extraItemId !== null) {
          dispatch({ type: 'remove', itemId: extraItemId });
          setItems((prev) => {
            const next = { ...prev };
            delete next[extraItemId];
            return next;
          });
        }
        patchItem(item.item_id, { mine: r.mine, result: null, requeue_at: null });
        toast.success(successMessage);
      } catch (e) {
        toast.error(errorMessage(e));
      }
    },
    [patchItem, toast],
  );

  const onGrade = useCallback(
    (item: StudyItem, grade: Grade | ScreenVerdict) => {
      if (item.kind === 'screen') {
        const verdict = grade as ScreenVerdict;
        const promise = submit(item, verdict);
        if (verdict === 'skip') return;
        void promise.then((res) => {
          if (!res || res.duplicate) return;
          let extraId: number | null = null;
          let message = zh.screen.markedKnown(item.word.display);
          if (verdict === 'unfamiliar') {
            unfamiliarRef.current.set(item.word.id, item.word);
            extraId = res.study_item?.item_id ?? null;
            message = res.study_item ? zh.screen.addedToday : zh.screen.addedTomorrow;
          }
          const undo = () => restoreItem(item, extraId, zh.common.undone);
          lastUndo.current = undo;
          toast.toast(message, {
            durationMs: UNDO_LIST_MS,
            action: {
              label: zh.common.undo,
              onClick: async () => {
                lastUndo.current = null;
                await undo();
              },
            },
          });
          setTimeout(() => {
            if (lastUndo.current === undo) lastUndo.current = null;
          }, UNDO_LIST_MS);
        });
        return;
      }
      if (grade === 'again') unfamiliarRef.current.set(item.word.id, item.word);
      void submit(item, grade);
    },
    [submit, restoreItem, toast],
  );

  const master = useCallback(
    (item: StudyItem) => {
      void submit(item, 'master');
      toast.toast(zh.study.mastered, {
        durationMs: UNDO_MASTER_MS,
        action: { label: zh.common.undo, onClick: () => restoreItem(item, null, zh.study.restored) },
      });
    },
    [submit, restoreItem, toast],
  );

  const onMaster = useCallback(
    (item: StudyItem) => {
      if (item.mine?.srs.mastery_suggested) master(item);
      else setConfirmMaster(item);
    },
    [master],
  );

  const onSkip = useCallback(
    (item: StudyItem) => {
      void submit(item, 'skip');
    },
    [submit],
  );

  // Button taps on the card: a double tap lands on the card that advanced under the finger (screen cards show
  // their verdict buttons at once, the header skip button is on every front), so taps right after a grade are dropped.
  // The keyboard map below calls onGrade / onSkip / onMaster directly and is never locked.
  const tapGrade = (item: StudyItem, grade: Grade | ScreenVerdict) => {
    if (tapLock.locked()) return;
    onGrade(item, grade);
  };
  const tapMaster = (item: StudyItem) => {
    if (tapLock.locked()) return;
    onMaster(item);
  };
  const tapSkip = (item: StudyItem) => {
    if (tapLock.locked()) return;
    onSkip(item);
  };

  const requestContent = useCallback(
    async (item: StudyItem) => {
      setRequestingContent(true);
      try {
        const res = await requestWordContent(item.word.id);
        patchItem(item.item_id, { content_state: res.state === 'ready' ? 'ready' : 'queued', content_deferred_until: null });
        toast.toast(zh.word.examplesQueued);
      } catch (e) {
        if (isApiError(e) && e.code === 'budget_exhausted') {
          const resumesAt = typeof e.details?.['resumes_at'] === 'string' ? (e.details['resumes_at'] as string) : new Date().toISOString();
          patchItem(item.item_id, { content_deferred_until: resumesAt });
        }
        if (isApiError(e) && e.code === 'rate_limited' && (e.detailNumber('retry_after_s') ?? 0) > 600) toast.error(zh.word.examplesQuotaToday); // the per-user daily quota (resets at UTC midnight), not a burst limit
        else toast.error(errorMessage(e));
      } finally {
        setRequestingContent(false);
      }
    },
    [patchItem, toast],
  );

  const more = useCallback(
    async (source: MoreSource) => {
      setMoreBusy(true);
      try {
        const res = await requestMore({ source });
        setData(res);
        if ((res.added ?? 0) === 0) toast.toast(zh.today.nothingMore);
      } catch (e) {
        if (isApiError(e) && e.code === 'batch_not_ready') toast.error(zh.today.buildFirst);
        else toast.error(errorMessage(e));
      } finally {
        setMoreBusy(false);
      }
    },
    [setData, toast],
  );

  const build = useCallback(async () => {
    try {
      setData(await buildToday());
    } catch (e) {
      toast.error(errorMessage(e));
    }
  }, [setData, toast]);

  // ---- completion → summary ----------------------------------------------------------------------
  const completing = useRef(false);
  useEffect(() => {
    if (!batch || !gradable || !complete || summary || queue.pending.length > 0 || completing.current) return;
    completing.current = true;
    (async () => {
      try {
        if (isToday) {
          const res = await completeToday();
          setSummary(res.summary);
        } else {
          setSummary({
            local_date: batch.local_date,
            review: batch.counts.review,
            new: batch.counts.new,
            extra: batch.counts.extra,
            screen: batch.counts.screen,
            again: 0,
            hard: 0,
            good: 0,
            mastered: 0,
            known: 0,
            unfamiliar: 0,
            study_minutes: queue.startedAt ? Math.round((Date.now() - Date.parse(queue.startedAt)) / 60_000) : 0,
            streak_days: data?.streak_days ?? 0,
            goal_met: true,
            next_push_at: data?.next_push_at ?? null,
            can_request_more: false,
          });
        }
      } catch (e) {
        toast.error(errorMessage(e));
      } finally {
        completing.current = false;
      }
    })();
  }, [batch, gradable, complete, summary, queue.pending.length, queue.startedAt, isToday, data, toast]);

  // ---- keyboard (FRONTEND §5.1.3: Space / 1 / 2 / 3 / 4 / S / P / Z / H; U = undo a screen card verdict) --
  const sessionActive = gradable && !summary && current !== null;
  useKeyboard(
    {
      Space: () => {
        if (!current) return;
        if (!queue.revealed) dispatch({ type: 'reveal' });
      },
      '1': () => current && (current.kind === 'screen' ? onGrade(current, 'known') : queue.revealed && onGrade(current, 'again')),
      '2': () => current && (current.kind === 'screen' ? onGrade(current, 'unfamiliar') : queue.revealed && onGrade(current, 'hard')),
      '3': () => current && current.kind !== 'screen' && queue.revealed && onGrade(current, 'good'),
      '4': () => current && current.kind !== 'screen' && queue.revealed && onMaster(current),
      s: () => current && onSkip(current),
      p: () => {
        if (!current) return;
        speak(current.word.display, accent);
        if (danceMode !== 'off') setDanceToken((t) => t + 1);
      },
      z: () => setZhForced((v) => !v),
      h: () => setHint((v) => !v),
      u: () => {
        const undo = lastUndo.current;
        lastUndo.current = null;
        if (undo) void undo();
      },
    },
    { enabled: sessionActive },
  );

  // ---- render ----------------------------------------------------------------------------------------
  if (loading && !data) {
    return (
      <section className="page study-page" aria-busy="true">
        <Skeleton height={28} width="40%" />
        <Skeleton height={160} className="study-page__skeleton" />
        <Skeleton lines={4} />
      </section>
    );
  }

  if (error && !data) {
    return (
      <section className="page study-page">
        <EmptyState title={errorMessage(error)} action={{ label: zh.common.retry, onClick: () => void reload() }} />
      </section>
    );
  }

  if (!batch) {
    return (
      <section className="page study-page">
        <EmptyState
          title={zh.today.buildFirst}
          description={data?.push_time ? zh.today.notYet(data.push_time) : undefined}
          action={batchParam === null && data?.can_build_now ? { label: zh.today.buildNow, onClick: () => void build() } : { label: zh.common.backToToday, to: routePaths.today }}
        />
      </section>
    );
  }

  const done = selectDone(queue);
  const total = selectTotal(queue);
  const pendingCount = queue.pending.length;
  const oldestPending = queue.pending.reduce<number | null>((acc, p) => {
    const t = Date.parse(p.created_at);
    return Number.isNaN(t) ? acc : acc === null ? t : Math.min(acc, t);
  }, null);
  const showSyncBanner = pendingCount > 1 && oldestPending !== null && now - oldestPending > SYNC_BANNER_AFTER_MS;

  // read-only replay of an older batch
  if (!gradable) {
    const list = batch.items;
    const item = list[Math.min(replayIndex, Math.max(0, list.length - 1))] ?? null;
    return (
      <section className="page study-page study-page--replay">
        <header className="study-page__head">
          <Link to={routePaths.batch(batch.id)} className="study-page__exit">
            {zh.common.back}
          </Link>
          <span className="study-page__progress muted">{zh.study.position(list.length > 0 ? Math.min(replayIndex + 1, list.length) : 0, list.length)}</span>
          <Link to={routePaths.today} className="study-page__exit">
            {zh.common.backToToday}
          </Link>
        </header>
        {item ? (
          <StudyCard
            key={item.item_id}
            item={item}
            revealed
            readOnly
            onReveal={() => undefined}
            onGrade={() => undefined}
            onMaster={() => undefined}
            onSkip={() => undefined}
            zhMode={settings?.zh_examples ?? 'tap'}
            showImage={settings?.show_images ?? true}
            imageWord={settings?.image_word ?? true}
            preview={previewAll(snapshotOf(item.mine), { uwId: item.mine?.id ?? null, timeZone })}
            zhForced={zhForced}
            accent={settings?.accent}
            onlyStages={settings?.stages}
            danceMode={danceMode}
            position={Math.min(replayIndex + 1, list.length)}
            total={list.length}
          />
        ) : (
          <EmptyState title={zh.history.empty} action={{ label: zh.common.backToToday, to: routePaths.today }} />
        )}
        {list.length > 1 && (
          <nav className="study-page__replay-nav" aria-label={zh.history.replay}>
            <Button variant="secondary" disabled={replayIndex <= 0} onClick={() => setReplayIndex((i) => Math.max(0, i - 1))}>
              ←
            </Button>
            {item && resultLabel(item.result) && <span className="muted">{resultLabel(item.result)}</span>}
            <Button variant="secondary" disabled={replayIndex >= list.length - 1} onClick={() => setReplayIndex((i) => Math.min(list.length - 1, i + 1))}>
              →
            </Button>
          </nav>
        )}
      </section>
    );
  }

  const unfamiliarWords = Array.from(unfamiliarRef.current.values());
  const waitingEntries = selectWaiting(queue);
  const nextAt = waitingEntries[0] ? Date.parse(waitingEntries[0].at) : null;
  const waitMinutes = nextAt !== null ? Math.max(1, Math.ceil((nextAt - now) / 60_000)) : 1;

  return (
    <section className="page study-page">
      <header className="study-page__head">
        <Link to={routePaths.today} className="study-page__exit">
          {zh.common.backToToday}
        </Link>
        <div className="study-page__meter" role="progressbar" aria-valuemin={0} aria-valuemax={total} aria-valuenow={done} aria-label={zh.study.title}>
          <span className="study-page__meter-fill" style={{ width: total > 0 ? `${(done / total) * 100}%` : '0%' }} />
        </div>
        <span className="study-page__progress muted">{zh.history.completed(done, total)}</span>
      </header>

      {showSyncBanner && (
        <p className="study-page__sync" role="status">
          {zh.study.pendingSync(pendingCount)}
        </p>
      )}

      {summary ? (
        <SessionSummary summary={summary} unfamiliarWords={unfamiliarWords} onMoreNew={() => void more('new')} onMoreScreen={() => void more('screen')} busy={moreBusy} />
      ) : current ? (
        <StudyCard
          key={current.item_id}
          item={current}
          revealed={queue.revealed}
          onReveal={() => dispatch({ type: 'reveal' })}
          onGrade={(g) => tapGrade(current, g)}
          onMaster={() => tapMaster(current)}
          onSkip={() => tapSkip(current)}
          zhMode={settings?.zh_examples ?? 'tap'}
          showImage={settings?.show_images ?? true}
          imageWord={settings?.image_word ?? true}
          preview={previewAll(snapshotOf(current.mine), { uwId: current.mine?.id ?? null, timeZone })}
          hint={hint}
          onHint={() => setHint(true)}
          zhForced={zhForced}
          busy={submittingItems.current.has(current.item_id)}
          position={Math.min(done + 1, Math.max(total, 1))}
          total={total}
          accent={settings?.accent}
          onlyStages={settings?.stages}
          danceMode={danceMode}
          danceToken={danceToken}
          danceAutoplay={danceAutoplay}
          onRequestContent={() => void requestContent(current)}
          requestingContent={requestingContent}
        />
      ) : waiting ? (
        <div className="study-page__waiting" role="status">
          <p className="study-page__waiting-text">{zh.study.waiting(waitingEntries.length, waitMinutes)}</p>
          <Button variant="primary" onClick={() => dispatch({ type: 'reviewNow' })}>
            {zh.study.reviewNow}
          </Button>
        </div>
      ) : complete ? (
        <div className="study-page__waiting" role="status" aria-busy="true">
          <Skeleton lines={3} />
        </div>
      ) : (
        <EmptyState title={zh.today.done} action={{ label: zh.common.backToToday, to: routePaths.today }} />
      )}

      <ConfirmDialog
        open={confirmMaster !== null}
        message={zh.study.masterConfirm}
        confirmLabel={zh.study.master}
        onConfirm={() => {
          const item = confirmMaster;
          setConfirmMaster(null);
          if (item) master(item);
        }}
        onCancel={() => setConfirmMaster(null)}
      />
    </section>
  );
}
