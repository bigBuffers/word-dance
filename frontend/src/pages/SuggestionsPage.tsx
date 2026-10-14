// SuggestionsPage — `/bank/suggestions` (FRONTEND §5.7): open suggestions with accept / keep and the
// "auto-applied" section with undo (7-day window). Every decision calls refreshCounters() so the tab-bar
// badge stays current (FRONTEND §3).
import { useState } from 'react';
import { errorMessage, isApiError } from '@/api/client';
import * as endpoints from '@/api/endpoints';
import type { Suggestion } from '@/api/types';
import { useAuth } from '@/auth/AuthContext';
import { canUndo, SuggestionRow } from '@/components/bank/SuggestionRow';
import { Button } from '@/components/ui/Button';
import { EmptyState } from '@/components/ui/EmptyState';
import { Skeleton } from '@/components/ui/Skeleton';
import { useApi } from '@/hooks/useApi';
import { usePageTitle } from '@/hooks/usePageTitle';
import { useToast } from '@/hooks/useToast';
import { zh } from '@/i18n/zh';
import './SuggestionsPage.css';

export default function SuggestionsPage() {
  usePageTitle(zh.suggestions.title);
  const toast = useToast();
  const { refreshCounters } = useAuth();
  const inbox = useApi((signal) => endpoints.getSuggestions('all', signal), []);
  const [busyId, setBusyId] = useState<number | null>(null);
  const [consolidating, setConsolidating] = useState(false);

  const items = inbox.data?.items ?? [];
  const open = items.filter((s) => s.status === 'open');
  const auto = items.filter((s) => canUndo(s));

  const setStatus = (id: number, status: Suggestion['status']) =>
    inbox.setData((prev) =>
      prev
        ? {
            ...prev,
            items: prev.items.map((s) => (s.id === id ? { ...s, status } : s)),
            open_count: prev.items.filter((s) => s.id !== id && s.status === 'open').length + (status === 'open' ? 1 : 0),
          }
        : prev,
    );

  const run = async (s: Suggestion, fn: () => Promise<string | null>, nextStatus: Suggestion['status']) => {
    setBusyId(s.id);
    try {
      const message = await fn();
      if (message) toast.success(message);
      setStatus(s.id, nextStatus);
      void refreshCounters();
    } catch (e) {
      toast.error(errorMessage(e));
      if (isApiError(e) && (e.code === 'already_resolved' || e.code === 'undo_expired')) void inbox.reload();
    } finally {
      setBusyId(null);
    }
  };

  const accept = (s: Suggestion) =>
    run(
      s,
      async () => {
        const res = await endpoints.acceptSuggestion(s.id);
        return res.result.message_zh || zh.common.saved;
      },
      'accepted',
    );
  const reject = (s: Suggestion) =>
    run(
      s,
      async () => {
        await endpoints.rejectSuggestion(s.id);
        return zh.common.saved;
      },
      'rejected',
    );
  const undo = (s: Suggestion) =>
    run(
      s,
      async () => {
        await endpoints.undoSuggestion(s.id);
        return zh.suggestions.undone;
      },
      'undone',
    );

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

  const empty = !inbox.loading && !inbox.error && open.length === 0 && auto.length === 0;

  return (
    <section className="page page--narrow sugg-page">
      <div className="sugg-page__head">
        <h1 className="page__title">{zh.suggestions.title}</h1>
        <Button size="sm" loading={consolidating} onClick={() => void consolidate()}>
          {zh.bank.consolidateNow}
        </Button>
      </div>

      {inbox.error && (
        <div className="sugg-page__error" role="alert">
          <span>{errorMessage(inbox.error)}</span>
          <Button size="sm" onClick={() => void inbox.reload()}>
            {zh.common.retry}
          </Button>
        </div>
      )}

      {inbox.loading && !inbox.data ? (
        <div aria-busy="true">
          <Skeleton lines={3} />
        </div>
      ) : empty ? (
        <EmptyState title={zh.suggestions.empty} action={{ label: zh.bank.consolidateNow, onClick: () => void consolidate() }} />
      ) : (
        <>
          {open.length > 0 && (
            <ul className="sugg-list" aria-label={zh.suggestions.title}>
              {open.map((s) => (
                <SuggestionRow key={s.id} s={s} busy={busyId === s.id} onAccept={accept} onReject={reject} />
              ))}
            </ul>
          )}
          {auto.length > 0 && (
            <section className="sugg-page__section" aria-labelledby="sugg-auto">
              <h2 id="sugg-auto">{zh.suggestions.autoSection}</h2>
              <ul className="sugg-list">
                {auto.map((s) => (
                  <SuggestionRow key={s.id} s={s} busy={busyId === s.id} onUndo={undo} />
                ))}
              </ul>
            </section>
          )}
        </>
      )}
    </section>
  );
}
