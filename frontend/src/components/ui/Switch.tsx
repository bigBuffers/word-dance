// Switch — accessible toggle (`role="switch"`), optionally with a label/description row.
import { useId, type ReactNode } from 'react';
import { cx } from './cx';
import './ui.css';

export interface SwitchProps {
  checked: boolean;
  onChange: (checked: boolean) => void;
  label?: ReactNode;
  description?: ReactNode;
  disabled?: boolean;
  /** Accessible name when no visible `label` is given. */
  'aria-label'?: string;
  className?: string;
  id?: string;
}

export function Switch({ checked, onChange, label, description, disabled = false, 'aria-label': ariaLabel, className, id }: SwitchProps) {
  const autoId = useId();
  const controlId = id ?? autoId;
  const labelId = `${controlId}-label`;
  const descId = `${controlId}-desc`;
  const hasLabel = label !== undefined && label !== null;
  const hasDesc = description !== undefined && description !== null;

  const control = (
    <button
      type="button"
      role="switch"
      id={controlId}
      className="switch__control"
      aria-checked={checked}
      aria-label={hasLabel ? undefined : ariaLabel}
      aria-labelledby={hasLabel ? labelId : undefined}
      aria-describedby={hasDesc ? descId : undefined}
      disabled={disabled}
      onClick={() => onChange(!checked)}
    >
      <span className="switch__thumb" aria-hidden="true" />
    </button>
  );

  if (!hasLabel) return <span className={cx('switch', disabled && 'switch--disabled', className)}>{control}</span>;

  return (
    <label className={cx('switch', disabled && 'switch--disabled', className)} htmlFor={controlId}>
      <span className="switch__text">
        <span id={labelId}>{label}</span>
        {hasDesc && (
          <span id={descId} className="switch__desc">
            {description}
          </span>
        )}
      </span>
      {control}
    </label>
  );
}
