// StudyCard — the front/back card of the study session (FRONTEND §4, §5.1).
// Front: headword, phonetic, 🔊, stage chips, kind badge, hint (cloze of the first example), reveal.
// Back: meaning (Claude `meaning_zh`, else the ECDICT translation), image, highlighted examples,
// collocations, mnemonic (a memory card's own hook + caveat while its picture is shown — switched on and not failed to
// load —, else the content's mnemonic: `memoryLines`), confusable chips, collapsible dictionary, SRS line and the "next-due" preview; grade bar
// unfamiliar · hard · good + mastered (primary with suggested badge when `mastery_suggested`) · skip. The grade bar
// publishes its height through `useBottomBarOffset`, so toasts stack above the buttons instead of covering them.
// `screen` items show screen card with known / unfamiliar / skip directly (reveal peeks). Content states (§5.1.5):
// queued & not deferred → skeleton + zh.study.contentPending; `content_deferred_until` set → budget-deferred copy,
// no skeleton, no generateExamples; none/failed → dictionary copy + generateExamples. Buttons disable while a grade is in flight.
import { useState, type MouseEvent, type ReactNode } from 'react';
import { Link } from 'react-router';
import type { DanceMode, Grade, ScreenVerdict, Stage, StudyItem } from '@/api/types';
import { Button } from '@/components/ui/Button';
import { cx } from '@/components/ui/cx';
import { Skeleton } from '@/components/ui/Skeleton';
import { KindBadge } from '@/components/word/KindBadge';
import { WordHeader } from '@/components/word/WordHeader';
import { useBottomBarOffset } from '@/hooks/useBottomBarOffset';
import type { Accent } from '@/hooks/useSpeech';
import { zh } from '@/i18n/zh';
import { routePaths } from '@/routes';
import { cloze, containsForm } from '@/utils/highlight';
import { formatPos } from '@/utils/pos';
import { formatMonthDay } from '@/utils/srsPreview';
import { ExampleList } from './ExampleList';
import { imageSrc, memoryLines, WordImage } from './WordImage';
import './study.css';

export interface StudyCardProps {
  item: StudyItem;
  revealed: boolean;
  onReveal: () => void;
  onGrade: (grade: Grade | ScreenVerdict) => void;
  onMaster: () => void;
  onSkip: () => void;
  zhMode: 'tap' | 'always';
  showImage: boolean;
  /** `settings.image_word`: false shows a memory card without its word layer (`WordImage`); omitted → with it, the server default. */
  imageWord?: boolean;
  /** "next-due" strings per grade (utils/srsPreview `previewAll`). */
  preview: Record<Grade, string>;
  /** hint cloze shown on the front (key H). */
  hint?: boolean;
  onHint?: () => void;
  /** Session-wide translation toggle (key Z). */
  zhForced?: boolean;
  /** A grade is in flight for this card. */
  busy?: boolean;
  /** 1-based position / total for the header counter. */
  position?: number;
  total?: number;
  /** Replay of a past batch: back face only, no grade bar, outcome chip. */
  readOnly?: boolean;
  accent?: Accent;
  /** The learner's target stages: the header shows only these chips plus the word's lowest stage (`StageChips.only`). */
  onlyStages?: readonly Stage[];
  onRequestContent?: () => void;
  requestingContent?: boolean;
  onImageRefresh?: () => void;
  onImageFlag?: () => void;
  imageRefreshing?: boolean;
  className?: string;
  /** word dance (`settings.dance_mode`): omitted or 'off' → the plain headword; otherwise the DancingWord with the word's spec (§6.5). */
  danceMode?: DanceMode;
  /** Replay counter from the page (key P), see `WordHeader.playToken`. */
  danceToken?: number;
  /** Play the dances when this card shows (the page decides): the spelling + stress dance when the front face — or a screen (recommended-word) card — mounts, the semantic dance when the back mounts at the reveal. */
  danceAutoplay?: boolean;
}

/** Label of a stored grade / verdict (`push_items.result`). */
export function resultLabel(result: string | null): string | null {
  switch (result) {
    case 'again':
      return zh.study.again;
    case 'hard':
      return zh.study.hard;
    case 'good':
      return zh.study.good;
    case 'master':
      return zh.study.master;
    case 'known':
      return zh.study.known;
    case 'unfamiliar':
      return zh.study.unfamiliar;
    case 'skip':
      return zh.study.skip;
    default:
      return null;
  }
}

export type ContentMode = 'ready' | 'pending' | 'deferred' | 'failed' | 'dictionary';

/** Which back-face variant the content fields call for (FRONTEND §5.1.5). */
export function contentMode(item: Pick<StudyItem, 'content' | 'content_state' | 'content_deferred_until'>): ContentMode {
  if (item.content_deferred_until) return 'deferred';
  if (item.content_state === 'ready' && item.content) return 'ready';
  if (item.content_state === 'queued') return 'pending';
  if (item.content_state === 'none' || item.content_state === 'failed') return 'failed';
  return 'dictionary';
}

function Key({ children }: { children: ReactNode }) {
  return (
    <kbd className="study-kbd" aria-hidden="true">
      {children}
    </kbd>
  );
}

function stop(e: MouseEvent) {
  e.stopPropagation();
}

function splitLines(text: string | null | undefined): string[] {
  return (text ?? '')
    .split(/\r?\n/)
    .map((s) => s.trim())
    .filter(Boolean);
}

export function StudyCard({
  item,
  revealed,
  onReveal,
  onGrade,
  onMaster,
  onSkip,
  zhMode,
  showImage,
  imageWord = true,
  preview,
  hint = false,
  onHint,
  zhForced = false,
  busy = false,
  position,
  total,
  readOnly = false,
  accent,
  onlyStages,
  onRequestContent,
  requestingContent = false,
  onImageRefresh,
  onImageFlag,
  imageRefreshing = false,
  className,
  danceMode = 'off',
  danceToken,
  danceAutoplay = false,
}: StudyCardProps) {
  const { word, content, mine } = item;
  // every kind of card dances (FRONTEND §5.1.1); a screen (recommended-word) card plays the spelling + stress dance only — its header never gets the
  // semantic (`semanticEnabled={false}` below), so the word's first show gives the spelling away, never the meaning
  const dance = danceMode !== 'off' ? word.dance : undefined;
  const semanticEnabled = danceMode === 'full';
  // the sticky grade / verdict bar tells the toast viewport how far it reaches up (toasts stack above the buttons)
  const barRef = useBottomBarOffset<HTMLDivElement>();
  // the picture source that could not be loaded, as `WordImage` reports it — the source and not a flag, so the failure is
  // never held against another picture (the other variant after `imageWord` changed); cleared when that source arrives after all
  const [failedSrc, setFailedSrc] = useState<string | null>(null);
  const isScreen = item.kind === 'screen';
  const forms = [word.lemma, word.display, ...word.forms];
  const firstExample = content?.examples.find((ex) => containsForm(ex.en, forms)) ?? content?.examples[0] ?? null;
  const mode = contentMode(item);
  const meaning = content?.meaning_zh?.trim() || word.translation?.trim() || word.translation_short;
  const dictLines = splitLines(word.translation);
  const suggested = mine?.srs.mastery_suggested === true;
  const counter = position !== undefined && total !== undefined ? zh.study.position(position, total) : null;
  const pos = formatPos(word.pos);
  const showBack = readOnly || revealed;
  const result = resultLabel(item.result);
  // the mnemonic section does not wait for the content: a memory card's hook comes with the picture (design D5) — and goes
  // with it: under a box left empty by a failed request (a flaky connection; the session itself keeps working offline) the
  // hook would be a line about a picture that is not there, so the content's own mnemonic shows as it does with pictures off
  const memory = memoryLines(item.image, showImage && failedSrc !== imageSrc(item.image, imageWord), mode === 'ready' ? content?.mnemonic_zh : null);

  const header = (
    <header className="study-card__top">
      <span className="study-card__counter">
        <KindBadge kind={item.kind} />
        {counter && <span className="study-card__pos">{counter}</span>}
      </span>
      {readOnly ? (
        result && <span className={cx('badge', 'study-card__result', `study-card__result--${item.result ?? 'none'}`)}>{result}</span>
      ) : (
        <Button variant="ghost" size="sm" disabled={busy} onClick={onSkip}>
          {zh.study.skip}
          <Key>S</Key>
        </Button>
      )}
    </header>
  );

  // ---- screen item (screen card): verdict buttons directly, reveal peeks ------------------------------
  if (isScreen) {
    return (
      <article className={cx('study-card', 'study-card--screen', className)} role="group" aria-label={word.display}>
        {header}
        <div className="study-card__face study-card__front">
          {/* a new word's first show: the spelling + stress dance, like a card front — no stage object, pose colour or ghosts, and 🔊 / P replay 'form' only */}
          <WordHeader word={word} size="lg" as="h2" accent={accent} onlyStages={onlyStages} className="study-card__word" dance={dance} playToken={danceToken} autoplay={danceAutoplay ? 'form' : false} semanticEnabled={false} />
          {showBack ? (
            <p className="study-card__peek" lang="zh-CN">
              {meaning}
            </p>
          ) : (
            <button type="button" className="study-card__peek-link" onClick={onReveal}>
              {zh.study.reveal}
              <Key>Space</Key>
            </button>
          )}
        </div>
        {!readOnly && (
          <div className="study-bar study-bar--screen" ref={barRef}>
            <Button variant="primary" tone="good" size="lg" disabled={busy} onClick={() => onGrade('known')}>
              {zh.study.known}
              <Key>1</Key>
            </Button>
            <Button variant="primary" tone="again" size="lg" disabled={busy} onClick={() => onGrade('unfamiliar')}>
              {zh.study.unfamiliar}
              <Key>2</Key>
            </Button>
          </div>
        )}
      </article>
    );
  }

  // ---- front -----------------------------------------------------------------------------------------
  if (!showBack) {
    const hintText = firstExample ? cloze(firstExample.en, forms) : null;
    return (
      <article className={cx('study-card', className)} role="group" aria-label={word.display}>
        {header}
        <div key="front" className="study-card__face study-card__front study-card__front--tappable" onClick={onReveal}>
          {/* semanticEnabled={false}: the front never shows the meaning — no stage object, pose colour or ghost copies before the reveal */}
          <WordHeader word={word} size="lg" as="h2" accent={accent} onlyStages={onlyStages} className="study-card__word" dance={dance} playToken={danceToken} autoplay={danceAutoplay ? 'form' : false} semanticEnabled={false} />
          {hint && hintText && (
            <p className="study-card__hint" lang="en">
              {hintText}
            </p>
          )}
          <div className="study-card__front-actions" onClick={stop}>
            {hintText && onHint && !hint && (
              <Button variant="ghost" onClick={onHint}>
                {zh.study.hint}
                <Key>H</Key>
              </Button>
            )}
            <Button variant="primary" size="lg" onClick={onReveal}>
              {zh.study.reveal}
              <Key>Space</Key>
            </Button>
          </div>
        </div>
      </article>
    );
  }

  // ---- back ------------------------------------------------------------------------------------------
  let contentBlock: ReactNode;
  switch (mode) {
    case 'ready':
      contentBlock = content && (
        <>
          {content.examples.length > 0 && (
            <section className="study-card__section" aria-label={zh.study.examples}>
              <h3 className="study-card__section-title">{zh.study.examples}</h3>
              <ExampleList examples={content.examples} lemma={word.lemma} forms={forms} zhMode={zhMode} zhForced={zhForced} accent={accent} />
            </section>
          )}
          {content.collocations.length > 0 && (
            <section className="study-card__section" aria-label={zh.study.collocations}>
              <h3 className="study-card__section-title">{zh.study.collocations}</h3>
              <ul className="chips chips--md study-card__collocations" lang="en">
                {content.collocations.map((c) => (
                  <li key={c} className="chip">
                    {c}
                  </li>
                ))}
              </ul>
            </section>
          )}
        </>
      );
      break;
    case 'pending':
      contentBlock = (
        <section className="study-card__section study-card__notice" aria-live="polite">
          <p className="study-card__notice-text">{zh.study.contentPending}</p>
          <Skeleton lines={3} />
        </section>
      );
      break;
    case 'deferred':
      contentBlock = (
        <section className="study-card__section study-card__notice study-card__notice--deferred">
          <p className="study-card__notice-text">{zh.study.contentDeferred}</p>
        </section>
      );
      break;
    case 'failed':
      contentBlock = (
        <section className="study-card__section study-card__notice">
          <p className="study-card__notice-text">{zh.study.contentFailed}</p>
          {onRequestContent && !readOnly && (
            <Button variant="secondary" size="sm" loading={requestingContent} onClick={onRequestContent}>
              {zh.word.generateExamples}
            </Button>
          )}
        </section>
      );
      break;
    default:
      contentBlock = null;
  }

  return (
    <article className={cx('study-card', 'study-card--revealed', className)} role="group" aria-label={word.display}>
      {header}
      <div key="back" className="study-card__face study-card__back">
        {/* keyed: the back face is new content, so its WordHeader mounts fresh and the semantic autoplay fires at the reveal */}
        <WordHeader
          word={word}
          size="md"
          as="h2"
          accent={accent}
          onlyStages={onlyStages}
          className="study-card__word"
          dance={dance}
          playToken={danceToken}
          autoplay={danceAutoplay && semanticEnabled ? 'semantic' : false}
          replay={semanticEnabled ? 'full' : 'form'}
          semanticEnabled={semanticEnabled}
        />
        <p className="study-card__meaning" lang="zh-CN" aria-live="polite">
          {meaning}
        </p>
        {showImage && (
          <WordImage
            image={item.image}
            showImages={showImage}
            imageWord={imageWord}
            alt={content?.image_alt_zh ?? null}
            word={word.display}
            dance={word.dance}
            danceMode={danceMode}
            onRefresh={readOnly ? undefined : onImageRefresh}
            onFlag={readOnly ? undefined : onImageFlag}
            refreshing={imageRefreshing}
            onFailed={setFailedSrc}
            onLoaded={(loadedSrc) => setFailedSrc((f) => (f === loadedSrc ? null : f))}
          />
        )}
        {contentBlock}
        {memory && (
          <section className="study-card__section" aria-label={zh.study.mnemonic}>
            <h3 className="study-card__section-title">{zh.study.mnemonic}</h3>
            <p className="study-card__mnemonic">{memory.text}</p>
            {memory.note && <p className="study-card__mnemonic-note">{memory.note}</p>}
          </section>
        )}
        {word.confusables.length > 0 && (
          <section className="study-card__section" aria-label={zh.study.confusable}>
            <h3 className="study-card__section-title">{zh.study.confusable}</h3>
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
        {(dictLines.length > 0 || word.definition) && (
          <details className="study-card__dict">
            <summary>{zh.study.dictionary}</summary>
            {pos && (
              <p className="study-card__dict-pos muted" lang="en">
                {pos}
              </p>
            )}
            {dictLines.length > 0 && (
              <ul className="study-card__dict-lines" lang="zh-CN">
                {dictLines.map((line, i) => (
                  <li key={i}>{line}</li>
                ))}
              </ul>
            )}
            {word.definition && (
              <p className="study-card__dict-def" lang="en">
                {word.definition}
              </p>
            )}
          </details>
        )}
        {mine && (
          <p className="study-card__srs muted">
            {mine.srs.repetitions > 0 ? zh.study.srsLine(mine.srs.repetitions, mine.srs.interval_days) : zh.study.srsNew}
            {mine.times_added > 1 && <span className="study-card__chip-inline"> · {zh.study.addedTimes(mine.times_added)}</span>}
            {mine.mastered_at && <span className="study-card__chip-inline"> · {zh.study.lastMastered(formatMonthDay(mine.mastered_at))}</span>}
          </p>
        )}
        {!readOnly && (
          <p className="study-card__preview muted">
            {zh.study.nextLabel}：{zh.study.hard} → {preview.hard} · {zh.study.good} → {preview.good}
          </p>
        )}
      </div>
      {!readOnly && (
        <div className="study-bar" ref={barRef}>
          <div className="study-bar__grades">
            <Button variant="primary" tone="again" size="lg" disabled={busy} onClick={() => onGrade('again')} aria-describedby={undefined}>
              <span className="study-bar__label">
                {zh.study.again}
                <Key>1</Key>
              </span>
              <span className="study-bar__due">{preview.again}</span>
            </Button>
            <Button variant="primary" tone="hard" size="lg" disabled={busy} onClick={() => onGrade('hard')}>
              <span className="study-bar__label">
                {zh.study.hard}
                <Key>2</Key>
              </span>
              <span className="study-bar__due">{preview.hard}</span>
            </Button>
            <Button variant="primary" tone="good" size="lg" disabled={busy} onClick={() => onGrade('good')}>
              <span className="study-bar__label">
                {zh.study.good}
                <Key>3</Key>
              </span>
              <span className="study-bar__due">{preview.good}</span>
            </Button>
          </div>
          <div className="study-bar__secondary">
            <Button variant={suggested ? 'primary' : 'secondary'} disabled={busy} onClick={onMaster} className={cx(suggested && 'study-bar__master--suggested')}>
              {zh.study.master}
              {suggested && <span className="badge study-bar__suggested">{zh.study.suggested}</span>}
              <Key>4</Key>
            </Button>
            <Button variant="ghost" disabled={busy} onClick={onSkip}>
              {zh.study.skip}
              <Key>S</Key>
            </Button>
          </div>
        </div>
      )}
    </article>
  );
}
