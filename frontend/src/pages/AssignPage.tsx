// AssignPage — `/assign` (API.md 124–129; docs/releases/2026-11-assignments.md): the admin or a guardian hands a learner a word list.
// The form: learner, the words (one per line or comma-separated; a search box appends words from the library), when to study
// (`today` / `spread`) and an optional name; "preview" shows what each typed word would become without writing anything, "assign"
// creates the list. Below it the caller's lists with their progress; a list opens to its words (scheduled day, grade, skips) and
// can take back the words that have not reached a day yet. Someone who may assign to nobody sees an explanation instead.
import { useEffect, useState } from 'react';
import { errorMessage } from '@/api/client';
import { createAssignment, getAssignLearners, getAssignment, getAssignments, getVocab, previewAssignment, withdrawAssignment } from '@/api/endpoints';
import type { AssignMode, AssignmentDetail, AssignmentWord, AssignPreviewItem, WordBrief } from '@/api/types';
import { resultLabel } from '@/components/study/StudyCard';
import { Button } from '@/components/ui/Button';
import { EmptyState } from '@/components/ui/EmptyState';
import { Field } from '@/components/ui/Field';
import { Segmented } from '@/components/ui/Segmented';
import { Skeleton } from '@/components/ui/Skeleton';
import { cx } from '@/components/ui/cx';
import { useApi } from '@/hooks/useApi';
import { usePageTitle } from '@/hooks/usePageTitle';
import { useToast } from '@/hooks/useToast';
import { zh } from '@/i18n/zh';
import { formatMonthDay } from '@/utils/srsPreview';
import './AssignPage.css';

const MODE_OPTIONS: { value: AssignMode; label: string }[] = [
  { value: 'today', label: zh.assign.modes.today },
  { value: 'spread', label: zh.assign.modes.spread },
];
const ASSIGNABLE = new Set(['new', 'studying', 'pending_ai']);

/** What a word of a list is doing now: waiting, withdrawn, or the day it was scheduled with its grade / skips. */
export function wordProgress(w: AssignmentWord): string {
  if (w.status === 'withdrawn') return zh.assign.word.withdrawn;
  if (w.status === 'pending') return w.waiting_lookup ? zh.assign.word.waiting : zh.assign.word.pending;
  const day = w.scheduled_date ? formatMonthDay(w.scheduled_date) : '';
  const outcome = resultLabel(w.result) ?? (w.skip_count > 0 ? zh.assign.word.skipped(w.skip_count) : zh.assign.word.open);
  return [day, outcome].filter(Boolean).join(' · ');
}

function PreviewRows({ items }: { items: AssignPreviewItem[] }) {
  return (
    <ul className="assign__preview" aria-label={zh.assign.preview}>
      {items.map((it, i) => (
        <li key={`${it.input}-${i}`} className={cx('assign__preview-row', !ASSIGNABLE.has(it.status) && 'is-off')}>
          <span className="assign__preview-word" lang="en">
            {it.display ?? it.input}
          </span>
          <span className="assign__preview-meaning muted">{it.meaning ?? ''}</span>
          <span className="assign__preview-status">{zh.assign.status[it.status]}</span>
        </li>
      ))}
    </ul>
  );
}

function ListCard({ id, onChanged }: { id: number; onChanged: () => void }) {
  const { data, error, loading, setData } = useApi<AssignmentDetail>((signal) => getAssignment(id, signal), [id]);
  const toast = useToast();
  const [busy, setBusy] = useState(false);
  if (loading && !data) return <Skeleton className="assign__skeleton" />;
  if (error || !data) return <p className="assign__error">{error ? errorMessage(error) : ''}</p>;
  const withdraw = async () => {
    setBusy(true);
    try {
      setData(await withdrawAssignment(id));
      onChanged();
    } catch (e) {
      toast.error(errorMessage(e));
    } finally {
      setBusy(false);
    }
  };
  return (
    <div className="assign__detail">
      <ul className="assign__words">
        {data.words.map((w) => (
          <li key={w.word_id} className={cx('assign__word', w.status === 'withdrawn' && 'is-off')}>
            <span className="assign__word-text" lang="en">
              {w.display}
            </span>
            <span className="assign__word-meaning muted">{w.meaning}</span>
            <span className="assign__word-progress">{wordProgress(w)}</span>
          </li>
        ))}
      </ul>
      {data.counts.pending > 0 && (
        <Button variant="secondary" size="sm" loading={busy} onClick={() => void withdraw()}>
          {zh.assign.withdraw}
        </Button>
      )}
    </div>
  );
}

export default function AssignPage() {
  usePageTitle(zh.assign.title);
  const toast = useToast();
  const learners = useApi((signal) => getAssignLearners(signal), []);
  const lists = useApi((signal) => getAssignments(signal), []);
  const [learnerId, setLearnerId] = useState<number | null>(null);
  const [text, setText] = useState('');
  const [mode, setMode] = useState<AssignMode>('today');
  const [title, setTitle] = useState('');
  const [preview, setPreview] = useState<AssignPreviewItem[] | null>(null);
  const [busy, setBusy] = useState<'preview' | 'submit' | null>(null);
  const [formError, setFormError] = useState<string | null>(null);
  const [openId, setOpenId] = useState<number | null>(null);
  const [query, setQuery] = useState('');
  const [found, setFound] = useState<WordBrief[] | null>(null);

  const people = learners.data?.items ?? [];
  const firstId = people[0]?.id ?? null;
  useEffect(() => {
    if (learnerId === null && firstId !== null) setLearnerId(firstId);
  }, [learnerId, firstId]);

  // the library search: a short debounce, the newest answer wins
  useEffect(() => {
    const q = query.trim();
    if (q.length < 2) {
      setFound(null);
      return;
    }
    let live = true;
    const timer = setTimeout(() => {
      getVocab({ q, page_size: 8 })
        .then((page) => live && setFound(page.items))
        .catch(() => live && setFound([]));
    }, 300);
    return () => {
      live = false;
      clearTimeout(timer);
    };
  }, [query]);

  const append = (word: string) => {
    setText((t) => (t.trim() ? `${t.replace(/\s+$/, '')}\n${word}` : word));
    setPreview(null);
  };

  const runPreview = async () => {
    if (learnerId === null || !text.trim()) return;
    setBusy('preview');
    setFormError(null);
    try {
      setPreview((await previewAssignment(learnerId, text)).items);
    } catch (e) {
      setFormError(errorMessage(e));
    } finally {
      setBusy(null);
    }
  };

  const submit = async () => {
    if (learnerId === null || !text.trim()) return;
    setBusy('submit');
    setFormError(null);
    try {
      const made = await createAssignment({ learner_id: learnerId, text, mode, ...(title.trim() ? { title: title.trim() } : {}) });
      toast.success(zh.assign.submitted(made.assignment.counts.total));
      setPreview(made.results);
      setText('');
      setTitle('');
      setOpenId(made.assignment.id);
      void lists.reload();
    } catch (e) {
      setFormError(errorMessage(e));
    } finally {
      setBusy(null);
    }
  };

  if (learners.loading && !learners.data) {
    return (
      <section className="page assign">
        <h1 className="page__title">{zh.assign.title}</h1>
        <Skeleton className="assign__skeleton" />
      </section>
    );
  }
  if (learners.error) {
    return (
      <section className="page assign">
        <h1 className="page__title">{zh.assign.title}</h1>
        <EmptyState title={errorMessage(learners.error)} action={{ label: zh.common.retry, onClick: () => void learners.reload() }} />
      </section>
    );
  }
  if (people.length === 0) {
    return (
      <section className="page assign">
        <h1 className="page__title">{zh.assign.title}</h1>
        <EmptyState title={zh.assign.noLearners} />
      </section>
    );
  }

  const items = lists.data?.items ?? [];
  return (
    <section className="page assign">
      <h1 className="page__title">{zh.assign.title}</h1>
      <form
        className="assign__form card"
        onSubmit={(e) => {
          e.preventDefault();
          void submit();
        }}
      >
        <Field label={zh.assign.learner}>
          {(control) => (
            <select {...control} className="assign__select" value={learnerId ?? ''} onChange={(e) => { setLearnerId(Number(e.target.value)); setPreview(null); }}>
              {people.map((p) => (
                <option key={p.id} value={p.id}>
                  {p.name}
                </option>
              ))}
            </select>
          )}
        </Field>
        <Field label={zh.assign.words} hint={zh.assign.wordsHint} error={formError ?? undefined}>
          {(control) => (
            <textarea {...control} className="assign__text" rows={6} lang="en" autoCapitalize="off" autoCorrect="off" spellCheck={false} value={text} onChange={(e) => { setText(e.target.value); setPreview(null); }} />
          )}
        </Field>
        <Field label={zh.assign.search}>
          {(control) => <input {...control} className="assign__input" type="search" placeholder={zh.assign.searchPlaceholder} value={query} onChange={(e) => setQuery(e.target.value)} />}
        </Field>
        {found && (
          <ul className="assign__found" aria-label={zh.assign.search}>
            {found.length === 0 && <li className="muted">{zh.assign.searchEmpty}</li>}
            {found.map((w) => (
              <li key={w.id}>
                <button type="button" className="assign__found-item" onClick={() => append(w.display)}>
                  <span lang="en">{w.display}</span>
                  <span className="muted">{w.translation_short}</span>
                </button>
              </li>
            ))}
          </ul>
        )}
        <Field label={zh.assign.mode} hint={zh.assign.modeHint[mode]}>
          {(control) => <Segmented block options={MODE_OPTIONS} value={mode} onChange={setMode} aria-labelledby={undefined} aria-label={zh.assign.mode} aria-describedby={control['aria-describedby']} />}
        </Field>
        <Field label={zh.assign.name}>{(control) => <input {...control} className="assign__input" maxLength={40} value={title} onChange={(e) => setTitle(e.target.value)} />}</Field>
        <div className="assign__actions">
          <Button type="button" variant="secondary" loading={busy === 'preview'} disabled={!text.trim() || busy === 'submit'} onClick={() => void runPreview()}>
            {zh.assign.preview}
          </Button>
          <Button type="submit" loading={busy === 'submit'} disabled={!text.trim() || busy === 'preview'}>
            {zh.assign.submit}
          </Button>
        </div>
        {preview && <PreviewRows items={preview} />}
      </form>

      <h2 className="assign__heading">{zh.assign.mine}</h2>
      {items.length === 0 && !lists.loading && <p className="muted">{zh.assign.empty}</p>}
      <ul className="assign__lists">
        {items.map((a) => (
          <li key={a.id} className="assign__list card">
            <div className="assign__list-head">
              <div className="assign__list-title">
                <span>{a.learner.name}</span>
                <span className="muted">
                  {formatMonthDay(a.created_at.slice(0, 10))} · {zh.assign.modes[a.mode]}
                  {a.title ? ` · ${a.title}` : ''}
                </span>
              </div>
              <Button variant="ghost" size="sm" aria-expanded={openId === a.id} onClick={() => setOpenId(openId === a.id ? null : a.id)}>
                {openId === a.id ? zh.assign.hide : zh.assign.detail}
              </Button>
            </div>
            <p className="assign__list-counts">
              {zh.assign.summary(a.counts.total, a.counts.scheduled, a.counts.done)}
              {a.counts.pending > 0 ? ` · ${zh.assign.pendingCount(a.counts.pending)}` : ''}
            </p>
            {openId === a.id && <ListCard id={a.id} onChanged={() => void lists.reload()} />}
          </li>
        ))}
      </ul>
    </section>
  );
}
