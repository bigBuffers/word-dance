// Segmented — compact single-choice control (radiogroup), e.g. current stage, example-translation mode, accent.
import { useRef, type KeyboardEvent, type ReactNode } from 'react';
import { cx } from './cx';
import './ui.css';

export interface SegmentedOption<V extends string> {
  value: V;
  label: ReactNode;
  disabled?: boolean;
}

export interface SegmentedProps<V extends string> {
  options: readonly SegmentedOption<V>[];
  value: V;
  onChange: (value: V) => void;
  'aria-label'?: string;
  'aria-labelledby'?: string;
  size?: 'sm' | 'md';
  /** Stretch to the container width. */
  block?: boolean;
  className?: string;
}

export function Segmented<V extends string>({
  options,
  value,
  onChange,
  'aria-label': ariaLabel,
  'aria-labelledby': ariaLabelledBy,
  size = 'md',
  block = false,
  className,
}: SegmentedProps<V>) {
  const groupRef = useRef<HTMLDivElement>(null);

  const onKeyDown = (e: KeyboardEvent<HTMLDivElement>) => {
    const enabled = options.map((option, index) => ({ option, index })).filter(({ option }) => !option.disabled);
    if (enabled.length === 0) return;
    const current = enabled.findIndex(({ option }) => option.value === value);
    let next: { option: SegmentedOption<V>; index: number } | undefined;
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
    onChange(next.option.value);
    groupRef.current?.querySelectorAll<HTMLButtonElement>('[role="radio"]')[next.index]?.focus();
  };

  return (
    <div
      ref={groupRef}
      className={cx('segmented', size === 'sm' && 'segmented--sm', block && 'segmented--block', className)}
      role="radiogroup"
      aria-label={ariaLabel}
      aria-labelledby={ariaLabelledBy}
      onKeyDown={onKeyDown}
    >
      {options.map((option) => {
        const checked = option.value === value;
        return (
          <button
            key={option.value}
            type="button"
            role="radio"
            className="segmented__opt"
            aria-checked={checked}
            tabIndex={checked ? 0 : -1}
            disabled={option.disabled}
            onClick={() => onChange(option.value)}
          >
            {option.label}
          </button>
        );
      })}
    </div>
  );
}
