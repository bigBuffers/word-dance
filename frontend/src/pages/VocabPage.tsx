// VocabPage — `/vocab` (FRONTEND §5.5): tabs all / zk / gk / cet4 / cet6, new-only toggle for a specific
// stage, search (prefix / forms / Chinese substring, debounced), status filter, sort, A–Z index, list with
// inline unfamiliar / known (POST /api/words/{id}/mark {context:'browse'} patched in place + 5-s undo toast calling
// `mark restore`), desktop bulk mode (POST /api/words/batch-mark), aria-live "total N words", pager.
import { useCallback, useMemo, useState } from 'react';
import { errorMessage } from '@/api/client';
import * as endpoints from '@/api/endpoints';
import type { BatchMarkAction, VocabQuery, VocabSort, VocabStageFilter, VocabStatusFilter } from '@/api/endpoints';
import type { MarkAction, Page, UserState, WordBrief } from '@/api/types';
import { LetterIndex } from '@/components/list/LetterIndex';
import { Pager, usePagedList } from '@/components/list/Pager';
import { SearchBox } from '@/components/list/SearchBox';
import { WordRow } from '@/components/list/WordRow';
import { Button } from '@/components/ui/Button';
import { EmptyState } from '@/components/ui/EmptyState';
import { Skeleton } from '@/components/ui/Skeleton';
import { Switch } from '@/components/ui/Switch';
import { Tabs } from '@/components/ui/Tabs';
import { isStage } from '@/components/word/StageChips';
import { useApi } from '@/hooks/useApi';
import { useLocalPref } from '@/hooks/useLocalPref';
import { usePageTitle } from '@/hooks/usePageTitle';
import { UNDO_LIST_MS, UNDO_MASTER_MS, useToast } from '@/hooks/useToast';
import { zh } from '@/i18n/zh';
import { routePaths } from '@/routes';
import './VocabPage.css';

const PAGE_SIZE = 50;
const TABS: readonly VocabStageFilter[] = ['all', 'zk', 'gk', 'cet4', 'cet6'];
const STATUSES: readonly VocabStatusFilter[] = ['all', 'unmarked', 'unfamiliar', 'known', 'mastered'];
const SORTS: readonly VocabSort[] = ['freq', 'alpha', 'difficulty'];

/** Optimistic state after a quick action (the server response replaces it). */
export function optimisticState(action: MarkAction, prev: UserState | null): UserState | null {
  switch (action) {
    case 'unfamiliar':
      return 'new';
    case 'known':
      return prev === 'new' || prev === 'learning' ? 'mastered' : 'known';
    case 'mastered':
      return prev === null ? 'known' : 'mastered';
    case 'remove':
      return 'removed';
    case 'reset':
      return 'new';
    default:
      return prev;
  }
}

/** Toast copy for a completed quick action (exported for tests). */
export function markToast(action: MarkAction, status: string): string {
  if (action === 'unfamiliar') return status === 'readded' ? zh.bank.status.readded : status === 'exists' ? zh.vocab.inBank : zh.vocab.addedToBank;
  if (action === 'known') return zh.vocab.status.known;
  if (action === 'mastered') return zh.study.mastered;
  if (action === 'remove') return zh.bank.tabs.removed;
  return zh.common.saved;
}

/** The 5-s undo is offered only when the server `restore` can succeed (API.md 26). */
export function markUndoable(action: MarkAction, status: string): boolean {
  if (action === 'remove' || action === 'reset' || action === 'restore') return false;
  return status !== 'exists' && status !== 'noop' && status !== 'readded';
}

export default function VocabPage() {
  usePageTitle(zh.vocab.title);
  const toast = useToast();
  const [tabPref, setTabPref] = useLocalPref<string>('wd.vocabTab', 'all');
  const tab: VocabStageFilter = tabPref === 'all' || isStage(tabPref) ? tabPref : 'all';
  const [newOnly, setNewOnly] = useState(false);
  const [q, setQ] = useState('');
  const [status, setStatus] = useState<VocabStatusFilter>('all');
  const [sort, setSort] = useState<VocabSort>('freq');
  const [letter, setLetter] = useState<string | null>(null);
  const [bulk, setBulk] = useState(false);
  const [selected, setSelected] = useState<ReadonlySet<number>>(new Set());
  const [busyIds, setBusyIds] = useState<ReadonlySet<number>>(new Set());
  const [bulkBusy, setBulkBusy] = useState(false);

  const effectiveNewOnly = tab !== 'all' && newOnly;
  const baseQuery = useMemo<VocabQuery>(
    () => ({
      stage: tab,
      ...(effectiveNewOnly ? { new_only: true } : {}),
      ...(status !== 'all' ? { status } : {}),
      sort,
    }),
    [tab, effectiveNewOnly, status, sort],
  );

  const list = usePagedList<WordBrief, Page<WordBrief>>(
    (page, signal) => endpoints.getVocab({ ...baseQuery, ...(q ? { q } : {}), ...(letter ? { letter } : {}), page, page_size: PAGE_SIZE }, signal),
    [baseQuery, q, letter],
  );
  const letters = useApi((signal) => endpoints.getVocabLetters(baseQuery, signal), [baseQuery]);

  const resetList = useCallback(() => {
    list.reset();
    setSelected(new Set());
  }, [list]);

  const onTab = (next: VocabStageFilter) => {
    setTabPref(next);
    setLetter(null);
    resetList();
  };
  const onSearch = (value: string) => {
    setQ(value.trim());
    setLetter(null);
    resetList();
  };
  const onLetter = (value: string | null) => {
    setLetter(value);
    resetList();
  };
  const onStatus = (value: VocabStatusFilter) => {
    setStatus(value);
    resetList();
  };
  const onSort = (value: VocabSort) => {
    setSort(value);
    resetList();
  };
  const onNewOnly = (value: boolean) => {
    setNewOnly(value);
    resetList();
  };

  const patch = useCallback(
    (id: number, state: UserState | null) => {
      list.setItems((prev) => prev.map((w) => (w.id === id ? { ...w, my_state: state } : w)));
    },
    [list],
  );
  const setBusy = (id: number, on: boolean) =>
    setBusyIds((prev) => {
      const next = new Set(prev);
      if (on) next.add(id);
      else next.delete(id);
      return next;
    });

  const undo = useCallback(
    async (id: number) => {
      try {
        const res = await endpoints.markWord(id, { action: 'restore', context: 'browse' });
        patch(id, res.state);
        toast.toast(zh.common.undone);
      } catch (e) {
        toast.error(errorMessage(e));
      }
    },
    [patch, toast],
  );

  const mark = async (word: WordBrief, action: MarkAction) => {
    const prev = word.my_state;
    setBusy(word.id, true);
    patch(word.id, optimisticState(action, prev));
    try {
      const res = await endpoints.markWord(word.id, { action, context: 'browse' });
      patch(word.id, res.state);
      toast.toast(markToast(action, res.status), {
        durationMs: action === 'mastered' ? UNDO_MASTER_MS : UNDO_LIST_MS,
        ...(markUndoable(action, res.status) ? { action: { label: zh.common.undo, onClick: () => undo(word.id) } } : {}),
      });
    } catch (e) {
      patch(word.id, prev);
      toast.error(errorMessage(e));
    } finally {
      setBusy(word.id, false);
    }
  };

  const toggleSelected = (id: number, on: boolean) =>
    setSelected((prev) => {
      const next = new Set(prev);
      if (on) next.add(id);
      else next.delete(id);
      return next;
    });

  const bulkMark = async (action: BatchMarkAction) => {
    const ids = [...selected];
    if (ids.length === 0 || bulkBusy) return;
    setBulkBusy(true);
    try {
      const res = await endpoints.batchMark({ items: ids.map((word_id) => ({ word_id, action })) });
      for (const r of res.results) if (r.ok) patch(r.word_id, r.state);
      setSelected(new Set());
      toast.success(action === 'unfamiliar' ? zh.vocab.addedToBank : zh.vocab.status.known);
    } catch (e) {
      toast.error(errorMessage(e));
    } finally {
      setBulkBusy(false);
    }
  };

  const total = list.total;
  const showEmptySearch = !list.loading && !list.error && q.length > 0 && total === 0;
  const newOnlyLabel = tab === 'cet6' ? zh.stages.newOnlyCet6 : zh.stages.newOnly;

  return (
    <section className="page vocab">
      <div className="vocab__head">
        <h1 className="page__title">{zh.vocab.title}</h1>
        <span className="vocab__count" aria-live="polite">
          {list.data ? zh.common.total(total) : null}
        </span>
      </div>

      <Tabs aria-label={zh.vocab.title} fill items={TABS.map((t) => ({ key: t, label: t === 'all' ? zh.common.all : zh.stages[t] }))} value={tab} onChange={onTab} />

      <div className="vocab__controls">
        <SearchBox value={q} onChange={onSearch} placeholder={zh.vocab.searchPlaceholder} />
        <div className="vocab__filters">
          <select aria-label={zh.vocab.status.all} value={status} onChange={(e) => onStatus(e.target.value as VocabStatusFilter)}>
            {STATUSES.map((s) => (
              <option key={s} value={s}>
                {zh.vocab.status[s]}
              </option>
            ))}
          </select>
          <select aria-label={zh.vocab.sort.freq} value={sort} onChange={(e) => onSort(e.target.value as VocabSort)}>
            {SORTS.map((s) => (
              <option key={s} value={s}>
                {zh.vocab.sort[s]}
              </option>
            ))}
          </select>
          {tab !== 'all' && <Switch checked={newOnly} onChange={onNewOnly} label={newOnlyLabel} />}
          <div className="vocab__bulk">
            {bulk && selected.size > 0 && <span className="vocab__bulk-count">{zh.vocab.selected(selected.size)}</span>}
            {bulk && (
              <>
                <Button size="sm" tone="again" loading={bulkBusy} disabled={selected.size === 0} onClick={() => void bulkMark('unfamiliar')}>
                  {zh.vocab.bulkUnfamiliar}
                </Button>
                <Button size="sm" tone="good" loading={bulkBusy} disabled={selected.size === 0} onClick={() => void bulkMark('known')}>
                  {zh.vocab.bulkKnown}
                </Button>
              </>
            )}
            <Button
              size="sm"
              variant={bulk ? 'primary' : 'secondary'}
              aria-pressed={bulk}
              onClick={() => {
                setBulk((b) => !b);
                setSelected(new Set());
              }}
            >
              {bulk ? zh.common.cancel : zh.vocab.bulk}
            </Button>
          </div>
        </div>
        <LetterIndex className="vocab__letters--inline" letters={letters.data?.items ?? []} active={letter} onPick={onLetter} />
      </div>

      <div className="vocab__body">
        <div className="vocab__main">
          {list.error && (
            <div className="vocab__error" role="alert">
              <span>{errorMessage(list.error)}</span>
              <Button size="sm" onClick={() => void list.reload()}>
                {zh.common.retry}
              </Button>
            </div>
          )}
          {list.loading && list.items.length === 0 ? (
            <div className="vocab__skeleton" aria-busy="true">
              {Array.from({ length: 8 }, (_, i) => (
                <Skeleton key={i} lines={2} />
              ))}
            </div>
          ) : showEmptySearch ? (
            <EmptyState title={zh.vocab.notFound(q)} action={{ label: zh.bank.add, to: routePaths.bankAddPrefill(q) }} />
          ) : (
            <ul className="word-list" aria-busy={list.loading || undefined}>
              {list.items.map((word) => (
                <WordRow
                  key={word.id}
                  word={word}
                  onMark={(action) => mark(word, action)}
                  selectable={bulk}
                  selected={selected.has(word.id)}
                  onSelect={(on) => toggleSelected(word.id, on)}
                  busy={busyIds.has(word.id)}
                />
              ))}
            </ul>
          )}
          <Pager page={list.page} pageSize={PAGE_SIZE} total={total} loading={list.loading} onChange={list.goTo} />
        </div>
        <LetterIndex className="vocab__letters--rail" rail letters={letters.data?.items ?? []} active={letter} onPick={onLetter} />
      </div>
    </section>
  );
}
