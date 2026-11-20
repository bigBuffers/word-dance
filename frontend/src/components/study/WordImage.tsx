// WordImage — the 16:10 picture box of a card / detail page (FRONTEND §4): lazy <img>, skeleton while
// loading, attribution caption (photo: zh.word.imageSource · title · creator · license ↗; card: zh.word.generatedCard;
// claude_svg: zh.word.aiImage) and the refresh-image / flag-image actions when handlers are given.
// Memory cards (docs/MEMORY_CARDS_DESIGN.md §3.6–3.7; `image.word_layer`): the word is drawn into the picture as its last
// layer, and an <img> cannot reach into its SVG — so hiding the word means asking the server for the other variant: with the
// learner's `image_word` off the source is `url + '?plain=1'` (endpoint 52, the same file without that layer). Such a card
// never offers refresh-image (the fetch chain would trade the drawing for a stock picture); flag-image stays. The texts that
// come with it (`hook_zh` / `note_zh`) feed the mnemonic section of the card and the detail page through `memoryLines` — while
// the picture is on screen, which is why the component tells its parent when a source could not be loaded (`onFailed`).
// Dancing cards (API.md §9.1 `image.dancing`): the drawing is put into the page by `DancingPicture`, which prints `word` on it and
// plays its motion; when that file cannot be read inline the same source is shown through the plain <img> below, still.
import { useEffect, useState } from 'react';
import type { DanceMode, DanceSpec, ImageMeta } from '@/api/types';
import { Button } from '@/components/ui/Button';
import { cx } from '@/components/ui/cx';
import { Skeleton } from '@/components/ui/Skeleton';
import { zh } from '@/i18n/zh';
import { DancingPicture } from './DancingPicture';
import './study.css';

export interface WordImageProps {
  image: ImageMeta;
  /** The user's show_images setting; false renders nothing. */
  showImages: boolean;
  /** The user's image_word setting; false asks for a memory card without its word layer (every other image is unaffected). */
  imageWord: boolean;
  /** Alt text (content.image_alt_zh, else the image's alt_zh, else the word); a memory card's own alt_zh comes before it. */
  alt?: string | null;
  /** The headword a dancing card prints on its ground (with `imageWord` on); without it such a card is shown as a plain picture. */
  word?: string;
  /** The word's dance spec: its doubled letters jump together on a dancing card. */
  dance?: DanceSpec | null;
  /** The learner's dance setting for a dancing card; omitted → 'off' (the picture and its word stay still). */
  danceMode?: DanceMode;
  onRefresh?: () => void;
  onFlag?: () => void;
  /** refresh-image in flight. */
  refreshing?: boolean;
  /**
   * The picture could not be loaded (the box stays empty). Called with the source that failed, so that a parent keys what it
   * remembers by source: a plain flag would outlive its picture — the other variant, the next image, the next word on a page
   * that does not remount — and take the hook of one that did load (`memoryLines`).
   */
  onFailed?: (src: string) => void;
  /** The picture has arrived: a source that failed before and is requested again (the component mounted anew) is on screen after all. */
  onLoaded?: (src: string) => void;
  className?: string;
}

/** Caption text for an image (FRONTEND §4): kind-specific labels or the attribution line. */
export function imageCaption(image: ImageMeta): string {
  if (image.kind === 'card') return zh.word.generatedCard;
  if (image.kind === 'svg' || image.provider === 'claude_svg') return zh.word.aiImage;
  const a = image.attribution;
  if (!a) return zh.word.imageSource;
  const line = a.text?.trim() || [a.title, a.creator, a.license].filter((s): s is string => Boolean(s && s.trim())).join(' · ');
  return line ? `${zh.word.imageSource} · ${line}` : zh.word.imageSource;
}

/** The <img> source: a memory card whose learner switched `image_word` off is fetched without its word layer (endpoint 52). */
export function imageSrc(image: ImageMeta, imageWord: boolean): string {
  return image.word_layer && !imageWord ? `${image.url}?plain=1` : image.url;
}

export interface MemoryLines {
  text: string;
  /** The memory card's sound / meaning caveat, shown as a quieter second line; null for a content mnemonic. */
  note: string | null;
}

/**
 * What the mnemonic section shows (design D5): while the picture is on screen and it brings a hook — the thing a memory card
 * acts out — that hook with the card's optional caveat; otherwise the content's own mnemonic as before (it predates the
 * picture and often disagrees with it, so the two are never shown together). `null` → no section.
 * `shown` is the caller's word for "on screen": pictures switched on (`show_images`) and this source not failed to load
 * (`onFailed`) — a hook under an empty box would be a line about a picture that is not there.
 */
export function memoryLines(image: ImageMeta, shown: boolean, mnemonic: string | null | undefined): MemoryLines | null {
  const hook = shown ? image.hook_zh?.trim() : '';
  if (hook) return { text: hook, note: image.note_zh?.trim() || null };
  return mnemonic ? { text: mnemonic, note: null } : null;
}

export function WordImage({ image, showImages, imageWord, alt, word, dance, danceMode = 'off', onRefresh, onFlag, refreshing = false, onFailed, onLoaded, className }: WordImageProps) {
  const src = imageSrc(image, imageWord);
  const [loaded, setLoaded] = useState(false);
  const [failed, setFailed] = useState(false);
  const [inlineFailed, setInlineFailed] = useState(false);
  useEffect(() => {
    setLoaded(false);
    setFailed(false);
    setInlineFailed(false);
  }, [src]);

  if (!showImages) return null;
  const caption = imageCaption(image);
  const landing = image.kind === 'photo' ? image.attribution?.landing_url : null;
  // a memory card's alt_zh is the scene of this very picture, written with it (and true of both variants); the content's
  // image_alt_zh was written before the card existed and describes a picture nobody drew, so here the card's own text wins
  const altText = (image.word_layer && image.alt_zh?.trim()) || alt?.trim() || image.alt_zh || '';
  // a memory card is not offered for replacement (design D6): the provider chain would put a stock picture in its place
  const refresh = image.word_layer ? undefined : onRefresh;
  // inline: a dancing card always (its word is printed by the page); a memory card while its word layer is shown and the word has a dance
  const inline = word !== undefined && !inlineFailed && (image.dancing || (image.word_layer && imageWord && !!dance));

  return (
    <figure className={cx('word-image', className)}>
      <div className={cx('word-image__box', image.kind !== 'photo' && 'word-image__box--flat')}>
        {!loaded && !failed && <Skeleton className="word-image__skeleton" />}
        {inline && (
          <DancingPicture
            key={src}
            className={cx('word-image__img', loaded && 'is-loaded')}
            src={src}
            word={image.dancing && imageWord && word !== undefined ? word : null}
            twins={dance?.marks.double}
            spec={dance}
            mode={danceMode}
            alt={altText}
            onLoaded={() => {
              setLoaded(true);
              onLoaded?.(src);
            }}
            onFailed={() => setInlineFailed(true)}
          />
        )}
        {!inline && !failed && (
          <img
            key={src}
            className={cx('word-image__img', loaded && 'is-loaded')}
            src={src}
            alt={altText}
            loading="lazy"
            decoding="async"
            width={image.width ?? undefined}
            height={image.height ?? undefined}
            onLoad={() => {
              setLoaded(true);
              onLoaded?.(src);
            }}
            onError={() => {
              setFailed(true);
              onFailed?.(src);
            }}
          />
        )}
      </div>
      <figcaption className="word-image__caption">
        <span className="word-image__source">
          {landing ? (
            <a href={landing} target="_blank" rel="noopener noreferrer">
              {caption} ↗
            </a>
          ) : (
            caption
          )}
        </span>
        {(refresh || onFlag) && (
          <span className="word-image__actions">
            {refresh && (
              <Button variant="ghost" size="sm" loading={refreshing} onClick={refresh}>
                {zh.word.changeImage}
              </Button>
            )}
            {onFlag && (
              <Button variant="ghost" size="sm" disabled={refreshing} onClick={onFlag}>
                {zh.word.flagImage}
              </Button>
            )}
          </span>
        )}
      </figcaption>
    </figure>
  );
}
