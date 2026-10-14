import { useEffect, type RefObject } from 'react';

/**
 * Mirrors a boolean `open` prop onto a native `<dialog>`: `showModal()` when supported (modal,
 * inert background, Esc → `cancel` event), falling back to the `open` attribute (older engines, jsdom).
 */
export function useNativeDialog(ref: RefObject<HTMLDialogElement | null>, open: boolean): void {
  useEffect(() => {
    const el = ref.current;
    if (!el) return;
    if (open) {
      if (el.open) return;
      if (typeof el.showModal === 'function') {
        try {
          el.showModal();
        } catch {
          el.setAttribute('open', '');
        }
      } else {
        el.setAttribute('open', '');
      }
    } else if (el.open) {
      if (typeof el.close === 'function') el.close();
      else el.removeAttribute('open');
    }
  }, [ref, open]);
}
