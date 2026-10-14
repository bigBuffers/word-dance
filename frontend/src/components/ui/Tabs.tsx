// Tabs — WAI-ARIA tablist with roving tabindex; horizontally scrollable on phones.
import { useId, useRef, type KeyboardEvent, type ReactNode } from 'react';
import { cx } from './cx';
import './ui.css';

export interface TabItem<K extends string = string> {
  key: K;
  label: ReactNode;
  /** Count badge; 0 / null / '' hide it. */
  badge?: number | string | null;
  disabled?: boolean;
}

export interface TabsProps<K extends string> {
  items: readonly TabItem<K>[];
  value: K;
  onChange: (key: K) => void;
  'aria-label'?: string;
  /** Tabs share the full width equally (good for 2–5 short labels). */
  fill?: boolean;
  className?: string;
}

export function Tabs<K extends string>({ items, value, onChange, 'aria-label': ariaLabel, fill = false, className }: TabsProps<K>) {
  const prefix = useId();
  const listRef = useRef<HTMLDivElement>(null);

  const focusTab = (index: number) => {
    const buttons = listRef.current?.querySelectorAll<HTMLButtonElement>('[role="tab"]');
    const target = buttons?.[index];
    if (!target) return;
    target.focus();
    if (typeof target.scrollIntoView === 'function') target.scrollIntoView({ block: 'nearest', inline: 'nearest' });
  };

  const onKeyDown = (e: KeyboardEvent<HTMLDivElement>) => {
    const enabled = items.map((item, index) => ({ item, index })).filter(({ item }) => !item.disabled);
    if (enabled.length === 0) return;
    const current = enabled.findIndex(({ item }) => item.key === value);
    let next: { item: TabItem<K>; index: number } | undefined;
    switch (e.key) {
      case 'ArrowRight':
      case 'ArrowDown':
        next = enabled[(current + 1) % enabled.length];
        break;
      case 'ArrowLeft':
      case 'ArrowUp':
        next = enabled[(current - 1 + enabled.length) % enabled.length];
        break;
      case 'Home':
        next = enabled[0];
        break;
      case 'End':
        next = enabled[enabled.length - 1];
        break;
      default:
        return;
    }
    if (!next) return;
    e.preventDefault();
    onChange(next.item.key);
    focusTab(next.index);
  };

  return (
    <div ref={listRef} className={cx('tabs', fill && 'tabs--fill', className)} role="tablist" aria-label={ariaLabel} onKeyDown={onKeyDown}>
      {items.map((item) => {
        const selected = item.key === value;
        const showBadge = item.badge !== undefined && item.badge !== null && item.badge !== 0 && item.badge !== '';
        return (
          <button
            key={item.key}
            type="button"
            role="tab"
            id={`${prefix}-${item.key}`}
            className="tab"
            aria-selected={selected}
            tabIndex={selected ? 0 : -1}
            disabled={item.disabled}
            onClick={() => onChange(item.key)}
          >
            {item.label}
            {showBadge && <span className="tab__badge">{item.badge}</span>}
          </button>
        );
      })}
    </div>
  );
}
