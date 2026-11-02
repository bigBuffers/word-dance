// AddWordPreviewRow — one line of the add words live preview (FRONTEND §4/§5.6): ✓ recognised ·
// "lemmatised to abandon (past tense)" · candidate chips (ambiguous) · "not in the dictionary, AI will validate" ·
// ⚠ reason_zh · "already in your bank". Suggestions (≤ 5 prefix matches) are offered as pickable chips too.
import type { ReactNode } from 'react';
import type { AddResult, LookupPreview, WordBrief } from '@/api/types';
import { cx } from '@/components/ui/cx';
import { Skeleton } from '@/components/ui/Skeleton';
import { StateBadge } from '@/components/word/StateBadge';
import { zh } from '@/i18n/zh';
import './bank.css';

/** Server statuses plus the client-only `validated` (a pending-AI row whose poll saw the AI check finish — FRONTEND §5.6). */
export type AddBadgeStatus = AddResult['status'] | 'validated';

/** Status badge of an `AddResult` / import row (zh.bank.status.*), shared by the add-words page and the import result sheet. */
export function AddStatusBadge({ status }: { status: AddBadgeStatus }) {
  return <span className={`status-badge status-badge--${status}`}>{zh.bank.status[status]}</span>;
}

export interface AddWordPreviewRowProps {
  /** The line as typed. */
  input: string;
  /** Server preview; null while loading or when the line failed the client-side rules. */
  preview: LookupPreview | null;
  loading?: boolean;
  /** Client-side rejection (DESIGN §5.1 mirror) shown without a request. */
  invalidMessage?: string | null;
  /** An earlier line normalises to the same lemma. */
  duplicate?: boolean;
  /** Candidate / suggestion picked for this line. */
  chosenId?: number | null;
  onPick?: (word: WordBrief) => void;
  className?: string;
}

function CandidateChips({ words, chosenId, onPick, label }: { words: WordBrief[]; chosenId: number | null | undefined; onPick?: (w: WordBrief) => void; label: string }) {
  if (words.length === 0) return null;
  return (
    <div className="preview-row__chips" role="group" aria-label={label}>
      {words.map((w) => (
        <button key={w.id} type="button" className="chip-btn" aria-pressed={chosenId === w.id} disabled={!onPick} onClick={() => onPick?.(w)}>
          <span lang="en">{w.display}</span>
          {w.translation_short && <span className="chip-btn__sub">{w.translation_short}</span>}
        </button>
      ))}
    </div>
  );
}

export function AddWordPreviewRow({ input, preview, loading = false, invalidMessage, duplicate = false, chosenId, onPick, className }: AddWordPreviewRowProps) {
  let tone: 'ok' | 'warn' | 'invalid' | 'muted' = 'muted';
  let status: ReactNode = null;
  let detail: ReactNode = null;
  let chips: ReactNode = null;

  if (invalidMessage) {
    tone = 'invalid';
    status = (
      <>
        <span aria-hidden="true">⚠</span> {invalidMessage}
      </>
    );
  } else if (loading || !preview) {
    status = <Skeleton width={140} height="1em" />;
  } else {
    const { via, match, mine } = preview;
    switch (via) {
      case 'invalid':
        tone = 'invalid';
        status = (
          <>
            <span aria-hidden="true">⚠</span> {preview.reason_zh ?? zh.errors.invalidWord}
          </>
        );
        break;
      case 'exact':
      case 'ecdict':
        tone = 'ok';
        status = (
          <>
            <span aria-hidden="true">✓</span> {mine ? zh.bank.preview.inBank : zh.bank.preview.exact}
          </>
        );
        detail = match ? (
          <>
            <span lang="en">{match.display}</span>
            {match.translation_short ? ` · ${match.translation_short}` : ''}
            {mine && (
              <>
                {' '}
                <StateBadge state={mine.state} srs={mine.srs} />
              </>
            )}
          </>
        ) : null;
        break;
      case 'form':
        tone = 'ok';
        status = (
          <>
            <span aria-hidden="true">✓</span> {mine ? zh.bank.preview.inBank : preview.lemma_note_zh ?? zh.bank.preview.form(match?.display ?? preview.normalized ?? input, zh.bank.formKinds.alt)}
          </>
        );
        detail = match ? (
          <>
            <span lang="en">{match.display}</span>
            {match.translation_short ? ` · ${match.translation_short}` : ''}
            {mine && preview.lemma_note_zh ? ` · ${preview.lemma_note_zh}` : ''}
          </>
        ) : null;
        break;
      case 'ambiguous':
        tone = 'warn';
        status = zh.bank.preview.ambiguous;
        chips = <CandidateChips words={preview.candidates} chosenId={chosenId} onPick={onPick} label={zh.bank.preview.ambiguous} />;
        break;
      case 'none':
      default:
        tone = 'warn';
        status = zh.bank.preview.none;
        chips = <CandidateChips words={preview.suggestions} chosenId={chosenId} onPick={onPick} label={zh.bank.preview.none} />;
        break;
    }
  }

  return (
    <li className={cx('preview-row', `preview-row--${tone}`, duplicate && 'is-duplicate', className)} aria-busy={loading || undefined}>
      <div className="preview-row__line">
        <span className="preview-row__input" lang="en">
          {input}
        </span>
        <span className="preview-row__status">{status}</span>
      </div>
      {detail && <div className="preview-row__detail">{detail}</div>}
      {duplicate && <div className="preview-row__detail preview-row__duplicate">{zh.bank.preview.duplicate}</div>}
      {chips}
    </li>
  );
}
