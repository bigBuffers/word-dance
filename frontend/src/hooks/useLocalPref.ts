// useLocalPref — per-viewer conveniences in localStorage (FRONTEND.md §3): never authoritative,
// every access wrapped in try/catch (private windows, blocked storage), JSON-serialised, synced
// across tabs through the `storage` event. Keys are namespaced by the caller (e.g. 'wd.vocabTab').
import { useCallback, useEffect, useRef, useState } from 'react';

export function readPref<T>(key: string, fallback: T): T {
  try {
    const raw = window.localStorage.getItem(key);
    if (raw === null) return fallback;
    return JSON.parse(raw) as T;
  } catch {
    return fallback;
  }
}

export function writePref<T>(key: string, value: T): void {
  try {
    window.localStorage.setItem(key, JSON.stringify(value));
  } catch {
    /* storage unavailable — the preference simply does not persist */
  }
}

export function removePref(key: string): void {
  try {
    window.localStorage.removeItem(key);
  } catch {
    /* ignore */
  }
}

export type SetPref<T> = (next: T | ((prev: T) => T)) => void;

/**
 * `[value, setValue, reset]` backed by `localStorage[key]`. `fallback` is used when the key is
 * missing or unreadable; `reset()` removes the key and restores the fallback.
 */
export function useLocalPref<T>(key: string, fallback: T): [T, SetPref<T>, () => void] {
  const [value, setValue] = useState<T>(() => readPref(key, fallback));
  const valueRef = useRef(value);
  const fallbackRef = useRef(fallback);
  useEffect(() => {
    valueRef.current = value;
    fallbackRef.current = fallback;
  });

  useEffect(() => {
    const onStorage = (e: StorageEvent) => {
      if (e.key !== key && e.key !== null) return;
      const next = readPref(key, fallbackRef.current);
      valueRef.current = next;
      setValue(next);
    };
    window.addEventListener('storage', onStorage);
    return () => window.removeEventListener('storage', onStorage);
  }, [key]);

  const set = useCallback<SetPref<T>>(
    (next) => {
      const resolved = typeof next === 'function' ? (next as (prev: T) => T)(valueRef.current) : next;
      valueRef.current = resolved;
      writePref(key, resolved);
      setValue(resolved);
    },
    [key],
  );

  const reset = useCallback(() => {
    removePref(key);
    valueRef.current = fallbackRef.current;
    setValue(fallbackRef.current);
  }, [key]);

  return [value, set, reset];
}
