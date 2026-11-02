// ScreenRunPage — rapid known / unfamiliar triage of one stage (FRONTEND §5.4, API.md 31/32/26). Verdicts post
// immediately with a `client_event_id`; the 5-s undo toast (key U) is the server undo
// `POST /api/words/{id}/mark {action:'restore', context:'screen_page'}` after which the card returns to
// the front of the deck (409 undo_expired → errors.undoExpired). Batches of 30 with zh.screen.another.
// Title: `screening · cet4`. Button / swipe verdicts go through `useTapLock` so a double tap cannot judge
// the card that advanced under the finger; keyboard verdicts are unlocked (`useKeyboard` drops auto-repeat).
import { useCallback, useEffect, useRef, useState } from 'react';
import { Link, useNavigate, useParams } from 'react-router';
import { errorMessage } from '@/api/client';
import { getScreenNext, markWord, postScreenVerdict } from '@/api/endpoints';
import type { ScreenVerdict, ScreenWord, WordBrief } from '@/api/types';
import { useAuth } from '@/auth/AuthContext';
import { ScreenCard } from '@/components/study/ScreenCard';
import { Button } from '@/components/ui/Button';
import { EmptyState } from '@/components/ui/EmptyState';
import { Skeleton } from '@/components/ui/Skeleton';
import { isStage } from '@/components/word/StageChips';
import { useKeyboard } from '@/hooks/useKeyboard';
import { writePref } from '@/hooks/useLocalPref';
import { usePageTitle } from '@/hooks/usePageTitle';
import { speak } from '@/hooks/useSpeech';
import { useTapLock } from '@/hooks/useTapLock';
import { UNDO_LIST_MS, useToast } from '@/hooks/useToast';
import { zh } from '@/i18n/zh';
import { routePaths } from '@/routes';
import { newClientEventId } from '@/study/queue';
import { SCREEN_STAGE_KEY } from './ScreenPage';
import './ScreenRunPage.css';

export const SCREEN_BATCH_SIZE = 30;

export default function ScreenRunPage() {
  const { stage: stageParam } = useParams();
  const stage = isStage(stageParam) ? stageParam : null;
  const title = stage ? `${zh.screen.title} · ${zh.stages[stage]}` : zh.screen.title;
  usePageTitle(title);
  const navigate = useNavigate();
  const toast = useToast();
  const { settings } = useAuth();

  const [deck, setDeck] = useState<ScreenWord[]>([]);
  const [remaining, setRemaining] = useState<number | null>(null);
  const [exhausted, setExhausted] = useState(false);
  const [fetching, setFetching] = useState(false);
  const [fetchError, setFetchError] = useState<string | null>(null);
  const [screened, setScreened] = useState(0);
  const [peeked, setPeeked] = useState(false);
  const lastUndo = useRef<(() => Promise<void>) | null>(null);
  const tapLock = useTapLock();

  const fetchMore = useCallback(async () => {
    if (!stage) return;
    setFetching(true);
    setFetchError(null);
    try {
      const res = await getScreenNext(stage, SCREEN_BATCH_SIZE);
      setDeck(res.items);
      setRemaining(res.remaining);
      setExhausted(res.items.length === 0);
    } catch (e) {
      setFetchError(errorMessage(e));
    } finally {
      setFetching(false);
    }
  }, [stage]);

  useEffect(() => {
    if (!stage) navigate(routePaths.screen, { replace: true });
  }, [stage, navigate]);

  useEffect(() => {
    if (!stage) return;
    writePref(SCREEN_STAGE_KEY, stage);
    void fetchMore();
  }, [stage, fetchMore]);

  const current = deck[0] ?? null;
  useEffect(() => {
    setPeeked(false);
  }, [current?.word.id]);

  const putBack = useCallback((word: WordBrief, countsAsScreened: boolean) => {
    setDeck((d) => [{ word, phonetic: word.phonetic }, ...d]);
    if (countsAsScreened) {
      setRemaining((r) => (r === null ? r : r + 1));
      setScreened((n) => Math.max(0, n - 1));
    }
  }, []);

  const verdict = useCallback(
    async (word: WordBrief, v: ScreenVerdict) => {
      const stored = v !== 'skip';
      setDeck((d) => (d[0]?.word.id === word.id ? d.slice(1) : d));
      tapLock.arm();
      if (stored) {
        setRemaining((r) => (r === null ? r : Math.max(0, r - 1)));
        setScreened((n) => n + 1);
      }
      try {
        const res = await postScreenVerdict({ client_event_id: newClientEventId(), word_id: word.id, verdict: v, context: 'screen_page' });
        if (!stored || res.duplicate) return;
        const message = v === 'known' ? zh.screen.markedKnown(word.display) : res.added_to_today ? zh.screen.addedToday : res.today ? zh.screen.addedTomorrow : zh.screen.addedBank;
        const undo = async () => {
          try {
            await markWord(word.id, { action: 'restore', context: 'screen_page' });
            putBack(word, true);
            toast.success(zh.common.undone);
          } catch (e) {
            toast.error(errorMessage(e));
          }
        };
        lastUndo.current = undo;
        toast.toast(message, {
          durationMs: UNDO_LIST_MS,
          action: {
            label: zh.common.undo,
            onClick: async () => {
              lastUndo.current = null;
              await undo();
            },
          },
        });
        setTimeout(() => {
          if (lastUndo.current === undo) lastUndo.current = null;
        }, UNDO_LIST_MS);
      } catch (e) {
        toast.error(errorMessage(e));
        putBack(word, stored);
      }
    },
    [putBack, tapLock, toast],
  );

  /** ScreenCard button / swipe verdicts: dropped for a moment after the deck advanced (double tap). */
  const tapVerdict = (word: WordBrief, v: ScreenVerdict) => {
    if (tapLock.locked()) return;
    void verdict(word, v);
  };

  useKeyboard(
    {
      '1': () => current && void verdict(current.word, 'known'),
      '2': () => current && void verdict(current.word, 'unfamiliar'),
      s: () => current && void verdict(current.word, 'skip'),
      Space: () => current && setPeeked(true),
      p: () => current && speak(current.word.display, settings?.accent ?? 'en-US'),
      u: () => {
        const undo = lastUndo.current;
        lastUndo.current = null;
        if (undo) void undo();
      },
    },
    { enabled: current !== null },
  );

  if (!stage) return null;

  return (
    <section className="page screen-run">
      <header className="screen-run__head">
        <Link to={routePaths.screen} className="screen-run__back">
          {zh.common.back}
        </Link>
        <h1 className="screen-run__title">{title}</h1>
        <span className="screen-run__remaining muted" aria-live="polite">
          {remaining !== null ? zh.screen.remaining(remaining) : ''}
        </span>
      </header>

      {current ? (
        <ScreenCard key={current.word.id} word={current.word} onVerdict={(v) => tapVerdict(current.word, v)} peeked={peeked} onPeek={() => setPeeked(true)} accent={settings?.accent} />
      ) : fetching ? (
        <div className="screen-run__loading" aria-busy="true">
          <Skeleton height={200} />
        </div>
      ) : fetchError ? (
        <EmptyState title={fetchError} action={{ label: zh.common.retry, onClick: () => void fetchMore() }} />
      ) : exhausted || remaining === 0 ? (
        <EmptyState title={zh.screen.allDone} description={screened > 0 ? zh.screen.screenedCount(screened) : undefined} action={{ label: zh.today.goVocab, to: routePaths.vocab }} />
      ) : (
        <div className="screen-run__between card">
          <p className="screen-run__between-text">{zh.screen.screenedCount(screened)}</p>
          <Button variant="primary" size="lg" onClick={() => void fetchMore()}>
            {zh.screen.another}
          </Button>
        </div>
      )}
    </section>
  );
}
