import type { ButtonHTMLAttributes, ReactNode, Ref } from 'react';
import { cx } from './cx';
import './ui.css';

export type ButtonVariant = 'primary' | 'secondary' | 'ghost' | 'danger';
/** Colour family; the default follows the brand, grade tones pair with their labels (FRONTEND §6.3). */
export type ButtonTone = 'brand' | 'again' | 'hard' | 'good' | 'screen';
export type ButtonSize = 'sm' | 'md' | 'lg';

export interface ButtonProps extends ButtonHTMLAttributes<HTMLButtonElement> {
  variant?: ButtonVariant;
  tone?: ButtonTone;
  size?: ButtonSize;
  /** Full-width. */
  block?: boolean;
  /** Shows a spinner, sets `aria-busy` and disables the button. */
  loading?: boolean;
  /** Square 44 px button holding only an icon — pass `aria-label`. */
  iconOnly?: boolean;
  /** Decorative leading icon. */
  icon?: ReactNode;
  ref?: Ref<HTMLButtonElement>;
}

export function Button({
  variant = 'secondary',
  tone = 'brand',
  size = 'md',
  block = false,
  loading = false,
  iconOnly = false,
  icon,
  className,
  children,
  disabled,
  type = 'button',
  ...rest
}: ButtonProps) {
  return (
    <button
      type={type}
      className={cx(
        'btn',
        `btn--${variant}`,
        `btn--${size}`,
        tone !== 'brand' && `btn--tone-${tone}`,
        block && 'btn--block',
        iconOnly && 'btn--icon',
        loading && 'is-loading',
        className,
      )}
      disabled={disabled || loading}
      aria-busy={loading || undefined}
      {...rest}
    >
      {loading && <span className="btn__spinner" aria-hidden="true" />}
      {icon !== undefined && !loading && (
        <span className="btn__icon" aria-hidden="true">
          {icon}
        </span>
      )}
      {children !== undefined && children !== null && (iconOnly ? children : <span className="btn__label">{children}</span>)}
    </button>
  );
}
