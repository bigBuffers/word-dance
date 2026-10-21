// ExampleList — example sentences with the headword/forms highlighted (utils/highlight.ts), a 🔊 per
// sentence and the Chinese behind a translation toggle unless `zhMode === 'always'` or the session toggled translations on
// (FRONTEND §4, §5.1.2).
import { useState } from 'react';
import type { Example } from '@/api/types';
import { cx } from '@/components/ui/cx';
import { SpeakButton } from '@/components/word/SpeakButton';
import type { Accent } from '@/hooks/useSpeech';
import { zh } from '@/i18n/zh';
import { highlight } from '@/utils/highlight';
import './study.css';

export interface ExampleListProps {
  examples: readonly Example[];
  lemma: string;
  forms: readonly string[];
  zhMode: 'tap' | 'always';
  /** Session-wide translation toggle (key Z) — shows every translation. */
  zhForced?: boolean;
  accent?: Accent;
  className?: string;
}

export function HighlightedText({ text, forms, lang = 'en' }: { text: string; forms: readonly string[]; lang?: string }) {
  return (
    <span lang={lang}>
      {highlight(text, forms).map((seg, i) => (seg.hit ? <mark key={i}>{seg.text}</mark> : <span key={i}>{seg.text}</span>))}
    </span>
  );
}

export function ExampleList({ examples, lemma, forms, zhMode, zhForced = false, accent, className }: ExampleListProps) {
  const [open, setOpen] = useState<Record<number, boolean>>({});
  if (examples.length === 0) return null;
  const allForms = [lemma, ...forms];
  const showAll = zhMode === 'always' || zhForced;
  return (
    <ol className={cx('examples', className)}>
      {examples.map((ex, i) => {
        const shown = showAll || open[i] === true;
        return (
          <li key={i} className="example">
            <div className="example__row">
              <p className="example__en">
                <HighlightedText text={ex.en} forms={allForms} />
              </p>
              <SpeakButton text={ex.en} size="sm" lang={accent} className="example__speak" />
            </div>
            {shown ? (
              <p className="example__zh" lang="zh-CN">
                {ex.zh}
              </p>
            ) : (
              <button type="button" className="example__zh-toggle" aria-expanded={false} onClick={() => setOpen((o) => ({ ...o, [i]: true }))}>
                {zh.study.zh}
              </button>
            )}
          </li>
        );
      })}
    </ol>
  );
}
