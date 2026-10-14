// Field — label + control + hint/error wiring (ids, aria-describedby, aria-invalid).
// Pass the control as a render function to receive the generated ids, or a plain node with your own `id`.
import { useId, type ReactNode } from 'react';
import { cx } from './cx';
import './ui.css';

export interface FieldControlProps {
  id: string;
  'aria-describedby'?: string;
  'aria-invalid'?: true;
  'aria-required'?: true;
}

export interface FieldProps {
  label: ReactNode;
  hint?: ReactNode;
  error?: ReactNode;
  required?: boolean;
  /** Control node, or a function receiving the ids to spread on the control. */
  children: ReactNode | ((control: FieldControlProps) => ReactNode);
  /** Use when `children` is a plain node that already carries this id. */
  htmlFor?: string;
  /** Label and control on one row (switches, short inputs). */
  inline?: boolean;
  className?: string;
}

export function Field({ label, hint, error, required = false, children, htmlFor, inline = false, className }: FieldProps) {
  const autoId = useId();
  const id = htmlFor ?? autoId;
  const hintId = `${id}-hint`;
  const errorId = `${id}-error`;
  const hasHint = hint !== undefined && hint !== null && hint !== '';
  const hasError = error !== undefined && error !== null && error !== '';
  const describedBy = [hasError && errorId, hasHint && hintId].filter(Boolean).join(' ') || undefined;

  const control: FieldControlProps = { id };
  if (describedBy) control['aria-describedby'] = describedBy;
  if (hasError) control['aria-invalid'] = true;
  if (required) control['aria-required'] = true;

  return (
    <div className={cx('field', inline && 'field--inline', hasError && 'field--invalid', className)}>
      <label className="field__label" htmlFor={id}>
        {label}
        {required && (
          <span className="field__req" aria-hidden="true">
            *
          </span>
        )}
      </label>
      {typeof children === 'function' ? children(control) : children}
      {hasHint && (
        <p id={hintId} className="field__hint">
          {hint}
        </p>
      )}
      {hasError && (
        <p id={errorId} className="field__error" role="alert">
          {error}
        </p>
      )}
    </div>
  );
}
