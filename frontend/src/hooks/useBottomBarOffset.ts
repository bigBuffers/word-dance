// useBottomBarOffset — tells the toast viewport how far the sticky grade / verdict bar reaches up from the
// bottom of the viewport (FRONTEND §3 toasts, §5.1 grade bar, §5.4 screen card). The toast viewport is fixed
// bottom-centre just above the tab bar — exactly where the study card's again / hard / good and the screen card's
// known / unfamiliar buttons sit — so without this the 5-s undo toast and the requeue toast covered the buttons the
// learner was about to press. The bar's ref callback measures the bar (ResizeObserver, window resize and scroll)
// and writes `--bottom-bar-h` on <html> with the `has-bottom-bar` class; `ui.css` then stacks the toasts above it.
// Unmounting the bar (read-only replay, session summary, another page) removes both again.
//
// Ownership: the value on <html> is global, but cards are keyed per item, so React commits a card swap as
// "detach the old ref → attach the new ref → run the OLD instance's effect cleanup". A clear is therefore only
// honoured from the instance that published the current value (a token per hook instance); a bar-less instance
// (a read-only card, the front face) can never wipe another card's bar on resize either.
import { useCallback, useEffect, useRef, useState } from 'react';

export const BOTTOM_BAR_VAR = '--bottom-bar-h';
export const BOTTOM_BAR_CLASS = 'has-bottom-bar';

/**
 * Distance (px) from the bottom of a `viewportHeight`-tall viewport to the top edge of a bar with `rect`:
 * the toast's `bottom`. 0 for an empty or off-screen bar (the caller then keeps the default position). A bar
 * whose top edge is in the upper half of the viewport — only possible when the bar itself is taller than half
 * the viewport, e.g. a landscape phone — contributes its own height, so the toasts never float mid-screen.
 */
export function bottomBarOffset(rect: Pick<DOMRect, 'top' | 'height'>, viewportHeight: number): number {
  const fromBottom = viewportHeight - rect.top;
  if (!Number.isFinite(fromBottom) || fromBottom <= 0 || !Number.isFinite(rect.height) || rect.height <= 0) return 0;
  return Math.max(0, Math.round(fromBottom <= viewportHeight / 2 ? fromBottom : rect.height));
}

let owner: object | null = null;
let published: number | null = null;

function publish(token: object, offset: number | null): void {
  if (typeof document === 'undefined') return;
  const root = document.documentElement;
  if (offset === null) {
    if (owner !== token) return; // another bar owns the value: a card swap's late cleanup, or a bar-less instance on resize
    owner = null;
    published = null;
    root.style.removeProperty(BOTTOM_BAR_VAR);
    root.classList.remove(BOTTOM_BAR_CLASS);
    return;
  }
  owner = token;
  if (published === offset) return; // scroll / resize listeners: no style recalculation when nothing moved
  published = offset;
  root.style.setProperty(BOTTOM_BAR_VAR, `${offset}px`);
  root.classList.add(BOTTOM_BAR_CLASS);
}

/** Test seam: forget the current owner (the DOM is left to the test's own cleanup). */
export function resetBottomBarOwner(): void {
  owner = null;
  published = null;
}

/** Ref callback for the one bottom action bar of the page; `null` (bar unmounted) or a zero-height bar clears the offset. */
export function useBottomBarOffset<T extends HTMLElement = HTMLElement>(): (el: T | null) => void {
  const [token] = useState<object>(() => ({}));
  const elRef = useRef<T | null>(null);
  const observerRef = useRef<ResizeObserver | null>(null);

  const measure = useCallback(() => {
    const el = elRef.current;
    if (!el || typeof window === 'undefined') {
      publish(token, null);
      return;
    }
    const offset = bottomBarOffset(el.getBoundingClientRect(), window.innerHeight);
    publish(token, offset > 0 ? offset : null); // an unmeasurable bar (not laid out, hidden) keeps the default position above the tab bar
  }, [token]);

  const ref = useCallback(
    (el: T | null) => {
      observerRef.current?.disconnect();
      observerRef.current = null;
      elRef.current = el;
      if (el && typeof ResizeObserver !== 'undefined') {
        observerRef.current = new ResizeObserver(() => measure());
        observerRef.current.observe(el);
      }
      measure();
    },
    [measure],
  );

  useEffect(() => {
    window.addEventListener('resize', measure);
    window.addEventListener('scroll', measure, { passive: true });
    return () => {
      window.removeEventListener('resize', measure);
      window.removeEventListener('scroll', measure);
      observerRef.current?.disconnect();
      observerRef.current = null;
      elRef.current = null;
      publish(token, null);
    };
  }, [measure, token]);

  return ref;
}
