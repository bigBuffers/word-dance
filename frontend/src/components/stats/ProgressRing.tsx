// ProgressRing — SVG ring `done/total`, animated once on mount (FRONTEND §4). `prefers-reduced-motion`
// disables the transition through the global rule in styles/global.css.
import { useEffect, useState } from 'react';
import { cx } from '@/components/ui/cx';
import './stats.css';

export interface ProgressRingProps {
  done: number;
  total: number;
  /** Diameter in px (default 112). */
  size?: number;
  /** Stroke width in px (default 10). */
  stroke?: number;
  /** Show the `done/total` figure inside the ring (default true). */
  showLabel?: boolean;
  /** Secondary caption under the figure. */
  caption?: string;
  className?: string;
}

export function ringFraction(done: number, total: number): number {
  if (!Number.isFinite(done) || !Number.isFinite(total) || total <= 0) return 0;
  return Math.min(1, Math.max(0, done / total));
}

export function ProgressRing({ done, total, size = 112, stroke = 10, showLabel = true, caption, className }: ProgressRingProps) {
  const [mounted, setMounted] = useState(false);
  useEffect(() => {
    const frame = requestAnimationFrame(() => setMounted(true));
    return () => cancelAnimationFrame(frame);
  }, []);

  const radius = (size - stroke) / 2;
  const circumference = 2 * Math.PI * radius;
  const fraction = mounted ? ringFraction(done, total) : 0;
  const complete = total > 0 && done >= total;
  const label = `${Math.max(0, done)}/${Math.max(0, total)}`;

  return (
    <div className={cx('ring', complete && 'ring--complete', className)} style={{ width: size, height: size }} role="img" aria-label={label}>
      <svg className="ring__svg" viewBox={`0 0 ${size} ${size}`} width={size} height={size} aria-hidden="true" focusable="false">
        <circle className="ring__track" cx={size / 2} cy={size / 2} r={radius} strokeWidth={stroke} />
        <circle
          className="ring__value"
          cx={size / 2}
          cy={size / 2}
          r={radius}
          strokeWidth={stroke}
          strokeDasharray={circumference}
          strokeDashoffset={circumference * (1 - fraction)}
          transform={`rotate(-90 ${size / 2} ${size / 2})`}
        />
      </svg>
      {showLabel && (
        <div className="ring__label">
          <span className="ring__figure">{label}</span>
          {caption && <span className="ring__caption">{caption}</span>}
        </div>
      )}
    </div>
  );
}
