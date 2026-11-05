// BankPage — `/bank` (FRONTEND §5.7): tabs new / learning / mastered / known / removed / attention with counts, search,
// sort, rows with StateBadge · added N times · AttentionBadge, overflow actions mastered / remove / reset / note / view,
// FAB add words, suggestions entry (badge from counters) and consolidate now. attention resolutions (edit / retry / keep / delete /
// replace with) remove the row from the tab and call refreshCounters().
import { useCallback, useState } from 'react';
import { Link, useNavigate } from 'react-router';
import { errorMessage, isApiError } from '@/api/client';
import * as endpoints from '@/api/endpoints';
import type { BankQuery, BankSort, BankStateFilter } from '@/api/endpoints';
import type { BankItem, BankResponse, MarkAction, UserWord, WordBrief, WordDetail } from '@/api/types';
import { useAuth } from '@/auth/AuthContext';
import { AttentionBadge, briefOf } from '@/components/bank/AttentionBadge';
import { Pager, usePagedList } from '@/components/list/Pager';
import { SearchBox } from '@/components/list/SearchBox';
import { WordRow } from '@/components/list/WordRow';
import { Button } from '@/components/ui/Button';
import { ConfirmDialog } from '@/components/ui/ConfirmDialog';
import { EmptyState } from '@/components/ui/EmptyState';
import { PlusIcon } from '@/components/ui/icons';
import { Sheet } from '@/components/ui/Sheet';
import { Skeleton } from '@/components/ui/Skeleton';
import { Tabs } from '@/components/ui/Tabs';
import { useLocalPref } from '@/hooks/useLocalPref';
import { usePageTitle } from '@/hooks/usePageTitle';
import { UNDO_MASTER_MS, useToast } from '@/hooks/useToast';
import { zh } from '@/i18n/zh';
import { routePaths } from '@/routes';
import { formatBadge } from '@/utils/format';
import './BankPage.css';

const PAGE_SIZE = 50;
type BankTab = Exclude<BankStateFilter, 'active'>;
const TABS: readonly BankTab[] = ['new', 'learning', 'mastered', 'known', 'removed', 'attention'];
const SORTS: readonly BankSort[] = ['added', 'due', 'alpha', 'ease', 'times_added'];

function isTab(value: unknown): value is BankTab {
  return typeof value === 'string' && (TABS as readonly string[]).includes(value);
}

/** Whether a row still belongs to the tab after its state/flags changed (exported for tests). */
export function rowBelongsToTab(tab: BankTab, mine: Pick<UserWord, 'state' | 'needs_attention'>): boolean {
  if (tab === 'attention') return mine.needs_attention;
  return mine.state === tab;
}

interface RowMenuProps {
  item: BankItem;
  onAction: (action: MarkAction) => void;
  onNote: () => void;
  busy: boolean;
}

function RowMenu({ item, onAction, onNote, busy }: RowMenuProps) {
  const [open, setOpen] = useState(false);
  const state = item.mine.state;
  const run = (action: MarkAction) => {
    setOpen(false);
    onAction(action);
  };
  return (
    <>
      <Button size="sm" variant="ghost" disabled={busy} aria-haspopup="dialog" aria-expanded={open} aria-label={`${zh.common.more} · ${item.display}`} onClick={() => setOpen(true)}>
        {zh.common.more}
      </Button>
      <Sheet open={open} onClose={() => setOpen(false)} title={item.display}>
        <div className="bank__menu">
          <Link className="btn btn--secondary btn--md btn--block" to={routePaths.word(item.id)} onClick={() => setOpen(false)}>
            <span className="btn__label">{zh.word.title}</span>
          </Link>
          <Button
            block
            onClick={() => {
              setOpen(false);
              onNote();
            }}
          >
            {zh.bank.note}
          </Button>
          {(state === 'new' || state === 'learning') && (
            <Button block variant="primary" tone="good" onClick={() => run('mastered')}>
              {zh.study.master}
            </Button>
          )}
          {state === 'learning' && (
            <Button block onClick={() => run('reset')}>
              {zh.word.reset}
            </Button>
          )}
          {state !== 'removed' && (
            <Button block variant="ghost" tone="again" onClick={() => run('remove')}>
              {zh.word.remove}
            </Button>
          )}
          {(state === 'mastered' || state === 'known' || state === 'removed') && (
            <Button block variant="primary" tone="again" onClick={() => run('unfamiliar')}>
              {zh.vocab.markUnfamiliar}
            </Button>
          )}
        </div>
      </Sheet>
    </>
  );
}

export default function BankPage() {
  usePageTitle(zh.bank.title);
  const toast = useToast();
  const navigate = useNavigate();
  const { counters, refreshCounters, settings } = useAuth();
  const [tabPref, setTabPref] = useLocalPref<string>('wd.bankTab', 'new');
  const tab: BankTab = isTab(tabPref) ? tabPref : 'new';
  const [q, setQ] = useState('');
  const [sort, setSort] = useState<BankSort>('added');
  const [busyIds, setBusyIds] = useState<ReadonlySet<number>>(new Set());
  const [confirm, setConfirm] = useState<{ item: BankItem; action: 'mastered' | 'reset' } | null>(null);
  const [noteFor, setNoteFor] = useState<BankItem | null>(null);
  const [noteDraft, setNoteDraft] = useState('');
  const [noteBusy, setNoteBusy] = useState(false);
  const [consolidating, setConsolidating] = useState(false);

  const list = usePagedList<BankItem, BankResponse>(
    (page, signal) => {
      const query: BankQuery = { state: tab, sort, page, page_size: PAGE_SIZE };
      if (q) query.q = q;
      return endpoints.getBank(query, signal);
    },
    [tab, sort, q],
  );
  const counts = list.data?.counts ?? null;

  const onTab = (next: BankTab) => {
    setTabPref(next);
    list.reset();
  };
  const onSearch = (value: string) => {
    setQ(value.trim());
    list.reset();
  };
  const onSort = (value: BankSort) => {
    setSort(value);
    list.reset();
  };

  const setBusy = (id: number, on: boolean) =>
    setBusyIds((prev) => {
      const next = new Set(prev);
      if (on) next.add(id);
      else next.delete(id);
      return next;
    });

  const removeRow = useCallback((id: number) => list.setItems((prev) => prev.filter((w) => w.id !== id)), [list]);

  /** Applies a fresh `mine` (and optionally word fields); rows that left the current tab disappear. */
  const patchMine = useCallback(
    (id: number, mine: UserWord | null, word?: Partial<WordBrief>) => {
      if (!mine) {
        removeRow(id);
        return;
      }
      list.setItems((prev) => prev.map((w) => (w.id === id ? { ...w, ...word, mine, my_state: mine.state } : w)).filter((w) => w.id !== id || rowBelongsToTab(tab, w.mine)));
    },
    [list, removeRow, tab],
  );

  const restore = useCallback(
    async (id: number) => {
      try {
        await endpoints.markWord(id, { action: 'restore', context: 'bank' });
        toast.toast(zh.study.restored);
        void list.reload();
      } catch (e) {
        toast.error(errorMessage(e));
      }
    },
    [list, toast],
  );

  const runAction = useCallback(
    async (item: BankItem, action: MarkAction) => {
      setBusy(item.id, true);
      try {
        const res = await endpoints.markWord(item.id, { action, context: 'bank' });
        if (action === 'mastered') {
          toast.toast(zh.study.mastered, {
            durationMs: UNDO_MASTER_MS,
            ...(res.status !== 'noop' && res.status !== 'exists' ? { action: { label: zh.common.undo, onClick: () => restore(item.id) } } : {}),
          });
        } else if (action === 'unfamiliar') {
          toast.toast(res.status === 'readded' ? zh.bank.status.readded : zh.vocab.addedToBank);
        } else if (action === 'remove') {
          toast.toast(zh.bank.tabs.removed);
        } else {
          toast.toast(zh.common.saved);
        }
        patchMine(item.id, res.mine);
        void refreshCounters();
      } catch (e) {
        toast.error(errorMessage(e));
      } finally {
        setBusy(item.id, false);
      }
    },
    [patchMine, refreshCounters, restore, toast],
  );

  const onRowAction = (item: BankItem, action: MarkAction) => {
    if ((action === 'mastered' && !item.mine.srs.mastery_suggested) || action === 'reset') {
      setConfirm({ item, action });
      return;
    }
    void runAction(item, action);
  };

  // ---- attention resolutions (API.md 36 / DESIGN §5.4) ----
  const withBusy = async (item: BankItem, fn: () => Promise<void>) => {
    setBusy(item.id, true);
    try {
      await fn();
    } catch (e) {
      toast.error(errorMessage(e));
      if (isApiError(e) && e.code === 'invalid_transition') void list.reload();
    } finally {
      setBusy(item.id, false);
    }
  };

  const onKeep = (item: BankItem) =>
    withBusy(item, async () => {
      const mine = await endpoints.patchBankEntry(item.id, { attention: 'keep' });
      toast.success(item.is_valid_english === false ? zh.bank.keptOnly : zh.common.saved);
      patchMine(item.id, mine);
      void refreshCounters();
    });
  const onRetry = (item: BankItem) =>
    withBusy(item, async () => {
      const mine = await endpoints.patchBankEntry(item.id, { attention: 'retry' });
      toast.toast(zh.bank.retrying);
      patchMine(item.id, mine);
      void refreshCounters();
    });
  const onEdit = (item: BankItem) =>
    withBusy(item, async () => {
      await endpoints.markWord(item.id, { action: 'remove', context: 'bank' });
      void refreshCounters();
      navigate(routePaths.bankAddPrefill(item.mine.input_text ?? item.display));
    });
  const onRemove = (item: BankItem) =>
    withBusy(item, async () => {
      const res = await endpoints.markWord(item.id, { action: 'remove', context: 'bank' });
      toast.toast(zh.bank.tabs.removed);
      patchMine(item.id, res.mine);
      void refreshCounters();
    });
  const onReplace = (item: BankItem) =>
    withBusy(item, async () => {
      await endpoints.acceptBankSuggestion(item.id);
      toast.success(zh.common.saved);
      removeRow(item.id);
      void list.reload();
      void refreshCounters();
    });
  const onUpdate = (item: BankItem, detail: WordDetail) => {
    patchMine(item.id, detail.mine, briefOf(detail.word));
    void refreshCounters();
  };

  const saveNote = async () => {
    if (!noteFor) return;
    setNoteBusy(true);
    try {
      const mine = await endpoints.patchBankEntry(noteFor.id, { note: noteDraft.trim() || null });
      patchMine(noteFor.id, mine);
      toast.success(zh.common.saved);
      setNoteFor(null);
    } catch (e) {
      toast.error(errorMessage(e));
    } finally {
      setNoteBusy(false);
    }
  };

  const consolidate = async () => {
    setConsolidating(true);
    try {
      await endpoints.consolidateBank();
      toast.success(zh.bank.consolidateQueued);
    } catch (e) {
      toast.error(errorMessage(e));
    } finally {
      setConsolidating(false);
    }
  };

  const suggestionsOpen = counters?.suggestions_open ?? 0;
  const total = list.total;
  const emptyBank = !list.loading && !list.error && list.data !== null && total === 0 && !q && (tab === 'new' || tab === 'learning');

  return (
    <section className="page bank">
      <div className="bank__head">
        <h1 className="page__title">{zh.bank.title}</h1>
        <div className="bank__head-actions">
          <Link className="btn btn--secondary btn--sm" to={routePaths.bankSuggestions}>
            <span className="btn__label">
              {zh.suggestions.title}
              {suggestionsOpen > 0 && <span className="bank__badge">{formatBadge(suggestionsOpen)}</span>}
            </span>
          </Link>
          <Button size="sm" loading={consolidating} onClick={() => void consolidate()}>
            {zh.bank.consolidateNow}
          </Button>
        </div>
      </div>

      <Tabs aria-label={zh.bank.title} items={TABS.map((t) => ({ key: t, label: zh.bank.tabs[t], badge: counts ? counts[t] : null }))} value={tab} onChange={onTab} />

      <div className="bank__controls">
        <SearchBox value={q} onChange={onSearch} placeholder={zh.vocab.searchPlaceholder} />
        <div className="bank__filters">
          <select aria-label={zh.common.sort} value={sort} onChange={(e) => onSort(e.target.value as BankSort)}>
            {SORTS.map((s) => (
              <option key={s} value={s}>
                {zh.bank.sort[s]}
              </option>
            ))}
          </select>
          <span className="bank__count" aria-live="polite">
            {list.data ? zh.bank.counts(total) : null}
          </span>
        </div>
      </div>

      {list.error && (
        <div className="bank__error" role="alert">
          <span>{errorMessage(list.error)}</span>
          <Button size="sm" onClick={() => void list.reload()}>
            {zh.common.retry}
          </Button>
        </div>
      )}

      {list.loading && list.items.length === 0 ? (
        <div className="bank__skeleton" aria-busy="true">
          {Array.from({ length: 6 }, (_, i) => (
            <Skeleton key={i} lines={2} />
          ))}
        </div>
      ) : emptyBank ? (
        <EmptyState title={zh.bank.empty} action={{ label: zh.bank.add, to: routePaths.bankAdd }} />
      ) : (
        <ul className="word-list" aria-busy={list.loading || undefined}>
          {list.items.map((item) => (
            <WordRow
              key={item.id}
              word={item}
              mine={item.mine}
              busy={busyIds.has(item.id)}
              onlyStages={settings?.stages}
              meta={item.mine.times_added > 1 ? <span className="chip">{zh.study.addedTimes(item.mine.times_added)}</span> : null}
              actions={
                <RowMenu
                  item={item}
                  busy={busyIds.has(item.id)}
                  onAction={(a) => onRowAction(item, a)}
                  onNote={() => {
                    setNoteFor(item);
                    setNoteDraft(item.mine.note ?? '');
                  }}
                />
              }
              footer={
                <AttentionBadge
                  mine={item.mine}
                  word={item}
                  busy={busyIds.has(item.id)}
                  onKeep={() => onKeep(item)}
                  onRetry={() => onRetry(item)}
                  onEdit={() => onEdit(item)}
                  onRemove={() => onRemove(item)}
                  onReplace={() => onReplace(item)}
                  onUpdate={(detail) => onUpdate(item, detail)}
                />
              }
            />
          ))}
        </ul>
      )}
      <Pager page={list.page} pageSize={PAGE_SIZE} total={total} loading={list.loading} onChange={list.goTo} />

      <Link className="btn btn--primary btn--lg bank__fab" to={routePaths.bankAdd}>
        <span className="btn__icon" aria-hidden="true">
          <PlusIcon />
        </span>
        <span className="btn__label">{zh.bank.add}</span>
      </Link>

      <ConfirmDialog
        open={confirm !== null}
        title={confirm?.action === 'reset' ? `${zh.word.reset} · ${confirm.item.display}` : zh.study.master}
        message={confirm?.action === 'reset' ? zh.word.resetConfirm : zh.study.masterConfirm}
        danger={confirm?.action === 'reset'}
        onCancel={() => setConfirm(null)}
        onConfirm={() => {
          if (confirm) void runAction(confirm.item, confirm.action);
          setConfirm(null);
        }}
      />

      <Sheet open={noteFor !== null} onClose={() => setNoteFor(null)} title={noteFor?.display}>
        <form
          className="bank__note-form"
          onSubmit={(e) => {
            e.preventDefault();
            void saveNote();
          }}
        >
          <textarea aria-label={zh.bank.note} placeholder={zh.bank.note} value={noteDraft} maxLength={500} rows={4} onChange={(e) => setNoteDraft(e.target.value)} />
          <Button type="submit" variant="primary" block loading={noteBusy}>
            {zh.common.save}
          </Button>
        </form>
      </Sheet>
    </section>
  );
}
