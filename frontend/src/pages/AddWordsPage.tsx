// AddWordsPage — `/bank/add` (FRONTEND §5.6): textarea (paste many; `?prefill=` honoured), live preview per
// line (client-side DESIGN §5.1 mirror first, then GET /api/lookup?q= debounced 300 ms, cached by lemma),
// ambiguous candidate chips (→ POST /api/bank/add-word), note, study today, results with status badges; pending
// rows poll through AttentionBadge until validated, then show `bank.status.validated` (badge + header count follow). Lines the
// client rejects carry the server's own reason strings (`zh.bank.invalidReason`). Calls refreshCounters() after every add.
import { useEffect, useMemo, useRef, useState } from 'react';
import { Link, useSearchParams } from 'react-router';
import { errorMessage } from '@/api/client';
import * as endpoints from '@/api/endpoints';
import type { AddResult, LookupPreview, WordBrief, WordDetail } from '@/api/types';
import { useAuth } from '@/auth/AuthContext';
import { AddStatusBadge, AddWordPreviewRow, type AddBadgeStatus } from '@/components/bank/AddWordPreviewRow';
import { AttentionBadge, briefOf } from '@/components/bank/AttentionBadge';
import { Button } from '@/components/ui/Button';
import { Field } from '@/components/ui/Field';
import { Switch } from '@/components/ui/Switch';
import { useDebounce } from '@/hooks/useDebounce';
import { usePageTitle } from '@/hooks/usePageTitle';
import { useToast } from '@/hooks/useToast';
import { zh } from '@/i18n/zh';
import { routePaths } from '@/routes';
import { analyseInput, MAX_WORDS_PER_ADD, type InputLine } from '@/utils/normalizeInput';
import '@/components/bank/bank.css';
import './AddWordsPage.css';

interface PreviewEntry {
  status: 'loading' | 'ready' | 'error';
  preview: LookupPreview | null;
  message: string | null;
}

/** Builds the synthetic `AddResult` shown when a single add-word call fails (exported for tests). */
export function failedResult(input: string, error: string): AddResult {
  return { input, status: 'invalid', word: null, mine: null, resolved_via: null, lemma_note_zh: null, candidates: [], error, message: null, added_to_today: false };
}

/** A result row; `validated` is set once the AttentionBadge poll saw the AI check finish (FRONTEND §5.6). */
export type ResultEntry = AddResult & { validated?: boolean };

/** Badge status of a row: the server status, or `validated` after a pending-AI row resolved (exported for tests). */
export function badgeStatus(r: ResultEntry): AddBadgeStatus {
  return r.validated ? 'validated' : r.status;
}

interface ResultRowProps {
  result: ResultEntry;
  studyToday: boolean;
  onPickCandidate: (word: WordBrief) => void;
  onEdit: (input: string) => void;
  onReplace: () => void;
  onRemove: () => void;
  onKeep: () => void;
  onUpdate: (detail: WordDetail) => void;
}

function ResultRow({ result, studyToday, onPickCandidate, onEdit, onReplace, onRemove, onKeep, onUpdate }: ResultRowProps) {
  const word = result.word;
  const todayNote = result.added_to_today ? zh.screen.addedToday : studyToday && result.status === 'pending_ai' ? zh.screen.addedTomorrow : null;
  return (
    <li className="result-row">
      <div className="result-row__line">
        <span className="result-row__input" lang="en">
          {word ? <Link to={routePaths.word(word.id)}>{word.display}</Link> : result.input}
        </span>
        <AddStatusBadge status={badgeStatus(result)} />
        {word && word.display.toLowerCase() !== result.input.trim().toLowerCase() && (
          <span className="result-row__detail" lang="en">
            ({result.input})
          </span>
        )}
      </div>
      {word?.translation_short && <div className="result-row__detail">{word.translation_short}</div>}
      {result.lemma_note_zh && <div className="result-row__note">{result.lemma_note_zh}</div>}
      {(result.error || result.message) && <div className="result-row__note">{result.error ?? result.message}</div>}
      {todayNote && <div className="result-row__today">{todayNote}</div>}
      {result.status === 'ambiguous' && result.candidates.length > 0 && (
        <div className="preview-row__chips" role="group" aria-label={zh.bank.preview.ambiguous}>
          {result.candidates.map((c) => (
            <button key={c.id} type="button" className="chip-btn" onClick={() => onPickCandidate(c)}>
              <span lang="en">{c.display}</span>
              {c.translation_short && <span className="chip-btn__sub">{c.translation_short}</span>}
            </button>
          ))}
        </div>
      )}
      {word && result.mine && (
        <AttentionBadge
          mine={result.mine}
          word={word}
          onEdit={() => onEdit(result.mine?.input_text ?? result.input)}
          onReplace={onReplace}
          onRemove={onRemove}
          onKeep={onKeep}
          onUpdate={onUpdate}
        />
      )}
    </li>
  );
}

export default function AddWordsPage() {
  usePageTitle(zh.bank.add);
  const toast = useToast();
  const { refreshCounters } = useAuth();
  const [params] = useSearchParams();
  const [text, setText] = useState(() => params.get('prefill') ?? '');
  const [note, setNote] = useState('');
  const [studyToday, setStudyToday] = useState(false);
  const [previews, setPreviews] = useState<Record<string, PreviewEntry>>({});
  const [chosen, setChosen] = useState<Record<string, WordBrief>>({});
  const [results, setResults] = useState<ResultEntry[] | null>(null);
  const [submitting, setSubmitting] = useState(false);
  const aliveRef = useRef(true);
  const textareaRef = useRef<HTMLTextAreaElement>(null);

  useEffect(() => {
    aliveRef.current = true;
    return () => {
      aliveRef.current = false;
    };
  }, []);

  const debouncedText = useDebounce(text, 300);
  const lines: InputLine[] = useMemo(() => analyseInput(debouncedText), [debouncedText]);
  const validLines = useMemo(() => lines.filter((l) => l.result.ok && !l.duplicate), [lines]);
  const tooMany = validLines.length > MAX_WORDS_PER_ADD;

  // Fetch previews for lemmas not seen yet (the cache lives for the page's lifetime).
  useEffect(() => {
    const missing: string[] = [];
    for (const line of validLines.slice(0, MAX_WORDS_PER_ADD)) {
      if (!line.result.ok) continue;
      const lemma = line.result.lemma;
      if (!(lemma in previews) && !missing.includes(lemma)) missing.push(lemma);
    }
    if (missing.length === 0) return;
    setPreviews((prev) => ({ ...prev, ...Object.fromEntries(missing.map((l) => [l, { status: 'loading', preview: null, message: null } satisfies PreviewEntry])) }));
    for (const lemma of missing) {
      endpoints.lookup(lemma).then(
        (preview) => {
          if (aliveRef.current) setPreviews((prev) => ({ ...prev, [lemma]: { status: 'ready', preview, message: null } }));
        },
        (e: unknown) => {
          if (aliveRef.current) setPreviews((prev) => ({ ...prev, [lemma]: { status: 'error', preview: null, message: errorMessage(e) } }));
        },
      );
    }
  }, [validLines, previews]);

  const pick = (lemma: string, word: WordBrief) =>
    setChosen((prev) => {
      const next = { ...prev };
      if (next[lemma]?.id === word.id) delete next[lemma];
      else next[lemma] = word;
      return next;
    });

  const replaceResult = (input: string, next: ResultEntry) => setResults((prev) => (prev ? prev.map((r) => (r.input === input ? next : r)) : prev));
  const patchResult = (input: string, patch: Partial<ResultEntry>) => setResults((prev) => (prev ? prev.map((r) => (r.input === input ? { ...r, ...patch } : r)) : prev));
  const noteBody = () => (note.trim() ? { note: note.trim() } : {});

  const addChosen = async (input: string, word: WordBrief) => {
    try {
      const res = await endpoints.addWord({ word_id: word.id, ...noteBody(), study_today: studyToday });
      replaceResult(input, { ...res, input });
      void refreshCounters();
    } catch (e) {
      toast.error(errorMessage(e));
    }
  };

  const submit = async () => {
    if (submitting || tooMany || validLines.length === 0) return;
    setSubmitting(true);
    const collected: AddResult[] = [];
    const plain: InputLine[] = [];
    const picked: { line: InputLine; word: WordBrief }[] = [];
    for (const line of validLines) {
      if (!line.result.ok) continue;
      const word = chosen[line.result.lemma];
      if (word) picked.push({ line, word });
      else plain.push(line);
    }
    try {
      if (plain.length > 0) {
        const res = await endpoints.addWords({ text: plain.map((l) => l.raw).join('\n'), ...noteBody(), study_today: studyToday });
        collected.push(...res.results);
      }
      for (const { line, word } of picked) {
        try {
          const res = await endpoints.addWord({ word_id: word.id, ...noteBody(), study_today: studyToday });
          collected.push({ ...res, input: line.raw });
        } catch (e) {
          collected.push(failedResult(line.raw, errorMessage(e)));
        }
      }
      setResults((prev) => [...collected, ...(prev ?? [])]);
      setText('');
      setChosen({});
      void refreshCounters();
    } catch (e) {
      toast.error(errorMessage(e));
    } finally {
      setSubmitting(false);
    }
  };

  const editAgain = (input: string) => {
    setText((prev) => (prev.trim() ? `${prev.trimEnd()}\n${input}` : input));
    textareaRef.current?.focus();
  };

  const resultActions = (result: ResultEntry) => ({
    onReplace: async () => {
      if (!result.word) return;
      try {
        const res = await endpoints.acceptBankSuggestion(result.word.id);
        toast.success(zh.common.saved);
        patchResult(result.input, { status: 'added', word: result.mine?.suggested_word ?? result.word, mine: res.mine });
        void refreshCounters();
      } catch (e) {
        toast.error(errorMessage(e));
      }
    },
    onRemove: async () => {
      if (!result.word) return;
      try {
        await endpoints.markWord(result.word.id, { action: 'remove', context: 'bank' });
        toast.toast(zh.bank.tabs.removed);
        patchResult(result.input, { mine: null });
        void refreshCounters();
      } catch (e) {
        toast.error(errorMessage(e));
      }
    },
    onKeep: async () => {
      if (!result.word) return;
      try {
        const mine = await endpoints.patchBankEntry(result.word.id, { attention: 'keep' });
        toast.success(result.word.is_valid_english === false ? zh.bank.keptOnly : zh.common.saved);
        patchResult(result.input, { mine });
        void refreshCounters();
      } catch (e) {
        toast.error(errorMessage(e));
      }
    },
    onEdit: async (input: string) => {
      if (!result.word) return;
      try {
        await endpoints.markWord(result.word.id, { action: 'remove', context: 'bank' });
        patchResult(result.input, { mine: null });
        void refreshCounters();
        editAgain(input);
      } catch (e) {
        toast.error(errorMessage(e));
      }
    },
    onUpdate: (detail: WordDetail) => {
      // the poll resolved: a pending-AI row whose word now carries a verdict (valid, or flagged by the AttentionBadge) is validated
      const validated = result.validated || (result.status === 'pending_ai' && detail.word.is_valid_english !== null);
      patchResult(result.input, { word: briefOf(detail.word), mine: detail.mine, ...(validated ? { validated: true } : {}) });
      void refreshCounters();
    },
  });

  const summary = results
    ? {
        added: results.filter((r) => r.status === 'added' || r.status === 'readded' || r.validated).length,
        pending: results.filter((r) => r.status === 'pending_ai' && !r.validated).length,
      }
    : null;

  return (
    <section className="page page--narrow addwords">
      <h1 className="page__title">{zh.bank.add}</h1>
      <Field label={zh.bank.add} hint={zh.bank.addMany} htmlFor="addwords-text">
        <textarea
          id="addwords-text"
          ref={textareaRef}
          value={text}
          autoFocus
          spellCheck={false}
          autoCapitalize="off"
          autoCorrect="off"
          lang="en"
          maxLength={4000}
          onChange={(e) => setText(e.target.value)}
        />
      </Field>
      <div className="addwords__hint" aria-live="polite">
        <span className={tooMany ? 'is-over' : undefined}>{tooMany ? zh.errors.tooManyWords : validLines.length > 0 ? zh.bank.counts(validLines.length) : null}</span>
      </div>

      {lines.length > 0 && (
        <ul className="preview-list addwords__preview" aria-live="polite" aria-label={zh.bank.add}>
          {lines.slice(0, MAX_WORDS_PER_ADD).map((line) => {
            const lemma = line.result.ok ? line.result.lemma : null;
            const entry = lemma ? previews[lemma] : undefined;
            return (
              <AddWordPreviewRow
                key={`${line.index}-${line.raw}`}
                input={line.raw}
                preview={entry?.preview ?? null}
                loading={entry?.status === 'loading'}
                invalidMessage={!line.result.ok ? zh.bank.invalidReason[line.result.reason] : entry?.status === 'error' ? entry.message : null}
                duplicate={line.duplicate}
                chosenId={lemma ? (chosen[lemma]?.id ?? null) : null}
                onPick={lemma ? (word) => pick(lemma, word) : undefined}
              />
            );
          })}
        </ul>
      )}

      <div className="addwords__options">
        <Field label={zh.bank.note} htmlFor="addwords-note">
          <input id="addwords-note" type="text" value={note} maxLength={500} onChange={(e) => setNote(e.target.value)} />
        </Field>
        <Switch checked={studyToday} onChange={setStudyToday} label={zh.bank.studyToday} />
      </div>
      <Button variant="primary" size="lg" block loading={submitting} disabled={tooMany || validLines.length === 0} onClick={() => void submit()}>
        {zh.bank.submit}
      </Button>

      {results && results.length > 0 && summary && (
        <div className="addwords__results">
          <h2>
            <span>{zh.bank.status.added}</span>
            <span className="addwords__summary">
              {zh.bank.counts(summary.added)}
              {summary.pending > 0 ? ` · ${zh.bank.pendingAi} ${summary.pending}` : ''}
            </span>
          </h2>
          <ul className="result-list" aria-live="polite">
            {results.map((r, i) => (
              <ResultRow key={`${r.input}-${i}`} result={r} studyToday={studyToday} onPickCandidate={(w) => void addChosen(r.input, w)} {...resultActions(r)} />
            ))}
          </ul>
        </div>
      )}
    </section>
  );
}
