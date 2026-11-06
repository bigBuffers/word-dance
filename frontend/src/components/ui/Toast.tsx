// Toast — provider + bottom-centre viewport (FRONTEND §3): ≤ 3 visible (the rest queue), optional
// action button with a countdown and progress bar (undo toasts: 8 s for mastered, 5 s for list toggles).
// On a page with a sticky grade / verdict bar the viewport sits above the bar (`html.has-bottom-bar` +
// `--bottom-bar-h`, published by hooks/useBottomBarOffset) so a toast never covers the known / unfamiliar buttons.
import { useCallback, useEffect, useMemo, useState, type ReactNode } from 'react';
import { DEFAULT_TOAST_MS, ERROR_TOAST_MS, MAX_VISIBLE_TOASTS, ToastContext, type ToastApi, type ToastItem, type ToastOptions } from '@/hooks/useToast';
import { zh } from '@/i18n/zh';
import { cx } from './cx';
import { CloseIcon } from './icons';
import './ui.css';

let sequence = 0;

export function ToastProvider({ children }: { children: ReactNode }) {
  const [items, setItems] = useState<ToastItem[]>([]);

  const dismiss = useCallback((id: string) => {
    setItems((prev) => (prev.some((t) => t.id === id) ? prev.filter((t) => t.id !== id) : prev));
  }, []);
  const dismissAll = useCallback(() => setItems([]), []);

  const toast = useCallback((message: string, options: ToastOptions = {}): string => {
    const kind = options.kind ?? 'info';
    const id = options.id ?? `toast-${++sequence}`;
    const item: ToastItem = {
      id,
      message,
      kind,
      durationMs: options.durationMs ?? (kind === 'error' ? ERROR_TOAST_MS : DEFAULT_TOAST_MS),
      createdAt: Date.now(),
      ...(options.action ? { action: options.action } : {}),
    };
    setItems((prev) => [...prev.filter((t) => t.id !== id), item]);
    return id;
  }, []);

  const api = useMemo<ToastApi>(
    () => ({
      toast,
      success: (message, options) => toast(message, { ...options, kind: 'success' }),
      error: (message, options) => toast(message, { ...options, kind: 'error' }),
      dismiss,
      dismissAll,
    }),
    [toast, dismiss, dismissAll],
  );

  return (
    <ToastContext.Provider value={api}>
      {children}
      <ToastViewport items={items} onDismiss={dismiss} />
    </ToastContext.Provider>
  );
}

export function ToastViewport({ items, onDismiss }: { items: ToastItem[]; onDismiss: (id: string) => void }) {
  const visible = items.slice(0, MAX_VISIBLE_TOASTS);
  return (
    <div className="toast-viewport" aria-live="polite" aria-relevant="additions">
      {visible.map((item) => (
        <ToastCard key={item.id} item={item} onDismiss={onDismiss} />
      ))}
    </div>
  );
}

function ToastCard({ item, onDismiss }: { item: ToastItem; onDismiss: (id: string) => void }) {
  const [secondsLeft, setSecondsLeft] = useState(() => Math.ceil(item.durationMs / 1000));
  const [acting, setActing] = useState(false);

  // The timer starts when the card becomes visible (queued toasts wait their turn).
  useEffect(() => {
    if (item.durationMs <= 0) return;
    const started = Date.now();
    const timer = setTimeout(() => onDismiss(item.id), item.durationMs);
    let ticker: ReturnType<typeof setInterval> | undefined;
    if (item.action) {
      ticker = setInterval(() => {
        setSecondsLeft(Math.max(0, Math.ceil((item.durationMs - (Date.now() - started)) / 1000)));
      }, 250);
    }
    return () => {
      clearTimeout(timer);
      if (ticker) clearInterval(ticker);
    };
  }, [item, onDismiss]);

  const runAction = async () => {
    if (!item.action || acting) return;
    setActing(true);
    try {
      await item.action.onClick();
    } finally {
      onDismiss(item.id);
    }
  };

  return (
    <div className={cx('toast', `toast--${item.kind}`)} role="status">
      <span className="toast__msg">{item.message}</span>
      {item.action && (
        <button type="button" className="toast__action" onClick={() => void runAction()} disabled={acting}>
          {item.action.label}
          {item.durationMs > 0 && (
            <span className="toast__count" aria-hidden="true">
              {secondsLeft}
            </span>
          )}
        </button>
      )}
      <button type="button" className="toast__close" aria-label={zh.common.close} onClick={() => onDismiss(item.id)}>
        <CloseIcon />
      </button>
      {item.action && item.durationMs > 0 && <span className="toast__bar" aria-hidden="true" style={{ animationDuration: `${item.durationMs}ms` }} />}
    </div>
  );
}
