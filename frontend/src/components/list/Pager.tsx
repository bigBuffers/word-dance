// Pager — numeric pager on desktop, load more on phones (FRONTEND §4). `onChange(page, mode)`: the
// desktop pager replaces the list (`'replace'`), the phone button appends the next page (`'append'`).
// Both variants are rendered; CSS shows one per breakpoint.
import { useCallback, useEffect, useRef, useState, type DependencyList, type Dispatch, type SetStateAction } from 'react';
import type { ApiError } from '@/api/client';
import type { Page } from '@/api/types';
import { cx } from '@/components/ui/cx';
import { Button } from '@/components/ui/Button';
import { ChevronIcon } from '@/components/ui/icons';
import { useApi } from '@/hooks/useApi';
import { zh } from '@/i18n/zh';
import './list.css';

export type PagerMode = 'replace' | 'append';

export interface PagedList<T, R extends Page<T>> {
  /** Accumulated rows (appended pages on phones, the current page on desktop). */
  items: T[];
  total: number;
  page: number;
  loading: boolean;
  error: ApiError | null;
  /** The latest raw response (e.g. `BankResponse.counts`). */
  data: R | null;
  /** Pager callback: `'replace'` shows that page, `'append'` adds it below the current rows. */
  goTo: (page: number, mode: PagerMode) => void;
  /** Back to page 1 with a fresh list (call when a filter changes). */
  reset: () => void;
  reload: () => Promise<void>;
  /** Patch rows in place (optimistic updates). */
  setItems: Dispatch<SetStateAction<T[]>>;
}

/**
 * Pagination state shared by the vocab / bank / admin lists: fetches `fetcher(page)` through `useApi`
 * and either replaces or appends the rows depending on the Pager mode. Filter changes belong in
 * `deps`; call `reset()` alongside them so the list restarts at page 1.
 */
export function usePagedList<T, R extends Page<T>>(fetcher: (page: number, signal: AbortSignal) => Promise<R>, deps: DependencyList): PagedList<T, R> {
  const [page, setPage] = useState(1);
  const [items, setItems] = useState<T[]>([]);
  const appendRef = useRef(false);
  const { data, error, loading, reload } = useApi((signal) => fetcher(page, signal), [...deps, page]);

  useEffect(() => {
    if (!data) return;
    const append = appendRef.current;
    appendRef.current = false;
    setItems((prev) => (append ? [...prev, ...data.items] : data.items));
  }, [data]);

  const goTo = useCallback((next: number, mode: PagerMode) => {
    appendRef.current = mode === 'append';
    setPage(next);
    if (mode === 'replace' && typeof window !== 'undefined') window.scrollTo({ top: 0 });
  }, []);

  const reset = useCallback(() => {
    appendRef.current = false;
    setPage(1);
  }, []);

  return { items, total: data?.total ?? 0, page, loading, error, data, goTo, reset, reload, setItems };
}

export interface PagerProps {
  page: number;
  pageSize: number;
  total: number;
  onChange: (page: number, mode: PagerMode) => void;
  loading?: boolean;
  className?: string;
}

export type PagerSlot = number | 'gap';

/** Page numbers to render: first, last, current ± 1, with gaps collapsed (`pageWindow(5, 12)` → 1 … 4 5 6 … 12). */
export function pageWindow(page: number, pages: number): PagerSlot[] {
  if (pages <= 7) return Array.from({ length: pages }, (_, i) => i + 1);
  const wanted = new Set<number>([1, pages, page - 1, page, page + 1]);
  if (page <= 3) [2, 3, 4].forEach((p) => wanted.add(p));
  if (page >= pages - 2) [pages - 1, pages - 2, pages - 3].forEach((p) => wanted.add(p));
  const sorted = [...wanted].filter((p) => p >= 1 && p <= pages).sort((a, b) => a - b);
  const out: PagerSlot[] = [];
  let prev = 0;
  for (const p of sorted) {
    if (prev && p - prev > 1) out.push('gap');
    out.push(p);
    prev = p;
  }
  return out;
}

export function pageCount(total: number, pageSize: number): number {
  return Math.max(1, Math.ceil(Math.max(0, total) / Math.max(1, pageSize)));
}

export function Pager({ page, pageSize, total, onChange, loading = false, className }: PagerProps) {
  const pages = pageCount(total, pageSize);
  if (pages <= 1) return null;
  const hasMore = page < pages;

  return (
    <>
      <nav className={cx('pager', 'pager--desktop', className)} aria-label={zh.common.pageOf(page, pages)}>
        <button
          type="button"
          className="pager__page"
          aria-label={`${zh.common.back} ${zh.common.pageOf(page - 1, pages)}`}
          disabled={page <= 1 || loading}
          onClick={() => onChange(page - 1, 'replace')}
        >
          <ChevronIcon style={{ transform: 'rotate(180deg)' }} />
        </button>
        {pageWindow(page, pages).map((slot, i) =>
          slot === 'gap' ? (
            <span key={`gap-${i}`} className="pager__gap" aria-hidden="true">
              …
            </span>
          ) : (
            <button
              key={slot}
              type="button"
              className="pager__page"
              aria-label={zh.common.pageOf(slot, pages)}
              aria-current={slot === page ? 'page' : undefined}
              disabled={loading}
              onClick={() => {
                if (slot !== page) onChange(slot, 'replace');
              }}
            >
              {slot}
            </button>
          ),
        )}
        <button
          type="button"
          className="pager__page"
          aria-label={`${zh.common.more} ${zh.common.pageOf(page + 1, pages)}`}
          disabled={!hasMore || loading}
          onClick={() => onChange(page + 1, 'replace')}
        >
          <ChevronIcon />
        </button>
      </nav>
      <div className={cx('pager', 'pager--phone', className)}>
        <span className="pager__info">{zh.common.pageOf(page, pages)}</span>
        {hasMore && (
          <Button variant="secondary" block loading={loading} onClick={() => onChange(page + 1, 'append')}>
            {zh.common.loadMore}
          </Button>
        )}
      </div>
    </>
  );
}
