// WordDetailPage — `/words/:idOrLemma` (FRONTEND §5.8, API.md 23–30). Full ECDICT entry, forms chips,
// Claude content (or the pending / deferred / failed copy with generateExamples), image with refresh-image (refresh →
// poll `GET …/image`) and flag-image (report target image), SRS panel, my last 20 actions, the actions bar
// (unfamiliar / mastered / remove / reset) and the report sheet. A lemma that maps to several headwords (409
// ambiguous_form) renders the candidate chips; `redirected_from` shows zh.word.redirected(from).
import { useCallback, useEffect, useRef, useState } from 'react';
import { Link, useParams } from 'react-router';
import { errorMessage, isApiError } from '@/api/client';
import { getWord, getWordContent, getWordImage, markWord, refreshWordImage, reportWord, requestWordContent } from '@/api/endpoints';
import type { ContentResponse, ReportTarget } from '@/api/endpoints';
import type { MarkAction, ReportReason, ReviewLogItem, UserState, WordBrief, WordDetail } from '@/api/types';
import { useAuth } from '@/auth/AuthContext';
import { ExampleList } from '@/components/study/ExampleList';
import { WordImage } from '@/components/study/WordImage';
import { Button } from '@/components/ui/Button';
import { ConfirmDialog } from '@/components/ui/ConfirmDialog';
import { EmptyState } from '@/components/ui/EmptyState';
import { Sheet } from '@/components/ui/Sheet';
import { Skeleton } from '@/components/ui/Skeleton';
import { cx } from '@/components/ui/cx';
import { formatDueSentence, StateBadge, stateLabel } from '@/components/word/StateBadge';
import { WordHeader } from '@/components/word/WordHeader';
import { useApi } from '@/hooks/useApi';
import { usePageTitle } from '@/hooks/usePageTitle';
import { UNDO_LIST_MS, UNDO_MASTER_MS, useToast } from '@/hooks/useToast';
import { zh } from '@/i18n/zh';
import { routePaths } from '@/routes';
import { formatPos } from '@/utils/pos';
import { formatDateTime } from '@/utils/srsPreview';
import './WordDetailPage.css';

const CONTENT_POLL_MS = 5_000;
const CONTENT_POLL_MAX = 24;
const IMAGE_POLL_MS = 3_000;
const IMAGE_POLL_MAX = 20;

type ConfirmKind = 'mastered' | 'remove' | 'reset';

const REPORT_REASONS: readonly ReportReason[] = ['wrong_meaning', 'unnatural_example', 'bad_translation', 'irrelevant_image', 'inappropriate_image', 'other'];

/** API.md 28 target for a reason (image reasons → image, dictionary-only words → dictionary). */
export function reportTargetFor(reason: ReportReason, hasContent: boolean): ReportTarget {
  if (reason === 'irrelevant_image' || reason === 'inappropriate_image') return 'image';
  if (reason === 'wrong_meaning' && !hasContent) return 'dictionary';
  return 'content';
}

/** Label of a `review_logs.action` for the my-history list. */
export function logActionLabel(action: string, newState: UserState | null): string {
  switch (action) {
    case 'again':
      return zh.study.again;
    case 'hard':
      return zh.study.hard;
    case 'good':
      return zh.study.good;
    case 'master':
      return zh.study.master;
    case 'skip':
      return zh.study.skip;
    case 'unfamiliar':
      return zh.study.unfamiliar;
    case 'readd':
      return zh.bank.status.readded;
    case 'known':
      return zh.study.known;
    case 'remove':
      return zh.word.remove;
    case 'reset':
      return zh.word.reset;
    case 'restore':
      return zh.common.undone;
    case 'add_custom':
      return zh.bank.status.added;
    case 'import':
      return zh.settings.import;
    case 'consolidate':
      return zh.suggestions.autoSection;
    default:
      return stateLabel(newState);
  }
}

function candidatesOf(details: Record<string, unknown> | undefined): WordBrief[] {
  const raw = details?.['candidates'];
  if (!Array.isArray(raw)) return [];
  return raw.filter((c): c is WordBrief => typeof c === 'object' && c !== null && typeof (c as WordBrief).id === 'number' && typeof (c as WordBrief).display === 'string');
}

function deferredFrom(res: ContentResponse, nowIso: string): string | null {
  if (res.deferred_until) return res.deferred_until;
  if (res.state === 'queued' && res.eta_s === null) return nowIso;
  return null;
}

function splitLines(text: string | null | undefined): string[] {
  return (text ?? '')
    .split(/\r?\n/)
    .map((s) => s.trim())
    .filter(Boolean);
}

export default function WordDetailPage() {
  const { idOrLemma = '' } = useParams();
  const key: number | string = /^\d+$/.test(idOrLemma) ? Number(idOrLemma) : idOrLemma;
  const { settings } = useAuth();
  const toast = useToast();
  const { data, error, loading, reload, setData } = useApi<WordDetail>((signal) => getWord(key, signal), [idOrLemma], { keepPreviousData: false });
  usePageTitle(data ? data.word.display : zh.word.title);

  const [confirm, setConfirm] = useState<ConfirmKind | null>(null);
  const [acting, setActing] = useState(false);
  const [reportOpen, setReportOpen] = useState(false);
  const [reason, setReason] = useState<ReportReason>('wrong_meaning');
  const [note, setNote] = useState('');
  const [reporting, setReporting] = useState(false);
  const [imageRefreshing, setImageRefreshing] = useState(false);
  const [requestingContent, setRequestingContent] = useState(false);
  const imagePoll = useRef<ReturnType<typeof setInterval> | null>(null);

  const patch = useCallback(
    (p: Partial<WordDetail>) => {
      setData((d) => (d ? { ...d, ...p } : d));
    },
    [setData],
  );

  useEffect(
    () => () => {
      if (imagePoll.current) clearInterval(imagePoll.current);
    },
    [],
  );

  // ---- content polling (5 s, max 24) while queued and not deferred ----------------------------------
  const wordId = data?.word.id ?? null;
  const pollKey = data ? `${data.word.id}:${data.content_state}:${data.content_deferred_until ?? ''}` : '';
  useEffect(() => {
    if (!data || wordId === null || data.content_state !== 'queued' || data.content_deferred_until !== null) return;
    let count = 0;
    let cancelled = false;
    const timer = setInterval(async () => {
      if (cancelled || document.visibilityState === 'hidden') return;
      if (++count > CONTENT_POLL_MAX) {
        clearInterval(timer);
        return;
      }
      try {
        const res = await getWordContent(wordId);
        if (cancelled) return;
        const deferred = deferredFrom(res, new Date().toISOString());
        if (res.state === 'ready' && res.content) patch({ content: res.content, content_state: 'ready', content_deferred_until: null });
        else if (deferred) patch({ content_deferred_until: deferred, content_state: res.state });
        else if (res.state !== 'queued') patch({ content_state: res.state });
      } catch {
        /* keep polling */
      }
    }, CONTENT_POLL_MS);
    return () => {
      cancelled = true;
      clearInterval(timer);
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [pollKey, patch]);

  // ---- image: refresh-image / flag-image then poll until a new image arrives -----------------------------------
  const startImagePoll = useCallback(
    (id: number, previousUrl: string) => {
      if (imagePoll.current) clearInterval(imagePoll.current);
      let count = 0;
      setImageRefreshing(true);
      imagePoll.current = setInterval(async () => {
        if (++count > IMAGE_POLL_MAX) {
          if (imagePoll.current) clearInterval(imagePoll.current);
          imagePoll.current = null;
          setImageRefreshing(false);
          return;
        }
        try {
          const image = await getWordImage(id);
          if (image.url !== previousUrl) {
            patch({ image });
            if (imagePoll.current) clearInterval(imagePoll.current);
            imagePoll.current = null;
            setImageRefreshing(false);
          }
        } catch {
          /* try again on the next tick */
        }
      }, IMAGE_POLL_MS);
    },
    [patch],
  );

  const refreshImage = useCallback(async () => {
    if (!data) return;
    try {
      await refreshWordImage(data.word.id);
      toast.toast(zh.word.changingImage);
      startImagePoll(data.word.id, data.image.url);
    } catch (e) {
      toast.error(errorMessage(e));
    }
  }, [data, startImagePoll, toast]);

  const flagImage = useCallback(async () => {
    if (!data) return;
    try {
      await reportWord(data.word.id, { target: 'image', reason: 'irrelevant_image' });
      toast.success(zh.word.reported);
      startImagePoll(data.word.id, data.image.url);
    } catch (e) {
      toast.error(errorMessage(e));
    }
  }, [data, startImagePoll, toast]);

  // ---- generateExamples ---------------------------------------------------------------------------------------
  const requestContent = useCallback(async () => {
    if (!data) return;
    setRequestingContent(true);
    try {
      const res = await requestWordContent(data.word.id);
      patch({ content_state: res.state === 'ready' ? 'ready' : 'queued', content_deferred_until: null });
      toast.toast(zh.word.examplesQueued);
    } catch (e) {
      if (isApiError(e) && e.code === 'budget_exhausted') {
        const resumesAt = typeof e.details?.['resumes_at'] === 'string' ? (e.details['resumes_at'] as string) : new Date().toISOString();
        patch({ content_deferred_until: resumesAt });
      }
      if (isApiError(e) && e.code === 'rate_limited' && (e.detailNumber('retry_after_s') ?? 0) > 600) toast.error(zh.word.examplesQuotaToday); // the per-user daily quota (resets at UTC midnight), not a burst limit
      else toast.error(errorMessage(e));
    } finally {
      setRequestingContent(false);
    }
  }, [data, patch, toast]);

  // ---- state transitions (API.md 26, context 'detail') -------------------------------------------
  const mark = useCallback(
    async (action: MarkAction) => {
      if (!data) return;
      const id = data.word.id;
      setActing(true);
      try {
        const res = await markWord(id, { action, context: 'detail' });
        patch({ mine: res.mine, word: { ...data.word, my_state: res.state } });
        const undo = async () => {
          try {
            const r = await markWord(id, { action: 'restore', context: 'detail' });
            setData((d) => (d ? { ...d, mine: r.mine, word: { ...d.word, my_state: r.state } } : d));
            toast.success(action === 'mastered' ? zh.study.restored : zh.common.undone);
            void reload();
          } catch (e) {
            toast.error(errorMessage(e));
          }
        };
        if (action === 'mastered' && res.state === 'mastered') {
          toast.toast(zh.study.mastered, { durationMs: UNDO_MASTER_MS, action: { label: zh.common.undo, onClick: undo } });
        } else if (action === 'unfamiliar' && res.status === 'added') {
          toast.toast(zh.vocab.addedToBank, { durationMs: UNDO_LIST_MS, action: { label: zh.common.undo, onClick: undo } });
        } else if (action === 'unfamiliar') {
          toast.toast(res.status === 'readded' ? zh.bank.status.readded : zh.vocab.inBank);
        } else {
          toast.success(zh.common.saved);
        }
        void reload();
      } catch (e) {
        toast.error(errorMessage(e));
      } finally {
        setActing(false);
      }
    },
    [data, patch, reload, setData, toast],
  );

  const onMastered = () => {
    if (data?.mine?.srs.mastery_suggested) void mark('mastered');
    else setConfirm('mastered');
  };

  const submitReport = async () => {
    if (!data) return;
    setReporting(true);
    try {
      const body = { target: reportTargetFor(reason, data.content !== null), reason, ...(note.trim() ? { note: note.trim().slice(0, 300) } : {}) };
      await reportWord(data.word.id, body);
      toast.success(zh.word.reported);
      setReportOpen(false);
      setNote('');
      if (body.target === 'image') startImagePoll(data.word.id, data.image.url);
    } catch (e) {
      toast.error(errorMessage(e));
    } finally {
      setReporting(false);
    }
  };

  // ---- render ----------------------------------------------------------------------------------------
  if (loading && !data) {
    return (
      <section className="page word-detail" aria-busy="true">
        <Skeleton height={40} width="50%" />
        <Skeleton lines={4} />
        <Skeleton height={180} />
      </section>
    );
  }

  if (error && !data) {
    if (error.code === 'ambiguous_form') {
      const candidates = candidatesOf(error.details);
      return (
        <section className="page word-detail">
          <h1 className="page__title" lang="en">
            {idOrLemma}
          </h1>
          <p>{zh.bank.preview.ambiguous}</p>
          <ul className="chips chips--md word-detail__candidates">
            {candidates.map((c) => (
              <li key={c.id}>
                <Link className="chip chip--link" to={routePaths.word(c.id)}>
                  <span lang="en">{c.display}</span>
                  {c.translation_short && <span className="word-detail__candidate-zh muted"> · {c.translation_short}</span>}
                </Link>
              </li>
            ))}
          </ul>
        </section>
      );
    }
    if (error.status === 404) {
      return (
        <section className="page word-detail">
          <EmptyState title={zh.vocab.notFound(idOrLemma)} action={{ label: zh.bank.add, to: routePaths.bankAddPrefill(idOrLemma) }} />
        </section>
      );
    }
    return (
      <section className="page word-detail">
        <EmptyState title={errorMessage(error)} action={{ label: zh.common.retry, onClick: () => void reload() }} />
      </section>
    );
  }
  if (!data) return null;

  const { word, content, mine } = data;
  const state = mine?.state ?? word.my_state;
  const inBank = state === 'new' || state === 'learning';
  const dictLines = splitLines(word.translation);
  const forms = [word.lemma, word.display, ...word.forms.map((f) => f.form)];
  const deferred = data.content_deferred_until !== null;
  const canRequestContent = (data.content_state === 'none' || data.content_state === 'failed') && !deferred && word.is_valid_english !== null;
  const timeZone = settings?.timezone;
  const dueSentence = mine && state === 'learning' ? formatDueSentence(mine.srs.due_at, mine.srs.step) : null;
  const pos = formatPos(word.pos);

  return (
    <section className="page word-detail">
      {data.redirected_from && <p className="word-detail__redirect muted">{zh.word.redirected(data.redirected_from)}</p>}

      <header className="word-detail__head">
        <WordHeader
          word={word}
          size="lg"
          as="h1"
          accent={settings?.accent}
          dance={(settings?.dance_mode ?? 'full') !== 'off' ? word.dance : undefined}
          replay={(settings?.dance_mode ?? 'full') === 'full' ? 'full' : 'form'}
          semanticEnabled={(settings?.dance_mode ?? 'full') === 'full'}
        />
        <div className="word-detail__state">
          <StateBadge state={state} srs={mine?.srs ?? null} />
          {mine && mine.times_added > 1 && <span className="badge">{zh.study.addedTimes(mine.times_added)}</span>}
          {word.is_valid_english === null && <span className="badge">{zh.bank.pendingAi}</span>}
          {word.is_valid_english === false && !mine?.needs_attention && <span className="badge">{zh.bank.keepOnly}</span>}
        </div>
      </header>

      <div className="word-detail__actions" role="group" aria-label={zh.word.actions}>
        {!inBank && (
          <Button variant="primary" tone="again" disabled={acting} onClick={() => void mark('unfamiliar')}>
            {zh.vocab.markUnfamiliar}
          </Button>
        )}
        {inBank && (
          <Button variant={mine?.srs.mastery_suggested ? 'primary' : 'secondary'} tone="good" disabled={acting} onClick={onMastered}>
            {zh.study.master}
            {mine?.srs.mastery_suggested && <span className="badge word-detail__suggested">{zh.study.suggested}</span>}
          </Button>
        )}
        {(inBank || state === 'mastered' || state === 'known') && (
          <Button variant="secondary" disabled={acting} onClick={() => setConfirm('remove')}>
            {zh.word.remove}
          </Button>
        )}
        {state === 'learning' && (
          <Button variant="ghost" disabled={acting} onClick={() => setConfirm('reset')}>
            {zh.word.reset}
          </Button>
        )}
        <Button variant="ghost" onClick={() => setReportOpen(true)}>
          {zh.word.report}
        </Button>
      </div>

      <section className="word-detail__section card" aria-label={zh.study.dictionary}>
        <h2 className="word-detail__section-title">{zh.study.dictionary}</h2>
        {pos && (
          <p className="muted word-detail__pos" lang="en">
            {pos}
          </p>
        )}
        {dictLines.length > 0 ? (
          <ul className="word-detail__lines" lang="zh-CN">
            {dictLines.map((line, i) => (
              <li key={i}>{line}</li>
            ))}
          </ul>
        ) : (
          <p lang="zh-CN">{word.translation_short}</p>
        )}
        {word.definition && (
          <p className="word-detail__definition muted" lang="en">
            {word.definition}
          </p>
        )}
        {word.forms.length > 0 && (
          <div className="word-detail__forms">
            <h3 className="word-detail__subtitle">{zh.word.forms}</h3>
            <ul className="chips">
              {word.forms.map((f) => (
                <li key={`${f.kind}:${f.form}`} className="chip">
                  <span lang="en">{f.form}</span>
                  <span className="muted"> · {(zh.bank.formKinds as Record<string, string>)[f.kind] ?? f.kind}</span>
                </li>
              ))}
            </ul>
          </div>
        )}
        {word.exam_tags.length > 0 && (
          <div className="word-detail__forms">
            <h3 className="word-detail__subtitle">{zh.word.examTags}</h3>
            <ul className="chips">
              {word.exam_tags.map((t) => (
                <li key={t} className="chip">
                  {t}
                </li>
              ))}
            </ul>
          </div>
        )}
      </section>

      <WordImage
        image={data.image}
        showImages={settings?.show_images ?? true}
        alt={content?.image_alt_zh ?? null}
        onRefresh={() => void refreshImage()}
        onFlag={() => void flagImage()}
        refreshing={imageRefreshing}
        className="word-detail__image"
      />

      <section className="word-detail__section card" aria-label={zh.study.examples}>
        {content && data.content_state === 'ready' && !deferred ? (
          <>
            {content.meaning_zh && (
              <p className="word-detail__meaning" lang="zh-CN">
                {content.meaning_zh}
              </p>
            )}
            <h2 className="word-detail__section-title">{zh.study.examples}</h2>
            <ExampleList examples={content.examples} lemma={word.lemma} forms={forms} zhMode={settings?.zh_examples ?? 'tap'} accent={settings?.accent} />
            {content.collocations.length > 0 && (
              <>
                <h3 className="word-detail__subtitle">{zh.study.collocations}</h3>
                <ul className="chips chips--md" lang="en">
                  {content.collocations.map((c) => (
                    <li key={c} className="chip">
                      {c}
                    </li>
                  ))}
                </ul>
              </>
            )}
            {content.mnemonic_zh && (
              <>
                <h3 className="word-detail__subtitle">{zh.study.mnemonic}</h3>
                <p className="word-detail__mnemonic">{content.mnemonic_zh}</p>
              </>
            )}
          </>
        ) : (
          <>
            <h2 className="word-detail__section-title">{zh.study.examples}</h2>
            {deferred ? (
              <p className="word-detail__notice word-detail__notice--deferred">{zh.study.contentDeferred}</p>
            ) : data.content_state === 'queued' ? (
              <>
                <p className="word-detail__notice muted">{zh.study.contentPending}</p>
                <Skeleton lines={3} />
              </>
            ) : (
              <p className="word-detail__notice muted">{zh.study.contentFailed}</p>
            )}
            {canRequestContent && (
              <Button variant="secondary" size="sm" loading={requestingContent} onClick={() => void requestContent()}>
                {zh.word.generateExamples}
              </Button>
            )}
          </>
        )}
      </section>

      {word.confusables.length > 0 && (
        <section className="word-detail__section card" aria-label={zh.study.confusable}>
          <h2 className="word-detail__section-title">{zh.study.confusable}</h2>
          <ul className="chips chips--md">
            {word.confusables.map((c) => (
              <li key={c}>
                <Link className="chip chip--link" to={routePaths.word(c)} lang="en">
                  {c}
                </Link>
              </li>
            ))}
          </ul>
        </section>
      )}

      {mine && (
        <section className="word-detail__section card" aria-label={zh.bank.title}>
          <h2 className="word-detail__section-title">{zh.bank.title}</h2>
          <dl className="word-detail__srs">
            <div>
              <dt>{zh.bank.tabs[mine.state]}</dt>
              <dd>{mine.srs.repetitions > 0 ? zh.study.srsLine(mine.srs.repetitions, mine.srs.interval_days) : zh.study.srsNew}</dd>
            </div>
            {dueSentence && (
              <div>
                <dt>{zh.bank.sort.due}</dt>
                <dd>{dueSentence}</dd>
              </div>
            )}
            <div>
              <dt>{zh.bank.sort.ease}</dt>
              <dd>{mine.srs.ease.toFixed(2)}</dd>
            </div>
            <div>
              <dt>{zh.bank.sort.times_added}</dt>
              <dd>{mine.times_added}</dd>
            </div>
            {mine.note && (
              <div className="word-detail__note">
                <dt>{zh.bank.note}</dt>
                <dd>{mine.note}</dd>
              </div>
            )}
          </dl>
        </section>
      )}

      {data.history.length > 0 && (
        <section className="word-detail__section card" aria-label={zh.word.history}>
          <h2 className="word-detail__section-title">{zh.word.history}</h2>
          <ol className="word-detail__history">
            {data.history.map((h: ReviewLogItem) => (
              <li key={h.id} className="word-detail__log">
                <span className="word-detail__log-when muted">{formatDateTime(h.created_at, timeZone)}</span>
                <span className={cx('badge', `word-detail__log--${h.action}`)}>{logActionLabel(h.action, h.new_state)}</span>
                {h.new_state && h.new_state !== h.prev_state && <span className="muted word-detail__log-state">→ {stateLabel(h.new_state)}</span>}
              </li>
            ))}
          </ol>
        </section>
      )}

      <ConfirmDialog
        open={confirm !== null}
        title={confirm === 'remove' ? zh.word.remove : confirm === 'reset' ? zh.word.reset : undefined}
        message={confirm === 'mastered' ? zh.study.masterConfirm : confirm === 'remove' ? zh.word.removeConfirm : zh.word.resetConfirm}
        confirmLabel={confirm === 'mastered' ? zh.study.master : confirm === 'remove' ? zh.word.remove : zh.word.reset}
        danger={confirm === 'remove' || confirm === 'reset'}
        busy={acting}
        onConfirm={async () => {
          const kind = confirm;
          setConfirm(null);
          if (kind) await mark(kind === 'mastered' ? 'mastered' : kind === 'remove' ? 'remove' : 'reset');
        }}
        onCancel={() => setConfirm(null)}
      />

      <Sheet
        open={reportOpen}
        onClose={() => setReportOpen(false)}
        title={zh.word.report}
        footer={
          <>
            <Button variant="secondary" onClick={() => setReportOpen(false)} disabled={reporting}>
              {zh.common.cancel}
            </Button>
            <Button variant="primary" loading={reporting} onClick={() => void submitReport()}>
              {zh.common.confirm}
            </Button>
          </>
        }
      >
        <fieldset className="word-detail__reasons">
          <legend className="visually-hidden">{zh.word.report}</legend>
          {REPORT_REASONS.map((r) => (
            <label key={r} className="word-detail__reason">
              <input type="radio" name="report-reason" value={r} checked={reason === r} onChange={() => setReason(r)} />
              <span>{zh.word.reportReasons[r]}</span>
            </label>
          ))}
        </fieldset>
        <textarea className="word-detail__report-note" rows={3} maxLength={300} value={note} onChange={(e) => setNote(e.target.value)} aria-label={zh.bank.note} />
      </Sheet>
    </section>
  );
}
