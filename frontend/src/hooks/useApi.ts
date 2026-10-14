// useApi — page-data hook (FRONTEND.md §3): `{data, error, loading, reload, setData}`.
// Re-runs the fetcher when `deps` change, aborts the previous in-flight request, ignores stale
// results and never surfaces AbortErrors. Optimistic updates patch `setData` and roll back on error.
import { useCallback, useEffect, useRef, useState, type DependencyList, type Dispatch, type SetStateAction } from 'react';
import { ApiError, isAbortError } from '@/api/client';
import { zh } from '@/i18n/zh';

export interface UseApiOptions {
  /** When false the fetcher does not run and `loading` is false (e.g. waiting for a param). Default true. */
  enabled?: boolean;
  /** Keep the previous `data` visible while reloading (default: keep; errors are cleared on each run). */
  keepPreviousData?: boolean;
}

export interface UseApiResult<T> {
  data: T | null;
  error: ApiError | null;
  loading: boolean;
  /** Re-runs the fetcher; resolves once that run has settled. */
  reload: () => Promise<void>;
  setData: Dispatch<SetStateAction<T | null>>;
}

export function useApi<T>(fetcher: (signal: AbortSignal) => Promise<T>, deps: DependencyList, options: UseApiOptions = {}): UseApiResult<T> {
  const { enabled = true, keepPreviousData = true } = options;
  const [data, setData] = useState<T | null>(null);
  const [error, setError] = useState<ApiError | null>(null);
  const [loading, setLoading] = useState<boolean>(enabled);
  const [tick, setTick] = useState(0);

  // Latest fetcher without re-running the effect when the closure identity changes.
  const fetcherRef = useRef(fetcher);
  useEffect(() => {
    fetcherRef.current = fetcher;
  });

  const waitersRef = useRef<Array<() => void>>([]);

  useEffect(() => {
    if (!enabled) {
      setLoading(false);
      return;
    }
    const controller = new AbortController();
    setLoading(true);
    setError(null);
    if (!keepPreviousData) setData(null);
    fetcherRef.current(controller.signal).then(
      (result) => {
        if (controller.signal.aborted) return;
        setData(result);
        setLoading(false);
      },
      (e: unknown) => {
        if (controller.signal.aborted || isAbortError(e)) return;
        setError(e instanceof ApiError ? e : new ApiError('internal_error', 0, zh.errors.server));
        setLoading(false);
      },
    );
    return () => controller.abort();
    // deps are the caller's explicit dependency list (same contract as useEffect)
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [...deps, tick, enabled, keepPreviousData]);

  // Resolve pending `reload()` promises once a run has settled.
  useEffect(() => {
    if (loading) return;
    const waiters = waitersRef.current;
    waitersRef.current = [];
    for (const resolve of waiters) resolve();
  }, [loading]);

  const reload = useCallback(
    () =>
      new Promise<void>((resolve) => {
        waitersRef.current.push(resolve);
        setTick((t) => t + 1);
      }),
    [],
  );

  return { data, error, loading, reload, setData };
}
