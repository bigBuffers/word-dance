// useKeyboard — page-level keyboard shortcuts for the study and screening sessions (FRONTEND §5.1/§5.4:
// Space / 1 / 2 / 3 / 4 / S / P / Z / H / U). Keys are matched by `normalizeKey()` (`' '` → `Space`,
// letters lower-cased); shortcuts are ignored while typing in a form control, while a native <dialog>
// is open (the dialog owns the keyboard) and when a modifier is held, so browser shortcuts keep working.
import { useEffect, useRef } from 'react';

export type KeyHandler = (event: KeyboardEvent) => void;
/** Map of normalised key → handler, e.g. `{ Space: reveal, '1': again, s: skip }`. */
export type KeyMap = Record<string, KeyHandler | undefined>;

export interface UseKeyboardOptions {
  /** Default true. */
  enabled?: boolean;
  /** Also fire while an input/textarea/select has focus (default false). */
  allowInInputs?: boolean;
}

export function normalizeKey(event: Pick<KeyboardEvent, 'key'>): string {
  const key = event.key;
  if (key === ' ' || key === 'Spacebar') return 'Space';
  if (key.length === 1) return key.toLowerCase();
  return key;
}

export function isEditableTarget(target: EventTarget | null): boolean {
  if (!(target instanceof HTMLElement)) return false;
  const tag = target.tagName;
  if (tag === 'INPUT' || tag === 'TEXTAREA' || tag === 'SELECT') return true;
  return target.isContentEditable;
}

function dialogOpen(): boolean {
  return typeof document !== 'undefined' && document.querySelector('dialog[open]') !== null;
}

export function useKeyboard(map: KeyMap, options: UseKeyboardOptions = {}): void {
  const { enabled = true, allowInInputs = false } = options;
  const mapRef = useRef(map);
  useEffect(() => {
    mapRef.current = map;
  });

  useEffect(() => {
    if (!enabled) return;
    const onKeyDown = (event: KeyboardEvent) => {
      if (event.defaultPrevented || event.repeat) return;
      if (event.ctrlKey || event.metaKey || event.altKey) return;
      if (!allowInInputs && isEditableTarget(event.target)) return;
      if (dialogOpen()) return;
      const handler = mapRef.current[normalizeKey(event)];
      if (!handler) return;
      event.preventDefault();
      handler(event);
    };
    window.addEventListener('keydown', onKeyDown);
    return () => window.removeEventListener('keydown', onKeyDown);
  }, [enabled, allowInInputs]);
}
