// KindBadge — push-item kind label (zh.study.kind.*: review / new / screen / extra; FRONTEND §5.1).
import type { ItemKind } from '@/api/types';
import { cx } from '@/components/ui/cx';
import { zh } from '@/i18n/zh';
import './word.css';

export interface KindBadgeProps {
  kind: ItemKind;
  className?: string;
}

export function KindBadge({ kind, className }: KindBadgeProps) {
  return <span className={cx('badge', `badge--${kind}`, className)}>{zh.study.kind[kind]}</span>;
}
