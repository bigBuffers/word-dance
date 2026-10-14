// useDebounce — debounced value / callback (search 250 ms, add-words preview 300 ms; FRONTEND §5.5/§5.6).
import { useEffect, useMemo, useRef, useState } from 'react';

/** Returns `value` once it has been stable for `delayMs`. */
export function useDebounce<T>(value: T, delayMs = 250): T {
  const [debounced, setDebounced] = useState(value);
  useEffect(() => {
    const timer = setTimeout(() => setDebounced(value), delayMs);
    return () => clearTimeout(timer);
  }, [value, delayMs]);
  return debounced;
}

export interface DebouncedFn<A extends unknown[]> {
  (...args: A): void;
  /** Drops a pending call. */
  cancel(): void;
  /** Runs a pending call immediately. */
  flush(): void;
}

/** A stable debounced wrapper around the latest `fn`; pending calls are cancelled on unmount. */
export function useDebouncedCallback<A extends unknown[]>(fn: (...args: A) => void, delayMs = 250): DebouncedFn<A> {
  const fnRef = useRef(fn);
  useEffect(() => {
    fnRef.current = fn;
  });

  const debounced = useMemo<DebouncedFn<A>>(() => {
    let timer: ReturnType<typeof setTimeout> | null = null;
    let pending: A | null = null;
    const run = () => {
      timer = null;
      if (pending) {
        const args = pending;
        pending = null;
        fnRef.current(...args);
      }
    };
    const wrapped = ((...args: A) => {
      pending = args;
      if (timer) clearTimeout(timer);
      timer = setTimeout(run, delayMs);
    }) as DebouncedFn<A>;
    wrapped.cancel = () => {
      if (timer) clearTimeout(timer);
      timer = null;
      pending = null;
    };
    wrapped.flush = () => {
      if (timer) clearTimeout(timer);
      run();
    };
    return wrapped;
  }, [delayMs]);

  useEffect(() => () => debounced.cancel(), [debounced]);
  return debounced;
}
