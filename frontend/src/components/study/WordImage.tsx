// WordImage — the 16:10 picture box of a card / detail page (FRONTEND §4): lazy <img>, skeleton while
// loading, attribution caption (photo: zh.word.imageSource · title · creator · license ↗; card: zh.word.generatedCard;
// claude_svg: zh.word.aiImage) and the refresh-image / flag-image actions when handlers are given.
import { useEffect, useState } from 'react';
import type { ImageMeta } from '@/api/types';
import { Button } from '@/components/ui/Button';
import { cx } from '@/components/ui/cx';
import { Skeleton } from '@/components/ui/Skeleton';
import { zh } from '@/i18n/zh';
import './study.css';

export interface WordImageProps {
  image: ImageMeta;
  /** The user's show_images setting; false renders nothing. */
  showImages: boolean;
  /** Alt text (content.image_alt_zh, else the image's alt_zh, else the word). */
  alt?: string | null;
  onRefresh?: () => void;
  onFlag?: () => void;
  /** refresh-image in flight. */
  refreshing?: boolean;
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

export function WordImage({ image, showImages, alt, onRefresh, onFlag, refreshing = false, className }: WordImageProps) {
  const [loaded, setLoaded] = useState(false);
  const [failed, setFailed] = useState(false);
  useEffect(() => {
    setLoaded(false);
    setFailed(false);
  }, [image.url]);

  if (!showImages) return null;
  const caption = imageCaption(image);
  const landing = image.kind === 'photo' ? image.attribution?.landing_url : null;
  const altText = alt?.trim() || image.alt_zh || '';

  return (
    <figure className={cx('word-image', className)}>
      <div className={cx('word-image__box', image.kind !== 'photo' && 'word-image__box--flat')}>
        {!loaded && !failed && <Skeleton className="word-image__skeleton" />}
        {!failed && (
          <img
            key={image.url}
            className={cx('word-image__img', loaded && 'is-loaded')}
            src={image.url}
            alt={altText}
            loading="lazy"
            decoding="async"
            width={image.width ?? undefined}
            height={image.height ?? undefined}
            onLoad={() => setLoaded(true)}
            onError={() => setFailed(true)}
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
        {(onRefresh || onFlag) && (
          <span className="word-image__actions">
            {onRefresh && (
              <Button variant="ghost" size="sm" loading={refreshing} onClick={onRefresh}>
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
