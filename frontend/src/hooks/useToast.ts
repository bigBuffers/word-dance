// useToast — global toast queue (FRONTEND.md §3): bottom-centre, ≤ 3 visible, undo toasts carry an
// action and a countdown (8 s for mastered, 5 s for list toggles). The provider and viewport live in
// `components/ui/Toast.tsx`; this module holds the context so hooks stay free of JSX.
import { createContext, useContext } from 'react';

export type ToastKind = 'info' | 'success' | 'error';

export interface ToastAction {
  label: string;
  onClick: () => void | Promise<void>;
}

export interface ToastOptions {
  kind?: ToastKind;
  /** Auto-dismiss delay; `0` keeps the toast until dismissed. Default 3000 ms (5000 for errors). */
  durationMs?: number;
  /** Optional action button (e.g. undo); the viewport shows a countdown while it is available. */
  action?: ToastAction;
  /** Stable id to replace an existing toast instead of stacking a new one. */
  id?: string;
}

export interface ToastItem {
  id: string;
  message: string;
  kind: ToastKind;
  durationMs: number;
  createdAt: number;
  action?: ToastAction;
}

export interface ToastApi {
  /** Shows a toast and returns its id. */
  toast(message: string, options?: ToastOptions): string;
  success(message: string, options?: Omit<ToastOptions, 'kind'>): string;
  error(message: string, options?: Omit<ToastOptions, 'kind'>): string;
  dismiss(id: string): void;
  dismissAll(): void;
}

export const DEFAULT_TOAST_MS = 3000;
export const ERROR_TOAST_MS = 5000;
/** Undo window for list toggles and screening verdicts (FRONTEND §5.4/§5.5). */
export const UNDO_LIST_MS = 5000;
/** Undo window for the mastered action on a study card (FRONTEND §5.1.3). */
export const UNDO_MASTER_MS = 8000;
export const MAX_VISIBLE_TOASTS = 3;

const warnOnce = (() => {
  let warned = false;
  return () => {
    if (warned || !import.meta.env.DEV) return;
    warned = true;
    console.warn('useToast() used outside <ToastProvider>; toasts are dropped.');
  };
})();

/** No-op implementation used outside a provider (keeps tests and isolated renders working). */
export const noopToastApi: ToastApi = {
  toast: () => {
    warnOnce();
    return '';
  },
  success: () => {
    warnOnce();
    return '';
  },
  error: () => {
    warnOnce();
    return '';
  },
  dismiss: () => undefined,
  dismissAll: () => undefined,
};

export const ToastContext = createContext<ToastApi>(noopToastApi);

export function useToast(): ToastApi {
  return useContext(ToastContext);
}
