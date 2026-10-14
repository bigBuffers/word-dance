// usePolling — `usePolling(fn, intervalMs, {enabled, max})` (FRONTEND.md §3).
//
// Calls `fn` every `intervalMs` while `enabled` and the document is visible (hidden tabs pause and
// resume on `visibilitychange`), stops after `max` calls or when `fn` resolves to `false`
// ("resolved, nothing more to poll"). Calls never overlap: the next tick is scheduled only after
// the previous call settled. The in-flight request is aborted on disable/unmount. Toggling
// `enabled` false → true (or calling `restart()`) starts a fresh cycle with the counter reset.
import { useCallback, useEffect, useRef, useState } from 'react';
import { isAbortError } from '@/api/client';

export interface PollingOptions {
  /** Poll only while true (default true). */
  enabled?: boolean;
  /** Maximum number of calls per cycle (default unlimited). */
  max?: number;
  /** Run the first call at once instead of after the first interval (default false). */
  immediate?: boolean;
}

export interface PollingState {
  /** Calls made in the current cycle. */
  polls: number;
  /** The cycle ended because `max` was reached or `fn` returned `false`. */
  exhausted: boolean;
  /** Starts a new cycle (counter reset) — e.g. after 「生成例句」 re-enqueued content. */
  restart: () => void;
}

export type PollFn = (signal: AbortSignal) => Promise<unknown>;

function isVisible(): boolean {
  return typeof document === 'undefined' || document.visibilityState !== 'hidden';
}

export function usePolling(fn: PollFn, intervalMs: number, options: PollingOptions = {}): PollingState {
  const { enabled = true, max, immediate = false } = options;
  const [polls, setPolls] = useState(0);
  const [exhausted, setExhausted] = useState(false);
  const [cycle, setCycle] = useState(0);

  const fnRef = useRef(fn);
  useEffect(() => {
    fnRef.current = fn;
  });

  useEffect(() => {
    setPolls(0);
    setExhausted(false);
    if (!enabled) return;

    let stopped = false;
    let count = 0;
    let timer: ReturnType<typeof setTimeout> | null = null;
    let waitingForVisibility = false;
    const controller = new AbortController();

    const schedule = (delay: number) => {
      if (stopped) return;
      timer = setTimeout(() => {
        timer = null;
        void tick();
      }, delay);
    };

    const finish = () => {
      stopped = true;
      setExhausted(true);
    };

    const tick = async () => {
      if (stopped) return;
      if (!isVisible()) {
        waitingForVisibility = true; // resume on visibilitychange
        return;
      }
      if (max !== undefined && count >= max) {
        finish();
        return;
      }
      count += 1;
      setPolls(count);
      let result: unknown;
      try {
        result = await fnRef.current(controller.signal);
      } catch (e) {
        if (stopped || isAbortError(e)) return;
        result = undefined; // errors are the caller's business; keep polling until max
      }
      if (stopped) return;
      if (result === false) {
        finish();
        return;
      }
      if (max !== undefined && count >= max) {
        finish();
        return;
      }
      schedule(intervalMs);
    };

    const onVisibility = () => {
      if (stopped || !isVisible() || !waitingForVisibility) return;
      waitingForVisibility = false;
      schedule(intervalMs);
    };
    if (typeof document !== 'undefined') document.addEventListener('visibilitychange', onVisibility);

    if (immediate) void tick();
    else schedule(intervalMs);

    return () => {
      stopped = true;
      if (timer) clearTimeout(timer);
      controller.abort();
      if (typeof document !== 'undefined') document.removeEventListener('visibilitychange', onVisibility);
    };
  }, [enabled, intervalMs, max, immediate, cycle]);

  const restart = useCallback(() => setCycle((c) => c + 1), []);

  return { polls, exhausted, restart };
}
