// useTapLock — guards the screening / study verdict buttons against a double tap (FRONTEND §5.4): the card
// advances optimistically on the first tap, so a second tap ~100–200 ms later would land on the NEXT card's
// button and judge a word the user never saw. Pages `arm()` the lock whenever a verdict advanced the card
// and drop pointer-originated verdicts while `locked()`. Keyboard shortcuts are never locked (rapid 1/1/1
// keying is the intended desktop flow; `useKeyboard` already drops auto-repeat).
import { useMemo, useRef } from 'react';

/** Pointer taps arriving within this many ms after a card change are ignored. */
export const TAP_LOCK_MS = 250;

export interface TapLock {
  /** Record that the card just advanced. */
  arm: () => void;
  /** True while taps must be ignored. */
  locked: () => boolean;
}

export function useTapLock(ms: number = TAP_LOCK_MS): TapLock {
  const armedAt = useRef(0);
  return useMemo(
    () => ({
      arm: () => {
        armedAt.current = Date.now();
      },
      locked: () => Date.now() - armedAt.current < ms,
    }),
    [ms],
  );
}
