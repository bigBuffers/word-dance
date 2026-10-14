// Skeleton — shimmer placeholder (decorative; the shimmer stops under prefers-reduced-motion).
import type { CSSProperties } from 'react';
import { cx } from './cx';
import './ui.css';

export interface SkeletonProps {
  /** Renders this many text lines (the last one shorter) instead of a single block. */
  lines?: number;
  width?: number | string;
  height?: number | string;
  variant?: 'text' | 'block' | 'circle';
  className?: string;
}

export function Skeleton({ lines, width, height, variant = 'block', className }: SkeletonProps) {
  if (lines && lines > 0) {
    return (
      <div className={cx('skeleton__lines', className)} aria-hidden="true">
        {Array.from({ length: lines }, (_, i) => (
          <span key={i} className="skeleton" style={{ width: i === lines - 1 && lines > 1 ? '60%' : '100%' }} />
        ))}
      </div>
    );
  }
  const style: CSSProperties = {};
  if (width !== undefined) style.width = width;
  if (height !== undefined) style.height = height;
  if (variant === 'circle' && height === undefined && width !== undefined) style.height = width;
  return <span className={cx('skeleton', variant === 'circle' && 'skeleton--circle', className)} style={style} aria-hidden="true" />;
}
